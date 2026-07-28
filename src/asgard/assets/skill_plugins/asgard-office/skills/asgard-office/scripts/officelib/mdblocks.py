"""Deterministic Markdown subset -> block tree.

Not a CommonMark implementation and not trying to be. It covers exactly the
constructs a document or a deck needs, and it fails loudly on nothing — an
unrecognised line is a paragraph, because a document build must not die on a
stray character. The point is that the same text produces the same .docx and
the same .pptx on every machine, with no renderer in the loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- inline runs


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    strike: bool = False
    link: str = ""


_INLINE = re.compile(
    r"""(?P<esc>\\.)
      | (?P<code>`+)(?P<code_body>.+?)(?P=code)
      | (?P<img>!\[(?P<img_alt>[^\]]*)\]\((?P<img_url>[^)\s]+)\))
      | \[(?P<link_text>[^\]]+)\]\((?P<link_url>[^)\s]+)\)
      | (?P<strong>\*\*|__)(?P<strong_body>.+?)(?P=strong)
      | (?P<strike>~~)(?P<strike_body>.+?)~~
      | (?P<em>[*_])(?P<em_body>[^*_]+?)(?P=em)
    """,
    re.VERBOSE | re.DOTALL,
)


def inline(text: str, **state: bool | str) -> list[Run]:
    """Parse one line of inline Markdown into styled runs."""
    bold = bool(state.get("bold"))
    italic = bool(state.get("italic"))
    strike = bool(state.get("strike"))
    link = str(state.get("link") or "")
    runs: list[Run] = []

    def emit(chunk: str, *, code: bool = False, url: str = "") -> None:
        if not chunk:
            return
        runs.append(Run(chunk, bold=bold, italic=italic, code=code, strike=strike, link=url or link))

    position = 0
    for match in _INLINE.finditer(text):
        emit(text[position : match.start()])
        position = match.end()
        if match.group("esc"):
            emit(match.group("esc")[1:])
        elif match.group("code"):
            emit(match.group("code_body"), code=True)
        elif match.group("img"):
            # Inline images are block-level in every target format; keep the alt text.
            emit(match.group("img_alt"))
        elif match.group("link_text"):
            runs.extend(
                inline(match.group("link_text"), bold=bold, italic=italic, strike=strike, link=match.group("link_url"))
            )
        elif match.group("strong"):
            runs.extend(inline(match.group("strong_body"), bold=True, italic=italic, strike=strike, link=link))
        elif match.group("strike"):
            runs.extend(inline(match.group("strike_body"), bold=bold, italic=italic, strike=True, link=link))
        elif match.group("em"):
            runs.extend(inline(match.group("em_body"), bold=bold, italic=True, strike=strike, link=link))
    emit(text[position:])
    return runs


def plain(runs: list[Run]) -> str:
    return "".join(run.text for run in runs)


# --------------------------------------------------------------------- blocks


@dataclass
class Block:
    kind: str  # heading | para | list | table | quote | code | image | rule | comment
    level: int = 0  # heading depth
    runs: list[Run] = field(default_factory=list)
    items: list["ListItem"] = field(default_factory=list)
    rows: list[list[list[Run]]] = field(default_factory=list)
    header: list[list[Run]] = field(default_factory=list)
    text: str = ""  # code body, image path, comment body
    lang: str = ""
    alt: str = ""
    ordered: bool = False


@dataclass
class ListItem:
    level: int
    runs: list[Run]
    ordered: bool = False
    checked: bool | None = None


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)([-*+])\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*(\S*)\s*$")
_IMAGE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_COMMENT = re.compile(r"^\s*<!--\s*(.*?)\s*-->\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    out, cell, escaped = [], "", False
    for char in body:
        if escaped:
            cell += char
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            out.append(cell.strip())
            cell = ""
        else:
            cell += char
    out.append(cell.strip())
    return out


def parse(text: str) -> list[Block]:
    """Markdown body (no frontmatter) -> flat block list."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    buffer: list[str] = []
    index = 0

    def flush() -> None:
        nonlocal buffer
        joined = " ".join(part.strip() for part in buffer if part.strip())
        if joined:
            blocks.append(Block("para", runs=inline(joined)))
        buffer = []

    while index < len(lines):
        line = lines[index]
        fence = _FENCE.match(line)
        if fence:
            flush()
            marker, lang = fence.group(1), fence.group(2)
            index += 1
            body: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith(marker[0] * 3):
                body.append(lines[index])
                index += 1
            index += 1
            blocks.append(Block("code", text="\n".join(body), lang=lang))
            continue

        comment = _COMMENT.match(line)
        if comment:
            flush()
            blocks.append(Block("comment", text=comment.group(1)))
            index += 1
            continue

        if not line.strip():
            flush()
            index += 1
            continue

        if _RULE.match(line):
            flush()
            blocks.append(Block("rule"))
            index += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            flush()
            blocks.append(Block("heading", level=len(heading.group(1)), runs=inline(heading.group(2).strip())))
            index += 1
            continue

        image = _IMAGE.match(line)
        if image:
            flush()
            blocks.append(Block("image", text=image.group(2), alt=image.group(1)))
            index += 1
            continue

        if _QUOTE.match(line):
            flush()
            quoted: list[str] = []
            while index < len(lines) and _QUOTE.match(lines[index]):
                match = _QUOTE.match(lines[index])
                assert match is not None
                quoted.append(match.group(1))
                index += 1
            joined = " ".join(part.strip() for part in quoted if part.strip())
            blocks.append(Block("quote", runs=inline(joined)))
            continue

        if _BULLET.match(line) or _ORDERED.match(line):
            flush()
            items: list[ListItem] = []
            while index < len(lines):
                bullet = _BULLET.match(lines[index])
                ordered = None if bullet else _ORDERED.match(lines[index])
                if not bullet and not ordered:
                    following = lines[index]
                    # A lazy continuation line wraps the previous item. Anything that
                    # opens another construct ends the list instead — a directive
                    # comment swallowed as list text is invisible until the deck is open.
                    interrupts = (
                        _HEADING.match(following)
                        or _COMMENT.match(following)
                        or _RULE.match(following)
                        or _FENCE.match(following)
                        or _QUOTE.match(following)
                        or "|" in following
                    )
                    if following.strip() and items and not interrupts:
                        items[-1].runs.extend(inline(" " + following.strip()))
                        index += 1
                        continue
                    break
                match = bullet or ordered
                assert match is not None
                indent = len(match.group(1).expandtabs(4))
                body = match.group(3)
                checked = None
                task = _TASK.match(body)
                if task:
                    checked = task.group(1).lower() == "x"
                    body = task.group(2)
                items.append(
                    ListItem(level=indent // 2, runs=inline(body), ordered=ordered is not None, checked=checked)
                )
                index += 1
            blocks.append(Block("list", items=items, ordered=bool(items and items[0].ordered)))
            continue

        if "|" in line and index + 1 < len(lines) and _TABLE_SEP.match(lines[index + 1]):
            flush()
            header = [inline(cell) for cell in _cells(line)]
            index += 2
            rows: list[list[list[Run]]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append([inline(cell) for cell in _cells(lines[index])])
                index += 1
            blocks.append(Block("table", header=header, rows=rows))
            continue

        buffer.append(line)
        index += 1

    flush()
    return blocks


def normalise_levels(items: list[ListItem]) -> list[ListItem]:
    """Collapse arbitrary indent widths into contiguous 0..n nesting levels."""
    seen = sorted({item.level for item in items})
    rank = {level: order for order, level in enumerate(seen)}
    return [ListItem(rank[item.level], item.runs, item.ordered, item.checked) for item in items]
