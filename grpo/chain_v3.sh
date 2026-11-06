#!/usr/bin/env bash
# v3 (v3_protocol.md): VWI pool, optional judge reward (JUDGE_MODEL), rounds 0-29.
# After rounds 9/19/29: LoRA merged into the weights, 216-group diagnostic (seeds 5, 6) with frozen run_eval.py.
# The §5.5 full evaluation is run by hand after the r029 decision. Re-running resumes after the last trained round.
set -euo pipefail
cd "$(dirname "$0")/.."
V=v3; MEM=${MEM:-0.75}  # other jobs share the GPU; MEM only sizes the KV cache (batch-invariant eval is unaffected)
ENV=/home/leesg17/miniconda3/etc/profile.d/conda.sh
diag() {  # $1 = checkpoint round tag
  local m=grpo/runs/$V/merged_$1
  [ -f "$m/config.json" ] || (source $ENV && conda activate vllm-train && python grpo/grpo.py merge --adapter grpo/runs/$V/ckpt/$1 --out "$m")
  for s in 5 6; do
    [ -f "runs/grpo_${V}_$1_216/seed$s/scores.json" ] || (source $ENV && conda activate vllm &&
      python run_eval.py --model "$m" --gpu-mem-util "$MEM" --seed $s --ids-file grpo/data/ids_216.txt --out "runs/grpo_${V}_$1_216/seed$s")
  done
}
for seg in "10 r009" "20 r019" "30 r029"; do
  set -- $seg
  next=$(grep -c '"phase": "train"' grpo/runs/$V/log.jsonl 2>/dev/null || true)
  RUN=runs/$V START=${next:-0} END=$1 JUDGE_MODEL=${JUDGE_MODEL:-} bash grpo/loop.sh \
    --pool data/pool_v3.jsonl --groups-per-step 4 --lr 1e-4 --gpu-mem "$MEM"
  diag $2
done
