"""Batch PatchLoop inference over SWE-bench Lite DEV (proposal: smoke -> pilot).

Each task runs the same single-instance pipeline as `qwen_small_dev --mode dev`
(Planner -> Coder -> Reviewer apply-retry, up to 2 candidates) with a FRESH model
backend, so per-task call/token budgets are identical and independent.

    python -m experiments.lite_batch --out /root/autodl-tmp/lite-dev-smoke-01 --limit 5
    python -m experiments.lite_batch --out ... --workers 4       # 4 tasks at once (7B, 24 GiB)
    python -m experiments.lite_batch --out ... --resume          # continue after a crash
    python -m experiments.lite_batch --list-repos                # repos to mirror first

Outputs in --out:
  manifest.json        what was run (task IDs, model, PatchLoop git commit, budgets)
  <instance_id>/       run_status.json (+ candidate.patch, predictions.jsonl)
  results.jsonl        one summary line per finished task
  all_preds.jsonl      every prediction, ready for the official SWE-bench harness
  summary.json         status counts and totals

Only the dev split is ever loaded. "prediction_ready" means a Git-applicable
candidate, NOT a resolved issue; only the official evaluator decides that.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import threading
import time
from typing import Callable, Iterable

from swebench_dev import DEVELOPMENT_SPLIT, LITE_DATASET_ID, DevelopmentTask, load_dev_tasks

EXPERIMENT = "patchloop-lite-dev-batch-v1"
MAX_WORKERS = 16
SUMMARY_FIELDS = (
    "instance_id", "repo", "agent", "status", "patch_status", "suspected_files",
    "planner_calls", "coder_calls", "reviewer_calls", "agent_calls", "attempt_count",
    "prompt_tokens", "completion_tokens", "reasoning_tokens", "duration_seconds",
    "prediction_available", "failed_stage", "error",
)


def select_tasks(tasks: list[DevelopmentTask], *, instance_ids: Iterable[str] | None = None,
                 limit: int | None = None) -> list[DevelopmentTask]:
    """Deterministic subset: explicit IDs in the given order, else the first `limit`."""
    if instance_ids:
        wanted = list(dict.fromkeys(instance_ids))
        by_id = {task.instance_id: task for task in tasks}
        missing = [item for item in wanted if item not in by_id]
        if missing:
            raise ValueError(f"Not in the dev split: {', '.join(missing)}")
        chosen = [by_id[item] for item in wanted]
    else:
        chosen = list(tasks)
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be >= 1")
        chosen = chosen[:limit]
    return chosen


def _patchloop_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parents[1]), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def build_manifest(tasks: list[DevelopmentTask], *, dataset_id: str,
                   settings: dict) -> dict:
    return {
        "experiment": EXPERIMENT,
        "dataset": dataset_id,
        "split": DEVELOPMENT_SPLIT,
        "instance_ids": [task.instance_id for task in tasks],
        "task_count": len(tasks),
        "patchloop_commit": _patchloop_commit(),
        "python": platform.python_version(),
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **settings,
    }


def _summary_line(report: dict) -> dict:
    return {key: report.get(key) for key in SUMMARY_FIELDS}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_batch(tasks: list[DevelopmentTask], out_dir: Path, *,
              run_one: Callable[[DevelopmentTask, Path], dict],
              manifest: dict, resume: bool = False, workers: int = 1,
              log: Callable[[str], None] = print) -> dict:
    """Run tasks (in parallel when workers > 1); tasks in results.jsonl are skipped on resume."""
    if type(workers) is not int or not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be an integer from 1 to {MAX_WORKERS}")
    out_dir = Path(out_dir).expanduser().resolve()
    manifest_path = out_dir / "manifest.json"
    if out_dir.exists() and any(out_dir.iterdir()):
        if not resume:
            raise ValueError("--out must be new or empty (use --resume to continue a batch)")
        if not manifest_path.exists():
            raise ValueError("--resume target has no manifest.json; not a batch directory")
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("instance_ids") != manifest["instance_ids"]:
            raise ValueError("--resume task list differs from the existing manifest")
        manifest = {**previous, "resumed_at": manifest["started_at"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    results_path = out_dir / "results.jsonl"
    done = {line["instance_id"] for line in _read_jsonl(results_path)}
    began = time.monotonic()
    lock = threading.Lock()  # guards results.jsonl appends and log lines

    pending = []
    for index, task in enumerate(tasks, 1):
        task_dir = out_dir / task.instance_id
        if task.instance_id in done:
            log(f"[{index}/{len(tasks)}] {task.instance_id}: already done, skipping")
            continue
        if task_dir.exists():
            # Interrupted mid-task: keep the evidence, retry in a fresh directory.
            task_dir.rename(out_dir / f"{task.instance_id}.interrupted-{int(time.time())}")
        pending.append((index, task, task_dir))

    def run_and_record(index: int, task: DevelopmentTask, task_dir: Path) -> None:
        with lock:
            log(f"[{index}/{len(tasks)}] {task.instance_id} ({task.repo}) ...")
        t0 = time.monotonic()
        try:
            report = run_one(task, task_dir)
        except Exception as exc:  # run_real_dev catches its own errors; this is a last resort
            report = {"instance_id": task.instance_id, "repo": task.repo,
                      "status": "batch_error", "error": f"{type(exc).__name__}: {exc}"[:500]}
            task_dir.mkdir(parents=True, exist_ok=True)
            (task_dir / "run_status.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        line = _summary_line({"repo": task.repo, **report, "instance_id": task.instance_id})
        with lock:
            with results_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
            log(f"    [{index}/{len(tasks)}] {task.instance_id} -> {line['status']} "
                f"in {time.monotonic() - t0:.1f}s")

    if workers <= 1:
        for item in pending:
            run_and_record(*item)
    else:
        # Each task has its own checkout, worktrees and model backend; the only shared
        # resource is the vLLM server, which batches concurrent requests.
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="lite-task")
        futures = [pool.submit(run_and_record, *item) for item in pending]
        try:
            for future in as_completed(futures):
                future.result()  # re-raise KeyboardInterrupt/SystemExit from a worker
        except BaseException:
            # Stop scheduling new tasks, then let in-flight ones finish and record their
            # results BEFORE re-raising, so nothing appends to results.jsonl after we
            # return (a later --resume would otherwise rerun or duplicate them). The
            # interpreter would join these threads at exit anyway; a second Ctrl+C
            # aborts the wait, and unfinished dirs are retried on --resume.
            with lock:
                log("Interrupted: waiting for in-flight tasks to finish (Ctrl+C again to abort)")
            pool.shutdown(wait=True, cancel_futures=True)
            raise
        pool.shutdown(wait=True)

    return write_summary(out_dir, tasks, elapsed=time.monotonic() - began)


def write_summary(out_dir: Path, tasks: list[DevelopmentTask], *, elapsed: float) -> dict:
    lines = {line["instance_id"]: line for line in _read_jsonl(out_dir / "results.jsonl")}
    predictions = []
    for task in tasks:
        pred = out_dir / task.instance_id / "predictions.jsonl"
        if task.instance_id in lines and lines[task.instance_id].get("status") == "prediction_ready" and pred.exists():
            predictions.extend(_read_jsonl(pred))
    (out_dir / "all_preds.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in predictions), encoding="utf-8")
    statuses = Counter(line.get("status") for line in lines.values())
    finished = len(lines)
    summary = {
        "experiment": EXPERIMENT,
        "tasks_total": len(tasks),
        "tasks_finished": finished,
        "status_counts": dict(sorted(statuses.items())),
        "prediction_ready": statuses.get("prediction_ready", 0),
        "prediction_ready_rate": round(statuses.get("prediction_ready", 0) / finished, 4) if finished else None,
        "localized_any_file": sum(1 for line in lines.values() if line.get("suspected_files")),
        "prompt_tokens": sum(int(line.get("prompt_tokens") or 0) for line in lines.values()),
        "completion_tokens": sum(int(line.get("completion_tokens") or 0) for line in lines.values()),
        "reasoning_tokens": sum(int(line.get("reasoning_tokens") or 0) for line in lines.values()),
        "model_seconds_total": round(sum(float(line.get("duration_seconds") or 0) for line in lines.values()), 1),
        "this_session_seconds": round(elapsed, 1),
        "official_evaluated": False,
        "note": "prediction_ready = Git-applicable candidate, not an official resolution.",
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", help="New output directory (or existing one with --resume)")
    parser.add_argument("--dataset", default=LITE_DATASET_ID,
                        choices=(LITE_DATASET_ID, "princeton-nlp/SWE-bench"))
    parser.add_argument("--instances", help="Comma-separated instance IDs (default: dataset order)")
    parser.add_argument("--limit", type=int, help="Run only the first N selected tasks")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--agent", choices=("pcr", "single"), default="pcr",
                        help="pcr = Planner-Coder-Reviewer (default); single = single-agent baseline (RQ3)")
    parser.add_argument("--edit-format", choices=("diff", "search_replace"), default="diff",
                        help="Coder output: unified diff (default) or SEARCH/REPLACE blocks")
    parser.add_argument("--workers", type=int, default=1,
                        help=f"Tasks run concurrently against vLLM (1..{MAX_WORKERS}; 4 suits 7B on a 24 GiB GPU)")
    parser.add_argument("--backend", choices=("qwen", "deepseek"), default="qwen",
                        help="qwen = local vLLM (default); deepseek = DeepSeek API (DEEPSEEK_API_KEY)")
    parser.add_argument("--reasoning-effort", choices=("none", "low", "high", "max"),
                        help="deepseek only (RQ1): thinking effort; default DEEPSEEK_REASONING_EFFORT "
                             "or none (= thinking disabled)")
    parser.add_argument("--retrieval-k", type=int, default=0,
                        help="Give both agents the top-K files from BM25 + issue-hint retrieval "
                             "(utils.retrieval) in their first message; 0 = off (default)")
    parser.add_argument("--list-repos", action="store_true",
                        help="Print the GitHub repos of the selected tasks and exit (for mirroring)")
    args = parser.parse_args()

    tasks = select_tasks(
        load_dev_tasks(args.dataset),
        instance_ids=[item.strip() for item in args.instances.split(",") if item.strip()] if args.instances else None,
        limit=args.limit,
    )
    if args.list_repos:
        for repo in sorted({task.repo for task in tasks}):
            print(repo)
        return 0
    if not args.out:
        parser.error("--out is required")
    if not 0 <= args.retrieval_k <= 50:
        parser.error("--retrieval-k must be in [0, 50]")

    from experiments.qwen_small_dev import run_qwen_dev
    from patchloop_task2.backends import load_settings, make_backend
    from patchloop_task2.qwen_small import STAGE_TOKENS

    if args.reasoning_effort not in (None, "none") and args.backend != "deepseek":
        parser.error("--reasoning-effort low/high/max needs --backend deepseek")
    settings = load_settings(args.backend, reasoning_effort=args.reasoning_effort)
    make_backend(args.backend, settings).verify()  # fail fast before any task if the model is down
    by_id = {task.instance_id: task for task in tasks}

    def run_one(task: DevelopmentTask, task_dir: Path) -> dict:
        backend = make_backend(args.backend, settings)  # fresh per-task call and token budget
        return run_qwen_dev(
            backend, task_dir, agent=args.agent,
            instance_id=task.instance_id, expected_repo=task.repo,
            expected_base=task.base_commit, dataset_id=args.dataset,
            task_loader=lambda instance_id: by_id[instance_id],
            edit_format=args.edit_format,
            **({"retrieval_k": args.retrieval_k} if args.retrieval_k else {}),
        )

    manifest = build_manifest(tasks, dataset_id=args.dataset, settings={
        "backend": args.backend,
        "model": settings.model,
        "endpoint": settings.endpoint,
        "max_calls_per_task": settings.max_calls,
        "context_chars": settings.context_chars,
        "timeout_seconds": settings.timeout_seconds,
        "stage_max_tokens": STAGE_TOKENS,
        # Ignored by DeepSeek in thinking mode (low/high/max): those runs are sampled.
        "temperature": 0,
        "reasoning_effort": getattr(settings, "reasoning_effort", "none"),
        "reasoning_tokens_per_call": getattr(settings, "reasoning_tokens_per_call", 0),
        "reasoning_budget_per_task": getattr(settings, "reasoning_budget", 0),
        "agent": args.agent,
        "max_candidates": 2,
        "docker_tests": False,
        "edit_format": args.edit_format,
        "retrieval_k": args.retrieval_k,
        # Greedy decoding can still differ slightly between batch sizes in vLLM.
        "workers": args.workers,
    })
    summary = run_batch(tasks, Path(args.out), run_one=run_one, manifest=manifest,
                        resume=args.resume, workers=args.workers)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
