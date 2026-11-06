#!/usr/bin/env python3
"""Full-900, paired-seed accuracy comparison; no forgetting selection/metric."""
import json
from pathlib import Path
import statistics

import numpy as np
from common import ROOT, require

HERE=Path(__file__).parent
RUNS=HERE/'runs'


def load_runs(root, expected_config=None, expected_rows=None):
    arrays=[];all_rows=[];scores=[]
    for seed in range(5):
        folder=root/f'seed{seed}'
        score=json.loads((folder/'scores.json').read_text())
        cfg=score['config']
        require(cfg['seed']==seed and score['n_questions']==900,'Missing/misidentified full evaluation')
        require(cfg['limit']==0 and not cfg['ids_file'],'Subset evaluation forbidden here')
        clean={k:v for k,v in cfg.items() if k not in ('model','out','seed')}
        if expected_config is None:expected_config=clean
        require(clean==expected_config,'Evaluation settings differ')
        data=[json.loads(x) for x in (folder/'predictions.jsonl').read_text().splitlines()]
        require(len(data)==900 and len({x['id'] for x in data})==900,'Duplicate/missing evaluation IDs')
        rows={r['id']:r for r in data}
        if expected_rows is None:expected_rows=rows
        require(set(rows)==set(expected_rows),'Question sets differ')
        for rid,row in rows.items():
            require(all(row[k]==expected_rows[rid][k] for k in ('prompt','gold','subject')),f'Input/scoring reference changed: {rid}')
        require(all(sum(r['subject']==s for r in data)==30 for s in cfg['subjects']), 'Subject count differs')
        require(len(cfg['subjects'])==30,'Incomplete subjects')
        vector=[int(rows[rid]['correct']) for rid in sorted(rows)]
        require(abs(sum(vector)/900-score['overall_micro'])<1e-10,'Stored score mismatch')
        arrays.append(vector);all_rows.append(rows);scores.append(score)
    return np.array(arrays),expected_config,expected_rows,scores


def delta_summary(base,tuned):
    delta=tuned-base
    rng=np.random.default_rng(0)
    per_question=delta.mean(axis=0)
    boot=np.array([rng.choice(per_question,size=len(per_question),replace=True).mean() for _ in range(10000)])
    return {'delta_percentage_points':float(delta.mean()*100),
            'question_bootstrap_95ci_pp':(np.quantile(boot,[.025,.975])*100).tolist(),
            'mean_corrected_per_seed':float(((base==0)&(tuned==1)).sum(axis=1).mean()),
            'mean_new_errors_per_seed':float(((base==1)&(tuned==0)).sum(axis=1).mean()),
            'ci_scope':'Question resampling conditional on these five generation seeds and this one training seed; not training-run uncertainty.'}


def main():
    base,cfg,rows,_=load_runs(ROOT/'results')
    results={}
    arrays={'base':base}
    for arm in ('answer','rationale'):
        array,_,_,_=load_runs(RUNS/f'mmmu_{arm}',cfg,rows)
        arrays[arm]=array
    # Check paired intervention identity and schedule, including all training exposures.
    configs=[json.loads((RUNS/f'{arm}_sft/config.json').read_text()) for arm in ('answer','rationale')]
    allowed={'out','target','loss','token_counts','target_tokens_total'}
    require({k:v for k,v in configs[0].items() if k not in allowed}=={k:v for k,v in configs[1].items() if k not in allowed},'Training controls differ beyond target')
    selected_types={'Diagrams','Plots and Charts','Trees and Graphs','Geometric Shapes'}
    mask=np.array([bool(set(rows[rid]['img_type'])&selected_types) for rid in sorted(rows)])
    for name,array in arrays.items():
        acc=array.mean(axis=1)*100
        results[name]={'accuracy_mean_percent':float(acc.mean()),'accuracy_seed_std_pp':float(acc.std(ddof=1)),
                       'seed_accuracy_percent':acc.tolist(),
                       'diagram_group_n':int(mask.sum()),'diagram_group_mean_percent':float(array[:,mask].mean()*100)}
    comparisons={f'{arm}_vs_base':delta_summary(base,arrays[arm]) for arm in ('answer','rationale')}
    comparisons['rationale_vs_answer']=delta_summary(arrays['answer'],arrays['rationale'])
    report={'results':results,'comparisons':comparisons,'training_counts':{'train':19,'held_out_diagnostic':5},
            'interpretation':'19-item feasibility pilot, one training seed per arm. Rationale vs answer changes supervised content and token count; it does not isolate an encoder mechanism.'}
    (HERE/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# 도표 풀이 SFT 파일럿 결과','',
           '원래 train에서 검수한 19개로 학습하고, MMMU validation 900개 전체를 동일한 5개 seed로 평가했다.',
           '학습 데이터와 분리한 외부 진단용 5개는 MMMU 점수에 포함하지 않는다.','',
           '| 모델 | 정확도 평균 ± seed 표준편차 |','|---|---|']
    for name,r in results.items():lines.append(f"| {name} | {r['accuracy_mean_percent']:.2f} ± {r['accuracy_seed_std_pp']:.2f}% |")
    lines.extend(['','| 비교 | 정확도 변화(%p) | 문항 bootstrap 95% 구간 |','|---|---|---|'])
    for name,r in comparisons.items():
        lo,hi=r['question_bootstrap_95ci_pp']
        lines.append(f"| {name} | {r['delta_percentage_points']:+.2f} | [{lo:+.2f}, {hi:+.2f}] |")
    lines.extend(['','19개·학습 seed 1개인 작은 파일럿이다. 구간은 문항을 재표집한 값이며 학습 seed 변동을 포함하지 않는다.',
                  '두 SFT 조건은 같은 문항·정답·학습 순서·업데이트 수를 썼다. 풀이 조건은 정답만 조건보다 감독 토큰 수가 많다.',
                  '따라서 차이는 이 학습 설정에서 풀이를 포함한 효과이며, 시각 인코더의 병목 여부를 직접 증명하지 않는다.'])
    (ROOT/'reports/diagram_pilot_results.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
