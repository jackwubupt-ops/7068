#!/usr/bin/env bash
# Start a LOCAL ONLY OpenAI-compatible vLLM service on your GPU server.
set -euo pipefail
cd "$(dirname "$0")/.."

# MODEL is the ID the PatchLoop client checks in /v1/models (QWEN_MODEL).
MODEL="${QWEN_MODEL:-Qwen/Qwen2.5-Coder-0.5B-Instruct}"
case "$MODEL" in
  "Qwen/Qwen2.5-Coder-0.5B-Instruct"|"Qwen/Qwen3-0.6B"|"Qwen/Qwen2.5-Coder-7B-Instruct") ;;
  *) echo "Unsupported model: $MODEL" >&2; exit 2 ;;
esac
# Optional: already-downloaded weights (e.g. from ModelScope). Served under $MODEL.
MODEL_PATH="${QWEN_MODEL_PATH:-}"
PORT="${QWEN_PORT:-8000}"
case "$PORT" in *[!0-9]*|"") echo "Port must be numeric" >&2; exit 2;; esac

if ! command -v vllm >/dev/null; then
  echo "vLLM unavailable. Run scripts/setup_qwen_small.sh and activate its venv." >&2
  exit 1
fi
echo "vllm executable: $(command -v vllm)"

SOURCE="$MODEL"
if [ -n "$MODEL_PATH" ]; then
  if [ ! -f "$MODEL_PATH/config.json" ] || ! ls "$MODEL_PATH"/*.safetensors >/dev/null 2>&1; then
    echo "QWEN_MODEL_PATH=$MODEL_PATH has no config.json/*.safetensors" >&2
    exit 1
  fi
  SOURCE="$MODEL_PATH"
  # Never fall back to downloading when local weights were requested.
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
fi

# Fail fast with a clear message instead of "Engine core initialization failed".
python scripts/check_cuda_compat.py

if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-gpu=index,name,driver_version,memory.total,memory.free --format=csv,noheader
fi

# 7B bf16 weights are ~15.2 GiB, so 0.65 of a 24 GiB card leaves almost no KV cache.
case "$MODEL" in
  *-7B-*) GPU_UTIL="${QWEN_GPU_MEMORY_UTIL:-0.90}" ;;
  *) GPU_UTIL="${QWEN_GPU_MEMORY_UTIL:-0.65}" ;;
esac

EXTRA=()
if [ "${QWEN_ENFORCE_EAGER:-0}" = "1" ]; then
  EXTRA+=(--enforce-eager)
fi
# Qwen3 thinks by default (<think>...</think> before the answer). PatchLoop's
# Planner/Reviewer expect bare JSON and preflight allows only 32 tokens, so
# disable thinking server-side unless QWEN3_ENABLE_THINKING=1.
if [ "$MODEL" = "Qwen/Qwen3-0.6B" ] && [ "${QWEN3_ENABLE_THINKING:-0}" != "1" ]; then
  EXTRA+=(--default-chat-template-kwargs '{"enable_thinking": false}')
fi

# Do not expose an unauthenticated endpoint on 0.0.0.0.
# From a different machine, use SSH: ssh -L 8000:127.0.0.1:8000 host
# 16K default: Coder prompts can reach ~24K chars (~8K tokens) + 3.5K output tokens,
# so 8192 can reject real PatchLoop requests.
echo "Serving ${SOURCE} as ${MODEL} on http://127.0.0.1:${PORT}/v1"
exec vllm serve "$SOURCE" \
  --served-model-name "$MODEL" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --dtype auto \
  --tensor-parallel-size 1 \
  --max-model-len "${QWEN_MAX_MODEL_LEN:-16384}" \
  --gpu-memory-utilization "$GPU_UTIL" \
  ${EXTRA[@]+"${EXTRA[@]}"}
