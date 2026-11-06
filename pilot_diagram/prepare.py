#!/usr/bin/env python3
"""Build the small, inspected pilot from authenticated ORIGINAL TRAIN rows only."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from audit_bmmr import REVISION, TRAIN_SHA, file_sha, image_fingerprint, normalize


def read_rows(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def prepare(source, images, out):
    require(file_sha(source) == TRAIN_SHA, 'Not the authenticated original training source')
    audit = ROOT / 'data/bmmr_audit'
    annotation_path = Path(__file__).with_name('annotations.json')
    annotations = json.loads(annotation_path.read_text())
    items = annotations['items']
    require(len({x['id'] for x in items}) == len(items), 'Duplicate annotation IDs')
    selected = {x['id']: x for x in items}
    screens = read_rows(audit / 'pilot_image_screen.jsonl') + read_rows(audit / 'target_extra_image_screen.jsonl')
    screens = {x['id']: x for x in screens}
    flagged = {x['id'] for x in read_rows(audit / 'text_overlap_flags.jsonl')}
    protected_path = audit / 'protected_image_index.json'
    protected = json.loads(protected_path.read_text())
    protected_bytes = {x['bytes_sha256'] for x in protected}
    protected_pixels = {x['pixels_sha256'] for x in protected}
    protected_dhash = [int(x['dhash64'], 16) for x in protected]
    for prefix in ('pilot', 'target_extra'):
        stats = json.loads((audit / f'{prefix}_image_summary.json').read_text())
        require(stats['protected_image_index_sha256'] == file_sha(protected_path), 'Protection index changed')
    originals = {}
    for line_no, line in enumerate(source.open(), 1):
        raw = json.loads(line)
        if raw['id'] in selected:
            originals[raw['id']] = (line_no, raw)
    require(set(originals) == set(selected), 'Annotation ID absent from original train')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'images').mkdir(exist_ok=True)
    rows = []
    seen_pixels, seen_questions, groups = {}, {}, {}
    for item in items:
        rid = item['id']
        require(rid not in flagged, f'Text/ID overlap: {rid}')
        screen = screens[rid]
        line_no, raw = originals[rid]
        require(screen['source_split'] == 'train' and screen['source_revision'] == REVISION, 'Wrong source split/revision')
        require(screen['source_path'] == 'trainset/bmmr-train-80k.jsonl', 'Wrong source path')
        require(screen['source_line'] == line_no and screen['question'] == raw['conversations'][0]['value'], 'Source text mismatch')
        require(screen['image'] == raw['image'] and len(raw['image']) == 1, 'Image source mismatch')
        require(screen['status'] == 'requires_question_and_annotation_review' and not screen['image_overlap_matches'], 'Overlap/invalid input held')
        require(item['split'] in ('train', 'diagnostic'), 'Invalid experiment split')
        require(item['group'] not in groups or groups[item['group']] == item['split'], 'Skill/source-family group split leakage')
        groups[item['group']] = item['split']
        name = raw['image'][0]
        require(Path(name).name == name, 'Unsafe image name')
        blob = (images / name).read_bytes()
        fp = image_fingerprint(blob)
        require(fp == screen['image_fingerprints'][name], 'Image changed since screening')
        require(fp['bytes_sha256'] not in protected_bytes and fp['pixels_sha256'] not in protected_pixels, 'Exact eval image overlap')
        require(all((int(fp['dhash64'], 16) ^ h).bit_count() > 4 for h in protected_dhash), 'Potential eval image overlap')
        require(fp['pixels_sha256'] not in seen_pixels, 'Duplicate pilot image')
        qnorm = normalize(screen['question'])
        require(qnorm not in seen_questions, 'Duplicate pilot question')
        seen_pixels[fp['pixels_sha256']] = rid
        seen_questions[qnorm] = rid
        require(re.fullmatch('[A-G]', item['answer']) is not None, 'Invalid answer')
        source_answer = re.findall(r'\\boxed\{([A-Z])\}', raw['conversations'][1]['value'])[-1]
        question = re.sub(r'<image(?:\s+\d+)?>', '', screen['question']).strip()
        teacher = '\n\n'.join([item['visual_evidence'], item['rule'], item['solution'], f"Answer: {item['answer']}"])
        dst = out / 'images' / name
        shutil.copyfile(images / name, dst)
        rows.append({
            'id': rid, 'source_split': 'train', 'source_revision': REVISION,
            'source_path': screen['source_path'], 'source_line': line_no, 'source_sha256': TRAIN_SHA,
            'source_question_sha256': hashlib.sha256(screen['question'].encode()).hexdigest(),
            'split': item['split'], 'group': item['group'], 'question': question,
            'image': f'images/{name}', 'image_sha256': fp['bytes_sha256'],
            'image_pixels_sha256': fp['pixels_sha256'], 'answer': item['answer'],
            'teacher_response': teacher, 'answer_only_response': f"Answer: {item['answer']}",
            'source_answer': source_answer, 'source_answer_agrees': source_answer == item['answer'],
            'annotation_version': annotations['annotation_version'],
            'review_status': 'assistant_image_and_solution_reviewed', 'human_verified': False,
            'ready_for_training': item['split'] == 'train',
        })
    # Detect similar images across experiment splits too, not only identical bytes.
    for i, a in enumerate(rows):
        for b in rows[i+1:]:
            if a['split'] != b['split']:
                fa = screens[a['id']]['image_fingerprints'][Path(a['image']).name]
                fb = screens[b['id']]['image_fingerprints'][Path(b['image']).name]
                require((int(fa['dhash64'],16)^int(fb['dhash64'],16)).bit_count() > 4, 'Near-duplicate image across train/diagnostic')
    for split in ('train', 'diagnostic'):
        (out / f'{split}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows if r['split']==split))
    lock = {
        'source_revision': REVISION, 'source_sha256': TRAIN_SHA,
        'annotation_sha256': file_sha(annotation_path), 'protected_index_sha256': file_sha(protected_path),
        'text_overlap_flags_sha256': file_sha(audit / 'text_overlap_flags.jsonl'),
        'files': {f'{s}.jsonl': file_sha(out / f'{s}.jsonl') for s in ('train','diagnostic')},
        'counts': dict(Counter(r['split'] for r in rows)),
        'source_answer_disagreements': [{'id':r['id'],'split':r['split'],'source':r['source_answer'],'reviewed':r['answer']} for r in rows if not r['source_answer_agrees']],
        'selection': 'Input quality and skill relevance chosen before student inference. All original source rows are train. Broad skill families kept within one experimental split.',
        'limitations': ['Small convenience pilot, not a representative efficacy estimate.', 'Same assistant authored and reviewed labels; no human or second-model verification.', 'No detected overlap under text, byte, pixel, and dHash screens; semantic overlap cannot be fully ruled out.', 'Publisher-level source IDs are unavailable in BMMR; group separation is a manual skill/template approximation.'],
    }
    (out / 'dataset_lock.json').write_text(json.dumps(lock, indent=2)+'\n')
    print(json.dumps(lock, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--out', type=Path, default=Path(__file__).parent)
    a = p.parse_args()
    prepare(a.source, a.images, a.out)
