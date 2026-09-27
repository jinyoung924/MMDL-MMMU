# RunPod에서 돌리기 — 실험 루프 운영 절차

> **Claude 세션은 이 문서를 먼저 읽고 §0의 절차대로만 git을 다룹니다.** 아래 다섯 명령 밖의 git 명령
> (`git add/commit/push/merge/rebase`를 직접 조합하는 것)은 쓰지 않습니다. 충돌은 이 규칙만으로 거의 사라집니다.

## 0. 실험 한 번의 루프 (Claude 세션용)

```
로컬 main                          pod                              로컬 main
─────────────                      ──────────────────────           ───────────────────────
① 코드·실험 설계                    ② bash cloud/runpod.sh           ③ fetch → runs/<RUN_NAME>/ 분석
   push-code "메시지"     ──────▶     results/<RUN_NAME> 브랜치로   ──▶  ④ merge (남김) 또는 drop (버림)
                                      seed마다 자동 push, pod 종료
```

| 단계 | 어디서 | 명령 | 하는 일 |
|---|---|---|---|
| ① | 로컬 | `bash cloud/local.sh push-code "실험 X: 프롬프트 변경"` | main에 코드·문서를 커밋하고 push. 먼저 `pull --rebase`로 최신 main을 받음. `runs/`는 절대 추가하지 않음 |
| ② | pod | `RUN_NAME=exp_x bash cloud/runpod.sh` | 환경 설치 → smoke test → 평가 → 결과를 `results/exp_x` 브랜치로 push → pod 종료. **pod에서는 코드를 고치지 않음** |
| ③ | 로컬 | `bash cloud/local.sh fetch exp_x` | `runs/exp_x/`를 로컬로 가져옴(git 상태는 안 바뀜). `python analyze.py compare results/seed* vs runs/exp_x/seed*` 등으로 분석 |
| ④a | 로컬 | `bash cloud/local.sh merge exp_x` | 남길 결과: main에 병합·push하고 원격 결과 브랜치 삭제 |
| ④b | 로컬 | `bash cloud/local.sh drop exp_x` | 버릴 결과: 원격 브랜치와 로컬 복사본 삭제 |
| 확인 | 로컬 | `bash cloud/local.sh status` / `list` | 현재 브랜치, 미커밋 변경, 병합 안 된 결과 브랜치 목록 |

**규칙 다섯 개**

1. 코드는 로컬 main에서만 고치고 `push-code`로만 올립니다. 실험을 pod에 올리기 **전에** push합니다(pod는 clone한 코드로 돕니다).
2. pod는 결과만 만듭니다. 결과는 항상 `results/<RUN_NAME>` 브랜치로 가고, main에는 사람이 ④에서 고른 것만 들어갑니다.
3. `RUN_NAME`은 실험마다 새로 짓습니다(`exp_cot_v2`, `sft_lr1e-4_eval`). 같은 이름은 "끊긴 실행을 이어서 하기"라는 뜻입니다.
4. `runs/` 아래는 손으로 만들거나 고치지 않습니다. pod가 쓰고 `fetch`/`merge`가 가져옵니다. `results/`는 공식 베이스라인이므로 건드리지 않습니다.
5. `push-code`가 "rebase conflict"로 멈추면 다른 세션이 같은 파일을 고친 것입니다. 충돌 파일을 고치고 `git rebase --continue && git push origin main` 한 번만 실행합니다. 그 외의 경우 직접 git을 만질 일은 없습니다.

**왜 충돌이 안 나는가.** 코드 커밋은 main에만, 결과 커밋은 실험별 브랜치에만 있고, 결과 브랜치는 `runs/<RUN_NAME>/` 아래 파일만 추가합니다.
서로 다른 파일만 만지는 브랜치는 어떤 순서로 병합해도 충돌하지 않습니다. 결과가 어느 코드로 만들어졌는지는 `runs/<RUN_NAME>/cloud_run.json`의 `code_commit`에 남습니다.

---

## 1. Pod 배포

### 1.1 사양

베이스라인 5 seed(64.93 ± 0.94)와 재현성 검증(899/900 일치)은 아래 환경에서 측정됐습니다. 엔진 버전이 바뀌면 같은 seed라도
응답이 달라지므로 **이 pin을 그대로 씁니다**(`requirements.txt`).

| 항목 | 값 | 어디서 정해지나 |
|---|---|---|
| Python | **3.11** | `setup_runpod.sh`가 venv에 설치 (이미지에 3.11이 없으면 `uv`로 받음) |
| CUDA / torch | **13.0** / `torch==2.11.0+cu130` | `requirements.txt` + PyTorch cu130 index |
| vLLM | **0.24.0** | `requirements.txt` |
| transformers / datasets | 5.13.0 / 5.0.1 | `requirements.txt` |
| GPU | RTX 4090 24 GB (bf16, sm 8.9) | 24 GB 미만이면 `run_eval.py --gpu-mem-util`을 낮춰야 함 |
| 호스트 드라이버 | **580 이상** (CUDA 13) | **RunPod 배포 화면의 CUDA 필터를 13.0 이상으로** |
| 볼륨 | `/workspace` 60 GB 이상 | venv 약 10 GB + HF 캐시(모델 9 GB, MMMU val+test 약 3 GB) + 결과 |
| 시간 | seed당 약 77분, 5 seed 약 6.5시간 | 설치 약 10분, smoke test 약 5분 별도 |

- **이미지는 무엇이든 됩니다.** 이미지에 깔린 torch는 쓰지 않고 `/workspace/venv`에 Python 3.11 환경을 따로 만듭니다.
  `setup_runpod.sh`는 드라이버가 580 미만이거나 CUDA 초기화가 안 되는 호스트를 설치 전에 걸러냅니다.
- 학습(`pilot_forgetting/train_sft.py`)까지 할 때는 `TRAIN=1`을 주면 `peft`, `accelerate`가 `--no-deps`로 추가됩니다.
- **새 환경에서 처음 돌릴 때는 베이스라인 5 seed를 한 번 다시 돌려** `results/seed*`와 문항 단위로 일치하는지 확인하세요
  (`python analyze.py compare results/seed* vs runs/<RUN_NAME>/seed*`). 일치하면 그 pod 사양을 이 표에 기록합니다.

### 1.2 배포 화면에 넣는 환경변수 (Environment Variables)

RunPod 웹의 pod 배포 화면에서 **이 세 개**를 넣습니다(값은 RunPod Secrets에 저장하고 `{{ RUNPOD_SECRET_이름 }}`으로 참조 권장).

| 이름 | 값 | 스크립트가 하는 일 | 없으면 |
|---|---|---|---|
| `GITHUB_TOKEN` | 이 레포에 쓰기 권한이 있는 GitHub PAT (fine-grained, Contents: read/write) | 결과를 `results/<RUN_NAME>` 브랜치로 push | **`runpod.sh`가 시작을 거부** (몇 시간짜리 결과가 pod에만 남는 사고 방지. 의도적이면 `ALLOW_NO_PUSH=1`) |
| `RUNPOD_USER_API_KEY` | RunPod API 키 (Settings → API Keys) | 실행이 끝나고 결과 push가 확인된 뒤 pod 자가 종료 | 경고만 출력. pod가 켜진 채 남으므로 직접 종료 |
| `PUBLIC_KEY` | 내 SSH 공개키 한 줄 (`ssh-ed25519 AAAA...`) | SSH 접속 허용. RunPod 공식 이미지가 `authorized_keys`에 넣고, 스크립트도 빠져 있으면 추가 | 웹 터미널로만 접속 |

`RUNPOD_POD_ID`는 RunPod이 자동으로 넣습니다. SSH 세션은 컨테이너 환경변수를 상속하지 않으므로 스크립트가 PID 1의 환경에서 읽습니다.
**결과 push가 실패하면 어떤 경우에도 pod를 종료하지 않습니다.** 결과가 GitHub에 있는 것이 확인된 뒤에만 종료합니다.

§1.4의 실행 knob(`RUN_NAME`, `MODEL`, `SEEDS` 등)도 같은 자리에 넣을 수 있습니다. 우선순위는 명령줄 > 배포 화면 > 기본값입니다.
평소에는 배포 화면에 위 세 개만 두고, 실행 knob은 SSH로 들어가 명령줄에서 줍니다.

### 1.3 pod 안에서 실행

```bash
git clone https://github.com/jinyoung924/MMDL-MMMU.git /workspace/MMDL-MMMU && cd /workspace/MMDL-MMMU
RUN_NAME=baseline_repro bash cloud/runpod.sh                                # 베이스라인 5 seed
MODEL=/workspace/ckpt_merged RUN_NAME=sft_v1_eval bash cloud/runpod.sh      # fine-tuned 체크포인트 평가
SEEDS="0" SKIP_SMOKE=1 RUN_NAME=quick bash cloud/runpod.sh                  # 1 seed만, smoke 생략

# 학습 → 병합 → 평가를 한 pod에서 (RUN_CMD가 그대로 eval 됨)
TRAIN=1 RUN_NAME=sft_lr1e-4 RUN_CMD='
  python pilot_forgetting/train_sft.py --out runs/$RUN_NAME/train &&
  python pilot_forgetting/train_sft.py --merge runs/$RUN_NAME/train/step2000 &&
  bash eval.sh $PWD/runs/$RUN_NAME/train/step2000_merged runs/$RUN_NAME/eval' bash cloud/runpod.sh
```

SSH 세션이 끊겨도 죽지 않게 `nohup bash cloud/runpod.sh &` 또는 `tmux` 안에서 실행하세요.
끊겼을 때는 **같은 `RUN_NAME`으로 다시 실행**하면 원격 결과 브랜치를 받아 끝난 seed를 복원하고 이어서 돕니다.

### 1.4 환경변수 (스크립트 knob, 전부 기본값 있음)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `RUN_NAME` | `<UTC 날짜-시간>-<pod id>` | 결과 폴더와 브랜치 이름. **항상 직접 지정 권장** |
| `MODEL` | `Qwen/Qwen3-VL-4B-Instruct` | HF id 또는 로컬 체크포인트 경로 (LoRA는 먼저 병합) |
| `OUT` | `runs/$RUN_NAME` | 결과 폴더. `results/`는 공식 베이스라인이므로 쓰지 않음 |
| `SEEDS` | `0 1 2 3 4` | `eval.sh`에 전달 |
| `RUN_CMD` | `bash eval.sh "$MODEL" "$OUT"` | 실제로 돌릴 명령. 학습 등 다른 작업은 여기로 |
| `TRAIN` | `0` | `1`이면 `peft`, `accelerate` 추가 설치 |
| `SKIP_SMOKE` | `0` | `1`이면 smoke test(과목 2개 × 1문항) 생략 |
| `AUTO_TERMINATE` | `1` | 성공 시 pod 종료 |
| `TERMINATE_ON_FAIL` | `0` | 실패한 pod도 종료할지. 기본은 살려 두어 SSH로 원인을 볼 수 있게 함 (요금 주의) |
| `ALLOW_NO_PUSH` | `0` | `1`이면 `GITHUB_TOKEN` 없이도 실행 (결과는 pod에만 남음. 테스트용) |
| `VENV_DIR`, `HF_HOME` | `/workspace/venv`, `/workspace/hf` | pod 재시작 후에도 남는 볼륨 |

### 1.5 실행 중 생기는 파일 (`runs/<RUN_NAME>/`)

| 파일 | 내용 | push 시점 |
|---|---|---|
| `seed<s>/predictions.jsonl`, `scores.json`, `table.md` | `run_eval.py` 산출물 (기존과 동일) | seed가 끝날 때마다 |
| `scores.json`, `table.md` | `analyze.py aggregate` 집계 | 마지막 |
| `cloud_run.json` | RUN_NAME, `code_commit`, 모델, GPU, 시작·종료 시각, `status`(ok/failed) | 마지막 |
| `requirements.lock.txt` | 실제 설치된 패키지 | 마지막 |
| `smoke/` | smoke test 결과 | 마지막 |
| `console.log` | 전체 콘솔 출력 | **안 함** (`*.log`는 gitignore). pod가 살아 있을 때만 |

---

## 2. 파일

| 파일 | 어디서 실행 | 역할 |
|---|---|---|
| `local.sh` | 로컬 | §0의 다섯 동작. Claude가 쓰는 유일한 git 진입점 |
| `runpod.sh` | pod | 진입점. 시크릿 읽기 → 결과 브랜치 → `setup_runpod.sh` → smoke → `RUN_CMD` → push → 종료 |
| `setup_runpod.sh` | pod | 드라이버·CUDA 사전 검사, Python 3.11 venv, `requirements.txt`, 버전 assert. 재실행 안전 |
| `push_results.sh` | pod | 결과 폴더 하나를 커밋해 `results/<RUN_NAME>`로 push. `eval.sh`의 `AFTER_SEED` 훅이 seed마다 호출 |

## 3. 브랜치 규칙과 안전장치

```
main                  ── local.sh push-code 가 만드는 코드·문서 커밋 + merge 가 만드는 "merge results/<RUN_NAME>" 커밋
results/<RUN_NAME>    ── pod가 만드는 "results(<RUN_NAME>): runs/.../seedN" 커밋만. runs/<RUN_NAME>/ 아래 파일만 추가
```

| 상황 | 막는 장치 |
|---|---|
| 결과 커밋에 코드가 섞임 | `push_results.sh`: `results/*` 브랜치가 아니면 거부, 넘겨받은 폴더만 stage. `runpod.sh`: 시작 시 수정된 추적 파일이 있으면 실행 거부 |
| 코드 커밋에 결과가 섞임 | `local.sh push-code`: `runs/`를 제외하고 add |
| 두 pod가 동시에 push | 실험마다 `RUN_NAME`이 다르면 브랜치·폴더가 달라 만나지 않음. 같은 브랜치면 거절 → fetch+rebase 재시도 5회 → 예비 브랜치 `results/<RUN_NAME>-<host>-<시각>` |
| 두 세션이 main을 동시에 수정 | `push-code`가 push 전에 `pull --rebase`. 같은 줄을 고쳤을 때만 멈추고 알려 줌 |
| 공식 베이스라인 `results/` 덮어쓰기 | 기본 `OUT`이 `runs/<RUN_NAME>` |
| 모델 가중치 커밋 | `.gitignore`: `runs/**/step*/`, `*_merged/` |
| pod가 중간에 죽음 | seed마다 push. 어떤 종료 경로에서도 wrap-up이 남은 결과를 push |

결과 커밋만 보기: `git log --oneline origin/results/<RUN_NAME> ^origin/main`. 코드 커밋만 보기: `git log --first-parent main`.

## 4. 문제 해결

| 증상 | 원인 / 조치 |
|---|---|
| `FATAL: host driver ... < 580` | CUDA 12 호스트. pod 종료 후 CUDA 필터 13.0 이상으로 재배포 |
| `cuInit rc=999` 또는 `804` | 호스트 GPU 초기화 불량. 다른 머신으로 |
| `expected a cu130 torch build` | pip이 다른 torch를 받음. `/workspace/venv` 삭제 후 재실행 |
| `push_results: no GITHUB_TOKEN -> skipped` | 환경변수 미설정. 토큰을 넣고 pod에서 `bash cloud/push_results.sh runs/<RUN_NAME>` |
| `FATAL: GITHUB_TOKEN cannot push` / `403 Permission denied` | 토큰에 Contents **write**가 없거나 이 레포가 선택되지 않음. 토큰을 다시 만들고(§5 Secrets), Secret을 바꿔도 **켜져 있는 pod의 환경변수는 바뀌지 않으므로** `GITHUB_TOKEN=<새 토큰> bash cloud/push_results.sh runs/<RUN_NAME>`으로 밀린 결과를 올리거나 pod를 재배포 |
| `current branch ... is not a results/* branch` | `runpod.sh`를 거치지 않고 push 스크립트만 부른 경우. `git checkout -B results/<RUN_NAME>` 후 재시도 |
| `tracked files are modified` (pod) | pod에서 코드를 고쳤음. 로컬에서 `push-code` 후 pod에서 `git checkout -- . && git pull` |
| `local.sh fetch`: `origin has no branch` | 아직 첫 seed가 끝나지 않았거나 push가 실패. `list`로 확인, pod의 `console.log` 확인 |
| `local.sh merge`: `uncommitted changes` | 먼저 `push-code`로 코드 변경을 올린 뒤 merge |
| smoke test 실패 | 환경·모델·데이터 문제. `runs/<RUN_NAME>/console.log`. 본 작업은 시작되지 않았고 pod는 살아 있음 |

---

## 5. RunPod 템플릿 값

My Templates → New Template에 그대로 입력합니다. 값만 적었습니다.

| 필드 | 값 |
|---|---|
| Template Name | `mmmu-eval-cu130` |
| Template Type | `Pod` |
| Container Image | `runpod/pytorch:1.3.2-cu1290-torch2130-ubuntu2404` |
| Container Start Command | (비움) |
| Container Disk | `20` GB |
| Volume Disk | `80` GB |
| Volume Mount Path | `/workspace` |
| Expose HTTP Ports | `8888` |
| Expose TCP Ports | `22` |

Environment Variables (Secrets에 먼저 등록하고 참조):

| Key | Value |
|---|---|
| `GITHUB_TOKEN` | `{{ RUNPOD_SECRET_GITHUB_TOKEN }}` |
| `RUNPOD_USER_API_KEY` | `{{ RUNPOD_SECRET_RUNPOD_USER_API_KEY }}` |
| `PUBLIC_KEY` | `ssh-ed25519 AAAA...` (내 공개키 한 줄, 그대로 입력) |

Secrets (Settings → Secrets):

| Name | Value |
|---|---|
| `GITHUB_TOKEN` | GitHub fine-grained PAT. **Repository access: Only select repositories → `jinyoung924/MMDL-MMMU`**, **Permissions → Contents: Read and write** (Read만 주면 clone은 되고 push만 403으로 실패함. `runpod.sh`가 시작 시 `push --dry-run`으로 검사) |
| `RUNPOD_USER_API_KEY` | RunPod API Key (Settings → API Keys, 권한 All) |

Pod 배포 시 선택:

| 항목 | 값 |
|---|---|
| GPU | `RTX 4090` (24 GB) × 1 |
| Additional Filters → CUDA Version | `13.0` 이상 |
| Pod Type | `On-Demand` (Spot은 중단 시 같은 `RUN_NAME`으로 재실행해 이어감) |
| Template | `mmmu-eval-cu130` |

배포 후 SSH로 들어가서:

```bash
git clone https://github.com/jinyoung924/MMDL-MMMU.git /workspace/MMDL-MMMU && cd /workspace/MMDL-MMMU
RUN_NAME=<실험이름> nohup bash cloud/runpod.sh > /workspace/runpod.out 2>&1 &
tail -f /workspace/runpod.out
```

- 이미지에 들어 있는 torch(cu129)는 쓰지 않습니다. `setup_runpod.sh`가 `/workspace/venv`에 Python 3.11 + cu130 환경을 따로 만듭니다.
  이미지는 git·curl·nvidia-smi·SSH(`PUBLIC_KEY` 처리)가 있는 RunPod 공식 이미지라는 이유로 고른 것이고, 호스트 조건은 CUDA 필터 13.0만 지키면 됩니다.
- Start Command를 비워 두는 이유: 이미지 기본 `/start.sh`가 `PUBLIC_KEY`를 `authorized_keys`에 넣고 sshd를 띄웁니다. 덮어쓰면 SSH가 안 됩니다.
