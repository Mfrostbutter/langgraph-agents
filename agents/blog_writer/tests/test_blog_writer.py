"""Headless wiring test: stub models + in-memory effects, drive both human gates.

No API key needed. Run with `python -m pytest agents/blog_writer/tests` or directly:
`python agents/blog_writer/tests/test_blog_writer.py`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# make the repo root importable when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from langgraph.checkpoint.memory import MemorySaver          # noqa: E402
from langgraph.types import Command                           # noqa: E402

from agents.blog_writer.graph import (                        # noqa: E402
    FactCheck, Ideas, Post, PostIdea, build_blog_writer_graph,
)


class _Structured:
    def __init__(self, value):
        self._v = value

    async def ainvoke(self, _messages):
        return self._v


class StubIdeator:
    def with_structured_output(self, schema):
        return _Structured(Ideas(ideas=[
            PostIdea(title="Idea A", angle="Angle A", source_keys=["s1"], outline=["a", "b"]),
            PostIdea(title="Idea B", angle="Angle B", source_keys=["s2"], outline=["c"]),
        ]))


class StubWriter:
    def with_structured_output(self, schema):
        if schema is FactCheck:
            return _Structured(FactCheck(flags=[]))
        return _Structured(Post(title="Idea A", description="d" * 130, tags=["t1", "t2"],
                                body_md="Body text. " * 120))


def _make_effects(published: list):
    sources = [
        {"key": "s1", "kind": "note", "title": "S1", "summary": "sum1", "content": "content one"},
        {"key": "s2", "kind": "note", "title": "S2", "summary": "sum2", "content": "content two"},
    ]

    def publish(post, keys, dry_run=True):
        published.append((post, keys, dry_run))
        return {"ok": True, "dry_run": dry_run, "slug": "idea-a", "path": "out/posts/idea-a.md", "note": "ok"}

    return {
        "fetch_all": lambda: sources,
        "partition_sources": lambda items: (items, []),
        "recent_posts": lambda: [],
        "publish": publish,
    }


async def _scenario():
    published: list = []
    graph = build_blog_writer_graph(StubIdeator(), StubWriter(), _make_effects(published),
                                    checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}, "recursion_limit": 50}

    s1 = await graph.ainvoke({}, cfg)
    assert "__interrupt__" in s1, "should pause at the idea gate"

    s2 = await graph.ainvoke(Command(resume={"action": "approve", "choice": 1, "mode": "dry_run"}), cfg)
    assert "__interrupt__" in s2, "should pause at the draft gate"

    s3 = await graph.ainvoke(Command(resume={"action": "approve", "mode": "dry_run"}), cfg)
    result = s3.get("result_md") or ""
    assert "Staged" in result, f"expected a staged (dry-run) result, got: {result[:120]}"
    assert published and published[0][2] is True, "publish must be called with dry_run=True"
    print("OK: two gates, dry-run publish reached.")


def test_blog_writer():
    asyncio.run(_scenario())


if __name__ == "__main__":
    test_blog_writer()
