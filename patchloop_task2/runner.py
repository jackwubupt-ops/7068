"""Task 1 plan -> Coder -> isolated Git patch application. No tests are run."""
from pathlib import Path
from .coder import CoderError, generate_patch, permitted_paths
from .workspace import apply_candidate


def apply_repair_plan(issue: str, plan: dict, *, coder_completion=None,
                      export_path: str | Path | None = None) -> dict:
    try:
        if not isinstance(plan, dict) or not isinstance(plan.get("repo_root"), str):
            raise CoderError("Task 1 result must include repo_root")
        if not isinstance(plan.get("base_commit"), str):
            raise CoderError("Task 1 result must include base_commit")
        allowed = permitted_paths(plan)
        patch = generate_patch(issue, plan, completion=coder_completion)
    except (CoderError, ValueError) as exc:
        return {"status": "generation_failed", "error_code": "invalid_plan_or_output",
                "error_message": str(exc), "execution_verified": False}
    result = apply_candidate(plan["repo_root"], plan["base_commit"], patch,
                             export_path=export_path, allowed_paths=allowed).to_dict()
    result["execution_verified"] = False
    result["test_status"] = "not_run"
    return result


def run_repair(issue: str, repo_root: str, base_commit: str, *,
               planner_completion=None, coder_completion=None,
               export_path: str | Path | None = None) -> dict:
    from pipeline_agent import run_localization
    options = {} if planner_completion is None else {"completion": planner_completion}
    plan = run_localization(issue, repo_root, base_commit, **options)
    return {"plan": plan, "patch_result": apply_repair_plan(
        issue, plan, coder_completion=coder_completion, export_path=export_path)}
