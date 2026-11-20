"""Shared local configuration for Demo, Task 1/2/3 and CLI entry points."""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).with_name(".env"))

PATCHLOOP_MODEL_BACKEND = os.getenv("PATCHLOOP_MODEL_BACKEND", "openai").lower()
if PATCHLOOP_MODEL_BACKEND not in {"openai", "qwen"}:
    raise ValueError("PATCHLOOP_MODEL_BACKEND must be openai or qwen")

if PATCHLOOP_MODEL_BACKEND == "qwen":
    from patchloop_task2.qwen_small import QwenSettings
    OPENAI_MODEL = QwenSettings.from_env().model
else:
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")


@lru_cache(maxsize=1)
def get_client():
    if PATCHLOOP_MODEL_BACKEND == "qwen":
        from patchloop_task2.qwen_small import QwenSettings
        settings = QwenSettings.from_env()
        return OpenAI(
            api_key=settings.api_key,
            base_url=settings.endpoint,
            timeout=settings.timeout_seconds,
            max_retries=0,
        )
    return OpenAI(timeout=60)
