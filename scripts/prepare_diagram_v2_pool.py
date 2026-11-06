"""Build a train-only, answer-blind REVIEW pool; protect every cached MMMU split."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import re

import pyarrow as pa

from audit_bmmr import (REVISION, MMMU_REVISION, TRAIN_SHA, CJK, SOLUTION_CUE,
                        file_sha, normalize, shingles, image_fingerprint, dump)

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT/'data/bmmr_audit'
OUT = ROOT/'data/diagram_v2'
SOURCE = Path('/tmp/bmmr_audit/bmmr-train-80k.jsonl')
CACHE = Path('/home/leesg17/.cache/huggingface/datasets/MMMU___mmmu')


def main():
    assert file_sha(SOURCE) == TRAIN_SHA
    OUT.mkdir(exist_ok=True)
    assert not (OUT/'summary.json').exists(), 'Do not overwrite a frozen review pool'
    protected_images = {r['bytes_sha256']:r for r in json.loads((OLD/'protected_image_index.json').read_text())}
    exact = defaultdict(set)
    inverted = defaultdict(set)
    grams_by_ref = {}
    counts = Counter()
    for path in sorted(CACHE.glob(f'*/0.0.0/{MMMU_REVISION}/mmmu-*.arrow')):
        split = path.stem.removeprefix('mmmu-').split('-')[0]
        assert split in ('dev','validation','test')
        with pa.memory_map(str(path),'r') as source:
            for batch in pa.ipc.open_stream(source):
                for row in batch.to_pylist():
                    counts[split] += 1
                    ref = 'MMMU/'+row['id']
                    exact[normalize(row['question'])].add(ref)
                    grams = shingles(row['question'])
                    grams_by_ref[ref] = grams
                    for gram in grams: inverted[gram].add(ref)
                    for k in range(1,8):
                        img = row[f'image_{k}']
                        if not img: continue
                        blob=img['bytes']; assert blob
                        digest=hashlib.sha256(blob).hexdigest()
                        if digest not in protected_images:
                            protected_images[digest] = dict(image_fingerprint(blob),references=[])
                        image_ref=ref+f'/image_{k}'
                        if image_ref not in protected_images[digest]['references']:
                            protected_images[digest]['references'].append(image_ref)
        print('Indexed',path.parent.parent.parent.name,split,flush=True)
    assert dict(counts)=={'dev':150,'test':10500,'validation':900},counts
    dump(OUT/'protected_image_index.json',list(protected_images.values()))
    old_flags={r['id'] for r in map(json.loads,(OLD/'text_overlap_flags.jsonl').read_text().splitlines())}
    prior_ids={r['id'] for r in json.loads((ROOT/'pilot_diagram/annotations.json').read_text())['items']}
    stats=Counter(); candidates=[];held=[]
    for n,line in enumerate(SOURCE.open(),1):
        r=json.loads(line);q=r['conversations'][0]['value']
        if r['id'] in old_flags or len(r['image'])!=1 or CJK.search(q) or len(q)<50 or SOLUTION_CUE.search(q):continue
        # Require three distinct option labels; no filtering on the source assistant's answer.
        labels=set(re.findall(r'(?:\(([A-H])\)|(?:^|\s)([A-H])[.:])',q))
        letters={a or b for a,b in labels}
        if not {'A','B','C'}.issubset(letters):continue
        if len(re.findall('[A-Za-z]{3,}',re.sub(r'<image.*?>',' ',q)))<3:continue
        stats['format_candidates']+=1
        refs=set(exact.get(normalize(q),()))
        grams=shingles(q)
        hits=Counter(ref for g in grams for ref in inverted.get(g,()))
        for ref,hit in hits.items():
            if hit>=8 and hit/min(len(grams),len(grams_by_ref[ref]))>=.8:refs.add(ref)
        if refs:
            held.append({'id':r['id'],'reason':'MMMU_any_split_text_overlap','references':sorted(refs)})
            continue
        candidates.append({'id':r['id'],'source_line':n,'source_split':'train',
            'source_path':'trainset/bmmr-train-80k.jsonl','source_revision':REVISION,
            'source_sha256':TRAIN_SHA,'question':q,'image':r['image'],
            'previously_annotated':r['id'] in prior_ids,
            'ready_for_training':False,'status':'requires_image_and_semantic_review'})
    random.Random(20261028).shuffle(candidates)
    # Retain duplicates in a separate list; never distribute them across roles.
    seen_images=set();seen_questions=set();unique=[]
    for r in candidates:
        q=normalize(r['question'])
        if q in seen_questions or any(im in seen_images for im in r['image']):
            held.append({'id':r['id'],'reason':'repeated_candidate_question_or_image'})
            continue
        seen_images.update(r['image']);seen_questions.add(q);unique.append(r)
    (OUT/'candidates.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in unique))
    (OUT/'held_text.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in held))
    summary={'source_revision':REVISION,'train_sha256':TRAIN_SHA,'protected_mmmu_counts':dict(counts),
        'protected_unique_image_bytes':len(protected_images),'counts':dict(stats),'unique_candidates':len(unique),
        'held_text_or_internal_duplicates':len(held),'candidate_sha256':file_sha(OUT/'candidates.jsonl'),
        'protected_image_index_sha256':file_sha(OUT/'protected_image_index.json'),
        'prior_audit_summary_sha256':file_sha(OLD/'summary.json'),
        'ready_for_training':False,'limitations':['Candidate format is heuristic; manual question/image review required.',
        'No assistant answer used in candidate selection or exported to reviewers.',
        'Exact/shingle/hash checks cannot rule out semantic overlap.']}
    dump(OUT/'summary.json',summary)
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__': main()
