# PatchLoop final comparison (SWE-bench Lite dev, official harness)

## Per-configuration results

| Config | Backend | Model | Agent | Reasoning | Tasks | Applicable | Resolved | Rate | Harness errors | Prompt tok | Completion tok | of which reasoning | s/task |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ds-pcr | deepseek | deepseek-flash | pcr | none | 23 | 23 | 10 | 43.5% | 0 | 929,465 | 28,266 | 0 | 13.5 |
| ds-single | deepseek | deepseek-flash | single | none | 23 | 20 | 10 | 43.5% | 0 | 854,523 | 8,530 | 0 | 7.8 |
| ds-pcr-low | deepseek | deepseek-flash | pcr | low | 23 | 22 | 11 | 47.8% | 0 | 859,122 | 185,374 | 154,185 | 51.9 |
| ds-pcr-high | deepseek | deepseek-flash | pcr | high | 23 | 22 | 10 | 43.5% | 0 | 1,039,560 | 238,919 | 204,201 | 63.4 |
| ds-pcr-max | deepseek | deepseek-flash | pcr | max | 23 | 18 | 8 | 34.8% | 0 | 970,023 | 423,603 | 319,558 | 102.8 |

## Paired comparisons

| Comparison | A | B | Rate A | Rate B | A-B | both / only A / only B / neither | McNemar p | 95% CI (A-B) |
|---|---|---|---|---|---|---|---|---|
| RQ3: P-C-R vs single agent (DeepSeek) | ds-pcr | ds-single | 43.5% | 43.5% | 0.0% | 8 / 2 / 2 / 11 | 1.0000 | [-17.4%, 17.4%] |
| RQ1: reasoning low vs none (DeepSeek P-C-R) | ds-pcr-low | ds-pcr | 47.8% | 43.5% | 4.3% | 9 / 2 / 1 / 11 | 1.0000 | [-8.7%, 17.4%] |
| RQ1: reasoning high vs none (DeepSeek P-C-R) | ds-pcr-high | ds-pcr | 43.5% | 43.5% | 0.0% | 9 / 1 / 1 / 12 | 1.0000 | [-13.0%, 13.0%] |
| RQ1: reasoning max vs none (DeepSeek P-C-R) | ds-pcr-max | ds-pcr | 34.8% | 43.5% | -8.7% | 7 / 1 / 3 / 12 | 0.6250 | [-26.1%, 8.7%] |
| RQ1: reasoning high vs low (DeepSeek P-C-R) | ds-pcr-high | ds-pcr-low | 43.5% | 47.8% | -4.3% | 9 / 1 / 2 / 11 | 1.0000 | [-17.4%, 8.7%] |

## Comparability warnings

- none: every pair differs only in the studied variable

_resolved = official SWE-bench harness verdict; applicable = Git-applicable candidate only. Small task counts: treat p-values and CIs as indicative._
