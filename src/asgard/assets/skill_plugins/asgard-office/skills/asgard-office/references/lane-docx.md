# Word lane

```bash
asgard skills run asgard-office -- build docx SPEC.md -o out.docx [--template NAME] [--values v.json]
```

## The spec

Markdown with YAML front matter. Everything is optional except a body.

```markdown
---
title: 2026 H1 platform review
subtitle: Availability, cost, and quality
author: Operations
company: Nuriflex
date: 2026-07-28
status: Draft
cover: true              # a full cover page; otherwise a compact title block
toc: true                # a real Word contents field
number_headings: true    # 1. / 1.1 / 1.1.1 prefixes, computed at build time
header: "Internal"       # running header text
footer: "Confidential"   # running footer text; the page number is always appended
template: report-ko      # a named template from the registry
theme:
  primary: "1E2761"      # headings, title
  secondary: "52606D"    # subheadings, quotes
  accent: "9A3412"       # rules, links
  surface: "F5F7FA"      # table header fill
  muted: "7B8794"        # captions, byline
  font_head: Calibri
  font_body: Calibri
  font_mono: Consolas
  font_cjk: "맑은 고딕"   # see "CJK" below — set this for any Korean document
  size_body: 11
  line_spacing: 1.15
page:
  size: a4               # a3 a4 a5 letter legal tabloid b5
  orientation: portrait  # or landscape
  margins: {top: 25mm, bottom: 25mm, left: 22mm, right: 22mm}
---
```

## What the body supports

| Markdown | Becomes |
|---|---|
| `# … ######` | Heading 1–4 (deeper collapses to 4), `keepNext` so it never orphans |
| paragraph | Normal, with `**bold**`, `*italic*`, `` `code` ``, `~~strike~~`, `[text](url)` |
| `- ` / `* ` / `1. ` | List Bullet / List Number, nested two levels by indent |
| `- [ ] ` / `- [x] ` | checkbox item |
| `\| a \| b \|` + `\|---\|` | a real Word table: shaded header, repeat-on-page-break, hairline grid, equal column widths that sum to the text width |
| `> ` | left-ruled quote, indented |
| ` ``` ` fence | shaded monospace block, one paragraph per line |
| `![alt](path)` | centred picture, scaled to the text width, `alt` becomes a caption. Paths resolve relative to the spec file |
| `---` | **page break** |
| `<!-- … -->` | dropped — use it for authoring notes that must not ship |

## Gotchas that actually bite

- **CJK text needs `font_cjk`.** Word chooses a separate font for East Asian
  script via `w:eastAsia`; leave it unset and Word substitutes one of its own,
  which is how a correct Korean document comes back looking like two documents
  stapled together. `verify` reports `cjk-font-unset` when it sees CJK runs
  without it.
- **The contents field is empty until a word processor updates it.** There is no
  way to precompute page numbers without laying the document out. What ships is
  a real `TOC` field that Word fills on open or print — not a frozen list that
  goes stale. `verify` reports this as `info`, and that is the expected state.
- **Never use a one-row table as a horizontal rule.** Paragraph borders reflow;
  tables do not. The builder already uses borders.
- **`---` is a page break, not a rule.** In the deck lane the same token starts a
  new slide. This is deliberate: both mean "the next thing starts here".
- **Numbered headings are computed at build time**, so the numbers are literal
  text. Renumbering means rebuilding — which is correct, because the spec is the
  source and the `.docx` is the artefact.

## Editing a document you did not build

Do not rebuild it. Two supported paths:

1. **`fill`** — the file has `{{placeholders}}`, or you can add them once.
   Formatting survives, including a placeholder Word has split across runs.
2. **`read --format json`** — inspect the block structure, then decide. If the
   change is structural, ask whether the document should become a template
   (`template adopt`) so the next round is a fill rather than an edit.

A `.doc` (legacy binary) must be converted before anything here can read it, and
that conversion needs LibreOffice — an external gate, not something this lane
does silently.

## Tracked changes and comments

`verify` reports their presence (`tracked-changes`). Producing them is not in
this lane: redlining requires wrapping every run in `<w:ins>`/`<w:del>` with
matching ids and authorship, and a partial implementation produces a document
that *looks* redlined in the accepted view while carrying untracked edits — the
worst possible failure for a contract. If redlining is needed, say so plainly
rather than approximating it.
