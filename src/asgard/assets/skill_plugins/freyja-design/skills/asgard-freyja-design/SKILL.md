---
name: asgard-freyja-design
description: "Freyja's default visual design engine. Use for every Freyja UI, UX, frontend, design-system, motion, accessibility, copy, localization, asset, reference, survey, review, and QA task: run the complete Freyja Design workflow and apply its final simplicity gate."
---

# Freyja default design engine

The exact pinned Oh My Design repository is under `references/oh-my-design/`. Treat every upstream agent as a Freyja role lens, not as a separate runtime identity. Do not summarize, rewrite, or omit a loaded canonical file.

Use the single safe runtime for every non-text surface:

```bash
asgard skills run asgard-freyja-design -- --help
```

- Run the official CLI with `-- cli install-skills ...` or `-- cli doctor ...`.
- Search or retrieve the 440 references with `-- reference list|show|copy`.
- Use `-- resource`, `-- extract`, or `-- materialize` for text, binary assets, directories, or the complete repository.
- Use `-- script <path>`, `-- npm root|web|mcp <script>`, or `-- prepare all` for the pinned hooks, survey/web application, development scripts, and archived MCP transport. Dependencies are installed into Asgard's derived cache, never into the canonical snapshot.

## Fixed order

1. Load `references/oh-my-design/skills/omd-feel/SKILL.md` first. Load its `reference.md` and `provenance.md` when that contract routes to them.
2. Select and load every task-relevant canonical OmD skill from `references/oh-my-design/skills/<name>/SKILL.md`. For preference-survey work also load `references/oh-my-design/.agents/skills/omd-design/SKILL.md` and its `REFERENCE_TAGS.md`.
3. Select the matching canonical role files from `references/oh-my-design/agents/`. Freyja performs those roles sequentially and preserves their gates, artifacts, revision caps, and handoffs.
4. Load `references/emil/freyja-emil-simplicity/SKILL.md` last and apply it as the subtraction and stopping gate.

For a new landing page, screen, product surface, or “design it for me” request, the default path is `omd-harness` plus `agents/omd-master.md`; follow the master phases and load each specialist role it calls. For an existing surface use `omd-apply`. Route design-system setup to `omd-init` or the survey skill, review to `omd-designer-review` and `omd-final-qa`, references to `omd-reference-capture`, assets or images to `omd-asset-fetch` or `omd-codex-image`, copy and locale work to the writer/humanize/locale skills, and experiments to the lab or gallery skills.

The canonical OmD skill set is: `claude-design`, `omd-apply`, `omd-asset-fetch`, `omd-codex-image`, `omd-designer-review`, `omd-experiment-gallery`, `omd-feel`, `omd-final-qa`, `omd-harness`, `omd-humanize`, `omd-init`, `omd-kr-writer`, `omd-lab-02-design-harness`, `omd-learn`, `omd-locale-adapter`, `omd-orchestrator`, `omd-reference-capture`, `omd-remember`, `omd-slop-audit`, `omd-sync`, and `omd-taste`.

The canonical Freyja role lenses are: `omd-a11y-auditor`, `omd-asset-curator`, `omd-codex-image`, `omd-critic`, `omd-designer-review`, `omd-final-qa`, `omd-humanizer`, `omd-kr-writer`, `omd-locale-adapter`, `omd-master`, `omd-microcopy`, `omd-orchestrator`, `omd-persona-tester`, `omd-slop-auditor`, `omd-ui-junior`, `omd-ux-engineer`, `omd-ux-researcher`, and `omd-ux-writer`.

Resolve upstream repository-relative paths under `references/oh-my-design/`. Use Asgard-equivalent tools when an upstream host-specific tool name differs; preserve the check and report it as unavailable rather than claiming it ran. Never use an upstream machine-specific absolute path.

Resolve conflicts in this order: the user's explicit request and the existing product design system; accessibility and runtime correctness; Oh My Design's system and workflow; Emil's restraint. Emil removes unearned elements but must not erase useful identity, information structure, state feedback, or evidence.

Before returning, render and use the result. Verify the primary task, desktop and mobile layout, keyboard focus, reduced motion, overflow, console output, and every gate selected by the OmD workflow.
