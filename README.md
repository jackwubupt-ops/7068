# PatchLoop / CodeNexus Demo

HKU COMP7608B project: incremental repository bug localization on top of the Group 8 CodeNexus demo.

## Run locally

Requirements: Python 3.11 and Git. Ripgrep is optional; repository search has a Python fallback.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
Copy-Item .env.example .env
```

Edit `.env` with your own `OPENAI_API_KEY`, `OPENAI_MODEL` and optional `OPENAI_BASE_URL` for an OpenAI-compatible provider. Choose a model your account supports; the template retains the original demo model. No credentials are included.

```powershell
.\.venv\Scripts\python.exe -m flask --app app run --debug
```

Open http://127.0.0.1:5000 for code generation or http://127.0.0.1:5000/localize for repository localization. `start.ps1` provides the same startup command. In VS Code, select `.venv/Scripts/python.exe`.

## Task 1: repository localization

Input: Issue text + local Git repository root + Base Commit SHA.
Output: candidate files + numbered evidence + root-cause hypothesis + repair plan.
The target repository must be clean and HEAD must match the commit. No clone, checkout, patch application or repository test execution is performed.

```powershell
.\.venv\Scripts\python.exe localize.py --repo C:\path\repo --base-commit YOUR_SHA --issue-file issue.txt
.\.venv\Scripts\python.exe demo_localization.py --offline
```

The offline demo uses real repository tools with scripted model actions. Omit `--offline` to run with the configured model. Neither a valid plan nor LLM scores establish that a repair works.

## Task 2: generate and apply a candidate Git patch

Task 2 reuses the Task 1 Planner output (suspected_files and verified read_file evidence).
The Coder produces a unified Git diff; the controlled harness validates the patch and applies
it only within a temporary detached Git worktree at the Base Commit.
The target repo stays unchanged and no repository code/tests are executed in Task 2.

~~~powershell
.\.venv\Scripts\python.exe repair.py --repo C:\path\target --base-commit FULL_SHA --issue-file issue.txt --out result.json --out-patch C:\temp\candidate.patch
~~~

An applied patch is not evidence that the issue is resolved. The original Flask Demo
and its generation route remain unchanged. See [Task 2 guide](docs/task2.md).

## Task 3: execution-grounded tests and Reviewer retries

Task 3 adds a real Docker test runner and a bounded Coder–Reviewer feedback
loop (maximum three complete patches, each checked out from the original Base
Commit). The Reviewer diagnoses actual failing test logs; Docker outages and
timeouts stop rather than being treated as code failures. No model-generated
shell commands execute, and the original target repository remains unchanged.

~~~powershell
docker pull python:3.11-slim
.\.venv\Scripts\python.exe -m examples.task3_docker_smoke
.\.venv\Scripts\python.exe repair_loop.py --repo C:\target --base-commit FULL_SHA --issue-file issue.txt --image python:3.11-slim --test-runner unittest --max-candidates 3 --out C:\logs\repair.json
~~~

The first command pre-pulls a trusted image; the smoke executes actual Docker
tests with **scripted model outputs**, not a real LLM. Real model runs reuse
the configured OpenAI-compatible adapter. An internal test pass is NOT
equivalent to official SWE-bench resolution. See [Task 3 guide](docs/task3.md).

## Real Qwen + SWE-bench development integration

The model endpoint must genuinely serve Qwen2.5-Coder-7B-Instruct (e.g. vLLM
on an NVIDIA GPU). Preserve the original CodeNexus API client: copy
`.env.qwen.example` to your local `.env`, and start the Qwen server.

~~~bash
python -m patchloop_task2.qwen
python -m pip install 'datasets>=3,<5'
python swebench_dev.py --mode inspect --output-dir /tmp/patchloop-dev-inspect
python swebench_dev.py --mode predict --instance-id sqlfluff__sqlfluff-4764 --output-dir /tmp/patchloop-qwen-dev
~~~

Inspect mode downloads a real historical Git repository from **full SWE-bench dev**.
Predict mode requires a LIVE Qwen endpoint and exports an applicable candidate
in official SWE-bench prediction format. An applicable patch is NOT a resolved issue.
SWE-bench Lite has no official dev split; leave its test split for held-out evaluation.

See [Qwen + SWE-bench guide](docs/qwen-swebench.md) for GPU setup, safety,
command lines, and official evaluation instructions.

## Qwen 0.5B / 0.6B local GPU inference and real SWE-bench development

**Primary model:** Qwen/Qwen2.5-Coder-0.5B-Instruct via a localhost-only vLLM server.
The existing CodeNexus Demo and Task 1–3 remain available. Qwen is an opt-in
experiment using a dedicated backend and NEVER silently falls back to DeepSeek.

~~~bash
bash scripts/setup_qwen_small.sh
source .venv-qwen-server/bin/activate
bash scripts/start_qwen_small.sh
# In another terminal, using a separate PatchLoop client environment:
python -m experiments.qwen_small_dev --mode preflight
python -m experiments.qwen_small_dev --mode smoke --out /tmp/qwen-smoke-01
python -m experiments.qwen_small_dev --mode dev --out /tmp/qwen-full-dev-01
~~~

Preflight and dev modes use ACTUAL model inference and require a running vLLM
endpoint; smoke also requires a Docker daemon. A separate CI smoke with scripted
model replies proves API/patch/Docker wiring but NOT Qwen model performance.

Only an applicable diff creates SWE-bench predictions. An official Resolved
or Unresolved verdict requires the pinned evaluation harness; historical
sqlfluff dependency repair is disclosed as a nonstandard environment override.

See [Qwen small-model guide](docs/qwen-small.md).

## Original demo and visualizations

```powershell
.\.venv\Scripts\python.exe pipeline_agent.py
.\.venv\Scripts\python.exe manual_generate.py
.\.venv\Scripts\python.exe Visualization1.py
.\.venv\Scripts\python.exe Visualization2.py
```

Generation scripts call the configured API and may incur charges. Visualizations use the included CSV. `test_agent.py` is a business module, not a pytest suite.

## Verification and team notes

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

- [Changelog](CHANGELOG.md): update this with each team change.
- [Contributing](CONTRIBUTING.md): project map, checks and Task 2 interface.
- [Task 1 implementation](docs/task1.md): interfaces, evidence and limits (Chinese).
- [Code review](docs/code-review.md): cleanup decisions and retained checks.
- [Offline example](docs/task1-demo.json): actual scripted demo output, with local path redacted.

`requirements.txt` contains direct dependency ranges; `requirements-lock.txt` records the installed versions. `.env`, virtual environments, caches and runtime logs are intentionally excluded from Git. Run the web app locally; its repository input grants access to local source files.

Real model localization and SWE-bench evaluation have not been validated. Task 3 adds Docker execution and Reviewer retries. A real development Issue checkout and live Qwen endpoint preflight are available; live Qwen inference, QLoRA and official SWE-bench evaluation require GPU/Docker execution and remain unverified.
