"""The GEO Auditor graph: a parallel fan-out / fan-in agent that probes AI answer
engines for citation share of YOUR site, then reasons over the gaps.

    START -> plan -> [ probe_openai | probe_anthropic | probe_gemini |
                       probe_perplexity | probe_brave | probe_you ] -> synthesize -> analyze -> END
                        (one branch per engine, all run in a single superstep)

`plan` announces which engines have keys. Each `probe_<engine>` node asks the fixed
query set against one engine concurrently (the blocking urllib calls run in a thread
so the branches really overlap) and writes its rows to the additive `results` channel.
`synthesize` is the fan-in: it reduces the rows into a per-engine citation table.
`analyze` (the model) reads that table and proposes GEO actions.

Pure factory: imports only its siblings plus langchain/langgraph. ALL network IO is
injected as `effects` (available/probe), so this runs with no keys (engines without a
key are skipped) and is importable from `langgraph dev` / Studio.

Live-graph convention: every intermediate node emits a *named* AIMessage whose name
EQUALS its node id (plan, probe_<engine>, synthesize, analyze). Many live graph views
highlight a node only on an exact node-id match. `analyze` emits its named step plus a
trailing unnamed AIMessage; that unnamed message is the final result.
"""
from __future__ import annotations

import asyncio
import operator
from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from .prompts import GEO_ANALYZE_SYSTEM, analyze_user


class GeoState(MessagesState):
    queries: list
    # Concurrent probe writes accumulate here (additive reducer), then synthesize reads.
    results: Annotated[list, operator.add]
    summary: dict


def _text(msg) -> str:
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else (b if isinstance(b, str) else "")
            for b in content
        ]
        return "\n".join(p for p in parts if p)
    return str(content)


def build_geo_graph(llm, effects: dict, checkpointer=None):
    """Compile the GEO Auditor graph.

    effects keys:
      engines        -> ordered tuple of engine names (drives the fan-out nodes)
      available(e)   -> bool, True when engine e has a key configured
      probe(e, q)    -> row dict (pure given the injected key; never raises).
                        Row keys used here: cited, brand_mentioned, competing_domains, status.
      target_domain  -> str, the domain you want cited (for the progress notes)
      brand_name     -> str, the brand/entity you want mentioned (for the notes)
    """
    engines = list(effects.get("engines") or ())
    target_domain = effects.get("target_domain") or "your site"
    brand_name = effects.get("brand_name") or "your brand"

    def plan(state: GeoState) -> dict:
        qs = state.get("queries") or []
        active = [e for e in engines if effects["available"](e)]
        skipped = [e for e in engines if not effects["available"](e)]
        text = (f"Probing {len(qs)} queries across {len(active)} engine(s) in parallel: "
                f"{', '.join(active) or 'none'}. Skipped (no key): {', '.join(skipped) or 'none'}.")
        return {"messages": [AIMessage(content=text, name="plan")]}

    def _make_probe(engine: str):
        async def probe_node(state: GeoState) -> dict:
            qs = state.get("queries") or []
            if not effects["available"](engine):
                note = f"{engine}: skipped, no API key configured."
                return {"messages": [AIMessage(content=note, name=f"probe_{engine}")],
                        "results": [{"engine": engine, "query": q, "status": "skipped"} for q in qs]}
            # urllib is blocking; run each query in a thread so the engine branches overlap.
            rows = list(await asyncio.gather(*(asyncio.to_thread(effects["probe"], engine, q) for q in qs)))
            cited = sum(1 for r in rows if r.get("cited"))
            mentioned = sum(1 for r in rows if r.get("brand_mentioned"))
            errors = sum(1 for r in rows if r.get("status") == "error")
            note = (f"{engine}: {len(rows)} queries, {cited} cited {target_domain}, "
                    f"{mentioned} mention {brand_name}, {errors} error(s).")
            return {"messages": [AIMessage(content=note, name=f"probe_{engine}")], "results": rows}

        return probe_node

    def synthesize(state: GeoState) -> dict:
        rows = state.get("results", [])
        by_engine: dict = {}
        for r in rows:
            e = r.get("engine", "?")
            d = by_engine.setdefault(e, {"probes": 0, "cited": 0, "mentioned": 0, "errors": 0,
                                         "skipped": 0, "_competing": set()})
            if r.get("status") == "skipped":
                d["skipped"] += 1
                continue
            d["probes"] += 1
            if r.get("status") == "error":
                d["errors"] += 1
            if r.get("cited"):
                d["cited"] += 1
            if r.get("brand_mentioned"):
                d["mentioned"] += 1
            for c in (r.get("competing_domains") or "").split(";"):
                if c:
                    d["_competing"].add(c)

        summary = {e: {"probes": d["probes"], "cited": d["cited"], "mentioned": d["mentioned"],
                       "errors": d["errors"], "skipped": d["skipped"],
                       "competing_domains": sorted(d["_competing"])}
                   for e, d in by_engine.items()}

        total_cited = sum(s["cited"] for s in summary.values())
        total_probed = sum(s["probes"] for s in summary.values())
        table = ["GEO citation probe complete.",
                 f"{total_cited} citation(s) of {target_domain} across {total_probed} live probe(s)."]
        for e, s in summary.items():
            table.append(f"- {e}: cited {s['cited']}, mentioned-brand {s['mentioned']}, "
                         f"errors {s['errors']}, skipped {s['skipped']} (of {len(state.get('queries') or [])})")
        return {"summary": summary, "messages": [AIMessage(content="\n".join(table), name="synthesize")]}

    async def analyze(state: GeoState) -> dict:
        summary = state.get("summary") or {}
        rows = state.get("results", [])
        if not summary:
            return {"messages": [AIMessage(content="No probe results to analyze.")]}
        ai = await llm.ainvoke([
            SystemMessage(content=GEO_ANALYZE_SYSTEM.format(target_domain=target_domain, brand_name=brand_name)),
            HumanMessage(content=analyze_user(summary, rows, state.get("queries"), target_domain, brand_name)),
        ])
        return {"messages": [
            AIMessage(content="Reasoned over the citation gaps; GEO actions below.", name="analyze"),
            AIMessage(content=_text(ai).strip()),
        ]}

    g = StateGraph(GeoState)
    g.add_node("plan", plan)
    # Node ids use '_' (':' is reserved). Each per-node AIMessage name equals its node id.
    for e in engines:
        g.add_node(f"probe_{e}", _make_probe(e))
    g.add_node("synthesize", synthesize)
    g.add_node("analyze", analyze)

    g.add_edge(START, "plan")
    for e in engines:                       # plan -> each probe: all run in one parallel superstep
        g.add_edge("plan", f"probe_{e}")
        g.add_edge(f"probe_{e}", "synthesize")   # each probe -> synthesize: fan-in barrier
    g.add_edge("synthesize", "analyze")
    g.add_edge("analyze", END)

    return g.compile(checkpointer=checkpointer)
