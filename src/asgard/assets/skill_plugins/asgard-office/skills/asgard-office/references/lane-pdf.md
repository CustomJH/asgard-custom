# PDF lane

PDF is a **destination** here, not a source format. It is what a document
becomes when it is finished, and the office formats are where the editing lives.
That framing decides what is in and out of scope.

## In scope

```bash
asgard skills run asgard-office -- read report.pdf                 # text per page
asgard skills run asgard-office -- read report.pdf --format json   # + metadata, page index
asgard skills run asgard-office -- verify report.pdf               # the checks below
asgard skills run asgard-office -- render report.pdf               # page images (needs a rasteriser)
asgard skills run asgard-office -- render report.docx              # docx/pptx/xlsx -> pdf (needs LibreOffice)
```

`verify` on a PDF reports:

- `encrypted` — nothing can be read until a password is supplied.
- `no-text-layer` — pages with no extractable text. The document is scanned or
  image-only, and every text-based check is blind to those pages.
- `form-fields` — how many fields the PDF declares and how many are still empty.
  Empty fields in a document about to be delivered are usually a defect.
- `unresolved-placeholder` / `draft-leftover` — `{{field}}`, `TODO`, `lorem`
  surviving into a final PDF.

## Out of scope, and what to use instead

| Need | Why not here | Where it goes |
|---|---|---|
| Scanned pages → text | OCR needs a model and a large dependency | An OCR tool, or [docling](https://github.com/docling-project/docling) / [marker](https://github.com/datalab-to/marker) for layout-aware extraction |
| Filling an AcroForm | Doable, but a partially-filled form that *looks* complete is worse than an obviously blank one | State the gap; fill it in the source document and re-export |
| Generating a PDF directly | A PDF that cannot be reopened and edited is a dead end for office work | Build `.docx`/`.pptx`, then `render` |
| Table extraction with geometry | pypdf gives text, not per-character boxes | [pdfplumber](https://github.com/jsvine/pdfplumber) |
| Redaction | Removing pixels is not removing data; a wrong redaction is a disclosure | A dedicated redaction tool, with verification |

The last row is the one that matters most. Drawing a black rectangle over text
in a PDF leaves the text in the file. Nothing in this lane will pretend
otherwise.

## Producing a PDF properly

```bash
asgard skills run asgard-office -- build docx spec.md -o report.docx
asgard skills run asgard-office -- verify report.docx --strict
asgard skills run asgard-office -- render report.docx -o out/
```

`render` produces `out/report.pdf` and `out/report-page-N.jpg`. **Read the page
images.** After staring at the spec you see what you intended rather than what
rendered; the images are the only place a wrapped title that pushed the rule
into the body becomes visible.

The renderer is LibreOffice, and its font substitution is not the reader's. A
face you specified and LibreOffice lacks is substituted with different metrics,
so a text-fit check on that face is approximate in either direction. Leave slack
(~10%) on any container using a font outside the Office-bundled set.

If LibreOffice is absent, `render` exits non-zero and names the install command.
That is the intended behaviour: a visual check that silently did not happen is
worse than one that never ran.
