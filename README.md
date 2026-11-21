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
| Entry point | web app: `python -m patchloop_app.web` |
| Models | the **DeepSeek API** (`deepseek-flash`; used for the final experiments; no GPU needed; data leaves the machine) or local **Qwen2.5-Coder-7B-Instruct** on vLLM (private; the proposal's model, kept as the capability baseline) |
| Evaluation | SWE-bench Lite **dev**, scored only by the official harness (`swebench==4.1.0`, local Docker) |
| Final experiments | RQ1: reasoning effort none / low / high on `deepseek-flash`; RQ3: P-C-R vs single agent; Qwen-7B pilots as the model baseline |

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
   │    P-C-R:  Planner ──search_repo/read_file──► plan (files + line spans + hypothesis)
   │            Coder  ──► SEARCH/REPLACE edit ──► harness: parse → match → git apply (isolated worktree)
   │            Reviewer (on a failed attempt) ──► diagnosis ──► Coder retry (2 attempts)
   │    single: one conversation: search/read ──► {"action":"edit"} ──► edit ──► apply (2 submissions)
   │
   └─ outcome
        applicable patch ──► STOP: maintainer accepts (export / commit on new branch) or rejects
        no file / no edit / all attempts failed ──► STOP: questions to the maintainer
        follow-up (extra guidance, other agent or model) ──► new linked round (max 5)
```

Autonomous decisions: which keywords to search, which files and line ranges to read, which files
to edit (Planner), when to stop investigating (single agent `edit` action), and how to repair
after a failed apply (Reviewer → Coder). The harness, not the model, applies patches, so a model
can never run shell commands. Guards: per-task call and token budgets, a repeated-action guard,
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

In the page, choose an **example task** (SWE-bench Lite dev issue; the text is editable) or a
**local Git repository** on the server, then the model and the agent, and press *Run agent*. The
timeline shows every decision, tool result, edit, apply result and recovery step. A patch is shown
as a diff and waits for **Accept / Reject**. Accept saves the patch and, for a local repository,
commits it on a new branch `patchloop/<session>` through a temporary worktree (the current branch
and working tree are untouched). *Follow-up* appends guidance and may switch agent or model.
*Cancel* stops after the current model call.

### Sample inputs and traces

| Sample | Kind | Expected behaviour |
|---|---|---|
| [`samples/01_ordinary.json`](samples/01_ordinary.json) | ordinary task | full trace; ends with a patch awaiting confirmation (or questions) |
| [`samples/02_changed_request.json`](samples/02_changed_request.json) | changed request | round 2 carries the follow-up guidance and switches to the single agent |
| [`samples/03_failure_vague.json`](samples/03_failure_vague.json) | failure: vague request | stops with questions, zero model calls |
| [`samples/04_failure_bad_repo.json`](samples/04_failure_bad_repo.json) | failure: invalid repository | fails with a clear message, nothing exported |

```bash
python -m patchloop_app.samples --backend deepseek --out results/samples   # writes <name>.json + <name>.md
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

| Batch | Agent | Reasoning effort | Question |
|---|---|---|---|
| `ds-pcr` | P-C-R | none | RQ3 and the RQ1 baseline |
| `ds-single` | single | none | RQ3 |
| `ds-pcr-low`, `ds-pcr-high` (`ds-pcr-max` optional) | P-C-R | low / high (/ max) | RQ1 |

Everything else is identical across batches (edit format, retrieval top-10, call budget, answer
caps). Results go to `final-comparison.md`; they are reported in the final report.

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
repaired images and kept as the model baseline. Details: [docs/qwen7b-limits.md](docs/qwen7b-limits.md).

## 6. Integrity, privacy and safety

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
| RQ3: single agent vs. P-C-R under matched budgets | done on Lite dev (final run on `deepseek-flash`; Qwen-7B pilots as baseline) |
| RQ2: execution feedback (tests in the loop) | **partial**: apply/format feedback only, no test execution in the loop |
| RQ1: QLoRA fine-tuning | **changed** to reasoning effort (none / low / high) on `deepseek-flash`: same question (does more compute improve repair?), inference-time instead of training-time compute; why: [docs/qwen7b-limits.md](docs/qwen7b-limits.md) |
| Official evaluation and ablations | done on Lite dev; Lite test not run |
| Added after measurements | retrieval, tolerant matching, diagnosis tools, eval-image repair, DeepSeek backend, interactive web app |

## 8. Repository map

| Path | Purpose |
|---|---|
| `patchloop_app/` | **web app** (`web.py`), session logic and stop rules (`session.py`), sample runner (`samples.py`) |
| `samples/` | sample requests (ordinary, changed request, failures) |
| `patchloop_task2/` | backends (`backends.py`, `qwen_small.py`), single agent, Coder, edit blocks, Reviewer, apply/validate |
| `prompt_agent.py`, `utils/repo_tools.py`, `utils/retrieval.py` | Planner, read-only tools, retrieval |
| `experiments/` | batch runner, P-C-R and single pipelines, official eval, paired stats, diagnosis, recall |
| `scripts/` | vLLM setup/start, repository mirroring, eval-image repair |
| `tests/` | offline unit and integration tests |
| `docs/` | runbooks and design notes; `docs/aliyun-gpu-runbook.md` is the main server guide |
| `app.py`, `templates/`, `static/`, `localize.py`, `repair*.py` | earlier course demo and Tasks 1–3 (kept; not part of the final app) |

## 9. Submitted version, AI use, attribution

- Submitted version: tag `[v1.0-final]`, commit `[SHA]`.
- AI assistance: see `AI_DECLARATION.md` (tools used, what they helped with, project prompts).
- Reused software and data: SWE-bench / SWE-bench Lite (dataset and evaluation harness),
  Qwen2.5-Coder-7B-Instruct, vLLM, PyTorch, Hugging Face `datasets` / `huggingface_hub`, the OpenAI
  Python SDK (as an OpenAI-compatible client), Flask, and the DeepSeek API; used under their
  published licenses and terms.
