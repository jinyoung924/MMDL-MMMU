#!/usr/bin/env python
"""Round 2 (targets/protocol.md): one adapter for all reading targets, and its MMMU verdict.

python targets/round2.py select              # music round-2 + chem templates + v12 anchors -> grpo/runs/round2/rft_train.jsonl
python targets/round2.py select round3 read_train3   # same for another round and Music training file
python targets/round2.py mc round2           # MC check of grpo/runs/heldout/v7_<tag>.jsonl; exit 1 on a significant loss
python targets/round2.py compare runs/round2_full   # 5 paired seeds: target questions, the rest, adoption verdict
python targets/round2.py compare runs/round3_full round3 music/rerender/ids.txt   # ... without the development questions
python targets/round2.py music runs/round3_music music/rerender/ids.txt    # a Music-only run against the base (exploratory)
"""
import json, random, re, statistics as st, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'grpo'), str(ROOT / 'music')]
import analyze  # noqa: E402
import reading  # noqa: E402

OUT = ROOT / 'grpo/runs/round2/rft_train.jsonl'
CHEM = ROOT / 'targets/chem'


def chem_tasks():
    """Chem tasks to train, by the registered step-1 rule: none if the base scores >= 70 % overall, else the tasks
    the base reads below 90 %. -> (tasks, per-task base accuracy)."""
    per = [json.loads(l) for l in open(CHEM / 'runs/chem_base.jsonl')]
    acc = lambda rs: 100 * sum(r['correct'] / r['n'] for r in rs) / len(rs)
    by = {}
    for r in per:
        by.setdefault(reading.task_of(r['qid']), []).append(r)
    scores = {t: round(acc(rs), 1) for t, rs in by.items()}
    return ([] if acc(per) >= 70 else [t for t, a in scores.items() if a < 90]), {**scores, 'all': round(acc(per), 1)}


def select(name='round2', music_file='read_train2'):
    from grpo import correct
    out = ROOT / f'grpo/runs/{name}/rft_train.jsonl'
    music = [json.loads(l) for l in open(ROOT / f'music/data/{music_file}.jsonl')]
    tasks, scores = chem_tasks()
    chem = [q for q in map(json.loads, open(CHEM / 'data/chem_train.jsonl')) if q['task'] in tasks]
    data = [reading.template_row(q) for q in music + chem]
    assert all(correct(q, d['response'], 'stop') == 1.0 for q, d in zip(music + chem, data))
    anchors = [d for d in map(json.loads, open(ROOT / 'grpo/runs/v12/rft_train.jsonl')) if d.get('replay')]
    print(json.dumps({'music': len(music), 'chem': len(chem), 'chem_tasks': tasks, 'chem_base': scores, 'anchors': len(anchors)}))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in data + anchors))


def mc(tag):
    """MC check as in v12 and Music step 2: 289 held-out MC items, 4 samples; a loss counts if the whole CI is below 0."""
    from heldout_compare import boot, load
    W = r'\bwait\b|\b(double[- ]check|re-?check|verify|let me check|let me verify)'
    h = ROOT / 'grpo/runs/heldout'
    ids = (ROOT / 'grpo/data/heldout/v7_unseen_v12.txt').read_text().split()
    b, t = load(h / 'v7_base.jsonl'), load(h / f'v7_{tag}.jsonl')
    assert all(b[i]['n'] == 4 and t[i]['n'] == 4 for i in ids)

    def style(f):
        rs = [r['text'] for r in map(json.loads, open(f)) if r['qid'] in set(ids) and r['finish'] == 'stop']
        return sum(map(len, rs)) / len(rs), 1000 * sum(len(re.findall(W, x, re.I)) for x in rs) / sum(map(len, rs))
    acc = lambda r: r['correct'] / r['n']
    d, lo, hi = boot([100 * (acc(t[i]) - acc(b[i])) for i in ids])
    (bc, bw), (tc, tw) = style(h / 'v7_base.rows.jsonl'), style(h / f'v7_{tag}.rows.jsonl')
    print(f'MC check n={len(ids)}  acc {100 * sum(acc(b[i]) for i in ids) / len(ids):.1f} -> '
          f'{100 * sum(acc(t[i]) for i in ids) / len(ids):.1f}  Δ {d:+.2f} [{lo:+.2f}, {hi:+.2f}]  '
          f'trunc {100 * sum(b[i]["trunc"] for i in ids) / (4 * len(ids)):.1f} -> {100 * sum(t[i]["trunc"] for i in ids) / (4 * len(ids)):.1f} %  '
          f'finished chars {bc:.0f} -> {tc:.0f}  wait+check/1k {bw:.2f} -> {tw:.2f}')
    sys.exit(1 if hi < 0 else 0)


def music(run, dev_file):
    """A Music-only run of the frozen pipeline (run_eval.py --subjects Music) against the base's Music answers:
    all 30 questions and the 25 outside the paired check. Exploratory: it cannot lead to adoption."""
    base = [analyze.load(ROOT / f'results/seed{s}') for s in range(5)]
    tuned = [analyze.load(Path(run) / f'seed{s}') for s in range(5)]
    ids = sorted(tuned[0])
    assert all(base[0][i]['subject'] == 'Music' for i in ids) and len(ids) == 30
    dev = {l.strip().split('-', 1)[1] for l in open(dev_file)}
    d = {i: st.mean(t[i]['correct'] for t in tuned) - st.mean(b[i]['correct'] for b in base) for i in ids}
    rng = random.Random(0)
    for name, qs in (('Music, all 30', ids), ('Music, 25 outside the paired check', [i for i in ids if i not in dev]),
                     ('the 5 paired-check questions', [i for i in ids if i in dev])):
        boots = sorted(st.mean(d[rng.choice(qs)] for _ in qs) for _ in range(2000))
        acc = lambda runs: 100 * st.mean(st.mean(r[i]['correct'] for i in qs) for r in runs)
        print(f'   {name:36s} n={len(qs):2d}  base {acc(base):5.1f} -> tuned {acc(tuned):5.1f}  Δ {100 * st.mean(d[i] for i in qs):+6.2f} '
              f'[{100 * boots[50]:+.2f}, {100 * boots[1949]:+.2f}]')
    print('   per seed  base ' + ' '.join(f'{100 * st.mean(b[i]["correct"] for i in ids):.1f}' for b in base)
          + '  tuned ' + ' '.join(f'{100 * st.mean(t[i]["correct"] for i in ids):.1f}' for t in tuned))
    tr = lambda runs: 100 * st.mean(r[i]['truncated'] for r in runs for i in ids)
    print(f'   truncated  base {tr(base):.1f} % -> tuned {tr(tuned):.1f} %')


def verdict(target, other, overall):
    """(Δ, lo, hi) triples -> the three registered statements."""
    return {'primary (target questions, CI low > 0)': target[1] > 0,
            'guard (other questions, CI not wholly below 0)': other[2] >= 0,
            'adopt (overall Δ >= 0 and guard holds)': overall[0] >= 0 and other[2] >= 0}


def compare(run, name='round2', dev_file=None, reps=2000):
    """dev_file: ids of MMMU questions that were looked at while the training data was designed (the paired check);
    they stay in the reported Music row but are left out of the target group that the primary criterion uses."""
    base = [analyze.load(ROOT / f'results/seed{s}') for s in range(5)]
    tuned = [analyze.load(Path(run) / f'seed{s}') for s in range(5)]
    ids = sorted(base[0])
    d = {i: st.mean(t[i]['correct'] for t in tuned) - st.mean(b[i]['correct'] for b in base) for i in ids}
    types = lambda p: p['img_type'] if isinstance(p['img_type'], list) else json.loads(p['img_type'].replace("'", '"'))
    music = [i for i in ids if base[0][i]['subject'] == 'Music']
    chem = [i for i in ids if 'Chemical Structures' in types(base[0][i])]
    train = ROOT / f'grpo/runs/{name}/rft_train.jsonl'
    with_chem = train.exists() and any(l.startswith('{"qid": "chem-') for l in open(train))
    dev = {l.strip().split('-', 1)[1] for l in open(dev_file)} if dev_file else set()
    target = sorted((set(music) | set(chem if with_chem else [])) - dev)
    other = [i for i in ids if i not in set(target) | dev]  # the development questions belong to neither group
    rng = random.Random(0)

    def ci(qs):
        boots = sorted(st.mean(d[rng.choice(qs)] for _ in qs) for _ in range(reps))
        return 100 * st.mean(d[i] for i in qs), 100 * boots[int(0.025 * reps)], 100 * boots[int(0.975 * reps)]
    rows = {'all': ci(ids), 'target questions': ci(target), 'Music': ci(music), 'Chemical Structures': ci(chem), 'other questions': ci(other)}
    n = {'all': len(ids), 'target questions': len(target), 'Music': len(music), 'Chemical Structures': len(chem), 'other questions': len(other)}
    for k, (m, lo, hi) in rows.items():
        print(f'   Δacc {k:22s} n={n[k]:3d}  {m:+6.2f} pts  95% CI [{lo:+.2f}, {hi:+.2f}]')
    print(f'   chem trained: {with_chem}; development questions left out of the target group: {len(dev)}; base {100 * st.mean(st.mean(b[i]["correct"] for i in ids) for b in base):.2f}, '
          f'tuned {100 * st.mean(st.mean(t[i]["correct"] for i in ids) for t in tuned):.2f}')
    for k, v in verdict(rows['target questions'], rows['other questions'], rows['all']).items():
        print(f'   {k}: {"YES" if v else "NO"}')


if __name__ == '__main__':
    assert list(verdict((2, 0.5, 4), (-0.1, -1, 1), (0.1, -1, 1)).values()) == [True, True, True]
    assert list(verdict((2, -0.5, 4), (-2, -3, -1), (0.1, -1, 1)).values()) == [False, False, False]
    assert list(verdict((2, 0.5, 4), (-0.3, -1, 1), (-0.1, -1, 1)).values()) == [True, True, False]
    cmd, *rest = sys.argv[1:] or ['']
    {'select': select, 'mc': mc, 'compare': compare, 'music': music}.get(cmd, lambda *a: sys.exit(__doc__))(*rest)
