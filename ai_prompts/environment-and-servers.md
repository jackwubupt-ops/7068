# Environment and servers

Choosing and setting up servers (GPU for Qwen/vLLM, then CPU for the DeepSeek runs), Docker and the SWE-bench harness.

- Tool / model: Claude Code (Anthropic), Claude Opus 5.5
- Original language: mostly Chinese; translated to English. Prompts only; AI responses are not included.
- Only prompts that set a direction or asked for a change are listed; routine messages (pasted logs,
  "next step", "has it finished?", language choice, single PR-merge confirmations) are left out.
- Time order within this file (UTC, 2026). Redacted: keys, hosts/IPs, user and folder names, e-mails.

| Time (UTC) | Prompt |
|---|---|
| 11-16 13:53 | Try Qwen3-0.6B. |
| 11-16 14:37 | Connect the 7B model first. |
| 11-20 11:23 | It seems we can only run these tests by renting an Alibaba Cloud server. Push forward along this engineering path. |
| 11-20 15:38 | Are there other rental platforms? This one is too hard to use. |
| 11-20 15:43 | Switch to Alibaba Cloud Hong Kong and write me a new runbook. |
| 11-21 12:29 | What server configuration can we use now? Is it fine without a GPU? |
| 11-22 00:49 | No GPU needed. If we want it faster, what server should we rent? |
| 11-22 00:51 | Walk me through opening a new server again. This time I'll use 32 vCPU / 64 GiB. Update your test commands. |
