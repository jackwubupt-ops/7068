"""Offline tests for the final comparison report (synthetic batch directories, no model)."""
import json
from pathlib import Path
import tempfile
import unittest

from experiments import final_report
from experiments.qwen_small_dev import run_qwen_dev

IDS = ["o__r-1", "o__r-2", "o__r-3", "o__r-4"]
SETTINGS = {"edit_format": "search_replace", "retrieval_k": 10, "max_calls_per_task": 20,
            "context_chars": 48000, "stage_max_tokens": {"coder": 3500}, "max_candidates": 2,
            "temperature": 0, "dataset": "princeton-nlp/SWE-bench_Lite", "split": "dev"}


def make_batch(root: Path, name: str, *, backend: str, model: str, agent: str,
               resolved: set[str], applicable: set[str], complete: bool = True, **overrides) -> Path:
    d = root / name
    d.mkdir()
    manifest = {"instance_ids": IDS, "backend": backend, "model": model, "agent": agent,
                **SETTINGS, **overrides}
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    lines = [{"instance_id": i, "status": "prediction_ready" if i in applicable else "patch_failed",
              "prompt_tokens": 100, "completion_tokens": 10, "duration_seconds": 2.0} for i in IDS]
    (d / "results.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    tasks = {i: "resolved" if i in resolved else ("unresolved" if i in applicable else "no_prediction")
             for i in IDS}
    (d / "official_eval.json").write_text(json.dumps(
        {"complete": complete, "run_id": name, "tasks": tasks}), encoding="utf-8")
    return d


class FinalReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dirs = {
            "ds-pcr": make_batch(self.root, "ds-pcr", backend="deepseek", model="deepseek-flash",
                                 agent="pcr", resolved={"o__r-1", "o__r-2"}, applicable=set(IDS)),
            "ds-single": make_batch(self.root, "ds-single", backend="deepseek", model="deepseek-flash",
                                    agent="single", resolved={"o__r-1"}, applicable={"o__r-1", "o__r-3"}),
            "qwen-pcr": make_batch(self.root, "qwen-pcr", backend="qwen",
                                   model="Qwen/Qwen2.5-Coder-7B-Instruct", agent="pcr",
                                   resolved=set(), applicable={"o__r-2"}),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_pairs_and_outputs(self):
        prefix = self.root / "out" / "final.v1"
        args = [f"--batch={k}={v}" for k, v in self.dirs.items()] + ["--out", str(prefix)]
        self.assertEqual(final_report.main(args), 0)
        report = json.loads(Path(f"{prefix}.json").read_text(encoding="utf-8"))
        titles = [(c["a"], c["b"]) for c in report["comparisons"]]
        self.assertEqual(titles, [("ds-pcr", "ds-single"), ("ds-pcr", "qwen-pcr")])
        rq3 = report["comparisons"][0]
        self.assertEqual(rq3["table"], {"both": 1, "only_a": 1, "only_b": 0, "neither": 2})
        self.assertEqual(rq3["warnings"], [])
        ds = report["batches"]["ds-pcr"]
        self.assertEqual((ds["tasks"], ds["applicable"], ds["resolved"]), (4, 4, 2))
        self.assertEqual(ds["prompt_tokens"], 400)
        self.assertNotIn("verdicts", ds)
        md = Path(f"{prefix}.md").read_text(encoding="utf-8")
        self.assertIn("| ds-pcr | deepseek | deepseek-flash | pcr | none | 4 | 4 | 2 | 50.0% |", md)

    def test_mismatched_settings_are_flagged(self):
        make_batch(self.root, "qwen-single", backend="qwen", model="Qwen/Qwen2.5-Coder-7B-Instruct",
                   agent="single", resolved=set(), applicable=set(), retrieval_k=0)
        b = {k: final_report.load_batch(k, self.root / k) for k in ("ds-single", "qwen-single")}
        self.assertEqual(final_report.comparability(b["ds-single"], b["qwen-single"]),
                         ["retrieval_k: 10 vs 0"])

    def test_confounded_pair_is_flagged(self):
        a = final_report.load_batch("ds-single", self.dirs["ds-single"])
        b = final_report.load_batch("qwen-pcr", self.dirs["qwen-pcr"])
        self.assertIn("model and agent all differ: the pair confounds several variables",
                      final_report.comparability(a, b))

    def test_reasoning_effort_pair_is_rq1_and_not_flagged(self):
        make_batch(self.root, "ds-pcr-high", backend="deepseek", model="deepseek-flash", agent="pcr",
                   resolved={"o__r-1", "o__r-2", "o__r-3"}, applicable=set(IDS), reasoning_effort="high")
        batches = {k: final_report.load_batch(k, self.root / k) for k in ("ds-pcr", "ds-pcr-high")}
        pairs = [p for p in final_report.DEFAULT_PAIRS if p[0] in batches and p[1] in batches]
        self.assertEqual([(p[0], p[1]) for p in pairs], [("ds-pcr-high", "ds-pcr")])
        report = final_report.build_report(batches, pairs, iterations=200)
        self.assertEqual(report["comparisons"][0]["warnings"], [])
        self.assertEqual(report["comparisons"][0]["table"]["only_a"], 1)
        self.assertEqual(report["batches"]["ds-pcr"]["reasoning_effort"], "none")

    def test_tasks_file_restricts_counts(self):
        batch = final_report.load_batch("ds-pcr", self.dirs["ds-pcr"], tasks={"o__r-2", "o__r-3"})
        self.assertEqual((batch["tasks"], batch["resolved"], batch["applicable"]), (2, 1, 2))
        with self.assertRaisesRegex(ValueError, "did not run"):
            final_report.load_batch("ds-pcr", self.dirs["ds-pcr"], tasks={"o__r-9"})

    def test_incomplete_evaluation_refused_by_default(self):
        d = make_batch(self.root, "bad", backend="deepseek", model="deepseek-flash", agent="pcr",
                       resolved=set(), applicable=set(), complete=False)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            final_report.load_batch("bad", d)
        self.assertFalse(final_report.load_batch("bad", d, allow_incomplete=True)["eval_complete"])


class ProviderLabelTests(unittest.TestCase):
    def test_deepseek_run_is_not_labelled_qwen(self):
        class FakeBackend:
            model, provider = "deepseek-flash", "deepseek"

        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp, \
                patch("experiments.qwen_small_dev.run_real_dev",
                      return_value={"status": "patch_failed"}):
            result = run_qwen_dev(FakeBackend(), Path(tmp), agent="pcr")
        self.assertEqual(result["experiment"], "deepseek-real-swebench-full-dev-v1")
        self.assertEqual(result["prediction_model_label"], "deepseek-flash")


if __name__ == "__main__":
    unittest.main()
