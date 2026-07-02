"""CLI entrypoint for Lab Notes.

    python -m agents.lab_notes.run --feed agents/lab_notes/sample_feed.json --out out

Reads a JSON feed of candidate items, drafts a newsletter issue, fact-checks it, and
pauses for your approval before staging an HTML draft under out/newsletters/. Set
NEWSLETTER_NAME to brand it. Needs ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

from common.models import build_models
from common.runner import run

from .effects import make_effects
from .graph import build_lab_notes_graph


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Lab Notes: gather -> draft -> fact-check -> approve -> stage a newsletter draft.")
    ap.add_argument("--feed", default="agents/lab_notes/sample_feed.json", help="JSON list of candidate items.")
    ap.add_argument("--out", default="out", help="Output dir for staged drafts + dedup ledger.")
    ap.add_argument("--window-days", type=int, default=35)
    args = ap.parse_args()

    ranker, writer = build_models()
    effects = make_effects(args.feed, args.out)
    graph = build_lab_notes_graph(ranker, writer, effects, checkpointer=MemorySaver())
    asyncio.run(run(graph, {"window_days": args.window_days}))


if __name__ == "__main__":
    main()
