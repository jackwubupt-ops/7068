# PatchLoop

**Agentic repository-level bug repair with a small open model, evaluated on SWE-bench Lite.**
HKU COMP7608B project, built on top of the Group 8 CodeNexus demo.

PatchLoop takes a real GitHub issue and the repository at its historical base commit, localizes
the bug with read-only tools, writes a candidate patch, applies it in an isolated Git worktree and
exports it in official SWE-bench prediction format. Whether an issue is *resolved* is decided only
by the official SWE-bench harness.

> **New here?** One machine, one runbook (Chinese, step by step with pass criteria):
> [Alibaba Cloud Hong Kong GPU runbook](docs/aliyun-gpu-runbook.md): an A10 (24 GB) ECS box with Docker and direct
> GitHub/Hugging Face access runs everything: Qwen2.5-Coder-7B on vLLM → SWE-bench Lite dev smoke and pilot →
> **official evaluation** (`swebench==4.1.0`, prebuilt images) → paired statistics.
> The older two-machine setup (AutoDL for inference + a CPU box for evaluation) is kept for reference only.

---

## Research questions (proposal)

| | Question | Comparison | Status |
|---|---|---|---|
| **RQ1** | Does QLoRA fine-tuning help a 7B code model repair repositories? | Qwen2.5-Coder-7B base vs. QLoRA (SWE-smith data, leakage-filtered) | not started |
| **RQ2** | Does execution feedback help? | 1 candidate vs. execution feedback with up to 3 candidates | apply-failure feedback only; test feedback not built yet |
| **RQ3** | Does a multi-agent structure help at a matched budget? | single agent vs. Planner–Coder–Reviewer | both pipelines implemented; no live results yet |

Data: SWE-bench Lite **dev** (23 tasks) for development, Lite **test** (300) held out for final
results. Primary metric: official resolution rate, with McNemar tests and bootstrap CIs on paired tasks.

## How it works

```
issue + repo @ base commit
        │
        ▼
 ┌──────────────┐  search_repo / read_file (read-only, bounded)
 │   Planner    │──────────────────────────────────────────────► suspected files + cited evidence
 └──────────────┘
        │
        ▼
 ┌──────────────┐  unified diff  or  SEARCH/REPLACE blocks (--edit-format)
 │    Coder     │──────────────────────────────────────────────► candidate patch
 └──────────────┘
        │  validate → git apply --check in a detached worktree at the base commit
        ▼
 ┌──────────────┐  on failure: diagnosis → Coder retries (2 attempts in SWE-bench runs)
 │   Reviewer   │
 └──────────────┘
        │
        ▼
 candidate.patch + predictions.jsonl  ──►  official SWE-bench harness / sb-cli  ──►  resolved?
```

`--agent single` replaces the three roles with **one** conversation using the same tools,
budgets and edit format (the RQ3 baseline).

## Status (2026-11-20)

| Area | State |
|---|---|
| Local serving | Qwen2.5-Coder-7B-Instruct on vLLM 0.19.1 / torch 2.10.0 (CUDA 12), verified live on an RTX 4090 |
| P-C-R pipeline on real SWE-bench tasks | verified live on one full-dev task (`sqlfluff__sqlfluff-4764`): 7B produced an applicable patch; judged likely unresolved, not officially evaluated |
| Lite dev batch runner (`--workers`, `--resume`) | implemented, offline-tested; live smoke pending |
| SEARCH/REPLACE edit format | implemented, offline-tested; live effect not measured |
| Single-agent baseline (RQ3) | implemented, offline-tested; live run pending |
| Execution feedback in the loop (RQ2) | not built (needs Docker during generation; planned: SWE-bench instance images) |
| QLoRA (RQ1) | not started |
| Batch official evaluation + paired stats | `experiments.official_eval` (local Docker harness) and `experiments.paired_compare` (McNemar, bootstrap); offline-tested |
| Official resolution rate on Lite | no data yet |

Offline test suite: 122 tests pass, 1 skipped. These use scripted model replies and prove
wiring only, **not** model quality.

## Quick start

### 1. Offline checks (any machine, Python 3.11, Git)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements-lock.txt "datasets>=3,<5"
python -m unittest discover -s tests
```

### 2. GPU server: serve Qwen2.5-Coder-7B locally

```bash
PYTHON=python3.11 bash scripts/setup_qwen_small.sh          # new venv: vllm 0.19.1 + torch 2.10.0 (CUDA 12)
source .venv-qwen-vllm-cu12/bin/activate
QWEN_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct \
QWEN_MODEL_PATH=/root/autodl-tmp/qwen-models/Qwen2.5-Coder-7B-Instruct \
  bash scripts/start_qwen_small.sh                          # binds 127.0.0.1:8000 only
```

The setup script refuses CUDA 13 wheels. `nvidia-smi`'s "CUDA Version" is the driver's ceiling,
not the runtime PyTorch uses; `scripts/check_cuda_compat.py` checks the real pairing.

### 3. Client: preflight and a batch run

```bash
cp .env.qwen-small.example .env      # set QWEN_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct, QWEN_TIMEOUT=300
python -m experiments.qwen_small_dev --mode preflight
python -m experiments.lite_batch --list-repos | bash scripts/mirror_repos.sh
python -m experiments.lite_batch --out runs/lite-pilot-pcr    --agent pcr    --edit-format search_replace --workers 4
python -m experiments.lite_batch --out runs/lite-pilot-single --agent single --edit-format search_replace --workers 4
```

Then score each batch with the official harness (separate venv with `requirements-swebench-eval.txt`, Docker required)
and compare configurations on the same tasks:

```bash
# on the Docker machine, after copying the batch directories there
python -m experiments.official_eval --batch runs/lite-pilot-pcr --harness-python /data/venvs/swebench/bin/python
python -m experiments.official_eval --batch runs/lite-pilot-single --harness-python /data/venvs/swebench/bin/python
python -m experiments.paired_compare runs/lite-pilot-pcr runs/lite-pilot-single
```

Without Docker, use sb-cli instead (full test runbook, stage 8).

## Batch runner options (`python -m experiments.lite_batch`)

| Option | Default | Meaning |
|---|---|---|
| `--out DIR` | required | new output directory (or an existing one with `--resume`) |
| `--dataset` | `princeton-nlp/SWE-bench_Lite` | only the `dev` split is ever loaded |
| `--instances a,b,c` / `--limit N` | all 23 | task subset, deterministic order |
| `--agent pcr\|single` | `pcr` | Planner–Coder–Reviewer or single-agent baseline |
| `--edit-format diff\|search_replace` | `diff` | Coder output format |
| `--workers N` | 1 | tasks run concurrently against vLLM (4 suits 7B on 24 GiB) |
| `--resume` | off | continue an interrupted batch with identical arguments |
| `--list-repos` | — | print repositories to mirror, then exit |

Output directory: `manifest.json` (tasks, model, budgets, git commit, agent, edit format,
workers), one sub-directory per task with `run_status.json` (+ `candidate.patch`,
`predictions.jsonl`), `results.jsonl`, `all_preds.jsonl` and `summary.json`.

### Task status meanings

| Status | Meaning |
|---|---|
| `prediction_ready` | an applicable patch was exported; **not** a resolution |
| `no_candidate_files` | the Planner localized no file |
| `no_submission` | the single agent never submitted an edit within its budget |
| `patch_failed` | every edit attempt failed validation or `git apply` |
| `experiment_error` / `batch_error` | model, protocol or harness error (see `failed_stage`, `error`) |
| `workspace_error` / `source_isolation_violation` | Git worktree problem / source checkout changed (prediction discarded) |

## Integrity rules

- Benchmark gold patches, `test_patch`, `FAIL_TO_PASS`/`PASS_TO_PASS` and hints never enter a prompt;
  the task loader strips them and only the `dev` split is loaded during development.
- The harness never edits model-written code. It may only recount `@@` hunk-header numbers;
  SEARCH blocks must match the original file exactly and exactly once.
- Patches are applied only in temporary detached worktrees; the source checkout must stay clean.
- No model-generated shell commands run. No silent fallback to another model provider.
- The vLLM endpoint binds to 127.0.0.1; use SSH port forwarding from other machines.
- `.env` is never committed.
- Scripted-reply tests and CI prove wiring, never model quality.

## Repository map

| Path | Purpose |
|---|---|
| `experiments/lite_batch.py` | SWE-bench Lite dev batch runner |
| `experiments/deepseek_swebench_dev.py` | single-task P-C-R pipeline on a real SWE-bench instance (`run_real_dev`) |
| `experiments/single_agent_dev.py` | single-task single-agent pipeline |
| `experiments/official_eval.py`, `paired_compare.py` | batch official evaluation (local harness) and McNemar/bootstrap comparison |
| `experiments/qwen_small_dev.py` | Qwen preflight / Docker smoke / single dev task CLI |
| `patchloop_task2/qwen_small.py` | local vLLM client with per-task call and token budgets |
| `patchloop_task2/coder.py`, `edit_blocks.py` | diff Coder; SEARCH/REPLACE parsing and conversion |
| `patchloop_task2/single_agent.py` | single-agent loop |
| `patchloop_task2/reviewer.py`, `loop.py`, `execution.py` | Reviewer, Task 3 Docker loop |
| `patchloop_task2/validator.py`, `normalizer.py`, `workspace.py` | patch validation, hunk recount, isolated apply |
| `prompt_agent.py`, `utils/repo_tools.py` | Planner (Task 1) and its read-only tools |
| `swebench_dev.py` | leak-safe SWE-bench dev loader and checkout |
| `scripts/` | GPU setup/start, CUDA compatibility check, repo mirroring, saved-prediction evaluation |
| `tests/` | offline unit and integration tests |
| `app.py`, `templates/`, `static/` | original CodeNexus Flask demo |

## Documentation

- [Alibaba Cloud GPU runbook](docs/aliyun-gpu-runbook.md): **main workflow**, one Hong Kong GPU box for serving, batches and official evaluation (Chinese)
- [Full test runbook](docs/full-test-runbook.md): old AutoDL GPU box workflow, reference only (Chinese)
- [Alibaba Cloud CPU runbook](docs/aliyun-runbook.md): old CPU-only evaluation box, reference only (Chinese)
- [Qwen small-model and 7B guide](docs/qwen-small.md): CUDA/driver compatibility, serving, batch options, edit formats, single agent
- [Qwen + SWE-bench guide](docs/qwen-swebench.md): official evaluation details
- [Task 1](docs/task1.md) · [Task 2](docs/task2.md) · [Task 3](docs/task3.md): Planner, Coder/apply harness, Docker Reviewer loop
- [DeepSeek live experiment](docs/experiments/deepseek-live.md)
- [Code review notes](docs/code-review.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

## Original CodeNexus demo and Tasks 1–3

The original demo and the course Tasks 1–3 remain available unchanged.

```bash
cp .env.example .env                              # OPENAI_API_KEY / OPENAI_MODEL / optional OPENAI_BASE_URL
python -m flask --app app run --debug             # http://127.0.0.1:5000 and /localize
python localize.py --repo PATH --base-commit SHA --issue-file issue.txt                 # Task 1
python repair.py --repo PATH --base-commit SHA --issue-file issue.txt --out r.json      # Task 2
python repair_loop.py --repo PATH --base-commit SHA --issue-file issue.txt \
  --image python:3.11-slim --test-runner unittest --max-candidates 3 --out r.json        # Task 3 (Docker)
python demo_localization.py --offline             # scripted demo with real repository tools
```

Set `PATCHLOOP_MODEL_BACKEND=qwen` to route the demo and Tasks 1–3 through the local vLLM server.
Generation scripts (`pipeline_agent.py`, `manual_generate.py`) call the configured API and may
incur charges; `Visualization1.py` and `Visualization2.py` plot the included CSV.

## Roadmap

1. Lite dev smoke and 23-task pilot with live 7B (P-C-R diff vs. search_replace, P-C-R vs. single agent), scored with the local official harness.
2. Execution feedback (RQ2): run existing tests and model-written reproduction scripts inside the SWE-bench instance images (never the eval script / test_patch), up to 3 candidates.
3. Lite test (300) paired runs with McNemar tests and bootstrap CIs.
4. QLoRA on SWE-smith with repository and near-duplicate leakage filtering (RQ1).
