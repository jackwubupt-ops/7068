# PatchLoop final comparison (SWE-bench Lite dev, official harness)

## Per-configuration results

| Config | Backend | Model | Agent | Reasoning | Tasks | Applicable | Resolved | Rate | Harness errors | Prompt tok | Completion tok | of which reasoning | s/task |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ds-pcr | deepseek | deepseek-flash | pcr | none | 23 | 22 | 10 | 43.5% | 0 | 1,123,096 | 32,985 | 0 | 19.6 |
| ds-single | deepseek | deepseek-flash | single | none | 23 | 21 | 11 | 47.8% | 0 | 973,690 | 8,479 | 0 | 9.5 |
| ds-pcr-low | deepseek | deepseek-flash | pcr | low | 23 | 20 | 10 | 43.5% | 0 | 847,093 | 165,384 | 106,944 | 52.6 |
| ds-pcr-high | deepseek | deepseek-flash | pcr | high | 23 | 22 | 8 | 34.8% | 0 | 1,160,584 | 192,142 | 92,376 | 53.5 |
| ds-pcr-max | deepseek | deepseek-flash | pcr | max | 23 | 22 | 11 | 47.8% | 0 | 1,234,112 | 327,996 | 281,586 | 100.5 |
| ds-pcr-exec | deepseek | deepseek-flash | pcr | none | 23 | 23 | 11 | 47.8% | 0 | 1,235,027 | 34,640 | 0 | 23.7 |
| ds-single-exec | deepseek | deepseek-flash | single | none | 23 | 19 | 7 | 30.4% | 0 | 1,094,433 | 10,075 | 0 | 15.6 |

## Paired comparisons

| Comparison | A | B | Rate A | Rate B | A-B | both / only A / only B / neither | McNemar p | 95% CI (A-B) |
|---|---|---|---|---|---|---|---|---|
| RQ3: P-C-R vs single agent (DeepSeek) | ds-pcr | ds-single | 43.5% | 47.8% | -4.3% | 9 / 1 / 2 / 11 | 1.0000 | [-21.7%, 8.7%] |
| RQ1: reasoning low vs none (DeepSeek P-C-R) | ds-pcr-low | ds-pcr | 43.5% | 43.5% | 0.0% | 7 / 3 / 3 / 10 | 1.0000 | [-21.7%, 21.7%] |
| RQ1: reasoning high vs none (DeepSeek P-C-R) | ds-pcr-high | ds-pcr | 34.8% | 43.5% | -8.7% | 8 / 0 / 2 / 13 | 0.5000 | [-21.7%, 0.0%] |
| RQ1: reasoning max vs none (DeepSeek P-C-R) | ds-pcr-max | ds-pcr | 47.8% | 43.5% | 4.3% | 9 / 2 / 1 / 11 | 1.0000 | [-8.7%, 17.4%] |
| RQ1: reasoning high vs low (DeepSeek P-C-R) | ds-pcr-high | ds-pcr-low | 34.8% | 43.5% | -8.7% | 6 / 2 / 4 / 11 | 0.6875 | [-30.4%, 13.0%] |
| RQ2: execution feedback vs none (DeepSeek P-C-R) | ds-pcr-exec | ds-pcr | 47.8% | 43.5% | 4.3% | 10 / 1 / 0 / 12 | 1.0000 | [0.0%, 13.0%] |
| RQ2: execution feedback vs none (DeepSeek single agent) | ds-single-exec | ds-single | 30.4% | 47.8% | -17.4% | 7 / 0 / 4 / 12 | 0.1250 | [-34.8%, -4.3%] |

## Comparability warnings

- none: every pair differs only in the studied variable

_resolved = official SWE-bench harness verdict; applicable = Git-applicable candidate only. Small task counts: treat p-values and CIs as indicative._
