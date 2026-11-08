#!/usr/bin/env bash
# v8 RFT (v8_protocol.md): base sampling, select, train, gate 1, gate 2. Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
date; echo "== step 1 sample"
(cd grpo
 [ -f runs/heldout/v8_base.jsonl ] || python grpo.py screen --pool data/pool_v3.jsonl --ids data/v8_num_all.txt \
   --samples 8 --seed 1 --out runs/heldout/v8_base.jsonl
 [ -f runs/heldout/v8mc_base.jsonl ] || python grpo.py screen --pool data/pool_v7.jsonl --ids data/v8_mc_train.txt \
   --samples 4 --seed 1 --out runs/heldout/v8mc_base.jsonl)
date; echo "== step 2 select"
[ -f grpo/runs/v8/rft_train.jsonl ] || python grpo/rft.py select v8
date; echo "== step 3 train"
[ -f grpo/runs/v8/rft/epoch2/adapter_model.safetensors ] || python grpo/rft.py train v8
date; echo "== step 4 gate 1"
[ -f grpo/runs/heldout/v8_rft.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v3.jsonl \
  --ids data/heldout/v8_unseen.txt --samples 8 --seed 2 --adapter runs/v8/rft/epoch2 --out runs/heldout/v8_rft.jsonl)
python grpo/heldout_compare.py v8 rft | tee grpo/runs/heldout/v8_rft_compare.txt
python - <<'PY' || { date; echo "== gate 1 FAILED (unseen CI low <= 0): stop"; exit 0; }
import sys; sys.path.insert(0, 'grpo')
from heldout_compare import boot, load
b, t = load('grpo/runs/heldout/v8_base.jsonl'), load('grpo/runs/heldout/v8_rft.jsonl')
ids = [i for i in open('grpo/data/heldout/v8_unseen.txt').read().splitlines() if i]
assert all(b[i]['n'] == 8 and t[i]['n'] == 8 for i in ids)
d, lo, hi = boot([100 * (t[i]['correct'] / t[i]['n'] - b[i]['correct'] / b[i]['n']) for i in ids])
print(f'gate 1 unseen: {d:+.2f} [{lo:+.2f}, {hi:+.2f}]'); sys.exit(0 if lo > 0 else 1)
PY
date; echo "== gate 1 passed -> step 5 MMMU dev"
[ -f grpo/runs/v8/merged_rft/config.json ] || python grpo/grpo.py merge --adapter grpo/runs/v8/rft/epoch2 --out grpo/runs/v8/merged_rft
conda activate vllm
SEEDS=0 bash eval.sh grpo/runs/v8/merged_rft runs/grpo_v8_rft_full
C=runs/grpo_v8_rft_full/cmp/seed0; mkdir -p $C; cp runs/grpo_v8_rft_full/seed0/{predictions.jsonl,table.md} $C/
python -c "
import json; s = json.load(open('runs/grpo_v8_rft_full/seed0/scores.json'))
[s['config'].pop(k, None) for k in ('enable_lora', 'lora_adapter', 'max_lora_rank')]
json.dump(s, open('$C/scores.json', 'w'), indent=2)"
python analyze.py compare results/seed* vs $C --base-mean 1 | tee runs/grpo_v8_rft_full/compare_base_mean.txt
date; echo "== v8 chain done"
