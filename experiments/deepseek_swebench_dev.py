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
from patchloop_task2.coder import permitted_paths
from patchloop_task2.loop import _coder
from patchloop_task2.normalizer import normalize_hunk_counts
from patchloop_task2.reviewer import review_failure
from patchloop_task2.workspace import apply_candidate
from pipeline_agent import run_localization
from swebench_dev import (
    DATASET_ID, DEVELOPMENT_SPLIT, checkout_dev_task, make_prediction,
    select_dev_task,
)

INSTANCE_ID = "sqlfluff__sqlfluff-4764"
EXPECTED_REPO = "sqlfluff/sqlfluff"
EXPECTED_BASE = "a820c139ccbe6d1865d73c4a459945cd69899f8f"
MAX_PLANNER_STEPS = 14


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



def _evidence_coverage_summary(messages: list[dict]) -> str:
    """Summarize ONLY actual successful read_file line coverage, not gold code."""
    summaries = []
    prefix = "Tool evidence (untrusted): "
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if not isinstance(content, str) or not content.startswith(prefix):
            continue
        try:
            entry = json.loads(content[len(prefix):])
            if entry.get("tool") != "read_file":
                continue
            result = entry.get("result", {})
            if not result.get("ok"):
                continue
            numbers = sorted({
                line.get("line_number")
                for line in result.get("lines", [])
                if isinstance(line, dict)
                and type(line.get("line_number")) is int
            })
            if not numbers:
                continue
            ranges = []
            start = end = numbers[0]
            for number in numbers[1:]:
                if number == end + 1:
                    end = number
                else:
                    ranges.append(f"{start}-{end}")
                    start = end = number
            ranges.append(f"{start}-{end}")
            path = str(result.get("file_path", ""))[:180]
            summaries.append(
                f"{entry.get('id')}: {path}: "
                + ",".join(ranges[:12])
            )
        except (TypeError, ValueError, AttributeError):
            continue
    return "; ".join(summaries[-12:])[:3000]


def _planner_request_messages(messages: list[dict], round_number: int) -> list[dict]:
    """Ask for a final plan grounded in exact observed line ranges, not gold."""
    if round_number < 10:
        return messages
    coverage = _evidence_coverage_summary(messages)
    return [*messages, {
        "role": "user",
        "content": (
            "STOP SEARCHING. Your NEXT response must be one JSON action='final' "
            "using the required schema. Prefer 1-2 candidate entries, avoid "
            "duplicate file entries. For EACH candidate, select a real cited "
            "read_file evidence ID whose file path MATCHES the candidate and "
            "set relevant_lines to a short inclusive span FULLY CONTAINED in "
            "the successfully read source lines. Here are the only available "
            "read_file evidence IDs and their exactly observed line ranges: "
            + (coverage or "(none)") + ". "
            "Do not cite lines outside these ranges. If none is appropriate, "
            "return suspected_files=[] and explain in limitations. No more "
            "search_repo/read_file actions. Do not invent evidence or fixes."
        ),
    }]


def _minimal_coder_messages(messages: list[dict]) -> list[dict]:
    """Bound diff scope without supplying a gold patch or altering source evidence."""
    return [*messages, {
        "role": "user",
        "content": (
            "Return ONLY a minimal, complete, correctly formatted Git unified diff. "
            "Fix the SINGLE most directly evidenced code path first. "
            "Do not rewrite or reproduce entire functions or files. "
            "Use no more than 3 hunks and at most 60 changed (+/-) lines total; "
            "preserve surrounding existing code verbatim. "
            "Make each @@ hunk's old/new line counts exactly match its included "
            "context, removals and additions, otherwise git apply will reject it. "
            "No markdown, explanation, placeholder ellipses, file additions or "
            "commands. The patch must apply to the provided historical Base Commit."
        ),
    }]



def run_real_dev(
    output_dir: str | Path, *,
    api=None, task_loader=select_dev_task, checkout_fn=checkout_dev_task,
    instance_id: str = INSTANCE_ID,
    expected_repo: str | None = EXPECTED_REPO,
    expected_base: str | None = EXPECTED_BASE,
    dataset_id: str = DATASET_ID,
    split: str = DEVELOPMENT_SPLIT,
) -> dict:
    """Use real model API by default; injectable dependencies are for offline unit tests.

    Defaults reproduce the original single sqlfluff instance. Batch runs pass
    another dev instance; expected_repo/expected_base=None skips those pins
    (the instance ID must still match exactly).
    """
    target = Path(output_dir).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError("Output directory must be new or empty to avoid stale predictions")
    target.mkdir(parents=True, exist_ok=True)

    report = {
        "experiment": "patchloop-deepseek-real-swebench-full-dev-v1",
        "instance_id": instance_id,
        "dataset": dataset_id,
        "split": split,
        "repo": expected_repo,
        "base_commit": expected_base,
        "status": "not_started",
        "live_api_preflight": False,
        "planner_calls": 0,
        "coder_calls": 0,
        "attempt_count": 0,
        "reviewer_calls": 0,
        "candidate_attempts": [],
        "patch_status": "not_started",
        "patch_sha256": None,
        "source_checkout_clean": None,
        "official_evaluated": False,
        "official_resolved": None,
        "prediction_available": False,
        "model": "deepseek-flash",
        "model_calls": [],
        "planner_action_trace": [],
    }

    stage = "api_initialization"
    began = time.monotonic()
    live = None
    try:
        live = api if api is not None else LiveDeepSeek(max_calls=16, coder_max_tokens=5500)
        report["model"] = live.model
        stage = "load_official_dev_task"
        task = task_loader(instance_id=instance_id)
        if (
            task.instance_id != instance_id
            or (expected_repo is not None and task.repo != expected_repo)
            or (expected_base is not None
                and task.base_commit.lower() != expected_base.lower())
        ):
            raise RuntimeError("DEV_TASK_MISMATCH: official instance fields changed")
        report["repo"] = task.repo
        report["base_commit"] = task.base_commit
        stage = "checkout_real_base_commit"
        with tempfile.TemporaryDirectory(prefix="patchloop-deepseek-swebench-dev-") as temp:
            checkout = checkout_fn(task, Path(temp) / "checkout")
            stage = "live_api_preflight"
            live.complete(
                "preflight", [{"role": "user", "content": "Reply with the word API_OK."}],
            )
            report["live_api_preflight"] = True
            stage = "real_planner_localization"
            def planner_completion(messages):
                # Log only action metadata and prior validation feedback.
                # Never persist issue text, source lines or untrusted model output.
                next_round = len(report["planner_action_trace"]) + 1
                raw = live.complete(
                    "planner", _planner_request_messages(messages, next_round)
                )
                event = {
                    "round": next_round,
                    "finalization_requested": next_round >= 10,
                }
                try:
                    decoded = json.loads(raw)
                    if isinstance(decoded, dict):
                        event["action"] = str(decoded.get("action", "unknown"))[:35]
                        args = decoded.get("arguments")
                        if isinstance(args, dict):
                            if isinstance(args.get("query"), str):
                                event["search_query"] = args["query"][:80]
                            if isinstance(args.get("relative_path"), str):
                                event["read_path"] = args["relative_path"][:160]
                        if event["action"] == "final":
                            plan_fields = decoded.get("plan")
                            if isinstance(plan_fields, dict):
                                suspects = plan_fields.get("suspected_files")
                                event["candidate_count"] = (
                                    len(suspects) if isinstance(suspects, list) else None
                                )
                    else:
                        event["action"] = "non_object"
                except ValueError:
                    event["action"] = "invalid_json"
                if messages and messages[-1].get("role") == "user":
                    previous = messages[-1].get("content", "")
                    if previous.startswith("Protocol validation error:"):
                        event["prior_protocol_error"] = previous[:140]
                report["planner_action_trace"].append(event)
                return raw

            plan = run_localization(
                task.problem_statement, str(checkout), task.base_commit,
                completion=planner_completion, max_steps=MAX_PLANNER_STEPS,
                search_result_limit=5, search_context_limit=1,
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
                # Task 3-style repair feedback for APPLY failures only.
                # No tests run here; only the official evaluator can grade the issue.
                allowed = permitted_paths(plan)
                patch_path = target / "candidate.patch"
                revision = None
                for attempt in (1, 2):
                    stage = "real_coder_patch"
                    proposal = _coder(
                        task.problem_statement, plan,
                        completion=lambda messages: live.complete(
                            "coder", _minimal_coder_messages(messages)
                        ), revision=revision,
                    )
                    raw_patch_sha256 = hashlib.sha256(
                        proposal.encode("utf-8")
                    ).hexdigest()
                    # Only @@ metadata counts are normalized. Actual proposed
                    # code lines are never edited by the harness.
                    proposal, corrected_headers = normalize_hunk_counts(proposal)
                    applied = apply_candidate(
                        checkout, task.base_commit, proposal,
                        export_path=patch_path, allowed_paths=allowed,
                    )
                    report["attempt_count"] = attempt
                    report["patch_status"] = applied.status
                    candidate = {
                        "attempt": attempt,
                        "patch_sha256": applied.patch_sha256,
                        "raw_model_patch_sha256": raw_patch_sha256,
                        "hunk_header_corrections": corrected_headers,
                        "patch_status": applied.status,
                        "error_code": applied.error_code,
                        "changed_files": list(applied.changed_files),
                    }
                    report["candidate_attempts"].append(candidate)
                    if applied.status == "applied":
                        stage = "write_official_prediction"
                        patch = patch_path.read_text(encoding="utf-8")
                        prediction = make_prediction(
                            task.instance_id, patch, model=live.model,
                        )
                        (target / "predictions.jsonl").write_text(
                            json.dumps(prediction, ensure_ascii=False) + "\n",
                            encoding="utf-8",
                        )
                        report["patch_sha256"] = hashlib.sha256(
                            patch.encode("utf-8")
                        ).hexdigest()
                        report["patch_size_bytes"] = patch_path.stat().st_size
                        report["prediction_available"] = True
                        report["status"] = "prediction_ready"
                        break
                    report["patch_error_code"] = applied.error_code
                    report["patch_error_message"] = str(
                        applied.error_message or ""
                    )[:500]
                    if applied.status == "workspace_failed":
                        report["status"] = "workspace_error"
                        break
                    if attempt == 2:
                        report["status"] = "patch_failed"
                        break
                    stage = "real_reviewer_apply_diagnosis"
                    failure = {
                        "stage": "apply",
                        "status": applied.status,
                        "error_code": applied.error_code,
                        "log_tail": str(applied.error_message or "")[:1200],
                    }
                    feedback = review_failure(
                        task.problem_statement, plan, proposal, failure,
                        completion=live.callback("reviewer"),
                    )
                    candidate["reviewer_failure_type"] = feedback["failure_type"]
                    revision = {
                        "previous_patch": proposal[:10000],
                        "failure": failure,
                        "reviewer": feedback,
                    }
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
            report["reviewer_calls"] = sum(
                call["stage"] == "reviewer" for call in live.calls
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
