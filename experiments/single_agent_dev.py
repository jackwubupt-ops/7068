"""Single-agent baseline (RQ3) on one SWE-bench dev instance.

Same task loading, checkout, budgets, prediction format and run_status.json
fields as experiments.deepseek_swebench_dev.run_real_dev (the P-C-R pipeline),
so lite_batch can run either and compare them task by task.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time

from experiments.deepseek_swebench_dev import _clean_source
from experiments.live_deepseek import _safe_error
from patchloop_task2.single_agent import run_single_agent
from swebench_dev import (
    DATASET_ID, DEVELOPMENT_SPLIT, checkout_dev_task, make_prediction, select_dev_task,
)

AGENT_MAX_STEPS = 16      # P-C-R: up to 14 Planner turns + 2 Coder + 1 Reviewer
AGENT_MAX_SUBMISSIONS = 2  # P-C-R: up to 2 Coder attempts


def run_single_dev(output_dir: str | Path, *, api, instance_id: str,
                   task_loader=select_dev_task, checkout_fn=checkout_dev_task,
                   expected_repo: str | None = None, expected_base: str | None = None,
                   dataset_id: str = DATASET_ID, split: str = DEVELOPMENT_SPLIT,
                   edit_format: str = "diff", retrieval_k: int = 0) -> dict:
    target = Path(output_dir).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError("Output directory must be new or empty to avoid stale predictions")
    target.mkdir(parents=True, exist_ok=True)
    report = {
        "experiment": "patchloop-single-agent-swebench-dev-v1",
        "agent": "single",
        "instance_id": instance_id,
        "dataset": dataset_id,
        "split": split,
        "repo": expected_repo,
        "base_commit": expected_base,
        "status": "not_started",
        "edit_format": edit_format,
        "agent_max_steps": AGENT_MAX_STEPS,
        "agent_max_submissions": AGENT_MAX_SUBMISSIONS,
        "patch_status": "not_attempted",
        "attempt_count": 0,
        "candidate_attempts": [],
        "agent_action_trace": [],
        "official_evaluated": False,
        "official_resolved": None,
        "prediction_available": False,
        "model": getattr(api, "model", None),
    }
    stage = "load_official_dev_task"
    began = time.monotonic()
    try:
        task = task_loader(instance_id=instance_id)
        if (task.instance_id != instance_id
                or (expected_repo is not None and task.repo != expected_repo)
                or (expected_base is not None and task.base_commit.lower() != expected_base.lower())):
            raise RuntimeError("DEV_TASK_MISMATCH: official instance fields changed")
        report["repo"] = task.repo
        report["base_commit"] = task.base_commit
        stage = "checkout_real_base_commit"
        with tempfile.TemporaryDirectory(prefix="patchloop-single-agent-") as temp:
            checkout = checkout_fn(task, Path(temp) / "checkout")
            candidates = None
            if retrieval_k:
                stage = "retrieval"
                from utils.retrieval import rank_files
                candidates = rank_files(checkout, task.problem_statement, retrieval_k)
                report["retrieval_candidates"] = [c["file_path"] for c in candidates]
            stage = "single_agent"
            patch_path = target / "candidate.patch"
            result = run_single_agent(
                task.problem_statement, checkout, task.base_commit,
                completion=api.callback("agent"), edit_format=edit_format,
                max_steps=AGENT_MAX_STEPS, max_submissions=AGENT_MAX_SUBMISSIONS,
                export_path=patch_path, candidate_files=candidates,
            )
            report["agent_action_trace"] = result.trace
            report["read_files"] = result.read_files
            report["candidate_attempts"] = result.submissions
            report["attempt_count"] = len(result.submissions)
            report["stop_reason"] = result.stop_reason
            # Analogue of P-C-R's suspected_files: files the agent actually edited.
            report["suspected_files"] = sorted(
                {path for item in result.submissions for path in item.get("changed_files", [])})
            if result.submissions:
                report["patch_status"] = result.submissions[-1]["patch_status"]
            report["status"] = result.status
            if result.status == "prediction_ready":
                stage = "write_official_prediction"
                patch = patch_path.read_text(encoding="utf-8")
                prediction = make_prediction(task.instance_id, patch, model=api.model)
                (target / "predictions.jsonl").write_text(
                    json.dumps(prediction, ensure_ascii=False) + "\n", encoding="utf-8")
                report["prediction_available"] = True
                report["patch_size_bytes"] = patch_path.stat().st_size
            report["source_checkout_clean"] = _clean_source(checkout, task.base_commit)
            if not report["source_checkout_clean"]:
                report["status"] = "source_isolation_violation"
                report["prediction_available"] = False
                (target / "predictions.jsonl").unlink(missing_ok=True)
    except Exception as exc:
        report["failed_stage"] = stage
        report["error"] = _safe_error(exc)
        report["status"] = "experiment_error"
    finally:
        calls = list(getattr(api, "calls", []))
        report["model_calls"] = calls
        report["agent_calls"] = sum(call.get("stage") == "agent" for call in calls)
        report["prompt_tokens"] = sum(int(call.get("prompt_tokens") or 0) for call in calls)
        report["completion_tokens"] = sum(int(call.get("completion_tokens") or 0) for call in calls)
        report["duration_seconds"] = round(time.monotonic() - began, 2)
        (target / "run_status.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
