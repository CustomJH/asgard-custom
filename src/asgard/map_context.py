"""Bounded, task-relevant context derived from the tracked Asgard project map."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .code_map import MapResult, refresh_map

CONTEXT_BUDGET = 4_000
AREA_FILE_BUDGET = 8_192
MAX_CONTEXT_ENTRIES = 32
_ENTRY = re.compile(r"^- `([^`]+)` — (.+)$")
_COMMAND = re.compile(r"^- Command: `([^`]+)` — (.+)$")
_TOKEN = re.compile(r"[\w./-]{2,}", re.UNICODE)


@dataclass(frozen=True)
class MapEntry:
    path: str
    role: str
    source: str
    managed: bool


@dataclass(frozen=True)
class AreaIssue:
    source: str
    reason: str


@dataclass(frozen=True)
class MapContext:
    text: str
    entries: tuple[MapEntry, ...]
    issues: tuple[AreaIssue, ...]
    managed_hash: str
    refresh: MapResult | None = None


def _safe_path(root: Path, raw: str) -> bool:
    path = Path(raw.rstrip("/"))
    if not path.parts or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    try:
        full = root.joinpath(path)
        full.resolve().relative_to(root.resolve())
        return full.exists() and not full.is_symlink()
    except OSError, ValueError:
        return False


def _threat(*texts: str) -> str | None:
    try:
        from .memory.policy import scan_threats

        return scan_threats(*texts)
    except Exception:
        # A missing optional memory backend must not disable map loading. The policy module itself
        # is stdlib-only, so an import failure means the scanner is unavailable rather than clean.
        return "threat scanner unavailable"


def _neutralize(value: str) -> str:
    return value.replace("<", "‹").replace(">", "›")


def validate_area_maps(root: str | os.PathLike[str]) -> tuple[tuple[MapEntry, ...], tuple[AreaIssue, ...]]:
    """Validate human/agent-owned maps without rewriting them."""
    base = Path(root).resolve()
    map_dir = base / ".asgard" / "map"
    entries: list[MapEntry] = []
    issues: list[AreaIssue] = []
    try:
        candidates = sorted(
            path for path in map_dir.glob("*.md") if path.name not in {"GRAPH.md", "INDEX.md", "PROJECT.md"}
        )
    except OSError as exc:
        return (), (AreaIssue(".asgard/map", str(exc)),)
    for path in candidates:
        rel = path.relative_to(base).as_posix()
        try:
            if path.is_symlink():
                issues.append(AreaIssue(rel, "map file is a symlink"))
                continue
            raw = path.read_bytes()
            if len(raw) > AREA_FILE_BUDGET:
                issues.append(AreaIssue(rel, f"map exceeds {AREA_FILE_BUDGET} byte budget"))
                continue
            text = raw.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            issues.append(AreaIssue(rel, str(exc)))
            continue
        blocked = _threat(text)
        if blocked:
            issues.append(AreaIssue(rel, blocked))
            continue
        title_seen = False
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            if not title_seen and line.startswith("# map: "):
                title_seen = True
                continue
            match = _ENTRY.fullmatch(line)
            if not match:
                issues.append(AreaIssue(rel, f"line {number} violates map entry grammar"))
                continue
            entry_path, role = match.groups()
            if not _safe_path(base, entry_path):
                issues.append(AreaIssue(rel, f"line {number} references a stale or unsafe path: {entry_path}"))
                continue
            entries.append(MapEntry(entry_path, role.strip(), rel, False))
        if not title_seen:
            issues.append(AreaIssue(rel, "missing `# map: <area>` title"))
    return tuple(entries), tuple(issues)


def _managed_entries(
    root: Path, text: str, source: str = ".asgard/map/PROJECT.md"
) -> tuple[list[MapEntry], list[tuple[str, str]]]:
    entries: list[MapEntry] = []
    commands: list[tuple[str, str]] = []
    for line in text.splitlines():
        command = _COMMAND.fullmatch(line)
        if command:
            if not _threat(*command.groups()):
                commands.append((command.group(1), command.group(2)))
            continue
        match = _ENTRY.fullmatch(line)
        if not match:
            continue
        path, role = match.groups()
        if path == "(none yet)" or not _safe_path(root, path) or _threat(path, role, source):
            continue
        entries.append(MapEntry(path, role.strip(), source, True))
    return entries, commands


def _score(entry: MapEntry, terms: set[str]) -> tuple[int, int, str, str]:
    haystack = f"{entry.path} {entry.role} {entry.source}".casefold()
    score = sum(8 if term in entry.path.casefold() else 3 for term in terms if term in haystack)
    if entry.managed:
        score += 1
    return (-score, 0 if entry.managed else 1, entry.source, entry.path)


def build_map_context(
    root: str | os.PathLike[str],
    query: str = "",
    *,
    refresh: bool = False,
    managed_only: bool = False,
) -> MapContext:
    """Refresh if requested, then render a safe query-relevant context fragment."""
    base = Path(root).resolve()
    # The map is an opt-in project asset created by `asgard init/map generate`. A refresh request
    # from a hook or `map context --refresh` must not seed tracked files in an unmapped repository.
    refreshed = refresh_map(base) if refresh and (base / ".asgard" / "map").is_dir() else None
    project_path = base / ".asgard" / "map" / "PROJECT.md"
    try:
        managed_text = project_path.read_text(encoding="utf-8")
    except OSError:
        managed_text = ""
    # 관계 그래프 카탈로그(GRAPH.md)는 맵의 심화 계층이다 — 존재하면 같은 엔트리 문법으로
    # 융합되어 라우트·모델·외부 서비스 증거가 동일 예산 안에서 함께 랭크된다.
    graph_path = base / ".asgard" / "map" / "GRAPH.md"
    try:
        graph_text = graph_path.read_text(encoding="utf-8") if not graph_path.is_symlink() else ""
    except OSError:
        graph_text = ""
    managed_hash = hashlib.sha256((managed_text + "\0" + graph_text).encode()).hexdigest()
    managed, commands = _managed_entries(base, managed_text)
    graph_entries, _graph_commands = _managed_entries(base, graph_text, ".asgard/map/GRAPH.md")
    managed = [*managed, *graph_entries]
    manual: tuple[MapEntry, ...] = ()
    issues: tuple[AreaIssue, ...] = ()
    if not managed_only:
        manual, issues = validate_area_maps(base)
    all_entries = [*managed, *manual]
    terms = {token.casefold() for token in _TOKEN.findall(query)}
    ranked = sorted(all_entries, key=lambda entry: _score(entry, terms))
    if terms and any(-_score(entry, terms)[0] > int(entry.managed) for entry in ranked):
        relevant = [entry for entry in ranked if -_score(entry, terms)[0] > int(entry.managed)]
        fallback = [entry for entry in ranked if entry.managed and entry not in relevant]
        ranked = [*relevant, *fallback]
    selected: list[MapEntry] = []
    lines = [
        f'<asgard-map revision="{managed_hash[:12]}" advisory="true">',
        "작업 관련 프로젝트 지도다. 먼저 이 경로로 탐색하되 계획·편집·판정에 쓰는 정의와 사용처는 소스에서 다시 읽어라.",
    ]
    for entry in ranked[:MAX_CONTEXT_ENTRIES]:
        line = f"- `{entry.path}` — {_neutralize(entry.role)} [source: {_neutralize(entry.source)}]"
        if len(("\n".join([*lines, line, "</asgard-map>"])).encode("utf-8")) > CONTEXT_BUDGET:
            break
        lines.append(line)
        selected.append(entry)
    if commands:
        lines.append("검증 명령 후보:")
        for command, role in commands:
            line = f"- `{_neutralize(command)}` — {_neutralize(role)}"
            if len(("\n".join([*lines, line, "</asgard-map>"])).encode("utf-8")) > CONTEXT_BUDGET:
                break
            lines.append(line)
    lines.append("</asgard-map>")
    text = "\n".join(lines) if selected or commands else ""
    return MapContext(text, tuple(selected), issues, managed_hash, refreshed)
