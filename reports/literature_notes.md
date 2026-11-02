# 문헌 조사 노트 — 방향 설정용 (2026-09-25)

범위는 실패 진단이 제기한 **두 질문**으로 한정했습니다. 목록을 늘리기보다, 전략의 갈림길을 판단하는 데 필요한 근거만 모았습니다.

1. 좁은 도메인으로 fine-tuning하면 VLM이 원래 잘하던 것을 얼마나 잊는가? RL(RFT)은 정말 덜 잊는가?
2. RL이 고칠 수 있는 실패와 고칠 수 없는 실패는 무엇인가?

**확인 방식**: 핵심 논문은 arXiv·학회 페이지와 본문을 직접 열어 수치를 확인했습니다. "추가" 항목은 초록 페이지만 확인했습니다.
수치는 각 논문이 보고한 값 그대로이며, 우리 설정과의 차이는 "주의" 칸에 적었습니다.

---

## 질문 1. 좁은 fine-tuning의 망각과 SFT vs RL

| 논문 | 설정 | 핵심 결과 | 주의 |
|---|---|---|---|
| Lai et al., *Reinforcement Fine-Tuning Naturally Mitigates Forgetting in Continual Post-Training*, arXiv 2507.05386 | Qwen2.5-VL-7B, VQA 7개 과제 순차 학습(PathVQA·Geometry3K 포함), 전체 파라미터 | 망각: SFT −10.4% vs GRPO −2.3%. MMMU(CoT) 52.1 → SFT 40.1 / GRPO 54.2. Qwen3-VL-8B: −7.1% vs −0.2%. 기제: 모든 rollout의 보상이 같은 프롬프트는 업데이트가 없음 | 목표 향상이 맞춰지지 않음(PathVQA: SFT 62.2 vs GRPO 41.3), 단일 실행 |
| Zhang et al., *Why Reinforcement Fine-Tuning Enables MLLMs Preserve Prior Knowledge Better: A Data Perspective*, ICLR 2026, arXiv 2506.23508 | Qwen2.5-VL-7B, 직소 퍼즐 학습 | MMMU(base 51.3): RFT 50.0 / 정답만 SFT **22.4** / GPT-4o 풀이 SFT 46.1 / GRPO 정책 rollout SFT 48.8. SFT가 목표 정확도는 더 높음(80 vs 75) | 합성 과제 1개, 학습 스텝 수 차이(RFT 약 27k vs SFT 400) |
| Luo et al., *RL Forgets! Towards Continual Policy Optimization*, arXiv 2607.04364 (2026.07 preprint) | **Qwen3-VL-4B**(2B·8B도), 2025년 데이터 5개 과제 순차, full SFT vs LoRA r=128 vs GRPO | 외부 11개 벤치 평균(base 59.5): full SFT 45.3 / LoRA 55.6 / GRPO 53.2. MMMU-Pro(base 51.2): 25.7 / 39.7 / 40.6. **GRPO가 LoRA-SFT보다 덜 잊지 않음.** GRPO의 KL 페널티는 새 학습만 늦추고 보존에는 도움 안 됨 | 동료 심사 전. SFT는 직답, RL은 추론을 생성 |
| Chen et al., *Retaining by Doing: The Role of On-Policy Data in Mitigating Forgetting*, ICML 2026, arXiv 2510.18874 | Llama·Qwen2.5 Instruct 1–8B, IFEval·MMLU·Countdown (텍스트) | 원인은 on-policy 데이터(KL 항·advantage 추정은 배제). Llama-8B Countdown: SFT 목표 +25.5 / 다른 곳 −36.4 vs GRPO +60.4 / +0.5. epoch마다 재생성한 데이터 → 망각 거의 없음. **초기 모델에서 한 번 뽑은 자기 정답으로 SFT(Self-SFT)는 크게 잊음** | 텍스트. 목표가 현재 행동과 멀면 RL도 잊음(자체 시뮬레이션) |
| Shenfeld et al., *RL's Razor: Why Online Reinforcement Learning Forgets Less*, ICLR 2026, arXiv 2509.04259 | Qwen2.5-3B-Instruct(수학·과학·도구), OpenVLA-7B, MNIST 장난감 | 새 과제 입력에서의 KL(base→tuned)이 망각을 예측(R² 0.96 장난감 / 0.71 LLM). 자기 정답 1-0 REINFORCE ≈ GRPO, 부정 예시 오프라인 학습 ≈ SFT | 텍스트. KL이 왜 망각을 부르는지는 설명 없음 |
| Biderman et al., *LoRA Learns Less and Forgets Less*, TMLR 2024, arXiv 2405.09673 | Llama-2-7B, 코드·수학 | LoRA는 full fine-tuning보다 덜 잊음(코드: 일반 점수 0.631 vs 0.512). 수학에서는 full이 절충이 더 나음 | 텍스트, 도메인 의존 |
| Zhai et al., *Investigating the Catastrophic Forgetting in Multimodal Large Language Model Fine-Tuning*, CPAL 2024, arXiv 2309.10313 | LLaVA-7B/13B | CIFAR-10으로 LoRA 1 epoch 뒤 MNIST 정확도 56.96% → 0.01% | 2023 모델, 좁은 답 형식 |
| Chu et al., *SFT Memorizes, RL Generalizes*, ICML 2025, arXiv 2501.17161 | Llama-3.2-Vision-11B, 카드 게임·내비게이션 | 보지 못한 변형에서 RL은 향상, SFT는 붕괴(내비게이션 텍스트판 +11.0 vs −79.5). 출력 형식은 SFT가 먼저 필요 | 무관한 능력의 보존은 보지 않음 |
| Lee & Choi, *The Role of Training Targets in Forgetting during Fine-Tuning of Time Series Foundation Models*, IJIBC (in press) | Chronos-T5, Moirai, 전체 파라미터 | 출력 이동량(KL)을 맞춰도 망각은 **학습 목표가 모델 생성인가 외부 관측인가**로 갈림(8개 조건 중 7). RAFT(best-of-G) ≈ GRPO, SFT+push는 효과 없음, 초기 적응 뒤 고정한 목표도 매 스텝 재샘플링과 비슷하게 보존 | 정답이 하나뿐인 시계열 설정. 사전학습 정책에서 바로 고정한 목표는 비교에서 제외 |

추가 (초록만 확인): Yang et al. ACL 2024, arXiv 2402.13669 (정답을 모델 자신의 말로 다시 써서 학습 → SFT보다 덜 잊음) ·
Shenfeld et al. 2026, arXiv 2601.19897 (시연을 보고 자기 자신이 교사가 됨 → SFT보다 덜 잊음) ·
Wang et al. 2026, arXiv 2607.01763 (조밀한 on-policy 자기 증류는 GRPO보다 더 잊음) ·
EAFT, arXiv 2601.02151 (SFT 망각을 모델의 확신 예측과 충돌하는 외부 정답 토큰으로 추적) ·
RaPO, arXiv 2605.09640 (모델 생성 정답이어도 drift가 망각과 연결) ·
Li et al. 2026, arXiv 2603.14493 (낮은 학습률이나 LoRA가 대부분의 망각을 막음, 질문 형식 과적합은 예외) ·
Zhu et al., arXiv 2510.08564 (Qwen2.5-VL-7B에서 attention 투영만 조정: 보류 과제 +0.6 vs full −17.5) ·
Jin et al., arXiv 2509.12235 (SFT 뒤의 RL이 SFT 후반에 잃은 OOD 추론을 되살림, 일부 체크포인트에서만).

### 질문 1의 결론

1. **VLM에서 좁은 SFT의 망각은 크다.** 기본 설정에서 MMMU·MMMU-Pro 기준 12~29점이 빠졌습니다(Lai, Zhang, Luo).
   우리 모델과 같은 Qwen3-VL-4B에서도 LoRA-SFT가 MMMU-Pro를 11.5점 잃었습니다(Luo). 망각은 우리 전략의 핵심 변수입니다.
2. **"RL이 덜 잊는다"는 우리 설정에서 전제가 아니라 검증할 가설입니다.**
   - 목표 향상을 맞춘 텍스트 연구와 예전 VLM 과제에서는 성립했습니다.
   - 그러나 **Qwen3-VL-4B + 2025년 과제에서는 GRPO가 LoRA-SFT보다 낫지 않았습니다**(Luo).
   - 따라서 비교 실험에는 **LoRA-SFT를 반드시 기준선으로** 넣고, LoRA 설정을 방법 간에 고정해야 합니다.
3. **자기 생성 정답은 주기적으로 다시 뽑아야 합니다.**
   - Chen은 초기 모델에서 한 번 뽑은 자기 정답(Self-SFT)이 크게 잊는다고 보고했습니다.
   - Lee & Choi도 "초기 적응 뒤 고정"만 검증했고, 사전학습 모델에서 바로 고정하는 경우는 제외했습니다.
   - 따라서 RAFT는 한 번 뽑고 끝내는 방식이 아니라 **epoch마다 다시 뽑는 반복형**으로 설계해야 합니다.
4. **VLM에서 정답 출처의 효과를 보여준 연구는 Zhang 하나**입니다(정답만 22.4 < GPT-4o 풀이 46.1 < 정책 rollout 48.8 < RFT 50.0).
   **STaR식 힌트 유도 자기 생성 정답의 망각을 잰 VLM 연구는 찾지 못했습니다.** 이동량을 맞춘 상태에서 정답 출처를 비교한 LLM·VLM 연구도 없습니다.
5. **24GB GPU에서 가능한 완화책**: 낮은 학습률의 LoRA(또는 attention만 조정), 일반 데이터 섞기, 자기 생성 정답의 epoch별 재생성,
   WiSE-FT(원 가중치와 보간), 학습 중 KL 모니터링. **GRPO의 KL 페널티는 효과가 없었습니다**(Lai, Luo).

---

## 질문 2. RL이 고칠 수 있는 것과 없는 것

| 논문 | 설정 | 핵심 결과 | 주의 |
|---|---|---|---|
| Yue et al., *Does Reinforcement Learning Really Incentivize Reasoning Capacity in LLMs Beyond the Base Model?*, NeurIPS 2025 (oral), arXiv 2504.13837 | Qwen2.5 ~32B(수학·코드), Qwen2.5-VL-7B(Geometry3K → MathVista/MathVision) | RL은 k=1에서 이기고 큰 k에서는 base가 이김(Minerva 32B, k=128에서 base가 약 9점 높음). AIME24에서 RL만 푼 문제 0%, base만 푼 문제 13.3%. 학습할수록 pass@256 하락. VLM 결과도 "매우 일치" | base 모델이 RL 전 모델 |
| Liu et al., *ProRL*, NeurIPS 2025, arXiv 2505.24864 | DeepSeek-R1-Distill-Qwen-1.5B, 약 16k H100시간 | 긴 RL로 base가 못 풀던 과제도 풂. 향상은 base가 약한 곳에서 가장 큼 | 계산량 막대, 텍스트 |
| Yan et al., *LUFFY: Learning to Reason under Off-Policy Guidance*, NeurIPS 2025, arXiv 2504.14945 | Qwen2.5-Math-7B, LLaMA-3.1-8B | 교사(R1) 풀이를 GRPO 그룹에 섞으면, on-policy RL이 보상 0에 머무는 어려운 데이터에서도 학습 | 수학. 새 능력은 교사 풀이에서 옴 |
| Shen et al., *Does RLVR Extend Reasoning Boundaries? Investigating Capability Expansion in Vision-Language Models*, arXiv 2511.00710 | Qwen2.5-VL-7B, Qwen3-VL-4B/8B, 합성 미로 | base가 k=512에서도 0%인 미로에서 RL이 약 10% 도달. 실제 과제 전이는 작음(ReasonMap 6.00 → 7.47%) | 합성 탐색 과제, 조밀 보상 + 커리큘럼, 지각과 무관 |
| Xiao et al., *Perception-R1: Advancing Multimodal Reasoning Capabilities of MLLMs via Visual Perception Reward*, ICLR 2026, arXiv 2506.07218 | Qwen2.5-VL-7B, Geometry3K 1,442문항 | **정답만 보상하는 GRPO는 지각을 유의하게 바꾸지 못함**, 지각 보상을 더하면 개선(McNemar p=0.04). MMMU 55.2 → GRPO 58.0 → Perception-R1 60.8 | 검정 50문항, 재현 base(55.2)가 공식(58.6)보다 낮음, 7B 판정 모델은 보상 해킹 |
| Wang et al., *PAPO: Perception-Aware Policy Optimization for Multimodal Reasoning*, ICLR 2026, arXiv 2507.06448 | Qwen2.5-VL-3B/7B, Qwen3-VL-2B-Thinking | 오답 200건 중 **67%가 지각 오류**. PAPO는 지각 오류를 30.5% 줄임. MMMU-Pro는 절대 +1.5(7B: 35.2 → 36.6) | 모델이 이 손실을 악용해 학습 붕괴 → 엔트로피 손실 추가 필요 |
| Wang et al., *InternVL3.5*, arXiv 2508.18265 | 1B–241B, Cascade RL(MPO → GSPO) | 4B: MMMU 64.3(SFT) → 65.4(MPO) → 66.6. 8B의 MPO 단계는 약 0.3K GPU시간에 +3.1 | 대규모 데이터, 자체 평가 |
| Yu et al., *DAPO*, NeurIPS 2025, arXiv 2503.14476 · Liu et al., *Understanding R1-Zero-Like Training (Dr. GRPO)*, COLM 2025, arXiv 2503.20783 | Qwen2.5-32B, 수학 | GRPO의 편향이 오답을 길게 만듦(Dr. GRPO가 수정). DAPO: Clip-Higher, dynamic sampling, 토큰 단위 손실, 과도한 길이에 부드러운 페널티 | **dynamic sampling은 늘 틀리는 문항을 버림** |
| *Qwen3-VL Technical Report*, arXiv 2511.21631 | — | 4B-Instruct MMMU 67.4(4B-Thinking 70.8). 사후학습에 RL이 이미 포함됨. 모델 카드 권장: presence_penalty 1.5, 이미지 입력 시 출력 최대 16,384 토큰 | — |

### 질문 2의 결론

1. **RL은 불안정 그룹(가끔 맞힘)에 맞고, 안정 오답(한 번도 못 맞힘)에는 학습 신호가 없습니다.** 모든 논문이 RL이 pass@1을 pass@k 쪽으로 끌어올린다는 데 동의합니다.
2. **정답만 보상하는 RL은 지각을 거의 개선하지 못합니다**(Perception-R1). 지각이 우리의 가장 큰 실패 유형이므로, 지각 보상이나 지각 정보가 담긴 데이터가 따로 필요합니다.
3. **현실적 기대치는 4B급 MMMU +1~3점**입니다. 우리 모델은 이미 RL을 거친 Instruct 모델이라 이보다 작을 수 있습니다.
4. 루프·잘림은 길이·반복 페널티로 줄일 수 있지만, 먼저 권장 설정(출력 16,384)으로 얼마나 회수되는지 봐야 합니다(진행 중인 실험).

---

## 방향 가설 (진단 × 문헌)

| 진단 그룹 | 처방 후보 | 근거 | 우리 실험에서 검증할 것 |
|---|---|---|---|
| 불안정 (가끔 맞힘) | 반복형 RAFT(epoch마다 재생성) 또는 GRPO | Yue, Chen, Lee & Choi | RAFT vs GRPO vs LoRA-SFT의 향상과 망각 |
| 안정 오답: 지각 | 지각 정보가 담긴 데이터 SFT, 힌트 유도 자기 생성, 지각 보상 RL | Perception-R1, PAPO, Zhang | **정답 출처별 망각** (VLM에서 선행연구 없음) |
| 안정 오답: 문항 결함 | 학습 표적에서 제외 | 사례집의 D 판정 | — |
| 안정 정답 | 망각 측정 기준 | — | MMMU 안정 정답 + 외부 벤치마크(MMMU-Pro 등) |

---

## 질문 3. 실패 유형별 개선 방법 (2026-09-26 추가)

지각(P)·지식(K)·생성(G)·추론(R) 실패를 고치는 방법에 대한 근거입니다. 모두 arXiv·학회 페이지와 본문으로 확인했고,
**(표)** 표시는 표에서 옮긴 수치라 인용 전에 원문 대조가 필요합니다. 적용 판단은 [`improvement_strategy.md`](improvement_strategy.md).

| 논문 | 질문 | 핵심 결과 | 주의 |
|---|---|---|---|
| Tong et al., *Cambrian-1*, NeurIPS 2024, arXiv 2406.16860 | 인코더 학습 | 인코더를 풀면 지식 벤치마크(MMMU 포함)를 뺀 모든 벤치마크가 오름. 지식 쪽은 "미미한 변화" | 수치 차이는 본문에 없음 |
| Karamcheti et al., *Prismatic VLMs*, ICML 2024, arXiv 2402.07865 | 인코더 학습 | 인코더 전체 미세조정이 성능을 유의하게 떨어뜨림(p=0.0038) | 소규모 데이터, LoRA 변형 없음 |
| Lu et al., *PathChat*, Nature 2024 | 병리 | 병리 전용 인코더 + 대규모 데이터로 이미지만의 객관식 진단 78.1%(GPT-4V 25.0%) | 인코더 효과 분리 불가, 규모가 큼 |
| Yang et al., *MolRecBench-Wild*, arXiv 2605.05832 | 구조식 | 실제 분자 이미지: 전문 인식기 MolScribe 41.1% > InternVL3.5 25.6% > 화학 특화 VLM 4.8~9.8% (표) | 인식 ≠ MMMU 풀이 |
| Yang et al., *LEGATO 2*, arXiv 2607.05769 | 악보 | OMR 전사를 문맥으로 주면 VLM의 악보 QA가 크게 오름(예: 51.8 → 71.7) (표) | frontier 모델만 시험 |
| Zhang et al., *MM1.5*, ICLR 2025, arXiv 2409.20566 | 캡션 데이터 | 고품질 합성 캡션이 단순 OCR 데이터보다 낫다는 결론적 증거 없음 | MMMU 단독 효과 미분리 |
| Zhang et al., *ViCrop*, ICLR 2025, arXiv 2502.17422 | 확대·크롭 | 학습 없는 주의 기반 크롭: V* 42.4 → 62.3, 일반 VQA는 +1 이내 (표) | 오래된 저해상도 모델 |
| Zheng et al., *DeepEyes*, ICLR 2026, arXiv 2505.14362 | 확대·크롭 | RL로 학습한 확대 도구: V* +18.9, 수학 추론 +1.7~1.9 (표) | 다중 GPU RL |
| Jiang et al., *KORE*, ICML 2026, arXiv 2510.19316 | 지식 주입 | Qwen2.5-VL-7B 보존 점수 66.9 → LoRA 주입 38.2 → 제약 어댑터 58.3 (표) | 뉴스·개체 지식, 점수 정의 미확인 |
| Hu et al., *MRAG-Bench*, ICLR 2025, arXiv 2410.08182 | RAG | 정답 지식을 검색해 줘도 GPT-4o +5.8%(사람 +33.2%) | — |
| Pipis et al., *Why Do Reasoning Models Loop?*, arXiv 2512.12895 | 루프 | greedy 루프 비율 R1-distill 1.5B/7B/32B = 76/49/37%, 어려운 문제일수록 증가. temperature는 임시방편 | 텍스트 수학 |
| Yeo et al., *Demystifying Long CoT*, arXiv 2502.03373 | 루프 | 길이 보상은 해킹되며, n-gram 반복 페널티로 완화 | 텍스트 |
| Wang et al., *VisualPRM*, arXiv 2503.10291 | 다수결 | MMMU-val N=8: InternVL2.5-8B 56.2 → 자기일관성 58.0 → PRM best-of-8 60.2 (표) | PRM은 별도 8B 모델 |
