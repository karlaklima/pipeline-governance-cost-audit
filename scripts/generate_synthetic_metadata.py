"""
Gera metadados sintéticos no formato de duas fontes reais do BigQuery:
  - INFORMATION_SCHEMA.TABLES / TABLE_STORAGE  -> seeds/table_catalog.csv
  - INFORMATION_SCHEMA.JOBS_BY_PROJECT         -> seeds/query_history.csv

Reproduz o cenário de negócio de um rollout real de `require_partition_filter`
em ~150 tabelas de um data warehouse, sem usar nenhum dado ou nome de tabela real.

Uso:
    python scripts/generate_synthetic_metadata.py
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

fake = Faker()
random.seed(7)
Faker.seed(7)

DATASETS = ["marketing_analytics", "finance_reporting", "clinical_ops", "logistics", "growth"]
N_TABLES = 150
DAYS_OF_QUERY_HISTORY = 30
TODAY = datetime(2026, 7, 1)

PRICE_PER_TB_USD = 6.25  # preço on-demand BigQuery (aprox., us-central1) — só para estimativa


def make_table(table_idx: int) -> dict:
    dataset = random.choice(DATASETS)
    table_id = f"{fake.word()}_{fake.word()}_{table_idx:03d}"

    # distribuição de tamanho bem assimétrica (a maioria pequena, poucas gigantes) -
    # imita o padrão real de um DW: poucas tabelas concentram a maior parte do custo
    size_gb = round(random.lognormvariate(mu=2.0, sigma=2.3), 2)
    size_gb = min(size_gb, 8000)

    is_partitioned = random.random() < 0.65
    partition_column = random.choice(["data_ingestao", "created_date", "dt_particao"]) if is_partitioned else None

    # tabelas já governadas (require_partition_filter já ativo) - simula rollout parcial já em andamento
    already_enforced = is_partitioned and random.random() < 0.20

    created_date = TODAY - timedelta(days=random.randint(60, 900))
    last_modified = TODAY - timedelta(days=random.randint(0, 30))

    return {
        "project_id": "empresa-dw-prod",
        "dataset_id": dataset,
        "table_id": table_id,
        "is_partitioned": is_partitioned,
        "partition_column": partition_column or "",
        "size_gb": size_gb,
        "row_count": int(size_gb * random.uniform(2_000_000, 6_000_000)),
        "require_partition_filter": already_enforced,
        "created_date": created_date.date().isoformat(),
        "last_modified_date": last_modified.date().isoformat(),
    }


def make_queries_for_table(table: dict, query_id_start: int) -> list[dict]:
    """Gera o histórico de queries dos últimos 30 dias que referenciam essa tabela."""
    if not table["is_partitioned"] or table["require_partition_filter"]:
        # tabelas não particionadas ou já governadas não entram na análise de risco
        n_queries = random.randint(0, 5)
    else:
        # tabelas maiores tendem a ser mais consultadas
        n_queries = int(min(300, max(1, table["size_gb"] * random.uniform(0.05, 0.4))))

    # "perfil de risco" da tabela: a maioria das tabelas já é consultada com boas práticas,
    # uma minoria tem muitas queries sem filtro de partição (candidatas a precisar de
    # coordenação com o time dono antes do rollout)
    if random.random() < 0.75:
        pct_sem_filtro = random.uniform(0.0, 0.05)   # tabela "segura" para rollout
    else:
        pct_sem_filtro = random.uniform(0.15, 0.60)  # tabela de risco, precisa de coordenação

    rows = []
    for i in range(n_queries):
        run_date = TODAY - timedelta(days=random.randint(0, DAYS_OF_QUERY_HISTORY))
        used_filter = random.random() > pct_sem_filtro

        if used_filter:
            # com partition pruning, escaneia só uma fração da tabela
            bytes_processed = int(table["size_gb"] * 1e9 * random.uniform(0.005, 0.08))
        else:
            # sem filtro, full scan (ou perto disso)
            bytes_processed = int(table["size_gb"] * 1e9 * random.uniform(0.7, 1.0))

        rows.append({
            "query_id": f"job_{query_id_start + i:06d}",
            "project_id": table["project_id"],
            "dataset_id": table["dataset_id"],
            "table_id": table["table_id"],
            "run_date": run_date.date().isoformat(),
            "bytes_processed": bytes_processed,
            "used_partition_filter": used_filter,
            "user_email": fake.user_name() + "@empresa.com",
        })

    return rows


def main():
    base = Path(__file__).resolve().parents[1] / "seeds"
    base.mkdir(exist_ok=True)

    tables = [make_table(i) for i in range(1, N_TABLES + 1)]

    with (base / "table_catalog.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=tables[0].keys())
        writer.writeheader()
        writer.writerows(tables)
    print(f"Gerado {len(tables)} tabelas em seeds/table_catalog.csv")

    all_queries = []
    qid = 1
    for t in tables:
        qs = make_queries_for_table(t, qid)
        all_queries.extend(qs)
        qid += len(qs) + 1

    with (base / "query_history.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_queries[0].keys())
        writer.writeheader()
        writer.writerows(all_queries)
    print(f"Gerado {len(all_queries)} registros de query em seeds/query_history.csv")


if __name__ == "__main__":
    main()
