"""User-composable template registry and the placeholder engine behind it.

A template is a directory, not a file format. That is the whole design: a user
adds one by making a folder, and the same folder works whether the skeleton is
Markdown or a real .docx someone handed them from their employer.

    <name>/
      template.toml     manifest — kind, field schema, theme defaults (required)
      body.md           Markdown skeleton with {{placeholders}}   (md-backed)
      base.docx|.pptx|.xlsx   an existing Office file to fill in  (file-backed)
      values.example.json     a filled-in example, used by `template check`

Lookup order is most-specific-first, so a project can shadow a global template
and a user can shadow a bundled one by name alone.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .specs import home

KINDS = ("docx", "pptx", "xlsx", "md")
FIELD_TYPES = ("text", "multiline", "date", "number", "list", "table", "image", "bool")
BUNDLED = Path(__file__).resolve().parents[1].parent / "assets" / "templates"


# ------------------------------------------------------------------- rendering

_TAG = re.compile(r"\{\{\s*([#^/&]?)\s*([A-Za-z0-9_.\-]+|\.)\s*\}\}")


def _lookup(stack: list, path: str):
    if path == ".":
        return stack[-1]
    for scope in reversed(stack):
        if not isinstance(scope, dict):
            continue
        cursor, ok = scope, True
        for part in path.split("."):
            if isinstance(cursor, dict) and part in cursor:
                cursor = cursor[part]
            else:
                ok = False
                break
        if ok:
            return cursor
    return None


def _truthy(value) -> bool:
    return not (value is None or value is False or value == "" or value == [] or value == {})


def stringify(value) -> str:
    if value is None or value is False:
        return ""
    if value is True:
        return "true"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (list, tuple)):
        return ", ".join(stringify(item) for item in value)
    return str(value)


def render(text: str, values: dict, *, strict: bool = False) -> tuple[str, list[str]]:
    """Expand `{{key}}`, `{{#section}}`, and `{{^inverted}}`. Returns (text, missing keys)."""
    missing: list[str] = []

    def walk(body: str, stack: list) -> str:
        out, position = [], 0
        for match in _TAG.finditer(body):
            if match.start() < position:
                continue
            out.append(body[position : match.start()])
            sigil, name = match.group(1), match.group(2)
            if sigil in ("#", "^"):
                close = _find_close(body, match.end(), name)
                if close is None:
                    raise ValueError(f"unclosed template section: {{{{#{name}}}}}")
                inner, position = body[match.end() : close[0]], close[1]
                value = _lookup(stack, name)
                if sigil == "^":
                    if not _truthy(value):
                        out.append(walk(inner, stack))
                elif isinstance(value, list):
                    for item in value:
                        out.append(walk(inner, [*stack, item if isinstance(item, dict) else {".": item}]))
                elif _truthy(value):
                    out.append(walk(inner, [*stack, value if isinstance(value, dict) else {".": value}]))
                continue
            if sigil == "/":
                position = match.end()
                continue
            value = _lookup(stack, name)
            if value is None and name != ".":
                missing.append(name)
            out.append(stringify(value))
            position = match.end()
        out.append(body[position:])
        return "".join(out)

    def _find_close(body: str, start: int, name: str) -> tuple[int, int] | None:
        depth, cursor = 1, start
        for match in _TAG.finditer(body, start):
            if match.group(2) != name:
                continue
            if match.group(1) in ("#", "^"):
                depth += 1
            elif match.group(1) == "/":
                depth -= 1
                if depth == 0:
                    return match.start(), match.end()
            cursor = match.end()
        return None

    result = walk(text, [values])
    if strict and missing:
        raise ValueError("unresolved template fields: " + ", ".join(sorted(set(missing))))
    return result, sorted(set(missing))


def placeholders(text: str) -> list[str]:
    """Every `{{name}}` referenced by a skeleton, sections included, in first-seen order."""
    seen: list[str] = []
    for match in _TAG.finditer(text):
        name = match.group(2)
        if name != "." and match.group(1) != "/" and name not in seen:
            seen.append(name)
    return seen


# -------------------------------------------------------------------- registry


@dataclass
class Field:
    key: str
    label: str = ""
    type: str = "text"
    required: bool = False
    example: object = None
    description: str = ""

    @classmethod
    def resolve(cls, raw: dict) -> "Field":
        key = str(raw.get("key") or "").strip()
        if not key:
            raise ValueError("template field needs a key")
        kind = str(raw.get("type") or "text").strip().lower()
        if kind not in FIELD_TYPES:
            raise ValueError(f"unknown field type for {key!r}: {kind} (expected one of {', '.join(FIELD_TYPES)})")
        return cls(
            key=key,
            label=str(raw.get("label") or key),
            type=kind,
            required=bool(raw.get("required")),
            example=raw.get("example"),
            description=str(raw.get("description") or ""),
        )


@dataclass
class Template:
    name: str
    kind: str
    root: Path
    origin: str  # project | global | bundled
    title: str = ""
    description: str = ""
    genre: str = ""
    language: str = ""
    fields: list[Field] = field(default_factory=list)
    theme: dict = field(default_factory=dict)
    page: dict = field(default_factory=dict)
    defaults: dict = field(default_factory=dict)

    @property
    def body(self) -> Path | None:
        """The skeleton. Markdown for documents and decks, YAML for workbooks."""
        for name in ("body.md", "body.yaml", "body.yml"):
            candidate = self.root / name
            if candidate.is_file():
                return candidate
        return None

    @property
    def base(self) -> Path | None:
        for suffix in (".docx", ".pptx", ".xlsx", ".dotx", ".potx"):
            candidate = self.root / f"base{suffix}"
            if candidate.is_file():
                return candidate
        return None

    @property
    def example(self) -> Path | None:
        candidate = self.root / "values.example.json"
        return candidate if candidate.is_file() else None

    def sample_values(self) -> dict:
        return {item.key: item.example for item in self.fields if item.example is not None}

    def summary(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "origin": self.origin,
            "title": self.title,
            "description": self.description,
            "genre": self.genre,
            "language": self.language,
            "backing": "file" if self.base else ("markdown" if self.body else "none"),
            "fields": [
                {
                    "key": item.key,
                    "label": item.label,
                    "type": item.type,
                    "required": item.required,
                    "description": item.description,
                }
                for item in self.fields
            ],
            "path": str(self.root),
        }


def _load(root: Path, origin: str) -> Template:
    manifest = root / "template.toml"
    if not manifest.is_file():
        raise ValueError(f"template.toml is missing: {root}")
    with manifest.open("rb") as handle:
        raw = tomllib.load(handle)
    if int(raw.get("schema") or 0) != 1:
        raise ValueError(f"template schema must be 1: {root}")
    name = str(raw.get("name") or root.name).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", name):
        raise ValueError(f"template name must match [a-z0-9][a-z0-9._-]{{0,63}}: {name}")
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"template kind must be one of {', '.join(KINDS)}: {root}")
    fields = [Field.resolve(item) for item in raw.get("fields") or [] if isinstance(item, dict)]
    duplicates = {item.key for item in fields if [f.key for f in fields].count(item.key) > 1}
    if duplicates:
        raise ValueError(f"duplicate template fields: {', '.join(sorted(duplicates))}")
    return Template(
        name=name,
        kind=kind,
        root=root,
        origin=origin,
        title=str(raw.get("title") or name),
        description=str(raw.get("description") or ""),
        genre=str(raw.get("genre") or ""),
        language=str(raw.get("language") or ""),
        fields=fields,
        theme=dict(raw.get("theme") or {}),
        page=dict(raw.get("page") or {}),
        defaults=dict(raw.get("defaults") or {}),
    )


def search_paths(root: Path | None = None) -> list[tuple[Path, str]]:
    project = (root or Path.cwd()) / ".asgard" / "office" / "templates"
    return [(project, "project"), (home() / "office" / "templates", "global"), (BUNDLED, "bundled")]


def discover(root: Path | None = None) -> tuple[list[Template], list[str]]:
    """All readable templates, nearest scope winning. Returns (templates, problems)."""
    found: dict[str, Template] = {}
    problems: list[str] = []
    for base, origin in search_paths(root):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name.startswith(".") or child.is_symlink():
                continue
            try:
                template = _load(child, origin)
            except (ValueError, OSError, tomllib.TOMLDecodeError) as exc:
                problems.append(f"{origin}:{child.name}: {exc}")
                continue
            found.setdefault(template.name, template)
    return sorted(found.values(), key=lambda item: (item.kind, item.name)), problems


def resolve(name: str, root: Path | None = None) -> Template:
    for template in discover(root)[0]:
        if template.name == name:
            return template
    raise ValueError(f"template not found: {name}")


def check(template: Template, values: dict) -> list[str]:
    """Field-schema violations, in the order a user would fix them."""
    problems: list[str] = []
    for item in template.fields:
        present = item.key in values and _truthy(values[item.key])
        if item.required and not present:
            problems.append(f"required field missing: {item.key} ({item.label})")
            continue
        if not present:
            continue
        value = values[item.key]
        if item.type == "number" and not isinstance(value, (int, float)):
            problems.append(f"field {item.key} must be a number, got {type(value).__name__}")
        elif item.type == "bool" and not isinstance(value, bool):
            problems.append(f"field {item.key} must be true/false, got {type(value).__name__}")
        elif item.type in ("list", "table") and not isinstance(value, list):
            problems.append(f"field {item.key} must be a list, got {type(value).__name__}")
        elif item.type == "table" and any(not isinstance(row, dict) for row in value):
            problems.append(f"field {item.key} must be a list of row mappings")
        elif item.type == "image" and not Path(str(value)).is_file():
            problems.append(f"field {item.key} points at a missing image: {value}")
    declared = {item.key for item in template.fields}
    if declared:
        for key in values:
            if key not in declared:
                problems.append(f"value not declared by the template (typo?): {key}")
    return problems
