# PatchLoop final comparison over 3 runs (SWE-bench Lite dev, official harness)

Runs (tags): final-ds, final-ds-r2, final-ds-r3

## Per-configuration results

| Config | Reasoning | Resolved per run | Mean | Mean rate | Range | Applicable (mean) | Completion tok (mean) | Reasoning tok (mean) | s/task (mean) | Run errors per run |
|---|---|---|---|---|---|---|---|---|---|---|
| ds-pcr | none | 10 / 12 / 10 | 10.67 | 46.4% | 10-12 | 23.0 | 27,622 | 0 | 13.0 | 0 / 0 / 0 |
| ds-single | none | 9 / 10 / 10 | 9.67 | 42.0% | 9-10 | 19.0 | 8,289 | 0 | 7.5 | 0 / 0 / 0 |
| ds-pcr-low | low | 11 / 9 / 11 | 10.33 | 44.9% | 9-11 | 21.3 | 157,604 | 105,235 | 42.5 | 2 / 0 / 0 |
| ds-pcr-high | high | 6 / 8 / 10 | 8.0 | 34.8% | 6-10 | 20.0 | 263,376 | 172,517 | 63.3 | 3 / 3 / 0 |
| ds-pcr-max | max | 9 / 11 / 8 | 9.33 | 40.6% | 8-11 | 19.7 | 452,191 | 346,629 | 106.2 | 1 / 2 / 4 |

## Paired comparisons (task level)

| Comparison | Mean rate A | Mean rate B | A-B | tasks A better / B better / tied | Sign test p | 95% CI (A-B, task bootstrap) | Pooled only A / only B |
|---|---|---|---|---|---|---|---|
| RQ3: P-C-R vs single agent (DeepSeek) | 46.4% | 42.0% | 4.3% | 3 / 3 / 17 | 1.0000 | [-8.7%, 18.8%] | 7 / 4 |
| RQ1: reasoning low vs none (DeepSeek P-C-R) | 44.9% | 46.4% | -1.5% | 2 / 4 / 17 | 0.6875 | [-8.7%, 7.2%] | 4 / 5 |
| RQ1: reasoning high vs none (DeepSeek P-C-R) | 34.8% | 46.4% | -11.6% | 1 / 6 / 16 | 0.1250 | [-23.2%, -1.5%] | 1 / 9 |
| RQ1: reasoning max vs none (DeepSeek P-C-R) | 40.6% | 46.4% | -5.8% | 2 / 5 / 16 | 0.4531 | [-17.4%, 5.8%] | 3 / 7 |
| RQ1: reasoning high vs low (DeepSeek P-C-R) | 34.8% | 44.9% | -10.1% | 1 / 6 / 16 | 0.1250 | [-20.3%, -1.5%] | 3 / 10 |

## Comparability warnings

- none

_Task-level tests: each task counts once (share of runs resolved), so repeated runs are not treated as independent tasks. Pooled counts are descriptive._
