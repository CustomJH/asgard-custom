---
name: asgard-freyja-design
description: "Freyja's default visual design engine. Use for every Freyja UI, UX, frontend, design-system, motion, accessibility, copy, localization, asset, reference, survey, review, and QA task: run the complete Freyja Design workflow and apply its final simplicity gate."
---

# Freyja default design engine

The exact pinned Vanadis repository is under `references/vanadis/`. Treat every upstream agent as a Freyja role lens, not as a separate runtime identity. Do not summarize, rewrite, or omit a loaded canonical file.

Use the single safe runtime for every non-text surface:

```bash
asgard skills run asgard-freyja-design -- --help
```

- Run the official CLI with `-- cli install-skills ...` or `-- cli doctor ...`.
- Search or retrieve the 440 references with `-- reference list|show|copy`.
- Use `-- resource`, `-- extract`, or `-- materialize` for text, binary assets, directories, or the complete repository.
- Use `-- script <path>`, `-- npm root|web|mcp <script>`, or `-- prepare all` for the pinned hooks, survey/web application, development scripts, and archived MCP transport. Dependencies are installed into Asgard's derived cache, never into the canonical snapshot.

## Fixed order

1. Load `references/vanadis/skills/vanadis-feel/SKILL.md` first. Load its `reference.md` and `provenance.md` when that contract routes to them.
2. Select and load every task-relevant canonical Vanadis skill from `references/vanadis/skills/<name>/SKILL.md`. For preference-survey work also load `references/vanadis/.agents/skills/vanadis-design/SKILL.md` and its `REFERENCE_TAGS.md`.
3. Select the matching canonical role files from `references/vanadis/agents/`. Freyja performs those roles sequentially and preserves their gates, artifacts, revision caps, and handoffs.
4. Load `references/vanadis-restraint/SKILL.md` last and apply it as the subtraction and stopping gate.

For a new landing page, screen, product surface, or “design it for me” request, the default path is `vanadis-harness` plus `agents/vanadis-master.md`; follow the master phases and load each specialist role it calls. For an existing surface use `vanadis-apply`. Route design-system setup to `vanadis-init` or the survey skill, review to `vanadis-designer-review` and `vanadis-final-qa`, references to `vanadis-reference-capture`, assets or images to `vanadis-asset-fetch` or `vanadis-codex-image`, copy and locale work to the writer/humanize/locale skills, and experiments to the lab or gallery skills.

The canonical Vanadis skill set is: `claude-design`, `vanadis-apply`, `vanadis-asset-fetch`, `vanadis-codex-image`, `vanadis-designer-review`, `vanadis-experiment-gallery`, `vanadis-feel`, `vanadis-final-qa`, `vanadis-harness`, `vanadis-humanize`, `vanadis-init`, `vanadis-kr-writer`, `vanadis-lab-02-design-harness`, `vanadis-learn`, `vanadis-locale-adapter`, `vanadis-orchestrator`, `vanadis-reference-capture`, `vanadis-remember`, `vanadis-slop-audit`, `vanadis-sync`, and `vanadis-taste`.

The canonical Freyja role lenses are: `vanadis-a11y-auditor`, `vanadis-asset-curator`, `vanadis-codex-image`, `vanadis-critic`, `vanadis-designer-review`, `vanadis-final-qa`, `vanadis-humanizer`, `vanadis-kr-writer`, `vanadis-locale-adapter`, `vanadis-master`, `vanadis-microcopy`, `vanadis-orchestrator`, `vanadis-persona-tester`, `vanadis-slop-auditor`, `vanadis-ui-junior`, `vanadis-ux-engineer`, `vanadis-ux-researcher`, and `vanadis-ux-writer`.

## Atomic design project structure

When Freyja sets up a new project structure, or the frontend component structure is not yet established, structure it as an atomic design system whenever possible. The default tree is `components/atoms|molecules|organisms` plus `templates` and `pages`; the framework's router convention wins for templates and pages. The hierarchy is framework-agnostic: React components, Vue SFCs, Svelte, web components, and server template partials are judged on the same five levels.

- Level ladder before editing: a piece that still works with every domain term removed is an atom or molecule; two or more atoms combined for one purpose is a molecule; anything that needs domain data is an organism; anything that only decides placement is a template; pages inject real data, routing, and SEO. State the judgment as `Atomic: <level>` in the report.
- Dependencies flow one way: lower levels never import higher levels. Server state and global-state subscriptions live at organism level or above; atoms and molecules stay controlled (props in, events out).
- Never mix a primitive and a domain section in one file. Promote a piece to a shared atom or molecule only after two real usage sites exist — do not generalize speculatively from one.
- An existing project convention wins on paths (`ui/` maps to the atom-molecule layer, `features/` or `widgets/` to the organism layer), but level judgment, one-way dependencies, and the mixed-file ban still apply. Reorganize directories only within the assigned scope.

Resolve upstream repository-relative paths under `references/vanadis/`. Use Asgard-equivalent tools when an upstream host-specific tool name differs; preserve the check and report it as unavailable rather than claiming it ran. Never use an upstream machine-specific absolute path.

Resolve conflicts in this order: the user's explicit request and the existing product design system; accessibility and runtime correctness; Vanadis's system and workflow; the Vanadis restraint gate. The restraint gate removes unearned elements but must not erase useful identity, information structure, state feedback, or evidence.

Before returning, render and use the result. Verify the primary task, desktop and mobile layout, keyboard focus, reduced motion, overflow, console output, and every gate selected by the Vanadis workflow.
