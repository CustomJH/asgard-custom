---
name: asgard-office
description: Create, read, edit, fill, and verify Word (.docx), PowerPoint (.pptx), Excel (.xlsx), and PDF documents. Use whenever the deliverable is an office document — report, proposal, memo, meeting minutes, spec, PRD, design doc, ADR, incident review, runbook, release notes, manual, paper, resume, slide deck, pitch, quarterly review, model, or a filled-in form — and whenever an existing .docx/.pptx/.xlsx/.pdf is the input. Also use for document templates: composing one, adopting an existing file as one, and rendering a template with values. Korean .hwp/.hwpx belongs to the `hwpx` skill instead.
---

# Asgard Office (Sága)

Documents are built from a spec, not typed into a binary. Write the spec, build,
verify, then look at it. Everything below runs without Word, LibreOffice, or
pandoc installed.

```bash
asgard skills run asgard-office -- outline                      # genre skeletons, 23 of them
asgard skills run asgard-office -- build docx SPEC.md -o out.docx
asgard skills run asgard-office -- build pptx DECK.md -o out.pptx
asgard skills run asgard-office -- build xlsx SHEET.yaml -o out.xlsx
asgard skills run asgard-office -- read FILE [--format json]
asgard skills run asgard-office -- verify FILE [--strict] [--json]
asgard skills run asgard-office -- fill FORM.docx --values v.json -o out.docx
asgard skills run asgard-office -- template list|show|new|adopt|check|render
asgard skills run asgard-office -- render FILE                  # needs LibreOffice
```

## Pick the lane

| Situation | Do this |
|---|---|
| Produce a new document, deck, or workbook | `outline <genre>` for the skeleton, fill it in, `build` |
| The layout belongs to someone else (letterhead, client shell, government form) | `fill` — never rebuild it |
| A shape you will produce repeatedly | make it a template: `template new`, or `template adopt --from FILE` |
| Read or summarise an existing file | `read` (`--format json` when you will edit against coordinates) |
| Korean `.hwp` / `.hwpx` | `asgard skills run hwpx -- extract FILE` — a different skill owns that format |

## The order that matters

1. **Structure before prose.** `outline <genre>` prints the sections that genre
   is expected to have, each with a `<!-- … -->` line saying what belongs there.
   Those comments never render into the document, so leave them until the
   section is written, then delete them.
2. **Build.** The spec is Markdown with YAML front matter (`docx`, `pptx`) or
   YAML (`xlsx`). Same spec, same output, every machine.
3. **Verify — not optional.** `verify` proves what a machine can prove: text
   past its box, shapes off the canvas, contrast below the WCAG floor, dangling
   package relationships, `{{placeholders}}` you forgot to fill, `TODO` left in
   the prose, formulas that will open as `#NAME?`. Fix every `error`. A `warn`
   is a defect a reader will see — justify it or fix it.
4. **Look at it, if you can.** `render` converts to PDF and page images. It
   needs LibreOffice and exits non-zero when that is absent, on purpose:
   only a layout engine knows where a line actually broke. `render --probe`
   reports what is installed.

## Rules

- **Never hand-edit the packed XML** of a file you built. Fix the spec and
  rebuild — otherwise the spec stops describing the artefact and the next build
  silently reverts your fix.
- **Never compute a number in Python and write the result into a spreadsheet.**
  Write the formula. A workbook that does not recalculate is a screenshot.
- **Every number in a document carries its source** where the reader can see it
  — a cell comment, a footnote, a parenthetical. When a number came from the
  user, say that plainly rather than implying an analysis.
- **Preserve the original.** `fill` and `build` write to a new path. Never
  overwrite the input.
- **A document that ships with `{{field}}` in it is a defect,** not a draft.
  `verify` treats it as an error.
- Prose quality is a separate axis: run the report style pass (`asgard-bragi-humanize`)
  on the text before it goes into a document meant for people to read.

## Templates

A template is a directory. That is the whole of it — a user adds one by making a
folder, and it works the same whether the skeleton is Markdown or a `.docx` an
employer handed them.

```
.asgard/office/templates/<name>/        project scope, checked in with the repo
~/.asgard/office/templates/<name>/      the user's own, across every project
  template.toml        kind, field schema, theme and page defaults  (required)
  body.md              Markdown skeleton with {{placeholders}}      (md-backed)
  base.docx|.pptx|.xlsx   an existing file to fill in               (file-backed)
  values.example.json  a worked example
```

Nearest scope wins, so a project template shadows a global one of the same name,
and a global one shadows a bundled one. `template check` validates a values file
against the field schema *before* a build, which is where a missing required
field should surface — not in the delivered document.

Read `templates.md` (below) before authoring or changing one.

## References

Load only the one you need, with:

```bash
asgard skills show asgard-office --resource references/<file>
```

**Use that command, not a file path.** Only `SKILL.md` is copied into a project's
skill folder; the references live in the installed package, so opening
`references/…` relative to this file fails in Claude Code, Cursor, and Codex
alike. The command works identically from every mode.

| File | When |
|---|---|
| `references/lane-docx.md` | building or editing a Word document |
| `references/lane-pptx.md` | building a deck; also the design rules that keep it from reading as generated |
| `references/lane-xlsx.md` | workbooks, formulas, financial-model conventions |
| `references/lane-pdf.md` | reading PDFs, forms, and what is out of reach here |
| `references/genres.md` | what each of the 23 genres owes its reader |
| `references/templates.md` | authoring templates and the placeholder engine |
| `references/qa.md` | the gate: what `verify` proves, what only a render can catch |
| `references/landscape.md` | the surveyed prior art and why each choice was made |
