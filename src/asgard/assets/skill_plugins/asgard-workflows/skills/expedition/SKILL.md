---
name: expedition
description: Map a decision-heavy effort that cannot fit in one agent session.
disable-model-invocation: true
---

# Expedition

Plan decisions, not implementation.

1. Name the destination: the concrete state that ends this effort.
2. If the route already fits one session, stop and recommend `blueprint` or `quests` instead.
3. Create one shared map in the configured issue tracker, otherwise `docs/expedition/<slug>.md`. Keep only destination, decisions-so-far pointers, fog, and out-of-scope.
4. Create decision quests only for questions precise enough to answer now. Keep unclear future questions in fog.
5. Resolve each quest with the cheapest sufficient instrument: repository facts, focused research, a `council` exchange with the user, or a throwaway `prototype` when only running code can answer.
6. Work at most one non-research decision quest per session. Claim it, resolve it, record the answer once, update the map pointer, and expose the next frontier.
7. Do not turn decision quests into implementation tasks until the route is clear.

Finish when no unresolved decision blocks a durable spec or executable quest set.
