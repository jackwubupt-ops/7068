# PatchLoop final comparison (SWE-bench Lite dev, official harness)

## Per-configuration results

| Config | Backend | Model | Agent | Reasoning | Tasks | Applicable | Resolved | Rate | Harness errors | Prompt tok | Completion tok | of which reasoning | s/task |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ds-pcr | deepseek | deepseek-flash | pcr | none | 23 | 23 | 9 | 39.1% | 0 | 1,108,885 | 32,485 | 0 | 16.8 |
| ds-single | deepseek | deepseek-flash | single | none | 23 | 19 | 9 | 39.1% | 0 | 1,029,061 | 7,698 | 0 | 9.0 |
| ds-pcr-low | deepseek | deepseek-flash | pcr | low | 23 | 22 | 8 | 34.8% | 0 | 812,900 | 106,460 | 72,427 | 36.6 |
| ds-pcr-high | deepseek | deepseek-flash | pcr | high | 23 | 21 | 9 | 39.1% | 0 | 1,099,865 | 151,440 | 111,291 | 51.4 |
| ds-pcr-max | deepseek | deepseek-flash | pcr | max | 23 | 21 | 10 | 43.5% | 0 | 1,133,941 | 765,773 | 496,914 | 194.1 |
| ds-pcr-exec | deepseek | deepseek-flash | pcr | none | 23 | 22 | 11 | 47.8% | 0 | 1,273,080 | 36,527 | 0 | 23.4 |
| ds-single-exec | deepseek | deepseek-flash | single | none | 23 | 20 | 8 | 34.8% | 0 | 1,176,813 | 9,660 | 0 | 15.7 |

## Paired comparisons

| Comparison | A | B | Rate A | Rate B | A-B | both / only A / only B / neither | McNemar p | 95% CI (A-B) |
|---|---|---|---|---|---|---|---|---|
| RQ3: P-C-R vs single agent (DeepSeek) | ds-pcr | ds-single | 39.1% | 39.1% | 0.0% | 9 / 0 / 0 / 14 | 1.0000 | [0.0%, 0.0%] |
| RQ1: reasoning low vs none (DeepSeek P-C-R) | ds-pcr-low | ds-pcr | 34.8% | 39.1% | -4.3% | 7 / 1 / 2 / 13 | 1.0000 | [-17.4%, 8.7%] |
| RQ1: reasoning high vs none (DeepSeek P-C-R) | ds-pcr-high | ds-pcr | 39.1% | 39.1% | 0.0% | 8 / 1 / 1 / 13 | 1.0000 | [-13.0%, 13.0%] |
| RQ1: reasoning max vs none (DeepSeek P-C-R) | ds-pcr-max | ds-pcr | 43.5% | 39.1% | 4.3% | 8 / 2 / 1 / 12 | 1.0000 | [-8.7%, 17.4%] |
| RQ1: reasoning high vs low (DeepSeek P-C-R) | ds-pcr-high | ds-pcr-low | 39.1% | 34.8% | 4.3% | 6 / 3 / 2 / 12 | 1.0000 | [-13.0%, 21.7%] |
| RQ2: execution feedback vs none (DeepSeek P-C-R) | ds-pcr-exec | ds-pcr | 47.8% | 39.1% | 8.7% | 9 / 2 / 0 / 12 | 0.5000 | [0.0%, 21.7%] |
| RQ2: execution feedback vs none (DeepSeek single agent) | ds-single-exec | ds-single | 34.8% | 39.1% | -4.3% | 8 / 0 / 1 / 14 | 1.0000 | [-13.0%, 0.0%] |

## Comparability warnings

- none: every pair differs only in the studied variable

_resolved = official SWE-bench harness verdict; applicable = Git-applicable candidate only. Small task counts: treat p-values and CIs as indicative._
