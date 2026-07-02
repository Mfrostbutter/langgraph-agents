"""The Blog Writer graph: mine a set of research sources, propose post ideas, pause for
a human to pick one, write the post, fact-check it against the sources, pause for
approval, and on a live approval publish it.

    START -> ingest -> ideate -> review_ideas[interrupt #1] -> prepare -> write ->
             factcheck -> (revise -> factcheck)* -> review_draft[interrupt #2] -> publish -> END

Pure factory: no app or service imports. Two injected models: `ideator` (cheap, proposes +
ranks ideas) and `writer` (quality, writes + fact-checks). ALL IO is the injected `effects`
map. Two interrupts; each interrupt value carries a `proposal` the runner streams to the
human. The bounded revise loop auto-fixes at most one round of high-severity fact-check flags.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from .prompts import (
    FACTCHECK_SYSTEM, IDEATE_SYSTEM, WRITE_SYSTEM,
    factcheck_user, ideate_user, revise_user, slugify, to_frontmatter, write_user,
)

MAX_REVISIONS = 1


class BlogWriterState(MessagesState):
    candidates: list          # fresh research sources
    recent_posts: list        # already-published (for dedup in ideation)
    ideas: list               # the 2-3 proposed ideas (dicts)
    chosen_idea: dict
    chosen_sources: list       # full source content for the chosen idea
    post: dict                 # {title, seoTitle, description, tags, body_md}
    flags: list
    revise_count: int
    idea_decision: dict
    draft_decision: dict
    result_md: str


# ── structured outputs ───────────────────────────────────────────────────────

class PostIdea(BaseModel):
    title: str = Field(description="Working title.")
    angle: str = Field(description="The angle in one or two sentences.")
    why_now: str = Field(default="", description="Why it is worth publishing now.")
    source_keys: list[str] = Field(default_factory=list, description="Source [key]s this draws on.")
    outline: list[str] = Field(default_factory=list, description="3-5 bullet outline.")


class Ideas(BaseModel):
    ideas: list[PostIdea] = Field(description="2-3 distinct post ideas.")


class Post(BaseModel):
    title: str
    seoTitle: str = Field(default="", description="<=60 chars, or empty if title already fits.")
    description: str = Field(description="One sentence, 120-160 chars.")
    tags: list[str] = Field(default_factory=list, description="4-7 lowercase topic tags.")
    body_md: str = Field(description="The Markdown body, no frontmatter, no H1 title line.")


class FactFlag(BaseModel):
    claim: str
    issue: str
    severity: str = Field(default="medium", description="high | medium | low")


class FactCheck(BaseModel):
    flags: list[FactFlag] = Field(default_factory=list)


def _ideas_md(ideas: list[dict]) -> str:
    out = ["## Proposed posts", "", "_Approve to write the first, or edit and submit the number "
           "(1-3) of the one you want. Reject to discard all._", ""]
    for i, idea in enumerate(ideas, 1):
        out.append(f"### {i}. {idea.get('title','')}")
        out.append(idea.get("angle", ""))
        if idea.get("why_now"):
            out.append(f"*Why now:* {idea['why_now']}")
        if idea.get("outline"):
            out.append("\n".join(f"- {b}" for b in idea["outline"]))
        out.append(f"_Sources: {', '.join(idea.get('source_keys', [])) or 'n/a'}_")
        out.append("")
    return "\n".join(out)


def _pick_index(decision: dict, n: int) -> int:
    """Resolve which idea the human chose. 'choice' wins; else a digit in 'edited'; else the top."""
    if not isinstance(decision, dict):
        return 0
    if isinstance(decision.get("choice"), int):
        return max(0, min(decision["choice"] - 1, n - 1))   # 1-based from the UI buttons
    edited = str(decision.get("edited") or "").strip()
    for tok in edited.split():
        if tok.isdigit():
            return max(0, min(int(tok) - 1, n - 1))
    return 0


def build_blog_writer_graph(ideator, writer, effects: dict, checkpointer=None):
    """ideator = cheap model (ideate); writer = quality model (write + factcheck).
    effects keys: fetch_all()->candidates, partition_sources(items)->(fresh,mined),
    recent_posts()->list, publish(post, source_keys, dry_run)->result."""

    def ingest(state: BlogWriterState) -> dict:
        items = effects["fetch_all"]()
        fresh, mined = effects["partition_sources"](items)
        pool = fresh or items  # if everything's been mined, allow reuse rather than stall
        recent = effects["recent_posts"]()
        note = (f"Read {len(items)} sources; {len(fresh)} not yet used in a post "
                f"({len(mined)} already mined). {len(recent)} posts already published.")
        return {"candidates": pool, "recent_posts": recent,
                "messages": [AIMessage(content=note, name="ingest")]}

    async def ideate(state: BlogWriterState) -> dict:
        cands = state["candidates"]
        if not cands:
            return {"ideas": [], "messages": [AIMessage(content="No sources to work from.", name="ideate")]}
        chooser = ideator.with_structured_output(Ideas)
        res: Ideas = await chooser.ainvoke([
            SystemMessage(content=IDEATE_SYSTEM),
            HumanMessage(content=ideate_user(cands, state.get("recent_posts") or [])),
        ])
        ideas = [i.model_dump() for i in res.ideas][:3]
        return {"ideas": ideas,
                "messages": [AIMessage(content=f"Proposed {len(ideas)} post idea(s).", name="ideate")]}

    def review_ideas(state: BlogWriterState) -> dict:
        ideas = state.get("ideas") or []
        if not ideas:
            return {"idea_decision": {"action": "reject"}}
        # `choices` -> the UI renders one approve button per idea (value is 1-based, read
        # by _pick_index). Approving a choice picks that idea; reject discards all.
        choices = [{"label": f"{i + 1}. {(idea.get('title') or 'Untitled')[:70]}", "value": i + 1}
                   for i, idea in enumerate(ideas)]
        decision = interrupt({"proposal": _ideas_md(ideas),
                              "subject": "Pick a post to write",
                              "choices": choices,
                              "modes": ["approve", "reject"]})
        return {"idea_decision": decision or {}}

    def prepare(state: BlogWriterState) -> dict:
        """Resolve the chosen idea + pull the full content of its cited sources."""
        ideas = state.get("ideas") or []
        d = state.get("idea_decision") or {}
        if (d.get("action") or "approve").lower() == "reject" or not ideas:
            return {"chosen_idea": {}, "chosen_sources": []}
        idea = ideas[_pick_index(d, len(ideas))]
        by_key = {c["key"]: c for c in state["candidates"]}
        chosen = [by_key[k] for k in idea.get("source_keys", []) if k in by_key]
        if not chosen:  # idea cited nothing resolvable; give the writer the top few sources
            chosen = state["candidates"][:3]
        return {"chosen_idea": idea, "chosen_sources": chosen,
                "messages": [AIMessage(content=f"Writing: {idea.get('title','')}", name="prepare")]}

    def route_after_ideas(state: BlogWriterState) -> str:
        d = state.get("idea_decision") or {}
        return "reject" if (d.get("action") or "approve").lower() == "reject" or not state.get("chosen_idea") else "write"

    async def write(state: BlogWriterState) -> dict:
        idea = state.get("chosen_idea") or {}
        sources = state.get("chosen_sources") or []
        composer = writer.with_structured_output(Post)
        post: Post = await composer.ainvoke([
            SystemMessage(content=WRITE_SYSTEM),
            HumanMessage(content=write_user(idea, sources, [p.get("title", "") for p in state.get("recent_posts") or []])),
        ])
        return {"post": post.model_dump(),
                "messages": [AIMessage(content=f"Drafted '{post.title}' ({len(post.body_md.split())} words).", name="write")]}

    async def factcheck(state: BlogWriterState) -> dict:
        post = state.get("post") or {}
        sources = state.get("chosen_sources") or []
        checker = writer.with_structured_output(FactCheck)
        try:
            fc: FactCheck = await checker.ainvoke([
                SystemMessage(content=FACTCHECK_SYSTEM),
                HumanMessage(content=factcheck_user(post.get("body_md", ""), sources)),
            ])
            flags = [f.model_dump() for f in fc.flags]
        except Exception:
            flags = []  # never block the pipeline on a checker failure
        note = (f"Fact-check flagged {len(flags)} claim(s)." if flags
                else "Fact-check passed; claims grounded in the sources.")
        return {"flags": flags, "messages": [AIMessage(content=note, name="factcheck")]}

    def route_factcheck(state: BlogWriterState) -> str:
        high = [f for f in (state.get("flags") or []) if str(f.get("severity", "")).lower() == "high"]
        return "revise" if high and state.get("revise_count", 0) < MAX_REVISIONS else "review_draft"

    async def revise(state: BlogWriterState) -> dict:
        post = state.get("post") or {}
        flags = state.get("flags") or []
        composer = writer.with_structured_output(Post)
        revised: Post = await composer.ainvoke([
            SystemMessage(content=WRITE_SYSTEM),
            HumanMessage(content=revise_user(post, flags, state.get("chosen_sources") or [])),
        ])
        n_high = len([f for f in flags if str(f.get("severity", "")).lower() == "high"])
        return {"post": revised.model_dump(), "revise_count": state.get("revise_count", 0) + 1,
                "messages": [AIMessage(content=f"Revised to fix {n_high} high-severity flag(s).", name="revise")]}

    def review_draft(state: BlogWriterState) -> dict:
        post = state.get("post") or {}
        flags = state.get("flags") or []
        preview = to_frontmatter({**post, "draft": True}, "(set on publish)")
        banner = ""
        if flags:
            banner = f"## Fact-check: {len(flags)} claim(s) to verify\n\n" + "".join(
                f"- **[{f.get('severity','?')}]** {f.get('claim','')}\n  _{f.get('issue','')}_\n" for f in flags) + "\n---\n\n"
        proposal = (banner + "_Approve with mode='live' to publish now, or mode='dry_run' (default) "
                    "to stage a draft. Edit to tweak, reject to discard._\n\n```markdown\n"
                    + preview + "\n```")
        decision = interrupt({"proposal": proposal, "subject": post.get("title", "Draft post"),
                              "flags": flags, "modes": ["approve", "edit", "reject"]})
        return {"draft_decision": decision or {}}

    def publish(state: BlogWriterState) -> dict:
        post = state.get("post") or {}
        if not post:  # idea stage was rejected — never reached the draft gate
            return {"result_md": "## Rejected\n\nNo idea was chosen. Nothing was written or published.",
                    "messages": [AIMessage(content="## Rejected at the idea stage. Nothing written.")]}
        d = state.get("draft_decision") or {}
        action = (d.get("action") or "approve").lower()
        if action == "reject":
            return {"result_md": "## Rejected\n\nThe post was rejected. Nothing was published.",
                    "messages": [AIMessage(content="## Rejected\n\nNothing published.")]}
        # apply a full-text edit if the human supplied one
        edited = (d.get("edited") or "").strip()
        if edited and len(edited) > 200:  # a real body edit, not an idea-pick token
            post = {**post, "body_md": edited}
        live = (d.get("mode") or "dry_run").lower() == "live"
        source_keys = [s["key"] for s in state.get("chosen_sources") or []]
        res = effects["publish"](post, source_keys, dry_run=not live)
        if not res.get("ok"):
            body = f"## Publish failed\n\n{res.get('error','unknown error')}\n\nThe draft file may still be staged."
            return {"result_md": body, "messages": [AIMessage(content=body)]}
        if res.get("dry_run"):
            body = (f"## Staged (dry run)\n\nWrote **{res['slug']}.md** as a draft at `{res['path']}`. "
                    f"{res.get('note','')}")
        else:
            body = (f"## Published\n\n**{post.get('title','')}** is live at `{res.get('path','')}`. "
                    f"{res.get('url','')}\n\n_{res.get('note','')}_\n\n"
                    f"_Slug: `{slugify(post.get('title',''))}` (add a hero image here if your theme uses one)._")
        return {"result_md": body, "messages": [AIMessage(content=body)]}

    g = StateGraph(BlogWriterState)
    g.add_node("ingest", ingest)
    g.add_node("ideate", ideate)
    g.add_node("review_ideas", review_ideas)
    g.add_node("prepare", prepare)
    g.add_node("write", write)
    g.add_node("factcheck", factcheck)
    g.add_node("revise", revise)
    g.add_node("review_draft", review_draft)
    g.add_node("publish", publish)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "ideate")
    g.add_edge("ideate", "review_ideas")
    g.add_edge("review_ideas", "prepare")
    g.add_conditional_edges("prepare", route_after_ideas, {"write": "write", "reject": "publish"})
    g.add_edge("write", "factcheck")
    g.add_conditional_edges("factcheck", route_factcheck, {"revise": "revise", "review_draft": "review_draft"})
    g.add_edge("revise", "factcheck")
    g.add_edge("review_draft", "publish")
    g.add_edge("publish", END)

    return g.compile(checkpointer=checkpointer)
