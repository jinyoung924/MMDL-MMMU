#!/usr/bin/env bash
# v4 (v4_protocol.md): hard pool, 8 samples, Sonnet hints for 0/8 questions, v4 reward, KL 0.001, rounds 0-29.
# After rounds 9/19/29: LoRA merged, frozen run_eval.py diagnostics (216 group seeds 5,6; at r029 also 166).
# Re-running resumes after the last trained round.
set -euo pipefail
cd "$(dirname "$0")/.."
V=v4; MEM=${MEM:-0.68}  # other jobs share the GPU; MEM only sizes the KV cache (batch-invariant eval is unaffected)
ENV=/home/leesg17/miniconda3/etc/profile.d/conda.sh
diag() {  # $1 = checkpoint round tag, $2 = group name (216 / 166)
  local m=grpo/runs/$V/merged_$1
  [ -f "$m/config.json" ] || (source $ENV && conda activate vllm-train && python grpo/grpo.py merge --adapter grpo/runs/$V/ckpt/$1 --out "$m")
  for s in 5 6; do
    [ -f "runs/grpo_${V}_$1_$2/seed$s/scores.json" ] || (source $ENV && conda activate vllm &&
      python run_eval.py --model "$m" --gpu-mem-util "$MEM" --seed $s --ids-file grpo/data/ids_$2.txt --out "runs/grpo_${V}_$1_$2/seed$s")
  done
}
for seg in "10 r009" "20 r019" "30 r029"; do
  set -- $seg
  next=$(grep -c '"phase": "train"' grpo/runs/$V/log.jsonl 2>/dev/null || true)
  RUN=runs/$V START=${next:-0} END=$1 JUDGE_MODEL=cli bash grpo/loop.sh \
    --pool data/pool_v4.jsonl --questions 16 --pool-offset 16 --samples 8 --no-topup --hints --reward v4 \
    --groups-per-step 4 --lr 1e-4 --beta 0.001 --gpu-mem "$MEM"
  diag $2 216
done
diag r029 166
