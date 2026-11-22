# Planning, requirements and repository

Progress against the proposal and the course guideline, README and TODO, branch merges and pull requests, CI fixes, repository clean-up, the report guide, the external review follow-up, and this AI declaration.

- Tool / model: Claude Code (Anthropic), Claude Opus 5.5
- Original language: mostly Chinese; translated to English. Prompts only; AI responses are not included.
- Time order within this file (dates and times in UTC, 2026); the full set spans 2026-11-16 to 11-22.
- Redacted: API keys, server host names and IP addresses, local user and folder names, e-mail addresses.
- `[pasted terminal output omitted]` marks command output pasted only for diagnosis; "(app button)"
  marks a prompt sent by a button in the Claude desktop app rather than typed.

| Time (UTC) | Prompt |
|---|---|
| 11-16 14:28 | [attached: the project proposal PDF] This is my proposal; follow it for the next steps. |
| 11-18 16:50 | Compared with our proposal, what have we completed? What are the difficulties? What problems urgently need solving? |
| 11-18 16:52 | Do you have any ideas for solving them? |
| 11-19 12:21 | Summarize this into an md file. |
| 11-19 13:50 | So the biggest problem now is that we cannot run the benchmark, and the rest of the multi-agent tooling is already done, right? |
| 11-19 13:52 | How do we solve it? Give me a direction that is feasible and lets us keep making progress. |
| 11-19 14:00 | Let's start; let's make some progress tonight. |
| 11-19 14:22 | Keep writing. |
| 11-20 04:29 | Keep writing. |
| 11-20 04:34 | Merge everything into a single main branch, then give me the complete testing procedure. |
| 11-20 04:39 | While merging, rewrite the README as a complete main README. |
| 11-20 04:42 | Update the home page as well. |
| 11-20 04:43 | So where are we now? |
| 11-20 04:52 | Write a todo.md and push it to GitHub, focused on the main upcoming tasks. |
| 11-20 04:53 | Merge #15. |
| 11-20 15:29 | Merge #16. |
| 11-20 17:04 | Merge #18. |
| 11-20 17:11 | Merge #19. |
| 11-20 17:18 | Merge #20. |
| 11-20 18:08 | Merge #21. |
| 11-20 18:35 | Merge #22. |
| 11-20 18:43 | Merge #23. |
| 11-20 19:30 | [pasted the full text of the COMP7608B Final Project Student Guideline] Let's pause the project and look at these submission requirements. Do I meet them? Do they match the requirements in the proposal? |
| 11-20 19:41 | Merge #24. |
| 11-20 19:46 | Merge #25. |
| 11-20 19:56 | How many of our core problems are solved now, and how many are not? |
| 11-20 20:10 | Merge #26. I also have a question: the instructor has objective requirements and expects continuity with the proposal. Is it acceptable to replace the underlying model with the DeepSeek API? |
| 11-20 20:21 | Merge both. |
| 11-21 05:35 | Summarize everything that is in my repository; I am about to make a fairly big change of direction. |
| 11-21 05:53 | Push and open PR. (app button) |
| 11-21 15:15 | [attached: the course final-project guideline PDF and our proposal PDF] Against this guideline and the final content, what do we still have left to do? |
| 11-22 03:05 | So do you think further optimization is needed? Does it now meet the instructor's hard requirements? How does it perform? |
| 11-22 03:08 | [pasted terminal output omitted] |
| 11-22 03:10 | [pasted terminal output omitted] |
| 11-22 03:18 | Tidy up the repository: delete unrelated content, check against the instructor's requirements and keep what matches them. |
| 11-22 03:25 | CI is failing on the PR. Find out why, fix it, and push. (app button) |
| 11-22 03:27 | [pasted terminal output: `gh: command not found`] |
| 11-22 03:29 | Authorized; push it. |
| 11-22 03:30 | Check against the instructor's guideline: what else needs changing? |
| 11-22 03:32 | OK, change these first. |
| 11-22 05:17 | After fixing, test for bugs; if there are none, tidy up the code, then generate a report-guide md document and send it straight to me; don't upload it to GitHub. |
| 11-22 05:18 | One more thing: why are my GitHub workflows still failing? Review it. |
| 11-22 06:54 | Merge this PR into main. |
| 11-22 15:48 | [attached: external review report deep-research-report.md] Based on this deep-research report, analyse and judge what we can still improve. |
| 11-22 15:51 | Skip item 5 for now; do the others and merge to main when done. |
| 11-22 16:05 | Fill in the AI declaration in the repository, and remember to translate all the AI prompts into English. |
