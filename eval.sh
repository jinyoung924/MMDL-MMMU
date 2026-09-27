#!/usr/bin/env bash
# The whole baseline in one command: 5 seeds x 900 questions, then mean ± sd (reports/mmmu_baseline.md §0).
#   bash eval.sh                                   # Qwen/Qwen3-VL-4B-Instruct -> results/
#   bash eval.sh /abs/path/to/finetuned_ckpt results_ft
#   SEEDS="0" bash eval.sh                         # single-seed smoke run
# Seeds that already finished are skipped, so a crash costs one seed, not all five.
# AFTER_SEED (optional): a command run with the finished seed dir as its argument. Unset locally (no-op);
#   cloud/runpod.sh sets it to cloud/push_results.sh so every finished seed is pushed before the next starts.
set -euo pipefail
MODEL=${1:-Qwen/Qwen3-VL-4B-Instruct}
OUT=${2:-results}
SEEDS=${SEEDS:-"0 1 2 3 4"}
for s in $SEEDS; do
  if [ ! -f "$OUT/seed$s/scores.json" ]; then
    python run_eval.py --model "$MODEL" --seed "$s" --out "$OUT/seed$s"
    if [ -n "${AFTER_SEED:-}" ]; then "$AFTER_SEED" "$OUT/seed$s"; fi
  fi
done
python analyze.py aggregate $(for s in $SEEDS; do echo "$OUT/seed$s"; done)
