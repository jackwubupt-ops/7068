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

    def __post_init__(self):
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
        if type(self.timeout_seconds) is not int or not 5 <= self.timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be 5..300")

    @classmethod
    def from_env(cls) -> "DeepSeekSettings":
        _load_dotenv()
        # Budgets default to the Qwen ones so the two backends stay matched.
        return cls(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
            endpoint=os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_ENDPOINT),
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            max_calls=int(os.getenv("DEEPSEEK_MAX_CALLS", os.getenv("QWEN_MAX_CALLS", "20"))),
            context_chars=int(os.getenv("DEEPSEEK_CONTEXT_CHARS", os.getenv("QWEN_CONTEXT_CHARS", "48000"))),
            timeout_seconds=int(os.getenv("DEEPSEEK_TIMEOUT", "120")),
        )


class DeepSeekBackend(QwenSmallBackend):
    """Same budgets/trimming/errors as the Qwen backend; non-thinking mode."""

    # DeepSeek's thinking mode is on by default; the agents expect direct JSON /
    # edit replies within the per-stage output caps, so it is switched off.
    extra_body = {"thinking": {"type": "disabled"}}
    provider = "deepseek"

    def __init__(self, settings: DeepSeekSettings | None = None, *, client=None):
        super().__init__(settings or DeepSeekSettings.from_env(), client=client)

    def verify(self) -> dict:
        # GET /models is not documented for DeepSeek: verify with a tiny real call.
        answer = self.complete("preflight", [{"role": "user", "content": "Reply with READY and nothing else."}])
        return {"status": "live_deepseek_api_ok", "model": self.model,
                "endpoint": self.settings.endpoint, "sample_response": answer[:80],
                "data_leaves_server": True}


def load_settings(name: str):
    if name == "qwen":
        return QwenSettings.from_env()
    if name == "deepseek":
        return DeepSeekSettings.from_env()
    raise ValueError(f"backend must be one of {BACKENDS}")


def make_backend(name: str, settings=None):
    settings = settings or load_settings(name)
    return DeepSeekBackend(settings) if name == "deepseek" else QwenSmallBackend(settings)
