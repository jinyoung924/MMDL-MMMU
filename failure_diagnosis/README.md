# 실패 진단 사례집 — baseline (Qwen3-VL-4B-Instruct, MMMU val)

Baseline 모델이 **어떤 이미지와 질문을 받고, 어떻게 풀다가 틀렸는지**를 유형별 무작위 사례로 모은 폴더입니다.
전수 목록이 아닙니다. 판정 기준은 [태깅 절차](../reports/failure_tagging_protocol.md)를 따릅니다.

## 1. 어떻게 뽑았나

| 단계 | 내용 |
|---|---|
| 모집단 | 두 실행(`ablation/cot_8192_seed0_run2` = seed 0, `ablation/cot_8192_seed1` = seed 1; 수정된 파서, 일반 모드)에서 **둘 다 틀린 248문항**. 한 번만 틀린 문항은 운일 수 있어 제외 |
| 무작위화 | 248문항을 고정 seed 0으로 섞음 → [order.txt](order.txt) |
| 판정 | 섞인 순서의 **앞 48문항**을 절차대로 판정 → [tags.jsonl](tags.jsonl) |
| 수록 | 유형별로 그 순서의 **앞 최대 5문항**. 순서가 무작위이므로 유형 안에서도 무작위 표본 |
| 채점 오류(S) | 모델 실패가 아니라 파이프라인 실패라 모집단이 다름: 수정 전 파서로 채점한 `ablation/cot_8192_seed0_run1`의 버그 12건([tags_scoring.jsonl](tags_scoring.jsonl)) 중 같은 방식으로 2건 |

## 2. 누가 판정했나 (한계부터)

- **48문항 판정**: Claude 에이전트 4개가 절차에 따라 모든 이미지를 직접 열고 판정했습니다.
- **수록 23건 검수**: 판정 에이전트와 별도로 Claude가 이미지와 풀이를 다시 확인했습니다. 판정을 바꾼 사례는 0건이고 비고를 보강했습니다.
  각 사례의 "검수" 줄에 확인 범위(이미지를 직접 봤는지)를 적었습니다.
- **기계 검증**:
  - "첫 오류" 인용문 48건 중 47건이 응답 원문과 글자 단위로 일치합니다(Music_22만 요약 인용).
  - Electronics_13의 선택지 중복은 스크립트로 확인했습니다.
  - G 10건은 두 응답이 모두 잘렸음을 자동으로 확인했습니다.
- **사람 검수 전입니다.** 태거와 검수자가 같은 계열 모델이라 같은 사각지대를 가질 수 있습니다.
  특히 병리·신경해부·악보 사례의 P/K/PK 판정과, "정답표가 틀렸다"는 D 판정은 팀 검수가 필요합니다.
- 태그는 **"모델이 쓴 풀이에서 처음 틀린 곳"을 관찰한 것**입니다. 그 오류가 오답의 원인인지는 개입 실험
  (빠진 정보를 주면 맞히는가)으로 따로 확인해야 합니다.

## 3. 48문항 판정 분포

| 유형 | 건수 | 비율 | 확신도 high / medium | 수록 |
|---|---|---|---|---|
| P 지각 | 21 | 44% | 14 / 7 | 5 |
| G 생성 실패 | 10 | 21% | 10 / 0 | 5 |
| K 지식 | 8 | 17% | 5 / 3 | 5 |
| D 문항 결함 | 6 | 13% | 2 / 4 | 5 |
| T 텍스트 이해 | 2 | 4% | 1 / 1 | 2 |
| PK 지각/지식 구분 불가 | 1 | 2% | 0 / 1 | 1 |
| R 추론 | 0 | 0% | — | 0 |
| S 채점 오류 / X 거부 | 0 | 0% | — | S는 별도 모집단에서 2 |

표본이 48건이라 비율의 오차가 큽니다(예: P 44%의 95% 신뢰구간은 약 31~58%).

## 4. 관찰

1. **지각(P)이 가장 큰 실패 유형입니다.**
   - 끝까지 풀었고 문항에도 문제가 없는 32건만 보면 P 21건(66%), K 8건(25%), T 2건, PK 1건입니다.
   - 독립 연구(PAPO, Wang et al., ICLR 2026)가 VLM 오답 200건에서 보고한 지각 오류 비율 67%와 비슷합니다.
   - 오독한 대상은 악보, 가계도 구조, 그래프 좌표, 당 구조식, 조각품의 재질·자세였습니다. 대부분 "아는 것"이 아니라 "보는 것"의 문제입니다.
2. **추론(R)이 0건입니다.** 계산 실수 같은 추론 오류는 샘플링에 따라 맞기도 하고 틀리기도 하므로, "두 번 다 틀린" 문항에는 거의 남지 않는 것으로 보입니다.
   가설: 추론 오류는 불안정 그룹(가끔 맞힘)에 몰려 있습니다. 불안정 그룹을 따로 분석해 확인해야 합니다.
3. **문항 결함(D)이 무시할 수 없는 크기입니다.**
   - 48건 중 6건(13%)입니다. 모집단 248건에 같은 비율을 적용하면 약 31건이고, 이는 **MMMU val 900문항의 약 3%가 어떤 모델도 맞힐 수 없는 문항**일 수 있다는 뜻입니다.
   - 학습 표적에서 빼야 하고, 점수 상한을 해석할 때도 고려해야 합니다.
4. **생성 실패(G) 중 일부는 결함 문항에서 비롯된 것으로 보입니다.**
   - Accounting_15(표의 수치와 맞는 보기가 없음), Energy_and_Power_20(그림의 150 m와 본문의 100 m가 충돌)은 모델이 존재하지 않는 답을 찾느라 헤매다 잘린 것으로 보입니다.
   - 이런 유형은 생성 예산을 늘려도 회수되지 않습니다.
5. **데이터 품질 문제**: Art_Theory_5는 스톤헨지를 묻는데 이미지는 무관한 루벤스 그림입니다. 문항 자체는 지식만으로 풀 수 있어 K로 판정했습니다.

## 5. 사례 목록

| 유형 | 문항 | 과목 | 이미지 유형 | 난이도 | 무엇이 잘못됐나 |
|---|---|---|---|---|---|
| P | [Art_Theory_20](P_perception/validation_Art_Theory_20/case.md) | Art_Theory | Photographs | Easy | 에트루리아 테라코타 석관을 '나무로 된, 잠든 부부의 중세 무덤 조각'으로 묘사 |
| P | [Biology_22](P_perception/validation_Biology_22/case.md) | Biology | Diagrams | Easy | 근친 가계도에서 A를 위쪽 부부의 '딸'로 오독 (실제는 배우자) |
| P | [Biology_29](P_perception/validation_Biology_29/case.md) | Biology | Chemical Structures | Easy | 말토스 구조식(α1→4)을 '배치가 다르다'며 버리고 과당 고리가 있는 수크로스를 선택 |
| P | [Music_21](P_perception/validation_Music_21/case.md) | Music | Sheet Music | Hard | 호른 III 음을 A#으로 오독 (실제 기보음 C5 → 실음 F4, 바이올린 II C#5와 증5도) |
| P | [Pharmacy_4](P_perception/validation_Pharmacy_4/case.md) | Pharmacy | Plots and Charts | Medium | 그래프의 점 (3.6, 8.5)를 (4, 10)으로 읽어 질량비가 다르다고 결론 |
| K | [Art_Theory_5](K_knowledge/validation_Art_Theory_5/case.md) | Art_Theory | Paintings | Medium | 스톤헨지가 장부맞춤을 쓰지 않았다고 단정 (실제로 사용). 이미지는 무관한 루벤스 그림 |
| K | [Design_13](K_knowledge/validation_Design_13/case.md) | Design | Paintings | Medium | 알렉산더 모자이크의 미세 테세라 목적을 '운반 용이성'으로 오해 |
| K | [Diagnostics_and_Laboratory_Medicine_7](K_knowledge/validation_Diagnostics_and_Laboratory_Medicine_7/case.md) | Diagnostics_and_Laboratory_Medicine | Microscopic Images | Medium | 병변은 정확히 묘사했으나 '타박상은 표층 이랑을 침범'한다는 지식 부족 |
| K | [Economics_23](K_knowledge/validation_Economics_23/case.md) | Economics | Tables | Hard | 현금 예금이 그 자체로 M1을 늘린다고 봄 (늘어나는 건 통화승수 효과분뿐) |
| K | [Finance_24](K_knowledge/validation_Finance_24/case.md) | Finance | Tables | Medium | 정당화 P/E 공식을 잘못 씀 (g, r은 맞게 구함) |
| T | [Chemistry_30](T_textual/validation_Chemistry_30/case.md) | Chemistry | Other | Medium | '원소 기호로 쓰라'는 지시를 무시하고 MX로 답함 |
| T | [Manage_11](T_textual/validation_Manage_11/case.md) | Manage | Diagrams | Medium | '비판자가 말하는 편익의 특성이 아닌 것'을 '단점인 것'으로 거꾸로 해석 |
| PK | [Basic_Medical_Science_25](PK_perception_or_knowledge/validation_Basic_Medical_Science_25/case.md) | Basic_Medical_Science | Medical Images | Easy | 미주신경 배측운동핵을 의문핵으로 판단 (위치 오독인지 지식 부족인지 구분 불가) |
| G | [Accounting_15](G_generation/validation_Accounting_15/case.md) | Accounting | Tables | Medium | 보기에 맞추려 계산을 반복하다 잘림 (표 수치로는 어느 보기와도 안 맞아 문항 결함 의심) |
| G | [Electronics_6](G_generation/validation_Electronics_6/case.md) | Electronics | Diagrams | Hard | 교류 회로 절점해석을 복소수 수기 계산으로 끌다 잘림 |
| G | [Energy_and_Power_20](G_generation/validation_Energy_and_Power_20/case.md) | Energy_and_Power | Diagrams | Hard | 같은 문단을 반복하는 루프 (그림 150 m와 본문 100 m 충돌, 보기 단위 오기 → 문항 결함 의심) |
| G | [Materials_13](G_generation/validation_Materials_13/case.md) | Materials | Diagrams | Hard | 전단 변형률 계산 방법을 여러 번 바꾸다 잘림 |
| G | [Materials_30](G_generation/validation_Materials_30/case.md) | Materials | Diagrams | Medium | 축 방향 해석을 여러 가지로 바꿔 보다 잘림 |
| D | [Basic_Medical_Science_22](D_item_defect/validation_Basic_Medical_Science_22/case.md) | Basic_Medical_Science | Diagrams | Medium | X연관 열성과 일치하는 가계도인데 정답표는 '불가능(False)' |
| D | [Chemistry_11](D_item_defect/validation_Chemistry_11/case.md) | Chemistry | Plots and Charts | Easy | 곡선은 '강산에 강염기 적정'(D)인데 정답표는 반대 방향 (B) |
| D | [Chemistry_23](D_item_defect/validation_Chemistry_23/case.md) | Chemistry | Plots and Charts | Medium | 시료 흡광도가 주어지지 않아 풀 수 없는 문항 |
| D | [Electronics_13](D_item_defect/validation_Electronics_13/case.md) | Electronics | Plots and Charts | Medium | 선택지 A와 C가 글자까지 동일 |
| D | [Manage_27](D_item_defect/validation_Manage_27/case.md) | Manage | Paintings | Hard | 'Emotional'은 pathos의 뜻이라 정답이 둘 (C와 A 모두 방어 가능) |
| S | [Marketing_25](S_scoring/validation_Marketing_25/case.md) | Marketing | Tables | Hard | 모델은 정답을 썼으나 옛 정규식이 'Answer'의 A를 읽음 (수정 완료) |
| S | [Math_14](S_scoring/validation_Math_14/case.md) | Math | Diagrams | Easy | 모델은 정답을 썼으나 옛 정규식이 'Answer'의 A를 읽음 (수정 완료) |

## 6. 폴더 구조

```
failure_diagnosis/
├── README.md             이 문서
├── tags.jsonl            48문항 판정 전체 (수록 여부와 무관하게 전부, 검수 기록 포함)
├── tags_scoring.jsonl    채점 오류(S) 12건 판정
├── order.txt             248문항의 무작위 순서 (감사용)
└── <유형>/<문항 ID>/
    ├── case.md           메타데이터 · 진단 · 이미지 · 문제 원문 · 두 풀이 전문
    └── image_N.png       모델이 본 이미지
```

## 7. 다시 만들기

```bash
# 1) 태깅할 문항 추출: 고정 seed로 섞은 순서의 앞 48문항
python analyze.py export ablation/cot_8192_seed0_run2 ablation/cot_8192_seed1 --out <작업폴더> --sample 48 --seed 0
# 2) <작업폴더>/untagged/* 를 reports/failure_tagging_protocol.md 절차로 태깅 → tags.jsonl
# 3) 유형별 사례 폴더 생성
python analyze.py export ablation/cot_8192_seed0_run2 ablation/cot_8192_seed1 --out failure_diagnosis \
    --tags failure_diagnosis/tags.jsonl --per-type 5 --seed 0
python analyze.py export ablation/cot_8192_seed0_run1 --out failure_diagnosis \
    --tags failure_diagnosis/tags_scoring.jsonl --per-type 2 --seed 0
```

`export`는 `datasets`가 필요하므로 vLLM 환경의 python으로 실행합니다. 공식 5 seed 실행(`results/seed0..4`)이 끝나면,
같은 명령에 그 폴더들을 넣어 "5번 모두 틀린 문항" 기준으로 다시 만들 수 있습니다.

## 8. 이미지 사용 주의

MMMU 이미지의 저작권은 원 출처에 있고, 데이터셋은 연구 목적으로 배포됩니다. 팀 저장소를 공개한다면 이 폴더의
`*.png`는 커밋에서 제외하는 것을 권장합니다.

## 9. Diagnostics 정밀 분석 (공식 5 seed 기준, 2026-09-26)

가장 약한 과목(Diagnostics_and_Laboratory_Medicine, 5 seed 평균 34.0)에서, 5번 모두 맞힌 4문항을 뺀 **26문항 전부**를 판정했습니다
([diagnostics_deepdive.jsonl](diagnostics_deepdive.jsonl)). 가끔 맞힌 문항은 틀린 풀이와 맞은 풀이를 나란히 비교했습니다.
문항마다 ① 이미지 해석이 맞았는지 ② 그 해석대로라면 결론이 따라오는지 ③ 이미지에 필요한 정보가 있는지를 따로 기록했습니다.
판정은 Claude 에이전트가 했고, 가장 강한 주장 4건(#2, #17, #18, #21)은 이미지로 다시 확인했습니다(4건 모두 일치).

| 항목 | 결과 (26문항) |
|---|---|
| 이미지 해석 | 틀림 11 · 일부만 맞음 7 · 맞음 5 · 확인 불가 3 → **해석 실패가 약 70%** |
| 해석이 맞았을 때의 실패 | 5건: 지식 3(#7, #13, #28), 추론 1(#26), 생성 1(#27) |
| 이미지에 필요한 정보가 있는가 | 있음 13 · 불분명 8 · **없음 5** (200px 썸네일 #10·#12·#21·#23, 조직 소견이 필요한데 MRI만 준 #16) |
| 판정 | P 15 · K 4 · D 3 · G 2 · PK 1 · R 1 |

- **해석 실패는 두 층위입니다.** 조직·장기 자체를 틀림(소뇌를 피부로, 뇌를 뼈로, 측두엽을 뇌간으로, 뇌실 주위 출혈을 태반으로: #2·#8·#12·#15)과,
  조직은 맞지만 소견을 잘못 읽음(#3·#5·#6·#9·#17·#18·#22 등)입니다.
- **없는 소견을 지어냅니다.** 세포가 보이지 않는 썸네일과 저배율 전체 슬라이드에서도 "유사분열", "육아종", "핵의 울타리 배열"을 자신 있게 묘사합니다.
- **"가끔 맞힘"이 능력을 뜻하지 않습니다.** #2·#9·#12·#21·#22·#23은 맞은 풀이도 이미지를 잘못 읽었고 운으로 정답 글자에 닿았습니다.
- 해석을 고치기만 하면 정답이 따라오는 문항(해석 실패 + 결론은 자기 해석과 일치)이 7건(#5·#6·#10·#15·#18·#20·#24)입니다.
