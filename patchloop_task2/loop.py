"""Task 3: Planner -> Coder -> controlled Docker tests -> Reviewer -> Coder.

Each complete candidate patch is validated and applied against the SAME base
commit. Test outcomes are internal feedback, not SWE-bench resolution labels.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import time

from .coder import CoderError, build_messages, extract_diff, permitted_paths
from .execution import DockerTestRunner, DockerTestSpec
from .reviewer import ReviewerError, review_failure
from .validator import PatchValidationError
from .workspace import (
    WorkspaceError, _good_result, _run_git, apply_candidate,
    isolated_worktree, resolve_base,
)


def _operator_output(path, root: Path) -> Path | None:
    if path is None:
        return None
    target = Path(path).expanduser().resolve()
    if target.is_relative_to(root.resolve()):
        raise ValueError("Output files cannot be written into the source repository")
    return target


def _trace(path: Path | None, record: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _coder(issue: str, plan: dict, *,
           completion=None, revision: dict | None = None) -> str:
    messages = build_messages(issue, plan)
    if revision:
        messages.append({
            "role": "user",
            "content": "Previous patch failed. Produce a COMPLETE REPLACEMENT diff "
            "against the ORIGINAL base commit (never an incremental diff):\n"
            + json.dumps(revision, ensure_ascii=False, separators=(",", ":"))[:14000],
        })
    if completion is None:
        from config import get_client, OPENAI_MODEL
        raw = get_client().chat.completions.create(
            model=OPENAI_MODEL, messages=messages, temperature=0,
            max_tokens=3000).choices[0].message.content
    else:
        raw = completion(messages)
    return extract_diff(raw)


def run_from_plan(
    issue: str, plan: dict, spec: DockerTestSpec, *,
    coder_completion=None, reviewer_completion=None,
    test_runner=None, max_candidates: int = 3,
    export_path: str | Path | None = None, trace_path: str | Path | None = None,
) -> dict:
    """Run bounded candidate repair loop. Plan must be Task 1's validated output."""
    if type(max_candidates) is not int or not 1 <= max_candidates <= 3:
        raise ValueError("max_candidates must be in [1,3]")
    if not isinstance(spec, DockerTestSpec):
        raise TypeError("DockerTestSpec must be operator-provided")
    if not isinstance(plan, dict):
        raise ValueError("Expected Task 1 plan")
    if not isinstance(plan.get("repo_root"), str) or not isinstance(plan.get("base_commit"), str):
        raise ValueError("Plan missing repo_root / base_commit")

    repo = Path(plan["repo_root"]).expanduser().resolve()
    base_commit = resolve_base(repo, plan["base_commit"])
    from utils.repo_tools import validate_repository
    validate_repository(repo, base_commit)
    export_file = _operator_output(export_path, repo)
    trace_file = _operator_output(trace_path, repo)
    allowed = permitted_paths(plan)
    runner = test_runner if test_runner is not None else DockerTestRunner()

    result = {
        "status": "not_started", "base_commit": base_commit,
        "attempt_count": 0, "attempts": [],
        "internal_tests_passed": False, "official_evaluated": False,
        "final_patch": None, "exported_patch": None,
    }
    revision = None
    _trace(trace_file, {"event": "start", "base_commit": base_commit,
                        "max_candidates": max_candidates, "image": spec.image,
                        "test_command": list(spec.command)})

    for number in range(1, max_candidates + 1):
        try:
            validate_repository(repo, base_commit)
            patch = _coder(issue, plan, completion=coder_completion, revision=revision)
        except (CoderError, ValueError, OSError, Exception) as exc:
            # A model exception is a model error; no executable actions are attempted.
            result["status"] = "model_error"
            result["error_message"] = str(exc)[:800]
            break
        digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()
        attempt = {"number": number, "patch_sha256": digest, "patch_status": None,
                   "test": None, "reviewer": None}
        result["attempt_count"] = number
        result["attempts"].append(attempt)

        applied = apply_candidate(repo, base_commit, patch, allowed_paths=allowed)
        attempt["patch_status"] = applied.status
        attempt["changed_files"] = applied.changed_files
        _trace(trace_file, {"event": "patch", "attempt": number, "sha256": digest,
                            "status": applied.status,
                            "error_code": applied.error_code})

        failure = None
        if applied.status != "applied":
            if applied.status == "workspace_failed":
                result["status"] = "infrastructure_error"
                result["error_message"] = applied.error_message
                break
            failure = {"stage": "apply", "status": applied.status,
                       "error_code": applied.error_code,
                       "log_tail": applied.error_message or ""}
        else:
            try:
                # Separate clean checkout per candidate. Never accumulate edits.
                with isolated_worktree(repo, base_commit) as wt:
                    _good_result(
                        _run_git(wt, "apply", "--check", "--index", "-", data=patch.encode()),
                        "test checkout patch check",
                    )
                    _good_result(
                        _run_git(wt, "apply", "--index", "-", data=patch.encode()),
                        "test checkout patch apply",
                    )
                    outcome = runner.run(wt, spec)
                    attempt["test"] = outcome.to_dict()
                    _trace(trace_file, {"event": "tests", "attempt": number,
                                        "status": outcome.status, "exit_code": outcome.exit_code,
                                        "duration_seconds": outcome.duration_seconds,
                                        "output_tail": outcome.output_tail[-2000:]})
                    if outcome.status == "passed":
                        if export_file is not None:
                            exported = _good_result(
                                _run_git(wt, "diff", "--cached", "--no-ext-diff", "--binary", "--"),
                                "export candidate",
                            )
                            export_file.parent.mkdir(parents=True, exist_ok=True)
                            export_file.write_bytes(exported)
                            result["exported_patch"] = str(export_file)
                        result["status"] = "internal_tests_passed"
                        result["internal_tests_passed"] = True
                        result["final_patch"] = patch
                        break
                    if outcome.status in {"docker_error", "timeout"}:
                        result["status"] = "infrastructure_error"
                        result["error_message"] = outcome.output_tail[-1200:]
                        break
                    failure = {"stage": "tests", "status": outcome.status,
                               "exit_code": outcome.exit_code,
                               "log_tail": outcome.output_tail}
            except (WorkspaceError, OSError, TimeoutError) as exc:
                result["status"] = "infrastructure_error"
                result["error_message"] = str(exc)[:800]
                break

        if failure is None:
            result["status"] = "infrastructure_error"
            result["error_message"] = "No structured failure available"
            break
        if number == max_candidates:
            result["status"] = "retry_exhausted"
            break
        try:
            advice = review_failure(issue, plan, patch, failure,
                                    completion=reviewer_completion)
        except (ReviewerError, ValueError, Exception) as exc:
            result["status"] = "reviewer_error"
            result["error_message"] = str(exc)[:800]
            break
        attempt["reviewer"] = advice
        _trace(trace_file, {"event": "reviewer", "attempt": number, **advice})
        revision = {
            "previous_patch": patch[:10000],
            "failure": {**failure, "log_tail": failure["log_tail"][-3000:]},
            "reviewer": advice,
        }

    if result["status"] == "not_started":
        result["status"] = "retry_exhausted"
    _trace(trace_file, {"event": "finish", "status": result["status"],
                        "attempt_count": result["attempt_count"],
                        "official_evaluated": False})
    return result


def run_execution_loop(
    issue: str, repo_root: str, base_commit: str, spec: DockerTestSpec, *,
    planner_completion=None, **kwargs,
) -> dict:
    from pipeline_agent import run_localization
    options = {} if planner_completion is None else {"completion": planner_completion}
    plan = run_localization(issue, repo_root, base_commit, **options)
    result = run_from_plan(issue, plan, spec, **kwargs)
    return {"plan": plan, "repair": result}
