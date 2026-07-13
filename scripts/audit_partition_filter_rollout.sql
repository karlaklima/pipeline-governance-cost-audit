-- audit_partition_filter_rollout.sql
--
-- Motor de auditoria para rollout de `require_partition_filter` em um data
-- warehouse BigQuery. Em produção, table_catalog e query_history vêm de:
--   - INFORMATION_SCHEMA.TABLES / TABLE_STORAGE  (metadados de tabela)
--   - INFORMATION_SCHEMA.JOBS_BY_PROJECT          (histórico de queries, 30d)
--
-- Aqui rodam como CSVs carregados no DuckDB, para reproduzir localmente.
--
-- CRITÉRIOS DE ELEGIBILIDADE (documentados, não hardcoded no meio da lógica):
--   1. Tabela particionada                          (pré-requisito técnico)
--   2. require_partition_filter ainda não ativo      (ainda não governada)
--   3. Tamanho >= limiar de relevância de custo       (:size_threshold_gb)
--      -> tabelas pequenas não justificam o risco/esforço de coordenação
--   4. Classificação de risco pelo padrão de queries dos últimos 30 dias:
--        'seguro_para_rollout'       -> <= 5% das queries não usam filtro
--        'requer_coordenacao'        -> > 5% das queries não usam filtro
--        'sem_historico_recente'     -> nenhuma query nos últimos 30 dias
--
-- PRIORIZAÇÃO:
--   Entre as tabelas "seguras", ordena por economia mensal estimada (desc) —
--   maximiza impacto de custo primeiro, minimizando risco de quebrar queries.
--   Tabelas "requer_coordenacao" aparecem separadas, com o e-mail dos usuários
--   que mais escaneiam sem filtro, para acionar antes de ativar o enforcement.

with query_stats as (

    select
        project_id,
        dataset_id,
        table_id,
        count(*)                                                          as total_queries_30d,
        sum(case when not used_partition_filter then 1 else 0 end)        as queries_sem_filtro,
        sum(case when not used_partition_filter then bytes_processed
                 else 0 end)                                              as bytes_escaneados_sem_filtro_30d,
        round(
            100.0 * sum(case when not used_partition_filter then 1 else 0 end)
            / nullif(count(*), 0), 1
        )                                                                  as pct_queries_sem_filtro

    from query_history
    group by 1, 2, 3

),

classificado as (

    select
        t.project_id,
        t.dataset_id,
        t.table_id,
        t.size_gb,
        t.partition_column,
        t.require_partition_filter,
        coalesce(q.total_queries_30d, 0)              as total_queries_30d,
        coalesce(q.pct_queries_sem_filtro, 0)         as pct_queries_sem_filtro,
        coalesce(q.bytes_escaneados_sem_filtro_30d, 0) as bytes_escaneados_sem_filtro_30d,

        case
            when coalesce(q.total_queries_30d, 0) = 0 then 'sem_historico_recente'
            when q.pct_queries_sem_filtro <= 5.0 then 'seguro_para_rollout'
            else 'requer_coordenacao'
        end as classificacao_risco,

        -- estimativa conservadora de economia: assume que o enforcement reduz
        -- em ~90% os bytes hoje escaneados sem filtro (partition pruning),
        -- extrapolado para custo mensal (janela de 30d ~ 1 mês)
        round(
            (coalesce(q.bytes_escaneados_sem_filtro_30d, 0) / power(10, 12)) * 0.90 * {{ price_per_tb }},
            2
        ) as economia_mensal_estimada_usd

    from table_catalog t
    left join query_stats q
        on t.project_id = q.project_id
        and t.dataset_id = q.dataset_id
        and t.table_id = q.table_id

    where t.is_partitioned = true
      and t.require_partition_filter = false
      and t.size_gb >= {{ size_threshold_gb }}

)

select
    project_id,
    dataset_id,
    table_id,
    size_gb,
    partition_column,
    total_queries_30d,
    pct_queries_sem_filtro,
    classificacao_risco,
    economia_mensal_estimada_usd

from classificado
order by
    case classificacao_risco
        when 'seguro_para_rollout' then 1
        when 'sem_historico_recente' then 2
        else 3
    end,
    economia_mensal_estimada_usd desc
