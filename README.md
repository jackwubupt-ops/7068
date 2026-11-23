# PatchLoop: an issue-to-patch repair agent with the maintainer in the loop

**COMP7608B final project** · Group **[GROUP NUMBER]** · Members: **[MEMBER NAMES]**
<!-- Names/IDs are filled in only in the submission ZIP copy; this repository is public. -->

**Submitted version:** git tag `[v1.0-final]` (see section 9).

PatchLoop helps a **repository maintainer** turn a bug report into a **reviewable, Git-applicable
patch**. The maintainer gives an issue and a repository at a commit. The agent finds the relevant
code with retrieval and read-only tools, decides which files to change, writes an edit, checks
that it applies, recovers from failed attempts, and then **stops for the maintainer's decision**:
accept (export the patch or commit it on a new branch), reject, or send a follow-up. When the
request is too vague, or the agent cannot locate or edit the code, it stops and asks instead of
guessing.

| | |
|---|---|
| Users | maintainers/contributors of Python repositories triaging bug reports |
| Need | a first candidate fix, localized and applicable, with a visible trace of how it was found |
| Scope | **in:** a bug report against Python code: a SWE-bench Lite dev example, any local Git repository (uncommitted edits included), or code pasted into the page; follow-ups that add guidance or change the agent, model, reasoning effort or test execution. **out:** new features or refactors, non-Python code, requests unrelated to the repository (these stop with clarification questions), pushing or merging (an accepted patch is only committed on a new local branch) |
| Entry point | web app: `python -m patchloop_app.web` |
| Models | the **DeepSeek API** (`deepseek-flash`; used for the final experiments; no GPU needed; data leaves the machine) or local **Qwen2.5-Coder-7B-Instruct** on vLLM (private; the proposal's model, kept as the capability baseline) |
| Evaluation | SWE-bench Lite **dev**, scored only by the official harness (`swebench==4.1.0`, local Docker) |
| Final experiments | RQ1: reasoning effort none / low / high / max on `deepseek-flash`; RQ2: execution feedback; RQ3: P-C-R vs single agent; Qwen-7B pilots as the model baseline |

---

## 1. How it works

```
issue + repo@commit
   │
   ├─ clarification check ── too short / matches no code ──► STOP: ask the maintainer (no model call)
   │
   ├─ retrieval (BM25 + paths/tracebacks/definitions named in the issue) → top-K candidate files
   │
   ├─ agent (choose one; same tools, budgets and model for both)
   │    P-C-R:  Planner ──search_repo/find_definition/list_directory/read_file──► plan (files + line spans + hypothesis)
   │            Coder  ──► SEARCH/REPLACE edit ──► harness: parse → match → git apply (isolated worktree)
   │            Reviewer (on a failed attempt) ──► diagnosis ──► Coder retry (2 attempts)
   │    single: one conversation: same 4 tools ──► {"action":"edit"} ──► edit ──► apply (2 submissions)
   │
   └─ outcome
        applicable patch ──► STOP: maintainer accepts (export / commit on new branch) or rejects
        no file / no edit / all attempts failed ──► STOP: questions to the maintainer
        follow-up (extra guidance, other agent or model) ──► new linked round (max 5)
```

Agent tools (all read-only, tracked files at the base commit only; nothing is imported or executed):

| Tool | What the agent gets |
|---|---|
| `search_repo(query)` | matching lines with context (ripgrep, or a Python fallback) |
| `find_definition(name)` | where a class, function or method is defined: file, qualified name, line span, signature (Python `ast`) |
| `list_directory(relative_path)` | the tracked sub-directories (with file counts) and files under a directory |
| `read_file(relative_path, start_line, end_line)` | up to 200 numbered lines |
| `run_tests(test_path)` (with execution feedback) | runs one EXISTING tracked test file or node id at the base commit in a Docker sandbox: pass/fail counts, failing tests, output tail (max 3 per task) |

With execution feedback on (`--exec-feedback`, or "Run existing tests" in the app), the harness also
re-runs the tests the agent ran plus the test files of the changed modules after every applied
candidate; tests that passed before and fail with the patch are regressions and go back to the
agent (P-C-R: Reviewer -> Coder retry). Sandbox: no network, no capabilities, resource limits,
timeout; SWE-bench tasks use their evaluation image, local repositories `PATCHLOOP_TEST_IMAGE`.
Hidden benchmark tests (`test_patch`, FAIL_TO_PASS) are never run.

Autonomous decisions: which tool to use and with which arguments, which files and line ranges to read, which files
to edit (Planner), when to stop investigating (single agent `edit` action), and how to repair
after a failed apply (Reviewer → Coder). The harness, not the model, applies patches, so a model
can never run shell commands. After `git apply`, every changed Python file must still parse (`ast`, nothing executed); an edit that breaks a previously parsable file is a failed attempt (`syntax_invalid`) and goes back to the agent. Guards: per-task call and token budgets, a repeated-action guard,
strict reply protocols with bounded retries, and history trimming.

## 2. Requirements

| Component | Needed for | Version / size |
|---|---|---|
| Linux x86_64, Python 3.11, Git ≥ 2.30 | everything | tested on Ubuntu 22.04 |
| NVIDIA GPU with ≥ 22 GB (A10 / RTX 4090), driver ≥ 525 | local Qwen backend only | vLLM 0.19.1 + torch 2.10.0 (CUDA 12, pinned in `requirements-qwen-server.txt`) |
| DeepSeek API key (paid) | DeepSeek backend only | `deepseek-flash` or `deepseek-v4-pro`, non-thinking mode |
| Docker | official evaluation only | `swebench==4.1.0`, prebuilt `swebench/sweb.eval.x86_64.*` images |
| Disk | | weights 15 GB, venvs ~15 GB, Lite dev eval images ~29 GB |

At least one backend must be available. With only a DeepSeek key, no GPU is needed.
Client dependencies are pinned in `requirements-lock.txt`.

## 3. Setup

Step-by-step server guide with checks: [docs/aliyun-gpu-runbook.md](docs/aliyun-gpu-runbook.md).
Short version:

```bash
git clone https://github.com/jackwubupt-ops/7068.git && cd 7068
python3.11 -m venv .venv-patchloop-client
.venv-patchloop-client/bin/pip install -r requirements-lock.txt "datasets>=3,<5"
cp .env.qwen-small.example .env          # then edit .env (see below); .env is git-ignored
.venv-patchloop-client/bin/python -m unittest discover -s tests   # offline tests, no GPU/API
```

Local Qwen backend (GPU server):

```bash
PYTHON=python3.11 bash scripts/setup_qwen_small.sh               # isolated vLLM venv (CUDA 12 pins)
.venv-qwen-vllm-cu12/bin/hf download Qwen/Qwen2.5-Coder-7B-Instruct --local-dir /data/qwen-models/Qwen2.5-Coder-7B-Instruct
source .venv-qwen-vllm-cu12/bin/activate
QWEN_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct QWEN_MODEL_PATH=/data/qwen-models/Qwen2.5-Coder-7B-Instruct \
  QWEN_MAX_MODEL_LEN=32768 bash scripts/start_qwen_small.sh       # serves on 127.0.0.1:8000 only
```

Never `pip install` anything else into `.venv-qwen-vllm-cu12`: its versions are pinned as a set
(an upgraded `huggingface-hub` once broke vLLM start-up).

### Configuration (`.env`)

| Variable | Value used | Meaning |
|---|---|---|
| `QWEN_MODEL` | `Qwen/Qwen2.5-Coder-7B-Instruct` | model id served by vLLM |
| `QWEN_BASE_URL` | `http://127.0.0.1:8000/v1` | local endpoint only (a remote endpoint must be HTTPS) |
| `QWEN_CONTEXT_CHARS` | `48000` | history budget per Planner/agent call (vLLM `max_model_len` 32768) |
| `QWEN_MAX_CALLS` / `QWEN_TIMEOUT` | `20` / `300` | per-task call budget / request timeout (s) |
| `DEEPSEEK_API_KEY` | *(secret)* | enables the DeepSeek backend; **never commit it** |
| `DEEPSEEK_MODEL` | `deepseek-flash` | or `deepseek-v4-pro` |
| `DEEPSEEK_REASONING_EFFORT` | `none` | RQ1: `none` (thinking off) / `low` / `high` / `max`; batch runs use `--reasoning-effort` |

Fixed in code for both backends: temperature 0; output caps per call: Planner 1500, Coder 3500,
Reviewer 900, single agent 3500 tokens; 15 000 output tokens per task; Planner ≤ 14 turns,
single agent ≤ 16 replies, 2 edit attempts. DeepSeek budgets default to the Qwen values.
With thinking on (effort low/high/max) the **answer** caps and the 15 000 answer-token budget are
unchanged; each call gets extra room for hidden reasoning equal to DeepSeek's default thinking-mode
`max_tokens` (65 536 for low/high, 131 072 for max) and reasoning tokens are counted and capped
per task separately (400k / 600k / 1.2M). A call that runs out of room while reasoning fails
with `REASONING_EXHAUSTED_CALL`. DeepSeek
ignores temperature in thinking mode, so those runs are sampled, not greedy.

## 4. Run the agent (web app)

```bash
source .venv-patchloop-client/bin/activate
python -m patchloop_app.web --port 7860 --runs-dir /data/app-runs
# on your laptop: ssh -L 7860:127.0.0.1:7860 user@server   then open http://127.0.0.1:7860
```

The server binds to 127.0.0.1 and starts with whichever backends respond. To listen on another
interface an access token is mandatory: `--host 0.0.0.0 --token <random>` (open
`/?token=<random>`; restrict the port to your IP).

In the page, choose an **example issue** (SWE-bench Lite dev; the text is editable), **my repository**
(a local Git repository; with commit `HEAD`, uncommitted edits are included through a snapshot, and
the user's files, index and branch are never changed) or **paste code** (a file name and its code; the
agent gets a private repository with just that file), describe the bug, choose the model, agent,
reasoning effort and test execution, and press *Run agent*. The
timeline shows every decision, tool result, edit, apply result and recovery step. A patch is shown
as a diff and waits for **Accept / Reject**. Accept saves the patch and, for a local repository,
commits it on a new branch `patchloop/<session>` through a temporary worktree (the current branch
and working tree are untouched). *Follow-up* starts a **new linked round** (it does not pause and resume the old run): the guidance
is appended and the agent, model, reasoning effort or test execution may change.
*Cancel* stops after the current model call; a request still waiting in the queue stops at once.
If the delivered patch breaks existing tests, the result card says so, lists the failing tests
and Accept needs an explicit "accept anyway".

### Sample inputs and traces

Recorded traces of all five samples (DeepSeek, 2026-11-22): [`final_results/samples/`](final_results/samples/).

| Sample | Kind | Expected behaviour |
|---|---|---|
| [`samples/01_ordinary.json`](samples/01_ordinary.json) | ordinary task | full trace; ends with a patch awaiting confirmation (or questions) |
| [`samples/02_changed_request.json`](samples/02_changed_request.json) | changed request | round 2 carries the follow-up guidance and switches to the single agent |
| [`samples/03_failure_vague.json`](samples/03_failure_vague.json) | failure: vague request | stops with questions, zero model calls |
| [`samples/04_failure_bad_repo.json`](samples/04_failure_bad_repo.json) | failure: invalid repository | fails with a clear message, nothing exported |
| [`samples/05_exec_feedback.json`](samples/05_exec_feedback.json) | ordinary task, tests on | existing tests run before/after the edit in Docker; regressions go back to the Reviewer |

```bash
python -m patchloop_app.samples --backend deepseek --out results/samples   # writes <name>.json + <name>.md
bash scripts/export_results.sh   # server: bundle reports, batch results and traces -> final_results/
```

## 5. Evaluation

| Step | Command |
|---|---|
| **Final experiment, end to end** | `bash scripts/run_final_deepseek.sh` (generation → official eval → 7B re-eval → report; resumable; runbook stage 17) |
| Batch generation | `python -m experiments.lite_batch --backend qwen\|deepseek [--reasoning-effort none\|low\|high\|max] --out DIR --agent pcr\|single --edit-format search_replace --retrieval-k 10 --workers 4` |
| Official evaluation | `python -m experiments.official_eval --batch DIR --harness-python /data/venvs/swebench/bin/python --max-workers 4` |
| Paired comparison | `python -m experiments.paired_compare DIR_A DIR_B` (exact McNemar + bootstrap CI) |
| Final report | `python -m experiments.final_report --batch ds-pcr=DIR --batch ds-single=DIR ... --tasks-file GOLD_IDS --out PREFIX` (all configs + RQ1/RQ3/model pairs, comparability warnings) |
| Failure diagnosis | `python -m experiments.diagnose_patches DIR... --out PREFIX` (gold used for scoring only) |
| Retrieval recall | `python -m experiments.retrieval_recall --out PREFIX` (no model) |
| Environment check | gold self-test (`python -m swebench.harness.run_evaluation ... --predictions_path gold`); repair with `bash scripts/fix_eval_images.sh` |

Only tasks whose **gold** patch resolves in our environment count. Before the image repair this
was 15 of 23 Lite dev tasks (pvlib ×5, pydicom-1139/1413 and pyvista-4315 failed on dependency
drift). Every batch directory records its settings in `manifest.json` (model, backend, budgets,
retrieval, agent, edit format, workers, git commit).

### Final experiment design (DeepSeek `deepseek-flash`)

| Batch | Agent | Reasoning effort | Execution feedback | Question |
|---|---|---|---|---|
| `ds-pcr` | P-C-R | none | off | RQ3, and the RQ1/RQ2 baseline |
| `ds-single` | single | none | off | RQ3, and the RQ2 single-agent baseline |
| `ds-pcr-low`, `ds-pcr-high`, `ds-pcr-max` | P-C-R | low / high / max | off | RQ1 |
| `ds-pcr-exec`, `ds-single-exec` | P-C-R / single | none | on | RQ2 |

Everything else is identical across batches (4 read-only tools, edit format, retrieval top-10,
call budget, answer caps, syntax check). **Code version:** the exec batches ran at PatchLoop
`5723b89`, the others at `ea3ce08`. The only commit between them changes `lite_batch --resume`
(re-run tasks that hit an API billing/network error; `git diff ea3ce08 5723b89 -- '*.py'` touches
only `experiments/lite_batch.py` and its test), and no final-t4 result contains such an error, so
the agent code is the same on both sides. `repeat_report` now lists a commit difference as a
comparability warning. Each configuration ran **three times** (tags `final-t4`,
`final-t4-r2`, `final-t4-r3`):

```bash
RQ1_EFFORTS="low high max" EXEC_AGENTS="pcr single" TAG=final-t4 bash scripts/run_final_deepseek.sh
python -m experiments.repeat_report --tag final-t4 --tag final-t4-r2 --tag final-t4-r3 \
    --tasks-file GOLD_IDS --out /data/analysis/final-repeats-t4
```

### Final results (2026-11-22; 3 runs per configuration; official harness; 23 Lite dev tasks, all gold-resolvable after the image repair)

All files behind these tables (reports, per-batch settings, official verdicts, patches, per-task
run statuses, gold self-test, sample traces) are in [`final_results/`](final_results/README.md).

| Config | Reasoning | Exec feedback | Resolved per run | Mean rate | Applicable (mean) | Completion tok (mean; reasoning) | s/task | Run errors per run |
|---|---|---|---|---|---|---|---|---|
| `ds-pcr` | none | off | 9 / 10 / 9 | 40.6% | 22.7 | 32,394 (0) | 17.3 | 0 / 0 / 0 |
| `ds-single` | none | off | 11 / 11 / 9 | 44.9% | 19.7 | 8,307 (0) | 10.3 | 0 / 0 / 0 |
| `ds-pcr-low` | low | off | 11 / 10 / 8 | 42.0% | 21.3 | 118,236 (77,510) | 40.4 | 0 / 2 / 1 |
| `ds-pcr-high` | high | off | 9 / 8 / 9 | 37.7% | 20.7 | 243,731 (166,955) | 73.0 | 3 / 1 / 1 |
| `ds-pcr-max` | max | off | 11 / 11 / 10 | 46.4% | 21.3 | 491,298 (372,232) | 135.4 | 2 / 0 / 2 |
| `ds-pcr-exec` | none | **on** | 11 / 11 / 11 | **47.8%** | 22.7 | 34,452 (0) | 23.3 | 0 / 0 / 0 |
| `ds-single-exec` | none | **on** | 10 / 7 / 8 | 36.2% | 19.3 | 9,872 (0) | 15.9 | 0 / 0 / 0 |

Paired comparisons at the **task level** (each task counts once, as the share of its 3 runs that
resolved it, so repeated runs are not treated as independent tasks): exact sign test over tasks,
bootstrap 95% CI resampling tasks.

| Question | Pair | Mean difference | Tasks A better / B better / tied | Sign test p | 95% CI |
|---|---|---|---|---|---|
| RQ2 | P-C-R: exec feedback vs none | **+7.2 pt** | **3 / 0** / 20 | 0.25 | [0.0, +15.9] |
| RQ2 | single: exec feedback vs none | -8.7 pt | 0 / 4 / 19 | 0.125 | [-18.8, -1.5] |
| RQ1 | low vs none | +1.5 pt | 5 / 5 / 13 | 1.00 | [-8.7, +11.6] |
| RQ1 | high vs none | -2.9 pt | 1 / 4 / 18 | 0.375 | [-10.1, +5.8] |
| RQ1 | max vs none | +5.8 pt | 3 / 2 / 18 | 1.00 | [-4.3, +17.4] |
| RQ1 | high vs low | -4.3 pt | 2 / 5 / 16 | 0.45 | [-11.6, +2.9] |
| RQ3 | P-C-R vs single | -4.3 pt | 1 / 3 / 19 | 0.625 | [-13.0, +2.9] |

- **RQ2 (execution feedback):** with P-C-R it was the only change that helped consistently: 11
  resolved in all three runs, 3 tasks better and none worse; 23 tasks are too few for significance
  (p = 0.25). The regression check ran 77 times on P-C-R candidates (38 passed, 18 regressions
  sent back to the Reviewer, 21 with no matching test) and cost about +6% output tokens and +35%
  time per task. For the single agent the same feedback hurt (0 better, 4 worse): a regression
  costs it one of its two submissions and the rewrite is often worse, whereas P-C-R's Reviewer
  diagnoses the failure before the Coder retries. Existing tests can also encode the buggy
  behaviour the issue asks to change, so a "regression" is a signal, not proof. Neither agent
  ever chose the `run_tests` tool itself; all feedback came from the harness check.
- **RQ1 (reasoning effort):** more inference-time compute did not improve repair. No effort level
  differs significantly from thinking off, and the ranking changes between run sets (here max is
  highest; in the earlier 2-tool runs high was lowest), while output tokens grow about 15x and
  time about 8x from none to max. Higher effort adds a failure mode: reasoning that exhausts
  DeepSeek's default thinking room before answering (`REASONING_EXHAUSTED_CALL`).
- **RQ3 (role separation):** no significant difference (40.6% vs 44.9%; earlier runs 46.4% vs
  42.0%). P-C-R produces more applicable patches (22.7 vs 19.7) at about 3.9x the output tokens
  and 1.7x the time per task.
- **Model:** DeepSeek vs Qwen2.5-Coder-7B (pilot v3 re-evaluated on the same repaired images,
  0/23 for both agents) against the original DeepSeek round 1 on the same server: P-C-R 10 vs 0
  tasks and single 10 vs 0 (McNemar p = 0.002 each; one run per side). Data:
  [`final_results/first-server/`](final_results/first-server/README.md).
- **Syntax check:** never triggered in the four non-thinking configurations (DeepSeek edits kept
  the files parsable); it is covered by offline tests and matters for weaker models or the
  Windows demo without Docker.

#### Earlier agent version (2 tools, no syntax check or execution feedback; tags `final-ds`, `final-ds-r2`, `final-ds-r3`)

Mean resolution: none 46.4%, single 42.0%, low 44.9%, high 34.8%, max 40.6%. Current vs earlier,
same config, task level (`repeat_report --vs-tag`):

| Config | Current | Earlier | Difference | Tasks better / worse / tied | Sign test p | 95% CI |
|---|---|---|---|---|---|---|
| `ds-pcr` | 40.6% | 46.4% | -5.8 pt | 1 / 2 / 20 | 1.00 | [-18.8, +5.8] |
| `ds-single` | 44.9% | 42.0% | +2.9 pt | 1 / 0 / 22 | 1.00 | [0.0, +8.7] |
| `ds-pcr-low` | 42.0% | 44.9% | -2.9 pt | 2 / 4 / 17 | 0.69 | [-10.1, +4.3] |
| `ds-pcr-high` | 37.7% | 34.8% | +2.9 pt | 4 / 3 / 16 | 1.00 | [-5.8, +11.6] |
| `ds-pcr-max` | 46.4% | 40.6% | +5.8 pt | 5 / 3 / 15 | 0.73 | [-4.3, +15.9] |

The agents did use the new tools: `find_definition` in 201 of 483 task runs (7.8% of all tool
calls, taking share from `search_repo`, 45% -> 33%), `list_directory` only 8 times; `run_tests` was
attempted 3 times and never produced a test run. Resolution did not change measurably: the
differences are within the run-to-run variation (e.g. P-C-R none: 10/12/10 earlier, 9/10/9 now).
The tools change how the agent localizes (more direct jumps to definitions, slightly more reads:
3.1 vs 2.6 `read_file` per task), not how often it fixes the issue.

- **Caveats:** 23 tasks; three runs per configuration; thinking mode ignores temperature and
  run-to-run variation is large. A first attempt with smaller reasoning room (8K/24K/48K per call)
  truncated Coder calls and was discarded; runs interrupted by API billing errors were resumed and
  those tasks rerun (CHANGELOG).

### Qwen2.5-Coder-7B pilots: why the final experiments use DeepSeek (Lite dev, 23 tasks, search_replace)

| Version | Change | P-C-R applicable | single applicable | resolved (P-C-R / single) |
|---|---|---|---|---|
| pilot v1 | baseline after harness fixes (#18–#20) | 3 | 2 | 0 / 0 |
| pilot v2 | Planner give-up rule + whitespace-tolerant matching (#21) | 7 | 7 | 0 / 0 |
| pilot v3 | + retrieval top-10 (#23; recall@10 = 0.83) | 14 | 11 | 0 / 0 |

Diagnosis of v3: the gold file is now read in 83% (P-C-R) / 74% (single) of tasks (v2: 44% / 56%);
the remaining failures are mostly wrong edits at or near the right place. Harness work raised
applicable patches from 3 to 14, but 0 were resolved: the bottleneck is the 7B model's repair
ability, not localization or the agent loop, so RQ1/RQ3 on 7B would compare 0 against 0. The
final experiments therefore run on `deepseek-flash`; the 7B batches are re-evaluated on the
repaired images and kept as the model baseline. Details: [docs/qwen7b-limits.md](docs/qwen7b-limits.md);
all pilot batches, the vLLM log and the diagnosis reports: [`final_results/first-server/`](final_results/first-server/README.md).

## 6. Reliability, non-functional requirements, integrity and privacy

### 6.1 Failure situations and recovery

| Failure | Detection | Bounded recovery or safe stop | What the user sees | Evidence |
|---|---|---|---|---|
| Vague or off-topic request | fewer than 8 words, or the text matches no code in the repository (retrieval) | stop **before any model call** | questions asking for the file, function or expected behaviour; "run anyway" button | `samples/03`, `tests/test_app_session.py` |
| Invalid repository or commit | Git checks: repository root, commit exists, clean tree | stop, nothing exported | `failed` with the reason | `samples/04` |
| Edit cannot be applied / bad edit format | SEARCH must match exactly once; `git apply --check` in an isolated worktree | P-C-R: Reviewer diagnoses, Coder retries (2 attempts); single agent: 2 submissions | warning per failed attempt, then a patch or questions | `tests/test_edit_blocks.py`, `tests/test_deepseek_swebench_dev.py` |
| Edit breaks Python syntax | `ast.parse` of every changed file (nothing executed) | same retry path (`syntax_invalid`) | the file, line and error in the timeline | `tests/test_syntax_check.py` |
| Edit breaks existing tests (with "Run existing tests") | tests that passed at the base commit fail with the patch (Docker sandbox) | Reviewer -> Coder retry; if the retry does not apply, the earlier applicable patch is kept for the benchmark, but the app marks it **"breaks existing tests"** and Accept needs an explicit override | test check result in the timeline; warning on the result card | `samples/05`, `tests/test_exec_feedback.py`; 18 regressions caught in the final P-C-R runs |
| Model reply truncated, empty, or thinking runs out | finish reason / stage caps (`QWEN_TRUNCATED_OUTPUT`, `REASONING_EXHAUSTED_CALL`) | counted as a failed reply or attempt, never a crash; per-task budgets end the run | warning, then a stop with questions | `tests/test_reasoning_effort.py`; run errors per configuration in section 5 |
| Agent loops or exceeds its budget | per-task caps: 20 model calls, 15k answer tokens (+ reasoning budget), 14 Planner / 16 agent steps, repeated-action guard | stop | `needs_clarification` with what was tried | `tests/test_single_agent.py`, `tests/test_reasoning_effort.py` |
| Model API unavailable (no balance, auth, network) | API error | the run fails cleanly; `lite_batch --resume` reruns only those tasks | `failed` with a generic API error (no response text) | `tests/test_lite_batch.py`; used once in the final runs |
| User changes their mind | Cancel / Reject / Follow-up buttons | cancel after the current model call (a queued request stops at once); reject exports nothing; at most 5 follow-up rounds | session status | `tests/test_app_session.py` |

**Repeated external actions.** Every model call is billed and sends data to DeepSeek, so calls are
bounded per task (calls, answer tokens, reasoning tokens, request timeout) and the SDK does not
retry automatically; batches rerun failed tasks only on an explicit `--resume`. The agent never
changes the user's repository: edits are applied in temporary worktrees, and only **Accept**
commits the patch, on a new branch `patchloop/<session>`; nothing is ever pushed.

### 6.2 Non-functional requirements

| Requirement | Target / check | Measured (final runs, 23 tasks x 3) | Trade-off |
|---|---|---|---|
| Latency (interactive use) | thinking off: under 60 s per task | P-C-R 17 s, single 10 s, with test execution 23 s per task | thinking low/high/max: 40 / 73 / 135 s with no gain in resolution |
| Cost per task | bounded by 20 calls and 15k answer tokens; reported per run | P-C-R ~32k output + ~37k prompt tokens; single ~8k output; max effort ~490k output | P-C-R costs ~4x the single agent for more applicable patches; max effort ~15x |
| Workload / concurrency | batch runs with 4 parallel tasks per configuration | 3 runs x 7 configurations in parallel on a 32-vCPU / 64 GiB server; each session in the app runs in its own thread and temporary worktree | budgets are per task; there is no server-wide rate limit beyond the API's own |
| Privacy | code stays local with the Qwen backend; DeepSeek receives the issue and the code the agent reads | stated in the UI before every DeepSeek run; `.env` is git-ignored; reports store no prompt text | DeepSeek is far stronger (10/23 vs 0/23) but data leaves the machine |
| Safety of execution | the model never runs commands; tests run only in a no-network, capability-dropped Docker container with limits | `tests/test_exec_feedback.py` checks the sandbox flags | test execution needs Docker; without it the app says so and continues |
| Reproducibility | every batch records its settings and Git commit (`manifest.json`) | 36 batches in `final_results/runs/` | thinking mode ignores temperature, so runs are repeated 3 times |

### 6.3 Integrity and privacy rules

- Gold patches, `test_patch`, `FAIL_TO_PASS`/`PASS_TO_PASS` and hints never enter a prompt: the
  task loader keeps only issue, repository and commit. Gold is read only by the post-hoc analysis
  scripts, which no inference module imports (enforced by a test).
- Patches are applied only in temporary isolated checkouts; model output is never executed.
- The harness never rewrites model code, except hunk-header recounts, trailing-whitespace tolerant
  matching and one constant indentation shift (recorded per block in `search_match_modes`).
- Local backend: code stays on the server. DeepSeek backend: the issue and the code the agent reads
  are sent to DeepSeek and billed; the UI states this before every run.
- `.env` (API keys) is git-ignored; vLLM and the web app bind to 127.0.0.1 by default.
- Offline tests use **scripted model replies** (labelled in each test file): they prove wiring and
  safety rules, not model quality. Nothing in the delivered app is mocked.

## 7. Delivered vs. proposal

| Proposal item | Status |
|---|---|
| Harness: schemas, model adapter, tracing, repository tools, clean workspaces | done (own JSON protocol and dataclasses instead of LangGraph/Pydantic) |
| Single-agent end-to-end MVP; Planner–Coder–Reviewer with feedback | done; feedback covers apply/format failures |
| RQ3: single agent vs. P-C-R under matched budgets | done on Lite dev (final runs on `deepseek-flash`, 3 runs: 40.6% vs 44.9%, no significant difference; Qwen-7B pilots as baseline) |
| RQ2: execution feedback (tests in the loop) | implemented: `run_tests` tool + post-apply regression check on existing tests (Docker sandbox); evaluated as `ds-pcr-exec` / `ds-single-exec`: +7.2 pt for P-C-R (3 better, 0 worse), -8.7 pt for the single agent; not significant at 23 tasks |
| RQ1: QLoRA fine-tuning | **changed** to reasoning effort (none / low / high / max) on `deepseek-flash`; done (more effort did not help): same question (does more compute improve repair?), inference-time instead of training-time compute; why: [docs/qwen7b-limits.md](docs/qwen7b-limits.md) |
| Official evaluation and ablations | done on Lite dev; Lite test not run |
| Added after measurements | retrieval, tolerant matching, diagnosis tools, eval-image repair, DeepSeek backend, interactive web app |

## 8. Repository map

| Path | Purpose |
|---|---|
| `patchloop_app/` | **web app** (`web.py`, entry point), session logic and stop rules (`session.py`), sample runner (`samples.py`), page (`templates/patchloop.html`) |
| `prompt_agent.py`, `pipeline_agent.py` | Planner (prompt and tool loop) and its handoff |
| `utils/repo_tools.py`, `utils/retrieval.py` | read-only agent tools (`search_repo`, `read_file`, `find_definition`, `list_directory`), retrieval |
| `patchloop_task2/` | model backends (`backends.py`, `qwen_small.py`), Coder (`coder.py`, `edit_blocks.py`), single agent, Reviewer, patch validation and isolated apply with syntax check (`validator.py`, `workspace.py`), execution feedback (`test_exec.py`); `loop.py`/`execution.py` are the earlier Task 3 execution loop, still used by the live smoke in `experiments/live_deepseek.py` |
| `experiments/` | batch runner (`lite_batch.py`), P-C-R and single pipelines, official evaluation, reports (`final_report.py`, `repeat_report.py`), paired statistics, failure diagnosis, retrieval recall |
| `scripts/` | server setup (`setup_eval_server.sh`), final experiment (`run_final_deepseek.sh`), eval-image repair, repository mirroring, result export; vLLM setup/start for the local 7B baseline |
| `samples/` | sample requests: ordinary, changed request, two failures, execution feedback |
| `final_results/` | exported results of the final experiment and the recorded sample traces |
| `tests/` | offline unit and integration tests (scripted model replies, real temporary Git repositories) |
| `docs/` | server runbook (`aliyun-gpu-runbook.md`) and the 7B evidence (`qwen7b-limits.md`) |

### Course submission checklist

| Requirement (guideline) | Where |
|---|---|
| Runnable application, entry point and run command (no notebooks) | section 4: `python -m patchloop_app.web` |
| Setup, run and evaluation commands; dependency versions; model settings; services, paid access, hardware | sections 2, 3, 5; `requirements-lock.txt`, `requirements-swebench-eval.txt`, `.env.qwen-small.example` |
| Source code, prompts and configuration | prompts: `prompt_agent.py` (Planner), `patchloop_task2/edit_blocks.py` and `coder.py` (Coder), `reviewer.py`, `single_agent.py`; settings: `patchloop_task2/backends.py`, `.env` keys in section 3 |
| Sample inputs: ordinary task, changed request, failure case | `samples/01`-`05` |
| Evaluation scripts, results, success/failure traces | `experiments/`, `scripts/run_final_deepseek.sh`; `final_results/` (results, `samples/` traces) |
| Settings recorded, variable outputs accounted for | every batch `manifest.json`; 3 runs per configuration, task-level paired tests (section 5) |
| Users, needs, scope | top table (Users, Need, Scope) |
| Reliability: at least two failure situations, detection, recovery, user feedback, repeated external actions | section 6.1 (nine situations, each with tests or traces) |
| Non-functional requirements: targets, measures, results, trade-offs | section 6.2 |
| Credentials kept out; mocks and unavailable parts labelled | section 6; `.env` is git-ignored; offline tests are labelled as scripted |
| Submitted version identified | section 9 |
| AI-use declaration and prompts | section 9 |

## 9. Submitted version, AI use, attribution

- Submitted version: tag `[v1.0-final]`, commit `[SHA]`.
- AI assistance: see [`AI_DECLARATION.md`](AI_DECLARATION.md) (tools used, what they helped with, project prompts in `ai_prompts/`).
- Reused software and data: SWE-bench / SWE-bench Lite (dataset and evaluation harness),
  Qwen2.5-Coder-7B-Instruct, vLLM, PyTorch, Hugging Face `datasets` / `huggingface_hub`, the OpenAI
  Python SDK (as an OpenAI-compatible client), Flask, and the DeepSeek API; used under their
  published licenses and terms.
