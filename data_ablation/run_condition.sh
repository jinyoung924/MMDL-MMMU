#!/usr/bin/env bash
# One ablation condition end to end: data -> decontamination -> (self-CoT) -> LoRA SFT -> merge -> MMMU eval -> compare.
#
#   bash data_ablation/run_condition.sh cosyn      # runs/<RUN_NAME>/...   (RUN_NAME defaults to abl_<condition>)
#   bash data_ablation/run_condition.sh vwi
#   bash data_ablation/run_condition.sh pmcvqa
#
# RunPod (cloud/runpod.sh takes care of env, results branch, push, pod shutdown):
#   TRAIN=1 RUN_NAME=abl_cosyn SEEDS="0 1" AUTO_TERMINATE=0 \
#     RUN_CMD='bash data_ablation/run_condition.sh cosyn' bash cloud/runpod.sh
# Colab (data_ablation/colab_ablation.ipynb sets these): runs/ on Drive, images + merged weights on local disk:
#   FAST_DIR=/content/fast MERGED_ROOT=/content/merged BS=2 ACCUM=4 BASE_DIRS="runs/base_l4/eval" \
#     bash data_ablation/run_condition.sh cosyn
#
# Every stage is skipped when its output already exists and the long stages (self-CoT, training) resume from
# their own checkpoints, so a dead session is re-run with the same command and continues.
# Knobs (env): N_RECORDS=12000  STEPS=1500  BS=8  ACCUM=1  SEEDS="0 1"  COT_SOURCE=dataset|self  PROTECT_PRO=0|1
#              MIN_RECORDS=1000  SMOKE=0|1 (1 = 30-question eval only, for a first end-to-end check)
#              BASE_DIRS="results/seed0 ... results/seed4" (paired baseline; on other hardware use a re-measured one)
#              PROTECT_CACHE=runs/protected_index.json (MMMU protected-set index; under runs/ so Colab keeps it on Drive)
#              FAST_DIR=<local dir>  (copy of data/ for image reads; outputs still go to runs/<RUN_NAME>/data)
#              MERGED_ROOT=<local dir> (merged 9 GB model goes to $MERGED_ROOT/<RUN_NAME> instead of runs/)
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
BASE_DIRS="${BASE_DIRS:-results/seed0 results/seed1 results/seed2 results/seed3 results/seed4}"
MERGED="${MERGED_ROOT:+$MERGED_ROOT/$RUN_NAME}"; MERGED="${MERGED:-$RUN/train/step${STEPS}_merged}"
# cosyn / vwi ship explanations -> "dataset"; pmcvqa has answers only -> the model writes its own solutions ("self")
case "$COND" in
  pmcvqa) COT_SOURCE="${COT_SOURCE:-self}" ;;
  *)      COT_SOURCE="${COT_SOURCE:-dataset}" ;;
esac
# CoSyn images are rendered from code -> cannot be MMMU images; text check only.
NOIMG=""; [[ "$COND" == cosyn ]] && NOIMG="--no-images"
PRO=""; [[ "$PROTECT_PRO" == 1 ]] && PRO="--pro"
mkdir -p "$RUN"
echo "== condition=$COND run=$RUN seeds=[$SEEDS] cot=$COT_SOURCE budget=${STEPS}x${BS}x${ACCUM} merged=$MERGED =="

# 1. data
if [[ ! -f "$DATA/raw.jsonl" ]]; then
  python data_ablation/prepare_data.py --dataset "$COND" --n "$N_RECORDS" --out "$DATA" ${EXTRA_PREP:-}
fi
# 2. decontamination (MMMU dev/val/test [+ MMMU-Pro])
if [[ ! -f "$DATA/clean.jsonl" ]]; then
  python data_ablation/decontaminate.py --data "$DATA" $NOIMG $PRO --cache "${PROTECT_CACHE:-runs/protected_index.json}"
fi
# images on a fast local disk (Google Drive is slow for 12k random reads); jsonl/report files stay in $DATA
IMG_DIR="$DATA"
if [[ -n "${FAST_DIR:-}" ]]; then
  IMG_DIR="$FAST_DIR/$RUN_NAME/data"
  mkdir -p "$IMG_DIR"
  echo "[sync] $DATA -> $IMG_DIR"
  rsync -a --ignore-existing "$DATA/" "$IMG_DIR/"
fi
# 3. responses (self_cot resumes from $DATA/self_cot_partial.jsonl)
if [[ ! -f "$DATA/sft.jsonl" ]]; then
  OVR=""; [[ "$COT_SOURCE" == self ]] && OVR="--overwrite"
  python data_ablation/self_cot.py --data "$IMG_DIR" --out-dir "$DATA" $OVR   # no-op when every record has a response
fi
if [[ "$IMG_DIR" != "$DATA" ]]; then cp -f "$DATA/sft.jsonl" "$IMG_DIR/sft.jsonl"; fi
python - "$DATA/sft.jsonl" "${MIN_RECORDS:-1000}" <<'PY'
import sys
n = sum(1 for l in open(sys.argv[1]) if l.strip())
print(f"[data] {n} SFT records")
assert n >= int(sys.argv[2]), f"fewer than {sys.argv[2]} training records: check decontam_report.json / self_cot_report.json"
PY
# 4. train (fixed budget; resumes from $RUN/train/latest) + merge
if [[ ! -d "$RUN/train/step$STEPS" ]]; then
  python data_ablation/train_sft.py --data "$IMG_DIR/sft.jsonl" --out "$RUN/train" \
      --steps "$STEPS" --bs "$BS" --accum "$ACCUM" ${EXTRA_TRAIN:-}
fi
if [[ ! -f "$MERGED/config.json" ]]; then
  python data_ablation/train_sft.py --merge "$RUN/train/step$STEPS" --merged-dir "$MERGED"
fi
# 5. MMMU eval with the frozen pipeline (eval.sh skips finished seeds; AFTER_SEED pushes each seed on RunPod)
if [[ "${SMOKE:-0}" == 1 ]]; then   # whole path in ~30 min: SMOKE=1 N_RECORDS=200 MIN_RECORDS=50 STEPS=20 bash ... cosyn
  python run_eval.py --model "$(realpath "$MERGED")" --seed 0 --limit 1 --out "$RUN/eval_smoke/seed0"
  echo "== smoke OK: $RUN/eval_smoke/seed0 (not comparable to the baseline; delete the run dir before the real run) =="
  exit 0
fi
SEEDS="$SEEDS" bash eval.sh "$(realpath "$MERGED")" "$RUN/eval"
# 6. paired comparison against the baseline (default: official main baseline results/seed0..4)
python analyze.py compare $BASE_DIRS vs $(for s in $SEEDS; do echo "$RUN/eval/seed$s"; done) | tee "$RUN/compare.txt"
python data_ablation/summarize.py --runs "$RUN" --base $BASE_DIRS | tee "$RUN/summary.md"
echo "== $COND done =="
