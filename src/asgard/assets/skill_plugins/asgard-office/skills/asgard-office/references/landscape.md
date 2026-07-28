# Prior art, and why this lane is shaped the way it is

Surveyed 2026-07-28. Star counts are from the GitHub API on that date and will
drift; they are here to show which projects the field actually converged on, not
as a score. Every "decision" line records a choice made *because* of what the
survey showed.

## Agent-facing document skills

| Project | Stars | License | What it establishes |
|---|---:|---|---|
| [anthropics/skills](https://github.com/anthropics/skills) — `skills/{docx,pptx,xlsx,pdf}` | 164.6k | **source-available, not open source** | The reference shape for a production document skill: a decision table per format, a validation script, and a mandatory render-and-look QA loop |
| [iOfficeAI/OfficeCLI](https://github.com/iOfficeAI/OfficeCLI) | 22.6k | Apache-2.0 | A single self-contained binary, an L1/L2/L3 progressive API (semantic view → element DOM → raw XML), an embedded renderer that closes the render→look→fix loop headlessly, and `{{key}}` template merge as a first-class verb |
| [tfriedel/claude-office-skills](https://github.com/tfriedel/claude-office-skills) | 798 | — | Community packaging of the same four lanes |
| [appautomaton/document-SKILLs](https://github.com/appautomaton/document-SKILLs) | 137 | MIT | Adaptation for a second agent runtime |
| [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) | 71.1k | — | The index; confirms document skills are the most-forked category |

**The licence is the load-bearing fact.** Anthropic's four document skills carry
a licence that forbids reproducing them, creating derivative works, and
distributing them. They were read for *what the problem demands* — the failure
modes, the QA discipline, the fact that a validation step has to be mandatory —
and nothing was copied. Every line in this lane is original work over MIT and
Apache libraries. That constraint is why this is a clean-room build and not a
vendoring, and it is the reason the implementation differs where it does (see
"Where this diverges").

## Engines

| Project | Stars | License | Role |
|---|---:|---|---|
| [python-docx](https://github.com/python-openxml/python-docx) | 5.7k | MIT | Word write/read. Adopted. |
| [python-pptx](https://github.com/scanny/python-pptx) | 3.5k | MIT | PowerPoint write/read. Adopted. |
| openpyxl (Foss Heptapod, not GitHub) | — | MIT | Excel write/read. Adopted. |
| [pypdf](https://github.com/py-pdf/pypdf) | 10.1k | BSD | PDF read/merge. Already an Asgard dependency. Adopted. |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | 10.6k | MIT | Per-character PDF geometry, tables. Not bundled — pypdf covers the text case. |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | 10.3k | **AGPL-3.0** | Better PDF extraction, incompatible licence for a bundled dependency. Rejected. |
| [docxtpl](https://github.com/elapouya/python-docx-template) | 2.7k | LGPL-2.1 | Jinja2-in-docx. The `{{field}}` + row-loop idea is standard because of this project; reimplemented rather than depended on, to keep the placeholder grammar identical across docx, pptx, and xlsx. |
| [fpdf2](https://github.com/py-pdf/fpdf2) · [xhtml2pdf](https://github.com/xhtml2pdf/xhtml2pdf) · [WeasyPrint](https://github.com/Kozea/WeasyPrint) | 1.5k · 2.4k · 9.4k | LGPL-3.0 · Apache-2.0 · BSD | Direct PDF generation. Not adopted: a PDF that cannot be reopened and edited is a dead end for office work. PDF here is an *output* of the office formats, not a source format. |

## Converters and readers

| Project | Stars | License | Note |
|---|---:|---|---|
| [markitdown](https://github.com/microsoft/markitdown) | 169.5k | MIT | The de-facto "anything → LLM-readable Markdown". Its lesson — read-back is half the job — is built in here as `read`. Not a dependency: for the formats this skill owns, reading through the same library that wrote the file keeps coordinates addressable, which a Markdown dump throws away. |
| [docling](https://github.com/docling-project/docling) | 63.9k | MIT | Best-in-class PDF layout analysis, heavy model dependencies. Out of scope; named here as the escalation for scanned documents. |
| [marker](https://github.com/datalab-to/marker) | 37.9k | Apache-2.0 | Same category, same reason. |
| [pandoc](https://github.com/jgm/pandoc) | 45.6k | GPL-2.0 | 60+ formats, the universal converter. Used opportunistically if present, never required — it is a system binary, and requiring one would break the one-command install. |
| [unstructured](https://github.com/Unstructured-IO/unstructured) | 15.2k | Apache-2.0 | Document ETL for RAG, not authoring. |

## Deck and typesetting ecosystems

| Project | Stars | License | What it taught |
|---|---:|---|---|
| [reveal.js](https://github.com/hakimel/reveal.js) | 72.0k | MIT | — |
| [Slidev](https://github.com/slidevjs/slidev) | 47.9k | MIT | `---` as slide separator; per-slide directives in front matter |
| [Marp](https://github.com/marp-team/marp) | 12.2k | MIT | Per-slide directives as HTML comments — invisible to any Markdown renderer |
| [Typst](https://github.com/typst/typst) | 55.1k | Apache-2.0 | Modern typesetting; a possible future PDF lane |
| [Quarto](https://github.com/quarto-dev/quarto-cli) | 5.9k | — | Scientific publishing over pandoc |
| [pandoc-latex-template](https://github.com/Wandmalfarbe/pandoc-latex-template) | 7.2k | BSD | A template as a *set of defaults*, not a file |
| [Awesome-CV](https://github.com/posquit0/Awesome-CV) | 28.1k | LPPL-1.3c | The resume genre's conventional structure |

**Decision.** The deck spec uses `---` separators (Slidev/Marp convention) and
HTML-comment directives (Marp convention), so a deck spec still reads as an
ordinary Markdown document in any editor, and the directives never render.

## Where this diverges, and why

1. **Pure Python, no binary required.** Anthropic's skills assume a sandbox with
   LibreOffice, pandoc, Poppler, and npm packages preinstalled; OfficeCLI ships a
   compiled binary. Asgard installs with one `uv tool install`, so `build`,
   `read`, `fill`, and `verify` had to work with nothing else present. Rendering
   is the only thing that genuinely cannot, and it is an explicit gate that
   exits non-zero rather than pretending.

2. **The gate is static and it runs everywhere.** Both references treat
   validation as "run the schema checker, then render and look". Rendering is
   unavailable on a bare install, so the checks that do not need a layout engine
   were pushed as far as they go: text-overflow estimation from font metrics,
   off-canvas geometry, WCAG contrast, package relationship integrity,
   unresolved placeholders, spreadsheet formula faults. `verify` catches the
   common defects without a renderer; `render` remains the gate for the rest.

3. **One placeholder grammar across all three formats.** docxtpl is Word-only,
   OfficeCLI's merge is scalar-only. Here `{{field}}` and `{{#rows}}…{{/rows}}`
   mean the same thing in a Markdown skeleton, a `.docx`, a `.pptx`, and an
   `.xlsx`, so a user learns it once.

4. **Templates are directories with a field schema.** OfficeCLI's merge takes
   whatever keys you pass. A schema lets `template check` fail *before* the
   build, which is where a missing required field should surface — not in the
   delivered document.

5. **Genres are first-class.** No surveyed project ships the structural
   knowledge of what an incident review or a decision record owes its reader.
   `outline` does, in 23 genres, with the guidance carried as comments that the
   builders strip.
