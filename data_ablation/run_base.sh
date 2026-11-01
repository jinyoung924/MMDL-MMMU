#!/usr/bin/env bash
# Re-measure the untouched base model on THIS hardware (paired baseline for conditions run on a different GPU
# than main's RTX 4090 results/seed*), then show how far it sits from main's numbers.
#   SEEDS="0 1" RUN_NAME=base_l4 bash data_ablation/run_base.sh
set -euo pipefail
cd "$(dirname "$0")/.."
RUN_NAME="${RUN_NAME:-base_$(hostname)}"
SEEDS="${SEEDS:-0 1}"
SEEDS="$SEEDS" bash eval.sh Qwen/Qwen3-VL-4B-Instruct "runs/$RUN_NAME/eval"
python analyze.py compare results/seed0 results/seed1 results/seed2 results/seed3 results/seed4 \
    vs $(for s in $SEEDS; do echo "runs/$RUN_NAME/eval/seed$s"; done) | tee "runs/$RUN_NAME/compare_vs_main.txt"
echo "== base on this GPU: runs/$RUN_NAME/eval (Δ vs main above should sit inside the noise band, |Δ| < ~1.5) =="
