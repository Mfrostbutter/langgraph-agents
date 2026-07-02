"""A tiny standalone human-in-the-loop runner.

In a full application you would drive these graphs from a web UI: stream node
updates to the browser, render the interrupt payload as an approval card, and
resume with the human's decision. This module is the CLI stand-in for that
runner so an agent runs on its own with nothing but a terminal.

Contract each agent's graph follows (see any `graph.py`):
  - progress is emitted as NAMED AIMessages   -> printed as `· [node] text`
  - the final result is an unnamed AIMessage / a `result_md` state field
  - a review node calls `interrupt({proposal, subject?, choices?, modes?})`
  - resuming with `Command(resume=<decision dict>)` continues the graph

The graph must be compiled WITH a checkpointer (pass `MemorySaver()` for a CLI
run) so it can pause and resume on the same `thread_id`.
"""
from __future__ import annotations

from langgraph.types import Command

_RULE = "=" * 72


def _print_progress(update: dict) -> None:
    for node, payload in (update or {}).items():
        if node == "__interrupt__" or not isinstance(payload, dict):
            continue
        for m in payload.get("messages", []):
            name = getattr(m, "name", None)
            if name:  # named -> progress line
                print(f"  · [{name}] {getattr(m, 'content', '')}")


def _ask_human(value: dict) -> dict:
    """Render the interrupt payload and collect a decision from the terminal."""
    print("\n" + _RULE)
    print("HUMAN REVIEW" + (f": {value['subject']}" if value.get("subject") else ""))
    print(_RULE)
    print(value.get("proposal", ""))

    choices = value.get("choices") or []
    if choices:
        print("\nChoices:")
        for c in choices:
            print(f"  {c.get('value')}. {c.get('label')}")

    modes = value.get("modes") or ["approve", "reject"]
    print(f"\nActions available: {', '.join(modes)}")
    action = (input("action [approve]: ").strip().lower() or "approve")
    decision: dict = {"action": action}

    if action == "approve":
        if choices:
            pick = input("choice number [1]: ").strip()
            if pick.isdigit():
                decision["choice"] = int(pick)
        # Agents that publish support mode=live|dry_run; others ignore it.
        mode = input("mode [dry_run] (dry_run/live): ").strip().lower()
        decision["mode"] = "live" if mode == "live" else "dry_run"
    elif action == "edit":
        decision["edited"] = input("edited text (or a choice number): ").strip()

    return decision


async def run(graph, initial_state: dict, thread_id: str = "cli-1", recursion_limit: int = 50):
    """Stream the graph, pause at every interrupt to ask the human, resume, repeat."""
    cfg = {"recursion_limit": recursion_limit, "configurable": {"thread_id": thread_id}}
    stream_input: object = initial_state
    final: str | None = None

    while True:
        interrupted = False
        async for update in graph.astream(stream_input, cfg, stream_mode="updates"):
            if "__interrupt__" in update:
                decision = _ask_human(update["__interrupt__"][0].value)
                stream_input = Command(resume=decision)
                interrupted = True
                break
            _print_progress(update)
            for _node, payload in update.items():
                if not isinstance(payload, dict):
                    continue
                if payload.get("result_md"):
                    final = payload["result_md"]
                # autonomous agents (no result_md) end on a trailing UNNAMED AIMessage
                for m in payload.get("messages", []):
                    if not getattr(m, "name", None):
                        txt = getattr(m, "content", "")
                        if isinstance(txt, str) and txt.strip():
                            final = txt
        if not interrupted:
            break

    print("\n" + _RULE + "\nRESULT\n" + _RULE)
    print(final or "(the graph produced no result_md)")
    return final
