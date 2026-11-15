"""Shared local configuration for the demo and CLI entry points."""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).with_name(".env"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")


@lru_cache(maxsize=1)
def get_client():
    return OpenAI(timeout=60)
