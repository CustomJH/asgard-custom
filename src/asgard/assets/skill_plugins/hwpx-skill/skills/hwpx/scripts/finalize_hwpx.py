#!/usr/bin/env python3
"""Finalize and quality-check an HWPX file after generation or template filling.

This tool covers failure modes that basic XML validation does not catch:

* stale hp:linesegarray layout caches after text replacement
* table cells that are likely to squeeze long text into too little height
* body paragraphs after headings that lost visible indentation
* optional real Hancom Office open validation through Windows COM

Usage:
    python scripts/finalize_hwpx.py output.hwpx --strip-linesegarray --layout
    python scripts/finalize_hwpx.py output.hwpx --hancom
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree


NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
}

LINESEG_RE = re.compile(
    rb"<hp:linesegarray\b[^>]*/>|<hp:linesegarray\b[^>]*>.*?</hp:linesegarray>",
    re.DOTALL,
)


def strip_linesegarray_from_bytes(data: bytes) -> tuple[bytes, int]:
    """Remove cached line-layout arrays from one XML payload."""

    new_data, count = LINESEG_RE.subn(b"", data)
    return new_data, count


def strip_linesegarray(hwpx_path: str | Path, output_path: str | Path | None = None) -> int:
    """Strip hp:linesegarray elements from all Contents/*.xml files.

    HWPX files edited outside Hancom can keep stale line layout caches. Hancom
    may then show a corruption/restore warning even when XML is well-formed.
    Removing these caches lets Hancom recalculate layout on open.
    """

    src = Path(hwpx_path)
    dst = Path(output_path) if output_path else src
    total_removed = 0

    fd, tmp_name = tempfile.mkstemp(suffix=".hwpx", dir=str(dst.parent))
    os.close(fd)
    tmp = Path(tmp_name)

    try:
        with zipfile.ZipFile(src, "r") as zin:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename.startswith("Contents/") and item.filename.endswith(".xml"):
                        data, removed = strip_linesegarray_from_bytes(data)
                        total_removed += removed

                    if item.filename == "mimetype":
                        zout.writestr(item, data, compress_type=zipfile.ZIP_STORED)
                    else:
                        zout.writestr(item, data)

        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            tmp.unlink()

    return total_removed


def _text_of(elem: etree._Element) -> str:
    return "".join(elem.xpath(".//hp:t/text()", namespaces=NS))


def _paragraph_texts(elem: etree._Element) -> list[str]:
    return [_text_of(p).strip() for p in elem.xpath("./hp:p", namespaces=NS)]


def _cell_addr(tc: etree._Element) -> tuple[int, int]:
    addr = tc.find("hp:cellAddr", NS)
    if addr is None:
        return (-1, -1)
    return int(addr.get("rowAddr", "-1")), int(addr.get("colAddr", "-1"))


def _cell_size(tc: etree._Element) -> tuple[int, int]:
    size = tc.find("hp:cellSz", NS)
    if size is None:
        return (0, 0)
    return int(size.get("width", "0")), int(size.get("height", "0"))


def _weighted_len(text: str) -> int:
    """Approximate visual width: CJK/fullwidth chars count heavier than ASCII."""

    total = 0
    for ch in text:
        total += 2 if ord(ch) > 127 else 1
    return total


def _is_heading(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    return bool(
        re.match(r"^(\[|【|▶|\d+[.)]\s|[가-힣][.)]\s|[A-Z][.)]\s|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.)]\s)", text)
        or len(text) <= 18 and text.endswith(":")
    )


def _has_visible_indent(text: str) -> bool:
    return bool(re.match(r"^(\s+|[-*]\s+|[▶※]\s*|\d+[.)]\s+|[가-힣][.)]\s+)", text))


def find_layout_warnings(
    hwpx_path: str | Path,
    *,
    max_cell_paragraph_chars: int = 90,
    min_long_cell_height: int = 6000,
) -> list[dict[str, Any]]:
    """Find likely text-format and table-layout risks.

    These are warnings, not schema errors. They point to areas that need human
    layout review or template-specific row height adjustments.
    """

    warnings: list[dict[str, Any]] = []

    with zipfile.ZipFile(hwpx_path, "r") as zf:
        section_names = [
            name for name in zf.namelist()
            if name.startswith("Contents/section") and name.endswith(".xml")
        ]

        for section_name in section_names:
            root = etree.fromstring(zf.read(section_name))

            # Table density checks.
            for table_index, tbl in enumerate(root.xpath(".//hp:tbl", namespaces=NS), start=1):
                for tc in tbl.xpath(".//hp:tc", namespaces=NS):
                    row, col = _cell_addr(tc)
                    width, height = _cell_size(tc)
                    paras = [p for p in _paragraph_texts(tc) if p]
                    if not paras:
                        continue

                    text = " ".join(paras)
                    longest_para = max((_weighted_len(p) for p in paras), default=0)
                    estimated_lines = max(1, math.ceil(_weighted_len(text) / 80))

                    if len(paras) == 1 and longest_para > max_cell_paragraph_chars:
                        warnings.append({
                            "type": "long_single_paragraph_cell",
                            "section": section_name,
                            "table": table_index,
                            "row": row,
                            "col": col,
                            "height": height,
                            "message": (
                                "Long table-cell text is in one paragraph; split it into "
                                "multiple paragraphs/list items before relying on wrapping."
                            ),
                            "sample": text[:120],
                        })

                    if (longest_para > max_cell_paragraph_chars or estimated_lines >= 3) and height < min_long_cell_height:
                        warnings.append({
                            "type": "short_row_for_long_cell",
                            "section": section_name,
                            "table": table_index,
                            "row": row,
                            "col": col,
                            "height": height,
                            "message": (
                                "Table row height is likely too small for the amount of text; "
                                "increase every cell height in the row and update table hp:sz height."
                            ),
                            "sample": text[:120],
                        })

                    if len(paras) >= 3 and height < min_long_cell_height:
                        warnings.append({
                            "type": "multi_paragraph_short_cell",
                            "section": section_name,
                            "table": table_index,
                            "row": row,
                            "col": col,
                            "height": height,
                            "message": "Multi-paragraph cell has a short row height.",
                            "sample": text[:120],
                        })

            # Visible indentation checks for top-level paragraphs after headings.
            top_paras = root.xpath("./hp:p[not(.//hp:tbl)]", namespaces=NS)
            prev_text = ""
            for p in top_paras:
                text = _text_of(p)
                if not text:
                    continue
                if _is_heading(prev_text) and not _is_heading(text) and not _has_visible_indent(text):
                    warnings.append({
                        "type": "body_paragraph_without_visible_indent",
                        "section": section_name,
                        "message": (
                            "Body paragraph after a heading has no visible indent/list marker. "
                            "Use the template body paragraph style or add a list/indent."
                        ),
                        "heading": prev_text[:80],
                        "sample": text[:120],
                    })
                prev_text = text

    return warnings


def hancom_open_check(hwpx_path: str | Path, *, visible: bool = False) -> tuple[bool, str]:
    """Try to open the HWPX file with Hancom Office through Windows COM."""

    if os.name != "nt":
        return False, "Hancom COM validation is only available on Windows."

    try:
        import win32com.client  # type: ignore
    except ImportError:
        return False, "pywin32 is not installed; install pywin32 to use --hancom."

    hwp = None
    try:
        hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
        try:
            hwp.XHwpWindows.Item(0).Visible = visible
        except Exception:
            pass
        try:
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception:
            pass
        ok = bool(hwp.Open(str(Path(hwpx_path).resolve()), "", ""))
        return (ok, "Hancom Open returned True." if ok else "Hancom Open returned False.")
    except Exception as exc:  # pragma: no cover - requires Hancom/COM
        return False, f"Hancom COM open failed: {exc}"
    finally:
        if hwp is not None:
            try:
                hwp.Quit()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize and quality-check an HWPX file")
    parser.add_argument("input", help="Path to .hwpx file")
    parser.add_argument("-o", "--output", help="Output path when stripping line layout caches")
    parser.add_argument(
        "--strip-linesegarray",
        action="store_true",
        help="Remove hp:linesegarray layout caches so Hancom recalculates layout",
    )
    parser.add_argument("--layout", action="store_true", help="Run table density and text indentation warnings")
    parser.add_argument("--hancom", action="store_true", help="Open the file with Hancom Office through Windows COM")
    parser.add_argument("--visible", action="store_true", help="Show the Hancom window during --hancom validation")
    parser.add_argument("--json", dest="json_path", help="Write machine-readable report JSON")
    args = parser.parse_args()

    report: dict[str, Any] = {
        "input": str(Path(args.input).resolve()),
        "status": "PASS",
        "actions": [],
        "warnings": [],
        "errors": [],
    }

    target = Path(args.output) if args.output else Path(args.input)

    if args.strip_linesegarray:
        removed = strip_linesegarray(args.input, target)
        report["actions"].append({"strip_linesegarray_removed": removed, "output": str(target.resolve())})

    check_path = target if args.strip_linesegarray else Path(args.input)

    if args.layout:
        layout_warnings = find_layout_warnings(check_path)
        report["warnings"].extend(layout_warnings)

    if args.hancom:
        ok, message = hancom_open_check(check_path, visible=args.visible)
        report["hancom"] = {"ok": ok, "message": message}
        if not ok:
            report["errors"].append(message)

    if report["errors"]:
        report["status"] = "FAIL"
    elif report["warnings"]:
        report["status"] = "WARN"

    print(f"HWPX FINALIZE: {report['status']}")
    for action in report["actions"]:
        print(f"  action: {action}")
    for warning in report["warnings"][:30]:
        location = ""
        if "table" in warning:
            location = f" table={warning['table']} row={warning['row']} col={warning['col']}"
        print(f"  warning: {warning['type']}{location}: {warning['message']}")
    if len(report["warnings"]) > 30:
        print(f"  warning: ... {len(report['warnings']) - 30} more")
    for error in report["errors"]:
        print(f"  error: {error}", file=sys.stderr)

    if args.json_path:
        Path(args.json_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    sys.exit(1 if report["status"] == "FAIL" else 0)


if __name__ == "__main__":
    main()
