#!/usr/bin/env bash
# Create an ISOLATED vLLM server environment pinned to a CUDA 12 stack.
#
# An unpinned `pip install vllm` pulls the newest vLLM (0.20+ defaults to
# CUDA 13 and torch>=2.11 cu13). Those wheels fail on drivers < 580 with
# "The NVIDIA driver on your system is too old (found version 12060)".
# This script never touches the driver, the OpenPI env, or the client env.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3.11}"
VENV="${QWEN_SERVER_VENV:-.venv-qwen-vllm-cu12}"
REQS="requirements-qwen-server.txt"

if ! command -v nvidia-smi >/dev/null; then
  echo "nvidia-smi not found: run this on the GPU server." >&2
  exit 1
fi
DRIVER="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1 | tr -d ' ')"
DRIVER_MAJOR="${DRIVER%%.*}"
echo "NVIDIA driver: ${DRIVER}"
if [ "${DRIVER_MAJOR}" -lt 525 ]; then
  echo "Driver ${DRIVER} is too old for any CUDA 12 runtime (need >= 525.60.13)." >&2
  exit 1
fi
if [ "${DRIVER_MAJOR}" -ge 580 ]; then
  echo "Driver supports CUDA 13; the pinned CUDA 12 stack still works on it."
fi

if [ -e "$VENV" ]; then
  echo "$VENV already exists. Remove it or set QWEN_SERVER_VENV to a new path;" >&2
  echo "reusing an env that already holds CUDA 13 wheels can leave mixed nvidia-* libs." >&2
  exit 1
fi

"$PYTHON" -c 'import sys; assert sys.version_info[:2] in {(3,10),(3,11),(3,12),(3,13)}, sys.version' \
  || { echo "vLLM 0.19.1 needs Python 3.10-3.13" >&2; exit 1; }

"$PYTHON" -m venv "$VENV"
# shellcheck disable=SC1090
. "$VENV/bin/activate"
python -m pip install --upgrade pip
# torch first, so the resolver never considers a CUDA 13 torch build.
python -m pip install "torch==2.10.0" "torchvision==0.25.0" "torchaudio==2.10.0"
python -m pip install -r "$REQS"
python -m pip check || echo "WARNING: pip check reported issues (see above)." >&2

echo "--- installed CUDA-related wheels ---"
python -m pip list 2>/dev/null | grep -iE '^(torch|vllm|transformers|nvidia-cuda-runtime|nvidia-cudnn|flashinfer)' || true
if python -m pip list 2>/dev/null | grep -qiE '^nvidia-.*-cu13 '; then
  echo "ERROR: CUDA 13 wheels were installed into $VENV; aborting." >&2
  exit 1
fi

python scripts/check_cuda_compat.py
echo "Ready. Run: source $VENV/bin/activate && bash scripts/start_qwen_small.sh"
