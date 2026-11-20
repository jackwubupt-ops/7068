"""Offline tests for the sample requests and their headless runner."""
import json
from pathlib import Path
import tempfile
import unittest

from patchloop_app.samples import build_request, load_samples, run_sample, to_markdown
from patchloop_app.session import SessionManager
from swebench_dev import DevelopmentTask
from tests.test_app_session import ScriptedBackend
from tests.test_edit_blocks import ORIGINAL, make_repo
from tests.test_single_agent import GOOD, READ

REQUIRED_KINDS = ("ordinary", "changed request", "failure")


class SampleFileTests(unittest.TestCase):
    def test_required_sample_kinds_exist_and_are_valid_requests(self):
        samples = load_samples()
        kinds = " ".join(s["kind"] for s in samples)
        for kind in REQUIRED_KINDS:
            self.assertIn(kind, kinds)
        task = DevelopmentTask("sqlfluff__sqlfluff-1625", "sqlfluff/sqlfluff", "a" * 40, "Real issue text")
        for s in samples:
            with self.subTest(sample=s["name"]):
                req = build_request(s["request"], "qwen", lambda iid: task)
                self.assertNotEqual(req.issue, "@task")
                self.assertEqual(req.backend, "qwen")
                self.assertTrue(s["expect"])
        self.assertEqual(build_request(samples[0]["request"], "deepseek", lambda iid: task).issue,
                         "Real issue text")


class RunnerTests(unittest.TestCase):
    def test_follow_up_sample_rejects_round_one_and_runs_round_two(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, _ = make_repo(root, {"pkg/mod.py": ORIGINAL})
            replies = [READ, GOOD, READ, GOOD]
            mgr = SessionManager(root / "runs", {"qwen": lambda: ScriptedBackend(replies)})
            sample = {"name": "x", "kind": "changed request", "description": "d", "expect": "e",
                      "request": {"source": "local", "repo_path": str(repo), "agent": "single",
                                  "issue": "Calling f(0) in pkg/mod.py returns 0 but it should return -1 for zero input."},
                      "follow_up": {"guidance": "Keep it minimal.", "agent": "single"}}
            views = run_sample(mgr, sample, "qwen", lambda iid: None)
            self.assertEqual([v["status"] for v in views], ["rejected", "awaiting_confirmation"])
            self.assertEqual(views[1]["parent"], views[0]["id"])
            md = to_markdown(sample, views)
            self.assertIn("round 2", md)
            self.assertIn("```diff", md)
            json.dumps(views)  # serializable for results/


if __name__ == "__main__":
    unittest.main()
