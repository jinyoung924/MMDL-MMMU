#!/usr/bin/env python
"""v11 part 0 pilot (v11_protocol.md): do hint / own-way prompts give targets shaped like the base's own solutions?

python grpo/v11_pilot.py prep      # data/v11_pilot_ids.txt, data/pool_v11_{hintw,A}.jsonl
python grpo/v11_pilot.py hints     # runs/v11p/hints.rows.jsonl -> data/pool_v11_B.jsonl
python grpo/v11_pilot.py report    # runs/v11p/{A,B}.rows.jsonl + v9 control -> table + pass rule
"""
import ast, json, random, re, statistics as st, sys
from pathlib import Path

G = Path(__file__).resolve().parent
D, R = G / 'data', G / 'runs/v11p'
REF = '\n\nReference solution (for you to understand the method; do not mention it):\n{ref}\n\n'
OWN_A = ('Now solve the problem yourself as you normally would, without relying on the reference: work it out step by '
         'step, check your reading of the figure and each step, and accept a fact only if you can verify it from the '
         'problem itself.')
HINT_W = ('\n\nReference solution:\n{ref}\n\nWrite a hint for a student who is stuck on this problem, in at most two '
          'sentences. Name the key idea or method only. Do not give any numbers, intermediate results, or the final answer.')
OWN_B = ('\n\nHint: {hint}\n\nSolve the problem yourself as you normally would (do not mention the hint): work it out '
         'step by step and check your reading of the figure and each step.')
WAIT = r'\bwait\b|\b(double[- ]check|re-?check|verify|let me check|let me verify)'


def load(f):
    return [json.loads(l) for l in open(f)]


def rows_by(*files):
    by = {}
    for f in files:
        for r in load(f):
            by.setdefault(r['qid'], []).append(r)
    return by


def split(q):
    head, sep, tail = q['text_plain'].rpartition('\nThink step by step')
    assert sep, q['qid']
    return head, sep + tail


def write(f, qs):
    f.write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in qs))


def pilot():
    pool = {q['qid']: q for q in load(D / 'pool_v9_ref.jsonl')}
    return [pool[i] for i in (D / 'v11_pilot_ids.txt').read_text().split()]


def prep():
    ids = (D / 'v9_ids.txt').read_text().split()
    (D / 'v11_pilot_ids.txt').write_text(''.join(i + '\n' for i in random.Random(0).sample(ids, 100)))
    qs = pilot()
    write(D / 'pool_v11_hintw.jsonl', [{**q, 'text': split(q)[0] + HINT_W.format(ref=q['reference'].strip())} for q in qs])
    write(D / 'pool_v11_A.jsonl', [{**q, 'text': split(q)[0] + REF.format(ref=q['reference'].strip()) + OWN_A + split(q)[1]}
                                  for q in qs])


def leaks(q, h):
    nums = [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', h.replace(',', ''))]
    if q['kind'] == 'num':
        return any(abs(x - float(q['gold'])) <= 1e-6 * max(1, abs(float(q['gold']))) for x in nums)
    o = q['options']
    opt = (o if isinstance(o, dict) else ast.literal_eval(o))[q['gold']]
    return (re.search(rf'\b(option|choice|answer)\s*\(?{q["gold"]}\)?(?![\w])|\({q["gold"]}\)', h, re.I) is not None
            or ' '.join(str(opt).split()).lower() in ' '.join(h.split()).lower())


def hints():
    by, out, bad = rows_by(R / 'hints.rows.jsonl'), [], {}
    for q in pilot():
        r = by[q['qid']][0]
        h = ' '.join(r['text'].split()).removeprefix('Hint:').strip()
        why = ('unfinished' if r['finish'] != 'stop' else 'long' if len(h) > 600 else 'leak' if leaks(q, h) else '')
        if why:
            bad[why] = bad.get(why, 0) + 1
            continue
        head, tail = split(q)
        out.append({**q, 'text': head + OWN_B.format(hint=h) + tail, 'hint': h})
    write(D / 'pool_v11_B.jsonl', out)
    (D / 'v11_pilot_B_ids.txt').write_text(''.join(q['qid'] + '\n' for q in out))
    print(json.dumps({'hints': len(out), 'dropped': bad}))


def report():
    qs = pilot()
    h = G / 'runs/heldout'
    base = {**rows_by(h / 'v8_base.rows.jsonl'), **rows_by(h / 'v7_base.rows.jsonl', h / 'v8mc_base.rows.jsonl')}
    num = rows_by(h / 'v8_base.rows.jsonl')
    med = {}
    for q in qs:
        rs = num[q['qid']] if q['kind'] == 'num' else base[q['qid']]
        L = [len(r['text']) for r in rs if r['finish'] == 'stop']
        med[q['qid']] = st.median(L) if L else None
    fallback = st.median(v for v in med.values() if v)
    med = {k: v or fallback for k, v in med.items()}
    ids = {q['qid'] for q in qs}
    res = {}
    for name, f in (('v9 control', h / 'v9_ref.rows.jsonl'), ('A own-way', R / 'A.rows.jsonl'), ('B hint', R / 'B.rows.jsonl')):
        rs = [r for r in load(f) if r['qid'] in ids]
        ok = [r for r in rs if r['finish'] == 'stop' and r['correct']]
        use = [r for r in ok if not re.search('reference|hint', r['text'], re.I) and len(r['text']) >= 0.6 * med[r['qid']]]
        ratio = st.median(len(r['text']) / med[r['qid']] for r in ok) if ok else 0
        dens = 1000 * sum(len(re.findall(WAIT, r['text'], re.I)) for r in ok) / max(1, sum(len(r['text']) for r in ok))
        items = len({r['qid'] for r in use})
        ok_ = ratio >= 0.6 and dens >= 0.5 and items >= 40
        res[name] = items if ok_ and name != 'v9 control' else -1
        print(f'{name:11s} n={len(rs)} acc {100*sum(r["correct"] for r in rs)/len(rs):.1f}% '
              f'trunc {100*sum(r["finish"] != "stop" for r in rs)/len(rs):.1f}% | correct finished: median length ratio '
              f'{ratio:.2f}, wait+check/1k {dens:.2f} | usable {len(use)} on {items} items -> {"PASS" if ok_ else "fail"}')
    best = max(res, key=res.get)
    print('chosen:', best if res[best] >= 0 else 'none (stop and report)')


if __name__ == '__main__':
    {'prep': prep, 'hints': hints, 'report': report}[sys.argv[1]]()
