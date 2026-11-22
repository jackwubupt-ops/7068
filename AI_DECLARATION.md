# AI-use declaration

COMP7608B final project · Group **[GROUP NUMBER]** · PatchLoop

> Fill in every `[TO FILL]` before submission. The guideline asks for: which AI tools/models were
> used, what they helped with, the project-related prompts (responses not required), redaction of
> credentials and personal information, and a note on any missing prompt records.

## 1. Tools and models used for development

| Tool / model | Used by | What it helped with |
|---|---|---|
| Claude Code (Anthropic, Claude Opus 5.5) | [TO FILL: member(s)] | switching the final experiment to the DeepSeek API; RQ1 reasoning-effort support; `find_definition`, `list_directory` and `run_tests` tools; execution feedback (Docker sandbox, regression check); syntax check; report and statistics scripts (`final_report.py`, `repeat_report.py`); server setup and export scripts; web UI redesign; offline tests; README, runbook and CHANGELOG text; step-by-step guidance for running the experiments on the server |
| [TO FILL: other tools, e.g. ChatGPT / Copilot / Codex] | [TO FILL] | [TO FILL] |

Every change was reviewed and run by the team: the offline test suite (209 tests), the official
SWE-bench harness for all reported results, and the recorded sample traces in
`final_results/samples/`. We are responsible for the correctness of the code and the report and can
explain all AI-assisted parts.

## 2. Models that are part of the system (not development assistance)

The agent itself calls a language model: DeepSeek `deepseek-flash` through the DeepSeek API (final
experiments and the web app) or Qwen2.5-Coder-7B-Instruct on local vLLM (baseline). Their prompts are
in the source code: `prompt_agent.py` (Planner), `patchloop_task2/edit_blocks.py` and `coder.py`
(Coder), `patchloop_task2/reviewer.py` (Reviewer), `patchloop_task2/single_agent.py` (single agent).

## 3. Project-related prompts

The prompts we gave to the AI tools are in `ai_prompts/` (one file per tool or session, prompts
only, in chronological order). Redacted: API keys, server addresses and IDs, e-mail addresses and
names other than the members'.

[TO FILL: list the files, e.g. `ai_prompts/claude-code-2026-11-21.md`]

## 4. Missing records

[TO FILL: e.g. "Prompts from sessions before 2026-11-XX were not saved; they covered ..." or "None."]
