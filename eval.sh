#!/usr/bin/env bash
# The whole baseline in one command: 5 seeds x 900 questions, then mean ± sd (reports/mmmu_baseline.md §0).
#   bash eval.sh                                   # Qwen/Qwen3-VL-4B-Instruct -> results/
#   bash eval.sh /abs/path/to/finetuned_ckpt results_ft
#   SEEDS="0" bash eval.sh                         # single-seed smoke run
# Seeds that already finished are skipped, so a crash costs one seed, not all five.
set -euo pipefail
MODEL=${1:-Qwen/Qwen3-VL-4B-Instruct}
OUT=${2:-results}
SEEDS=${SEEDS:-"0 1 2 3 4"}
for s in $SEEDS; do
  [ -f "$OUT/seed$s/scores.json" ] || python run_eval.py --model "$MODEL" --seed "$s" --out "$OUT/seed$s"
done
python analyze.py aggregate $(for s in $SEEDS; do echo "$OUT/seed$s"; done)
