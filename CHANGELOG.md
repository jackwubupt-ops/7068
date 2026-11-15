# Changelog

Record changes here so teammates can understand behavior and interface changes.
Add new entries under **Unreleased** in the same commit as the implementation.
These are development milestones, not published GitHub releases.

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
