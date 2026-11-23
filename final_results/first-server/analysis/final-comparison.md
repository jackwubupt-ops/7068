# PatchLoop final comparison (SWE-bench Lite dev, official harness)

## Per-configuration results

| Config | Backend | Model | Agent | Reasoning | Tasks | Applicable | Resolved | Rate | Harness errors | Prompt tok | Completion tok | of which reasoning | s/task |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ds-pcr | deepseek | deepseek-flash | pcr | none | 23 | 23 | 10 | 43.5% | 0 | 928,549 | 30,733 | 0 | 13.5 |
| ds-single | deepseek | deepseek-flash | single | none | 23 | 18 | 10 | 43.5% | 0 | 1,009,736 | 8,374 | 0 | 7.2 |
| ds-pcr-low | deepseek | deepseek-flash | pcr | low | 23 | 20 | 10 | 43.5% | 0 | 856,509 | 107,345 | 72,560 | 32.7 |
| ds-pcr-high | deepseek | deepseek-flash | pcr | high | 23 | 17 | 11 | 47.8% | 0 | 1,002,322 | 208,958 | 166,462 | 56.5 |
| ds-pcr-max | deepseek | deepseek-flash | pcr | max | 23 | 20 | 9 | 39.1% | 0 | 942,279 | 375,252 | 271,464 | 88.2 |
| qwen-pcr | qwen | Qwen/Qwen2.5-Coder-7B-Instruct | pcr | none | 23 | 14 | 0 | 0.0% | 0 | 1,037,441 | 26,948 | 0 | 53.8 |
| qwen-single | qwen | Qwen/Qwen2.5-Coder-7B-Instruct | single | none | 23 | 11 | 0 | 0.0% | 0 | 402,448 | 14,340 | 0 | 25.5 |

## Paired comparisons

| Comparison | A | B | Rate A | Rate B | A-B | both / only A / only B / neither | McNemar p | 95% CI (A-B) |
|---|---|---|---|---|---|---|---|---|
| RQ3: P-C-R vs single agent (DeepSeek) | ds-pcr | ds-single | 43.5% | 43.5% | 0.0% | 9 / 1 / 1 / 12 | 1.0000 | [-13.0%, 13.0%] |
| RQ1: reasoning low vs none (DeepSeek P-C-R) | ds-pcr-low | ds-pcr | 43.5% | 43.5% | 0.0% | 9 / 1 / 1 / 12 | 1.0000 | [-13.0%, 13.0%] |
| RQ1: reasoning high vs none (DeepSeek P-C-R) | ds-pcr-high | ds-pcr | 47.8% | 43.5% | 4.3% | 10 / 1 / 0 / 12 | 1.0000 | [0.0%, 13.0%] |
| RQ1: reasoning max vs none (DeepSeek P-C-R) | ds-pcr-max | ds-pcr | 39.1% | 43.5% | -4.3% | 8 / 1 / 2 / 12 | 1.0000 | [-17.4%, 8.7%] |
| RQ1: reasoning high vs low (DeepSeek P-C-R) | ds-pcr-high | ds-pcr-low | 47.8% | 43.5% | 4.3% | 10 / 1 / 0 / 12 | 1.0000 | [0.0%, 13.0%] |
| Model: DeepSeek vs Qwen-7B (P-C-R) | ds-pcr | qwen-pcr | 43.5% | 0.0% | 43.5% | 0 / 10 / 0 / 13 | 0.0020 | [26.1%, 65.2%] |
| Model: DeepSeek vs Qwen-7B (single agent) | ds-single | qwen-single | 43.5% | 0.0% | 43.5% | 0 / 10 / 0 / 13 | 0.0020 | [21.7%, 65.2%] |

## Comparability warnings

- none: every pair differs only in the studied variable

_resolved = official SWE-bench harness verdict; applicable = Git-applicable candidate only. Small task counts: treat p-values and CIs as indicative._
