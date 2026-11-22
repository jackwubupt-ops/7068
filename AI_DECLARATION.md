# AI-use declaration

COMP7608B final project · Group **[GROUP NUMBER]** · PatchLoop

(The group number and member names are filled in the submitted ZIP and report only; this public
repository keeps them out.)

## 1. Tools and models used for development

| Tool / model | What it helped with |
|---|---|
| **Claude Code** (Anthropic), model Claude Opus 5.5 | Server setup and runbooks (vLLM/Qwen GPU servers, then CPU servers for the DeepSeek runs, Docker and the official SWE-bench harness); diagnosing pasted server errors; the Lite batch runner and resume logic; Planner fixes and tolerant SEARCH-block matching; file retrieval; switching the final experiment to the DeepSeek API; RQ1 reasoning-effort support; the `find_definition`, `list_directory` and `run_tests` tools; execution feedback (Docker sandbox, existing-test regression check); the syntax check; statistics and report scripts (`final_report.py`, `repeat_report.py`); server setup and export scripts; the web app (sessions, follow-ups, pasted code, uncommitted-edit snapshot, UI redesign, unsafe-candidate outcome, queue cancel); offline tests; CI fixes; README, CHANGELOG and runbook text; checking the project against the course guideline and the proposal. |
| **ChatGPT** (OpenAI), Deep Research mode | One external review report of the repository at commit `27e8b68` against the course guideline. We used its findings as a checklist; the follow-up changes (unsafe-candidate outcome, queue cancel, commit comparability check, follow-up wording) were made with Claude Code and are in the CHANGELOG. |

How we used them: we described the goal or pasted the error, the assistant proposed or wrote the
change, and we reviewed, ran and merged it through pull requests. Every reported number comes from
our own runs: the official SWE-bench harness for all resolution results, the offline test suite
(214 tests, run on Ubuntu and Windows in CI) for the code, and the recorded traces in
`final_results/samples/`. We are responsible for the correctness of the code and the report and can
explain all AI-assisted parts.

## 2. Models that are part of the system (not development assistance)

The agent itself calls a language model: DeepSeek `deepseek-flash` through the DeepSeek API (final
experiments and the web app) or Qwen2.5-Coder-7B-Instruct on local vLLM (baseline). Their prompts are
in the source code: `prompt_agent.py` (Planner), `patchloop_task2/edit_blocks.py` and `coder.py`
(Coder), `patchloop_task2/reviewer.py` (Reviewer), `patchloop_task2/single_agent.py` (single agent).

## 3. Project-related prompts

All prompts are in [`ai_prompts/`](ai_prompts/README.md), translated into English, in time order,
prompts only:

| File | Tool | Period (UTC) | Prompts |
|---|---|---|---|
| `ai_prompts/01-claude-code-2026-11-16_to_11-20.md` | Claude Code | 2026-11-16 – 11-20 | 71 |
| `ai_prompts/02-claude-code-2026-11-20_to_11-21.md` | Claude Code | 2026-11-20 – 11-21 | 62 |
| `ai_prompts/03-claude-code-2026-11-21_to_11-22.md` | Claude Code | 2026-11-21 – 11-22 | 81 |

Redacted: API keys, server host names and IP addresses, local user and folder names, e-mail
addresses. Terminal output pasted only for diagnosis is replaced by a short placeholder.

## 4. Missing records

- **Before 2026-11-16:** prompts from the earlier work (the proposal stage and the initial
  repository built on 2026-11-15: localization demo, Planner/Coder/Reviewer integration, Docker test
  execution, first DeepSeek and Qwen pipelines) were not kept in the session logs we could export.
- **ChatGPT Deep Research:** the prompt for the external review report was not saved; it asked for a
  code review of the repository at `27e8b68` against the course guideline.
- **Pasted output:** long terminal logs pasted for diagnosis are omitted (they contained no
  instructions, and some contained server identifiers).
