---
name: design-system
description: Build or audit primitive, semantic, and component tokens, component states, CSS variables, and design-system handoff artifacts.
---

# Design System — Asgard adapter

Load Freyja's `asgard-freyja-hnoss` first so atomic ownership, promotion, and dependency rules remain authoritative. Use `references/upstream-skill.md` plus the exact token/component reference needed; helper scripts and starter assets are available as sibling resources.

When a helper is required, retrieve it with `asgard skills show design-system --resource <relative-path>` and materialize it inside the project before execution. Extend the project's existing tokens instead of creating a parallel system.
