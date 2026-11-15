"""Task 2 integration tests: temporary Git repository, no live LLM calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from patchloop_task2.coder import build_messages
from patchloop_task2.runner import apply_repair_plan, run_repair

GOOD_PATCH = ("diff --git a/calc.py b/calc.py\n"
              "--- a/calc.py\n+++ b/calc.py\n"
              "@@ -1,2 +1,2 @@\n def divide(a, b):\n"
              "-    return a // b\n+    return a / b\n")


class Task2IntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "calc.py").write_text("def divide(a, b):\n    return a // b\n", encoding="utf-8")
        (self.root / "other.py").write_text("def other():\n    return 1\n", encoding="utf-8")
        for cmd in (("init",), ("add", "."), ("-c", "user.name=Demo", "-c", "user.email=demo@example.com", "commit", "-m", "fixture")):
            subprocess.run(["git", "-C", str(self.root), *cmd], check=True, capture_output=True)
        self.commit = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        self.plan = {"repo_root": str(self.root), "base_commit": self.commit,
                     "suspected_files": [{"file_path": "calc.py", "relevant_lines": [1, 2],
                                          "reason": "Uses floor division", "evidence_ids": ["E2"]}],
                     "root_cause_hypothesis": "Floor division loses fractions",
                     "planned_changes": ["Use true division"],
                     "evidence": [{"id": "E2", "tool": "read_file", "result": {
                         "ok": True, "file_path": "calc.py", "lines": [
                             {"line_number": 1, "text": "def divide(a, b):"},
                             {"line_number": 2, "text": "    return a // b"}]}}]}

    def test_patch_applies_in_isolated_worktree(self):
        result = apply_repair_plan("divide(3,2) should be 1.5", self.plan, coder_completion=lambda _: GOOD_PATCH)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["changed_files"], ["calc.py"])
        self.assertEqual(result["test_status"], "not_run")
        self.assertEqual((self.root / "calc.py").read_text(), "def divide(a, b):\n    return a // b\n")
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.root), "status", "--porcelain"]), b"")

    def test_candidate_whitelist_rejects_other_file(self):
        result = apply_repair_plan("bug", self.plan, coder_completion=lambda _: GOOD_PATCH.replace("calc.py", "other.py"))
        self.assertEqual(result["status"], "patch_invalid")

    def test_malformed_model_output(self):
        result = apply_repair_plan("bug", self.plan, coder_completion=lambda _: "Use / instead")
        self.assertEqual(result["status"], "generation_failed")

    def test_no_candidates(self):
        result = apply_repair_plan("bug", dict(self.plan, suspected_files=[]), coder_completion=lambda _: GOOD_PATCH)
        self.assertEqual(result["status"], "generation_failed")

    def test_patch_does_not_apply(self):
        result = apply_repair_plan("bug", self.plan,
                                   coder_completion=lambda _: GOOD_PATCH.replace("return a // b", "return a ** b"))
        self.assertEqual(result["status"], "apply_failed")

    def test_task1_schema_evidence(self):
        messages = build_messages("division bug", self.plan)
        self.assertIn("suspected_files", messages[1]["content"])
        self.assertIn("a // b", messages[1]["content"])

    def test_pipeline_bridge(self):
        fake = SimpleNamespace(run_localization=lambda *args, **kwargs: self.plan)
        with patch.dict(sys.modules, {"pipeline_agent": fake}):
            result = run_repair("division bug", str(self.root), self.commit,
                                planner_completion=lambda _: json.dumps({"action": "final"}),
                                coder_completion=lambda _: GOOD_PATCH)
        self.assertEqual(result["patch_result"]["status"], "applied")
        self.assertFalse(result["patch_result"]["execution_verified"])


    def test_real_task1_to_task2_end_to_end_offline(self):
        # This path does NOT mock run_localization. It exercises the actual
        # Task 1 Planner, real search_repo/read_file, Task 2 Coder contract,
        # Git validation and isolated patch application.
        actions = iter([
            {"action": "search_repo", "arguments": {"query": "divide"}},
            {"action": "read_file", "arguments": {
                "relative_path": "calc.py", "start_line": 1, "end_line": 2}},
            {"action": "final", "plan": {
                "issue_summary": "Division unexpectedly truncates fractions",
                "suspected_files": self.plan["suspected_files"],
                "root_cause_hypothesis": "The floor division discards fractions",
                "planned_changes": ["Change // to /"],
                "limitations": ["Scripted offline Planner; correctness unverified"]}}
        ])
        output = run_repair(
            "divide(3,2) should return 1.5", str(self.root), self.commit,
            planner_completion=lambda _: json.dumps(next(actions)),
            coder_completion=lambda _: GOOD_PATCH,
        )
        self.assertEqual(output["plan"]["suspected_files"][0]["file_path"], "calc.py")
        self.assertEqual(len(output["plan"]["evidence"]), 2)
        self.assertEqual(output["patch_result"]["status"], "applied")
        self.assertFalse(output["patch_result"]["execution_verified"])
        self.assertEqual(
            (self.root / "calc.py").read_text(encoding="utf-8"),
            "def divide(a, b):\\n    return a // b\\n".replace("\\n", "\n"),
        )


if __name__ == "__main__":
    unittest.main()
