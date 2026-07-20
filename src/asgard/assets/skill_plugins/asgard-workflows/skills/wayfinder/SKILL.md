---
name: wayfinder
description: Map a decision-heavy effort that cannot fit in one agent session.
disable-model-invocation: true
---

# Wayfinder

Plan decisions, not implementation.

1. Name the destination: the concrete state that ends this effort.
2. If the route already fits one session, stop and recommend `to-spec` or `to-tickets` instead.
3. Create one shared map in the configured issue tracker, otherwise `docs/wayfinder/<slug>.md`. Keep only destination, decisions-so-far pointers, fog, and out-of-scope.
4. Create decision tickets only for questions precise enough to answer now. Keep unclear future questions in fog.
5. Work at most one non-research decision ticket per session. Claim it, resolve it, record the answer once, update the map pointer, and expose the next frontier.
6. Do not turn decision tickets into implementation tasks until the route is clear.

Finish when no unresolved decision blocks a durable spec or executable ticket set.
