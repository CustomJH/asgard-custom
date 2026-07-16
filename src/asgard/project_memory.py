"""선택형 backend 기반 프로젝트 메모리의 등록 정책과 artifact projection.

Asgard 메모리는 개인(로컬)과 프로젝트(선택 backend) 두 종류뿐이다. 이 모듈은 세 번째
정본을 만들지 않는다. 코드·문서·Git은 사실의 provenance이고, 활성 backend 하나가 팀 공유
프로젝트 메모리를 저장·검색한다.
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import time
from collections.abc import Iterable, Sequence

from .memory import scan_threats
from .memory_bridge import backend_target, server_retain_items, stage_retain

KINDS = frozenset(
    {
        "decision",
        "policy",
        "contract",
        "component",
        "incident",
        "experiment",
        "migration",
        "runbook",
        "artifact",
    }
)
RELATIONS = frozenset(
    {
        "supersedes",
        "supportedBy",
        "appliesTo",
        "causedBy",
        "resolvedBy",
        "dependsOn",
        "implements",
        "documents",
    }
)
IMPORTANCE = frozenset({"normal", "high", "critical"})
CONFIDENCE = frozenset({"observed", "verified"})
STATUSES = frozenset({"active", "superseded", "historical"})
MAX_ARTIFACT_BYTES = 100_000
PROJECTION_MANIFEST = "project-memory-manifest.json"
PROJECTION_VERSION = 3
PROJECTION_LOCK_TTL = 300
ONTOLOGY_SCHEMA = "asgard-project-artifact-v1"
MAX_ONTOLOGY_VALUE = 512

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
_PLACEHOLDERS = ("example", "placeholder", "changeme", "redacted", "dummy", "test-only", "your-", "your_", "****")
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|secret[_-]?key)\b\s*[:=]\s*[\"']?([^\s\"']{8,})"
    ),
    re.compile(r"\b(?:sk|gh[oprsu]|github_pat)_[A-Za-z0-9_-]{16,}\b"),
    # Codex 교차검증이 지적한 누락 유형. `$VAR`/`{var}`/`<token>` 참조는 값이 아니므로 제외.
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),  # JWT 3분절
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"(?i)--(?:token|password|passwd|api-key|secret)[= ](?![$\{<])\S{8,}"),  # CLI flag-value
    re.compile(r"://[^/\s:@]{1,64}:(?![$\{])[^@\s/]{6,}@"),  # URL 내장 크레덴셜 scheme://user:pass@host
)


@dataclasses.dataclass(frozen=True)
class ProjectRecord:
    record_id: str
    kind: str
    title: str
    content: str
    source: str
    source_revision: str
    importance: str = "high"
    confidence: str = "verified"
    status: str = "active"
    scope: str = "project"
    relations: tuple[dict[str, str], ...] = ()


@dataclasses.dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    reasons: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ArtifactCandidate:
    path: str
    content: str
    content_hash: str
    kind: str
    importance: str
    score: int
    reasons: tuple[str, ...]
    structural_hash: str
    extractor: str
    symbols: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class TurnRetentionResult:
    status: str
    document_id: str = ""
    reason: str = ""


@dataclasses.dataclass(frozen=True)
class CompletionProposalResult:
    status: str
    approval_id: str = ""
    record_id: str = ""
    preview: str = ""
    reason: str = ""


def scan_secrets(*values: str) -> str | None:
    """저장 전 명백한 credential 패턴을 차단한다. placeholder 예시는 허용한다."""
    text = "\n".join(str(v) for v in values if v)
    low = text.lower()
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        sample = match.group(0).lower()
        if any(
            marker in sample or marker in low[max(0, match.start() - 30) : match.end() + 30] for marker in _PLACEHOLDERS
        ):
            continue
        return "credential-like content"
    return None


def validate_record(record: ProjectRecord, root: str | None = None) -> ValidationResult:
    """프로젝트 메모리 등록 기준을 기계적으로 집행한다.

    공유·지속성·검증·provenance·중요도·안전성을 모두 만족해야 한다. `root`는 향후
    repository 정책 확장을 위한 계약이며 source가 URL/test/commit일 수 있어 파일 존재를
    강제하지 않는다.
    """
    del root
    reasons: list[str] = []
    if record.scope != "project":
        reasons.append("scope must be project")
    if record.kind not in KINDS:
        reasons.append("unknown kind")
    if record.importance not in IMPORTANCE:
        reasons.append("invalid importance")
    if record.confidence not in CONFIDENCE:
        reasons.append("unverified confidence")
    if record.status not in STATUSES:
        reasons.append("temporary or invalid status")
    if not record.record_id.strip() or not re.fullmatch(r"[A-Za-z0-9._:-]+", record.record_id):
        reasons.append("invalid record_id")
    if len(record.title.strip()) < 4 or len(record.content.strip()) < 20:
        reasons.append("record is not self-contained")
    if not record.source.strip() or not record.source_revision.strip():
        reasons.append("provenance required")
    for relation in record.relations:
        if relation.get("type") not in RELATIONS or not str(relation.get("target") or "").strip():
            reasons.append("invalid relation")
            break
    threat = scan_threats(record.title, record.content, record.source)
    if threat:
        reasons.append(f"prompt injection: {threat}")
    secret = scan_secrets(record.title, record.content, record.source)
    if secret:
        reasons.append(secret)
    return ValidationResult(not reasons, tuple(reasons))


def _neutral_line(value: str) -> str:
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())


def retain_turn(
    root: str,
    cfg: dict,
    *,
    session_id: str,
    turn_id: str,
    user_text: str,
    assistant_text: str,
    mode: str,
) -> TurnRetentionResult:
    """한 user/assistant turn을 idempotent backend record로 opt-in retain한다."""
    del root
    user = str(user_text).strip()
    assistant = str(assistant_text).strip()
    if not user or not assistant:
        return TurnRetentionResult("skipped", reason="empty turn")
    secret = scan_secrets(user, assistant)
    if secret:
        return TurnRetentionResult("skipped", reason=secret)
    threat = scan_threats(user, assistant)
    if threat:
        return TurnRetentionResult("skipped", reason=f"prompt injection: {threat}")
    target = backend_target(cfg)
    project = str(target["project_id"])
    project_uid = str(target.get("project_uid") or "")
    binding_id = str(target.get("binding_id") or "")
    if not project:
        return TurnRetentionResult("skipped", reason="project_id missing")
    stable = hashlib.sha256(f"{project_uid}\0{binding_id}\0{session_id}\0{turn_id}".encode()).hexdigest()[:24]
    document_id = f"asgard:turn:{stable}"
    clean_mode = _neutral_line(mode)
    content = (
        "[ProjectTurn]\n"
        f"Mode: {clean_mode}\n"
        f"Session: {_neutral_line(session_id)}\n"
        f"Turn: {_neutral_line(turn_id)}\n\n"
        f"User: {user[:6000]}\n\n"
        f"Assistant: {assistant[:6000]}"
    )
    item = {
        "content": content,
        "context": "asgard project conversation turn",
        "document_id": document_id,
        "update_mode": "replace",
        "tags": [f"project:{project}", "kind:turn", f"mode:{clean_mode}"],
        "metadata": {
            "scope": "project",
            "kind": "turn",
            "session_id": _neutral_line(session_id),
            "turn_id": _neutral_line(turn_id),
            "mode": clean_mode,
            "trust": "untrusted-conversation",
            "project_uid": project_uid,
            "binding_id": binding_id,
            "record_schema": "asgard-project-memory-v1",
        },
    }
    try:
        result = server_retain_items(cfg, [item])
    except Exception as exc:
        return TurnRetentionResult("failed", document_id=document_id, reason=type(exc).__name__)
    if result.get("success") is not True:
        return TurnRetentionResult(
            "failed", document_id=document_id, reason=str(result.get("error") or "retain rejected")
        )
    return TurnRetentionResult("retained", document_id=document_id)


def _completion_kind(request: str) -> str:
    low = request.lower()
    for kind, words in (
        ("migration", ("migration", "마이그레이션", "schema 변경")),
        ("incident", ("incident", "장애", "재발", "복구")),
        ("experiment", ("benchmark", "실험", "평가", "비교")),
        ("policy", ("policy", "정책", "보안 규칙")),
        ("decision", ("decision", "결정", "선택")),
        ("contract", ("contract", "계약", "public api", "프로토콜")),
        ("runbook", ("runbook", "운영 절차", "배포 절차")),
    ):
        if any(word in low for word in words):
            return kind
    return "component"


def propose_completion(
    root: str,
    cfg: dict,
    *,
    session_id: str,
    request: str,
    response: str,
    changed_files: Sequence[str],
    evidence: Sequence[dict],
    verified: bool,
) -> CompletionProposalResult:
    """검증 완료된 write 과업을 구조화 record로 제안하되 원격 저장은 승인 전까지 하지 않는다."""
    files = [str(path).strip() for path in changed_files if str(path).strip()]
    if not verified or not files:
        return CompletionProposalResult("skipped", reason="verified changed task required")
    if any(os.path.basename(path).lower() in _SECRET_NAMES for path in files):
        return CompletionProposalResult("skipped", reason="secret path")
    kind = _completion_kind(request)
    important_component = any(
        os.path.basename(path).lower() in _MANIFESTS
        or os.path.basename(path).lower().startswith("readme")
        or any(word in path.lower().replace("-", "_") for word in _IMPORTANT_CODE_WORDS)
        for path in files
    )
    if kind == "component" and not important_component:
        return CompletionProposalResult("skipped", reason="completed change is not important project history")
    revision = source_revision(root)
    successful = [
        f"{str(row.get('cmd') or '').strip()} (exit {row.get('exit_code')})"
        for row in evidence
        if isinstance(row, dict) and row.get("exit_code") == 0 and str(row.get("cmd") or "").strip()
    ]
    title = _neutral_line(request)[:120]
    summary = _neutral_line(response)[:600]
    content = (
        f"검증 완료된 프로젝트 과업: {title}\n"
        f"결과: {summary}\n"
        f"변경 파일: {', '.join(files[:30])}\n"
        f"검증 증거: {'; '.join(successful[:10]) or '(quest verifier PASS)'}"
    )
    digest = hashlib.sha256(f"{session_id}\0{revision}\0{title}".encode()).hexdigest()[:20]
    record = ProjectRecord(
        record_id=f"completion.{digest}",
        kind=kind,
        title=title,
        content=content,
        source=f"quest:{_neutral_line(session_id)}",
        source_revision=revision,
        importance="high",
        confidence="verified",
    )
    validation = validate_record(record, root)
    if not validation.accepted:
        return CompletionProposalResult("skipped", reason="; ".join(validation.reasons))
    target = backend_target(cfg)
    item = record_item(
        record,
        str(target["project_id"]),
        project_uid=str(target.get("project_uid") or ""),
        binding_id=str(target.get("binding_id") or ""),
    )
    approval_id = stage_retain(root, item, target=backend_target(cfg))
    preview = (
        render_record(record)
        + f"\n\napproval_id: {approval_id}\n"
        + f"사용자 승인: asgard memory project-approve {approval_id} (또는 MCP memory_retain_commit)"
    )
    return CompletionProposalResult("proposed", approval_id, record.record_id, preview)


def render_record(record: ProjectRecord) -> str:
    """backend가 provider-side extraction 없이도 검색할 수 있는 ontology-informed 자립 문장."""
    lines = [
        f"[ProjectMemory:{record.kind}:{record.record_id}]",
        f"Title: {_neutral_line(record.title)}",
        f"Status: {record.status}",
        f"Importance: {record.importance}",
        f"Confidence: {record.confidence}",
        f"Source: {_neutral_line(record.source)} @ {_neutral_line(record.source_revision)}",
        "",
        record.content.strip(),
    ]
    if record.relations:
        lines.extend(["", "Relations:"])
        lines.extend(f"- {relation['type']}: {_neutral_line(relation['target'])}" for relation in record.relations)
    return "\n".join(lines)


def record_item(
    record: ProjectRecord,
    project_id: str,
    *,
    project_uid: str = "",
    binding_id: str = "",
) -> dict:
    validation = validate_record(record)
    if not validation.accepted:
        raise ValueError("project memory rejected: " + "; ".join(validation.reasons))
    project = _neutral_line(project_id)
    stable_record = hashlib.sha256((project_uid + "\0" + record.record_id).encode()).hexdigest()[:24]
    return {
        "content": render_record(record),
        "context": f"asgard project {record.kind}",
        "document_id": f"asgard:record:{stable_record}",
        "update_mode": "replace",
        "tags": [
            f"project:{project}",
            f"kind:{record.kind}",
            f"importance:{record.importance}",
            f"status:{record.status}",
        ],
        "metadata": {
            "record_id": record.record_id,
            "kind": record.kind,
            "source": record.source,
            "source_revision": record.source_revision,
            "importance": record.importance,
            "confidence": record.confidence,
            "status": record.status,
            "scope": "project",
            "project_uid": project_uid,
            "binding_id": binding_id,
            "record_schema": "asgard-project-memory-v1",
        },
    }


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
            content = open(full, encoding="utf-8").read()
        except OSError, UnicodeError:
            continue
        if not content.strip() or scan_secrets(content):
            continue
        score, kind, importance, reasons = _assess(norm, content, norm in changed)
        if score < 35:
            continue
        content_hash = hashlib.sha256(content.encode()).hexdigest()
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


def artifact_item(
    candidate: ArtifactCandidate,
    project_id: str,
    source_revision: str,
    *,
    project_uid: str = "",
    binding_id: str = "",
) -> dict:
    path_hash = hashlib.sha256(f"{project_uid}\0{candidate.path}".encode()).hexdigest()[:24]
    symbols = ", ".join(candidate.symbols)[:MAX_ONTOLOGY_VALUE]
    imports = ", ".join(candidate.imports)[:MAX_ONTOLOGY_VALUE]
    header = (
        f"[ProjectArtifact:{candidate.kind}]\n"
        f"Path: {candidate.path}\n"
        f"Revision: {source_revision}\n"
        f"Content-SHA256: {candidate.content_hash}\n"
        f"Symbols: {symbols or '(none)'}\n"
        f"Imports: {imports or '(none)'}\n"
        f"Importance: {candidate.importance}\n\n"
    )
    return {
        "content": header + candidate.content,
        "context": f"asgard project artifact {candidate.kind}",
        "document_id": f"asgard:artifact:{path_hash}",
        "update_mode": "replace",
        "tags": [f"project:{project_id}", "artifact", f"kind:{candidate.kind}", f"importance:{candidate.importance}"],
        "metadata": {
            "source": candidate.path,
            "source_revision": source_revision,
            "content_hash": candidate.content_hash,
            "structural_hash": candidate.structural_hash,
            "ontology_schema": ONTOLOGY_SCHEMA,
            "ontology_type": "source-artifact",
            "origin": "deterministic",
            "extractor": candidate.extractor,
            "symbols": symbols,
            "imports": imports,
            "kind": candidate.kind,
            "importance": candidate.importance,
            "scope": "project",
            "status": "active",
            "confidence": "verified",
            "project_uid": project_uid,
            "binding_id": binding_id,
            "record_schema": "asgard-project-memory-v1",
        },
    }


def _artifact_document_id(path: str, project_uid: str = "") -> str:
    path_hash = hashlib.sha256((project_uid + "\0" + path).encode()).hexdigest()[:24]
    return f"asgard:artifact:{path_hash}"


def _projection_manifest_path(root: str) -> str:
    return os.path.join(root, ".asgard", "state", PROJECTION_MANIFEST)


def load_projection_manifest(root: str) -> dict:
    """Manifest 부재는 bootstrap, 파손은 stale remote 정리를 보존하기 위해 fail-closed."""
    path = _projection_manifest_path(root)
    if not os.path.exists(path):
        return {
            "version": PROJECTION_VERSION,
            "backend": "",
            "project_id": "",
            "project_uid": "",
            "binding_id": "",
            "target_fingerprint": "",
            "last_synced_revision": "",
            "items": {},
        }
    try:
        with open(path, encoding="utf-8") as source:
            data = json.load(source)
        if isinstance(data, dict) and data.get("version") in (1, 2) and isinstance(data.get("items"), dict):
            # Unbound manifests must never authorize foreign tombstones. Bootstrap from local source instead.
            data = {
                **data,
                "version": PROJECTION_VERSION,
                "backend": "",
                "project_id": str(data.get("bank") or ""),
                "project_uid": "",
                "binding_id": "",
                "target_fingerprint": "",
                "items": {},
            }
            data.pop("bank", None)
        items = data.get("items") if isinstance(data, dict) else None
        if (
            not isinstance(data, dict)
            or data.get("version") != PROJECTION_VERSION
            or not isinstance(items, dict)
            or not all(
                isinstance(data.get(field), str)
                for field in ("backend", "project_id", "project_uid", "binding_id", "target_fingerprint")
            )
        ):
            raise ValueError("unsupported projection manifest")
        for source_path, entry in items.items():
            if (
                not isinstance(source_path, str)
                or _canonical_repo_path(os.path.realpath(root), source_path) != source_path
                or not isinstance(entry, dict)
                or not all(
                    isinstance(entry.get(field), str) and entry[field]
                    for field in ("document_id", "content_hash", "structural_hash", "kind", "status")
                )
            ):
                raise ValueError("malformed projection manifest item")
        return data
    except (OSError, AttributeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("project memory projection manifest is corrupt; rebuild explicitly") from exc


@contextlib.contextmanager
def _projection_guard(root: str):
    """Kernel-owned advisory lock; process death releases it without stale-file reclamation."""
    lock = _projection_manifest_path(root) + ".lock"
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    deadline = time.monotonic() + 5
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        while not acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("project memory projection lock timeout")
                time.sleep(0.01)
        owner = f"{os.getpid()}:{secrets.token_hex(8)}"
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, owner.encode())
        os.fsync(fd)
        yield
    finally:
        try:
            if acquired:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _save_projection_manifest(root: str, data: dict) -> None:
    path = _projection_manifest_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
        directory = os.open(os.path.dirname(path), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


def projection_plan(
    root: str,
    project_id: str,
    candidates: Iterable[ArtifactCandidate],
    *,
    force: bool = False,
    target: dict | None = None,
) -> dict:
    current = {candidate.path: candidate for candidate in candidates}
    manifest = load_projection_manifest(root)
    target_identity = target or {"engine": "", "project_id": project_id, "fingerprint": ""}
    same_target = (
        manifest.get("backend") == target_identity.get("engine")
        and manifest.get("project_id") == target_identity.get("project_id")
        and manifest.get("project_uid") == target_identity.get("project_uid")
        and manifest.get("binding_id") == target_identity.get("binding_id")
        and manifest.get("target_fingerprint") == target_identity.get("fingerprint")
    )
    previous = manifest.get("items", {}) if same_target else {}
    upserts = [
        candidate
        for path, candidate in sorted(current.items())
        if force
        or previous.get(path, {}).get("content_hash") != candidate.content_hash
        or previous.get(path, {}).get("structural_hash") != candidate.structural_hash
    ]
    removed_paths = sorted(set(previous) - set(current))
    new_by_hash: dict[str, list[str]] = {}
    for path, candidate in current.items():
        if path not in previous:
            new_by_hash.setdefault(candidate.content_hash, []).append(path)
    old_by_hash: dict[str, list[str]] = {}
    for path in removed_paths:
        old_by_hash.setdefault(str(previous[path].get("content_hash") or ""), []).append(path)
    renamed: dict[str, str] = {}
    for path in removed_paths:
        content_hash = str(previous[path].get("content_hash") or "")
        matches = new_by_hash.get(content_hash, [])
        if len(matches) == 1 and len(old_by_hash.get(content_hash, [])) == 1:
            renamed[path] = matches[0]
    return {
        "manifest": manifest,
        "target": target_identity,
        "previous": previous,
        "current": current,
        "upserts": upserts,
        "removed": removed_paths,
        "renamed": renamed,
    }


def projection_plan_id(project_id: str, plan: dict, source_revision: str, *, force: bool = False) -> str:
    """실제로 publish할 전체 payload와 provenance revision을 식별한다."""
    target = plan.get("target") or {}
    project_uid = str(target.get("project_uid") or "")
    binding_id = str(target.get("binding_id") or "")
    items = [
        artifact_item(
            candidate,
            project_id,
            source_revision,
            project_uid=project_uid,
            binding_id=binding_id,
        )
        for candidate in plan["upserts"]
    ]
    items.extend(
        _tombstone_item(
            path,
            plan["previous"][path],
            project_id,
            source_revision,
            plan["renamed"].get(path, ""),
            project_uid=project_uid,
            binding_id=binding_id,
        )
        for path in plan["removed"]
    )
    payload = {
        "target": plan.get("target") or {"engine": "", "project_id": project_id, "fingerprint": ""},
        "mode": "force-all" if force else "manifest-diff",
        "source_revision": source_revision,
        "items": items,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _tombstone_item(
    path: str,
    entry: dict,
    project_id: str,
    revision: str,
    renamed_to: str = "",
    *,
    project_uid: str = "",
    binding_id: str = "",
) -> dict:
    status = "renamed" if renamed_to else "deleted"
    content = f"[ProjectArtifactTombstone]\nPath: {path}\nStatus: {status}\nRevision: {revision}"
    if renamed_to:
        content += f"\nRenamed-To: {renamed_to}"
    metadata = {
        "source": path,
        "source_revision": revision,
        "content_hash": entry.get("content_hash", ""),
        "structural_hash": entry.get("structural_hash", ""),
        "kind": entry.get("kind", "artifact"),
        "scope": "project",
        "origin": "deterministic",
        "status": status,
        "project_uid": project_uid,
        "binding_id": binding_id,
        "record_schema": "asgard-project-memory-v1",
    }
    if renamed_to:
        metadata["renamed_to"] = renamed_to
    return {
        "content": content,
        "context": "asgard project artifact tombstone",
        "document_id": entry.get("document_id") or _artifact_document_id(path, project_uid),
        "update_mode": "replace",
        "tags": [f"project:{project_id}", "artifact", f"status:{status}"],
        "metadata": metadata,
    }


def _projection_summary(plan: dict) -> dict:
    return {
        "upserted_count": len(plan["upserts"]),
        "deleted_count": len(plan["removed"]) - len(plan["renamed"]),
        "renamed_count": len(plan["renamed"]),
        "paths": [candidate.path for candidate in plan["upserts"]],
        "removed": [
            {
                "path": path,
                "status": "renamed" if path in plan["renamed"] else "deleted",
                "renamed_to": plan["renamed"].get(path, ""),
            }
            for path in plan["removed"]
        ],
    }


def sync_artifacts(
    root: str,
    cfg: dict,
    candidates: Iterable[ArtifactCandidate],
    *,
    source_revision: str | None = None,
    force: bool = False,
    expected_plan_id: str | None = None,
) -> dict:
    target = backend_target(cfg)
    project_id = str(target["project_id"])
    candidate_list = list(candidates)
    with _projection_guard(root):
        revision = source_revision or globals()["source_revision"](root)
        for candidate in candidate_list:
            canonical = _canonical_repo_path(os.path.realpath(root), candidate.path)
            if canonical != candidate.path:
                raise ValueError(f"non-canonical project artifact path: {candidate.path}")
            try:
                with open(os.path.join(root, candidate.path), "rb") as source:
                    live_hash = hashlib.sha256(source.read()).hexdigest()
            except OSError as exc:
                raise ValueError(f"project artifact changed after scan: {candidate.path}") from exc
            if live_hash != candidate.content_hash:
                raise ValueError(f"project artifact changed after scan: {candidate.path}")
        plan = projection_plan(root, project_id, candidate_list, force=force, target=target)
        actual_plan_id = projection_plan_id(project_id, plan, revision, force=force)
        if expected_plan_id is not None and not secrets.compare_digest(expected_plan_id, actual_plan_id):
            raise ValueError("project memory sync plan changed; preview again")
        project_uid = str(target.get("project_uid") or "")
        binding_id = str(target.get("binding_id") or "")
        items = [
            artifact_item(
                candidate,
                project_id,
                revision,
                project_uid=project_uid,
                binding_id=binding_id,
            )
            for candidate in plan["upserts"]
        ]
        items.extend(
            _tombstone_item(
                path,
                plan["previous"][path],
                project_id,
                revision,
                plan["renamed"].get(path, ""),
                project_uid=project_uid,
                binding_id=binding_id,
            )
            for path in plan["removed"]
        )
        result = server_retain_items(cfg, items) if items else {"success": True}
        summary = _projection_summary(plan)
        if result.get("success") is not True:
            return {
                **result,
                **summary,
                "items_count": len(items),
                "plan_id": actual_plan_id,
            }
        manifest_items = {
            candidate.path: {
                "document_id": _artifact_document_id(candidate.path, project_uid),
                "content_hash": candidate.content_hash,
                "structural_hash": candidate.structural_hash,
                "extractor": candidate.extractor,
                "kind": candidate.kind,
                "status": "active",
            }
            for candidate in candidate_list
        }
        _save_projection_manifest(
            root,
            {
                "version": PROJECTION_VERSION,
                "backend": target["engine"],
                "project_id": project_id,
                "project_uid": project_uid,
                "binding_id": binding_id,
                "target_fingerprint": target["fingerprint"],
                "last_synced_revision": revision,
                "items": manifest_items,
            },
        )
        return {
            **result,
            **summary,
            "success": True,
            "items_count": len(items),
            "plan_id": actual_plan_id,
        }
