#!/usr/bin/env bash
# One ablation condition end to end: data -> decontamination -> (self-CoT) -> LoRA SFT -> merge -> MMMU eval -> compare.
#
#   bash data_ablation/run_condition.sh cosyn      # runs/<RUN_NAME>/...   (RUN_NAME defaults to abl_<condition>)
#   bash data_ablation/run_condition.sh vwi
#   bash data_ablation/run_condition.sh pmcvqa
#
# On RunPod (cloud/runpod.sh takes care of env, results branch, push, pod shutdown):
#   TRAIN=1 RUN_NAME=abl_cosyn SEEDS="0 1" AUTO_TERMINATE=0 \
#     RUN_CMD='bash data_ablation/run_condition.sh cosyn' bash cloud/runpod.sh
#   # screening says "worth it"? same pod, same RUN_NAME, more seeds: training/merge are skipped, finished seeds too
#   SEEDS="0 1 2 3 4" bash data_ablation/run_condition.sh cosyn
#
# Every stage is skipped when its output already exists, so a crashed run resumes with the same command.
# Knobs (env): N_RECORDS=12000  STEPS=1500  BS=8  ACCUM=1  SEEDS="0 1"  COT_SOURCE=dataset|self  PROTECT_PRO=0|1
#              MIN_RECORDS=1000  SMOKE=0|1 (1 = 30-question eval only, for a first end-to-end check)
#              EXTRA_PREP="..." (passed to prepare_data.py)  EXTRA_TRAIN="..." (passed to train_sft.py)
set -euo pipefail
COND="${1:?usage: run_condition.sh <cosyn|vwi|pmcvqa>}"
cd "$(dirname "$0")/.."
RUN_NAME="${RUN_NAME:-abl_$COND}"
RUN="runs/$RUN_NAME"
DATA="$RUN/data"
SEEDS="${SEEDS:-0 1}"
N_RECORDS="${N_RECORDS:-12000}"
STEPS="${STEPS:-1500}"; BS="${BS:-8}"; ACCUM="${ACCUM:-1}"
PROTECT_PRO="${PROTECT_PRO:-0}"
# cosyn / vwi ship explanations -> "dataset"; pmcvqa has answers only -> the model writes its own solutions ("self")
case "$COND" in
  pmcvqa) COT_SOURCE="${COT_SOURCE:-self}" ;;
  *)      COT_SOURCE="${COT_SOURCE:-dataset}" ;;
esac
# CoSyn images are rendered from code -> cannot be MMMU images; text check only.
NOIMG=""; [[ "$COND" == cosyn ]] && NOIMG="--no-images"
PRO=""; [[ "$PROTECT_PRO" == 1 ]] && PRO="--pro"
mkdir -p "$RUN"
echo "== condition=$COND run=$RUN seeds=[$SEEDS] cot=$COT_SOURCE budget=${STEPS}x${BS}x${ACCUM} =="

# 1. data
if [[ ! -f "$DATA/raw.jsonl" ]]; then
  python data_ablation/prepare_data.py --dataset "$COND" --n "$N_RECORDS" --out "$DATA" ${EXTRA_PREP:-}
fi
# 2. decontamination (MMMU dev/val/test [+ MMMU-Pro])
if [[ ! -f "$DATA/clean.jsonl" ]]; then
  python data_ablation/decontaminate.py --data "$DATA" $NOIMG $PRO
fi
# 3. responses
if [[ ! -f "$DATA/sft.jsonl" ]]; then
  if [[ "$COT_SOURCE" == self ]]; then
    python data_ablation/self_cot.py --data "$DATA" --overwrite
  else
    python data_ablation/self_cot.py --data "$DATA"      # only fills records that have no response (no-op for cosyn/vwi)
  fi
fi
python - "$DATA/sft.jsonl" "${MIN_RECORDS:-1000}" <<'PY'
import sys
n = sum(1 for l in open(sys.argv[1]) if l.strip())
print(f"[data] {n} SFT records")
assert n >= int(sys.argv[2]), f"fewer than {sys.argv[2]} training records: check decontam_report.json / self_cot_report.json"
PY
# 4. train (fixed budget) + merge
if [[ ! -d "$RUN/train/step$STEPS" ]]; then
  python data_ablation/train_sft.py --data "$DATA/sft.jsonl" --out "$RUN/train" \
      --steps "$STEPS" --bs "$BS" --accum "$ACCUM" ${EXTRA_TRAIN:-}
fi
if [[ ! -f "$RUN/train/step${STEPS}_merged/config.json" ]]; then
  python data_ablation/train_sft.py --merge "$RUN/train/step$STEPS"
fi
# 5. MMMU eval with the frozen pipeline (eval.sh skips finished seeds; AFTER_SEED pushes each seed on RunPod)
if [[ "${SMOKE:-0}" == 1 ]]; then   # whole path in ~30 min: SMOKE=1 N_RECORDS=200 MIN_RECORDS=50 STEPS=20 bash ... cosyn
  python run_eval.py --model "$PWD/$RUN/train/step${STEPS}_merged" --seed 0 --limit 1 --out "$RUN/eval_smoke/seed0"
  echo "== smoke OK: $RUN/eval_smoke/seed0 (not comparable to the baseline; delete the run dir before the real run) =="
  exit 0
fi
SEEDS="$SEEDS" bash eval.sh "$PWD/$RUN/train/step${STEPS}_merged" "$RUN/eval"
# 6. paired comparison against the official main baseline (results/seed0..4)
python analyze.py compare results/seed0 results/seed1 results/seed2 results/seed3 results/seed4 \
    vs $(for s in $SEEDS; do echo "$RUN/eval/seed$s"; done) | tee "$RUN/compare.txt"
python data_ablation/summarize.py --runs "$RUN" | tee "$RUN/summary.md"
echo "== $COND done =="
