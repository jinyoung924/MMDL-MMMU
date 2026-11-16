#!/usr/bin/env python
"""Music steps 1-2 (music/protocol.md): exam-style score-reading items, rendered from ABC with verovio, exact labels.

python music/reading.py test      # -> music/data/read_test.jsonl (300 MC items, grpo pool format), images, ids
python music/reading.py report music/runs/read_base.jsonl      # per-task accuracy after `grpo.py screen`
python music/reading.py train     # -> music/data/read_train.jsonl: other fonts, no test item, each with its exact reading
python music/reading.py select template   # reading as the solution + v12 anchors -> grpo/runs/music/rft_train.jsonl
python music/reading.py test2 | train2    # round 2 (Amendment 3): notes under a key signature; worn training renders
python music/reading.py train3            # round 3 (Amendment 4): harder positions, steps after the reading, question forms
python music/reading.py cells RUN.jsonl RUN2.jsonl   # round-3 gate: single notes outside the staff, two-note items
python music/reading.py check             # pitch and interval labels of every set against verovio's own note data
python music/reading.py gate music/runs/read_base.jsonl music/runs/read_tuned.jsonl   # paired delta, exit 1 if CI low <= 0
Runs in the `vllm-train` env (verovio, cairosvg).
"""
import io, json, random, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'grpo')]
from run_eval import COT_MC_SUFFIX  # noqa: E402

D = ROOT / 'music/data'
LETTERS = 'CDEFGAB'
SEMI = dict(zip(LETTERS, (0, 2, 4, 5, 7, 9, 11)))
ACC, SIGN = {'': 0, '^': 1, '_': -1}, {'': '', '^': '♯', '_': '♭'}  # ABC accidental -> semitones, printed sign
# A pitch is a diatonic step number: 7 * octave + letter index (C4 = 28). Bottom staff line of each clef:
BOTTOM = {'treble': 30, 'bass': 18, 'alto': 24, 'tenor': 22}  # E4, G2, F3, D3
KEYS = dict(zip(range(-6, 7), 'Gb Db Ab Eb Bb F C G D A E B F#'.split()))  # flats negative, sharps positive
TIMES = '2/4 3/4 4/4 5/4 6/4 3/8 6/8 7/8 9/8 12/8 2/2 3/2'.split()
VALUES = [('/2', 'sixteenth'), ('', 'eighth'), ('3/2', 'dotted eighth'), ('2', 'quarter'), ('3', 'dotted quarter'),
          ('4', 'half'), ('6', 'dotted half'), ('8', 'whole')]  # ABC length at L:1/8, name; ordered by length
TASKS = ['clef', 'pitch', 'keysig', 'timesig', 'duration', 'interval']
TEST_FONT = 'Leland'  # verovio music font used only for the test set; training data must not use it
TRAIN_FONTS = ['Leipzig', 'Bravura', 'Gootville', 'Petaluma']
TRAIN_N = {'pitch': 800, 'interval': 600, 'keysig': 300, 'duration': 300, 'clef': 200, 'timesig': 200}
# round 2 (Amendment 3): notes under a key signature, and training renders worn like scans
KEY_TASKS = ['pitch_key', 'interval_key']
TRAIN2_N = {'clef': 200, 'pitch': 500, 'keysig': 250, 'timesig': 150, 'duration': 250, 'interval': 400,
            'pitch_key': 500, 'interval_key': 300}

# round 3 (Amendment 4): half of the notes outside the five lines, the steps after the reading spelled out,
# several question forms, more C clefs
TRAIN3_N = {'clef': 400, 'pitch': 800, 'pitch_key': 600, 'interval': 600, 'interval_key': 400, 'semitones': 300,
            'keysig': 250, 'duration': 250, 'timesig': 100}
STEM3 = {'clef': ['Which clef is used in this excerpt?', 'Name the clef at the start of this staff.', 'What clef does this staff begin with?'],
         'note': ['Select the name of this note.', 'Name the note shown on the staff.', 'Which note is written here?'],
         'interval': ['Name the interval between the two notes.', 'Name this interval.', 'What interval do these two notes form?'],
         'quality': ['What type of interval is this?', 'Select the quality of this interval.'],
         'semitones': ['How many semitones are there between the two notes?', 'How many semitones apart are the two notes?']}

# --- wording of the exact reading that the generation prompt carries (step 2) ---
CLEF = {'treble': 'treble clef (G clef: its curl wraps around line 2, which is G4)',
        'bass': 'bass clef (F clef: its two dots sit on either side of line 4, which is F3)',
        'alto': 'alto clef (C clef centred on line 3, the middle line, which is middle C)',
        'tenor': 'tenor clef (C clef centred on line 4, which is middle C)'}
ORDER = {1: 'F♯ C♯ G♯ D♯ A♯ E♯'.split(), -1: 'B♭ E♭ A♭ D♭ G♭ C♭'.split()}
SHAPE = {'note': {'sixteenth': 'a filled note head with a stem and two flags', 'eighth': 'a filled note head with a stem and one flag',
                  'quarter': 'a filled note head with a stem and no flag', 'half': 'an open note head with a stem',
                  'whole': 'an open note head without a stem'},
         'rest': {'sixteenth': 'a slanted stroke with two small hooks', 'eighth': 'a slanted stroke with one small hook',
                  'quarter': 'a zigzag-shaped sign', 'half': 'a small block sitting on top of line 3',
                  'whole': 'a small block hanging below line 4'}}
HINT = ('\n\nWhat the image shows (treat this as your own reading of the image; do not mention that it was given):\n{ref}\n\n'
        'Now solve the problem yourself, step by step, in your own words.')
LEAK = re.compile(r'reference|(provided|given|above|stated) (reading|description|information|facts)|we are told|i (was|am) told|'
                  r'as (stated|described|mentioned|noted) (above|in)|according to the (text|note|information|prompt|description)|'
                  r'the description|what the image shows', re.I)  # "We are given a staff" is the model's normal opening


def abc_note(step, acc=''):
    o, l = divmod(step, 7)
    return acc + (LETTERS[l].lower() + "'" * (o - 5) if o >= 5 else LETTERS[l] + ',' * (4 - o))


def semitone(step, acc=''):
    return 12 * (step // 7) + SEMI[LETTERS[step % 7]] + ACC[acc]


def interval(lo, hi):
    """(quality, number) between two (step, accidental) notes, lo below hi; quality None if beyond dim/aug."""
    n = hi[0] - lo[0] + 1
    simple = (n - 1) % 7 + 1
    diff = semitone(*hi) - semitone(*lo) - 12 * ((n - 1) // 7) - (0, 2, 4, 5, 7, 9, 11)[simple - 1]
    names = ({0: 'perfect', 1: 'augmented', -1: 'diminished'} if simple in (1, 4, 5)
             else {0: 'major', -1: 'minor', 1: 'augmented', -2: 'diminished'})
    return names.get(diff), n


def iv_name(q, n):
    return f"{q} {'octave' if n == 8 else {2: '2nd', 3: '3rd'}.get(n, f'{n}th')}"


def key_name(k):
    return 'no sharps or flats' if k == 0 else f"{abs(k)} {'sharp' if k > 0 else 'flat'}{'s' if abs(k) > 1 else ''}"


def pname(step, acc=''):
    return LETTERS[step % 7] + SIGN[acc] + str(step // 7)


def where(o):
    """Staff position in words; o = diatonic steps above the bottom line (-4 .. 12)."""
    if 0 <= o <= 8:
        return f"{'in space' if o % 2 else 'on line'} {o // 2 + 1} of the staff, counted from the bottom"
    return {-1: 'in the space just below the bottom line', -2: 'on the first ledger line below the staff',
            -3: 'just below the first ledger line below the staff', -4: 'on the second ledger line below the staff',
            9: 'in the space just above the top line', 10: 'on the first ledger line above the staff',
            11: 'just above the first ledger line above the staff', 12: 'on the second ledger line above the staff'}[o]


def count_out(clef, o):
    """Ledger positions spelled out from the nearest staff line: 'Counting down ... from line 1 (D3): C3, B2, A2, G2. '"""
    if 0 <= o <= 8:
        return ''
    edge, d = (0, -1) if o < 0 else (8, 1)
    return (f"Counting {'down' if d < 0 else 'up'} one step at a time from line {1 if d < 0 else 5} ({pname(BOTTOM[clef] + edge)}): "
            + ', '.join(pname(BOTTOM[clef] + edge + d * k) for k in range(1, abs(o - edge) + 1)) + '. ')


def begins(clef):
    return f"The staff begins with {'an' if clef == 'alto' else 'a'} {CLEF[clef]}"


def key_acc(k, letter):
    """ABC accidental that key signature k (flats negative) gives to a note letter: '^', '_' or ''."""
    return '^' if k > 0 and letter in 'FCGDAE'[:k] else '_' if k < 0 and letter in 'BEADGC'[:-k] else ''


def key_text(k):
    return f"The key signature has {key_name(k)}: {', '.join(ORDER[1 if k > 0 else -1][:abs(k)])}."


OWN = {'': 'with no accidental in front of it', '^': 'with a sharp sign in front of it',
       '_': 'with a flat sign in front of it', '=': 'with a natural sign in front of it'}


def under_key(k, step, own):
    """-> (effective ABC accidental, why) for a note with its own accidental `own` ('' none, '=' natural) in key k."""
    letter = LETTERS[step % 7]
    if own:
        return ('' if own == '=' else own), f"its own {'natural' if own == '=' else 'sharp' if own == '^' else 'flat'} sign overrides the key signature"
    acc = key_acc(k, letter)
    return acc, (f"the key signature {'sharpens' if acc == '^' else 'flattens'} every {letter}" if acc
                 else f'the key signature does not change {letter}')


def staff(clef):
    b = BOTTOM[clef]
    return (f"lines {' '.join(pname(b + 2 * k) for k in range(5))} and spaces "
            f"{' '.join(pname(b + 2 * k + 1) for k in range(4))}, both from the bottom")


def head(clef, key='C', time=None, unit='1/8'):
    """No M: line = no time signature printed (verovio draws `M:none` as a "0")."""
    return 'X:1\n' + (f'M:{time}\n' if time else '') + f'L:{unit}\nK:{key} clef={clef}\n'


def bars(rng, clef, time, n=2):
    """n measures of random notes inside the staff that fill the meter (unit = eighth note)."""
    num, den = map(int, time.split('/'))
    out = []
    for _ in range(n):
        left, bar = num * 8 // den, []
        while left:
            d = rng.choice([x for x in (1, 2, 4) if x <= left])
            bar.append(abc_note(BOTTOM[clef] + rng.randrange(9)) + (str(d) if d > 1 else ''))
            left -= d
        out.append(' '.join(bar))
    return ' | '.join(out) + ' |]\n'


def item(task, i, rng, wide=False):
    """-> (abc, question stem, gold option text, three distractor texts, the exact reading in words).
    i cycles the classes of the task. wide (training data only) adds a random key signature to `duration` items, so
    that every note and rest value exists outside the test set. The random draws without `wide` must stay as they
    are: the test set is defined by them."""
    clef = rng.choice(list(BOTTOM))
    if task == 'clef':
        clef = list(BOTTOM)[i % 4]
        time = rng.choice(TIMES[:3])
        return (head(clef, KEYS[rng.randrange(-6, 7)], time) + bars(rng, clef, time), 'Which clef is used in this excerpt?',
                f'{clef} clef', [f'{c} clef' for c in BOTTOM if c != clef], begins(clef) + '.')
    if task == 'pitch':  # one whole note, up to two ledger lines below or above the staff
        step, acc = BOTTOM[clef] + rng.randrange(-4, 13), rng.choice(['', '', '', '^', '_'])
        name = lambda s: LETTERS[s % 7] + SIGN[acc]
        sign = {'': 'with no accidental', '^': 'with a sharp sign in front of it', '_': 'with a flat sign in front of it'}[acc]
        return (head(clef, unit='1/1') + abc_note(step, acc) + ' |]\n', 'Select the name of this note.', name(step),
                [name(step + d) for d in rng.sample((-2, -1, 1, 2), 3)],
                f'{begins(clef)}. In this clef the staff has {staff(clef)}. The note head is '
                f'{where(step - BOTTOM[clef])}, {sign}. {count_out(clef, step - BOTTOM[clef])}That position is {pname(step)}, '
                f'so the note is {name(step)}.')
    if task == 'keysig':
        k, time = i % 13 - 6, rng.choice(TIMES[:3])
        near = [x for x in (k - 1, k + 1, -k, k - 2, k + 2) if -6 <= x <= 6 and x != k]
        return (head(clef, KEYS[k], time) + bars(rng, clef, time, 1), 'How many sharps or flats are in the key signature?',
                key_name(k), [key_name(x) for x in rng.sample(sorted(set(near)), 3)],
                f'Between the clef and the time signature, the key signature shows {key_name(k)}'
                + (f": {', '.join(ORDER[1 if k > 0 else -1][:abs(k)])}." if k else '.'))
    if task == 'timesig':
        time = TIMES[i % len(TIMES)]
        num, den = time.split('/')
        near = [t for t in TIMES if t != time and (t.split('/')[0] == num or t.split('/')[1] == den)]
        far = [t for t in TIMES if t != time and t not in near]
        return (head(clef, 'C', time) + bars(rng, clef, time), 'What is the time signature of this excerpt?', time,
                (rng.sample(near, min(3, len(near))) + rng.sample(far, 3))[:3],
                f'Right after the clef, the time signature has {num} on top and {den} at the bottom: {time}.')
    if task == 'duration':  # one note or one rest
        v, rest = i % len(VALUES), (i // len(VALUES)) % 2
        kind = 'rest' if rest else 'note'
        sym = 'z' if rest else abc_note(BOTTOM[clef] + rng.randrange(1, 8))
        near = [x for x in (v - 2, v - 1, v + 1, v + 2) if 0 <= x < len(VALUES)]
        wrong = ([f'{VALUES[x][1]} {kind}' for x in rng.sample(near, 3)] if len(near) >= 3 else
                 [f'{VALUES[x][1]} {kind}' for x in rng.sample([x for x in range(len(VALUES)) if x != v], 3)])
        name = VALUES[v][1]
        shape = SHAPE[kind][name.replace('dotted ', '')] + (', followed by a dot' if 'dotted' in name else '')
        return (head(clef, KEYS[rng.randrange(-6, 7)] if wide else 'C') + sym + VALUES[v][0] + ' |]\n',
                f'What is the value of this {kind}?', f'{name} {kind}', wrong,
                f"The {kind} is drawn as {shape}. That is {'an' if name[0] == 'e' else 'a'} {name} {kind}.")
    if task == 'interval':  # two whole notes, 2nd to 10th
        clef, n = rng.choice(['treble', 'bass']), i % 9 + 2
        while True:
            lo = (BOTTOM[clef] + rng.randrange(-2, 14 - n), rng.choice(['', '', '^', '_']))
            hi = (lo[0] + n - 1, rng.choice(['', '', '^', '_']))
            q, _ = interval(lo, hi)
            if q:
                break
        same = [x for x in (('perfect', 'augmented', 'diminished') if (n - 1) % 7 + 1 in (1, 4, 5)
                            else ('major', 'minor', 'augmented', 'diminished')) if x != q]
        m = rng.choice([x for x in (n - 1, n + 1) if 2 <= x <= 10])
        other = iv_name('perfect' if (m - 1) % 7 + 1 in (1, 4, 5) else rng.choice(['major', 'minor']), m)
        pair = [lo, hi]
        rng.shuffle(pair)
        if n == 8 and pair[0][1] and not pair[1][1]:  # no doubt whether an accidental carries over
            pair.reverse()
        say = lambda p: (f"{where(p[0] - BOTTOM[clef])}{', with a sharp sign' if p[1] == '^' else ', with a flat sign' if p[1] == '_' else ''}"
                         f": {pname(*p)}")
        return (head(clef, unit='1/1') + ' '.join(abc_note(*p) for p in pair) + ' |]\n', 'Name the interval between the two notes.',
                iv_name(q, n), [iv_name(x, n) for x in rng.sample(same, 2)] + [other],
                f'{begins(clef)}; it has {staff(clef)}. The first note is {say(pair[0])}. The second note '
                f'is {say(pair[1])}. So the lower note is {pname(*lo)} and the upper note is {pname(*hi)}. Counting letter names '
                f"from {LETTERS[lo[0] % 7]} up to {LETTERS[hi[0] % 7]} gives {n} ({' '.join(LETTERS[s % 7] for s in range(lo[0], hi[0] + 1))}), "
                f'so the interval number is {n}. {pname(*lo)} up to {pname(*hi)} is {semitone(*hi) - semitone(*lo)} semitones, '
                f'which makes it a {iv_name(q, n)}.'.replace(' a augmented', ' an augmented'))
    if task == 'pitch_key':  # one whole note under a key signature
        k = rng.choice([x for x in range(-6, 7) if x])
        step, own = BOTTOM[clef] + rng.randrange(-4, 13), rng.choice(['', '', '', '', '^', '_', '='])
        acc, why = under_key(k, step, own)
        name = lambda s, a: LETTERS[s % 7] + SIGN[a]
        o = step - BOTTOM[clef]
        return (head(clef, KEYS[k], unit='1/1') + abc_note(step, own) + ' |]\n', 'Select the name of this note.', name(step, acc),
                [name(step, a) for a in ('', '^', '_') if a != acc] + [name(step + rng.choice((-1, 1)), acc)],
                f'{begins(clef)}. In this clef the staff has {staff(clef)}. {key_text(k)} The note head is {where(o)}, {OWN[own]}. '
                f'{count_out(clef, o)}That position is {pname(step)}. {why[0].upper() + why[1:]}, so the note is {name(step, acc)}.')
    if task == 'interval_key':  # two whole notes under a key signature, 2nd to 10th
        clef, n, k = rng.choice(['treble', 'bass']), i % 9 + 2, rng.choice([x for x in range(-6, 7) if x])
        while True:
            low = BOTTOM[clef] + rng.randrange(-2, 14 - n)
            notes = [(low, rng.choice(['', '', '', '^', '_', '='])), (low + n - 1, rng.choice(['', '', '', '^', '_', '=']))]
            (la, lw), (ha, hw) = under_key(k, *notes[0]), under_key(k, *notes[1])
            lo, hi = (low, la), (low + n - 1, ha)
            q, _ = interval(lo, hi)
            if q and not (n == 8 and (notes[0][1] or notes[1][1])):  # octaves: no accidental that might carry over
                break
        same = [x for x in (('perfect', 'augmented', 'diminished') if (n - 1) % 7 + 1 in (1, 4, 5)
                            else ('major', 'minor', 'augmented', 'diminished')) if x != q]
        m = rng.choice([x for x in (n - 1, n + 1) if 2 <= x <= 10])
        other = iv_name('perfect' if (m - 1) % 7 + 1 in (1, 4, 5) else rng.choice(['major', 'minor']), m)
        pair = [(notes[0], lo, lw), (notes[1], hi, hw)]
        rng.shuffle(pair)
        say = lambda p: f'{where(p[0][0] - BOTTOM[clef])}, {OWN[p[0][1]]}: {pname(p[0][0])}; {p[2]}, so it is {pname(*p[1])}'
        return (head(clef, KEYS[k], unit='1/1') + ' '.join(abc_note(*p[0]) for p in pair) + ' |]\n', 'Name the interval between the two notes.',
                iv_name(q, n), [iv_name(x, n) for x in rng.sample(same, 2)] + [other],
                f'{begins(clef)}; it has {staff(clef)}. {key_text(k)} The first note is {say(pair[0])}. The second note is '
                f'{say(pair[1])}. So the lower note is {pname(*lo)} and the upper note is {pname(*hi)}. Counting letter names '
                f"from {LETTERS[lo[0] % 7]} up to {LETTERS[hi[0] % 7]} gives {n} ({' '.join(LETTERS[x % 7] for x in range(lo[0], hi[0] + 1))}), "
                f'so the interval number is {n}. {pname(*lo)} up to {pname(*hi)} is {semitone(*hi) - semitone(*lo)} semitones, '
                f'which makes it a {iv_name(q, n)}.'.replace(' a augmented', ' an augmented'))
    raise ValueError(task)


def spot(rng, clef, lo=-4, hi=12):
    """Staff position for a round-3 note: half of them outside the five lines, where round 2 read worst."""
    outside = [o for o in (-4, -3, -2, -1, 9, 10, 11, 12) if lo <= o <= hi]
    inside = [o for o in range(0, 9) if lo <= o <= hi]
    return BOTTOM[clef] + rng.choice(outside if outside and (not inside or rng.random() < 0.5) else inside)


def read3(clef, k, step, own):
    """One note in words -> (effective ABC accidental, phrase that ends with the note's full name). k = 0: no key signature."""
    if k:
        acc, why = under_key(k, step, own)
    else:
        acc = own
        why = ('it has no accidental and there is no key signature' if not own else
               f"the {'sharp' if own == '^' else 'flat'} sign {'raises' if own == '^' else 'lowers'} it by a semitone")
    o = step - BOTTOM[clef]
    return acc, f'{where(o)}, {OWN[own]}. {count_out(clef, o)}That position is {pname(step)}; {why}, so it is {pname(step, acc)}'


def item3(task, i, rng, wide=True):
    """Round-3 training items -> item()'s five values plus the plain truth (note name, interval name or semitone
    count), which the question may ask for in several forms. Tasks not rebuilt here come from item()."""
    an = lambda name: ('an ' if name[0] in 'aeiou' else 'a ') + name
    tf = lambda claim_true: ('True', ['False']) if claim_true else ('False', ['True'])  # option order stays True, False
    if task == 'clef':
        clef, time = ['treble', 'bass', 'alto', 'tenor', 'alto', 'tenor'][i % 6], rng.choice(TIMES[:3])
        return (head(clef, KEYS[rng.randrange(-6, 7)], time) + bars(rng, clef, time), rng.choice(STEM3['clef']), f'{clef} clef',
                [f'{c} clef' for c in BOTTOM if c != clef], begins(clef) + '.', f'{clef} clef')
    if task in ('pitch', 'pitch_key'):
        clef = rng.choice(list(BOTTOM))
        k = rng.choice([x for x in range(-6, 7) if x]) if task == 'pitch_key' else 0
        step, own = spot(rng, clef), rng.choice(['', '', '', '', '^', '_', '='] if k else ['', '', '', '^', '_'])
        acc, said = read3(clef, k, step, own)
        name = lambda st, a: LETTERS[st % 7] + SIGN[a]
        truth = name(step, acc)
        wrong = ([name(step + d, acc) for d in rng.sample((-2, -1, 1, 2), 3)] if rng.random() < 0.5 else
                 [name(step, a) for a in ('', '^', '_') if a != acc] + [name(step + rng.choice((-1, 1)), acc)])
        src = head(clef, KEYS[k], unit='1/1') + abc_note(step, own) + ' |]\n'
        text = (f"{begins(clef)}. In this clef the staff has {staff(clef)}. {key_text(k) if k else 'There is no key signature.'} "
                f'The note head is {said}.')
        if rng.random() < 0.2:
            claim = truth if i % 2 == 0 else rng.choice(wrong)
            gold, other = tf(i % 2 == 0)
            return (src, f'True or False: this note is {claim}.', gold, other,
                    text + f" The statement says {claim}, which is {'right' if i % 2 == 0 else 'wrong'}.", truth)
        return src, rng.choice(STEM3['note']), truth, wrong, text, truth
    if task in ('interval', 'interval_key', 'semitones'):
        clef, n = rng.choice(['treble', 'bass', 'treble', 'bass', 'alto', 'tenor']), i % 9 + 2
        k = rng.choice([x for x in range(-6, 7) if x]) if task == 'interval_key' or (task == 'semitones' and rng.random() < 0.4) else 0
        while True:
            low = spot(rng, clef, -4, 13 - n)
            steps = (low, low + n - 1)
            owns = [rng.choice(['', '', '', '^', '_', '='] if k else ['', '', '^', '_']) for _ in steps]
            accs = [read3(clef, k, st, own)[0] for st, own in zip(steps, owns)]
            lo, hi = (steps[0], accs[0]), (steps[1], accs[1])
            q, _ = interval(lo, hi)
            if q and not (n == 8 and (owns[0] or owns[1])):  # octaves: no accidental that might carry over
                break
        pair = list(zip(steps, owns))
        rng.shuffle(pair)
        src = head(clef, KEYS[k], unit='1/1') + ' '.join(abc_note(*x) for x in pair) + ' |]\n'
        semis, nat = semitone(*hi) - semitone(*lo), semitone(steps[1]) - semitone(steps[0])
        adj = ([f"the lower note is {'raised' if accs[0] == '^' else 'lowered'}, which makes the gap one semitone {'smaller' if accs[0] == '^' else 'larger'}"] if accs[0] else []) \
            + ([f"the upper note is {'raised' if accs[1] == '^' else 'lowered'}, which makes the gap one semitone {'larger' if accs[1] == '^' else 'smaller'}"] if accs[1] else [])
        assert nat - ACC[accs[0]] + ACC[accs[1]] == semis
        text = (f"{begins(clef)}; it has {staff(clef)}. {key_text(k) if k else 'There is no key signature.'} "
                f'The first note is {read3(clef, k, *pair[0])[1]}. The second note is {read3(clef, k, *pair[1])[1]}. '
                f'So the lower note is {pname(*lo)} and the upper note is {pname(*hi)}. Without accidentals, {pname(steps[0])} up to '
                f"{pname(steps[1])} is {nat} semitones{'; ' + ' and '.join(adj) if adj else ''}. So {pname(*lo)} up to {pname(*hi)} is {semis} semitones.")
        if task == 'semitones':
            wrong = rng.sample([x for x in (semis - 1, semis + 1, semis - 2, semis + 2, semis - 3, semis + 3) if x >= 0][:4], 3)
            return src, rng.choice(STEM3['semitones']), str(semis), [str(x) for x in wrong], text, str(semis)
        simple = (n - 1) % 7 + 1
        base = 'perfect' if simple in (1, 4, 5) else 'major'
        ref = (0, 2, 4, 5, 7, 9, 11)[simple - 1] + 12 * ((n - 1) // 7)
        size = {0: 'exactly that size', -1: 'one semitone smaller', 1: 'one semitone larger', -2: 'two semitones smaller'}[semis - ref]
        full = iv_name(q, n)
        text += (f" Counting letter names from {LETTERS[steps[0] % 7]} up to {LETTERS[steps[1] % 7]} gives {n} "
                 f"({' '.join(LETTERS[x % 7] for x in range(steps[0], steps[1] + 1))}), so the interval number is {n}. "
                 f'{an(iv_name(base, n)).capitalize()} is {ref} semitones; this interval is {size}, so it is {an(full)}.')
        same = [x for x in (('perfect', 'augmented', 'diminished') if base == 'perfect' else ('major', 'minor', 'augmented', 'diminished')) if x != q]
        m = rng.choice([x for x in (n - 1, n + 1) if 2 <= x <= 10])
        names = [iv_name(x, n) for x in rng.sample(same, 2)] + [iv_name('perfect' if (m - 1) % 7 + 1 in (1, 4, 5) else rng.choice(['major', 'minor']), m)]
        form = rng.choice(['name', 'name', 'quality', 'tf'])
        if form == 'quality':
            return (src, rng.choice(STEM3['quality']), q, rng.sample([x for x in ('perfect', 'major', 'minor', 'diminished', 'augmented') if x != q], 3),
                    text, full)
        if form == 'tf':
            claim = full if i % 2 == 0 else rng.choice(names)
            gold, other = tf(i % 2 == 0)
            return (src, f'True or False: the interval between the two notes is {an(claim)}.', gold, other,
                    text + f" The statement says {claim}, which is {'right' if i % 2 == 0 else 'wrong'}.", full)
        return src, rng.choice(STEM3['interval']), full, names, text, full
    return item(task, i, rng, wide=True)


def degrade(img, rng, lo=90, hi=201, longest=False):
    """Grey drawing -> cropped, lightly blurred and JPEG-compressed, like the MMMU scans. Its height (or, with
    `longest`, its longer side) becomes lo..hi-1 px."""
    from PIL import Image, ImageFilter, ImageOps
    img = ImageOps.expand(img.crop(ImageOps.invert(img).getbbox()), 14, 255)
    k, (w, h) = rng.randrange(lo, hi), img.size
    size = (k, round(h * k / w)) if longest and w >= h else (round(w * k / h), k)  # height path: same arithmetic as ever
    img = img.resize((max(1, size[0]), max(1, size[1])), Image.LANCZOS)
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0, 0.7)))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=rng.randrange(40, 91))
    return Image.open(io.BytesIO(buf.getvalue())).convert('RGB')


def raster(tk, abc):
    import cairosvg
    from PIL import Image
    if not tk.loadData(abc):
        raise ValueError(abc)
    png = cairosvg.svg2png(bytestring=tk.renderToSVG(1).encode(), background_color='white', output_width=1400)
    return Image.open(io.BytesIO(png)).convert('L')


def render(tk, abc, rng):
    """ABC -> verovio SVG -> degraded grey image (staff system about 90-200 px tall)."""
    return degrade(raster(tk, abc), rng)


def render_worn(tk, abc, rng):
    """Round-2 training renders only: more of what scanned exam papers do to an excerpt. A slight tilt, heavier
    strokes, a wider size range, sometimes pure black and white, uneven margins and a stray letter beside the staff."""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    img = raster(tk, abc)
    if rng.random() < 0.5:
        img = img.rotate(rng.uniform(-1.5, 1.5), resample=Image.BICUBIC, expand=True, fillcolor=255)
    if rng.random() < 0.25:
        img = img.filter(ImageFilter.MinFilter(3))  # heavier black strokes
    img = degrade(img, rng, 70, 221).convert('L')
    if rng.random() < 0.25:
        t = rng.randrange(120, 200)
        img = img.point(lambda v: 255 if v > t else 0).filter(ImageFilter.GaussianBlur(0.4))
    if rng.random() < 0.4:
        img = ImageOps.expand(img, tuple(rng.randrange(0, 41) for _ in range(4)), 255)
        if rng.random() < 0.5 and img.width > 60:
            ImageDraw.Draw(img).text((rng.randrange(2, 12), rng.randrange(2, 8)), rng.choice(['A', 'B', 'C', 'D', '(a)', '(b)', '1.', '2.']), fill=0)
    return img.convert('RGB')


def draw_music(worn=False):
    import verovio
    tk = verovio.toolkit()

    def draw(abc, font, rng):
        tk.setOptions({'font': font, 'scale': 60, 'pageWidth': 3000, 'adjustPageHeight': True,
                       'adjustPageWidth': True, 'header': 'none', 'footer': 'none'})
        return (render_worn if worn else render)(tk, abc, rng)
    return draw


def make(split, per_task, seed, fonts, exclude=(), item=None, draw=None, tasks=None, out=None, name='read', key='abc'):
    """Items for one split. Test items are unique. Training items may repeat (small tasks; each repeat is a new render)
    but never reuse a (task, source) pair in `exclude` (the test set); their prompt carries the exact reading (HINT) and
    `text_plain` keeps the normal prompt, which is what training uses. The defaults build the Music sets; other targets
    (targets/chem.py) pass their own item(task, i, rng, wide) and draw(source, style, rng) and reuse the rest."""
    item, draw, tasks, out = item or globals()['item'], draw or draw_music(), tasks or TASKS, out or D
    rng, seen, rows, train = random.Random(seed), set(exclude), [], not split.startswith('test')
    (out / f'{name}_{split}').mkdir(parents=True, exist_ok=True)
    for task in tasks:
        for i in range(per_task[task] if train else per_task):
            while True:
                abc, stem, gold, wrong, ref, *truth = item(task, i, rng, wide=train)
                if (task, abc) not in seen and len({gold, *wrong}) == len(wrong) + 1:
                    break
            if not train:
                seen.add((task, abc))
            font = rng.choice(fonts)
            f = out / f'{name}_{split}' / f'{task}_{i}.png'
            draw(abc, font, rng).save(f)
            opts = wrong[:]
            opts.insert(i % (len(wrong) + 1), gold)  # gold letter balanced over the options
            opts = dict(zip('ABCD', opts))
            body = '<image>\n' + stem + '\n' + ''.join(f'({k}) {v}\n' for k, v in opts.items())
            row = {'qid': f'{name}-{split}-{task}-{i}', 'kind': 'mc', 'task': task, 'image': str(f), 'text': body + COT_MC_SUFFIX,
                   'gold': 'ABCD'[i % (len(wrong) + 1)], 'options': opts, key: abc, 'font': font}
            if train:
                row.update(text=body.rstrip('\n') + HINT.format(ref=ref) + '\n' + COT_MC_SUFFIX, text_plain=row['text'],
                           reference=ref, **({'truth': truth[0]} if truth else {}))
            rows.append(row)
    (out / f'{name}_{split}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    (out / f'{name}_{split}_ids.txt').write_text(''.join(r['qid'] + '\n' for r in rows))
    print(f'{split}: {len(rows)} items -> {out / f"{name}_{split}.jsonl"}')


def check(*files):
    """Pitch and interval labels against the notes verovio itself holds after reading the ABC (its MEI): letter,
    octave and the written accidental, or for a note under a key signature the accidental the key gives it.
    verovio keeps the previous piece's key for a following piece in C (the drawing is unaffected, the note data is
    not), so for pieces in C only written accidentals are read."""
    import re, verovio
    tk = verovio.toolkit()
    for f in files:
        n = bad = 0
        for r in map(json.loads, open(f)):
            if not r['task'].startswith(('pitch', 'interval', 'semitones')):
                continue
            assert tk.loadData(r['abc'])
            keyed, notes = '\nK:C ' not in r['abc'], []
            for tag in re.findall(r'<note\b[^>]*>|<accid\b[^>]*>', tk.getMEI()):
                a = dict(re.findall(r'([\w.]+)="([^"]*)"', tag))
                acc = a.get('accid') or (a.get('accid.ges') if keyed else None)
                if tag.startswith('<note'):
                    notes.append([7 * int(a['oct']) + 'cdefgab'.index(a['pname']), acc])
                else:
                    notes[-1][1] = acc or notes[-1][1]
            notes = sorted((st, {'s': '^', 'f': '_'}.get(acc, '')) for st, acc in notes)
            got = (LETTERS[notes[0][0] % 7] + SIGN[notes[0][1]] if r['task'].startswith('pitch') else
                   str(semitone(*notes[1]) - semitone(*notes[0])) if r['task'] == 'semitones' else iv_name(*interval(*notes)))
            n, bad = n + 1, bad + (got != r.get('truth', r['options'][r['gold']]))
        print(f'{Path(f).name}: {n - bad}/{n} pitch and interval labels agree with verovio')
        assert not bad


def abc_steps(abc):
    """(step, own accidental) of every note in the last ABC line."""
    import re
    out = []
    for tok in abc.splitlines()[-1].replace('|]', '').split():
        m = re.match(r"([\^_=]?)([A-Ga-g])([,']*)", tok)
        octave = (5 if m.group(2).islower() else 4) + m.group(3).count("'") - m.group(3).count(',')
        out.append((7 * octave + LETTERS.index(m.group(2).upper()), m.group(1)))
    return out


def cells(*runs):
    """Round-3 gate on the two test sets: single notes outside the five lines >= 90 %, two-note items >= 85 %."""
    import re
    pool = {q['qid']: q for f in ('read_test', 'read_test2') for q in map(json.loads, open(D / f'{f}.jsonl'))}
    agg = {}
    for f in runs:
        for r in map(json.loads, open(Path(f).with_suffix('.rows.jsonl'))):
            q = pool[r['qid']]
            if q['task'].startswith('interval'):
                key = 'two notes'
            elif q['task'].startswith('pitch'):
                o = abc_steps(q['abc'])[0][0] - BOTTOM[re.search(r'clef=(\w+)', q['abc']).group(1)]
                key = 'single note inside the staff' if 0 <= o <= 8 else 'single note outside the staff'
            else:
                continue
            a = agg.setdefault(key, [0, 0])
            a[0], a[1] = a[0] + r['correct'], a[1] + 1
    acc = {k: 100 * a / n for k, (a, n) in agg.items()}
    for k in sorted(agg):
        print(f'{k:30s} {acc[k]:5.1f} %  (n={agg[k][1]})')
    ok = acc['single note outside the staff'] >= 90 and acc['two notes'] >= 85
    print('cells gate (outside the staff >= 90 %, two notes >= 85 %):', 'PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


def task_of(qid):
    return qid.split('-')[2]


def report(f):
    from heldout_compare import boot
    f = Path(f)
    per = {r['qid']: r for r in map(json.loads, open(f))}
    rows = [json.loads(l) for l in open(f.with_suffix('.rows.jsonl'))]
    print(f'{"task":9s} items  acc [95% CI]            truncated  finished acc')
    for t in [*dict.fromkeys(map(task_of, per)), 'all']:
        ids = [q for q in per if t in ('all', task_of(q))]
        m, lo, hi = boot([100 * per[q]['correct'] / per[q]['n'] for q in ids])
        rs = [r for r in rows if t in ('all', task_of(r['qid']))]
        fin = [r['correct'] for r in rs if r['finish'] == 'stop']
        print(f'{t:9s} {len(ids):5d}  {m:5.1f} [{lo:5.1f}, {hi:5.1f}]  {100 * (1 - len(fin) / len(rs)):8.1f} %  '
              f'{100 * sum(fin) / max(1, len(fin)):8.1f}')


def template_row(q):
    """Training row whose solution is the item's exact reading, closed with the option letter (Amendment 2)."""
    return {'qid': q['qid'], 'text': q['text_plain'], 'image': q['image'], 'response':
            f"{q['reference']}\nAmong the options, that is ({q['gold']}) {q['options'][q['gold']]}.\n\nAnswer: {q['gold']}"}


def select(mode, gen=ROOT / 'music/runs/read_train_gen.rows.jsonl', out=ROOT / 'grpo/runs/music/rft_train.jsonl'):
    """Training file = music targets + the v12 anchors (the base's own long correct solutions on hard numeric and MC items).
    mode 'template' (Amendment 2, the one in use): the exact reading itself is the solution, closed with the option letter.
    mode 'own' (first attempt, stopped by its rule): one correct, finished solution per item, written by the base with
    the reading in its prompt, that does not give the hint away; stops if a task keeps < 60 % of its items."""
    from grpo import correct
    pool = {q['qid']: q for q in map(json.loads, open(D / 'read_train.jsonl'))}
    anchors = [d for d in map(json.loads, open(ROOT / 'grpo/runs/v12/rft_train.jsonl')) if d.get('replay')]
    if mode == 'template':
        data = [template_row(q) for q in pool.values()]
        assert all(correct(pool[d['qid']], d['response'], 'stop') == 1.0 for d in data)
        chars = sorted(len(d['response']) for d in data)
        print(json.dumps({'music': len(data), 'music_median_chars': chars[len(chars) // 2], 'anchors': len(anchors)}))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in data + anchors))
        return
    by, rng, data, leak = {}, random.Random(0), [], 0
    for r in map(json.loads, open(gen)):
        by.setdefault(r['qid'], []).append(r)
    for qid, q in pool.items():
        ok = [r for r in by.get(qid, []) if r['correct'] and r['finish'] == 'stop']
        clean = [r for r in ok if not LEAK.search(r['text'])]
        leak += len(ok) - len(clean)
        if clean:
            data.append({'qid': qid, 'text': q['text_plain'], 'image': q['image'], 'response': rng.choice(clean)['text']})
    kept = {t: sum(task_of(d['qid']) == t for d in data) / TRAIN_N[t] for t in TASKS}
    chars = sorted(len(d['response']) for d in data)
    print(json.dumps({'music': len(data), 'kept': {t: round(v, 3) for t, v in kept.items()}, 'dropped_for_leak': leak,
                      'music_median_chars': chars[len(chars) // 2], 'anchors': len(anchors)}))
    if min(kept.values()) < 0.6:
        sys.exit('a task keeps fewer than 60 % of its items: stop (music/protocol.md step 2)')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in data + anchors))


def gate(fb, ft):
    """Paired per-item delta (tuned - base) with a bootstrap CI over items; exit code 1 unless the CI low is > 0."""
    from heldout_compare import boot, load
    b, t = load(fb), load(ft)
    assert set(b) == set(t) and all(b[q]['n'] == t[q]['n'] for q in b)
    acc = lambda r: 100 * r['correct'] / r['n']
    for name in [*dict.fromkeys(map(task_of, b)), 'all']:
        ids = [q for q in b if name in ('all', task_of(q))]
        d, lo, hi = boot([acc(t[q]) - acc(b[q]) for q in ids])
        print(f'{name:9s} n={len(ids):3d}  {sum(acc(b[q]) for q in ids) / len(ids):5.1f} -> {sum(acc(t[q]) for q in ids) / len(ids):5.1f}'
              f'  Δ {d:+6.2f} [{lo:+.2f}, {hi:+.2f}]  trunc {100 * sum(b[q]["trunc"] for q in ids) / sum(b[q]["n"] for q in ids):.1f}'
              f' -> {100 * sum(t[q]["trunc"] for q in ids) / sum(t[q]["n"] for q in ids):.1f} %')
    sys.exit(0 if lo > 0 else 1)  # lo of the last row = all items


if __name__ == '__main__':
    assert [abc_note(28), abc_note(35, '^'), abc_note(18), abc_note(42, '_')] == ['C', '^c', 'G,,', "_c'"]
    assert interval((16, ''), (24, '^')) == ('major', 9) and interval((27, '_'), (33, '_')) == ('minor', 7)  # E2-F#3, Bb3-Ab4
    assert interval((29, ''), (38, '^')) == ('major', 10) and interval((28, ''), (35, '')) == ('perfect', 8)
    assert interval((28, ''), (31, '^')) == ('augmented', 4) and interval((28, '_'), (30, '^'))[0] is None
    assert iv_name('perfect', 8) == 'perfect octave' and iv_name('major', 3) == 'major 3rd' and key_name(-1) == '1 flat'
    assert staff('treble').startswith('lines E4 G4 B4 D5 F5 and spaces F4 A4 C5 E5') and 'F3 A3 C4 E4 G4' in staff('alto')
    assert count_out('tenor', -4) == 'Counting down one step at a time from line 1 (D3): C3, B2, A2, G2. ' and not count_out('bass', 8)
    assert count_out('treble', 10) == 'Counting up one step at a time from line 5 (F5): G5, A5. '
    assert key_acc(2, 'C') == '^' and key_acc(2, 'G') == '' and key_acc(-3, 'A') == '_' and key_acc(-3, 'D') == ''
    assert under_key(-2, 27, '')[0] == '_' and under_key(-2, 27, '=')[0] == '' and under_key(1, 31, '_')[0] == '_'  # B3, B3 natural, F4 flat
    assert begins('alto').startswith('The staff begins with an alto') and begins('bass').startswith('The staff begins with a bass')
    assert where(0).startswith('on line 1') and where(3).startswith('in space 2') and where(8).startswith('on line 5')
    assert LEAK.search('Based on the provided description') and not LEAK.search('We are given a staff. The note is on line 2.')
    cmd, *rest = sys.argv[1:] or ['']
    if cmd == 'test':
        make('test', 50, 0, [TEST_FONT])
    elif cmd == 'train':
        make('train', TRAIN_N, 1, TRAIN_FONTS,
             exclude={(q['task'], q['abc']) for q in map(json.loads, open(D / 'read_test.jsonl'))})
    elif cmd == 'test2':  # round 2: notes under a key signature, same font and rendering as the test set
        make('test2', 50, 2, [TEST_FONT], tasks=KEY_TASKS)
    elif cmd == 'train2':  # round 2: all eight tasks, worn renders, nothing from either test set
        make('train2', TRAIN2_N, 3, TRAIN_FONTS, tasks=list(TRAIN2_N), draw=draw_music(worn=True),
             exclude={(q['task'], q['abc']) for f in ('read_test', 'read_test2') for q in map(json.loads, open(D / f'{f}.jsonl'))})
    elif cmd == 'train3':  # round 3: harder positions, steps after the reading, several question forms
        tests = [q['abc'] for f in ('read_test', 'read_test2') for q in map(json.loads, open(D / f'{f}.jsonl'))]
        make('train3', TRAIN3_N, 4, TRAIN_FONTS, tasks=list(TRAIN3_N), item=item3, draw=draw_music(worn=True),
             exclude={(t, a) for t in TRAIN3_N for a in tests})  # no test content under any task name
    elif cmd == 'cells':
        cells(*rest)
    elif cmd == 'check':
        check(*(rest or sorted(map(str, D.glob('read_*.jsonl')))))
    elif cmd == 'report':
        report(*rest)
    elif cmd == 'select':
        select(*rest)
    elif cmd == 'gate':
        gate(*rest)
    else:
        sys.exit(__doc__)
