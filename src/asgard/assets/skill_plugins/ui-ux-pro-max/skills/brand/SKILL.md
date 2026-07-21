---
name: brand
description: Define or audit brand voice, visual identity, messaging, asset organization, and brand consistency. Use for brand guidelines and reusable brand context.
---

# Brand — Asgard adapter

Treat an existing project brand guide and tokens as the source of truth. Load `references/upstream-skill.md` for the full workflow, then only the required reference or helper under `references/`, `scripts/`, or `templates/`.

Upstream commands assume a `.claude/skills/brand` install. In Asgard, load a helper with `asgard skills show brand --resource <relative-path>` and materialize it in a project-scoped tool directory before running it. Do not invent missing brand decisions or overwrite existing guides without explicit authorization.
