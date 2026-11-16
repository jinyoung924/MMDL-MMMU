#!/usr/bin/env bash
# StructReward stage A2 (structreward/protocol.md, Amendment 1): cold-start SFT on the base model's own correct solutions
# written in the structured format, then the same three checks as stage A; stage B follows if both gates pass.
# Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
R=structreward/runs; N=sr_sft2; A=runs/$N/rft/epoch2; MEM=${MEM:-0.75}
date; echo "== own solutions: the base model solves the 5,000 SFT questions with the format instruction (2 samples each)"
[ -f structreward/data/sft_own_pool.jsonl ] || python structreward/sr.py prep_own
own() {  # out ids seed
  [ -f "$1" ] || (cd grpo && python grpo.py screen --pool ../structreward/data/sft_own_pool.jsonl --ids "../$2" \
    --samples 2 --seed "$3" --gpu-mem $MEM --out "../$1")
}
own $R/own_base_s0.jsonl structreward/data/sft_own_ids.txt 0
if [ -f $R/own_base_s1.jsonl ] || ! python structreward/sr.py select_own | tee $R/select_own.txt; then
  date; echo "== fewer than 3,000 questions with a usable solution: 2 more samples for the questions without one"
  [ -f $R/sft_own_missing_s0.txt ] || cp structreward/data/sft_own_missing.txt $R/sft_own_missing_s0.txt
  own $R/own_base_s1.jsonl $R/sft_own_missing_s0.txt 1
  python structreward/sr.py select_own | tee $R/select_own.txt
fi
date; echo "== cold-start SFT on own solutions (2 epochs)"
[ -f grpo/$A/adapter_model.safetensors ] || python grpo/rft.py train $N
date; echo "== gate 1: held-out 300 (format rate, accuracy against the base)"
[ -f $R/heldout_sft2.jsonl ] || (cd grpo && python grpo.py screen --pool ../structreward/data/heldout.jsonl \
  --ids ../structreward/data/heldout_ids.txt --samples 4 --seed 0 --gpu-mem $MEM --adapter $A --out ../$R/heldout_sft2.jsonl)
G=pass
python structreward/sr.py heldout sft2 | tee $R/gate_heldout_sft2.txt || G=fail
date; echo "== check: MC items (289, forgetting guard; reported, not a gate)"
[ -f grpo/runs/heldout/v7_$N.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v7.jsonl \
  --ids data/heldout/v7_unseen_v12.txt --samples 4 --gpu-mem $MEM --adapter $A --out runs/heldout/v7_$N.jsonl)
python targets/round2.py mc $N | tee $R/check_mc_sft2.txt || true
date; echo "== gate 2: MMMU dev (900 questions, seed 0, frozen pipeline, GPU share $MEM)"
[ -f grpo/runs/$N/merged/config.json ] || python grpo/grpo.py merge --adapter grpo/$A --out grpo/runs/$N/merged
conda activate vllm
[ -f runs/${N}_full/seed0/scores.json ] || python run_eval.py --model grpo/runs/$N/merged --seed 0 --gpu-mem-util $MEM --out runs/${N}_full/seed0
python analyze.py compare results/seed* vs runs/${N}_full/seed0 --base-mean 1 | tee runs/${N}_full/compare_base_mean.txt
python3 -c "
import json; a = 100 * json.load(open('runs/${N}_full/seed0/scores.json'))['overall_micro']
print(f'dev {a:.2f}  (base 5-seed mean 65.16; stops at <= 63.06)  gate 2:', 'fail' if a <= 63.06 else 'pass')" | tee $R/gate_dev_sft2.txt
date; echo "== stage A2 done (gate 1: $G)"
if [ "$G" = pass ] && grep -q "gate 2: pass" $R/gate_dev_sft2.txt; then
  date; echo "== both gates passed: stage B on the own-solution cold start"
  COLD=$N RUN_NAME=sr_rl2 bash structreward/chain_b.sh
fi
