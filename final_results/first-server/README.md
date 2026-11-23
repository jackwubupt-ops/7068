# First evaluation server (2026-11-20 – 11-21): Qwen-7B pilots and the original DeepSeek round 1

Exported from the first server (1× NVIDIA A10 24 GB) before it was released. Same file layout as
`final_results/runs/` (manifest, summary, official verdicts, predictions, per-task run status; no
prompts, keys or repository checkouts).

| Batch (`runs/`) | Model | Commit | What it is | Applicable | Resolved |
|---|---|---|---|---|---|
| `lite-pilot-pcr` / `-single` | Qwen2.5-Coder-7B-Instruct | `3fc9dfa` | pilot v1: baseline after harness fixes (#18–#20) | 3 / 2 | 0 / 0 |
| `lite-pilot-v2-pcr` / `-single` | Qwen2.5-Coder-7B-Instruct | `06e2ad8` | pilot v2: Planner give-up rule + whitespace-tolerant matching (#21) | 7 / 7 | 0 / 0 |
| `lite-pilot-v3-pcr` / `-single` | Qwen2.5-Coder-7B-Instruct | `d0af2ab` | pilot v3: + retrieval top-10 (#23); re-evaluated on the repaired images (`official_eval.json`; first verdict kept as `official_eval.pre-repair.json`) | 14 / 11 | 0 / 0 |
| `final-ds-pcr` / `-single` | deepseek-flash | `fe63ecd` | original DeepSeek round 1, the run paired with pilot v3 for the model comparison | 23 / 18 | 10 / 10 |
| `final-ds-pcr-low` / `-high` / `-max` | deepseek-flash | `fe63ecd` | **invalid** RQ1 round 1: thinking room 8K/24K/48K truncated Coder calls (fixed in `35a992a`; rerun in `../runs/`) | — | kept for the record |

Each pilot version and the round-1 DeepSeek batches ran **once** (pilot v1–v3 are three code
versions, not repeats). All runs: search_replace edits, temperature 0, 20 model calls and 48,000
history characters per task, output caps Planner 1,500 / Coder 3,500 / Reviewer 900 / agent 3,500
tokens, at most 2 candidates, 4 workers, the 2-tool agent (`search_repo`, `read_file`). Pilot v3 and
the DeepSeek round use retrieval top-10.

`analysis/`:
- `final-comparison.md`: the original model comparison. P-C-R 10 vs 0 and single 10 vs 0, both
  McNemar p = 0.002.
- `pilot-v2.md`, `pilot-v3.md`: failure diagnosis; for v3 the gold file is read in 83% / 74% of tasks.
- `pilot-*-pcr-vs-single.json`: P-C-R vs single within a pilot.

`logs/vllm-qwen7b-server.log`: the vLLM 0.19.1 server log for the pilots. Line 24 shows the
non-default arguments (`max_model_len` 32768, `host` 127.0.0.1); the log also shows BF16, no
quantization, and an NVIDIA A10. The private IP and host name are redacted.

The later DeepSeek runs in `../runs/` (`final-ds*` with commit `35a992a`, `final-t4*`) ran on
fresh CPU servers.
