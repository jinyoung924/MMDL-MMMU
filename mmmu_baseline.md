# MMMU-val Baseline Evaluation Report — Qwen3-VL-4B-Instruct

- **팀명**: _(기입)_
- **팀원**: _(기입)_
- **작성일**: 2026-09-22
- **재현 커맨드**: `bash scripts/run_mmmu_eval.sh`

---

## 1. 환경 / 재현성

| 항목 | 값 |
|---|---|
| 모델 checkpoint | `Qwen/Qwen3-VL-4B-Instruct` (ebb281ec70b05090aa6165b016eac8ec08e71b17), bf16 (config.json `torch_dtype` 기본값, 양자화/캐스팅 없음) |
| 추론 백엔드 | vLLM 0.29.0 (`+cu129` wheel), torch 2.13.0+cu129, transformers 5.17.0, Python 3.12.3. 선택 이유: <br>(1) vLLM의 SamplingParams는 Qwen 공식 권장값에 있는 `중복 단어 방지 옵션(presence_penalty)`과 `결과 고정 번호(seed)`를 그대로 쓸 수 있어서 <br>(2) 속도가 빠름 <br>(3) RTX 4090은 최신 LLM들이 기본으로 쓰는 bf16 연산을 칩 자체에서 완벽 지원하니, 데이터 형식을 억지로 바꾸거나 학습 중 연산이 터질 걱정 없이 그대로 돌리면 된다. |
| 사용 GPU | RunPod RTX 4090 24 GB × 1 (이미지 `runpod/pytorch:1.3.2-cu1290-torch2130-ubuntu2404`, 드라이버 595.91.07) |
| 실측 peak VRAM | 22,987 MiB (`nvidia-smi` 2초 간격 폴링). <br>vLLM이 `gpu_memory_utilization=0.90`만큼 KV 캐시를 선점하므로 device 사용량은 설정값에 의해 결정된다. 가중치는 약 9 GB. |
| 총 소요 시간 | 3,837초 (약 64분, 900문제, 엔진 로딩 포함). 모델 다운로드와 패키지 설치 약 6분은 별도. |
| 의존성 | [requirements.txt](../requirements.txt) (pin) <br> [results/requirements.lock.txt](../results/requirements.lock.txt) (실행 환경 `pip freeze`) <br> 설치 스크립트 : [scripts/setup_runpod.sh](../scripts/setup_runpod.sh) |
| 실행 커맨드 | 아래 코드 블록 참조 |

```bash
MODEL_PATH=Qwen/Qwen3-VL-4B-Instruct \
MODEL_REVISION=ebb281ec70b05090aa6165b016eac8ec08e71b17 \
DATA_ROOT=MMMU/MMMU \
DATA_REVISION=98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68 \
OUT_DIR=results/mmmu_baseline \
bash scripts/run_mmmu_eval.sh
```

- 다섯 변수는 모두 기본값이 위와 같아 생략 가능하다. `MODEL_PATH`와 `DATA_ROOT`는 로컬 디렉토리도 받는다(로컬이면 revision은 무시). fine-tune 후 재평가는 `MODEL_PATH`만 바꾸면 된다.
- 프롬프트, sampling, 해상도, 엔진 설정은 전부 [configs/mmmu_baseline.yaml](../configs/mmmu_baseline.yaml) 한 파일에 있고, 실행 시 실제 적용값이 `<OUT_DIR>/config_resolved.yaml`로 저장된다.
- 과목 단위로 `predictions/<과목>.jsonl`에 기록하며, 같은 `OUT_DIR`로 다시 실행하면 끝난 과목은 건너뛴다.
- 산출물: [results/mmmu_baseline/](../results/mmmu_baseline/) (문제별 원문 응답·파싱 결과·토큰 수·이미지 크기, 점수표, `run_meta.json`, `run.log`).

## 2. 프롬프트

**실제 모델에 들어간 프롬프트 전문** (Qwen chat template의 user turn 내용. system prompt 없음. 변수는 `{}`):

객관식 (847문제):
```
{question}

(A) {option_1}
(B) {option_2}
...

Answer the preceding multiple choice question. The last line of your response should be of the following format: 'Answer: $LETTER' (without quotes) where LETTER is one of options. Think step by step before answering.
```

주관식 (53문제):
```
{question}

Answer the preceding question. The last line of your response should be of the following format: 'Answer: $ANSWER' (without quotes) where ANSWER is your final answer. Think step by step before answering.
```

- 이미지 배치: 텍스트(질문과 선택지) 안의 `<image N>` 토큰이 처음 나오는 자리에 해당 이미지를 끼워 넣는다(interleave). <br>텍스트에서 참조되지 않는 이미지는 맨 앞에 둔다. <br>같은 이미지가 다시 참조되면 그 자리는 문자열 `<image N>` 그대로 남긴다. <br>구현: [src/mmmu_eval/data.py](../src/mmmu_eval/data.py) `build_content`.
- **출처**: 지시문은 MMMU-Pro 공식 CoT 프롬프트(https://github.com/MMMU-Benchmark/MMMU/tree/main/mmmu-pro 의 `prompts.yaml`)에서 차용했다. <br> 주관식 문구는 같은 형식을 주관식에 맞게 직접 고쳤다. 질문과 선택지 렌더링 `(A) ...`은 MMMU 공식 `mmmu/utils/data_utils.py::construct_prompt`를 따랐다.
- **선택 이유**: 처음에는 MMMU 공식 direct-answer 템플릿(`Answer with the option's letter from the given choices directly.`)으로 평가했다. 그런데 이 모델은 그 지시를 받고도 900문제 중 309문제에서 스스로 긴 풀이를 썼다. 응답 방식이 문제마다 섞이면, fine-tuning이 "풀이를 쓰는 비율"만 바꿔도 점수가 움직여 전후 비교가 흐려진다. CoT 프롬프트는 900문제 전부에서 같은 방식(풀이 후 `Answer:` 줄)을 끌어내므로 비교 기준으로 더 안정적이다. direct 템플릿 결과는 7절의 ablation으로 남겼다.

## 3. 생성(Decoding) 설정

### 3.1 Sampling recipe

| 파라미터 | 값 |
|---|---|
| `do_sample` | true |
| `temperature` | 0.7 |
| `top_p` | 0.8 |
| `top_k` | 20 |
| `repetition_penalty` | 1.0 |
| `presence_penalty` | 1.5 |
| `seed` | 3407 (요청별 seed = 3407 + 과목 번호×1000 + 문제 번호. 실행 순서나 resume 여부와 무관하게 같은 문제는 같은 seed를 받는다) |

- **출처**: (1) 모델 repo `Qwen/Qwen3-VL-4B-Instruct` @ebb281e 의 `generation_config.json`: `do_sample=true, temperature=0.7, top_p=0.8, top_k=20, repetition_penalty=1.0`. (2) Qwen3-VL GitHub README의 "Generation Hyperparameters" 절, Instruct 모델 항목: `greedy=false, seed=3407, top_p=0.8, top_k=20, temperature=0.7, repetition_penalty=1.0, presence_penalty=1.5, out_seq_length=32768` — https://github.com/QwenLM/Qwen3-VL . 두 출처의 값이 일치하며, `presence_penalty`와 `seed`는 (2)에만 있다. 공식값을 그대로 썼고 `out_seq_length`만 3.2절의 이유로 다르게 정했다.

### 3.2 생성 예산 / 이미지 해상도

| 파라미터 | 값 |
|---|---|
| `max_new_tokens` | 8192 |
| 이미지 해상도 처리 | 이미지당 `min_pixels=65,536`(64토큰, 프로세서 기본 `shortest_edge`) ~ `max_pixels=2,097,152`(2048토큰). Qwen 프로세서와 같은 `smart_resize` 규칙(가로세로를 32의 배수로 반올림, Qwen3-VL은 32×32픽셀당 비주얼 토큰 1개)으로 사전 리사이즈한다. 문제당 비주얼 토큰 합이 12,288을 넘으면 모든 이미지를 비례 축소한다. `max_model_len=16384`. |

**선택 근거**
- **`max_new_tokens`는 실측으로 정했다.** 1024토큰에서는 direct 프롬프트인데도 166/900건이 답을 내기 전에 잘렸고, 그 정확도는 34.3%였다(완료 응답 61.4%). 8192로 올리자 그중 90건이 풀이를 마쳤고(정확도 71.1%) 점수가 56.44에서 60.11로 올랐다. 회복된 90건 중 2048토큰 안에 끝난 것은 32건, 4096 안에 끝난 것은 61건이라 8192를 택했다.
- **공식값 32768을 쓰지 않은 이유.** 8192에서도 끝나지 않는 응답은 대부분 수렴하지 못하는 풀이여서(7절), 예산을 4배로 늘리면 실행 시간(현재 64분)만 과목당 최장 응답 길이에 비례해 늘어날 가능성이 크다. 24 GB에서 30문제 동시 생성을 유지하려는 절충이기도 하다(가중치 약 9 GB, KV 캐시 약 12 GB, 토큰당 KV 약 0.15 MB). 이 선택이 점수에 미치는 영향은 7절에서 다룬다.
- **해상도 상한.** 프로세서 기본 `longest_edge=16,777,216`픽셀(이미지당 최대 약 16k 토큰)을 그대로 두면 최대 7장인 문제에서 컨텍스트를 넘는다. MMMU 이미지는 대부분 작아서(문제당 비주얼 토큰 중앙값 210, 최대 4,052) 2048토큰 상한에 걸린 문제는 36건뿐이고, 문제당 12,288토큰 예산에 걸린 문제는 없다. 최대 프롬프트 길이는 4,165토큰이라 8192토큰 생성을 더해도 `max_model_len` 안에 든다.

## 4. 채점(파싱) 방식

- **사용한 파서/로직**: MMMU 공식 평가 코드 `mmmu/utils/eval_utils.py`의 `parse_multi_choice_response`, `parse_open_response`, `eval_multi_choice`, `eval_open`과 그 보조 함수를 그대로 옮겼다 — https://github.com/MMMU-Benchmark/MMMU . 구현: [src/mmmu_eval/parser.py](../src/mmmu_eval/parser.py). 그 앞에 `Answer:` 줄을 뽑는 단계를 직접 추가했다(MMMU-Pro의 응답 규약).
- **동작 방식 요약**
  1. 응답에서 마지막 `Answer: ...` 줄을 찾아 그 내용만 남긴다. `**`, `$`, `\boxed{}` 같은 마크업은 지우고 괄호는 남긴다. 그런 줄이 없으면(대부분 잘린 응답) 응답 전체를 다음 단계로 넘긴다.
  2. 객관식: 양끝 구두점 제거 → `(A)` 형태 탐색 → 없으면 공백으로 둘러싸인 ` A ` 탐색 → 없고 5단어를 넘으면 선택지 본문 텍스트 매칭 → 후보가 여럿이면 가장 뒤에 나온 것 → 후보가 없으면 무작위 선택(fallback).
  3. 주관식: 핵심 구절과 숫자를 뽑아 정규화(소문자, 소수 둘째 자리 반올림)한 뒤 정답(복수 허용)과 비교한다. 숫자는 일치, 문자열은 포함 관계로 판정한다.
- **공식 코드와 다른 점**: fallback의 무작위 선택에 문제별 고정 seed를 써서 결과가 매번 같게 했고, `parse_fallback` 플래그로 건수를 집계한다. 본 실행의 fallback은 19건이며 전부 잘린 응답이다. 풀이를 마친 객관식 713건은 모두 `Answer:` 줄에서 선택지가 파싱됐다.
- 저장된 응답은 `python scripts/regrade.py --out_dir <dir>`로 GPU 없이 다시 채점할 수 있다.

## 5. 결과

| No. | Subject | Data Num | Acc |
|---|---|---|---|
| 1 | Accounting | 30 | 66.67 |
| 2 | Agriculture | 30 | 53.33 |
| 3 | Architecture_and_Engineering | 30 | 46.67 |
| 4 | Art | 30 | 63.33 |
| 5 | Art_Theory | 30 | 86.67 |
| 6 | Basic_Medical_Science | 30 | 73.33 |
| 7 | Biology | 30 | 60.00 |
| 8 | Chemistry | 30 | 56.67 |
| 9 | Clinical_Medicine | 30 | 63.33 |
| 10 | Computer_Science | 30 | 63.33 |
| 11 | Design | 30 | 73.33 |
| 12 | Diagnostics_and_Laboratory_Medicine | 30 | 26.67 |
| 13 | Economics | 30 | 80.00 |
| 14 | Electronics | 30 | 40.00 |
| 15 | Energy_and_Power | 30 | 60.00 |
| 16 | Finance | 30 | 70.00 |
| 17 | Geography | 30 | 63.33 |
| 18 | History | 30 | 70.00 |
| 19 | Literature | 30 | 83.33 |
| 20 | Manage | 30 | 66.67 |
| 21 | Marketing | 30 | 90.00 |
| 22 | Materials | 30 | 53.33 |
| 23 | Math | 30 | 60.00 |
| 24 | Mechanical_Engineering | 30 | 50.00 |
| 25 | Music | 30 | 40.00 |
| 26 | Pharmacy | 30 | 83.33 |
| 27 | Physics | 30 | 76.67 |
| 28 | Psychology | 30 | 76.67 |
| 29 | Public_Health | 30 | 76.67 |
| 30 | Sociology | 30 | 63.33 |
| | **Overall (macro avg)** | **900** | **64.56** |

계산식: `Overall = mean(30개 과목 accuracy)` = 64.56. 과목당 30문제로 균등하므로 micro 평균(581/900 = 64.56)과 같다. 두 값 모두 [scores.json](../results/mmmu_baseline/scores.json)에 기록했다. 과목별 Acc는 맞힌 문제 수 / 30이다.

## 6. 공식 수치와의 비교

| | Overall (MMMU val) |
|---|---|
| 공식 (Qwen3-VL Technical Report) | 67.4 |
| 우리 재현 결과 | 64.56 |
| 차이 (Δ) | −2.84 |

## 7. 격차 분석

원인을 분리하려고 같은 recipe, seed, 파서로 세 번 실행했다.

| 실행 | 프롬프트 | 예산 | Overall | 주관식 | 잘림 | 완료 응답 Acc | 잘린 응답 Acc |
|---|---|---|---|---|---|---|---|
| A | direct | 1024 | 56.44 | 15.1 | 166 | 61.4 | 34.3 |
| B | direct | 8192 | 60.11 | 15.1 | 77 | 62.1 | 39.0 |
| C (본 결과) | CoT | 8192 | 64.56 | 37.7 | 145 | 71.3 | 29.7 |

① 생성 예산(+3.67). direct 지시에도 모델은 309문제에서 풀이를 썼다. A는 그중 166건이 잘렸고 무작위 fallback 73건이 모두 여기서 나왔다. B에서 풀이를 마친 90건의 정확도는 71.1%다.

② 프롬프트(+4.45). 즉답을 강제하면 계산 문제를 찍는다. CoT로 주관식이 15.1→37.7, Chemistry 33→57, Manage 37→67, Physics 60→77로 올랐다. 인식 위주 과목은 반대로 내렸다(Diagnostics 40→27). 공식 평가도 풀이를 허용했을 가능성이 높다.

③ 남은 Δ. C에서도 145건(16%)이 8192토큰 안에 끝나지 않았다. 공학 4과목과 Music에 몰려 있고, 가정을 바꿔가며 수렴하지 못하는 풀이가 대부분이다(글자 단위 반복 루프는 15건). 완료된 755건만 보면 71.3%로 공식치를 넘는다. 따라서 남은 2.84점은 모델 능력보다 미종료 응답의 처리(공식 `out_seq_length` 32768, 우리는 8192)와 표본 오차(단일 seed, 이항 표준오차 약 1.6점)로 설명된다. 해상도 상한에 걸린 문제는 36건뿐이라 영향이 작다고 보나 검증하지는 못했다.

## 8. 기타 특이사항 / 한계 (Optional)

- **실행 이력.** 본 결과는 커밋 `b7a06ac`에서 `--prompt_style mmmu_pro_cot --max_new_tokens 8192` 플래그로 실행했다. 이후 이 값을 설정 파일 기본값으로 옮겼으며, 적용된 설정은 [config_resolved.yaml](../results/mmmu_baseline/config_resolved.yaml)과 동일하다. `run.log`와 `run_meta.json`에는 실행 당시의 출력 경로(`ablation_cot_8k`)가 남아 있다.
- **재채점.** 실행 후 `Answer:` 줄 추출 정규식의 결함 두 가지를 고쳤다. 괄호로 시작하는 답(`Answer: (D) ...`)에서 괄호를 지우던 것과, 기호로 시작하는 답(`Answer: $360`)을 놓쳐 풀이 전체를 채점하던 것이다. 저장된 응답을 다시 채점해 7건이 바뀌었고 점수는 64.44에서 64.56이 됐다. direct 실행 두 개는 변화가 없다.
- **너그러운 주관식 채점.** `Answer:` 줄이 없는 주관식 응답 11건(전부 잘린 응답)은 공식 파서 동작대로 풀이 전체에서 숫자를 찾는다. 이 중 3건이 정답 처리됐다(최대 0.33점). 공식 도구와의 일치를 위해 그대로 두었다.
- **재현성.** direct 실행 A와 B에서 짧게 답한 591건 중 575건의 응답이 글자까지 같았다. 나머지 차이는 vLLM 배치 구성에 따른 수치 비결정성으로 추정한다. 긴 CoT 응답은 같은 seed라도 재실행 시 일부 달라질 수 있으며, seed를 바꾼 반복 측정은 하지 못했다.
- **인프라.** 첫 RunPod 호스트는 `nvidia-smi`는 정상인데 CUDA 드라이버 초기화가 실패했다(`/dev/nvidia-uvm` I/O 오류). 이후 설치 스크립트 맨 앞에 드라이버 사전 검사를 넣었다. PyPI의 `vllm==0.29.0`은 CUDA 13 빌드라서 GitHub 릴리스의 `+cu129` wheel을 쓴다.
- **다음에 해볼 것.** 미종료 145건에 대해 예산 32768 또는 `repetition_penalty` 조정의 효과 측정, seed 3~5개 반복으로 분산 추정, `max_pixels` 상한 해제 ablation.
