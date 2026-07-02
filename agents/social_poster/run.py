"""CLI entrypoint for the Social Poster.

    python -m agents.social_poster.run --feed agents/social_poster/sample_feed.json --out out

Picks the single best story from a JSON feed, drafts a long-form post + a short caption,
fact-checks them, and pauses for your approval. The reference publisher NEVER posts; it
writes the approved copy to out/social/<slug>/. Needs ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

from common.models import build_models
from common.runner import run

from .effects import make_effects
from .graph import build_social_graph


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Social Poster: pick a story -> draft two posts -> fact-check -> approve -> publish.")
    ap.add_argument("--feed", default="agents/social_poster/sample_feed.json", help="JSON list of candidate items.")
    ap.add_argument("--out", default="out", help="Output dir for staged posts + dedup ledger.")
    ap.add_argument("--window-days", type=int, default=14)
    args = ap.parse_args()

    ranker, writer = build_models()
    effects = make_effects(args.feed, args.out)
    graph = build_social_graph(ranker, writer, effects, checkpointer=MemorySaver())
    asyncio.run(run(graph, {"window_days": args.window_days}))


if __name__ == "__main__":
    main()
