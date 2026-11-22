# PatchLoop final comparison (SWE-bench Lite dev, official harness)

## Per-configuration results

| Config | Backend | Model | Agent | Reasoning | Tasks | Applicable | Resolved | Rate | Harness errors | Prompt tok | Completion tok | of which reasoning | s/task |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ds-pcr | deepseek | deepseek-flash | pcr | none | 23 | 23 | 12 | 52.2% | 0 | 895,522 | 28,976 | 0 | 12.7 |
| ds-single | deepseek | deepseek-flash | single | none | 23 | 19 | 10 | 43.5% | 0 | 873,798 | 8,552 | 0 | 7.2 |
| ds-pcr-low | deepseek | deepseek-flash | pcr | low | 23 | 22 | 9 | 39.1% | 0 | 770,774 | 154,732 | 123,961 | 41.9 |
| ds-pcr-high | deepseek | deepseek-flash | pcr | high | 23 | 20 | 8 | 34.8% | 0 | 1,031,353 | 276,005 | 169,564 | 63.7 |
| ds-pcr-max | deepseek | deepseek-flash | pcr | max | 23 | 19 | 11 | 47.8% | 0 | 956,066 | 335,089 | 291,114 | 89.0 |

## Paired comparisons

| Comparison | A | B | Rate A | Rate B | A-B | both / only A / only B / neither | McNemar p | 95% CI (A-B) |
|---|---|---|---|---|---|---|---|---|
| RQ3: P-C-R vs single agent (DeepSeek) | ds-pcr | ds-single | 52.2% | 43.5% | 8.7% | 9 / 3 / 1 / 10 | 0.6250 | [-8.7%, 26.1%] |
| RQ1: reasoning low vs none (DeepSeek P-C-R) | ds-pcr-low | ds-pcr | 39.1% | 52.2% | -13.0% | 9 / 0 / 3 / 11 | 0.2500 | [-26.1%, 0.0%] |
| RQ1: reasoning high vs none (DeepSeek P-C-R) | ds-pcr-high | ds-pcr | 34.8% | 52.2% | -17.4% | 8 / 0 / 4 / 11 | 0.1250 | [-34.8%, -4.3%] |
| RQ1: reasoning max vs none (DeepSeek P-C-R) | ds-pcr-max | ds-pcr | 47.8% | 52.2% | -4.3% | 10 / 1 / 2 / 10 | 1.0000 | [-17.4%, 8.7%] |
| RQ1: reasoning high vs low (DeepSeek P-C-R) | ds-pcr-high | ds-pcr-low | 34.8% | 39.1% | -4.3% | 6 / 2 / 3 / 12 | 1.0000 | [-21.7%, 13.0%] |

## Comparability warnings

- none: every pair differs only in the studied variable

_resolved = official SWE-bench harness verdict; applicable = Git-applicable candidate only. Small task counts: treat p-values and CIs as indicative._
