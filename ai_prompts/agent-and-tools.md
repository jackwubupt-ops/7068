# Agent design and tools

Planner and Coder fixes, tolerant SEARCH-block matching, file retrieval, switching the model to the DeepSeek API, new agent tools (`find_definition`, `list_directory`, `run_tests`), execution feedback, and LangGraph/LangChain considerations.

- Tool / model: Claude Code (Anthropic), Claude Opus 5.5
- Original language: mostly Chinese; translated to English. Prompts only; AI responses are not included.
- Time order within this file (dates and times in UTC, 2026); the full set spans 2026-11-16 to 11-22.
- Redacted: API keys, server host names and IP addresses, local user and folder names, e-mail addresses.
- `[pasted terminal output omitted]` marks command output pasted only for diagnosis; "(app button)"
  marks a prompt sent by a button in the Claude desktop app rather than typed.

| Time (UTC) | Prompt |
|---|---|
| 11-20 17:08 | Change it according to option B. |
| 11-20 18:01 | Fix the Planner first. |
| 11-20 18:05 | Also do the tolerant matching for SEARCH blocks at the same time. |
| 11-20 18:31 | What other directions for improvement do you see? No rush to continue experiments; right now I just need better results quickly. |
| 11-20 18:33 | Start the diagnosis. |
| 11-20 18:37 | Do the retrieval first; let's start. |
| 11-20 19:47 | Can we connect the DeepSeek API? The accuracy of this 7B model is ridiculously low; it can't really serve as a reasonable agent system. |
| 11-20 20:13 | Then let's keep pushing the engineering forward. |
| 11-21 15:17 | Quoting your item ④ "LangGraph and Pydantic are not used; we use our own JSON protocol and dataclasses": is adding them a lot of trouble? |
| 11-21 15:49 | Did I not call any tools? |
| 11-21 15:50 | Should we add two more useful tools? |
| 11-21 15:51 | Let's add them after all; I'll finish running everything today. |
| 11-21 15:59 | Where is my run_tests? Also beautify the web front end while you're at it; it's too ugly. |
| 11-21 16:05 | If possible, while adding the above, evaluate what other features could be added to the whole agent system, e.g. LangGraph/LangChain, a harness, or more practical tools. Besides assessing feasibility, if there is anything you think we must try, open a new PR for it, separate from the current PR that adds these tools. |
| 11-22 00:45 | Does this count as a tool? |
| 11-22 00:46 | So it doesn't need an experiment to validate its feasibility? |
| 11-22 03:15 | So did the newly added tools make any difference? |
