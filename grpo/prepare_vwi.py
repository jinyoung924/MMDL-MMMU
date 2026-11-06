#!/usr/bin/env python
"""VisualWebInstruct-verified -> GRPO v3 pool: one image, English, single-number answers, minus MMMU-val overlaps.

The Gemini-verified step-by-step solution of each item is kept as the judge's reference (v3_protocol.md).
"""
import io, json, random, re, sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from grpo import gold_number
from prepare_virl import mmmu_overlap  # same overlap rules as v1/v2
from run_eval import COT_OPEN_SUFFIX

SRC = Path('/home/leesg17/data/vwi_verified')
CJK = re.compile(r'[㐀-鿿぀-ヿ가-힯]')
TARGET = 8000  # ponytail: fixed pool size; one v3 run uses ~2k questions
# Gold must be exactly "[var =] number [short unit]": v3 round 0 showed the looser one-number rule letting
# labels ("R1 is the input resistor."), option answers ("B) 3 L") and inequalities ("a_n < 0") through.
LETTER = r'[^\W\d_\u00b2\u00b3\u00b9\u2070-\u2079]'  # \w counts superscript digits as word chars
NUM_ONLY = re.compile(r'^\s*\$?\s*(?:' + LETTER + r'{1,3}(?:_\{?' + LETTER + r'+\}?)?\s*=\s*)?'
                      r'(-?\d[\d,]*(?:\.\d+)?(?:\s*(?:\\times|×|x)\s*10\^\{?-?\d+\}?)?)'
                      r'\s*[^\d=<>()]{0,15}?\s*\$?\.?\s*$')
OPTIONS = re.compile(r'(?:^|\n)\s*\(?[A-Ea-e][\).]\s')
# v6 (`prepare_vwi.py v6`): only Business / Tech & Eng questions, where MMMU's headroom is (keyword match on the
# question; ponytail: keywords also catch some physics/chemistry, a classifier if purity matters)
V6 = sys.argv[1:] == ['v6']
DOMAINS = {'tech_eng': re.compile(r'circuit|resistor|capacitor|inductor|voltage|transistor|amplifier|beam|stress|strain|truss|'
                                  r'moment of inertia|shear|thermodynamic|enthalpy|entropy|turbine|pump|fluid|pipe|heat transfer|'
                                  r'motor|transformer|power factor|rankine|carnot|gear|torque|logic gate|algorithm|binary'),
           'business': re.compile(r'\bcost|price|profit|revenue|interest rate|demand|supply|tax|investment|depreciation|'
                                  r'dividend|balance sheet|income statement|inventory|cash flow|gdp|inflation|elasticity|bond|'
                                  r'stock|portfolio')}  # tech first: 'supply', 'cost' also appear in circuit problems


def strict_gold(short_answer):
    m = NUM_ONLY.match(short_answer)
    return gold_number(m.group(1)) if m else None


def main():
    text_hit, image_hit = mmmu_overlap()
    files = sorted(SRC.glob('batch_*/*.parquet'))
    random.Random(0).shuffle(files)
    why, pool = Counter(), []
    (SRC / 'images').mkdir(exist_ok=True)
    for f in files:
        t = pq.read_table(f)
        for r in t.to_pylist():
            q = (r['question'] or '').strip()
            dom = next((k for k, d in DOMAINS.items() if d.search(q.lower())), None)
            if V6 and dom is None:
                why['off_domain'] += 1; continue
            gold = strict_gold(r['short_answer'] or '')
            if len(r['images']) != 1:
                why['not_single_image'] += 1; continue
            if CJK.search(q) or CJK.search(r['answer'] or ''):
                why['non_english'] += 1; continue
            if gold is None or len(r['short_answer']) > 40:
                why['not_single_number'] += 1; continue
            if r['difficulty'] < 2:
                why['difficulty_1'] += 1; continue
            if len(OPTIONS.findall(q)) >= 2:
                why['multiple_choice_question'] += 1; continue
            if q.count('<image>') > 1:
                why['image_marker'] += 1; continue
            if text_hit(q):
                why['mmmu_text_overlap'] += 1; continue
            blob = r['images'][0]['bytes']
            if image_hit(blob):
                why['mmmu_image_overlap'] += 1; continue
            path = SRC / 'images' / f"{f.parent.name}_{r['idx']}.png"
            path.write_bytes(blob)
            q = q if '<image>' in q else '<image>\n' + q
            pool.append({'qid': f"vwi-{f.parent.name}-{r['idx']}", 'kind': 'num', 'text': q + '\n' + COT_OPEN_SUFFIX,
                         'question': q.replace('<image>', '').strip(), 'image': str(path), 'gold': gold,
                         'gold_str': r['short_answer'], 'reference': r['answer'], 'difficulty': r['difficulty'], 'domain': dom})
        print(f.name, 'pool', len(pool), dict(why), flush=True)
        if len(pool) >= TARGET and not V6:
            break
    random.Random(0).shuffle(pool)
    name = 'pool_v6_all' if V6 else 'pool_v3'
    with open(HERE / f'data/{name}.jsonl', 'w') as out:
        out.writelines(json.dumps(x, ensure_ascii=False) + '\n' for x in pool)
    (HERE / f'data/{name}_summary.json').write_text(json.dumps({'excluded': why, 'pool': len(pool),
        'domain': Counter(x['domain'] for x in pool),
        'difficulty': Counter(x['difficulty'] for x in pool), 'source_revision': '0e54d1161f62daabb2a13346949b02bb8df5b836'}, indent=1))


if __name__ == '__main__':
    main()
