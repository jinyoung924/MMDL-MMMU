#!/usr/bin/env bash
# Round 2 (targets/protocol.md): one adapter for the Music round-2 items and the chem items, with the v12 anchors.
# Waits for the chem base measurement, then: key-signature base, select, train, gates, MMMU 5 seeds. Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
while systemctl --user is-active -q chem-base; do sleep 30; done
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
M=music/runs; C=targets/chem/runs
A=runs/round2/rft/epoch2   # adapter, relative to grpo/
screen() {  # pool ids out [adapter]
  [ -f "$3" ] || (cd grpo && python grpo.py screen --pool "../$1" --ids "../$2" --samples 4 --seed 0 ${4:+--adapter $4} --out "../$3")
}
date; echo "== base on the key-signature items"
screen music/data/read_test2.jsonl music/data/read_test2_ids.txt $M/read2_base.jsonl
python music/reading.py report $M/read2_base.jsonl | tee $M/read2_base_report.txt
date; echo "== select"
[ -f grpo/runs/round2/rft_train.jsonl ] || python targets/round2.py select
date; echo "== train"
[ -f grpo/$A/adapter_model.safetensors ] || python grpo/rft.py train round2
date; echo "== gate: Music reading test"
screen music/data/read_test.jsonl music/data/read_test_ids.txt $M/read_round2.jsonl $A
G=pass
python music/reading.py gate $M/read_base.jsonl $M/read_round2.jsonl | tee $M/gate_reading_round2.txt || G=fail
date; echo "== Music reading gate: $G"
echo "== key-signature items (reported, not a gate)"
screen music/data/read_test2.jsonl music/data/read_test2_ids.txt $M/read2_round2.jsonl $A
python music/reading.py gate $M/read2_base.jsonl $M/read2_round2.jsonl | tee $M/gate_reading2_round2.txt || true
if grep -q '^{"qid": "chem-' grpo/runs/round2/rft_train.jsonl; then
  date; echo "== gate: chem reading test"
  screen targets/chem/data/chem_test.jsonl targets/chem/data/chem_test_ids.txt $C/chem_round2.jsonl $A
  python targets/chem.py gate $C/chem_base.jsonl $C/chem_round2.jsonl | tee $C/gate_round2.txt || G=fail
  date; echo "== gates so far: $G"
fi
date; echo "== MC check (289 items)"
[ -f grpo/runs/heldout/v7_round2.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v7.jsonl \
  --ids data/heldout/v7_unseen_v12.txt --samples 4 --adapter $A --out runs/heldout/v7_round2.jsonl)
python targets/round2.py mc round2 | tee $M/gate_mc_round2.txt || G=fail
date; echo "== all gates: $G"
[ "$G" = pass ] || { date; echo "== a gate failed: stop"; exit 0; }
date; echo "== MMMU 5 seeds"
[ -f grpo/runs/round2/merged/config.json ] || python grpo/grpo.py merge --adapter grpo/$A --out grpo/runs/round2/merged
conda activate vllm
O=runs/round2_full
SEEDS="0 1 2 3 4" bash eval.sh grpo/runs/round2/merged $O
for s in 0 1 2 3 4; do
  D=$O/cmp/seed$s; mkdir -p $D; cp $O/seed$s/{predictions.jsonl,table.md} $D/
  python -c "
import json; s = json.load(open('$O/seed$s/scores.json'))
[s['config'].pop(k, None) for k in ('enable_lora', 'lora_adapter', 'max_lora_rank')]
json.dump(s, open('$D/scores.json', 'w'), indent=2)"
done
python analyze.py compare results/seed* vs $O/cmp/seed* --target Music | tee $O/compare.txt
python analyze.py compare results/seed* vs $O/cmp/seed0 $O/cmp/seed1 --target Music | tee $O/compare_seeds01.txt
python targets/round2.py compare $O | tee $O/verdict.txt
date; echo "== round 2 done"
