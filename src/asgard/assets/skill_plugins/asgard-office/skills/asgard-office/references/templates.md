# Templates

A template is a directory. A user adds one by making a folder — no registration
step, no build, no code.

```
.asgard/office/templates/<name>/     project scope, checked in with the repo
~/.asgard/office/templates/<name>/   the user's own, across every project
<bundled>/assets/templates/<name>/   ships with Asgard
```

Nearest scope wins by name, so a project template shadows a global one, and a
global one shadows a bundled one. `template list` shows which scope each came
from.

## Layout

```
<name>/
  template.toml          required — kind, field schema, theme and page defaults
  body.md                Markdown skeleton with {{placeholders}}     (md-backed)
  base.docx|.pptx|.xlsx   an existing Office file to fill in         (file-backed)
  values.example.json    a worked example
```

A template is one or the other. **Markdown-backed** means the structure is text
and the theme drives the look — right when you own the design. **File-backed**
means the layout belongs to someone else (an employer's letterhead, a client's
proposal shell, a government form) and must not move; only the marked slots
change.

## The manifest

```toml
schema = 1
name = "board-report"          # [a-z0-9][a-z0-9._-]{0,63}, must be unique
kind = "docx"                  # docx | pptx | xlsx | md
title = "Board report"
description = "Quarterly board pack, Nuriflex house style"
genre = "report"               # optional, from `outline`
language = "ko"                # optional

[theme]                        # merged under a spec's own theme, key by key
primary = "1E2761"
accent  = "9A3412"
font_cjk = "맑은 고딕"

[page]
size = "a4"
margins = {top = "25mm", bottom = "25mm", left = "22mm", right = "22mm"}

[defaults]                     # front-matter defaults for every spec built from this
toc = true
number_headings = true
footer = "Confidential"

[[fields]]
key = "quarter"
label = "Quarter"
type = "text"                  # text multiline date number list table image bool
required = true                # a missing required field fails the render
example = "FY26 Q2"
description = "Appears on the cover and in the running footer"

[[fields]]
key = "risks"
type = "table"                 # a list of row mappings, for {{#risks}} … {{/risks}}
description = "one entry per repeated row; keys: item, owner, due"
```

`type` is checked at render time: `number` must be numeric, `bool` boolean,
`list`/`table` a list, `table` a list of mappings, and `image` must point at a
file that exists. A value whose key no field declares is reported as a probable
typo — which is the check that catches `{"quater": …}` before the build.

## The placeholder grammar

The same in a Markdown skeleton, a `.docx`, a `.pptx`, and an `.xlsx`.

| Form | Meaning |
|---|---|
| `{{name}}` | scalar substitution |
| `{{a.b}}` | dotted path into nested values |
| `{{#name}} … {{/name}}` | list → repeat the block per item, item keys in scope; scalar → render once if truthy |
| `{{^name}} … {{/name}}` | render only when the value is absent or empty |
| `{{.}}` | the current item, inside a list of plain values |

In a **`.docx` table**, put `{{#rows}}` in the first cell of a row and
`{{/rows}}` in the last: that row is repeated once per item, and each item's keys
resolve inside it. This is the mechanic behind quote lines, risk registers, and
attendee tables.

Word fragments a visible phrase across many runs, so `{{client}}` often does not
exist as one string in the XML. `fill` works on the paragraph's joined text and
writes back only the runs the span actually touches, which is why surrounding
bold, colour, and font survive.

**In YAML front matter, quote the placeholder**: `title: "{{title}}"`. Unquoted,
`{{title}}` is a YAML flow mapping and the front matter fails to parse before it
can be filled. (The parser recovers from the unquoted form, but do not rely on
it — quote it.)

## Making one

```bash
# from a genre skeleton
asgard skills run asgard-office -- template new board-report --genre report --kind docx
asgard skills run asgard-office -- template new board-report --genre report --global

# from a file someone already made — placeholders are scanned into the schema
asgard skills run asgard-office -- template adopt client-form --from ~/Downloads/form.docx

# check a values file against the schema, before building anything
asgard skills run asgard-office -- template check board-report --values q2.json

# build
asgard skills run asgard-office -- template render board-report --values q2.json -o q2.docx
```

`adopt` copies the source in as `base.<ext>`, reads every `{{…}}` in the package
— headers, footers, and speaker notes included — and infers types: a name used
as `{{#items}}` becomes a `table` field, and the names inside that span are
recorded as its row keys rather than being reported as top-level fields.

## Authoring notes

- **Put the guidance in HTML comments.** `<!-- one row per risk; owner and due
  date are mandatory -->` is visible to whoever fills the template in and is
  dropped by every builder, so it never reaches the delivered document.
- **Mark a field required only if the document is wrong without it.** `required`
  is a hard stop, and a template that cannot render is worse than one with a
  blank line.
- **Give every field an `example`.** `template show` prints it, and
  `values.example.json` is generated from it — that file is how most people will
  learn the template.
- **Keep `theme` in the template, not in every spec.** That is the point of the
  merge: a spec overrides one colour without restating the set.
- **A template with neither `body.md` nor a `base.*` file cannot render**, and
  says so rather than producing an empty document.
