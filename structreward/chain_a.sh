#!/usr/bin/env bash
# StructReward stage A (structreward/protocol.md): cold-start SFT, then its three checks. Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
R=structreward/runs; A=runs/sr_sft/rft/epoch2   # adapter, relative to grpo/
MEM=${MEM:-0.75}   # GPU share for vLLM; 0.85 / 0.90 ran out of memory next to other GPU jobs on this machine (11/14 19:49)
mkdir -p $R
date; echo "== cold-start SFT (5,000 targets, 2 epochs)"
[ -f grpo/$A/adapter_model.safetensors ] || python grpo/rft.py train sr_sft
date; echo "== gate 1: held-out 300 (format rate, accuracy against the base)"
screen() {  # out [adapter]
  [ -f "$1" ] || (cd grpo && python grpo.py screen --pool ../structreward/data/heldout.jsonl --ids ../structreward/data/heldout_ids.txt \
    --samples 4 --seed 0 --gpu-mem $MEM ${2:+--adapter $2} --out "../$1")
}
screen $R/heldout_base.jsonl
screen $R/heldout_sft.jsonl $A
G=pass
python structreward/sr.py heldout sft | tee $R/gate_heldout_sft.txt || G=fail
date; echo "== check: MC items (289, forgetting guard; reported, not a gate)"
[ -f grpo/runs/heldout/v7_sr_sft.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v7.jsonl \
  --ids data/heldout/v7_unseen_v12.txt --samples 4 --gpu-mem $MEM --adapter $A --out runs/heldout/v7_sr_sft.jsonl)
python targets/round2.py mc sr_sft | tee $R/check_mc_sft.txt || true
date; echo "== gate 2: MMMU dev (900 questions, seed 0, frozen pipeline)"
[ -f grpo/runs/sr_sft/merged/config.json ] || python grpo/grpo.py merge --adapter grpo/$A --out grpo/runs/sr_sft/merged
conda activate vllm
# The frozen pipeline with a smaller GPU share: first confirm on the base model that this does not change the responses
[ -f runs/base_music_mem/seed0/scores.json ] || python run_eval.py --subjects Music --seed 0 --gpu-mem-util $MEM --out runs/base_music_mem/seed0
python3 -c "
import json
a = {p['id']: p['response'] for p in map(json.loads, open('results/seed0/predictions.jsonl'))}
b = {p['id']: p['response'] for p in map(json.loads, open('runs/base_music_mem/seed0/predictions.jsonl'))}
print('base seed 0, Music, GPU share $MEM: identical responses', sum(a[i] == b[i] for i in b), '/', len(b))" | tee $R/check_mem.txt
[ -f runs/sr_sft_full/seed0/scores.json ] || python run_eval.py --model grpo/runs/sr_sft/merged --seed 0 --gpu-mem-util $MEM --out runs/sr_sft_full/seed0
python analyze.py compare results/seed* vs runs/sr_sft_full/seed0 --base-mean 1 | tee runs/sr_sft_full/compare_base_mean.txt
python3 -c "
import json; a = 100 * json.load(open('runs/sr_sft_full/seed0/scores.json'))['overall_micro']
print(f'dev {a:.2f}  (base 5-seed mean 65.16; stage A stops the as-is line at <= 63.06)  gate 2:', 'fail' if a <= 63.06 else 'pass')" | tee $R/gate_dev_sft.txt
date; echo "== stage A done (gate 1: $G)"
