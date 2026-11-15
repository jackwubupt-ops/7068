"""LIVE DeepSeek API -> real Git repair -> isolated Docker tests.

This script NEVER fabricates a model completion. Missing credentials and API
failures are reported as NOT RUN / ERROR, not as successful experiments.

Example:
  DEEPSEEK_API_KEY=... python -m experiments.live_deepseek --report /tmp/report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from patchloop_task2.execution import DockerTestSpec
from patchloop_task2.loop import run_execution_loop

ALLOWED_MODELS = {"deepseek-flash", "deepseek-v4-pro"}
OFFICIAL_ENDPOINT = "https://api.deepseek.com"
MAX_CALLS = 10
MAX_COMPLETION_TOKENS = 11_000
ISSUE = (
    "Repository bug: calc.py contains divide(a, b), which uses floor division "
    "(//) and incorrectly returns 1 for divide(3, 2). The desired result is 1.5. "
    "Change only the existing calc.py function to perform true division while "
    "preserving the function name and arguments. The tests are already provided."
)


def _git(root: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(root), *args], check=True,
        capture_output=True, text=True, timeout=20,
    )
    return process.stdout.strip()


def create_real_git_fixture(root: Path) -> str:
    """A real git repository, not an in-memory mock."""
    root.mkdir(parents=True, exist_ok=False)
    (root / "calc.py").write_text(
        "def divide(a, b):\n    return a // b\n", encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_calc.py").write_text(
        "import unittest\n"
        "from calc import divide\n\n"
        "class DivideTests(unittest.TestCase):\n"
        "    def test_fraction(self):\n"
        "        self.assertEqual(divide(3, 2), 1.5)\n\n"
        "    def test_exact(self):\n"
        "        self.assertEqual(divide(8, 2), 4)\n",
        encoding="utf-8",
    )
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=PatchLoop Experiment",
         "-c", "user.email=experiment@example.invalid", "commit", "-qm", "bug fixture")
    return _git(root, "rev-parse", "HEAD")


class LiveDeepSeek:
    """Controlled, metered real HTTP completions through the official endpoint."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 client=None):
        token = api_key if api_key is not None else os.getenv("DEEPSEEK_API_KEY", "")
        if not token or token in {"EMPTY", "DUMMY", "YOUR_API_KEY"}:
            raise ValueError(
                "MISSING_DEEPSEEK_API_KEY: set DEEPSEEK_API_KEY as a GitHub "
                "Actions repository secret, or in the local process environment"
            )
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
        if self.model not in ALLOWED_MODELS:
            raise ValueError("Use an official DeepSeek model: deepseek-flash or deepseek-v4-pro")
        if client is None:
            from openai import OpenAI
            client = OpenAI(
                api_key=token, base_url=OFFICIAL_ENDPOINT,
                timeout=75, max_retries=0,
            )
        self.client = client
        self.calls: list[dict] = []
        self.output_tokens = 0

    def complete(self, stage: str, messages: list[dict]) -> str:
        if len(self.calls) >= MAX_CALLS or self.output_tokens >= MAX_COMPLETION_TOKENS:
            raise RuntimeError("LIVE_API_BUDGET_EXHAUSTED: maximum request/token budget reached")
        if stage not in {"preflight", "planner", "coder", "reviewer"}:
            raise ValueError("Unsupported agent role")
        max_tokens = {
            "preflight": 24,
            "planner": 1500,
            "coder": 2200,
            "reviewer": 700,
        }[stage]
        remaining = MAX_COMPLETION_TOKENS - self.output_tokens
        max_tokens = min(max_tokens, remaining)
        # Official DeepSeek docs: non-thinking mode is explicit. Planner needs
        # strict machine-readable JSON and Coder needs a raw text unified diff.
        started = time.monotonic()
        reply = self.client.chat.completions.create(
            model=self.model, messages=messages,
            max_tokens=max_tokens, temperature=0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        duration = round(time.monotonic() - started, 3)
        if not reply.choices:
            raise RuntimeError(f"LIVE_API_BAD_RESPONSE: no choice ({stage})")
        choice = reply.choices[0]
        output = choice.message.content
        usage = getattr(reply, "usage", None)
        tokens = getattr(usage, "completion_tokens", None)
        if isinstance(tokens, int):
            self.output_tokens += tokens
        else:
            # Conservatively charge the requested token budget when usage is absent.
            self.output_tokens += max_tokens
        self.calls.append({
            "stage": stage,
            "response_id_present": bool(getattr(reply, "id", None)),
            "response_model": str(getattr(reply, "model", ""))[:100],
            "finish_reason": getattr(choice, "finish_reason", None),
            "latency_seconds": duration,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": tokens,
            "output_sha256": (
                hashlib.sha256(output.encode("utf-8")).hexdigest()
                if isinstance(output, str) else None
            ),
        })
        if not isinstance(output, str) or not output.strip():
            raise RuntimeError(f"LIVE_API_EMPTY_RESPONSE: {stage}")
        if getattr(choice, "finish_reason", None) == "length":
            raise RuntimeError(f"LIVE_API_TRUNCATED: {stage}")
        return output

    def callback(self, stage: str):
        return lambda messages: self.complete(stage, messages)


def _safe_error(exc: BaseException) -> str:
    """Never report exception repr from HTTP clients (may contain request headers)."""
    msg = str(exc)
    # HTTP SDK error responses sometimes include echoed request payloads.
    # Keep only exception type and a brief generic status; no raw API response.
    return type(exc).__name__ + ": " + (
        msg if isinstance(exc, (ValueError, RuntimeError)) else "API/network operation failed"
    )[:180]


def run_live_experiment(*, report_path: str | Path | None = None,
                        model: str | None = None, client=None,
                        api_key: str | None = None) -> dict:
    result = {
        "experiment": "patchloop-deepseek-real-api-smoke-v1",
        "provider": "DeepSeek official OpenAI-compatible API",
        "endpoint": OFFICIAL_ENDPOINT,
        "model": model or os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        "api_preflight_passed": False,
        "planner_uses_real_api": False,
        "coder_uses_real_api": False,
        "reviewer_uses_real_api": False,
        "model_calls": [],
        "status": "NOT_RUN",
        "internal_tests_passed": False,
        "official_swebench_evaluated": False,
    }
    try:
        live = LiveDeepSeek(api_key=api_key, model=model, client=client)
        result["model"] = live.model
        # Make one small real request to establish the actual credentials/network.
        live.complete("preflight", [{"role": "user", "content":
                                    "Reply with only API_OK to confirm connectivity."}])
        result["api_preflight_passed"] = True
        with tempfile.TemporaryDirectory(prefix="patchloop-deepseek-live-") as directory:
            checkout = Path(directory) / "target"
            base_commit = create_real_git_fixture(checkout)
            result["git_base_commit"] = base_commit
            spec = DockerTestSpec(image="python:3.11-slim", timeout_seconds=60)
            try:
                output = run_execution_loop(
                    ISSUE, str(checkout), base_commit, spec,
                    planner_completion=live.callback("planner"),
                    coder_completion=live.callback("coder"),
                    reviewer_completion=live.callback("reviewer"),
                    max_candidates=2,
                )
                repair = output["repair"]
                result["status"] = repair["status"]
                result["attempt_count"] = repair["attempt_count"]
                result["internal_tests_passed"] = repair["internal_tests_passed"]
                result["attempts"] = [{
                    "number": item["number"],
                    "patch_status": item["patch_status"],
                    "patch_sha256": item["patch_sha256"],
                    "changed_files": item.get("changed_files", []),
                    "test_status": (item["test"] or {}).get("status"),
                    "test_exit_code": (item["test"] or {}).get("exit_code"),
                    "reviewer_feedback_present": item.get("reviewer") is not None,
                } for item in repair["attempts"]]
                if repair.get("error_message"):
                    result["error"] = str(repair["error_message"])[:250]
            except Exception as exc:
                result["status"] = "PIPELINE_ERROR"
                result["error"] = _safe_error(exc)
            # Original git source must never be patched.
            result["original_repo_clean"] = (
                _git(checkout, "status", "--porcelain") == ""
                and (checkout / "calc.py").read_text(encoding="utf-8")
                == "def divide(a, b):\n    return a // b\n"
            )
            if not result["original_repo_clean"]:
                result["status"] = "ISOLATION_VIOLATION"
                result["internal_tests_passed"] = False
    except Exception as exc:
        result["status"] = (
            "NOT_RUN_MISSING_CREDENTIALS"
            if "MISSING_DEEPSEEK_API_KEY" in str(exc) else "API_ERROR"
        )
        result["error"] = _safe_error(exc)
    finally:
        if "live" in locals():
            result["model_calls"] = live.calls
            result["prompt_tokens"] = sum(
                x["prompt_tokens"] or 0 for x in live.calls
            )
            result["completion_tokens"] = sum(
                x["completion_tokens"] or 0 for x in live.calls
            )
            result["planner_uses_real_api"] = any(
                x["stage"] == "planner" for x in live.calls
            )
            result["coder_uses_real_api"] = any(
                x["stage"] == "coder" for x in live.calls
            )
            result["reviewer_uses_real_api"] = any(
                x["stage"] == "reviewer" for x in live.calls
            )
        if report_path is not None:
            dest = Path(report_path).expanduser().resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="Safe JSON report path")
    args = parser.parse_args()
    result = run_live_experiment(report_path=args.report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["internal_tests_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
