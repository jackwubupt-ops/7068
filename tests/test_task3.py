"""Task 3 offline integration tests use real temporary Git repos, not a live model."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from patchloop_task2.execution import DockerTestRunner, DockerTestSpec, TestOutcome
from patchloop_task2.loop import run_execution_loop, run_from_plan
from patchloop_task2.reviewer import ReviewerError, review_failure

BAD_PATCH = (
    "diff --git a/calc.py b/calc.py\n"
    "--- a/calc.py\n+++ b/calc.py\n"
    "@@ -1,2 +1,2 @@\n def divide(a, b):\n"
    "-    return a // b\n+    return a * b\n"
)
GOOD_PATCH = BAD_PATCH.replace("return a * b", "return a / b")
REVIEW = json.dumps({"failure_type": "test_failure",
                     "diagnosis": "Multiplication does not preserve division semantics",
                     "suggested_fix": "Change the arithmetic operator to true division"})


class FakeDockerRunner:
    def __init__(self, *, timeout=False):
        self.seen = []
        self.timeout = timeout

    def run(self, workspace, spec):
        code = (workspace / "calc.py").read_text(encoding="utf-8")
        self.seen.append(code)
        if self.timeout:
            return TestOutcome("timeout", None, "timed out", 1)
        if "return a / b" in code:
            return TestOutcome("passed", 0, "2 tests OK", .1)
        return TestOutcome("failed", 1, "AssertionError: expected 1.5, got 3", .1)


class Task3Test(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo"
        self.root.mkdir()
        (self.root / "calc.py").write_text("def divide(a, b):\n    return a // b\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Task3",
                        "-c", "user.email=test@example.com", "commit", "-m", "fixture"],
                       check=True, capture_output=True)
        self.commit = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        self.plan = {
            "repo_root": str(self.root), "base_commit": self.commit,
            "suspected_files": [{"file_path": "calc.py", "relevant_lines": [1, 2],
                                 "reason": "floor division", "evidence_ids": ["E2"]}],
            "root_cause_hypothesis": "Uses floor division",
            "planned_changes": ["Replace // with /"],
            "evidence": [{"id": "E2", "tool": "read_file", "result": {
                "ok": True, "file_path": "calc.py", "lines": [
                    {"line_number": 1, "text": "def divide(a, b):"},
                    {"line_number": 2, "text": "    return a // b"}]}}],
        }
        self.spec = DockerTestSpec("python:3.11-slim")

    def test_success_after_failed_patch_and_review(self):
        replies = iter([BAD_PATCH, GOOD_PATCH])
        runner = FakeDockerRunner()
        with tempfile.TemporaryDirectory() as output:
            patch_path = Path(output) / "fixed.patch"
            trace_path = Path(output) / "trace.jsonl"
            result = run_from_plan(
                "divide(3,2) should return 1.5", self.plan, self.spec,
                coder_completion=lambda _: next(replies),
                reviewer_completion=lambda _: REVIEW,
                test_runner=runner, max_candidates=3,
                export_path=patch_path, trace_path=trace_path,
            )
            self.assertEqual(result["status"], "internal_tests_passed")
            self.assertEqual(result["attempt_count"], 2)
            self.assertEqual([a["test"]["status"] for a in result["attempts"]],
                             ["failed", "passed"])
            self.assertEqual(result["attempts"][0]["reviewer"]["failure_type"], "test_failure")
            self.assertIn("return a / b", patch_path.read_text(encoding="utf-8"))
            event_types = [json.loads(s)["event"] for s in trace_path.read_text().splitlines()]
            self.assertEqual(event_types, ["start", "patch", "tests", "reviewer",
                                           "patch", "tests", "finish"])
        self.assertEqual(len(runner.seen), 2)
        self.assertIn("return a * b", runner.seen[0])
        self.assertIn("return a / b", runner.seen[1])
        self.assertFalse(result["official_evaluated"])
        self.assertEqual((self.root / "calc.py").read_text(),
                         "def divide(a, b):\n    return a // b\n")
        self.assertEqual(subprocess.check_output(
            ["git", "-C", str(self.root), "status", "--porcelain"]), b"")

    def test_revision_context_contains_reviewer_feedback(self):
        contexts = []
        def coder(messages):
            contexts.append(messages)
            return [BAD_PATCH, GOOD_PATCH][len(contexts) - 1]
        result = run_from_plan("bug", self.plan, self.spec, coder_completion=coder,
                               reviewer_completion=lambda _: REVIEW,
                               test_runner=FakeDockerRunner())
        self.assertTrue(result["internal_tests_passed"])
        self.assertEqual(len(contexts), 2)
        self.assertIn("COMPLETE REPLACEMENT", contexts[1][-1]["content"])
        self.assertIn("true division", contexts[1][-1]["content"])

    def test_one_candidate_stops_without_reviewer(self):
        result = run_from_plan("bug", self.plan, self.spec,
                               coder_completion=lambda _: BAD_PATCH,
                               reviewer_completion=lambda _: self.fail("Reviewer should not run"),
                               test_runner=FakeDockerRunner(), max_candidates=1)
        self.assertEqual(result["status"], "retry_exhausted")
        self.assertEqual(result["attempt_count"], 1)

    def test_docker_timeout_stops_retry(self):
        result = run_from_plan("bug", self.plan, self.spec,
                               coder_completion=lambda _: BAD_PATCH,
                               reviewer_completion=lambda _: self.fail("Cannot review timeout"),
                               test_runner=FakeDockerRunner(timeout=True))
        self.assertEqual(result["status"], "infrastructure_error")
        self.assertEqual(result["attempt_count"], 1)

    def test_invalid_patch_is_not_executed(self):
        runner = FakeDockerRunner()
        result = run_from_plan("bug", self.plan, self.spec,
                               coder_completion=lambda _: GOOD_PATCH.replace("calc.py", "other.py"),
                               reviewer_completion=lambda _: REVIEW,
                               test_runner=runner, max_candidates=1)
        self.assertEqual(result["status"], "retry_exhausted")
        self.assertEqual(result["attempts"][0]["patch_status"], "patch_invalid")
        self.assertEqual(runner.seen, [])

    def test_reject_output_into_source_repo(self):
        with self.assertRaises(ValueError):
            run_from_plan("bug", self.plan, self.spec, export_path=self.root / "output.patch",
                          coder_completion=lambda _: GOOD_PATCH,
                          test_runner=FakeDockerRunner())

    def test_real_planner_tools_to_repair_loop(self):
        actions = iter([
            {"action": "search_repo", "arguments": {"query": "divide"}},
            {"action": "read_file", "arguments": {
                "relative_path": "calc.py", "start_line": 1, "end_line": 2}},
            {"action": "final", "plan": {
                "issue_summary": "division rounds result",
                "suspected_files": self.plan["suspected_files"],
                "root_cause_hypothesis": "Uses floor division",
                "planned_changes": ["Replace // with /"],
                "limitations": ["Scripted offline model actions"]}},
        ])
        data = run_execution_loop(
            "divide(3,2) should return 1.5", str(self.root), self.commit,
            self.spec, planner_completion=lambda _: json.dumps(next(actions)),
            coder_completion=lambda _: GOOD_PATCH, test_runner=FakeDockerRunner(),
        )
        self.assertEqual(data["repair"]["status"], "internal_tests_passed")
        self.assertEqual(len(data["plan"]["evidence"]), 2)

    def test_no_docker_returns_infrastructure_error(self):
        with patch("patchloop_task2.execution.shutil.which", return_value=None):
            result = DockerTestRunner().run(self.root, self.spec)
        self.assertEqual(result.status, "docker_error")

    def test_bad_spec_rejected(self):
        with self.assertRaises(ValueError):
            DockerTestSpec("image\n--privileged")
        with self.assertRaises(ValueError):
            DockerTestSpec("python:3.11-slim", timeout_seconds=1)
        with self.assertRaises(ValueError):
            DockerTestSpec("python:3.11-slim", command=("python", "bad\narg"))

    def test_reviewer_schema_enforced(self):
        with self.assertRaises(ReviewerError):
            review_failure("bug", self.plan, GOOD_PATCH, {"stage": "tests"},
                           completion=lambda _: '{"failure_type":"test_failure"}')


if __name__ == "__main__":
    unittest.main()
