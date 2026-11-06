#!/usr/bin/env python3
"""External pilot diagnostic, NOT the official MMMU score. No labels in prompts."""
import argparse
import json
import os
from pathlib import Path
import random
import time

from common import MODEL, MODEL_REV, PIXELS, load_pilot, prompt, sha
from run_eval import ANSWER_TAG_MC


def main(a):
    rows, lock = load_pilot(a.data, a.split)
    a.out.mkdir(parents=True, exist_ok=False)
    os.environ['VLLM_BATCH_INVARIANT'] = '1'
    random.seed(a.seed)
    from PIL import Image
    from transformers import AutoProcessor
    from vllm import LLM, SamplingParams
    rev = None if Path(a.model).is_dir() else MODEL_REV
    proc = AutoProcessor.from_pretrained(a.model, revision=rev, **PIXELS)
    inputs = []
    for row in rows:
        with Image.open(a.data/row['image']) as im:
            image = im.convert('RGB')
        inputs.append({'prompt':prompt(proc,row), 'multi_modal_data':{'image':[image]}})
    llm = LLM(model=a.model, revision=rev, dtype='auto', trust_remote_code=True,
              max_model_len=24576, gpu_memory_utilization=0.90,
              limit_mm_per_prompt={'image':7}, seed=a.seed, mm_processor_kwargs=PIXELS)
    sp = SamplingParams(temperature=.7, top_p=.8, top_k=20, repetition_penalty=1.,
                        presence_penalty=1.5, max_tokens=8192, seed=a.seed)
    start = time.time()
    outputs = llm.generate(inputs, sp)
    results = []
    for row, output in zip(rows, outputs):
        answer = output.outputs[0]
        tags = ANSWER_TAG_MC.findall(answer.text)
        parsed = tags[-1].upper() if tags else None
        results.append({'id':row['id'],'split':a.split,'gold':row['answer'],
                        'response':answer.text,'parsed':parsed,'correct':parsed==row['answer'],
                        'truncated':answer.finish_reason=='length','answer_tag_found':bool(tags)})
    (a.out/'predictions.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in results))
    summary = {'n':len(rows),'correct':sum(r['correct'] for r in results),
               'accuracy':sum(r['correct'] for r in results)/len(rows),
               'truncated':sum(r['truncated'] for r in results),'elapsed_sec':time.time()-start,
               'model':a.model,'seed':a.seed,'split':a.split,
               'dataset_lock_sha256':sha(a.data/'dataset_lock.json'),
               'scope':'External train-derived pilot diagnostic; not MMMU and not official score.',
               'parsing':'Existing Answer-tag regex only; absent tag is incorrect, no random fallback.'}
    (a.out/'scores.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=Path(__file__).parent)
    p.add_argument('--split',choices=['train','diagnostic'],default='diagnostic')
    p.add_argument('--model',default=MODEL)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seed',type=int,default=0)
    main(p.parse_args())
