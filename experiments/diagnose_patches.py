"""Post-hoc failure diagnosis of finished batches, scored against the GOLD patch.

    python -m experiments.diagnose_patches /data/runs/lite-pilot-v2-pcr /data/runs/lite-pilot-v2-single \
        --out /data/analysis/pilot-v2

ANALYSIS ONLY. The gold patch is loaded here, after a batch has finished, to
measure where the pipeline fails (TODO P2-2). Nothing in this module is
imported by inference code, and nothing it writes goes into a batch directory,
so the gold patch can never reach a prompt. tests/test_diagnose_patches.py
checks that no inference module imports it.

Per task it reports what the agent READ, which files it SELECTED (P-C-R
Planner) and EDITED, and whether those touch the gold files and the gold hunk
lines (old-file line ranges, with a small margin). Each unresolved task gets one
failure category:

    never_read_gold_file      localization: the gold file was never read
    read_gold_not_selected    gold file read, but not chosen/edited
    no_applicable_patch       gold file chosen, but no Git-applicable patch
    wrong_location            patch touches a gold file, far from the gold hunks
    right_location_wrong_fix  patch overlaps the gold hunks, tests still fail

Outputs <out>.json (all rows) and <out>.md (summary + every applicable patch
next to the gold patch, for reading by humans).
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Callable, Iterable

CATEGORIES = ("resolved", "never_read_gold_file", "read_gold_not_selected",
              "no_applicable_patch", "wrong_location", "right_location_wrong_fix")
HUNK_MARGIN = 5
_FILE = re.compile(r"^diff --git a/(\S+) b/\S+", re.M)
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def patch_hunks(patch: str) -> dict[str, list[tuple[int, int]]]:
    """{file: [(old_start, old_end), ...]} from a unified diff."""
    hunks: dict[str, list[tuple[int, int]]] = {}
    current = None
    for line in (patch or "").splitlines():
        match = _FILE.match(line)
        if match:
            current = match.group(1)
            hunks.setdefault(current, [])
            continue
        match = _HUNK.match(line)
        if match and current is not None:
            start = int(match.group(1))
            length = int(match.group(2)) if match.group(2) is not None else 1
            hunks[current].append((start, start + max(length, 1) - 1))
    return hunks


def hunks_overlap(pred: dict, gold: dict, margin: int = HUNK_MARGIN) -> bool:
    for path, spans in pred.items():
        for a0, a1 in spans:
            for b0, b1 in gold.get(path, []):
                if a0 <= b1 + margin and b0 <= a1 + margin:
                    return True
    return False


def load_gold(dataset: str, split: str, loader: Callable | None = None) -> dict[str, str]:
    if loader is None:
        from datasets import load_dataset
        loader = load_dataset
    return {row["instance_id"]: row["patch"] for row in loader(dataset, split=split)}


def _read_paths(status: dict) -> set[str]:
    trace = status.get("planner_action_trace") or status.get("agent_action_trace") or []
    paths = {e["read_path"] for e in trace if isinstance(e, dict) and e.get("read_path")}
    paths.update(status.get("read_files") or [])
    return paths


def _prediction(task_dir: Path) -> str:
    path = task_dir / "predictions.jsonl"
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            return json.loads(line).get("model_patch") or ""
    return ""


def diagnose_task(status: dict, prediction: str, gold_patch: str, verdict: str | None) -> dict:
    gold = patch_hunks(gold_patch)
    gold_files = set(gold)
    pred = patch_hunks(prediction)
    read = _read_paths(status)
    selected = set(status.get("suspected_files") or [])
    agent = status.get("agent") or ("pcr" if "planner_action_trace" in status else "single")
    row = {
        "instance_id": status.get("instance_id"),
        "agent": agent,
        "run_status": status.get("status"),
        "official": verdict,
        "gold_files": sorted(gold_files),
        "read_files": sorted(read),
        "selected_files": sorted(selected),
        "edited_files": sorted(pred),
        "read_gold": bool(read & gold_files),
        "selected_gold": bool(selected & gold_files),
        "edited_gold": bool(set(pred) & gold_files),
        "hunk_overlap": hunks_overlap(pred, gold),
    }
    if verdict == "resolved":
        category = "resolved"
    elif not row["read_gold"]:
        category = "never_read_gold_file"
    elif not prediction and agent == "pcr" and not row["selected_gold"]:
        category = "read_gold_not_selected"
    elif not prediction:
        category = "no_applicable_patch"
    elif not row["edited_gold"]:
        category = "read_gold_not_selected"
    elif not row["hunk_overlap"]:
        category = "wrong_location"
    else:
        category = "right_location_wrong_fix"
    row["category"] = category
    return row


def diagnose_batch(batch: Path, gold: dict[str, str]) -> tuple[dict, list[dict]]:
    batch = Path(batch)
    manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    verdicts = {}
    official = batch / "official_eval.json"
    if official.is_file():
        verdicts = json.loads(official.read_text(encoding="utf-8")).get("tasks", {})
    rows = []
    for iid in manifest["instance_ids"]:
        status_path = batch / iid / "run_status.json"
        status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {
            "instance_id": iid, "status": "missing"}
        status.setdefault("instance_id", iid)
        status.setdefault("agent", manifest.get("agent"))
        if iid not in gold:
            raise ValueError(f"{iid} not in the gold split; wrong --dataset/--split?")
        row = diagnose_task(status, _prediction(batch / iid), gold[iid], verdicts.get(iid))
        row["prediction"] = _prediction(batch / iid)
        rows.append(row)
    return manifest, rows


def summarize(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    n = len(rows) or 1
    return {
        "tasks": len(rows),
        "read_gold_rate": round(sum(r["read_gold"] for r in rows) / n, 3),
        "selected_gold_rate": round(sum(r["selected_gold"] for r in rows) / n, 3),
        "edited_gold_rate": round(sum(r["edited_gold"] for r in rows) / n, 3),
        "hunk_overlap_rate": round(sum(r["hunk_overlap"] for r in rows) / n, 3),
        "categories": {c: sum(r["category"] == c for r in rows) for c in CATEGORIES},
    }


def render_markdown(results: list[tuple[str, dict, list[dict]]], gold: dict[str, str]) -> str:
    out = ["# Patch diagnosis (gold used for scoring only)", ""]
    for name, summary, _ in results:
        out.append(f"## {name}")
        out.append("")
        out.append(f"- read gold file: {summary['read_gold_rate']:.0%}, "
                   f"selected: {summary['selected_gold_rate']:.0%}, "
                   f"edited: {summary['edited_gold_rate']:.0%}, "
                   f"hunk overlap: {summary['hunk_overlap_rate']:.0%}")
        for cat, count in summary["categories"].items():
            out.append(f"- {cat}: {count}")
        out.append("")
    for name, _, rows in results:
        for row in rows:
            if not row["prediction"]:
                continue
            out += [f"### {name} / {row['instance_id']}: {row['category']} ({row['official']})", "",
                    "Model patch:", "```diff", row["prediction"].rstrip(), "```", "",
                    "Gold patch:", "```diff", gold[row["instance_id"]].rstrip(), "```", ""]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("batches", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path,
                        help="output prefix OUTSIDE the batch dirs, e.g. /data/analysis/pilot-v2")
    args = parser.parse_args(argv)
    for batch in args.batches:
        if args.out.resolve().is_relative_to(batch.resolve()):
            parser.error("--out must not be inside a batch directory")
    manifests = [json.loads((b / "manifest.json").read_text(encoding="utf-8")) for b in args.batches]
    keys = {(m.get("dataset"), m.get("split", "dev")) for m in manifests}
    if len(keys) != 1:
        parser.error(f"batches come from different datasets/splits: {sorted(keys)}")
    dataset, split = keys.pop()
    gold = load_gold(dataset, split)
    results = []
    for batch in args.batches:
        _, rows = diagnose_batch(batch, gold)
        summary = summarize(rows)
        results.append((batch.name, summary, rows))
        print(f"{batch.name:24s} read_gold={summary['read_gold_rate']:.0%} "
              f"selected={summary['selected_gold_rate']:.0%} edited={summary['edited_gold_rate']:.0%} "
              f"hunk_overlap={summary['hunk_overlap_rate']:.0%}")
        for cat, count in summary["categories"].items():
            print(f"    {cat:26s} {count}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {name: {"summary": s, "tasks": [{k: v for k, v in r.items() if k != "prediction"}
                                                for r in rows]} for name, s, rows in results}
    args.out.with_suffix(".json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.out.with_suffix(".md").write_text(render_markdown(results, gold), encoding="utf-8")
    print(f"wrote {args.out.with_suffix('.json')} and {args.out.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
