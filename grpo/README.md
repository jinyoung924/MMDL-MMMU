# grpo/ — 강화학습(GRPO) 실험 코드 v1–v6

Qwen3-VL-4B-Instruct를 RTX 4090(24GB) 한 장에서 GRPO + LoRA로 학습하는 코드입니다.
실험별 설정·결과·교훈은 [reports/training_experiments.md](../reports/training_experiments.md)에 정리돼 있습니다.
이 문서는 **코드를 다시 돌리는 방법**만 다룹니다.

## 한 라운드의 흐름

```
rollout (vLLM)  →  [judge (v3–v5) | teacher-score (v6)]  →  train (HF + PEFT)  →  guard
```

- **rollout**: 라운드마다 풀에서 문항 N개, 문항당 샘플 G개를 생성합니다(T=1, 8,192토큰, 평가와 같은 이미지 해상도). 샘플링한 토큰의 logprob(행동 정책 μ)도 함께 저장합니다.
- **judge** (v3–v5): Sonnet(headless `claude -p`, effort low)이 참조 풀이와 비교해 그림 읽기(`image_ok`)와 추론(`reasoning_ok`)을 판정합니다.
- **teacher-score** (v6): 교사 Qwen3-VL-8B-Instruct-FP8이 학생이 쓴 토큰 하나하나에 logprob를 매깁니다(vLLM `prompt_logprobs`).
- **train**: LoRA r16/α32(언어 모델의 q,k,v,o,gate,up,down), clipped surrogate(0.2), base와의 k3 KL, token-mean loss. 그룹 안 보상이 모두 같으면 건너뜁니다(v6은 교사 항으로 학습).
- **guard**: 정지 규칙을 검사합니다(정답률 급락, 잘림 > 35%, KL > 0.1, 길이 붕괴). 걸리면 체인이 멈춥니다.

단계마다 별도 프로세스로 돌려 GPU 메모리를 비웁니다. 라운드 상태는 `runs/<버전>/log.jsonl`에 쌓이고, 다시 실행하면 이어서 돌아갑니다.

## 파일

| 파일 | 내용 |
|---|---|
| `grpo.py` | 전부 여기에 있습니다: `rollout`, `screen`, `teacher-score`, `judge*`, `train`, `guard`, `merge`, `selfcheck`. 채점기(숫자·수식·단위 허용 오차)와 `python grpo.py selfcheck` 자체 검사 포함 |
| `loop.sh` | 라운드 START..END-1 반복 (rollout → judge/teacher → train → guard) |
| `chain.sh` | v1/v2: 학습 + 216문항 진단 + 900문항 평가 |
| `chain_v3.sh` … `chain_v6.sh` | 버전별 전체 실행(학습 구간 + 체크포인트 병합 + 평가 + 정지 규칙) |
| `prepare_virl.py` | v1/v2 풀: ViRL39K 단일 이미지 객관식 → `data/pool.jsonl` (3,670) |
| `prepare_vwi.py` | v3–v6 풀: VisualWebInstruct-verified 숫자 단답 → `data/pool_v3.jsonl` (8,091), `prepare_vwi.py v6` → `data/pool_v6_all.jsonl` (3,795) |
| `ste_eval.py`, `prep_queue.sh` | v6 사전 점검(프롬프트 변형, 교사 후보 평가) |
| `judge_instructions.md` | v3–v5 Sonnet 판정 지시문 |
| `ram_watch.sh` | RAM이 5GB 아래로 떨어지면 우리 작업만 멈추는 감시기 |
| `v3_protocol.md` … `v6_protocol.md`, `v6_prep_protocol.md` | **실행 전에 등록한 규칙**과 그 뒤의 수정(Amendment)·정지 기록. 결과를 본 뒤 규칙을 바꾼 경우는 모두 여기에 사유와 함께 남아 있습니다 |
| `data/ids_{216,166,88,430}.txt` | MMMU val을 base 5 seed 정답 수로 나눈 문항 목록(1–3/5, 0/5, 4/5, 5/5). **평가용이며 학습에는 쓰지 않습니다** |
| `data/pool_v4.jsonl`, `data/pool_v6.jsonl` | 실제로 학습에 쓴 풀. base·교사 사전 풀이 결과(`screen_v4.jsonl`, `screen_v6.jsonl`)로 걸렀기 때문에 GPU 없이는 다시 만들 수 없어 함께 올립니다 |

## 다시 돌리기

환경: conda `vllm-train` (vLLM 0.24.0, torch 2.11.0+cu130, transformers 5.13.0, peft 0.21.0)으로 학습하고, 평가는 루트의 평가 환경(`vllm`)에서 합니다.

```bash
cd MMMU-val
python grpo/grpo.py selfcheck                                  # 채점기·보상 자체 검사
python grpo/prepare_vwi.py v6                                  # 풀 만들기 (원본: TIGER-Lab/VisualWebInstruct-verified)
systemd-run --user --unit grpo-v6 -p WorkingDirectory=$PWD bash -c "bash grpo/chain_v6.sh >> grpo/runs/chain_v6.out 2>&1"
```

- 원본 데이터 경로(`/home/leesg17/data/...`)는 스크립트 상단의 `SRC`에서 바꿉니다.
- 평가는 항상 LoRA를 병합한 전체 체크포인트로 합니다(제출 형식: 외부 레이어 없음). `python grpo/grpo.py merge --adapter <ckpt> --out <dir>` → `SEEDS=0 bash eval.sh <dir> runs/<이름>`.
- 비교: `python analyze.py compare results/seed* vs runs/<이름>/seed0 --base-mean 1`. 병합 모델의 `scores.json`에 LoRA 관련 키(`enable_lora` 등)가 있으면 `compare`가 설정이 다르다며 거부합니다. 그 키 세 개를 지운 복사본으로 비교합니다(값은 기본값이라 결과에 영향 없음).

## 레포에 없는 것

- `runs/` (48GB): 라운드별 생성 결과, 어댑터, 병합 체크포인트. MMMU 평가 결과는 루트 `runs/grpo_*`에 있습니다.
- `data/pool.jsonl`, `data/pool_v3.jsonl`, `data/pool_v6_all.jsonl`: `prepare_*.py`로 다시 만듭니다.
- 판정 모델 검증 패킷(`judge_validation_*`): Geometry3K DEV 120개 응답에 대한 판정 원본. 요약 수치는 `v3_protocol.md`에 있습니다.
  다시 돌리려면(`validate-judge`, `judge-packets --validation`) `data/geometry_stability/review_pool.jsonl`과 `pilot_diagram/stability_v1/error_feedback_v12_20261101/`의 교사 판정 원본이 필요합니다. 둘 다 레포에 없습니다.
- `prepare_virl.py`가 읽는 `data/bmmr_audit/protected_image_index.json`(MMMU 이미지 해시): `scripts/fetch_bmmr_audit_sources.py` → `scripts/audit_bmmr.py`로 다시 만듭니다.

## 실행하며 겪은 문제 (다시 돌릴 때 주의)

- **vLLM 엔진은 fork로 뜹니다.** HF processor가 torch 연산을 한 뒤 엔진을 만들면 자식 프로세스가 멈춥니다(교사 채점이 7시간 멈춘 적 있음). 엔진을 먼저 만듭니다.
- **이미지 토큰을 미리 펼친 토큰 프롬프트**를 넘기면 vLLM이 한 번 더 펼칩니다. `<|image_pad|>` 하나만 넣고, 교사가 본 토큰이 학생 토큰과 같은지 검사합니다(`teacher-score`의 assert).
- **systemd-oomd가 RAM 부족 시 VS Code 스코프 전체를 죽입니다**(62GB 머신). 긴 작업은 `systemd-run --user`로 띄우고 `ram_watch.sh`를 같이 돌립니다.
- 같은 GPU에 다른 작업이 있으면 `--gpu-mem`을 0.68 정도로 낮춥니다(0.90에서 vLLM OOM).
