"""python-docx helpers that the library does not expose: fields, borders, CJK fonts.

Word stores a page number as a field code, not text, and a paragraph rule as a
border, not a table. Both are one-liners in OOXML and absent from python-docx,
so they live here rather than being open-coded in three places.
"""

from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

MONO_SHADE = "F2F4F7"


def _rfonts(rpr, latin: str, east_asian: str | None) -> None:
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    fonts.set(qn("w:ascii"), latin)
    fonts.set(qn("w:hAnsi"), latin)
    fonts.set(qn("w:cs"), latin)
    fonts.set(qn("w:eastAsia"), east_asian or latin)


def set_fonts(run, *, latin: str, east_asian: str | None = None) -> None:
    """Word picks a different font for CJK text unless w:eastAsia is set too.

    Without it a Korean document renders in whatever Word guesses, which is how
    an otherwise correct .docx comes back looking like two documents stapled
    together.
    """
    run.font.name = latin
    _rfonts(run._element.get_or_add_rPr(), latin, east_asian)


def set_style_fonts(style, *, latin: str, east_asian: str | None = None) -> None:
    """Same fix one level up, so body text inherits it instead of every run carrying it."""
    style.font.name = latin
    _rfonts(style.element.get_or_add_rPr(), latin, east_asian)


def shade(element, fill: str) -> None:
    """Cell or paragraph background. Word ignores CSS; this is the only lever."""
    properties = element.get_or_add_tcPr() if element.tag.endswith("}tc") else element.get_or_add_pPr()
    existing = properties.find(qn("w:shd"))
    if existing is not None:
        properties.remove(existing)
    node = OxmlElement("w:shd")
    node.set(qn("w:val"), "clear")  # 'solid' renders as a black box, never use it
    node.set(qn("w:color"), "auto")
    node.set(qn("w:fill"), fill)
    properties.append(node)


def paragraph_border(paragraph, *, edge: str = "bottom", color: str = "D9DEE5", size: int = 6) -> None:
    """A horizontal rule. A one-row table looks identical and breaks every reflow."""
    properties = paragraph._p.get_or_add_pPr()
    borders = properties.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        properties.append(borders)
    node = OxmlElement(f"w:{edge}")
    node.set(qn("w:val"), "single")
    node.set(qn("w:sz"), str(size))
    node.set(qn("w:space"), "4")
    node.set(qn("w:color"), color)
    borders.append(node)


def field_run(paragraph, instruction: str, *, placeholder: str = "") -> None:
    """Insert a Word field (PAGE, NUMPAGES, TOC, ...) as a proper field, not text."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction_node = OxmlElement("w:instrText")
    instruction_node.set(qn("xml:space"), "preserve")
    instruction_node.text = f" {instruction} "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = placeholder
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for node in (begin, instruction_node, separate, text, end):
        run._element.append(node)


def toc_field(paragraph, depth: int = 3) -> None:
    """A table of contents Word fills in on update (Ctrl+A, F9 / print preview).

    There is no way to precompute page numbers without laying the document out,
    which needs Word. Shipping the field is the honest form: it is a real TOC
    that the reader's Word populates, not a frozen list that goes stale.
    """
    field_run(paragraph, f'TOC \\o "1-{depth}" \\h \\z \\u', placeholder="Update this field to build the contents.")


def hyperlink(paragraph, url: str, runs_builder) -> None:
    """python-docx has no hyperlink API; this wires the run into the part's rels."""
    part = paragraph.part
    relationship = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    node = OxmlElement("w:hyperlink")
    node.set(qn("r:id"), relationship)
    for run in runs_builder():
        node.append(run._element)
    paragraph._p.append(node)


def style_run(run, *, size: float | None = None, color: str | None = None, bold: bool | None = None) -> None:
    if size is not None:
        run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        run.font.bold = bold


def table_borders(table, color: str = "D9DEE5", size: int = 4) -> None:
    """Uniform hairline grid. The default table style varies by Word version."""
    properties = table._tbl.tblPr
    existing = properties.find(qn("w:tblBorders"))
    if existing is not None:
        properties.remove(existing)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), str(size))
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), color)
        borders.append(node)
    properties.append(borders)


def repeat_header(row) -> None:
    """Mark a table row as a header so it repeats across page breaks."""
    properties = row._tr.get_or_add_trPr()
    node = OxmlElement("w:tblHeader")
    node.set(qn("w:val"), "true")
    properties.append(node)


def keep_with_next(paragraph) -> None:
    """Stop a heading from being orphaned at the foot of a page."""
    properties = paragraph._p.get_or_add_pPr()
    node = OxmlElement("w:keepNext")
    properties.append(node)
