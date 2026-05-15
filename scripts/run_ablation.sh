#!/usr/bin/env bash
# Stream C:批次跑完 16 個 ablation config
set -euo pipefail

cd "$(dirname "$0")/.."

CONFIGS=(configs/experiments/ablation/*.yaml)
echo "將跑 ${#CONFIGS[@]} 個 ablation experiment..."

for cfg in "${CONFIGS[@]}"; do
  echo
  echo "===== $(basename "$cfg") ====="
  uv run python scripts/run_experiment.py --config "$cfg"
done

echo
echo "全部完成。聚合資料夾在 results/runs/agg_abl_*"
