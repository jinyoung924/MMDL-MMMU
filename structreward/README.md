# structreward/ — StructReward 재현과 어려운 문항 학습 (11/14–11/16)

Qwen3-VL-4B-Instruct로 StructReward(arXiv 2608.08326 v2)를 재현한 실험과, 그 뒤에 이어진 어려운 문항 학습의 코드입니다.
결과와 교훈은 [reports/training_experiments.md](../reports/training_experiments.md) §6에 정리돼 있습니다.
이 문서는 **어느 시도가 어느 파일인지**와 **다시 돌리는 방법**만 다룹니다.

실행 전에 정한 규칙과 실행 중의 모든 기록(시각, 수치, 틀렸던 판단의 정정)은 [protocol.md](protocol.md)에 있습니다.
길지만 시간순이므로, 특정 시도만 보려면 아래 표의 "기록" 열에 적힌 절로 가면 됩니다.

## 시도와 파일

| 시도 | 실행 스크립트 | 기록 (`protocol.md`) | MMMU 결과 폴더 | MMMU (base 65.16) |
|---|---|---|---|---|
| 준비 SFT, 논문 방식 (단계 A) | `chain_a.sh` | Stages and registered rules | `runs/sr_sft_full/` | 52.33 |
| 준비 SFT, 형식 지시로 쓴 자기 풀이 (A2) | `chain_a2.sh` | Amendment 1 | — (쓸 풀이 0개로 중단) | — |
| 형식 지시만 준 base (진단) | `diag_format_eval.py` | Run log 11/15 01:41 | `runs/diag_base_format/` | 64.67 |
| 준비 SFT, 자기 풀이 그대로 (A3) | `chain_a3.sh` | Amendment 2, 3 | `runs/sr_sft3_full/` | 63.44 |
| GRPO 1차: 논문의 과정 점수 | `chain_b.sh` | Amendment 4 | `runs/sr_rl3_r015_full/` | 64.00 |
| GRPO 2차: 참고 결과 수로 나눔 | `chain_b.sh` | Amendment 5 | `runs/sr_rl4_r020_full/` | 61.89 |
| GRPO 3차: 둘 중 큰 수로 나눔 | `chain_b.sh` | Amendment 6 | `runs/sr_rl5_r024_full/` | 63.67 |
| GRPO 4차: 감사에서 찾은 결함 수정 | `chain_b.sh` | Amendment 7 | `runs/sr_rl6_r019_full/` | 62.89 |
| GRPO 5차: KL 계수 0.01 | `chain_b.sh` | Amendment 8 | `runs/sr_rl7_r024_full/` | 62.00 |
| 원인 확인: 과정 점수·판단 과제 없이 | `chain_b.sh` | Run log 11/16 11:21 (diagnostic 6) | `runs/sr_rl8_r024_full/` | 63.78 |
| 어려운 문항 학습 (base에서 출발) | `chain_hard.sh` | Amendment 9 | `runs/hard1_r024_full/` | 64.89 (25회차) |

모든 MMMU 수치는 900문항, seed 0입니다. 1·2·4차는 보호 장치에 걸려 멈춘 시점의 모델을 잰 참고 평가입니다.

## 파일

| 파일 | 내용 |
|---|---|
| `sr.py` | 전부 여기에 있습니다. 데이터 만들기(`build`, `prep_own`, `select_own`, `build_hard`), 학습 풀이 점검(`check_targets`), 보상(`reward`), 판단 과제(`aux`), 안 본 문항 비교(`heldout`), 자체 점검(`selfcheck`) |
| `chain_a.sh`, `chain_a2.sh`, `chain_a3.sh` | 준비 SFT 세 가지. 학습 → 안 본 300문항 → 객관식 점검 → MMMU 개발 평가 |
| `chain_b.sh` | 과정 보상 GRPO. 회차마다 생성 → 보상 → 판단 과제 → 학습 → 보호 장치, 25·50회차 뒤 MMMU 평가 |
| `chain_hard.sh` | 어려운 문항 학습. 정답 여부만 보상, 8회차마다 어려운 문항 점검 |
| `diag_format_eval.py` | 평가 프롬프트에 형식 지시만 덧붙여 base를 평가하는 진단 |
| `protocol.md` | 사전 등록 규칙, 수정 기록(Amendment 1–9), 실행 기록 |

`chain_b.sh`는 다섯 번의 실행과 확인 실행을 환경 변수로 구분합니다. 변수를 주지 않으면 처음 등록한 설정으로 돕니다.

| 변수 | 뜻 | 실행별 값 |
|---|---|---|
| `COLD`, `RUN_NAME` | 출발 모델, 실행 이름 | `sr_sft3`, `sr_rl3` … `sr_rl8` |
| `STEPS` | 과정 점수 읽는 방식 | 1차 `steps`, 2차 `recall`, 3차 `both`, 4·5차 `"both clean"`, 확인 실행 `"right clean"` |
| `TRUNC=` | 잘린 응답을 학습에 넣음 | 4차부터 |
| `NORM=--per-response` | 응답별로 평균한 뒤 합침 | 4차부터 |
| `AUX` | 판단 과제 | 4·5차 `balanced`, 확인 실행 `none` |
| `PROBE`, `PROBE_MAX` | 어려운 문항 점검 주기와 한도 | 4차부터 `8`, `8` |
| `BETA` | KL 계수 | 5차부터 `0.01` |
| `QUESTIONS`, `MAX_ROUNDS` | 회차당 문항 수, 회차 수 | 확인 실행 `40`, `25` |

실행별 정확한 명령은 `protocol.md`의 각 Amendment 끝 "Launch" 줄에 있습니다.

## 다시 돌리려면

```bash
conda activate vllm-train && export HF_HUB_OFFLINE=1
python structreward/sr.py selfcheck          # 보상·읽기 규칙 자체 점검
python structreward/sr.py build              # VisualPRM400K-v1.1-Raw → 준비 SFT 5,000 / RL 풀 1,000 / 안 본 문항 300
bash structreward/chain_a3.sh                # 준비 SFT (자기 풀이)
COLD=sr_sft3 RUN_NAME=sr_rl5 STEPS=both bash structreward/chain_b.sh    # 예: GRPO 3차
python structreward/sr.py build_hard && bash structreward/chain_hard.sh # 어려운 문항 학습
```

체인은 다시 실행하면 이어서 돕니다. GPU 한 장(24GB)에서 준비 SFT는 약 4시간, GRPO 25회차는 약 2.5시간, MMMU 평가는 약 80분 걸립니다.

## 레포에 없는 것

- `data/` (21GB): VisualPRM400K-v1.1-Raw 원본과 `sr.py build`가 만든 풀. `OpenGVLab/VisualPRM400K-v1.1-Raw`의 `annotations.zip`과 `images.zip`을 `data/visualprm_raw/`에 받은 뒤 `sr.py build`로 다시 만듭니다. 어려운 문항 풀은 `grpo/data/pool_v4.jsonl`, `pool_v7.jsonl`과 base 선별 기록에서 `sr.py build_hard`로 만듭니다.
- `runs/`: 회차별 생성 응답, 보상 기록, 점검 응답. 요약 수치는 `protocol.md`와 보고서에 있습니다.
- 어댑터와 병합 모델(`grpo/runs/sr_*`, `grpo/runs/hard1`).
- MMMU 평가의 응답 전문. 점수(`scores.json`)와 base와의 비교(`compare_base_mean.txt`)만 올렸습니다.

## 다시 돌릴 때 주의

- `chain_*.sh`가 도는 동안 그 스크립트를 고치면 안 됩니다. bash가 파일을 읽어 가며 실행합니다. `sr.py`와 `grpo/grpo.py`도 회차마다 새로 읽히므로, 고칠 때는 돌고 있는 실행의 결과가 달라지지 않는지 확인해야 합니다.
- 회차마다 문항이 바뀌므로 보호 장치의 기준은 "변하지 않은 모델을 잘못 멈추는 비율"을 저장된 응답으로 먼저 재 봐야 합니다. 12문항 회차에서 예전 잘림 기준(35%)은 18.5%를 잘못 멈췄습니다.
- 문항 번호가 겹치면 보상이 다른 문항의 정답으로 매겨집니다. `build_hard`는 겹치면 멈춥니다.
