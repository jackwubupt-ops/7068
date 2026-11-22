"""Combine repeated runs of the final experiment (same settings, different run tags).

Each run of scripts/run_final_deepseek.sh with its own TAG writes one batch per config
($RUNS/$TAG-pcr, $TAG-single, $TAG-pcr-low, ...). This report puts the runs side by side:

    python -m experiments.repeat_report --runs-dir /data/runs \
        --tag final-ds --tag final-ds-r2 --tag final-ds-r3 \
        --tasks-file /data/analysis/final-comparison.gold-tasks.txt \
        --out /data/analysis/final-repeats

Per config: resolved in each run, mean and range, mean applicable/tokens/time, run errors.
Per pair (same pairs as final_report): mean rates over all runs, and a TASK-LEVEL paired
test so repeated runs of the same task are not counted as independent evidence:
  - per task, a = share of runs where A resolved it, b = the same for B;
  - sign test over tasks with a != b (exact two-sided, as McNemar);
  - bootstrap 95% CI of mean(a - b), resampling tasks (runs stay together per task).
Also listed: the pooled discordant counts over all task-runs (descriptive only).
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from experiments.final_report import DEFAULT_PAIRS, comparability, load_batch
from experiments.paired_compare import mcnemar_exact

CONFIGS = ("pcr", "single", "pcr-low", "pcr-high", "pcr-max", "pcr-exec", "single-exec")


def load_runs(runs_dir: Path, tags: list[str], *, tasks: set[str] | None = None) -> dict:
    """{label: [batch per tag]} for configs present in EVERY tag."""
    out = {}
    for config in CONFIGS:
        dirs = [Path(runs_dir) / f"{tag}-{config}" for tag in tags]
        if not all(d.is_dir() for d in dirs):
            continue
        label = f"ds-{config}"
        out[label] = [load_batch(f"{label}@{tag}", d, tasks=tasks) for tag, d in zip(tags, dirs)]
    if not out:
        raise ValueError("no config was found under every tag")
    return out


def summarize(runs: list[dict]) -> dict:
    k = len(runs)
    resolved = [r["resolved"] for r in runs]
    n = runs[0]["tasks"]
    errors = [r["status_counts"].get("experiment_error", 0) + r["status_counts"].get("batch_error", 0)
              for r in runs]
    mean = lambda key: round(sum(r[key] or 0 for r in runs) / k, 1)  # noqa: E731
    return {
        "runs": k, "tasks": n, "agent": runs[0]["agent"],
        "reasoning_effort": runs[0]["reasoning_effort"],
        "resolved_per_run": resolved,
        "resolved_mean": round(sum(resolved) / k, 2),
        "resolved_rate_mean": round(sum(resolved) / (k * n), 4),
        "resolved_min": min(resolved), "resolved_max": max(resolved),
        "applicable_mean": mean("applicable"),
        "completion_tokens_mean": mean("completion_tokens"),
        "reasoning_tokens_mean": mean("reasoning_tokens"),
        "seconds_per_task_mean": mean("seconds_per_task"),
        "run_errors_per_run": errors,
    }


def task_shares(runs: list[dict]) -> dict[str, float]:
    ids = set(runs[0]["verdicts"])
    for r in runs[1:]:
        if set(r["verdicts"]) != ids:
            raise ValueError(f"{r['label']}: different task list than {runs[0]['label']}")
    return {i: sum(r["verdicts"][i] for r in runs) / len(runs) for i in sorted(ids)}


def task_level_compare(a_runs: list[dict], b_runs: list[dict], *, iterations: int = 10000,
                       seed: int = 7608) -> dict:
    a, b = task_shares(a_runs), task_shares(b_runs)
    if set(a) != set(b):
        raise ValueError("the two configs were run on different task lists")
    ids = sorted(a)
    diffs = [a[i] - b[i] for i in ids]
    a_better = sum(1 for d in diffs if d > 0)
    b_better = sum(1 for d in diffs if d < 0)
    rng = random.Random(seed)
    n = len(ids)
    boot = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(iterations))
    pooled = {"only_a": 0, "only_b": 0}
    for ra, rb in zip(a_runs, b_runs):  # run i of A paired with run i of B
        for i in ids:
            pooled["only_a"] += ra["verdicts"][i] and not rb["verdicts"][i]
            pooled["only_b"] += rb["verdicts"][i] and not ra["verdicts"][i]
    return {
        "tasks": n,
        "rate_a_mean": round(sum(a.values()) / n, 4),
        "rate_b_mean": round(sum(b.values()) / n, 4),
        "diff_mean": round(sum(diffs) / n, 4),
        "tasks_a_better": a_better, "tasks_b_better": b_better,
        "tasks_tied": n - a_better - b_better,
        "sign_test_p": round(mcnemar_exact(a_better, b_better), 6),
        "bootstrap_95ci_diff": (round(boot[int(0.025 * iterations)], 4),
                                round(boot[min(iterations - 1, int(0.975 * iterations))], 4)),
        "pooled_discordant": pooled,
        "per_task": {i: {"a": round(a[i], 3), "b": round(b[i], 3)} for i in ids},
    }


def build_report(runs: dict, tags: list[str], *, iterations: int = 10000, seed: int = 7608,
                 vs_runs: dict | None = None, vs_tags: list[str] | None = None) -> dict:
    comparisons = []
    for label_a, label_b, title in DEFAULT_PAIRS:
        if label_a not in runs or label_b not in runs:
            continue
        warnings = sorted({w for ra, rb in zip(runs[label_a], runs[label_b])
                           for w in comparability(ra, rb) if "same evaluation run id" not in w})
        comparisons.append({"title": title, "a": label_a, "b": label_b, "warnings": warnings,
                            **task_level_compare(runs[label_a], runs[label_b],
                                                 iterations=iterations, seed=seed)})
    for label, earlier in (vs_runs or {}).items():
        if label not in runs:
            continue
        # Same config, two agent versions (e.g. tools added since the earlier runs).
        # A different commit is the point of a version comparison: not a warning here.
        warnings = sorted({w for ra, rb in zip(runs[label], earlier)
                           for w in comparability(ra, rb)
                           if "same evaluation run id" not in w and "commit differs" not in w})
        comparisons.append({"title": f"Version: {label} current vs earlier ({', '.join(vs_tags or [])})",
                            "a": label, "b": f"{label} (earlier)", "warnings": warnings,
                            **task_level_compare(runs[label], earlier, iterations=iterations, seed=seed)})
    return {"tags": tags, "vs_tags": vs_tags or [],
            "configs": {label: summarize(r) for label, r in runs.items()},
            "comparisons": comparisons, "bootstrap": {"iterations": iterations, "seed": seed},
            "note": ("Task-level tests: each task counts once (share of runs resolved), so repeated "
                     "runs are not treated as independent tasks. Pooled counts are descriptive.")}


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render_markdown(report: dict) -> str:
    tags = ", ".join(report["tags"])
    rows = ["| Config | Reasoning | Resolved per run | Mean | Mean rate | Range | Applicable (mean) | "
            "Completion tok (mean) | Reasoning tok (mean) | s/task (mean) | Run errors per run |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, c in report["configs"].items():
        rows.append(f"| {label} | {c['reasoning_effort']} | "
                    f"{' / '.join(map(str, c['resolved_per_run']))} | {c['resolved_mean']} | "
                    f"{_pct(c['resolved_rate_mean'])} | {c['resolved_min']}-{c['resolved_max']} | "
                    f"{c['applicable_mean']} | {c['completion_tokens_mean']:,.0f} | "
                    f"{c['reasoning_tokens_mean']:,.0f} | {c['seconds_per_task_mean']} | "
                    f"{' / '.join(map(str, c['run_errors_per_run']))} |")
    pairs = ["| Comparison | Mean rate A | Mean rate B | A-B | tasks A better / B better / tied | "
             "Sign test p | 95% CI (A-B, task bootstrap) | Pooled only A / only B |",
             "|---|---|---|---|---|---|---|---|"]
    warn = []
    for c in report["comparisons"]:
        lo, hi = c["bootstrap_95ci_diff"]
        p = c["pooled_discordant"]
        pairs.append(f"| {c['title']} | {_pct(c['rate_a_mean'])} | {_pct(c['rate_b_mean'])} | "
                     f"{_pct(c['diff_mean'])} | {c['tasks_a_better']} / {c['tasks_b_better']} / "
                     f"{c['tasks_tied']} | {c['sign_test_p']:.4f} | [{_pct(lo)}, {_pct(hi)}] | "
                     f"{p['only_a']} / {p['only_b']} |")
        warn += [f"- {c['a']} vs {c['b']}: {w}" for w in c["warnings"]]
    return "\n".join([
        f"# PatchLoop final comparison over {len(report['tags'])} runs (SWE-bench Lite dev, official harness)",
        "", f"Runs (tags): {tags}", "", "## Per-configuration results", "", *rows, "",
        "## Paired comparisons (task level)", "", *pairs, "",
        "## Comparability warnings", "", *(warn or ["- none"]), "", f"_{report['note']}_", ""])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs-dir", default="/data/runs")
    parser.add_argument("--tag", action="append", required=True, help="run tag (repeatable, >= 2)")
    parser.add_argument("--tasks-file", help="restrict to these instance IDs (one per line)")
    parser.add_argument("--vs-tag", action="append", default=[],
                        help="tags of EARLIER runs of the same configs (another agent version): adds "
                             "per-config current-vs-earlier comparisons (repeatable)")
    parser.add_argument("--iterations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=7608)
    parser.add_argument("--out", required=True, help="output prefix: writes PREFIX.json and PREFIX.md")
    args = parser.parse_args(argv)
    if len(args.tag) < 2:
        parser.error("give at least two --tag values")
    tasks = None
    if args.tasks_file:
        tasks = {line.strip() for line in Path(args.tasks_file).read_text(encoding="utf-8").splitlines()
                 if line.strip()}
    vs_runs = load_runs(Path(args.runs_dir), args.vs_tag, tasks=tasks) if args.vs_tag else None
    report = build_report(load_runs(Path(args.runs_dir), args.tag, tasks=tasks), args.tag,
                          iterations=args.iterations, seed=args.seed,
                          vs_runs=vs_runs, vs_tags=args.vs_tag)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(f"{args.out}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown = render_markdown(report)
    Path(f"{args.out}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
