# Project-related AI prompts

Prompts we gave to AI assistants while building PatchLoop, as required by the COMP7608B guideline
(AI responses are not required and are not included). See [../AI_DECLARATION.md](../AI_DECLARATION.md)
for the declaration. Files are grouped by what the prompts were about:

| File | Tool / model | Prompts | Covers |
|---|---|---|---|
| [environment-and-servers.md](environment-and-servers.md) | Claude Code, Claude Opus 5.5 | 75 | GPU/CPU servers, vLLM/Qwen, Docker, SWE-bench harness, mirrors, runbooks, setup errors |
| [agent-and-tools.md](agent-and-tools.md) | Claude Code, Claude Opus 5.5 | 17 | Planner/Coder fixes, SEARCH-block matching, retrieval, DeepSeek API, new tools, execution feedback |
| [experiments-and-evaluation.md](experiments-and-evaluation.md) | Claude Code, Claude Opus 5.5 | 63 | batch runner, pilot and final runs, official evaluation, fine-tuning plan → RQ1, repeats, results and traces |
| [web-app-and-demo.md](web-app-and-demo.md) | Claude Code, Claude Opus 5.5 | 13 | web entry point, Windows walkthrough, UI redesign, free-form code for the demo |
| [planning-requirements-and-repository.md](planning-requirements-and-repository.md) | Claude Code, Claude Opus 5.5 | 46 | proposal and guideline checks, README, merges and PRs, CI, clean-up, review follow-up, declaration |

ChatGPT (proposal writing, background research, one external code review, and use by other team
members) is declared in `AI_DECLARATION.md`; those prompt records were not saved (see its section 4).

How these files were made: the Claude Code prompts (2026-11-16 to 11-22) were exported from the
session logs, de-duplicated (the desktop app stores a copy of the conversation per branch of a
session), grouped by topic, kept in time order within each file, and translated from Chinese into
English. Terminal output pasted only for diagnosis is replaced by `[pasted terminal output omitted]`
with a short note of what it showed. Redacted: API keys, server host names and IP addresses, local
user and folder names, e-mail addresses.
