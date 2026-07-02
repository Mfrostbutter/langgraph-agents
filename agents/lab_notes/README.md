# lab-notes

A human-in-the-loop LangGraph agent that turns a feed of AI news into a monthly
**newsletter issue**: it ranks and routes candidates into modules (the one thing,
tools, repos, worth reading), writes each in a verdict voice, fact-checks the draft
against the sources, pauses for your approval, and stages an HTML email **draft** (it
never sends).

```
START -> ingest -> select -> write -> assemble -> factcheck ->
         (revise -> assemble)* -> review[gate] -> stage -> END
```

Two models (cheap ranker + quality writer), a bounded self-repair loop on high-severity
fact-check flags, and one human gate. Two things make this more than a summarizer:

- **Prompt-injection defense.** Feed items come from public RSS / GitHub / HN, which can
  carry injection payloads. Every model call treats them as untrusted DATA, fenced with
  delimiters, with a standing guard in the system prompt.
- **Grounded fact-check.** The `factcheck` node grades every concrete claim (names,
  version numbers, counts, dates) against the source items, not the model's memory, and
  auto-revises once before surfacing anything left to the human.

## Quickstart

```bash
pip install -r ../../requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export NEWSLETTER_NAME="The Brief"          # optional: brand the issue

python -m agents.lab_notes.run --feed agents/lab_notes/sample_feed.json --out out
```

You approve at the gate; it writes `out/newsletters/<date>-<slug>.html` (a self-contained
file you can open in a browser). Nothing is emailed.

## The effects seam

| function | reference impl (local) | swap for |
|---|---|---|
| `fetch_all(window_days)` | reads a JSON feed | an RSS/GitHub/HN aggregator |
| `partition_seen(items)` | dedups vs a local JSON ledger | a `seen` table |
| `recent_titles()` | past subjects from a ledger | your sent archive |
| `mark_seen(items, slug)` | records shipped URLs | your DB |
| `stage(subject, html, dry_run)` | writes an HTML file | your email tool's draft API |

Wire `stage` to Listmonk / Mailchimp / Buttondown to create a real draft campaign.
Pass `newsletter_title`, `newsletter_tagline`, `signup_html`, `signoff_html` to
`make_effects()` to brand the masthead and footer.

## Test (no API key)

```bash
python agents/lab_notes/tests/test_lab_notes.py
```
