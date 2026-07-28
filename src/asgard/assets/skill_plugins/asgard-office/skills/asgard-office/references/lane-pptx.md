# Deck lane

```bash
asgard skills run asgard-office -- build pptx DECK.md -o out.pptx [--template NAME] [--values v.json]
```

## The spec

Front matter, then slides separated by `---` on its own line. Per-slide
direction rides in HTML comments, so the spec still reads as a document and the
directives never render.

```markdown
---
title: H1 operations review
author: Operations
company: Nuriflex
date: 2026-07-28
size: 16x9              # 16x9 (13.33x7.5in) · 4x3 (10x7.5in) · a4
footer: Operations review   # appears bottom-right from slide 2 on, with the number
theme:
  primary: "1E2761"     # title-slide ground, headings
  secondary: "3C4A8C"   # section-slide ground
  accent: "F96167"      # bullets, stat figures
  background: "FFFFFF"  # content-slide ground
  surface: "F2F4F9"     # table header fill, quote ground
---

# H1 operations review
Availability, cost, and quality
<!-- notes: lead with the number, not the cause -->

---

## The quarter in three numbers
<!-- layout: stat -->
- 99.94% :: availability (target 99.9%)
- 107% :: of planned cost
- 0 :: quality regressions
```

## Layouts

Named with `<!-- layout: … -->`, or inferred. Inference is good enough that most
decks never declare one.

| Layout | Use | Built from |
|---|---|---|
| `title` | opening slide | heading + one paragraph; ground is `theme.primary` |
| `section` | divider | heading + optional line; ground is `theme.secondary` |
| `bullets` | the default | lists, paragraphs, code |
| `two-col` | comparison | one list split by an item that is exactly `\|\|\|`; without the marker it splits in half |
| `stat` | headline figures | list items shaped `value :: label`, up to 8, laid out in a grid |
| `quote` | a single pulled line | one blockquote |
| `table` | tabular detail | a Markdown table |
| `image` | picture plus text | `![alt](path)` or `<!-- image: path -->`; picture right, text left |
| `blank` | title only | |

Other directives: `<!-- notes: … -->` (speaker notes, repeatable),
`<!-- background: 1E2761 -->` (per-slide ground).

## Design rules the builder already enforces

These exist because they are the specific tells of a generated deck.

- **No accent stripes, no colour bars, no rules under titles.** Header bars
  spanning the slide, vertical sidebar stripes, thin edge accents on cards —
  all of them read as filler. Contrast and whitespace carry the structure instead.
- **Ink follows its ground.** Every text colour is checked against the slide's
  actual background and darkened or lightened until it clears the WCAG floor
  (3:1 for large text, 4.5:1 for body) with its hue intact. A brand coral that
  fails on white becomes a darker coral, not black.
- **Text boxes carry no inset**, so text aligns with shapes at the same x.
- **Bullets are real bullets** (`a:buChar`), never a typed `•` — a typed glyph
  doubles up the moment the deck is opened in a template that already bullets.
- **Speaker notes go in the notes pane**, never in a text box on the slide.

## Rules for the author

- **Vary the layout.** `verify` reports `layout-monotony` after three
  consecutive slides with the same shape signature. Three bullet slides in a row
  is the commonest reason a deck stops being read.
- **Four bullets, not six.** If a slide needs six, it is two slides.
- **Do not centre body text.** Titles centre; paragraphs and lists do not.
- **A text-only slide is a weak slide.** `verify` flags it as `info`. A stat
  block, a table, or an image carries the same point further.
- **Fonts you write are rendered by the reader's PowerPoint, not here.** Prefer
  faces that ship with Office — Calibri, Arial, Cambria, Times New Roman — for
  anything where fit matters. For Korean, set a face the reader will have
  (맑은 고딕 / Malgun Gothic) rather than one only your machine has.

## Overflow

The single most common user-visible defect, and the one `verify` was built
around: `text-overflow` estimates the rendered height of every text frame from
its font sizes, box width, and per-script advance widths (CJK glyphs are roughly
twice Latin), and reports the boxes whose content does not fit.

It is an estimate. It will not catch a line that breaks one word early, and it
is approximate for a font the reader has and you do not. `render` is the gate
for that — but overflow large enough to matter shows up here, on a machine with
nothing installed.

## Editing an existing deck or template

`fill` for placeholder substitution — it reaches shape text, table cells, and
speaker notes.

Building *on top of* a real `.potx`/`.pptx` template is supported by pointing a
registry template's `base.pptx` at it; the deck then inherits that file's masters
and theme. Restructuring someone else's deck — duplicating slides, reordering
`<p:sldIdLst>`, cleaning orphaned media — is not in this lane. It requires
package surgery whose half-done state is an unopenable file.
