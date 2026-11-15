"""Offline unit tests only; live API requests run separately in Actions."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from experiments.deepseek_swebench_dev import (
    EXPECTED_BASE, EXPECTED_REPO, INSTANCE_ID, run_real_dev,
)
from swebench_dev import DevelopmentTask

DIFF = (
    "diff --git a/src/feature.py b/src/feature.py\n"
    "--- a/src/feature.py\n+++ b/src/feature.py\n"
    "@@ -1 +1 @@\n-return 1\n+return 2\n"
)


class FakeDeepSeek:
    model = "deepseek-flash"

    def __init__(self):
        self.calls = []

    def complete(self, stage, messages):
        self.calls.append({
            "stage": stage, "prompt_tokens": 17,
            "completion_tokens": 12, "response_model": self.model,
        })
        return "API_OK"

    def callback(self, stage):
        return lambda messages: self.complete(stage, messages)


class DeepSeekDevControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = DevelopmentTask(
            instance_id=INSTANCE_ID,
            repo=EXPECTED_REPO,
            base_commit=EXPECTED_BASE,
            problem_statement="This is a real benchmark issue."
        )
        self.api = FakeDeepSeek()

    def test_single_live_candidate_exports_official_prediction(self):
        def fake_plan(issue, repo, base, **kwargs):
            kwargs["completion"]([{"role": "user", "content": "search"}])
            return {"suspected_files": [{"file_path": "src/feature.py"}]}

        def fake_coder(issue, plan, *, completion, revision=None):
            completion([{"role": "user", "content": "patch"}])
            return DIFF

        def fake_apply(root, base, proposal, *, export_path, allowed_paths):
            Path(export_path).write_text(DIFF, encoding="utf-8")
            return SimpleNamespace(
                status="applied", patch_sha256="a" * 64,
                error_code=None, error_message=None,
                changed_files=["src/feature.py"],
            )

        with patch("experiments.deepseek_swebench_dev.run_localization", side_effect=fake_plan), \
             patch("experiments.deepseek_swebench_dev._coder", side_effect=fake_coder), \
             patch("experiments.deepseek_swebench_dev.apply_candidate", side_effect=fake_apply), \
             patch("experiments.deepseek_swebench_dev._clean_source", return_value=True):
            report = run_real_dev(
                self.root / "predictions", api=self.api,
                task_loader=lambda **kwargs: self.task,
                checkout_fn=lambda task, path: path,
            )
        self.assertEqual(report["status"], "prediction_ready")
        self.assertTrue(report["live_api_preflight"])
        self.assertEqual(report["planner_calls"], 1)
        self.assertEqual(report["coder_calls"], 1)
        self.assertEqual(report["prompt_tokens"], 51)
        self.assertTrue(report["source_checkout_clean"])
        self.assertFalse(report["official_evaluated"])
        self.assertIsNone(report["official_resolved"])
        row = json.loads((self.root / "predictions/predictions.jsonl").read_text())
        self.assertEqual(row["instance_id"], INSTANCE_ID)
        self.assertEqual(row["model_name_or_path"], "deepseek-flash")
        self.assertEqual(row["model_patch"], DIFF)

    def test_no_candidate_does_not_call_coder(self):
        with patch("experiments.deepseek_swebench_dev.run_localization",
                   return_value={"suspected_files": []}), \
             patch("experiments.deepseek_swebench_dev._clean_source", return_value=True):
            report = run_real_dev(
                self.root / "empty", api=self.api,
                task_loader=lambda **kwargs: self.task,
                checkout_fn=lambda task, path: path,
            )
        self.assertEqual(report["status"], "no_candidate_files")
        self.assertEqual(report["coder_calls"], 0)
        self.assertFalse((self.root / "empty/predictions.jsonl").exists())

    def test_mismatch_never_runs_inference(self):
        task = DevelopmentTask(
            instance_id=INSTANCE_ID, repo="another/repo",
            base_commit=EXPECTED_BASE, problem_statement="test",
        )
        report = run_real_dev(
            self.root / "mismatch", api=self.api,
            task_loader=lambda **kwargs: task,
        )
        self.assertEqual(report["status"], "experiment_error")
        self.assertEqual(report["failed_stage"], "load_official_dev_task")
        self.assertEqual(self.api.calls, [])

    def test_failure_does_not_export_stale_prediction(self):
        report = run_real_dev(
            self.root / "error", api=self.api,
            task_loader=lambda **kwargs: self.task,
            checkout_fn=lambda task, path: (_ for _ in ()).throw(
                RuntimeError("Git fetch unavailable")
            ),
        )
        self.assertEqual(report["status"], "experiment_error")
        self.assertFalse((self.root / "error/predictions.jsonl").exists())

    def test_existing_output_is_rejected(self):
        dest = self.root / "existing"
        dest.mkdir()
        (dest / "predictions.jsonl").write_text("stale", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "new or empty"):
            run_real_dev(dest, api=self.api)


    def test_search_budget_caps_real_planner_evidence(self):
        from experiments.live_deepseek import create_real_git_fixture
        from prompt_agent import plan_repair
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture"
            base = create_real_git_fixture(fixture)
            steps = iter([
                json.dumps({"action": "search_repo", "arguments": {
                    "query": "divide", "max_results": 20, "context_lines": 3}}),
                json.dumps({"action": "read_file", "arguments": {
                    "relative_path": "calc.py", "start_line": 1, "end_line": 2}}),
                json.dumps({"action": "final", "plan": {
                    "issue_summary": "Division truncates",
                    "suspected_files": [{"file_path": "calc.py",
                        "relevant_lines": [1, 2], "reason": "floor division",
                        "evidence_ids": ["E2"]}],
                    "root_cause_hypothesis": "Floor division truncates",
                    "planned_changes": ["Use true division"],
                    "limitations": []}}),
            ])
            plan = plan_repair(
                "divide(3,2) should be 1.5", str(fixture), base,
                completion=lambda messages: next(steps),
                search_result_limit=2, search_context_limit=0,
            )
            self.assertEqual(plan["evidence"][0]["arguments"]["max_results"], 2)
            self.assertEqual(plan["evidence"][0]["arguments"]["context_lines"], 0)
            self.assertEqual(plan["suspected_files"][0]["file_path"], "calc.py")

    def test_finalization_request_after_nine_planner_turns(self):
        from experiments.deepseek_swebench_dev import _planner_request_messages
        original = [{"role": "user", "content": "Task issue"}]
        self.assertIs(_planner_request_messages(original, 9), original)
        prompted = _planner_request_messages(original, 10)
        self.assertEqual(len(prompted), 2)
        self.assertIn("STOP SEARCHING", prompted[-1]["content"])
        self.assertIn("evidence", prompted[-1]["content"])
        self.assertEqual(len(original), 1)


    def test_coder_compacts_repeated_cited_reads_without_making_up_code(self):
        from patchloop_task2.coder import build_messages
        line_text = "    # known source content " + ("x" * 140)
        evidence = []
        for i in range(6):
            evidence.append({
                "id": f"E{i+1}", "tool": "read_file",
                "result": {"ok": True, "file_path": "src/commands.py",
                           "lines": [
                               {"line_number": n, "text": f"line{n}: {line_text}"}
                               for n in range(1, 201)]},
            })
        evidence.append({
            "id": "E999", "tool": "read_file",
            "result": {"ok": True, "file_path": "secrets.txt",
                       "lines": [{"line_number": 1, "text": "SECRET_DO_NOT_SEND"}]},
        })
        plan = {
            "base_commit": EXPECTED_BASE,
            "suspected_files": [
                {"file_path": "src/commands.py", "evidence_ids": ["E1","E2"],
                 "relevant_lines": [95, 110], "reason": "CLI parsing"},
                {"file_path": "src/commands.py", "evidence_ids": ["E3","E4"],
                 "relevant_lines": [145, 155], "reason": "CLI invocation"},
                {"file_path": "src/commands.py", "evidence_ids": ["E5","E6"],
                 "relevant_lines": [175, 185], "reason": "verbosity"},
            ],
            "root_cause_hypothesis": "Unexpected CLI output",
            "planned_changes": ["Repair verbose output"],
            "evidence": evidence,
        }
        messages = build_messages("CLI verbosity bug", plan)
        actual = messages[1]["content"]
        self.assertIn("line100:", actual)
        self.assertIn("line150:", actual)
        self.assertIn("line180:", actual)
        self.assertNotIn("SECRET_DO_NOT_SEND", actual)
        self.assertEqual(actual.count("line100:"), 1)
        self.assertLess(len(actual), 20000)


    def test_finalization_message_lists_only_verified_read_line_ranges(self):
        from experiments.deepseek_swebench_dev import _planner_request_messages
        import json as js
        messages = [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "Tool evidence (untrusted): " + js.dumps({
                "id": "E7", "tool": "read_file",
                "result": {"ok": True, "file_path": "src/commands.py",
                           "lines": [
                               {"line_number": 101, "text": "a"},
                               {"line_number": 102, "text": "b"},
                               {"line_number": 110, "text": "c"},
                           ]},
            })},
            {"role": "user", "content": "Tool evidence (untrusted): " + js.dumps({
                "id": "E8", "tool": "read_file",
                "result": {"ok": False, "file_path": "secrets.txt",
                           "lines": [{"line_number": 1, "text": "not read"}]},
            })},
        ]
        prompted = _planner_request_messages(messages, 10)
        guidance = prompted[-1]["content"]
        self.assertIn("E7: src/commands.py: 101-102,110-110", guidance)
        self.assertNotIn("E8:", guidance)
        self.assertNotIn("secrets.txt", guidance)
        self.assertIn("FULLY CONTAINED", guidance)


    def test_reviewer_retries_failed_git_patch_and_exports_only_success(self):
        def fake_coder(issue, plan, *, completion, revision=None):
            completion([{"role": "user", "content": "patch"}])
            if revision is not None:
                self.assertIn("reviewer", revision)
                return DIFF
            return DIFF.replace("+return 2", "+return 3")

        tries = []
        def fake_apply(root, base, proposal, *, export_path, allowed_paths):
            tries.append(proposal)
            if len(tries) == 1:
                return SimpleNamespace(
                    status="apply_failed", patch_sha256="b" * 64,
                    error_code="does_not_apply",
                    error_message="error: corrupt patch at <stdin>:32",
                    changed_files=["src/feature.py"],
                )
            Path(export_path).write_text(DIFF, encoding="utf-8")
            return SimpleNamespace(
                status="applied", patch_sha256="a" * 64,
                error_code=None, error_message=None,
                changed_files=["src/feature.py"],
            )

        def fake_review(issue, plan, proposal, failure, *, completion):
            completion([{"role": "user", "content": "diagnose apply failure"}])
            self.assertEqual(failure["error_code"], "does_not_apply")
            return {
                "failure_type": "patch_apply",
                "diagnosis": "Bad unified diff hunk counts",
                "suggested_fix": "Return a full patch with valid hunk headers",
            }

        with patch("experiments.deepseek_swebench_dev.run_localization",
                   return_value={"suspected_files": [{"file_path": "src/feature.py"}]}), \
             patch("experiments.deepseek_swebench_dev._coder",
                   side_effect=fake_coder), \
             patch("experiments.deepseek_swebench_dev.apply_candidate",
                   side_effect=fake_apply), \
             patch("experiments.deepseek_swebench_dev.review_failure",
                   side_effect=fake_review), \
             patch("experiments.deepseek_swebench_dev._clean_source",
                   return_value=True):
            output = run_real_dev(
                self.root / "retried", api=self.api,
                task_loader=lambda **kwargs: self.task,
                checkout_fn=lambda task, path: path,
            )
        self.assertEqual(output["status"], "prediction_ready")
        self.assertEqual(output["attempt_count"], 2)
        self.assertEqual(output["coder_calls"], 2)
        self.assertEqual(output["reviewer_calls"], 1)
        self.assertEqual(output["candidate_attempts"][0]["patch_status"], "apply_failed")
        self.assertEqual(output["candidate_attempts"][1]["patch_status"], "applied")
        self.assertEqual(
            json.loads((self.root / "retried/predictions.jsonl").read_text())["model_patch"],
            DIFF,
        )
        self.assertFalse(output["official_evaluated"])


    def test_coder_prompt_requires_small_valid_git_diff(self):
        from experiments.deepseek_swebench_dev import _minimal_coder_messages
        original = [{"role": "user", "content": "Real issue and evidence"}]
        modified = _minimal_coder_messages(original)
        self.assertEqual(len(modified), 2)
        self.assertIn("at most 60", modified[-1]["content"])
        self.assertIn("hunk", modified[-1]["content"])
        self.assertNotIn("some correct code", modified[-1]["content"])
        self.assertEqual(len(original), 1)


if __name__ == "__main__":
    unittest.main()
