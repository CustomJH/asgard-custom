"""Deterministic codebase map.

The map is an orientation index, not a history log or proof of correctness.  It records only
landmarks observed on disk and owns exactly ``PROJECT.md``; human-authored area maps remain intact.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
import tomllib
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .templates.map import MAP_INDEX_MD

_PROJECT_FILE = "PROJECT.md"
_GENERATED_MARKER = "<!-- asgard:project-map schema=1 -->"
_LEGACY_MARKER = "> Asgard managed orientation map."
_ENTRY_RE = re.compile(r"^- `([^`]+)` — ", re.M)
_IGNORED_DIRS = {
    ".asgard",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "ref",
    "target",
    "vendor",
}
_MANIFESTS = {
    "pyproject.toml": "Python project manifest",
    "package.json": "Node.js project manifest",
    "Cargo.toml": "Rust package manifest",
    "go.mod": "Go module manifest",
    "pom.xml": "Maven project manifest",
    "build.gradle": "Gradle build manifest",
    "build.gradle.kts": "Gradle Kotlin build manifest",
    "Makefile": "build/task entrypoint",
    "justfile": "project task entrypoint",
    "docker-compose.yml": "container stack definition",
    "docker-compose.yaml": "container stack definition",
}
_AREA_ROLES = {
    "app": "application source area",
    "apps": "application workspace area",
    "cmd": "executable command area",
    "config": "configuration area",
    "crates": "Rust workspace crates",
    "docker": "container and deployment area",
    "docs": "documentation area",
    "infra": "infrastructure area",
    "internal": "internal package area",
    "lib": "library source area",
    "packages": "package workspace area",
    "scripts": "automation scripts",
    "src": "primary source area",
    "test": "test area",
    "tests": "test area",
}
_LANGUAGE_BY_SUFFIX = {
    ".c": "C",
    ".cpp": "C++",
    ".cs": "C#",
    ".go": "Go",
    ".java": "Java",
    ".js": "JavaScript",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".php": "PHP",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
}


@dataclass(frozen=True)
class MapResult:
    project: str
    changed: bool
    files_scanned: int
    landmarks: int
    path: str
    index_changed: bool = False


@dataclass(frozen=True)
class MapCheck:
    ok: bool
    trackable: bool
    index_current: bool
    owned: bool
    added: tuple[str, ...]
    removed: tuple[str, ...]
    expected_hash: str
    actual_hash: str


class MapError(RuntimeError):
    """Base class for deterministic map setup failures."""


class MapSafetyError(MapError):
    """The managed output path is unsafe."""


class MapOwnershipError(MapError):
    """A human-owned map conflicts with Asgard's reserved output."""


def _safe_component(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", lambda: False)
    return not path.is_symlink() and not bool(is_junction())


def _map_dir(root: Path, *, create: bool) -> Path:
    asgard = root / ".asgard"
    map_dir = asgard / "map"
    for component in (asgard, map_dir):
        if not _safe_component(component):
            raise MapSafetyError(f"managed map path is a symlink/junction: {component}")
    if create:
        map_dir.mkdir(parents=True, exist_ok=True)
    if map_dir.exists():
        try:
            map_dir.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise MapSafetyError(f"managed map path escapes project root: {map_dir}") from exc
        for child in map_dir.iterdir():
            if child.name.casefold() == _PROJECT_FILE.casefold() and child.name != _PROJECT_FILE:
                raise MapOwnershipError(f"reserved map filename collision: {child.name}")
            if child.suffix.casefold() == ".md" and not _safe_component(child):
                raise MapSafetyError(f"map documents cannot be symlinks/junctions: {child}")
    return map_dir


def _owned_project_map(content: str) -> bool:
    lines = content.splitlines()
    if lines and lines[0] == _GENERATED_MARKER:
        return True
    return len(lines) >= 3 and lines[0].startswith("# Project Map — ") and lines[2].startswith(_LEGACY_MARKER)


def _safe_label(value: str) -> str:
    return "".join(
        " " if unicodedata.category(ch).startswith("C") else "_" if ch == "`" else ch
        for ch in value
    ).strip()


def _safe_relpath(path: Path) -> bool:
    return bool(path.parts) and not any(
        unicodedata.category(ch).startswith("C") or ch == "`" for ch in path.as_posix()
    )


def _files(root: Path) -> list[Path]:
    def allowed(path: Path) -> bool:
        return _safe_relpath(path) and not any(
            part in _IGNORED_DIRS or part.startswith(".") for part in path.parts
        )

    # In a repository, Git is the canonical project boundary: tracked files plus non-ignored
    # worktree additions. This prevents benchmark copies, build outputs, and local workspaces from
    # becoming false landmarks. Non-Git folders retain a portable os.walk fallback.
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True,
            check=False,
            timeout=30,
        )
        if proc.returncode == 0:
            paths = [Path(raw.decode("utf-8", "surrogateescape")) for raw in proc.stdout.split(b"\0") if raw]
            return sorted(
                (p for p in paths if allowed(p) and (root / p).is_file() and not (root / p).is_symlink()),
                key=lambda p: p.as_posix(),
            )
    except subprocess.TimeoutExpired as exc:
        raise MapError("git inventory timed out after 30 seconds") from exc
    except OSError:
        pass

    found: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _IGNORED_DIRS and not d.startswith("."))
        for name in sorted(names):
            if name.startswith("."):
                continue
            path = Path(current, name)
            try:
                if path.is_file() and not path.is_symlink():
                    rel = path.relative_to(root)
                    if allowed(rel):
                        found.append(rel)
            except OSError:
                continue
    return sorted(found, key=lambda p: p.as_posix())


def _toml(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            value = tomllib.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _project_name(root: Path) -> str:
    pyproject = _toml(root / "pyproject.toml")
    value = (pyproject.get("project") or {}).get("name")
    if isinstance(value, str) and value.strip():
        return _safe_label(value)
    cargo = _toml(root / "Cargo.toml")
    value = (cargo.get("package") or {}).get("name")
    if isinstance(value, str) and value.strip():
        return _safe_label(value)
    package = root / "package.json"
    try:
        import json

        value = json.loads(package.read_text(encoding="utf-8")).get("name")
        if isinstance(value, str) and value.strip():
            return _safe_label(value)
    except (OSError, ValueError):
        pass
    return "project"


def _add(entries: dict[str, str], path: str, role: str) -> None:
    entries.setdefault(path, role)


def _landmarks(root: Path, files: list[Path]) -> dict[str, str]:
    entries: dict[str, str] = {}
    file_set = {p.as_posix() for p in files}
    top_dirs = {p.parts[0] for p in files if len(p.parts) > 1}

    for manifest, role in _MANIFESTS.items():
        if manifest in file_set:
            _add(entries, manifest, role)
    if "README.md" in file_set:
        _add(entries, "README.md", "project overview and operating guide")
    for name, role in _AREA_ROLES.items():
        if name in top_dirs:
            _add(entries, name + "/", role)

    # Python package roots are stronger landmarks than every module file.
    for p in files:
        if p.name == "__init__.py" and len(p.parts) >= 2:
            parent = p.parent.as_posix() + "/"
            _add(entries, parent, "Python package root")

    pyproject = _toml(root / "pyproject.toml")
    scripts = (pyproject.get("project") or {}).get("scripts") or {}
    if isinstance(scripts, dict):
        for command, target in sorted(scripts.items()):
            if not isinstance(target, str):
                continue
            module = target.split(":", 1)[0].strip()
            candidate = module.replace(".", "/") + ".py"
            options = (candidate, "src/" + candidate)
            hit = next((p for p in options if p in file_set), None)
            if hit:
                _add(entries, hit, f"CLI entrypoint `{_safe_label(str(command))}`")

    entrypoints = {
        "main.py": "application entrypoint",
        "app.py": "application entrypoint",
        "src/main.rs": "Rust executable entrypoint",
        "src/lib.rs": "Rust library entrypoint",
        "cmd/main.go": "Go executable entrypoint",
        "index.js": "JavaScript entrypoint",
        "index.ts": "TypeScript entrypoint",
    }
    for path, role in entrypoints.items():
        if path in file_set:
            _add(entries, path, role)

    # Monorepo/service boundaries: a directory below a known workspace root that owns a manifest.
    manifest_names = set(_MANIFESTS) | {"go.mod"}
    for p in files:
        if p.name in manifest_names and len(p.parts) > 1:
            parent = p.parent.as_posix() + "/"
            _add(entries, parent, f"project boundary ({p.name})")

    return dict(sorted(entries.items()))


def _render(root: Path) -> tuple[str, int, int, str]:
    files = _files(root)
    entries = _landmarks(root, files)
    project = _project_name(root)
    languages = Counter(_LANGUAGE_BY_SUFFIX[p.suffix.lower()] for p in files if p.suffix.lower() in _LANGUAGE_BY_SUFFIX)
    language_text = ", ".join(f"{name} ({count})" for name, count in languages.most_common()) or "not inferred"
    lines = [
        _GENERATED_MARKER,
        f"# Project Map — {project}",
        "",
        "> Asgard managed orientation map. Regenerate with `asgard setup map`; do not hand-edit this file.",
        "> It is a navigation hint, not completion evidence: re-read every path used by a plan.",
        "",
        "## Orientation",
        "",
        "- Project root: `./`",
        f"- Languages by observed source files: {language_text}",
        f"- Evidence scan: {len(files)} files; {len(entries)} landmarks",
        "",
        "## Landmarks",
        "",
    ]
    lines.extend(f"- `{path}` — {role}" for path, role in entries.items())
    if not entries:
        lines.append("- `(none yet)` — add project files, then rerun `asgard setup map`")
    lines += [
        "",
        "## Navigation contract",
        "",
        "- Read `PROJECT.md` first, then the matching human-authored area map if present.",
        "- Verify target definitions and usages from source before planning or editing.",
        "- Structural changes refresh this managed map before Verifier hashing; use `--check` in CI to detect drift.",
        "",
    ]
    return "\n".join(lines), len(files), len(entries), project


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _entry_paths(text: str) -> set[str]:
    return set(_ENTRY_RE.findall(text))


def _trackable(root: Path, path: Path) -> bool:
    """False only when Git explicitly ignores the map; non-Git folders remain supported."""
    try:
        rel = path.relative_to(root).as_posix()
        proc = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "--", rel],
            capture_output=True,
            check=False,
        )
        return proc.returncode != 0
    except (OSError, ValueError):
        return True


def check_map(root: str | os.PathLike[str]) -> MapCheck:
    base = Path(root).resolve()
    expected, _, _, _ = _render(base)
    map_dir = _map_dir(base, create=False)
    path = map_dir / _PROJECT_FILE
    index_path = map_dir / "INDEX.md"
    try:
        actual = path.read_text(encoding="utf-8")
    except OSError:
        actual = ""
    try:
        index_current = index_path.read_text(encoding="utf-8") == MAP_INDEX_MD
    except OSError:
        index_current = False
    owned = _owned_project_map(actual)
    trackable = _trackable(base, path)
    return MapCheck(
        ok=actual == expected and trackable and index_current and owned,
        trackable=trackable,
        index_current=index_current,
        owned=owned,
        added=tuple(sorted(_entry_paths(expected) - _entry_paths(actual))),
        removed=tuple(sorted(_entry_paths(actual) - _entry_paths(expected))),
        expected_hash=_hash(expected),
        actual_hash=_hash(actual),
    )


def _atomic_write(root: Path, path: Path, content: str) -> None:
    map_dir = _map_dir(root, create=True)
    if path.parent != map_dir:
        raise MapSafetyError(f"write target is outside managed map directory: {path}")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=map_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def refresh_map(root: str | os.PathLike[str], *, dry_run: bool = False) -> MapResult:
    base = Path(root).resolve()
    content, files_scanned, landmarks, project = _render(base)
    map_dir = _map_dir(base, create=not dry_run)
    project_path = map_dir / _PROJECT_FILE
    try:
        current = project_path.read_text(encoding="utf-8")
    except OSError:
        current = ""
    if project_path.exists() and not _owned_project_map(current):
        raise MapOwnershipError(f"refusing to overwrite human-owned {project_path}")
    changed = current != content
    index_path = map_dir / "INDEX.md"
    try:
        index_current = index_path.read_text(encoding="utf-8")
    except OSError:
        index_current = ""
    index_changed = index_current != MAP_INDEX_MD
    if not dry_run:
        if index_changed:
            _atomic_write(base, index_path, MAP_INDEX_MD)
        if changed:
            _atomic_write(base, project_path, content)
    return MapResult(project, changed, files_scanned, landmarks, str(project_path), index_changed)
