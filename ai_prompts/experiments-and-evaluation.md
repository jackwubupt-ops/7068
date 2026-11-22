# Experiments and evaluation

The batch runner, the official evaluation, the fine-tuning plan replaced by the reasoning-effort RQ1, repeated runs, results and traces.

- Tool / model: Claude Code (Anthropic), Claude Opus 5.5
- Original language: mostly Chinese; translated to English. Prompts only; AI responses are not included.
- Only prompts that set a direction or asked for a change are listed; routine messages (pasted logs,
  "next step", "has it finished?", language choice, single PR-merge confirmations) are left out.
- Time order within this file (UTC, 2026). Redacted: keys, hosts/IPs, user and folder names, e-mails.

| Time (UTC) | Prompt |
|---|---|
| 11-16 15:56 | Write the Lite batch runner. |
| 11-17 06:28 | So do you think we must run the official evaluation? |
| 11-20 11:35 | How should we demonstrate the fine-tuned model results? |
| 11-20 11:37 | So how do we do the LoRA fine-tuning? |
| 11-20 11:53 | So what is the training dataset? And is there no other solution for RQ2? |
| 11-20 11:58 | Maybe let B handle all the testing. I need to sort out the process: fine-tune first and then evaluate, or evaluate first and then fine-tune? |
| 11-20 17:46 | "Another reminder: the smoke results are already valuable; package them per runbook stage 12 and download a backup from Workbench." Package one first. |
| 11-21 05:44 | Can RQ1 be changed to compare different reasoning-effort levels? That would still show continuity with the proposal, which planned to show improvability through fine-tuning. |
| 11-21 12:10 | Let's continue to round two. |
| 11-21 13:50 | Quoting the limitations you listed ("only 23 tasks; each configuration ran once; thinking mode does not use temperature, so results are random; the first round was discarded because the reasoning budget was too small, as recorded in the CHANGELOG"): does this need adjusting, for example by running a fuller evaluation? |
| 11-21 13:52 | Do option A first (repeat twice). |
| 11-22 00:46 | Then merge it and run the full experiment on the server. |
| 11-22 03:01 | Generate the traces and package everything. |
