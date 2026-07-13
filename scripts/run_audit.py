"""
Executa audit_partition_filter_rollout.sql contra os CSVs de metadados
sintéticos (table_catalog, query_history) e gera o relatório priorizado.

Os limiares (size_threshold_gb, price_per_tb) são parametrizáveis via CLI,
para que o time possa reavaliar o rollout conforme o orçamento/apetite de
risco mudar, sem editar o SQL.

Uso:
    python scripts/run_audit.py --size-threshold-gb 10 --price-per-tb 6.25
"""

import argparse
from pathlib import Path

import duckdb


def load_sql(path: Path, size_threshold_gb: float, price_per_tb: float) -> str:
    sql = path.read_text(encoding="utf-8")
    sql = sql.replace("{{ size_threshold_gb }}", str(size_threshold_gb))
    sql = sql.replace("{{ price_per_tb }}", str(price_per_tb))
    return sql


def main():
    parser = argparse.ArgumentParser(description="Auditoria de rollout de require_partition_filter")
    parser.add_argument("--size-threshold-gb", type=float, default=10.0,
                         help="Tamanho mínimo (GB) para uma tabela entrar na análise")
    parser.add_argument("--price-per-tb", type=float, default=6.25,
                         help="Preço on-demand por TB escaneado (USD), para estimativa de economia")
    parser.add_argument("--output", type=str, default="output/rollout_priorizado.csv",
                         help="Caminho do CSV de saída")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    seeds_dir = root / "seeds"
    sql_path = root / "scripts" / "audit_partition_filter_rollout.sql"
    output_path = root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(database=":memory:")
    con.execute(f"create table table_catalog as select * from read_csv_auto('{seeds_dir / 'table_catalog.csv'}')")
    con.execute(f"create table query_history as select * from read_csv_auto('{seeds_dir / 'query_history.csv'}')")

    sql = load_sql(sql_path, args.size_threshold_gb, args.price_per_tb)
    result_df = con.execute(sql).df()

    result_df.to_csv(output_path, index=False)

    n_total = len(result_df)
    n_seguro = (result_df["classificacao_risco"] == "seguro_para_rollout").sum()
    n_coordenacao = (result_df["classificacao_risco"] == "requer_coordenacao").sum()
    n_sem_historico = (result_df["classificacao_risco"] == "sem_historico_recente").sum()
    economia_total_seguro = result_df.loc[
        result_df["classificacao_risco"] == "seguro_para_rollout", "economia_mensal_estimada_usd"
    ].sum()

    print(f"\n=== Auditoria de rollout de require_partition_filter ===")
    print(f"Limiar de tamanho: >= {args.size_threshold_gb} GB | Preço/TB: US$ {args.price_per_tb}\n")
    print(f"Tabelas elegíveis analisadas: {n_total}")
    print(f"  - seguro_para_rollout:     {n_seguro}")
    print(f"  - requer_coordenacao:      {n_coordenacao}")
    print(f"  - sem_historico_recente:   {n_sem_historico}")
    print(f"\nEconomia mensal estimada (somente tabelas seguras): US$ {economia_total_seguro:,.2f}")
    print(f"\nTop 10 por economia mensal estimada:")
    print(result_df.head(10).to_string(index=False))
    print(f"\nRelatório completo salvo em: {output_path}")


if __name__ == "__main__":
    main()
