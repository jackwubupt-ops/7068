# Changelog

Record changes here so teammates can understand behavior and interface changes.
Add new entries under **Unreleased** in the same commit as the implementation.
These are development milestones, not published GitHub releases.

## Repository cleanup for submission (2026-11-22)

### Removed
- The original CodeNexus code-generation demo and its Task 1-3 CLIs, which are not part of the final agent: `app.py`, `templates/`, `static/`, `start.ps1`, `code_agent.py`, `test_agent.py`, `evaluator.py`, `manual_generate.py`, `Visualization*.py`, `experiment_results_extreme.csv`, `demo_localization.py`, `localize.py`, `repair.py`, `repair_loop.py`, `requirements.txt`, `.env.example`, `.env.qwen.example`, `examples/`, and their tests.
- SWE-bench 3.0.0-era evaluation helpers (`experiments/swebench_eval_compat.py`, `experiments/swebench_report.py`, `scripts/evaluate_saved_swebench.sh`), superseded by `experiments/official_eval.py` with swebench 4.1.0.
- Superseded docs (`docs/task1-3.md`, AutoDL and CPU-only runbooks, small-Qwen notes, live-smoke notes, code review notes) and `TODO.md` (unfinished work is listed in README section 7); CI workflows for retired experiments.

### Changed
- `pipeline_agent.py` is only the Planner handoff; `prompt_agent.py` no longer contains the demo's prompt refiner. CI runs the offline suite on Linux and Windows for `main` and `feat/**`. README gains a course submission checklist; CONTRIBUTING describes the current layout.

## Final results with the current agent (2026-11-22)

### Changed
- README section 5 now reports the final experiment with the current agent (4 tools, syntax check, optional execution feedback), 7 configurations x 3 runs (`final-t4*`): RQ2 execution feedback +7.2 pt for P-C-R (3 tasks better, 0 worse) and -8.7 pt for the single agent; RQ1 no effort level better than thinking off; RQ3 no difference. The earlier 2-tool runs are kept as the previous version, compared per config with `repeat_report --vs-tag`.
- `lite_batch --resume` reruns tasks that failed on the model API (billing, auth, rate limit, network: `API/network operation failed`) instead of keeping them as results; model-side errors stay. Used once when the DeepSeek balance ran out mid-run.

### Added
- `repeat_report --vs-tag`: compares each configuration with earlier runs of another agent version.
- `scripts/setup_eval_server.sh`: rerunnable one-shot setup of a fresh CPU evaluation server.

## Python syntax check after apply (2026-11-22)

### Added
- `apply_candidate` parses every changed `.py` file with `ast` after `git apply` (nothing is imported or executed). If a file that parsed at the base commit no longer parses, the candidate fails as `syntax_invalid` / `python_syntax_error` with file and line, is not exported, and follows the normal failed-attempt path (P-C-R: Reviewer stage `syntax` -> Coder retry; single agent: rejected submission). New files and files already unparsable at the base commit are not blocked. Manifests list `harness_checks`.

## Execution feedback (RQ2) and a redesigned web app (2026-11-22)

### Added
- `patchloop_task2/test_exec.py`: the repository's EXISTING tests run in a Docker sandbox (no network, all capabilities dropped, no new privileges, memory/CPU/pid limits, timeout that kills the container). SWE-bench tasks use their prebuilt evaluation image (patch applied inside a throw-away container); local repositories use `PATCHLOOP_TEST_IMAGE` with the worktree mounted read-only. Hidden `test_patch` / FAIL_TO_PASS tests are never used.
- `run_tests(test_path)` agent tool (Planner and single agent; tracked test files only, at most 3 runs per task, at the base commit) and a harness regression check after every applied candidate: tests that passed before and fail with the patch go back to the agent (P-C-R: Reviewer -> Coder retry; single agent: replacement submission). If the replacement does not apply, the earlier applicable candidate is kept.
- `lite_batch --exec-feedback`, `EXEC_AGENTS="pcr single"` in `run_final_deepseek.sh` (batches `*-pcr-exec`, `*-single-exec`), RQ2 pairs in `final_report`, manifests record `exec_feedback`.
- Web app: "Run existing tests" switch (states when Docker or a test image is unavailable), test results in the timeline, and a redesigned page (progress steps, run statistics, readable diff, light and dark themes).

## Two more agent tools: find_definition and list_directory (2026-11-22)

### Added
- `find_definition(name)`: locates Python classes, functions and methods by name (qualified name, kind, line span, signature) with `ast` over tracked files; nothing is imported or executed. `list_directory(relative_path)`: tracked sub-directories (with file counts) and files under a directory.
- Both are offered to the Planner and the single agent alike (RQ3 parity), validated like the existing tools (`TOOL_ARGUMENTS`), shown in the web timeline, and recorded in every batch manifest (`agent_tools`). `final_report` treats `agent_tools` as a studied variable; batches without the field are the earlier 2-tool agent.

### Changed
- `find_definition` counts as localization evidence for the Planner like `search_repo`. Final experiments are rerun with the 4-tool agent; the earlier 2-tool runs are kept as a tool ablation.

## Final experiment results recorded (2026-11-21)

### Added
- `experiments/repeat_report.py`: combines repeated runs of the final experiment (one tag per run): per-config resolved per run, mean and range; task-level paired comparisons (sign test over tasks, task bootstrap CI) so repeated runs of a task are not counted as independent.

### Changed
- README section 5 now holds the final results over 3 runs (official harness, 23 Lite dev tasks): mean resolution none 46.4%, single 42.0%, low 44.9%, high 34.8%, max 40.6%. Higher reasoning effort did not improve resolution; RQ3 shows no significant difference. Run 1 alone (high 6/23) overstated the high-effort drop.

## Final experiment on DeepSeek Flash; RQ1 becomes reasoning effort (2026-11-21)

### Added
- DeepSeek reasoning effort (`DEEPSEEK_REASONING_EFFORT` / `lite_batch --reasoning-effort`: none, low, high, max). `none` keeps thinking disabled (previous behavior, still the default). With thinking on, answer caps and the answer-token budget are unchanged; each call gets extra `max_tokens` room for hidden reasoning, and reasoning tokens are recorded per call/task (`reasoning_tokens`) and capped per task (`REASONING_TOKEN_BUDGET_EXHAUSTED`). An answer longer than the stage cap counts as truncated, exactly as without thinking.
- `experiments/final_report.py`: per-configuration table and paired comparisons (RQ1 effort pairs, RQ3 P-C-R vs single, DeepSeek vs Qwen-7B), optional restriction to gold-resolvable tasks, comparability warnings for settings that differ inside a pair.
- `scripts/run_final_deepseek.sh`: end-to-end, resumable final experiment (preflight, generation, official evaluation, re-evaluation of the Qwen-7B batches on the repaired images with the old verdicts kept, report).
- `docs/qwen7b-limits.md`: the evidence that the 7B model cannot carry the system, and how RQ1 continues the proposal.

### Changed
- `lite_batch` manifests record `reasoning_effort`, `reasoning_tokens_per_call` and `reasoning_budget_per_task`; summaries add `reasoning_tokens`.
- DeepSeek request timeout may be up to 900 s (default 120 s for none, 600/600/900 s for low/high/max).
- Per-call reasoning room raised from 8K/24K/48K to DeepSeek's default thinking-mode `max_tokens` (64K for low/high, 128K for max); per-task reasoning budgets 400k/600k/1.2M. The first live run with the smaller room cut off the reasoning of some Coder calls (empty answers), which biased RQ1 against higher effort. Such calls are now reported as `REASONING_EXHAUSTED_CALL`.
- DeepSeek batch runs are labelled `deepseek-...` instead of `qwen-...` in `run_status.json`.

### Verified and not verified
- Offline tests only (scripted fake clients) plus a dry run of the script with simulated batches. A live single-task check (high effort) confirmed that `completion_tokens` includes `reasoning_tokens` and that `max_tokens` covers both.

## Alibaba Cloud server and local official evaluation (2026-11-20)

### Added
- `docs/aliyun-runbook.md`: a CPU-only Alibaba Cloud VM (Hong Kong region, x86_64, Docker) runs only the official harness; AutoDL keeps inference and QLoRA training. Includes a gold-patch evaluator self-check and the AutoDL → Alibaba Cloud transfer steps.
- `experiments/official_eval.py`: evaluates a whole `lite_batch` directory with pinned `swebench==4.1.0` (prebuilt `swebench/sweb.eval.*` images, separate venv) and writes `official_eval.json` over the full task list (unpredicted tasks count as not resolved; harness errors mark the run incomplete).
- `experiments/paired_compare.py`: paired table, exact McNemar p-value and seeded bootstrap CI for two evaluated batches.
- `requirements-swebench-eval.txt`.

### Fixed
- `lite_batch --workers N`: on Ctrl+C the batch now waits for in-flight tasks to record their results before exiting. Previously a still-running task could append to `results.jsonl` after the interrupt, racing a later `--resume` (flaky test, ~25%).

### Verified and not verified
- Offline tests only (122 pass, 1 skipped). Prebuilt images for all 23 Lite dev tasks were confirmed to exist on Docker Hub; nothing has run on Alibaba Cloud yet.

## Small Qwen live integration and official SWE-bench result (2026-11-15)

### Added
- Qwen/Qwen2.5-Coder-0.5B-Instruct as the default small-model vLLM backend, with Qwen/Qwen3-0.6B as an opt-in small-model comparison.
- Live model preflight, real model Git/Docker repair smoke, real full-dev prediction, bounded prompt history and strict output budgets.
- PATCHLOOP_MODEL_BACKEND=qwen to route the original CodeNexus Demo and Task 1-3 shared OpenAI client to local vLLM while preserving the default provider behavior.
- Reproducible GPU server/client setup scripts, environment example, docs and offline Qwen model-contract tests.
- Scoped historical sqlfluff dependency fix in pinned official SWE-bench 3.0.0 evaluator; strict Resolved/Unresolved/Infrastructure Error classification.
- GitHub Actions cross-platform and real Docker scripted-model tests, plus a manually triggered official evaluation job.

### Verified and not verified
- Actual GitHub CI run 43713323015: Windows/Linux full regression, real Git+Docker scripted-Qwen smoke, actual SWE-bench dev checkout and evaluator job all completed successfully.
- Same run: pinned official SWE-bench evaluated one SAVED **DeepSeek** model prediction: 1 completed instance, 0 environment errors, **Unresolved**. The environment-only types-pkg_resources -> types-setuptools override is disclosed and is NOT pristine evaluation.
- The Qwen small model itself has **NOT YET been run on the user's GPU server**; CI fake replies do NOT establish live Qwen quality.
- Do not report an official Qwen resolution score until actual inference and evaluation on the server complete.

## Qwen and real SWE-bench dev integration — 2026-11-15

### Added
- Explicit Qwen2.5-Coder-7B-Instruct endpoint configuration and live /models + chat preflight.
- Leakage-safe SWE-bench full dev adapter with only issue/repo/base_commit/instance_id exposed to agents.
- CLI for historical Git checkout, read-only inspection, live Qwen single-patch inference, and official predictions export.
- Cross-platform unit tests, real dev issue checkout CI smoke, `.env.qwen.example` and setup documentation.

### Validation and limitations
- Real `sqlfluff__sqlfluff-4764` full dev Issue and exact Git checkout/search verified in GitHub Actions without model inference.
- Live Qwen 7B inference requires a GPU-hosted vLLM server and has not been run in GitHub CI.
- Official SWE-bench resolution, QLoRA and held-out Lite test evaluations remain pending.

## Task 3 — execution-grounded repair and retries (2026-11-15)

### Added
- Isolated Docker test runner with network disabled, read-only mounted worktree, non-root execution and resource/timeout limits.
- Reviewer JSON diagnoses and a bounded Coder revision loop (max 3 independent candidates).
- Structured per-attempt statuses, JSONL trace, internal-success-only diff export and operator-controlled CLI.
- Real Docker smoke with a deliberately failing first candidate, Reviewer correction and passing second candidate.
- Offline unit tests and cross-platform CI regression plus Ubuntu Docker smoke.

### Compatibility and limits
- Original CodeNexus routes, Task 1 Planner, Task 2 Coder/patch CLI and output schemas remain accessible.
- Internal tests passed does not imply SWE-bench resolved; QLoRA and official evaluation are not implemented.
- GitHub Actions run uses scripted model responses; live LLM repair quality is not yet verified.
## Task 2 integration — 2026-11-15

### Added
- Controlled Coder bridge consuming Task 1 suspected_files and read_file evidence.
- Unified diff validator, tracked-file whitelist and detached temporary Git worktree patch application.
- repair.py CLI and docs/task2.md; retained the original Flask Demo and Task 1 entry points.
- tests/test_task2.py: 7 offline tests with real temporary Git repos and deterministic model outputs.

### Limits / validation
- Task 2's standalone integration suite ran locally: 7 tests passed.
- Full combined repository regression and live LLM execution are not yet verified.
- A successful git apply does not establish functional repair; Docker tests/Reviewer/SWE-bench remain future work.

## Unreleased — 2026-11-15

### Changed
- Converted both web pages to English and requested English generated descriptions and repair plans.
- Changed `test_and_improve_code(code, prompt)` to return a report string instead of printing it. The web route uses the return value; the CLI pipeline prints it.
- Removed global stdout reassignment from the web request handler.
- Removed unused imports, obsolete comments, duplicate directory creation and the unused `utils/log_utils.py` module.
- Removed duplicate credential validation and the redundant file-size precheck; SDK credential validation and bounded-read limits remain.
- Removed the silent zero-score fallback when model scoring returns invalid JSON; parsing errors now propagate.
- Simplified UTF-8 code saving with `pathlib` and fixed recursion detection counting a function's own definition as recursion.
- Excluded runtime logs and local environment variants from Git, while retaining `.env.example`.
- Added contributor instructions and a code review record; prepared the project for the public `7068` repository.

### Compatibility
- Original Flask startup commands, `/`, `/localize`, model configuration and Task 1 plan format remain available.
- Callers of `test_and_improve_code` must now use its returned string; external callers relying on printed output should wrap the call in `print(...)`.
- Path isolation, evidence validation, repository commit checks and resource budgets remain required by Task 1.

### Validation
- Unit tests cover English pages, report rendering, invalid score JSON, recursion detection, UTF-8 saving, existing generation and repository localization.
- Actual run: 21 tests, 20 passed and 1 skipped because Windows did not permit creating a symlink. The Windows junction test passed.
- The offline localization demo, `pip check`, syntax compilation and HTTP checks of both English pages passed.
- Real LLM and SWE-bench evaluation remain unverified; offline actions are explicitly scripted.

## Task 1 baseline — 2026-11-15

### Added
- `utils/repo_tools.py`: bounded literal search, numbered read-only file access, repository/commit checks and tracked-file validation.
- `prompt_agent.plan_repair`: bounded JSON action loop, tool evidence and validated repair plans.
- `pipeline_agent.run_localization`, `localize.py`, `/localize` and `demo_localization.py`.
- Regression and security tests plus `docs/task1.md` and an offline demonstration record.

### Preserved
- CodeNexus prompt refinement, algorithm classification, code generation, static analysis and model review.
- Shared API client and configurable compatible backend; no mandatory model migration.

### Scope
- No patch application, repository test execution, Reviewer retry system, QLoRA training or SWE-bench evaluation was implemented.

## Environment baseline — 2026-11-15

- Created a Python 3.11 virtual environment and recorded direct and locked dependencies.
- Moved API credentials and endpoint configuration out of source code into `.env`.
- Removed the hardcoded proxy and corrected visualization CSV paths.

## Entry template

For future changes, record: **what changed**, **why**, **affected interfaces**,
**verification command/results**, and **known limitations**. Distinguish offline
tests from real model calls; never record expected results as actual results.
