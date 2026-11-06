# SFT 파일럿과 RFT 준비 (2026-10-28 ~ 11-02)

GRPO v1 이전에 진행한 학습 실험을 정리했습니다. 대부분 다른 에이전트(Codex)가 진행했고, 원래 기록은 보고서 30여 개와 `pilot_diagram/` 아래 약 2,300개 파일입니다.
여기에는 실험별 설정, 결과, 판정만 모았습니다. 모든 수치는 원문 보고서에서 가져왔고, 각 절 끝에 출처를 적었습니다.
전체 흐름은 [training_experiments.md](training_experiments.md)에 있습니다.

**레포에 있는 원문**은 아래 "원문 위치" 표에 ✓로 표시했습니다. 나머지 보고서, 가중치, 실험 폴더별 기록은 레포에 넣지 않았습니다. 출처에 적힌 파일 중 일부는 레포에 없습니다.

**결론 요약**

- 외부에서 써 준 정답·풀이로 SFT를 했습니다. 설정을 10번 넘게 바꿨지만 기본 모델을 넘은 적이 없습니다.
- MMMU 900문항 × 5 seed로 평가한 실험은 도표 SFT v1 하나뿐입니다. 결과는 −9.5점(풀이 포함)과 −14.2점(정답만)입니다.
- 학습이 안 된 것은 아닙니다. 목표 풀이의 NLL은 0 가까이 떨어졌고, 학습한 24문항은 24/24로 풀었습니다. 그런데도 처음 보는 문항의 점수는 떨어졌습니다.
- 정답 보상 GRPO의 첫 파일럿(R0)도 32번 업데이트한 뒤 개선이 없었습니다(DEV24 20/24 → 19/24). 이 결과가 GRPO v1–v6의 출발점입니다.

## 먼저 알아둘 것

| 항목 | 내용 |
|---|---|
| 모델 | `Qwen/Qwen3-VL-4B-Instruct` @ `ebb281ec` (평가와 같은 revision) |
| 공통 LoRA | r=16, α=32, dropout 0. 언어 모델의 q/k/v/o/gate/up/down만 학습하고 비전 인코더는 고정. batch 1 × accum 4, max_length 6144, 학습 seed 0. 10/30부터는 기반 모델 BF16, LoRA와 Adam 상태 FP32 |
| Geometry3K 세트 | 10/30 이후 실험은 모두 InterGPS Geometry3K의 **원래 train split 안에서** 나눈 세트를 씁니다. TRAIN24/28/32는 학습용입니다. **DEV40·DEV24는 내부 검증용이며 MMMU가 아닙니다.** DEV24 = 약점 12문항(기본 모델이 5번 중 1–3번 맞힘) + 안정 12문항(5/5) |
| 생성·채점 | vLLM native LoRA(병합 안 함). T 0.7, top_p 0.8, top_k 20, presence penalty 1.5, 최대 8192토큰. 마지막 `Answer:` 태그만 채점하고 무작위 대체 답은 쓰지 않습니다. **그래서 Geometry3K 점수는 공식 64.93과 비교할 수 없습니다** |
| 정답 풀이 작성 | 어시스턴트(Codex) 또는 Terra(`gpt-6.1-terra`, reasoning max)가 썼습니다. Terra는 구독 경로의 하위 에이전트로 호출했고 API 키는 쓰지 않았습니다. 검수도 모델이 했으며 사람 검수는 없습니다 |
| 판정 방식 | 실험마다 통과 기준을 사전 등록했습니다. 기준을 못 넘으면 추가 seed, 확인 세트(CONF), 공식 MMMU 평가 없이 종료했습니다. CONF와 공식 평가는 끝까지 한 번도 실행하지 않았습니다 |

## 타임라인

| 날짜 | 실험 | 한 줄 결과 |
|---|---|---|
| 10/28 | §1. BMMR 데이터 감사 | train 88,991행 중 엄격 조건(영어 질문, 객관식, 이미지 1개, 중복 없음) 통과 후보는 346개 |
| 10/28–29 | §2. 도표 SFT v1 | MMMU 5 seed 평균: 풀이 SFT 55.44, 정답만 SFT 50.76 (기본 64.93) |
| 10/29 | §3. 도표 v2 | 그림 사실을 주면 83.3% → 94.2%. SFT 체크포인트 12개는 모두 기본 이하 |
| 10/29–31 | §4. 안정성 SFT | 약점 문항 학습(B)이 무작위 학습(A)과 기본 모델보다 낮음. 사전 기준 6개 중 4개 실패 |
| 10/31–11/01 | §5. 원인 분석 v2–v5 | 풀이 형식, 백엔드, 디코더 모두 원인이 아님. 모델은 목표 풀이를 외울 수 있음 |
| 11/01 | §6. 원인 분석 v6–v11 | 학습 문항 24/24를 외워도 DEV 약점은 하락. attention과 MLP의 LoRA 변화가 함께 손상을 만듦 |
| 11/01 | §7. Terra 교사와 v12 | 짧고 정확한 Terra 풀이로 학습해도 약점 8 → 2(A) / 6(B) |
| 11/02 | §8. RFT/GRPO 준비와 R0 | 1024토큰 상한에서 128응답 중 84개 잘림. DEV24 20 → 19 |

---

## 1. BMMR 학습 데이터 감사 (10/28)

| | |
|---|---|
| 목표 | 팀이 1순위 후보로 제안한 BMMR-Train을 학습에 쓸 수 있는지, 그리고 평가 데이터와 겹치지 않는지 확인 |
| 데이터 | `guanyu615/BMMR` @ `e07b24f9`. train 88,991행. eval 고유 ID 20,458개(TSV는 cot 유무로 40,916행). 보호 대상은 BMMR-Eval과 MMMU val 900문항 |
| 방법 | 학습 없음. ID, 정규화한 질문의 exact match, 5단어 shingle 중첩을 검사. 후보 60개는 이미지 SHA256과 dHash(해밍 거리 ≤ 4)까지 검사 |
| 핵심 수치 | 정답·언어·과목 필드가 따로 없음. 정답은 기존 풀이 끝의 글자에서 추출 <br> 질문과 답변 모두 CJK 문자가 없는 행: 6,163개 <br> 텍스트 중복 플래그: 1,424행(BMMR-Eval 1,423, MMMU val 1) <br> 엄격 조건(CJK 없는 질문, 보기 형식, 단일 정답 글자, 이미지 1개, 풀이 혼입·중복 플래그 없음) 통과: 346개, 내부 중복 제거 후 344개 <br> 이미지 검사한 60개: 유사 이미지 보류 7개, 내용 부족 1개, 검수 대기 52개 |
| 판정 | `ready_for_training=false`. 영어 객관식이 적고 기존 풀이는 대부분 중국어 |
| 교훈 | BMMR에는 "영어 객관식 + 검증된 정답"이 부족해서 그대로는 SFT 데이터가 될 수 없습니다 |

출처: `reports/bmmr_data_audit.md`, `data/bmmr_audit/summary.json`

## 2. 도표 풀이 SFT v1 (10/28–29)

| | |
|---|---|
| 가설 | 그림의 위치·연결·기호를 읽고 규칙을 적용하는 풀이로 학습하면 정확도가 오른다. 같은 정답을 두고 "정답만"과 "근거 풀이 포함"을 비교 |
| 데이터 | BMMR train 이미지 38개를 직접 확인. 14개는 보류하고 24개에 새 주석을 씀 → 학습 19개 / 외부 진단 5개 <br> 주석 형식은 `시각 근거 → 적용 규칙 → 짧은 풀이 → Answer: X`. Codex가 작성했고 독립 검수는 없음 <br> 24개 중 4개는 BMMR 원래 답이 틀려서 고침 |
| 학습 | lr 5e-5, warmup 4, 8 epoch(152회 노출, 38 업데이트) <br> 감독 토큰: 정답만 608, 풀이 20,144 <br> 학습 손실: 정답만 6.70 → 0.00001, 풀이 2.86 → 0.72 |
| 평가 | 수정하지 않은 `run_eval.py`로 MMMU val 900문항 × seed 0–4. LoRA는 BF16으로 병합해 평가 |
| 핵심 수치 | 기본 64.93 ± 0.94 <br> **풀이 55.44 ± 0.53**, 기본 대비 −9.49 [−11.51, −7.47] <br> **정답만 50.76 ± 0.55**, 기본 대비 −14.18 [−17.18, −11.22] <br> 풀이 − 정답만: +4.69 [+2.00, +7.40] <br> seed 0 응답 길이 중앙값: 기본 2,690.5자, 풀이 591.5자, 정답만 9자 <br> 학습한 19문항 재풀이: 기본 14, 풀이 11, 정답만 19 |
| 판정 | 두 SFT 모두 크게 하락. 학습 seed 1개, 19문항짜리 작은 파일럿 |
| 교훈 | 짧은 외부 정답 몇십 개로도 모델의 CoT가 무너집니다(응답 길이 −78%, −99.7%). PathVQA 망각 파일럿과 같은 방향입니다 |

뒤에 확인한 점이 하나 있습니다(§3). adapter를 FP32로 실행할 때와 BF16으로 실행할 때 답이 바뀌는 사례가 나왔습니다. 하지만 v1 하락 중 병합 반올림이 차지하는 비율은 측정하지 않았습니다.

출처: `pilot_diagram/README.md`, `reports/diagram_pilot_results.md`, `pilot_diagram/comparison.json`, `pilot_diagram/training_summary.json`, `reports/diagram_sft_v2_plan.md`(응답 길이와 19문항 재풀이)

## 3. 도표 v2: 정보 개입 진단과 소규모 SFT (10/29)

**(a) 정보 개입 진단 (학습 없음)**

| | |
|---|---|
| 목표 | 기본 모델에 무엇을 더 주면 맞히는지 확인: 시각 사실인가, 일반 규칙인가 |
| 데이터 | BMMR train에서 고른 개발용 40문항. 이 문항들은 SFT에서 영구 제외. 5조건 × seed 0/1/2 = 600응답 |
| 핵심 수치 | 기본 83.33% <br> 시각 사실·관계 추가 94.17% (+10.83) <br> 일반 규칙 추가 83.33% (0) <br> 둘 다 추가 96.67% (+13.33, CI [+5.83, +21.67]) <br> 길이를 맞춘 중립 문구 85.83% (+2.50) <br> 시각 사실 − 중립 문구: CI [−0.83, +18.33] |
| 교훈 | 병목은 지식보다 그림에서 사실을 읽어 연결하는 단계라는 관찰입니다. 다만 시각 사실 단독과 중립 문구의 차이는 CI가 0을 포함합니다 |

**(b) 소규모 SFT 4조건**

| | |
|---|---|
| 가설 | "시각 사실 → 규칙 → 적용" 형식의 풀이로 SFT하면, 적어도 학습 문항에서는 +10%p가 난다 |
| 데이터 | BMMR train 후보 657개 중 135개에 주석을 씀. 보호 자료와 연결된 12개와 정답이 불분명한 1개를 빼서 122개 <br> 학습 80 / 잠금 확인 40 / 예비 2. 계획한 160/80/80에는 못 미침 |
| 학습 | 문단형·항목형 target × lr 1e-5·5e-5 = 4조건 <br> 1 epoch = 20 업데이트(warmup 2), 체크포인트 5/10/20 <br> 감독 토큰: 문단형 6,943, 항목형 7,668 |
| 평가 | 학습 문항 중 고정 40개, 생성 seed 0, native LoRA. 대조군은 0으로 채운 adapter <br> 통과 기준: 대조군 대비 +10%p(39/40 이상) |
| 핵심 수치 | 대조군 35/40 <br> 4조건 × 5/10/20 step 정답 수: 1e-5 문단형 35/34/32, 1e-5 항목형 35/31/29, 5e-5 문단형 32/32/27, 5e-5 항목형 33/28/26 <br> 5e-5 문단형 20 step: 응답 길이 중앙값 532.5 → 75.5토큰, 기존 오답 2개를 고치고 새 오답 10개 |
| 판정 | 통과 0개. 개발·확인·공식 평가는 실행하지 않음 |
| 부수 발견 | 같은 adapter라도 PEFT(FP32)와 vLLM native(BF16) 실행 결과가 8문항 중 4개에서 토큰열이, 1개에서 최종 답이 달랐음. adapter 정밀도만 BF16으로 바꾸면 native 출력과 일치. 이후 실험은 native 경로로 평가 |
| 교훈 | 학습할수록 점수가 내려갑니다(5 step → 20 step). 학습 손실이 줄어도 정답률이 오르지는 않습니다 |

출처: `reports/diagram_pilot_results.md`(v2 절), `reports/diagram_sft_v2_plan.md`, `pilot_diagram/v2/README.md`, `pilot_diagram/v2/sft_protocol.json`, `pilot_diagram/v2/diagnostic_summary.json`

## 4. 안정성(stability) SFT: 가끔 맞히는 문항 겨냥 (10/29–31)

**4.1 MMMU val 불안정 문항 분석 (학습 없음)**

- 공식 5 seed의 4,500개 응답을 다시 분석했습니다. 무작위 대체 답으로 맞힌 경우를 빼면, 5번 중 1–3번 맞히는 문항이 213개입니다(0/5 173개, 4/5 87개, 5/5 427개).
- 이 213개 문항의 응답 1,065개 중 369개(34.65%)가 8192토큰에서 잘렸습니다. 안정적으로 맞히는 문항에서는 1.55%입니다. 그러나 같은 문항 안에서 비교하면 오답이 더 길다는 신호가 없어서, "짧게 답하도록 학습하자"는 결론은 내리지 않았습니다.
- seed 하나로 거르면 대부분 놓칩니다. 기존 train80에서 찾은 1–3/5 후보 9개 중 6개가 seed 0에서는 정답이었습니다.

출처: `reports/stability_sft_plan.md`, `scripts/analyze_stability.py`

**4.2 Geometry3K 모집과 A/B SFT**

| | |
|---|---|
| 가설 | 예시 수와 업데이트 수가 같을 때, 기본 모델이 1–3/5로 푸는 "약점" 문항으로 학습하는 쪽(B)이 같은 유형의 무작위 문항으로 학습하는 쪽(A)보다 낫다 |
| 데이터 | InterGPS Geometry3K @ `99e6b529`의 원래 train 2,101문항만 사용. val/test는 중복 보호용으로만 씀 <br> 유형은 선·삼각형·사각형 × 각·길이·비로 제한 <br> 모델 출력을 보기 전에 출처 그룹 단위로 역할 고정: train 234 / dev 117 / 확인 115(보호 후 212/110/110) <br> 351문항에서 최대 5 seed, 응답 1,245개로 정답 빈도를 측정 <br> 최종 세트: A 28 / B 28(5문항 겹침), DEV40 = 약점 12 + 안정 12 + 나머지 16 |
| 정답 풀이 | 어시스턴트가 문제와 그림만 보고 쓰고, 다른 어시스턴트가 검수 <br> 짧은 형식(B 기준 54–138토큰, 중앙값 80) <br> 감독 토큰: A 2,104 / B 2,301 |
| 학습 | **lr 1e-5 고정, warmup 없음, 1 epoch = 7 업데이트**, 체크포인트 4·7 <br> 학습 손실은 거의 그대로: A 2.65 → 2.67, B 2.82 → 2.73 |
| 평가 | DEV40에 새 생성 seed 10을 써서 체크포인트 선택(진입 기준은 B7만 통과) → seed 11·12 추가 |
| 핵심 수치 (seed 10–12 합계) | 전체 /120: 기본 101, A7 103, B7 97 <br> 약점 /36: 기본 21, A7 24, B7 18 <br> 안정 /36: 셋 모두 36 <br> 약점 seed별: 기본 6/6/9, A 8/8/8, B 8/5/5 <br> B − 기본(약점) 95% CI: [−25.00, +5.56]%p |
| 판정 | 사전 기준 6개 중 4개 실패 → `stopped_development_operating_gates_failed`. A의 점추정이 높은 것도 개선으로 인정하지 않음 |
| 후속 진단 | B7에게 자기가 학습한 28문항을 다시 풀게 함: 69/140 → 75/140. 응답 34개가 새로 맞고 28개가 새로 틀림. 고정한 8쌍 중 7쌍은 첫 오류 단계가 그림 읽기 |
| 교훈 | seed 10에서 "통과"한 결과가 seed 11·12에서 뒤집혔습니다. 약점 12문항 × seed 1개로는 체크포인트를 고를 수 없습니다 |

출처: `reports/stability_sampling_protocol_20261030.md`, `reports/stability_review_findings.md`, `pilot_diagram/stability_v1/README.md`, `pilot_diagram/stability_v1/runs/development_aggregate.json`, `reports/stability_step_diagnostic_results_20261031.md`

이 단계의 나머지 보고서는 절차를 고친 개정문이라 따로 읽지 않아도 됩니다.

| 보고서 | 내용 |
|---|---|
| `stability_sft_execution_plan.md` | 원래 설계: 풀이 형식 A/B. 위의 선택 정책 A/B로 대체 |
| `stability_arithmetic_preflight.md` | PEFT와 native 경로 비교. 이후 FP32 master + BF16 autocast를 채택 |
| `stability_semantic_protection_amendment_20261030.md` | TRAIN1707이 DEV780을 회전한 같은 그림임을 발견. 논리식 해시 검사 추가 |
| `stability_source_metadata_amendment_20261031.md` | 유형 표기가 틀린 TRAIN1368을 A·B 양쪽에서 제외 |
| `stability_development_recruitment_extension_20261031.md` | DEV 약점이 7개(최소 12개)뿐이라 dev 74문항에 seed 2–4 추가 생성(222응답) |
| `stability_step_diagnostic_20261031.md` | 위 후속 진단의 사전 등록 |

## 5. 원인 분석 v2–v5 (10/31–11/01)

A/B가 실패한 뒤, 학습이 안 된 것인지, 풀이가 나빴는지, 추론 경로가 문제인지를 하나씩 확인했습니다. 학습 데이터는 모두 B 세트에서 고른 TRAIN24입니다.

| 실험 | 질문 | 설정 | 핵심 수치 | 결론 |
|---|---|---|---|---|
| v2 메커니즘 | 7 업데이트로 목표를 배우기는 했나? 상세 풀이(D)가 간결 풀이(C)보다 나은가? | C는 기존 짧은 풀이(1,990토큰/epoch). D는 어시스턴트 2명이 쓰고 교차검토한 풀이(5,713토큰/epoch). lr 1e-5, 5 epoch = 30 업데이트 | 기존 A7·B7 모두 28/28문항에서 목표 NLL이 감소(기본 2.7239 → A7 2.5800, B7 2.5775) <br> TRAIN24 seed 0: 기본 12, C5 13, D5 18 <br> DEV 약점 /36(seed 13–15): 기본 23, C5 15, D5 24 <br> D5 − 기본: +2.78 [−13.89, +22.22] | 학습은 됐음. 상세 풀이가 간결 풀이보다 낫지만 기본 대비 향상은 없음 |
| v3 그림 관계 주입 (학습 없음) | 정확한 그림 사실(F)을 주면, 길이를 맞춘 일반 지시(G)보다 나은가? | TRAIN24 × seed 0, 1 | F 45/48 vs G 28/48 <br> 차이 +35.42%p [+18.75, +52.08] <br> 생성 토큰: F 106,866 vs G 210,243 | 정답 사실만 주면 대부분 풂. 병목은 그림 사실을 연결하는 단계. 풀이 타당성 기준은 미달 |
| v4 백엔드·학습량 | vLLM BF16 배포 경로에서 효과가 사라지나? 3배(90 업데이트) 학습하면 나아지나? | D 목표 그대로, 15 epoch = 90 업데이트 | 백엔드 NLL 이득: HF 0.7766, native 0.7784 → 통과 <br> DEV 약점 /36(seed 16–18): 기본 22, D30 15, D90 16 <br> 목표 NLL 1.573 → 1.099 <br> 태그 누락은 18 → 5로 줄었지만, 태그는 있는 오답이 5 → 19로 늘어남 | 백엔드는 원인이 아님. 더 학습하면 자신 있게 틀림 |
| v5 디코더·학습 가능성 | presence penalty 1.5가 SFT 효과를 가렸나? 모델이 목표 풀이를 학습할 수 있기는 한가? | (a) TRAIN8, penalty 1.5 vs 0 <br> (b) TRAIN4를 lr 1e-5와 1e-4로 각각 64 업데이트 | (a) penalty 1.5 → 0: 기본 3 → 6, D90 4 → 1(D90은 penalty 0에서 6개 잘림) <br> (b) 목표 NLL 1.047 → 0.003(1e-5), 0.00001(1e-4). greedy 4/4, 교사 풀이를 글자 그대로 재현 | penalty는 원인이 아님. 모델은 풀이를 외울 수 있음. 문제는 일반화 |

출처: `reports/stability_mechanism_v2_results_20261031.md`, `reports/stability_native_relation_probe_v3_results_20261031.md`, `reports/stability_causal_v4_results_20261101.md`, `reports/stability_causal_v5_decoder_trainability_20261101.md`

개정과 보조 보고서는 다음과 같습니다.

- `stability_mechanism_v2_execution_guard_20261031.md`: 실행 코드 해시 고정 추가.
- `stability_learning_trace_changes_20261031.md`: v2 TRAIN7 검수를 다시 집계한 것. 정답 0 → 6/7, 타당한 최종 풀이 0 → 3/7, 오류 없는 풀이 0 → 0.
- `stability_causal_v4_resource_amendment_20261101.md`: GPU 메모리 0.85 → 0.75.
- `stability_causal_v4_instrumentation_repair_20261101.md`: 진단 프로세스에만 `VLLM_ALLOW_INSECURE_SERIALIZATION=1` 적용.

## 6. 외워도 안 되는 이유: v6–v11 (11/01)

| 실험 | 설정 | 핵심 수치 | 결론 |
|---|---|---|---|
| v6 완전 적합 (FIT128) | D90에 lr 1e-4로 128 업데이트 추가(512회 노출, 121,853토큰) | 목표 NLL 1.0991 → 0.00504 <br> TRAIN24 24/24, 그중 20개는 교사 풀이를 글자 그대로 출력 <br> DEV24 seed 16 약점: 기본 8, D90 6, FIT 6 <br> 안정: 12 / 11 / 12 <br> FIT의 DEV 풀이 6개 중 타당한 풀이 0개 | 적합은 전이로 이어지지 않음 |
| v7 새 초기화 (FRESH128) | 같은 128 업데이트를 새 LoRA에서 시작 | TRAIN 24/24 <br> 약점 /36(seed 16–18): 기본 23, FIT128 12, FRESH128 18 | D90의 학습 이력이 더 나쁘게 만들지만, 새로 시작해도 기본 이하 |
| v8 가중치 제거 | FIT128에서 attention 또는 MLP의 LoRA 변화를 0으로 설정 | 약점 /36: 둘 다 제거(기본과 같음) 23, attention만 남김 22, MLP만 남김 22, 둘 다 남김(FIT128) 12 | 두 묶음이 함께 있을 때 손상이 생김. 어느 쪽을 빼도 기본 수준으로 돌아오지만 기본을 넘지는 못함 |
| v9 문구·암기 | "Find x"와 "Compute x", 학습 문항과 비학습 문항 비교 | 학습 문항의 답(6)을 다른 문항에 그대로 쓴 경우 없음 | 답 암기의 증거 없음. 문구 민감성은 있지만 판정 기준 실패 |
| v10 D90 가중치 제거 | v8을 원래 D90에 적용 | 대조 재현 4개 중 1개만 일치해서 8응답 뒤 중단 | 판정 불가 |
| v11 MLP 동결 학습 | 처음부터 attention만 학습(ATTN, MLP 고정)과 전체 학습(FULL) 비교. lr 1e-4, 30 업데이트(120회 노출, 28,565토큰) | DEV24 seed 16 약점: 기본 8, FULL 5 step 4 / 30 step 5, ATTN 5 step 8 / 30 step 5 <br> 안정: 기본 12, FULL 12 / 11, ATTN 12 / 11 | 동결해도 손상이 늦게 올 뿐. 업데이트가 늘수록 DEV 점수가 떨어짐 |

출처: `reports/stability_full24_fit_causal_v6_20261101.md`, `pilot_diagram/stability_v1/causal_diagnostic_closure_v7_v10_20261101.json`(v7, v9, v10은 별도 보고서 없음), `reports/stability_parameter_causal_v8_20261101.md`, `reports/stability_paired_freeze_v11_20261101.md`. v4–v10 종합은 `reports/stability_sft_causal_findings_20261101.md`에 있습니다. v11 전에 쓴 문서입니다.

## 7. Terra 교사와 오류 교정 SFT v12 (11/01)

**Terra 교사 확인.** 질문은 "교사가 못 푸는 문제라서 학생도 못 배운 것인가"였습니다.

- Terra(`gpt-6.1-terra`, reasoning max)에게 문제, 선택지, 그림만 주었습니다.
- TRAIN24는 24/24, DEV 약점 12는 12/12를 맞혔습니다. 풀이는 짧습니다.
- 교사 능력 부족은 원인이 아닙니다. DEV 풀이는 평가에만 쓰고 학습에는 넣지 않았습니다.

출처: `reports/terra61max_teacher_and_student_examples_20261101.md`, `pilot_diagram/stability_v1/teacher_terra61max_v1_20261101/protocol.json`

**v12 오류 교정 SFT**

| | |
|---|---|
| 가설 | 학생 자신의 오류를 보여 주고 고치게 하면 전이된다. A는 오류 다음에 다시 풀기, B는 오류 진단·교정 다음에 다시 풀기 |
| 데이터 | TRAIN24 <br> 정답 풀이: Terra가 쓴 TRAIN 풀이를 그대로 사용. **40–101토큰, 중앙값 59.5** <br> 학생 오류 구간: 기본 모델의 TRAIN 응답(seed 0–4) 중 처음 틀린 것 <br> 교정문: Terra 2명이 쓰고 교차검토. 1문항(train/259)은 보류해서 23개 |
| 학습 | 새 LoRA에서 시작. lr 1e-4, 30 업데이트(120회 노출) <br> 5회 순환: 0·2·4회차는 질문만 주고 풀이 학습, 1·3회차는 오류 맥락을 주고 학습 <br> 감독 토큰: A 7,891, B 11,013 |
| 평가 | DEV24 × seed 16. 기준: 약점 순증 2개 이상, 안정 문항 신규 손실 0개 |
| 핵심 수치 | 목표 NLL(48뷰): A 2.6052 → 0.0974(top-1 62.4% → 97.0%), B 2.5125 → 0.4252 <br> 약점 /12: 기본 8, A 2, B 6 <br> 안정 /12: 기본 12, A 10, B 11 <br> 약점에서 타당한 풀이: 기본 5, A 2, B 1 |
| 판정 | 두 군 모두 실패, 종료 |
| 교훈 | 짧고 정확한 외부 풀이로 바꿔도 결과는 같았습니다. 목표 풀이를 잘 예측하게 되는 것과 새 문제를 푸는 능력은 따로 움직입니다 |

참고: 입력, 초기값, seed가 같아도 5 step 뒤 A와 B의 가중치가 달랐습니다(최대 절대 차이 0.00072). 그래서 B − A 차이에는 수치 잡음도 섞여 있습니다.

출처: `reports/stability_error_feedback_v12_20261101.md`, `pilot_diagram/stability_v1/error_feedback_v12_20261101/training_protocol.json`, 같은 폴더 `training_outputs/*/initial_BASE_feedback_nll.json`(토큰 길이)

## 8. RFT/GRPO 준비와 R0 파일럿 (11/02)

**설계 조사.** 다음 경로로 원래 모델에서 시작하는 LoRA GRPO를 골랐습니다. 비교할 보상은 두 가지였습니다.

- R0: 정답 보상.
- R1: 그림 사실 검증 보상. 검증기가 기준 풀이 24개 중 23개를 unknown으로 판정해서 활성화하지 않았습니다.

출처: `reports/rft_performance_research_20261102.md`

**준비 검사 (optimizer 업데이트 0회)**

TRAIN32(약점 24 + 안정 8)로 다음을 확인했습니다.

| 검사 | 결과 |
|---|---|
| 생성 길이 상한 | 1024에서 첫 2문항 응답 8/8 잘림. 2048에서 4/4 잘림. 4096에서 8개 중 5개 잘림. 기준(32개 중 1개 이하)을 모두 실패 |
| 확률 일치 | 생성 시점의 log prob과 전체 문맥으로 다시 계산한 값의 최대 차이가 0.25–0.49 nats로 기준 0.2를 넘음(평균 차이는 통과) |
| 정답 보상의 한계 | TRAIN242의 응답은 모두 그림의 `ST=TR`을 `SR=TR`로 잘못 읽음. 그중 하나는 틀린 논증으로 정답 D를 맞혔고, 정답 보상은 여기에 +1을 줌 |

출처: `reports/rft_grpo_preflight_20261102.md`

**R0 파일럿**

| | |
|---|---|
| 가설 | 정답 보상 GRPO가 기본 모델을 넘는다 |
| 데이터 | TRAIN32(약점 24 + 안정 8), 약점 3 : 안정 1 순서 |
| 학습 | 새 LoRA(언어층 7개 모듈), lr 5e-6, KL 0.04, PPO clip 0.2 <br> G=4, 32그룹 = 128응답, 응답당 최대 1024토큰, 고정 분모 4×1024(Dr.GRPO 방식) <br> 보상: 정상 종료하고 마지막 `Answer: X` 하나가 정답과 일치하면 1, 그 외(잘림 포함) 0 <br> 준비 검사와 달리 잘린 응답을 그룹에서 빼지 않고 보상 0으로 포함(`R0_protocol.json`의 `truncation_policy`). 생성 시 기록한 행동 정책 μ를 비율의 분모로 사용 |
| 학습 기록 | 32 업데이트 완료 <br> 128응답 중 **84개가 길이 제한으로 종료**, 보상 1은 34개 <br> 정오가 섞여 학습 신호가 생긴 그룹: 13개(약점 10, 안정 3) <br> 나머지 19그룹(전부 0점 15, 전부 1점 4)은 KL 항만으로 업데이트 |
| 평가 | DEV24 × seed 16, native, 기존 CoT 프롬프트 그대로 |
| 핵심 수치 | 전체 20/24 → 19/24 <br> 약점 8 → 7 (새로 맞힘: 1095, 새로 틀림: 2055·908) <br> 안정 12 → 12 <br> 약점에서 정답이면서 풀이도 타당: 5 → 5 |
| 판정 | 기준(약점 순증 2개 이상) 실패, 종료 |
| 교훈 | 1024토큰 상한에서는 응답 대부분이 잘려 학습 신호가 32그룹 중 13그룹에만 생겼습니다. 이 파일럿만으로 RFT의 효과를 판단할 수는 없습니다 |

출처: `reports/rft_grpo_v2_20261102.md`, `pilot_diagram/stability_v1/rft_grpo_v2_20261102/R0_protocol.json`

마지막 두 실험(v12 SFT와 R0 GRPO)은 모두 DEV24 seed 16 하나로 판정했습니다. 약점 문항 결과는 SFT가 8 → 2 또는 6, GRPO가 8 → 7입니다. 안정 문항 결과는 SFT가 12 → 10 또는 11, GRPO가 12 → 12입니다. 같은 조건의 SFT 대 RFT 비교는 아니므로 망각 차이를 입증한 것은 아닙니다.

## 전체 교훈

1. **외부 풀이 SFT는 작은 데이터에서 일관되게 손해였습니다.** MMMU 전체로 잰 유일한 결과는 −9.5점과 −14.2점입니다. Geometry3K에서도 모든 변형이 약점 DEV에서 기본 이하였습니다. 목표 NLL이 0에 가깝고 학습 문항을 24/24로 풀어도 처음 보는 문항으로는 전이되지 않았습니다.
2. **병목은 그림 사실의 연결이고, 지식은 아닙니다.** 그림 사실을 직접 주면 크게 오릅니다(83.3% → 94.2%, F 45/48 vs G 28/48). 일반 규칙을 주면 변화가 없었습니다. 정답 풀이를 따라 쓰게 하는 SFT는 이 단계를 가르치지 못했습니다.
3. **출력 형식이 쉽게 무너집니다.** 짧은 target으로 학습하면 응답이 짧아집니다(2,690자 → 9자, 532 → 75토큰). 망각 파일럿과 같은 현상입니다. 모델 자신의 풀이 방식을 유지하는 학습(자기 생성 target, RL)이 필요하다는 근거입니다.
4. **이 규모의 평가로는 고를 수 없습니다.** 약점 12문항 × seed 1개의 95% CI 폭이 수십 %p였습니다. seed 10의 "통과"는 seed 11·12에서 뒤집혔습니다. DEV도 여러 번 다시 썼습니다. 이후 GRPO 단계는 216문항 진단과 MMMU 900문항 평가로 넘어갔습니다.
5. **엔지니어링 함정이 실제로 결과를 바꿉니다.** adapter의 FP32/BF16 실행 차이로 답이 바뀌었습니다. 생성 시점과 재계산 확률이 불일치했습니다. 1024토큰 상한에서는 응답의 66%가 잘렸습니다. 학습 결과를 해석하기 전에 실행 경로와 생성 예산부터 맞춰야 합니다.

## 원문 위치

| 실험 | 레포에 있는 것 (✓) | 레포에 없는 원문 (로컬 보관) |
|---|---|---|
| BMMR 감사 | ✓ `reports/bmmr_data_audit.md`, `data/bmmr_audit/*summary.json`, `scripts/audit_bmmr.py` | — |
| 도표 v1 | ✓ `reports/diagram_pilot_results.md`, `pilot_diagram/` 코드·주석·결과, `pilot_diagram/runs/mmmu_{answer,rationale}/` (MMMU 5 seed 응답 전문) | 병합 가중치 |
| 도표 v2 | ✓ `pilot_diagram/v2/` 요약 JSON | `reports/diagram_sft_v2_plan.md`, 어댑터, 학습 데이터 |
| 안정성 A/B | ✓ `pilot_diagram/stability_v1/cohort/dataset_lock.json`, `runs/development_aggregate.json` | `reports/stability_sft_plan.md`, `stability_sampling_protocol_20261030.md`, `stability_review_findings.md` |
| 원인 분석 v2–v11 | ✓ `pilot_diagram/stability_v1/mechanism_v2/corpus.json`, `causal_diagnostic_closure_v7_v10_20261101.json` | `reports/stability_*_v2…v11_*.md`, `stability_sft_causal_findings_20261101.md` |
| Terra, v12 | ✓ `reports/stability_error_feedback_v12_20261101.md`, `pilot_diagram/stability_v1/error_feedback_v12_20261101/` 설정·학습 데이터 | `reports/terra61max_teacher_and_student_examples_20261101.md` |
| RFT R0 | ✓ `reports/rft_grpo_v2_20261102.md`, `pilot_diagram/stability_v1/rft_grpo_v{1,2}_20261102/` 설정·판정 | `reports/rft_performance_research_20261102.md`, `rft_grpo_preflight_20261102.md` |

stability_v1의 코드(176개 파일)는 서로 해시로 묶여 있어 일부만으로는 실행되지 않으므로 넣지 않았습니다. 레시피는 protocol JSON과 이 문서에 있습니다.

**확인하지 못한 점**

- v1 하락 중 BF16 병합 반올림이 차지하는 비율은 측정하지 않았습니다.
- 약점 12문항 × seed 16–18에서 기본 모델 점수가 보고서마다 다릅니다. v4·Terra 보고서는 22/36, v7·v8은 23/36(0 adapter)이고, 보고서 안에서 이 차이를 설명하지 않습니다.
- 정답 풀이와 풀이 검수는 모두 모델이 했습니다(Codex, Terra). Terra의 실제 모델 스냅샷은 확인할 수 없습니다.
- 모든 실험의 학습 seed는 0 하나입니다.
