"""CLI entrypoint for the Blog Writer.

    python -m agents.blog_writer.run --sources sources --out out

Reads Markdown sources from --sources, proposes ideas, and walks you through the two
human gates in the terminal. Publishing is a dry-run (a local draft) unless you approve
with mode=live. Needs ANTHROPIC_API_KEY (a .env file is loaded automatically).
"""
from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

from common.models import build_models
from common.runner import run

from .effects import make_effects
from .graph import build_blog_writer_graph


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Blog Writer: research -> ideas -> draft -> publish, with two human gates.")
    ap.add_argument("--sources", default="sources", help="Directory of Markdown research sources.")
    ap.add_argument("--out", default="out", help="Output directory for posts + the dedup ledger.")
    args = ap.parse_args()

    ideator, writer = build_models()
    effects = make_effects(args.sources, args.out)
    graph = build_blog_writer_graph(ideator, writer, effects, checkpointer=MemorySaver())
    asyncio.run(run(graph, {}))


if __name__ == "__main__":
    main()
