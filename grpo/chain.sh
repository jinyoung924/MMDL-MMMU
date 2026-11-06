#!/usr/bin/env bash
# Quick check: GRPO rounds 0-9 -> eval 216-group (seeds 5,6) -> rounds 10-19 -> eval 216-group + full 900.
# Eval seeds 5+ so tuned runs never share random streams with the selection seeds 0-4.
#   V=v2 bash grpo/chain.sh --lr 1e-4        # extra args go to grpo.py; RESUME=<round> to restart mid-way
set -euo pipefail
cd "$(dirname "$0")/.."
V=${V:-v1}
evalrun() {  # $1 = ckpt round, $2 = ids file or "", $3 = seed, $4 = out
  (source /home/leesg17/miniconda3/etc/profile.d/conda.sh && conda activate vllm &&
   python run_eval.py --gpu-mem-util 0.85 --enable-lora --lora-adapter "grpo/runs/$V/ckpt/$1" --seed "$3" \
     ${2:+--ids-file "$2"} --out "$4")
}
RUN=runs/$V START=${RESUME:-0} END=10 bash grpo/loop.sh --groups-per-step 4 "$@"
for s in 5 6; do evalrun r009 grpo/data/ids_216.txt $s runs/grpo_${V}_r009_216/seed$s; done
RUN=runs/$V START=10 END=20 bash grpo/loop.sh --groups-per-step 4 "$@"
for s in 5 6; do evalrun r019 grpo/data/ids_216.txt $s runs/grpo_${V}_r019_216/seed$s; done
evalrun r019 "" 5 runs/grpo_${V}_r019_full/seed5
