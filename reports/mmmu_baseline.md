# MMMU-val Baseline Evaluation Report — Qwen3-VL-4B-Instruct
- **재현 커맨드**: `bash scripts/run_mmmu_eval.sh --model_path Qwen/Qwen3-VL-4B-Instruct --data_root ./data/hf_datasets`

---

## 1. 환경 / 재현성

| 항목 | 값 |
|---|---|
| 모델 checkpoint | `Qwen/Qwen3-VL-4B-Instruct` (ebb281ec70b05090aa6165b016eac8ec08e71b17) |
| 추론 백엔드 | vLLM 0.29.0 (torch 2.13.0+cu130, transformers 5.16.1, datasets 4.8.5). Qwen 공식 recipe의 `presence_penalty`를 vLLM `SamplingParams`는 지원하고 `transformers.generate()`는 지원하지 않는다. 배치 추론으로 900문항 처리 시간도 줄인다. Qwen 공식 MMMU 평가 스크립트도 vLLM을 쓴다. |
| 사용 GPU | NVIDIA L4, CUDA 기준 22.0 GiB (nvidia-smi 23,034 MiB), Colab Pro, driver 580.82.07 |
| 실측 peak VRAM | 미측정. vLLM이 `gpu_memory_utilization=0.90`으로 미리 확보하므로 상한은 약 19.8 GiB(22.0 × 0.90)다. 엔진이 별도 프로세스라 로그가 노트북에 남지 않았다. 제출 스크립트는 실측값을 `summary.json`의 `peak_vram`에 기록한다. |
| 총 소요 시간 | 약 2시간 52분 (모델 로드 약 5분 + 추론 약 2시간 47분, 데이터 로드 제외). 아래 주석 참고 |
| 의존성 | [`requirements.txt`](../requirements.txt) (Colab: [`scripts/setup_colab.sh`](../scripts/setup_colab.sh)) |
| 실행 커맨드 | `bash scripts/run_mmmu_eval.sh --model_path <HF repo id 또는 체크포인트 경로> --data_root <MMMU 데이터 캐시 경로>` (전체 예시는 아래) |

```bash
# 1) 의존성 설치 (새 venv 기준. Colab은 bash scripts/setup_colab.sh)
pip install -r requirements.txt

# 2) 평가: 추론 → 채점 → 집계. 결과는 results/<run_tag>/ 에 저장
bash scripts/run_mmmu_eval.sh \
  --model_path Qwen/Qwen3-VL-4B-Instruct \
  --data_root ./data/hf_datasets \
  --run_tag v5_maxtok8192

# 파인튜닝 체크포인트 재평가: 경로와 run_tag만 바꾼다 (나머지 설정은 동일하게 유지)
bash scripts/run_mmmu_eval.sh --model_path /path/to/checkpoint --data_root ./data/hf_datasets --run_tag ft_v1
```

- `--model_path`가 HF repo id면 `--model_revision`(기본값 ebb281ec…)으로 고정해 받고, 로컬 디렉터리면 그대로 읽는다. `--data_root`는 `load_dataset(..., cache_dir=...)`로 넘어가며, 비어 있으면 MMMU를 revision 98e6ac0c…로 내려받는다.
- 산출물: `raw_generations.jsonl`(문항별 원본 응답·토큰 수·종료 사유), `graded_results.csv`, `summary.json`, `results_table.md`(5번 표), `run_config.json`(실행 조건 지문), `environment.json`.
- 같은 `run_tag`에 다른 설정으로 이어 쓰려 하면 `run_config.json` 대조에서 실행을 거부한다. 중단 후 재실행하면 완료된 문항 id는 건너뛴다.
- **제출 결과의 출처.** 5번 표는 [`colab/mmmu_eval_v5.ipynb`](../colab/mmmu_eval_v5.ipynb) 실행 결과([`results/v5_maxtok8192/`](../results/v5_maxtok8192/))다. `scripts/mmmu_eval.py`는 이 노트북의 프롬프트·이미지 처리·채점 셀을 원문 그대로 옮긴 것이고, v5 원본 응답 900건을 재채점(`--grade_only`)해 문항 단위로 불일치 0건임을 확인했다.
- **소요 시간 주석.** 모델 로드는 vLLM 로그 기준 17:21:07→17:26:08(약 5분)이다. 추론 루프 로그는 36개 배치 중 35개까지 누적 162.1분이 남았고, 마지막 배치 로그는 Colab 연결이 끊긴 구간이라 출력에서 유실됐다. 평균 배치 시간(4.6분)을 더해 추정했다.

## 2. 프롬프트

**실제 모델에 들어간 프롬프트 전문** (변수 부분은 `{}`로 표시):

객관식 (`question_type == "multiple-choice"`, 보기 수는 문항에 따라 2~9개):

```
{question}

(A) {option_A}
(B) {option_B}
(C) {option_C}
(D) {option_D}


Answer with the option's letter from the given choices directly.
```

단답형 (`question_type == "open"`):

```
{question}

Answer the question using a single word or phrase.
```

- 시스템 프롬프트는 없다. 위 텍스트를 user 메시지 하나에 담고 vLLM `llm.chat`이 Qwen3-VL chat template을 적용한다.
- 질문과 보기에 있는 `<image N>` 태그 자리에 해당 이미지를 끼워 넣는다(텍스트와 이미지 교차). 태그가 없는 문항은 텍스트 뒤에 이미지를 순서대로 붙인다.
- 마지막 보기 뒤 빈 줄 두 개는 원 구현의 형식(`"{}\n\n{}\n\n..."`에 보기마다 `\n`)을 그대로 따른 결과다.
- **출처**: MMMU 벤치마크 공식 구현 [MMMU-Benchmark/MMMU](https://github.com/MMMU-Benchmark/MMMU)의 `mmmu/configs/llava1.5.yaml`(지시문)과 `mmmu/utils/data_utils.py`의 `construct_prompt`(보기 형식). 이미지 교차 배치는 직접 구현했다(`scripts/mmmu_eval.py`의 `build_chat_content`).
- **선택 이유**: 벤치마크 제작자의 레퍼런스 구현이라 특정 모델에 맞춘 조정이 없고, 파인튜닝 전후를 같은 기준으로 비교하기에 중립적이다. Qwen 공식 스크립트는 다른 프롬프트를 쓰며, 그 영향은 7번에서 분석한다.

## 3. 생성(Decoding) 설정

### 3.1 Sampling recipe

| 파라미터 | 값 |
|---|---|
| `do_sample` | True (vLLM은 `temperature > 0`이면 샘플링하며 별도 `do_sample` 인자가 없다) |
| `temperature` | 0.7 |
| `top_p` | 0.8 |
| `top_k` | 20 |
| `repetition_penalty` | 1.0 |
| `presence_penalty` | 1.5 |
| `seed` | 3407 |

- **출처**: Qwen 공식 Qwen3-VL 저장소 [README의 "Evaluation Reproduction" 섹션](https://github.com/QwenLM/Qwen3-VL)에 Instruct 모델용으로 명시된 값을 그대로 썼다. 같은 저장소의 MMMU 평가 안내([`evaluation/mmmu/README.md`](https://github.com/QwenLM/Qwen3-VL/blob/main/evaluation/mmmu/README.md))에도 동일한 값이 있다. 공식 recipe의 `out_seq_length`(32768)만 3.2의 이유로 줄였다.

### 3.2 생성 예산 / 이미지 해상도

| 파라미터 | 값 |
|---|---|
| `max_new_tokens` | 8192 (공식 32768) |
| 이미지 해상도 처리 (`min_pixels`/`max_pixels` 등) | 프로세서 기본값 유지. 면적 1,048,576 px(이미지당 약 1,024 비주얼 토큰)를 넘는 이미지만 종횡비를 유지해 축소 (984장 중 96장, 9.8%) |
| `max_model_len` | 12,288 (= 생성 8,192 + 프롬프트 4,096) |
| 기타 | bf16, `gpu_memory_utilization=0.90`, `max_num_seqs=8`, CUDA graph 사용 |

**선택 근거**:
- **32768을 쓰지 않은 이유.** KV 캐시는 토큰당 144 KiB(36층 × KV 헤드 8 × 128차원 × K·V 2개 × bf16 2바이트)다. 32768토큰까지 가는 시퀀스 하나가 약 4.5 GiB(프롬프트 포함 최대 4.8 GiB)를 차지해, 가중치를 뺀 L4의 KV 여유로는 동시 처리가 1~2개로 줄어든다. 실제로 32768로 시도했을 때(동시 2개 설정) 400문항에 5.8시간이 걸려 900문항 기준 약 13시간이 예상됐고, Colab 세션 한도를 넘겨 중단했다.
- **8192를 고른 근거.** 2,048토큰 예비 실행에서는 129건(14.3%)이 잘렸고 56.56점이었다. 8,192로 늘리자 잘림이 73건(8.1%)으로 줄고 58.44점이 됐으며, 추론은 약 2시간 47분으로 한 세션 안에 끝났다. 생성 토큰 중앙값은 8이라 대부분의 응답은 예산과 무관하다.
- **`max_model_len`.** 모델 기본값 262,144를 쓰면 KV 캐시에 36 GiB가 필요해 L4에서 초기화가 실패한다. 900문항 프롬프트의 최대 길이가 2,491토큰이므로 프롬프트 몫은 4,096으로 충분하다.
- **이미지 상한.** 프로세서 기본 상한(16,777,216 px)이면 이미지 한 장이 최대 16,384토큰까지 커질 수 있다. MMMU는 문항당 최대 7장이라 프롬프트 예산을 넘길 수 있어 이미지당 약 1,024토큰으로 묶었다. 상한 아래 이미지는 원본 그대로 들어간다.

## 4. 채점(파싱) 방식

- 사용한 파서/로직: MMMU 공식 구현 [`mmmu/utils/eval_utils.py`](https://github.com/MMMU-Benchmark/MMMU/blob/main/mmmu/utils/eval_utils.py)의 `parse_multi_choice_response`, `parse_open_response`, `eval_multi_choice`, `eval_open`을 그대로 이식했다(`scripts/mmmu_eval.py` 2절). 직접 추가한 것은 복수 정답 문자열(`"['42', '42.0']"`)을 리스트로 복원하는 `parse_gold_answer` 하나다.
- 동작 방식 요약:
  - **객관식**: 응답 앞뒤 구두점을 떼고 (1) `(A)` 괄호 형식, (2) 공백으로 둘러싸인 ` A `, (3) 응답이 5단어를 넘으면 보기 텍스트 자체 순으로 후보를 찾는다. 후보가 여럿이면 응답에서 가장 뒤에 나온 것을 고른다. **후보가 없으면 `random.choice`로 무작위 선택한다**(시드 42, 응답 파일 순서대로 채점해 재현 가능).
  - **단답형**: 응답을 문장 단위로 나눠 "is", "answer", "therefore", "=" 같은 표지 뒤의 가장 짧은 구절과 그 안의 숫자를 후보로 뽑는다. 숫자는 소수 둘째 자리 반올림 후 정답과 같으면, 문자열은 정답이 후보에 포함되면 정답으로 본다.
  - 판정은 `graded_results.csv`에 문항별(`pred`, `gold`, `correct`, 토큰 수, `finish_reason`)로 남긴다.

## 5. 결과

| No. | Subject | Data Num | Acc |
|---|---|---|---|
| 1 | Accounting | 30 | 63.33 (19/30) |
| 2 | Agriculture | 30 | 56.67 (17/30) |
| 3 | Architecture_and_Engineering | 30 | 40.00 (12/30) |
| 4 | Art | 30 | 60.00 (18/30) |
| 5 | Art_Theory | 30 | 80.00 (24/30) |
| 6 | Basic_Medical_Science | 30 | 70.00 (21/30) |
| 7 | Biology | 30 | 56.67 (17/30) |
| 8 | Chemistry | 30 | 30.00 (9/30) |
| 9 | Clinical_Medicine | 30 | 66.67 (20/30) |
| 10 | Computer_Science | 30 | 56.67 (17/30) |
| 11 | Design | 30 | 73.33 (22/30) |
| 12 | Diagnostics_and_Laboratory_Medicine | 30 | 40.00 (12/30) |
| 13 | Economics | 30 | 66.67 (20/30) |
| 14 | Electronics | 30 | 43.33 (13/30) |
| 15 | Energy_and_Power | 30 | 60.00 (18/30) |
| 16 | Finance | 30 | 53.33 (16/30) |
| 17 | Geography | 30 | 53.33 (16/30) |
| 18 | History | 30 | 70.00 (21/30) |
| 19 | Literature | 30 | 80.00 (24/30) |
| 20 | Manage | 30 | 46.67 (14/30) |
| 21 | Marketing | 30 | 83.33 (25/30) |
| 22 | Materials | 30 | 43.33 (13/30) |
| 23 | Math | 30 | 53.33 (16/30) |
| 24 | Mechanical_Engineering | 30 | 33.33 (10/30) |
| 25 | Music | 30 | 36.67 (11/30) |
| 26 | Pharmacy | 30 | 56.67 (17/30) |
| 27 | Physics | 30 | 56.67 (17/30) |
| 28 | Psychology | 30 | 73.33 (22/30) |
| 29 | Public_Health | 30 | 86.67 (26/30) |
| 30 | Sociology | 30 | 63.33 (19/30) |
| | **Overall (macro avg)** | **900** | **58.44** |

계산식: `Overall = mean(30개 과목 accuracy)` = 58.44. 과목당 30문항으로 균등하므로 전체 정답 비율(526/900 = 58.44%)과 같다. 문항 유형별로는 객관식 61.39% (520/847), 단답형 11.32% (6/53)다.

## 6. 공식 수치와의 비교

| | Overall (MMMU val) |
|---|---|
| 공식 (Qwen3-VL Technical Report) | 67.4 |
| 우리 재현 결과 | 58.44 |
| 차이 (Δ) | −8.96 |

## 7. 격차 분석

58.44점으로 공식 67.4보다 8.96점 낮다. 아래 수치는 모두 v5 문항별 로그(`results/v5_maxtok8192`)에서 계산했다.

1. **생성 잘림.** 73건(8.1%)이 8,192토큰에서 끊겼고 정확도는 19.2%로 무작위 수준이다. MMMU 공식 파서는 보기 문자를 못 찾으면 무작위로 고른다. 잘린 응답을 열어보니 35건(48%)이 같은 계산을 되풀이하는 루프였고(끝부분 8-gram 반복률 50% 초과), 나머지도 결론 없이 끊겼다. 2,048토큰 예비 실행(잘림 14.3%, 56.56점)보다 나아졌지만 예산만으로는 풀리지 않는 유형이다.
2. **추론 억제.** 정상 종료한 객관식은 65.4%로 공식과 2.0점 차이다. 그중 16토큰 이하 직답 551건은 60.8%, 128토큰 이상 추론 후 답한 172건은 80.2%였다. 프롬프트의 "directly" 지시가 추론을 막았을 가능성이 크다.
3. **평가 프로토콜 차이.** Qwen 공식 MMMU 스크립트(QwenLM/Qwen3-VL `evaluation/mmmu`)는 지시문이 다르고, 작은 이미지를 약 1M px로 키우며(우리 프롬프트 토큰 중앙값 338), 규칙 추출 실패 시 GPT judge로 답을 뽑는다. 우리는 세 항목 모두 MMMU 공식 구현을 따랐다.
4. **표본 분산.** temperature 0.7 단일 샘플이며 900문항 표준오차는 약 ±1.6점이다.

## 8. 기타 특이사항 / 한계 (Optional)

- **Colab 환경 문제.** (1) `pip install -U pillow`가 결함 릴리스 Pillow 12.3.0을 설치해 `ImportError: cannot import name '_Ink' from 'PIL._typing'`이 났다. 12.2.0으로 고정했다. (2) vLLM이 설치한 torch 2.13.0은 CUDA 13.0 빌드인데, Colab에 미리 깔린 torchaudio 2.11.0은 버전 문자열이 같은 CUDA 12.8 빌드라 pip가 교체하지 않았다. torch 스택을 먼저 지우고 재설치해 해결했다(`scripts/setup_colab.sh`).
- **기록 누락.** peak VRAM은 측정하지 못했고, 마지막 추론 배치 로그는 Colab 연결 끊김으로 유실돼 소요 시간 일부를 추정했다. 제출 스크립트는 두 값을 `summary.json`에 자동 기록한다.
- **단답형 53문항(11.32%).** 잘림은 0건이고 생성 토큰 중앙값은 5로, 예산이 아니라 실제 오답이 대부분이다. 오답 47건 중 4건은 정답과 상대오차 2% 이내였지만 공식 채점 규칙(소수 둘째 자리 반올림 후 완전 일치)에 따라 오답 처리됐다(예: 정답 24.32, 예측 24.3).
- **다음에 시도할 것.** Qwen 공식 MMMU 평가 스크립트의 프로토콜(프롬프트, 이미지 해상도 1280×28×28~5120×28×28 px, 규칙 추출 + judge)로 맞춰 7번의 원인별 기여를 분리 측정한다. 이때도 파인튜닝 전후 비교를 위해 같은 스크립트와 같은 설정을 유지한다.
