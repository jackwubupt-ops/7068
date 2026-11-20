"""Offline tests for the single-agent baseline (scripted replies + real Git).

These prove wiring and the protocol only, NOT live model quality.
"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from experiments.qwen_small_dev import run_qwen_dev
from patchloop_task2.qwen_small import QwenSettings, QwenSmallBackend
from patchloop_task2.single_agent import run_single_agent
from swebench_dev import DevelopmentTask
from tests.test_edit_blocks import ORIGINAL, block, make_repo

SEARCH = json.dumps({"action": "search_repo", "arguments": {"query": "def g"}})
READ = json.dumps({"action": "read_file", "arguments": {"relative_path": "pkg/mod.py"}})
GOOD = block("    return 0\n\n\ndef g():", "    return -1\n\n\ndef g():")


class Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages):
        self.seen.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class SingleAgentLoopTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo, self.sha = make_repo(self.root, {"pkg/mod.py": ORIGINAL, "pkg/other.py": "B = 2\n"})

    def run_agent(self, replies, **kwargs):
        model = Scripted(replies)
        result = run_single_agent("f(0) should return -1", self.repo, self.sha, completion=model,
                                  export_path=self.root / "candidate.patch", **kwargs)
        return result, model

    def test_search_read_submit_reaches_prediction_ready(self):
        result, model = self.run_agent([SEARCH, READ, GOOD])
        self.assertEqual(result.status, "prediction_ready")
        self.assertEqual([e["action"] for e in result.trace], ["search_repo", "read_file", "submit"])
        self.assertEqual(result.read_files, ["pkg/mod.py"])
        self.assertIn("+    return -1", (self.root / "candidate.patch").read_text())
        # Tool results really reach the model.
        self.assertIn("Tool result (untrusted)", model.seen[2][-1]["content"])
        self.assertIn("SEARCH/REPLACE", model.seen[0][0]["content"])

    def test_cannot_edit_before_reading_or_edit_unread_files(self):
        unread = block("B = 2", "B = 3", path="pkg/other.py")
        result, model = self.run_agent([GOOD, READ, unread], max_submissions=2)
        self.assertEqual(result.status, "patch_failed")
        first, second = result.submissions
        self.assertEqual(first["error_code"], "invalid_submission")
        self.assertEqual(second["error_code"], "path_not_allowed")
        self.assertIn("Submission rejected", model.seen[1][-1]["content"])

    def test_failed_submission_feedback_then_retry_succeeds(self):
        bad = block("    return zero", "    return -1")
        result, model = self.run_agent([READ, bad, GOOD])
        self.assertEqual(result.status, "prediction_ready")
        self.assertEqual([s["patch_status"] for s in result.submissions], ["edit_invalid", "applied"])
        self.assertIn("search_not_found", model.seen[2][-1]["content"])

    def test_protocol_errors_do_not_stop_the_agent(self):
        result, model = self.run_agent(["not json", json.dumps({"action": "run_tests"}), READ, GOOD])
        self.assertEqual(result.status, "prediction_ready")
        self.assertIn("Protocol error", model.seen[1][-1]["content"])
        self.assertEqual(result.trace[1]["action"], "run_tests")
        self.assertIn("protocol_error", result.trace[1])

    def test_fenced_json_actions_are_accepted_like_planner(self):
        fence = chr(96) * 3
        fenced_search = fence + "json\n" + SEARCH + "\n" + fence
        fenced_read = fence + "\n" + READ + "\n" + fence
        result, _ = self.run_agent([fenced_search, fenced_read, GOOD])
        self.assertEqual(result.status, "prediction_ready")
        self.assertEqual([e["action"] for e in result.trace], ["search_repo", "read_file", "submit"])
        self.assertNotIn("protocol_error", result.trace[0])

    def test_repeated_identical_action_is_not_rerun_and_agent_is_nudged(self):
        result, model = self.run_agent([SEARCH, READ, SEARCH, READ, GOOD])
        self.assertEqual(result.status, "prediction_ready")
        self.assertEqual([e.get("repeat_of_step") for e in result.trace], [None, None, 1, 2, None])
        self.assertIn("Repeated action", model.seen[3][-1]["content"])
        self.assertIn("submit your SEARCH/REPLACE edit", model.seen[3][-1]["content"])
        # Repeats still consume the shared step budget.
        result, _ = self.run_agent([SEARCH, SEARCH, SEARCH], max_steps=3)
        self.assertEqual((result.status, result.stop_reason), ("no_submission", "step_budget_exhausted"))

    def test_same_file_different_range_is_not_a_repeat(self):
        other = json.dumps({"action": "read_file", "arguments": {"relative_path": "pkg/mod.py", "start_line": 2}})
        result, _ = self.run_agent([READ, other, GOOD])
        self.assertEqual(result.status, "prediction_ready")
        self.assertNotIn("repeat_of_step", result.trace[1])

    def test_protocol_error_records_raw_head(self):
        result, _ = self.run_agent(["<tool_call>oops", READ, GOOD])
        self.assertEqual(result.trace[0]["raw_head"], "<tool_call>oops")

    def test_budget_and_step_exhaustion_end_without_submission(self):
        result, _ = self.run_agent([READ, RuntimeError("QWEN_CALL_BUDGET_EXHAUSTED")])
        self.assertEqual(result.status, "no_submission")
        self.assertEqual(result.stop_reason, "QWEN_CALL_BUDGET_EXHAUSTED")
        result, _ = self.run_agent([SEARCH, READ, SEARCH], max_steps=3)
        self.assertEqual((result.status, result.stop_reason), ("no_submission", "step_budget_exhausted"))

    def test_other_runtime_errors_propagate(self):
        with self.assertRaises(RuntimeError):
            self.run_agent([RuntimeError("QWEN_TRUNCATED_OUTPUT:agent")])

    def test_diff_format_submission(self):
        diff = ("diff --git a/pkg/mod.py b/pkg/mod.py\n--- a/pkg/mod.py\n+++ b/pkg/mod.py\n"
                "@@ -6,3 +6,3 @@\n \n def g():\n-    return 0\n+    return 9\n")
        result, model = self.run_agent([READ, diff], edit_format="diff")
        self.assertEqual(result.status, "prediction_ready", result.submissions)
        self.assertIn("unified diff", model.seen[0][0]["content"])


class FakeBackend:
    """Mimics QwenSmallBackend's interface with scripted replies."""
    model = "Qwen/Qwen2.5-Coder-7B-Instruct"

    def __init__(self, replies):
        self.script = Scripted(replies)
        self.calls = []

    def callback(self, stage):
        def complete(messages):
            self.calls.append({"stage": stage, "prompt_tokens": 10, "completion_tokens": 5})
            return self.script(messages)
        return complete


class SingleDevRunTests(unittest.TestCase):
    def test_run_qwen_dev_single_writes_labelled_prediction_and_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, sha = make_repo(root, {"pkg/mod.py": ORIGINAL})
            task = DevelopmentTask(instance_id="owner__proj-1", repo="owner/proj",
                                   base_commit=sha, problem_statement="f(0) should return -1")
            out = root / "out"
            out.mkdir()
            report = run_qwen_dev(
                FakeBackend([SEARCH, READ, GOOD]), out, agent="single", edit_format="search_replace",
                instance_id=task.instance_id, expected_repo=task.repo, expected_base=sha,
                task_loader=lambda instance_id: task, checkout_fn=lambda t, p: repo,
            )
            self.assertEqual(report["status"], "prediction_ready", report.get("error"))
            self.assertEqual(report["agent"], "single")
            self.assertEqual(report["agent_calls"], 3)
            self.assertEqual(report["suspected_files"], ["pkg/mod.py"])
            self.assertTrue(report["source_checkout_clean"])
            prediction = json.loads((out / "predictions.jsonl").read_text())
            self.assertEqual(prediction["model_name_or_path"], "qwen2.5-coder-7b-instruct-single-agent")
            self.assertEqual(prediction["model_patch"], (out / "candidate.patch").read_text())
            saved = json.loads((out / "run_status.json").read_text())
            self.assertEqual(saved["experiment"], "qwen-single-agent-swebench-dev-v1")

    def test_unknown_agent_rejected(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            run_qwen_dev(FakeBackend([]), Path(temp), agent="swarm")


class AgentStageBackendTests(unittest.TestCase):
    def test_agent_stage_uses_coder_cap_and_trims_history(self):
        sent = {}

        def create(**kwargs):
            sent.update(kwargs)
            return SimpleNamespace(
                model="m", usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="{}"))])

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        backend = QwenSmallBackend(QwenSettings(model="Qwen/Qwen2.5-Coder-7B-Instruct",
                                                context_chars=5000), client=client)
        history = [{"role": "system", "content": "s"}, {"role": "user", "content": "issue"}]
        history += [{"role": "user", "content": "x" * 1000} for _ in range(10)]
        backend.complete("agent", history)
        self.assertEqual(sent["max_tokens"], 3500)
        self.assertLess(len(sent["messages"]), len(history))
        self.assertGreater(backend.calls[0]["dropped_history_messages"], 0)


if __name__ == "__main__":
    unittest.main()
