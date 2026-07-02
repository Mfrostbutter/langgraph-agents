"""Headless wiring test: stub models + in-memory effects, drive the gate to publish.

Run: `python agents/social_poster/tests/test_social_poster.py`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from langgraph.checkpoint.memory import MemorySaver           # noqa: E402
from langgraph.types import Command                            # noqa: E402

from agents.social_poster.graph import (                       # noqa: E402
    FactCheck, Selection, SocialPost, build_social_graph,
)


class _Structured:
    def __init__(self, value):
        self._v = value

    async def ainvoke(self, _messages):
        return self._v


class StubRanker:
    def with_structured_output(self, schema):
        return _Structured(Selection(index=0, reason="strongest story"))


class StubWriter:
    def with_structured_output(self, schema):
        if schema is FactCheck:
            return _Structured(FactCheck(flags=[]))
        return _Structured(SocialPost(facebook_md="A long-form post about the thing.",
                                      instagram_caption="Short caption.\n#ai #agents",
                                      link="", image_idea="A before/after diagram."))


def _effects(staged: list, published: list):
    items = [{"title": "Big agent release", "url": "u0", "source": "changelog",
              "summary": "It changes how you build.", "kind": "news", "score": 0}]

    def stage(post, item, slug, image=None, dry_run=False):
        staged.append((post, item, slug))
        return {"ok": True, "dry_run": False, "paths": {"facebook": "out/social/x/facebook.md",
                                                        "instagram": "out/social/x/instagram.md"}}

    def publish(post, image=None, dry_run=False):
        published.append((post, dry_run))
        return {"dry_run": True, "missing_creds": ["reference"], "would": {}}

    return {"fetch_all": lambda w: items, "partition_seen": lambda its: (its, []),
            "recent_titles": lambda: [], "mark_seen": lambda its, slug: None,
            "stage": stage, "publish": publish}


async def _scenario():
    staged: list = []
    published: list = []
    graph = build_social_graph(StubRanker(), StubWriter(), _effects(staged, published),
                               checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "sp1"}, "recursion_limit": 50}

    s1 = await graph.ainvoke({"window_days": 14}, cfg)
    assert "__interrupt__" in s1, "should pause at the review gate"
    assert "Long-form post" in s1["__interrupt__"][0].value.get("proposal", ""), "preview should show both drafts"

    s2 = await graph.ainvoke(Command(resume={"action": "approve", "mode": "dry_run"}), cfg)
    result = s2.get("result_md") or ""
    assert "Dry run" in result, f"reference publish is a dry run, got: {result[:120]}"
    assert staged, "the approved copy should be staged locally"
    assert published and published[0][1] is True, "publish called in dry-run mode"
    print("OK: pick -> draft -> factcheck -> gate -> stage + dry-run publish reached.")


def test_social_poster():
    asyncio.run(_scenario())


if __name__ == "__main__":
    test_social_poster()
