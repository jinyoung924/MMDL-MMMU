#!/usr/bin/env python
"""Chemical-structure reading items (targets/protocol.md): skeletal formulas drawn with RDKit from SMILES built here,
so every label is exact. Same item format, splits, report and gate as music/reading.py.

python targets/chem.py test      # -> targets/chem/data/chem_test.jsonl (280 MC items, grpo pool format), images, ids
python targets/chem.py train     # -> targets/chem/data/chem_train.jsonl: other fonts, no test item, each with its reading
python targets/chem.py report RUN.jsonl | gate BASE.jsonl TUNED.jsonl
Runs in the `vllm-train` env (rdkit added there with `pip install --no-deps rdkit`).
"""
import io, json, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'music')]
import reading  # noqa: E402  (make, degrade, report, gate)

D = ROOT / 'targets/chem/data'
TASKS = ['ring_size', 'chain', 'atom_count', 'ring_position', 'locant', 'double_bonds', 'wedge']
FONTS = {'NimbusRoman': '/usr/share/fonts/opentype/urw-base35/NimbusRoman-Regular.otf',
         'NimbusSans': '/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf',
         'DejaVuSans': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
         'DejaVuSerif': '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
         'FreeSans': '/usr/share/fonts/truetype/freefont/FreeSans.ttf'}
TEST_FONT = 'NimbusRoman'  # label font used only for the test set; training data must not use it
TRAIN_FONTS = [f for f in FONTS if f != TEST_FONT]
TRAIN_N = {'ring_size': 350, 'chain': 300, 'atom_count': 300, 'ring_position': 350, 'locant': 300, 'double_bonds': 300, 'wedge': 300}
SUBS = {'Br': 'Br', 'Cl': 'Cl', 'F': 'F', 'I': 'I', 'OH': 'O', 'NH2': 'N', 'SH': 'S'}  # printed label -> SMILES atom
RING_NAMES = {3: 'triangle', 4: 'square', 5: 'pentagon', 6: 'hexagon', 7: 'heptagon', 8: 'octagon'}
RELATION = {1: 'on the same ring carbon (1,1)', 2: 'on adjacent ring carbons (1,2)',
            3: 'one ring carbon apart (1,3)', 4: 'on opposite ring carbons (1,4)'}
BOND = {'wedge': 'as a solid wedge', 'dash': 'as a hashed (dashed) wedge', 'plain': 'as a plain line'}
SKELETAL = 'In a skeletal formula every corner and every unlabelled line end is a carbon atom.'


def near(rng, g, lo, hi):
    """Three wrong whole numbers close to g, inside lo..hi (from the four nearest that fit)."""
    return rng.sample([x for x in (g - 1, g + 1, g - 2, g + 2, g - 3, g + 3) if lo <= x <= hi][:4], 3)


def doubles(rng, bonds, d):
    """d bond positions out of range(bonds), no two next to each other (no cumulated double bonds)."""
    while True:
        pos = sorted(rng.sample(range(bonds), d))
        if all(b - a > 1 for a, b in zip(pos, pos[1:])):
            return pos


def chain_smiles(n, dbl=(), subs=None):
    """Unbranched carbon chain; dbl = positions of double bonds (bond j joins carbons j and j+1); subs = {carbon: label}."""
    subs = subs or {}
    return ''.join(('=' if j - 1 in dbl else '') + 'C' + (f'({SUBS[subs[j]]})' if j in subs else '') for j in range(n))


def ring_smiles(n, dbl=(), subs=None):
    """Carbon ring; the closing bond (n-1) is always single, so dbl only holds positions 0..n-2."""
    subs = subs or {}
    atoms = [('=' if j - 1 in dbl else '') + 'C' + ('1' if j == 0 else '') + ''.join(f'({SUBS[x]})' for x in subs.get(j, []))
             for j in range(n)]
    return ''.join(atoms) + '1'


def listing(labels):
    return ', '.join(labels[:-1]) + (' and ' if len(labels) > 1 else '') + labels[-1]


def item(task, i, rng, wide=False):
    """-> (source, question stem, gold option text, wrong option texts, the exact reading in words).
    source = SMILES, plus ' W:<centre>:<group>:<wedge|dash>' when one bond is drawn as a wedge. i cycles the classes."""
    labels = list(SUBS)
    if task == 'ring_size':
        n = i % 6 + 3
        d = rng.randrange(0, {3: 2, 4: 2, 5: 3, 6: 4, 7: 4, 8: 5}[n])
        dbl = doubles(rng, n - 1, d)
        free = [j for j in range(n)]
        subs = {j: [rng.choice(labels)] for j in rng.sample(free, rng.randrange(0, 3))}
        attached = [x for v in subs.values() for x in v]
        return (ring_smiles(n, dbl, subs), 'How many atoms are in the ring?', str(n), [str(x) for x in near(rng, n, 3, 10)],
                f'{SKELETAL} The ring is a closed {RING_NAMES[n]}: counting its corners gives {n}, so the ring has {n} atoms.'
                + (f" {d} of the ring bonds {'is' if d == 1 else 'are'} drawn as double lines." if d else '')
                + (f' {listing(attached)} {"is" if len(attached) == 1 else "are"} attached to the ring and not part of it.' if attached else ''))
    if task == 'chain':
        n = i % 7 + 3
        subs = {j: rng.choice(labels) for j in rng.sample(range(n), rng.randrange(0, min(3, n) + 1))}
        return (chain_smiles(n, subs=subs), 'How many carbon atoms are in the chain?', str(n), [str(x) for x in near(rng, n, 1, 12)],
                f'{SKELETAL} The zigzag chain has {n - 1} bonds between carbons, so it has {n} carbon atoms.'
                + (f' The labels {listing(sorted(set(subs.values())))} are other atoms attached to the chain, not carbons.' if subs else ''))
    if task == 'atom_count':  # how often one label is drawn
        c, target = i % 4 + 1, rng.choice(labels[:4])
        n = rng.randrange(max(5, c + 2), 10)
        spots = rng.sample(range(n), min(n, c + rng.randrange(0, 3)))
        subs = {j: (target if k < c else rng.choice([x for x in labels if x != target])) for k, j in enumerate(spots)}
        others = sorted({x for x in subs.values() if x != target})
        return (chain_smiles(n, subs=subs), f'How many {target} atoms are drawn in the structure?', str(c),
                [str(x) for x in near(rng, c, 0, 7)],
                f'The label {target} appears {c} time{"s" if c > 1 else ""} in the drawing, each on its own carbon of the chain, so there '
                f'{"are" if c > 1 else "is"} {c} {target} atom{"s" if c > 1 else ""}.'
                + (f' The other label{"s" if len(others) > 1 else ""} ({listing(others)}) {"are" if len(others) > 1 else "is"} not counted.' if others else ''))
    if task == 'ring_position':  # two different groups on a six-membered ring
        r = i % 4 + 1
        aromatic = r != 1 and rng.random() < 0.5
        a, b = rng.sample(labels, 2)
        subs = {0: [a, b]} if r == 1 else {0: [a], r - 1: [b]}
        ring = 'benzene ring (hexagon with three double bonds)' if aromatic else 'cyclohexane ring (plain hexagon)'
        how = {1: 'on that same carbon', 2: 'on the very next ring carbon', 3: 'two carbons further round the ring',
               4: 'three carbons further round the ring, directly opposite'}[r]
        return (ring_smiles(6, (0, 2, 4) if aromatic else (), subs), f'How are the {a} and {b} groups placed on the ring?',
                RELATION[r], [RELATION[x] for x in RELATION if x != r],
                f'The structure is a six-membered {ring}. {a} sits on one ring carbon and {b} sits {how}. '
                f'So the two groups are {RELATION[r]}.')
    if task == 'locant':
        k, x = i % 4 + 1, rng.choice(labels)
        n = rng.randrange(max(4, 2 * k - 1), 10)
        text = lambda j: f'carbon {j}' + (' (the end carbon)' if j == 1 else '')
        return (chain_smiles(n, subs={k - 1: x}), f'Counting from the end of the chain that is nearer to it, which carbon carries the {x} group?',
                text(k), [text(j) for j in range(1, 5) if j != k],
                f'{SKELETAL} The chain has {n} carbon atoms. The {x} label is attached to '
                + ('a carbon at the end of the chain' if k == 1 else f'the carbon that is {k - 1} bond{"s" if k > 2 else ""} away from the nearer chain end')
                + f', so it is on carbon {k}.')
    if task == 'double_bonds':
        d = i % 5
        if rng.random() < 0.7:
            n = rng.randrange(max(5, 2 * d + 1), 11)
            src, shape = chain_smiles(n, doubles(rng, n - 1, d)), f'chain of {n} carbons'
        else:
            n = rng.randrange(max(5, 2 * d), 9)
            src, shape = ring_smiles(n, doubles(rng, n - 1, d)), f'ring of {n} carbons'
        return (src, 'How many carbon-carbon double bonds are drawn?', str(d), [str(x) for x in near(rng, d, 0, 6)],
                f'The structure is a {shape}. A double bond is drawn as two parallel lines between the same two carbons. '
                + (f'{d} bond{"s are" if d > 1 else " is"} drawn that way' if d else 'No bond is drawn that way')
                + f', so there {"are" if d != 1 else "is"} {d} carbon-carbon double bond{"s" if d != 1 else ""}.')
    if task == 'wedge':  # one group on an inner chain carbon, its bond drawn as wedge, dash or plain line
        how, x = ['wedge', 'dash', 'plain'][i % 3], rng.choice(labels)
        a, b = rng.randrange(1, 4), rng.randrange(1, 4)
        tail = 'C' * b
        if rng.random() < 0.5:  # a second group further along the chain, always on a plain line
            y = rng.choice([l for l in labels if l != x])
            tail = 'C' * b + f'C({SUBS[y]})' + 'C' * rng.randrange(1, 3)
        src = 'C' * a + f'C({SUBS[x]})' + tail + ('' if how == 'plain' else f' W:{a}:{a + 1}:{how}')
        shape = {'wedge': 'a solid, filled wedge that is narrow at the chain carbon and wide at the group',
                 'dash': 'a wedge made of short parallel dashes', 'plain': 'a single plain line of even width'}[how]
        means = {'wedge': 'A solid wedge means the group points towards the viewer.',
                 'dash': 'A hashed wedge means the group points away from the viewer.',
                 'plain': 'A plain line shows no direction in space.'}[how]
        return (src, f'How is the bond to the {x} group drawn?', BOND[how], [BOND[h] for h in BOND if h != how],
                f'The bond from the chain carbon to {x} is drawn as {shape}. {means}')
    raise ValueError(task)


def draw(src, font, rng):
    from PIL import Image
    from rdkit import Chem
    from rdkit.Chem import rdDepictor
    from rdkit.Chem.Draw import rdMolDraw2D
    smiles, *mark = src.split(' ')
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(src)
    rdDepictor.Compute2DCoords(mol)
    d = rdMolDraw2D.MolDraw2DCairo(rng.randrange(380, 561), rng.randrange(280, 401))
    o = d.drawOptions()
    o.useBWAtomPalette()
    o.bondLineWidth, o.rotate, o.fontFile, o.padding = rng.uniform(1.3, 2.8), rng.choice([0, 0, 0, 30, -30, 90, 180]), FONTS[font], 0.1
    if mark:  # W:<centre>:<group>:<wedge|dash> -> that bond gets the direction, nothing else is wedged
        _, a, b, how = mark[0].split(':')
        mol = rdMolDraw2D.PrepareMolForDrawing(mol, wedgeBonds=False)
        bond = mol.GetBondBetweenAtoms(int(a), int(b))
        assert bond.GetBeginAtomIdx() == int(a)  # the narrow end is the chain carbon
        bond.SetBondDir(Chem.BondDir.BEGINWEDGE if how == 'wedge' else Chem.BondDir.BEGINDASH)
        o.prepareMolsBeforeDrawing = False
    d.DrawMolecule(mol)
    d.FinishDrawing()
    return reading.degrade(Image.open(io.BytesIO(d.GetDrawingText())).convert('L'), rng, 180, 561, longest=True)


def facts(src):
    """What RDKit itself finds in the molecule; used by the self-check to confirm the labels built in item()."""
    from rdkit import Chem
    mol = Chem.MolFromSmiles(src.split(' ')[0])
    Chem.Kekulize(mol, clearAromaticFlags=True)  # benzene is drawn, and counted, with its three double lines
    rings = mol.GetRingInfo().AtomRings()
    return {'carbons': sum(a.GetSymbol() == 'C' for a in mol.GetAtoms()), 'ring': len(rings[0]) if rings else 0,
            'double': sum(b.GetBondTypeAsDouble() == 2 for b in mol.GetBonds()),
            'symbols': [a.GetSymbol() for a in mol.GetAtoms()], 'mol': mol}


def check(n=400):
    """Labels from item() against what RDKit computes from the same SMILES (independent of the string building)."""
    from rdkit import Chem
    rng = random.Random(123)
    for i in range(n):
        for task in TASKS:
            src, stem, gold, wrong, ref = item(task, i, rng)
            f = facts(src)
            mol = f['mol']
            assert len({gold, *wrong}) == len(wrong) + 1, (task, gold, wrong)
            if task == 'ring_size':
                assert f['ring'] == int(gold), src
            elif task == 'chain':
                assert f['carbons'] == int(gold) and not f['ring'], src
            elif task == 'atom_count':
                sym = {'OH': 'O', 'NH2': 'N', 'SH': 'S'}.get(stem.split()[2], stem.split()[2])
                assert f['symbols'].count(sym) == int(gold), src
            elif task == 'double_bonds':
                assert f['double'] == int(gold), src
            elif task == 'ring_position':
                het = [a.GetIdx() for a in mol.GetAtoms() if a.GetSymbol() != 'C']
                c1, c2 = (mol.GetAtomWithIdx(h).GetNeighbors()[0].GetIdx() for h in het)
                path = len(Chem.GetShortestPath(mol, c1, c2)) if c1 != c2 else 1
                assert f['ring'] == 6 and len(het) == 2 and RELATION[path] == gold, (src, path, gold)
            elif task == 'locant':
                het = next(a for a in mol.GetAtoms() if a.GetSymbol() != 'C')
                c, ends = het.GetNeighbors()[0].GetIdx(), [a.GetIdx() for a in mol.GetAtoms() if a.GetSymbol() == 'C' and
                                                             sum(n.GetSymbol() == 'C' for n in a.GetNeighbors()) == 1]
                k = min(1 if c == e else len(Chem.GetShortestPath(mol, c, e)) for e in ends)
                assert gold.startswith(f'carbon {k}'), (src, k, gold)
            elif task == 'wedge':
                how = src.split(':')[-1] if ' W:' in src else 'plain'
                assert BOND[how] == gold, src
                if ' W:' in src:
                    a, b = map(int, src.split(':')[1:3])
                    assert mol.GetAtomWithIdx(b).GetSymbol() != 'C' and mol.GetBondBetweenAtoms(a, b) is not None, src
    print(f'check: {n * len(TASKS)} items agree with RDKit')


if __name__ == '__main__':
    assert chain_smiles(4, (1,), {0: 'Br'}) == 'C(Br)C=CC' and ring_smiles(6, (0, 2, 4)) == 'C1=CC=CC=C1'
    assert ring_smiles(6, subs={0: ['Cl'], 3: ['OH']}) == 'C1(Cl)CCC(O)CC1' and listing(['Br', 'Cl', 'OH']) == 'Br, Cl and OH'
    cmd, *rest = sys.argv[1:] or ['']
    common = dict(item=item, draw=draw, tasks=TASKS, out=D, name='chem', key='smiles')
    if cmd == 'check':
        check()
    elif cmd == 'test':
        check()
        reading.make('test', 40, 0, [TEST_FONT], **common)
    elif cmd == 'train':
        check()
        reading.make('train', TRAIN_N, 1, TRAIN_FONTS,
                     exclude={(q['task'], q['smiles']) for q in map(json.loads, open(D / 'chem_test.jsonl'))}, **common)
    elif cmd == 'report':
        reading.report(*rest)
    elif cmd == 'gate':
        reading.gate(*rest)
    else:
        sys.exit(__doc__)
