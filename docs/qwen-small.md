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

Run in the existing PatchLoop repository on the GPU server. Use SEPARATE Python environments for vLLM and the client so the OpenPI environment is not overwritten.

~~~bash
git clone https://github.com/jackwubupt-ops/7068.git
cd 7068
git switch feature/qwen-small-end2end
nvidia-smi
df -h .

# Create an independent vLLM environment. Weights download on first launch.
bash scripts/setup_qwen_small.sh
source .venv-qwen-server/bin/activate
bash scripts/start_qwen_small.sh
~~~

The inference server binds only to 127.0.0.1:8000, NEVER a public network interface. The defaults of 16K max sequence length and 0.65 GPU memory utilization are starting points, not guarantees.

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
cp .env.qwen-small.example .env
python -m experiments.qwen_small_dev --mode preflight
~~~

The local .env must NEVER be committed. QWEN_API_KEY=EMPTY is ONLY for a localhost vLLM endpoint and is not a paid-provider key. The client has NO silent fallback to DeepSeek or OpenAI.

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
