# geo-auditor

An autonomous LangGraph agent that measures your **citation share in AI answer
engines** (Generative Engine Optimization). It asks a fixed set of questions across
several engines *in parallel*, records whether each answer cited your domain or
mentioned your brand and which competitors it cited instead, then has a model reason
over the gaps and propose concrete GEO actions.

```
START -> plan -> [ probe_openai | probe_anthropic | probe_gemini |
                   probe_perplexity | probe_brave | probe_you ] -> synthesize -> analyze -> END
                    (one branch per engine, all in a single parallel superstep)
```

This is the **parallel fan-out / fan-in** pattern: `plan` dispatches one probe node
per engine, they run concurrently and append rows to an additive `results` channel,
`synthesize` reduces them into a per-engine table, and `analyze` (the model) turns the
table into a prioritized action list. No human gate; it just runs and reports.

## Quickstart

```bash
pip install -r ../../requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...          # required (analysis + the anthropic probe)
# optional, one per engine you want to probe:
export OPENAI_API_KEY=...  GEMINI_API_KEY=...  PERPLEXITY_API_KEY=...  BRAVE_API_KEY=...  YOU_API_KEY=...

python -m agents.geo_auditor.run \
  --domain your-domain.com \
  --brand "Your Brand" \
  --queries agents/geo_auditor/sample_queries.txt
```

It probes every engine you have a key for and skips the rest, so you can start with
just one. Each engine uses its web-search / grounding mode so the citations are real.

## What each engine needs

| engine | key env var | notes |
|---|---|---|
| openai | `OPENAI_API_KEY` | Responses API + `web_search` tool |
| anthropic | `ANTHROPIC_API_KEY` | Messages API + `web_search` tool |
| gemini | `GEMINI_API_KEY` | Google Search grounding |
| perplexity | `PERPLEXITY_API_KEY` | `sonar`, natively cites |
| brave | `BRAVE_API_KEY` | summarizer needs the Pro AI plan; else result URLs only |
| you | `YOU_API_KEY` | Smart API (schema varies by account) |

The probes are plain stdlib `urllib` and fail open (a dead engine reports `error`,
never crashes the run). Add an engine by writing one adapter in
[`probes.py`](probes.py) that returns `(answer_text, [citation_urls])`.

## Configure the audit

- `--domain` / `GEO_TARGET_DOMAINS` (comma-separated) — what counts as a citation win.
- `--brand` / `GEO_BRAND_TOKEN` — the entity string that counts as a mention.
- `--queries` — a text file, one question per line. These should be the questions your
  audience actually asks; the default set is generic and meant to be replaced.

## Test (no API key, no network)

```bash
python agents/geo_auditor/tests/test_geo_auditor.py     # stub llm + mock engines
```
