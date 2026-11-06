#!/usr/bin/env python3
"""Durable serial GPU job with stage status; fails closed on changed code/data."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from common import MODEL, ROOT, load_pilot, require, sha

HERE=Path(__file__).resolve().parent
RUNS=HERE/'runs'
EVAL_PY='/home/leesg17/miniconda3/envs/vllm/bin/python'
TRAIN_PY='/home/leesg17/miniconda3/envs/vllm-train/bin/python'


def main():
    RUNS.mkdir(exist_ok=True)
    with (RUNS/'job.lock').open('w') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        rows,lock=load_pilot(HERE,'train')
        require(subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()=='solgyu-lee','Wrong branch')
        require(not (RUNS/'status.json').exists(),'Job already initialized; inspect state before rerunning')
        files=[HERE/x for x in ['annotations.json','dataset_lock.json','train.jsonl','diagnostic.jsonl',
                               'train.py','evaluate.py','common.py','compare.py','checks.py','run_pilot.py']]
        files += [ROOT/'run_eval.py',ROOT/'analyze.py']
        snapshot={str(p):sha(p) for p in files}
        (RUNS/'code_and_data_lock.json').write_text(json.dumps(snapshot,indent=2)+'\n')
        state={'pid':os.getpid(),'status':'running','started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),
               'dataset_lock_sha256':sha(HERE/'dataset_lock.json'),'completed_stages':[]}
        def save():
            tmp=RUNS/'status.json.tmp';tmp.write_text(json.dumps(state,indent=2)+'\n');tmp.replace(RUNS/'status.json')
        def stage(name,command):
            require(all(sha(Path(p))==h for p,h in snapshot.items()),'Code/data changed during experiment')
            require(subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()=='solgyu-lee','Branch changed')
            state.update(current_stage=name,command=command,stage_started_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
            save();print(f'START {name}',flush=True)
            env=os.environ.copy();env['PYTHONUNBUFFERED']='1'
            with (RUNS/f'{name}.log').open('x') as log:
                subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
            state['completed_stages'].append(name);save();print(f'DONE {name}',flush=True)
        try:
            stage('integrity_checks',[TRAIN_PY,str(HERE/'checks.py')])
            for arm in ('rationale','answer'):
                stage(f'train_{arm}',[TRAIN_PY,str(HERE/'train.py'),'--target',arm,'--out',str(RUNS/f'{arm}_sft')])
            stage('base_diagnostic',[EVAL_PY,str(HERE/'evaluate.py'),'--out',str(RUNS/'base_diagnostic')])
            for arm in ('rationale','answer'):
                for split in ('diagnostic','train'):
                    stage(f'{arm}_{split}',[EVAL_PY,str(HERE/'evaluate.py'),'--model',str(RUNS/f'{arm}_sft/merged'),
                                          '--split',split,'--out',str(RUNS/f'{arm}_{split}')])
            # All 900 questions, both arms, all five seeds. No early model selection on MMMU.
            for seed in range(5):
                for arm in ('rationale','answer'):
                    out=RUNS/f'mmmu_{arm}/seed{seed}'
                    require(not out.exists(),'Refusing stale/partial official evaluation output')
                    stage(f'mmmu_{arm}_seed{seed}',[EVAL_PY,str(ROOT/'run_eval.py'),'--model',str(RUNS/f'{arm}_sft/merged'),
                                                  '--seed',str(seed),'--out',str(out)])
            for arm in ('rationale','answer'):
                stage(f'aggregate_{arm}',[EVAL_PY,str(ROOT/'analyze.py'),'aggregate',
                                        *[str(RUNS/f'mmmu_{arm}/seed{s}') for s in range(5)]])
            stage('compare',[EVAL_PY,str(HERE/'compare.py')])
            state.update(status='complete',current_stage=None,finished_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'));save()
        except BaseException as error:
            state.update(status='failed',error=repr(error),finished_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'));save()
            raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--launch',action='store_true',help='Detach the serial GPU job and print its PID')
    a=p.parse_args()
    if a.launch:
        RUNS.mkdir(exist_ok=True)
        require(not (RUNS/'status.json').exists(),'Job already initialized')
        with (RUNS/'runner.log').open('x') as log:
            proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve())],cwd=ROOT,
                                  stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        print(json.dumps({'launched_pid':proc.pid,'status_file':str(RUNS/'status.json')}))
    else:main()
