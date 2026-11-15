"""Qwen vLLM endpoint preflight for live SWE-bench development runs.

The existing Planner/Coder/Reviewer already use config.get_client() and
OPENAI_MODEL. This module checks their shared endpoint before inference.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

QWEN_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"


def validate_qwen_configuration(environ=None) -> dict:
    env = os.environ if environ is None else environ
    model = env.get("OPENAI_MODEL", "")
    endpoint = env.get("OPENAI_BASE_URL", "")
    if model != QWEN_MODEL:
        raise ValueError(f"Live SWE-bench requires OPENAI_MODEL={QWEN_MODEL}; got {model!r}")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Set OPENAI_BASE_URL to your own running vLLM /v1 endpoint")
    if not endpoint.rstrip("/").endswith("/v1"):
        raise ValueError("OPENAI_BASE_URL must end with /v1")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Do not embed credentials in model endpoint URL")
    if parsed.hostname in {"api.openai.com", "api.deepseek.com"}:
        raise ValueError("This run must target a real Qwen-serving endpoint, not the old Demo provider")
    return {"model": model, "base_url": endpoint.rstrip("/")}


def verify_qwen_endpoint(client=None) -> dict:
    """Make a real chat request; no mock or stand-in response counts as a live check."""
    config = validate_qwen_configuration()
    if client is None:
        from config import get_client
        client = get_client()
    available = client.models.list()
    names = [m.id for m in available.data]
    if config["model"] not in names:
        raise RuntimeError("vLLM /models did not advertise the expected Qwen model ID")
    result = client.chat.completions.create(
        model=config["model"],
        messages=[{"role": "user", "content": "Respond with the single word READY."}],
        temperature=0, max_tokens=12,
    )
    if not result.choices or not isinstance(result.choices[0].message.content, str):
        raise RuntimeError("No usable model output")
    output = result.choices[0].message.content.strip()
    if not output:
        raise RuntimeError("Empty Qwen completion")
    return {"model": config["model"], "endpoint": config["base_url"],
            "chat_ok": True, "sample_output": output[:100],
            "prompt_tokens": getattr(getattr(result, "usage", None), "prompt_tokens", None),
            "completion_tokens": getattr(getattr(result, "usage", None), "completion_tokens", None)}


def main() -> int:
    import json
    result = verify_qwen_endpoint()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
