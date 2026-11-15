#!/usr/bin/env bash
# Start a LOCAL ONLY OpenAI-compatible vLLM service on your GPU server.
set -euo pipefail

MODEL="${QWEN_MODEL:-Qwen/Qwen2.5-Coder-0.5B-Instruct}"
case "$MODEL" in
  "Qwen/Qwen2.5-Coder-0.5B-Instruct"|"Qwen/Qwen3-0.6B") ;;
  *) echo "Unsupported model: $MODEL" >&2; exit 2 ;;
esac
PORT="${QWEN_PORT:-8000}"
case "$PORT" in *[!0-9]*|"") echo "Port must be numeric" >&2; exit 2;; esac

if ! command -v vllm >/dev/null; then
  echo "vLLM unavailable. Install it in a separate GPU environment first." >&2
  exit 1
fi
if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-gpu=index,name,memory.total,memory.free --format=csv,noheader
fi

# Do not expose an unauthenticated endpoint on 0.0.0.0.
# From a different machine, use SSH: ssh -L 8000:127.0.0.1:8000 host
echo "Serving ${MODEL} locally on http://127.0.0.1:${PORT}/v1"
exec vllm serve "$MODEL" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --dtype auto \
  --tensor-parallel-size 1 \
  --max-model-len "${QWEN_MAX_MODEL_LEN:-16384}" \
  --gpu-memory-utilization "${QWEN_GPU_MEMORY_UTIL:-0.65}"
