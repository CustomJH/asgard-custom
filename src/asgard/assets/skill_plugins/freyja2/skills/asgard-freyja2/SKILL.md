---
name: asgard-freyja2
description: "Freyja 2 — Freyja's second visual delivery engine. A complete design workflow: 23 commands (shape, critique, audit, polish, bolder, quieter, animate, live, and more), persistent PRODUCT.md/DESIGN.md context, seeded direction variation, a numeric craft floor, and a deterministic anti-slop detector. Use when Freyja 2 or engine 2 is requested, or when the task calls for its command-style design workflow."
---

# Freyja 2 — second visual delivery engine

The complete engine lives under `engine/` (relative to this skill's directory) and is followed wholesale. It is self-contained: vanilla node scripts (node >= 22.12), no package installs, no API keys.

1. Load `engine/SKILL.md` and follow it exactly — its Setup (run `node engine/scripts/context.mjs` once per session from the project root), its routing table of 23 commands and playbooks under `engine/reference/`, its craft floor, and its detector directives. That file is this engine's single design authority.
2. Path resolution: any `{{scripts_path}}`-style or `scripts/...` reference in engine documents resolves under `engine/scripts/`. Run scripts with `node`. Never run any network installer; everything needed is vendored here.
3. Detector and hooks: hook manifests are vendored under `engine/hooks/` for reference. Asgard does not auto-install host hooks; replicate their effect by running `node engine/scripts/hook.mjs` after UI file edits and once before finishing, whenever working inside a project directory. Findings are acted on, not summarized away.
4. Subagent roles live under `engine/agents/`. When a playbook asks for one and the host exposes a Task/Agent tool, spawn a general agent primed with that file's contents; otherwise substitute a disclosed in-thread pass.
5. Motion architecture invariant (Asgard addition, benchmark-proven): content paints first, choreography is additive. Never gate the hero or primary content's first paint behind an entrance sequence — base states stay visible without JS and without animation classes; staged openings that delay first paint are reserved for explicit user requests.
6. Asgard-wide invariants apply unchanged: user-facing surfaces follow Asgard's language and emoji conventions, accessibility floors (contrast, keyboard focus, prefers-reduced-motion) are never lifted, and evidence-first reporting is unchanged.
