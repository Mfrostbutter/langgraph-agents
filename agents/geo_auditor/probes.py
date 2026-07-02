"""GEO probe IO + scoring. Pure, stdlib-only (urllib), fail-open.

Each engine adapter calls one external AI answer engine with web search enabled and
returns (answer_text, [citation_urls]). `run_probe` wraps an adapter with scoring and
never raises: a missing key returns status="skipped", any error returns status="error".
This module is injected into the graph via effects, so the graph never imports it and
Studio can run with no keys.

Scoring is parameterized: pass your `target_domains` (which count as a citation win) and
a lowercase `brand_token` (an entity string like a person or company name to detect a
mention). No module-level identity constants, so this drops into any brand.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

# Engine -> env var holding its key. Order here is the fan-out / catalog order.
ENGINE_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "brave": "BRAVE_API_KEY",
    "you": "YOU_API_KEY",
}
ENGINE_NAMES = tuple(ENGINE_KEYS.keys())

OPENAI_MODEL = "gpt-4o-mini"
ANTHROPIC_MODEL = "claude-haiku-4-5"
PERPLEXITY_MODEL = "sonar"
GEMINI_MODEL = "gemini-2.5-flash"


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _post_json(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, headers: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1).lower().lstrip("www.") if m else ""


def _is_ours(url: str, domains: tuple[str, ...]) -> bool:
    d = _domain_of(url)
    return any(d == dom or d.endswith("." + dom) for dom in domains)


# ── Engine adapters: each returns (answer_text, [citation_urls]) ─────────────

def probe_openai(query: str, key: str) -> tuple[str, list[str]]:
    data = _post_json("https://api.openai.com/v1/responses",
                      {"model": OPENAI_MODEL, "tools": [{"type": "web_search"}], "input": query},
                      {"Authorization": f"Bearer {key}"})
    text_parts: list[str] = []
    urls: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []) or []:
            if content.get("type") == "output_text":
                text_parts.append(content.get("text", ""))
                for ann in content.get("annotations", []) or []:
                    if ann.get("type") == "url_citation":
                        urls.append(ann.get("url", ""))
    return "\n".join(text_parts), urls


def probe_anthropic(query: str, key: str) -> tuple[str, list[str]]:
    data = _post_json("https://api.anthropic.com/v1/messages",
                      {"model": ANTHROPIC_MODEL, "max_tokens": 1500,
                       "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
                       "messages": [{"role": "user", "content": query}]},
                      {"x-api-key": key, "anthropic-version": "2023-06-01"})
    text_parts: list[str] = []
    urls: list[str] = []
    for block in data.get("content", []):
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
            for cit in block.get("citations", []) or []:
                if cit.get("url"):
                    urls.append(cit["url"])
        elif btype == "web_search_tool_result":
            for res in block.get("content", []) or []:
                if isinstance(res, dict) and res.get("url"):
                    urls.append(res["url"])
    return "\n".join(text_parts), urls


def probe_perplexity(query: str, key: str) -> tuple[str, list[str]]:
    data = _post_json("https://api.perplexity.ai/chat/completions",
                      {"model": PERPLEXITY_MODEL, "messages": [{"role": "user", "content": query}]},
                      {"Authorization": f"Bearer {key}"})
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    urls = list(data.get("citations") or [])
    for res in data.get("search_results") or []:
        if isinstance(res, dict) and res.get("url"):
            urls.append(res["url"])
    return text, urls


def probe_gemini(query: str, key: str) -> tuple[str, list[str]]:
    """Google Search grounding. Citation uris are Google redirect URLs that hide the real
    domain, so domain detection leans on the grounding source titles (appended to the
    answer text) and on the answer body."""
    data = _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}",
        {"contents": [{"parts": [{"text": query}]}], "tools": [{"google_search": {}}]}, {})
    text_parts: list[str] = []
    titles: list[str] = []
    urls: list[str] = []
    for cand in data.get("candidates", []) or []:
        for part in (cand.get("content", {}) or {}).get("parts", []) or []:
            if "text" in part:
                text_parts.append(part["text"])
        gm = cand.get("groundingMetadata", {}) or {}
        for chunk in gm.get("groundingChunks", []) or []:
            web = chunk.get("web", {}) or {}
            if web.get("uri"):
                urls.append(web["uri"])
            if web.get("title"):
                titles.append(web["title"])
    text = "\n".join(text_parts)
    if titles:
        text += "\nGROUNDING SOURCES: " + " ".join(titles)
    return text, urls


def probe_brave(query: str, key: str) -> tuple[str, list[str]]:
    """Brave Search + AI summarizer. Summarizer needs the Pro AI plan; without it we
    still capture indexed result URLs."""
    search = _get_json("https://api.search.brave.com/res/v1/web/search?summary=1&q=" + urllib.parse.quote(query),
                       {"X-Subscription-Token": key, "Accept": "application/json"})
    urls = [r["url"] for r in ((search.get("web", {}) or {}).get("results", []) or [])
            if isinstance(r, dict) and r.get("url")]
    text = ""
    skey = (search.get("summarizer", {}) or {}).get("key")
    if skey:
        summ = _get_json("https://api.search.brave.com/res/v1/summarizer/search?key=" + urllib.parse.quote(skey),
                         {"X-Subscription-Token": key, "Accept": "application/json"})
        text = " ".join(str(s.get("data", "")) for s in (summ.get("summary") or []) if isinstance(s, dict))
    return text, urls


def probe_you(query: str, key: str) -> tuple[str, list[str]]:
    """You.com Smart API (best-effort schema; adjust if the account differs)."""
    data = _get_json("https://chat-api.you.com/smart?query=" + urllib.parse.quote(query), {"X-API-Key": key})
    text = data.get("answer", "") or ""
    urls = [h["url"] for h in (data.get("search_results", []) or []) if isinstance(h, dict) and h.get("url")]
    return text, urls


_ADAPTERS = {
    "openai": probe_openai, "anthropic": probe_anthropic, "gemini": probe_gemini,
    "perplexity": probe_perplexity, "brave": probe_brave, "you": probe_you,
}


# ── Scoring + the fail-open entrypoint ───────────────────────────────────────

def evaluate(text: str, urls: list[str], domains: tuple[str, ...], brand_token: str) -> dict:
    ours = [u for u in urls if _is_ours(u, domains)]
    blob = (text or "").lower()
    cited_in_text = any(dom in blob for dom in domains)
    competing = sorted({_domain_of(u) for u in urls if u and not _is_ours(u, domains)} - {""})
    return {
        "cited": bool(ours) or cited_in_text,
        "brand_mentioned": bool(brand_token) and brand_token in blob,
        "cited_url": ours[0] if ours else "",
        "competing_domains": ";".join(competing[:8]),
    }


def run_probe(engine: str, query: str, key: str, domains: tuple[str, ...], brand_token: str) -> dict:
    """Probe one engine for one query and score it. Never raises. A blank key ->
    status='skipped'; any failure -> status='error' with the message."""
    row = {"engine": engine, "query": query, "cited": False, "brand_mentioned": False,
           "cited_url": "", "competing_domains": "", "error": "", "status": "ok"}
    if not key:
        row["status"] = "skipped"
        return row
    fn = _ADAPTERS.get(engine)
    if fn is None:
        row["status"] = "error"
        row["error"] = f"unknown engine {engine!r}"
        return row
    try:
        text, urls = fn(query, key)
        row.update(evaluate(text, urls, domains, brand_token))
    except Exception as e:  # a dead engine must not kill the run
        row["status"] = "error"
        row["error"] = repr(e)[:200]
    return row
