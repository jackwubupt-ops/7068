"""Offline tests for the model backends (fake OpenAI client, no network)."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from patchloop_app.session import Request, SessionManager
from patchloop_task2.backends import DeepSeekBackend, DeepSeekSettings, make_backend
from patchloop_task2.qwen_small import QwenSettings, QwenSmallBackend


class FakeClient:
    def __init__(self, text="READY"):
        self.requests = []
        self.text = text
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.text), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2))


class DeepSeekTests(unittest.TestCase):
    def settings(self, **kw):
        return DeepSeekSettings(**{"api_key": "sk-test-not-real", **kw})

    def test_settings_validation(self):
        with self.assertRaisesRegex(ValueError, "MISSING_DEEPSEEK_API_KEY"):
            DeepSeekSettings(api_key="")
        with self.assertRaises(ValueError):
            self.settings(model="gpt-4o")
        with self.assertRaises(ValueError):
            self.settings(endpoint="http://api.deepseek.com")
        self.assertEqual(self.settings().model, "deepseek-flash")

    def test_requests_disable_thinking_and_keep_shared_budgets(self):
        client = FakeClient()
        backend = DeepSeekBackend(self.settings(), client=client)
        self.assertEqual(backend.verify()["status"], "live_deepseek_api_ok")
        sent = client.requests[0]
        self.assertEqual(sent["model"], "deepseek-flash")
        self.assertEqual(sent["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(sent["temperature"], 0)
        self.assertEqual(sent["max_tokens"], 32)  # same preflight cap as Qwen
        backend.complete("agent", [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])
        self.assertEqual(client.requests[1]["max_tokens"], 3500)  # same agent cap as Qwen
        self.assertEqual(backend.provider, "deepseek")

    def test_qwen_requests_have_no_extra_body(self):
        client = FakeClient()
        QwenSmallBackend(QwenSettings(model="Qwen/Qwen2.5-Coder-7B-Instruct"), client=client).complete(
            "preflight", [{"role": "user", "content": "x"}])
        self.assertNotIn("extra_body", client.requests[0])

    def test_from_env_and_factory(self):
        env = {"DEEPSEEK_API_KEY": "sk-test-not-real", "DEEPSEEK_MODEL": "deepseek-v4-pro",
               "QWEN_CONTEXT_CHARS": "40000"}
        with patch.dict("os.environ", env, clear=False), \
             patch("patchloop_task2.backends._load_dotenv"):
            settings = DeepSeekSettings.from_env()
            self.assertEqual((settings.model, settings.context_chars), ("deepseek-v4-pro", 40000))
            with patch("openai.OpenAI"):
                self.assertIsInstance(make_backend("deepseek", settings), DeepSeekBackend)
        with self.assertRaises(ValueError):
            make_backend("gemini")

    def test_prediction_label_for_any_model(self):
        from experiments import qwen_small_dev
        backend = SimpleNamespace(model="deepseek-flash")
        with tempfile.TemporaryDirectory() as out, \
             patch.object(qwen_small_dev, "run_real_dev", return_value={"status": "no_candidate_files"}):
            result = qwen_small_dev.run_qwen_dev(backend, Path(out), agent="pcr")
        self.assertEqual(result["prediction_model_label"], "deepseek-flash")


class SessionBackendChoiceTests(unittest.TestCase):
    def test_unknown_backend_is_rejected_by_the_session_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(tmp, {"qwen": lambda: None})
            with self.assertRaisesRegex(ValueError, "not available"):
                mgr.start(Request(issue="x" * 50, source="local", repo_path=tmp, backend="deepseek"),
                          run_async=False)


if __name__ == "__main__":
    unittest.main()
