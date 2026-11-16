#!/usr/bin/env python
"""Why does the learned reading not carry over to MMMU? Same content, two appearances (diagnostic, MMMU val only read).

Five MMMU Music questions whose content is one or two whole notes (types the adapters were trained on) are asked
twice: with the original scanned image, and with the same notes re-drawn by the generator's renderer.
python music/rerender_check.py build     # -> music/rerender/pool.jsonl, images, ids
python music/rerender_check.py report    # after grpo.py screen for base / round 1 / round 2 / ... (see the run log)
python music/rerender_check.py gate round3   # exit 1 unless that model answers >= 70 % of the scan items right
"""
import json, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'music')]
import analyze, reading  # noqa: E402

OUT = ROOT / 'music/rerender'
H = 'X:1\nL:1/1\nK:{} clef={}\n{} |]\n'
# question -> (ABC of what the scan shows, verified in step 0 and by eye; note names a correct reading must state)
ITEMS = {'validation_Music_3': (H.format('C', 'bass', 'E,, ^F,'), ['E2', 'F♯3']),
         'validation_Music_15': (H.format('C', 'alto', 'C,'), ['C3']),
         'validation_Music_25': (H.format('C', 'treble', "_b c'"), ['B♭5', 'C6']),
         'validation_Music_26': (H.format('C', 'treble', '_A'), ['A♭']),
         'validation_Music_28': (H.format('Bb', 'treble', 'B, _A'), ['B♭3', 'A♭4'])}


def build():
    preds, draw, rng, rows = analyze.load(ROOT / 'results/seed0'), reading.draw_music(), random.Random(0), []
    (OUT / 'img').mkdir(parents=True, exist_ok=True)
    for qid, (abc, names) in ITEMS.items():
        p = preds[qid]
        assert p['prompt'].count('<image 1>') == 1 and '<image 2>' not in p['prompt']
        f = OUT / 'img' / f'{qid}.png'
        draw(abc, reading.TEST_FONT, rng).save(f)
        for kind, img in (('scan', ROOT / f'music/step0/cases/{qid}/image_1.png'), ('redrawn', f)):
            rows.append({'qid': f'{kind}-{qid}', 'kind': 'mc', 'image': str(img), 'gold': p['gold'],
                         'text': p['prompt'].replace('<image 1>', '<image>'), 'abc': abc, 'names': names})
    (OUT / 'pool.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    (OUT / 'ids.txt').write_text(''.join(r['qid'] + '\n' for r in rows))
    print(f'{len(rows)} items -> {OUT / "pool.jsonl"}')


def report():
    pool = {r['qid']: r for r in map(json.loads, open(OUT / 'pool.jsonl'))}
    print(f'{"model":8s} {"image":8s}  answer right   reading right (all note names stated)   per question: answer/reading of samples')
    for model in sorted(f.name[:-len('.rows.jsonl')] for f in OUT.glob('*.rows.jsonl')):
        rows = [json.loads(l) for l in open(OUT / f'{model}.rows.jsonl')]
        for kind in ('scan', 'redrawn'):
            rs = [r for r in rows if r['qid'].startswith(kind)]
            read = lambda r: all(n in r['text'] for n in pool[r['qid']]['names'])
            per = '  '.join(f"{q.split('_')[-1]}:{sum(r['correct'] for r in rs if r['qid'].endswith(q)):.0f}/{sum(read(r) for r in rs if r['qid'].endswith(q))}"
                            f"/{sum(r['qid'].endswith(q) for r in rs)}" for q in ITEMS)
            print(f'{model:8s} {kind:8s}  {100 * sum(r["correct"] for r in rs) / len(rs):5.1f} %        '
                  f'{100 * sum(map(read, rs)) / len(rs):5.1f} %                              {per}')


def gate(model):
    rs = [json.loads(l) for l in open(OUT / f'{model}.rows.jsonl') if '"scan-' in l]
    acc = 100 * sum(r['correct'] for r in rs) / len(rs)
    print(f'paired check, {model}: {acc:.1f} % of {len(rs)} answers right on the scanned images (needed 70 %)')
    sys.exit(0 if acc >= 70 else 1)


if __name__ == '__main__':
    cmd, *rest = sys.argv[1:] or ['']
    {'build': build, 'report': report, 'gate': gate}.get(cmd, lambda *a: sys.exit(__doc__))(*rest)
