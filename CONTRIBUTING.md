# Contributing to PatchLoop

## Setup

Use Python 3.11, Git and optionally ripgrep. Copy `.env.example` to `.env` and
fill in your own credentials. Never commit keys or `.env` files.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m flask --app app run --debug
```

## Project map

- `app.py`, `templates/`: English web pages for generation and localization.
- `config.py`: shared API client, endpoint and model configuration.
- `prompt_agent.py`: original refinement and Task 1 Planner.
- `code_agent.py`: original standalone code generator.
- `test_agent.py`: syntax validation and LLM review; returns a report string.
- `evaluator.py`: heuristic code metrics, not correctness guarantees.
- `utils/repo_tools.py`: read-only repository access and commit checks.
- `pipeline_agent.py`: callable generation and localization entry points.
- `localize.py`: real-model localization CLI.
- `demo_localization.py`: temporary-repository demo; `--offline` scripts model actions.
- `tests/test_task1.py`: offline regression and repository boundary tests.

## Before opening a pull request

1. Keep changes incremental and preserve the original demo.
2. Add behavior tests for changed contracts and run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe demo_localization.py --offline
.\.venv\Scripts\python.exe -m pip check
```

3. Update `CHANGELOG.md` under Unreleased, including interface changes and actual validation.
4. Keep web text and model-facing display instructions in English.
5. Review `git diff --cached` for credentials, generated logs and unrelated files.

## Task 2 handoff

`run_localization(issue, repo_root, base_commit)` returns a dictionary containing
candidate files, referenced line ranges, real tool evidence, a root-cause
hypothesis and planned changes. `execution_verified` is always false in Task 1.
Build patch application and execution in a controlled workspace rather than
changing repository files through the read-only tools.

Target repositories must be clean and checked out at the supplied commit. Do
not modify them during localization. The tools are bounded local inspection,
not a sandbox for concurrently hostile filesystems or immutable Git snapshots.
