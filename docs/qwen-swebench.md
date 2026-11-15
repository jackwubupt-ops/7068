# Real Qwen2.5-Coder-7B + SWE-bench development integration

## Scope and truth in reporting

- Real Qwen means the actual weights of Qwen/Qwen2.5-Coder-7B-Instruct are served through a local or tunneled vLLM OpenAI-compatible API. An endpoint claiming that model name is not cryptographic proof of weights; check the vLLM launch logs.
- Use princeton-nlp/SWE-bench **dev** (225 issues) for development. SWE-bench Lite has no official dev split; reserve Lite **test** (300 issues) for final reporting.
- Task 1+2 patch application does not mean issue resolved. The official SWE-bench evaluation harness decides whether tests pass.
- GitHub CI without a GPU can verify real dev issue ingestion and historical Git checkout, but cannot claim to have run the 7B model.

## A. Launch Qwen on an NVIDIA GPU server (e.g. AutoDL)

Use a SEPARATE Python environment for vLLM to avoid replacing the Demo's pinned dependencies.

~~~bash
python3.11 -m venv /root/autodl-tmp/qwen-vllm-venv
source /root/autodl-tmp/qwen-vllm-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install vllm
nvidia-smi
export CUDA_VISIBLE_DEVICES=0
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct \
  --host 127.0.0.1 --port 8000 \
  --dtype auto --tensor-parallel-size 1 \
  --max-model-len 8192 --gpu-memory-utilization 0.85
~~~

Common 7B BF16 inference can fit on a 24GB NVIDIA GPU, but actual headroom depends on VRAM, vLLM version and context length. Reduce the max context if needed. A first launch downloads model weights and requires Hugging Face connectivity. Never expose an unauthenticated endpoint publicly.

If PatchLoop runs on your own computer, create an SSH port-forward to the GPU server so the local address 127.0.0.1:8000 reaches the remote vLLM process.

## B. Point existing CodeNexus shared client to Qwen

Copy .env.qwen.example to .env in the PatchLoop root and use:

~~~dotenv
OPENAI_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_API_KEY=EMPTY
~~~

Never commit .env. The existing Planner, Coder and Reviewer share config.get_client(), so no alternate agent architecture is needed.

Verify a REAL chat call before attempting an Issue:

~~~bash
python -m patchloop_task2.qwen
~~~

This checks the advertised model ID and makes a short completion request. It refuses the original GPT/DeepSeek Demo endpoint.

## C. Inspect a REAL SWE-bench full-dev Issue + base repository

~~~bash
python -m pip install "datasets>=3,<5"
python swebench_dev.py --mode inspect --output-dir /tmp/patchloop-dev-inspect
~~~

The output contains the actual instance ID, repo, historical base SHA and a read-only search summary. The issue text and commit come from official SWE-bench full dev, not a synthetic bug. No model inference, patch application or source execution happens at this stage.

## D. Try the first real Qwen patch on that dev task

~~~bash
python swebench_dev.py --mode predict \
  --instance-id INSTANCE_ID_FROM_INSPECT \
  --output-dir /tmp/patchloop-qwen-dev
~~~

This requires the live Qwen endpoint and invokes the existing Task 1 Planner and Task 2 Coder. If a generated unified diff can be applied, it exports candidate.patch and predictions.jsonl with official SWE-bench fields plus run-status JSON. The result APPLIED is not an internal test pass and not officially resolved.

The Task 1 tools are intentionally bounded and the Coder only modifies Planner-identified files, so a complex real issue may fail localization or patch application. Record failure status rather than changing the task secretly.

## E. Run OFFICIAL SWE-bench development evaluation

Use an x86_64 host with Docker permissions and enough disk/RAM. Install the SWE-bench harness in its own environment. Check the installed harness CLI options first:

~~~bash
python -m pip install swebench
python -m swebench.harness.run_evaluation --help
python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench \
  --split dev \
  --instance_ids INSTANCE_ID_FROM_INSPECT \
  --predictions_path /tmp/patchloop-qwen-dev/predictions.jsonl \
  --max_workers 1 \
  --run_id patchloop-qwen-dev-001
~~~

The official harness determines resolved/unresolved. Do not label a dev result as SWE-bench Lite. Lite test evaluation is a later held-out experiment with a different dataset and split.

SWE-bench recommends x86_64, about 120GB free disk and >=16GB RAM for general evaluation. Docker cannot necessarily run inside a rental GPU container; if Docker is unavailable, run the evaluator on another Docker-capable Linux host. Do not reuse the same run_id when a prediction changed, because the evaluator caches results.

## Safety and reproducibility

- The adapter reads only instance_id, repo, base_commit and problem_statement. Gold patch, test patch, labels, hidden tests and hints are never sent to agents.
- Every inference attempt is pinned to a full real base commit and never modifies the original checkout.
- Qwen configuration is validated before live model inference; offline tests never masquerade as real model quality.
- Real Docker tests and official SWE-bench scoring are distinct. Do not use arbitrary repo tests in the lightweight Task 3 runner as official results.
- QLoRA and a large-scale ablation study are later steps.

## Verification

~~~bash
python -m unittest discover -s tests -v
python demo_localization.py --offline
python -m examples.task3_docker_smoke
python -m examples.swebench_real_dev_smoke
python -m patchloop_task2.qwen
~~~

The final check is live and requires Qwen/vLLM already running. The GitHub CI SWE-bench smoke uses real benchmark issue/repository input but no model.
