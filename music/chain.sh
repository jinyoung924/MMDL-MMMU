#!/usr/bin/env bash
# Music steps 2-3 (music/protocol.md, Amendment 2): template targets (the exact reading as the solution) + v12 anchors,
# train, reading gate, MC check, then MMMU seed 0 if both gates pass. Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
conda activate vllm-train
R=music/runs
A=runs/music/rft/epoch2   # adapter, relative to grpo/
date; echo "== 2b select (template targets, Amendment 2)"
[ -f grpo/runs/music/rft_train.jsonl ] || python music/reading.py select template
date; echo "== 2c train"
[ -f grpo/$A/adapter_model.safetensors ] || python grpo/rft.py train music
date; echo "== 2d reading gate (test set, 4 samples, seed 0, as for the base)"
[ -f $R/read_tuned.jsonl ] || (cd grpo && python grpo.py screen --pool ../music/data/read_test.jsonl \
  --ids ../music/data/read_test_ids.txt --samples 4 --seed 0 --adapter $A --out ../$R/read_tuned.jsonl)
G1=pass
python music/reading.py gate $R/read_base.jsonl $R/read_tuned.jsonl | tee $R/gate_reading.txt || G1=fail
date; echo "== reading gate: $G1"
date; echo "== 2e MC check (289 items, 4 samples, as in v12)"
[ -f grpo/runs/heldout/v7_music.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v7.jsonl \
  --ids data/heldout/v7_unseen_v12.txt --samples 4 --adapter $A --out runs/heldout/v7_music.jsonl)
G2=pass
python - <<'PY' | tee $R/gate_mc.txt || G2=fail
import json, re, sys; sys.path.insert(0, 'grpo')
from heldout_compare import boot, load
W = r'\bwait\b|\b(double[- ]check|re-?check|verify|let me check|let me verify)'
ids = open('grpo/data/heldout/v7_unseen_v12.txt').read().split()
h = 'grpo/runs/heldout/'
b, t = load(h + 'v7_base.jsonl'), load(h + 'v7_music.jsonl')
assert all(b[i]['n'] == 4 and t[i]['n'] == 4 for i in ids)
def style(f):
    rs = [r['text'] for r in map(json.loads, open(f)) if r['qid'] in set(ids) and r['finish'] == 'stop']
    return sum(map(len, rs)) / len(rs), 1000 * sum(len(re.findall(W, x, re.I)) for x in rs) / sum(map(len, rs))
acc = lambda r: r['correct'] / r['n']
d, lo, hi = boot([100 * (acc(t[i]) - acc(b[i])) for i in ids])
(bc, bw), (tc, tw) = style(h + 'v7_base.rows.jsonl'), style(h + 'v7_music.rows.jsonl')
print(f'MC check n={len(ids)}  acc {100*sum(acc(b[i]) for i in ids)/len(ids):.1f} -> '
      f'{100*sum(acc(t[i]) for i in ids)/len(ids):.1f}  Δ {d:+.2f} [{lo:+.2f}, {hi:+.2f}]  '
      f'trunc {100*sum(b[i]["trunc"] for i in ids)/(4*len(ids)):.1f} -> {100*sum(t[i]["trunc"] for i in ids)/(4*len(ids)):.1f} %  '
      f'finished chars {bc:.0f} -> {tc:.0f}  wait+check/1k {bw:.2f} -> {tw:.2f}')
sys.exit(1 if hi < 0 else 0)  # significant loss = the whole CI below 0
PY
date; echo "== MC check: $G2"
[ "$G1" = pass ] && [ "$G2" = pass ] || { date; echo "== a step-2 gate failed: stop"; exit 0; }
date; echo "== 3 MMMU seed 0"
[ -f grpo/runs/music/merged/config.json ] || python grpo/grpo.py merge --adapter grpo/$A --out grpo/runs/music/merged
conda activate vllm
O=runs/music_full
SEEDS=0 bash eval.sh grpo/runs/music/merged $O
C=$O/cmp/seed0; mkdir -p $C; cp $O/seed0/{predictions.jsonl,table.md} $C/
python -c "
import json; s = json.load(open('$O/seed0/scores.json'))
[s['config'].pop(k, None) for k in ('enable_lora', 'lora_adapter', 'max_lora_rank')]
json.dump(s, open('$C/scores.json', 'w'), indent=2)"
python analyze.py compare results/seed* vs $C --base-mean 1 --target Music | tee $O/compare_base_mean.txt
date; echo "== music chain done"
