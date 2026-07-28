# Workbook lane

```bash
asgard skills run asgard-office -- build xlsx SHEET.yaml -o out.xlsx [--values v.json]
asgard skills run asgard-office -- verify out.xlsx          # formula lint
asgard skills run asgard-office -- render --recalc out.xlsx # needs LibreOffice
```

## The spec

```yaml
title: FY26 operating cost model
author: Operations
theme: {primary: "1E2761", surface: "F2F4F9"}

sheets:
  - name: Assumptions          # <= 31 chars, Excel's limit
    title: Assumptions         # an in-sheet heading; data then starts at row 3
    columns:
      - {header: Item, width: 34}
      - {header: Value, width: 14, format: "0.0%"}
      - {header: Source, width: 44}
    rows:                      # a list of lists, or a path to a .csv/.tsv
      - ["Retry amplification", 0.32, "H1 measured, batch-ingest logs"]
    inputs: [B4, B5]           # blue text on yellow — the cells a reader may edit
    notes: {B4: "H1 actual. Converges to 0 once the retry cap lands."}
    freeze: A4                 # defaults to the row under the header
    table: false               # true adds a banded Excel table with autofilter
    legend: true               # prints the colour convention at the bottom

  - name: Model
    columns: [{header: Period, width: 12}, {header: Cost, width: 16, format: "$#,##0"}]
    rows: [["Q1", 120000]]
    cells:                     # formulas and one-off values, by reference
      C2: "=B2*Assumptions!$B$4"
      B5: "=SUM(B2:B3)"
    formats: {D: "0.0x", B7: "0.0%"}   # a whole column, or a single cell
```

`rows` accepts a CSV or TSV path instead of a list; it resolves relative to the
spec file, and numeric-looking strings are coerced so they do not sit in the
sheet as text with a formula pointing at them.

## Requirements for anything delivered

- **Formulas, never computed results.** Write `=SUM(B2:B9)`, not the total your
  script worked out. A workbook that does not recalculate when its inputs change
  is a screenshot with extra steps.
- **Every assumption in its own labelled cell**, referenced by the formulas that
  use it: `=B5*(1+$B$6)`, never `=B5*1.05`.
- **Every hardcoded number carries its source** — a cell comment (`notes:`) or an
  adjacent cell. Cite the real source when one exists; when the number came from
  the user, say that plainly.
- **A workbook someone else will fill in needs a legend** naming which cells to
  edit, and one example row in the expected format. Set `legend: true` — but
  never add an example row to a file you were asked to *edit*.
- **Editing an existing file: match its conventions.** They override everything
  here. Find its designated input cells first — a distinct font colour or fill
  marks them — write only there, and leave existing formulas alone.

## The colour convention

Every reviewer of a financial model reads these before the numbers, and the
builder applies them:

| Colour | Meaning |
|---|---|
| blue text (`0000FF`), yellow fill | a human types this — `inputs:` |
| black | derived by formula; do not overwrite |
| green (`008000`) | links to another sheet in this workbook |
| red (`FF0000`) | links to a **separate file** |

Number formats: currency `$#,##0` with the unit in the header (`Revenue ($mm)`),
negatives in parentheses, zeros rendered as `-`, percentages `0.0%` **stored as
fractions** (`0.15` renders `15.0%`; storing `15` renders `1500.0%`), multiples
`0.0x`, years as text so they do not render as `2,024`.

## Formula lint — what `verify` proves

- **`missing-xlfn`.** Excel stores every post-2007 function name with an
  `_xlfn.` prefix and hides it in the UI. Written bare into the XML,
  `TEXTJOIN`, `CONCAT`, `IFS`, `SWITCH`, `MAXIFS`, `MINIFS`, `XOR`, and `IFNA`
  all open as `#NAME?`. Write `=_xlfn.TEXTJOIN(...)`.
- **`spill-formula`.** `XLOOKUP`, `XMATCH`, `FILTER`, `SORT`, `SORTBY`,
  `UNIQUE`, `SEQUENCE`, `RANDARRAY` spill into neighbouring cells, and a
  library-written file carries no spill metadata — only the anchor cell ever
  gets a value, and no error is reported. Use `INDEX`/`MATCH` for lookups, and
  sort, filter, and de-duplicate in the generator before writing cells.
- **`external-link`.** A formula reading `='[1]Returns'!$B$2` names a separate
  file on disk. That file is almost never delivered with the workbook, and
  re-saving strips the cached value that was holding the data. Inline the values
  or ship both files.
- **`inconsistent-row`.** Three or more formulas in one row that are not the same
  shape. A single hand-edited cell mid-row is the commonest silent modelling
  error, and it produces no error anywhere else.
- **`formula-error`.** A cached result that is `#REF!`, `#NAME?`, `#VALUE!`,
  `#DIV/0!`, `#N/A`, `#NULL!`, or `#NUM!`. Never ship one. If you believe an
  error predates you, prove it: load the *original* with `data_only=True` and
  look at that cell.

## Cached values

openpyxl writes formulas as strings with no cached results. Until something
evaluates them, every formula cell reads back as `None` to pandas, to
`load_workbook(data_only=True)`, and to most previewers. `verify` reports this
as `no-cached-values` — an `info`, because the workbook is correct, not broken.

Two ways to resolve it: the reader opens it in Excel once, or
`render --recalc FILE` evaluates it with LibreOffice and rewrites it in place.
The recalc reports how many formulas produced a value and names any that
errored.

**A clean recalc proves the formulas evaluate, not that they are right.** An
off-by-one range yields a clean file with wrong numbers. Write two or three
formulas first and check they pull the values you expect before building a grid.
