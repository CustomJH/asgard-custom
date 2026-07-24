"""Deterministic codebase map.

The map is an orientation index, not a history log or proof of correctness.  It records only
landmarks observed on disk and owns exactly ``PROJECT.md``; human-authored area maps remain intact.
"""

from __future__ import annotations

import ast
import hashlib
import json
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
_GENERATED_MARKER = "<!-- asgard:project-map schema=2 -->"
_GENERATED_MARKER_RE = re.compile(r"^<!-- asgard:project-map schema=\d+ -->$")
_LEGACY_MARKER = "> Asgard managed orientation map."
_ENTRY_RE = re.compile(r"^- `([^`]+)` — ", re.M)
_MAX_PROJECT_MAP_BYTES = 32 * 1024
_MAX_LANDMARKS = 200
_MAX_SURFACE_FILES = 48
_MAX_SYMBOLS_PER_FILE = 5
_MAX_SOURCE_BYTES = 512 * 1024
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
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".hh": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".go": "Go",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
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
    if lines and _GENERATED_MARKER_RE.fullmatch(lines[0]):
        return True
    return len(lines) >= 3 and lines[0].startswith("# Project Map — ") and lines[2].startswith(_LEGACY_MARKER)


def _safe_label(value: str) -> str:
    return "".join(
        " " if unicodedata.category(ch).startswith("C") else "_" if ch == "`" else ch for ch in value
    ).strip()


def _safe_relpath(path: Path) -> bool:
    return bool(path.parts) and not any(unicodedata.category(ch).startswith("C") or ch == "`" for ch in path.as_posix())


def _files(root: Path) -> list[Path]:
    def allowed(path: Path) -> bool:
        return _safe_relpath(path) and not any(part in _IGNORED_DIRS or part.startswith(".") for part in path.parts)

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
    except OSError, tomllib.TOMLDecodeError:
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
        value = json.loads(package.read_text(encoding="utf-8")).get("name")
        if isinstance(value, str) and value.strip():
            return _safe_label(value)
    except OSError, ValueError:
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


def _verification_commands(root: Path, files: list[Path]) -> list[tuple[str, str]]:
    """Infer only commands backed by checked-in manifests or task definitions."""
    file_set = {path.as_posix() for path in files}
    commands: dict[str, str] = {}
    pyproject = _toml(root / "pyproject.toml")
    if "pyproject.toml" in file_set:
        if "pytest" in (pyproject.get("tool") or {}) or any(path.parts[:1] == ("tests",) for path in files):
            commands["python -m pytest"] = "Python test suite"
        tools = pyproject.get("tool") or {}
        if "ruff" in tools:
            commands["ruff check ."] = "Python lint"
            commands["ruff format --check ."] = "Python format check"
        if "ty" in tools:
            commands["ty check"] = "Python type check"
    if "package.json" in file_set:
        try:
            package = json.loads((root / "package.json").read_text(encoding="utf-8"))
            scripts = package.get("scripts") if isinstance(package, dict) else {}
            runner = "pnpm" if "pnpm-lock.yaml" in file_set else "yarn" if "yarn.lock" in file_set else "npm run"
            if isinstance(scripts, dict):
                for name in ("test", "lint", "typecheck", "check", "build"):
                    if isinstance(scripts.get(name), str):
                        command = f"{runner} {name}" if runner != "yarn" else f"yarn {name}"
                        commands[command] = f"package script `{name}`"
        except OSError, ValueError:
            pass
    if "Cargo.toml" in file_set:
        commands["cargo test"] = "Rust test suite"
        commands["cargo check"] = "Rust compile check"
    if "go.mod" in file_set:
        commands["go test ./..."] = "Go test suite"
    if "Makefile" in file_set:
        try:
            makefile = (root / "Makefile").read_text(encoding="utf-8")
            for target in ("test", "lint", "check", "build"):
                if re.search(rf"(?m)^{re.escape(target)}\s*:", makefile):
                    commands[f"make {target}"] = f"Make target `{target}`"
        except OSError:
            pass
    return sorted(commands.items())


def _python_module(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    if parts and parts[0] in {"src", "lib"}:
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _python_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args)]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    args.extend(arg.arg for arg in node.args.kwonlyargs)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    rendered = ", ".join(args[:5]) + (", …" if len(args) > 5 else "")
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({rendered})"


def _python_surface(root: Path, path: Path, modules: dict[str, str]) -> tuple[list[str], list[str]]:
    try:
        full = root / path
        if full.stat().st_size > _MAX_SOURCE_BYTES:
            return [], []
        tree = ast.parse(full.read_text(encoding="utf-8"), filename=path.as_posix())
    except OSError, SyntaxError, UnicodeError:
        return [], []
    symbols: list[str] = []
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            symbols.append(_python_signature(node))
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            symbols.append(f"class {node.name}")
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    uses: set[str] = set()
    for name in imported:
        candidates = [module for module in modules if name == module or name.startswith(module + ".")]
        if candidates:
            uses.add(modules[max(candidates, key=len)])
    return symbols[:_MAX_SYMBOLS_PER_FILE], sorted(uses)


_TSJS_EXPORT_PATTERN = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)", re.M
)
_SURFACE_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    ".js": (
        re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.M),
        re.compile(r"^\s*export\s+(?:default\s+)?class\s+([A-Za-z_$][\w$]*)", re.M),
    ),
    ".jsx": (
        re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.M),
        re.compile(r"^\s*export\s+(?:default\s+)?class\s+([A-Za-z_$][\w$]*)", re.M),
    ),
    ".mjs": (
        re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.M),
        re.compile(r"^\s*export\s+(?:default\s+)?class\s+([A-Za-z_$][\w$]*)", re.M),
    ),
    ".cjs": (
        re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.M),
        re.compile(r"^\s*export\s+(?:default\s+)?class\s+([A-Za-z_$][\w$]*)", re.M),
    ),
    ".ts": (_TSJS_EXPORT_PATTERN,),
    ".tsx": (_TSJS_EXPORT_PATTERN,),
    # Vue SFCs embed a <script> block using JS/TS export syntax; the surrounding template/style
    # markup never matches the export keyword so scanning the whole file is safe.
    ".vue": (_TSJS_EXPORT_PATTERN,),
    ".go": (
        re.compile(r"^\s*func\s+([A-Z]\w*)\s*\(", re.M),
        re.compile(r"^\s*type\s+([A-Z]\w*)\s+", re.M),
    ),
    ".rs": (re.compile(r"^\s*pub(?:\([^)]*\))?\s+(?:async\s+)?(?:fn|struct|enum|trait|type)\s+([A-Za-z_]\w*)", re.M),),
    ".java": (
        re.compile(r"^\s*public\s+(?:final\s+|abstract\s+)?(?:class|interface|record|enum)\s+([A-Za-z_]\w*)", re.M),
    ),
    # Kotlin declarations are public by default; match modifier-prefixed declarations while
    # letting an explicit private/internal/protected prefix fail the keyword position.
    ".kt": (
        re.compile(
            r"^\s*(?:(?:public|open|abstract|final|data|sealed|enum|annotation|value|inner"
            r"|suspend|operator|infix|inline|tailrec|external|expect|actual|fun)\s+)*"
            r"(?:class|interface|object|fun)\s+([A-Za-z_]\w*)",
            re.M,
        ),
    ),
    # C has no export keyword, so a name is only counted as a function definition when a return
    # type token precedes it (excludes control-flow keywords like `if`/`while`, which have none).
    ".c": (
        re.compile(r"^(?!static\b)(?:[A-Za-z_]\w*[\s*]+){1,4}([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{", re.M),
        re.compile(r"^\s*(?:typedef\s+)?struct\s+([A-Za-z_]\w*)\s*\{", re.M),
        re.compile(r"^\s*(?:typedef\s+)?enum\s+([A-Za-z_]\w*)\s*\{", re.M),
    ),
    ".h": (
        re.compile(r"^(?!static\b)(?:[A-Za-z_]\w*[\s*]+){1,4}([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{", re.M),
        re.compile(r"^\s*(?:typedef\s+)?struct\s+([A-Za-z_]\w*)\s*\{", re.M),
        re.compile(r"^\s*(?:typedef\s+)?enum\s+([A-Za-z_]\w*)\s*\{", re.M),
    ),
    ".cpp": (
        re.compile(r"^\s*(?:template\s*<[^>]*>\s*)?class\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*(?:typedef\s+)?struct\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*namespace\s+([A-Za-z_]\w*)\s*\{", re.M),
    ),
    ".cc": (
        re.compile(r"^\s*(?:template\s*<[^>]*>\s*)?class\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*(?:typedef\s+)?struct\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*namespace\s+([A-Za-z_]\w*)\s*\{", re.M),
    ),
    ".cxx": (
        re.compile(r"^\s*(?:template\s*<[^>]*>\s*)?class\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*(?:typedef\s+)?struct\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*namespace\s+([A-Za-z_]\w*)\s*\{", re.M),
    ),
    ".hpp": (
        re.compile(r"^\s*(?:template\s*<[^>]*>\s*)?class\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*(?:typedef\s+)?struct\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*namespace\s+([A-Za-z_]\w*)\s*\{", re.M),
    ),
    ".hh": (
        re.compile(r"^\s*(?:template\s*<[^>]*>\s*)?class\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*(?:typedef\s+)?struct\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*namespace\s+([A-Za-z_]\w*)\s*\{", re.M),
    ),
    ".cs": (
        re.compile(
            r"^\s*public\s+(?:static\s+|abstract\s+|sealed\s+|partial\s+)*"
            r"(?:class|interface|struct|enum|record)\s+([A-Za-z_]\w*)",
            re.M,
        ),
    ),
    ".php": (
        re.compile(r"^\s*(?:abstract\s+|final\s+)?class\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*interface\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*trait\s+([A-Za-z_]\w*)", re.M),
        # Global functions (column 0) and class methods declared `public function`.
        re.compile(r"^function\s+([A-Za-z_]\w*)\s*\(", re.M),
        re.compile(r"^\s+public\s+(?:static\s+)?function\s+([A-Za-z_]\w*)\s*\(", re.M),
    ),
    ".rb": (
        re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.M),
        re.compile(r"^\s*def\s+(?:self\.)?([a-z_]\w*[?!=]?)", re.M),
    ),
    ".swift": (
        re.compile(r"^\s*(?:public|open)\s+(?:final\s+)?(?:class|struct|enum|protocol|func)\s+([A-Za-z_]\w*)", re.M),
    ),
}


def _generic_surface(root: Path, path: Path) -> list[str]:
    patterns = _SURFACE_PATTERNS.get(path.suffix.lower(), ())
    if not patterns:
        return []
    try:
        full = root / path
        if full.stat().st_size > _MAX_SOURCE_BYTES:
            return []
        text = full.read_text(encoding="utf-8")
    except OSError, UnicodeError:
        return []
    names: list[str] = []
    for pattern in patterns:
        names.extend(match.group(1) for match in pattern.finditer(text))
    return list(dict.fromkeys(names))[:_MAX_SYMBOLS_PER_FILE]


def _diversify(rows: list[tuple[str, list[str], list[str]]]) -> list[tuple[str, list[str], list[str]]]:
    """depth-2 서브트리 라운드로빈 — 한 대량 트리(예: 아토믹 `components/`)의 표면 독점을 막는다.

    그룹 순서는 정렬된 행의 첫 등장 순서를 따르므로 단일 그룹 저장소에선 순서가 불변이다.
    """
    groups: dict[str, list[tuple[str, list[str], list[str]]]] = {}
    for row in rows:
        parts = row[0].split("/")
        groups.setdefault("/".join(parts[:2]), []).append(row)
    ordered: list[tuple[str, list[str], list[str]]] = []
    queues = [queue for queue in groups.values()]
    while queues:
        remaining = []
        for queue in queues:
            ordered.append(queue.pop(0))
            if queue:
                remaining.append(queue)
        queues = remaining
    return ordered


def _surface_entries(root: Path, files: list[Path]) -> list[tuple[str, str]]:
    source_files = [
        path
        for path in files
        if path.suffix.lower() in ({".py"} | set(_SURFACE_PATTERNS))
        and "test" not in {part.casefold() for part in path.parts}
        and not path.name.startswith("_")
    ]
    python_modules = {_python_module(path): path.as_posix() for path in source_files if path.suffix.lower() == ".py"}
    rows: list[tuple[str, list[str], list[str]]] = []
    inbound: Counter[str] = Counter()
    for path in source_files:
        if path.suffix.lower() == ".py":
            symbols, uses = _python_surface(root, path, python_modules)
        else:
            symbols, uses = _generic_surface(root, path), []
        if symbols:
            rows.append((path.as_posix(), symbols, uses))
            inbound.update(uses)
    rows.sort(key=lambda row: (-inbound[row[0]], row[0]))
    rendered: list[tuple[str, str]] = []
    for path, symbols, uses in _diversify(rows)[:_MAX_SURFACE_FILES]:
        role = "public surface: " + "; ".join(symbols)
        if uses:
            role += "; uses " + ", ".join(f"`{dependency}`" for dependency in uses[:4])
        rendered.append((path, role))
    return rendered


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
        "> Asgard managed orientation map. Regenerate with `asgard map update`; do not hand-edit this file.",
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
    landmark_rows = list(entries.items())[:_MAX_LANDMARKS]
    lines.extend(f"- `{path}` — {role}" for path, role in landmark_rows)
    if len(entries) > len(landmark_rows):
        lines.append(f"- Additional landmarks omitted by budget: {len(entries) - len(landmark_rows)}")
    if not entries:
        lines.append("- `(none yet)` — add project files, then rerun `asgard map update`")
    commands = _verification_commands(root, files)
    lines += ["", "## Detected verification", ""]
    lines.extend(f"- Command: `{command}` — {role}" for command, role in commands)
    if not commands:
        lines.append("- No verification command inferred from checked-in manifests.")
    lines += ["", "## Public surfaces", ""]
    surface_rows = _surface_entries(root, files)
    footer = [
        "",
        "## Navigation contract",
        "",
        "- Read `PROJECT.md` first, then the matching human-authored area map if present.",
        "- Verify target definitions and usages from source before planning or editing.",
        "- Structural changes refresh this managed map before Verifier hashing; use `asgard map check` in CI.",
        "",
    ]
    for path, role in surface_rows:
        candidate = f"- `{path}` — {role}"
        projected = "\n".join([*lines, candidate, *footer])
        if len(projected.encode("utf-8")) > _MAX_PROJECT_MAP_BYTES:
            lines.append("- Additional public surfaces omitted by byte budget.")
            break
        lines.append(candidate)
    lines += footer
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
    except OSError, ValueError:
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


def refresh_map(root: str | os.PathLike[str], *, dry_run: bool = False, force: bool = False) -> MapResult:
    """force=True 는 소유권 거부만 우회한다 (init — 현재 디렉토리가 정본인 명시 재설정).
    안전 검사(심링크·경로 탈출·예약 파일명 충돌)는 force 와 무관하게 하드 에러."""
    base = Path(root).resolve()
    content, files_scanned, landmarks, project = _render(base)
    map_dir = _map_dir(base, create=not dry_run)
    project_path = map_dir / _PROJECT_FILE
    try:
        current = project_path.read_text(encoding="utf-8")
    except OSError:
        current = ""
    if project_path.exists() and not _owned_project_map(current) and not force:
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
