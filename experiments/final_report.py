"""Final comparison report over several evaluated lite_batch directories.

The final experiment runs on the DeepSeek API (`deepseek-flash`):
  RQ1  reasoning effort none / low / high (/ max) for P-C-R (inference-time compute,
       replacing the proposal's QLoRA training-time improvement)
  RQ3  P-C-R vs. the single agent under identical budgets (effort none)
The earlier Qwen2.5-Coder-7B batches are added as the model-capability baseline
(why the 7B model alone cannot carry the system). Every batch needs `official_eval.json`.

    python -m experiments.final_report \
        --batch ds-pcr=/data/runs/final-ds-pcr --batch ds-single=/data/runs/final-ds-single \
        --batch qwen-pcr=/data/runs/lite-pilot-v3-pcr --batch qwen-single=/data/runs/lite-pilot-v3-single \
        --tasks-file /data/eval-selftest/gold_resolved.txt --out /data/analysis/final

Without --pair, the default pairs are used for the labels present:
ds-pcr vs ds-single (RQ3); ds-pcr-low/-high/-max vs ds-pcr and high vs low (RQ1);
ds-pcr vs qwen-pcr and ds-single vs qwen-single (model).
--tasks-file restricts every number to the listed instance IDs (one per line;
e.g. the tasks whose gold patch resolves in our environment).

Outputs PREFIX.json and PREFIX.md (tables ready for the report). Settings that
differ inside a pair (other than the variable being compared) are listed as
comparability warnings; read those before quoting a difference.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.paired_compare import compare, load_verdicts

# Settings that must match inside a pair for the comparison to be fair.
MATCHED_SETTINGS = ("edit_format", "retrieval_k", "max_calls_per_task", "context_chars",
                    "stage_max_tokens", "max_candidates", "temperature", "dataset", "split")
# The variables a pair may study; exactly one of them should differ inside a pair.
VARIABLES = ("model", "agent", "reasoning_effort", "agent_tools")
# Batches from before the find_definition/list_directory tools had only these two.
LEGACY_TOOLS = ["read_file", "search_repo"]
DEFAULT_PAIRS = (("ds-pcr", "ds-single", "RQ3: P-C-R vs single agent (DeepSeek)"),
                 ("ds-pcr-low", "ds-pcr", "RQ1: reasoning low vs none (DeepSeek P-C-R)"),
                 ("ds-pcr-high", "ds-pcr", "RQ1: reasoning high vs none (DeepSeek P-C-R)"),
                 ("ds-pcr-max", "ds-pcr", "RQ1: reasoning max vs none (DeepSeek P-C-R)"),
                 ("ds-pcr-high", "ds-pcr-low", "RQ1: reasoning high vs low (DeepSeek P-C-R)"),
                 ("ds-pcr", "qwen-pcr", "Model: DeepSeek vs Qwen-7B (P-C-R)"),
                 ("ds-single", "qwen-single", "Model: DeepSeek vs Qwen-7B (single agent)"))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_batch(label: str, directory: Path, *, tasks: set[str] | None = None,
               allow_incomplete: bool = False) -> dict:
    directory = Path(directory)
    manifest = _read_json(directory / "manifest.json")
    if not manifest:
        raise ValueError(f"{label}: {directory} has no manifest.json; not a lite_batch directory")
    evaluation, verdicts = load_verdicts(directory, allow_incomplete=allow_incomplete)
    if tasks is not None:
        missing = tasks - set(verdicts)
        if missing:
            raise ValueError(f"{label}: --tasks-file lists tasks this batch did not run: "
                             f"{', '.join(sorted(missing)[:5])}")
        verdicts = {iid: ok for iid, ok in verdicts.items() if iid in tasks}
    lines = {line["instance_id"]: line for line in _read_jsonl(directory / "results.jsonl")
             if line.get("instance_id") in verdicts}
    statuses = evaluation.get("tasks", {})
    n = len(verdicts)
    resolved = sum(verdicts.values())
    seconds = sum(float(line.get("duration_seconds") or 0) for line in lines.values())
    return {
        "label": label,
        "dir": str(directory),
        "backend": manifest.get("backend", "qwen"),
        "model": manifest.get("model"),
        "agent": manifest.get("agent"),
        "reasoning_effort": manifest.get("reasoning_effort") or "none",
        "agent_tools": manifest.get("agent_tools") or LEGACY_TOOLS,
        "settings": {key: manifest.get(key) for key in MATCHED_SETTINGS},
        "patchloop_commit": manifest.get("patchloop_commit"),
        "eval_run_id": evaluation.get("run_id"),
        "eval_complete": bool(evaluation.get("complete")),
        "tasks": n,
        "applicable": sum(1 for line in lines.values() if line.get("status") == "prediction_ready"),
        "resolved": resolved,
        "resolved_rate": round(resolved / n, 4) if n else 0.0,
        "harness_errors": sum(1 for iid in verdicts if statuses.get(iid) == "harness_error"),
        "prompt_tokens": sum(int(line.get("prompt_tokens") or 0) for line in lines.values()),
        "completion_tokens": sum(int(line.get("completion_tokens") or 0) for line in lines.values()),
        "reasoning_tokens": sum(int(line.get("reasoning_tokens") or 0) for line in lines.values()),
        "seconds_per_task": round(seconds / len(lines), 1) if lines else None,
        "status_counts": _count(line.get("status") for line in lines.values()),
        "verdicts": verdicts,
    }


def _count(values) -> dict:
    out: dict = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return dict(sorted(out.items()))


def comparability(a: dict, b: dict) -> list[str]:
    """Differences that are NOT the variable under study."""
    warnings = [f"{key}: {a['settings'][key]!r} vs {b['settings'][key]!r}"
                for key in MATCHED_SETTINGS if a["settings"][key] != b["settings"][key]]
    differing = [key for key in VARIABLES if a[key] != b[key]]
    if len(differing) > 1:
        warnings.append(f"{' and '.join(differing)} all differ: the pair confounds several variables")
    if a["eval_run_id"] and a["eval_run_id"] == b["eval_run_id"]:
        warnings.append("both batches report the same evaluation run id")
    for side in (a, b):
        if not side["eval_complete"]:
            warnings.append(f"{side['label']}: official evaluation incomplete")
    return warnings


def build_report(batches: dict[str, dict], pairs, *, iterations: int = 10000,
                 seed: int = 7608) -> dict:
    comparisons = []
    for label_a, label_b, title in pairs:
        if label_a not in batches or label_b not in batches:
            raise ValueError(f"pair {label_a}:{label_b} names a label without --batch")
        a, b = batches[label_a], batches[label_b]
        result = compare(a["verdicts"], b["verdicts"], iterations=iterations, seed=seed)
        comparisons.append({"title": title, "a": label_a, "b": label_b,
                            "warnings": comparability(a, b),
                            **{k: v for k, v in result.items() if k != "per_task"},
                            "per_task": result["per_task"]})
    return {
        "batches": {label: {k: v for k, v in batch.items() if k != "verdicts"}
                    for label, batch in batches.items()},
        "comparisons": comparisons,
        "bootstrap": {"iterations": iterations, "seed": seed},
        "note": ("resolved = official SWE-bench harness verdict; applicable = Git-applicable "
                 "candidate only. Small task counts: treat p-values and CIs as indicative."),
    }


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render_markdown(report: dict) -> str:
    rows = ["| Config | Backend | Model | Agent | Reasoning | Tasks | Applicable | Resolved | Rate | "
            "Harness errors | Prompt tok | Completion tok | of which reasoning | s/task |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, b in report["batches"].items():
        rows.append(f"| {label} | {b['backend']} | {b['model']} | {b['agent']} | "
                    f"{b['reasoning_effort']} | {b['tasks']} | "
                    f"{b['applicable']} | {b['resolved']} | {_pct(b['resolved_rate'])} | "
                    f"{b['harness_errors']} | {b['prompt_tokens']:,} | {b['completion_tokens']:,} | "
                    f"{b['reasoning_tokens']:,} | "
                    f"{b['seconds_per_task'] if b['seconds_per_task'] is not None else '-'} |")
    pairs = ["| Comparison | A | B | Rate A | Rate B | A-B | both / only A / only B / neither | "
             "McNemar p | 95% CI (A-B) |", "|---|---|---|---|---|---|---|---|---|"]
    warn = []
    for c in report["comparisons"]:
        t = c["table"]
        lo, hi = c["bootstrap_95ci_diff"]
        pairs.append(f"| {c['title']} | {c['a']} | {c['b']} | {_pct(c['rate_a'])} | "
                     f"{_pct(c['rate_b'])} | {_pct(c['diff_a_minus_b'])} | "
                     f"{t['both']} / {t['only_a']} / {t['only_b']} / {t['neither']} | "
                     f"{c['mcnemar_exact_p']:.4f} | [{_pct(lo)}, {_pct(hi)}] |")
        for w in c["warnings"]:
            warn.append(f"- {c['a']} vs {c['b']}: {w}")
    out = ["# PatchLoop final comparison (SWE-bench Lite dev, official harness)", "",
           "## Per-configuration results", "", *rows, "",
           "## Paired comparisons", "", *pairs, "",
           "## Comparability warnings", "", *(warn or ["- none: every pair differs only in the studied variable"]),
           "", f"_{report['note']}_", ""]
    return "\n".join(out)


def parse_batch_arg(text: str) -> tuple[str, Path]:
    label, sep, path = text.partition("=")
    if not sep or not label or not path:
        raise argparse.ArgumentTypeError("--batch must be LABEL=DIR")
    return label, Path(path).expanduser()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", action="append", type=parse_batch_arg, required=True,
                        metavar="LABEL=DIR", help="evaluated lite_batch directory (repeatable)")
    parser.add_argument("--pair", action="append", metavar="A:B",
                        help="labels to compare, A minus B (repeatable; default: see above)")
    parser.add_argument("--tasks-file", help="restrict to these instance IDs (one per line)")
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--iterations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=7608)
    parser.add_argument("--out", required=True, help="output prefix: writes PREFIX.json and PREFIX.md")
    args = parser.parse_args(argv)

    labels = [label for label, _ in args.batch]
    if len(set(labels)) != len(labels):
        parser.error("--batch labels must be unique")
    tasks = None
    if args.tasks_file:
        tasks = {line.strip() for line in Path(args.tasks_file).read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.startswith("#")}
        if not tasks:
            parser.error("--tasks-file is empty")
    batches = {label: load_batch(label, path, tasks=tasks, allow_incomplete=args.allow_incomplete)
               for label, path in args.batch}
    if args.pair:
        pairs = []
        for item in args.pair:
            a, sep, b = item.partition(":")
            if not sep:
                parser.error("--pair must be A:B")
            pairs.append((a, b, f"{a} vs {b}"))
    else:
        pairs = [p for p in DEFAULT_PAIRS if p[0] in batches and p[1] in batches]
        if not pairs:
            parser.error("no default pair matches the labels; pass --pair A:B")
    try:
        report = build_report(batches, pairs, iterations=args.iterations, seed=args.seed)
    except ValueError as exc:
        parser.error(str(exc))
    report["tasks_file"] = args.tasks_file
    prefix = Path(args.out).expanduser()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{prefix}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    markdown = render_markdown(report)
    Path(f"{prefix}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
