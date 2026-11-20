"""Offline-only contract tests for small-Qwen backend and evaluation override."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from patchloop_task2.qwen_small import (
    DEFAULT_MODEL, QwenSettings, QwenSmallBackend,
    trim_planner_history, clean_json_fence,
)
from experiments.swebench_eval_compat import replace_legacy_stub
from experiments.qwen_small_dev import run_qwen_dev


class FakeClient:
    def __init__(self, responses=None, model=DEFAULT_MODEL):
        self.responses = iter(responses or ["READY"])
        self.requested = []
        self.models = SimpleNamespace(
            list=lambda: SimpleNamespace(data=[SimpleNamespace(id=model)])
        )
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create)
        )

    def create(self, **kwargs):
        self.requested.append(kwargs)
        value = next(self.responses)
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=value), finish_reason="stop"
            )],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4),
        )


class SettingsTests(unittest.TestCase):
    def test_small_qwen_defaults(self):
        config = QwenSettings()
        self.assertEqual(config.model, "Qwen/Qwen2.5-Coder-0.5B-Instruct")
        self.assertTrue(config.endpoint.endswith("/v1"))

    def test_model_and_endpoint_restrictions(self):
        QwenSettings(model="Qwen/Qwen3-0.6B")
        QwenSettings(model="Qwen/Qwen2.5-Coder-7B-Instruct")
        with self.assertRaises(ValueError):
            QwenSettings(model="Qwen/Qwen2.5-Coder-32B-Instruct")
        with self.assertRaises(ValueError):
            QwenSettings(endpoint="http://gpu.example:8000/v1")
        with self.assertRaises(ValueError):
            QwenSettings(endpoint="https://gpu.example/v1?api_key=unsafe")
        with self.assertRaises(ValueError):
            QwenSettings(api_key="")

    def test_environment_reads_only_qwen_settings(self):
        mapping = {
            "QWEN_MODEL": DEFAULT_MODEL,
            "QWEN_BASE_URL": "http://localhost:8000/v1",
            "QWEN_API_KEY": "EMPTY",
        }
        with patch.dict("os.environ", mapping, clear=True):
            got = QwenSettings.from_env()
        self.assertEqual(got.model, DEFAULT_MODEL)
        self.assertEqual(got.api_key, "EMPTY")

    def test_planner_history_never_truncates_a_message(self):
        system = {"role": "system", "content": "system"}
        issue = {"role": "user", "content": "issue"}
        msgs = [system, issue] + [
            {"role": "user", "content": "A" * 2000},
            {"role": "assistant", "content": "next"},
            {"role": "user", "content": "latest evidence"},
        ]
        result, dropped = trim_planner_history(msgs, 100)
        self.assertEqual(dropped, 1)
        self.assertEqual(result[0], system)
        self.assertEqual(result[1], issue)
        self.assertEqual(result[-1]["content"], "latest evidence")
        self.assertEqual(len(msgs), 5)

    def test_outer_json_fence_only(self):
        fence = chr(96) * 3
        self.assertEqual(
            clean_json_fence(fence + 'json\n{"action":"final"}\n' + fence),
            '{"action":"final"}',
        )
        self.assertEqual(clean_json_fence("plain"), "plain")

    def test_live_preflight_contract_with_scripted_http_client(self):
        fence = chr(96) * 3
        client = FakeClient(["READY", fence + 'json\n{"action":"final"}\n' + fence])
        backend = QwenSmallBackend(QwenSettings(), client=client)
        response = backend.verify()
        self.assertEqual(response["status"], "live_qwen_api_ok")
        value = backend.complete("planner", [
            {"role": "system", "content": "do JSON"},
            {"role": "user", "content": "issue"},
        ])
        self.assertEqual(json.loads(value), {"action": "final"})
        self.assertEqual(client.requested[0]["model"], DEFAULT_MODEL)
        self.assertEqual(client.requested[0]["temperature"], 0)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(backend.calls[0]["completion_tokens"], 4)
        self.assertNotIn("api_key", str(backend.calls))

    def test_preflight_fails_on_wrong_model_id(self):
        client = FakeClient(model="some-other-model")
        with self.assertRaisesRegex(RuntimeError, "QWEN_MODEL_ID_MISMATCH"):
            QwenSmallBackend(QwenSettings(), client=client).verify()

    def test_swebench_compat_patch_does_not_change_other_packages(self):
        reqs = (
            "types-pkg_resources\n"
            "types-pkg_resources # old stubs\n"
            "types-pkg_resources-extra\n"
            "pytest\n"
        )
        updated, n = replace_legacy_stub(reqs)
        self.assertEqual(n, 2)
        self.assertEqual(updated.splitlines()[0], "types-setuptools")
        self.assertIn("types-pkg_resources-extra", updated)
        self.assertEqual(updated.splitlines()[-1], "pytest")

    def test_dev_wrapper_never_claims_official_resolution(self):
        fake_backend = SimpleNamespace(model=DEFAULT_MODEL)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prediction"
            path.mkdir()
            def fake_prediction(output, *, api):
                (output / "predictions.jsonl").write_text(json.dumps({
                    "instance_id": "sqlfluff__sqlfluff-4764",
                    "model_name_or_path": DEFAULT_MODEL,
                    "model_patch": "diff --git a/a.py b/a.py\n",
                }), encoding="utf-8")
                return {"status": "prediction_ready", "official_evaluated": True,
                        "official_resolved": True}
            with patch(
                "experiments.qwen_small_dev.run_real_dev",
                side_effect=fake_prediction,
            ) as run:
                report = run_qwen_dev(fake_backend, path)
            run.assert_called_once()
            self.assertFalse(report["official_evaluated"])
            self.assertIsNone(report["official_resolved"])
            prediction = json.loads((path / "predictions.jsonl").read_text())
            self.assertEqual(prediction["model_name_or_path"], "qwen2.5-coder-0.5b-instruct")
            self.assertEqual(
                json.loads((path / "run_status.json").read_text())["experiment"],
                "qwen-small-real-swebench-full-dev-v1",
            )


    def test_official_report_distinguishes_build_error_from_unresolved(self):
        from experiments.swebench_report import classify_official_report
        issue = "sqlfluff__sqlfluff-4764"
        error = classify_official_report({
            "submitted_instances": 1, "completed_instances": 0,
            "error_instances": 1, "error_ids": [issue],
        }, issue)
        self.assertEqual(error["status"], "infrastructure_error")
        self.assertIsNone(error["official_resolved"])
        good = classify_official_report({
            "submitted_instances": 1, "completed_instances": 1,
            "resolved_instances": 1, "error_instances": 0,
            "resolved_ids": [issue],
        }, issue)
        self.assertEqual(good["status"], "resolved")
        bad = classify_official_report({
            "submitted_instances": 1, "completed_instances": 1,
            "unresolved_instances": 1, "error_instances": 0,
            "unresolved_ids": [issue],
        }, issue)
        self.assertEqual(bad["status"], "unresolved")
        self.assertFalse(bad["official_resolved"])


    def test_original_demo_shared_client_can_be_switched_to_local_qwen(self):
        import os
        import subprocess
        import sys
        env = dict(os.environ)
        env.update({
            "PATCHLOOP_MODEL_BACKEND": "qwen",
            "QWEN_MODEL": DEFAULT_MODEL,
            "QWEN_BASE_URL": "http://127.0.0.1:8000/v1",
            "QWEN_API_KEY": "EMPTY",
        })
        script = (
            "import json,config;"
            "print(json.dumps({'model':config.OPENAI_MODEL,"
            "'url':str(config.get_client().base_url)}))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script], env=env,
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        info = json.loads(completed.stdout)
        self.assertEqual(info["model"], DEFAULT_MODEL)
        self.assertIn("127.0.0.1:8000/v1", info["url"])


if __name__ == "__main__":
    unittest.main()
