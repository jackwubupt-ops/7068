# Agent design and tools

Planner and Coder fixes, tolerant SEARCH-block matching, file retrieval, the switch to the DeepSeek API, new agent tools, execution feedback, LangGraph/LangChain considerations.

- Tool / model: Claude Code (Anthropic), Claude Opus 5.5
- Original language: mostly Chinese; translated to English. Prompts only; AI responses are not included.
- Only prompts that set a direction or asked for a change are listed; routine messages (pasted logs,
  "next step", "has it finished?", language choice, single PR-merge confirmations) are left out.
- Time order within this file (UTC, 2026). Redacted: keys, hosts/IPs, user and folder names, e-mails.

| Time (UTC) | Prompt |
|---|---|
| 11-20 18:01 | Fix the Planner first. |
| 11-20 18:05 | Also do the tolerant matching for SEARCH blocks at the same time. |
| 11-20 18:31 | What other directions for improvement do you see? No rush to continue experiments; right now I just need better results quickly. |
| 11-20 18:33 | Start the diagnosis. |
| 11-20 18:37 | Do the retrieval first; let's start. |
| 11-20 19:47 | Can we connect the DeepSeek API? The accuracy of this 7B model is ridiculously low; it can't really serve as a reasonable agent system. |
| 11-21 15:17 | Quoting your item ④ "LangGraph and Pydantic are not used; we use our own JSON protocol and dataclasses": is adding them a lot of trouble? |
| 11-21 15:50 | Should we add two more useful tools? |
| 11-21 15:51 | Let's add them after all; I'll finish running everything today. |
| 11-21 15:59 | Where is my run_tests? Also beautify the web front end while you're at it; it's too ugly. |
| 11-21 16:05 | If possible, while adding the above, evaluate what other features could be added to the whole agent system, e.g. LangGraph/LangChain, a harness, or more practical tools. Besides assessing feasibility, if there is anything you think we must try, open a new PR for it, separate from the current PR that adds these tools. |
| 11-22 03:15 | So did the newly added tools make any difference? |
