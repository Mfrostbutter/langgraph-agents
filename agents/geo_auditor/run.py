"""CLI entrypoint for the GEO Auditor.

    python -m agents.geo_auditor.run --domain example.com --brand "Example Co" \
        --queries agents/geo_auditor/sample_queries.txt

Probes every AI answer engine you have a key for (OPENAI_API_KEY, ANTHROPIC_API_KEY,
GEMINI_API_KEY, PERPLEXITY_API_KEY, BRAVE_API_KEY, YOU_API_KEY), in parallel, then has
the model propose GEO actions. Runs with any subset of keys, including none (every engine
just reports skipped). Needs ANTHROPIC_API_KEY for the analysis step.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

from common.models import build_models
from common.runner import run

from .effects import make_effects
from .graph import build_geo_graph


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="GEO Auditor: probe AI answer engines for citation share of your site.")
    ap.add_argument("--domain", help="Target domain that counts as a citation win (or set GEO_TARGET_DOMAINS).")
    ap.add_argument("--brand", help="Brand/entity string to detect a mention (or set GEO_BRAND_TOKEN).")
    ap.add_argument("--queries", help="Path to a file with one query per line. Defaults to the built-in examples.")
    args = ap.parse_args()

    queries = None
    if args.queries:
        queries = [ln.strip() for ln in Path(args.queries).read_text(encoding="utf-8").splitlines() if ln.strip()]

    effects = make_effects([args.domain] if args.domain else None, args.brand, queries)
    _cheap, quality = build_models()
    graph = build_geo_graph(quality, effects, checkpointer=MemorySaver())
    asyncio.run(run(graph, {"queries": effects["queries"]}))


if __name__ == "__main__":
    main()
