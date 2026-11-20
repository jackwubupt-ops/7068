"""Offline tests for batch-level official evaluation and paired statistics (no Docker)."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments import official_eval, paired_compare
from experiments.official_eval import classify, harness_command, load_batch, model_label, report_filename
from experiments.paired_compare import bootstrap_diff_ci, compare, mcnemar_exact

IDS = ["a__a-1", "b__b-2", "c__c-3", "d__d-4"]


def write_batch(root: Path, preds: list[dict], ids=IDS) -> Path:
    root.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "dataset": "princeton-nlp/SWE-bench_Lite", "split": "dev", "instance_ids": ids,
        "agent": "pcr", "edit_format": "search_replace", "model": "Qwen/Qwen2.5-Coder-7B-Instruct"}))
    (root / "all_preds.jsonl").write_text("".join(json.dumps(p) + "\n" for p in preds))
    return root


def pred(iid, label="qwen-7b-pcr"):
    return {"instance_id": iid, "model_name_or_path": label, "model_patch": "diff --git a/x b/x\n"}


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_denominator_is_full_task_list(self):
        batch = write_batch(self.root / "b", [pred(IDS[0]), pred(IDS[1])])
        manifest, preds = load_batch(batch)
        result = classify(manifest, preds, {"resolved_ids": [IDS[0]], "unresolved_ids": [IDS[1]]})
        self.assertEqual(result["total_tasks"], 4)
        self.assertEqual(result["resolved"], 1)
        self.assertEqual(result["resolved_rate"], 0.25)
        self.assertEqual(result["tasks"][IDS[2]], "no_prediction")
        self.assertTrue(result["complete"])

    def test_harness_errors_and_missing_verdicts_mark_incomplete(self):
        batch = write_batch(self.root / "b", [pred(i) for i in IDS[:3]])
        manifest, preds = load_batch(batch)
        result = classify(manifest, preds, {"resolved_ids": [], "unresolved_ids": [IDS[0]],
                                            "error_ids": [IDS[1]]})
        self.assertEqual(result["tasks"][IDS[1]], "harness_error")
        self.assertEqual(result["tasks"][IDS[2]], "not_evaluated")
        self.assertFalse(result["complete"])

    def test_no_report_means_nothing_evaluated(self):
        batch = write_batch(self.root / "b", [pred(IDS[0])])
        manifest, preds = load_batch(batch)
        result = classify(manifest, preds, None)
        self.assertEqual(result["tasks"][IDS[0]], "not_evaluated")
        self.assertFalse(result["complete"])

    def test_rejects_foreign_or_duplicate_predictions(self):
        with self.assertRaises(ValueError):
            load_batch(write_batch(self.root / "x", [pred("zzz__z-9")]))
        with self.assertRaises(ValueError):
            load_batch(write_batch(self.root / "y", [pred(IDS[0]), pred(IDS[0])]))

    def test_model_label_must_be_unique(self):
        with self.assertRaises(ValueError):
            model_label([pred(IDS[0], "a"), pred(IDS[1], "b")])
        self.assertEqual(report_filename("org/model", "r1"), "org__model.r1.json")

    def test_harness_command_uses_prebuilt_images_and_manifest_dataset(self):
        manifest = {"dataset": "princeton-nlp/SWE-bench_Lite", "split": "dev"}
        cmd = harness_command("py", manifest, Path("/p.jsonl"), "r1", ["a", "b"],
                              max_workers=4, timeout=900)
        self.assertEqual(cmd[cmd.index("--namespace") + 1], "swebench")
        self.assertEqual(cmd[cmd.index("--split") + 1], "dev")
        self.assertEqual(cmd[cmd.index("--instance_ids") + 1:cmd.index("--instance_ids") + 3], ["a", "b"])

    def test_main_runs_harness_in_batch_official_dir_and_refuses_reused_run_id(self):
        batch = write_batch(self.root / "lite-run", [pred(IDS[0])])

        def fake_run(cmd, cwd, env):
            Path(cwd, "qwen-7b-pcr.lite-run.json").write_text(json.dumps(
                {"resolved_ids": [IDS[0]], "unresolved_ids": []}))
            return type("R", (), {"returncode": 0})()

        with patch.object(official_eval, "check_harness_version", return_value="4.1.0"), \
             patch.object(official_eval.subprocess, "run", side_effect=fake_run):
            code = official_eval.main(["--batch", str(batch)])
            self.assertEqual(code, 0)  # unpredicted tasks are verdicts (not solved), not gaps
        result = json.loads((batch / "official_eval.json").read_text())
        self.assertEqual(result["tasks"][IDS[0]], "resolved")
        with patch.object(official_eval, "check_harness_version", return_value="4.1.0"), \
             self.assertRaises(SystemExit):
            official_eval.main(["--batch", str(batch)])


class PairedTests(unittest.TestCase):
    def test_mcnemar_exact_values(self):
        self.assertEqual(mcnemar_exact(0, 0), 1.0)
        self.assertAlmostEqual(mcnemar_exact(0, 6), 2 / 64)
        self.assertAlmostEqual(mcnemar_exact(3, 3), 1.0)
        self.assertAlmostEqual(mcnemar_exact(1, 5), 2 * 7 / 64)

    def test_compare_table_and_rejects_mismatched_tasks(self):
        a = {"t1": True, "t2": True, "t3": False, "t4": False}
        b = {"t1": True, "t2": False, "t3": False, "t4": True}
        result = compare(a, b, iterations=200)
        self.assertEqual(result["table"], {"both": 1, "only_a": 1, "only_b": 1, "neither": 1})
        self.assertEqual(result["diff_a_minus_b"], 0.0)
        with self.assertRaises(ValueError):
            compare(a, {"t1": True})

    def test_bootstrap_is_deterministic_and_bounded(self):
        a, b = [True] * 6 + [False] * 4, [True] * 2 + [False] * 8
        first = bootstrap_diff_ci(a, b, iterations=500)
        self.assertEqual(first, bootstrap_diff_ci(a, b, iterations=500))
        self.assertTrue(-1 <= first[0] <= 0.4 <= first[1] <= 1)

    def test_main_refuses_incomplete_evaluations(self):
        with tempfile.TemporaryDirectory() as temp:
            for name, complete in (("a", True), ("b", False)):
                d = Path(temp, name)
                d.mkdir()
                (d / "official_eval.json").write_text(json.dumps(
                    {"complete": complete, "tasks": {"t1": "resolved"}}))
            with self.assertRaises(ValueError):
                paired_compare.main([str(Path(temp, "a")), str(Path(temp, "b"))])
            self.assertEqual(paired_compare.main([str(Path(temp, "a")), str(Path(temp, "b")),
                                                  "--allow-incomplete", "--iterations", "50"]), 0)


if __name__ == "__main__":
    unittest.main()
