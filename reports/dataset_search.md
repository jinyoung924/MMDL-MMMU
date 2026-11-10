# 사용 데이터셋 조사 — Qwen3-VL-4B 파인튜닝(데이터셋 조사 + contamination test)

# 1. 데이터셋 조사

> 2·3열은 데이터셋 카드·논문·저장소 원문을 직접 열어 확인한 내용입니다. 4열은 2장 절차를 코드로 옮긴 `decontam/`을 RunPod에서 돌린 결과로 채웁니다. 1열에서 원문과 다른 부분은 각 표 아래 **확인 메모**에 적었습니다.
## 우선순위 1

| 0. 데이터셋 이름 | 1. 간단한 설명 | 2. 사용할 부분 | 3. 채택 이유 | 4. Contamination 테스트 결과 |
|---|---|---|---|---|
| [CoSyn-400K music](https://huggingface.co/datasets/allenai/CoSyn-400K) | CoSyn의 악보 subset, 이미지 12.1K장. LLM이 생성한 code로 렌더링한 합성 이미지와 code 기반 QA(question·explanation·answer) | train 12k장 전체(validation 128장은 남겨 둠). 이미지당 QA 5~10개의 question·explanation·answer를 쓰고 explanation을 풀이로 사용 | 악보는 모델이 늘 틀리는 그림 유형의 대표. 정답이 렌더링 코드에서 나와 정확하고, 합성 이미지라 MMMU 이미지와 겹칠 위험이 낮음. **주의**: QA를 이미지가 아니라 코드를 보고 만들어 그림에 안 보이는 내용을 묻는 문항이 섞일 수 있어 표본 검수 필요 | exact - · near-dup - · 13-gram 0 · paraphrase - · A/B/C = 0/0/0 · 제거 0건 (0.00%) · 적중 MMMU 0 / Pro 0 · Safe (간이 검사: 이미지 검사 생략(합성: LilyPond 렌더), paraphrase 미검사) |
| [MusiXQA](https://huggingface.co/datasets/puar-playground/MusiXQA) | MusiXTeX로 만든 합성 악보 9,600장 + MIDI·structured annotation. pitch·duration·chord·clef·key/time signature QA(OMR형). MIT | `train_qa_simple.json`(chord·layout·OCR QA). 음표를 하나하나 옮겨 적는 `train_qa_omr.json`은 제외 | 조표·박자·화음처럼 악보 기호 자체를 읽는 연습이 됨. 합성(MusiXTeX)·MIT. **주의**: 답이 템플릿 문자열이라 MMMU식 짧은 답으로 바꿔야 함 | exact - · near-dup - · 13-gram 0 · paraphrase - · A/B/C = 0/0/0 · 제거 0건 (0.00%) · 적중 MMMU 0 / Pro 0 · Safe (간이 검사: 이미지 검사 생략(합성: MusiXTeX 렌더), paraphrase 미검사) |
| [CoSyn-400K circuit](https://huggingface.co/datasets/allenai/CoSyn-400K) | CoSyn의 회로도 subset, 이미지 10.6K장. question·explanation·answer | train 10.5k장 전체, music과 같은 방식 | 회로도는 늘 틀리는 문항에서 '그림을 잘못 봄'이 잦은 유형. 정답이 코드에서 나오고 합성 이미지(LaTeX 렌더) | exact - · near-dup - · 13-gram 0 · paraphrase - · A/B/C = 0/0/0 · 제거 0건 (0.00%) · 적중 MMMU 0 / Pro 0 · Safe (간이 검사: 이미지 검사 생략(합성: LaTeX 렌더), paraphrase 미검사) |
| [CircuitVQA](https://github.com/rahcode7/Circuit-VQA) | 회로도 5,725장(hand-drawn 3,175 + schematic 2,550), 기호 약 70종, 사람 bbox annotation 기반 template QA 115K개 이상. counting·spatial counting·position·value·junction 5개 유형 | train QA 80,548개. counting·position·value 위주로 쓰고, junction(yes/no, 전체의 약 58%)은 줄여서 유형 균형을 맞춤 | 실제 손그림·회로도 이미지라 합성 데이터보다 MMMU 그림에 가까움. 정답이 bounding box 정보에서 나와 기계 채점 가능. **주의**: 실제 이미지라 이미지 겹침 검사가 특히 중요, CC-BY-SA 3.0(같은 조건으로 공유) | exact 0 · near-dup 0 · 13-gram 0 · paraphrase - · A/B/C = 0/0/0 · 제거 0건 (0.00%) · 적중 MMMU 0 / Pro 0 · Safe (간이 검사: near-dup은 pHash, paraphrase 미검사) |
| [CoSyn-400K chemical](https://huggingface.co/datasets/allenai/CoSyn-400K) | CoSyn의 분자 구조 subset, 이미지 9.07K장. question·explanation·answer | train 8.94k장 전체, music과 같은 방식 | 화학 구조식은 '무엇을 봐야 하는지 알아야 읽히는' 그림의 대표. RDKit 렌더라 정답이 정확 | exact - · near-dup - · 13-gram 0 · paraphrase - · A/B/C = 0/0/0 · 제거 0건 (0.00%) · 적중 MMMU 0 / Pro 0 · Safe (간이 검사: 이미지 검사 생략(합성: RDKit 렌더), paraphrase 미검사) |

- CoSyn-400K는 ODC-BY license. QA는 GPT-4o mini로 생성.

**확인 메모 (1열과 원문이 다른 곳)**
- **CoSyn-400K**: train/validation split이 있음(카드 표현으로 "unofficial", validation 128장). QA는 이미지당 5~10개, 답은 한 단어·구·숫자. 이미지 코드는 Claude 3.5 Sonnet, QA와 풀이는 GPT-4o mini가 이미지 없이 코드만 보고 작성. MMMU 오염 검사 언급 없음. ([카드](https://huggingface.co/datasets/allenai/CoSyn-400K), [논문](https://arxiv.org/abs/2502.14846))
- **MusiXQA**: 논문 안에서 악보 수가 9,600장(서론)과 96k(3.1절)로 서로 다름. QA 유형은 OCR·OMR·layout·chord 네 가지이고, clef·key·time signature는 QA 유형이 아니라 주석 종류. ([논문](https://arxiv.org/abs/2506.23009), [파일 목록](https://huggingface.co/datasets/puar-playground/MusiXQA/tree/main))
- **CircuitVQA**: QA는 115,582개(train 80,548 / val 11,721 / test 23,313). 질문 문장은 ChatGPT로 만든 유형별 문장 약 20개를 돌려 쓰고, 정답은 원 데이터의 bounding box에서 만들되 spatial counting·value는 저자가 직접 라벨링. 이미지는 Roboflow·Kaggle의 실제 회로 이미지. 다운로드는 Google Drive. ([저장소](https://github.com/rahcode7/Circuit-VQA), [ECML-PKDD 2024](https://mlanthology.org/ecmlpkdd/2024/mehta2024ecmlpkdd-circuitvqa))

## 우선순위 2

| 0. 데이터셋 이름 | 1. 간단한 설명 | 2. 사용할 부분 | 3. 채택 이유 | 4. Contamination 테스트 결과 |
|---|---|---|---|---|
| [PathVQA](https://huggingface.co/datasets/flaviagiammarino/path-vqa) | 병리 이미지 4,998장, open-ended QA 32,799개. 위치·모양·색·외형을 묻는 질문. 병리 교과서·PEIR 라이브러리 이미지의 caption에서 반자동 생성 후 수작업 검수 | HF train split(19,654 QA, 이미지 2,599장). 절반을 차지하는 yes/no는 비율을 낮추고 open 답 위주 | MMMU 의학 과목의 병리 이미지와 같은 종류. **주의**: 병리 교과서와 PEIR 라이브러리 이미지라 MMMU와 출처가 겹칠 수 있음. 팀 파일럿에서 yes/no 답만 학습하자 MMMU가 −2.89점 떨어졌으므로 풀이를 포함한 형식으로만 사용 | exact 0 · near-dup 0 · 13-gram 1 · paraphrase - · A/B/C = 0/0/0 · 제거 0건 (0.00%) · 적중 MMMU 0 / Pro 0 · Safe (간이 검사: near-dup은 pHash, paraphrase 미검사) |
| [SLAKE](https://huggingface.co/datasets/BoKelvin/SLAKE) | radiology 이미지 642장, 영·중 bilingual QA 약 14K(train 9,849). 의사 annotation과 medical knowledge base 포함 | train split의 영어 QA만(4,919개, 이미지 450장) | 의사가 만든 영상의학 QA. 이미지는 공개 의료영상 데이터셋(NIH ChestX-ray, Medical Segmentation Decathlon, CHAOS)에서 와서 교과서 출처가 아님. **주의**: open 답은 자유 서술이라 기계 채점이 어려움 | exact 0 · near-dup 0 · 13-gram 0 · paraphrase - · A/B/C = 0/0/0 · 제거 0건 (0.00%) · 적중 MMMU 0 / Pro 0 · Safe (간이 검사: near-dup은 pHash, paraphrase 미검사) |
| [VQA-RAD](https://huggingface.co/datasets/flaviagiammarino/vqa-rad) | radiology 이미지 315장(head·chest·abdomen), clinician이 만든 QA 3,515개. CC0 | train split(1,793 QA, 이미지 313장) | 영상의학 보조 데이터. **주의**: test 이미지 거의 전부가 train에도 있어 VQA-RAD로 학습하면 VQA-RAD test는 평가에 쓸 수 없음. MedPix 교육 사례(웹)라 겹침 검사 필요 | exact 0 · near-dup 0 · 13-gram 0 · paraphrase - · A/B/C = 0/0/0 · 제거 0건 (0.00%) · 적중 MMMU 0 / Pro 0 · Safe (간이 검사: near-dup은 pHash, paraphrase 미검사) |
| [PubMedVision](https://huggingface.co/datasets/FreedomIntelligence/PubMedVision) | PubMed 이미지-텍스트 쌍을 GPT-4V로 재구성한 의료 VQA 1,294,062개. MMMU Health & Medicine 향상 보고 | InstructionTuning VQA(647,031개) 중 MMMU 의학 과목과 맞는 modality만 소량 샘플 | MMMU 의학 점수 향상을 보고한 데이터. **주의**: 그 결과는 8B LLaVA에 다른 데이터와 함께 학습한 것이고 오염 검사가 없었음. 답이 긴 서술이라 자동 채점 불가, 이미지 약 60GB | exact - · near-dup - · 13-gram 0 · paraphrase - · A/B/C = 0/0/0 · 제거 0건 (0.00%) · 적중 MMMU 0 / Pro 0 · Safe (간이 검사: 이미지 검사 생략(이미지 60GB라 텍스트만), paraphrase 미검사) |
| [ChemVQA-2K](https://ieee-dataport.org/documents/chemvqa-2k-visual-question-answering-dataset-molecular-understanding) | SMILES로 렌더링한 분자 이미지 1,924장, 분자당 QA 10개(총 19,240개) | 19,240 QA 전부. 공식 split이 없어 직접 나눔 | 분자식·분자량·원자 수·작용기 같은 짧은 답을 RDKit으로 계산해 정답이 정확. **주의**: 무작위 조각을 이어 만든 분자라 실제 화합물이 아님, IEEE DataPort는 구독 필요(Mendeley 미러는 로그인 여부 미확인) | 미검사 (데이터를 받지 못함: IEEE DataPort 구독 필요. 합성(RDKit 렌더)이라 이미지 겹침 위험은 낮음) |
| [SSMR-Bench train (AutoMusicTheoryQA)](https://github.com/Linzwcs/AutoMusicTheoryQA) | MelodyHub 악보에 music theory rule을 적용해 생성한 추론 문제. train visual 8,000 + textual 8,000. Rhythm·Chord·Interval·Scale, 정답 검증 가능(CoT 없음) | `Train_visual` 8k(필요하면 `Train_textual` 8k 추가) | 4지선다라 MMMU 형식과 같고 답이 정해져 있어 GRPO 보상에 바로 쓸 수 있음. **주의**: 풀이(CoT)가 없어 SFT용이면 풀이를 따로 만들어야 함 | exact - · near-dup - · 13-gram 0 · paraphrase - · A/B/C = 0/0/0 · 제거 0건 (0.00%) · 적중 MMMU 0 / Pro 0 · Safe (간이 검사: 이미지 검사 생략(합성: 악보 렌더), paraphrase 미검사) |
| [NOTA](https://huggingface.co/datasets/MYTH-Lab/NOTA-dataset) | 악보 이미지 기반 1,019,237 records, 3 tasks. 악보 이미지 ↔ ABC notation alignment, music information extraction, notation analysis | `train_IE` 중 조·박자·제목처럼 답이 짧은 정보 추출 문항 일부 | 악보 정보 추출 데이터가 많음. **주의**: HF에 실제로 있는 건 707,539행(153GB). analysis는 자유 서술, alignment는 ABC 전사 전체라 제외 | exact - · near-dup - · 13-gram 0 · paraphrase - · A/B/C = 0/0/0 · 제거 0건 (0.00%) · 적중 MMMU 0 / Pro 0 · Safe (간이 검사: 이미지 검사 생략(이미지가 행에 없어 텍스트만), paraphrase 미검사) |
| [OpenMMReasoner-SFT-874K](https://huggingface.co/datasets/OpenMMReasoner/OpenMMReasoner-SFT-874K) | 원문 QA 약 103K개에 Qwen3-VL-235B-Instruct로 reasoning trace를 여러 개 distill한 SFT 874K(RL 74K 별도) | 지각 데이터에 섞을 보조용으로 소량만 샘플. `<think>…</think><answer>…</answer>` 형식을 평가 형식(`Answer: X`)으로 변환 | 그림 데이터만 학습하면 풀이 습관이 무너지는 것을 막는 용도. **주의**: AI2D·ScienceQA 같은 교과서풍 데이터가 섞여 있고 MMMU 오염 검사를 하지 않았다고 되어 있어, 우리 검사가 필수 | exact - · near-dup - · 13-gram 47 · paraphrase - · A/B/C = 0/0/4 · 제거 4건 (0.00%) · 적중 MMMU 0 / Pro 2 · 판정 보류(text recall 미측정) (간이 검사: 이미지 검사 생략(이미지가 행에 없어 텍스트만), paraphrase 미검사) |
| [ViRL39K](https://huggingface.co/datasets/TIGER-Lab/ViRL39K) | RL용 verifiable QA 38,870개, 모델 크기별 PassRate annotation. MIT | GRPO 단계용. Science·Tables/Diagrams/Charts 카테고리 위주 | 답이 `\boxed{}`로 기계 채점 가능해 GRPO 보상에 바로 쓰임. **주의**: PassRate는 7B·32B 모델 기준이라 우리 4B 모델로 다시 재야 함(`grpo/passrate_filter.py`). AI2D·ScienceQA가 섞여 있어 오염 검사 필요 | exact 0 · near-dup 0 · 13-gram 4 · paraphrase - · A/B/C = 0/0/1 · 제거 1건 (0.00%) · 적중 MMMU 0 / Pro 1 · Risky (간이 검사: near-dup은 pHash, paraphrase 미검사) |

- PathVQA·SLAKE·VQA-RAD를 평가에도 쓰면 train split만 학습에 넣는다.
- OpenMMReasoner·ViRL39K는 perception 데이터가 아니라 reasoning 유지·RL 단계용 보조 데이터다.

**확인 메모 (1열과 원문이 다른 곳)**
- **PathVQA**: "open-ended QA"가 아니라 약 절반(49.8%)이 yes/no. HF판은 중복 제거 후 32,632 QA·이미지 4,289장(train 19,654 / val 6,259 / test 6,719). 이미지 출처는 병리 교과서 2권과 PEIR. ([카드](https://huggingface.co/datasets/flaviagiammarino/path-vqa), [논문](https://arxiv.org/abs/2003.10286))
- **SLAKE**: HF train은 9,835행이고 그중 영어는 4,919개(나머지는 중국어). ([HF 통계](https://datasets-server.huggingface.co/statistics?dataset=BoKelvin/SLAKE&config=default&split=train), [논문](https://arxiv.org/abs/2102.09542))
- **VQA-RAD**: 3,515는 원래 만든 질문 수이고 공개된 QA는 2,248개(HF 중복 제거 후 2,244). 작성자는 의대생·전공의 15명. 이미지가 train 313장, test 203장인데 전체가 315장이라 test 이미지 중 최소 201장이 train에도 있음(카드 수치로 계산). ([카드](https://huggingface.co/datasets/flaviagiammarino/vqa-rad), [논문](https://www.nature.com/articles/sdata2018251))
- **PubMedVision**: 1,294,062 = Alignment 647,031 + InstructionTuning 647,031, 이미지 914,960장. MMMU 의학 향상은 LLaVA-v1.5-LLaMA3-8B 기준(검증셋 38.6 → 50.3)이고 MMMU 오염 검사 언급 없음. ([카드](https://huggingface.co/datasets/FreedomIntelligence/PubMedVision), [논문](https://arxiv.org/abs/2406.19280))
- **ChemVQA-2K**: 분자는 실제 화합물이 아니라 무작위 조각을 이어 만든 것. 공식 split 없음, IEEE DataPort는 구독 필요. ([IEEE DataPort](https://ieee-dataport.org/documents/chemvqa-2k-visual-question-answering-dataset-molecular-understanding))
- **SSMR-Bench**: 문항 유형은 9종(`class_name`), "MelodyHub" 출처와 Scale 카테고리는 원문에서 확인하지 못함. 4지선다(정답 1 + 오답 3), CoT 없음. ([HF](https://huggingface.co/datasets/Sylence/SSMR-Bench), [논문](https://arxiv.org/abs/2509.04059))
- **NOTA**: 1,019,237은 논문 초록의 수치이고(논문 안에서도 수치가 서로 다름), HF에 실제 올라온 건 707,539행. ([HF](https://huggingface.co/datasets/MYTH-Lab/NOTA-dataset), [논문](https://arxiv.org/abs/2502.14893))
- **OpenMMReasoner**: 103K를 Qwen3-VL-235B로 질문당 8번 distill해 걸러 낸 것이 약 583K이고, 나머지는 MMR1·MiroMind-M1 수학 데이터를 더한 것. 하위셋 llava_cot 554K·mmr1 199K·m1_sft 92K·OpenVLThinker 22.2K·WeMath 6.94K. ([HF](https://huggingface.co/datasets/OpenMMReasoner/OpenMMReasoner-SFT-874K), [논문](https://arxiv.org/abs/2511.16334))
- **ViRL39K**: PassRate는 두 모델(32B 학습본, 7B base) 기준이고, 7B 열은 32B가 다 맞힌 문항(약 절반)에만 있고 나머지는 −1. ([HF](https://huggingface.co/datasets/TIGER-Lab/ViRL39K), [논문](https://arxiv.org/abs/2504.08837))

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
