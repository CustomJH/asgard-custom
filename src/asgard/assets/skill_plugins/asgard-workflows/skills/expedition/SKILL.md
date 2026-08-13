---
name: expedition
description: Map a decision-heavy effort that cannot fit in one agent session.
disable-model-invocation: true
---

# Expedition

Plan decisions, not implementation.

This is the heaviest flow in the set, and reaching for it too early costs more than it saves. A
well-scoped feature belongs on `council` and then `blueprint`. An expedition is for the effort that
genuinely will not fit one session — where decisions are still blocking the spec.

Its unit is a **decision quest**: a question whose resolution is a decision, not a slice of a build
to execute. That qualifier is the whole distinction, and it is what stops the map being read as a
backlog. Once the term is established, "quest" is the everyday word for it.

1. Name the destination: the concrete state that ends this effort.
2. If the route already fits one session, stop and recommend `blueprint` or `quests` instead.
3. Create one shared map in the configured issue tracker, otherwise `docs/expedition/<slug>.md`.
   Keep only destination, decisions-so-far pointers, fog, and out-of-scope.
4. Create decision quests only for questions precise enough to answer now. Keep unclear future
   questions in fog.
5. Resolve each quest with the cheapest sufficient instrument: repository facts, focused research, a
   `council` exchange with the user, or a throwaway `prototype` when only running code can answer.
6. Work at most one non-research decision quest per session. Claim it, resolve it, record the answer
   once, update the map pointer, and expose the next frontier.
7. Do not turn decision quests into implementation tasks until the route is clear.

## Research quests burn down in parallel

Research is a genuine shared blocker that downstream decisions hang on — that dependency is exactly
what the map's blocking edges exist to render — but resolving it needs nobody at the keyboard. So
charting does not stop to read it. After the quests exist, dispatch one read-only agent per research
quest, all in the same message so they run concurrently: `asgard-ullr` for anything the repository
can answer, and the `[ASGARD_RESEARCH]` checkpoint under `--external-research` for evidence from
outside it. Each one's findings land on a throwaway `research/<slug>` branch — or
`docs/expedition/<slug>/research-<name>.md` when a branch is unwanted — and the map records a
pointer to it. Research quests are the one exception to one quest per session.

## Handing off

When the map clears, this skill hands off; it does not build. Merge onto `blueprint`, which collapses
the map's linked decisions into a plan somebody can execute. Going straight to implementation is
only right when the effort turned out genuinely small.

Finish when no unresolved decision blocks a durable spec or executable quest set.
