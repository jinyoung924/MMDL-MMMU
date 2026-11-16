#!/usr/bin/env bash
# Exploratory, outside the gates (music/protocol.md run log): the round-3 model on the 30 MMMU Music questions,
# frozen pipeline, 5 seeds. First the base on Music only, seed 0, to confirm that a subject-only run reproduces the
# Music answers of the full run.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
[ -f grpo/runs/round3/merged/config.json ] || python grpo/grpo.py merge --adapter grpo/runs/round3/rft/epoch2 --out grpo/runs/round3/merged
conda activate vllm
date; echo "== base, Music only, seed 0 (reproduction check)"
[ -f runs/base_music_check/seed0/scores.json ] || python run_eval.py --seed 0 --subjects Music --out runs/base_music_check/seed0
python - <<'PY'
import json
full = {p['id']: p for p in map(json.loads, open('results/seed0/predictions.jsonl')) if p['subject'] == 'Music'}
sub = {p['id']: p for p in map(json.loads, open('runs/base_music_check/seed0/predictions.jsonl'))}
same = sum(full[i]['response'] == sub[i]['response'] for i in full)
print(f'base Music-only vs full run, seed 0: {same}/{len(full)} responses identical, '
      f'{sum(full[i]["correct"] == sub[i]["correct"] for i in full)}/{len(full)} same verdict')
PY
date; echo "== round 3, Music only, 5 seeds"
for s in 0 1 2 3 4; do
  [ -f runs/round3_music/seed$s/scores.json ] || python run_eval.py --model grpo/runs/round3/merged --seed $s --subjects Music --out runs/round3_music/seed$s
done
python targets/round2.py music runs/round3_music music/rerender/ids.txt | tee runs/round3_music/music.txt
date; echo "== music-only done"
