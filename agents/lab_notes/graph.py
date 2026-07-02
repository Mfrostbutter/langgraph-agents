"""The Lab Notes graph: gather AI signal, draft a monthly newsletter issue in a
verdict voice, fact-check it against the sources, pause for human approval, and on
approve stage an email DRAFT (never send).

    START -> ingest -> select -> write -> assemble -> factcheck ->
             (revise -> assemble)* -> review[interrupt] -> stage -> END

Pure factory (no app/service imports). ALL IO is the injected `effects` map (source
fetch, dedup, staging), so it runs from `langgraph dev` / Studio. Two models: `ranker`
(cheap, does SELECT) and `writer` (quality, does WRITE + fact-check). One interrupt; the
runner streams named AIMessages as progress and the final unnamed message as the result.

Newsletter branding (masthead title, tagline, signup + signoff HTML) is read from the
effects map so nothing brand-specific lives in the graph.
"""
from __future__ import annotations

import datetime
from typing import Sequence  # noqa: F401  (kept for parity / type hints in forks)

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from .prompts import (
    FACTCHECK_SYSTEM, NEWSLETTER_NAME, SELECT_SYSTEM, WRITE_SYSTEM,
    factcheck_user, revise_user, select_user, write_user,
)

MAX_REVISIONS = 1


class LabNotesState(MessagesState):
    window_days: int
    candidates: list
    modules: dict
    issue: dict
    subject: str
    draft_md: str
    draft_html: str
    issue_slug: str
    flags: list
    revise_count: int
    decision: dict
    result_md: str


# ── Structured outputs ───────────────────────────────────────────────────────

class Selection(BaseModel):
    one_thing: int = Field(description="Index of the single most important item.")
    tools: list[int] = Field(default_factory=list, description="2-4 indices for Tools worth a look.")
    repos: list[int] = Field(default_factory=list, description="2-3 indices for Trending repos.")
    reading: list[int] = Field(default_factory=list, description="3-4 indices for Worth reading.")


class Verdict(BaseModel):
    index: int = Field(description="Candidate index this verdict is about.")
    line: str = Field(description="The verdict, one or two sentences. No title; it is added for you.")


class Issue(BaseModel):
    subject: str
    intro_md: str
    one_thing_md: str
    tools: list[Verdict] = Field(default_factory=list)
    repos: list[Verdict] = Field(default_factory=list)
    reading: list[Verdict] = Field(default_factory=list)
    bench_md: str = ""
    steal_md: str = ""


class FactFlag(BaseModel):
    claim: str = Field(description="The exact claim in the draft that is questionable.")
    issue: str = Field(description="One line: why (unsupported, contradicts a source, sources disagree).")
    severity: str = Field(default="medium", description="high | medium | low")


class FactCheck(BaseModel):
    flags: list[FactFlag] = Field(default_factory=list)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _paras(md: str) -> str:
    """Blank-line-separated text -> <p> blocks; bold a leading 'The move:' / 'The signal:' label."""
    out = []
    for chunk in (md or "").strip().split("\n\n"):
        chunk = chunk.strip().replace("\n", " ")
        if not chunk:
            continue
        chunk = _esc(chunk)
        for label in ("The move:", "The signal:"):
            if chunk.startswith(label):
                chunk = f"<strong>{label}</strong>" + chunk[len(label):]
        out.append(f"<p>{chunk}</p>")
    return "\n".join(out)


def _verdict_list(verdicts: list[dict], candidates: list[dict]) -> str:
    rows = []
    for v in verdicts:
        i = v.get("index", -1)
        if not (0 <= i < len(candidates)):
            continue
        it = candidates[i]
        rows.append(f'  <li><strong><a href="{_esc(it.get("url",""))}">{_esc(it.get("title",""))}</a>.'
                    f'</strong> <em>{_esc(v.get("line",""))}</em></li>')
    return "<ul>\n" + "\n".join(rows) + "\n</ul>" if rows else ""


def _md_to_text(md: str) -> str:
    return " ".join((md or "").split())


def build_lab_notes_graph(ranker, writer, effects: dict, checkpointer=None):
    """ranker = cheap model (SELECT); writer = quality model (WRITE + factcheck).
    effects keys: fetch_all(window_days)->items, partition_seen(items)->(fresh,seen),
    recent_titles()->list[str], mark_seen(items, used_issue), stage(subject, html, dry_run)->dict.
    Optional branding keys: newsletter_title, newsletter_tagline, signup_html, signoff_html."""

    masthead_title = effects.get("newsletter_title") or NEWSLETTER_NAME.upper()
    tagline = effects.get("newsletter_tagline") or "What's worth your attention in AI, filtered by what survives production."
    signup_html = effects.get("signup_html") or ""
    signoff_html = effects.get("signoff_html") or ""

    async def ingest(state: LabNotesState) -> dict:
        window = int(state.get("window_days") or 35)
        items = effects["fetch_all"](window)
        fresh, seen = effects["partition_seen"](items)
        note = (f"Gathered {len(items)} candidates from the last {window} days; "
                f"{len(fresh)} fresh after dedup ({len(seen)} already covered).")
        return {"candidates": fresh, "messages": [AIMessage(content=note, name="ingest")]}

    async def select(state: LabNotesState) -> dict:
        cands = state["candidates"]
        if not cands:
            return {"modules": {}, "messages": [AIMessage(content="No fresh candidates to work with.", name="select")]}
        chooser = ranker.with_structured_output(Selection)
        sel: Selection = await chooser.ainvoke([
            SystemMessage(content=SELECT_SYSTEM),
            HumanMessage(content=select_user(cands)),
        ])
        n = len(cands)
        clip = lambda xs: [i for i in xs if 0 <= i < n]  # noqa: E731
        modules = {"one_thing": clip([sel.one_thing]), "tools": clip(sel.tools)[:4],
                   "repos": clip(sel.repos)[:3], "reading": clip(sel.reading)[:4]}
        picked = sum(len(v) for v in modules.values())
        return {"modules": modules,
                "messages": [AIMessage(content=f"Selected {picked} items across 4 modules.", name="select")]}

    async def write(state: LabNotesState) -> dict:
        cands = state["candidates"]
        modules = state.get("modules") or {}
        try:
            recent = effects["recent_titles"]()
        except Exception:
            recent = []
        composer = writer.with_structured_output(Issue)
        issue: Issue = await composer.ainvoke([
            SystemMessage(content=WRITE_SYSTEM),
            HumanMessage(content=write_user(modules, cands, recent)),
        ])
        return {"issue": issue.model_dump(), "subject": issue.subject,
                "messages": [AIMessage(content="Drafted the issue (one-thing, tools, repos, reading, bench, steal).", name="write")]}

    def assemble(state: LabNotesState) -> dict:
        cands = state["candidates"]
        issue = state.get("issue") or {}
        slug = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m") + "-auto"
        subject = (issue.get("subject") or NEWSLETTER_NAME).strip()

        html = [f'<div class="masthead"><div class="t">{_esc(masthead_title)}</div>'
                f'<div class="s">{_esc(tagline)}</div></div>',
                _paras(issue.get("intro_md", "")),
                '<div class="mod">The one thing</div>', _paras(issue.get("one_thing_md", ""))]
        if issue.get("tools"):
            html += ['<div class="mod">Tools worth a look</div>', _verdict_list(issue["tools"], cands)]
        if issue.get("repos"):
            html += ['<div class="mod">Trending repos</div>', _verdict_list(issue["repos"], cands)]
        if issue.get("bench_md"):
            html += ['<div class="mod">From the bench</div>', _paras(issue["bench_md"])]
        if issue.get("reading"):
            html += ['<div class="mod">Worth reading</div>', _verdict_list(issue["reading"], cands)]
        if issue.get("steal_md"):
            html += ['<div class="mod">Steal this</div>', f"<blockquote>{_esc(_md_to_text(issue['steal_md']))}</blockquote>"]
        html.append('<hr class="divider">')
        if signup_html:
            html.append(signup_html)
        if signoff_html:
            html.append(signoff_html)
        draft_html = "\n".join(h for h in html if h)

        def md_verdicts(key, label):
            vs = issue.get(key) or []
            if not vs:
                return ""
            lines = [f"### {label}"]
            for v in vs:
                i = v.get("index", -1)
                if 0 <= i < len(cands):
                    lines.append(f"- **{cands[i].get('title','')}**: {v.get('line','')}\n  {cands[i].get('url','')}")
            return "\n".join(lines)

        md = [f"# {subject}", "", issue.get("intro_md", ""), "",
              "## The one thing", issue.get("one_thing_md", ""),
              md_verdicts("tools", "Tools worth a look"), md_verdicts("repos", "Trending repos"),
              ("## From the bench\n" + issue["bench_md"]) if issue.get("bench_md") else "",
              md_verdicts("reading", "Worth reading"),
              ("## Steal this\n" + issue["steal_md"]) if issue.get("steal_md") else ""]
        draft_md = "\n\n".join(m for m in md if m).strip()

        return {"subject": subject, "issue_slug": slug, "draft_html": draft_html, "draft_md": draft_md,
                "messages": [AIMessage(content=f"Assembled issue '{subject}'. Fact-checking.", name="assemble")]}

    def _sources_for_check(state: LabNotesState) -> str:
        cands = state["candidates"]
        used = sorted({i for idxs in (state.get("modules") or {}).values() for i in idxs})
        return "\n".join(
            f"[{i}] ({cands[i].get('source','')}) {cands[i].get('title','')} :: "
            f"{cands[i].get('summary','') or '(no summary)'} :: {cands[i].get('url','')}"
            for i in used if 0 <= i < len(cands))

    def _claims_text(issue: dict, cands: list) -> str:
        parts = [issue.get("intro_md", ""), "ONE THING: " + issue.get("one_thing_md", ""),
                 "BENCH: " + issue.get("bench_md", ""), "STEAL: " + issue.get("steal_md", "")]
        for key in ("tools", "repos", "reading"):
            for v in issue.get(key) or []:
                i = v.get("index", -1)
                t = cands[i].get("title", "") if 0 <= i < len(cands) else ""
                parts.append(f"{key.upper()} [{t}]: {v.get('line','')}")
        return "\n".join(p for p in parts if p.strip())

    async def factcheck(state: LabNotesState) -> dict:
        issue = state.get("issue") or {}
        cands = state["candidates"]
        checker = writer.with_structured_output(FactCheck)
        try:
            fc: FactCheck = await checker.ainvoke([
                SystemMessage(content=FACTCHECK_SYSTEM),
                HumanMessage(content=factcheck_user(_claims_text(issue, cands), _sources_for_check(state))),
            ])
            flags = [f.model_dump() for f in fc.flags]
        except Exception:
            flags = []  # never block the pipeline on a checker failure
        note = (f"Fact-check flagged {len(flags)} claim(s) to verify."
                if flags else "Fact-check passed; claims grounded in the sources.")
        return {"flags": flags, "messages": [AIMessage(content=note, name="factcheck")]}

    def route_factcheck(state: LabNotesState) -> str:
        high = [f for f in (state.get("flags") or []) if str(f.get("severity", "")).lower() == "high"]
        return "revise" if high and state.get("revise_count", 0) < MAX_REVISIONS else "review"

    async def revise(state: LabNotesState) -> dict:
        issue = state.get("issue") or {}
        flags = state.get("flags") or []
        cands = state["candidates"]
        composer = writer.with_structured_output(Issue)
        revised: Issue = await composer.ainvoke([
            SystemMessage(content=WRITE_SYSTEM),
            HumanMessage(content=revise_user(issue, flags, cands, state.get("modules") or {})),
        ])
        n_high = len([f for f in flags if str(f.get("severity", "")).lower() == "high"])
        return {"issue": revised.model_dump(), "subject": revised.subject,
                "revise_count": state.get("revise_count", 0) + 1,
                "messages": [AIMessage(content=f"Revised to fix {n_high} high-severity flag(s).", name="revise")]}

    def review(state: LabNotesState) -> dict:
        """HALT for human approval. Bake any remaining fact-check flags into the proposal."""
        flags = state.get("flags") or []
        draft = state.get("draft_md", "")
        if flags:
            banner = f"## Fact-check: {len(flags)} claim(s) to verify before sending\n\n"
            for f in flags:
                banner += f"- **[{f.get('severity','?')}]** {f.get('claim','')}\n  _{f.get('issue','')}_\n"
            proposal = banner + "\n---\n\n" + draft
        else:
            proposal = "## Fact-check passed (claims grounded in the sources)\n\n---\n\n" + draft
        decision = interrupt({"proposal": proposal, "subject": state.get("subject", ""),
                              "flags": flags, "modes": ["approve", "edit", "reject"]})
        return {"decision": decision or {}}

    async def stage(state: LabNotesState) -> dict:
        d = state.get("decision") or {}
        action = (d.get("action") or "approve").lower()
        subject = state.get("subject", NEWSLETTER_NAME)
        slug = state.get("issue_slug", "")

        if action == "reject":
            return {"result_md": "## Rejected\n\nThe issue was rejected. Nothing was staged.",
                    "messages": [AIMessage(content="## Rejected\n\nNothing staged.")]}

        edited = (d.get("edited") or "").strip()
        edit_note = ("\n\n_You submitted edits. The draft was staged as written; apply your edits in "
                     "your email tool's editor before sending._") if edited else ""

        res = effects["stage"](subject, state.get("draft_html", ""), dry_run=False)
        if not res.get("ok"):
            return {"result_md": f"## Staging failed\n\n{res.get('error','unknown error')}",
                    "messages": [AIMessage(content=f"## Staging failed\n\n{res.get('error','unknown error')}")]}

        # Record what shipped so future issues do not repeat it.
        try:
            cands = state["candidates"]
            mod_of = {i: name for name, idxs in (state.get("modules") or {}).items() for i in idxs}
            shipped = [{**cands[i], "module": name} for i, name in mod_of.items() if 0 <= i < len(cands)]
            if shipped and slug:
                effects["mark_seen"](shipped, slug)
        except Exception:
            pass

        if res.get("dry_run"):
            body = (f"## Dry run, nothing staged\n\nWould have staged a draft for **{subject}** "
                    f"({(res.get('would') or {}).get('body_bytes','?')} bytes).")
        else:
            url = res.get("edit_url", "")
            body = (f"## Staged\n\nWrote a DRAFT of **{subject}** at `{url}`. Review and send it from "
                    f"your email tool.\n\n_The agent never sends; you do._{edit_note}")
        return {"result_md": body, "messages": [AIMessage(content=body)]}

    g = StateGraph(LabNotesState)
    for name, fn in (("ingest", ingest), ("select", select), ("write", write), ("assemble", assemble),
                     ("factcheck", factcheck), ("revise", revise), ("review", review), ("stage", stage)):
        g.add_node(name, fn)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "select")
    g.add_edge("select", "write")
    g.add_edge("write", "assemble")
    g.add_edge("assemble", "factcheck")
    g.add_conditional_edges("factcheck", route_factcheck, {"revise": "revise", "review": "review"})
    g.add_edge("revise", "assemble")
    g.add_edge("review", "stage")
    g.add_edge("stage", END)

    return g.compile(checkpointer=checkpointer)
