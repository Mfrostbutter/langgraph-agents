# social-poster

A human-in-the-loop LangGraph agent that turns a feed of AI news into **one** social
post per run. It picks the single strongest story, drafts a long-form post and a short
image-first caption in a maker voice, fact-checks both against the source, pauses for
your approval, and (on approve) generates a visual and publishes through your channels.

```
START -> ingest -> select -> draft -> factcheck -> review[gate] -> publish -> END
                                ^_________ revise ______|  (bounded auto-fix)
```

Same guarantees as `lab-notes`: **prompt-injection defense** on every model call
(feed items are untrusted data) and a **grounded fact-check** that flags any claim not
supported by the one source item, auto-revising once before the human sees it.

> The reference publisher **never posts anywhere**. On approve it writes the approved
> copy to `out/social/<slug>/` and reports a dry run. Wiring real posting is the one
> function you implement (see below).

## Quickstart

```bash
pip install -r ../../requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

python -m agents.social_poster.run --feed agents/social_poster/sample_feed.json --out out
```

Approve at the gate; the two drafts land in `out/social/<date>-<slug>/` as
`facebook.md` + `instagram.md` + `meta.json`.

## The effects seam

| function | reference impl | swap for |
|---|---|---|
| `fetch_all(window_days)` | reads a JSON feed | an RSS/GitHub/HN aggregator |
| `partition_seen` / `mark_seen` | local JSON dedup ledger | a `seen` table |
| `recent_titles()` | past titles from a ledger | your post history |
| `stage(post, item, slug, image, dry_run)` | writes local files | keep, or your DAM |
| `publish(post, image, dry_run)` | **dry run, never posts** | your platform API |
| `generate_image(prompt, slug)` *(optional)* | not wired | an image model |

To post for real, implement `publish()` against your platform (Meta Graph API, X,
LinkedIn, Bluesky, ...) and return `{"ok": True, "facebook": {...}, "instagram": {...}}`.
To attach a generated image, add a `generate_image` key to the effects dict; the graph
calls it after approval and threads the result into `stage`/`publish`.

The two draft fields are just *a long-form post* and *a short caption* — retarget them
to whatever two platforms you publish to.

## Test (no API key, no network)

```bash
python agents/social_poster/tests/test_social_poster.py
```
