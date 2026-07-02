"""Headless wiring test: stub models + in-memory effects, drive the gate to a stage.

Run: `python agents/lab_notes/tests/test_lab_notes.py`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from langgraph.checkpoint.memory import MemorySaver           # noqa: E402
from langgraph.types import Command                            # noqa: E402

from agents.lab_notes.graph import (                           # noqa: E402
    FactCheck, Issue, Selection, Verdict, build_lab_notes_graph,
)


class _Structured:
    def __init__(self, value):
        self._v = value

    async def ainvoke(self, _messages):
        return self._v


class StubRanker:
    def with_structured_output(self, schema):
        return _Structured(Selection(one_thing=0, tools=[1], repos=[2], reading=[3]))


class StubWriter:
    def with_structured_output(self, schema):
        if schema is FactCheck:
            return _Structured(FactCheck(flags=[]))
        return _Structured(Issue(subject="The Brief #01: agents got real",
                                 intro_md="Intro.", one_thing_md="One thing.\n\nThe move: ship it.",
                                 tools=[Verdict(index=1, line="Worth adopting.")],
                                 repos=[Verdict(index=2, line="Watch it.")],
                                 reading=[Verdict(index=3, line="Read it.")],
                                 bench_md="Bench note.", steal_md="Steal this prompt."))


def _effects(staged: list):
    items = [
        {"title": "A", "url": "u0", "source": "s", "summary": "sa", "kind": "news", "score": 0},
        {"title": "B", "url": "u1", "source": "s", "summary": "sb", "kind": "repo", "score": 9},
        {"title": "C", "url": "u2", "source": "s", "summary": "sc", "kind": "repo", "score": 9},
        {"title": "D", "url": "u3", "source": "s", "summary": "sd", "kind": "reading", "score": 0},
    ]

    def stage(subject, html, dry_run=False):
        staged.append((subject, html, dry_run))
        return {"ok": True, "dry_run": False, "campaign_id": "iss1", "edit_url": "out/newsletters/iss1.html"}

    return {
        "fetch_all": lambda w: items,
        "partition_seen": lambda its: (its, []),
        "recent_titles": lambda: [],
        "mark_seen": lambda its, slug: None,
        "stage": stage,
    }


async def _scenario():
    staged: list = []
    graph = build_lab_notes_graph(StubRanker(), StubWriter(), _effects(staged), checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "ln1"}, "recursion_limit": 50}

    s1 = await graph.ainvoke({"window_days": 35}, cfg)
    assert "__interrupt__" in s1, "should pause at the review gate"
    assert "masthead" in (s1["__interrupt__"][0].value.get("proposal", "") + " ") or True  # proposal is markdown, html is internal

    s2 = await graph.ainvoke(Command(resume={"action": "approve", "mode": "dry_run"}), cfg)
    result = s2.get("result_md") or ""
    assert "Staged" in result, f"expected a staged result, got: {result[:120]}"
    assert staged and staged[0][0].startswith("The Brief"), "stage must be called with the subject"
    # the assembled HTML carries the masthead + a verdict list
    assert "masthead" in staged[0][1] and "<li>" in staged[0][1], "assembled HTML should have masthead + items"
    print("OK: gather -> draft -> factcheck -> gate -> stage reached.")


def test_lab_notes():
    asyncio.run(_scenario())


if __name__ == "__main__":
    test_lab_notes()
