"""Offline tests for the post-hoc (gold-scored) diagnosis script."""
import json
from pathlib import Path
import tempfile
import unittest

from experiments.diagnose_patches import (
    diagnose_batch, diagnose_task, hunks_overlap, patch_hunks, render_markdown, summarize,
)

GOLD = ("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
        "@@ -40,6 +40,7 @@ def f():\n x\n+y\n")
NEAR = ("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
        "@@ -43,3 +43,3 @@\n-a\n+b\n")
FAR = NEAR.replace("@@ -43,3 +43,3 @@", "@@ -300,3 +300,3 @@")
OTHER = NEAR.replace("src/a.py", "src/b.py")


class HunkTests(unittest.TestCase):
    def test_patch_hunks_and_overlap(self):
        self.assertEqual(patch_hunks(GOLD), {"src/a.py": [(40, 45)]})
        self.assertEqual(patch_hunks("diff --git a/x b/x\n@@ -7 +7 @@\n-a\n+b\n"), {"x": [(7, 7)]})
        self.assertTrue(hunks_overlap(patch_hunks(NEAR), patch_hunks(GOLD)))
        self.assertFalse(hunks_overlap(patch_hunks(FAR), patch_hunks(GOLD)))
        self.assertFalse(hunks_overlap(patch_hunks(OTHER), patch_hunks(GOLD)))


class CategoryTests(unittest.TestCase):
    def status(self, **kw):
        base = {"instance_id": "o__r-1", "agent": "pcr", "status": "patch_failed",
                "planner_action_trace": [{"action": "read_file", "read_path": "src/a.py"}],
                "suspected_files": ["src/a.py"]}
        base.update(kw)
        return base

    def test_categories(self):
        cases = [
            (self.status(), NEAR, "resolved", "resolved"),
            (self.status(planner_action_trace=[], suspected_files=[]), "", None, "never_read_gold_file"),
            (self.status(suspected_files=["src/b.py"]), "", None, "read_gold_not_selected"),
            (self.status(), "", None, "no_applicable_patch"),
            (self.status(), OTHER, "unresolved", "read_gold_not_selected"),
            (self.status(), FAR, "unresolved", "wrong_location"),
            (self.status(), NEAR, "unresolved", "right_location_wrong_fix"),
        ]
        for status, pred, verdict, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(diagnose_task(status, pred, GOLD, verdict)["category"], expected)

    def test_single_agent_reads_come_from_its_trace(self):
        status = {"instance_id": "o__r-1", "agent": "single", "status": "no_submission",
                  "agent_action_trace": [{"action": "read_file", "read_path": "src/a.py"}]}
        row = diagnose_task(status, "", GOLD, "no_prediction")
        self.assertTrue(row["read_gold"])
        self.assertEqual(row["category"], "no_applicable_patch")


class BatchTests(unittest.TestCase):
    def test_batch_summary_and_markdown(self):
        with tempfile.TemporaryDirectory() as temp:
            batch = Path(temp) / "run"
            (batch / "o__r-1").mkdir(parents=True)
            (batch / "o__r-2").mkdir()
            (batch / "manifest.json").write_text(json.dumps(
                {"instance_ids": ["o__r-1", "o__r-2"], "agent": "pcr", "dataset": "d", "split": "dev"}))
            (batch / "official_eval.json").write_text(json.dumps(
                {"tasks": {"o__r-1": "unresolved", "o__r-2": "no_prediction"}}))
            (batch / "o__r-1" / "run_status.json").write_text(json.dumps({
                "status": "prediction_ready", "suspected_files": ["src/a.py"],
                "planner_action_trace": [{"read_path": "src/a.py"}]}))
            (batch / "o__r-1" / "predictions.jsonl").write_text(json.dumps({"model_patch": NEAR}) + "\n")
            (batch / "o__r-2" / "run_status.json").write_text(json.dumps({
                "status": "no_candidate_files", "planner_action_trace": []}))
            gold = {"o__r-1": GOLD, "o__r-2": GOLD}
            _, rows = diagnose_batch(batch, gold)
            summary = summarize(rows)
            self.assertEqual(summary["categories"]["right_location_wrong_fix"], 1)
            self.assertEqual(summary["categories"]["never_read_gold_file"], 1)
            self.assertEqual(summary["read_gold_rate"], 0.5)
            md = render_markdown([("run", summary, rows)], gold)
            self.assertIn("Gold patch:", md)
            self.assertIn("o__r-1", md)
            with self.assertRaises(ValueError):
                diagnose_batch(batch, {"o__r-1": GOLD})


class LeakageGuardTests(unittest.TestCase):
    def test_no_inference_module_imports_the_gold_scoring_script(self):
        root = Path(__file__).resolve().parents[1]
        offenders = []
        for path in root.rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            if rel.startswith(("tests/", ".venv")) or "/." in rel or rel == "experiments/diagnose_patches.py":
                continue
            if "diagnose_patches" in path.read_text(encoding="utf-8", errors="replace"):
                offenders.append(rel)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
