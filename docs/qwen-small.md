# PatchLoop: Qwen 0.5B–0.6B live inference + SWE-bench Dev

## Scope and status labels

This branch extends the original CodeNexus Demo, Task 1 Planner, Task 2 Coder, and Task 3 Reviewer/Docker loop. It does not rewrite or delete those components.

**Primary model:** Qwen/Qwen2.5-Coder-0.5B-Instruct, a code-instruction model that is much smaller than previous 7B/DeepSeek baselines. **Optional:** Qwen/Qwen3-0.6B for a small-model comparison. There is no model exactly named "Qwen 0.5-1B".

Status meanings:

- live_qwen_api_ok: a REAL HTTP model completion succeeded.
- internal_tests_passed: a real Qwen candidate passed selected Docker tests on a synthetic Git issue.
- prediction_ready: a real Qwen candidate Git patch applied to the official SWE-bench full/dev base commit.
- resolved / unresolved: the pinned official SWE-bench evaluator FINISHED its regression tests.
- infrastructure_error: the Docker environment failed. Do not call this unresolved.

CI that uses scripted model responses NEVER proves real Qwen repair capability.

## 1. GPU server (Linux + NVIDIA CUDA)

### 1.1 Driver / CUDA / PyTorch compatibility (read first)

| Layer | Where to read it | Example (AutoDL RTX 4090 D) |
|---|---|---|
| Kernel driver | `nvidia-smi` "Driver Version" | 560.35.03 |
| Highest CUDA the driver supports | `nvidia-smi` "CUDA Version" | 12.6 |
| CUDA runtime PyTorch was built with | `python -c "import torch; print(torch.version.cuda)"` | must be 12.x |

`nvidia-smi`'s CUDA Version is a ceiling set by the driver, not the runtime in use.
A CUDA 12.8/12.9 runtime works on a 12.6 driver (CUDA minor-version compatibility,
driver >= 525.60.13). A CUDA 13 runtime needs driver >= 580 and fails with
`The NVIDIA driver on your system is too old (found version 12060)`.

An unpinned `pip install vllm` installs the newest vLLM. Since vLLM 0.20.0 the
default PyPI wheel is CUDA 13 and pins torch >= 2.11, whose PyPI wheels are cu13.
`requirements-qwen-server.txt` pins the last CUDA 12 line instead:

- `vllm==0.19.1`: default wheel built with CUDA 12.9.1, includes sm_89 (RTX 4090).
- `torch==2.10.0`: the PyPI Linux wheel is cu128.
- `transformers==5.5.3`, `tokenizers==0.22.2`, `huggingface-hub==1.10.2`: the versions vLLM v0.19.1 CI tests with.

Do not upgrade the NVIDIA driver inside an AutoDL container. If your driver is
>= 580 you may use a newer vLLM, but this pinned stack also works there.

### 1.2 Install and start

Use a NEW environment. Do not reuse an env that already holds vLLM 0.20+/torch cu13
wheels, and do not install into the OpenPI environment.

~~~bash
cd /root/autodl-tmp/7068
git switch feature/qwen-small-end2end && git pull
nvidia-smi
df -h .

# Creates .venv-qwen-vllm-cu12 (override with QWEN_SERVER_VENV). Refuses an existing path.
PYTHON=python3.11 bash scripts/setup_qwen_small.sh
source .venv-qwen-vllm-cu12/bin/activate
python scripts/check_cuda_compat.py   # expects torch_cuda_runtime 12.x, compatible=true

# Serve already-downloaded weights (ModelScope/HF) under the HF model ID the client expects.
# HF_HUB_OFFLINE=1 is set automatically, so nothing is re-downloaded.
QWEN_MODEL_PATH=/root/autodl-tmp/qwen-models/Qwen2.5-Coder-0.5B-Instruct \
  bash scripts/start_qwen_small.sh
~~~

Without `QWEN_MODEL_PATH` the model is fetched from Hugging Face on first launch.
The script runs `check_cuda_compat.py` first and stops with a readable error if
the torch CUDA runtime is newer than the driver supports.

The inference server binds only to 127.0.0.1:8000, NEVER a public network interface.
Defaults: `QWEN_MAX_MODEL_LEN=16384` (Coder prompts can reach about 8K tokens plus
3.5K output tokens, so 8192 can reject real requests) and `QWEN_GPU_MEMORY_UTIL=0.65`.
If CUDA graph capture or torch.compile fails, retry with `QWEN_ENFORCE_EAGER=1`.

### 1.3 Optional: Qwen3-0.6B comparison

Qwen3 runs in thinking mode by default. `start_qwen_small.sh` passes
`--default-chat-template-kwargs '{"enable_thinking": false}'` when
`QWEN_MODEL=Qwen/Qwen3-0.6B`, so replies are bare text/JSON like Qwen2.5-Coder.
Set `QWEN3_ENABLE_THINKING=1` only for a separate thinking-mode experiment.
The client `.env` must use the same `QWEN_MODEL`.

~~~bash
modelscope download --model Qwen/Qwen3-0.6B --local_dir /root/autodl-tmp/qwen-models/Qwen3-0.6B
QWEN_MODEL=Qwen/Qwen3-0.6B QWEN_MODEL_PATH=/root/autodl-tmp/qwen-models/Qwen3-0.6B \
  bash scripts/start_qwen_small.sh
~~~

### 1.4 Proposal base model: Qwen2.5-Coder-7B-Instruct

The project proposal uses Qwen2.5-Coder-7B-Instruct as the RQ1 baseline and QLoRA base.
bf16 weights are about 15.2 GiB; the start script defaults `--gpu-memory-utilization`
to 0.90 for 7B (0.65 for the small models), which leaves roughly 5–6 GiB of KV cache on
a 24 GiB RTX 4090 — enough for `--max-model-len 16384`. The client `.env` must use the
same `QWEN_MODEL`; raise `QWEN_TIMEOUT` (for example 300) because 7B decoding is slower.

~~~bash
modelscope download --model Qwen/Qwen2.5-Coder-7B-Instruct --local_dir /root/autodl-tmp/qwen-models/Qwen2.5-Coder-7B-Instruct
QWEN_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct QWEN_MODEL_PATH=/root/autodl-tmp/qwen-models/Qwen2.5-Coder-7B-Instruct \
  bash scripts/start_qwen_small.sh
~~~

Verify the endpoint:

~~~bash
curl -s http://127.0.0.1:8000/v1/models
curl -s http://127.0.0.1:8000/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen2.5-Coder-0.5B-Instruct","messages":[{"role":"user","content":"Reply with READY"}],"max_tokens":8,"temperature":0}'
~~~

If running the PatchLoop client on another computer, use SSH port forwarding, not an unauthenticated public API:

~~~bash
ssh -N -L 8000:127.0.0.1:8000 USER@YOUR_GPU_SERVER
~~~

## 2. PatchLoop client (another terminal)

~~~bash
cd 7068
python3.11 -m venv .venv-patchloop-client
source .venv-patchloop-client/bin/activate
python -m pip install -U pip
python -m pip install -r requirements-lock.txt
python -m pip install "datasets>=3,<5"
[ -f .env ] || cp .env.qwen-small.example .env
# If .env already exists, add the QWEN_* and PATCHLOOP_MODEL_BACKEND settings to it manually.
python -m experiments.qwen_small_dev --mode preflight
~~~

The local .env must NEVER be committed. QWEN_API_KEY=EMPTY is ONLY for a localhost vLLM endpoint and is not a paid-provider key. PATCHLOOP_MODEL_BACKEND=qwen also routes the ORIGINAL CodeNexus Flask Demo and the shared Task 1-3 model client through the same local vLLM server. The default OpenAI-compatible behavior remains unchanged unless this flag is set. The Qwen client has NO silent fallback to DeepSeek or OpenAI.

## 3. REAL Qwen -> Git -> Docker smoke

Requires Docker Engine on the machine running the client. Rental GPU containers may not allow nested Docker. If docker info fails, use the dev prediction step and evaluate on a separate Docker-capable Linux host.

~~~bash
docker info
docker pull python:3.11-slim
python -m experiments.qwen_small_dev --mode smoke --max-candidates 2 --out /tmp/qwen-small-smoke-01
~~~

This genuinely calls vLLM for Planner/Coder/Reviewer, validates the diff, applies it in detached Git worktrees, runs real Docker unittest cases and records outcomes. Failure to return JSON or an applicable patch is an actual failed model attempt.

An OFFLINE API-CONTRACT test, using scripted model replies but REAL Git/Docker, is available:

~~~bash
python -m examples.qwen_small_scripted_smoke
~~~

That proves only integration, not live model quality.

## 4. REAL SWE-bench Full/dev issue

~~~bash
python -m experiments.qwen_small_dev --mode dev --out /tmp/qwen-small-swebench-dev-01
~~~

The CLI reuses the leak-safe full SWE-bench dev loader, issue sqlfluff__sqlfluff-4764 at historical base commit a820c139ccbe6d1865d73c4a459945cd69899f8f, with the original Task 1 -> Task 2 code and up to two Coder attempts.

The Harness accepts diffs only for Planner-suspected, tracked regular files. It may deterministically correct a hunk HEADER COUNT, but NEVER model-generated code lines; corrections and original hashes are recorded.

Only when status=prediction_ready does it produce candidate.patch, official-format predictions.jsonl, and a detailed run_status.json. A Git-applicable patch does NOT mean the Issue is resolved.

## 5. OFFICIAL SWE-bench evaluation, with disclosed environment fix

Use x86_64 Linux with Docker Engine and enough free disk/RAM. The official project recommends roughly 120 GB free disk and 16 GB memory for general evaluation, though one instance may need less.

Use an independent evaluator environment:

~~~bash
python3.11 -m venv .venv-swebench
source .venv-swebench/bin/activate
python -m pip install "swebench==3.0.0"
bash scripts/evaluate_saved_swebench.sh /tmp/qwen-small-swebench-dev-01/predictions.jsonl qwen-dev-001
~~~

The wrapper runs official SWE-bench 3.0.0 test logic but substitutes ONE historically unavailable dependency in the sqlfluff Docker environment:

- types-pkg_resources -> types-setuptools.

This is a disclosed NONSTANDARD ENVIRONMENT COMPATIBILITY OVERRIDE, not a claim to have run a pristine original image. It does not modify tests, gold patches, or model predictions. For pristine evaluation, provide a verified historical wheel/prebuilt image instead.

The report intentionally distinguishes Resolved, Unresolved, and Infrastructure Error. A green workflow with zero completed instances is not a valid score.

## 6. Verification and comparison

~~~bash
python -m unittest discover -s tests -v
python -m examples.qwen_small_scripted_smoke  # Docker scripted response
python -m examples.swebench_real_dev_smoke     # real dev issue, no inference
python -m experiments.qwen_small_dev --mode preflight  # REAL Qwen API
~~~

For comparison with DeepSeek, keep dataset instance list, retries, prompt, evaluation environment and generation limits fixed. The 0.5B model is an engineering baseline, not a substitute for a high-capacity repair model.

This ChatGPT GitHub integration cannot SSH to your rented GPU server. No live Qwen inference result is claimed until the preflight or dev CLI actually connects to your running local vLLM service. Never commit SSH credentials or expose port 8000 publicly.
