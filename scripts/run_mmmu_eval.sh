#!/usr/bin/env bash
# MMMU-val 평가 한 커맨드 실행
#
#   bash scripts/run_mmmu_eval.sh --model_path <HF repo id 또는 체크포인트 경로> --data_root <MMMU 데이터 캐시 경로> [옵션]
#
# 인자를 생략하면 환경변수 MODEL_PATH / DATA_ROOT, 그것도 없으면 아래 기본값을 쓴다.
# 명령행에 준 --model_path / --data_root 가 기본값보다 우선한다 (argparse 는 마지막 값을 쓴다).
#
# 예
#   bash scripts/run_mmmu_eval.sh --model_path Qwen/Qwen3-VL-4B-Instruct --data_root ./data/hf_datasets
#   bash scripts/run_mmmu_eval.sh --model_path /path/to/finetuned_ckpt --data_root ./data/hf_datasets --run_tag ft_v1
#   bash scripts/run_mmmu_eval.sh --data_root ./data/hf_datasets --limit_per_subject 1      # 스모크 테스트
#   bash scripts/run_mmmu_eval.sh --grade_only --run_tag v5_maxtok8192                   # 재채점 (GPU 불필요)
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
MODEL_PATH="${MODEL_PATH:-Qwen/Qwen3-VL-4B-Instruct}"
DATA_ROOT="${DATA_ROOT:-./data/hf_datasets}"

echo "[run_mmmu_eval] ${PYTHON} scripts/mmmu_eval.py --model_path ${MODEL_PATH} --data_root ${DATA_ROOT} $*"
exec "${PYTHON}" scripts/mmmu_eval.py --model_path "${MODEL_PATH}" --data_root "${DATA_ROOT}" "$@"