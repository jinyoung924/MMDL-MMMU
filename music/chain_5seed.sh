#!/usr/bin/env bash
# Music step 3 (music/protocol.md): MMMU seeds 1-4 of the merged model (seed 0 exists), then the comparisons.
# Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm
O=runs/music_full
date; echo "== MMMU 5 seeds"
SEEDS="0 1 2 3 4" bash eval.sh grpo/runs/music/merged $O
for s in 0 1 2 3 4; do
  C=$O/cmp/seed$s; mkdir -p $C; cp $O/seed$s/{predictions.jsonl,table.md} $C/
  python -c "
import json; s = json.load(open('$O/seed$s/scores.json'))
[s['config'].pop(k, None) for k in ('enable_lora', 'lora_adapter', 'max_lora_rank')]
json.dump(s, open('$C/scores.json', 'w'), indent=2)"
done
# primary and guard: all five seeds paired
python analyze.py compare results/seed* vs $O/cmp/seed* --target Music | tee $O/compare.txt
# forgetting on what the base reliably solved: pair seeds 0-1, select on the held-out base seeds 2-4
python analyze.py compare results/seed* vs $O/cmp/seed0 $O/cmp/seed1 --target Music | tee $O/compare_seeds01.txt
date; echo "== music 5-seed done"
