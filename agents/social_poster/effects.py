"""Reference effects for the Social Poster: local files, zero external services, and it
NEVER posts anywhere. The reference `publish` is a dry run; wiring real posting is the
one function you implement.

Swap for your world:
  - fetch_all  -> your RSS/GitHub/HN aggregator
  - stage      -> already local (an audit copy); keep or point elsewhere
  - publish    -> your platform API (Meta Graph API, X, LinkedIn, Bluesky, ...)
  - generate_image (optional) -> an image model (add the key under "generate_image")

Local layout (under out_dir):
  <feed_path>              JSON list of items: {title, url, source, summary, kind, score}
  <out>/social/<slug>/     facebook.md + instagram.md + meta.json per approved post
  <out>/.social_seen.json  URLs already posted (dedup)
  <out>/.social_titles.json  titles already posted (so the writer avoids repeats)
"""
from __future__ import annotations

import json
from pathlib import Path


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def make_effects(feed_path: str = "feed.json", out_dir: str = "out") -> dict:
    feed = Path(feed_path)
    out = Path(out_dir)
    social_dir = out / "social"
    seen_path = out / ".social_seen.json"
    titles_path = out / ".social_titles.json"

    def fetch_all(window_days: int) -> list[dict]:
        items = _load(feed, [])
        return items if isinstance(items, list) else []

    def partition_seen(items: list[dict]):
        seen = set(_load(seen_path, []))
        fresh = [it for it in items if it.get("url") not in seen]
        older = [it for it in items if it.get("url") in seen]
        return fresh, older

    def recent_titles() -> list[str]:
        titles = _load(titles_path, [])
        return titles if isinstance(titles, list) else []

    def mark_seen(items: list[dict], used_slug: str) -> None:
        seen = set(_load(seen_path, []))
        titles = _load(titles_path, [])
        for it in items:
            if it.get("url"):
                seen.add(it["url"])
            if it.get("title") and it["title"] not in titles:
                titles.append(it["title"])
        out.mkdir(parents=True, exist_ok=True)
        seen_path.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")
        titles_path.write_text(json.dumps(titles, indent=2), encoding="utf-8")

    def stage(post: dict, item: dict, slug: str, image=None, dry_run: bool = False) -> dict:
        try:
            d = social_dir / slug
            d.mkdir(parents=True, exist_ok=True)
            fb = d / "facebook.md"
            ig = d / "instagram.md"
            link = post.get("link") or item.get("url", "")
            fb.write_text((post.get("facebook_md", "") + f"\n\nFirst comment: {link}\n"), encoding="utf-8")
            ig.write_text((post.get("instagram_caption", "") + "\n"), encoding="utf-8")
            (d / "meta.json").write_text(json.dumps(
                {"source": item.get("url", ""), "title": item.get("title", ""),
                 "image_idea": post.get("image_idea", ""), "image": image}, indent=2), encoding="utf-8")
            return {"ok": True, "dry_run": False, "paths": {"facebook": str(fb), "instagram": str(ig)}}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def publish(post: dict, image=None, dry_run: bool = False) -> dict:
        # Reference publisher: never posts. It reports a dry run so the pipeline completes
        # end-to-end and the approved content lands in out/social/<slug>/. Implement this
        # against your platform's API to post for real (return {"ok": True, "facebook": {...},
        # "instagram": {...}} on success).
        return {"dry_run": True, "missing_creds": ["no publish backend wired in the reference effects"],
                "would": {"facebook": {"endpoint": "(your long-form platform API)"},
                          "instagram": {"endpoint": "(your image-first platform API)"}}}

    return {"fetch_all": fetch_all, "partition_seen": partition_seen, "recent_titles": recent_titles,
            "mark_seen": mark_seen, "stage": stage, "publish": publish}
