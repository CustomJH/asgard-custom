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
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path

from .templates.map import MAP_INDEX_MD

_PROJECT_FILE = "PROJECT.md"
# 짝 저장소 지도의 파일 이름 머리 — 이 머리를 단 파일은 관리 파일이라 영역 지도 문법 검사에서 빠지고
# (`map_context.validate_area_maps`), 주입면에서는 PROJECT.md·GRAPH.md 와 같은 관리 출처로 읽힌다.
PEER_MAP_PREFIX = "PEER-"
# 짝 저장소 한 곳에서 지도에 실을 파일 수 상한. 세션 저장소는 상한이 없는데 짝만 거는 이유는 비용의
# 임자다 — 지도 새로고침은 UserPromptSubmit 훅이 30초 제한으로 돌리고, 그 안에서 죽으면 조용히
# 넘어간다(fail-open). 남의 모노레포 하나가 그 예산을 다 먹으면 세션 저장소 지도까지 같이 사라진다.
# lagom: 고정 숫자다. 저장소마다 달리 잡아야 할 근거가 생기면 `paths` 섹션의 설정 키로 올린다.
_MAX_PEER_FILES = 6000
_GENERATED_MARKER = "<!-- asgard:project-map schema=3 -->"
_GENERATED_MARKER_RE = re.compile(r"^<!-- asgard:project-map schema=\d+ -->$")
_LEGACY_MARKER = "> Asgard managed orientation map."
_ENTRY_RE = re.compile(r"^- `([^`]+)` — ", re.M)
# 짝 지도가 자기 안에 적어 두는 신선도 표식 — 다음 판정은 이 줄만 다시 계산해 비교한다.
_PEER_REVISION_RE = re.compile(r"^- Source revision: (\S+)$", re.M)
_MAX_PROJECT_MAP_BYTES = 32 * 1024
_MAX_LANDMARKS = 200
_MAX_SURFACE_FILES = 48
_MAX_SYMBOLS_PER_FILE = 5
_MAX_SOURCE_BYTES = 512 * 1024
_MAX_DOC_FILES = 40
_MAX_DOC_SECTIONS = 6
# 문서 레인은 마크다운만 본다. reStructuredText 는 제목을 밑줄로 다는 별개 문법이라, 같은
# 정규식으로 읽으면 제목 아닌 줄을 제목이라 우기게 된다 — 못 읽는 형식은 안 읽는다.
_DOC_SUFFIXES = {".md", ".mdx"}
_DOC_TITLE = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.M)
_DOC_SECTION = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.M)
# 오리엔테이션 맵의 범위 — 지도는 **지금 고칠 나무**를 가리켜야 한다. health.IGNORED_DIRS와
# 목적이 달라 공유하지 않지만(그쪽 주석 참조), "남의 나무·죽은 나무는 방향이 아니다"는 같다.
# `archive`와 `skill_plugins`가 빠져 있어 이 저장소 지도 284엔트리 중 198개(70%)가 아카이브와
# 이식해 온 스킬 번들을 가리켰고, 질의 랭킹 1위까지 그쪽이 먹었다 (26-08-01 실측).
_IGNORED_DIRS = {
    ".asgard",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "archive",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
    "ref",
    "site-packages",
    "skill_plugins",
    "target",
    "third_party",
    "thirdparty",
    "vendor",
    "vendored",
    "venv",
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
    ".dart": "Dart",
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
    ".svelte": "Svelte",
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
    # 이번 새로고침이 다시 쓴 짝 저장소 지도 파일 이름 (선언이 빠져 지운 것도 포함).
    peers_written: tuple[str, ...] = ()


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
    # 다시 그려야 하는 짝 저장소 지도 — 내용이 어긋난 것과 선언이 빠진 뒤 남은 것.
    peer_drift: tuple[str, ...] = ()


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
            listed = sorted(
                (p for p in paths if allowed(p) and (root / p).is_file() and not (root / p).is_symlink()),
                key=lambda p: p.as_posix(),
            )
            # 빈 성공은 경계가 아니라 경계 부재다: 상위 저장소가 ignore 한 하위 트리(레퍼런스
            # 사본·벤더 복사본)에서 ls-files는 성공하면서 아무것도 못 본다. 사용자가 가리킨
            # 루트가 곧 프로젝트다 — 조용한 빈 지도 대신 walk 폴백으로 내려간다.
            if listed:
                return listed
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


def peer_roots(root: str | os.PathLike[str]) -> list[tuple[str, Path]]:
    """(라벨, 절대경로) — 이 프로젝트가 선언한 짝 저장소 전부.

    라벨은 세션 뿌리 기준 상대경로다 (`../helios-application`). 지도 항목이 그 라벨을 그대로 앞에
    달기 때문에, 세션 뿌리에서 읽는 사람도 에이전트도 적힌 경로를 그대로 열 수 있다. 증거를 모으는
    훅(`asgard_hooklib.tree.peer_roots`)이 쓰는 표기와 같은 표기다 — 갈리면 지도가 가리키는 파일과
    판정이 세는 파일이 서로 다른 이름을 갖는다.

    짝 저장소에는 아무것도 쓰지 않는다. 그 저장소가 남의 것이거나(팀 저장소) 옛 판 아스가르드가
    깔려 있을 수 있어서, 지도는 읽기만 하고 결과물은 전부 세션 저장소의 `.asgard/map/` 에 남는다."""
    from .settings import declared_roots

    base = Path(root).resolve()
    out: list[tuple[str, Path]] = []
    for declared in declared_roots(str(base)):
        path = Path(declared)
        if not path.is_dir() or path.is_symlink():
            continue
        out.append((os.path.relpath(path, base).replace("\\", "/"), path))
    return sorted(out)


def peer_map_names(labels: list[str]) -> dict[str, str]:
    """라벨 → 이 지도가 사는 파일 이름. `../helios-application` → `PEER-helios-application.md`.

    `..` 은 파일 이름에 못 쓰므로 떨군다. 그래서 서로 다른 두 짝이 같은 이름으로 접힐 수 있고
    (`../a/b` 와 `../a-b`), 그때는 라벨 사전순으로 뒤에 번호를 붙여 가른다 — 두 지도가 한 파일을
    번갈아 덮어쓰면 새로고침마다 내용이 뒤집힌다."""
    used: dict[str, str] = {}
    names: dict[str, str] = {}
    for label in sorted(labels):
        stem = "-".join(part for part in label.split("/") if part not in {"", ".", ".."}) or "root"
        stem = _safe_label(stem).replace(" ", "-") or "root"
        candidate = stem
        suffix = 2
        while candidate in used:
            candidate = f"{stem}-{suffix}"
            suffix += 1
        used[candidate] = label
        names[label] = f"{PEER_MAP_PREFIX}{candidate}.md"
    return names


def _budget_files(files: list[Path], limit: int) -> tuple[list[Path], int]:
    """상한을 넘는 목록을 최상위 디렉터리 라운드로빈으로 줄인다. (남긴 것, 버린 수).

    정렬 순서대로 자르면 알파벳 뒤쪽 서비스가 통째로 사라진다 — `helios-batch` 부터 채우다가
    `helios-fe` 를 한 파일도 못 싣는 식이다. 서비스마다 한 파일씩 번갈아 담으면 상한이 걸려도
    모든 최상위 트리가 지도에 남는다."""
    if len(files) <= limit:
        return files, 0
    groups: dict[str, deque[Path]] = {}
    for path in files:
        groups.setdefault(path.parts[0] if len(path.parts) > 1 else "", deque()).append(path)
    kept: list[Path] = []
    queues = list(groups.values())
    while queues and len(kept) < limit:
        remaining = []
        for queue in queues:
            if len(kept) >= limit:
                break
            kept.append(queue.popleft())
            if queue:
                remaining.append(queue)
        queues = remaining
    return sorted(kept, key=lambda p: p.as_posix()), len(files) - len(kept)


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


def verification_commands(root: str | os.PathLike[str]) -> list[tuple[str, str]]:
    """이 저장소의 매니페스트가 뒷받침하는 명령 — 지도의 `## Detected verification` 과 같은 것.

    `justfile.detect_recipes` 가 이 자리를 부른다. 감지기를 하나로 두는 이유는 갈리면 주입면이
    광고하는 명령과 Justfile 이 담은 명령이 서로 다른 것을 가리키기 때문이다."""
    base = Path(root)
    return _verification_commands(base, _files(base))


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
    # deque 인 이유는 `popleft` 하나다 — 리스트의 `pop(0)`은 한 번 꺼낼 때마다 뒤 전체를 앞으로
    # 민다. 라운드로빈은 모든 행을 정확히 한 번씩 꺼내므로 그 이동이 행 수의 제곱으로 쌓인다.
    queues = [deque(queue) for queue in groups.values()]
    while queues:
        remaining = []
        for queue in queues:
            ordered.append(queue.popleft())
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


def _document_entries(root: Path, files: list[Path]) -> list[tuple[str, str]]:
    """추적된 문서의 제목과 절 이름 — 본문은 적지 않는다.

    "이미 답이 적힌 문서가 어디 있나"는 홉 절감이 가장 큰 질문 부류인데 지도에는 그 레인이
    없었다: 이 저장소의 추적 문서 23개 중 지도가 가리키던 건 `README.md` 하나였고, 역할 정본인
    `templates/roles/*.md` 는 통째로 밖에 있었다 (26-08-01 실측). 제목과 H2 만으로 "여기 열어라"
    는 충분하다 — 본문까지 적으면 지도가 문서의 사본이 되고, 사본은 곧 낡는다.

    얕은 경로를 먼저 둔다. 뿌리의 README 가 `benchmarks/*/REPORT.md` 보다 방위에 가깝다.
    """
    rendered: list[tuple[str, str]] = []
    candidates = sorted(
        (path for path in files if path.suffix.lower() in _DOC_SUFFIXES),
        key=lambda path: (len(path.parts), path.as_posix()),
    )
    for path in candidates[:_MAX_DOC_FILES]:
        try:
            full = root / path
            if full.stat().st_size > _MAX_SOURCE_BYTES:
                continue
            text = full.read_text(encoding="utf-8")
        except OSError, UnicodeError:
            continue
        title = _DOC_TITLE.search(text)
        sections = [_safe_label(name) for name in _DOC_SECTION.findall(text)[:_MAX_DOC_SECTIONS]]
        # 제목도 절도 없으면 문서라 부를 근거가 없다 — 조각글·라이선스 본문 따위다.
        if not title and not sections:
            continue
        role = "doc: " + (_safe_label(title.group(1)) if title else path.stem)
        if sections:
            role += " · sections: " + "; ".join(name for name in sections if name)
        rendered.append((path.as_posix(), role))
    return rendered


def _orientation_rows(root: Path, files: list[Path], landmarks: int, *, peer: str, omitted: int) -> list[str]:
    """`## Orientation` 본문. 짝 지도는 네 줄을 더 단다 — 뿌리 표기, 그래프 경계, 신선도, 잘린 수."""
    languages = Counter(_LANGUAGE_BY_SUFFIX[p.suffix.lower()] for p in files if p.suffix.lower() in _LANGUAGE_BY_SUFFIX)
    language_text = ", ".join(f"{name} ({count})" for name, count in languages.most_common()) or "not inferred"
    rows = [
        f"- Project root: `{peer + '/' if peer else './'}`",
        f"- Languages by observed source files: {language_text}",
        f"- Evidence scan: {len(files)} files; {landmarks} landmarks",
    ]
    if not peer:
        return rows
    rows += [
        "- Declared work root of the session repository — paths below open as written from `./`.",
        "- The relation graph (`asgard map impact` / `trace`) covers the session repository only.",
        f"- Source revision: {_peer_revision(root)}",
    ]
    if omitted:
        rows.append(f"- Files omitted by peer budget: {omitted} of {len(files) + omitted}")
    return rows


def _landmark_rows(entries: dict[str, str], prefix: str) -> list[str]:
    shown = list(entries.items())[:_MAX_LANDMARKS]
    rows = [f"- `{prefix}{path}` — {role}" for path, role in shown]
    if len(entries) > len(shown):
        rows.append(f"- Additional landmarks omitted by budget: {len(entries) - len(shown)}")
    if not entries:
        rows.append("- `(none yet)` — add project files, then rerun `asgard map update`")
    return rows


def _render(root: Path, *, peer: str = "") -> tuple[str, int, int, str]:
    """지도 문서 하나. `peer` 가 있으면 그 라벨의 짝 저장소 지도이고, 항목 경로 앞에 라벨이 붙는다.

    짝 지도가 세션 지도와 다른 것은 셋이다. 항목 경로가 세션 뿌리 기준이라 그대로 열리고, 검증 명령
    구간이 없고(그 명령은 저쪽 저장소에서 돌려야 한다), 파일 수에 상한이 있다."""
    files = _files(root)
    prefix = peer + "/" if peer else ""
    omitted_files = 0
    if peer:
        files, omitted_files = _budget_files(files, _MAX_PEER_FILES)
    entries = _landmarks(root, files)
    project = _project_name(root)
    lines = [
        _GENERATED_MARKER,
        f"# Peer Map — {project}" if peer else f"# Project Map — {project}",
        "",
        "> Asgard managed orientation map. Regenerate with `asgard map update`; do not hand-edit this file.",
        "> It is a navigation hint, not completion evidence: re-read every path used by a plan.",
        "",
        "## Orientation",
        "",
        *_orientation_rows(root, files, len(entries), peer=peer, omitted=omitted_files),
        "",
        "## Landmarks",
        "",
        *_landmark_rows(entries, prefix),
    ]
    # 검증 명령은 그 명령이 도는 저장소의 것이다. 짝 지도에 넣으면 주입면이 "질의에 가까운 이
    # 저장소의 명령"으로 내보내는데, 세션 뿌리에서 돌리면 그 명령은 없거나 다른 프로젝트를 검사한다.
    if not peer:
        commands = _verification_commands(root, files)
        lines += ["", "## Detected verification", ""]
        lines.extend(f"- Command: `{command}` — {role}" for command, role in commands)
        if not commands:
            lines.append("- No verification command inferred from checked-in manifests.")
    # 문서가 공개 표면보다 앞에 오는 이유는 값이 아니라 예산이다: 표면 행이 예산을 먼저 다 쓰면
    # 문서 레인은 큰 리포에서 한 줄도 못 나온다. 둘 다 자기 상한이 있어 서로를 밀어내지는 않는다.
    lines += ["", "## Documents", ""]
    document_rows = _document_entries(root, files)
    if not document_rows:
        lines.append("- No tracked markdown document with a title or sections.")
    lines.extend(f"- `{prefix}{path}` — {role}" for path, role in document_rows)
    lines += ["", "## Public surfaces", ""]
    surface_rows = _surface_entries(root, files)
    footer = [
        "",
        "## Navigation contract",
        "",
        "- Read `PROJECT.md` first, then the matching human-authored area map if present.",
        "- A `## Documents` row lists a document's own title and sections — open it before re-deriving what it already records.",
        "- Verify target definitions and usages from source before planning or editing.",
        "- Structural changes refresh this managed map before Verifier hashing; use `asgard map check` in CI.",
        "",
    ]
    for path, role in surface_rows:
        candidate = f"- `{prefix}{path}` — {role}"
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


def _peer_targets(base: Path) -> dict[str, tuple[str, Path]]:
    """파일 이름 → (라벨, 짝 저장소 절대경로). 선언이 없으면 빈 사전이다."""
    peers = peer_roots(base)
    names = peer_map_names([label for label, _ in peers])
    return {names[label]: (label, path) for label, path in peers}


def _peer_revision(root: Path) -> str:
    """짝 저장소의 스탯 지문 — 경로·크기·mtime 만 본다, 파일 내용은 안 읽는다.

    이 값이 지도 안에 한 줄로 적히고, 다음 판정은 그 줄만 다시 계산해 비교한다. 대조를 값싸게
    두는 게 요점이다: 신선도 검사는 판정마다 돌고(`hooks/quest_log.py` 의 지도 최신 확인),
    짝이 큰 모노레포면 매번 통째로 다시 그리는 값이 턴마다 붙는다.

    mtime 오탐(내용이 같은 touch)은 다시 그리는 쪽으로만 틀린다 — 낡은 지도를 최신이라 부르지
    않는다. 지도에 실린 파일 집합과 같은 집합을 세야 하므로 상한도 같이 건다."""
    files, _ = _budget_files(_files(root), _MAX_PEER_FILES)
    digest = hashlib.sha256()
    for rel in files:
        try:
            stat = (root / rel).stat()
        except OSError:
            continue
        digest.update(f"{rel.as_posix()}\0{stat.st_size}\0{stat.st_mtime_ns}".encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
    return "source-stat-sha256:" + digest.hexdigest()


def _peer_drift(map_dir: Path, targets: dict[str, tuple[str, Path]]) -> tuple[str, ...]:
    """다시 그려야 하는 짝 지도 이름 — 스탯 지문이 어긋난 것과, 선언이 사라져 남은 것.

    남은 파일을 드리프트로 세는 이유는 지도의 계약이다. 지도에 있는 경로는 디스크에 있어야 하는데,
    선언이 빠진 뒤의 짝 지도는 아무도 안 여는 저장소를 가리키며 계속 답을 낸다."""
    drift = []
    for name, (_label, path) in targets.items():
        recorded = _PEER_REVISION_RE.search(_read_map(map_dir / name))
        if recorded is None or recorded.group(1) != _peer_revision(path):
            drift.append(name)
    for path in sorted(map_dir.glob(PEER_MAP_PREFIX + "*.md")):
        if path.name not in targets and _owned_project_map(_read_map(path)):
            drift.append(path.name)
    return tuple(sorted(set(drift)))


def _read_map(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def check_map(root: str | os.PathLike[str]) -> MapCheck:
    base = Path(root).resolve()
    expected, _, _, _ = _render(base)
    map_dir = _map_dir(base, create=False)
    peer_drift = _peer_drift(map_dir, _peer_targets(base))
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
        ok=actual == expected and trackable and index_current and owned and not peer_drift,
        trackable=trackable,
        index_current=index_current,
        owned=owned,
        peer_drift=peer_drift,
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
    """force=True는 소유권 거부만 우회한다 (init — 현재 디렉토리가 정본인 명시 재설정).
    안전 검사(심링크·경로 탈출·예약 파일명 충돌)는 force와 무관하게 하드 에러."""
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
    targets = _peer_targets(base)
    peers_written = _peer_drift(map_dir, targets)
    for name in peers_written:
        # 사람이 쓴 파일은 이름이 같아도 덮지 않는다 — PROJECT.md 와 같은 소유 규칙이다. 선언이
        # 빠져 지우는 갈래는 `_peer_drift` 가 이미 표식을 봤으므로 여기 안 걸린다.
        existing = _read_map(map_dir / name)
        if name in targets and existing and not _owned_project_map(existing) and not force:
            raise MapOwnershipError(f"refusing to overwrite human-owned {map_dir / name}")
    if not dry_run:
        if index_changed:
            _atomic_write(base, index_path, MAP_INDEX_MD)
        if changed:
            _atomic_write(base, project_path, content)
        for name in peers_written:
            target = map_dir / name
            if name in targets:
                label, peer_path = targets[name]
                _atomic_write(base, target, _render(peer_path, peer=label)[0])
            else:
                target.unlink(missing_ok=True)
    return MapResult(project, changed, files_scanned, landmarks, str(project_path), index_changed, peers_written)
