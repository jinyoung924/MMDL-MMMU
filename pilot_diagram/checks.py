#!/usr/bin/env python3
"""Leakage-negative controls, arithmetic cross-checks, and real processor loss masks."""
import copy
import heapq
import json
import math
from pathlib import Path
import shutil
import tempfile

from common import MODEL, MODEL_REV, PIXELS, load_pilot, sha

HERE = Path(__file__).parent


def check_negative_controls():
    load_pilot(HERE, 'train')
    outcomes = []
    for case in ('original_eval_row','diagnostic_in_training','cross_split_group','tampered_manifest','tampered_image'):
        with tempfile.TemporaryDirectory(prefix='diagram-split-check-') as tmp:
            dst=Path(tmp)
            for name in ('annotations.json','dataset_lock.json','train.jsonl','diagnostic.jsonl'):
                shutil.copyfile(HERE/name,dst/name)
            shutil.copytree(HERE/'images',dst/'images')
            rows=[json.loads(x) for x in (dst/'train.jsonl').read_text().splitlines()]
            diagnostic=[json.loads(x) for x in (dst/'diagnostic.jsonl').read_text().splitlines()]
            if case=='original_eval_row':rows[0]['source_split']='test'
            if case=='diagnostic_in_training':rows[0]=diagnostic[0]
            if case=='cross_split_group':rows[0]['group']=diagnostic[0]['group']
            if case=='tampered_manifest':rows[0]['question']+=' changed'
            if case=='tampered_image':(dst/rows[0]['image']).write_bytes(b'changed')
            (dst/'train.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            if case not in ('tampered_manifest','tampered_image'):
                lock=json.loads((dst/'dataset_lock.json').read_text())
                lock['files']['train.jsonl']=sha(dst/'train.jsonl')
                (dst/'dataset_lock.json').write_text(json.dumps(lock))
            try:load_pilot(dst,'train')
            except ValueError as e:outcomes.append({'case':case,'rejected':True,'reason':str(e)})
            else:raise AssertionError(f'Unsafe input accepted: {case}')
    return outcomes


def check_math():
    edges={1:[(6,5),(2,35)],6:[(5,8),(7,2),(3,12)],3:[(1,2),(7,5),(2,1),(4,3)],7:[(5,4),(4,15)],4:[(5,1)]}
    queue=[(0,1)];seen={};order=[]
    while queue:
        d,u=heapq.heappop(queue)
        if u in seen:continue
        seen[u]=d;order.append(u)
        for v,w in edges.get(u,[]):heapq.heappush(queue,(d+w,v))
    assert order[1:]==[6,7,5,3,2,4]
    assert [seen[i] for i in order]==[0,5,7,11,17,18,20]
    assert 6**2+8**2==10**2
    assert math.isclose(2*(4*math.sqrt(2))**2,8**2)
    for x,y in [(-1,4),(-1,-2)]:assert math.isclose((y-1)**2/9-(x+1)**2/4,1)
    def area(a,b,c):return abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))/2
    for t in [.2,.4,.7]:
        a=(0.,1.);b=(0.,0.);c=(1.,0.);d=(1.,1.);e=(1.,t);f=(1/(1-t),0.)
        assert math.isclose(area(d,e,f),area(b,c,e))
    for s,a in [(9.,3.),(8.,math.sqrt(30)),(12.,7.)]:
        length=math.hypot(s,a)
        strip_width=a*a/length
        assert math.isclose(length*strip_width,a*a)
    assert min([5,5.25,5.5,5.75,6],key=lambda x:abs(x-math.sqrt(30)))==5.5
    for (x,y),target in zip([(1,-1),(3,0),(2,1)],[(1,1),(0,3),(-1,2)]):assert (-y,x)==target
    for (x,y),target in zip([(1,-4),(1,-6),(3,-3),(3,-1)],[(-5,-4),(-5,-6),(-7,-3),(-7,-1)]):assert (-4-x,y)==target
    return {'dijkstra_distances':seen,'geometry_and_coordinate_checks':'passed',
            'scope':'Checks calculations conditional on manually transcribed image features; not independent visual verification.'}


def check_masks():
    from PIL import Image
    from transformers import AutoProcessor
    from train import encode
    proc=AutoProcessor.from_pretrained(MODEL,revision=MODEL_REV,local_files_only=True,**PIXELS)
    rows,_=load_pilot(HERE,'train')
    result=[]
    for row in rows:
        for target in ('answer_only_response','teacher_response'):
            with Image.open(HERE/row['image']) as im:enc=encode(proc,row,im.convert('RGB'),row[target])
            supervised=enc['labels'][0]!=-100
            decoded=proc.tokenizer.decode(enc['input_ids'][0][supervised],skip_special_tokens=False)
            assert decoded==row[target]+'<|im_end|>'
            assert supervised.sum().item()<enc['input_ids'].shape[1]
            result.append({'id':row['id'],'target':target,'sequence_tokens':enc['input_ids'].shape[1],
                           'supervised_tokens':int(supervised.sum())})
    return result


if __name__=='__main__':
    result={'negative_controls':check_negative_controls(),'math':check_math(),'loss_masks':check_masks()}
    (HERE/'checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS: five leakage/tamper negative controls; math cross-checks; all 38 assistant-only loss masks.')
