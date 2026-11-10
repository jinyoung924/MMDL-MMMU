# Contamination 검사 (`reports/dataset_search.md` 2장)

> 후보 데이터셋(T)마다 MMMU dev·val과 MMMU-Pro(E)에 겹치는 문항을 찾아 등급을 매기고, 제거 건수와 판정을 **1장 표 4열 형식 한 줄**로 남깁니다. RunPod GPU 한 대에서 한 번에 돌립니다.

## 돌리기

pod에서 저장소를 클론하고 이 폴더(`decontam/`)를 저장소 맨 위에 둔 뒤 실행합니다. 새 파일만 추가하므로 main에 올리지 않고 압축을 풀어도 `runpod.sh` 검사에 걸리지 않습니다.

```bash
git clone https://github.com/jinyoung924/MMDL-MMMU.git /workspace/MMDL-MMMU && cd /workspace/MMDL-MMMU
python -m zipfile -e decontam.zip .
RUN_NAME=decontam_v1 SKIP_SMOKE=1 RUN_CMD='bash decontam/run_all.sh "$OUT"' \
  nohup bash cloud/runpod.sh > /workspace/runpod.out 2>&1 &
```

끝나면 노트북에서 `bash cloud/local.sh fetch decontam_v1` 후 `runs/decontam_v1/dataset_search_filled.md`를 엽니다. 4열이 채워진 표입니다. 일부만 돌리려면 `DATASETS="cosyn_music slake"`를 앞에 붙입니다.

**처음엔 노트북에서 `python decontam/tests/test_local.py`로 논리부터 확인합니다** (네트워크·GPU 없이 수 초, `PASS`가 나와야 함).

## 흐름

```
build_eval_index.py   E 인덱스: 이미지 SHA-256 · SSCD 임베딩 · 13-gram · 다국어 문장 임베딩 · 썸네일 · 육안 검토 하한
recall.py make        E 문항 100개(MMMU val 50 + Pro 50)의 변형본: 이미지 편집 / 패러프레이즈 / 중국어 번역 / 둘 다
check.py detect       T 레코드마다 4가지 검출 → hits.jsonl, 판정 후보, review/(0.95 미만 의심 이미지)
judge.py              텍스트만 겹친 후보를 LLM(Qwen2.5-7B-Instruct)이 "같은 문제인가"로 판정
check.py grade        A/B/C/D 등급 · 제거 목록 · 적중 E 문항 수 k · recall r로 잔여 오염 추정 → Safe / Use after removal / Risky
fill_md.py            report.json의 한 줄을 dataset_search.md 4열에 써 넣음
```

## 문서 2장과 다르게 정한 것 (이유)

| 항목 | 문서 | 이 코드 | 이유 |
|---|---|---|---|
| 패러프레이즈 후보 | 임베딩 top-5 → judge | top-5 중 cosine ≥ 0.80만 | PubMedVision처럼 백만 단위 T에서 모든 쌍을 judge에 보낼 수 없음. 이 기준이 놓치는 비율은 recall의 `text`·`trans`에 그대로 드러남 |
| recall 측정 | 변형본을 T 사본에 넣고 다시 검출 | 변형본만 따로 검출 | 검출이 레코드마다 독립이라 결과가 같음 (template 판정만 T 전체를 보는데, 변형본은 모두 유일) |
| MMMU-Pro | test 1,730 | standard(10 options) 문항 + vision 스크린샷을 같은 문항의 이미지로 | 4·10 options는 문항이 같고 vision은 id를 공유 |
| 이미지가 없는 행 | — | NOTA·OpenMMReasoner·PubMedVision(기본)은 **텍스트만** 검사, 4열 끝에 "(텍스트만)" | 이미지가 HF 행에 없거나(경로만) 수십~백수십 GB. PubMedVision은 `PMV_IMAGES=1`로 이미지까지 |
| 육안 검토 | 0.95 아래 하위 1%까지 | `review/`에 T 이미지(파일명에 E 이미지 번호·유사도), E 쪽은 `eval_index/thumbs/<번호>.jpg` | 확인한 쌍은 `tid eid` 줄로 적어 `grade --confirmed`에 넘기면 이미지 일치로 셉니다 |

## 직접 받아야 하는 것

- **ChemVQA-2K**: IEEE DataPort 구독 또는 Mendeley 미러에서 받아 `/workspace/decontam/data/chemvqa/`에 csv와 이미지를 둡니다. 없으면 건너뜁니다.
- **CircuitVQA**: README의 Google Drive 링크 두 개를 `gdown`으로 자동으로 받습니다. 막히면 같은 방식으로 직접 두면 됩니다. 필드명이 자동 인식과 다르면 `inspect.txt`를 보고 `CIRCUIT_FIELDS="question=...,image=..."`를 줍니다.

## 결과 파일 (`runs/<RUN_NAME>/<dataset>/`)

- `report.json` — 4열 한 줄(`line`), 등급별 수, 적중 E 문항 id, recall과 판정
- `removed_ids.txt` — 학습 데이터에서 뺄 레코드 id
- `inspect.txt` — 읽은 레코드 앞 3개 (필드 인식 확인용)
- `review_list.txt` — 눈으로 볼 의심 이미지 목록

## 아직 확인하지 못한 것

- 실제 HF 데이터와 GPU로는 돌려 보지 않았습니다. 가짜 E·T로 전 경로(`tests/test_local.py`)만 확인했습니다.
- SSCD 가중치(`dl.fbaipublicfiles.com`)와 다국어 임베딩 모델을 pod에서 처음 받습니다.
- 4장(행동 검사: clean/flagged 비교, 보기 순서, blind)은 파인튜닝한 모델이 있어야 해서 여기에 없습니다.
