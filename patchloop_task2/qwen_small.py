"""OpenAI-compatible local vLLM client for sub-1B Qwen development experiments.

No silent fallback to DeepSeek/OpenAI. A model response must come from the
configured vLLM endpoint. Client injection is ONLY for offline contract tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import time
from urllib.parse import urlparse

MODELS = {
    "Qwen/Qwen2.5-Coder-0.5B-Instruct",
    "Qwen/Qwen3-0.6B",
    # Proposal base model (RQ1 baseline and QLoRA base).
    "Qwen/Qwen2.5-Coder-7B-Instruct",
}
DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
# "agent" is the single-agent baseline (RQ3): one conversation that both explores
# and submits edits, so it gets the Coder's output cap and the Planner's history trim.
STAGE_TOKENS = {"preflight": 32, "planner": 1500, "coder": 3500, "reviewer": 900, "agent": 3500}


@dataclass(frozen=True)
class QwenSettings:
    model: str = DEFAULT_MODEL
    endpoint: str = "http://127.0.0.1:8000/v1"
    api_key: str = "EMPTY"
    max_calls: int = 20
    context_chars: int = 18500
    timeout_seconds: int = 100

    def __post_init__(self):
        if self.model not in MODELS:
            raise ValueError("Unsupported Qwen model; choose Qwen2.5-Coder-0.5B/7B-Instruct or Qwen3-0.6B")
        uri = urlparse(self.endpoint)
        if (uri.scheme not in {"http", "https"} or not uri.hostname
                or not self.endpoint.rstrip("/").endswith("/v1")
                or uri.username or uri.password or uri.query or uri.fragment):
            raise ValueError("QWEN_BASE_URL must be a clean http(s) /v1 endpoint")
        if uri.scheme == "http" and uri.hostname not in {
            "localhost", "127.0.0.1", "::1"
        }:
            raise ValueError(
                "Remote HTTP endpoint is not secure: use SSH port forwarding to localhost or HTTPS"
            )
        if not self.api_key:
            raise ValueError("QWEN_API_KEY cannot be empty (use EMPTY for local vLLM without auth)")
        if type(self.max_calls) is not int or not 2 <= self.max_calls <= 40:
            raise ValueError("max_calls must be an integer from 2 to 40")
        if type(self.context_chars) is not int or not 5000 <= self.context_chars <= 50000:
            raise ValueError("context_chars must be 5000..50000")
        if type(self.timeout_seconds) is not int or not 5 <= self.timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be 5..300")

    @classmethod
    def from_env(cls) -> "QwenSettings":
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        except ImportError:
            pass
        return cls(
            model=os.getenv("QWEN_MODEL", DEFAULT_MODEL),
            endpoint=os.getenv("QWEN_BASE_URL", "http://127.0.0.1:8000/v1"),
            api_key=os.getenv("QWEN_API_KEY", "EMPTY"),
            max_calls=int(os.getenv("QWEN_MAX_CALLS", "20")),
            context_chars=int(os.getenv("QWEN_CONTEXT_CHARS", "18500")),
            timeout_seconds=int(os.getenv("QWEN_TIMEOUT", "100")),
        )


def trim_planner_history(messages: list[dict], limit: int) -> tuple[list[dict], int]:
    """Keep system, original issue and recent evidence; never invent source lines.

    Tool evidence retained for Task 1's FINAL validation lives in the harness.
    The model window is deliberately smaller so sub-1B inference fits its KV cache.
    """
    if not isinstance(messages, list) or len(messages) < 2:
        raise ValueError("Expected system message and issue message")
    preserved = messages[:2]
    initial = sum(len(str(x.get("content", ""))) for x in preserved)
    if initial > limit:
        raise ValueError("System and issue prompts alone exceed Qwen context budget")
    remaining = limit - initial
    selected = []
    skipped = 0
    for item in reversed(messages[2:]):
        if not isinstance(item, dict):
            raise ValueError("Invalid message object")
        size = len(str(item.get("content", "")))
        if size <= remaining:
            selected.append(item)
            remaining -= size
        else:
            skipped += 1
    return preserved + list(reversed(selected)), skipped


def clean_json_fence(raw: str) -> str:
    """Strip ONLY an outer markdown JSON fence used by very small models."""
    if not isinstance(raw, str):
        raise ValueError("Model returned non-text completion")
    stripped = raw.strip()
    marker = chr(96) * 3
    if stripped.startswith(marker):
        lines = stripped.splitlines()
        if (len(lines) >= 3 and lines[0].strip() in {marker, marker + "json"}
                and lines[-1].strip() == marker):
            return "\n".join(lines[1:-1]).strip()
    return raw


class QwenSmallBackend:
    extra_body: dict | None = None  # provider-specific request fields (DeepSeekBackend)
    provider = "qwen"
    # Hidden reasoning (DeepSeek thinking mode, RQ1). max_tokens covers reasoning + answer,
    # so each call gets this many extra tokens for reasoning ON TOP of the stage's answer
    # cap. Answer caps and the 15 000 answer-token budget stay identical across effort
    # levels; reasoning tokens are counted (and capped per task) separately.
    reasoning_allowance = 0
    reasoning_budget = 0  # per-task reasoning tokens; 0 = reasoning not expected

    def __init__(self, settings: QwenSettings | None = None, *, client=None):
        self.settings = settings or QwenSettings.from_env()
        self.model = self.settings.model
        if client is None:
            from openai import OpenAI
            client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.endpoint,
                max_retries=0,
                timeout=self.settings.timeout_seconds,
            )
        self.client = client
        self.calls: list[dict] = []
        self.output_tokens = 0     # answer tokens (excludes hidden reasoning)
        self.reasoning_tokens = 0

    def complete(self, stage: str, messages: list[dict]) -> str:
        if stage not in STAGE_TOKENS:
            raise ValueError("Unsupported Qwen stage")
        if len(self.calls) >= self.settings.max_calls:
            raise RuntimeError("QWEN_CALL_BUDGET_EXHAUSTED")
        if self.output_tokens >= 15000:
            raise RuntimeError("QWEN_TOKEN_BUDGET_EXHAUSTED")
        if self.reasoning_budget and self.reasoning_tokens >= self.reasoning_budget:
            raise RuntimeError("REASONING_TOKEN_BUDGET_EXHAUSTED")
        if stage in {"planner", "agent"}:
            transmitted, omitted = trim_planner_history(messages, self.settings.context_chars)
        else:
            transmitted, omitted = messages, 0
            total = sum(len(str(m.get("content", ""))) for m in messages)
            if total > max(self.settings.context_chars + 3500, 24000):
                raise ValueError(f"{stage} prompt exceeds context budget")
        t0 = time.monotonic()
        request_limit = min(STAGE_TOKENS[stage], 15000 - self.output_tokens)
        reply = self.client.chat.completions.create(
            model=self.model,
            messages=transmitted,
            max_tokens=request_limit + self.reasoning_allowance,
            temperature=0,  # ignored by DeepSeek in thinking mode (sampling then varies)
            **({"extra_body": self.extra_body} if self.extra_body else {}),
        )
        duration = round(time.monotonic() - t0, 3)
        if not reply.choices:
            raise RuntimeError(f"QWEN_EMPTY_CHOICES:{stage}")
        choice = reply.choices[0]
        value = getattr(choice.message, "content", None)
        usage = getattr(reply, "usage", None)
        output_count = getattr(usage, "completion_tokens", None)
        details = getattr(usage, "completion_tokens_details", None)
        reasoning = getattr(details, "reasoning_tokens", None)
        reasoning = reasoning if isinstance(reasoning, int) and reasoning > 0 else 0
        if isinstance(output_count, int):
            answer_tokens = max(0, output_count - reasoning)
        else:
            answer_tokens = request_limit
        self.output_tokens += answer_tokens
        self.reasoning_tokens += reasoning
        self.calls.append({
            "stage": stage,
            "response_model": str(getattr(reply, "model", ""))[:120],
            "finish_reason": str(getattr(choice, "finish_reason", "")),
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": output_count,
            "reasoning_tokens": reasoning,
            "latency_seconds": duration,
            "dropped_history_messages": omitted,
            "output_sha256": sha256(value.encode("utf-8")).hexdigest()
            if isinstance(value, str) else None,
        })
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"QWEN_EMPTY_CONTENT:{stage}")
        if getattr(choice, "finish_reason", None) == "length":
            raise RuntimeError(f"QWEN_TRUNCATED_OUTPUT:{stage}")
        if self.reasoning_allowance and answer_tokens > request_limit:
            # Same rule as without reasoning: an answer longer than the stage cap would
            # have been cut off, so the extra reasoning room must not lengthen answers.
            raise RuntimeError(f"QWEN_TRUNCATED_OUTPUT:{stage}")
        return clean_json_fence(value) if stage in {"planner", "reviewer"} else value

    def callback(self, stage: str):
        return lambda messages: self.complete(stage, messages)

    def verify(self) -> dict:
        data = self.client.models.list()
        advertised = [getattr(item, "id", None) for item in data.data]
        if self.model not in advertised:
            raise RuntimeError(
                "QWEN_MODEL_ID_MISMATCH: the /v1/models endpoint does not advertise "
                + self.model
            )
        answer = self.complete("preflight", [{
            "role": "user", "content": "Reply with READY and nothing else."
        }])
        return {
            "status": "live_qwen_api_ok",
            "model": self.model,
            "endpoint": self.settings.endpoint,
            "sample_response": answer[:80],
            "live_calls": len(self.calls),
        }
