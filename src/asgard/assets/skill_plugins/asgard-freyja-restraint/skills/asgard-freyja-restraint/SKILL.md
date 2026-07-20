---
name: asgard-freyja-restraint
description: Prevent generic AI-generated UI patterns and enforce deliberate visual hierarchy, restrained metadata, functional decoration, grounded visuals, and concise copy. Use when Freyja designs, implements, polishes, or reviews interfaces, websites, landing pages, and dashboards.
---

# Freyja Visual Restraint

Build deliberate, opinionated, functional interfaces. Remove generic AI design tropes unless the
product's real content or interaction requires them.

## Layout and composition

- Do not wrap every element in a bordered, rounded card. Separate content with typography, space,
  and layout first.
- Do not put a section heading on the left and its description on the right of the same row. Stack
  the heading and supporting text vertically.

## Typography and hierarchy

- Do not add a small, all-caps, colored eyebrow above section headings. Let the title carry the
  hierarchy.
- Use at most one subtitle per heading block. Tighten the copy instead of adding hierarchy layers.

## Components

- Use pills, badges, and status indicators only for dynamic, actionable data such as `Active` or
  `14 errors`. Never use them as decorative flair.
- Number cards only when they describe a strict sequence or chronological funnel.

## Text density and metadata

- Do not invent coordinates, timestamps, dates, version or issue tags, edition names, reading
  times, page counts, source counts, plate indices, file paths, or similar pseudo-technical detail.
  Include metadata only when it is real, functional, and necessary.
- Do not scatter small all-caps or monospace labels around headers, footers, image edges, corners,
  or section breaks.
- Make every label, caption, tag, and line of microcopy carry necessary meaning. Remove it when its
  absence loses no information.
- Do not label visible structure such as `LOGO` or `HERO`, and do not repeat the same identity or
  location in several places.
- Leave empty regions quiet. Do not fill space with decorative text or metadata.

## Visuals, icons, and data

- Do not use Unicode emoji as interface icons. Use one consistent SVG icon library such as Lucide
  or Phosphor.
- Keep utility icons at or below `32px`. Use images, UI snippets, or custom graphic forms instead of
  enlarging a generic line icon into hero artwork.
- Make charts represent realistic data scales and grouping. Do not place unrelated metrics over a
  generic gradient.
- Avoid default purple-to-blue SaaS gradients. Prefer solid brand colors, strict monochrome, or a
  mesh gradient justified by the art direction.
- Use `backdrop-filter: blur()` only for content floating over a complex, moving, or textured
  background.
- Avoid heavy single-layer shadows. Use subtle layered shadows or deliberate hard borders.

## Copy

- Do not use filler words such as Unleash, Unlock, Supercharge, Elevate, Seamless, Seamlessly,
  Leverage, Dive In, Tapestry, Next-generation, or Next-level.
- Do not use em dashes in headings or body copy. Rewrite with commas, periods, or parentheses.
- Show the feature with realistic UI, data, or code before explaining it with abstract claims.
