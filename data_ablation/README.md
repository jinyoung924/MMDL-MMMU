# 데이터셋별 효과 측정 (data ablation)

외부 데이터셋 하나로 LoRA SFT를 한 뒤, **main의 공식 베이스라인(`results/seed0~4`, 64.93 ± 0.94)과 같은 파이프라인·같은 seed·같은 문항으로 짝 비교**해 그 데이터셋이 MMMU 점수를 얼마나 바꾸는지 잰다. 평가 코드(`run_eval.py`, `eval.sh`, `analyze.py`)는 건드리지 않고 그대로 호출한다.

## 설계

| 항목 | 값 | 이유 |
|---|---|---|
| 비교 방식 | 조건마다 base에서 따로 학습 (단독 비교) | 어느 데이터가 효과를 냈는지 분리 |
| 학습 예산 | **1,500 step × batch 8 = 12,000 예시, 모든 조건 동일** (`STEPS`, `BS`, `ACCUM`) | 데이터 양이 아니라 데이터 내용의 차이를 잰다 |
| 학습 방식 | LoRA r=16, lr 1e-4, cosine, 언어모델 q/k/v/o/gate/up/down만 (pilot_forgetting과 동일) | 파일럿과 같은 조건이라 그 결과와 비교 가능 |
| 프롬프트 | `run_eval.build_prompt(style="cot")` — 평가와 **같은 문구** | 학습한 행동 = 평가가 재는 행동 |
| 손실 | 응답 전체(풀이 + `Answer: X` 줄) | 파일럿 교훈: 답만 학습하면 풀이 습관이 무너짐 |
| 평가 | `eval.sh` 그대로 (CoT 프롬프트, 8,192 토큰, 결정적 모드) | main과 문항 단위 비교 가능 |
| 1차 선별 | seed 0·1 (조건당 평가 2회) | 비용 절감 |
| 2차 확정 | 1차에서 CI가 0을 벗어난 조건만 seed 0~4 | main과 같은 조건의 최종 수치 |
| 판정 | `analyze.py compare` + `summarize.py`: Δ 전체 [95% CI], Δ 표적/비표적 과목, 잘림·태그 비율 | 표적에서 오르고 비표적에서 안 떨어져야 채택 |

## 조건

| 조건 | 데이터 | 표적 실패 유형 | 응답(풀이) 출처 | 오염 검사 |
|---|---|---|---|---|
| `cosyn` | `allenai/CoSyn-400K` chemical·circuit·music·chart·diagram, 하위셋당 2,400 (이미지당 QA 2개) | P 지각: 화학 구조식, 회로, 악보, 그래프, 다이어그램 | 데이터셋의 explanation | 텍스트만 (코드로 렌더링한 합성 이미지) |
| `vwi` | `TIGER-Lab/VisualWebInstruct` conversation 중 **웹 수집분(`visualwebinstruct/` 이미지)만**, 단일 턴, 최종 답 추출 가능한 것 | R·K STEM (수학·물리·화학·공학·금융) | 데이터셋의 GPT-4o 풀이 + `Answer:` 줄 추가 | 이미지 + 텍스트 |
| `pmcvqa` | `xmcmic/PMC-VQA` train.csv 4지선다, 병리·현미경 키워드 50% 우선 | P 의학 영상 | **self-CoT**: base 모델이 평가 프롬프트로 4개 생성, 정답인 것 중 가장 짧은 것 (RFT) | 이미지 + 텍스트 |

`pmcvqa`만 풀이 출처가 다르다(데이터셋에 풀이가 없음). 이것이 교란 변수라고 판단되면 `COT_SOURCE=self`로 세 조건 모두 self-CoT로 맞출 수 있다.

## 실행 (RunPod, A100 80GB)

코드는 이 브랜치를 push한 뒤 pod에서 clone한다. `cloud/runpod.sh`가 환경 설치, `results/<RUN_NAME>` 브랜치 push, pod 종료를 맡는다(`cloud/README.md`).

```bash
git clone -b data-ablation https://github.com/jinyoung924/MMDL-MMMU.git /workspace/MMDL-MMMU && cd /workspace/MMDL-MMMU

# 1차 선별: 조건 하나 = pod 하나 (세 조건을 세 pod에서 동시에 돌려도 됨). 끝나도 pod를 살려 둔다.
TRAIN=1 RUN_NAME=abl_cosyn  SEEDS="0 1" AUTO_TERMINATE=0 RUN_CMD='bash data_ablation/run_condition.sh cosyn'  nohup bash cloud/runpod.sh &
TRAIN=1 RUN_NAME=abl_vwi    SEEDS="0 1" AUTO_TERMINATE=0 RUN_CMD='bash data_ablation/run_condition.sh vwi'    nohup bash cloud/runpod.sh &
TRAIN=1 RUN_NAME=abl_pmcvqa SEEDS="0 1" AUTO_TERMINATE=0 RUN_CMD='bash data_ablation/run_condition.sh pmcvqa' nohup bash cloud/runpod.sh &

# 2차 확정: 같은 pod, 같은 RUN_NAME. 학습·병합과 끝난 seed는 건너뛰고 seed 2~4만 평가한다.
SEEDS="0 1 2 3 4" bash data_ablation/run_condition.sh cosyn && bash cloud/push_results.sh runs/abl_cosyn
```

로컬에서 결과를 모으고 표를 만든다.

```bash
bash cloud/local.sh fetch abl_cosyn; bash cloud/local.sh fetch abl_vwi; bash cloud/local.sh fetch abl_pmcvqa
python data_ablation/summarize.py --runs runs/abl_cosyn runs/abl_vwi runs/abl_pmcvqa --out data_ablation/results.md
```

처음 돌리기 전에 데이터 스키마를 눈으로 확인한다(HF 카드와 다르면 어댑터를 고쳐야 한다):

```bash
python data_ablation/prepare_data.py --dataset cosyn --inspect
python data_ablation/prepare_data.py --dataset vwi --inspect
python data_ablation/prepare_data.py --dataset pmcvqa --inspect
```

### 조건당 예상 시간 (A100 80GB)

| 단계 | cosyn | vwi | pmcvqa |
|---|---|---|---|
| 데이터 준비 | 10분 | 30~60분 (이미지 zip 수십 GB 다운로드) | 30~60분 (images.zip 약 20 GB) |
| 오염 검사 | 5분 (+ 처음 한 번 MMMU test 다운로드 ~3 GB, 보호 인덱스 생성 10~20분) | 10분 | 10분 |
| self-CoT | — | — | 1~2시간 (12k × 4 샘플) |
| 학습 1,500 step | 1~2시간 | 1.5~3시간 (응답 길어 느림) | 1~2시간 |
| 평가 2 seed | 1.5~2.5시간 | 같음 | 같음 |
| **합계** | **약 4~5시간** | **약 5~7시간** | **약 5~7시간** |

`/workspace` 볼륨은 150 GB 이상을 권한다(venv 10 + HF 캐시 15 + VWI/PMC 이미지 아카이브 50 + 병합 체크포인트 9 GB × 조건).

## 산출물 (`runs/<RUN_NAME>/`)

| 경로 | 내용 | git |
|---|---|---|
| `data/manifest.json` | 데이터셋 id, **resolved revision sha**, seed, 건수, 필터 | push |
| `data/decontam_report.json` | 보호 집합 크기, 제거 건수·사유·예시, 제거된 id 전체 | push |
| `data/self_cot_report.json` | 생성 건수, pass-count 분포, 채택 건수 | push |
| `data/raw.jsonl` → `clean.jsonl` → `sft.jsonl`, `images/` | 변환·정화·풀이 채운 레코드 | **ignore** (manifest로 재생성) |
| `train/log.json` | 학습 설정, loss 곡선, code commit | push |
| `train/step1500/`, `step1500_merged/` | 어댑터, 병합 가중치 | **ignore** |
| `eval/seed*/` | `run_eval.py` 산출물 (main과 동일 형식) | push (seed마다) |
| `compare.txt`, `summary.md` | `analyze.py compare`, `summarize.py` 결과 | push |

## 오염 검사 (`decontaminate.py`)

- 보호 집합: `MMMU/MMMU` @ `DATA_REV` 30과목 × dev·validation·test 전부. MMMU-Pro는 MMMU validation·test 문항에서 만들어졌으므로(id에 `validation_`, `test_` 접두) test까지 보호하면 함께 덮인다. `--pro`로 `MMMU/MMMU_Pro` standard를 추가할 수 있다.
- 이미지: 바이트 md5 일치, 64비트 pHash Hamming ≤ 6 (리사이즈·JPEG 재압축은 거리 0, 서로 다른 이미지는 약 30). **크롭은 잡지 못한다**(5% 크롭에서 거리 12). 의심되면 `--phash-dist 12`로 다시 돌려 제거 예시를 눈으로 본다.
- 텍스트: 정규화한 질문의 8-gram이 보호 질문에 하나라도 있으면 제거. 정확 일치도 따로 센다.
- 역방향 오염(Qwen3-VL이 이미 이 데이터로 학습했는지)은 검사할 수 없다. 보고서에 기대 효과를 깎는 요인으로 적는다.

## 새 데이터셋 추가

`prepare_data.py`에 `prep_<name>(a, cfg)` 함수를 하나 추가하고 `DATASETS`에 등록한다. 반환은 `common.py` 형식의 레코드 리스트와 manifest에 넣을 dict. `make_prompt()`로 프롬프트를 만들면 평가와 같은 문구가 보장된다. 풀이가 없는 데이터는 `response=""`로 두면 `run_condition.sh`가 self-CoT로 채운다. `summarize.py`의 `TARGET`에 표적 과목을 적는다.

## 검증 상태

- GPU 없이 확인한 것: 세 어댑터(모의 데이터셋·zip·csv로 전 경로), 오염 검사(pHash 거리 특성, n-gram, 보고서), `summarize.py`와 `analyze.py compare`(main의 seed 파일에 인위적 변화를 준 결과로), 문법·단위 테스트.
- **실제 HF 데이터로는 아직 돌리지 않았다.** VWI의 이미지 아카이브 파일명(`imgs.zip`/`images.zip`)과 내부 경로, PMC-VQA의 `Answer_label` 형식은 카드 기준으로 썼고 `--inspect`로 먼저 확인해야 한다. 어댑터는 이름이 다르면 멈추고 후보 목록을 출력한다.
- 학습·self-CoT·평가는 pod에서 처음 돌릴 때 아래처럼 약 30분짜리 smoke를 한 번 돌려 전 경로를 확인한 뒤 본 실행을 권한다(결과는 베이스라인과 비교 불가, 끝나면 `runs/smoke_*` 삭제).

```bash
SMOKE=1 N_RECORDS=200 MIN_RECORDS=50 STEPS=20 RUN_NAME=smoke_pmcvqa bash data_ablation/run_condition.sh pmcvqa
```
