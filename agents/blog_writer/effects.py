"""Reference effects for the Blog Writer: everything is local files, so the agent runs
with zero external services. This is the seam to swap for your own world.

The graph never touches any of this directly, it only calls the four functions returned
by `make_effects()`. To wire the agent to a real feed + publisher, write your own
`make_effects` that returns the same four callables (e.g. `fetch_all` hits your CMS /
RSS / database, and `publish` opens a PR against your site repo).

Local layout (under the paths passed to make_effects):
  <sources>/*.md      one Markdown file per research source. First `# H1` line is the
                      title; the rest is the content. `key` = the filename stem.
  <out>/posts/*.md    published (or dry-run draft) posts.
  <out>/.ledger.json  {source_key: post_slug} so a source is not mined twice.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from .prompts import slugify, to_frontmatter


def _read_source(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    title, start = path.stem, 0
    if lines and lines[0].startswith("# "):
        title, start = lines[0][2:].strip(), 1
    body = "\n".join(lines[start:]).strip()
    summary = next((ln.strip() for ln in lines[start:] if ln.strip()), "")[:200]
    return {"key": path.stem, "kind": "note", "title": title, "summary": summary, "content": body}


def _load_ledger(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _post_title(path: Path) -> str:
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("title:"):
            return ln.split(":", 1)[1].strip().strip('"').strip("'")
    return path.stem


def make_effects(sources_dir: str = "sources", out_dir: str = "out") -> dict:
    sources = Path(sources_dir)
    out = Path(out_dir)
    posts_dir = out / "posts"
    ledger_path = out / ".ledger.json"

    def fetch_all() -> list[dict]:
        if not sources.exists():
            return []
        return [_read_source(p) for p in sorted(sources.glob("*.md"))]

    def partition_sources(items: list[dict]):
        """Split into (fresh, mined) by whether a source has already fed a post."""
        ledger = _load_ledger(ledger_path)
        fresh = [it for it in items if it["key"] not in ledger]
        mined = [it for it in items if it["key"] in ledger]
        return fresh, mined

    def recent_posts() -> list[dict]:
        if not posts_dir.exists():
            return []
        return [{"title": _post_title(p)} for p in sorted(posts_dir.glob("*.md"))]

    def publish(post: dict, source_keys: list[str], dry_run: bool = True) -> dict:
        try:
            posts_dir.mkdir(parents=True, exist_ok=True)
            slug = slugify(post.get("title") or "untitled")
            front = to_frontmatter({**post, "draft": dry_run}, datetime.date.today().isoformat())
            path = posts_dir / f"{slug}.md"
            path.write_text(front, encoding="utf-8")
            # record which sources this post consumed so they are not mined again
            ledger = _load_ledger(ledger_path)
            for k in source_keys:
                ledger[k] = slug
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
            return {"ok": True, "dry_run": dry_run, "slug": slug, "path": str(path),
                    "note": "draft (dry run)" if dry_run else "published to the local out/ dir"}
        except Exception as e:  # publish fails closed: report, leave whatever was written
            return {"ok": False, "error": str(e)}

    return {"fetch_all": fetch_all, "partition_sources": partition_sources,
            "recent_posts": recent_posts, "publish": publish}
