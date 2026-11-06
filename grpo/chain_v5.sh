#!/usr/bin/env bash
# v5 (v5_protocol.md): v4 + overlong filtering, no image credit, KL 0.01, length stop rule. Rounds 0-29.
# Round 0 = v4's base rollouts (prepared by hand). Diagnostics after rounds 9/19/29; a 216 diagnostic more
# than 2 SE below v1 (< 31.7 %) at r009/r019 stops the run. Re-running resumes after the last trained round.
set -euo pipefail
cd "$(dirname "$0")/.."
V=v5; MEM=${MEM:-0.68}
ENV=/home/leesg17/miniconda3/etc/profile.d/conda.sh
diag() {  # $1 = checkpoint round tag, $2 = group name (216 / 166)
  local m=grpo/runs/$V/merged_$1
  [ -f "$m/config.json" ] || (source $ENV && conda activate vllm-train && python grpo/grpo.py merge --adapter grpo/runs/$V/ckpt/$1 --out "$m")
  for s in 5 6; do
    [ -f "runs/grpo_${V}_$1_$2/seed$s/scores.json" ] || (source $ENV && conda activate vllm &&
      python run_eval.py --model "$m" --gpu-mem-util "$MEM" --seed $s --ids-file grpo/data/ids_$2.txt --out "runs/grpo_${V}_$1_$2/seed$s")
  done
}
floor() {  # stop rule: mean 216 accuracy over seeds 5,6 below 31.7 % (v1 37.5 % minus 2 SE)
  python3 -c "import json,sys; a=[json.load(open(f'runs/grpo_${V}_$1_216/seed{s}/scores.json'))['overall_micro'] for s in (5,6)]; print('diag', '$1', a); sys.exit(1 if sum(a)/2 < 0.317 else 0)"
}
for seg in "10 r009" "20 r019" "30 r029"; do
  set -- $seg
  next=$(grep -c '"phase": "train"' grpo/runs/$V/log.jsonl 2>/dev/null || true)
  RUN=runs/$V START=${next:-0} END=$1 JUDGE_MODEL=cli bash grpo/loop.sh \
    --pool data/pool_v4.jsonl --questions 16 --pool-offset 16 --samples 8 --no-topup --hints --reward v5 \
    --drop-truncated --length-guard --groups-per-step 4 --lr 1e-4 --beta 0.01 --gpu-mem "$MEM"
  diag $2 216
  [ "$2" = r029 ] || floor $2
done
diag r029 166
