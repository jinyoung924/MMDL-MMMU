#!/usr/bin/env bash
# v12 (v12_protocol.md): v11 data + long own-correct MC anchors; train, gate 1, MC check, MMMU seed 0.
# Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
date; echo "== step 2 select"
[ -f grpo/runs/v12/rft_train.jsonl ] || python grpo/rft.py select v12
date; echo "== step 3 train"
[ -f grpo/runs/v12/rft/epoch2/adapter_model.safetensors ] || python grpo/rft.py train v12
date; echo "== step 4 gate 1"
[ -f grpo/runs/heldout/v8_mcanchor.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v3.jsonl \
  --ids data/heldout/v8_unseen.txt --samples 8 --seed 2 --adapter runs/v12/rft/epoch2 --out runs/heldout/v8_mcanchor.jsonl)
python grpo/heldout_compare.py v8 mcanchor | tee grpo/runs/heldout/v8_mcanchor_compare.txt
G1=pass
python - <<'PY' || G1=fail
import sys; sys.path.insert(0, 'grpo')
from heldout_compare import boot, load
b, t = load('grpo/runs/heldout/v8_base.jsonl'), load('grpo/runs/heldout/v8_mcanchor.jsonl')
ids = [i for i in open('grpo/data/heldout/v8_unseen.txt').read().splitlines() if i]
assert all(b[i]['n'] == 8 and t[i]['n'] == 8 for i in ids)
d, lo, hi = boot([100 * (t[i]['correct'] / t[i]['n'] - b[i]['correct'] / b[i]['n']) for i in ids])
print(f'gate 1 unseen: {d:+.2f} [{lo:+.2f}, {hi:+.2f}]'); sys.exit(0 if lo > 0 else 1)
PY
date; echo "== gate 1 $G1"
date; echo "== step 5 MC check (descriptive): v12, then v11 as reference"
for a in v12 v11; do
  [ -f grpo/runs/heldout/v7_$a.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v7.jsonl \
    --ids data/heldout/v7_unseen_v12.txt --samples 4 --adapter runs/$a/rft/epoch2 --out runs/heldout/v7_$a.jsonl)
done
python - <<'PY' | tee grpo/runs/heldout/v7_mccheck_compare.txt
import json, re, sys; sys.path.insert(0, 'grpo')
from heldout_compare import boot, load
W = r'\bwait\b|\b(double[- ]check|re-?check|verify|let me check|let me verify)'
ids = open('grpo/data/heldout/v7_unseen_v12.txt').read().split()
h = 'grpo/runs/heldout/'
b = load(h + 'v7_base.jsonl')
def style(f):
    rs = [r['text'] for r in map(json.loads, open(f)) if r['qid'] in set(ids) and r['finish'] == 'stop']
    return sum(map(len, rs)) / len(rs), 1000 * sum(len(re.findall(W, x, re.I)) for x in rs) / sum(map(len, rs))
bc, bw = style(h + 'v7_base.rows.jsonl')
for a in ('v12', 'v11'):
    t = load(h + f'v7_{a}.jsonl')
    assert all(b[i]['n'] == 4 and t[i]['n'] == 4 for i in ids)
    acc = lambda r: r['correct'] / r['n']
    d, lo, hi = boot([100 * (acc(t[i]) - acc(b[i])) for i in ids])
    tc, tw = style(h + f'v7_{a}.rows.jsonl')
    print(f'MC check {a} n={len(ids)}  acc {100*sum(acc(b[i]) for i in ids)/len(ids):.1f} -> '
          f'{100*sum(acc(t[i]) for i in ids)/len(ids):.1f}  Δ {d:+.2f} [{lo:+.2f}, {hi:+.2f}]  '
          f'trunc {100*sum(b[i]["trunc"] for i in ids)/(4*len(ids)):.1f} -> {100*sum(t[i]["trunc"] for i in ids)/(4*len(ids)):.1f} %  '
          f'finished chars {bc:.0f} -> {tc:.0f}  wait+check/1k {bw:.2f} -> {tw:.2f}')
PY
[ "$G1" = pass ] || { date; echo "== gate 1 FAILED (unseen CI low <= 0): stop"; exit 0; }
date; echo "== gate 1 passed -> step 6 MMMU dev (seed 0)"
[ -f grpo/runs/v12/merged/config.json ] || python grpo/grpo.py merge --adapter grpo/runs/v12/rft/epoch2 --out grpo/runs/v12/merged
conda activate vllm
O=runs/grpo_v12_full
SEEDS=0 bash eval.sh grpo/runs/v12/merged $O
C=$O/cmp/seed0; mkdir -p $C; cp $O/seed0/{predictions.jsonl,table.md} $C/
python -c "
import json; s = json.load(open('$O/seed0/scores.json'))
[s['config'].pop(k, None) for k in ('enable_lora', 'lora_adapter', 'max_lora_rank')]
json.dump(s, open('$C/scores.json', 'w'), indent=2)"
python analyze.py compare results/seed* vs $C --base-mean 1 | tee $O/compare_base_mean.txt
date; echo "== v12 chain done"
