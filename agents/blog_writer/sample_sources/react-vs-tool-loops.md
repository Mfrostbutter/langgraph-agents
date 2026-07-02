# When a ReAct loop beats a hand-wired pipeline

A recurring theme from recent agent-engineering talks: teams reach for a fully
hand-wired graph when a bounded ReAct tool-loop would have been simpler and more
robust. The argument, made repeatedly by practitioners shipping agents in
production, is that the loop lets the model recover from a bad tool call on its
own, where a rigid pipeline just fails the step.

The counterpoint is cost and unpredictability: a loop can wander, and every extra
turn is tokens. The consensus that emerged was to bound the loop (a low recursion
limit), keep the tools read-only where possible, and put a human gate before any
write. Use a fixed pipeline only when the steps are genuinely known in advance.

Numbers cited varied by team, but the shape held: fewer nodes, more reliance on a
capable model to route, and a hard cap so the loop cannot spin.
