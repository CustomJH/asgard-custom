---
name: grill-me
description: Relentlessly clarify a plan or design, one decision at a time.
disable-model-invocation: true
---

# Grill

Resolve the decision tree before acting.

1. Inspect the environment for facts; never ask the user what tools or files can answer.
2. Ask exactly one decision question per turn. Give a recommended answer and its main tradeoff.
3. Resolve prerequisite decisions before dependent branches. Record assumptions explicitly.
4. When a decision can only be settled by running code — how logic behaves, how a UI feels — load `prototype` and put a throwaway artifact in front of the user instead of debating.
5. When a domain term resolves or a costly decision lands, load `domain-modeling` and record it in `CONTEXT.md` or `docs/adr/` in the same turn, so the outcome survives this chat.
6. Do not edit files, launch implementation, or declare agreement until the user confirms the shared understanding.

Finish when the important branches have explicit decisions and no answer depends on an unresolved term. Then size the confirmed work and route it: fits one fresh context window → implement directly; larger → `to-spec` then `to-tickets`; decisions still block a spec → `wayfinder`.
