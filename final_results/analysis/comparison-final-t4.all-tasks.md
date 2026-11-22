# PatchLoop final comparison (SWE-bench Lite dev, official harness)

## Per-configuration results

| Config | Backend | Model | Agent | Reasoning | Tasks | Applicable | Resolved | Rate | Harness errors | Prompt tok | Completion tok | of which reasoning | s/task |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ds-pcr | deepseek | deepseek-flash | pcr | none | 23 | 23 | 9 | 39.1% | 0 | 1,061,090 | 31,713 | 0 | 15.5 |
| ds-single | deepseek | deepseek-flash | single | none | 23 | 19 | 11 | 47.8% | 0 | 1,078,799 | 8,743 | 0 | 12.3 |
| ds-pcr-low | deepseek | deepseek-flash | pcr | low | 23 | 22 | 11 | 47.8% | 0 | 772,446 | 82,865 | 53,158 | 31.9 |
| ds-pcr-high | deepseek | deepseek-flash | pcr | high | 23 | 19 | 9 | 39.1% | 0 | 1,132,206 | 387,610 | 297,198 | 114.2 |
| ds-pcr-max | deepseek | deepseek-flash | pcr | max | 23 | 21 | 11 | 47.8% | 0 | 1,125,203 | 380,125 | 338,196 | 111.5 |
| ds-pcr-exec | deepseek | deepseek-flash | pcr | none | 23 | 23 | 11 | 47.8% | 0 | 1,091,557 | 32,189 | 0 | 22.8 |
| ds-single-exec | deepseek | deepseek-flash | single | none | 23 | 19 | 10 | 43.5% | 0 | 1,263,374 | 9,881 | 0 | 16.4 |

## Paired comparisons

| Comparison | A | B | Rate A | Rate B | A-B | both / only A / only B / neither | McNemar p | 95% CI (A-B) |
|---|---|---|---|---|---|---|---|---|
| RQ3: P-C-R vs single agent (DeepSeek) | ds-pcr | ds-single | 39.1% | 47.8% | -8.7% | 9 / 0 / 2 / 12 | 0.5000 | [-21.7%, 0.0%] |
| RQ1: reasoning low vs none (DeepSeek P-C-R) | ds-pcr-low | ds-pcr | 47.8% | 39.1% | 8.7% | 9 / 2 / 0 / 12 | 0.5000 | [0.0%, 21.7%] |
| RQ1: reasoning high vs none (DeepSeek P-C-R) | ds-pcr-high | ds-pcr | 39.1% | 39.1% | 0.0% | 8 / 1 / 1 / 13 | 1.0000 | [-13.0%, 13.0%] |
| RQ1: reasoning max vs none (DeepSeek P-C-R) | ds-pcr-max | ds-pcr | 47.8% | 39.1% | 8.7% | 8 / 3 / 1 / 11 | 0.6250 | [-8.7%, 26.1%] |
| RQ1: reasoning high vs low (DeepSeek P-C-R) | ds-pcr-high | ds-pcr-low | 39.1% | 47.8% | -8.7% | 9 / 0 / 2 / 12 | 0.5000 | [-21.7%, 0.0%] |
| RQ2: execution feedback vs none (DeepSeek P-C-R) | ds-pcr-exec | ds-pcr | 47.8% | 39.1% | 8.7% | 9 / 2 / 0 / 12 | 0.5000 | [0.0%, 21.7%] |
| RQ2: execution feedback vs none (DeepSeek single agent) | ds-single-exec | ds-single | 43.5% | 47.8% | -4.3% | 10 / 0 / 1 / 12 | 1.0000 | [-13.0%, 0.0%] |

## Comparability warnings

- none: every pair differs only in the studied variable

_resolved = official SWE-bench harness verdict; applicable = Git-applicable candidate only. Small task counts: treat p-values and CIs as indicative._
