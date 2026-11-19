"""Offline tests for the SWE-bench Lite dev batch runner (no model, no network)."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from experiments.deepseek_swebench_dev import run_real_dev
from experiments.lite_batch import build_manifest, run_batch, select_tasks
from swebench_dev import LITE_DATASET_ID, DevelopmentTask, load_dev_tasks

SHA = "b" * 40


def make_task(n: int, repo: str = "owner/proj") -> DevelopmentTask:
    return DevelopmentTask(instance_id=f"owner__proj-{n}", repo=repo,
                           base_commit=SHA, problem_statement=f"issue {n}")


def fake_run_one(task, task_dir):
    task_dir.mkdir(parents=True)
    ready = task.instance_id.endswith("1")
    report = {"instance_id": task.instance_id, "repo": task.repo,
              "status": "prediction_ready" if ready else "no_candidate_files",
              "suspected_files": ["a.py"] if ready else [],
              "prompt_tokens": 10, "completion_tokens": 5, "duration_seconds": 1.5}
    if ready:
        (task_dir / "predictions.jsonl").write_text(json.dumps({
            "instance_id": task.instance_id, "model_name_or_path": "m",
            "model_patch": "diff --git a/a.py b/a.py\n"}) + "\n", encoding="utf-8")
    (task_dir / "run_status.json").write_text(json.dumps(report), encoding="utf-8")
    return report


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tasks = [make_task(n) for n in range(1, 6)]

    def test_limit_keeps_dataset_order(self):
        chosen = select_tasks(self.tasks, limit=2)
        self.assertEqual([t.instance_id for t in chosen], ["owner__proj-1", "owner__proj-2"])

    def test_explicit_ids_keep_given_order_and_reject_unknown(self):
        chosen = select_tasks(self.tasks, instance_ids=["owner__proj-3", "owner__proj-1"])
        self.assertEqual([t.instance_id for t in chosen], ["owner__proj-3", "owner__proj-1"])
        with self.assertRaises(ValueError):
            select_tasks(self.tasks, instance_ids=["owner__proj-99"])

    def test_loader_only_reads_dev_split_and_strips_gold_fields(self):
        seen = {}

        def loader(dataset_id, split):
            seen.update(dataset=dataset_id, split=split)
            return [{"instance_id": "owner__proj-1", "repo": "owner/proj", "base_commit": SHA,
                     "problem_statement": "x", "patch": "GOLD", "test_patch": "GOLD"}]

        tasks = load_dev_tasks(LITE_DATASET_ID, loader=loader)
        self.assertEqual(seen, {"dataset": LITE_DATASET_ID, "split": "dev"})
        self.assertFalse(hasattr(tasks[0], "patch"))
        with self.assertRaises(ValueError):
            load_dev_tasks("someone/else", loader=loader)


class BatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name) / "batch"
        self.tasks = [make_task(1), make_task(2), make_task(11)]
        self.manifest = build_manifest(self.tasks, dataset_id=LITE_DATASET_ID, settings={"model": "m"})

    def run_it(self, run_one=fake_run_one, **kwargs):
        return run_batch(self.tasks, self.out, run_one=run_one, manifest=self.manifest,
                         log=lambda _: None, **kwargs)

    def test_outputs_manifest_results_predictions_and_summary(self):
        summary = self.run_it()
        manifest = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(manifest["instance_ids"], [t.instance_id for t in self.tasks])
        self.assertEqual(manifest["split"], "dev")
        lines = (self.out / "results.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 3)
        preds = [json.loads(x) for x in (self.out / "all_preds.jsonl").read_text().splitlines()]
        self.assertEqual({p["instance_id"] for p in preds}, {"owner__proj-1", "owner__proj-11"})
        self.assertEqual(summary["prediction_ready"], 2)
        self.assertEqual(summary["status_counts"], {"no_candidate_files": 1, "prediction_ready": 2})
        self.assertEqual(summary["localized_any_file"], 2)
        self.assertEqual(summary["prompt_tokens"], 30)
        self.assertFalse(summary["official_evaluated"])

    def test_refuses_non_empty_out_without_resume(self):
        self.run_it()
        with self.assertRaises(ValueError):
            self.run_it()

    def test_resume_skips_finished_and_retries_interrupted(self):
        calls = []

        def crash_on_second(task, task_dir):
            if task.instance_id == "owner__proj-2":
                task_dir.mkdir(parents=True)
                raise KeyboardInterrupt
            calls.append(task.instance_id)
            return fake_run_one(task, task_dir)

        with self.assertRaises(KeyboardInterrupt):
            self.run_it(run_one=crash_on_second)
        calls.clear()

        def record(task, task_dir):
            calls.append(task.instance_id)
            return fake_run_one(task, task_dir)

        summary = self.run_it(run_one=record, resume=True)
        self.assertEqual(calls, ["owner__proj-2", "owner__proj-11"])
        self.assertEqual(summary["tasks_finished"], 3)
        self.assertTrue(any(p.name.startswith("owner__proj-2.interrupted-") for p in self.out.iterdir()))

    def test_resume_rejects_different_task_list(self):
        self.run_it()
        other = build_manifest(self.tasks[:1], dataset_id=LITE_DATASET_ID, settings={})
        with self.assertRaises(ValueError):
            run_batch(self.tasks[:1], self.out, run_one=fake_run_one, manifest=other,
                      resume=True, log=lambda _: None)

    def test_task_exception_is_recorded_and_batch_continues(self):
        def flaky(task, task_dir):
            if task.instance_id == "owner__proj-1":
                raise RuntimeError("boom")
            return fake_run_one(task, task_dir)

        summary = self.run_it(run_one=flaky)
        self.assertEqual(summary["status_counts"].get("batch_error"), 1)
        self.assertEqual(summary["tasks_finished"], 3)


class ParallelBatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name) / "batch"
        self.tasks = [make_task(n) for n in (1, 2, 3, 11)]
        self.manifest = build_manifest(self.tasks, dataset_id=LITE_DATASET_ID, settings={})

    def run_it(self, run_one=fake_run_one, **kwargs):
        return run_batch(self.tasks, self.out, run_one=run_one, manifest=self.manifest,
                         log=lambda _: None, **kwargs)

    def test_tasks_really_overlap_and_summary_matches_sequential(self):
        barrier = threading.Barrier(4, timeout=10)

        def overlapping(task, task_dir):
            barrier.wait()  # only passes if all 4 tasks are in flight at once
            return fake_run_one(task, task_dir)

        summary = self.run_it(run_one=overlapping, workers=4)
        self.assertEqual(summary["tasks_finished"], 4)
        self.assertEqual(summary["status_counts"], {"no_candidate_files": 2, "prediction_ready": 2})
        lines = [json.loads(x) for x in (self.out / "results.jsonl").read_text().splitlines()]
        self.assertEqual(sorted(x["instance_id"] for x in lines),
                         sorted(t.instance_id for t in self.tasks))
        preds = (self.out / "all_preds.jsonl").read_text().splitlines()
        self.assertEqual(len(preds), 2)

    def test_worker_exception_is_recorded_without_stopping_others(self):
        def flaky(task, task_dir):
            if task.instance_id == "owner__proj-2":
                raise RuntimeError("boom")
            return fake_run_one(task, task_dir)

        summary = self.run_it(run_one=flaky, workers=3)
        self.assertEqual(summary["status_counts"].get("batch_error"), 1)
        self.assertEqual(summary["tasks_finished"], 4)

    def test_interrupt_in_worker_propagates_and_resume_finishes(self):
        def interrupt(task, task_dir):
            if task.instance_id == "owner__proj-3":
                task_dir.mkdir(parents=True)
                raise KeyboardInterrupt
            return fake_run_one(task, task_dir)

        with self.assertRaises(KeyboardInterrupt):
            self.run_it(run_one=interrupt, workers=2)
        summary = self.run_it(resume=True, workers=2)
        self.assertEqual(summary["tasks_finished"], 4)
        lines = [json.loads(x) for x in (self.out / "results.jsonl").read_text().splitlines()]
        self.assertEqual(len({x["instance_id"] for x in lines}), len(lines))  # no duplicates

    def test_rejects_bad_worker_counts(self):
        for bad in (0, 17, "4"):
            with self.assertRaises(ValueError):
                self.run_it(workers=bad)


class GeneralizedDevRunTests(unittest.TestCase):
    """run_real_dev accepts any dev instance when the batch passes its fields."""

    def test_other_instance_runs_and_reports_its_own_fields(self):
        task = make_task(7, repo="pvlib/pvlib-python")

        class Api:
            model = "m"
            calls = []

            def complete(self, stage, messages):
                self.calls.append({"stage": stage})
                return "OK"

            def callback(self, stage):
                return lambda m: self.complete(stage, m)

        with tempfile.TemporaryDirectory() as temp, \
             patch("experiments.deepseek_swebench_dev.run_localization",
                   return_value={"suspected_files": []}), \
             patch("experiments.deepseek_swebench_dev._clean_source", return_value=True):
            report = run_real_dev(
                Path(temp) / "o", api=Api(), instance_id=task.instance_id,
                expected_repo=task.repo, expected_base=task.base_commit,
                dataset_id=LITE_DATASET_ID,
                task_loader=lambda instance_id: task, checkout_fn=lambda t, p: p,
            )
        self.assertEqual(report["status"], "no_candidate_files")
        self.assertEqual(report["instance_id"], task.instance_id)
        self.assertEqual(report["repo"], "pvlib/pvlib-python")
        self.assertEqual(report["dataset"], LITE_DATASET_ID)

    def test_wrong_instance_from_loader_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            report = run_real_dev(
                Path(temp) / "o", api=type("A", (), {"model": "m", "calls": []})(),
                instance_id="owner__proj-1", expected_repo=None, expected_base=None,
                task_loader=lambda instance_id: make_task(2),
            )
        self.assertEqual(report["status"], "experiment_error")
        self.assertEqual(report["failed_stage"], "load_official_dev_task")


if __name__ == "__main__":
    unittest.main()
