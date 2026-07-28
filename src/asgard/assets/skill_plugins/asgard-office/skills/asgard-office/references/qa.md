# The gate

```bash
asgard skills run asgard-office -- verify FILE [--strict] [--json]
```

Exit code 0 unless there are errors, or `--strict` and there are warnings.

## The three bands

**`error` — the file is broken, or it ships something the author did not mean.**
Never deliver past one.

| Code | Meaning |
|---|---|
| `not-a-package` / `no-content-types` / `malformed-xml` | the file will not open |
| `dangling-relationship` | a part references something not in the package |
| `unsafe-path` | a package entry escapes the archive root |
| `unresolved-placeholder` | `{{field}}` survived into the delivered document |
| `off-slide` | a shape sits outside the canvas — PowerPoint writes it, it is simply not visible |
| `formula-error` | a cached `#REF!` / `#NAME?` / `#DIV/0!` |
| `external-link` | a formula points at a workbook file that is not being delivered |

**`warn` — a defect a reader will see.** Fix it or be able to say why not.

| Code | Meaning |
|---|---|
| `text-overflow` | estimated text height exceeds its box |
| `overlap` | two text boxes intersect by more than 0.06 sq in |
| `low-contrast` | below the WCAG floor for that text size on that ground |
| `heading-jump` | a heading level skipped, so the contents tree reads wrong |
| `empty-heading` | a heading with no text |
| `cjk-font-unset` | CJK text with no `w:eastAsia` face — Word will substitute one |
| `draft-leftover` | `TODO`, `TBD`, `lorem`, `[insert …]`, `여기에 입력` in the prose |
| `untitled-slide` | a slide with no text at all |
| `missing-xlfn` / `spill-formula` / `inconsistent-row` | see `lane-xlsx.md` |
| `empty-toc` | a contents field with no headings to list |

**`info` — true, and it needs a human rather than a fix.**

`toc-needs-update` (expected: Word fills the field on open) · `tracked-changes`
· `no-cached-values` (expected until something recalculates) · `text-only-slide`
· `layout-monotony` · `no-text-layer` · `encrypted` · `form-fields`.

## What the gate cannot see

It has no layout engine. It does not know where a line actually broke, whether a
two-line title pushed the rule into the body, or how a font the reader has and
you do not will measure. The overflow check is an estimate from font metrics and
per-script advance widths — good enough to catch overflow that matters, blind to
a line that breaks one word early.

`render` is the gate for the rest, and it is external on purpose:

```bash
asgard skills run asgard-office -- render --probe        # what is installed
asgard skills run asgard-office -- render out.docx -o qa/
```

It exits non-zero when LibreOffice is absent and names the install command. A
visual check that silently did not happen is worse than one that never ran.

**Read the page images.** After working on the spec you see what you intended
rather than what rendered. Look for, in this order:

1. text overflowing or cut off at a box or page boundary — the most common
   user-visible defect, every time
2. overlapping elements: text through shapes, lines through words
3. footers or citations colliding with the content above
4. uneven gaps — cramped in one place, empty in another
5. content closer than 0.5in to a slide edge, or outside the page margin
6. a template's decoration mispositioned after text replacement — a title
   underline placed for one line, with a title that wrapped to two
7. anything still reading as a placeholder

## The loop

```bash
build → verify --strict → fix the spec → build → render → read the images → fix → build
```

Fix defects **in the spec**, never by hand-editing the built file. The moment
you edit the artefact, the spec stops describing it and the next build silently
reverts your fix.

The first render usually has two or three real issues. Find those, fix them,
re-render, and stop. A fourth pass is almost always polishing something no
reader will notice.

## Beyond the gate

`verify` proves structure. Two things it deliberately does not judge:

- **Whether the numbers are right.** A clean workbook with an off-by-one range
  is clean and wrong. Check two or three formulas by hand against values you
  know before building out a grid.
- **Whether the prose is any good.** Run the report style pass (`asgard-bragi-humanize`)
  on the text before it goes into a document meant for people to read, and the
  restraint pass (`asgard-lagom-compress`) if it is long.
