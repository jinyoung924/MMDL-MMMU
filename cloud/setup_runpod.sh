#!/usr/bin/env bash
# Environment setup on a RunPod pod, pinned to the environment the baseline was measured in
# (requirements.txt: Python 3.11 / CUDA 13.0 / vLLM 0.24.0 / torch 2.11.0+cu130).
# Idempotent: safe to re-run after a pod restart. Called by cloud/runpod.sh; can be run alone.
#
# The image does not matter: Python 3.11 is installed into a venv on /workspace (via uv when the image
# lacks 3.11). What DOES matter is the host driver: CUDA 13 wheels need driver >= 580 (see cloud/README.md).
set -euo pipefail
cd "$(dirname "$0")/.."

# /workspace survives pod stop/start -> keep the venv and the HF cache (model 9 GB + MMMU ~3 GB) there.
if [[ -z "${HF_HOME:-}" && -d /workspace ]]; then export HF_HOME=/workspace/hf; fi
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
mkdir -p "$HF_HOME"
grep -q 'HF_HOME=' ~/.bashrc 2>/dev/null || echo "export HF_HOME=$HF_HOME" >> ~/.bashrc

echo "== system =="
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
DRIVER_MAJOR="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | cut -d. -f1)"
if [[ "${DRIVER_MAJOR:-0}" -lt 580 ]]; then
  echo "FATAL: host driver $DRIVER_MAJOR < 580. torch 2.11.0+cu130 needs a CUDA 13 driver." >&2
  echo "       Terminate this pod and deploy with the CUDA filter set to 13.0 or higher." >&2
  exit 2
fi

# Some hosts ship a forward-compat libcuda inside the image that GeForce cards reject (cuInit 804).
# Putting the host driver's libcuda first fixes it; harmless where it is not needed.
HOST_LIBCUDA_DIR="${NVIDIA_CTK_LIBCUDA_DIR:-/usr/lib/x86_64-linux-gnu}"
if [[ -e "$HOST_LIBCUDA_DIR/libcuda.so.1" ]]; then
  export LD_LIBRARY_PATH="$HOST_LIBCUDA_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  grep -q 'LD_LIBRARY_PATH=' ~/.bashrc 2>/dev/null || echo "export LD_LIBRARY_PATH=$LD_LIBRARY_PATH" >> ~/.bashrc
fi

echo "== CUDA preflight (before the ~10 min install) =="
# nvidia-smi can look fine while the CUDA driver cannot initialise (e.g. /dev/nvidia-uvm EIO -> cuInit 999).
# Nothing inside the container can fix that, so fail here instead of after the install.
if [[ "${SKIP_CUDA_PREFLIGHT:-0}" != "1" ]]; then
python3 - <<'PY'
import ctypes, sys
lib = ctypes.CDLL("libcuda.so.1")
rc = lib.cuInit(0)
n = ctypes.c_int(0)
rc2 = lib.cuDeviceGetCount(ctypes.byref(n))
print(f"cuInit rc={rc}, device count={n.value}")
if rc != 0 or rc2 != 0 or n.value < 1:
    sys.exit("FATAL: CUDA driver cannot initialise on this host (not a Python/package problem). "
             "Terminate this pod and deploy on a different machine.")
PY
fi

echo "== venv (Python 3.11) =="
if [[ -z "${VENV_DIR:-}" ]]; then
  if [[ -d /workspace ]]; then VENV_DIR=/workspace/venv; else VENV_DIR="$PWD/.venv"; fi
fi
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  if command -v python3.11 >/dev/null 2>&1; then
    python3.11 -m venv "$VENV_DIR"
  else
    # Image has no 3.11 -> let uv download a standalone CPython 3.11 (no apt, no PPA).
    if ! command -v uv >/dev/null 2>&1; then
      curl -LsSf https://astral.sh/uv/install.sh | sh
      export PATH="$HOME/.local/bin:$PATH"
    fi
    uv venv --python 3.11 --seed "$VENV_DIR"
  fi
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python --version | grep -q ' 3\.11\.' || { echo "FATAL: venv python is $(python --version), need 3.11" >&2; exit 2; }
echo "venv: $VENV_DIR ($(python --version))"

echo "== python deps (requirements.txt, cu130 wheels) =="
python -m pip install -q --upgrade pip
# The +cu130 torch pin lives on the PyTorch index; vLLM 0.24.0 itself comes from PyPI.
python -m pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu130
if [[ "${TRAIN:-0}" == "1" ]]; then
  # Training extras exactly as pilot_forgetting/README.md installs them (no-deps keeps the eval pins intact).
  python -m pip install --no-deps peft accelerate
fi

echo "== verify =="
python - <<'PY'
import platform, sys, torch, vllm, transformers, datasets
print(f"python       : {platform.python_version()}")
print(f"torch        : {torch.__version__} (cuda {torch.version.cuda})")
print(f"vllm         : {vllm.__version__}")
print(f"transformers : {transformers.__version__}")
print(f"datasets     : {datasets.__version__}")
assert torch.cuda.is_available(), "CUDA not available inside torch"
assert str(torch.version.cuda).startswith("13."), f"expected a cu130 torch build, got cuda {torch.version.cuda}"
assert vllm.__version__ == "0.24.0", f"expected vLLM 0.24.0 (the pinned eval engine), got {vllm.__version__}"
p = torch.cuda.get_device_properties(0)
print(f"gpu          : {p.name}, {p.total_memory / 2**30:.1f} GiB, sm_{p.major}{p.minor}, bf16={torch.cuda.is_bf16_supported()}")
assert p.major >= 8, "bf16 needs compute capability >= 8.0"
PY
echo "setup OK"
