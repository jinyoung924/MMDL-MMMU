#!/usr/bin/env bash
# v7 RFT steps 2-5 (v7_protocol.md); step 1 (base sampling) runs first as its own unit. Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
while systemctl --user is-active -q v7-step1; do sleep 60; done
[ -f grpo/runs/heldout/v7_base.jsonl ] || { echo "step 1 output missing"; exit 1; }
conda activate vllm-train
date; echo "== step 2 select"
[ -f grpo/runs/v7/rft_train.jsonl ] || python grpo/rft.py select
date; echo "== step 3 train"
[ -f grpo/runs/v7/rft/epoch2/adapter_model.safetensors ] || python grpo/rft.py train
date; echo "== step 4 gate 1"
[ -f grpo/runs/heldout/v7_rft.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v7.jsonl \
  --ids data/heldout/v7_all.txt --samples 4 --adapter runs/v7/rft/epoch2 --out runs/heldout/v7_rft.jsonl)
python grpo/heldout_compare.py v7 rft | tee grpo/runs/heldout/v7_rft_compare.txt
python - <<'PY' || { date; echo "== gate 1 FAILED (unseen CI low <= 0): stop"; exit 0; }
import sys; sys.path.insert(0, 'grpo')
from heldout_compare import boot, load
b, t = load('grpo/runs/heldout/v7_base.jsonl'), load('grpo/runs/heldout/v7_rft.jsonl')
ids = [i for i in open('grpo/data/heldout/v7_unseen.txt').read().splitlines() if i]
d, lo, hi = boot([100 * (t[i]['correct'] / t[i]['n'] - b[i]['correct'] / b[i]['n']) for i in ids])
print(f'gate 1 unseen: {d:+.2f} [{lo:+.2f}, {hi:+.2f}]'); sys.exit(0 if lo > 0 else 1)
PY
date; echo "== gate 1 passed -> step 5 MMMU dev"
[ -f grpo/runs/v7/merged_rft/config.json ] || python grpo/grpo.py merge --adapter grpo/runs/v7/rft/epoch2 --out grpo/runs/v7/merged_rft
conda activate vllm
SEEDS=0 bash eval.sh grpo/runs/v7/merged_rft runs/grpo_v7_rft_full
C=runs/grpo_v7_rft_full/cmp/seed0; mkdir -p $C; cp runs/grpo_v7_rft_full/seed0/{predictions.jsonl,table.md} $C/
python -c "
import json; s = json.load(open('runs/grpo_v7_rft_full/seed0/scores.json'))
[s['config'].pop(k, None) for k in ('enable_lora', 'lora_adapter', 'max_lora_rank')]
json.dump(s, open('$C/scores.json', 'w'), indent=2)"
python analyze.py compare results/seed* vs $C --base-mean 1 | tee runs/grpo_v7_rft_full/compare_base_mean.txt
date; echo "== v7 chain done"
