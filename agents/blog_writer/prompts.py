"""Prompts + small formatting helpers for the Blog Writer, kept out of the graph so
they can be versioned and tested on their own.

CUSTOMIZE `AUTHOR_VOICE` (or set the BLOG_AUTHOR_VOICE env var) for your own writer
or brand. The default casts the author as a CURATOR / commentator on other people's
ideas (talks, studies, articles) who adds their own read, NOT someone recounting work
they personally did. The honesty rules below are the whole point of this agent: the
`factcheck` node grades the draft against the sources so the model cannot fabricate a
first-person experience or misattribute a finding.
"""
from __future__ import annotations

import os
import re

# ── The one thing worth customizing: who is writing, in what voice. ───────────
AUTHOR_VOICE = os.environ.get("BLOG_AUTHOR_VOICE") or (
    "Voice and rules (non-negotiable):\n"
    "- The author is a CURATOR and commentator. They HIGHLIGHT an idea or practice worth "
    "attention from the research (conference talks, studies, other people's work) and add their "
    "own read on it. They are NOT recounting work they personally did.\n"
    "- CRITICAL HONESTY RULE: never fabricate a first-person experience. No invented anecdote, "
    "project, metric, codebase, client, demo, or event. Do not write 'I shipped a 2,000-line PR' "
    "or 'I tested this on a 300k-line repo' unless that is literally the author's and present in "
    "the inputs. Every concrete example, story, number, and finding comes FROM the sources and "
    "must be ATTRIBUTED to whoever it belongs to (the speaker, the study, the team), e.g. 'the "
    "Stanford study found', 'the speaker argued at the 2025 conference'.\n"
    "- First person is for the author's ANALYSIS and OPINION only ('I think', 'my read is', "
    "'what strikes me here'), never for invented experience.\n"
    "- Write for a semi-technical reader: works in tech, not a deep engineer. Explain the why.\n"
    "- Ground every concrete claim in the provided sources. Do not invent facts not present there.\n"
)

IDEATE_SYSTEM = (
    "You propose blog post ideas from a set of research notes (article breakdowns, talk summaries, "
    "study notes). Each idea is a piece of CURATED COMMENTARY: an idea or practice from the research "
    "the author wants to highlight and add perspective to, with a clear angle and a reason it is "
    "worth publishing now. Not a claim of personal experience. Prefer ideas that synthesize across "
    "sources over a single-source summary. Avoid anything close to an already-published post.\n\n"
    + AUTHOR_VOICE
)


def ideate_user(candidates: list[dict], recent_posts: list[dict]) -> str:
    src = "\n".join(f"[{c['key']}] ({c.get('kind','note')}) {c['title']} :: {c.get('summary','')}" for c in candidates)
    pub = "\n".join(f"- {p['title']}" for p in recent_posts if p.get("title")) or "(none yet)"
    return (
        "Available research sources (use the [key] to cite which ones an idea draws on):\n"
        f"{src}\n\n"
        "Already published (do NOT propose anything close to these):\n"
        f"{pub}\n\n"
        "Propose 2-3 distinct post ideas. For each: a working title, the angle in one or two "
        "sentences, why it is worth publishing now, the source keys it draws on, and a 3-5 bullet "
        "outline."
    )


WRITE_SYSTEM = (
    "You write a complete blog post from the chosen idea and its research sources. It is CURATED "
    "COMMENTARY: the author is highlighting an idea or practice from the research and adding "
    "perspective, NOT recounting work they did. Return the post body as clean Markdown (no "
    "frontmatter, no H1 title line; the title is a separate field). Open with the idea or a sourced "
    "observation (NOT a personal anecdote). Develop the angle with specifics drawn from AND attributed "
    "to the sources, woven with the author's analysis. Close with a takeaway the reader can use. "
    "700-1100 words. Also produce the metadata fields.\n\n" + AUTHOR_VOICE
)


def write_user(idea: dict, sources: list[dict], recent_titles: list[str]) -> str:
    src = "\n\n".join(f"=== [{s['key']}] {s['title']} ===\n{s.get('content','')}" for s in sources)
    avoid = ", ".join(recent_titles[:30]) or "(none)"
    return (
        f"Chosen idea:\nTitle: {idea.get('title')}\nAngle: {idea.get('angle')}\n"
        f"Outline:\n- " + "\n- ".join(idea.get("outline", [])) + "\n\n"
        f"Do not re-cover these already-published angles: {avoid}\n\n"
        f"Research sources (ground every claim in these):\n{src}\n\n"
        "Write the post. Fields: title (final, punchy), seoTitle (<=60 chars, or empty if title "
        "already fits), description (one sentence, 120-160 chars, for SEO + cards), tags (4-7 "
        "lowercase topic tags), body_md (the Markdown body)."
    )


FACTCHECK_SYSTEM = (
    "You verify a draft blog post against the research sources it was written from, for accuracy AND "
    "honest framing. Flag: (1) any concrete claim (names, numbers, versions, dates, attributions, "
    "technique descriptions) unsupported by or contradicting the sources; and (2) any FIRST-PERSON "
    "claim that the author personally did, built, tested, watched, shipped, or experienced something "
    "when that thing actually comes from the sources (someone else's work, study, or talk) or is not "
    "in the sources at all. The author is curating and commentating, so a fabricated personal "
    "anecdote or a claimed experiment/metric/codebase that is really someone else's is a HIGH severity "
    "flag, and the fix is to attribute it to its real source or cut it. The author's genuine opinions "
    "and analysis ('I think', 'my read') are NOT flags. Return a list of flags; an empty list means "
    "it is accurate and honestly framed."
)


def factcheck_user(body_md: str, sources: list[dict]) -> str:
    src = "\n\n".join(f"=== [{s['key']}] {s['title']} ===\n{s.get('content','')}" for s in sources)
    return f"Draft post body:\n{body_md}\n\nSources:\n{src}\n\nList the unsupported/contradicted claims."


def revise_user(post: dict, flags: list[dict], sources: list[dict]) -> str:
    fl = "\n".join(f"- [{f.get('severity','?')}] {f.get('claim','')}: {f.get('issue','')}" for f in flags)
    src = "\n\n".join(f"=== [{s['key']}] {s['title']} ===\n{s.get('content','')}" for s in sources)
    return (
        "Revise the post to fix these fact-check flags. Keep everything else intact; change only "
        "what the flags require. Re-ground the fixed claims in the sources, or cut them.\n\n"
        f"Current post:\nTitle: {post.get('title')}\n\n{post.get('body_md','')}\n\n"
        f"Flags to fix:\n{fl}\n\nSources:\n{src}\n\n"
        "Return the full corrected post (all fields)."
    )


# ── formatting helpers ────────────────────────────────────────────────────────

def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "untitled").lower()).strip("-")
    return s or "untitled"


def to_frontmatter(post: dict, pub_date: str) -> str:
    """Assemble Markdown frontmatter + body. This is a common static-site shape
    (title, seoTitle?, description, pubDate, tags[], heroImage?, draft) that works with
    Astro/Hugo/Jekyll-style content collections. Adjust the keys to match your site."""
    title = (post.get("title") or "Untitled").replace('"', "'").strip()
    desc = (post.get("description") or "").replace('"', "'").strip()
    seo = (post.get("seoTitle") or "").replace('"', "'").strip()
    hero = (post.get("heroImage") or "").strip()
    tags = post.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    tag_line = "[" + ", ".join(f"'{t}'" for t in tags) + "]"
    lines = ["---", f'title: "{title}"']
    if seo:
        lines.append(f'seoTitle: "{seo}"')
    if hero:
        lines.append(f'heroImage: "{hero}"')
    lines += [f'description: "{desc}"', f"pubDate: {pub_date}", f"tags: {tag_line}",
              f"draft: {str(post.get('draft', False)).lower()}", "---", "", post.get("body_md", "").strip(), ""]
    return "\n".join(lines)
