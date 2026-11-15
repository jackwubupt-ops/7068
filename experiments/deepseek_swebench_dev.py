"""One REAL DeepSeek attempt on one official SWE-bench FULL-dev issue.

Never use the benchmark's gold patch, test_patch, FAIL_TO_PASS or hints for
inference. This step exports a candidate; the OFFICIAL harness is separate.

    python -m experiments.deepseek_swebench_dev --out /tmp/swebench-live-001
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time

from experiments.live_deepseek import LiveDeepSeek, _safe_error
from patchloop_task2.runner import apply_repair_plan
from pipeline_agent import run_localization
from swebench_dev import (
    DATASET_ID, DEVELOPMENT_SPLIT, checkout_dev_task, make_prediction,
    select_dev_task,
)

INSTANCE_ID = "sqlfluff__sqlfluff-4764"
EXPECTED_REPO = "sqlfluff/sqlfluff"
EXPECTED_BASE = "a820c139ccbe6d1865d73c4a459945cd69899f8f"
MAX_PLANNER_STEPS = 8


def _clean_source(path: Path, base: str) -> bool:
    status = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True, text=True, timeout=15,
    )
    head = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=15,
    )
    return (
        status.returncode == 0 and status.stdout.strip() == ""
        and head.returncode == 0 and head.stdout.strip().lower() == base.lower()
    )


def run_real_dev(
    output_dir: str | Path, *,
    api=None, task_loader=select_dev_task, checkout_fn=checkout_dev_task,
) -> dict:
    """Use real model API by default; injectable dependencies are for offline unit tests."""
    target = Path(output_dir).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError("Output directory must be new or empty to avoid stale predictions")
    target.mkdir(parents=True, exist_ok=True)

    report = {
        "experiment": "patchloop-deepseek-real-swebench-full-dev-v1",
        "instance_id": INSTANCE_ID,
        "dataset": DATASET_ID,
        "split": DEVELOPMENT_SPLIT,
        "repo": EXPECTED_REPO,
        "base_commit": EXPECTED_BASE,
        "status": "not_started",
        "live_api_preflight": False,
        "planner_calls": 0,
        "coder_calls": 0,
        "attempt_count": 0,
        "patch_status": "not_started",
        "patch_sha256": None,
        "source_checkout_clean": None,
        "official_evaluated": False,
        "official_resolved": None,
        "prediction_available": False,
        "model": "deepseek-flash",
        "model_calls": [],
    }

    stage = "api_initialization"
    began = time.monotonic()
    live = None
    try:
        live = api if api is not None else LiveDeepSeek()
        report["model"] = live.model
        stage = "load_official_dev_task"
        task = task_loader(instance_id=INSTANCE_ID)
        if (
            task.instance_id != INSTANCE_ID or task.repo != EXPECTED_REPO
            or task.base_commit.lower() != EXPECTED_BASE
        ):
            raise RuntimeError("DEV_TASK_MISMATCH: official instance fields changed")
        stage = "checkout_real_base_commit"
        with tempfile.TemporaryDirectory(prefix="patchloop-deepseek-swebench-dev-") as temp:
            checkout = checkout_fn(task, Path(temp) / "checkout")
            stage = "live_api_preflight"
            live.complete(
                "preflight", [{"role": "user", "content": "Reply with the word API_OK."}],
            )
            report["live_api_preflight"] = True
            stage = "real_planner_localization"
            plan = run_localization(
                task.problem_statement, str(checkout), task.base_commit,
                completion=live.callback("planner"), max_steps=MAX_PLANNER_STEPS,
            )
            files = plan.get("suspected_files", [])
            report["suspected_file_count"] = len(files)
            # This list is only the actual model's localization, not a gold hint.
            report["suspected_files"] = [
                entry.get("file_path") for entry in files if isinstance(entry, dict)
            ]
            if not files:
                report["status"] = "no_candidate_files"
                report["patch_status"] = "not_attempted"
            else:
                stage = "real_coder_patch"
                patch_path = target / "candidate.patch"
                applied = apply_repair_plan(
                    task.problem_statement, plan,
                    coder_completion=live.callback("coder"),
                    export_path=patch_path,
                )
                report["attempt_count"] = 1
                report["patch_status"] = applied["status"]
                if applied["status"] != "applied":
                    report["status"] = "patch_failed"
                    report["patch_error_code"] = applied.get("error_code")
                    report["patch_error_message"] = str(applied.get("error_message", ""))[:500]
                else:
                    stage = "write_official_prediction"
                    patch = patch_path.read_text(encoding="utf-8")
                    prediction = make_prediction(
                        task.instance_id, patch, model=live.model,
                    )
                    prediction_path = target / "predictions.jsonl"
                    prediction_path.write_text(
                        json.dumps(prediction, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                    report["patch_sha256"] = hashlib.sha256(
                        patch.encode("utf-8")
                    ).hexdigest()
                    report["patch_size_bytes"] = patch_path.stat().st_size
                    report["prediction_available"] = True
                    report["status"] = "prediction_ready"
            report["source_checkout_clean"] = _clean_source(
                checkout, task.base_commit,
            )
            if not report["source_checkout_clean"]:
                report["status"] = "source_isolation_violation"
                report["prediction_available"] = False
                (target / "predictions.jsonl").unlink(missing_ok=True)
    except Exception as exc:
        report["failed_stage"] = stage
        report["error"] = _safe_error(exc)
        report["status"] = (
            "missing_credentials"
            if "MISSING_DEEPSEEK_API_KEY" in str(exc)
            else "experiment_error"
        )
    finally:
        if live is not None:
            report["model_calls"] = list(live.calls)
            report["planner_calls"] = sum(
                call["stage"] == "planner" for call in live.calls
            )
            report["coder_calls"] = sum(
                call["stage"] == "coder" for call in live.calls
            )
            report["prompt_tokens"] = sum(
                int(call.get("prompt_tokens") or 0) for call in live.calls
            )
            report["completion_tokens"] = sum(
                int(call.get("completion_tokens") or 0) for call in live.calls
            )
        report["duration_seconds"] = round(time.monotonic() - began, 2)
        (target / "run_status.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="New directory OUTSIDE source repository")
    args = parser.parse_args()
    report = run_real_dev(args.out)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # Exit 0 only for a real API-generated, git-applicable prediction, NOT a resolution.
    return 0 if report["status"] == "prediction_ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
