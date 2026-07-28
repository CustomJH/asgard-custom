"""Frontmatter, units, colour, and theme resolution shared by every Sága lane."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

try:  # pyyaml ships with Asgard; the fallback keeps a vendored copy runnable alone.
    import yaml
except ImportError:  # pragma: no cover - exercised only on a stripped install
    yaml = None  # type: ignore[assignment]

_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_HEX = re.compile(r"\A#?([0-9a-fA-F]{6})\Z")


def home() -> Path:
    """Asgard's global directory, mirroring settings.global_dir without importing it."""
    override = os.environ.get("ASGARD_HOME")
    if override:
        return Path(override)
    return Path(os.environ.get("HOME") or os.path.expanduser("~")) / ".asgard"


def _mini_yaml(text: str) -> dict:
    """Flat `key: value` fallback when pyyaml is absent. Nested blocks are skipped."""
    out: dict = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or line[:1] in (" ", "\t"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        raw = value.strip()
        if raw in ("true", "false"):
            out[key.strip()] = raw == "true"
        elif raw.lstrip("-").isdigit():
            out[key.strip()] = int(raw)
        else:
            out[key.strip()] = raw.strip("\"'")
    return out


# `title: {{name}}` is a YAML flow mapping, not a string, so an unquoted
# placeholder makes the front matter fail to parse before it can be filled in.
# Quoting is the correct authoring form and the skeletons emit it — but a
# hand-written spec should not die on a rule nobody told the author about.
_BARE_PLACEHOLDER = re.compile(r"^(\s*[\w.\-]+:[ \t]+)(?![\"'])(.*\{\{.*)$", re.M)


def _quote_placeholders(text: str) -> str:
    def wrap(match: re.Match) -> str:
        value = match.group(2).rstrip()
        return f'{match.group(1)}"{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'

    return _BARE_PLACEHOLDER.sub(wrap, text)


def load_yaml(text: str) -> dict:
    if not text.strip():
        return {}
    if yaml is None:
        return _mini_yaml(text)
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        loaded = yaml.safe_load(_quote_placeholders(text))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("spec front matter must be a mapping")
    return loaded


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (metadata, body). A document without front matter is still valid."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    return load_yaml(match.group(1)), text[match.end() :]


def load_data(path: Path) -> dict:
    """Values file for a template render — JSON, or YAML when pyyaml is present."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        loaded = load_yaml(text)
    else:
        loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise ValueError(f"values file must be a mapping: {path}")
    return loaded


# ----------------------------------------------------------------- dimensions

_UNITS = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72.0, "px": 25.4 / 96.0}

PAGE_SIZES_MM = {
    "a4": (210.0, 297.0),
    "a3": (297.0, 420.0),
    "a5": (148.0, 210.0),
    "letter": (215.9, 279.4),
    "legal": (215.9, 355.6),
    "tabloid": (279.4, 431.8),
    "b5": (176.0, 250.0),
}

SLIDE_SIZES_IN = {
    "16x9": (13.333, 7.5),
    "16:9": (13.333, 7.5),
    "widescreen": (13.333, 7.5),
    "4x3": (10.0, 7.5),
    "4:3": (10.0, 7.5),
    "a4": (11.69, 8.27),
}


def mm(value: object, fallback: float) -> float:
    """Parse a length into millimetres. Bare numbers are already millimetres."""
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    for suffix, factor in _UNITS.items():
        if text.endswith(suffix):
            head = text[: -len(suffix)].strip()
            try:
                return float(head) * factor
            except ValueError:
                return fallback
    try:
        return float(text)
    except ValueError:
        return fallback


def hex_color(value: object, fallback: str) -> str:
    match = _HEX.match(str(value or "").strip()) if value is not None else None
    return match.group(1).upper() if match else fallback


# ---------------------------------------------------------------------- theme


@dataclass
class Theme:
    """One palette + type scale, shared by the document and deck lanes.

    Defaults are deliberately neutral: a document that never declares a theme
    should read as a plain professional document, not as a styled artefact.
    """

    primary: str = "1F2933"
    secondary: str = "52606D"
    accent: str = "9A3412"
    background: str = "FFFFFF"
    surface: str = "F5F7FA"
    text: str = "1F2933"
    muted: str = "6B7684"  # 4.6:1 on white — the WCAG body floor, checked in tests
    font_head: str = "Calibri"
    font_body: str = "Calibri"
    font_mono: str = "Consolas"
    font_cjk: str = ""  # w:eastAsia — empty means "same as the Latin face"
    size_title: float = 40.0
    size_h1: float = 20.0
    size_h2: float = 15.0
    size_h3: float = 12.5
    size_body: float = 11.0
    size_caption: float = 9.0
    line_spacing: float = 1.15

    @classmethod
    def resolve(cls, raw: object) -> "Theme":
        theme = cls()
        if not isinstance(raw, dict):
            return theme
        for name in ("primary", "secondary", "accent", "background", "surface", "text", "muted"):
            if name in raw:
                setattr(theme, name, hex_color(raw[name], getattr(theme, name)))
        for name in ("font_head", "font_body", "font_mono", "font_cjk"):
            if raw.get(name):
                setattr(theme, name, str(raw[name]))
        if raw.get("font"):  # one font for everything
            theme.font_head = theme.font_body = str(raw["font"])
        for name in ("size_title", "size_h1", "size_h2", "size_h3", "size_body", "size_caption", "line_spacing"):
            if name in raw:
                try:
                    setattr(theme, name, float(raw[name]))
                except (TypeError, ValueError):
                    pass
        return theme


@dataclass
class PageSetup:
    width_mm: float = 210.0
    height_mm: float = 297.0
    top_mm: float = 25.4
    bottom_mm: float = 25.4
    left_mm: float = 25.4
    right_mm: float = 25.4
    landscape: bool = False

    @classmethod
    def resolve(cls, raw: object) -> "PageSetup":
        page = cls()
        if not isinstance(raw, dict):
            return page
        size = str(raw.get("size") or "a4").strip().lower()
        if size in PAGE_SIZES_MM:
            page.width_mm, page.height_mm = PAGE_SIZES_MM[size]
        page.landscape = str(raw.get("orientation") or "").strip().lower() == "landscape"
        if page.landscape:
            page.width_mm, page.height_mm = page.height_mm, page.width_mm
        margins = raw.get("margins")
        if isinstance(margins, (int, float, str)):
            every = mm(margins, page.top_mm)
            page.top_mm = page.bottom_mm = page.left_mm = page.right_mm = every
        elif isinstance(margins, dict):
            page.top_mm = mm(margins.get("top"), page.top_mm)
            page.bottom_mm = mm(margins.get("bottom"), page.bottom_mm)
            page.left_mm = mm(margins.get("left"), page.left_mm)
            page.right_mm = mm(margins.get("right"), page.right_mm)
        return page


@dataclass
class DocMeta:
    title: str = ""
    subtitle: str = ""
    author: str = ""
    date: str = ""
    company: str = ""
    status: str = ""
    language: str = ""
    toc: bool = False
    number_headings: bool = False
    cover: bool = False
    header: str = ""
    footer: str = ""
    template: str = ""
    theme: Theme = field(default_factory=Theme)
    page: PageSetup = field(default_factory=PageSetup)
    extra: dict = field(default_factory=dict)

    @classmethod
    def resolve(cls, raw: dict) -> "DocMeta":
        meta = cls()
        for name in (
            "title",
            "subtitle",
            "author",
            "date",
            "company",
            "status",
            "language",
            "header",
            "footer",
            "template",
        ):
            if raw.get(name) is not None:
                setattr(meta, name, str(raw[name]))
        meta.toc = bool(raw.get("toc"))
        meta.number_headings = bool(raw.get("number_headings") or raw.get("numbered"))
        meta.cover = bool(raw.get("cover"))
        meta.theme = Theme.resolve(raw.get("theme"))
        meta.page = PageSetup.resolve(raw.get("page"))
        known = {
            "title",
            "subtitle",
            "author",
            "date",
            "company",
            "status",
            "language",
            "header",
            "footer",
            "template",
            "toc",
            "number_headings",
            "numbered",
            "cover",
            "theme",
            "page",
        }
        meta.extra = {key: value for key, value in raw.items() if key not in known}
        return meta
