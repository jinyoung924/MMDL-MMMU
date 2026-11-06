#!/usr/bin/env python3
"""Audit pinned Geometry3K sources and build a train-only manual-review pool.

No model runs, roles, or training-ready records. Geometry3K val/test supply only
protection fingerprints. Generic short stems never create text-only edges.
Run with the existing vllm Python, -B, for Pillow/numpy/pyarrow.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

sys.dont_write_bytecode = True
import pyarrow as pa
from audit_bmmr import (EVAL_SHA, MMMU_REVISION, EVAL_SUFFIX, file_sha,
                        image_fingerprint, normalize, shingles)

ROOT = Path(__file__).resolve().parents[1]
REVISION = '99e6b5293c7bb4a5eaf2a370e6b213c79ab33ebb'
EXPECTED = {'train': 2101, 'val': 300, 'test': 601}
MIN_SHINGLES = 8
CONTAINMENT = .6
PROTECT_DHASH = 4
GROUP_DHASH = 8
GOALS = {'Angle', 'Length', 'Ratio'}
QUADRILATERALS = {'Parallelogram', 'Rectangle', 'Trapezoid', 'Rhombus', 'Square', 'Quadrilateral'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha_bytes(blob):
    return hashlib.sha256(blob).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def variants(row):
    # Choices are deliberately excluded from text matching: common numeric
    # option lists must not manufacture semantic duplicate edges.
    return list(dict.fromkeys(str(row.get(key, '')).strip()
                             for key in ('problem_text', 'annotat_text')
                             if str(row.get(key, '')).strip()))


def text_features(texts):
    norms = {normalize(text) for text in texts if normalize(text)}
    grams = set().union(*(shingles(text) for text in texts)) if texts else set()
    # Match exact stems only when each exact variant itself is nontrivial.
    exact = {n for n in norms if len(shingles(n)) >= MIN_SHINGLES}
    return {'norms': norms, 'exact': exact, 'grams': grams}


def member_metadata(z, member):
    info = z.getinfo(member)
    return {'member': member, 'uncompressed_bytes': info.file_size,
            'compressed_bytes': info.compress_size, 'crc32': f'{info.CRC:08x}'}


def atomic_output(path, payload, replace_existing):
    if path.exists():
        if path.read_bytes() == payload:
            return
        require(replace_existing, f'Existing output differs; use --replace-existing for this builder output only: {path}')
    path.write_bytes(payload)


class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))
    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i
    def union(self, i, j):
        a, b = self.find(i), self.find(j)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def build(args):
    out = args.out.resolve()
    lock_path = out / 'source_lock.json'
    lock = json.loads(lock_path.read_text())
    require(lock['revision'] == REVISION, 'Unexpected official revision')
    require(lock['candidate_allowed_source_split'] == 'train', 'Non-train candidate policy')
    require({r['path'] for r in lock['files']} == {'train.zip', 'val.zip', 'test.zip'}, 'Unexpected archive list')
    source_checks = []
    archive_specs = {}
    for entry in lock['files']:
        path = args.archive_dir / entry['path']
        require(path.is_file(), f'Missing archive: {path}')
        require(path.stat().st_size == entry['bytes'], f'Source size mismatch: {path.name}')
        digest = file_sha(path)
        require(digest == entry['sha256'], f'Source SHA256 mismatch: {path.name}')
        with path.open('rb') as f:
            h = hashlib.sha1(b'blob ' + str(entry['bytes']).encode() + b'\0')
            for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
                h.update(block)
        require(h.hexdigest() == entry['git_blob_sha1'], f'Git blob mismatch: {path.name}')
        split = path.stem
        require(entry['purpose'] == ('candidate_source' if split == 'train' else 'protection_only'), 'Archive purpose mismatch')
        archive_specs[split] = (path, entry)
        source_checks.append({'archive': str(path), **entry, 'sha256_verified': True, 'git_blob_verified': True})
    print('Verified all three pinned archives', flush=True)

    old_protected_path = ROOT / 'data/diagram_v2/protected_image_index.json'
    old_pool_path = ROOT / 'data/diagram_v2/pool_image_screen.jsonl'
    old_protected = json.loads(old_protected_path.read_text())
    old_pool = read_jsonl(old_pool_path)
    require(len(old_pool) == 657, 'Expected every one of 657 frozen old-pool rows')
    require(len({str(r['id']) for r in old_pool}) == 657, 'Old pool ID duplication')
    unchanged_inputs = {str(p): file_sha(p) for p in [lock_path, old_protected_path, old_pool_path]}
    protected_images = []
    protected_by_bytes = {}
    protected_text = []
    protected_features = []

    def add_image(fp, reference, category, metadata=None):
        digest = fp['bytes_sha256']
        if digest not in protected_by_bytes:
            protected_by_bytes[digest] = len(protected_images)
            protected_images.append({**fp, 'index': len(protected_images), 'references': [], 'categories': [], 'source_members': []})
        record = protected_images[protected_by_bytes[digest]]
        require(record['pixels_sha256'] == fp['pixels_sha256'] and record['dhash64'] == fp['dhash64'], 'Inconsistent fingerprint for identical bytes')
        if reference not in record['references']:
            record['references'].append(reference)
        if category not in record['categories']:
            record['categories'].append(category)
        if metadata and metadata not in record['source_members']:
            record['source_members'].append(metadata)

    def add_text(texts, reference, category, metadata=None):
        f = text_features(texts)
        protected_features.append(f)
        protected_text.append({'index': len(protected_text), 'reference': reference,
                               'category': category,
                               'normalized_variant_sha256': sorted(sha_bytes(n.encode()) for n in f['norms']),
                               'distinct_5word_shingles': len(f['grams']),
                               'nontrivial_exact_variant_count': len(f['exact']),
                               'metadata': metadata or {}})

    for record in old_protected:
        for ref in record['references']:
            add_image({k: record[k] for k in ('bytes_sha256', 'pixels_sha256', 'dhash64', 'width', 'height')},
                      ref, 'existing_MMMU_any_split_or_BMMR_eval')
    old_image_count = 0
    for i, row in enumerate(old_pool):
        require(len(row['image']) == 1, 'Expected single-image old pool')
        for name in row['image']:
            local = args.old_images / name
            require(local.is_file(), f'Old pool image absent: {local}')
            fp = row['image_fingerprints'][name]
            require(sha_bytes(local.read_bytes()) == fp['bytes_sha256'], f'Old pool image bytes changed: {name}')
            add_image(fp, f'FrozenBMMRPool/{i}/{row["id"]}/{name}', 'all_657_frozen_old_pool_images',
                      {'local_path': str(local), 'old_pool_index': i, 'old_pool_id': str(row['id'])})
            old_image_count += 1
        add_text([row['question']], f'FrozenBMMRPool/{i}/{row["id"]}', 'all_657_frozen_old_pool_questions')
    require(old_image_count == 657, 'Failed to protect every old image')
    print('Protected original image index and all 657 frozen pool images', flush=True)

    # Question text from external evaluation sources is read only for overlap.
    # No answer/solution fields are accessed or exported.
    bmmr_eval = args.bmmr_eval
    require(file_sha(bmmr_eval) == EVAL_SHA, 'BMMR evaluation source mismatch')
    csv.field_size_limit(sys.maxsize)
    bmmr_rows = 0
    with bmmr_eval.open(newline='') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            add_text([row['question'].split(EVAL_SUFFIX)[0]], 'BMMR-Eval/' + row['index'], 'BMMR_eval_text')
            bmmr_rows += 1
    unchanged_inputs[str(bmmr_eval)] = EVAL_SHA
    mmmu_counts = Counter()
    cache_files = sorted(args.mmmu_cache.glob(f'*/0.0.0/{MMMU_REVISION}/mmmu-*.arrow'))
    require(bool(cache_files), 'Missing MMMU cache protection sources')
    for path in cache_files:
        split = path.stem.removeprefix('mmmu-').split('-')[0]
        require(split in {'dev', 'validation', 'test'}, f'Unexpected MMMU split {split}')
        with pa.memory_map(str(path), 'r') as source:
            for batch in pa.ipc.open_stream(source):
                for row in batch.select(['id', 'question']).to_pylist():
                    add_text([row['question']], 'MMMU/' + row['id'], 'MMMU_any_split_text')
                    mmmu_counts[split] += 1
    require(dict(mmmu_counts) == {'dev': 150, 'test': 10500, 'validation': 900}, f'MMMU protection counts differ: {mmmu_counts}')

    candidates = []
    candidate_features = []
    candidate_fingerprints = []
    ids_by_split = {}
    geometry_protected_image_count = Counter()
    source_field_counts = Counter()
    for split in ('val', 'test', 'train'):
        path, spec = archive_specs[split]
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            require(all(not n.startswith('/') and '..' not in Path(n).parts for n in names), 'Unsafe archive path')
            data_members = sorted((n for n in names if n.endswith('/data.json')), key=lambda n: int(n.split('/')[1]))
            require(len(data_members) == EXPECTED[split], f'Unexpected {split} row count')
            ids = set()
            for member in data_members:
                member_id = int(member.split('/')[1])
                require(member.split('/')[0] == split, 'Archive/member split mismatch')
                raw = z.read(member)
                row = json.loads(raw)
                require(row['data_type'] == split, f'Wrong embedded split: {member}')
                require(isinstance(row['id'], int) and row['id'] == member_id, f'Wrong embedded ID: {member}')
                require(member_id not in ids, 'Duplicate source ID')
                ids.add(member_id)
                plain = f'{split}/{member_id}/img_diagram.png'
                point = f'{split}/{member_id}/img_diagram_point.png'
                require(plain in names and point in names, 'Missing native diagram variants')
                if split != 'train':
                    # Do not read answer or choices for val/test protection.
                    meta = {'split': split, 'id': member_id, 'archive_sha256': spec['sha256'],
                            'data_member': member, 'data_member_sha256': sha_bytes(raw)}
                    add_text(variants(row), f'Geometry3K/{split}/{member_id}', f'Geometry3K_{split}_text', meta)
                    for image_member in (plain, point):
                        fp = image_fingerprint(z.read(image_member))
                        add_image(fp, f'Geometry3K/{image_member}', f'Geometry3K_{split}_image',
                                  {'archive': str(path), **meta, **member_metadata(z, image_member)})
                        geometry_protected_image_count[split] += 1
                    continue
                choices = row['choices']
                require(isinstance(choices, list) and len(choices) == 4 and all(isinstance(c, str) and c.strip() for c in choices), f'Invalid native four-way choices: {member}')
                require(isinstance(row['answer'], str) and row['answer'] in ('A', 'B', 'C', 'D'), f'Invalid train gold: {member}')
                texts = variants(row)
                require(bool(texts), f'Missing question: {member}')
                annotated = str(row.get('annotat_text', '')).strip()
                stem = annotated or str(row['problem_text']).strip()
                question = stem + '\n' + '\n'.join(f'{letter}. {choice}' for letter, choice in zip('ABCD', choices))
                blob = z.read(plain)
                fp = image_fingerprint(blob)
                image_path = args.train_image_dir / str(member_id) / 'img_diagram.png'
                image_path.parent.mkdir(parents=True, exist_ok=True)
                if image_path.exists():
                    require(sha_bytes(image_path.read_bytes()) == fp['bytes_sha256'], f'Existing image mismatch: {image_path}')
                else:
                    image_path.write_bytes(blob)
                goals = row.get('problem_type_goal', [])
                graph_types = row.get('problem_type_graph', [])
                tags = sorted(set(t for t in graph_types if t in {'Line', 'Triangle', 'Circle'}) |
                              ({'Quadrilateral'} if set(graph_types) & QUADRILATERALS else set()))
                source_field_counts.update(row.keys())
                record = {
                    'index': len(candidates), 'id': f'Geometry3K/train/{member_id}',
                    'source_id': member_id, 'source_split': 'train', 'data_type_verified': 'train',
                    'source_repository': lock['repository'], 'source_revision': REVISION,
                    'source_archive': str(path), 'source_archive_sha256': spec['sha256'],
                    'source_data_member': member, 'source_data_member_sha256': sha_bytes(raw),
                    'source_data_member_metadata': member_metadata(z, member),
                    'source_image_member': plain, 'source_image_member_metadata': member_metadata(z, plain),
                    'alternate_point_image_member_metadata': member_metadata(z, point),
                    'raw_problem_text': row['problem_text'], 'raw_annotat_text': row['annotat_text'],
                    'native_choices': choices, 'question': question,
                    'gold': {'answer': row['answer'], 'choice': choices[ord(row['answer']) - ord('A')],
                             'origin': 'official_original_train_data.json', 'independently_verified': False},
                    'source_metadata': {key: row.get(key) for key in ('source', 'annot_id', 'is_standard', 'comment', 'unit', 'img_width', 'img_height', 'date', 'system')},
                    'source_native_nonchoice_fields': {key: value for key, value in row.items() if key not in {'choices', 'answer', 'detailed_solution', 'problem_text', 'annotat_text'}},
                    'problem_type_goal': goals, 'problem_type_graph': graph_types,
                    'sampling_goal_matches': sorted(set(goals) & GOALS), 'sampling_tags': tags,
                    'priority_for_angle_length_ratio_review': bool(set(goals) & GOALS),
                    'image_path': str(image_path.resolve()), 'image_fingerprint': fp,
                    'ready_for_training': False, 'internal_role': None,
                    'manual_review_required': ['question_and_native_choices', 'independent_gold_verification',
                                               'image_facts_and_semantic_overlap', 'source_answer_leakage_in_picture'],
                }
                candidates.append(record)
                candidate_features.append(text_features(texts))
                candidate_fingerprints.append(fp)
            ids_by_split[split] = ids
        print(f'Processed Geometry3K {split}: {len(ids)} rows', flush=True)
    require(ids_by_split['train'] == set(range(2101)), 'Unexpected native train ID range')
    require(ids_by_split['val'] == set(range(2101, 2401)), 'Unexpected native val ID range')
    require(ids_by_split['test'] == set(range(2401, 3002)), 'Unexpected native test ID range')
    require(not any(ids_by_split[a] & ids_by_split[b] for a,b in [('train','val'),('train','test'),('val','test')]), 'Source split ID intersection')

    protected_exact = defaultdict(set)
    protected_inverted = defaultdict(set)
    for j, features in enumerate(protected_features):
        for norm in features['exact']:
            protected_exact[norm].add(j)
        for gram in features['grams']:
            protected_inverted[gram].add(j)
    protected_hashes = [int(r['dhash64'], 16) for r in protected_images]
    direct = set()
    direct_image = set()
    direct_text = set()
    match_categories = Counter()
    for i, row in enumerate(candidates):
        f, fp = candidate_features[i], candidate_fingerprints[i]
        image_matches = []
        h = int(fp['dhash64'], 16)
        minimum_distance = 65
        nearest_index = None
        for j, (other, oh) in enumerate(zip(protected_images, protected_hashes)):
            methods = []
            distance = (h ^ oh).bit_count()
            if distance < minimum_distance:
                minimum_distance, nearest_index = distance, j
            if fp['bytes_sha256'] == other['bytes_sha256']:
                methods.append('bytes_sha256')
            if fp['pixels_sha256'] == other['pixels_sha256']:
                methods.append('pixels_sha256')
            if distance <= PROTECT_DHASH:
                methods.append('dhash64_hamming_le_4')
            if methods:
                image_matches.append({'protected_image_index': j, 'methods': methods, 'dhash_distance': distance})
                match_categories.update(other['categories'])
        text_indices = defaultdict(set)
        for norm in f['exact']:
            for j in protected_exact.get(norm, ()):
                text_indices[j].add('nontrivial_exact_normalized_stem')
        hits = Counter(j for gram in f['grams'] for j in protected_inverted.get(gram, ()))
        for j, hit in hits.items():
            denominator = min(len(f['grams']), len(protected_features[j]['grams']))
            if hit >= MIN_SHINGLES and hit / max(1, denominator) >= CONTAINMENT:
                text_indices[j].add('5word_shingles_min_8_containment_ge_0.6')
        text_matches = [{'protected_text_index': j, 'methods': sorted(methods),
                         'shared_5word_shingles': hits.get(j, 0),
                         'containment': hits.get(j, 0) / max(1, min(len(f['grams']), len(protected_features[j]['grams'])))}
                        for j, methods in sorted(text_indices.items())]
        row['minimum_protected_dhash_distance'] = minimum_distance
        row['nearest_protected_image_index'] = nearest_index
        row['protection_image_matches'] = image_matches
        row['protection_text_matches'] = text_matches
        if image_matches:
            direct_image.add(i)
        if text_matches:
            direct_text.add(i)
        if image_matches or text_matches:
            direct.add(i)
        if (i + 1) % 250 == 0:
            print(f'Overlap-screened train rows: {i+1}', flush=True)

    uf = UnionFind(len(candidates))
    edges = []
    hashes = [int(f['dhash64'], 16) for f in candidate_fingerprints]
    for i in range(len(candidates)):
        fi, imgi = candidate_features[i], candidate_fingerprints[i]
        for j in range(i):
            fj, imgj = candidate_features[j], candidate_fingerprints[j]
            distance = (hashes[i] ^ hashes[j]).bit_count()
            methods = []
            if imgi['bytes_sha256'] == imgj['bytes_sha256']:
                methods.append('bytes_sha256')
            if imgi['pixels_sha256'] == imgj['pixels_sha256']:
                methods.append('pixels_sha256')
            if distance <= GROUP_DHASH:
                methods.append('dhash64_hamming_le_8')
            exact = bool(fi['exact'] & fj['exact'])
            if exact:
                methods.append('nontrivial_exact_normalized_stem')
            hit = len(fi['grams'] & fj['grams']) if min(len(fi['grams']), len(fj['grams'])) >= MIN_SHINGLES else 0
            containment = hit / max(1, min(len(fi['grams']), len(fj['grams'])))
            if hit >= MIN_SHINGLES and containment >= CONTAINMENT:
                methods.append('5word_shingles_min_8_containment_ge_0.6')
            if methods:
                uf.union(i, j)
                edges.append({'indices': [j, i], 'methods': methods, 'dhash_distance': distance,
                              'shared_5word_shingles': hit, 'containment': containment})
    components = defaultdict(list)
    for i in range(len(candidates)):
        components[uf.find(i)].append(i)
    protected_components = {uf.find(i) for i in direct}
    components_out = []
    decisions = []
    for root, members in sorted(components.items()):
        group = f'Geometry3K/train/group_{root:04d}'
        touches = sorted(set(members) & direct)
        held = root in protected_components
        components_out.append({'group': group, 'size': len(members), 'indices': members,
                               'source_ids': [candidates[i]['source_id'] for i in members],
                               'protected': held, 'directly_protected_indices': touches})
        for i in members:
            row = candidates[i]
            row['group'] = group
            row['group_size'] = len(members)
            row['direct_protection_hold'] = i in direct
            row['group_protection_hold'] = held
            row['eligible_for_manual_review'] = not held
            row['status'] = ('held_direct_protection_overlap' if i in direct else
                             'held_transitive_group_protection' if held else
                             'requires_manual_question_image_gold_and_leakage_review')
            decisions.append({'index': i, 'id': row['id'], 'group': group,
                              'direct_protection_hold': i in direct, 'group_protection_hold': held,
                              'eligible_for_manual_review': not held, 'ready_for_training': False})

    eligible = [r for r in candidates if r['eligible_for_manual_review']]
    eligible_components = [r for r in components_out if not r['protected']]
    group_hist = Counter(c['size'] for c in components_out)
    eligible_hist = Counter(c['size'] for c in eligible_components)
    thresholds = {'image_protection_dhash_hamming_le': PROTECT_DHASH,
                  'within_train_group_dhash_hamming_le': GROUP_DHASH,
                  'text_shingle_words': 5, 'text_min_shared_distinct_shingles': MIN_SHINGLES,
                  'text_containment_ge': CONTAINMENT,
                  'exact_normalized_text_requires_min_distinct_shingles_per_variant': MIN_SHINGLES,
                  'choices_excluded_from_text_matching': True,
                  'protection_propagates_through_transitive_train_groups': True}
    protection = {'schema_version': 'geometry3k_protection_index_v1', 'purpose': 'protection_only',
                  'ready_for_training': False, 'source_revision': REVISION,
                  'images': protected_images, 'texts': protected_text,
                  'text_storage': 'Only normalized question hashes/counts/references, no protected text, answers, solutions, or pixels exported.',
                  'source_protection_counts': {'old_index_unique_images': len(old_protected),
                                               'frozen_old_pool_images_checked': old_image_count,
                                               'Geometry3K_diagram_variants': dict(geometry_protected_image_count),
                                               'BMMR_eval_questions': bmmr_rows, 'MMMU_questions': dict(mmmu_counts)}}
    groups = {'schema_version': 'geometry3k_group_audit_v1', 'source_split': 'train',
              'ready_for_training': False, 'thresholds': thresholds, 'edges': edges,
              'components': components_out, 'decisions': sorted(decisions, key=lambda d: d['index']),
              'component_size_histogram': dict(sorted(group_hist.items())),
              'eligible_component_size_histogram': dict(sorted(eligible_hist.items())),
              'largest_components': [{'group': c['group'], 'size': c['size'], 'protected': c['protected']}
                                     for c in sorted(components_out, key=lambda c: (-c['size'], c['group']))[:20]],
              'transitive_propagation_additional_held_rows': sum(r['group_protection_hold'] and not r['direct_protection_hold'] for r in candidates)}
    overlap_method_rows = defaultdict(set)
    image_category_rows = defaultdict(set)
    text_category_rows = defaultdict(set)
    for row in candidates:
        for match in row['protection_image_matches']:
            for method in match['methods']:
                overlap_method_rows[method].add(row['id'])
            for category in protected_images[match['protected_image_index']]['categories']:
                image_category_rows[category].add(row['id'])
        for match in row['protection_text_matches']:
            text_category_rows[protected_text[match['protected_text_index']]['category']].add(row['id'])
    summary = {'schema_version': 'geometry3k_audit_summary_v1', 'source_revision': REVISION,
               'source_archives_verified': source_checks, 'thresholds': thresholds,
               'native_split_rows_verified': {k: len(v) for k,v in ids_by_split.items()},
               'candidate_rows': len(candidates), 'candidate_source_split': 'train',
               'native_four_way_mc_rows': len(candidates), 'internal_roles_assigned': 0,
               'all_old_657_images_verified': True, 'old_fingerprints_reused_after_actual_bytes_sha256_verification': True, 'protected_unique_images': len(protected_images),
               'protected_question_records': len(protected_text),
               'minimum_protected_dhash_distance_histogram': dict(sorted(Counter(r['minimum_protected_dhash_distance'] for r in candidates).items())),
               'direct_image_protection_rows': len(direct_image), 'direct_text_protection_rows': len(direct_text),
               'direct_any_protection_rows': len(direct),
               'direct_image_hold_rows_by_method': {k: len(v) for k,v in sorted(overlap_method_rows.items())},
               'direct_image_near_only_rows': len(direct_image - {i for i,r in enumerate(candidates) if r['id'] in overlap_method_rows['pixels_sha256'] or r['id'] in overlap_method_rows['bytes_sha256']}),
               'direct_image_hold_rows_by_category': {k: len(v) for k,v in sorted(image_category_rows.items())},
               'direct_text_hold_rows_by_category': {k: len(v) for k,v in sorted(text_category_rows.items())},
               'transitive_additional_hold_rows': groups['transitive_propagation_additional_held_rows'],
               'held_rows_after_group_propagation': len(candidates)-len(eligible),
               'eligible_manual_review_rows': len(eligible), 'within_train_components': len(components_out),
               'eligible_components': len(eligible_components), 'within_train_edges': len(edges),
               'component_size_histogram': groups['component_size_histogram'],
               'eligible_component_size_histogram': groups['eligible_component_size_histogram'],
               'max_one_per_eligible_component': len(eligible_components),
               'sampling_goal_counts_all': dict(Counter(g for r in candidates for g in r['problem_type_goal'])),
               'sampling_goal_counts_eligible': dict(Counter(g for r in eligible for g in r['problem_type_goal'])),
               'sampling_tag_counts_eligible': dict(Counter(g for r in eligible for g in r['sampling_tags'])),
               'eligible_priority_goal_rows': sum(r['priority_for_angle_length_ratio_review'] for r in eligible),
               'eligible_priority_goal_components': len({r['group'] for r in eligible if r['priority_for_angle_length_ratio_review']}),
               'image_overlap_match_counts_by_protection_category': dict(match_categories),
               'image_cache': str(args.train_image_dir.resolve()),
               'image_path_pattern': str(args.train_image_dir.resolve() / '{source_id}' / 'img_diagram.png'),
               'gold_policy': 'Official original train gold preserved for later verification; not independently verified. No evaluation answers/solutions exported. No source gold used for selecting, grouping, or sampling priority.',
               'ready_for_training': False,
               'manual_review_required': True, 'thresholds_relaxed_for_quantity': False,
               'old_source_locks_and_roles_modified': False,
               'input_sha256': unchanged_inputs,
               'limitations': ['dHash and text overlap are conservative review heuristics, not proof of semantic equivalence or non-overlap.',
                               'Transitive grouping may hold many distinct problems because simple diagram shapes can have similar dHash values.',
                               'No image answer-leakage screen or independent gold verification has been performed; every surviving row needs manual review.',
                               'Protected question text is used only in memory to produce protection matches; protected answers, solutions, and pixels are never exported.',
                               'Train image cache is under /tmp; pinned archive/member paths and hashes support reconstruction.']}
    # Fail before output if protected data leaked into candidate/gold records.
    require(len(candidates) == 2101 and all(r['source_split'] == 'train' and r['internal_role'] is None and not r['ready_for_training'] for r in candidates), 'Candidate source/role boundary violation')
    require(all('/val/' not in r['id'] and '/test/' not in r['id'] for r in candidates), 'Protected ID in candidate pool')
    require(all(file_sha(Path(path)) == digest for path,digest in unchanged_inputs.items()), 'An input changed during audit')
    print('Pre-serialization feasibility: ' + json.dumps({key: summary[key] for key in ('candidate_rows', 'direct_image_protection_rows', 'direct_text_protection_rows', 'direct_any_protection_rows', 'transitive_additional_hold_rows', 'eligible_manual_review_rows', 'within_train_components', 'eligible_components', 'minimum_protected_dhash_distance_histogram', 'component_size_histogram')}), flush=True)
    pool_bytes = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in candidates).encode()
    protection_bytes = (json.dumps(protection, ensure_ascii=False, indent=2) + '\n').encode()
    group_bytes = (json.dumps(groups, ensure_ascii=False, indent=2) + '\n').encode()
    outputs = {'review_pool.jsonl': pool_bytes, 'protected_image_index.json': protection_bytes,
               'group_audit.json': group_bytes}
    summary['output_sha256'] = {name: sha_bytes(payload) for name,payload in outputs.items()}
    outputs['audit_summary.json'] = (json.dumps(summary, ensure_ascii=False, indent=2) + '\n').encode()
    for name,payload in outputs.items():
        atomic_output(out / name, payload, args.replace_existing)
    print(json.dumps({key: summary[key] for key in ('candidate_rows','direct_image_protection_rows',
          'direct_text_protection_rows','direct_any_protection_rows','transitive_additional_hold_rows',
          'eligible_manual_review_rows','within_train_components','eligible_components',
          'eligible_priority_goal_rows','eligible_priority_goal_components','image_cache')}, indent=2), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive-dir', type=Path, default=Path('/tmp/geometry3k_audit'))
    p.add_argument('--out', type=Path, default=ROOT/'data/geometry_stability')
    p.add_argument('--train-image-dir', type=Path, default=Path('/tmp/geometry3k_audit/train_images'))
    p.add_argument('--old-images', type=Path, default=Path('/tmp/bmmr_audit/pilot_images'))
    p.add_argument('--bmmr-eval', type=Path, default=Path('/tmp/bmmr_audit/BMMR.tsv'))
    p.add_argument('--mmmu-cache', type=Path, default=Path('/home/leesg17/.cache/huggingface/datasets/MMMU___mmmu'))
    p.add_argument('--replace-existing', action='store_true', help='Replace only the four outputs owned by this builder')
    build(p.parse_args())
