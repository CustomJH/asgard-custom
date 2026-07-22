---
name: design
description: Explicit umbrella workflow for routing brand, design-system, UI styling, logo, slide, banner, icon, and social-asset work to the matching Freyja or bundled specialist skill.
disable-model-invocation: true
---

# Design — Asgard adapter

This is an explicit umbrella, not a default for every visual task. Load `references/upstream-skill.md` for its complete routing table, then choose one narrow specialist: `brand`, `design-system`, `ui-styling`, `banner-design`, or `slides`; use Freyja's `asgard-freyja-logo-studio` for logos and the current image-generation capability for generated visuals.

External Claude-only skill names and `AskUserQuestion` calls in the upstream text are compatibility hints, not hard dependencies. Use Asgard's existing role contracts, ask only when a material choice is blocked, and never install or invoke a missing external generator silently.
