"""Build the two Anthropic chat models these agents use.

The pattern throughout this repo is TWO models per agent:
  - a cheap/fast model for triage, ranking, and structured selection
  - a quality model for writing prose and fact-checking

Both are injected into the graph factory, so the graph never reads env or
constructs a client itself (see any agent's `graph.py`). Override the model
IDs with env vars without touching code.
"""
from __future__ import annotations

import os

# Sensible defaults. Override per deployment.
QUALITY_MODEL = os.environ.get("LGA_QUALITY_MODEL", "claude-sonnet-5")
CHEAP_MODEL = os.environ.get("LGA_CHEAP_MODEL", "claude-haiku-4-5-20251001")


def build_models(quality_temperature: float = 0.4):
    """Return (cheap, quality) ChatAnthropic clients. Raises if no key is set."""
    from langchain_anthropic import ChatAnthropic

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Put it in a .env file or your environment. "
            "(For a no-key structural run, drive the graph with stub models — see each agent's tests.)"
        )
    cheap = ChatAnthropic(model=CHEAP_MODEL, temperature=0, max_tokens=2048, api_key=key)
    quality = ChatAnthropic(model=QUALITY_MODEL, temperature=quality_temperature, max_tokens=4096, api_key=key)
    return cheap, quality
