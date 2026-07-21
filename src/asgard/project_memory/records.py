"""등록 정책의 순수 계층 — 상수·record dataclass·검증·직렬화(backend IO 없음)."""

from __future__ import annotations

import dataclasses
import hashlib
import re

from ..memory import policy as _memory_policy
from ..memory import scan_secrets, scan_threats

_PLACEHOLDERS = _memory_policy._SECRET_PLACEHOLDERS
_SECRET_PATTERNS = _memory_policy._SECRET_PATTERNS

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
ONTOLOGY_SCHEMA = "asgard-project-artifact-v1"
MAX_ONTOLOGY_VALUE = 512


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
    relation_values: list[str] = []
    for relation in record.relations:
        if relation.get("type") not in RELATIONS or not str(relation.get("target") or "").strip():
            reasons.append("invalid relation")
            break
        relation_values.extend((str(relation.get("type") or ""), str(relation.get("target") or "")))
    threat = scan_threats(record.title, record.content, record.source, record.source_revision, *relation_values)
    if threat:
        reasons.append(f"prompt injection: {threat}")
    secret = scan_secrets(record.title, record.content, record.source, record.source_revision, *relation_values)
    if secret:
        reasons.append(secret)
    return ValidationResult(not reasons, tuple(reasons))


def _neutral_line(value: str) -> str:
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())


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
    content = render_record(record)
    return {
        "content": content,
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
            "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        },
        # 승인 파일에는 backend payload와 함께 backend-neutral 원자료를 보관한다. backend
        # adapter는 이 키를 무시하고, 승인 commit/rehydrate만 정본 생성에 사용한다.
        "record": {
            "schema": "asgard-project-memory-v1",
            "record_id": record.record_id,
            "kind": record.kind,
            "title": record.title,
            "content": record.content.strip(),
            "source": record.source,
            "source_revision": record.source_revision,
            "importance": record.importance,
            "confidence": record.confidence,
            "status": record.status,
            "scope": record.scope,
            "relations": [dict(relation) for relation in record.relations],
        },
    }
