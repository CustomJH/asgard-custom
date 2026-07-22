---
name: design-dna
description: Extract a portable three-dimension Design DNA JSON from visual references, explain its schema, or apply an existing DNA profile to content. Use for explicit reference-to-profile or profile-to-design transfer; not for ordinary UI design or review.
---

# Design DNA — Freyja specialist

Design DNA is a translation layer across three dimensions:

1. **design_system** — measurable tokens: color, type, spacing, layout, shape, elevation, motion, components
2. **design_style** — qualitative intent: mood, visual language, composition, imagery, interaction feel, brand voice
3. **visual_effects** — rendering behavior: Canvas, WebGL, 3D, particles, shaders, scroll, cursor, SVG, glass

## Asgard scope and precedence

Use this skill only when the requested artifact is a Design DNA schema/JSON, reference extraction,
or an explicit transfer from a DNA profile. It is not Freyja's general design authority.

- The repository's existing design system and the user's brief outrank this profile.
- `asgard-freyja-reference-atlas` owns source provenance and reference diversity. Record only sources
  actually inspected; do not turn an inaccessible URL into invented evidence.
- `ui-ux-pro-max` supplies broad product/UX direction when no reference DNA exists.
- `asgard-freyja-hnoss`, `asgard-freyja-gersemi`, `asgard-freyja-motion`, and
  `asgard-freyja-folkvangr` own implementation decisions in their domains.
- `design-md-review` validates an existing project `DESIGN.md`; Design DNA must not overwrite it.
- `asgard-freyja-restraint`, accessibility, performance, and browser-verification gates still apply.

When guidance conflicts, use this order: explicit user constraint → repository convention → verified
reference evidence → inferred DNA value → generic recommendation. Label inference. Preserve every
schema key, but use `null` or `"unknown"` when evidence is absent; never invent exact hex, pixel,
font, library, or effect values merely to make the JSON look complete.

## Phase selection

Infer the requested phase from the artifact, then execute only what is needed:

- **Structure**: user asks for the schema or dimensions.
- **Analyze**: user provides references and wants a structured profile.
- **Generate**: user provides a DNA JSON and content to implement.
- **Analyze → Generate**: user requests both extraction and implementation.

Do not pause between phases already requested. When the requested phase is complete, finish without a
mandatory follow-up question; mention the next available phase in one sentence only if useful.

## Phase 1 — Structure

Read `references/schema.md`. Present the complete field structure and explain which dimension is
measured, perceived, or rendered. Do not generate sample values unless asked.

## Phase 2 — Analyze references

1. Read `references/schema.md`.
2. Inspect each supplied image, screenshot, URL, video, or source file with the appropriate tool.
3. Separate direct observations, computed measurements, and inferences. For multiple references,
   record the dominant pattern and meaningful variants instead of averaging incompatible systems.
4. Populate every schema key. Use `null`/`"unknown"` for unavailable evidence and explain important
   uncertainty in `meta.description` or `visual_effects.composite_notes`.
5. Output valid JSON. Keep source references exact and do not claim runtime effects from a static
   screenshot; describe only the visible cue and mark the implementation as inferred.

For code-backed pages, inspect actual tokens and detect Canvas/WebGL/Three.js/Pixi/GSAP/Lottie,
custom shaders, scroll observers, and SVG animation. For screenshots, estimate rather than asserting
false precision.

## Phase 3 — Generate from DNA

1. Read `references/generation-guide.md` and validate the supplied JSON before changing code.
2. Map design-system values to the project's existing tokens and components; preserve its framework,
   architecture, dependencies, and asset pipeline. A self-contained HTML file is only the fallback
   when the user asks for a standalone artifact or no project stack exists.
3. Treat qualitative style fields as direction, not as permission to override usability.
4. Implement only effects whose `enabled` state and evidence justify them. Prefer CSS/platform
   features, then existing dependencies. Do not add a CDN or an unpinned `latest` dependency.
5. Use original assets only when access and reuse rights permit it; otherwise request, link, or create
   an explicitly distinct substitute.
6. Verify contrast, keyboard/focus behavior, responsive layout, reduced motion, effect fallback,
   resize/cleanup, and the rendered result. Source inspection alone is not a visual verdict.

## Resources

- `references/schema.md` — full three-dimension field schema
- `references/generation-guide.md` — DNA-to-code mapping and quality checks
- `references/upstream-skill.md` — pinned upstream contract for provenance and exact comparison

Bundled from `zanwei/design-dna` revision
`9d9d79568df31cd846681f89fd3be1c3ce0c2aff` under the MIT license. The Asgard precedence and
evidence rules above intentionally narrow unsafe or overlapping upstream defaults.
