"""Offline tests for the repeated-runs report (synthetic batch directories, no model)."""
import json
from pathlib import Path
import tempfile
import unittest

from experiments import repeat_report
from tests.test_final_report import IDS, make_batch


def batch(root, tag, config, resolved, **kw):
    agent = "single" if config == "single" else "pcr"
    effort = config.split("-", 1)[1] if config.startswith("pcr-") else "none"
    return make_batch(root, f"{tag}-{config}", backend="deepseek", model="deepseek-flash", agent=agent,
                      resolved=set(resolved), applicable=set(IDS), reasoning_effort=effort, **kw)


class RepeatReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # run 1: pcr {1,2}, high {1}; run 2: pcr {1,3}, high {1,2}
        batch(self.root, "t1", "pcr", ["o__r-1", "o__r-2"])
        batch(self.root, "t1", "pcr-high", ["o__r-1"])
        batch(self.root, "t2", "pcr", ["o__r-1", "o__r-3"])
        batch(self.root, "t2", "pcr-high", ["o__r-1", "o__r-2"])
        batch(self.root, "t1", "single", ["o__r-1"])  # only in t1: skipped

    def tearDown(self):
        self.tmp.cleanup()

    def test_summary_and_task_level_pairing(self):
        prefix = self.root / "out" / "rep"
        self.assertEqual(repeat_report.main(["--runs-dir", str(self.root), "--tag", "t1", "--tag", "t2",
                                             "--out", str(prefix)]), 0)
        report = json.loads(Path(f"{prefix}.json").read_text(encoding="utf-8"))
        self.assertEqual(set(report["configs"]), {"ds-pcr", "ds-pcr-high"})
        pcr = report["configs"]["ds-pcr"]
        self.assertEqual((pcr["resolved_per_run"], pcr["resolved_mean"]), ([2, 2], 2.0))
        self.assertEqual(pcr["resolved_rate_mean"], 0.5)
        [c] = report["comparisons"]
        self.assertEqual((c["a"], c["b"]), ("ds-pcr-high", "ds-pcr"))
        # shares high: r1 1, r2 .5, r3 0 ; pcr: r1 1, r2 .5, r3 .5 -> one task pcr better
        self.assertEqual((c["tasks_a_better"], c["tasks_b_better"], c["tasks_tied"]), (0, 1, 3))
        self.assertEqual(c["diff_mean"], -0.125)
        self.assertEqual(c["pooled_discordant"], {"only_a": 1, "only_b": 2})
        self.assertEqual(c["warnings"], [])
        self.assertIn("Sign test p", Path(f"{prefix}.md").read_text(encoding="utf-8"))

    def test_needs_two_tags_and_matching_tasks(self):
        with self.assertRaises(SystemExit):
            repeat_report.main(["--runs-dir", str(self.root), "--tag", "t1", "--out", str(self.root / "x")])
        with self.assertRaisesRegex(ValueError, "no config"):
            repeat_report.load_runs(self.root, ["t1", "missing"])


if __name__ == "__main__":
    unittest.main()
