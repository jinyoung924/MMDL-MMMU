# Contamination 간이 검사 — 결과

> **검수까지 끝났습니다. 학습에서 뺄 레코드는 2개 데이터셋의 5개이고, ViRL39K는 계산상 Risky입니다.** 뺄 레코드 목록은 아래 「학습에서 뺄 레코드」에 있고, `reports/dataset_search.md` 4열도 이 결과로 채웠습니다. 간이 검사라 바꿔 쓴 문제와 잘라 낸 이미지는 놓칠 수 있습니다.

## 판정 요약

데이터셋마다 간이 검사 결과입니다. 판정 기준은 `reports/dataset_search.md` 2장 2.3절을 그대로 따랐습니다.

| 데이터셋 | 판정 | 적중 MMMU / Pro | 검수 대기 레코드 (그림 / 텍스트) |
|---|---|---|---|
| circuitvqa | Safe | 0 / 0 | 0 / 0 |
| cosyn_chemical | Safe | 0 / 0 | 0 / 0 |
| cosyn_circuit | Safe | 0 / 0 | 0 / 0 |
| cosyn_music | Safe | 0 / 0 | 0 / 0 |
| musixqa | Safe | 0 / 0 | 0 / 0 |
| nota | Safe | 0 / 0 | 0 / 0 |
| openmmreasoner | 판정 보류(text recall 미측정) | 0 / 2 | 0 / 0 |
| pathvqa | Safe | 0 / 0 | 0 / 0 |
| pubmedvision | Safe | 0 / 0 | 0 / 0 |
| slake | Safe | 0 / 0 | 0 / 0 |
| ssmr | Safe | 0 / 0 | 0 / 0 |
| virl39k | Risky | 0 / 1 | 0 / 0 |
| vqarad | Safe | 0 / 0 | 0 / 0 |
| chemvqa | 검사 못 함 | - | FileNotFoundError: no data files for chemvqa under /sessions/rcw-011ftnijzqddjjv… |

## Risky가 나오는 이유

**간이 검사는 잘라 낸 이미지를 거의 못 잡기 때문에, 그림이 한 건이라도 겹치면 계산상 Risky가 됩니다.** 평가 이미지를 일부러 편집해 다시 찾게 한 결과, 크기 축소 0.997·JPEG 1.0는 거의 다 잡았지만 5% 자르기는 0.018, 자르기+축소+JPEG는 0.022만 잡았습니다(표본 325장). 2.3절은 이 중 가장 낮은 값을 recall r로 쓰므로, 남은 오염 추정 k × (1 − r) / r이 크게 부풀려집니다.

| 데이터셋 | 적중 MMMU / Pro | r | 잔여 inflation (%p) |
|---|---|---|---|
| virl39k | 0 / 1 | 0.018 | MMMU 0.0 · Pro 3.154 |

실제로 겹친 건 아래 「학습에서 뺄 레코드」에 있는 레코드뿐이라, Risky인 데이터셋은 팀에서 셋 중 하나를 고르면 됩니다. **(1) 그 레코드만 빼고 사용**(간이 검사의 낮은 r을 감수), (2) RunPod 정식 검사(`decontam/run_all.sh`, SSCD로 자르기도 잡음)로 r을 다시 잰 뒤 판정, (3) 데이터셋째 학습에서 제외.

## 학습에서 뺄 레코드

검수에서 같은 문제(Y)로 확정됐거나 이미지가 그대로 같은 레코드입니다. 학습 데이터를 만들 때 이 id를 빼 주세요.

| 데이터셋 | 레코드 id | 겹친 시험 문항 |
|---|---|---|
| openmmreasoner | `13464` | `pro:test_Math_282` |
| openmmreasoner | `80660` | `pro:test_Math_436` |
| openmmreasoner | `87108` | `pro:test_Math_282` |
| openmmreasoner | `MMR1-SFT-10194` | `pro:test_Math_436` |
| virl39k | `Processed-485678e7-6d95-4964-85c4-e1d0edcc5d14` | `pro:test_Physics_173` |

## 검수할 후보

검수할 후보가 없습니다. (텍스트 후보는 모두 검수했고, 답은 `qc_work/results/*/text_candidates.csv`에 남아 있습니다.)

