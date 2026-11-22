# PatchLoop final comparison (SWE-bench Lite dev, official harness)

## Per-configuration results

| Config | Backend | Model | Agent | Reasoning | Tasks | Applicable | Resolved | Rate | Harness errors | Prompt tok | Completion tok | of which reasoning | s/task |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ds-pcr | deepseek | deepseek-flash | pcr | none | 23 | 23 | 10 | 43.5% | 0 | 844,527 | 25,624 | 0 | 12.7 |
| ds-single | deepseek | deepseek-flash | single | none | 23 | 18 | 9 | 39.1% | 0 | 952,552 | 7,786 | 0 | 7.4 |
| ds-pcr-low | deepseek | deepseek-flash | pcr | low | 23 | 20 | 11 | 47.8% | 0 | 798,506 | 132,705 | 37,558 | 33.7 |
| ds-pcr-high | deepseek | deepseek-flash | pcr | high | 23 | 18 | 6 | 26.1% | 0 | 946,070 | 275,205 | 143,787 | 62.7 |
| ds-pcr-max | deepseek | deepseek-flash | pcr | max | 23 | 22 | 9 | 39.1% | 0 | 1,037,686 | 597,881 | 429,215 | 126.8 |

## Paired comparisons

| Comparison | A | B | Rate A | Rate B | A-B | both / only A / only B / neither | McNemar p | 95% CI (A-B) |
|---|---|---|---|---|---|---|---|---|
| RQ3: P-C-R vs single agent (DeepSeek) | ds-pcr | ds-single | 43.5% | 39.1% | 4.3% | 8 / 2 / 1 / 12 | 1.0000 | [-8.7%, 17.4%] |
| RQ1: reasoning low vs none (DeepSeek P-C-R) | ds-pcr-low | ds-pcr | 47.8% | 43.5% | 4.3% | 9 / 2 / 1 / 11 | 1.0000 | [-8.7%, 17.4%] |
| RQ1: reasoning high vs none (DeepSeek P-C-R) | ds-pcr-high | ds-pcr | 26.1% | 43.5% | -17.4% | 6 / 0 / 4 / 13 | 0.1250 | [-34.8%, -4.3%] |
| RQ1: reasoning max vs none (DeepSeek P-C-R) | ds-pcr-max | ds-pcr | 39.1% | 43.5% | -4.3% | 8 / 1 / 2 / 12 | 1.0000 | [-17.4%, 8.7%] |
| RQ1: reasoning high vs low (DeepSeek P-C-R) | ds-pcr-high | ds-pcr-low | 26.1% | 47.8% | -21.7% | 6 / 0 / 5 / 12 | 0.0625 | [-39.1%, -4.3%] |

## Comparability warnings

- none: every pair differs only in the studied variable

_resolved = official SWE-bench harness verdict; applicable = Git-applicable candidate only. Small task counts: treat p-values and CIs as indicative._
