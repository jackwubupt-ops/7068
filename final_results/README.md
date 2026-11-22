# Final results (server export, 2026-11-22)

Produced on the evaluation server with `bash scripts/export_results.sh`; the numbers in the main
README section 5 come from these files. No API keys, prompts or repository checkouts are included.

| Path | Content |
|---|---|
| `analysis/final-repeats-t4.md` | **main result**: current agent, 7 configurations x 3 runs (RQ1, RQ2, RQ3), task-level paired tests |
| `analysis/final-repeats-t4-vs-old.md` | current agent vs the earlier 2-tool version, per configuration |
| `analysis/comparison-final-t4*.md` | one report per run (per-configuration table, McNemar + bootstrap pairs) |
| `analysis/final-repeats.md`, `analysis/final-comparison*.md` | earlier agent version (2 tools), 3 runs |
| `runs/<batch>/` | `manifest.json` (all settings, commit), `summary.json`, `official_eval.json` (official SWE-bench harness verdicts), `results.jsonl`, `all_preds.jsonl` (the patches), `<task>/run_status.json` (per-task decisions, tool calls, attempts, test checks, token usage; no prompt text) |
| `eval-selftest/gold.gold-all-dev-fixed.json` | gold-patch self-test after the image repair: 23/23 resolved |
| `samples/` | traces of the five sample requests (`.md` readable, `.json` full session views): ordinary task, changed request, vague request, invalid repository, execution feedback |

Batch names: `final-t4[-r2|-r3]-<config>` = current agent, `final-ds[-r2|-r3]-<config>` = earlier
agent; configs `pcr`, `single`, `pcr-low`, `pcr-high`, `pcr-max`, `pcr-exec`, `single-exec`.
