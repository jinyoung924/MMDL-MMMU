# Qwen3-VL-4B-Instruct MMMU-val 베이스라인 평가

`Qwen/Qwen3-VL-4B-Instruct`를 MMMU validation 900문항으로 평가하는 파이프라인이다. 파인튜닝 전후를 같은 방식으로 비교하려고 만들었으며, 체크포인트 경로만 바꿔 같은 설정으로 다시 평가할 수 있다.

| | Overall (MMMU val, macro) |
|---|---|
| 이 파이프라인 (v5) | **58.44** (526/900) |
| 공식 (Qwen3-VL Technical Report) | 67.4 |

설정, 과목별 결과, 공식 수치와의 격차 분석은 [`reports/mmmu_baseline.md`](reports/mmmu_baseline.md)에 있다.

## 빠른 시작

```bash
# 1) 의존성 설치 (새 venv 기준)
pip install -r requirements.txt

# 2) 평가 실행: 추론 → 채점 → 집계
bash scripts/run_mmmu_eval.sh \
  --model_path Qwen/Qwen3-VL-4B-Instruct \
  --data_root ./data/hf_datasets
```

결과는 `results/baseline/`에 저장된다. `--data_root`가 비어 있으면 MMMU를 고정 revision으로 내려받고, 이미 있으면 재사용한다.

**파인튜닝 체크포인트 재평가**는 경로와 결과 폴더 이름만 바꾼다. 나머지 설정은 그대로 두어야 베이스라인과 비교할 수 있다.

```bash
bash scripts/run_mmmu_eval.sh \
  --model_path /path/to/finetuned_checkpoint \
  --data_root ./data/hf_datasets \
  --run_tag ft_v1
```

체크포인트 디렉터리에는 가중치와 함께 토크나이저·프로세서 설정 파일(`preprocessor_config.json`, `chat_template.json` 등)이 있어야 한다. LoRA는 병합한 체크포인트를 넘긴다.

### Colab에서 실행

Colab에 미리 설치된 torch 스택은 vLLM이 요구하는 것과 CUDA 빌드가 달라 충돌한다. `setup_colab.sh`가 이를 정리한 뒤 설치한다. 평가는 별도 파이썬 프로세스로 돌기 때문에 설치 후 런타임을 재시작할 필요는 없다.

```bash
!git clone -b <브랜치명> <저장소 URL> repo && cd repo && bash scripts/setup_colab.sh
!cd repo && bash scripts/run_mmmu_eval.sh --model_path Qwen/Qwen3-VL-4B-Instruct --data_root ./data/hf_datasets
```

## 요구 사항

| 항목 | 값 |
|---|---|
| GPU | 24GB급 (검증: NVIDIA L4 22.0 GiB. 실습실 RTX 4090 24GB 기준으로 설계) |
| NVIDIA 드라이버 | 580 이상 (torch 2.13.0이 CUDA 13.0 빌드) |
| Python | 3.10 이상 3.15 미만 (검증: 3.13.15) |
| 주요 패키지 | vllm 0.29.0, torch 2.13.0, transformers 5.16.1, datasets 4.8.5, pillow 12.2.0 |
| 소요 시간 | L4 기준 약 2시간 50분 (모델 로드 약 5분 + 추론 약 2시간 47분) |

## 실행 모드

| 모드 | 명령 | GPU | 용도 |
|---|---|---|---|
| 전체 평가 | `bash scripts/run_mmmu_eval.sh --model_path ... --data_root ...` | 필요 | 900문항 추론, 채점, 집계 |
| 스모크 테스트 | 위 명령 + `--limit_per_subject 1` | 필요 | 과목당 1문항(30문항)으로 전 경로 점검. `results/<run_tag>_smoke/`에 저장되며 보고용 아님 |
| 재채점 | `bash scripts/run_mmmu_eval.sh --grade_only --run_tag v5_maxtok8192` | 불필요 | 기존 `raw_generations.jsonl`을 다시 채점. 원본을 덮지 않고 `*_regrade` 파일로 저장 |
| 프롬프트 재현 검증 | `bash scripts/run_mmmu_eval.sh --data_root ... --verify_prompts_against results/v5_maxtok8192/raw_generations.jsonl` | 불필요 | 데이터셋에서 900문항 프롬프트를 다시 만들어 기준 파일과 문항 단위로 대조 |

## 주요 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--model_path` | `Qwen/Qwen3-VL-4B-Instruct` | HF repo id 또는 로컬 체크포인트 디렉터리 |
| `--model_revision` | `ebb281ec70b05090aa6165b016eac8ec08e71b17` | HF repo id일 때 고정할 commit. 로컬 디렉터리면 무시 |
| `--data_root` | (필수) | MMMU 데이터셋 캐시 디렉터리 |
| `--dataset_revision` | `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68` | MMMU dataset commit |
| `--run_tag` | `baseline` | 결과 폴더 이름 (`results/<run_tag>/`) |
| `--max_new_tokens` | 8192 | 생성 예산 (공식 32768, 축소 이유는 보고서 3.2) |
| `--max_model_len` | 12288 | 생성 8,192 + 프롬프트 4,096 |
| `--image_max_pixels` | 1048576 | 이 면적을 넘는 이미지만 종횡비 유지 축소 |
| `--max_num_seqs` | 8 | vLLM 동시 시퀀스 수 |
| `--gpu_memory_utilization` | 0.90 | vLLM이 미리 확보할 GPU 메모리 비율 |
| `--enforce_eager` | 꺼짐 | CUDA graph를 끈다. 초기화 중 메모리가 부족할 때 사용 |
| `--model_cache_dir` | HF 기본 캐시 | 모델 가중치 저장 위치 |

전체 목록은 `python3 scripts/mmmu_eval.py --help`로 볼 수 있다.

## 고정 설정

| 항목 | 값 | 출처 |
|---|---|---|
| 모델 | `Qwen/Qwen3-VL-4B-Instruct` @ ebb281ec, bf16 | 과제 지정 |
| 데이터 | `MMMU/MMMU` @ 98e6ac0c, validation, 30과목 × 30문항 | 과제 지정 |
| Sampling | temperature 0.7, top_p 0.8, top_k 20, repetition_penalty 1.0, presence_penalty 1.5, seed 3407 | [Qwen3-VL README "Evaluation Reproduction"](https://github.com/QwenLM/Qwen3-VL) |
| 프롬프트 | MMMU 공식 템플릿 (`Answer with the option's letter from the given choices directly.` 등) | [MMMU-Benchmark/MMMU](https://github.com/MMMU-Benchmark/MMMU) `configs/llava1.5.yaml`, `utils/data_utils.py` |
| 채점 | MMMU 공식 파서, 답을 못 찾으면 무작위 선택 (시드 42) | MMMU-Benchmark/MMMU `utils/eval_utils.py` |

프롬프트 전문과 각 값을 고른 이유는 보고서 2~4번에 있다.

## 산출물

`results/<run_tag>/`에 다음 파일이 생긴다.

| 파일 | 내용 |
|---|---|
| `raw_generations.jsonl` | 문항별 프롬프트 정보, 모델 응답, 프롬프트·생성 토큰 수, 종료 사유 |
| `graded_results.csv` | 문항별 예측, 정답, 정오, 토큰 수 |
| `summary.json` | 과목별·전체 정확도, 소요 시간, peak VRAM, 설정 |
| `results_table.md` | 보고서 5번 표를 그대로 붙여넣을 수 있는 형태 |
| `run_config.json` | 실행 조건 지문 |
| `environment.json` | 패키지 버전, GPU, 드라이버 |

## 재현성 장치

- **실행 조건 지문.** 같은 `run_tag` 폴더에 다른 설정으로 이어 쓰려 하면 `run_config.json`과 대조해 실행을 거부한다.
- **중단 후 재개.** 25문항마다 결과를 파일에 기록하고, 다시 실행하면 완료된 문항 id는 건너뛴다.
- **완료된 결과 보호.** 900문항이 끝난 폴더에는 전체 실행이 쓰지 않는다. 제출 결과(`results/v5_maxtok8192/`)가 덮이지 않는다.
- **채점 재현.** 무작위 선택은 시드 42로 응답 파일 순서대로 이루어진다. v5 원본 응답 900건을 스크립트로 재채점한 결과 문항 단위 불일치는 0건이었다.

## 저장소 구성

```
colab/mmmu_eval_v5.ipynb     제출 결과를 만든 Colab(L4) 노트북, 실행 출력 포함
results/v5_maxtok8192/       제출 결과 (58.44)
scripts/mmmu_eval.py         평가 스크립트. 노트북의 프롬프트·이미지·채점 코드를 그대로 옮김
scripts/run_mmmu_eval.sh     한 커맨드 실행 진입점
scripts/setup_colab.sh       Colab 전용 설치
requirements.txt             버전 고정 의존성
reports/mmmu_baseline.md     제출 보고서
```

## 알려진 문제

- **Pillow 12.3.0**: `ImportError: cannot import name '_Ink' from 'PIL._typing'`이 나는 결함 릴리스다. `requirements.txt`에서 12.2.0으로 고정했다.
- **Colab의 torch/torchaudio 불일치**: `PyTorch and TorchAudio were compiled with different CUDA versions` 오류가 나면 `scripts/setup_colab.sh`로 다시 설치한다.
- **`max_model_len`을 지정하지 않으면** 모델 기본값 262,144 때문에 KV 캐시에 36 GiB가 필요해 24GB GPU에서 초기화가 실패한다. 기본값 12,288을 유지한다.
- **초기화 중 메모리 부족**: `--enforce_eager`를 켜고, 그래도 부족하면 `--max_num_seqs 4`로 낮춘다.
