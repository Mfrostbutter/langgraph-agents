# Eval-first is becoming the default for agent teams

Several 2025 conference talks converged on the same practice: write the evals
before you tune the agent. The pitch is that a non-deterministic system needs a
test harness that scores outputs against criteria, not exact-match assertions, and
that the first run mostly debugs your evaluators rather than your agent.

Speakers described a two-tier setup: a cheap deterministic tier over pure functions
that runs free in CI, and a behavior tier over the real agent scored by a
cross-vendor LLM judge. The recurring warning was to never let a model grade its
own output, and to bucket guardrail cases separately so a blended average does not
hide a real regression.

The through-line: teams that added evals early shipped changes with more
confidence, because a regression showed up as a score drop instead of a user
complaint.
