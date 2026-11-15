#!/usr/bin/env bash
# Isolate vLLM/CUDA dependencies from the existing CodeNexus/OpenPI project.
set -euo pipefail
PYTHON="${PYTHON:-python3.11}"
"$PYTHON" -m venv .venv-qwen-server
. .venv-qwen-server/bin/activate
python -m pip install --upgrade pip
python -m pip install "vllm"
echo "Ready. Activate .venv-qwen-server and run bash scripts/start_qwen_small.sh"
