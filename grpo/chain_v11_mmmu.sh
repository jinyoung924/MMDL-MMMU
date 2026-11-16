#!/usr/bin/env bash
# v11 part 1 Amendment 1 (v11_protocol.md): exploratory MMMU 5 seeds of the epoch-2 adapter. Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
date; echo "== merge"
[ -f grpo/runs/v11/merged/config.json ] || python grpo/grpo.py merge --adapter grpo/runs/v11/rft/epoch2 --out grpo/runs/v11/merged
conda activate vllm
O=runs/grpo_v11_5seed
date; echo "== MMMU 5 seeds"
SEEDS="0 1 2 3 4" bash eval.sh grpo/runs/v11/merged $O
for s in 0 1 2 3 4; do
  C=$O/cmp/seed$s; mkdir -p $C; cp $O/seed$s/{predictions.jsonl,table.md} $C/
  python -c "
import json; s = json.load(open('$O/seed$s/scores.json'))
[s['config'].pop(k, None) for k in ('enable_lora', 'lora_adapter', 'max_lora_rank')]
json.dump(s, open('$C/scores.json', 'w'), indent=2)"
done
python analyze.py compare results/seed* vs $O/cmp/seed* | tee $O/compare.txt
date; echo "== v11 MMMU done"
