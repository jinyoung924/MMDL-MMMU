#!/usr/bin/env python
"""v7 RFT (v7_protocol.md): fine-tune on the student's own correct responses to items it sometimes solves.

python grpo/rft.py select     # runs/heldout/v7_base.rows.jsonl -> runs/v7/rft_train.jsonl, data/heldout/v7_{seen,all}.txt
python grpo/rft.py train      # -> runs/v7/rft/epoch{1,2} (LoRA adapters)
python grpo/rft.py ids v8 / select v8 / train v8     # v8_protocol.md, outputs under runs/v8
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
    v8 = OUT.name == 'v8'
    {'ids': ids_v8, 'select': select_v8 if v8 else select, 'train': train}[sys.argv[1]]()
