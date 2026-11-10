# 데이터셋 오염 검사 진행 보고

Nov 10, 2026 · @영민

**[→ 할 일로 바로가기](#할-일-정식-검사-돌리기)**

> **한 줄 요약.** `dataset_search.md` 1장 표의 2·3·4열은 다 채웠고, 4열은 **CPU 간이 검사** 결과입니다. 정식 검사 코드는 준비됐지만 GPU를 띄우지 못해, **GPU가 있는 팀원이 돌려 주시면** 마무리됩니다.

> 지금까지의 결과로는 14개 후보 중 **11개가 Safe**이고, **학습에서 뺄 레코드는 5개**(OpenMMReasoner 4, ViRL39K 1)입니다. ViRL39K는 간이 검사의 한계 때문에 계산상 **Risky**로 나왔고, ChemVQA는 데이터를 받지 못해 검사하지 못했습니다.

## 한 일

표의 2·3열은 원문을 직접 열어 확인하며 채웠고, 4열은 2장 절차를 가볍게 줄인 간이 검사를 돌린 뒤 **겹침 후보를 사람이 하나씩 확인해서** 채웠습니다.

1. **2·3열 (사용할 부분, 채택 이유).** 데이터셋 카드·논문·저장소를 열어 AI가 쓴 내용을 대조했습니다. 1열 설명과 원문이 다른 곳은 각 표 아래 **확인 메모**에 출처와 함께 적었습니다.
2. **4열 (contamination test).** 후보 14개를 MMMU dev·val(1,050문항)과 MMMU-Pro(1,730문항)에 대어 봤습니다. 그림은 픽셀이 같은지와 눈으로 비슷한지(pHash)를, 문장은 13단어가 연달아 같은지(13-gram)를 보고, 등급과 판정은 2장 규칙을 그대로 따랐습니다.
3. **사람 검수.** 기계가 골라 낸 겹침 후보 104쌍을 그림과 문제를 나란히 놓고 확인했고, 그중 **5쌍만 같은 문제**였습니다. 검수 화면과 이유는 `reports/decontam_review.md`에 있습니다.
4. **정식 검사 준비.** 간이 검사를 실제 데이터로 돌리며 찾은 버그 두 개를 정식 검사 코드에 고쳐 넣었고, RunPod과 Colab 어느 쪽에서든 돌아가게 만들었습니다. 다만 제 쪽에서는 RunPod을 쓸 수 없었고 Colab 실행은 실패해, **실제 데이터·GPU로는 아직 한 번도 돌지 않았습니다.**

## 결과 정리

간이 검사로는 **MMMU dev·val과 겹친 것은 없었고, MMMU-Pro와 겹친 레코드가 두 데이터셋에서 5개** 나왔습니다. 아래 표는 문제가 있는 것부터 적었습니다.

| 데이터셋 | 판정 | 뺄 레코드 |
| --- | --- | --- |
| OpenMMReasoner | 판정 보류 (문장 겹침 4건, 텍스트 recall 미측정) | 4 |
| ViRL39K | Risky (그림 겹침 1건) | 1 |
| ChemVQA | 미검사 (IEEE DataPort 구독 필요) | – |
| 나머지 11개 | Safe | 0 |

나머지 11개는 CoSyn music·circuit·chemical, MusiXQA, CircuitVQA, PathVQA, SLAKE, VQA-RAD, PubMedVision, SSMR, NOTA입니다. **판정 보류**는 겹친 건 빼면 되지만, 텍스트 검사가 겹침을 얼마나 놓치는지(recall)를 간이 검사에서 재지 않아 판정을 확정하지 못했다는 뜻입니다.

학습에서 뺄 레코드는 아래 다섯 개입니다. 둘씩 같은 MMMU-Pro 문항과 겹쳤습니다.

| 데이터셋 | 레코드 id | 겹친 MMMU-Pro 문항 |
| --- | --- | --- |
| OpenMMReasoner | `13464`, `87108` | test\_Math\_282 |
| OpenMMReasoner | `80660`, `MMR1-SFT-10194` | test\_Math\_436 |
| ViRL39K | `Processed-485678e7-6d95-4964-85c4-e1d0edcc5d14` | test\_Physics\_173 |

## 간이 검사가 못 보는 것

간이 검사의 Safe는 **찾아낸 겹침이 없다**는 뜻이고, 놓쳤을 수 있는 겹침까지 배제했다는 뜻은 아닙니다. 빈틈은 세 군데이고, 정식 검사는 이 세 곳을 메우도록 짜여 있습니다.

| 빈틈 | 간이 검사 | 정식 검사 |
| --- | --- | --- |
| 잘라 낸 그림 | pHash. 잘라 낸 사본을 2%만 다시 찾음 | SSCD 이미지 임베딩 |
| 바꿔 쓴 문장·번역 | 13-gram만 봄 | 다국어 임베딩 + LLM 판정 |
| 놓친 비율(recall) | 그림만 측정, 문장은 못 잼 | 그림·문장·번역 모두 측정 |

첫째 빈틈 때문에 **ViRL39K가 Risky**로 나왔습니다. 실제로 겹친 그림은 1건이지만, 잘린 그림을 2%만 찾는 검사라면 같은 겹침이 수십 건 숨어 있을 수 있다고 계산되기 때문입니다. 둘째와 셋째 빈틈 때문에 OpenMMReasoner는 판정을 확정하지 못했습니다.

그림을 아예 보지 않은 데이터셋도 있습니다. 합성 이미지 5개(CoSyn 셋, MusiXQA, SSMR)는 렌더링으로 만든 그림이라 MMMU와 겹칠 위험이 낮다고 보고 건너뛰었고, PubMedVision·NOTA·OpenMMReasoner는 이미지가 행에 없거나 수십 GB여서 문장만 봤습니다.

## 할 일: 정식 검사 돌리기

GPU 한 대에서 `reports` 브랜치의 `decontam/run_all.sh`를 돌리면 **4열이 정식 검사 결과로 다시 채워집니다.** 팀이 쓰던 `cloud/runpod.sh`에 그대로 얹히게 만들어 두었습니다.

1. **pod 띄우기.** RTX 4090 24GB, CUDA 필터 13.0 이상, 볼륨 100GB, 환경변수 `GITHUB_TOKEN`·`RUNPOD_USER_API_KEY`(`cloud/README.md` 1장과 같음).
2. **SLAKE 하나로 확인.** E 인덱스와 recall 측정도 이때 만들어집니다. 끝나도 pod가 꺼지지 않게 `AUTO_TERMINATE=0`을 줍니다.
3. **같은 pod에서 전체 실행.** 끝난 단계(E 인덱스, SLAKE)는 건너뜁니다.
4. **결과 받기.** 노트북에서 `bash cloud/local.sh fetch decontam_v1` 후 `runs/decontam_v1/dataset_search_filled.md`(채워진 표)와 데이터셋별 `removed_ids.txt`(뺄 레코드)를 봅니다.

```bash
git clone -b reports https://github.com/jinyoung924/MMDL-MMMU.git /workspace/MMDL-MMMU && cd /workspace/MMDL-MMMU
# 2) 확인용: SLAKE 하나
DATASETS=slake AUTO_TERMINATE=0 RUN_NAME=decontam_v1 SKIP_SMOKE=1 RUN_CMD='bash decontam/run_all.sh "$OUT"' \
  nohup bash cloud/runpod.sh > /workspace/runpod.out 2>&1 &
tail -f /workspace/runpod.out    # "[run_all ...] done"이 나오면 끝
# 3) 전체
RUN_NAME=decontam_v1 SKIP_SMOKE=1 RUN_CMD='bash decontam/run_all.sh "$OUT"' \
  nohup bash cloud/runpod.sh > /workspace/runpod.out 2>&1 &
```

돌린 뒤에는 세 가지를 봐 주세요.

- **의심 그림.** 데이터셋별 `review_list.txt`는 SSCD 유사도가 0.95 아래지만 가까운 그림 목록입니다. pod의 `/workspace/decontam/results/<데이터셋>/review/`에서 눈으로 보고, 같은 그림이면 `tid eid`를 한 줄씩 적어 `check.py grade --confirmed`에 넘기면 적중으로 셉니다.
- **Risky가 나온 데이터셋.** 2.3 기준대로 레코드만 빼고 쓸지, 데이터셋 째로 뺄지 정합니다.
- **ChemVQA.** IEEE DataPort 구독이 있는 분이 csv와 이미지를 `/workspace/decontam/data/chemvqa/`에 두면 함께 검사됩니다.

코드는 가짜 데이터 테스트만 통과했고 **실제 데이터·GPU로는 처음 도는 것**이라, SLAKE 확인에서 에러가 나면 `runpod.out` 마지막 부분을 저(이영민)에게 보내 주세요. ~~RunPod이 어려우면 `decontam/colab.ipynb`를 Colab GPU에서 위에서부터 실행하는 길도 있지만, 제가 시도했을 때는 실패했고 원인은 아직 못 봤습니다.~~
