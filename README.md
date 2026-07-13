# Pipeline Governance & Cost Audit Tool

Ferramenta de auditoria que analisa metadados de um data warehouse BigQuery e
prioriza o rollout de `require_partition_filter` — a flag que obriga toda
query a filtrar por coluna de partição, evitando full table scans acidentais
e caros.

> Reproduz o *framework de decisão* de um rollout de governança real que
> conduzi em produção (dezenas de tabelas, auditoria via `INFORMATION_SCHEMA`).
> Os dados aqui são sintéticos; a lógica de elegibilidade e classificação de
> risco é a mesma.

## O problema

Ativar `require_partition_filter` numa tabela sem cuidado **quebra em
produção** qualquer query que hoje não filtra por partição. Ativar tabela
nenhuma **deixa dinheiro na mesa** — full scans em tabelas de centenas de GB
custam caro e acontecem silenciosamente. O trabalho de governança não é
"ativar em tudo", é decidir **em que ordem** e **com que nível de risco**
ativar cada tabela.

## Critérios de elegibilidade

Uma tabela entra na análise se, e somente se:

1. **É particionada** — pré-requisito técnico do próprio recurso.
2. **Ainda não está governada** (`require_partition_filter = false`).
3. **Tamanho acima de um limiar configurável** (padrão: 10 GB) — tabelas
   pequenas não justificam o esforço de coordenação com o time dono.

## Classificação de risco

Para cada tabela elegível, olho o histórico de queries dos últimos 30 dias:

| Classificação | Critério | Ação |
|---|---|---|
| `seguro_para_rollout` | ≤ 5% das queries não usam filtro | Ativar direto |
| `requer_coordenacao` | > 5% das queries não usam filtro | Falar com o time dono antes |
| `sem_historico_recente` | 0 queries em 30 dias | Investigar se a tabela ainda é usada |

O limiar de 5% não é arbitrário — é o ponto onde o risco de quebrar uma
query legítima começa a pesar mais que o ganho de ativar imediatamente.
Abaixo disso, o volume de exceção é pequeno o suficiente pra tratar
reativamente (avisar o usuário depois que a query falhar) sem gerar
incidente.

## Priorização

Entre as tabelas `seguro_para_rollout`, ordeno por **economia mensal
estimada** (descendente) — maximiza o impacto de custo primeiro, minimizando
risco. Tabelas `requer_coordenacao` ficam separadas — o objetivo delas não é
"quando ativar" e sim "com quem falar antes".

### Metodologia de estimativa de economia (e suas limitações)

```
economia_mensal_usd ≈ (bytes escaneados sem filtro nos últimos 30d / 1e12)
                        × 0.90 × preço_por_TB
```

O fator `0.90` assume que o partition pruning reduz ~90% dos bytes escaneados
— uma estimativa conservadora, não uma medição exata (o ganho real depende
de quantas partições cada query cobre). Isso é intencional: **é melhor
subestimar economia do que criar expectativa que a governança não entrega.**
Documentar essa suposição explicitamente é parte do critério de qualidade
do relatório — qualquer número sem a suposição por trás é inútil pra quem
vai decidir orçamento.

## Como rodar

```bash
pip install duckdb faker pandas pytest

./scripts/audit_partition_filter_rollout.sh 10 6.25
# argumentos: [limiar_tamanho_gb] [preco_por_tb_usd]
```

Isso gera dados sintéticos (se ainda não existirem) e roda a auditoria,
imprimindo um resumo no terminal e salvando o relatório completo em
`output/rollout_priorizado.csv`.

Rodar os testes da lógica de classificação:

```bash
python3 -m pytest tests/ -v
```

## Resultado (dados sintéticos deste repo, limiar = 10GB)

- **39 tabelas elegíveis** analisadas
- **24 seguras** para rollout imediato
- **15 exigem coordenação** com o time dono antes de ativar
- Economia mensal estimada (só tabelas seguras): calculada dinamicamente a
  cada execução — os dados sintéticos são gerados com seed fixo, então o
  número é reproduzível, mas depende do `--price-per-tb` usado

## Estrutura

```
scripts/
  generate_synthetic_metadata.py     -- gera table_catalog.csv e query_history.csv
  audit_partition_filter_rollout.sql -- o motor: critérios + classificação + priorização
  run_audit.py                       -- executa o SQL com parâmetros configuráveis
  audit_partition_filter_rollout.sh  -- wrapper para rodar via CI/cron
tests/
  test_audit_logic.py                -- valida a lógica de classificação com fixture controlado
seeds/                                -- metadados sintéticos gerados
output/                               -- relatório final (gerado, não versionado)
```

## Por que isso é diferente de "mais um pipeline ETL"
A maior parte de portfólio de engenharia de dados mostra pipelines de
ingestão/transformação. Esse projeto mostra outro tipo de trabalho sênior:
**decidir onde aplicar uma mudança de governança que tem custo real de errar
em ambas as direções** (não ativar = desperdício; ativar sem critério =
incidente). O SQL é simples de propósito — o valor está nos critérios de
decisão documentados, não na complexidade técnica.

## Stack

`DuckDB` · `Python` (`duckdb`, `pandas`, `faker`) · SQL · `pytest` · Bash
