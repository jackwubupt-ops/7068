# Planning, requirements and repository

Progress against the proposal and the course guideline, README, merging, CI, repository clean-up, the report guide, the external review follow-up and this AI declaration.

- Tool / model: Claude Code (Anthropic), Claude Opus 5.5
- Original language: mostly Chinese; translated to English. Prompts only; AI responses are not included.
- Only prompts that set a direction or asked for a change are listed; routine messages (pasted logs,
  "next step", "has it finished?", language choice, single PR-merge confirmations) are left out.
- Time order within this file (UTC, 2026). Redacted: keys, hosts/IPs, user and folder names, e-mails.

| Time (UTC) | Prompt |
|---|---|
| 11-16 14:28 | [attached: the project proposal PDF] This is my proposal; follow it for the next steps. |
| 11-18 16:50 | Compared with our proposal, what have we completed? What are the difficulties? What problems urgently need solving? |
| 11-18 16:52 | Do you have any ideas for solving them? |
| 11-19 13:50 | So the biggest problem now is that we cannot run the benchmark, and the rest of the multi-agent tooling is already done, right? |
| 11-19 13:52 | How do we solve it? Give me a direction that is feasible and lets us keep making progress. |
| 11-20 04:34 | Merge everything into a single main branch, then give me the complete testing procedure. |
| 11-20 04:39 | While merging, rewrite the README as a complete main README. |
| 11-20 04:42 | Update the home page as well. |
| 11-20 04:52 | Write a todo.md and push it to GitHub, focused on the main upcoming tasks. |
| 11-20 19:30 | Let's pause the project and look at these submission requirements. Do I meet them? Do they match the requirements in the proposal? |
| 11-20 19:56 | How many of our core problems are solved now, and how many are not? |
| 11-20 20:10 | The instructor has objective requirements and expects continuity with the proposal. Is it acceptable to replace the underlying model with the DeepSeek API? |
| 11-21 05:35 | Summarize everything that is in my repository; I am about to make a fairly big change of direction. |
| 11-21 15:15 | [attached: the course final-project guideline PDF and our proposal PDF] Against this guideline and the final content, what do we still have left to do? |
| 11-22 03:05 | So do you think further optimization is needed? Does it now meet the instructor's hard requirements? How does it perform? |
| 11-22 03:18 | Tidy up the repository: delete unrelated content, check against the instructor's requirements and keep what matches them. |
| 11-22 03:30 | Check against the instructor's guideline: what else needs changing? |
| 11-22 05:17 | After fixing, test for bugs; if there are none, tidy up the code, then generate a report-guide md document and send it straight to me; don't upload it to GitHub. |
| 11-22 05:18 | One more thing: why are my GitHub workflows still failing? Review it. |
| 11-22 15:48 | [attached: external review report deep-research-report.md] Based on this deep-research report, analyse and judge what we can still improve. |
| 11-22 15:51 | Skip item 5 for now; do the others and merge to main when done. |
| 11-22 16:05 | Fill in the AI declaration in the repository, and remember to translate all the AI prompts into English. |
| 11-22 16:22 | Do not use time in the file names; group the prompt files by function. ChatGPT also wrote the proposal and did the research, and the other members used ChatGPT too. |
| 11-22 16:35 | Make it more concise: leave out prompts that do not decide a concrete direction. |
