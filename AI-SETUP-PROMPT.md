# AI Setup Prompt: run and adapt these agents

Copy the block below into your AI assistant (Claude, ChatGPT, Cursor, etc.)
and it will walk you through setting up, running, and adapting the agents in
this repo. If the assistant has repo access, tell it to read `README.md` and
`CLAUDE.md` too.

```text
You are helping me set up and adapt the agents in the langgraph-agents repo
(https://github.com/Mfrostbutter/langgraph-agents): four production-shaped,
human-in-the-loop LangGraph content agents (blog_writer, lab_notes,
social_poster, geo_auditor).

SETUP (do this first, verify each step):
1. Clone and create a virtual environment:
     git clone https://github.com/Mfrostbutter/langgraph-agents.git
     cd langgraph-agents
     python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
     pip install -r requirements.txt
   Keep the pinned versions (langgraph==1.2.4, langchain-core==1.4.6,
   langchain-anthropic==1.4.5); the agents were built and tested against them.
2. Set ANTHROPIC_API_KEY in the environment or in a .env file at the repo
   root (run.py loads .env automatically). Optional overrides:
   LGA_QUALITY_MODEL (default claude-sonnet-5) and LGA_CHEAP_MODEL (default
   claude-haiku-4-5-20251001).
3. Prove the wiring BEFORE spending API credits. The tests use stub models and
   in-memory effects, so they need no key and no network:
     python -m pytest agents

RUNNING (always from the repo root, as modules):
     python -m agents.blog_writer.run   --sources agents/blog_writer/sample_sources --out out
     python -m agents.lab_notes.run     --feed agents/lab_notes/sample_feed.json --out out
     python -m agents.social_poster.run --feed agents/social_poster/sample_feed.json --out out
     python -m agents.geo_auditor.run   --domain your-domain.com --brand "Your Brand"
Each run pauses at human gates in the terminal: choose approve / reject /
edit, and for publishing agents choose mode dry_run (default) or live. All
output defaults to local files under out/; nothing is published or emailed
until a real publish/stage effect is wired AND the human approves mode=live.

HOW THE CODE IS SHAPED (respect this when adapting):
- agents/<name>/graph.py is a PURE FACTORY:
  build_*_graph(models..., effects: dict, checkpointer=None). Graphs import
  no app, network, file, or env code, so they load in `langgraph dev` /
  Studio unchanged.
- ALL side effects (fetch, dedup, publish, image gen) are callables in the
  injected `effects` dict. agents/<name>/effects.py is a local-file
  reference implementation; each agent's README has the effects table.
- Two models per content agent: cheap (triage/rank) + quality (write and
  fact-check), from common/models.build_models(). geo_auditor uses one model.
- common/runner.py is the shared CLI runner (streams updates, renders
  interrupt payloads, resumes with Command(resume=decision)).

TO ADAPT AN AGENT TO MY STACK:
1. Read the target agent's README and its effects.py.
2. Write my own make_effects() returning the SAME callables with the same
   signatures (e.g. fetch_all hits my RSS/CMS/database; publish opens a PR,
   posts to my CMS, or calls my email tool). Do NOT edit graph.py to call
   services directly; keep effects injected.
3. Keep the interrupt contract intact: the review node's payload
   ({proposal, subject?, choices?, modes?}) and the decision dict
   ({action, choice?, mode?, edited?}) are what the runner and any future UI
   rely on.
4. Wire it in run.py (or my own entrypoint): build models, build effects,
   compile with a checkpointer (MemorySaver for CLI), drive with
   common.runner.run.
5. Re-run the agent's headless test, then a dry_run with real models, before
   ever approving mode=live.

Ask me which agent I want to run or adapt, and what my real sources and
publish target are, then proceed step by step.
```
