"""Unit and offline integration tests for Qwen endpoint and real dev adapter."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from patchloop_task2.qwen import QWEN_MODEL, validate_qwen_configuration, verify_qwen_endpoint
from swebench_dev import DevelopmentTask, sanitize_task, make_prediction, run_dev_instance


GOOD_PATCH = (
    "diff --git a/calc.py b/calc.py\n"
    "--- a/calc.py\n+++ b/calc.py\n"
    "@@ -1,2 +1,2 @@\n def divide(a, b):\n"
    "-    return a // b\n+    return a / b\n"
)


class QwenConfigTests(unittest.TestCase):
    def test_qwen_config_requires_explicit_matching_model(self):
        info = validate_qwen_configuration({
            "OPENAI_MODEL": QWEN_MODEL,
            "OPENAI_BASE_URL": "http://localhost:8000/v1",
        })
        self.assertEqual(info["model"], QWEN_MODEL)
        with self.assertRaises(ValueError):
            validate_qwen_configuration({
                "OPENAI_MODEL": "gpt-3.5-turbo",
                "OPENAI_BASE_URL": "http://localhost:8000/v1",
            })
        with self.assertRaises(ValueError):
            validate_qwen_configuration({
                "OPENAI_MODEL": QWEN_MODEL,
                "OPENAI_BASE_URL": "https://api.openai.com/v1",
            })

    def test_qwen_preflight_invokes_real_endpoint_contract(self):
        usage = SimpleNamespace(prompt_tokens=5, completion_tokens=1)
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="READY"))],
            usage=usage)
        client = SimpleNamespace(
            models=SimpleNamespace(list=lambda: SimpleNamespace(data=[
                SimpleNamespace(id=QWEN_MODEL)])),
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: completion)),
        )
        environ = {"OPENAI_MODEL": QWEN_MODEL,
                   "OPENAI_BASE_URL": "http://localhost:8000/v1"}
        with patch("patchloop_task2.qwen.os.environ", environ):
            actual = verify_qwen_endpoint(client)
        self.assertTrue(actual["chat_ok"])
        self.assertEqual(actual["completion_tokens"], 1)


class SWEDevTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "repo"
        self.root.mkdir()
        (self.root / "calc.py").write_text(
            "def divide(a, b):\n    return a // b\n", encoding="utf-8")
        for args in (
            ("init",), ("add", "."),
            ("-c", "user.name=Dev", "-c", "user.email=test@example.com",
             "commit", "-m", "baseline"),
        ):
            subprocess.run(["git", "-C", str(self.root), *args],
                           check=True, capture_output=True)
        self.commit = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            text=True).strip()
        self.task = DevelopmentTask(
            instance_id="pytest-dev__pytest-12345",
            repo="pytest-dev/pytest", base_commit=self.commit,
            problem_statement="divide(3,2) must return 1.5",
        )

    def test_whitelist_prevents_gold_or_tests_in_agent_task(self):
        item = {"instance_id": self.task.instance_id, "repo": self.task.repo,
                "base_commit": self.task.base_commit,
                "problem_statement": self.task.problem_statement,
                "patch": "SECRET_GOLD",
                "test_patch": "SECRET_HIDDEN_TEST",
                "FAIL_TO_PASS": "SECRET_LABEL", "hints_text": "SECRET_HINT"}
        clean = sanitize_task(item)
        self.assertNotIn("SECRET", json.dumps(clean.__dict__))
        self.assertEqual(set(clean.__dict__), {
            "instance_id", "repo", "base_commit", "problem_statement"})

    def test_predict_offline_uses_real_task_contract_and_exports_only_candidate(self):
        actions = iter([
            {"action": "search_repo", "arguments": {"query": "divide"}},
            {"action": "read_file", "arguments": {
                "relative_path": "calc.py", "start_line": 1, "end_line": 2}},
            {"action": "final", "plan": {
                "issue_summary": "Floor division is incorrect",
                "suspected_files": [{"file_path": "calc.py",
                                     "relevant_lines": [1, 2],
                                     "reason": "floor division", "evidence_ids": ["E2"]}],
                "root_cause_hypothesis": "Using // loses fraction",
                "planned_changes": ["Use /"],
                "limitations": ["Offline scripted model, no execution tests"]}},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            status = run_dev_instance(
                self.task, self.root, Path(tmp) / "out",
                planner_completion=lambda _: json.dumps(next(actions)),
                coder_completion=lambda _: GOOD_PATCH,
            )
            self.assertEqual(status["patch_status"], "applied")
            payload = json.loads((Path(tmp) / "out/predictions.jsonl").read_text())
            self.assertEqual(payload["instance_id"], self.task.instance_id)
            self.assertEqual(payload["model_patch"], GOOD_PATCH)
            self.assertEqual(payload["model_name_or_path"], "scripted-offline")
            self.assertFalse(status["official_evaluated"])
            self.assertEqual(subprocess.check_output(
                ["git", "-C", str(self.root), "status", "--porcelain"]), b"")

    def test_prediction_requires_patch(self):
        with self.assertRaises(ValueError):
            make_prediction(self.task.instance_id, "not a patch")


if __name__ == "__main__":
    unittest.main()
