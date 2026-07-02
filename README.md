# langgraph-agents

A collection of **production-shaped, human-in-the-loop LangGraph agents** you can run,
read, and adapt. Each one is a real content-operations agent (not a toy): it gathers
input, uses a cheap model to triage and a quality model to write, **fact-checks its own
output against the sources**, pauses for a human to approve, and only then acts.

They all share one design so they are easy to learn from and to reuse:

- **Pure-factory graphs.** `build_*_graph(models..., effects, checkpointer)` builds a
  compiled graph with no app, network, or file imports. The graph is importable
  anywhere, including `langgraph dev` / Studio.
- **Injected effects.** Every side effect (fetch, dedup, publish, image gen) is a
  function passed in as an `effects` dict. Each agent ships a **local-file reference
  implementation** so it runs with zero external services, and a table telling you what
  to swap for your own world.
- **Human-in-the-loop.** A `review` node calls `interrupt(...)`; a shared CLI runner
  ([`common/runner.py`](common/runner.py)) drives the graph, pauses at each gate, asks
  you on the terminal, and resumes.
- **Grounded fact-check.** The content agents grade every concrete claim (names, version
  numbers, counts, dates) against the source material and auto-revise once before the
  human sees it. Feed items are treated as untrusted data (prompt-injection defense).

## The agents

| agent | what it does | shape |
|---|---|---|
| [`blog_writer`](agents/blog_writer) | research notes -> post ideas -> draft -> fact-check -> publish | 2 gates, self-repair |
| [`lab_notes`](agents/lab_notes) | news feed -> monthly newsletter issue -> stage an email draft | 1 gate, self-repair |
| [`social_poster`](agents/social_poster) | news feed -> one long-form post + short caption -> publish | 1 gate, self-repair |
| [`geo_auditor`](agents/geo_auditor) | probe AI answer engines for your citation share, propose GEO actions | autonomous, parallel fan-out |

`blog_writer`, `lab_notes`, and `social_poster` show the **content pipeline** pattern
(cheap-model select -> quality-model write -> ground-check -> human gate -> act).
`geo_auditor` shows the **parallel fan-out / fan-in** pattern (one probe node per engine,
running concurrently, reduced into a table the model reasons over).

## Quickstart

```bash
git clone https://github.com/Mfrostbutter/langgraph-agents.git
cd langgraph-agents
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...              # or a .env file

# run any agent from the repo root:
python -m agents.blog_writer.run  --sources agents/blog_writer/sample_sources --out out
python -m agents.lab_notes.run    --feed    agents/lab_notes/sample_feed.json --out out
python -m agents.social_poster.run --feed   agents/social_poster/sample_feed.json --out out
python -m agents.geo_auditor.run  --domain your-domain.com --brand "Your Brand"
```

Every agent defaults to **safe, local output**: drafts are written to `out/` and nothing
is published or emailed until you wire a real `publish`/`stage` effect. See each agent's
README for its effects table and what to swap.

Setting up or adapting these agents with an AI assistant? Give it
[AI-SETUP-PROMPT.md](AI-SETUP-PROMPT.md); it is a copy-paste prompt covering setup,
the runnable commands, and how to swap effects without breaking the architecture.

## Models

Two models per agent, built by [`common/models.py`](common/models.py) and overridable via
env: `LGA_QUALITY_MODEL` (default `claude-sonnet-5`) and `LGA_CHEAP_MODEL` (default
`claude-haiku-4-5-20251001`). The cheap model triages/ranks; the quality model writes and
fact-checks.

## Tests

Each agent has a headless wiring test that uses **stub models + in-memory effects**, so it
proves topology, the interrupt/resume, and the effect calls with **no API key and no
network**:

```bash
python agents/blog_writer/tests/test_blog_writer.py
python agents/lab_notes/tests/test_lab_notes.py
python agents/social_poster/tests/test_social_poster.py
python agents/geo_auditor/tests/test_geo_auditor.py
# or: python -m pytest agents
```

## Pins

Built and tested against `langgraph==1.2.4`, `langchain-core==1.4.6`,
`langchain-anthropic==1.4.5` (see [`requirements.txt`](requirements.txt)).

## Provenance

These agents are one-way public forks of internal production agents. Edits here do not
flow back; the internal fleet is canonical, and this repo evolves independently as a
learn-and-adapt edition.

## License

[MIT](LICENSE) © Michael Frostbutter
