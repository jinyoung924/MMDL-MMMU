# 사용 데이터셋 조사 — Qwen3-VL-4B 파인튜닝(데이터셋 조사 + contamination test)

# 1. 데이터셋 조사
## 우선순위 1

| 0. 데이터셋 이름 | 1. 간단한 설명 | 2. 사용할 부분 | 3. 채택 이유 | 4. Contamination 테스트 결과 |
|---|---|---|---|---|
| [CoSyn-400K music](https://huggingface.co/datasets/allenai/CoSyn-400K) | CoSyn의 악보 subset, 이미지 12.1K장. LLM이 생성한 code로 렌더링한 합성 이미지와 code 기반 QA(question·explanation·answer) | | | |
| [MusiXQA](https://huggingface.co/datasets/puar-playground/MusiXQA) | MusiXTeX로 만든 합성 악보 9,600장 + MIDI·structured annotation. pitch·duration·chord·clef·key/time signature QA(OMR형). MIT | | | |
| [CoSyn-400K circuit](https://huggingface.co/datasets/allenai/CoSyn-400K) | CoSyn의 회로도 subset, 이미지 10.6K장. question·explanation·answer | | | |
| [CircuitVQA](https://github.com/rahcode7/Circuit-VQA) | 회로도 5,725장(hand-drawn 3,175 + schematic 2,550), 기호 약 70종, 사람 bbox annotation 기반 template QA 115K개 이상. counting·spatial counting·position·value·junction 5개 유형 | | | |
| [CoSyn-400K chemical](https://huggingface.co/datasets/allenai/CoSyn-400K) | CoSyn의 분자 구조 subset, 이미지 9.07K장. question·explanation·answer | | | |

- CoSyn-400K는 ODC-BY license. QA는 GPT-4o mini로 생성.

## 우선순위 2

| 0. 데이터셋 이름 | 1. 간단한 설명 | 2. 사용할 부분 | 3. 채택 이유 | 4. Contamination 테스트 결과 |
|---|---|---|---|---|
| [PathVQA](https://huggingface.co/datasets/flaviagiammarino/path-vqa) | 병리 이미지 4,998장, open-ended QA 32,799개. 위치·모양·색·외형을 묻는 질문. 병리 교과서·PEIR 라이브러리 이미지의 caption에서 반자동 생성 후 수작업 검수 | | | |
| [SLAKE](https://huggingface.co/datasets/BoKelvin/SLAKE) | radiology 이미지 642장, 영·중 bilingual QA 약 14K(train 9,849). 의사 annotation과 medical knowledge base 포함 | | | |
| [VQA-RAD](https://huggingface.co/datasets/flaviagiammarino/vqa-rad) | radiology 이미지 315장(head·chest·abdomen), clinician이 만든 QA 3,515개. CC0 | | | |
| [PubMedVision](https://huggingface.co/datasets/FreedomIntelligence/PubMedVision) | PubMed 이미지-텍스트 쌍을 GPT-4V로 재구성한 의료 VQA 1,294,062개. MMMU Health & Medicine 향상 보고 | | | |
| [ChemVQA-2K](https://ieee-dataport.org/documents/chemvqa-2k-visual-question-answering-dataset-molecular-understanding) | SMILES로 렌더링한 분자 이미지 1,924장, 분자당 QA 10개(총 19,240개) | | | |
| [SSMR-Bench train (AutoMusicTheoryQA)](https://github.com/Linzwcs/AutoMusicTheoryQA) | MelodyHub 악보에 music theory rule을 적용해 생성한 추론 문제. train visual 8,000 + textual 8,000. Rhythm·Chord·Interval·Scale, 정답 검증 가능(CoT 없음) | | | |
| [NOTA](https://huggingface.co/datasets/MYTH-Lab/NOTA-dataset) | 악보 이미지 기반 1,019,237 records, 3 tasks. 악보 이미지 ↔ ABC notation alignment, music information extraction, notation analysis | | | |
| [OpenMMReasoner-SFT-874K](https://huggingface.co/datasets/OpenMMReasoner/OpenMMReasoner-SFT-874K) | 원문 QA 약 103K개에 Qwen3-VL-235B-Instruct로 reasoning trace를 여러 개 distill한 SFT 874K(RL 74K 별도) | | | |
| [ViRL39K](https://huggingface.co/datasets/TIGER-Lab/ViRL39K) | RL용 verifiable QA 38,870개, 모델 크기별 PassRate annotation. MIT | | | |

- PathVQA·SLAKE·VQA-RAD를 평가에도 쓰면 train split만 학습에 넣는다.
- OpenMMReasoner·ViRL39K는 perception 데이터가 아니라 reasoning 유지·RL 단계용 보조 데이터다.

---


# 2. Contamination test

### 용어

| 용어 | 정의 |
|---|---|
| T (training set) | 2열에서 확정한 학습 데이터 최종본(CoT 재생성·포맷 변환 후) |
| E (evaluation set) | MMMU dev 150 + validation 900, MMMU-Pro 1,730. domain 평가셋을 쓰면 추가 |
| Contamination | E 문항의 이미지·질문·정답이 T에 들어 있는 상태 |
| Decontamination | T에서 오염 샘플을 제거하는 것 |
| Exact / Near-duplicate | 완전히 같음 / resize·crop·압축 등으로만 다름 |
| Paraphrase | 표현만 바꾼(재작성·번역) 같은 문제 |
| Cross-modal / Unimodal | 이미지와 질문이 함께 겹침 / 한쪽만 겹침 |
| Flagged / Clean item | 1단계에서 T와 match된 E 문항 / 나머지 E 문항 |
| Recall | 실제 오염 중 검출 파이프라인이 찾아낸 비율 |
| Residual contamination | 제거 후에도 검출되지 않고 남은 오염 |
| Inflation | 오염 때문에 생기는 정답률 상승 |

**E 구성**
- MMMU test 10,500은 정답이 비공개라 test 제출 시에만 포함한다.
- MMMU-Pro는 validation split 없이 test 1,730문항이 전부이고, 3개 config(standard 4·10 options, vision)가 같은 문항을 공유한다. ID에 `test_*`가 섞여 MMMU test 출신 문항이 있는 것으로 보이므로(ID 기준 추정) MMMU와 별도로 넣는다.
- 평가에 쓰는 데이터셋(예: PathVQA test)은 train split만 T에 넣는다.

### 1. Detection (data-level)

| 대상 | 방법 | match 기준 |
|---|---|---|
| Image · exact | 디코딩·RGB 변환 후 SHA-256 | 해시 일치 |
| Image · near-duplicate | SSCD embedding cosine similarity. E를 index로 두고 T 이미지마다 max similarity 계산 | ≥ 0.95. 그 아래는 E 변형본(crop·resize·JPEG) similarity 하위 1%까지 육안 검토 |
| Text · exact | 정규화한 question + options의 13-gram | 1개 이상 일치(13 token 미만은 전체 일치) |
| Text · paraphrase | embedding top-5 후보 → LLM judge | judge가 같은 문제로 판정 |

- 정규화: 소문자, 공백·구두점 통일, `<image n>`·보기 기호 제거.
- MMMU는 문항당 이미지 최대 7장 → 이미지 단위로 비교 후 문항 단위로 집계. MMMU-Pro vision 이미지(질문을 담은 screenshot)도 index에 포함.
- Template 질문(T 안에서 같은 문자열 10회 이상, 예: "How many resistors are in the circuit?")은 image match와 함께일 때만 인정. CircuitVQA·CoSyn·PathVQA 등에 해당.
- LLM이 생성·재작성한 데이터(PubMedVision, OpenMMReasoner, CoT 재생성본)도 동일하게 검사한다.
- PubMedVision·OpenMMReasoner·ViRL39K처럼 실제 이미지나 공개 데이터를 모은 데이터를 먼저 검사한다. MMMU도 교과서·온라인 자료에서 수집돼 원천이 겹칠 수 있다.

### 2. Sample-level decontamination

| 등급 | 조건 | 조치 |
|---|---|---|
| A. Cross-modal | image + question match | 제거 |
| B. Unimodal (image) | image만 match | 제거. 같은 이미지의 다른 QA가 정답 단서를 담을 수 있음 |
| C. Unimodal (text) | question만 match | judge가 같은 문제로 판정하면 제거 |
| D. Clean | match 없음 | 유지 |

### 3. Dataset-level risk assessment
검출에는 false negative가 있으므로, 검출된 오염이 많은 데이터셋일수록 제거 후에도 residual contamination이 남을 가능성이 크다. 이를 수치로 판정한다.

- **Recall r**: MMMU val 50 + MMMU-Pro 50문항의 변형본(image 변형 / paraphrase·번역 / 둘 다)을 T 사본에 넣고 1단계로 다시 찾은 비율. 데이터셋에 해당하는 변형 유형 중 최솟값을 쓴다. 측정 후 변형본은 폐기한다.
- **k**: 데이터셋이 적중한 E 문항 수(2단계 A·B·C, 벤치마크별)
- **Residual estimate** = k × (1 − r) / r
- **Residual inflation** = Residual estimate ÷ E 문항 수. 남은 오염 문항을 모두 맞혔을 때의 정답률 상승 상한(MMMU val 1문항 = 0.11%p, MMMU-Pro 1문항 = 0.058%p)

| 판정 | 조건 | 조치 |
|---|---|---|
| Safe | k = 0 | 그대로 사용 |
| Use after removal | Residual inflation < 0.5%p | 2단계 제거 후 사용 |
| Risky | Residual inflation ≥ 0.5%p | 제외. 꼭 써야 하면 포함/제외 ablation으로 영향만 보고 |

- 적중의 과반이 한 subset에 몰리면 그 subset을 먼저 통째로 제외하고 다시 계산한다.
- 벤치마크별로 판정해 더 나쁜 쪽을 따른다.
- 예: k = 6, r = 0.8 → Residual estimate 1.5 → MMMU val 0.17%p → Use after removal.
- 0.5%p와 100문항은 기준 예시다. 0.5%p는 기대 향상폭보다 충분히 작게 조정한다.

### 4. Behavioral test (model-level)
Qwen3-VL-4B base의 기존 오염은 통제할 수 없으므로 base와 fine-tuned(FT)의 차이만 본다.

| 검사 | 방법 | 오염 신호 |
|---|---|---|
| Clean vs flagged | flagged·clean item 각각의 정답률 변화 비교(McNemar test, bootstrap 95% CI) | flagged 향상폭이 clean보다 유의하게 큼 |
| Option order sensitivity | 보기 순서 permutation 3개로 재평가 | FT의 정답률 하락이 base보다 유의하게 큼 |
| Blind test | 이미지를 같은 크기의 빈 이미지로 교체 | FT 후 새로 맞힌 문항이 1단계 후보와 겹침 |

- Blind 정답률 상승은 text-only 지식 학습으로도 생기므로 1단계 후보와 겹칠 때만 memorization으로 본다. MMMU-Pro standard는 text-only로 풀리는 문항을 걸러낸 셋이라 신호가 더 강하다. vision config는 blind test에서 제외한다.
- 최종 보고에는 전체 정답률과 clean item 정답률을 함께 적는다.

### 기록 형식
- 표 4열: `exact a · near-dup b · 13-gram c · paraphrase d · A/B/C = x/y/z · 제거 n건 (n/N%) · 적중 MMMU k₁ / Pro k₂ · 판정`

| Benchmark | Config | Item 수 (clean / flagged) | Acc base → FT (clean) | Acc base → FT (flagged) | Option order Δ (base / FT) | Blind acc (base / FT) |
|---|---|---|---|---|---|---|
| MMMU | validation | | | | | |
| MMMU-Pro | standard (10 options) | | | | | |
| MMMU-Pro | vision | | | | | 해당 없음 |

### 도구 · 참고
- 도구: SSCD(Pizzi et al., CVPR 2022) + FAISS, [llm-decontaminator](https://github.com/lm-sys/llm-decontaminator), [MM-Detect](https://github.com/MLLM-Data-Contamination/MM-Detect), lmms-eval
- FineVision §2.4 — [arXiv 2510.17269](https://arxiv.org/abs/2510.17269): SSCD + cosine 0.95로 66개 benchmark 대상 decontamination
- Rethinking Benchmark and Contamination for Language Models with Rephrased Samples — [arXiv 2311.04850](https://arxiv.org/abs/2311.04850): n-gram은 paraphrase를 놓침 → embedding + LLM judge
- MM-Detect — [arXiv 2411.03823](https://arxiv.org/abs/2411.03823): cross-modal / unimodal 구분, option order sensitivity
- MMMU — [arXiv 2311.16502](https://arxiv.org/abs/2311.16502), MMMU-Pro — [arXiv 2409.02813](https://arxiv.org/abs/2409.02813)