# Project-related AI prompts

Prompts we gave to AI assistants while building PatchLoop, as required by the COMP7608B guideline
(AI responses are not required and are not included). See [../AI_DECLARATION.md](../AI_DECLARATION.md)
for the declaration.

| File | Tool / model | Period (UTC) | Prompts | Main topics |
|---|---|---|---|---|
| [01-claude-code-2026-11-16_to_11-20.md](01-claude-code-2026-11-16_to_11-20.md) | Claude Code, Claude Opus 5.5 | 2026-11-16 – 11-20 | 71 | Qwen/vLLM server setup, first SWE-bench dev runs, Lite batch runner, progress vs proposal, merging branches, README, fine-tuning plan, repository mirroring |
| [02-claude-code-2026-11-20_to_11-21.md](02-claude-code-2026-11-20_to_11-21.md) | Claude Code, Claude Opus 5.5 | 2026-11-20 – 11-21 | 62 | cloud server choice and runbook, Qwen-7B pilot runs, Planner and SEARCH-block fixes, retrieval, guideline check, web app entry point, switch to the DeepSeek API, RQ1 as reasoning effort |
| [03-claude-code-2026-11-21_to_11-22.md](03-claude-code-2026-11-21_to_11-22.md) | Claude Code, Claude Opus 5.5 | 2026-11-21 – 11-22 | 81 | final DeepSeek experiments and repeats, guideline gap check, new tools and `run_tests`, execution feedback, web UI redesign, pasted-code demo, repository clean-up, CI fixes, review follow-ups, this declaration |

How these files were made: the prompts were exported from the Claude Code session logs, ordered by
time, de-duplicated (the desktop app stores a copy of the conversation per branch of a session), and
translated from Chinese into English. Terminal output that was pasted only for diagnosis is replaced
by `[pasted terminal output omitted]` with a short note of what it showed. Redacted: API keys, server
host names and IP addresses, local user and folder names, e-mail addresses.
