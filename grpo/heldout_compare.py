#!/usr/bin/env python
"""Held-out pool test analysis (heldout_protocol.md): paired per-item accuracy, bootstrap CI over items.

python grpo/heldout_compare.py v6 r029      # runs/heldout/v6_{base,r029}.jsonl, sets data/heldout/v6_{seen,unseen}.txt
"""
import json, random, sys
from pathlib import Path

G = Path(__file__).resolve().parent


def boot(d, n=10000, seed=0):
    rng, k = random.Random(seed), len(d)
    m = sorted(sum(d[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    return sum(d) / k, m[int(0.025 * n)], m[int(0.975 * n) - 1]


def load(f):
    return {r['qid']: r for r in map(json.loads, open(f))}


def finished_chars(f):
    c = [len(r['text']) for r in map(json.loads, open(f)) if r['finish'] == 'stop']
    return sum(c) / max(1, len(c))


if __name__ == '__main__':
    assert boot([1.0] * 5) == (1.0, 1.0, 1.0)
    pool, tag = sys.argv[1], sys.argv[2]
    f0, f1 = G / f'runs/heldout/{pool}_base.jsonl', G / f'runs/heldout/{pool}_{tag}.jsonl'
    b, t = load(f0), load(f1)
    for s in ('seen', 'unseen'):
        if not (G / f'data/heldout/{pool}_{s}.txt').exists():  # v8 has no seen set
            continue
        ids = [i for i in (G / f'data/heldout/{pool}_{s}.txt').read_text().splitlines() if i in b and i in t]
        acc = lambda r: r['correct'] / r['n']
        tr = lambda r: r['trunc'] / r['n']
        d, lo, hi = boot([100 * (acc(t[i]) - acc(b[i])) for i in ids])
        print(f'{pool} {s:6s} n={len(ids)}  acc {100*sum(acc(b[i]) for i in ids)/len(ids):.1f} -> '
              f'{100*sum(acc(t[i]) for i in ids)/len(ids):.1f}  Δ {d:+.2f} [{lo:+.2f}, {hi:+.2f}]  '
              f'trunc {100*sum(tr(b[i]) for i in ids)/len(ids):.1f} -> {100*sum(tr(t[i]) for i in ids)/len(ids):.1f} %  '
              f'mean tokens {sum(b[i]["tokens"] for i in ids)/len(ids):.0f} -> {sum(t[i]["tokens"] for i in ids)/len(ids):.0f}')
    print(f'finished-response chars (all items): {finished_chars(f0.with_suffix(".rows.jsonl")):.0f} -> '
          f'{finished_chars(f1.with_suffix(".rows.jsonl")):.0f}')
