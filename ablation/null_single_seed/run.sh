#!/usr/bin/env bash
# Null test for single-seed dev runs (reports/improvement_strategy.md §5.5): treat base seed j (1..4) as if it were
# a "tuned" seed-0 run. The model is unchanged, so every Δ printed here is pure noise -> how big a dev-run Δ must be.
#   bash ablation/null_single_seed/run.sh > ablation/null_single_seed/result.txt
set -euo pipefail
cd "$(dirname "$0")/../.."
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for j in 1 2 3 4; do
  d=$tmp/seed$j; mkdir -p "$d"; ln -s "$PWD/results/seed$j/predictions.jsonl" "$d/"
  python -c "import json,sys; s=json.load(open(sys.argv[1])); s['config']['seed']=0; json.dump(s,open(sys.argv[2],'w'))" \
    "results/seed$j/scores.json" "$d/scores.json"
  base=results/seed0; for k in 1 2 3 4; do [ $k = $j ] || base="$base results/seed$k"; done
  for mode in 0 1; do
    echo "### tuned = base seed$j relabeled as seed 0, --base-mean $mode"
    python analyze.py compare $base vs "$d" --base-mean $mode | grep -E 'Δacc (all|non-target, base)|stable-correct \('
  done
done
