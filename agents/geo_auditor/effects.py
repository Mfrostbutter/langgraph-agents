"""Reference effects for the GEO Auditor: wire the real engine probes to config.

Nothing here is brand-specific. You supply:
  - target_domains : domains that count as a citation win (arg or GEO_TARGET_DOMAINS, comma-sep)
  - brand_token    : a lowercase entity string to detect a mention (arg or GEO_BRAND_TOKEN)
  - queries        : the question set to probe (arg or the default examples below)

`available(e)` is True when engine e's API key env var is set; `probe(e, q)` runs the
real HTTP probe and scores it. Engines without a key are skipped, so the agent runs with
whatever subset of keys you have (including none).
"""
from __future__ import annotations

import os

from .probes import ENGINE_KEYS, ENGINE_NAMES, run_probe

# Replace these with the questions your audience actually asks an AI answer engine.
DEFAULT_QUERIES = [
    "best open source tools for building AI agents",
    "how to run a self-hosted AI automation stack",
    "how do I add human-in-the-loop approval to a LangGraph agent",
    "python framework for building stateful LLM agents",
]


def _split(csv: str) -> list[str]:
    return [x.strip() for x in (csv or "").split(",") if x.strip()]


def make_effects(target_domains: list[str] | None = None,
                 brand_token: str | None = None,
                 queries: list[str] | None = None) -> dict:
    domains = tuple(d.lower().lstrip("www.") for d in (target_domains or _split(os.environ.get("GEO_TARGET_DOMAINS", ""))))
    raw_brand = brand_token if brand_token is not None else os.environ.get("GEO_BRAND_TOKEN", "")
    brand = (raw_brand or "").lower().strip()

    def available(engine: str) -> bool:
        return bool(os.environ.get(ENGINE_KEYS.get(engine, ""), "").strip())

    def probe(engine: str, query: str) -> dict:
        key = os.environ.get(ENGINE_KEYS.get(engine, ""), "").strip()
        return run_probe(engine, query, key, domains, brand)

    return {
        "engines": ENGINE_NAMES,
        "available": available,
        "probe": probe,
        "queries": queries or DEFAULT_QUERIES,
        "target_domain": domains[0] if domains else "your-domain.com",
        "brand_name": raw_brand or "your brand",
    }
