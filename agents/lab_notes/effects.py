"""Reference effects for Lab Notes: local files, zero external services.

Swap these for your world: `fetch_all` for an RSS/GitHub/HN aggregator, and `stage`
for your email tool's draft API (Listmonk/Mailchimp/Buttondown/etc.). The reference
`stage` writes a self-contained HTML file you can open in a browser; it never sends.

Local layout (under out_dir):
  <feed_path>          JSON list of candidate items: {title, url, source, summary, kind, score}
  <out>/newsletters/*.html   staged issue drafts
  <out>/.seen.json           URLs already shipped (dedup)
  <out>/.issues.json         subjects already sent (so the writer avoids repeats)
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

_STYLE = (
    "body{font:16px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;max-width:640px;margin:2rem auto;"
    "padding:0 1rem;color:#111}.masthead .t{font-weight:800;letter-spacing:.12em}.masthead .s{color:#666}"
    ".mod{font-weight:700;margin:1.4rem 0 .4rem;border-top:1px solid #eee;padding-top:1rem}"
    "a{color:#0a5}blockquote{border-left:3px solid #0a5;margin:0;padding-left:1rem;color:#333}"
)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "issue").lower()).strip("-") or "issue"


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def make_effects(feed_path: str = "feed.json", out_dir: str = "out", **branding) -> dict:
    feed = Path(feed_path)
    out = Path(out_dir)
    seen_path = out / ".seen.json"
    issues_path = out / ".issues.json"
    news_dir = out / "newsletters"

    def fetch_all(window_days: int) -> list[dict]:
        items = _load(feed, [])
        return items if isinstance(items, list) else []

    def partition_seen(items: list[dict]):
        seen = set(_load(seen_path, []))
        fresh = [it for it in items if it.get("url") not in seen]
        older = [it for it in items if it.get("url") in seen]
        return fresh, older

    def recent_titles() -> list[str]:
        titles = _load(issues_path, [])
        return titles if isinstance(titles, list) else []

    def mark_seen(items: list[dict], used_issue: str) -> None:
        seen = set(_load(seen_path, []))
        for it in items:
            if it.get("url"):
                seen.add(it["url"])
        out.mkdir(parents=True, exist_ok=True)
        seen_path.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")

    def stage(subject: str, html: str, dry_run: bool = False) -> dict:
        try:
            news_dir.mkdir(parents=True, exist_ok=True)
            slug = datetime.date.today().strftime("%Y-%m-%d") + "-" + _slug(subject)[:50]
            doc = (f"<!doctype html><html><head><meta charset='utf-8'><title>{subject}</title>"
                   f"<style>{_STYLE}</style></head><body>\n{html}\n</body></html>\n")
            path = news_dir / f"{slug}.html"
            path.write_text(doc, encoding="utf-8")
            issues = _load(issues_path, [])
            if subject not in issues:
                issues.append(subject)
            issues_path.write_text(json.dumps(issues, indent=2), encoding="utf-8")
            return {"ok": True, "dry_run": False, "campaign_id": slug,
                    "edit_url": str(path), "path": str(path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    eff = {"fetch_all": fetch_all, "partition_seen": partition_seen, "recent_titles": recent_titles,
           "mark_seen": mark_seen, "stage": stage}
    # optional branding passthrough: newsletter_title, newsletter_tagline, signup_html, signoff_html
    eff.update({k: v for k, v in branding.items() if v})
    return eff
