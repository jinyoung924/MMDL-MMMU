"""Read-only analysis of existing five-seed MMMU predictions; outputs are evaluation-only."""
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'analysis/stability'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def valid_correct(p):
    return bool(p['correct'] and not p['fallback_guess'])


def measures(ps):
    return {'n': len(ps), 'official_correct': sum(p['correct'] for p in ps),
            'correct_excluding_random_fallback': sum(valid_correct(p) for p in ps),
            'truncated': sum(p['truncated'] for p in ps),
            'fallback': sum(p['fallback_guess'] for p in ps),
            'median_response_characters': statistics.median(len(p['response']) for p in ps) if ps else None}


def main():
    configs, runs, provenance = [], [], []
    for seed in range(5):
        folder = ROOT / f'results/seed{seed}'
        configs.append(json.loads((folder / 'scores.json').read_text())['config'])
        rows = list(map(json.loads, (folder / 'predictions.jsonl').read_text().splitlines()))
        run = {p['id']: p for p in rows}
        assert len(run) == len(rows) == 900
        assert configs[-1]['seed'] == seed
        runs.append(run)
        provenance.append({'seed': seed, 'predictions_sha256': sha(folder / 'predictions.jsonl'),
                           'scores_sha256': sha(folder / 'scores.json')})
    assert all(set(r) == set(runs[0]) for r in runs)
    assert all(all(c.get(k) == configs[0].get(k) for k in set(c) | set(configs[0])
                   if k not in ('seed', 'out')) for c in configs)
    ids = sorted(runs[0])
    for i in ids:
        assert all(all(r[i].get(k) == runs[0][i].get(k) for k in
                       ('gold', 'prompt', 'subject', 'subfield', 'img_type', 'topic_difficulty')) for r in runs)
    official = {i: sum(r[i]['correct'] for r in runs) for i in ids}
    observed = {i: sum(valid_correct(r[i]) for r in runs) for i in ids}
    groups = {}
    for label, ks in [('zero', {0}), ('priority', {1, 2, 3}), ('near', {4}), ('stable', {5})]:
        selected = [i for i in ids if observed[i] in ks]
        ps = [r[i] for r in runs for i in selected]
        groups[label] = {'questions': len(selected), 'all': measures(ps),
                         'correct': measures([p for p in ps if valid_correct(p)]),
                         'wrong': measures([p for p in ps if not valid_correct(p)])}
    axes = {}
    paired_lengths = []
    paired_complete_lengths = []
    for i in ids:
        if not 1 <= observed[i] <= 3:
            continue
        correct = [r[i] for r in runs if valid_correct(r[i])]
        wrong = [r[i] for r in runs if not valid_correct(r[i])]
        paired_lengths.append(statistics.mean(len(p['response']) for p in wrong)
                              - statistics.mean(len(p['response']) for p in correct))
        correct = [p for p in correct if not p['truncated']]
        wrong = [p for p in wrong if not p['truncated'] and not p['fallback_guess']]
        if correct and wrong:
            paired_complete_lengths.append(statistics.mean(len(p['response']) for p in wrong)
                                           - statistics.mean(len(p['response']) for p in correct))
    for field in ('subject', 'subfield', 'img_type', 'topic_difficulty'):
        counts = defaultdict(Counter)
        for i in ids:
            values = runs[0][i].get(field)
            if not isinstance(values, list):
                values = [values]
            for value in values:
                counts[str(value)][observed[i]] += 1
        axes[field] = sorted([{'name': name, 'n': sum(c.values()),
                                'histogram': {str(k): c[k] for k in range(6)},
                                'priority': sum(c[k] for k in (1, 2, 3))}
                               for name, c in counts.items()], key=lambda r: (-r['priority'], r['name']))
    # Replay a cheap screening policy on already available data. This is policy design,
    # not an independent accuracy estimate, and cannot predict the train cohort's recall.
    mixed = [i for i in ids if valid_correct(runs[0][i]) != valid_correct(runs[1][i])]
    audits = []
    for outcome in (False, True):
        pool = [i for i in ids if all(valid_correct(r[i]) == outcome for r in runs[:2])]
        pool.sort(key=lambda i: hashlib.sha256(('stability-audit-v1:' + i).encode()).hexdigest())
        audits.extend(pool[:math.ceil(.2 * len(pool))])
    target = {i for i in ids if 1 <= observed[i] <= 3}
    advanced = set(mixed + audits)
    replay = {'initial_responses': 1800, 'additional_responses': 3 * len(advanced),
              'full_five_seed_responses': 4500, 'mixed_after_two': len(mixed),
              'audit_questions': len(audits), 'all_priority_questions': len(target),
              'priority_captured_without_audit': len(target & set(mixed)),
              'priority_captured_with_audit': len(target & advanced),
              'priority_missed': len(target - advanced),
              'interpretation': 'Retrospective cost/coverage tradeoff on MMMU only; never labels unadvanced items stable.'}
    # Pair success and failure within the same question; find descriptive stable comparators.
    pairs = []
    for subject in axes['subject'][:6]:
        choices = [i for i in ids if i in target and runs[0][i]['subject'] == subject['name']
                   and any(valid_correct(r[i]) and not r[i]['truncated'] for r in runs)]
        choices.sort(key=lambda i: hashlib.sha256(('review-v1:' + i).encode()).hexdigest())
        for i in choices[:2]:
            p = runs[0][i]
            correct = next(s for s in range(5) if valid_correct(runs[s][i]) and not runs[s][i]['truncated'])
            wrong = min((s for s in range(5) if not valid_correct(runs[s][i])),
                        key=lambda s: (runs[s][i]['truncated'], runs[s][i]['fallback_guess'], s))
            controls = [j for j in ids if observed[j] == 5 and runs[0][j]['subject'] == p['subject']]
            controls.sort(key=lambda j: (-sum(runs[0][j].get(k) == p.get(k) for k in
                                              ('subfield', 'img_type', 'topic_difficulty')), j))
            pairs.append({'id': i, 'subject': p['subject'], 'success_seed': correct, 'failure_seed': wrong,
                          'observed_correct': observed[i], 'stable_comparator': controls[0] if controls else None,
                          'role': 'evaluation_diagnosis_only', 'ready_for_training': False,
                          'review_status': 'pending_image_and_rationale_review'})
    summary = {'scope': 'Existing MMMU validation diagnosis; NEVER training or teacher targets.',
               'script_sha256': sha(Path(__file__)), 'sources': provenance,
               'official_histogram': dict(sorted(Counter(official.values()).items())),
               'excluding_random_fallback_histogram': dict(sorted(Counter(observed.values()).items())),
               'groups_excluding_random_fallback': groups, 'axes_excluding_random_fallback': axes,
               'within_question_length_association': {
                   'unit': 'mean wrong response characters minus mean correct response characters per question',
                   'all_priority_questions': len(paired_lengths),
                   'median_difference': statistics.median(paired_lengths),
                   'questions_where_wrong_is_longer': sum(x > 0 for x in paired_lengths),
                   'both_complete_subset_questions': len(paired_complete_lengths),
                   'both_complete_median_difference': statistics.median(paired_complete_lengths),
                   'both_complete_wrong_is_longer': sum(x > 0 for x in paired_complete_lengths),
                   'interpretation': 'Descriptive association, not an intervention on length; complete-only subset is selected.'},
               'staged_screen_replay': replay,
               'limitations': ['Correct outputs may still contain invalid reasoning.',
                              'Length/truncation associations do not establish causes.',
                              'Prior failure tags were selected from a different population.',
                              'Five observed trials do not establish true success probability 0 or 1.',
                              'Repeatedly inspected validation is exploratory, not a fresh confirmation set.']}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    (OUT / 'review_pairs.jsonl').write_text(''.join(json.dumps(p, ensure_ascii=False) + '\n' for p in pairs))
    (OUT / 'question_index.jsonl').write_text(''.join(json.dumps({
        'id': i, 'subject': runs[0][i]['subject'], 'official_correct': official[i],
        'correct_excluding_random_fallback': observed[i], 'role': 'evaluation_diagnosis_only',
        'ready_for_training': False,
        'success_seeds': [s for s in range(5) if valid_correct(runs[s][i])],
        'failure_seeds': [s for s in range(5) if not valid_correct(runs[s][i])],
    }, ensure_ascii=False) + '\n' for i in ids))
    print(json.dumps({'histogram': summary['excluding_random_fallback_histogram'],
                      'groups': groups, 'replay': replay, 'review_pairs': len(pairs)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
