# Contributing

Use Python 3.11 and Git (ripgrep optional). Create the client environment and `.env` as in the
README (section 3); never commit `.env` or any key.

## Layout

- `patchloop_app/`: the web app (entry point `python -m patchloop_app.web`), sessions and stop
  rules, sample runner.
- `prompt_agent.py`, `pipeline_agent.py`: Planner and its handoff; `utils/repo_tools.py`: read-only
  agent tools; `utils/retrieval.py`: candidate-file retrieval.
- `patchloop_task2/`: model backends, Coder, edit blocks, single agent, Reviewer, patch validation
  and isolated apply (`workspace.py`), execution feedback (`test_exec.py`), the earlier Task 3
  execution loop (`loop.py`, `execution.py`).
- `experiments/`: batch runner, official evaluation, reports and statistics.
- `scripts/`: server setup, final experiment, image repair, result export; `samples/`: sample
  requests; `final_results/`: exported results and traces; `tests/`: offline tests.

## Checks before a pull request

```bash
python -m unittest discover -s tests
```

Tests use scripted model replies (labelled in each file) and real temporary Git repositories; they
never call a model API. Record behaviour changes in `CHANGELOG.md` in the same commit.
