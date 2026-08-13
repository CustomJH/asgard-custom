---
name: council
description: Convene a war council that clarifies a plan or design, one round of decisions at a time.
disable-model-invocation: true
---

# Council

Resolve the decision tree before acting.

Map the work as a **design tree**: every decision branches into the decisions that hang off it. The
**frontier** is every decision whose prerequisites are already settled — the questions answerable now,
without guessing at answers you have not heard yet.

## Work the tree in rounds

1. Draw the frontier. A question whose answer depends on another question still open belongs to a
   later round, not this one.
2. Put the **whole frontier** to the user in one message, numbered, each with your recommended
   answer and the tradeoff that answer accepts. Then stop and wait.
3. The answers reshape the tree: settled decisions push the frontier outward and unblock what
   depended on them. Redraw it and ask the next round.

Each question takes this shape — mirror the user's language, and keep the question body as long as
the decision needs:

```
⠶ Q1 — <what is being decided>
<the options, and what hangs on the choice>
Recommend: <your answer>, which accepts <the tradeoff>
```

## Facts are yours, decisions are theirs

Never ask the user for anything the repository, the tools, or the environment can answer. When a
frontier question needs such a fact, dispatch `asgard-ullr` to find it. Do not block the round on it:
a running exploration is an unsettled prerequisite, so only the questions downstream of it wait —
put the rest of the frontier to the user now, and fold the report in when it lands.

## Instruments

- A decision only running code can settle — how logic behaves, how a surface feels — goes to
  `prototype`. Put a throwaway artifact in front of the user instead of debating it.
- A domain term that resolves, or a costly decision that lands, goes to `domain-modeling` in the
  same turn: `CONTEXT.md` or `docs/adr/`, so the outcome survives this chat.
- A frontier question the user cannot answer alone — it belongs to someone else, not to the
  repository — goes to `inquiry`. Say so and keep the rest of the frontier moving; that question is
  blocked on a person, not on fog.

Record every assumption explicitly. Do not edit files, launch implementation, or declare agreement
until the user confirms the shared understanding.

Finish when the frontier is empty: every branch visited, nothing left silently assumed, and no
answer depending on an unresolved term. Then size the confirmed work and route it: fits one fresh
context window → implement directly; larger → `blueprint` then `quests`; decisions still block a
spec → `expedition`.
