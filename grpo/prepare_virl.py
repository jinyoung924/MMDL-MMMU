#!/usr/bin/env python
"""ViRL39K single-image multiple-choice items -> GRPO pool, minus MMMU-val overlaps.

Overlap rules are the BMMR audit's (scripts/audit_bmmr.py): normalized exact question,
5-gram shingle overlap (>=8 shared and >=80%), image pixel SHA-256, dHash Hamming <= 4.
Every flag is excluded; nothing is reviewed by hand.
"""
import json, random, re, sys, zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from audit_bmmr import image_fingerprint, normalize, shingles
from run_eval import COT_MC_SUFFIX, DATA_REV, SUBJECTS

SRC = Path('/home/leesg17/data/virl39k')
OUT = Path(__file__).resolve().parent / 'data'
MATH_SHARE = 0.3  # ponytail: fixed category cap; grade-school math is the bulk of ViRL39K and least MMMU-like


def mmmu_overlap():
    """(text_hit, image_hit) predicates against all 900 MMMU-val questions and their images."""
    from datasets import load_dataset
    mmmu = [q for s in SUBJECTS for q in load_dataset('MMMU/MMMU', s, split='validation',
            revision=DATA_REV).select_columns(['question'])['question']]
    assert len(mmmu) == 900
    exact, inv, grams = {normalize(q) for q in mmmu}, defaultdict(set), []
    for j, q in enumerate(mmmu):
        grams.append(shingles(q))
        for g in grams[-1]:
            inv[g].add(j)

    def text_hit(q):
        if normalize(q) in exact:
            return True
        g = shingles(q)
        hits = Counter(j for x in g for j in inv.get(x, ()))
        return any(c >= 8 and c / min(len(g), len(grams[j])) >= .8 for j, c in hits.items())

    prot = [x for x in json.loads((ROOT / 'data/bmmr_audit/protected_image_index.json').read_text())
            if any(r.startswith('MMMU/') for r in x['references'])]
    px = {x['pixels_sha256'] for x in prot}
    dh = np.array([int(x['dhash64'], 16) for x in prot], dtype=np.uint64)

    def image_hit(blob):
        fp = image_fingerprint(blob)
        x = np.bitwise_xor(dh, np.uint64(int(fp['dhash64'], 16)))
        near = np.unpackbits(x.view(np.uint8).reshape(-1, 8), axis=1).sum(1) <= 4
        return fp['pixels_sha256'] in px or bool(near.any())

    return text_hit, image_hit


def main():
    text_hit, image_hit = mmmu_overlap()
    df = pd.read_parquet(SRC / '39Krelease.parquet')
    why, keep = Counter(), []
    zf = zipfile.ZipFile(SRC / 'images.zip')
    for r in df.itertuples():
        m = re.fullmatch(r'\\boxed\{\(?([A-H])\)?\}', r.answer.strip())
        letters = set(re.findall(r'(?:^|\n)\s*\(?([A-H])[\)\.:]', r.question))
        if not m or m[1] not in letters or len(letters) < 2:
            why['not_letter_mc'] += 1; continue
        if len(r.image) != 1 or r.question.count('<image>') > 1:
            why['not_single_image'] += 1; continue
        if r.PassRate_32BTrained >= 1.0:  # smoke test: these were 4/4 for our base, i.e. no GRPO signal
            why['solved_by_32B_trained'] += 1; continue
        if 'boxed' in r.question:
            why['boxed_instruction'] += 1; continue
        if text_hit(r.question):
            why['mmmu_text_overlap'] += 1; continue
        blob = zf.read(r.image[0])
        if image_hit(blob):
            why['mmmu_image_overlap'] += 1; continue
        q = r.question.strip()
        q = q if '<image>' in q else '<image>\n' + q
        keep.append({'qid': r.qid, 'text': q + '\n' + COT_MC_SUFFIX, 'image': r.image[0],
                     'gold': m[1], 'category': r.category, 'source': r.source,
                     'pass32': r.PassRate_32BTrained, 'pass7': r.PassRate_7BBase})
    print('excluded', dict(why), 'kept', len(keep))

    rng = random.Random(0)
    is_math = lambda x: 'Math' in x['category'] or 'Geometric' in x['category']
    math, rest = [x for x in keep if is_math(x)], [x for x in keep if not is_math(x)]
    rng.shuffle(math)
    pool = rest + math[:int(len(rest) * MATH_SHARE / (1 - MATH_SHARE))]
    rng.shuffle(pool)
    print('pool', len(pool), Counter(x['category'] for x in pool).most_common())

    for x in pool:
        zf.extract(x['image'], SRC)
        x['image'] = str(SRC / x['image'])
    OUT.mkdir(exist_ok=True)
    with open(OUT / 'pool.jsonl', 'w') as f:
        f.writelines(json.dumps(x, ensure_ascii=False) + '\n' for x in pool)
    (OUT / 'pool_summary.json').write_text(json.dumps({'excluded': why, 'kept': len(keep),
        'pool': len(pool), 'categories': Counter(x['category'] for x in pool),
        'virl_revision': '812ec617dea4bc8a4e751663b88e4ebb7de4d00e'}, indent=1))


if __name__ == '__main__':
    main()
