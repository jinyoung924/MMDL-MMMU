#!/usr/bin/env python
"""VisualWebInstruct-verified letter-MC items -> v7 RFT pool `data/pool_v7.jsonl` (+ held-out split).

The item list `data/pool_v7_qids.json` (3,924) comes from the 2026-11-06 read-only survey: an option list parsed from the
question, a gold letter mapped from short_answer and present among the options, one image, English, no MMMU-val text or
image overlap (prepare_virl.mmmu_overlap), then one item per VWI base idx, difficulty >= 2, 3-5 options and no duplicate
(option set, gold). This script re-parses each listed item, re-checks the gold, saves the image and renders the prompt
the way run_eval.build_prompt renders MMMU multiple choice: stem, "(A) option" lines, then the CoT MC suffix.

python grpo/prepare_vwi_mc.py      # vllm-train env (pyarrow)
"""
import json, random, re, sys
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
from run_eval import COT_MC_SUFFIX

SRC = Path('/home/leesg17/data/vwi_verified')  # TIGER-Lab/VisualWebInstruct-verified @0e54d116
MARK = re.compile(r'(?:^|(?<=[\s:,;]))(\()?([A-Ha-h])([\).:])(?=\s)')
FINAL = re.compile(r'(?:option|answer|choice)s?(?:\s+is)?\s*:?\s*(?:\*\*)?\s*\(?([A-Ha-h])\)?(?![A-Za-z])', re.I)
HELDOUT = 300  # first 300 of the shuffled pool: never trained on (v7_protocol.md gate 1)


def parse_options(q):
    """Longest chain of same-style markers A,B,C,... (consecutive letters) -> ({LETTER: text}, stem end) or (None, None)."""
    ms, best = list(MARK.finditer(q)), None
    for i, m in enumerate(ms):
        if m[2] not in 'Aa':
            continue
        style, chain = (bool(m[1]), m[3], m[2].isupper()), [m]
        for n in ms[i + 1:]:
            if (bool(n[1]), n[3], n[2].isupper()) == style and ord(n[2]) == ord(chain[-1][2]) + 1:
                chain.append(n)
        if len(chain) >= 2 and (best is None or len(chain) >= len(best)):
            best = chain
    if not best:
        return None, None
    opts = {}
    for k, m in enumerate(best):
        end = best[k + 1].start() if k + 1 < len(best) else len(q)
        opts[m[2].upper()] = q[m.end():end].strip().strip(',;').strip()
    if best[-1].end() < len(q) and '\n' in q[best[-1].end():].strip():  # text after the last option: keep its first line
        opts[best[-1][2].upper()] = q[best[-1].end():].strip().split('\n')[0].strip()
    return opts, best[0].start()


def norm(s):
    return re.sub(r'[\s$\\{}().,;:*]+', '', s.lower())


def gold_letter(sa, opts):
    s = sa.strip()
    if re.match(r'^\(?[A-Ha-h]\)?\s*(?:,|and|&)\s*\(?[A-Ha-h]\)?(?:[\s,]|$)', s):
        return None
    for pat in (r'^\s*\(?([A-Ha-h])\)?[.)]?\s*$', r'^\s*\(?([A-Ha-h])[\).:]\s'):
        m = re.match(pat, s)
        if m:
            return m[1].upper()
    m = FINAL.search(s)
    if m and (m[1].isupper() or s[m.start(1) - 1] == '('):
        return m[1].upper()
    for ok in (lambda t: norm(t) and norm(t) == norm(s), lambda t: len(norm(t)) >= 4 and norm(t) in norm(s)):
        hits = [L for L, t in opts.items() if ok(t)]
        if len(hits) == 1:
            return hits[0]
    return None


def render(q, opts, start):
    stem = q[:start].replace('<image>', '').strip()
    return '<image>\n' + stem + '\n' + ''.join(f'({k}) {v}\n' for k, v in opts.items()) + COT_MC_SUFFIX


def main():
    want = json.loads((HERE / 'data/pool_v7_qids.json').read_text())
    by_batch = {}
    for qid in want:
        b, idx = qid[len('vwi-'):].rsplit('-', 1)
        by_batch.setdefault(b, set()).add(idx)
    (SRC / 'images').mkdir(exist_ok=True)
    pool = {}
    for b, idxs in sorted(by_batch.items()):
        for f in sorted((SRC / b).glob('*.parquet')):
            for batch in pq.ParquetFile(f).iter_batches(batch_size=256):
                for r in batch.to_pylist():
                    if r['idx'] not in idxs:
                        continue
                    q = r['question'].strip()
                    opts, start = parse_options(q)
                    gold = gold_letter(r['short_answer'] or '', opts or {})
                    assert opts and gold in opts and len(r['images']) == 1, (b, r['idx'])
                    path = SRC / 'images' / f"{b}_{r['idx']}.png"
                    path.write_bytes(r['images'][0]['bytes'])
                    pool[f'vwi-{b}-{r["idx"]}'] = {'qid': f'vwi-{b}-{r["idx"]}', 'kind': 'mc', 'text': render(q, opts, start),
                                                   'image': str(path), 'gold': gold, 'options': opts,
                                                   'difficulty': r['difficulty'], 'reference': r['answer']}
        print(b, len(pool), flush=True)
    assert len(pool) == len(want), (len(pool), len(want))
    out = [pool[q] for q in want]
    random.Random(0).shuffle(out)
    (HERE / 'data/pool_v7.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in out))
    (HERE / 'data/heldout/v7_unseen.txt').write_text('\n'.join(x['qid'] for x in out[:HELDOUT]) + '\n')
    (HERE / 'data/v7_train_ids.txt').write_text('\n'.join(x['qid'] for x in out[HELDOUT:]) + '\n')
    (HERE / 'data/v7_all_ids.txt').write_text('\n'.join(x['qid'] for x in out) + '\n')
    print(json.dumps({'pool': len(out), 'heldout': HELDOUT, 'train': len(out) - HELDOUT}))


if __name__ == '__main__':
    assert parse_options('Pick: (A) 2, (B) 3, (C) 4') == ({'A': '2', 'B': '3', 'C': '4'}, 6)
    assert gold_letter('The correct option is (B) √2 – 1.', {'A': '1', 'B': '√2 – 1'}) == 'B'
    assert gold_letter('15/4', {'A': '-5/4', 'C': '15/4'}) == 'C'
    assert render('<image>Find x. (A) 1 (B) 2', {'A': '1', 'B': '2'}, 15) == '<image>\nFind x.\n(A) 1\n(B) 2\n' + COT_MC_SUFFIX
    main()
