#!/usr/bin/env bash
# v10 (v10_protocol.md): v9 data + replay of own correct responses on solved items; train, gate 1, MMMU 5 seeds.
# Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
date; echo "== step 2 select"
[ -f grpo/runs/v10/rft_train.jsonl ] || python grpo/rft.py select v10
date; echo "== step 3 train"
[ -f grpo/runs/v10/rft/epoch2/adapter_model.safetensors ] || python grpo/rft.py train v10
date; echo "== step 4 gate 1"
[ -f grpo/runs/heldout/v8_sdftmix.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v3.jsonl \
  --ids data/heldout/v8_unseen.txt --samples 8 --seed 2 --adapter runs/v10/rft/epoch2 --out runs/heldout/v8_sdftmix.jsonl)
python grpo/heldout_compare.py v8 sdftmix | tee grpo/runs/heldout/v8_sdftmix_compare.txt
python - <<'PY' || { date; echo "== gate 1 FAILED (unseen CI low <= 0): stop"; exit 0; }
import sys; sys.path.insert(0, 'grpo')
from heldout_compare import boot, load
b, t = load('grpo/runs/heldout/v8_base.jsonl'), load('grpo/runs/heldout/v8_sdftmix.jsonl')
ids = [i for i in open('grpo/data/heldout/v8_unseen.txt').read().splitlines() if i]
assert all(b[i]['n'] == 8 and t[i]['n'] == 8 for i in ids)
d, lo, hi = boot([100 * (t[i]['correct'] / t[i]['n'] - b[i]['correct'] / b[i]['n']) for i in ids])
print(f'gate 1 unseen: {d:+.2f} [{lo:+.2f}, {hi:+.2f}]'); sys.exit(0 if lo > 0 else 1)
PY
date; echo "== gate 1 passed -> step 5 MMMU 5 seeds"
[ -f grpo/runs/v10/merged/config.json ] || python grpo/grpo.py merge --adapter grpo/runs/v10/rft/epoch2 --out grpo/runs/v10/merged
conda activate vllm
O=runs/grpo_v10_5seed
SEEDS="0 1 2 3 4" bash eval.sh grpo/runs/v10/merged $O
for s in 0 1 2 3 4; do
  C=$O/cmp/seed$s; mkdir -p $C; cp $O/seed$s/{predictions.jsonl,table.md} $C/
  python -c "
import json; s = json.load(open('$O/seed$s/scores.json'))
[s['config'].pop(k, None) for k in ('enable_lora', 'lora_adapter', 'max_lora_rank')]
json.dump(s, open('$C/scores.json', 'w'), indent=2)"
done
python analyze.py compare results/seed* vs $O/cmp/seed* | tee $O/compare.txt
date; echo "== v10 chain done"
