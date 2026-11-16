#!/usr/bin/env python
"""First-error tagging for the next candidate targets (targets/protocol.md); same procedure as music/step0.py.

python targets/tag.py export              # -> targets/{chem,diagrams}/{cases/<id>/, order.txt, batches.json}
python targets/tag.py summary chem        # targets/chem/tags_{A,B}.jsonl [adjudication.jsonl] -> registered rule
python targets/tag.py summary diagrams    # set A counts per kind, agreement with set B on the shared questions
"""
import ast, json, math, random, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'music')]
import analyze  # noqa: E402
import step0  # noqa: E402  (HEAD, TAIL, kappa, summary with the Music rule)

T = ROOT / 'targets'
SETS = {'chem': ('Chemical Structures', None, None), 'diagrams': ('Diagrams', 48, 16)}  # image type, tagged by A, by B


def shown(p):
    r = p['response']
    if len(r) <= step0.HEAD + step0.TAIL:
        return p
    cut = f'\n\n[... {len(r) - step0.HEAD - step0.TAIL:,} characters omitted ...]\n\n'
    return {**p, 'response': r[:step0.HEAD] + cut + r[-step0.TAIL:]}  # TAIL 3000 keeps analyze.looped() exact


def split(ids, size=7):
    n = math.ceil(len(ids) / size)
    return [ids[k::n] for k in range(n)]


def export():
    from datasets import load_dataset
    dirs = [ROOT / f'results/seed{s}' for s in range(5)]
    cfg, runs = analyze.check_comparable(dirs), [analyze.load(d) for d in dirs]
    for name, (kind, n_a, n_b) in SETS.items():
        pick = {}
        for i, p in runs[0].items():
            wrong = [(s, R[i]) for s, R in enumerate(runs) if not R[i]['correct']]
            types = p['img_type'] if isinstance(p['img_type'], list) else ast.literal_eval(p['img_type'])
            if kind in types and wrong:  # finished responses first, then truncated
                pick[i] = sorted(wrong, key=lambda x: (x[1]['truncated'], x[0]))[:2]
        order = sorted(pick)
        random.Random(0).shuffle(order)
        (T / name).mkdir(parents=True, exist_ok=True)
        (T / name / 'order.txt').write_text('\n'.join(order) + '\n')
        a = order[:n_a] if n_a else order
        b = order[:n_b] if n_b else random.Random(1).sample(order, len(order))  # chem: all, in another order
        by_subject = defaultdict(set)
        for i in a:
            by_subject[runs[0][i]['subject']].add(i)
        for subject, want in by_subject.items():
            for r in load_dataset(cfg['data'], subject, split='validation', revision=cfg['data_revision']):
                if r['id'] not in want:
                    continue
                d = T / name / 'cases' / r['id']
                d.mkdir(parents=True, exist_ok=True)
                imgs = []
                for k in range(1, 8):
                    if r.get(f'image_{k}'):
                        r[f'image_{k}'].convert('RGB').save(d / f'image_{k}.png')
                        imgs.append(f'![image {k}](image_{k}.png)')
                seeds, preds = zip(*pick[r['id']])
                (d / 'case.md').write_text(analyze.case_md(r, [shown(p) for p in preds], seeds, imgs, None))
        (T / name / 'batches.json').write_text(json.dumps({'A': split(a), 'B': split(b)}, indent=1))
        print(f'{name}: {len(pick)} with a wrong answer, A tags {len(a)} in {len(split(a))} batches, B tags {len(b)} '
              f'in {len(split(b))}; subjects {dict(Counter(runs[0][i]["subject"] for i in a).most_common())}')


def wilson(k, n, z=1.96):
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * (c - h), 100 * (c + h)


def summary(name):
    out = T / name
    if name == 'chem':  # double-tagged in full: the Music step-0 rule as it is
        step0.OUT = out
        adj = [str(out / 'adjudication.jsonl')] if (out / 'adjudication.jsonl').exists() else []
        return step0.summary(str(out / 'tags_A.jsonl'), str(out / 'tags_B.jsonl'), *adj)
    A, B = analyze.load_tags(out / 'tags_A.jsonl'), analyze.load_tags(out / 'tags_B.jsonl')
    judged = [i for i in sorted(A) if A[i]['tag'] not in ('D', 'S')]
    k = sum(A[i]['first_error'] == 'P' for i in judged)
    lo, hi = wilson(k, len(judged))
    print(f'set A: {len(A)} tagged, judged {len(judged)} (D/S: {sorted(set(A) - set(judged))})')
    print(f'first_error = P: {k}/{len(judged)} = {100 * k / len(judged):.0f} % [{lo:.0f}, {hi:.0f}]')
    print(f'tags {dict(Counter(A[i]["tag"] for i in A).most_common())}  first_error '
          f'{dict(Counter(A[i]["first_error"] for i in A).most_common())}')
    kinds = defaultdict(list)
    for i in judged:
        kinds[A[i]['image_kind'].lower()].append(A[i]['first_error'])
    for kind, v in sorted(kinds.items(), key=lambda x: -len(x[1])):
        print(f'  {kind:34s} n={len(v):2d}  P {v.count("P"):2d}  other {dict(Counter(x for x in v if x != "P"))}')
    both = sorted(set(A) & set(B))
    pa, pb = [A[i]['first_error'] == 'P' for i in both], [B[i]['first_error'] == 'P' for i in both]
    print(f'A vs B on {len(both)}: kappa (P vs not) {step0.kappa(pa, pb):.2f}, P agreement {sum(x == y for x, y in zip(pa, pb))}'
          f'/{len(both)}, tag agreement {sum(A[i]["tag"] == B[i]["tag"] for i in both)}/{len(both)}')


if __name__ == '__main__':
    assert split(list(range(25))) and sorted(sum(split(list(range(25))), [])) == list(range(25)) and len(split(list(range(48)))) == 7
    lo, hi = wilson(5, 10)
    assert 23 < lo < 24 and 76 < hi < 77 and len(shown({'response': 'x' * 20000})['response']) < 9100
    cmd, *rest = sys.argv[1:] or ['']
    if cmd == 'export':
        export()
    elif cmd == 'summary':
        summary(*rest)
    else:
        sys.exit(__doc__)
