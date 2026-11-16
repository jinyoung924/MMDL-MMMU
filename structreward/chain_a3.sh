#!/usr/bin/env bash
# StructReward stage A3 (structreward/protocol.md, Amendment 3): cold-start SFT on the base model's own solutions as
# written (plain numbered steps, no tags or boxes added), behind the target check (gate 0); then the checks of stage A.
# Stage B is not started from here (its reward reading for this format is registered first). Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
R=structreward/runs; N=sr_sft3; A=runs/$N/rft/epoch2; MEM=${MEM:-0.75}
date; echo "== targets (own solutions as written) and gate 0 (target check)"
python structreward/sr.py select_own | tee $R/select_own3.txt
python structreward/sr.py check_targets $N | tee $R/check_targets3.txt
date; echo "== cold-start SFT on own solutions (2 epochs)"
[ -f grpo/$A/adapter_model.safetensors ] || python grpo/rft.py train $N
date; echo "== gate 1: held-out 300 (numbered-step format rate, accuracy against the base)"
[ -f $R/heldout_sft3.jsonl ] || (cd grpo && python grpo.py screen --pool ../structreward/data/heldout.jsonl \
  --ids ../structreward/data/heldout_ids.txt --samples 4 --seed 0 --gpu-mem $MEM --adapter $A --out ../$R/heldout_sft3.jsonl)
G=pass
python structreward/sr.py heldout sft3 steps | tee $R/gate_heldout_sft3.txt || G=fail
date; echo "== check: MC items (289, forgetting guard; reported, not a gate)"
[ -f grpo/runs/heldout/v7_$N.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v7.jsonl \
  --ids data/heldout/v7_unseen_v12.txt --samples 4 --gpu-mem $MEM --adapter $A --out runs/heldout/v7_$N.jsonl)
python targets/round2.py mc $N | tee $R/check_mc_sft3.txt || true
date; echo "== gate 2: MMMU dev (900 questions, seed 0, frozen pipeline, GPU share $MEM)"
[ -f grpo/runs/$N/merged/config.json ] || python grpo/grpo.py merge --adapter grpo/$A --out grpo/runs/$N/merged
conda activate vllm
[ -f runs/${N}_full/seed0/scores.json ] || python run_eval.py --model grpo/runs/$N/merged --seed 0 --gpu-mem-util $MEM --out runs/${N}_full/seed0
python analyze.py compare results/seed* vs runs/${N}_full/seed0 --base-mean 1 | tee runs/${N}_full/compare_base_mean.txt
python3 -c "
import json; a = 100 * json.load(open('runs/${N}_full/seed0/scores.json'))['overall_micro']
print(f'dev {a:.2f}  (base 5-seed mean 65.16; stops at <= 63.06)  gate 2:', 'fail' if a <= 63.06 else 'pass')" | tee $R/gate_dev_sft3.txt
date; echo "== stage A3 done (gate 1: $G)"
