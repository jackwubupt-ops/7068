"""Real Docker smoke: two failed-then-passed candidate attempts; no live LLM.

Requirements: Git and a pre-pulled python:3.11-slim image.
The target repository and test code are only executed in a constrained container.
"""
from pathlib import Path
import json
import subprocess
import tempfile

from patchloop_task2.execution import DockerTestSpec
from patchloop_task2.loop import run_execution_loop


FIRST = (
    "diff --git a/calc.py b/calc.py\n"
    "--- a/calc.py\n+++ b/calc.py\n"
    "@@ -1,2 +1,2 @@\n def divide(a, b):\n"
    "-    return a // b\n+    return a * b\n"
)
SECOND = FIRST.replace("return a * b", "return a / b")


def main():
    with tempfile.TemporaryDirectory(prefix="patchloop-smoke-") as directory:
        root = Path(directory) / "target"
        root.mkdir()
        (root / "calc.py").write_text(
            "def divide(a, b):\n    return a // b\n", encoding="utf-8")
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_calc.py").write_text(
            "import unittest\n"
            "from calc import divide\n"
            "class DivisionTest(unittest.TestCase):\n"
            "    def test_fraction(self):\n"
            "        self.assertEqual(divide(3, 2), 1.5)\n"
            "    def test_exact(self):\n"
            "        self.assertEqual(divide(8, 2), 4)\n", encoding="utf-8")
        for args in (
            ("init",), ("add", "."),
            ("-c", "user.name=PatchLoop", "-c", "user.email=smoke@example.com",
             "commit", "-m", "fixture"),
        ):
            subprocess.run(["git", "-C", str(root), *args],
                           check=True, capture_output=True)
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        issue = "divide(3,2) returns 1, expected 1.5."
        actions = iter([
            {"action": "search_repo", "arguments": {"query": "divide"}},
            {"action": "read_file", "arguments": {
                "relative_path": "calc.py", "start_line": 1, "end_line": 2}},
            {"action": "final", "plan": {
                "issue_summary": issue,
                "suspected_files": [{"file_path": "calc.py",
                                     "relevant_lines": [1, 2],
                                     "reason": "floor division",
                                     "evidence_ids": ["E2"]}],
                "root_cause_hypothesis": "Floor division discards fractions",
                "planned_changes": ["Use true division"],
                "limitations": ["Scripted model actions, not a live LLM"]}},
        ])
        codes = iter([FIRST, SECOND])
        reviewer = json.dumps({
            "failure_type": "test_failure",
            "diagnosis": "First candidate still fails division tests",
            "suggested_fix": "Use / instead of *",
        })
        spec = DockerTestSpec(
            image="python:3.11-slim",
            command=("python", "-m", "unittest", "discover", "-s", "tests", "-v"),
            timeout_seconds=60,
        )
        outcome = run_execution_loop(
            issue, str(root), commit, spec,
            planner_completion=lambda _: json.dumps(next(actions)),
            coder_completion=lambda _: next(codes),
            reviewer_completion=lambda _: reviewer,
            trace_path=Path(directory) / "trace.jsonl",
            export_path=Path(directory) / "patch.diff",
        )
        result = outcome["repair"]
        print(json.dumps({
            "status": result["status"], "attempt_count": result["attempt_count"],
            "test_statuses": [a["test"]["status"] if a["test"] else None
                              for a in result["attempts"]],
            "official_evaluated": result["official_evaluated"],
        }, indent=2))
        assert result["status"] == "internal_tests_passed", result
        assert result["attempt_count"] == 2, result
        assert [a["test"]["status"] for a in result["attempts"]] == ["failed", "passed"]
        assert (root / "calc.py").read_text(encoding="utf-8").endswith("return a // b\n")
        assert subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"]) == b""


if __name__ == "__main__":
    main()
