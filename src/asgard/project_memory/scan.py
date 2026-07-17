"""아티팩트 채굴 — Git/worktree 스캔, 구조 fingerprint, 중요도 평가 (결정론)."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Sequence

from .records import MAX_ARTIFACT_BYTES, ArtifactCandidate, scan_secrets

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "target",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".asgard",
    }
)
_SECRET_NAMES = frozenset({".env", ".env.local", ".npmrc", ".pypirc", "credentials", "credentials.json"})
_TEXT_EXTENSIONS = frozenset(
    {
        ".md",
        ".mdx",
        ".rst",
        ".txt",
        ".py",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".jsonl",
        ".xml",
        ".owl",
        ".ttl",
        ".sql",
        ".sh",
        ".bash",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".proto",
    }
)
_MANIFESTS = frozenset(
    {
        "pyproject.toml",
        "package.json",
        "cargo.toml",
        "go.mod",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    }
)
_IMPORTANT_CODE_WORDS = frozenset(
    {
        "api",
        "auth",
        "cli",
        "config",
        "contract",
        "gateway",
        "hook",
        "main",
        "memory",
        "migration",
        "model",
        "provider",
        "schema",
        "security",
        "settings",
        "storage",
    }
)


def _git_paths(root: str) -> list[str] | None:
    try:
        result = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True, timeout=10)
        return [p.decode("utf-8", "surrogateescape") for p in result.stdout.split(b"\0") if p]
    except Exception:
        return None


def _walk_paths(root: str) -> list[str]:
    paths: list[str] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS]
        for name in files:
            paths.append(os.path.relpath(os.path.join(base, name), root).replace(os.sep, "/"))
    return paths


def changed_paths(root: str) -> list[str]:
    """HEAD 대비 tracked 변경과 untracked 파일을 반환한다. Git 불능이면 빈 목록."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"], cwd=root, capture_output=True, check=True, timeout=10
        )
        out: list[str] = []
        entries = [e for e in result.stdout.split(b"\0") if e]
        index = 0
        while index < len(entries):
            raw = entries[index].decode("utf-8", "surrogateescape")
            path = raw[3:] if len(raw) >= 4 else ""
            if raw[:2].strip().startswith(("R", "C")) and index + 1 < len(entries):
                # porcelain -z emits `R  new-path\0old-path\0`; retain the current path
                # and consume the historical path so it is not parsed as another entry.
                index += 1
            if path:
                out.append(path.replace(os.sep, "/"))
            index += 1
        return sorted(set(out))
    except Exception:
        return []


def source_revision(root: str) -> str:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True, timeout=10
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"], cwd=root, capture_output=True, check=True, timeout=10
        ).stdout
        if not status:
            return f"HEAD={head}"
        digest = hashlib.sha256(status)
        for path in changed_paths(root):
            digest.update(path.encode("utf-8", "surrogateescape"))
            full = os.path.join(root, path)
            try:
                with open(full, "rb") as source:
                    for chunk in iter(lambda: source.read(64 * 1024), b""):
                        digest.update(chunk)
            except OSError:
                digest.update(b"<deleted>")
        return f"HEAD={head};WORKTREE={digest.hexdigest()}"
    except Exception:
        return "HEAD=working-tree"


def _is_text_candidate(path: str) -> bool:
    name = os.path.basename(path).lower()
    suffix = os.path.splitext(name)[1]
    return name in _MANIFESTS or suffix in _TEXT_EXTENSIONS


def _python_signal(content: str) -> tuple[int, list[str]]:
    try:
        tree = ast.parse(content)
    except SyntaxError, ValueError:
        return 0, []
    points, reasons = 0, []
    if ast.get_docstring(tree):
        points += 8
        reasons.append("module documentation")
    public = [
        n.name
        for n in tree.body
        if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
    ]
    if public:
        points += min(12, 4 + len(public) * 2)
        reasons.append("public code contract")
    return points, reasons


def _node_signature(node: ast.AST | None) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False) if node is not None else ""


def _argument_signature(arguments: ast.arguments) -> dict:
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults = [None] * (len(positional) - len(arguments.defaults)) + list(arguments.defaults)

    def render(kind: str, arg: ast.arg, default: ast.AST | None = None) -> dict:
        return {
            "kind": kind,
            "name": arg.arg,
            "annotation": _node_signature(arg.annotation),
            "default": _node_signature(default),
        }

    posonly_count = len(arguments.posonlyargs)
    return {
        "positional": [
            render("posonly" if index < posonly_count else "positional", arg, defaults[index])
            for index, arg in enumerate(positional)
        ],
        "vararg": render("vararg", arguments.vararg) if arguments.vararg else None,
        "kwonly": [
            render("kwonly", arg, arguments.kw_defaults[index]) for index, arg in enumerate(arguments.kwonlyargs)
        ],
        "kwarg": render("kwarg", arguments.kwarg) if arguments.kwarg else None,
    }


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    return {
        "name": node.name,
        "async": isinstance(node, ast.AsyncFunctionDef),
        "args": _argument_signature(node.args),
        "returns": _node_signature(node.returns),
        "decorators": tuple(_node_signature(decorator) for decorator in node.decorator_list),
        "type_params": tuple(_node_signature(parameter) for parameter in getattr(node, "type_params", ())),
    }


def _structure(path: str, content: str, content_hash: str) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    """재생성 가능한 구조 fingerprint. 구현 본문은 제외하고 public topology만 hash한다."""
    if not path.lower().endswith(".py"):
        return content_hash, "content-v1", (), ()
    try:
        tree = ast.parse(content)
    except SyntaxError, ValueError:
        return content_hash, "python-ast-v2-degraded", (), ()
    symbols: list[str] = []
    imports: list[str] = []
    functions: list[dict] = []
    classes: list[dict] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(f"function:{node.name}")
            functions.append(_function_signature(node))
        elif isinstance(node, ast.ClassDef):
            symbols.append(f"class:{node.name}")
            methods = [
                _function_signature(child)
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            classes.append(
                {
                    "name": node.name,
                    "bases": tuple(_node_signature(base) for base in node.bases),
                    "keywords": tuple(
                        (keyword.arg or "**", _node_signature(keyword.value)) for keyword in node.keywords
                    ),
                    "decorators": tuple(_node_signature(decorator) for decorator in node.decorator_list),
                    "type_params": tuple(_node_signature(parameter) for parameter in getattr(node, "type_params", ())),
                    "methods": methods,
                }
            )
        elif isinstance(node, ast.Import):
            imports.extend(
                alias.name if alias.asname is None else f"{alias.name} as {alias.asname}" for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            aliases = ",".join(
                alias.name if alias.asname is None else f"{alias.name} as {alias.asname}" for alias in node.names
            )
            imports.append(f"{module}:{aliases}")
    payload = {
        "functions": functions,
        "classes": classes,
        "imports": sorted(imports),
    }
    structural_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return structural_hash, "python-ast-v2", tuple(sorted(symbols)), tuple(sorted(imports))


def _assess(path: str, content: str, changed: bool) -> tuple[int, str, str, list[str]]:
    low = path.lower()
    name = os.path.basename(low)
    parts = [p for p in low.split("/") if p]
    score, reasons, kind = 0, [], "artifact"
    if name.startswith("readme") or name in {"agents.md", "claude.md", "contributing.md"}:
        score += 55
        reasons.append("project governance/documentation")
        kind = "policy"
    if name in _MANIFESTS:
        score += 50
        reasons.append("build/runtime contract")
        kind = "contract"
    if any(p in {"docs", "doc", "adr", "adrs", "architecture", "design", "runbooks"} for p in parts[:-1]):
        score += 45
        reasons.append("architecture/history document")
        kind = "decision" if "adr" in parts or "adrs" in parts else "artifact"
    if any(p in {"migrations", "migration", "schemas", "schema"} for p in parts[:-1]):
        score += 40
        reasons.append("data/interface evolution")
        kind = "migration" if "migration" in low else "contract"
    if low.startswith(("src/", "lib/", "app/")):
        score += 10
        reasons.append("production source")
        kind = "component"
        stem_words = set(re.split(r"[^a-z0-9]+", os.path.splitext(name)[0]))
        if stem_words & _IMPORTANT_CODE_WORDS:
            score += 20
            reasons.append("core boundary name")
        if name.endswith(".py"):
            extra, why = _python_signal(content)
            score += extra
            reasons.extend(why)
    if changed:
        score += 25
        reasons.append("working-tree change")
    importance = "critical" if score >= 65 else "high" if score >= 45 else "normal"
    return score, kind, importance, reasons


def _canonical_repo_path(root: str, path: str) -> str | None:
    raw = path.replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        return None
    normalized = os.path.normpath(raw).replace(os.sep, "/")
    if normalized in ("", ".") or normalized == ".." or normalized.startswith("../"):
        return None
    full = os.path.realpath(os.path.join(root, normalized))
    try:
        if os.path.commonpath((root, full)) != root:
            return None
    except ValueError:
        return None
    return os.path.relpath(full, root).replace(os.sep, "/")


def scan_project(root: str, changed_paths: Sequence[str] | None = None) -> list[ArtifactCandidate]:
    """중요한 tracked 코드·문서를 결정적으로 선별한다.

    `changed_paths=None`이면 Git 상태를 읽고, 명시한 빈 목록은 전체 baseline 중요도만 평가한다.
    source 파일 전체를 무차별 retain하지 않고 중요도 35점 이상만 반환한다.
    """
    root = os.path.realpath(root)
    raw_changed = changed_paths if changed_paths is not None else globals()["changed_paths"](root)
    changed = {canonical for path in raw_changed if (canonical := _canonical_repo_path(root, path)) is not None}
    paths = _git_paths(root)
    if paths is None:
        paths = _walk_paths(root)
    canonical_paths = {canonical for path in paths if (canonical := _canonical_repo_path(root, path)) is not None}
    candidates: list[ArtifactCandidate] = []
    for norm in sorted(canonical_paths | changed):
        parts = [p.lower() for p in norm.split("/")]
        name = parts[-1] if parts else ""
        if not norm or any(p in _SKIP_DIRS for p in parts[:-1]) or name in _SECRET_NAMES:
            continue
        if parts and parts[0] in {"tests", "test", "spikes", "examples"}:
            continue
        if name.endswith((".lock", ".min.js", ".map")) or not _is_text_candidate(norm):
            continue
        full = os.path.realpath(os.path.join(root, norm))
        if os.path.commonpath([root, full]) != root or not os.path.isfile(full):
            continue
        try:
            if os.path.getsize(full) > MAX_ARTIFACT_BYTES:
                continue
            with open(full, "rb") as source:
                raw_content = source.read()
            content = raw_content.decode("utf-8")
        except OSError, UnicodeError:
            continue
        if not content.strip() or scan_secrets(content):
            continue
        score, kind, importance, reasons = _assess(norm, content, norm in changed)
        if score < 35:
            continue
        # The same raw-byte digest is used by pre-publication TOCTOU checks and ambient
        # freshness checks. Text-mode universal-newline conversion would make CRLF files
        # permanently appear changed on Windows.
        content_hash = hashlib.sha256(raw_content).hexdigest()
        structural_hash, extractor, symbols, imports = _structure(norm, content, content_hash)
        candidates.append(
            ArtifactCandidate(
                path=norm,
                content=content,
                content_hash=content_hash,
                kind=kind,
                importance=importance,
                score=score,
                reasons=tuple(reasons),
                structural_hash=structural_hash,
                extractor=extractor,
                symbols=symbols,
                imports=imports,
            )
        )
    return candidates
