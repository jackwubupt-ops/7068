"""Offline recall of utils.retrieval against the gold files (no model, no GPU).

    python -m experiments.retrieval_recall --out /data/analysis/retrieval-lite-dev

For each dev task: check out the base commit (local mirrors), rank files with
utils.retrieval.rank_files (issue text + repository only), and report at which
rank the first gold-edited file appears. Prints recall@1/3/5/10/20 and writes
per-task ranks to <out>.json.

ANALYSIS ONLY, like experiments.diagnose_patches: the gold patch is used to
SCORE retrieval, never as an input to it, and no inference module imports this
script (see tests/test_diagnose_patches.py).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import time

from experiments.diagnose_patches import load_gold, patch_hunks
from swebench_dev import LITE_DATASET_ID, checkout_dev_task, load_dev_tasks
from utils.retrieval import rank_files

KS = (1, 3, 5, 10, 20)


def gold_rank(ranked: list[dict], gold_files: set[str]) -> int | None:
    for index, item in enumerate(ranked, 1):
        if item["file_path"] in gold_files:
            return index
    return None


def recall_table(ranks: list[int | None]) -> dict:
    n = len(ranks) or 1
    return {f"recall@{k}": round(sum(1 for r in ranks if r is not None and r <= k) / n, 3) for k in KS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dataset", default=LITE_DATASET_ID,
                        choices=(LITE_DATASET_ID, "princeton-nlp/SWE-bench"))
    parser.add_argument("--instances", help="Comma-separated instance IDs (default: all dev tasks)")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    tasks = load_dev_tasks(args.dataset)
    if args.instances:
        wanted = {i.strip() for i in args.instances.split(",") if i.strip()}
        tasks = [t for t in tasks if t.instance_id in wanted]
    gold = load_gold(args.dataset, "dev")
    rows = []
    for task in tasks:
        gold_files = set(patch_hunks(gold[task.instance_id]))
        t0 = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="patchloop-retrieval-") as temp:
            checkout = checkout_dev_task(task, Path(temp) / "checkout")
            ranked = rank_files(checkout, task.problem_statement, max(KS))
        rank = gold_rank(ranked, gold_files)
        rows.append({"instance_id": task.instance_id, "gold_files": sorted(gold_files), "rank": rank,
                     "top5": [r["file_path"] for r in ranked[:5]],
                     "seconds": round(time.monotonic() - t0, 1)})
        print(f"{task.instance_id:40s} gold rank = {rank if rank else '>20'}  ({rows[-1]['seconds']}s)")
    table = recall_table([r["rank"] for r in rows])
    print(json.dumps(table))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".json").write_text(
        json.dumps({"dataset": args.dataset, "recall": table, "tasks": rows}, indent=2), encoding="utf-8")
    print(f"wrote {args.out.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
