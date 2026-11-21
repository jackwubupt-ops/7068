"""Model backends behind ONE interface, so the agents and harness never change.

    qwen      local vLLM, Qwen2.5-Coder-7B-Instruct (proposal model; private, no API cost)
    deepseek  hosted DeepSeek API (stronger model; the issue and code SENT to DeepSeek)

Both use QwenSmallBackend's logic: the same per-stage output caps, the same
per-task call and token budgets, the same history trimming and the same error
codes, so a batch run on either backend is directly comparable.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse

from .qwen_small import QwenSettings, QwenSmallBackend

DEEPSEEK_MODELS = {"deepseek-flash", "deepseek-v4-pro"}
# RQ1: reasoning effort. "none" = thinking disabled (the default and the RQ3 setting);
# low/high/max enable DeepSeek's thinking mode. Per effort: (extra max_tokens per call
# for reasoning, reasoning-token budget per task, default request timeout in seconds).
# The per-call room equals DeepSeek's own default max_tokens in thinking mode (64K, and
# 128K for max), so the effort level -- not our cap -- decides how long the model thinks.
# (A first run with 8K/24K/48K cut off the reasoning of some Coder calls.)
REASONING_EFFORTS = ("none", "low", "high", "max")
REASONING_DEFAULTS = {
    "none": (0, 0, 120),
    "low": (65536, 400_000, 600),
    "high": (65536, 600_000, 600),
    "max": (131072, 1_200_000, 900),
}
DEEPSEEK_ENDPOINT = "https://api.deepseek.com"
BACKENDS = ("qwen", "deepseek")
_PLACEHOLDERS = {"", "EMPTY", "DUMMY", "YOUR_API_KEY", "sk-..."}


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    except ImportError:
        pass


@dataclass(frozen=True)
class DeepSeekSettings:
    model: str = "deepseek-flash"
    endpoint: str = DEEPSEEK_ENDPOINT
    api_key: str = ""
    max_calls: int = 20
    context_chars: int = 48000
    timeout_seconds: int = 120
    reasoning_effort: str = "none"
    reasoning_tokens_per_call: int | None = None   # None = default for the effort
    reasoning_budget: int | None = None            # None = default for the effort

    def __post_init__(self):
        if self.reasoning_effort not in REASONING_EFFORTS:
            raise ValueError(f"DEEPSEEK_REASONING_EFFORT must be one of {list(REASONING_EFFORTS)}")
        allowance, budget, _ = REASONING_DEFAULTS[self.reasoning_effort]
        if self.reasoning_tokens_per_call is None:
            object.__setattr__(self, "reasoning_tokens_per_call", allowance)
        if self.reasoning_budget is None:
            object.__setattr__(self, "reasoning_budget", budget)
        if self.reasoning_effort == "none" and (self.reasoning_tokens_per_call or self.reasoning_budget):
            raise ValueError("reasoning token settings need DEEPSEEK_REASONING_EFFORT low/high/max")
        if self.reasoning_effort != "none" and not (
                1024 <= self.reasoning_tokens_per_call <= 131072 and self.reasoning_budget >= 1024):
            raise ValueError("reasoning_tokens_per_call must be 1024..131072 and reasoning_budget >= 1024")
        if self.model not in DEEPSEEK_MODELS:
            raise ValueError(f"DEEPSEEK_MODEL must be one of {sorted(DEEPSEEK_MODELS)}")
        if self.api_key.strip() in _PLACEHOLDERS:
            raise ValueError("MISSING_DEEPSEEK_API_KEY: set DEEPSEEK_API_KEY in .env (never commit it)")
        if urlparse(self.endpoint).scheme != "https":
            raise ValueError("The DeepSeek endpoint must use HTTPS")
        if type(self.max_calls) is not int or not 2 <= self.max_calls <= 40:
            raise ValueError("max_calls must be an integer from 2 to 40")
        if type(self.context_chars) is not int or not 5000 <= self.context_chars <= 50000:
            raise ValueError("context_chars must be 5000..50000")
        if type(self.timeout_seconds) is not int or not 5 <= self.timeout_seconds <= 900:
            raise ValueError("timeout_seconds must be 5..900")

    @classmethod
    def from_env(cls, reasoning_effort: str | None = None) -> "DeepSeekSettings":
        _load_dotenv()
        effort = reasoning_effort or os.getenv("DEEPSEEK_REASONING_EFFORT", "none")
        default_timeout = REASONING_DEFAULTS.get(effort, (0, 0, 120))[2]
        optional = lambda name: int(os.environ[name]) if os.getenv(name) else None
        # Budgets default to the Qwen ones so the two backends stay matched.
        return cls(
            reasoning_effort=effort,
            reasoning_tokens_per_call=optional("DEEPSEEK_REASONING_TOKENS_PER_CALL"),
            reasoning_budget=optional("DEEPSEEK_REASONING_BUDGET"),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
            endpoint=os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_ENDPOINT),
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            max_calls=int(os.getenv("DEEPSEEK_MAX_CALLS", os.getenv("QWEN_MAX_CALLS", "20"))),
            context_chars=int(os.getenv("DEEPSEEK_CONTEXT_CHARS", os.getenv("QWEN_CONTEXT_CHARS", "48000"))),
            timeout_seconds=int(os.getenv("DEEPSEEK_TIMEOUT", str(default_timeout))),
        )


class DeepSeekBackend(QwenSmallBackend):
    """Same budgets/trimming/errors as the Qwen backend; reasoning effort is configurable.

    effort "none": thinking explicitly disabled (DeepSeek enables it by default), so
    replies are direct JSON/edits within the per-stage caps. low/high/max: thinking
    enabled at that effort; the hidden reasoning gets its own per-call room and
    per-task budget, the visible answer keeps the same caps (RQ1).
    """

    provider = "deepseek"

    def __init__(self, settings: DeepSeekSettings | None = None, *, client=None):
        super().__init__(settings or DeepSeekSettings.from_env(), client=client)
        effort = self.settings.reasoning_effort
        self.reasoning_effort = effort
        if effort == "none":
            self.extra_body = {"thinking": {"type": "disabled"}}
        else:
            # Passed in extra_body: the OpenAI SDK does not know every DeepSeek value ("max").
            self.extra_body = {"thinking": {"type": "enabled"}, "reasoning_effort": effort}
            self.reasoning_allowance = self.settings.reasoning_tokens_per_call
            self.reasoning_budget = self.settings.reasoning_budget

    def verify(self) -> dict:
        # GET /models is not documented for DeepSeek: verify with a tiny real call.
        answer = self.complete("preflight", [{"role": "user", "content": "Reply with READY and nothing else."}])
        return {"status": "live_deepseek_api_ok", "model": self.model,
                "reasoning_effort": self.reasoning_effort,
                "endpoint": self.settings.endpoint, "sample_response": answer[:80],
                "data_leaves_server": True}


def load_settings(name: str, *, reasoning_effort: str | None = None):
    if name == "qwen":
        if reasoning_effort not in (None, "none"):
            raise ValueError("reasoning effort applies to the deepseek backend only")
        return QwenSettings.from_env()
    if name == "deepseek":
        return DeepSeekSettings.from_env(reasoning_effort)
    raise ValueError(f"backend must be one of {BACKENDS}")


def make_backend(name: str, settings=None):
    settings = settings or load_settings(name)
    return DeepSeekBackend(settings) if name == "deepseek" else QwenSmallBackend(settings)
