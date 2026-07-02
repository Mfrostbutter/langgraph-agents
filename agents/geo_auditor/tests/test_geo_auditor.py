"""Headless wiring test: stub llm + mock probe engines, verify the fan-out /
fan-in / analyze topology. No API key, no network.

Run: `python agents/geo_auditor/tests/test_geo_auditor.py`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from langchain_core.messages import AIMessage                 # noqa: E402
from langgraph.checkpoint.memory import MemorySaver           # noqa: E402

from agents.geo_auditor.graph import build_geo_graph          # noqa: E402


class StubLLM:
    async def ainvoke(self, _messages):
        return AIMessage(content="GEO actions: build an entity page; earn a backlink.")


def _mock_effects():
    def probe(engine, query):
        # engine 'b' knows the brand but does not cite the site (the sharp gap signal)
        cited = engine == "mock_a"
        return {"engine": engine, "query": query, "cited": cited, "brand_mentioned": True,
                "competing_domains": "competitor.com", "status": "ok"}

    return {"engines": ("mock_a", "mock_b"), "available": lambda e: True, "probe": probe,
            "queries": ["q1", "q2"], "target_domain": "example.com", "brand_name": "Example"}


async def _scenario():
    graph = build_geo_graph(StubLLM(), _mock_effects(), checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "geo1"}, "recursion_limit": 50}
    state = await graph.ainvoke({"queries": ["q1", "q2"]}, cfg)

    summary = state.get("summary") or {}
    assert set(summary) == {"mock_a", "mock_b"}, f"both engines should be in the summary: {summary}"
    assert summary["mock_a"]["cited"] == 2, "mock_a cites on every query"
    assert summary["mock_b"]["cited"] == 0, "mock_b never cites"
    final = [m for m in state["messages"] if not getattr(m, "name", None)][-1].content
    assert "GEO actions" in final, f"analyze should produce the final actions, got: {final[:80]}"
    print("OK: parallel fan-out (2 engines) -> synthesize -> analyze reached.")


def test_geo_auditor():
    asyncio.run(_scenario())


if __name__ == "__main__":
    test_geo_auditor()
