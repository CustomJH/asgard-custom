---
name: aceternity-ui
description: Search Aceternity UI's live free-component catalog, inspect dependencies and registry metadata, and adopt an existing React or Next.js component before building common motion or interaction patterns from scratch. Use for landing pages, interactive sections, animated backgrounds, cards, navigation, forms, text effects, and reusable UI behavior.
---

# Aceternity UI

Reuse a suitable free component when it removes real implementation work. Do not force Aceternity
into a non-React project or replace a simpler existing project component.

## Find a component

Search the live AI catalog with an English functional query:

    asgard skills run aceternity-ui search "interactive comparison slider" --limit 8

Use `--json` when another tool will consume the result. Inspect one exact component before adding it:

    asgard skills run aceternity-ui show compare --json

The helper returns free components only. It does not bundle a stale catalog or expose paid blocks.
If the live catalog is unavailable, inspect `https://ui.aceternity.com/ai-recommendations` and the
component documentation directly instead of inventing a slug.

## Select and adopt

1. Check the project's framework, Tailwind setup, `components.json`, existing components, and
   installed dependencies. Stop if existing code or CSS already covers the need.
2. Choose by functional fit, accessibility, reduced-motion behavior, dependency cost, and visual
   consistency. Do not choose the most animated option by default.
3. Open the returned documentation and registry URL. Review its files and dependencies before
   changing the project.
4. For a compatible shadcn project, run the exact returned install command without `--overwrite`.
   Never initialize shadcn, overwrite files, or use a Pro item merely to satisfy this skill.
5. Adapt the copied code to the project's tokens, types, content, breakpoints, keyboard behavior,
   and `prefers-reduced-motion`. Apply `asgard-freyja-restraint`; remove decorative motion or
   metadata that does not serve the task.
6. Run the project's focused tests and type checks, then inspect the interaction in a browser at
   desktop and mobile sizes. Treat registry code as owned project code after installation.

Prefer the component's current `motion` dependency and `motion/react` imports. Do not add GSAP,
Lottie, or a second animation engine unless the selected interaction genuinely needs it.
