#!/usr/bin/env bash
#
# audit_partition_filter_rollout.sh
#
# Wrapper de execução da auditoria de rollout de require_partition_filter.
# Permite rodar via CI/cron com parâmetros configuráveis, sem precisar
# lembrar da sintaxe do script Python por trás.
#
# Uso:
#   ./scripts/audit_partition_filter_rollout.sh [size_threshold_gb] [price_per_tb]
#
# Exemplo:
#   ./scripts/audit_partition_filter_rollout.sh 10 6.25

set -euo pipefail

SIZE_THRESHOLD_GB="${1:-10}"
PRICE_PER_TB="${2:-6.25}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Gerando metadados sintéticos (caso ainda não existam)..."
if [[ ! -f "$ROOT_DIR/seeds/table_catalog.csv" ]]; then
    python3 "$SCRIPT_DIR/generate_synthetic_metadata.py"
fi

echo "Rodando auditoria (limiar=${SIZE_THRESHOLD_GB}GB, preço/TB=\$${PRICE_PER_TB})..."
python3 "$SCRIPT_DIR/run_audit.py" \
    --size-threshold-gb "$SIZE_THRESHOLD_GB" \
    --price-per-tb "$PRICE_PER_TB" \
    --output "output/rollout_priorizado.csv"

echo "Concluído."
