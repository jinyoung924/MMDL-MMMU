#!/usr/bin/env bash
# Music round 3 (music/protocol.md, Amendment 4): select, train, four gates, then MMMU 5 seeds if all pass.
# Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
M=music/runs
A=runs/round3/rft/epoch2   # adapter, relative to grpo/
screen() {  # pool ids out samples
  [ -f "$3" ] || (cd grpo && python grpo.py screen --pool "../$1" --ids "../$2" --samples "$4" --seed 0 --adapter $A --out "../$3")
}
date; echo "== select"
[ -f grpo/runs/round3/rft_train.jsonl ] || python targets/round2.py select round3 read_train3
date; echo "== train"
[ -f grpo/$A/adapter_model.safetensors ] || python grpo/rft.py train round3
G=pass
date; echo "== gate 1: reading test"
screen music/data/read_test.jsonl music/data/read_test_ids.txt $M/read_round3.jsonl 4
python music/reading.py gate $M/read_base.jsonl $M/read_round3.jsonl | tee $M/gate_reading_round3.txt || G=fail
screen music/data/read_test2.jsonl music/data/read_test2_ids.txt $M/read2_round3.jsonl 4
python music/reading.py gate $M/read2_base.jsonl $M/read2_round3.jsonl | tee $M/gate_reading2_round3.txt || true
date; echo "== gate 2: positions and two-note items"
python music/reading.py cells $M/read_round3.jsonl $M/read2_round3.jsonl | tee $M/gate_cells_round3.txt || G=fail
date; echo "== gate 3: paired check on five MMMU questions (16 samples)"
screen music/rerender/pool.jsonl music/rerender/ids.txt music/rerender/round3.jsonl 16
python music/rerender_check.py gate round3 | tee $M/gate_paired_round3.txt || G=fail
python music/rerender_check.py report | tee music/rerender/report.txt
date; echo "== gate 4: MC check (289 items)"
[ -f grpo/runs/heldout/v7_round3.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v7.jsonl \
  --ids data/heldout/v7_unseen_v12.txt --samples 4 --adapter $A --out runs/heldout/v7_round3.jsonl)
python targets/round2.py mc round3 | tee $M/gate_mc_round3.txt || G=fail
date; echo "== all gates: $G"
[ "$G" = pass ] || { date; echo "== a gate failed: stop"; exit 0; }
date; echo "== MMMU 5 seeds"
[ -f grpo/runs/round3/merged/config.json ] || python grpo/grpo.py merge --adapter grpo/$A --out grpo/runs/round3/merged
conda activate vllm
O=runs/round3_full
SEEDS="0 1 2 3 4" bash eval.sh grpo/runs/round3/merged $O
for s in 0 1 2 3 4; do
  D=$O/cmp/seed$s; mkdir -p $D; cp $O/seed$s/{predictions.jsonl,table.md} $D/
  python -c "
import json; s = json.load(open('$O/seed$s/scores.json'))
[s['config'].pop(k, None) for k in ('enable_lora', 'lora_adapter', 'max_lora_rank')]
json.dump(s, open('$D/scores.json', 'w'), indent=2)"
done
python analyze.py compare results/seed* vs $O/cmp/seed* --target Music | tee $O/compare.txt
python analyze.py compare results/seed* vs $O/cmp/seed0 $O/cmp/seed1 --target Music | tee $O/compare_seeds01.txt
python targets/round2.py compare $O round3 music/rerender/ids.txt | tee $O/verdict.txt
date; echo "== round 3 done"
