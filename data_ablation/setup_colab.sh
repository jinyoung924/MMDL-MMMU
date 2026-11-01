#!/usr/bin/env bash
# Colab environment for the data-ablation loop, pinned like the RunPod/4090 baseline environment
# (requirements.txt: Python 3.11 / vLLM 0.24.0 / torch 2.11.0+cu130) plus peft/accelerate for training.
#
#   bash data_ablation/setup_colab.sh            # -> /content/venv (local disk; rebuilt every session, ~10 min)
#   source /content/venv/bin/activate
#
# Colab's own torch stack is not touched: everything goes into a separate Python 3.11 venv made with uv, exactly as
# cloud/setup_runpod.sh does on a pod. The host driver must be >= 580 (CUDA 13 wheels); Colab L4/A100 runtimes
# have shipped 580.x since 2026-09 (results/v5 environment.json on the dongjun-lee branch).
set -euo pipefail
cd "$(dirname "$0")/.."
VENV_DIR="${VENV_DIR:-/content/venv}"
export HF_HOME="${HF_HOME:-/content/hf}"
mkdir -p "$HF_HOME"

echo "== system =="
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
DRIVER_MAJOR="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | cut -d. -f1)"
if [[ "${DRIVER_MAJOR:-0}" -lt 580 ]]; then
  echo "FATAL: driver $DRIVER_MAJOR < 580; torch 2.11.0+cu130 needs a CUDA 13 driver. Runtime -> Disconnect and delete runtime, then reconnect." >&2
  exit 2
fi

echo "== venv (Python 3.11 via uv) =="
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
    export PATH="$HOME/.local/bin:$PATH"
  fi
  uv venv --python 3.11 --seed "$VENV_DIR" >/dev/null
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python --version | grep -q ' 3\.11\.' || { echo "FATAL: venv python is $(python --version), need 3.11" >&2; exit 2; }

echo "== python deps (requirements.txt, cu130 wheels) =="
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu130
python -m pip install -q --no-deps peft accelerate
# pillow 12.3.0 raised `ImportError: cannot import name '_Ink' from 'PIL._typing'` in one Colab stack (dongjun-lee
# branch, 2026-09). The pinned stack here was validated with 12.3.0 on the 4090; if the import below fails on it,
# fall back to 12.2.0 (image decoding only, does not change evaluation results).
python - <<'PY' || python -m pip install -q "pillow==12.2.0"
import PIL.Image, torchvision  # noqa
PY

echo "== verify =="
python - <<'PY'
import platform, torch, vllm, transformers, datasets, peft, PIL
print(f"python {platform.python_version()} | torch {torch.__version__} (cuda {torch.version.cuda}) | vllm {vllm.__version__} | "
      f"transformers {transformers.__version__} | datasets {datasets.__version__} | peft {peft.__version__} | pillow {PIL.__version__}")
assert torch.cuda.is_available(), "CUDA not available inside torch"
assert str(torch.version.cuda).startswith("13."), f"expected a cu130 torch build, got cuda {torch.version.cuda}"
assert vllm.__version__ == "0.24.0", f"expected vLLM 0.24.0 (the pinned eval engine), got {vllm.__version__}"
p = torch.cuda.get_device_properties(0)
print(f"gpu {p.name}, {p.total_memory / 2**30:.1f} GiB, bf16={torch.cuda.is_bf16_supported()}")
PY
echo "setup OK -> source $VENV_DIR/bin/activate"
