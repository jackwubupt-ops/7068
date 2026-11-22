# Web app and demo

The interactive web entry point, running it on a Windows machine, the UI redesign, free-form code for the live demo, and UI fixes.

- Tool / model: Claude Code (Anthropic), Claude Opus 5.5
- Original language: mostly Chinese; translated to English. Prompts only; AI responses are not included.
- Time order within this file (dates and times in UTC, 2026); the full set spans 2026-11-16 to 11-22.
- Redacted: API keys, server host names and IP addresses, local user and folder names, e-mail addresses.
- `[pasted terminal output omitted]` marks command output pasted only for diagnosis; "(app button)"
  marks a prompt sent by a button in the Claude desktop app rather than typed.

| Time (UTC) | Prompt |
|---|---|
| 11-20 19:33 | Only build the web page; it's simpler to interact with. Start with the interactive entry point. |
| 11-21 15:23 | The instructor's guideline asks for an agent application that runs on its own, right? Have I not built that yet? And the agent so far has only been tested on paper, so it doesn't meet the instructor's requirement yet? In the end the instructor may just type arbitrary natural-language requests. |
| 11-21 15:25 | Does this have to be hosted on the server? |
| 11-21 15:26 | Walk me through the whole process on my other Windows machine. |
| 11-21 15:45 | Next step. |
| 11-22 03:40 | First beautify the front-end interaction; it looks bad right now. Then, after that, walk me through item 8, which we do ourselves. |
| 11-22 03:50 | [pasted test output: 209 tests, 1 failure, 1 skipped] |
| 11-22 03:52 | [pasted terminal output omitted] |
| 11-22 03:56 | So during the demo, if the instructor wants to change some code, written on the spot, what do we do? |
| 11-22 04:55 | [attached screenshot of the old page] This page doesn't look good! The logic is unclear and there is no sense of design. Redesign it; also note this screenshot is the old version of the page, so build on the new version. |
| 11-22 05:07 | There's no difference? |
| 11-22 05:07 | [pasted terminal output omitted] |
| 11-22 05:15 | Fix two things in the UI: after a request is created, reset everything in "New request" to the defaults; and delete the words "bug report → reviewed, Git-applicable patch". |
