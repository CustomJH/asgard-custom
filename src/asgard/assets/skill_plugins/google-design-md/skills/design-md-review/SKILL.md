---
name: design-md-review
description: Validate and review DESIGN.md design-system tokens, structure, references, typography, components, and WCAG contrast with Asgard's Python port.
triggers: design.md audit, design.md review, design system audit, design system review, design token audit, token validation, 디자인 시스템 검수, 디자인 시스템 리뷰, 디자인 토큰 검수, 토큰 검증
agent: freyja, freyja-lead
agents: freyja, freyja-lead
---

# DESIGN.md review — Freyja

When a task asks to review a design system, locate its `DESIGN.md`. Do not create one merely because
it is absent; report the missing source of truth unless creation was requested.

Run the bundled Python linter first:

    asgard skills run design-md-review lint <path/to/DESIGN.md>

The command emits JSON and exits 1 only when errors exist, 2 when the file cannot be read. Warnings
still require judgment. Use each finding's `path` and message as evidence, then compare the document
against the actual CSS, theme, component, or token implementation in scope. Tokens are normative;
prose explains intent but must not silently override token values.

Review beyond syntax:

- Check that brand personality, audience, hierarchy, and interaction states are explicit enough to
  guide another agent without guessing.
- Check responsive behavior, keyboard focus, reduced motion, semantic colors, and empty/error states
  when the product uses them; the DESIGN.md schema is a minimum, not the whole UX contract.
- Treat unknown extension sections as valid and preserve them. Duplicate headings, unresolved token
  references, invalid values, and implementation drift are actionable.
- Report findings as severity, exact path or section, evidence, impact, and smallest correction. Do
  not claim the upstream Node CLI ran; this command is Asgard's Python port.

The upstream alpha specification is bundled at `references/spec.md`. Print it when exact wording is
needed:

    asgard skills run design-md-review spec

Python port notice: Asgard reimplemented the lint/spec execution path from Google Labs Code
`design.md` revision `bde692f2bc92ef7fdd0cf277b2704ab074b70efd`; `diff` and `export` are not included.
