# PatchLoop final comparison over 3 runs (SWE-bench Lite dev, official harness)

Runs (tags): final-t4, final-t4-r2, final-t4-r3

## Per-configuration results

| Config | Reasoning | Resolved per run | Mean | Mean rate | Range | Applicable (mean) | Completion tok (mean) | Reasoning tok (mean) | s/task (mean) | Run errors per run |
|---|---|---|---|---|---|---|---|---|---|---|
| ds-pcr | none | 9 / 10 / 9 | 9.33 | 40.6% | 9-10 | 22.7 | 32,394 | 0 | 17.3 | 0 / 0 / 0 |
| ds-single | none | 11 / 11 / 9 | 10.33 | 44.9% | 9-11 | 19.7 | 8,307 | 0 | 10.3 | 0 / 0 / 0 |
| ds-pcr-low | low | 11 / 10 / 8 | 9.67 | 42.0% | 8-11 | 21.3 | 118,236 | 77,510 | 40.4 | 0 / 2 / 1 |
| ds-pcr-high | high | 9 / 8 / 9 | 8.67 | 37.7% | 8-9 | 20.7 | 243,731 | 166,955 | 73.0 | 3 / 1 / 1 |
| ds-pcr-max | max | 11 / 11 / 10 | 10.67 | 46.4% | 10-11 | 21.3 | 491,298 | 372,232 | 135.4 | 2 / 0 / 2 |
| ds-pcr-exec | none | 11 / 11 / 11 | 11.0 | 47.8% | 11-11 | 22.7 | 34,452 | 0 | 23.3 | 0 / 0 / 0 |
| ds-single-exec | none | 10 / 7 / 8 | 8.33 | 36.2% | 7-10 | 19.3 | 9,872 | 0 | 15.9 | 0 / 0 / 0 |

## Paired comparisons (task level)

| Comparison | Mean rate A | Mean rate B | A-B | tasks A better / B better / tied | Sign test p | 95% CI (A-B, task bootstrap) | Pooled only A / only B |
|---|---|---|---|---|---|---|---|
| RQ3: P-C-R vs single agent (DeepSeek) | 40.6% | 44.9% | -4.3% | 1 / 3 / 19 | 0.6250 | [-13.0%, 2.9%] | 1 / 4 |
| RQ1: reasoning low vs none (DeepSeek P-C-R) | 42.0% | 40.6% | 1.5% | 5 / 5 / 13 | 1.0000 | [-8.7%, 11.6%] | 6 / 5 |
| RQ1: reasoning high vs none (DeepSeek P-C-R) | 37.7% | 40.6% | -2.9% | 1 / 4 / 18 | 0.3750 | [-10.1%, 5.8%] | 2 / 4 |
| RQ1: reasoning max vs none (DeepSeek P-C-R) | 46.4% | 40.6% | 5.8% | 3 / 2 / 18 | 1.0000 | [-4.3%, 17.4%] | 7 / 3 |
| RQ1: reasoning high vs low (DeepSeek P-C-R) | 37.7% | 42.0% | -4.3% | 2 / 5 / 16 | 0.4531 | [-11.6%, 2.9%] | 5 / 8 |
| RQ2: execution feedback vs none (DeepSeek P-C-R) | 47.8% | 40.6% | 7.2% | 3 / 0 / 20 | 0.2500 | [0.0%, 15.9%] | 5 / 0 |
| RQ2: execution feedback vs none (DeepSeek single agent) | 36.2% | 44.9% | -8.7% | 0 / 4 / 19 | 0.1250 | [-18.8%, -1.5%] | 0 / 6 |

## Comparability warnings

- none

_Task-level tests: each task counts once (share of runs resolved), so repeated runs are not treated as independent tasks. Pooled counts are descriptive._
