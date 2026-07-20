---
name: quests
description: Split a spec or plan into dependency-aware tracer-bullet quests.
disable-model-invocation: true
---

# Quests

1. Read the source spec or current plan and the relevant domain vocabulary.
2. Draft narrow but complete vertical slices. Each quest must cross the needed layers, be independently demonstrable or verifiable, and fit one fresh context window.
3. Declare blocking edges. Prefer an unblocked frontier; use expand–migrate–contract only for wide mechanical changes that cannot stay green as vertical slices.
4. Present titles, blockers, delivered behavior, and acceptance criteria. Wait for user confirmation before publishing.
5. Publish to the repository's configured tracker; if none is documented, write one file per quest under `docs/quests/<feature>/`.
6. Do not implement quests in this invocation.

Finish when every quest is independently executable and no dependency is implicit in conversation history.
