"""
Testa a lógica de classificação de risco do audit_partition_filter_rollout.sql
com um fixture pequeno e controlado (não depende dos dados sintéticos gerados
aleatoriamente), para garantir que os limiares de negócio (5% de queries sem
filtro = seguro) continuam corretos após qualquer alteração no SQL.
"""

from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def con():
    connection = duckdb.connect(database=":memory:")

    connection.execute("""
        create table table_catalog (
            project_id varchar, dataset_id varchar, table_id varchar,
            is_partitioned boolean, partition_column varchar,
            size_gb double, row_count bigint, require_partition_filter boolean,
            created_date varchar, last_modified_date varchar
        )
    """)
    connection.execute("""
        create table query_history (
            query_id varchar, project_id varchar, dataset_id varchar, table_id varchar,
            run_date varchar, bytes_processed bigint, used_partition_filter boolean,
            user_email varchar
        )
    """)

    # tabela A: particionada, não governada, grande, 0% queries sem filtro -> segura
    connection.execute("""
        insert into table_catalog values
        ('p','ds','table_a', true, 'dt', 100.0, 1000, false, '2026-01-01', '2026-06-01'),
        ('p','ds','table_b', true, 'dt', 100.0, 1000, false, '2026-01-01', '2026-06-01'),
        ('p','ds','table_c', true, 'dt', 1.0,   1000, false, '2026-01-01', '2026-06-01'),
        ('p','ds','table_d', true, 'dt', 100.0, 1000, true,  '2026-01-01', '2026-06-01'),
        ('p','ds','table_e', false, '', 100.0, 1000, false, '2026-01-01', '2026-06-01')
    """)

    # table_a: 10 queries, todas com filtro -> 0% sem filtro -> seguro
    for i in range(10):
        connection.execute(
            "insert into query_history values (?,?,?,?,?,?,?,?)",
            [f"q_a_{i}", "p", "ds", "table_a", "2026-06-01", 1_000_000, True, "u@x.com"]
        )

    # table_b: 10 queries, 3 sem filtro (30%) -> requer_coordenacao
    for i in range(10):
        used_filter = i >= 3
        connection.execute(
            "insert into query_history values (?,?,?,?,?,?,?,?)",
            [f"q_b_{i}", "p", "ds", "table_b", "2026-06-01", 5_000_000_000, used_filter, "u@x.com"]
        )

    return connection


def run_audit(connection, size_threshold_gb=10, price_per_tb=6.25):
    sql_path = ROOT / "scripts" / "audit_partition_filter_rollout.sql"
    sql = sql_path.read_text(encoding="utf-8")
    sql = sql.replace("{{ size_threshold_gb }}", str(size_threshold_gb))
    sql = sql.replace("{{ price_per_tb }}", str(price_per_tb))
    return connection.execute(sql).df()


def test_table_below_size_threshold_is_excluded(con):
    df = run_audit(con, size_threshold_gb=10)
    assert "table_c" not in df["table_id"].values  # 1GB < limiar de 10GB


def test_non_partitioned_table_is_excluded(con):
    df = run_audit(con, size_threshold_gb=10)
    assert "table_e" not in df["table_id"].values  # não particionada


def test_already_governed_table_is_excluded(con):
    df = run_audit(con, size_threshold_gb=10)
    assert "table_d" not in df["table_id"].values  # require_partition_filter já ativo


def test_zero_pct_sem_filtro_is_classified_as_safe(con):
    df = run_audit(con, size_threshold_gb=10)
    row = df[df["table_id"] == "table_a"].iloc[0]
    assert row["classificacao_risco"] == "seguro_para_rollout"


def test_thirty_pct_sem_filtro_requires_coordination(con):
    df = run_audit(con, size_threshold_gb=10)
    row = df[df["table_id"] == "table_b"].iloc[0]
    assert row["classificacao_risco"] == "requer_coordenacao"


def test_savings_estimate_is_non_negative(con):
    df = run_audit(con, size_threshold_gb=10)
    assert (df["economia_mensal_estimada_usd"] >= 0).all()
