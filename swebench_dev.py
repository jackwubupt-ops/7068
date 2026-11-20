"""Leakage-safe adapter for REAL SWE-bench full development instances.

Development uses dev splits only: princeton-nlp/SWE-bench dev (single-instance
runs) or princeton-nlp/SWE-bench_Lite dev (23 tasks, batch runs). SWE-bench_Lite
test is reserved for final evaluation and is never loaded here.
Neither gold patch, test patch, test labels nor hints are passed to agents.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
import re
import subprocess
import tempfile

DATASET_ID = "princeton-nlp/SWE-bench"
LITE_DATASET_ID = "princeton-nlp/SWE-bench_Lite"
DEV_DATASETS = {DATASET_ID, LITE_DATASET_ID}
DEVELOPMENT_SPLIT = "dev"
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")


@dataclass(frozen=True)
class DevelopmentTask:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str

    def __post_init__(self):
        if not isinstance(self.instance_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,120}", self.instance_id):
            raise ValueError("Invalid SWE-bench instance ID")
        if not isinstance(self.repo, str) or not _REPO.fullmatch(self.repo):
            raise ValueError("Invalid GitHub repository")
        if not isinstance(self.base_commit, str) or not _SHA.fullmatch(self.base_commit):
            raise ValueError("Invalid base commit")
        if not isinstance(self.problem_statement, str) or not self.problem_statement.strip():
            raise ValueError("Empty issue text")


def sanitize_task(raw: dict) -> DevelopmentTask:
    """Only copy the four inference-permitted fields, NEVER the gold patch."""
    if not isinstance(raw, dict):
        raise ValueError("Invalid SWE-bench row")
    return DevelopmentTask(
        instance_id=raw["instance_id"], repo=raw["repo"],
        base_commit=raw["base_commit"], problem_statement=raw["problem_statement"],
    )


def load_dev_tasks(dataset_id: str = LITE_DATASET_ID, *, loader=None) -> list[DevelopmentTask]:
    """All tasks of a DEV split, in dataset order, with only inference-safe fields."""
    if dataset_id not in DEV_DATASETS:
        raise ValueError("Unsupported development dataset")
    if loader is None:
        try:
            from datasets import load_dataset as loader
        except ImportError as exc:
            raise RuntimeError("Install optional dev dependency: pip install datasets") from exc
    # The split is hard-coded: the Lite test split must never be loaded for development.
    return [sanitize_task(item) for item in loader(dataset_id, split=DEVELOPMENT_SPLIT)]


def select_dev_task(*, instance_id: str | None = None,
                    repository: str | None = None) -> DevelopmentTask:
    """Load the official full SWE-bench dev split; no Lite test contamination."""
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError("Install optional dev dependency: pip install datasets") from exc
    dataset = load_dataset(DATASET_ID, split=DEVELOPMENT_SPLIT)
    for item in dataset:
        if instance_id is not None and item.get("instance_id") != instance_id:
            continue
        if repository is not None and item.get("repo") != repository:
            continue
        return sanitize_task(item)
    raise ValueError("Requested issue/repository not found in SWE-bench full dev; never fall back to test")


def _git(*arguments: str, timeout: int = 180) -> str:
    process = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *arguments],
        capture_output=True, text=True, timeout=timeout,
        check=False,
    )
    if process.returncode:
        raise RuntimeError(f"Git operation failed: {process.stderr.strip()[:700]}")
    return process.stdout.strip()


def checkout_dev_task(task: DevelopmentTask, destination: str | Path) -> Path:
    """Clone a real public repository then checkout EXACT base SHA, never execute code."""
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise ValueError("Target destination already exists; refusing to overwrite it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{task.repo}.git"
    _git("clone", "--filter=blob:none", "--no-checkout", "--", url, str(destination), timeout=240)
    try:
        try:
            _git("-C", str(destination), "checkout", "--detach", task.base_commit, timeout=240)
        except RuntimeError:
            _git("-C", str(destination), "fetch", "--depth=1", "origin", task.base_commit, timeout=240)
            _git("-C", str(destination), "checkout", "--detach", task.base_commit, timeout=240)
        actual = _git("-C", str(destination), "rev-parse", "HEAD")
        if actual.lower() != task.base_commit.lower():
            raise RuntimeError("Checked out an unexpected commit")
        from utils.repo_tools import validate_repository
        validate_repository(destination, actual)
        return destination
    except Exception:
        # Caller owns the sandbox directory. Retain failure evidence for debugging.
        raise


def inspect_dev_task(task: DevelopmentTask, checkout: Path) -> dict:
    """Read-only smoke proving a real issue and matching historical checkout."""
    from utils.repo_tools import search_repo, validate_repository
    repository = validate_repository(checkout, task.base_commit)
    words = re.findall(r"[A-Za-z_][A-Za-z_0-9]{3,}", task.problem_statement)
    common = {"that", "with", "from", "when", "this", "should", "does", "have", "after",
              "about", "using", "into", "because", "there", "some", "issue"}
    query = next((w for w in words if w.lower() not in common), "def")
    search = search_repo(checkout, query, max_results=3, context_lines=1)
    return {
        "instance_id": task.instance_id, "dataset": DATASET_ID,
        "split": DEVELOPMENT_SPLIT, "repo": task.repo,
        "base_commit": repository["base_commit"], "issue_chars": len(task.problem_statement),
        "search_query": query, "search_ok": search["ok"],
        "search_match_count": len(search.get("matches", [])),
        "search_truncated": search.get("truncated", False),
        "model_called": False, "official_evaluated": False,
    }


def make_prediction(instance_id: str, model_patch: str,
                    model: str = "Qwen/Qwen2.5-Coder-7B-Instruct") -> dict:
    if not isinstance(model_patch, str) or not model_patch.startswith("diff --git a/"):
        raise ValueError("Only export a real model-generated Git patch")
    return {"instance_id": instance_id, "model_name_or_path": model,
            "model_patch": model_patch}


def run_dev_instance(
    task: DevelopmentTask, checkout: Path, output_dir: Path, *,
    planner_completion=None, coder_completion=None,
) -> dict:
    """Run existing Task 1 -> Task 2 on a real development issue and repository."""
    from patchloop_task2.runner import run_repair
    from patchloop_task2.qwen import QWEN_MODEL, verify_qwen_endpoint
    if planner_completion is None or coder_completion is None:
        # No silent fallbacks to the Demo's GPT/DeepSeek defaults.
        verify_qwen_endpoint()
    output_dir = Path(output_dir).expanduser().resolve()
    if output_dir.is_relative_to(Path(checkout).resolve()):
        raise ValueError("Output must be outside the task source checkout")
    output_dir.mkdir(parents=True, exist_ok=True)
    patchfile = output_dir / "candidate.patch"
    data = run_repair(
        task.problem_statement, str(checkout), task.base_commit,
        planner_completion=planner_completion,
        coder_completion=coder_completion,
        export_path=patchfile,
    )
    result = {
        "instance_id": task.instance_id, "dataset": DATASET_ID, "split": "dev",
        "model": QWEN_MODEL if planner_completion is None and coder_completion is None else "scripted-offline",
        "patch_status": data["patch_result"]["status"],
        "official_evaluated": False,
    }
    (output_dir / "run_status.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if data["patch_result"]["status"] == "applied":
        patch = patchfile.read_text(encoding="utf-8")
        entry = make_prediction(task.instance_id, patch,
                                model=result["model"])
        # The official SWE-bench harness accepts JSONL predictions.
        (output_dir / "predictions.jsonl").write_text(
            json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
        result["prediction_file"] = str(output_dir / "predictions.jsonl")
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Real SWE-bench full dev adapter")
    parser.add_argument("--mode", choices=("inspect", "predict"), default="inspect")
    parser.add_argument("--instance-id", help="Exact dev instance ID")
    parser.add_argument("--repository", help="Optional exact GitHub repo, e.g. pytest-dev/pytest")
    parser.add_argument("--output-dir", required=True)
    arguments = parser.parse_args()
    task = select_dev_task(instance_id=arguments.instance_id, repository=arguments.repository)
    output = Path(arguments.output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="patchloop-real-dev-") as temporary:
        checkout = checkout_dev_task(task, Path(temporary) / "checkout")
        if arguments.mode == "inspect":
            result = inspect_dev_task(task, checkout)
        else:
            result = run_dev_instance(task, checkout, output)
    (output / "dev_task_status.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if arguments.mode == "inspect" or result["patch_status"] == "applied" else 1


if __name__ == "__main__":
    raise SystemExit(main())
