"""Offline tests for issue -> file retrieval and how both agents receive it."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.retrieval_recall import gold_rank, recall_table
from patchloop_task2.single_agent import run_single_agent
from tests.test_edit_blocks import make_repo
from utils.retrieval import candidate_message_fields, is_test_path, rank_files, tokens

FILES = {
    "src/pkg/parser.py": "class Parser:\n    def parse_value(self, text):\n        return int(text)\n",
    "src/pkg/render.py": "def render_table(rows):\n    return '\\n'.join(rows)\n",
    "src/pkg/util/strings.py": "def strip_all(x):\n    return x.strip()\n",
    "tests/test_parser.py": "from pkg.parser import Parser\n\ndef test_parse_value():\n    Parser().parse_value('1')\n",
    "README.md": "parse_value parse_value parse_value\n",
}


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo, self.sha = make_repo(Path(temp.name), FILES)

    def paths(self, issue, k=5):
        return [c["file_path"] for c in rank_files(self.repo, issue, k)]

    def test_tokens_split_identifiers(self):
        self.assertIn("parse", tokens("parse_value"))
        self.assertIn("table", tokens("renderTable"))
        self.assertNotIn("the", tokens("the"))

    def test_defined_name_ranks_source_above_its_test(self):
        ranked = self.paths("Parser.parse_value crashes on '1.5'")
        self.assertEqual(ranked[0], "src/pkg/parser.py")
        self.assertLess(ranked.index("src/pkg/parser.py"), ranked.index("tests/test_parser.py"))
        self.assertNotIn("README.md", ranked)  # only tracked .py files

    def test_path_traceback_and_module_mentions(self):
        self.assertEqual(self.paths('File "/usr/lib/site-packages/pkg/util/strings.py", line 2')[0],
                         "src/pkg/util/strings.py")
        self.assertEqual(self.paths("Calling pkg.render on rows gives junk")[0], "src/pkg/render.py")
        top = rank_files(self.repo, "see src/pkg/render.py", 1)[0]
        self.assertIn("path named in issue", top["why"])

    def test_validation_and_test_paths(self):
        with self.assertRaises(ValueError):
            rank_files(self.repo, "  ")
        with self.assertRaises(ValueError):
            rank_files(self.repo, "x", 0)
        self.assertTrue(is_test_path("tests/a.py"))
        self.assertTrue(is_test_path("pkg/test_a.py"))
        self.assertFalse(is_test_path("pkg/contest.py"))

    def test_candidate_fields_carry_no_scores(self):
        fields = candidate_message_fields([{"file_path": "a.py", "score": 3.1, "why": ["keyword match"]}])
        self.assertEqual(fields["candidate_files"], [{"file_path": "a.py", "why": ["keyword match"]}])
        self.assertIn("unverified", fields["candidate_files_note"])


class AgentWiringTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo, self.sha = make_repo(Path(temp.name), FILES)

    def test_single_agent_first_message_has_candidates_only_when_given(self):
        seen = []
        def model(messages):
            seen.append(json.loads(messages[1]["content"]))
            raise RuntimeError("QWEN_CALL_BUDGET_EXHAUSTED")
        cands = [{"file_path": "src/pkg/parser.py", "score": 1.0, "why": ["defines Parser"]}]
        run_single_agent("Parser bug", self.repo, self.sha, completion=model, candidate_files=cands)
        run_single_agent("Parser bug", self.repo, self.sha, completion=model)
        self.assertEqual(seen[0]["candidate_files"][0]["file_path"], "src/pkg/parser.py")
        self.assertNotIn("candidate_files", seen[1])

    def test_planner_first_message_has_the_same_fields(self):
        from prompt_agent import plan_repair
        seen = []
        def model(messages):
            seen.append(json.loads(messages[1]["content"]))
            return "not json"
        cands = [{"file_path": "src/pkg/parser.py", "score": 1.0, "why": ["defines Parser"]}]
        with self.assertRaises(ValueError):
            plan_repair("Parser bug", self.repo, self.sha, completion=model, max_steps=1,
                        candidate_files=cands)
        expected = candidate_message_fields(cands)
        self.assertEqual({k: seen[0][k] for k in expected}, expected)

    def test_runner_ranks_files_only_when_retrieval_k_is_set(self):
        from experiments.deepseek_swebench_dev import run_real_dev
        from swebench_dev import DevelopmentTask
        from tests.test_deepseek_swebench_dev import FakeDeepSeek
        task = DevelopmentTask("o__r-1", "o/r", self.sha, "Parser.parse_value is wrong")
        seen = {}
        def fake_plan(issue, repo, base, **kwargs):
            seen["kwargs"] = kwargs
            return {"suspected_files": []}
        with tempfile.TemporaryDirectory() as out, \
             patch("experiments.deepseek_swebench_dev.run_localization", side_effect=fake_plan), \
             patch("experiments.deepseek_swebench_dev._clean_source", return_value=True):
            report = run_real_dev(Path(out) / "a", api=FakeDeepSeek(), instance_id="o__r-1",
                                  expected_repo="o/r", expected_base=self.sha,
                                  task_loader=lambda **kw: task, checkout_fn=lambda t, p: self.repo,
                                  retrieval_k=3)
            self.assertEqual(report["retrieval_candidates"][0], "src/pkg/parser.py")
            self.assertEqual(seen["kwargs"]["candidate_files"][0]["file_path"], "src/pkg/parser.py")
            report = run_real_dev(Path(out) / "b", api=FakeDeepSeek(), instance_id="o__r-1",
                                  expected_repo="o/r", expected_base=self.sha,
                                  task_loader=lambda **kw: task, checkout_fn=lambda t, p: self.repo)
            self.assertNotIn("retrieval_candidates", report)
            self.assertNotIn("candidate_files", seen["kwargs"])


class RecallTests(unittest.TestCase):
    def test_gold_rank_and_recall(self):
        ranked = [{"file_path": p} for p in ("a.py", "b.py", "c.py")]
        self.assertEqual(gold_rank(ranked, {"c.py", "z.py"}), 3)
        self.assertIsNone(gold_rank(ranked, {"z.py"}))
        table = recall_table([1, 3, None, 12])
        self.assertEqual(table["recall@1"], 0.25)
        self.assertEqual(table["recall@5"], 0.5)
        self.assertEqual(table["recall@20"], 0.75)


if __name__ == "__main__":
    unittest.main()
