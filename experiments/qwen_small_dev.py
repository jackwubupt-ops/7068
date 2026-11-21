"""Small-Qwen live experiments: API preflight, Git/Docker smoke and SWE-bench dev.

Runs on the GPU server itself or via a localhost SSH tunnel to vLLM.
The CLI never reads benchmark gold patches or official test labels into agents.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time

from experiments.live_deepseek import ISSUE, create_real_git_fixture
from experiments.deepseek_swebench_dev import run_real_dev
from patchloop_task2.execution import DockerTestSpec
from patchloop_task2.loop import run_execution_loop
from patchloop_task2.qwen_small import QwenSmallBackend


def _git_clean(repo: Path, sha: str) -> bool:
    state = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True, text=True, timeout=15,
    )
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=15,
    )
    return (state.returncode == 0 and not state.stdout.strip()
            and head.returncode == 0 and head.stdout.strip() == sha)


def run_qwen_smoke(backend: QwenSmallBackend, *,
                   max_candidates: int = 2) -> dict:
    """A real vLLM model generates actions; real tests run in constrained Docker."""
    backend.verify()
    with tempfile.TemporaryDirectory(prefix="patchloop-qwen-smoke-") as temp:
        root = Path(temp) / "repo"
        sha = create_real_git_fixture(root)
        tests = DockerTestSpec(
            "python:3.11-slim",
            command=("python", "-m", "unittest", "discover", "-s", "tests", "-v"),
            timeout_seconds=60,
        )
        data = run_execution_loop(
            ISSUE, str(root), sha, tests,
            planner_completion=backend.callback("planner"),
            coder_completion=backend.callback("coder"),
            reviewer_completion=backend.callback("reviewer"),
            max_candidates=max_candidates, normalize_hunks=True,
        )
        repair = data["repair"]
        return {
            "experiment": "qwen-small-live-docker-smoke-v1",
            "model": backend.model,
            "status": repair["status"],
            "internal_tests_passed": repair["internal_tests_passed"],
            "official_evaluated": False,
            "original_checkout_clean": _git_clean(root, sha),
            "attempts": [{
                "number": x["number"],
                "patch_status": x["patch_status"],
                "hunk_header_corrections": x.get("hunk_header_corrections", 0),
                "test_status": (x.get("test") or {}).get("status"),
                "reviewer_used": x.get("reviewer") is not None,
            } for x in repair["attempts"]],
            "call_count": len(backend.calls),
            "model_calls": backend.calls,
        }


def run_qwen_dev(backend: QwenSmallBackend, output_dir: Path, *, agent: str = "pcr",
                 **task_options) -> dict:
    """Real public issue; no official benchmark verdict is claimed here.

    agent="pcr" runs Planner -> Coder -> Reviewer (run_real_dev); agent="single"
    runs the single-agent baseline (RQ3). task_options are forwarded (instance_id,
    task_loader, ...); with none given this is the original sqlfluff dev instance.
    """
    if agent == "pcr":
        result = run_real_dev(output_dir, api=backend, **task_options)
    elif agent == "single":
        from experiments.deepseek_swebench_dev import INSTANCE_ID
        from experiments.single_agent_dev import run_single_dev
        task_options.setdefault("instance_id", INSTANCE_ID)
        result = run_single_dev(output_dir, api=backend, **task_options)
    else:
        raise ValueError("agent must be 'pcr' or 'single'")
    # Classic SWE-bench uses model_name_or_path in artifact filenames.
    # Preserve the exact HF ID in run_status but use a slash-free evaluation label.
    label = {
        "Qwen/Qwen2.5-Coder-0.5B-Instruct": "qwen2.5-coder-0.5b-instruct",
        "Qwen/Qwen3-0.6B": "qwen3-0.6b",
        "Qwen/Qwen2.5-Coder-7B-Instruct": "qwen2.5-coder-7b-instruct",
    }.get(backend.model, backend.model.split("/")[-1].lower()) + ("-single-agent" if agent == "single" else "")
    if result["status"] == "prediction_ready":
        predictions = output_dir / "predictions.jsonl"
        record = json.loads(predictions.read_text(encoding="utf-8"))
        if record["model_name_or_path"] != backend.model:
            raise ValueError("Unexpected model identity in generated prediction")
        record["model_name_or_path"] = label
        predictions.write_text(
            json.dumps(record, ensure_ascii=False) + "\\n".replace("\\n", "\n"),
            encoding="utf-8",
        )
    result["prediction_model_label"] = label
    # The same pipeline serves both backends; name the run after the real provider.
    provider = getattr(backend, "provider", "qwen")
    result["experiment"] = ("qwen-small-real-swebench-full-dev-v1" if agent == "pcr"
                            else "qwen-single-agent-swebench-dev-v1")
    if provider != "qwen":
        result["experiment"] = result["experiment"].replace("qwen-small", provider).replace("qwen", provider)
    result["provider"] = provider
    result["agent"] = agent
    result["official_evaluated"] = False
    result["official_resolved"] = None
    (output_dir / "run_status.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    from patchloop_task2.qwen_small import QwenSettings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "smoke", "dev"),
                        default="preflight")
    parser.add_argument("--out", help="NEW output directory for dev or report")
    parser.add_argument("--max-candidates", type=int, default=2)
    parser.add_argument("--agent", choices=("pcr", "single"), default="pcr",
                        help="dev mode: Planner-Coder-Reviewer (default) or single-agent baseline")
    parser.add_argument("--edit-format", choices=("diff", "search_replace"), default="diff",
                        help="dev mode Coder output: unified diff or SEARCH/REPLACE blocks")
    args = parser.parse_args()

    backend = QwenSmallBackend(QwenSettings.from_env())
    t0 = time.monotonic()
    if args.mode == "preflight":
        result = backend.verify()
    elif args.mode == "smoke":
        result = run_qwen_smoke(backend, max_candidates=args.max_candidates)
    else:
        if not args.out:
            parser.error("--out is required for --mode dev")
        target = Path(args.out).expanduser().resolve()
        if target.exists() and any(target.iterdir()):
            parser.error("--out must be a new or empty directory")
        target.mkdir(parents=True, exist_ok=True)
        backend.verify()
        result = run_qwen_dev(backend, target, agent=args.agent, edit_format=args.edit_format)
    result["duration_seconds"] = round(time.monotonic() - t0, 2)
    if args.out and args.mode != "dev":
        target = Path(args.out).expanduser().resolve()
        if target.exists() and any(target.iterdir()):
            parser.error("--out must be a new or empty directory")
        target.mkdir(parents=True, exist_ok=True)
        (target / "run_status.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    success = (args.mode == "preflight" and result["status"] == "live_qwen_api_ok"
               or args.mode == "smoke" and result["internal_tests_passed"]
               or args.mode == "dev" and result["status"] == "prediction_ready")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
