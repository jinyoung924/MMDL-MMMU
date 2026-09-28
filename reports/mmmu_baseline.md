# MMMU-val Baseline Evaluation Report — Qwen3-VL-4B-Instruct

- **팀명**: 11조
- **팀원**: 김진영, 김동준, 이솔규, 이영민
- **작성일**: 2026-09-28
- **재현 커맨드**: `bash eval.sh` (5 seed × 900문항 → 평균 ± 표준편차, RTX 4090 기준 약 6.4시간)

> 이 파이프라인은 **체크포인트 경로 하나만 바꿔** fine-tuned 모델을 같은 조건으로 재평가하도록 만들었습니다:
> `bash eval.sh /abs/path/to/finetuned_ckpt results_ft`. 프롬프트·생성 파라미터·파서·데이터 revision은 전부
> `run_eval.py`의 기본값에 고정되어 있고, 실제 사용된 값은 매 실행 `scores.json`의 `config`에 기록됩니다.
>
> 코드는 [`run_eval.py`](../run_eval.py)(1회 실행: 프롬프트 구성 → vLLM 생성 → 채점), [`analyze.py`](../analyze.py)(seed 집계·실패 분석),
> [`eval.sh`](../eval.sh)(한 커맨드 진입점) 세 파일, 의존성은 [`requirements.txt`](../requirements.txt) 하나입니다.
> 아래 모든 설정값은 실측으로 골랐고, 근거가 된 실행 결과는 [`ablation/`](../ablation/)에 응답 전문과 함께 들어 있습니다.

---

## 1. 환경 / 재현성

| 항목 | 값 |
|---|---|
| 모델 checkpoint | `Qwen/Qwen3-VL-4B-Instruct` revision `ebb281ec70b05090aa6165b016eac8ec08e71b17` (bf16, 양자화 없음) |
| 데이터셋 | `MMMU/MMMU` revision `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68`, split `validation`. 30개 과목 config를 **각각** `load_dataset("MMMU/MMMU", <과목>, split="validation", revision=...)`로 로드. 필터링·서브샘플링 없음 (과목당 30문항, 총 900문항) |
| 추론 백엔드 | **vLLM 0.24.0** (offline `LLM.generate`), `VLLM_BATCH_INVARIANT=1`. **선택 이유**: `transformers.generate()`로 한 건씩 돌리면 GPU가 대부분 놀아 900문항 × 이미지 평가가 수 시간 이상 걸립니다. vLLM은 continuous batching + paged KV cache로 같은 24GB 카드에서 실행 시간을 한 자릿수 배 줄이고, KV cache 예산(`gpu_memory_utilization`)이 명시적 knob이 되어 VRAM 한도를 문서화하기 쉽습니다. 부작용(배치 구성에 따라 출력이 달라짐)은 배치 불변 모드로 막았습니다(§3.1) |
| 사용 GPU | NVIDIA GeForce RTX 4090, 24,564 MiB |
| 실측 peak VRAM | **23,754 MiB** (`gpu_memory_utilization=0.90`으로 KV cache를 미리 잡는 값이라 "허용한 양"에 가까움. 작은 카드에서는 이 knob을 낮추면 됨) |
| 총 소요 시간 | 900문항 1회 **76~78분** (배치 불변 모드; 일반 모드는 약 45분), 5 seed 합계 약 6.4시간 |
| 의존성 | [`requirements.txt`](../requirements.txt) — Python 3.11.15 / CUDA 13.0 / torch 2.11.0+cu130 / transformers 5.13.0 / datasets 5.0.1 |
| 실행 커맨드 | 아래 |

```bash
pip install -r requirements.txt
bash eval.sh Qwen/Qwen3-VL-4B-Instruct results
#   인자 1: 모델 — HF repo id 또는 로컬 체크포인트 디렉터리 (로컬이면 revision 무시)
#   인자 2: 출력 폴더
# eval.sh 내부 (s = 0..4; 끝난 seed는 건너뛰므로 중단돼도 이어서 실행):
#   python run_eval.py --model <MODEL> --model-revision ebb281ec... \
#                      --data MMMU/MMMU --data-revision 98e6ac0c... --seed <s> --out results/seed<s>
#   python analyze.py aggregate results/seed*        # -> results/table.md, results/scores.json
```

- 모델·데이터는 repo에 넣지 않고 `huggingface_hub` 표준 캐시(`~/.cache/huggingface`, `HF_HOME`으로 변경 가능)로 받으며,
  revision은 `run_eval.py`의 기본값(`MODEL_REV`, `DATA_REV`)으로 pin 했습니다. 하드코딩된 절대경로는 없고, 채점자는
  위 두 인자 외에 바꿀 것이 없습니다.
- **재현성 장치**: (1) 실제 사용된 전체 config를 매 실행 `scores.json`에 기록, (2) `analyze.py aggregate`는 seed 외의
  config가 하나라도 다른 실행은 합치기를 거부, (3) 같은 seed 재실행 시 900문항 중 899개 응답이 글자 단위로 일치하고
  점수는 동일(64.33, `ablation/repro_seed0`). fine-tuned 체크포인트는 `bash eval.sh <경로> results_ft`로 같은 조건에서 재평가합니다.

## 2. 프롬프트

**실제 모델에 들어간 프롬프트 전문** (변수는 `{}`, 최종 채택 = `--prompt-style cot`):

객관식:
```
{question}
(A) {option_A}
(B) {option_B}
(C) {option_C}
...
Think step by step, then give your final answer on the last line in exactly this format: "Answer: X"  (X = the letter of the correct option).
```

주관식:
```
{question}
Think step by step, then give your final answer on the last line in exactly this format: "Answer: <single word or phrase>".
```

이 텍스트가 `Qwen3VLProcessor.apply_chat_template(add_generation_prompt=True)`의 기본 템플릿으로 단일 user turn에 감싸집니다
(`<|im_start|>user\n … <|im_end|>\n<|im_start|>assistant\n`, 이미지 자리는 `<|vision_start|><|image_pad|>…<|vision_end|>`).
**system prompt는 넣지 않았습니다.** 문항별로 실제 사용된 텍스트는 `results/seed*/predictions.jsonl`의 `prompt` 필드에 그대로 남아 있습니다.

- **출처**: 질문·선택지 조립(`(A) ...` 줄 형식)은 MMMU 공식 저장소
  [`mmmu/utils/data_utils.py`](https://github.com/MMMU-Benchmark/MMMU/blob/main/mmmu/utils/data_utils.py)의 `construct_prompt()`를
  그대로 따랐고, **마지막 지시문 한 문장만 직접 설계**했습니다. 원본 지시문
  (`Answer with the option's letter from the given choices directly.`, [`llava1.5.yaml`](https://github.com/MMMU-Benchmark/MMMU/blob/main/mmmu/configs/llava1.5.yaml))도
  같은 조건에서 실측했습니다.
- **선택 이유 (실측)**: Qwen3-VL-4B는 "바로 답하라"는 지시를 따르지 않고 계산 과목에서 CoT를 시작해 버립니다. 그 결과
  응답이 예산에서 잘리고, 잘린 응답은 파서가 답을 못 찾아 무작위 추측으로 떨어집니다. 어차피 추론을 하므로 **추론을
  허용하되 마지막 줄 형식을 강제**하는 쪽이 유리했습니다. 두 변형은 마지막 한 문장만 다르고 폴백 파서를 공유합니다.

  | 프롬프트 (max_new_tokens 8192) | 실행 | 종합 | 잘림 | 무작위 추측 |
  |---|---|---|---|---|
  | MMMU 공식 (`answer directly`) | 1회 | 59.78 | 83 | 7 |
  | 직접 설계 (CoT + 답 형식 강제) | 1회 | 65.44 | 135 | 16 |
  | **직접 설계 (CoT + 답 형식 강제)** | **5 seed 평균** | **64.93 ± 0.94** | 137.8 | 13.4 |

  차이 5.2점은 seed 간 표준편차(0.94)보다 훨씬 큽니다. 완주한 응답은 예외 없이 `Answer:` 줄을 쓰므로, 태그 미검출은 잘린 응답에서만 생깁니다.

- **이미지 배치**: MMMU는 텍스트 안의 `<image N>` 자리에 이미지를 두며, 선택지 자체가 이미지인 문항도 있습니다.
  `interleave()`가 프롬프트를 `<image N>` 위치에서 잘라 **등장 순서대로** 텍스트와 이미지를 번갈아 넣고, 참조되지 않은
  이미지는 버리지 않고 맨 뒤에 덧붙입니다.

## 3. 생성(Decoding) 설정

### 3.1 Sampling recipe

| 파라미터 | 값 |
|---|---|
| `do_sample` | `true` |
| `temperature` | `0.7` |
| `top_p` | `0.8` |
| `top_k` | `20` |
| `repetition_penalty` | `1.0` |
| `presence_penalty` | `1.5` |
| `seed` | `0, 1, 2, 3, 4` (요청 단위 `SamplingParams(seed=s)` + 배치 불변 모드) |

- **출처**: (1) pin한 revision에 동봉된 `generation_config.json`
  (`do_sample: true, temperature 0.7, top_p 0.8, top_k 20, repetition_penalty 1.0`),
  (2) [HuggingFace 모델 카드](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct)의 vision-language 과제 권장값 `presence_penalty 1.5`
  (텍스트 전용 권장값 temp 1.0 / top_p 1.0 / top_k 40 / presence 2.0과 다르며, MMMU는 VL 과제이므로 VL 값 사용).

- **`presence_penalty`를 바꿔 봤다가 공식값으로 되돌린 경위**: 잘림이 가장 큰 단일 오답 원인이어서(§3.2), "반복 억제
  (`presence_penalty 1.5`)가 오히려 풀이를 표류시켜 못 끝내게 하는 것 아닌가"를 의심했습니다. 별도 브랜치의 단일 seed 실행에서
  8,192 토큰 안에 못 끝낸 145문항만 골라 조건을 바꿔 세 번 돌렸습니다(그 실행의 오답 319건 중 102건이 이 문항들).

  | 조건 (같은 145문항) | 검증하려던 가설 | 정답률 | 잘림 |
  |---|---|---|---|
  | 같은 설정 재실행 | 잘림이 우연인가 | 35.2% | 96 |
  | 잘린 응답 뒤에 `Answer:`를 붙여 답 강제 | 답에는 도달했는데 표류하느라 못 쓰는가 | 37.2% | 107 |
  | 답 강제 + `presence_penalty 0` | 반복 억제가 표류를 유발하는가 | 41.4% | 121 |

  - `presence_penalty`를 0으로 내리자 잘림이 오히려 늘었습니다(107 → 121). 반복 억제가 없으면 같은 계산을 더 맴돕니다.
    정답률 35~41%의 차이는 145문항 1회 실행의 표본 오차 범위라 판정 근거로 삼지 않았습니다.
  - 강제로 받아낸 답의 정답률은 31~34%로 4지선다 무작위(25%)에 가까웠습니다. 이 문항들은 "답을 알지만 못 쓴 것"이 아니라
    모델이 수렴하지 못하는 유형이며, 같은 seed로 다시 돌려도 3분의 2가 다시 잘렸습니다.
  - 결론: 잘림은 생성 설정으로 회복되지 않으므로 **`presence_penalty`는 공식값 1.5를 유지**하고, 답 강제 후처리도 파이프라인에
    넣지 않았습니다. 공식 recipe에서 벗어날 근거가 없음을 실측으로 확인한 셈입니다.

- **sampling인데 재현성은 어떻게 확보했나**: seed 고정만으로는 부족했습니다. 같은 설정·seed 0으로 900문항을 두 번 돌리자
  글자 단위로 같은 응답은 **32개**뿐이었고 점수가 65.44 → 62.44로 달라졌습니다. 원인은 continuous batching으로 배치
  구성이 바뀌면 bf16 누산 순서가 바뀌어 logits가 미세하게 달라지고, temperature 0.7 샘플링이 이를 증폭하기 때문입니다.
  - **배치 불변 모드** (`VLLM_BATCH_INVARIANT=1`, 기본값): 60문항 배치와 90문항 배치의 공통 60문항 비교에서 일반 모드
    0/60 → 배치 불변 60/60 일치. 900문항 재실행에서 899/900 일치, 정오 뒤집힘 0건. 비용은 약 1.7배 느려짐.
  - **5 seed 평균**: 결정성은 "같은 seed → 같은 결과"만 보장하고 샘플링 분산은 남습니다(seed별 64.22~66.56). 그래서
    평균 ± 표준편차로 보고하고, fine-tuning 전후 비교도 같은 5 seed로 합니다.

### 3.2 생성 예산 / 이미지 해상도

| 파라미터 | 값 |
|---|---|
| `max_new_tokens` | `8192` |
| `max_pixels` (이미지당) | `1280 × 32 × 32 = 1,310,720` px → 이미지당 최대 **1,280 vision token** |
| `min_pixels` (이미지당) | `4 × 32 × 32 = 4,096` px |
| `max_model_len` | `24576` |
| `limit_mm_per_prompt` | `{"image": 7}` |
| `gpu_memory_utilization` | `0.90` |

**생성 예산 — 이 파이프라인에서 점수를 가장 크게 좌우한 단일 파라미터.** 두 프롬프트 × 예산으로 900문항을 재실행했습니다.

| 프롬프트 | `max_new_tokens` | 종합 (1회) | 잘림 | 무작위 추측 | 소요 |
|---|---|---|---|---|---|
| mmmu 공식 | 512 | 53.33 | 215 | 108 | 1.5분 |
| mmmu 공식 | 2048 | 57.56 | 144 | 39 | 4.2분 |
| mmmu 공식 | 4096 | 60.00 | 118 | 20 | 9.7분 |
| mmmu 공식 | 8192 | 59.78 | 83 | 7 | 23.2분 |
| CoT | 4096 | 63.00 | 203 | 22 | 19.9분 |
| **CoT (채택)** | **8192** | **65.44** (5 seed: 64.93 ± 0.94) | 135 | 16 | 40.3분 (배치 불변 77분) |

- 512는 응답의 24%를 잘랐고, 잘린 문항 정확도는 27.4%(완주 61.5%)였으며 무작위 추측 108건이 **전부** 잘린 응답이었습니다.
  과목별 `512 잘림 건수`와 `512→4096 상승폭`의 상관계수는 0.859로, 짧은 예산은 평가 장치가 만든 오답을 대량 생산합니다.
- **8192 선택 근거**는 점수가 아니라(4096→8192 차이는 실행 간 sd 약 2점 안) **잘림 감소**(CoT 203 → 135)입니다.
  잘린 응답은 채점이 사실상 찍기가 되므로 잘림 자체가 측정 오차원이고, 8192는 잘림을 15%로 낮추면서 1회를 한 시간 안팎에 끝내는 절충점입니다.
- **16,384로 늘리면?** 5 seed에서 한 번이라도 잘린 224문항을 Qwen 권장치 16,384로 다시 돌린 결과(seed 0·1), 잘린 응답의
  **70%는 여전히 잘렸고**(반복 루프 82건 중 4건만 종료) 새로 완주한 응답의 정확도도 약 60%로 낮아, 종합은 두 seed 모두
  **+0.78점**에 그쳤습니다. 비용은 224문항에 seed당 약 190분이라 파이프라인은 8192를 유지합니다.

**이미지 해상도.** Qwen3-VL은 vision token 1개 = 32×32 px(patch 16 × merge 2). 저장소 기본값은 이미지당 16,384 token이라
7장짜리 문항은 프롬프트가 11만 토큰을 넘겨 24GB에서 감당이 안 됩니다. MMMU val 이미지 982장을 실측하니 중앙값 198k px,
p95 1.52M px로, 1.31M px 캡을 넘는 이미지는 59장(6%)뿐입니다. 즉 94%는 원본 그대로 들어가고, 최악(7장)도
8,960 token으로 `max_model_len` 안입니다. 캡을 2,048 token / `max_model_len 32768`로 푼 ablation(`cot_8192_hires`)에서
모든 픽셀 구간의 변화가 실행 간 흔들림 범위 안이었고(전체 64.70 ± 2.00 → 65.11), 오답 표본 50문항 중 고해상도로 맞힌 수(12)가
seed만 바꿔 맞힌 수(12)와 같았습니다. 캡은 성능 원인이 아니므로 유지합니다.

## 4. 채점(파싱) 방식

- **사용한 파서**: MMMU 공식 저장소 [`mmmu/utils/eval_utils.py`](https://github.com/MMMU-Benchmark/MMMU/blob/main/mmmu/utils/eval_utils.py)의
  `parse_multi_choice_response` / `parse_open_response` / `eval_open`을 **로직 변경 없이 `run_eval.py`에 이식(vendored)**.
  유일한 변경은 무작위 fallback 발동 여부를 플래그로 함께 반환하는 것(점수에 영향 없음).
- **0단계 (CoT 프롬프트 전용, 직접 구현)**: 응답에서 `Answer:\s*\(?\s*([A-Za-z])(?![A-Za-z])`의 **마지막 매치**를 답으로
  씁니다(도중에 "Answer: A일까?"라고 언급해도 마지막 줄이 이김). 태그가 없거나 선택지 범위 밖이면 아래 공식 파서로 폴백합니다.
  주관식은 `Answer:` 뒤 텍스트를 공식 `parse_open_response`에 넘깁니다.
- **객관식 폴백 순서** (앞 단계에서 후보가 나오면 멈춤): ① 양끝 구두점 제거 → ② `(A)` 형태 괄호 글자 → ③ 공백으로 둘러싸인
  단독 글자 → ④ 응답이 5단어 초과면 선택지 본문 텍스트 등장 여부 → ⑤ 끝내 없으면 `random.choice` (**무작위 추측**).
  후보가 여럿이면 응답에서 가장 뒤에 나온 것을 택합니다.
- **주관식**: 문장/줄 단위로 나눈 뒤 `is `, `therefore `, `answer `, `=` 등 단서 뒤의 가장 짧은 조각과 거기서 뽑은 숫자를
  후보로 삼고, 소문자화·숫자 반올림(소수 2자리) 정규화 후 정답(복수 허용)과 부분 문자열 일치하면 정답.
- **파서 버그 수정 (2026-09-22)**: 초기 정규식 `Answer:\s*\(?\s*([A-Za-z])\s*\)?`는 `\s*`가 줄바꿈을 넘어
  `Final Answer:⏎Answer: C`에서 둘째 줄 "Answer"의 **A**를 답으로 읽었습니다(seed 0에서 16건, 그중 정답을 쓰고도 오답
  처리된 문항 12건). `(?![A-Za-z])` 조건 하나로 수정했고, 900개 응답을 독립 기준("줄 첫머리의 마지막 `Answer: X`")으로
  재추출해 불일치 0건을 확인했습니다. 수정 전 ablation은 저장된 응답을 수정된 파서로 재채점해 표기했습니다.
- **무작위 fallback 주의**: `random.seed(seed)`로 재현 가능하게 만들고 `fallback_guess`로 세어 `scores.json`과
  `predictions.jsonl`에 남깁니다. 실측상 발동은 **전부 잘린 응답**에서만 일어나므로(5 seed 합계 67건, 1.5%) 파서가 아니라
  생성 예산의 지표입니다.
- **알려진 한계**: 선택지 내용이 알파벳 한 글자이면서 기호와 어긋나는 문항 2개(`Basic_Medical_Science_17`, `Music_15`)에서
  모델이 이미지 라벨 글자를 답으로 쓰면 오독될 수 있습니다. 규칙 기반 채점의 결정성을 지키기 위해 고치지 않았습니다.

## 5. 결과

최종 설정으로 seed 0~4를 돌린 결과입니다(`results/table.md`, `results/scores.json`). Acc는 5 seed 평균, sd는 seed 간 표본 표준편차.

| No. | Subject | Data Num | Acc (mean of 5 seeds) | sd |
|---|---|---|---|---|
| 1 | Accounting | 30 | 78.0 | 6.5 |
| 2 | Agriculture | 30 | 57.3 | 1.5 |
| 3 | Architecture_and_Engineering | 30 | 52.7 | 9.2 |
| 4 | Art | 30 | 61.3 | 3.8 |
| 5 | Art_Theory | 30 | 80.7 | 2.8 |
| 6 | Basic_Medical_Science | 30 | 71.3 | 4.5 |
| 7 | Biology | 30 | 47.3 | 10.6 |
| 8 | Chemistry | 30 | 45.3 | 8.7 |
| 9 | Clinical_Medicine | 30 | 70.7 | 2.8 |
| 10 | Computer_Science | 30 | 66.7 | 5.3 |
| 11 | Design | 30 | 74.0 | 6.4 |
| 12 | Diagnostics_and_Laboratory_Medicine | 30 | 34.0 | 7.2 |
| 13 | Economics | 30 | 80.0 | 7.8 |
| 14 | Electronics | 30 | 46.0 | 4.9 |
| 15 | Energy_and_Power | 30 | 58.7 | 4.5 |
| 16 | Finance | 30 | 73.3 | 5.3 |
| 17 | Geography | 30 | 58.0 | 5.1 |
| 18 | History | 30 | 71.3 | 7.7 |
| 19 | Literature | 30 | 82.0 | 1.8 |
| 20 | Manage | 30 | 57.3 | 6.4 |
| 21 | Marketing | 30 | 85.3 | 3.8 |
| 22 | Materials | 30 | 58.7 | 5.6 |
| 23 | Math | 30 | 63.3 | 5.3 |
| 24 | Mechanical_Engineering | 30 | 44.7 | 3.8 |
| 25 | Music | 30 | 36.0 | 7.2 |
| 26 | Pharmacy | 30 | 82.0 | 1.8 |
| 27 | Physics | 30 | 80.7 | 5.5 |
| 28 | Psychology | 30 | 77.3 | 2.8 |
| 29 | Public_Health | 30 | 89.3 | 5.5 |
| 30 | Sociology | 30 | 64.7 | 3.0 |
| | **Overall (macro avg)** | **900** | **64.93** | 0.94 |

**계산식**: 과목 Acc = seed별 30문항 정답 비율의 5 seed 평균. `Overall = mean(30개 과목 Acc)` (macro average).
과목당 30문항으로 균등하므로 micro average(4,500개 응답 중 정답 비율)와 수학적으로 같습니다.

**실행 완전성 / 산술 정합**: 5 seed 모두 `scores.json`의 `n_questions = 900`, 과목별 `num = 30`입니다(`--limit`, `--ids-file`은
ablation 전용이며 공식 실행에서는 기본값 0/빈값). `run_eval.py`는 seed마다 macro와 micro를 **독립적으로** 계산해 기록하는데
5 seed 모두 두 값이 일치합니다. 한 과목이라도 덜 로드되면 두 값이 갈라지므로, 30과목 × 30문항이 빠짐없이 들어갔다는 증거입니다.
seed별 종합: **64.33 / 66.56 / 64.78 / 64.22 / 64.78** → 평균 64.93, sd 0.94.
문항 단위로는 5 seed 중 0회 정답 166문항 / 1~4회 304문항 / 5회 430문항이며, pass@5는 81.56%입니다.

## 6. 공식 수치와의 비교

| | Overall (MMMU val) |
|---|---|
| 공식 (Qwen3-VL Technical Report, arXiv 2511.21631, Table 4) | 67.4 |
| 우리 재현 결과 (5 seed 평균 ± 표준편차) | **64.93 ± 0.94** (seed별 64.22 ~ 66.56) |
| 차이 (Δ) | **−2.47** (5 seed 최고값 66.56도 67.4 미달) |

## 7. 격차 분석

Δ = −2.47은 샘플링 노이즈가 아닙니다(seed 간 sd 0.94, 5 seed 최고값 66.56도 미달). §2~§4의 선택을 후보로 두고 하나씩 실측했습니다.

1. **생성 예산 — 격차의 약 1/3.** 응답의 15.3%가 8,192 토큰에서 잘리고, 잘린 응답의 정확도는 35%(완주 70%)입니다.
잘린 응답을 직접 열어보니 31%가 같은 문장을 반복하는 루프였습니다. 잘린 224문항을 16,384로 이어 쓰게 해도 70%는
여전히 잘렸고 종합은 두 seed 모두 +0.78점이었습니다(3.2).
2. **이미지 해상도 — 원인 아님.** 캡을 2,048 token으로 풀어도 모든 픽셀 구간의 변화가 노이즈 범위였습니다(3.2).
3. **sampling — 원인 아님.** 공식 recipe를 그대로 썼고, 5 seed 평균이라 sampling 운은 sd 0.94 안에 있습니다.
4. **파서 — 원인 아님.** 우리 버그 12건은 수정했고 독립 기준과 불일치 0건입니다(§4). 무작위 추측 1.5%는 전부 잘린 응답입니다.
5. **문항 결함.** 오답 표본 48건 중 6건(13%)이 정답표 오류·정보 누락·선택지 중복이었습니다(val의 약 3%). 공식 평가도
같은 문항을 풀므로 격차 원인은 아니지만 상한을 만듭니다(`failure_diagnosis/`).
6. **프롬프트 — 남는 약 1.7점의 가장 유력한 후보.** 공식 평가의 프롬프트·파서·예산은 비공개라 검증할 수 없습니다.
다만 우리 실험에서 지시문 한 문장만으로 5.2점이 움직였으므로(2), 비공개 프롬프트 차이만으로 이 크기는 충분히 생깁니다.

## 8. 기타 특이사항 / 한계

- **남은 잘림**: 응답의 15.3%(seed당 127~146건)가 8,192 토큰에서 잘리고, 그중 31%는 같은 문장을 반복하는 루프입니다.
  예산을 두 배로 늘려도 +0.78점이라 유지했습니다.
- **과목 점수의 분산**: 종합 sd는 0.94이지만 과목 sd는 최대 10.6(Biology, 5 seed 범위 26.7점)입니다. 과목 간 차이와
  fine-tuning 전후 차이는 반드시 같은 seed끼리 짝지어 해석해야 합니다(`analyze.py compare`).
- **재현성에 대한 초기 오판**: 처음에는 요청 단위 seed만으로 결정적이라고 판단했으나 실측(32/900 일치)으로 틀렸음을
  확인하고 배치 불변 모드를 도입했습니다. 결정성은 `max_model_len` 등 엔진 설정까지 같을 때만 성립합니다.

- **fine-tuning 재평가 시 주의**: `max_new_tokens`가 점수를 가장 크게 좌우하므로(1회 기준 53.33~65.44) 체크포인트 비교 시
  **반드시 고정**해야 합니다. 더 장황해진 모델이 잘림이 늘어 점수가 떨어지는 착시가 생깁니다. 같은 5 seed·배치 불변 모드로
  평가하며, `analyze.py`는 모델 경로 외 설정이 다르면 비교를 거부합니다. 망각 측정 시 "base가 맞힌 문항"은 비교에 쓰지 않는
  seed로 골라야 합니다(같은 실행으로 고르면 평균 회귀로 약 10점의 가짜 망각 발생, [`pilot_forgetting/`](../pilot_forgetting/README.md)).
- **실패 진단(후속 과제용)**: 두 실행에서 모두 틀린 문항 무작위 48건을 태깅한 결과 지각 오류 44%, 생성 실패 21%,
  지식 17%, 문항 결함 13%였습니다. 사례집은 [`failure_diagnosis/`](../failure_diagnosis/README.md).
