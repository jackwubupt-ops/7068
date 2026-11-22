"""Offline tests for execution feedback (run_tests tool + post-apply regression check).

Docker is replaced by a scripted runner (labelled): these prove the sandbox argv,
the validation, the regression rule and the agent wiring, NOT real test results.
"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments.deepseek_swebench_dev import run_real_dev
from patchloop_task2.single_agent import run_single_agent
from patchloop_task2.test_exec import (RunResult, TestEnv, TestTool, _docker_argv, parse_outcomes,
                                       regression_message, swebench_image)
from swebench_dev import DevelopmentTask
from tests.test_edit_blocks import ORIGINAL, block, make_repo

ENV = TestEnv("swebench/sweb.eval.x86_64.o_1776_r-1:latest", "swebench")
TEST_FILE = "def test_f():\n    pass\n"


def fake_runner(results):
    """results(patch) -> outcomes; records every call."""
    calls = []

    def run(env, checkout, base, patch, targets):
        calls.append((patch, list(targets)))
        outcome = results(patch)
        if isinstance(outcome, RunResult):
            return outcome
        return RunResult("completed", 0 if all(v == "PASSED" for v in outcome.values()) else 1,
                         outcome, "log tail", 1.5)
    run.calls = calls
    return run


class ParsingAndArgvTests(unittest.TestCase):
    def test_parse_pytest_and_unittest_output(self):
        text = ("PASSED tests/test_a.py::test_one\nFAILED tests/test_a.py::test_two - AssertionError\n"
                "ERROR tests/test_b.py::test_x\nSKIPPED [1] tests/test_a.py:9: no\n"
                "test_div (tests.test_calc.CalcTest.test_div) ... ok\n"
                "test_add (test_calc.CalcTest) ... FAIL\n")
        self.assertEqual(parse_outcomes(text), {
            "tests/test_a.py::test_one": "PASSED", "tests/test_a.py::test_two": "FAILED",
            "tests/test_b.py::test_x": "ERROR", "tests.test_calc.CalcTest.test_div": "PASSED",
            "test_calc.CalcTest.test_add": "FAILED"})

    def test_sandbox_argv_keeps_targets_out_of_the_shell_script(self):
        argv = _docker_argv(ENV, "n", ["tests/test_a.py::test_one"], apply=True, worktree=None)
        script = argv[argv.index("-c") + 1]
        self.assertNotIn("test_a", script)
        self.assertEqual(argv[-1], "tests/test_a.py::test_one")
        for flag in (["--network", "none"], ["--cap-drop", "ALL"], ["--pull", "never"]):
            i = argv.index(flag[0])
            self.assertEqual(argv[i:i + 2], flag)
        self.assertIn("APPLY=1", argv)
        mount = _docker_argv(TestEnv("python:3.11-slim", "mount", python="python"), "n", ["t/test_x.py"],
                             apply=False, worktree=Path("/tmp/wt"))
        self.assertIn("--read-only", mount)
        self.assertIn("65534:65534", mount)
        self.assertIn("type=bind,src=/tmp/wt,dst=/workspace,readonly", mount)
        self.assertEqual(swebench_image("pydicom__pydicom-1139"),
                         "swebench/sweb.eval.x86_64.pydicom_1776_pydicom-1139:latest")


class TestToolTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo, self.sha = make_repo(Path(temp.name), {
            "pkg/mod.py": ORIGINAL, "tests/test_mod.py": TEST_FILE, "tests/helper.py": "X = 1\n",
            "pkg/other.py": "B = 2\n"})

    def test_target_validation(self):
        tool = TestTool(ENV, self.repo, self.sha, runner=fake_runner(lambda p: {}))
        self.assertEqual(tool.validate_target("tests/test_mod.py::test_f"), "tests/test_mod.py::test_f")
        for bad in ("pkg/mod.py", "tests/test_missing.py", "../tests/test_mod.py", "-x",
                    "tests/test_mod.py; rm -rf /", "/etc/passwd", 7):
            with self.assertRaises(ValueError, msg=bad):
                tool.validate_target(bad)

    def test_tool_runs_at_base_and_is_bounded_and_honest_when_unavailable(self):
        runner = fake_runner(lambda p: {"tests/test_mod.py::test_f": "PASSED"})
        tool = TestTool(ENV, self.repo, self.sha, runner=runner)
        out = tool.run_tool(self.repo, test_path="tests/test_mod.py")
        self.assertTrue(out["ok"])
        self.assertEqual(out["counts"], {"PASSED": 1})
        self.assertIsNone(runner.calls[0][0])                # base commit: no patch
        self.assertEqual(tool.requested, ["tests/test_mod.py"])
        tool.run_tool(self.repo, test_path="tests/test_mod.py::test_f")
        tool.run_tool(self.repo, test_path="tests/test_mod.py::test_f")
        self.assertIn("at most 3", tool.run_tool(self.repo, test_path="tests/test_mod.py")["error"])
        off = TestTool(None, self.repo, self.sha).run_tool(self.repo, test_path="tests/test_mod.py")
        self.assertFalse(off["ok"])
        self.assertIn("unavailable", off["error"])

    def test_check_patch_regression_rules(self):
        base = {"tests/test_mod.py::test_f": "PASSED", "tests/test_mod.py::test_g": "FAILED"}
        cases = {
            "broken": ({"tests/test_mod.py::test_f": "FAILED", "tests/test_mod.py::test_g": "FAILED"},
                       "regressions"),
            "fixed": ({"tests/test_mod.py::test_f": "PASSED", "tests/test_mod.py::test_g": "PASSED"}, "passed"),
            "syntax": ({}, "regressions"),
        }
        for name, (after, expected) in cases.items():
            runner = fake_runner(lambda p, after=after: base if p is None else after)
            tool = TestTool(ENV, self.repo, self.sha, runner=runner)
            check = tool.check_patch("PATCH", ["pkg/mod.py"])
            self.assertEqual(check["status"], expected, name)
            self.assertEqual(check["targets"], ["tests/test_mod.py"])   # found from the changed module
        self.assertEqual(TestTool(ENV, self.repo, self.sha, runner=fake_runner(lambda p: base))
                         .check_patch("P", ["pkg/other.py"])["status"], "no_tests")
        infra = fake_runner(lambda p: base if p is None else RunResult("docker_error", None, {}, "x", 0))
        self.assertEqual(TestTool(ENV, self.repo, self.sha, runner=infra).check_patch("P", ["pkg/mod.py"])["status"],
                         "infra_error")
        self.assertEqual(TestTool(None, self.repo, self.sha).check_patch("P", ["pkg/mod.py"])["status"],
                         "unavailable")

    def test_selection_finds_test_dir_and_embedded_module_names(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        repo, sha = make_repo(Path(temp.name), {
            "src/pkg/rules/L031.py": "X = 1\n", "test/rules/std_L031_test.py": TEST_FILE,
            "test/rules/std_L0310_test.py": TEST_FILE, "test/core/parser_test.py": TEST_FILE,
            "src/pkg/core/parser.py": "Y = 1\n", "test/__init__.py": ""})
        tool = TestTool(ENV, repo, sha, runner=fake_runner(lambda p: {}))
        self.assertEqual(tool.select_targets(["src/pkg/rules/L031.py"]), ["test/rules/std_L031_test.py"])
        self.assertEqual(tool.select_targets(["src/pkg/core/parser.py"]), ["test/core/parser_test.py"])
        self.assertEqual(tool.validate_target("test/rules/std_L031_test.py"), "test/rules/std_L031_test.py")

    def test_regression_message_names_tests(self):
        text = regression_message({"targets": ["t.py"], "regressions": ["t.py::a"], "log_tail": "boom"})
        self.assertIn("t.py::a", text)
        self.assertIn("boom", text)


class SingleAgentExecTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo, self.sha = make_repo(self.root, {"pkg/mod.py": ORIGINAL, "tests/test_mod.py": TEST_FILE})
        self.read = json.dumps({"action": "read_file", "arguments": {"relative_path": "pkg/mod.py"}})
        self.run = json.dumps({"action": "run_tests", "arguments": {"test_path": "tests/test_mod.py"}})
        self.bad = block("    return 0\n\n\ndef g():", "    return 9\n\n\ndef g():")
        self.good = block("    return 0\n\n\ndef g():", "    return -1\n\n\ndef g():")
        self.runner = fake_runner(lambda p: {"tests/test_mod.py::test_f":
                                             "FAILED" if p and "return 9" in p else "PASSED"})

    def agent(self, replies):
        replies = list(replies)
        tool = TestTool(ENV, self.repo, self.sha, runner=self.runner)
        result = run_single_agent("f(0) should return -1", self.repo, self.sha,
                                  completion=lambda m: replies.pop(0), test_tool=tool,
                                  export_path=self.root / "c.patch")
        return result, tool

    def test_regression_goes_back_to_the_agent_then_fix_is_accepted(self):
        result, tool = self.agent([self.run, self.read, self.bad, self.good])
        self.assertEqual(result.status, "prediction_ready")
        self.assertIn("return -1", result.patch)
        self.assertEqual([s["test_check"]["status"] for s in result.submissions], ["regressions", "passed"])
        self.assertEqual([r["kind"] for r in tool.records], ["tool", "check", "check"])

    def test_keeps_earlier_candidate_when_replacement_does_not_apply(self):
        broken = block("not in the file", "x")
        result, _ = self.agent([self.read, self.bad, broken])
        self.assertEqual(result.status, "prediction_ready")
        self.assertIn("return 9", result.patch)
        self.assertIn("return 9", (self.root / "c.patch").read_text())
        self.assertIn("kept_earlier_candidate", result.stop_reason)


class PcrExecTests(unittest.TestCase):
    def test_reviewer_gets_test_regressions_and_coder_retries(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        repo, sha = make_repo(root, {"src/feature.py": "return 1\n", "tests/test_feature.py": TEST_FILE})
        task = DevelopmentTask("o__r-1", "o/r", sha, "feature should return 3")
        d2, d3 = (f"diff --git a/src/feature.py b/src/feature.py\n--- a/src/feature.py\n"
                  f"+++ b/src/feature.py\n@@ -1 +1 @@\n-return 1\n+return {n}\n" for n in (2, 3))
        diffs = iter([d2, d3])
        seen_failures = []

        class Api:
            model = "deepseek-flash"
            calls = []

            def complete(self, stage, messages):
                self.calls.append({"stage": stage})
                return "API_OK"

            def callback(self, stage):
                return lambda messages: self.complete(stage, messages)

        def fake_apply(checkout, base, proposal, *, export_path, allowed_paths):
            Path(export_path).write_text(proposal, encoding="utf-8")
            return SimpleNamespace(status="applied", patch_sha256="a" * 64, error_code=None,
                                   error_message=None, changed_files=["src/feature.py"])

        def fake_review(issue, plan, shown, failure, completion):
            seen_failures.append(failure)
            return {"failure_type": "test_failure", "diagnosis": "d", "suggested_fix": "s"}

        runner = fake_runner(lambda p: {"tests/test_feature.py::test_f": "FAILED" if p and "+return 2" in p else "PASSED"})
        with patch("experiments.deepseek_swebench_dev.run_localization",
                   return_value={"suspected_files": [{"file_path": "src/feature.py"}]}) as plan, \
             patch("experiments.deepseek_swebench_dev._coder", side_effect=lambda *a, **k: next(diffs)), \
             patch("experiments.deepseek_swebench_dev.normalize_hunk_counts", side_effect=lambda d: (d, 0)), \
             patch("experiments.deepseek_swebench_dev.apply_candidate", side_effect=fake_apply), \
             patch("experiments.deepseek_swebench_dev.review_failure", side_effect=fake_review), \
             patch("experiments.deepseek_swebench_dev._clean_source", return_value=True), \
             patch("patchloop_task2.test_exec.docker_run", runner):
            report = run_real_dev(root / "out", api=Api(), task_loader=lambda **k: task,
                                  checkout_fn=lambda t, p: repo, instance_id="o__r-1",
                                  expected_repo=None, expected_base=None,
                                  exec_feedback=True, test_env_fn=lambda iid: ENV)
        self.assertIn("test_tool", plan.call_args.kwargs)
        self.assertEqual(report["status"], "prediction_ready")
        self.assertEqual([a["test_check"]["status"] for a in report["candidate_attempts"]],
                         ["regressions", "passed"])
        self.assertEqual(seen_failures[0]["stage"], "tests")
        self.assertIn("tests/test_feature.py::test_f", seen_failures[0]["log_tail"])
        prediction = json.loads((root / "out" / "predictions.jsonl").read_text())
        self.assertEqual(prediction["model_patch"], d3)
        self.assertTrue(report["exec_feedback"] and report["test_env_available"])


if __name__ == "__main__":
    unittest.main()
