#!/usr/bin/env python3
"""Paired LoRA-SFT pilot: same authenticated train rows, answer vs grounded solution."""
import argparse
import json
import math
from pathlib import Path
import random
import time

from common import MODEL, MODEL_REV, PIXELS, load_pilot, prompt, require, sha

LORA_TARGETS = r'.*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)'


def encode(proc, row, image, target, max_length=6144):
    p = prompt(proc, row)
    # Match the repository's existing SFT convention, with an explicit prefix check.
    prefix = proc(text=[p], images=[image], return_tensors='pt')
    enc = proc(text=[p + target + '<|im_end|>'], images=[image], return_tensors='pt')
    n = prefix['input_ids'].shape[1]
    require(enc['input_ids'].shape[1] <= max_length, f"Sequence too long; no silent truncation: {row['id']}")
    require(enc['input_ids'][0,:n].equal(prefix['input_ids'][0]), 'Prompt/target token boundary mismatch')
    labels = enc['input_ids'].clone()
    labels[:,:n] = -100
    require((labels != -100).sum().item() > 1, 'No supervised target tokens')
    enc['labels'] = labels
    return enc


def main(a):
    import torch
    from PIL import Image
    from transformers import AutoModelForImageTextToText, AutoProcessor
    from peft import LoraConfig, get_peft_model
    rows, lock = load_pilot(a.data, 'train')
    # The loader checks the held-out file, but no held-out example is encoded or passed to the model.
    require(torch.cuda.is_available(), 'GPU unavailable; refusing an accidental CPU training run')
    require(a.epochs > 0 and a.accum > 0, 'Invalid training budget')
    a.out.mkdir(parents=True, exist_ok=False)
    torch.manual_seed(a.seed)
    torch.cuda.manual_seed_all(a.seed)
    random.seed(a.seed)
    proc = AutoProcessor.from_pretrained(MODEL, revision=MODEL_REV, local_files_only=True, **PIXELS)
    proc.tokenizer.padding_side = 'right'
    key = 'teacher_response' if a.target == 'rationale' else 'answer_only_response'
    encoded = []
    token_counts = []
    for row in rows:
        with Image.open(a.data/row['image']) as im:
            enc = encode(proc, row, im.convert('RGB'), row[key], a.max_length)
        token_counts.append({'id':row['id'],'sequence':enc['input_ids'].shape[1],
                             'target':int((enc['labels']!=-100).sum())})
        encoded.append(enc)
    order = []
    rng = random.Random(a.seed)
    for epoch in range(a.epochs):
        indices = list(range(len(rows)))
        rng.shuffle(indices)
        order.extend(indices)
    steps = math.ceil(len(order)/a.accum)
    config = {**{k:str(v) if isinstance(v,Path) else v for k,v in vars(a).items()},
              'model':MODEL,'model_revision':MODEL_REV,'pixels':PIXELS,
              'dataset_lock_sha256':sha(a.data/'dataset_lock.json'),
              'training_script_sha256':sha(Path(__file__)),
              'common_script_sha256':sha(Path(__file__).with_name('common.py')),
              'n_train':len(rows),'n_exposures':len(order),'optimizer_steps':steps,
              'loss':'Mean cross-entropy over assistant target tokens; prompt/image tokens masked.',
              'train_ids':[r['id'] for r in rows], 'exposure_order':[rows[i]['id'] for i in order],
              'token_counts':token_counts,
              'target_tokens_total':sum(x['target'] for x in token_counts)*a.epochs,
              'torch_version':torch.__version__,'gpu':torch.cuda.get_device_name(0)}
    (a.out/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    model = AutoModelForImageTextToText.from_pretrained(MODEL, revision=MODEL_REV, local_files_only=True, dtype=torch.bfloat16).to('cuda')
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=a.rank,lora_alpha=2*a.rank,lora_dropout=0.,target_modules=LORA_TARGETS))
    trainable = [(n,p) for n,p in model.named_parameters() if p.requires_grad]
    require(trainable and all('language_model' in n and 'lora_' in n for n,p in trainable), 'Unexpected trainable weights')
    config['trainable_parameters'] = sum(p.numel() for n,p in trainable)
    config['trainable_module_names'] = [n for n,p in trainable]
    (a.out/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    opt = torch.optim.AdamW([p for n,p in trainable],lr=a.lr,weight_decay=0.)
    sched = torch.optim.lr_scheduler.LambdaLR(opt,lambda s:min(1.,(s+1)/a.warmup))
    model.train()
    start = time.time()
    with (a.out/'metrics.jsonl').open('w') as log:
        for step, pos in enumerate(range(0,len(order),a.accum),1):
            batch = order[pos:pos+a.accum]
            losses = []
            opt.zero_grad(set_to_none=True)
            for index in batch:
                enc = {k:v.to('cuda') for k,v in encoded[index].items()}
                loss = model(**enc).loss
                require(torch.isfinite(loss).item(), 'Nonfinite loss')
                (loss/len(batch)).backward()
                losses.append(loss.item())
            grad_norm = torch.nn.utils.clip_grad_norm_([p for n,p in trainable],1.)
            require(torch.isfinite(grad_norm).item(), 'Nonfinite gradients')
            opt.step()
            sched.step()
            record={'step':step,'steps':steps,'loss':sum(losses)/len(losses),
                    'grad_norm':float(grad_norm),'lr':opt.param_groups[0]['lr'],
                    'elapsed_sec':round(time.time()-start,1)}
            log.write(json.dumps(record)+'\n');log.flush()
            print(json.dumps(record),flush=True)
    require(any(p.detach().abs().max().item()>0 for n,p in trainable if 'lora_B' in n), 'Adapter did not update')
    model.save_pretrained(a.out/'adapter')
    del opt, encoded
    model.gradient_checkpointing_disable()
    model.config.use_cache = True
    model.eval()
    merged = model.merge_and_unload().to('cpu')
    merged.save_pretrained(a.out/'merged')
    proc.save_pretrained(a.out/'merged')
    result={'status':'complete','elapsed_sec':round(time.time()-start,1),
            'peak_gpu_bytes':torch.cuda.max_memory_allocated(),'optimizer_steps':steps,
            'n_train':len(rows),'target':a.target,'dataset_lock_sha256':config['dataset_lock_sha256']}
    (a.out/'complete.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=Path(__file__).parent)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--target',choices=['answer','rationale'],required=True)
    p.add_argument('--seed',type=int,default=0)
    p.add_argument('--epochs',type=int,default=8)
    p.add_argument('--accum',type=int,default=4)
    p.add_argument('--rank',type=int,default=16)
    p.add_argument('--lr',type=float,default=5e-5)
    p.add_argument('--warmup',type=int,default=4)
    p.add_argument('--max-length',type=int,default=6144)
    main(p.parse_args())
