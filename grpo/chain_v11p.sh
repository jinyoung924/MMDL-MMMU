#!/usr/bin/env bash
# v11 part 0 pilot (v11_protocol.md): hints, variants A and B (generation only), report. Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
cd grpo
mkdir -p runs/v11p
date; echo "== B1 hints"
[ -f runs/v11p/hints.jsonl ] || python grpo.py screen --pool data/pool_v11_hintw.jsonl --ids data/v11_pilot_ids.txt \
  --samples 1 --seed 4 --max-tokens 512 --out runs/v11p/hints.jsonl
python v11_pilot.py hints
date; echo "== A own-way"
[ -f runs/v11p/A.jsonl ] || python grpo.py screen --pool data/pool_v11_A.jsonl --ids data/v11_pilot_ids.txt \
  --samples 4 --seed 5 --out runs/v11p/A.jsonl
date; echo "== B hint"
[ -f runs/v11p/B.jsonl ] || python grpo.py screen --pool data/pool_v11_B.jsonl --ids data/v11_pilot_B_ids.txt \
  --samples 4 --seed 5 --out runs/v11p/B.jsonl
date; echo "== report"
python v11_pilot.py report | tee runs/v11p/report.txt
date; echo "== v11 pilot done"
