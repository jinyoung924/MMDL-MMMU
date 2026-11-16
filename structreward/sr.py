#!/usr/bin/env python
"""StructReward replication (structreward/protocol.md; paper arXiv 2608.08326 v2).

python structreward/sr.py build              # VisualPRM400K-v1.1-Raw -> data/{sft,pool_rl,heldout}.jsonl, grpo/runs/sr_sft/rft_train.jsonl
python structreward/sr.py reward RUN ROUND [steps]   # rewrite 'reward' in grpo/RUN/rounds/rROUND.jsonl with the gated reward, eq. (10)
python structreward/sr.py aux RUN ROUND      # judgment / choice examples from the same rollouts -> rROUND.aux.jsonl
python structreward/sr.py heldout TAG        # runs/heldout_{base,TAG}.jsonl: accuracy vs base, format rate (gate: >= 80 %)
python structreward/sr.py prep_own / select_own   # stage A2: the base model's own solutions as SFT targets (Amendment 1)
python structreward/sr.py selfcheck
Run from the repo root in the `vllm-train` env.
"""
import hashlib, json, os, random, re, sys, zipfile
from collections import Counter, defaultdict
from pathlib import Path

S = Path(__file__).resolve().parent
sys.path[:0] = [str(S.parent / 'grpo'), str(S.parent), str(S.parent / 'scripts')]
from grpo import SYMBOLIC, answer_value, close, correct, expr_value
from run_eval import COT_MC_SUFFIX, COT_OPEN_SUFFIX

RAW = S / 'data/visualprm_raw'
# Source subsets (protocol: the domains the paper names; Chinese sources and counting / document / chart sources left out)
SUBSETS = {
    'scienceqa': ['scienceqa_multi_choice_en_20240402_extracted'],
    'm3cot': ['m3cot_train_extracted'],
    'ai2d': ['ai2d_train_12k_en_20240410_extracted'],
    'geometry3k': ['geometry3k_en_20240402_extracted', 'geometry3k_en_20240402_extracted_open_ended_only'],
    'geos': ['geos_en_20240402_extracted', 'geos_en_20240402_extracted_open_ended_only'],
    'geo170k': ['geo170k_extracted_full'],
    'geomverse': ['geomverse_extracted'],
    'mavis_geo': [f'mavis_geo_depth{d}_text_dominant_vision_dominant_en' for d in range(4)],
    'mavis_function': [f'mavis_function_{f}' for f in ('abs', 'cos', 'log', 'poly', 'sin', 'tan')],
}
N_SFT, N_RL, N_HELD = 5000, 1000, 300
W = dict(length=0.42, steps=0.23, visual=0.20, label=0.10, fmt=0.05)  # paper, SFT data selection
LAM = dict(fmt=0.10, right=0.25, rule=0.75, cons=0.15)  # paper, eq. (10)
SUFFIXES = ("Answer with the option's letter from the given choices directly.",
            'Answer the question using a single word or phrase.',
            'Please answer the question based on the options mentioned before.')
CJK = re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]')
VISUAL = re.compile(r'\b(image|figure|diagram|graph|chart|picture|plot|map|shown|shows|see|observe|look|label(?:l?ed)?|marked)\b', re.I)


# ---- questions -------------------------------------------------------------------------------------------------
def question(r):
    """VisualPRM record -> pool item in our prompt format (run_eval.build_prompt, CoT suffix), or None.
    Kinds kept: lettered multiple choice, unlettered options (AI2D; letters are assigned), numeric open answers."""
    if not isinstance(r['image'], str) or CJK.search(r['question_orig'] + r['response']):
        return None
    lines = [l.rstrip() for l in r['question_orig'].strip().split('\n') if l.strip()]
    if lines and lines[-1].strip() in SUFFIXES:
        lines.pop()
    ans = str(r['answer']).strip()
    lines = [l for l in lines if l.strip() != 'Choices:']
    opts = [(m[1], m[2].strip()) for l in lines if (m := re.match(r'([A-H])[.:] (.*)', l))]
    if opts and [k for k, _ in opts] == [chr(65 + i) for i in range(len(opts))] and len(opts) >= 2:
        body = [l for l in lines if not re.match(r'[A-H][.:] ', l)]
        options = dict(opts)
        if ans not in options:
            return None
        gold = ans
    elif 3 <= len(lines) <= 7 and ans in lines[1:]:  # AI2D: question line, then unlettered option lines
        body, options = lines[:1], {chr(65 + i): o for i, o in enumerate(lines[1:])}
        gold = next(k for k, v in options.items() if v == ans)
    else:
        v, _ = answer_value(ans)
        if v is None or not re.fullmatch(r'[-+\d.,/\s%°]+|.*(\\frac|sqrt|√|π|\\pi).*', ans):
            return None
        q = '\n'.join(lines)
        return {'kind': 'num', 'text': '<image>\n' + q + '\n' + COT_OPEN_SUFFIX, 'gold': v, 'gold_str': ans, 'question': q}
    q = '\n'.join(body)
    return {'kind': 'mc', 'text': '<image>\n' + q + '\n' + ''.join(f'({k}) {v}\n' for k, v in options.items()) + COT_MC_SUFFIX,
            'gold': gold, 'options': options, 'question': q}


# ---- local results and the normalized format ---------------------------------------------------------------------
MATH = re.compile(r'\\\[(.+?)\\\]|\\\((.+?)\\\)|\$\$(.+?)\$\$|\$([^$\n]+?)\$', re.S)
EQ = re.compile(r'(?<![<>!=\\])=(?!=)|\\approx|≈')
NUMU = re.compile(r'(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?\s?(?:%|°)?')
CHOICE = re.compile(r'\b[Oo]ption\s*\(?([A-H])\)?(?![a-z])|\(([A-H])\)|\banswer is\s*\(?([A-H])\b(?![a-z])')


def local_result(step):
    """The value a step arrives at (our rule; the paper does not give one). Priority: right-hand side of the last
    formula, last plain '= value', option letter, yes/no, last number. None if the step states none of these."""
    return next((res for res in _results(step) if canon(res)), None)


def _results(step):
    segs = [next(g for g in m.groups() if g is not None) for m in MATH.finditer(step)]
    for seg in reversed(segs):  # the last formula that states a value: an equation, or anything with a digit in it
        line = ([l for l in re.split(r'\\\\|\n', seg) if l.strip()] or [''])[-1]
        if EQ.search(line) or re.search(r'\d', line):
            rhs = re.sub(r'\\(?:text|mathrm)\{[^{}]*\}\s*$', '', EQ.split(line)[-1])
            yield re.sub(r'(?:\\[,;! ]?|[\s.,;&])+$', '', rhs).strip()
            break
    plain = MATH.sub(' ', step)
    m = re.findall(r'(?<![<>!=])=\s*([^=\n]{1,40}?)[.,;]?\s*$', plain, re.M)
    if m:
        yield m[-1].strip(' *')
    m = CHOICE.findall(plain)
    if m:
        yield next(x for x in m[-1] if x)
    m = re.findall(r'\b(yes|no|true|false)\b', plain, re.I)
    if m:
        yield m[-1].lower()
    m = NUMU.findall(re.sub(r'^\s*(?:\d+\.|Step \d+[:.]?)\s', '', plain, flags=re.M))  # not the list numbering
    if m:
        yield m[-1].strip()


def trajectory(r):
    """-> (step texts without the final-answer line, their MC scores, final answer string) or None."""
    s = r['steps_with_score']
    if not s:
        return None
    head, sep, fin = s[-1]['step'].rpartition('Final answer:')
    if not sep or not fin.strip() or '\n' in fin.strip():
        return None
    steps = [(x['step'], x['score']) for x in s[:-1]] + ([(head, s[-1]['score'])] if head.strip() else [])
    return [t for t, _ in steps], [c for _, c in steps], fin.strip(), s[-1]['score']


def givens(question):
    """Numbers that already stand in the question text: restating one of them is not a result (load_pool, check_targets)."""
    return {float(x.replace(',', '')) for x in re.findall(r'(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?', question)}


def restated(res, given):
    return (v := value(res)) is not None and v in given


def normalize(texts):
    """Steps without a local result join the next step (trailing ones join the last) -> [(text, result)]."""
    out, buf = [], []
    for t in texts:
        # the source's own list number, and its own 'Step n:' line starts (they would read as our step markers)
        buf.append(re.sub(r'^Step \d+:\s*', '', re.sub(r'^\s*\d+\.\s+', '', t.strip()), flags=re.M))
        res = local_result(t)
        if res is not None:
            out.append(('\n\n'.join(buf), res))
            buf = []
    if buf and out:
        out[-1] = ('\n\n'.join([out[-1][0]] + buf), out[-1][1])
    return out


def target(steps, answer):
    """The normalized response: one <think> block, 'Step i:' markers, a \\boxed local result per step, then our
    pipeline's answer line (the paper puts a boxed answer there; our frozen parser needs 'Answer:')."""
    body = '\n'.join(f'Step {i}: {t} \\boxed{{{res}}}' for i, (t, res) in enumerate(steps, 1))
    return f'<think>\n{body}\n</think>\nAnswer: {answer}'


def boxed(s):
    """Contents of every \\boxed{...} in s, braces balanced."""
    out, i = [], s.find('\\boxed{')
    while i >= 0:
        depth, j = 1, i + 7
        while j < len(s) and depth:
            depth += {'{': 1, '}': -1}.get(s[j], 0)
            j += 1
        if depth:
            break
        out.append(s[i + 7:j - 1].strip())
        i = s.find('\\boxed{', j)
    return out


def parse(text):
    """Response -> (format valid, local results in order, final answer or None). Valid = exactly one reasoning block,
    step indices 1..M in order, a boxed result in every step, and an answer line after the block."""
    blocks = re.findall(r'<think>(.*?)</think>', text, re.S)
    tags = re.findall(r'Answer:\s*(.+)', text.rsplit('</think>', 1)[-1]) if '</think>' in text else []
    ans = tags[-1].strip() if tags else None
    if len(blocks) != 1 or text.count('<think>') != 1:
        return False, [], ans
    marks = list(re.finditer(r'^Step (\d+):', blocks[0], re.M))
    parts = [blocks[0][m.end():marks[i + 1].start() if i + 1 < len(marks) else None] for i, m in enumerate(marks)]
    res = [(boxed(p) or [None])[-1] for p in parts]
    ok = bool(marks) and [int(m[1]) for m in marks] == list(range(1, len(marks) + 1)) and None not in res and ans is not None
    return ok, [x for x in res if x is not None], ans


# ---- matching and the reward ------------------------------------------------------------------------------------------
def canon(s):
    s = re.sub(r'\\(?:text|mathrm|mathbf)\{([^{}]*)\}', r'\1', s)
    for a, b in (('\\dfrac', '\\frac'), ('\\tfrac', '\\frac'), ('^\\circ', '°'), ('^{\\circ}', '°'), ('\\times', '*'),
                 ('\\cdot', '*'), ('×', '*'), ('\\left', ''), ('\\right', ''), ('\\,', ''), ('\\!', ''), ('$', '')):
        s = s.replace(a, b)
    return re.sub(r'[\s.,;:()\[\]]+$|^[\s(\[]+', '', re.sub(r'\s+', '', s.lower()))


def value(s):
    """Number a result stands for, or None when it is not purely numeric (variables left: compare as text)."""
    t = re.sub(r'\\(?:text|mathrm)\{[^{}]*\}|[$°%]|\^\{?\\circ\}?|\\left|\\right|\\,', '', s.strip()).strip()
    # a number, then optional unit words ("8 cm", "12m^2"); a single letter glued to the number is a variable ("3x")
    m = re.fullmatch(r'([-+]?\d+(?:,\d{3})*(?:\.\d+)?)(?:(?:\s+[a-zA-Z]|[a-zA-Z]{2})[a-zA-Z ]{0,20}(?:\^\{?[23]\}?)?)?', t)
    if m:
        return float(m[1].replace(',', ''))
    t = re.sub(r'\\sqrt\{([^{}]*)\}', r'sqrt(\1)', t)  # before grpo.expr_value, whose \frac pattern takes no inner braces
    if SYMBOLIC.search(t) and not re.search(r'[a-zA-Z]', re.sub(r'\\[dt]?frac|sqrt|\\pi|pi|\\cdot|\\times', '', t)):
        return expr_value(t)
    return None


def match(a, b):
    """Numbers within 1 % (grpo.close); everything else equal after canonical form."""
    va, vb = value(a), value(b)
    if va is not None and vb is not None:
        return close(va, vb)
    return va is None and vb is None and canon(a) == canon(b) != ''


def rule(gen, ref, over=None):
    """Eq. (6)-(7): generated results in order, each matched to a reference result after the last matched one;
    share of generated steps that found a match (the paper), or matches over `over` when given (Amendment 5: the
    number of reference results, so that writing fewer steps cannot raise the share)."""
    j = z = 0
    for a in gen:  # a step without a readable result (None, plain-step reading) stays in the denominator, unmatched
        k = next((k for k in range(j, len(ref)) if a is not None and match(a, ref[k])), None)
        if k is not None:
            z, j = z + 1, k + 1
    return z / (over or len(gen)) if gen else 0.0


VALUES = re.compile(r'(?:(?<![<>!=])=|≈|\\approx)\s*\$?\s*(-?\d+(?:,\d{3})*(?:\.\d+)?(?:\s?/\s?\d+(?:\.\d+)?)?\s?(?:π|\\pi|%|°|\^\\circ)?)'
                    r'|\b[Oo]ption\s*\(?([A-H])\)?(?![a-z])|\(([A-H])\)|\banswer is\s*\(?([A-H])\b(?![a-z])|\b(yes|no|true|false)\b', re.I)


def all_values(text):
    """Amendment 8: every value the solution states, in order of appearance and without regard to the step marks:
    a number after an equals sign, an option mention, yes / no / true / false. Merging or splitting steps cannot
    change this list."""
    return [next(g for g in m.groups() if g).strip() for m in VALUES.finditer(text.rpartition('\nAnswer:')[0])]


def in_order(gen, ref):
    """Largest number of reference results that the generated values contain in the same order (each used once)."""
    f = [[0] * (len(ref) + 1) for _ in range(len(gen) + 1)]
    for i, a in enumerate(gen):
        for j, b in enumerate(ref):
            f[i + 1][j + 1] = f[i][j] + 1 if match(a, b) else max(f[i][j + 1], f[i + 1][j])
    return f[-1][-1]


def read_steps(text):
    """Amendment 4, the counterpart of `parse` for the plain numbered steps of the stage A3 model -> (format valid,
    the result of every step by `local_result`, None where a step states none, final answer)."""
    parts = numbered(text)
    if parts is None:
        return False, [], None
    return True, [local_result(p) for p in parts], text.rpartition('\nAnswer:')[2].strip()


def reward(q, text, finish, steps=''):
    """Eq. (4)-(10). R_right is our pipeline's check of the last 'Answer:' of a finished response. With `steps` the
    response is read as plain numbered steps (Amendment 4) instead of the tagged, boxed format; steps = 'recall' or
    'both' also changes the denominator of the rule term (Amendments 5 and 6)."""
    ok, res, ans = read_steps(text) if steps else parse(text)
    ok = ok and (finish == 'stop' or not steps)  # plain-step reading: a response cut at the token limit has no valid format
    right = correct(q, text, finish)
    letter = (ans or '').strip('() .').upper()[:1]
    last = next((x for x in reversed(res) if x is not None), None)  # the last result that could be read
    cons = float(last is not None and ans is not None and (match(last, ans) or match(last, (q.get('options') or {}).get(letter, ''))
                                                           or canon(last) == letter.lower() != ''))
    # denominator of the rule term: generated steps (paper), reference results ('recall', Amendment 5), or the larger
    # of the two ('both', Amendment 6: neither merging nor splitting steps can raise the share)
    over = {'recall': len(q['ref']), 'both': max(len(res), len(q['ref']))}.get(steps)
    r_rule = rule(res, q['ref'], over) if ok else 0.0
    if steps == 'right':  # diagnostic 6: the outcome alone, no format term and no process term
        return {'fmt': float(ok), 'right': right, 'rule': 0.0, 'cons': cons, 'steps': len(res), 'total': float(right)}
    if steps == 'values':  # candidate (run log 2026-11-16 05:40): share of the reference results found among all stated values, in order
        vals = all_values(text) if ok else []
        r_rule = in_order(vals, q['ref']) / len(q['ref']) if ok else 0.0
        return {'fmt': float(ok), 'right': right, 'rule': r_rule, 'cons': cons, 'steps': len(res), 'values': len(vals),
                'total': LAM['fmt'] * ok + LAM['right'] * right + LAM['rule'] * right * r_rule * (1 + LAM['cons'] * cons)}
    return {'fmt': float(ok), 'right': right, 'rule': r_rule, 'cons': cons, 'steps': len(res),
            'total': LAM['fmt'] * ok + LAM['right'] * right + LAM['rule'] * right * r_rule * (1 + LAM['cons'] * cons)}


CUT = re.compile(r'(\\times|\\cdot|\\div|[-+*/=(,])\s*$')  # a formula our result rule cut off before its last operand


def clean_ref(ref):
    """Amendment 7: reference results without a literal \\boxed wrapper, without cut-off formulas (never the last
    one), and without a result equal to the one before it (matching both paid for stating a value twice)."""
    out, ref = [], [(boxed(r) or [r])[0] if r.startswith('\\boxed') else r for r in ref]
    for i, r in enumerate(ref):
        if not (i < len(ref) - 1 and CUT.search(r.strip())) and not (out and match(r, out[-1])):
            out.append(r)
    return out


def load_pool(name, clean=''):
    """Pool rows by qid for scoring. Reference results that only restate a number of the question are left out
    (Amendment 2; the last one stays), so a response earns no process reward for copying the given values.
    With `clean` the list also goes through `clean_ref` (Amendment 7)."""
    out = {}
    for q in map(json.loads, open(S / f'data/{name}.jsonl')):
        g = givens(q['question'])
        ref = [r for r in q['ref'][:-1] if not restated(r, g)] + q['ref'][-1:]
        out[q['qid']] = {**q, 'ref': clean_ref(ref) if clean else ref}
    return out


def reward_round(run, rnd, steps='', clean=''):
    f = S.parent / 'grpo' / run / f'rounds/r{int(rnd):03d}.jsonl'
    pool = load_pool(os.environ.get('SR_POOL', 'pool_rl'), clean)  # SR_POOL: the hard pool of Amendment 9
    rows = [json.loads(l) for l in open(f)]
    for r in rows:
        r['sr'] = reward(pool[r['qid']], r['text'], r['finish'], steps)
        r['reward'] = r['sr']['total']
    f.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    n = len(rows)
    print(json.dumps({'round': int(rnd), 'phase': 'reward', **{k: round(sum(r['sr'][k] for r in rows) / n, 4)
                      for k in ('fmt', 'right', 'rule', 'cons', 'steps', 'values', 'total') if k in rows[0]['sr']}}))


JUDGE = ("\n\nA student's solution:\n{a}\n\nIs the final answer of this solution correct? "
         'Reply with exactly one word: Correct or Incorrect.')
CHOOSE = ('\n\nSolution A:\n{a}\n\nSolution B:\n{b}\n\nExactly one of the two solutions reaches the correct final answer. '
          'Which one? Reply with exactly one letter: A or B.')


def aux_examples(rows, pool, rng, balanced=''):
    """Rollout recycling (paper, eq. 14-15) from finished responses: per question one pointwise example (a random
    response, target Correct / Incorrect) and, if the group has both outcomes, one pairwise example (one right and
    one wrong response in random order, target A / B). The question is shown without the CoT instruction.
    `balanced` (Amendment 7): pointwise examples only from questions with both outcomes, one right and one wrong
    response each, so the two targets are equally frequent (as drawn before, 92 % were 'Correct')."""
    by, out = defaultdict(list), []
    for r in rows:
        if r['finish'] == 'stop':
            by[r['qid']].append(r)
    for qid, g in by.items():
        head, cut = pool[qid]['text'].rsplit('Think step by step', 1)[0].rstrip(), lambda r: r['text'][:6000]
        ok, bad = [r for r in g if r['correct']], [r for r in g if not r['correct']]
        for r in ([rng.choice(ok), rng.choice(bad)] if ok and bad else []) if balanced else [rng.choice(g)]:
            out.append({'qid': qid, 'task': 'point', 'image': r['image'], 'text': head + JUDGE.format(a=cut(r)),
                        'target': 'Correct' if r['correct'] else 'Incorrect'})
        if ok and bad:
            pair = [rng.choice(ok), rng.choice(bad)]
            flip = rng.random() < 0.5
            a, b = pair[::-1] if flip else pair
            out.append({'qid': qid, 'task': 'pair', 'image': a['image'], 'text': head + CHOOSE.format(a=cut(a), b=cut(b)),
                        'target': 'B' if flip else 'A'})
    return out


def aux_round(run, rnd, balanced=''):
    d = S.parent / 'grpo' / run / 'rounds'
    pool = {q['qid']: q for q in map(json.loads, open(S / f"data/{os.environ.get('SR_POOL', 'pool_rl')}.jsonl"))}
    out = aux_examples([json.loads(l) for l in open(d / f'r{int(rnd):03d}.jsonl')], pool, random.Random(int(rnd)), balanced)
    (d / f'r{int(rnd):03d}.aux.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in out))
    print(json.dumps({'round': int(rnd), 'phase': 'aux', **Counter(x['task'] + ':' + x['target'] for x in out)}))


# ---- data ------------------------------------------------------------------------------------------------------------
def candidates(subset, z):
    """One entry per usable trajectory of the subset: the question in our format plus the normalized trajectory."""
    out = []
    for f in SUBSETS[subset]:
        with z.open(f'annotations/{f}.jsonl') as fh:
            for line in fh:
                r = json.loads(line)
                q, tr = question(r), trajectory(r)
                if q is None or tr is None:
                    continue
                texts, scores, fin, fin_score = tr
                if q['kind'] == 'mc' and fin not in q['options']:  # AI2D writes the option text
                    fin = next((k for k, v in q['options'].items() if v == fin), fin)
                if fin_score != 1.0 or not correct(q, 'Answer: ' + fin, 'stop'):
                    continue
                fin = q['gold'] if q['kind'] == 'mc' else q['gold_str']  # the answer line carries the verified label itself
                kept = [(t, c) for t, c in zip(texts, scores) if c > 0]  # "retains only its correct steps"
                steps = normalize([t for t, _ in kept])
                if not steps or parse(target(steps, fin))[:2] != (True, [res for _, res in steps]):
                    continue  # no local result at all, or the written target does not read back (stray tags, braces)
                img = r['image'].replace('VisualPRM400K-v1.1-Raw/', 'images/')
                key = hashlib.sha1((img + '\n' + q['question']).encode()).hexdigest()[:12]
                out.append({**q, 'qid': f'vprm-{subset}-{key}', 'subset': subset, 'zip_image': img, 'answer': fin,
                            'steps': steps, 'all_correct': len(kept) == len(texts),
                            'feat': {'length': sum(len(t) for t in texts), 'steps': len(steps),
                                     'visual': sum(bool(VISUAL.search(t)) for t in texts) / len(texts),
                                     'label': sum(scores) / len(scores),
                                     'fmt': sum(local_result(t) is not None for t in texts) / len(texts)}})
    return out


def rank(xs):
    order = sorted(range(len(xs)), key=xs.__getitem__)
    out = [0.0] * len(xs)
    for i, j in enumerate(order):
        out[j] = i / max(1, len(xs) - 1)
    return out


def build():
    """Held-out 300, then the RL pool 1,000: random questions, one per image, taken subset by subset in turn (a subset
    that runs out passes its share on). SFT 5,000: per subset the questions ranked by the paper's weights, again taken
    in turn, one per image, from images not used above. Items that hit MMMU by text or image are dropped
    (grpo/prepare_virl.mmmu_overlap: the BMMR-audit rules)."""
    from prepare_virl import mmmu_overlap
    text_hit, image_hit = mmmu_overlap()
    za, zi = zipfile.ZipFile(RAW / 'annotations.zip'), zipfile.ZipFile(RAW / 'images.zip')
    names, rng, skip, stats = set(zi.namelist()), random.Random(0), Counter(), {}

    def usable(c):  # image present and not an MMMU hit; extracts the image on first use
        if c['zip_image'] not in names:
            skip['image missing'] += 1
            return False
        if text_hit(c['question']):
            skip['MMMU text hit'] += 1
            return False
        blob = zi.read(c['zip_image'])
        if image_hit(blob):
            skip['MMMU image hit'] += 1
            return False
        p = RAW / c['zip_image']
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(blob)
        c['image'] = str(p)
        return True

    by, order = {}, {}
    for s in SUBSETS:
        by[s] = defaultdict(lambda: defaultdict(list))
        cands = candidates(s, za)
        for c in cands:
            by[s][c['zip_image']][c['qid']].append(c)
        order[s] = sorted(by[s])
        rng.shuffle(order[s])
        stats[s] = {'trajectories': len(cands), 'questions': len({c['qid'] for c in cands}), 'images': len(order[s])}

    def draw(n, pick):
        out, live = [], list(SUBSETS)
        while len(out) < n and live:
            for s in list(live):
                if len(out) < n:
                    c = pick(s)
                    out += [c] if c else []
                    live = live if c else [x for x in live if x != s]
        return out

    def random_question(s):  # next unused image: its best-labelled trajectory with at least 2 results is the reference
        while order[s]:
            qs = by[s].pop(order[s].pop())
            c = max((c for q in qs.values() for c in q if len(c['steps']) >= 2), key=lambda c: c['feat']['label'], default=None)
            if c is not None and usable(c):
                return c
        return None

    held = draw(N_HELD, random_question)
    pool = draw(N_RL, random_question)
    ranked, used = {}, set()
    for s in SUBSETS:  # per question the longest fully-correct trajectory with 3-12 steps, scored with the paper's weights
        best = [max(ok, key=lambda c: (c['feat']['length'], c['feat']['label'])) for qs in by[s].values() for q in qs.values()
                if (ok := [c for c in q if c['all_correct'] and 3 <= len(c['steps']) <= 12])]
        for k in ('length', 'steps'):
            for c, v in zip(best, rank([c['feat'][k] for c in best])):
                c['feat'][k + '_rank'] = v
        for c in best:
            f = c['feat']
            c['score'] = (W['length'] * f['length_rank'] + W['steps'] * f['steps_rank'] + W['visual'] * f['visual']
                          + W['label'] * f['label'] + W['fmt'] * f['fmt'])
        ranked[s] = sorted(best, key=lambda c: c['score'])
        stats[s]['sft_candidates'] = len(best)

    def best_question(s):
        while ranked[s]:
            c = ranked[s].pop()
            if c['zip_image'] not in used and usable(c):
                used.add(c['zip_image'])
                return c
        return None

    sft = draw(N_SFT, best_question)
    for name, rows in (('heldout', held), ('rl', pool), ('sft', sft)):
        for s, n in Counter(c['subset'] for c in rows).items():
            stats[s][name] = n
    row = lambda c: {k: c[k] for k in ('qid', 'kind', 'subset', 'text', 'image', 'gold', 'question') if k in c} | {
        'gold_str': c.get('gold_str'), 'options': c.get('options'), 'ref': [r for _, r in c['steps']],
        'reference': target(c['steps'], c['answer'])}
    dump = lambda f, rows: Path(f).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    dump(S / 'data/pool_rl.jsonl', [row(c) for c in pool])
    dump(S / 'data/heldout.jsonl', [row(c) for c in held])
    dump(S / 'data/sft.jsonl', [row(c) | {'score': round(c['score'], 4), 'feat': c['feat']} for c in sft])
    out = S.parent / 'grpo/runs/sr_sft'
    out.mkdir(parents=True, exist_ok=True)
    dump(out / 'rft_train.jsonl', [{'qid': c['qid'], 'text': c['text'], 'image': c['image'],
                                    'response': target(c['steps'], c['answer'])} for c in sft])
    full = lambda c: reward({**c, 'ref': [r for _, r in c['steps']]}, target(c['steps'], c['answer']), 'stop')
    for rows in (sft, pool, held):  # every written target must pass our own parser and get the full process reward
        for c in rows:
            assert (rw := full(c))['fmt'] == 1 and rw['right'] == 1 and rw['rule'] == 1, (c['qid'], rw)
    ids = [{c['zip_image'] for c in rows} for rows in (sft, pool, held)]
    assert not (ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2]) and len(ids[0]) == len(sft), 'image shared between or within splits'
    chars = sorted(len(target(c['steps'], c['answer'])) for c in sft)
    summary = {'sft': len(sft), 'rl': len(pool), 'heldout': len(held), 'skipped': dict(skip), 'subsets': stats,
               'kind': {n: Counter(c['kind'] for c in rows) for n, rows in (('sft', sft), ('rl', pool), ('heldout', held))},
               'sft_steps_mean': round(sum(len(c['steps']) for c in sft) / len(sft), 2),
               'rl_ref_steps_mean': round(sum(len(c['steps']) for c in pool) / len(pool), 2),
               'sft_target_chars': {'p10': chars[len(chars) // 10], 'median': chars[len(chars) // 2], 'p90': chars[9 * len(chars) // 10]},
               'sft_targets_with_consistent_last_result': round(sum(full(c)['cons'] for c in sft) / len(sft), 3)}
    (S / 'data/build_summary.json').write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))


def build_hard():
    """Amendment 9, the hard pool: questions the base model answers right only some of the time.
    Multiple choice: pool_v7 items with <= 3 of 4 right in the base's first screen and 1-3 of 4 in its second
    (grpo/runs/heldout/v7_base.jsonl, v8mc_base.jsonl), none of the MC-check questions. Numeric: pool_v4 without the
    probe questions. MMMU overlap is checked again. Rounds of 12 = 8 multiple choice + 4 numeric, random order (seed 0)
    -> data/pool_hard.jsonl, data/pool_hard_len.jsonl (the base's response length per question, for the length guard)."""
    from prepare_virl import mmmu_overlap
    G, rng = S.parent / 'grpo', random.Random(0)
    rd = lambda f: [json.loads(l) for l in open(G / f)]
    ids = lambda f: set(Path(f).read_text().split('\n')) - {''}
    text_hit, image_hit = mmmu_overlap()
    fresh = {r['qid']: r['correct'] for r in rd('runs/heldout/v8mc_base.jsonl')}
    skip = ids(G / 'data/heldout/v7_unseen_v12.txt') | ids(S / 'data/probe_ids.txt')
    mc = [q | {'question': q['text'].removeprefix('<image>\n').removesuffix(COT_MC_SUFFIX).strip(), 'subset': 'hard_mc'}
          for q in rd('data/pool_v7.jsonl') if 1 <= fresh.get(q['qid'], 0) <= 3 and q['qid'] not in skip]
    skip |= {q['qid'] for q in mc}  # an item can be in both sources under one id; rewards are looked up by id
    num = [q | {'subset': 'hard_num', 'options': None} for q in rd('data/pool_v4.jsonl') if q['qid'] not in skip]
    hit = [q['qid'] for q in mc + num if text_hit(q['question']) or image_hit(Path(q['image']).read_bytes())]
    mc, num = ([q for q in x if q['qid'] not in hit] for x in (mc, num))
    rng.shuffle(mc), rng.shuffle(num)
    n = min(len(mc) // 8, len(num) // 4)
    rows = [q for i in range(n) for q in mc[8 * i:8 * i + 8] + num[4 * i:4 * i + 4]]
    assert len({q['qid'] for q in rows}) == len(rows), 'question id used twice'
    keep = ('qid', 'kind', 'subset', 'text', 'image', 'gold', 'gold_str', 'options', 'question')
    (S / 'data/pool_hard.jsonl').write_text(''.join(json.dumps({k: q.get(k) for k in keep} | {'ref': []}, ensure_ascii=False) + '\n' for q in rows))
    tok = {r['qid']: r['tokens'] for f in ('data/screen_v4.jsonl', 'runs/heldout/v7_base.jsonl') for r in rd(f)}
    med = sorted(tok[q['qid']] for q in rows if q['qid'] in tok)[len(rows) // 2 - 1]
    (S / 'data/pool_hard_len.jsonl').write_text(''.join(json.dumps({'qid': q['qid'], 'tokens': tok.get(q['qid'], med)}) + '\n' for q in rows))
    print(json.dumps({'rounds': n, 'questions': len(rows), 'mc': 8 * n, 'numeric': 4 * n, 'mmmu_hits_dropped': len(hit),
                      'mc_candidates': len(mc), 'numeric_candidates': len(num), 'without_screen_length': sum(q['qid'] not in tok for q in rows)}))


FORMAT = ('Write your reasoning inside a single <think> ... </think> block, as numbered steps. Begin each step on a new line '
          'with "Step 1:", "Step 2:", and so on, and end each step with the result of that step inside \\boxed{}. '
          'Close the block with </think> before the final answer line.\n')


def prep_own():
    """Stage A2 (protocol, Amendment 1): the SFT questions with the format instruction placed before the CoT suffix.
    'text_plain' keeps the normal prompt, which is what training uses (as in v9)."""
    out = []
    for q in map(json.loads, open(S / 'data/sft.jsonl')):
        head, sep, tail = q['text'].rpartition('Think step by step')
        assert sep, q['qid']
        out.append({k: q.get(k) for k in ('qid', 'kind', 'subset', 'image', 'gold', 'gold_str', 'options', 'question')}
                   | {'text': head + FORMAT + sep + tail, 'text_plain': q['text']})
    (S / 'data/sft_own_pool.jsonl').write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in out))
    (S / 'data/sft_own_ids.txt').write_text(''.join(q['qid'] + '\n' for q in out))


def numbered(text):
    """Stage A3 format (Amendment 3), the base's own plain numbered steps: 'Step 1:' .. 'Step M:' at line starts, in
    order, from the first line on, and the answer line last. -> the step texts, or None."""
    marks = list(re.finditer(r'^Step (\d+):', text, re.M))
    body, sep, ans = text.rpartition('\nAnswer:')
    if (not marks or not sep or '\n' in ans.strip() or text[:marks[0].start()].strip()
            or [int(m[1]) for m in marks] != list(range(1, len(marks) + 1)) or marks[-1].start() > len(body)):
        return None
    return [body[m.end():marks[i + 1].start() if i + 1 < len(marks) else None] for i, m in enumerate(marks)]


def select_own():
    """Amendment 3: per question the longest of the base's own finished, correct responses that are plain numbered
    steps (at least 3; none of the tags or boxes), used as written (runs/own_base_s*.rows.jsonl)
    -> grpo/runs/sr_sft3/rft_train.jsonl. Exit 1 if fewer than 3,000 questions have one."""
    pool = {q['qid']: q for q in map(json.loads, open(S / 'data/sft_own_pool.jsonl'))}
    rows = [json.loads(l) for f in sorted((S / 'runs').glob('own_base_s*.rows.jsonl')) for l in open(f)]
    good = defaultdict(list)
    for r in rows:
        if (r['finish'] == 'stop' and r['correct'] and len(numbered(r['text']) or []) >= 3
                and '\\boxed' not in r['text'] and 'think>' not in r['text']):
            good[r['qid']].append(r['text'].strip())
    data = [{'qid': i, 'text': pool[i]['text_plain'], 'image': pool[i]['image'], 'response': max(good[i], key=len)}
            for i in pool if i in good]
    out = S.parent / 'grpo/runs/sr_sft3'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'rft_train.jsonl').write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in data))
    print(json.dumps({'questions': len(pool), 'responses': len(rows), 'finished': sum(r['finish'] == 'stop' for r in rows),
                      'correct': sum(bool(r['correct']) for r in rows), 'usable': sum(map(len, good.values())), 'targets': len(data),
                      'steps_mean': round(sum(len(numbered(d['response'])) for d in data) / max(1, len(data)), 2),
                      'by_subset': Counter(pool[d['qid']]['subset'] for d in data)}))
    sys.exit(0 if len(data) >= 3000 else 1)


CHECKS = re.compile(r'\b(wait|let me (?:re)?check|re-?examine|double-check|verify|however|but wait|actually|reconsider)\b', re.I)


def check_targets(name):
    """Gate before an SFT (Amendment 2): the targets of grpo/runs/NAME against the base's own finished solutions on the
    held-out questions and against the stage A targets, each weighted to NAME's mix of subsets. Pass = '=' signs per
    solution and the share of solutions with a self-check word both above the midpoint of those two. Exit 1 otherwise."""
    quest = {q['qid']: q['question'] for q in map(json.loads, open(S / 'data/sft.jsonl'))}
    load = lambda n: [(r['qid'], r['response']) for r in map(json.loads, open(S.parent / f'grpo/runs/{n}/rft_train.jsonl'))]
    sets = {name: load(name), 'stage A targets': load('sr_sft'),
            'base, own solutions': [(r['qid'], r['text']) for r in map(json.loads, open(S / 'runs/heldout_base.rows.jsonl'))
                                    if r['finish'] == 'stop']}
    mix = Counter(i.split('-')[1] for i, _ in sets[name])

    def mean(rows, f):  # per subset, then weighted to the mix of the checked targets
        by = defaultdict(list)
        for i, t in rows:
            by[i.split('-')[1]].append(f(t))
        return sum(mix[s] * sum(v) / len(v) for s, v in by.items()) / sum(mix[s] for s in by)

    got = {}
    for k, rows in sets.items():
        chars = sorted(len(t) for _, t in rows)
        got[k] = (mean(rows, lambda t: t.count('=')), 100 * mean(rows, lambda t: bool(CHECKS.search(t))))
        line = f"{k:20s} n {len(rows):5d}  '=' {got[k][0]:5.1f}  self-check {got[k][1]:5.1f} %  chars p10/median/p90 " \
               f"{chars[len(chars) // 10]} / {chars[len(chars) // 2]} / {chars[9 * len(chars) // 10]}"
        # what boxes hold, where targets have them: a number of the question restated (not in the last step), no value at all
        bx = [(b, givens(quest[i]), j == len(res) - 1) for i, t in rows if i in quest for res in [parse(t)[1]] for j, b in enumerate(res)]
        if bx:
            line += (f"  boxes {len(bx)}: restated {100 * sum(restated(b, g) and not last for b, g, last in bx) / len(bx):.1f} %"
                     f"  no digit or option {100 * sum(not re.search(r'[0-9]', b) and not re.fullmatch(r'[a-h]|yes|no|true|false', canon(b)) for b, _, _ in bx) / len(bx):.1f} %")
        print(line)
    mid = [(got['stage A targets'][j] + got['base, own solutions'][j]) / 2 for j in (0, 1)]
    ok = got[name][0] > mid[0] and got[name][1] > mid[1]
    print(f"midpoints: '=' {mid[0]:.1f}, self-check {mid[1]:.1f} %  ->  target check: {'pass' if ok else 'fail'}")
    sys.exit(0 if ok else 1)


def heldout(tag, steps=''):
    """Held-out 300 questions, 4 samples each (grpo.py screen): accuracy of the tagged model against the base, paired
    by question, and how both score under the structured reward. Exit 1 if fewer than 80 % of the tagged model's
    responses have the valid format (protocol, stage A gate 1); with a third argument 'steps' the format is the
    plain numbered steps of Amendment 3 (`numbered`) instead of the tagged, boxed one."""
    from heldout_compare import boot, load
    pool = load_pool('heldout')
    files = {k: S / f'runs/heldout_{k}.jsonl' for k in ('base', tag)}
    b, t = load(files['base']), load(files[tag])
    acc = lambda r: r['correct'] / r['n']
    d, lo, hi = boot([100 * (acc(t[i]) - acc(b[i])) for i in sorted(pool)])
    print(f"held-out n={len(pool)}  acc {100 * sum(acc(b[i]) for i in pool) / len(pool):.1f} -> "
          f"{100 * sum(acc(t[i]) for i in pool) / len(pool):.1f}  Δ {d:+.2f} [{lo:+.2f}, {hi:+.2f}]")
    fmt = {}
    for k, f in files.items():
        rows = [json.loads(l) for l in open(f.with_suffix('.rows.jsonl'))]
        rw = [reward(pool[r['qid']], r['text'], r['finish'], steps) for r in rows]
        fin = [len(r['text']) for r in rows if r['finish'] == 'stop']
        fmt[k] = sum(numbered(r['text']) is not None for r in rows) / len(rows) if steps else sum(x['fmt'] for x in rw) / len(rw)
        print(f"  {k:8s} format {100 * fmt[k]:.1f} %  rule {sum(x['rule'] for x in rw) / len(rw):.3f}  cons {sum(x['cons'] for x in rw) / len(rw):.3f}  "
              f"reward {sum(x['total'] for x in rw) / len(rw):.3f}  steps {sum(x['steps'] for x in rw) / len(rw):.1f}  "
              f"truncated {100 * (1 - len(fin) / len(rows)):.1f} %  finished chars {sum(fin) / max(1, len(fin)):.0f}")
    sys.exit(0 if fmt[tag] >= 0.8 else 1)


def selfcheck():
    assert local_result('Subtract: \\[ x^2 = 324 - 81 \\]\n\n\\[ x^2 = 243 \\]') == '243'
    assert local_result('Thus, the correct answer is \\( 9\\sqrt{3} \\).') == '9\\sqrt{3}'
    assert local_result('2. **Area**: the area = 384 square units.') == '384 square units'
    assert local_result('So Option B is correct because it matches.') == 'B' and local_result('1. Look at the map.') is None
    assert local_result('3. There are 8 green particles in Solution B.') == '8'
    assert local_result('We need the length of \\( SC \\).') is None and local_result('speed: \\( 910 \\, \\text{m/s} \\)') == '910'
    assert normalize(['Let us begin.', 'We get \\(x = 2\\).', 'Done here.']) == [('Let us begin.\n\nWe get \\(x = 2\\).\n\nDone here.', '2')]
    t = target([('a', '2'), ('b', '\\frac{1}{2}')], 'B')
    assert parse(t) == (True, ['2', '\\frac{1}{2}'], 'B')
    assert parse(t.replace('Step 2', 'Step 3'))[0] is False and parse(t.replace('<think>', ''))[0] is False
    assert parse(t.replace(' \\boxed{2}', ''))[0] is False and parse('Step 1: \\boxed{2}\nAnswer: B')[0] is False
    assert match('0.5', '\\frac{1}{2}') and match('35°', '35') and match('9 \\sqrt{3}', '9\\sqrt{3}') and match('384 square units', '384')
    assert not match('2x + 3', '2x - 1') and match('x + 1', 'x+1') and not match('3', 'B') and not match('', '')
    assert not match('3x', '3') and match('12 m^2', '12') and match('\\frac{9\\sqrt{2}}{2}', '6.364')
    assert rule(['1', '2', '3'], ['1', '2', '3']) == 1 and rule(['2', '1'], ['1', '2']) == 0.5 and rule(['1', '1'], ['1', '2']) == 0.5
    q = {'kind': 'mc', 'gold': 'B', 'options': {'A': '1', 'B': '0.5'}, 'ref': ['2', '0.5']}
    r = reward(q, t, 'stop')
    assert r['fmt'] == r['right'] == r['rule'] == r['cons'] == 1 and abs(r['total'] - (0.10 + 0.25 + 0.75 * 1.15)) < 1e-9, r
    w = reward(q, t.replace('Answer: B', 'Answer: A'), 'stop')
    assert w['right'] == 0 and abs(w['total'] - 0.10) < 1e-9, w  # a wrong answer keeps only the format term
    assert reward(q, t, 'length')['right'] == 0 and reward(q, 'Answer: B', 'stop')['total'] == 0.25
    g = [{'qid': 'q', 'finish': 'stop', 'correct': c, 'text': f'sol{i}', 'image': 'i.png'} for i, c in enumerate([1.0, 0.0, 0.0])]
    ex = aux_examples(g + [{**g[0], 'finish': 'length'}], {'q': {'text': '<image>\nQ?\n(A) 1\n' + COT_MC_SUFFIX}}, random.Random(0))
    assert [x['task'] for x in ex] == ['point', 'pair'] and ex[0]['text'].startswith('<image>\nQ?\n(A) 1\n\nA student')
    assert ex[1]['target'] == ('A' if ex[1]['text'].index('sol0') < ex[1]['text'].index('Solution B') else 'B')
    assert 'Think step by step' not in ex[0]['text'] and aux_examples(g[1:], {'q': {'text': 'Q'}}, random.Random(0))[0]['target'] == 'Incorrect'
    own = '<think>\nStep 1: The radius is half of 16. \\boxed{8}\nStep 2: Area is 3.14 * 64 / 2. \\boxed{100.48}\n</think>\nAnswer: 100.48'
    assert parse(own) == (True, ['8', '100.48'], '100.48') and FORMAT.endswith('line.\n') and '\\boxed{}' in FORMAT
    n = reward({'kind': 'num', 'gold': 100.48, 'gold_str': '100.48', 'options': None, 'ref': ['8', '100.48']}, own, 'stop')
    assert n['fmt'] == n['right'] == n['rule'] == n['cons'] == 1, n  # pool rows of numeric questions carry options = None
    g = givens('AB is 12 and the angle is 35.5 degrees, 1,200 in all')
    assert g == {12.0, 35.5, 1200.0} and restated('12 cm', g) and not restated('24', g) and not restated('x + 12', g)
    raw = 'Step 1: AB is 12.\nStep 2: Half of it is 6.\nStep 3: Twice is 24.\nAnswer: 24'
    assert numbered(raw) == [' AB is 12.\n', ' Half of it is 6.\n', ' Twice is 24.'] and numbered(raw.replace('Step 3', 'Step 5')) is None
    assert numbered(raw + '\nmore') is None and numbered('First.\n' + raw) is None and numbered(raw.replace('\nAnswer: 24', '')) is None
    nq = {'kind': 'num', 'gold': 24.0, 'gold_str': '24', 'options': None, 'ref': ['6', '24']}
    p = reward(nq, raw, 'stop', 'steps')  # Amendment 4: results 12 (not a reference result), 6, 24 -> 2 of 3 steps matched
    assert p['fmt'] == p['right'] == p['cons'] == 1 and p['steps'] == 3 and abs(p['rule'] - 2 / 3) < 1e-9, p
    assert abs(p['total'] - (0.10 + 0.25 + 0.75 * 2 / 3 * 1.15)) < 1e-9 and reward(nq, raw, 'stop')['fmt'] == 0
    assert read_steps(raw.replace('Half of it is 6.', 'Look at the half.'))[1] == ['12', None, '24']
    assert rule([None, '6', None], ['6']) == 1 / 3 and reward(nq, 'Answer: 24', 'stop', 'steps')['total'] == 0.25
    one = 'Step 1: AB is 12, half of it is 6, and twice 12 is 24.\nAnswer: 24'  # the whole solution merged into one step
    assert reward(nq, one, 'stop', 'steps')['rule'] == 1 and reward(nq, one, 'stop', 'recall')['rule'] == 0.5  # Amendment 5
    assert reward(nq, raw, 'stop', 'recall')['rule'] == 1 and rule(['6', '7', '8', '24'], ['6', '24'], 2) == 1
    split = raw.replace('Step 3: Twice is 24.', 'Step 3: Twice 12.\nStep 4: That is 20 plus 4.\nStep 5: So 24.')  # the same in 5 steps
    assert reward(nq, split, 'stop', 'recall')['rule'] == 1 and reward(nq, split, 'stop', 'both')['rule'] == 0.4  # Amendment 6
    assert reward(nq, one, 'stop', 'both')['rule'] == 0.5 and abs(reward(nq, raw, 'stop', 'both')['rule'] - 2 / 3) < 1e-9
    # Amendment 7: repeated, boxed and cut-off reference results; a cut response earns nothing; balanced judgment examples
    assert clean_ref(['90', '\\boxed{55°}', '55°', '2.5 \\times', '55', '7', '7']) == ['90', '55°', '7'] and clean_ref(['3 \\times']) == ['3 \\times']
    assert reward(nq, raw, 'length', 'both')['total'] == 0 and reward(nq, raw.replace('Answer: 24', 'Answer: 7'), 'stop', 'both')['total'] == 0.10
    gr = [{'qid': 'q', 'finish': 'stop', 'correct': c, 'text': f'sol{i}', 'image': 'i.png'} for i, c in enumerate([1.0, 0.0, 0.0])]
    bal = aux_examples(gr, {'q': {'text': 'Q'}}, random.Random(0), 'balanced')
    assert [x['target'] for x in bal if x['task'] == 'point'] == ['Correct', 'Incorrect'] and sum(x['task'] == 'pair' for x in bal) == 1
    assert aux_examples(gr[1:], {'q': {'text': 'Q'}}, random.Random(0), 'balanced') == []  # no pointwise example from a one-sided question
    # Amendment 8: values are read without the step marks, so the same solution in 1, 3 or 5 steps scores the same
    eq = 'Step 1: AB = 12.\nStep 2: Half of it = 6, so option (B) is out.\nStep 3: Twice AB = 24.\nAnswer: 24'
    assert all_values(eq) == ['12', '6', 'B', '24'] and in_order(['12', '6', 'B', '24'], ['6', '24']) == 2 and in_order(['24', '6'], ['6', '24']) == 1
    merged = eq.replace('\nStep 2: ', ' ').replace('\nStep 3: ', ' ')
    v3, v1 = reward(nq, eq, 'stop', 'values'), reward(nq, merged, 'stop', 'values')
    assert numbered(merged) is not None and v3['rule'] == v1['rule'] == 1 and v3['values'] == v1['values'] == 4 and v3['total'] == v1['total']
    assert reward(nq, eq.replace('= 6', '= 5'), 'stop', 'values')['rule'] == 0.5 and reward(nq, eq, 'length', 'values')['total'] == 0
    assert [reward(nq, t, f, 'right')['total'] for t, f in ((eq, 'stop'), (eq, 'length'), (eq.replace('Answer: 24', 'Answer: 7'), 'stop'), ('24', 'stop'))] == [1, 0, 0, 0]
    print('selfcheck ok')


if __name__ == '__main__':
    {'build': build, 'selfcheck': selfcheck, 'reward': lambda: reward_round(*sys.argv[2:6]),
     'heldout': lambda: heldout(*sys.argv[2:4]), 'aux': lambda: aux_round(*sys.argv[2:5]),
     'prep_own': prep_own, 'select_own': select_own, 'check_targets': lambda: check_targets(sys.argv[2]),
     'build_hard': build_hard}[sys.argv[1]]()
