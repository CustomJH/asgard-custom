#!/usr/bin/env python3
"""Python lint/spec path adapted from google-labs-code/design.md.

Copyright 2026 Google LLC. Licensed under Apache-2.0.
Modified by the Asgard project: Python implementation; upstream diff/export are omitted.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from coloraide import Color

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_TOKEN_DEPTH = 20
MAX_REFERENCE_DEPTH = 10
REF = re.compile(r"^\{([a-zA-Z0-9._-]+)\}$")
DIMENSION = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)(px|em|rem)$")
KNOWN_KEYS = ("version", "name", "description", "colors", "typography", "rounded", "spacing", "components")
TYPOGRAPHY_PROPS = {
    "fontFamily",
    "fontSize",
    "fontWeight",
    "lineHeight",
    "letterSpacing",
    "fontFeature",
    "fontVariation",
}
COMPONENT_PROPS = {"backgroundColor", "textColor", "typography", "rounded", "padding", "size", "height", "width"}
SECTION_ORDER = (
    "Overview",
    "Colors",
    "Typography",
    "Layout",
    "Elevation & Depth",
    "Shapes",
    "Components",
    "Do's and Don'ts",
)
SECTION_ALIASES = {"Brand & Style": "Overview", "Layout & Spacing": "Layout", "Elevation": "Elevation & Depth"}
MD3_FAMILIES = {"primary", "secondary", "tertiary", "error", "surface", "background", "outline"}


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader: UniqueLoader, node: yaml.Node, deep: bool = False) -> dict:
    result: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate YAML key: {key}", key_node.start_mark)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _finding(severity: str, message: str, path: str | None = None) -> dict[str, str]:
    row = {"severity": severity, "message": message}
    if path:
        row["path"] = path
    return row


def _extract(content: str) -> tuple[list[str], list[str]]:
    lines = content.splitlines()
    blocks: list[str] = []
    headings: list[str] = []
    frontmatter_end = -1
    if lines and lines[0] == "---":
        try:
            frontmatter_end = lines.index("---", 1)
            blocks.append("\n".join(lines[1:frontmatter_end]))
        except ValueError:
            pass

    index = 0
    while index < len(lines):
        if index <= frontmatter_end:
            index = frontmatter_end + 1
            continue
        line = lines[index]
        match = re.match(r"^(```|~~~)(yaml|yml)?(?:\s.*)?$", line, re.I)
        if match:
            fence, language = match.groups()
            end = index + 1
            while end < len(lines) and not lines[end].startswith(fence):
                end += 1
            if end < len(lines) and language:
                blocks.append("\n".join(lines[index + 1 : end]))
            index = end + 1
            continue
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            headings.append(heading.group(1))
        index += 1
    return blocks, headings


def _parse(content: str) -> tuple[dict[str, Any] | None, list[str], str | None]:
    blocks, headings = _extract(content)
    if not blocks:
        return None, headings, "No YAML content found. Expected frontmatter (---) or fenced yaml code blocks."
    merged: dict[str, Any] = {}
    for block in blocks:
        try:
            value = yaml.load(block, Loader=UniqueLoader)
        except yaml.YAMLError as exc:
            return None, headings, f"YAML parse error: {exc}"
        if value is None:
            continue
        if not isinstance(value, dict):
            return None, headings, "YAML content must be an object."
        duplicate = set(merged).intersection(value)
        if duplicate:
            return None, headings, f"Section '{sorted(duplicate)[0]}' is defined in multiple YAML blocks."
        merged.update(value)
    return merged, headings, None


def _leaves(value: Any, prefix: str = "", depth: int = 0):
    if depth > MAX_TOKEN_DEPTH:
        raise ValueError(f"token nesting depth exceeds {MAX_TOKEN_DEPTH}")
    if not isinstance(value, dict):
        return
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, dict):
            yield from _leaves(child, path, depth + 1)
        else:
            yield path, child


def _as_map(raw: Any, path: str, findings: list[dict[str, str]]) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        findings.append(_finding("error", "Expected a YAML object.", path))
        return {}
    return raw


def _split_mix(raw: str) -> list[str]:
    parts: list[str] = []
    start = depth = 0
    for index, char in enumerate(raw):
        depth += char == "("
        depth -= char == ")"
        if char == "," and depth == 0:
            parts.append(raw[start:index].strip())
            start = index + 1
    parts.append(raw[start:].strip())
    return parts


def _color_mix(raw: str) -> Color | None:
    if not raw.lower().startswith("color-mix(") or not raw.endswith(")"):
        return None
    parts = _split_mix(raw[10:-1])
    if len(parts) != 3 or not parts[0].lower().startswith("in "):
        return None
    space = parts[0][3:].split()[0]

    def operand(value: str) -> tuple[Color | None, float | None]:
        match = re.match(r"^(.*?)(?:\s+(\d+(?:\.\d+)?)%)?$", value)
        if not match:
            return None, None
        return _color(match.group(1).strip()), float(match.group(2)) if match.group(2) else None

    first, first_percent = operand(parts[1])
    second, second_percent = operand(parts[2])
    if first is None or second is None:
        return None
    if first_percent is None and second_percent is None:
        second_percent = 50.0
    elif first_percent is None:
        first_percent = 100.0 - second_percent
    elif second_percent is None:
        second_percent = 100.0 - first_percent
    total = first_percent + second_percent
    if total <= 0:
        return None
    try:
        return first.mix(second, percent=second_percent / total, space=space)
    except ValueError:
        return None


def _color(raw: Any) -> Color | None:
    if not isinstance(raw, str) or REF.fullmatch(raw):
        return None
    mixed = _color_mix(raw)
    if mixed is not None:
        return mixed
    try:
        return Color(raw)
    except ValueError:
        return None


def _resolve(symbols: dict[str, Any], path: str, seen: set[str] | None = None, depth: int = 0) -> Any:
    if depth > MAX_REFERENCE_DEPTH:
        return None
    seen = seen or set()
    if path in seen or path not in symbols:
        return None
    seen.add(path)
    value = symbols[path]
    match = REF.fullmatch(value) if isinstance(value, str) else None
    return _resolve(symbols, match.group(1), seen, depth + 1) if match else value


def _family(name: str) -> str:
    name = re.sub(r"^on-", "", name)
    name = re.sub(r"^inverse-", "", name)
    name = re.sub(r"^on-", "", name)
    name = re.sub(r"-(?:container.*|fixed.*|dim|bright|tint|variant)$", "", name)
    return name


def _distance(left: str, right: str) -> int:
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        next_row = [i]
        for j, b in enumerate(right, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = next_row
    return row[-1]


def lint(content: str) -> dict[str, Any]:
    raw, headings, parse_error = _parse(content)
    if parse_error:
        finding = _finding("warning", parse_error)
        return {"findings": [finding], "summary": {"errors": 0, "warnings": 1, "infos": 0}}
    assert raw is not None
    findings: list[dict[str, str]] = []
    colors = _as_map(raw.get("colors"), "colors", findings)
    typography = _as_map(raw.get("typography"), "typography", findings)
    rounded = _as_map(raw.get("rounded"), "rounded", findings)
    spacing = _as_map(raw.get("spacing"), "spacing", findings)
    components = _as_map(raw.get("components"), "components", findings)
    symbols: dict[str, Any] = {}
    resolved_colors: dict[str, Color] = {}

    try:
        color_items = list(_leaves(colors))
        rounded_items = list(_leaves(rounded))
        spacing_items = list(_leaves(spacing))
    except ValueError as exc:
        findings.append(_finding("error", str(exc)))
        color_items = rounded_items = spacing_items = []

    for name, value in color_items:
        path = f"colors.{name}"
        symbols[path] = value
        if not (isinstance(value, str) and REF.fullmatch(value)):
            parsed = _color(value)
            if parsed is None:
                findings.append(_finding("error", f"'{value}' is not a valid CSS color.", path))
            else:
                resolved_colors[name] = parsed
    for root, items in (("rounded", rounded_items), ("spacing", spacing_items)):
        for name, value in items:
            path = f"{root}.{name}"
            symbols[path] = value
            if root == "rounded" and not (isinstance(value, str) and (DIMENSION.fullmatch(value) or REF.fullmatch(value))):
                findings.append(_finding("error", f"'{value}' is not a valid px, em, or rem dimension.", path))
            if root == "spacing" and not (
                isinstance(value, (int, float)) or isinstance(value, str) and (DIMENSION.fullmatch(value) or REF.fullmatch(value))
            ):
                findings.append(_finding("error", f"'{value}' is not a valid spacing value.", path))

    for name, props in typography.items():
        path = f"typography.{name}"
        if not isinstance(props, dict):
            findings.append(_finding("error", "Typography token must be an object.", path))
            continue
        symbols[path] = props
        for prop, value in props.items():
            if prop not in TYPOGRAPHY_PROPS:
                continue
            prop_path = f"{path}.{prop}"
            if prop in {"fontSize", "letterSpacing"} and not (
                isinstance(value, str) and (DIMENSION.fullmatch(value) or REF.fullmatch(value))
            ):
                findings.append(_finding("error", f"'{value}' is not a valid dimension.", prop_path))
            elif prop == "lineHeight" and not (
                isinstance(value, (int, float))
                or isinstance(value, str) and (DIMENSION.fullmatch(value) or REF.fullmatch(value) or value.replace(".", "", 1).isdigit())
            ):
                findings.append(_finding("error", f"'{value}' is not a valid line height.", prop_path))
            elif prop == "fontWeight":
                try:
                    float(value)
                except (TypeError, ValueError):
                    findings.append(_finding("error", f"'{value}' is not a valid font weight.", prop_path))

    for name, value in color_items:
        if isinstance(value, str) and REF.fullmatch(value):
            resolved = _resolve(symbols, f"colors.{name}")
            parsed = _color(resolved)
            if parsed is not None:
                resolved_colors[name] = parsed

    referenced: set[str] = set()
    for name, props in components.items():
        path = f"components.{name}"
        if not isinstance(props, dict):
            findings.append(_finding("error", "Component token must be an object.", path))
            continue
        resolved_props: dict[str, Any] = {}
        for prop, value in props.items():
            prop_path = f"{path}.{prop}"
            if prop not in COMPONENT_PROPS:
                findings.append(_finding("warning", f"'{prop}' is not a recognized component sub-token.", prop_path))
            match = REF.fullmatch(value) if isinstance(value, str) else None
            if match:
                referenced.add(match.group(1))
                resolved = _resolve(symbols, match.group(1))
                if resolved is None:
                    findings.append(_finding("error", f"Reference {value} does not resolve to any defined token.", path))
                resolved_props[prop] = resolved
            else:
                resolved_props[prop] = value
        background = _color(resolved_props.get("backgroundColor"))
        text = _color(resolved_props.get("textColor"))
        if background is not None and text is not None:
            ratio = background.contrast(text, method="wcag21")
            if ratio < 4.5:
                findings.append(
                    _finding("warning", f"textColor on backgroundColor has contrast ratio {ratio:.2f}:1, below WCAG AA 4.5:1.", path)
                )

    if colors and "primary" not in colors:
        findings.append(_finding("warning", "No 'primary' color defined.", "colors"))
    if colors and not typography:
        findings.append(_finding("warning", "No typography tokens defined; agents will use default fonts.", "typography"))
    if colors and not spacing:
        findings.append(_finding("info", "No spacing tokens defined; layout spacing will fall back to agent defaults.", "spacing"))
    if colors and not rounded:
        findings.append(_finding("info", "No rounded tokens defined; corner rounding will fall back to agent defaults.", "rounded"))

    referenced_families = {_family(path.removeprefix("colors.")) for path in referenced if path.startswith("colors.")}
    if components:
        for name in resolved_colors:
            family = _family(name)
            if f"colors.{name}" not in referenced and family not in referenced_families and family not in MD3_FAMILIES:
                findings.append(_finding("warning", f"'{name}' is defined but never referenced by any component.", f"colors.{name}"))

    canonical = [SECTION_ALIASES.get(name, name) for name in headings]
    duplicates = sorted({name for name in canonical if canonical.count(name) > 1})
    for name in duplicates:
        findings.append(_finding("error", f"Duplicate section heading: {name}."))
    known = [name for name in canonical if name in SECTION_ORDER]
    if any(SECTION_ORDER.index(a) > SECTION_ORDER.index(b) for a, b in zip(known, known[1:])):
        findings.append(_finding("warning", "Sections appear out of canonical order."))

    for key in raw:
        if key in KNOWN_KEYS:
            continue
        candidates = [(known_key, _distance(str(key).lower(), known_key.lower())) for known_key in KNOWN_KEYS]
        best, distance = min(candidates, key=lambda item: item[1])
        if distance <= 2:
            findings.append(_finding("warning", f'Unknown key "{key}" — did you mean "{best}"?', str(key)))

    counts = {
        "colors": len(resolved_colors),
        "typography": len(typography),
        "rounded": len(rounded_items),
        "spacing": len(spacing_items),
        "components": len(components),
    }
    if any(counts.values()):
        findings.append(_finding("info", "Design system defines " + ", ".join(f"{value} {key}" for key, value in counts.items() if value) + "."))
    summary = {
        "errors": sum(row["severity"] == "error" for row in findings),
        "warnings": sum(row["severity"] == "warning" for row in findings),
        "infos": sum(row["severity"] == "info" for row in findings),
    }
    return {"findings": findings, "summary": summary}


def _read(path: str) -> str:
    if path == "-":
        content = sys.stdin.read(MAX_INPUT_BYTES + 1)
    else:
        with open(path, encoding="utf-8") as handle:
            content = handle.read(MAX_INPUT_BYTES + 1)
    if len(content.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    return content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="design-md-review")
    sub = parser.add_subparsers(dest="command", required=True)
    lint_parser = sub.add_parser("lint", help="validate a DESIGN.md file")
    lint_parser.add_argument("file", help="path to DESIGN.md or - for stdin")
    sub.add_parser("spec", help="print the bundled upstream specification")
    args = parser.parse_args(argv)
    if args.command == "spec":
        print(Path(__file__).parents[1].joinpath("references", "spec.md").read_text(encoding="utf-8"), end="")
        return 0
    try:
        report = lint(_read(args.file))
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
