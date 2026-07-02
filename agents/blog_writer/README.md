# blog-writer

A human-in-the-loop LangGraph agent that turns a folder of research notes into a
publishable blog post. It proposes a few post ideas, lets you pick one, writes the
post, **fact-checks the draft against the source material**, and publishes on your
approval. The fact-check is the point: it casts the author as a *curator* of other
people's ideas and flags any claim (or fabricated first-person anecdote) that is not
grounded in the sources.

```
START -> ingest -> ideate -> review_ideas[gate 1] -> prepare -> write ->
         factcheck -> (revise -> factcheck)* -> review_draft[gate 2] -> publish -> END
```

Two human gates, a bounded self-repair loop (one auto-revision on high-severity
fact-check flags), and two models: a cheap one proposes/ranks ideas, a quality one
writes and checks.

## Quickstart

```bash
pip install -r ../../requirements.txt          # from the repo root
export ANTHROPIC_API_KEY=sk-ant-...            # or put it in a .env file

# from the repo root:
python -m agents.blog_writer.run --sources agents/blog_writer/sample_sources --out out
```

You will be walked through both gates in the terminal. Publishing defaults to a
**dry run** (writes a local draft under `out/posts/`); approve with `mode: live` to
publish for real. With the local reference effects, "live" just drops the `draft:`
flag and writes the same file, so it is safe to try.

## The effects seam (how to wire it to your world)

The graph never touches a file, feed, or API directly. All IO is four functions
built by [`effects.py`](effects.py):

| function | reference impl (local files) | swap for |
|---|---|---|
| `fetch_all()` | reads `*.md` from a sources dir | your CMS / RSS / DB |
| `partition_sources(items)` | dedups against a local JSON ledger | a `seen` table |
| `recent_posts()` | reads titles from `out/posts/` | your published index |
| `publish(post, keys, dry_run)` | writes a Markdown file | a PR against your site repo |

Write your own `make_effects()` that returns the same four callables and the graph
is unchanged. `to_frontmatter()` in [`prompts.py`](prompts.py) emits a common
static-site frontmatter shape (Astro/Hugo/Jekyll-style); adjust the keys for your site.

## Customize the voice

Set `BLOG_AUTHOR_VOICE` (or edit `AUTHOR_VOICE` in `prompts.py`) to change who the
post sounds like. The default is a semi-technical curator with strict
no-fabrication / attribute-everything rules.

## Test (no API key)

```bash
python agents/blog_writer/tests/test_blog_writer.py     # stub models, drives both gates
```
