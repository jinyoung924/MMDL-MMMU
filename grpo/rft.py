#!/usr/bin/env python
"""v7 RFT (v7_protocol.md): fine-tune on the student's own correct responses to items it sometimes solves.

python grpo/rft.py select     # runs/heldout/v7_base.rows.jsonl -> runs/v7/rft_train.jsonl, data/heldout/v7_{seen,all}.txt
python grpo/rft.py train      # -> runs/v7/rft/epoch{1,2} (LoRA adapters)
python grpo/rft.py ids v8 / select v8 / train v8     # v8_protocol.md, outputs under runs/v8
python grpo/rft.py prep v9 / select v9 / train v9    # v9_protocol.md (SDFT-style), outputs under runs/v9
python grpo/rft.py select v10 / train v10            # v10_protocol.md (v9 data + replay), outputs under runs/v10
python grpo/rft.py select v11 / train v11            # v11_protocol.md part 1 (v9 data + long own-style anchors)
python grpo/rft.py select v12 / train v12            # v12_protocol.md (v11 data + long own-correct MC anchors)
Run from the repo root in the `vllm-train` env; merge with `grpo.py merge --adapter runs/v7/rft/epoch2 --out ...`.
"""
import json, random, sys, time
from pathlib import Path

G = Path(__file__).resolve().parent
sys.path[:0] = [str(G), str(G.parent)]
from grpo import LORA_TARGETS, MODEL, PIXELS, REV, chat

OUT = G / 'runs' / (sys.argv[2] if len(sys.argv) > 2 else 'v7')


def rows_by(*files):
    by = {}
    for f in files:
        for r in map(json.loads, open(f)):
            by.setdefault(r['qid'], []).append(r)
    return by


def ids_v8():
    """v8 items (v8_protocol.md): hard numeric items (11/04 base screen: < 2 of 2 correct, not both truncated) and the v7
    MC training candidates with < 4 of 4 correct. 300 random numeric items are held out before any v8 sampling."""
    by = rows_by(G / 'runs/heldout/v7_base.rows.jsonl')
    mc = [q for q in (G / 'data/v7_train_ids.txt').read_text().split() if sum(r['correct'] for r in by[q]) < 4]
    num = [r['qid'] for r in map(json.loads, open(G / 'data/screen_v4.jsonl'))
           if r['correct'] < 2 and r['trunc'] < 2 and r['qid'] not in set(mc)]  # 2 VWI items are in both pools: MC only
    random.Random(0).shuffle(num)
    assert len(num) == 881 and len(mc) == 821
    import hashlib  # VWI sub-questions share a source idx ("838101.4") or an image: such train items leave training
    img = {q['qid']: q['image'] for q in map(json.loads, open(G / 'data/pool_v3.jsonl'))}
    key = lambda q: (q.split('.')[0], hashlib.sha256(open(img[q], 'rb').read()).hexdigest())
    held = {k for q in num[:300] for k in key(q)}
    train = [q for q in num[300:] if not set(key(q)) & held]
    for f, ids in (('heldout/v8_unseen', num[:300]), ('v8_num_train', train), ('v8_num_all', num[:300] + train), ('v8_mc_train', mc)):
        (G / f'data/{f}.txt').write_text('\n'.join(ids) + '\n')


def select_v8():
    """8 base samples per training item (numeric: v8 screen; MC: v7 screen + v8 top-up) -> up to 4 correct responses
    of each item with 1-7 of 8 correct. Stop if fewer than 500 items qualify."""
    pools = [{q['qid']: q for q in map(json.loads, open(G / f'data/{p}.jsonl'))} for p in ('pool_v3', 'pool_v7')]
    h = G / 'runs/heldout'  # rows per pool: 3 numeric qids also exist in pool_v7 (MC rendering of the same VWI item)
    bys = rows_by(h / 'v8_base.rows.jsonl'), rows_by(h / 'v7_base.rows.jsonl', h / 'v8mc_base.rows.jsonl')
    rng, data, items = random.Random(0), [], []
    for pool, by, f in zip(pools, bys, ('v8_num_train', 'v8_mc_train')):
        for qid in (G / f'data/{f}.txt').read_text().split():
            assert len(by[qid]) == 8, qid
            chosen = pick(by[qid], rng, k=4)
            items += [qid] if chosen else []
            data += [{'qid': qid, 'text': pool[qid]['text'], 'image': pool[qid]['image'], 'response': r['text']}
                     for r in chosen]
    print(json.dumps({'items': len(items), 'responses': len(data)}))
    if len(items) < 500:
        sys.exit('fewer than 500 items qualify: stop (v8_protocol.md step 2)')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'rft_train.jsonl').write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in data))


REF = ('\n\nReference solution (to help you understand the method; do not mention it):\n{ref}\n\n'
       'Now solve the problem yourself, step by step, in your own words.')


def prep_v9():
    """v9 (v9_protocol.md): the v8 training items with <= 3 of 8 base correct. The prompt gets the VWI reference
    solution before the CoT suffix; 'text_plain' keeps the normal prompt, which is what training uses."""
    pools = [{q['qid']: q for q in map(json.loads, open(G / f'data/{p}.jsonl'))} for p in ('pool_v3', 'pool_v7')]
    h = G / 'runs/heldout'
    bys = rows_by(h / 'v8_base.rows.jsonl'), rows_by(h / 'v7_base.rows.jsonl', h / 'v8mc_base.rows.jsonl')
    out = []
    for pool, by, f in zip(pools, bys, ('v8_num_train', 'v8_mc_train')):
        for qid in (G / f'data/{f}.txt').read_text().split():
            if sum(r['correct'] for r in by[qid]) <= 3:
                q = pool[qid]
                head, sep, tail = q['text'].rpartition('\nThink step by step')
                assert sep and q['reference'].strip(), qid
                out.append({**q, 'text': head + REF.format(ref=q['reference'].strip()) + sep + tail, 'text_plain': q['text']})
    assert len({q['qid'] for q in out}) == len(out)
    print(json.dumps({'items': len(out)}))
    (G / 'data/pool_v9_ref.jsonl').write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in out))
    (G / 'data/v9_ids.txt').write_text(''.join(q['qid'] + '\n' for q in out))


def select_v9():
    """Up to 2 random correct, finished responses per item that do not mention the reference; stop if < 300 items."""
    pool = {q['qid']: q for q in map(json.loads, open(G / 'data/pool_v9_ref.jsonl'))}
    by = rows_by(G / 'runs/heldout/v9_ref.rows.jsonl')
    rng, data, items = random.Random(0), [], []
    for qid in (G / 'data/v9_ids.txt').read_text().split():
        ok = [r for r in by[qid] if r['correct'] and 'reference' not in r['text'].lower()]
        chosen = rng.sample(ok, min(2, len(ok)))
        items += [qid] if chosen else []
        data += [{'qid': qid, 'text': pool[qid]['text_plain'], 'image': pool[qid]['image'], 'response': r['text']}
                 for r in chosen]
    print(json.dumps({'items': len(items), 'responses': len(data)}))
    if len(items) < 300:
        sys.exit('fewer than 300 items qualify: stop (v9_protocol.md step 2)')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'rft_train.jsonl').write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in data))


def select_v10():
    """v10 (v10_protocol.md): the v9 training data plus the same number of replay responses, i.e. the base's own correct
    responses on items it already solves: numeric v8 training items with >= 7 of 8 correct (up to 4 each), then one
    response each from random v7 MC training items with 4 of 4. Replay items sharing a source id or an exact image
    with the v8 held-out set are skipped."""
    import hashlib
    sdft = [json.loads(l) for l in open(G / 'runs/v9/rft_train.jsonl')]
    pools = [{q['qid']: q for q in map(json.loads, open(G / f'data/{p}.jsonl'))} for p in ('pool_v3', 'pool_v7')]
    key = lambda pool, q: (q.split('.')[0], hashlib.sha256(open(pool[q]['image'], 'rb').read()).hexdigest())
    held = {k for q in (G / 'data/heldout/v8_unseen.txt').read_text().split() for k in key(pools[0], q)}
    ok = lambda pool, q: not set(key(pool, q)) & held
    entry = lambda pool, r: {'qid': r['qid'], 'text': pool[r['qid']]['text'], 'image': pool[r['qid']]['image'],
                             'response': r['text'], 'replay': True}
    h, rng, rep = G / 'runs/heldout', random.Random(0), []
    nb = rows_by(h / 'v8_base.rows.jsonl')
    for qid in (G / 'data/v8_num_train.txt').read_text().split():
        good = [r for r in nb[qid] if r['correct']]
        if len(good) >= 7 and ok(pools[0], qid):
            rep += [entry(pools[0], r) for r in rng.sample(good, 4)]
    mb = rows_by(h / 'v7_base.rows.jsonl')
    mc = [q for q in (G / 'data/v7_train_ids.txt').read_text().split() if sum(r['correct'] for r in mb[q]) == 4]
    rng.shuffle(mc)
    for qid in mc:
        if len(rep) >= len(sdft):
            break
        if ok(pools[1], qid):
            rep.append(entry(pools[1], rng.choice(mb[qid])))
    print(json.dumps({'sdft': len(sdft), 'replay': len(rep), 'replay_numeric': sum(r['qid'] in nb for r in rep)}))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'rft_train.jsonl').write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in sdft + rep))


def select_v11():
    """v11 part 1 (v11_protocol.md): the v9 training data plus the same number of long own-style anchors, i.e. the
    base's own correct, finished responses on the hard numeric v8 training items (any count of 1..8 correct; up to 4
    per item, seed 0), shuffled and cut to the v9 count. v8_num_train already excludes held-out source ids and images;
    the check is repeated."""
    import hashlib
    sdft = [json.loads(l) for l in open(G / 'runs/v9/rft_train.jsonl')]
    pool = {q['qid']: q for q in map(json.loads, open(G / 'data/pool_v3.jsonl'))}
    key = lambda q: (q.split('.')[0], hashlib.sha256(open(pool[q]['image'], 'rb').read()).hexdigest())
    held = {k for q in (G / 'data/heldout/v8_unseen.txt').read_text().split() for k in key(q)}
    rng, rep, nb = random.Random(0), [], rows_by(G / 'runs/heldout/v8_base.rows.jsonl')
    for qid in (G / 'data/v8_num_train.txt').read_text().split():
        good = [r for r in nb[qid] if r['correct'] and r['finish'] == 'stop']
        assert not set(key(qid)) & held, qid
        rep += [{'qid': qid, 'text': pool[qid]['text'], 'image': pool[qid]['image'], 'response': r['text'], 'replay': True}
                for r in rng.sample(good, min(4, len(good)))]
    rng.shuffle(rep)
    rep = rep[:len(sdft)]
    print(json.dumps({'sdft': len(sdft), 'anchor': len(rep), 'anchor_items': len({r['qid'] for r in rep}),
                      'anchor_median_chars': sorted(len(r['response']) for r in rep)[len(rep) // 2]}))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'rft_train.jsonl').write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in sdft + rep))


def select_v12():
    """v12 (v12_protocol.md): v11 data as is (v9 targets + numeric anchors) plus the base's own correct, finished
    responses on the hard MC v8 training items (up to 4 per item, seed 0). Also writes the MC check set: v7 held-out
    items that share no source id or image with any v12 training item."""
    import hashlib
    v11 = [json.loads(l) for l in open(G / 'runs/v11/rft_train.jsonl')]
    pools = {q['qid']: q for p in ('pool_v3', 'pool_v7') for q in map(json.loads, open(G / f'data/{p}.jsonl'))}
    p7 = {q['qid']: q for q in map(json.loads, open(G / 'data/pool_v7.jsonl'))}
    key = lambda pool, q: (q.split('.')[0], hashlib.sha256(open(pool[q]['image'], 'rb').read()).hexdigest())
    held8 = {k for q in (G / 'data/heldout/v8_unseen.txt').read_text().split() for k in key(pools, q)}
    rng, mc, mb = random.Random(0), [], rows_by(G / 'runs/heldout/v7_base.rows.jsonl', G / 'runs/heldout/v8mc_base.rows.jsonl')
    for qid in (G / 'data/v8_mc_train.txt').read_text().split():
        good = [r for r in mb[qid] if r['correct'] and r['finish'] == 'stop']
        assert len(mb[qid]) == 8 and not set(key(p7, qid)) & held8, qid
        mc += [{'qid': qid, 'text': p7[qid]['text'], 'image': p7[qid]['image'], 'response': r['text'], 'replay': True}
               for r in rng.sample(good, min(4, len(good)))]
    data = v11 + mc
    train_keys = {k for d in data for k in (d['qid'].split('.')[0], hashlib.sha256(open(d['image'], 'rb').read()).hexdigest())}
    check = [q for q in (G / 'data/heldout/v7_unseen.txt').read_text().split() if not set(key(p7, q)) & train_keys]
    (G / 'data/heldout/v7_unseen_v12.txt').write_text(''.join(q + '\n' for q in check))
    print(json.dumps({'v9': sum(not d.get('replay') for d in v11), 'num_anchor': sum(bool(d.get('replay')) for d in v11),
                      'mc_anchor': len(mc), 'mc_items': len({d['qid'] for d in mc}),
                      'mc_median_chars': sorted(len(d['response']) for d in mc)[len(mc) // 2], 'mc_check_items': len(check)}))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'rft_train.jsonl').write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in data))


def pick(rows, rng, k=2):
    """rows of one item -> up to k random correct responses if the item has 1..n-1 correct, else []."""
    ok = [r for r in rows if r['correct']]
    return rng.sample(ok, min(k, len(ok))) if 0 < len(ok) < len(rows) else []


def select():
    pool = {q['qid']: q for q in map(json.loads, open(G / 'data/pool_v7.jsonl'))}
    by = {}
    for r in map(json.loads, open(G / 'runs/heldout/v7_base.rows.jsonl')):
        by.setdefault(r['qid'], []).append(r)
    rng, data, items = random.Random(0), [], []
    for qid in (G / 'data/v7_train_ids.txt').read_text().split():
        assert len(by[qid]) == 4, qid
        chosen = pick(by[qid], rng)
        items += [qid] if chosen else []
        data += [{'qid': qid, 'text': pool[qid]['text'], 'image': pool[qid]['image'], 'response': r['text']} for r in chosen]
    print(json.dumps({'items': len(items), 'responses': len(data)}))
    if len(items) < 500:
        sys.exit('fewer than 500 items qualify: stop (v7_protocol.md step 2)')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'rft_train.jsonl').write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in data))
    seen = random.Random(0).sample(items, 100)
    (G / 'data/heldout/v7_seen.txt').write_text('\n'.join(seen) + '\n')
    unseen = (G / 'data/heldout/v7_unseen.txt').read_text().split()
    (G / 'data/heldout/v7_all.txt').write_text('\n'.join(unseen + seen) + '\n')


def encode(proc, d):
    from PIL import Image
    with Image.open(d['image']) as im:
        img = im.convert('RGB')
    prompt = chat(proc, d['text'])
    enc = proc(text=[prompt + d['response'] + '<|im_end|>'], images=[img], return_tensors='pt')
    n = enc['input_ids'].shape[1] - proc(text=[prompt], images=[img], return_tensors='pt')['input_ids'].shape[1]
    return enc, n  # loss on the last n tokens: the response and <|im_end|>


def nll(inner, enc, n):
    """Mean NLL of the last n tokens. As in grpo.py train: hidden states, then the 152k-vocab head in 1024-token
    checkpointed chunks (full fp32 logits of an 8k-token response, plus their gradient, do not fit; 11/08 OOM)."""
    import torch
    from torch.utils.checkpoint import checkpoint

    def chunk_logp(h, t):
        return torch.log_softmax(inner.lm_head(h).float(), -1).gather(-1, t[:, None])[:, 0]
    h = inner.model(**enc, use_cache=False).last_hidden_state[0, -n - 1:-1]
    t = enc['input_ids'][0, -n:]
    return -torch.cat([checkpoint(chunk_logp, h[i:i + 1024], t[i:i + 1024], use_reentrant=False)
                       for i in range(0, n, 1024)]).mean()


def train(epochs=2, lr=1e-4, warmup=20, accum=16, seed=0):
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForImageTextToText, AutoProcessor
    torch.manual_seed(seed)
    proc = AutoProcessor.from_pretrained(MODEL, revision=REV, **PIXELS)
    model = AutoModelForImageTextToText.from_pretrained(MODEL, revision=REV, dtype=torch.bfloat16).to('cuda')
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.0, target_modules=LORA_TARGETS,
                                             bias='none'))
    params = [p for p in model.parameters() if p.requires_grad]
    for p in params:  # fp32 LoRA weights, bf16 autocast forward: as grpo.py train
        p.data = p.data.float()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.enable_input_require_grads()
    model.config.use_cache = False
    model.train()
    inner = model.get_base_model()
    data = [json.loads(l) for l in open(OUT / 'rft_train.jsonl')]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warmup))
    step, t0, log = 0, time.time(), []
    for ep in range(1, epochs + 1):
        order = list(range(len(data)))
        random.Random(seed + ep).shuffle(order)
        for i in range(0, len(order) - accum + 1, accum):  # ponytail: drops the < accum tail of each epoch
            tot = 0.0
            for j in order[i:i + accum]:
                enc, n = encode(proc, data[j])
                with torch.autocast('cuda', dtype=torch.bfloat16):
                    loss = nll(inner, enc.to('cuda'), n)
                (loss / accum).backward()
                tot += loss.item() / accum
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
            step += 1
            log.append({'epoch': ep, 'step': step, 'loss': round(tot, 4), 'sec': round(time.time() - t0)})
            if step % 10 == 0:
                print(log[-1], flush=True)
        model.save_pretrained(OUT / f'rft/epoch{ep}')
        (OUT / 'rft/log.json').write_text(json.dumps({'n': len(data), 'lr': lr, 'accum': accum, 'log': log}, indent=1))


if __name__ == '__main__':
    rng = random.Random(0)
    assert pick([{'correct': True}] * 4, rng) == [] and pick([{'correct': False}] * 4, rng) == []
    assert len(pick([{'correct': True}] * 3 + [{'correct': False}], rng)) == 2
    assert len(pick([{'correct': True}] * 7 + [{'correct': False}], rng, k=4)) == 4
    sel = {'v7': select, 'v8': select_v8, 'v9': select_v9, 'v10': select_v10, 'v11': select_v11,
           'v12': select_v12}.get(OUT.name)  # other runs (music/protocol.md) bring their own rft_train.jsonl and only train
    {'ids': ids_v8, 'prep': prep_v9, 'select': sel, 'train': train}[sys.argv[1]]()
