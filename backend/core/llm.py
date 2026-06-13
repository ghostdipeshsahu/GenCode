"""Shared LLM client for GenCode.

All three components that talk to the LLM — Code Generator (Step 3), Assessor
agent (Step 4), and Author script (Step 7) — go through here so the provider,
model, key handling, and dotenv loading live in one place.

Provider note: spec section 8 pins Anthropic + claude-sonnet-4-6, but for this
build the Anthropic account has no credit balance. We are using OpenRouter
(OpenAI-compatible) + openai/gpt-oss-120b:free as a $0 substitute. Swap
BASE_URL + MODEL + KEY_ENV when credits arrive.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


# Resolve backend/.env from this file's location so the working directory
# does not matter at import time.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_DIR / ".env")


BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "openai/gpt-oss-120b:free"
KEY_ENV = "OPENROUTER_API_KEY"

# Headers OpenRouter uses for rate-limit accounting / dashboard attribution.
EXTRA_HEADERS = {
    "HTTP-Referer": "https://github.com/nxtwave/gencode",
    "X-Title": "GenCode",
}


_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Lazy singleton. Importing this module does not require the key."""
    global _client
    if _client is None:
        key = os.environ.get(KEY_ENV)
        if not key:
            raise RuntimeError(
                f"{KEY_ENV} is not set. Put it in gencode/backend/.env "
                "or export it in the shell."
            )
        _client = OpenAI(base_url=BASE_URL, api_key=key)
    return _client
