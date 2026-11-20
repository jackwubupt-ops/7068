"""Official SWE-bench evaluation of a whole lite_batch output directory (local Docker).

Runs the PINNED official harness (swebench==4.1.0, prebuilt `swebench/sweb.eval.*`
images from Docker Hub) in its OWN virtualenv, then writes `official_eval.json`
next to the batch: one verdict per task over the batch's FULL task list.

    python -m experiments.official_eval --batch /data/runs/lite-pilot-pcr \
        --harness-python /data/venvs/swebench/bin/python --max-workers 4

Denominator rule: every task in manifest.json counts. A task without a
prediction is `no_prediction` (= not resolved). A harness error is
`harness_error` and is reported separately; it is NOT silently counted as a
model failure -- rerun it with a new --run-id before using the numbers.

Integrity: this module only scores finished predictions. Gold tests are used
by the official harness inside Docker; nothing from here ever reaches a prompt.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HARNESS_VERSION = "4.1.0"
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
RESOLVED = "resolved"
TASK_STATUSES = ("resolved", "unresolved", "empty_patch", "harness_error",
                 "not_evaluated", "no_prediction")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_batch(batch: Path) -> tuple[dict, list[dict]]:
    manifest_path = batch / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"{batch} has no manifest.json; not a lite_batch directory")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ids = manifest.get("instance_ids")
    if not isinstance(ids, list) or not ids:
        raise ValueError("manifest.json has no instance_ids")
    preds = read_jsonl(batch / "all_preds.jsonl")
    seen = set()
    for pred in preds:
        iid = pred.get("instance_id")
        if iid not in ids:
            raise ValueError(f"Prediction for {iid!r} is not in the manifest task list")
        if iid in seen:
            raise ValueError(f"Duplicate prediction for {iid}")
        seen.add(iid)
        if not isinstance(pred.get("model_patch"), str):
            raise ValueError(f"Prediction for {iid} has no model_patch string")
    return manifest, preds


def model_label(preds: list[dict]) -> str:
    """The harness names its report after ONE model; all predictions must agree."""
    labels = {pred.get("model_name_or_path") for pred in preds}
    if len(labels) != 1:
        raise ValueError(f"Predictions must share one model_name_or_path, got {sorted(map(str, labels))}")
    label = labels.pop()
    if not isinstance(label, str) or not label:
        raise ValueError("Predictions have no model_name_or_path")
    return label


def report_filename(label: str, run_id: str) -> str:
    return label.replace("/", "__") + f".{run_id}.json"


def classify(manifest: dict, preds: list[dict], report: dict | None, *,
             run_id: str | None = None) -> dict:
    """Per-task verdicts over the manifest's full task list."""
    if report is not None and not isinstance(report, dict):
        raise ValueError("Harness report must be a JSON object")
    report = report or {}

    def ids(key: str) -> set[str]:
        value = report.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"Harness report field {key} must be a list")
        return set(value)

    resolved, unresolved = ids("resolved_ids"), ids("unresolved_ids")
    errors, empty = ids("error_ids"), ids("empty_patch_ids")
    if resolved & unresolved:
        raise ValueError("Harness report lists an instance as both resolved and unresolved")
    predicted = {pred["instance_id"] for pred in preds}
    tasks = {}
    for iid in manifest["instance_ids"]:
        if iid not in predicted:
            status = "no_prediction"
        elif iid in errors:
            status = "harness_error"
        elif iid in resolved:
            status = "resolved"
        elif iid in unresolved:
            status = "unresolved"
        elif iid in empty:
            status = "empty_patch"
        else:
            status = "not_evaluated"
        tasks[iid] = status
    counts = {name: sum(1 for s in tasks.values() if s == name) for name in TASK_STATUSES}
    total = len(tasks)
    complete = counts["harness_error"] == 0 and counts["not_evaluated"] == 0
    return {
        "evaluator": f"swebench=={HARNESS_VERSION} (local Docker, prebuilt images)",
        "run_id": run_id,
        "dataset": manifest.get("dataset"),
        "split": manifest.get("split"),
        "agent": manifest.get("agent"),
        "edit_format": manifest.get("edit_format"),
        "model": manifest.get("model"),
        "total_tasks": total,
        "submitted": len(predicted),
        "resolved": counts["resolved"],
        "resolved_rate": round(counts["resolved"] / total, 4) if total else 0.0,
        "status_counts": counts,
        "complete": complete,
        "note": ("All tasks have a verdict." if complete else
                 "harness_error/not_evaluated present: rerun those with a NEW --run-id; "
                 "do not report this rate as final."),
        "tasks": tasks,
    }


def harness_command(python: str, manifest: dict, preds_path: Path, run_id: str,
                    instance_ids: list[str], *, max_workers: int, timeout: int) -> list[str]:
    return [
        python, "-m", "swebench.harness.run_evaluation",
        "--dataset_name", manifest["dataset"],
        "--split", manifest.get("split", "dev"),
        "--predictions_path", str(preds_path),
        "--instance_ids", *instance_ids,
        "--max_workers", str(max_workers),
        "--timeout", str(timeout),
        "--namespace", "swebench",
        "--cache_level", "env",
        "--run_id", run_id,
    ]


def check_harness_version(python: str) -> str:
    out = subprocess.run(
        [python, "-c", "import importlib.metadata as m; print(m.version('swebench'))"],
        capture_output=True, text=True, timeout=60,
    )
    version = out.stdout.strip()
    if out.returncode != 0 or version != HARNESS_VERSION:
        raise RuntimeError(f"{python} must have swebench=={HARNESS_VERSION} installed "
                           f"(found {version or out.stderr.strip()[:200]!r})")
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", required=True, help="lite_batch output directory")
    parser.add_argument("--harness-python", default=sys.executable,
                        help=f"python of the venv holding swebench=={HARNESS_VERSION}")
    parser.add_argument("--run-id", help="default: <batch dir name>; must be NEW for each attempt")
    parser.add_argument("--max-workers", type=int, default=4, help="<= 75%% of CPU cores")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds per instance")
    parser.add_argument("--classify-only", metavar="REPORT",
                        help="skip the harness; classify an existing harness report JSON")
    args = parser.parse_args(argv)

    batch = Path(args.batch).expanduser().resolve()
    manifest, preds = load_batch(batch)
    run_id = args.run_id or batch.name
    if not SAFE_ID.fullmatch(run_id):
        parser.error("--run-id may only contain letters, digits, '.', '_' and '-'")
    if not 1 <= args.max_workers <= 64:
        parser.error("--max-workers must be 1..64")

    report = None
    if args.classify_only:
        report = json.loads(Path(args.classify_only).read_text(encoding="utf-8"))
    elif preds:
        label = model_label(preds)
        check_harness_version(args.harness_python)
        work = batch / "official"
        work.mkdir(exist_ok=True)
        report_path = work / report_filename(label, run_id)
        if report_path.exists() or (work / "logs" / "run_evaluation" / run_id).exists():
            parser.error(f"run id {run_id!r} was already used in {work}; pass a NEW --run-id "
                         "(the harness silently reuses old per-instance results)")
        cmd = harness_command(args.harness_python, manifest, batch / "all_preds.jsonl", run_id,
                              [p["instance_id"] for p in preds],
                              max_workers=args.max_workers, timeout=args.timeout)
        print("$ " + " ".join(cmd), flush=True)
        # cwd=work: the harness writes its report and logs/ into the current directory.
        code = subprocess.run(cmd, cwd=work, env={**os.environ, "PYTHONNOUSERSITE": "1"}).returncode
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
        else:
            print(f"Harness exited {code} without writing {report_path}", file=sys.stderr)
    else:
        print("No predictions in this batch: every task is no_prediction.")

    result = classify(manifest, preds, report, run_id=run_id)
    (batch / "official_eval.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                                              encoding="utf-8")
    shown = {k: v for k, v in result.items() if k != "tasks"}
    print(json.dumps(shown, indent=2, ensure_ascii=False))
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
