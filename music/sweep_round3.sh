#!/usr/bin/env bash
# Round-3 adapter at lower strength (targets/protocol.md, "Guard": adapter strength is a free knob).
# For each strength: a copy of the adapter with lora_alpha scaled, then reading tests, paired check, MC check.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
M=music/runs
for S in 50 75; do
  T=round3_a$S; A=runs/round3/rft/epoch2_a$S
  [ -f grpo/$A/adapter_config.json ] || python - <<PY
import json, shutil
src, dst = 'grpo/runs/round3/rft/epoch2', 'grpo/$A'
shutil.copytree(src, dst)
c = json.load(open(dst + '/adapter_config.json'))
c['lora_alpha'] = c['lora_alpha'] * $S / 100
json.dump(c, open(dst + '/adapter_config.json', 'w'), indent=2)
print('strength $S %: lora_alpha', c['lora_alpha'])
PY
  screen() { [ -f "$3" ] || (cd grpo && python grpo.py screen --pool "../$1" --ids "../$2" --samples "$4" --seed 0 --adapter $A --out "../$3"); }
  date; echo "== strength $S %: reading tests"
  screen music/data/read_test.jsonl music/data/read_test_ids.txt $M/read_$T.jsonl 4
  python music/reading.py gate $M/read_base.jsonl $M/read_$T.jsonl | tee $M/gate_reading_$T.txt || true
  screen music/data/read_test2.jsonl music/data/read_test2_ids.txt $M/read2_$T.jsonl 4
  python music/reading.py cells $M/read_$T.jsonl $M/read2_$T.jsonl | tee $M/gate_cells_$T.txt || true
  date; echo "== strength $S %: paired check"
  screen music/rerender/pool.jsonl music/rerender/ids.txt music/rerender/$T.jsonl 16
  python music/rerender_check.py gate $T | tee $M/gate_paired_$T.txt || true
  date; echo "== strength $S %: MC check"
  [ -f grpo/runs/heldout/v7_$T.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v7.jsonl \
    --ids data/heldout/v7_unseen_v12.txt --samples 4 --adapter $A --out runs/heldout/v7_$T.jsonl)
  python targets/round2.py mc $T | tee $M/gate_mc_$T.txt || true
done
python music/rerender_check.py report | tee music/rerender/report.txt
date; echo "== sweep done"
