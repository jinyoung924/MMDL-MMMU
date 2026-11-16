#!/usr/bin/env python
"""Music step 0 (music/protocol.md): tagging packets for Music questions with >= 1 wrong official seed, and the gate.

python music/step0.py export                         # -> music/step0/cases/<id>/, music/step0/batches.json
python music/step0.py summary A.jsonl B.jsonl [ADJ.jsonl]   # agreement, counts, registered gate
"""
import json, random, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import analyze  # noqa: E402  (frozen pipeline helpers: load, check_comparable, case_md)

OUT, SEEDS, HEAD, TAIL = ROOT / 'music/step0', range(5), 6000, 3000  # TAIL 3000 keeps analyze.looped() exact


def shown(p):
    r = p['response']
    if not p['truncated'] or len(r) <= HEAD + TAIL:
        return p
    cut = f'\n\n[... {len(r) - HEAD - TAIL:,} characters omitted; the response hit the token limit ...]\n\n'
    return {**p, 'response': r[:HEAD] + cut + r[-TAIL:]}


def export():
    from datasets import load_dataset
    dirs = [ROOT / f'results/seed{s}' for s in SEEDS]
    cfg, runs = analyze.check_comparable(dirs), [analyze.load(d) for d in dirs]
    pick = {}
    for i, p in runs[0].items():
        wrong = [(s, R[i]) for s, R in zip(SEEDS, runs) if not R[i]['correct']]
        if p['subject'] == 'Music' and wrong:  # finished responses first, then truncated; seed order within each
            pick[i] = sorted(wrong, key=lambda x: (x[1]['truncated'], x[0]))[:2]
    for r in load_dataset(cfg['data'], 'Music', split='validation', revision=cfg['data_revision']):
        if r['id'] not in pick:
            continue
        d = OUT / 'cases' / r['id']
        d.mkdir(parents=True, exist_ok=True)
        imgs = []
        for n in range(1, 8):
            if r.get(f'image_{n}'):
                r[f'image_{n}'].convert('RGB').save(d / f'image_{n}.png')
                imgs.append(f'![image {n}](image_{n}.png)')
        seeds, preds = zip(*pick[r['id']])
        (d / 'case.md').write_text(analyze.case_md(r, [shown(p) for p in preds], seeds, imgs, None))
    batches = {}
    for name, seed in (('A', 0), ('B', 1)):  # two taggers, different splits
        ids = sorted(pick)
        random.Random(seed).shuffle(ids)
        batches[name] = [ids[k::4] for k in range(4)]
    (OUT / 'batches.json').write_text(json.dumps(batches, indent=1))
    print(f'{len(pick)} cases -> {OUT / "cases"}; batches {[len(b) for b in batches["A"]]}')


def gate(strict, lenient, adjudicated, n):
    """Registered rule: pass if strict >= n/2; fail if lenient < n/2; in between, adjudication decides."""
    if 2 * strict >= n:
        return 'PASS'
    if 2 * lenient < n:
        return 'FAIL'
    if adjudicated is None:
        return 'ADJUDICATE'
    return 'PASS' if 2 * (strict + adjudicated) >= n else 'FAIL'


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(k) / n) * (b.count(k) / n) for k in set(a) | set(b))
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def summary(fa, fb, fadj=None):
    A, B = analyze.load_tags(fa), analyze.load_tags(fb)
    ids = sorted(i for b in json.load(open(OUT / 'batches.json'))['A'] for i in b)
    missing = [i for i in ids if i not in A or i not in B]
    if missing:
        sys.exit(f'missing tags for {missing}')
    judged = [i for i in ids if not (A[i]['tag'] in 'DS' and B[i]['tag'] in 'DS')]
    pa, pb = [A[i]['first_error'] == 'P' for i in judged], [B[i]['first_error'] == 'P' for i in judged]
    strict, lenient = sum(x and y for x, y in zip(pa, pb)), sum(x or y for x, y in zip(pa, pb))
    split = [i for i, x, y in zip(judged, pa, pb) if x != y]
    adj = None
    if fadj:
        J = analyze.load_tags(fadj)
        if sorted(J) != split:
            sys.exit(f'adjudication must cover exactly {split}')
        adj = sum(J[i]['first_error'] == 'P' for i in split)
    print(f'cases {len(ids)}, judged {len(judged)} (both D/S: {sorted(set(ids) - set(judged))})')
    print(f'first_error = P: A {sum(pa)}, B {sum(pb)}; strict {strict}, lenient {lenient}; need {len(judged) / 2:g}')
    print(f'kappa (P vs not) {kappa(pa, pb):.2f}; tag agreement {sum(A[i]["tag"] == B[i]["tag"] for i in ids)}/{len(ids)}')
    for n, T in (('A', A), ('B', B)):
        print(f'{n}: tag {dict(Counter(T[i]["tag"] for i in ids).most_common())}  first_error '
              f'{dict(Counter(T[i]["first_error"] for i in ids).most_common())}  reading_kind '
              f'{dict(Counter(T[i].get("reading_kind") or "-" for i in ids if T[i]["first_error"] == "P").most_common())}')
    print(f'disagree on P ({len(split)}): {split}' + (f'; adjudicated P {adj}' if fadj else ''))
    print(f'GATE: {gate(strict, lenient, adj, len(judged))}')


if __name__ == '__main__':
    assert [gate(14, 20, None, 27), gate(5, 13, None, 27), gate(10, 20, None, 27), gate(10, 20, 4, 27),
            gate(10, 20, 3, 27), gate(13, 13, None, 26)] == ['PASS', 'FAIL', 'ADJUDICATE', 'PASS', 'FAIL', 'PASS']
    assert abs(kappa([1, 1, 0, 0], [1, 0, 0, 0]) - 0.5) < 1e-9
    cmd, *rest = sys.argv[1:] or ['']
    if cmd == 'export':
        export()
    elif cmd == 'summary':
        summary(*rest)
    else:
        sys.exit(__doc__)
