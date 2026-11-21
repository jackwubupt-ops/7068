"""Offline tests for RQ1 reasoning effort on the DeepSeek backend.

Scripted fake client (no network): proves the request fields and the token accounting,
not model quality.
"""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from patchloop_task2.backends import DeepSeekBackend, DeepSeekSettings, load_settings
from patchloop_task2.qwen_small import QwenSettings, QwenSmallBackend

MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


class ThinkingClient:
    """Replies with `completion` tokens of which `reasoning` are hidden reasoning."""

    def __init__(self, completion=600, reasoning=500, finish="stop", text="READY"):
        self.requests = []
        self.completion, self.reasoning, self.finish, self.text = completion, reasoning, finish, text
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=self.completion,
                                completion_tokens_details=SimpleNamespace(reasoning_tokens=self.reasoning))
        return SimpleNamespace(model=kwargs["model"], usage=usage, choices=[SimpleNamespace(
            message=SimpleNamespace(content=self.text), finish_reason=self.finish)])


def settings(**kw):
    return DeepSeekSettings(**{"api_key": "sk-test-not-real", **kw})


class ReasoningEffortTests(unittest.TestCase):
    def test_none_is_the_default_and_disables_thinking(self):
        client = ThinkingClient(completion=5, reasoning=0)
        backend = DeepSeekBackend(settings(), client=client)
        backend.complete("coder", MSGS)
        self.assertEqual(client.requests[0]["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(client.requests[0]["max_tokens"], 3500)
        self.assertEqual((backend.reasoning_allowance, backend.reasoning_budget), (0, 0))

    def test_high_enables_thinking_with_extra_room_but_same_answer_cap(self):
        client = ThinkingClient(completion=1500, reasoning=1200)
        backend = DeepSeekBackend(settings(reasoning_effort="high"), client=client)
        backend.complete("coder", MSGS)
        sent = client.requests[0]
        self.assertEqual(sent["extra_body"], {"thinking": {"type": "enabled"}, "reasoning_effort": "high"})
        self.assertEqual(sent["max_tokens"], 3500 + 24576)
        self.assertEqual(backend.output_tokens, 300)     # answer tokens only
        self.assertEqual(backend.reasoning_tokens, 1200)
        self.assertEqual(backend.calls[0]["reasoning_tokens"], 1200)

    def test_answer_longer_than_stage_cap_counts_as_truncated(self):
        client = ThinkingClient(completion=2000, reasoning=100)  # answer 1900 > planner cap 1500
        backend = DeepSeekBackend(settings(reasoning_effort="low"), client=client)
        with self.assertRaisesRegex(RuntimeError, "QWEN_TRUNCATED_OUTPUT:planner"):
            backend.complete("planner", MSGS)

    def test_reasoning_budget_stops_the_task(self):
        client = ThinkingClient(completion=3000, reasoning=2900)
        backend = DeepSeekBackend(settings(reasoning_effort="low", reasoning_budget=5000), client=client)
        backend.complete("agent", MSGS)
        backend.complete("agent", MSGS)
        with self.assertRaisesRegex(RuntimeError, "REASONING_TOKEN_BUDGET_EXHAUSTED"):
            backend.complete("agent", MSGS)

    def test_settings_validation_and_defaults(self):
        with self.assertRaisesRegex(ValueError, "REASONING_EFFORT"):
            settings(reasoning_effort="medium")
        with self.assertRaisesRegex(ValueError, "need"):
            settings(reasoning_tokens_per_call=4096)
        mx = settings(reasoning_effort="max")
        self.assertEqual((mx.reasoning_tokens_per_call, mx.reasoning_budget), (49152, 600_000))
        env = {"DEEPSEEK_API_KEY": "sk-test-not-real", "DEEPSEEK_REASONING_EFFORT": "low"}
        with patch.dict("os.environ", env, clear=False), patch("patchloop_task2.backends._load_dotenv"):
            from_env = DeepSeekSettings.from_env()
            self.assertEqual((from_env.reasoning_effort, from_env.timeout_seconds), ("low", 300))
            self.assertEqual(load_settings("deepseek", reasoning_effort="high").reasoning_effort, "high")
            with self.assertRaisesRegex(ValueError, "deepseek backend only"):
                load_settings("qwen", reasoning_effort="high")

    def test_qwen_accounting_unchanged_without_details(self):
        client = ThinkingClient(completion=40, reasoning=None)
        backend = QwenSmallBackend(QwenSettings(model="Qwen/Qwen2.5-Coder-7B-Instruct"), client=client)
        backend.complete("coder", MSGS)
        self.assertEqual((backend.output_tokens, backend.reasoning_tokens), (40, 0))
        self.assertEqual(client.requests[0]["max_tokens"], 3500)


if __name__ == "__main__":
    unittest.main()
