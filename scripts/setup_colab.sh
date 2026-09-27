#!/usr/bin/env bash
# Colab 전용 환경 준비. 새 venv / 실습실 서버에서는 `pip install -r requirements.txt` 한 줄이면 된다.
#
# Colab 에 미리 깔린 torch / torchaudio 는 vllm 이 요구하는 것과 버전 문자열이 같아도 CUDA 빌드가 달라
# (예: torchaudio 2.11.0+cu128 vs torch 2.13.0+cu130) pip 가 교체하지 않고, import vllm 시점에
# "PyTorch and TorchAudio were compiled with different CUDA versions" 오류가 난다.
# 그래서 torch 스택을 먼저 지우고 requirements.txt 대로 한 번에 설치한다.
#
# 평가는 별도 파이썬 프로세스(scripts/run_mmmu_eval.sh)로 돌기 때문에 설치 후 노트북 커널을 재시작할 필요는 없다.
set -euo pipefail
cd "$(dirname "$0")/.."

pip uninstall -y -q torch torchvision torchaudio torchcodec || true
pip install -q -r requirements.txt

# 설치 직후 torch 생태계 CUDA 빌드 일치 확인 (불일치면 여기서 바로 실패)
python3 - <<'PY'
import torch, torchvision, torchaudio, PIL, vllm
print(f"torch {torch.__version__} (CUDA {torch.version.cuda}) | torchvision {torchvision.__version__} | "
      f"torchaudio {torchaudio.__version__} | vllm {vllm.__version__} | pillow {PIL.__version__}")
PY