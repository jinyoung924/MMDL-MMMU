#!/usr/bin/env bash
# Run the whole screening queue unattended: base (this GPU's paired baseline) then each condition in turn.
#
#   bash data_ablation/run_all.sh                       # base cosyn vwi pmcvqa
#   bash data_ablation/run_all.sh cosyn pmcvqa          # a subset / different order
#
# Idempotent: a finished item is skipped (base: every seed's scores.json exists; condition: summary.md exists) and
# an unfinished one resumes inside run_condition.sh / eval.sh. When a Colab session dies, re-run the same command.
# Smoke settings that may linger in the environment (SMOKE, N_RECORDS, STEPS, RUN_NAME from the notebook's
# config cell) are overridden here so the real runs always use the real budget.
set -euo pipefail
cd "$(dirname "$0")/.."
ORDER=("$@"); [[ ${#ORDER[@]} -eq 0 ]] && ORDER=(base cosyn vwi pmcvqa)
export SEEDS="${SEEDS:-0 1}"
export SMOKE=0 N_RECORDS="${N_RECORDS_ALL:-12000}" MIN_RECORDS=1000 STEPS="${STEPS_ALL:-1500}"
unset RUN_NAME
BASE_RUN="${BASE_RUN:-base_l4}"
T0=$(date +%s)
log() { echo "[run_all $(date +%H:%M) +$(( ($(date +%s) - T0) / 60 ))min] $*"; }

base_done() { for s in $SEEDS; do [[ -f "runs/$BASE_RUN/eval/seed$s/scores.json" ]] || return 1; done; }

for item in "${ORDER[@]}"; do
  if [[ "$item" == base ]]; then
    if base_done; then log "base: runs/$BASE_RUN already has seeds [$SEEDS] -> skip"; continue; fi
    log "base: evaluating the untouched model on this GPU, seeds [$SEEDS]"
    RUN_NAME="$BASE_RUN" bash data_ablation/run_base.sh
    continue
  fi
  if [[ -f "runs/abl_$item/summary.md" ]]; then log "$item: runs/abl_$item/summary.md exists -> skip"; continue; fi
  if base_done; then
    export BASE_DIRS="$(for s in $SEEDS; do echo -n "runs/$BASE_RUN/eval/seed$s "; done)"
  else
    export BASE_DIRS="results/seed0 results/seed1 results/seed2 results/seed3 results/seed4"
    log "WARNING: no $BASE_RUN on this GPU -> comparing against main's RTX 4090 baseline"
  fi
  log "$item: start (baseline = $BASE_DIRS)"
  RUN_NAME="abl_$item" bash data_ablation/run_condition.sh "$item"
  log "$item: done"
done

if ls -d runs/abl_* >/dev/null 2>&1; then
  python data_ablation/summarize.py --runs $(ls -d runs/abl_*) --base ${BASE_DIRS:-results/seed0 results/seed1 results/seed2 results/seed3 results/seed4} \
      --out runs/results_all.md >/dev/null && cat runs/results_all.md
fi
log "queue finished: ${ORDER[*]}"
