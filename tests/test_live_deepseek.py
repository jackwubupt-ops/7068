"""Offline tests for the real DeepSeek experiment harness (no paid API calls)."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import unittest

from experiments.live_deepseek import (
    ISSUE, LiveDeepSeek, create_real_git_fixture, run_live_experiment,
)


class FakeResponses:
    def __init__(self):
        self.request_count = 0
        self.requests = []

    def create(self, **kwargs):
        self.request_count += 1
        self.requests.append(kwargs)
        return SimpleNamespace(
            id=f"mock-response-{self.request_count}",
            model="deepseek-flash",
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="API_OK"),
                finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
        )


class LiveDeepSeekContractTest(unittest.TestCase):
    def test_requires_real_credentials(self):
        with self.assertRaisesRegex(ValueError, "MISSING_DEEPSEEK_API_KEY"):
            LiveDeepSeek(api_key="")

    def test_offline_response_contract(self):
        fake = FakeResponses()
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=fake))
        live = LiveDeepSeek(api_key="TEST_ONLY_NOT_REAL_KEY",
                            model="deepseek-flash", client=client)
        answer = live.complete("preflight", [{"role": "user", "content": "Hi"}])
        self.assertEqual(answer, "API_OK")
        self.assertEqual(live.calls[0]["stage"], "preflight")
        self.assertEqual(live.calls[0]["prompt_tokens"], 12)
        self.assertEqual(live.calls[0]["completion_tokens"], 3)
        self.assertEqual(fake.requests[0]["extra_body"]["thinking"]["type"], "disabled")
        self.assertEqual(fake.requests[0]["model"], "deepseek-flash")
        self.assertLessEqual(fake.requests[0]["max_tokens"], 24)

    def test_unknown_model_rejected(self):
        with self.assertRaises(ValueError):
            LiveDeepSeek(api_key="TEST_ONLY", model="deepseek-chat",
                         client=SimpleNamespace())

    def test_fixture_is_real_clean_git_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "sample"
            sha = create_real_git_fixture(root)
            head = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                text=True).strip()
            self.assertEqual(head, sha)
            self.assertEqual(len(sha), 40)
            self.assertIn("return a // b", (root / "calc.py").read_text())
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(root), "status", "--porcelain"]),
                b"",
            )

    def test_missing_key_is_explicit_not_false_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            outcome = run_live_experiment(
                report_path=Path(temporary) / "result.json", api_key="")
            self.assertEqual(outcome["status"], "NOT_RUN_MISSING_CREDENTIALS")
            self.assertFalse(outcome["api_preflight_passed"])
            self.assertFalse(outcome["internal_tests_passed"])
            self.assertEqual(outcome["model_calls"], [])


    def test_configured_coder_token_budget_is_bounded(self):
        fake = FakeResponses()
        client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        live = LiveDeepSeek(api_key="TEST_ONLY_NOT_REAL_KEY", model="deepseek-flash",
                            client=client, coder_max_tokens=5500)
        live.complete("coder", [{"role": "user", "content": "Output a Git diff"}])
        self.assertEqual(fake.requests[-1]["max_tokens"], 5500)
        with self.assertRaises(ValueError):
            LiveDeepSeek(api_key="TEST_ONLY", client=client, coder_max_tokens=90000)


if __name__ == "__main__":
    unittest.main()
