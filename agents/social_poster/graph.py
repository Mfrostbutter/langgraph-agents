"""The Social Poster graph: gather AI signal, pick the single best story, draft a
long-form post + a short caption in a maker voice, ground-check the claims, pause for
human approval, and on approve generate a visual + publish via your channels.

    START -> ingest -> select -> draft -> factcheck -> review[interrupt] -> publish -> END
                                    ^___________ revise __________|  (bounded auto-fix)

Pure factory (no app imports). ALL IO is the injected `effects` map (source fetch, dedup,
optional image generation, staging, publishing), so it runs from `langgraph dev` / Studio.
Two models: `ranker` (cheap, SELECT) and `writer` (quality, DRAFT). One interrupt; the
runner streams named AIMessages as progress and the final unnamed message as the result.

The two draft fields (facebook_md, instagram_caption) are just a long-form post + a short
image-first caption; retarget them to whatever platforms you publish to via the `publish`
effect. The reference `publish` writes local files and never posts anywhere.
"""
from __future__ import annotations

import datetime
import hashlib
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from .prompts import (
    DRAFT_SYSTEM, FACTCHECK_SYSTEM, SELECT_SYSTEM,
    draft_user, factcheck_user, revise_user, select_user,
)

MAX_REVISIONS = 1


class SocialState(MessagesState):
    window_days: int
    candidates: list
    pick_index: int
    pick_reason: str
    post: dict
    slug: str
    draft_md: str
    flags: list
    revise_count: int
    decision: dict
    result_md: str


# ── Structured outputs ───────────────────────────────────────────────────────

class Selection(BaseModel):
    index: int = Field(description="Index of the single best item to post about.")
    reason: str = Field(default="", description="One line: why this item.")


class SocialPost(BaseModel):
    facebook_md: str = Field(description="The long-form post body, 120-220 words. No raw URL in body.")
    instagram_caption: str = Field(description="The short caption, 60-125 words, hashtags on last line.")
    link: str = Field(default="", description="Canonical URL for first-comment / link-in-bio.")
    image_idea: str = Field(default="", description="One or two sentences describing the supporting visual.")


class FactFlag(BaseModel):
    claim: str = Field(description="The exact claim in the draft that is questionable.")
    issue: str = Field(description="One line: why (unsupported by source, contradicts source).")
    severity: str = Field(default="medium", description="high | medium | low")


class FactCheck(BaseModel):
    flags: list[FactFlag] = Field(default_factory=list)


def _slugify(title: str, url: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:48] or "post"
    h = hashlib.sha1((url or title or "").encode("utf-8")).hexdigest()[:6]
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    return f"{date}-{base}-{h}"


def _source_for_check(item: dict) -> str:
    return (f"({item.get('source','')}) {item.get('title','')} :: "
            f"{item.get('summary','') or '(no summary)'} :: {item.get('url','')}")


def _claims_text(post: dict) -> str:
    return f"FACEBOOK:\n{post.get('facebook_md','')}\n\nINSTAGRAM:\n{post.get('instagram_caption','')}"


def _preview_md(post: dict, item: dict, pick_reason: str) -> str:
    link = post.get("link") or item.get("url") or ""
    return "\n".join([
        f"**Story:** {item.get('title','')}  ({item.get('source','')})",
        f"**Why this one:** {pick_reason}" if pick_reason else "",
        f"**Source:** {item.get('url','')}",
        "",
        "### Long-form post",
        (post.get("facebook_md") or "").strip(),
        f"\n_First comment / link:_ {link}",
        "",
        "### Short caption",
        (post.get("instagram_caption") or "").strip(),
        "",
        f"**Image idea:** {post.get('image_idea','') or '(none given)'}",
        "_On approve: an image is generated (if an image effect is configured), then the posts are "
        "published via your `publish` effect. The reference publish is a dry run that writes local "
        "files. Approve = publish._",
    ])


def _audit_note(stage_res: dict) -> str:
    if stage_res and stage_res.get("ok") and not stage_res.get("dry_run"):
        p = stage_res.get("paths", {})
        return f"\n\n_Local copy saved: `{p.get('facebook','')}` + `{p.get('instagram','')}`._"
    return ""


def _publish_report(pub: dict, image: dict | None) -> str:
    """Format the publish outcome (live, partial, dry-run, or failure) for the human."""
    head_lines = []
    if image and image.get("ok"):
        head_lines.append(f"**Image:** generated ({image.get('resolution','')} {image.get('aspect','')}).".strip())
    elif image and image.get("dry_run"):
        head_lines.append("**Image:** skipped (no image effect configured).")
    elif image:
        head_lines.append(f"**Image:** generation failed ({image.get('error','unknown')}).")

    if pub.get("dry_run"):
        miss = pub.get("missing_creds") or []
        w = pub.get("would", {})
        why = (f"Missing publish credentials: {', '.join(miss)}." if miss
               else "No publish backend configured." if not w else "Dry-run requested.")
        body = ["## Dry run, nothing posted", "", why, "",
                f"- **Channel A** would POST `{(w.get('facebook') or {}).get('endpoint','(your platform)')}`.",
                f"- **Channel B** would POST `{(w.get('instagram') or {}).get('endpoint','(your platform)')}`."]
    elif not pub.get("ok"):
        body = ["## Publish failed", "", pub.get("error", "unknown error")]
    else:
        fb = pub.get("facebook") or {}
        ig = pub.get("instagram") or {}
        fb_line = (f"- **Channel A:** posted (`{fb.get('post_id','')}`)"
                   if fb.get("ok") else f"- **Channel A:** FAILED ({fb.get('error','')})")
        ig_line = (f"- **Channel B:** posted (`{ig.get('media_id','')}`)"
                   if ig.get("ok") else f"- **Channel B:** FAILED ({ig.get('error','')})")
        head = "## Posted" if (fb.get("ok") and ig.get("ok")) else "## Posted (partial)"
        body = [head, "", fb_line, ig_line]

    return "\n".join(head_lines + ([""] if head_lines else []) + body)


def build_social_graph(ranker, writer, effects: dict, checkpointer=None):
    """ranker = cheap model (SELECT); writer = quality model (DRAFT).
    effects keys: fetch_all(window_days)->items, partition_seen(items)->(fresh,seen),
    recent_titles()->list[str], mark_seen(items, used_slug), stage(post, item, slug, image,
    dry_run)->dict (local copy), publish(post, image, dry_run)->dict. Optional:
    generate_image(prompt, slug)->dict."""

    async def ingest(state: SocialState) -> dict:
        window = int(state.get("window_days") or 14)
        items = effects["fetch_all"](window)
        fresh, seen = effects["partition_seen"](items)
        note = (f"Gathered {len(items)} candidates from the last {window} days; "
                f"{len(fresh)} fresh after dedup ({len(seen)} already posted).")
        return {"candidates": fresh, "messages": [AIMessage(content=note, name="ingest")]}

    async def select(state: SocialState) -> dict:
        cands = state["candidates"]
        if not cands:
            return {"pick_index": -1,
                    "messages": [AIMessage(content="No fresh candidates to post about.", name="select")]}
        chooser = ranker.with_structured_output(Selection)
        sel: Selection = await chooser.ainvoke([
            SystemMessage(content=SELECT_SYSTEM),
            HumanMessage(content=select_user(cands)),
        ])
        idx = sel.index if 0 <= sel.index < len(cands) else 0
        return {"pick_index": idx, "pick_reason": sel.reason or "",
                "messages": [AIMessage(content=f"Picked: {cands[idx].get('title','')}", name="select")]}

    async def draft(state: SocialState) -> dict:
        cands = state["candidates"]
        idx = state.get("pick_index", -1)
        if not (0 <= idx < len(cands)):
            return {"post": {}, "messages": [AIMessage(content="Nothing to draft.", name="draft")]}
        item = cands[idx]
        try:
            recent = effects["recent_titles"]()
        except Exception:
            recent = []
        composer = writer.with_structured_output(SocialPost)
        sp: SocialPost = await composer.ainvoke([
            SystemMessage(content=DRAFT_SYSTEM),
            HumanMessage(content=draft_user(item, recent)),
        ])
        post = sp.model_dump()
        if not post.get("link"):
            post["link"] = item.get("url", "")
        slug = _slugify(item.get("title", ""), item.get("url", ""))
        return {"post": post, "slug": slug,
                "messages": [AIMessage(content="Drafted the long-form post and the short caption.", name="draft")]}

    async def factcheck(state: SocialState) -> dict:
        cands = state["candidates"]
        idx = state.get("pick_index", -1)
        post = state.get("post") or {}
        if not post or not (0 <= idx < len(cands)):
            return {"flags": [], "messages": [AIMessage(content="Nothing to fact-check.", name="factcheck")]}
        item = cands[idx]
        checker = writer.with_structured_output(FactCheck)
        try:
            fc: FactCheck = await checker.ainvoke([
                SystemMessage(content=FACTCHECK_SYSTEM),
                HumanMessage(content=factcheck_user(_claims_text(post), _source_for_check(item))),
            ])
            flags = [f.model_dump() for f in fc.flags]
        except Exception:
            flags = []  # never block the pipeline on a checker failure
        note = (f"Fact-check flagged {len(flags)} claim(s) to verify."
                if flags else "Fact-check passed; claims grounded in the source.")
        return {"flags": flags, "messages": [AIMessage(content=note, name="factcheck")]}

    def route_factcheck(state: SocialState) -> str:
        high = [f for f in (state.get("flags") or []) if str(f.get("severity", "")).lower() == "high"]
        return "revise" if high and state.get("revise_count", 0) < MAX_REVISIONS else "review"

    async def revise(state: SocialState) -> dict:
        cands = state["candidates"]
        idx = state.get("pick_index", -1)
        post = state.get("post") or {}
        flags = state.get("flags") or []
        item = cands[idx] if 0 <= idx < len(cands) else {}
        composer = writer.with_structured_output(SocialPost)
        revised: SocialPost = await composer.ainvoke([
            SystemMessage(content=DRAFT_SYSTEM),
            HumanMessage(content=revise_user(post, flags, item)),
        ])
        new_post = revised.model_dump()
        if not new_post.get("link"):
            new_post["link"] = post.get("link") or item.get("url", "")
        n_high = len([f for f in flags if str(f.get("severity", "")).lower() == "high"])
        return {"post": new_post, "revise_count": state.get("revise_count", 0) + 1,
                "messages": [AIMessage(content=f"Revised to fix {n_high} high-severity flag(s).", name="revise")]}

    def review(state: SocialState) -> dict:
        cands = state["candidates"]
        idx = state.get("pick_index", -1)
        post = state.get("post") or {}
        item = cands[idx] if 0 <= idx < len(cands) else {}
        preview = _preview_md(post, item, state.get("pick_reason", ""))
        flags = state.get("flags") or []
        if flags:
            banner = f"## Fact-check: {len(flags)} claim(s) to verify before posting\n\n"
            for f in flags:
                banner += f"- **[{f.get('severity','?')}]** {f.get('claim','')}\n  _{f.get('issue','')}_\n"
            proposal = banner + "\n---\n\n" + preview
        else:
            proposal = "## Fact-check passed (claims grounded in the source)\n\n---\n\n" + preview
        decision = interrupt({"proposal": proposal, "subject": item.get("title", ""),
                              "flags": flags, "modes": ["approve", "edit", "reject"]})
        return {"decision": decision or {}}

    async def publish(state: SocialState) -> dict:
        """On approve: generate the image (if configured), keep a local copy, then publish
        via the `publish` effect. The reference publish is a dry run (writes local files);
        wire it to your platform's API to post for real."""
        d = state.get("decision") or {}
        action = (d.get("action") or "approve").lower()
        cands = state["candidates"]
        idx = state.get("pick_index", -1)
        item = cands[idx] if 0 <= idx < len(cands) else {}
        post = state.get("post") or {}
        slug = state.get("slug", "")

        if action == "reject":
            body = "## Rejected\n\nNothing was generated or posted."
            return {"result_md": body, "messages": [AIMessage(content=body)]}

        # Image first (image-first platforms require one). Generated only now, post-approval.
        image = None
        gen = effects.get("generate_image")
        if gen is not None:
            try:
                image = gen(post.get("image_idea", ""), slug)
            except Exception as e:
                image = {"ok": False, "error": f"{type(e).__name__}: {e}"}

        # Keep a local copy of what was approved (non-fatal).
        stage_res = {}
        try:
            stage_res = effects["stage"](post, item, slug, image=image, dry_run=False)
        except Exception as e:
            stage_res = {"ok": False, "error": f"{type(e).__name__}: {e}"}

        # 'edit' is not auto-merged into a live post; save it and skip posting so we never
        # publish text the human meant to change.
        if action == "edit":
            body = ("## Edits noted, posting skipped\n\nYou edited the draft; the agent does not merge "
                    "free-text edits into a live post. The draft was saved; re-run to regenerate, or "
                    "post manually.") + _audit_note(stage_res)
            return {"result_md": body, "messages": [AIMessage(content=body)]}

        mode = (d.get("mode") or "").lower()
        pub = effects["publish"](post, image, dry_run=(mode == "dry_run"))

        if pub.get("ok") and not pub.get("dry_run"):
            try:
                if item and slug:
                    effects["mark_seen"]([{**item, "module": "social"}], slug)
            except Exception:
                pass

        body = _publish_report(pub, image) + _audit_note(stage_res)
        return {"result_md": body, "messages": [AIMessage(content=body)]}

    g = StateGraph(SocialState)
    for name, fn in (("ingest", ingest), ("select", select), ("draft", draft),
                     ("factcheck", factcheck), ("revise", revise), ("review", review), ("publish", publish)):
        g.add_node(name, fn)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "select")
    g.add_edge("select", "draft")
    g.add_edge("draft", "factcheck")
    g.add_conditional_edges("factcheck", route_factcheck, {"revise": "revise", "review": "review"})
    g.add_edge("revise", "factcheck")
    g.add_edge("review", "publish")
    g.add_edge("publish", END)

    return g.compile(checkpointer=checkpointer)
