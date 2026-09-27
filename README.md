# Qwen3-VL-4B × MMMU-val — 평가 파이프라인, 실패 진단, 개선 계획

Qwen3-VL-4B-Instruct를 MMMU validation 900문항으로 평가하는 **재현 가능한 파이프라인**과, 그 위에서 한 실패 진단·개선 계획입니다.
fine-tuning한 모델도 체크포인트 경로만 바꿔 같은 조건으로 다시 평가합니다.

| | MMMU val |
|---|---|
| 이 파이프라인 (5 seed 평균 ± 표준편차) | **64.93 ± 0.94** (seed 0–4: 64.33 / 66.56 / 64.78 / 64.22 / 64.78) |
| Qwen 공식 | 67.4 |

## 빠른 시작

```bash
pip install -r requirements.txt                                    # vLLM 0.24.0, RTX 4090 24GB에서 검증
bash eval.sh                                                       # 5 seed × 900문항 → results/ (seed당 약 76분)
bash eval.sh /abs/path/to/checkpoint results_ft                    # fine-tuned 모델 (LoRA는 먼저 병합)
python analyze.py compare results/seed* vs results_ft/seed*        # 같은 seed·같은 문항끼리 전후 비교 (망각 포함)
python analyze.py failures results/seed*                           # 늘 틀림 / 가끔 맞힘 / 늘 맞힘, 잘림·루프 분해
```

같은 명령이면 같은 결과가 나옵니다(같은 seed 재실행 899/900 일치). 설정이 다른 실행은 `analyze.py`가 평균·비교를 거부합니다.

## 폴더

| 경로 | 내용 |
|---|---|
| `run_eval.py` | 평가 1회: 프롬프트 구성 → vLLM 생성 → 채점 → `predictions.jsonl`, `scores.json` |
| `eval.sh` | 한 줄 실행: 5 seed 평가 + 집계 |
| `analyze.py` | 집계(`aggregate`), 실패 분석(`failures`), 사례 추출(`export`), 전후 비교(`compare`) |
| `results/` | 공식 베이스라인 5 seed. 문항별 응답 전문 포함 |
| `ablation/` | 프롬프트·생성 예산·해상도·재현성 실험 |
| `reports/` | 보고서와 문서 (아래 읽는 순서) |
| `failure_diagnosis/` | 실패 유형별 사례집 (이미지·문제·5 seed 응답) |
| `pilot_forgetting/` | 망각 파일럿: PathVQA LoRA-SFT 코드와 평가 결과 |
| `encoder_probe/` | 비전 인코더 탐침 코드와 결과 |
| `cloud/` | RunPod 실행: 환경 설치, 결과 브랜치 push, pod 자동 종료 |
| `runs/` | 클라우드 실행 결과 (`runs/<RUN_NAME>/`, `results/<RUN_NAME>` 브랜치에서 병합됨) |

## 읽는 순서

1. [reports/mmmu_baseline.md](reports/mmmu_baseline.md): 1차 과제 보고서. 파이프라인의 모든 선택과 근거, 공식 수치와의 격차 분석
2. [reports/improvement_strategy.md](reports/improvement_strategy.md): 종합. 시도한 것, 실패 유형과 원인, 학습 방향, 망각 측정 계획. 부록 A에 모든 실행 목록
3. [failure_diagnosis/README.md](failure_diagnosis/README.md): 실패 사례. 판정 절차는 [reports/failure_tagging_protocol.md](reports/failure_tagging_protocol.md)
4. [reports/literature_notes.md](reports/literature_notes.md): 전략에 쓴 문헌
5. [pilot_forgetting/README.md](pilot_forgetting/README.md), [encoder_probe/results.md](encoder_probe/results.md)

## 결과 파일 형식 (팀원 결과와 비교할 때)

- `<run>/predictions.jsonl`: 한 줄 = 한 문항. `id`, `subject`, `img_type`, `topic_difficulty`, `prompt`, `response`(응답 전문),
  `parsed`, `gold`, `correct`, `truncated`(8,192토큰에서 잘림), `fallback_guess`(답을 못 찾아 무작위), `answer_tag_found`.
  서술형 문항의 `parsed`는 `null`입니다(점수에는 영향 없음. 투표 등 후처리 시 `response`에서 다시 파싱).
- `<run>/scores.json`: 과목별 정확도, 30과목 평균, 실행 설정 전체(`config`).
- 문항 `id`가 MMMU와 같으므로 다른 파이프라인 결과와 문항 단위로 맞대어 볼 수 있습니다.

## 레포에 없는 것

- 모델 가중치 (`pilot_forgetting/runs/*/step*`): `pilot_forgetting/train_sft.py`로 다시 만듭니다.
- 탐침 입력 데이터 (`encoder_probe/data/`, 831MB): `python encoder_probe/probe.py data`로 다시 만듭니다.
- 실행 로그, 초기 임시 분석, 수업 과제 안내문.
- 학습·탐침 환경은 평가 환경에 `peft`, `accelerate`(탐침은 `verovio`, `cairosvg`, `scikit-learn`도)를 더한 것입니다.

## 클라우드(RunPod) 실행

실험 한 번의 루프는 네 명령입니다. 자세한 절차와 규칙은 [cloud/README.md](cloud/README.md) §0을 **먼저** 읽으세요.

```bash
bash cloud/local.sh push-code "실험 X"          # ① 로컬 main: 코드 커밋 + push
RUN_NAME=exp_x bash cloud/runpod.sh            # ② pod: 설치 → smoke → 평가 → results/exp_x 브랜치로 자동 push → 종료
bash cloud/local.sh fetch exp_x                # ③ 로컬: runs/exp_x/ 를 받아 analyze.py 로 분석
bash cloud/local.sh merge exp_x                # ④ 로컬: 남길 결과만 main에 병합 (버리면 drop)
```

pod 배포 시 환경변수 `GITHUB_TOKEN`, `RUNPOD_USER_API_KEY`, `PUBLIC_KEY`가 필요합니다. 코드 커밋은 main에만, 결과 커밋은
`results/<RUN_NAME>` 브랜치에만 쌓이며 결과 브랜치는 `runs/<RUN_NAME>/` 아래 파일만 추가하므로 병합 충돌이 나지 않습니다.
