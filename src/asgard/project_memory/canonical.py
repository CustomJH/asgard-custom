"""승인된 프로젝트 record의 Git 정본과 backend 재생."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
from typing import Any, cast

import yaml

from ..memory_bridge import backend_target, claim_retain, finish_retain, server_consolidate, server_retain_items
from .records import ProjectRecord, record_item, validate_record

RECORD_SCHEMA = "asgard-project-memory-v1"
RECORDS_RELATIVE_DIR = os.path.join(".asgard", "memory", "records")
MAX_RECORD_FILE_BYTES = 1_000_000

# 정본 record 가 0건인 상태는 서로 다른 셋이고, 셋 다 items_count 가 0이라 개수로는 안 갈린다.
# 뱅크의 문서 수가 그 셋을 가르는 유일한 관측값이라 빈 계획은 뱅크를 한 번 세고 답한다.
# 정본과 뱅크가 함께 비어 있으면 재수화할 것이 없고, 정본만 비어 있으면 정본이 사라진 것이며,
# 세는 것 자체가 실패하면 어느 쪽인지 모른다 — 셋 다 성공이 아니므로 CLI 는 1을 낸다.
EMPTY_PLAN_MESSAGES: dict[str, str] = {
    "canonical-and-bank-empty": "canonical records are 0 and the bank holds no document; nothing to rehydrate",
    "canonical-empty-bank-holds-records": (
        "canonical records are 0 while the bank holds {count} document(s). The bank was left untouched; "
        "restore {records_dir} (git show <commit>^:{records_dir}/<file>.md) and preview again"
    ),
    "bank-unreachable": (
        "canonical records are 0 and the bank document count is unreachable ({detail}); the bank was left untouched"
    ),
}


def _unsafe_path(path: str) -> bool:
    return os.path.islink(path) or bool(getattr(os.path, "isjunction", lambda _path: False)(path))


def records_dir(root: str, *, create: bool = False) -> str:
    """프로젝트 루트 아래 정본 디렉터리만 허용한다."""
    root = os.path.realpath(root)
    parts = (os.path.join(root, ".asgard"), os.path.join(root, ".asgard", "memory"))
    path = os.path.join(root, RECORDS_RELATIVE_DIR)
    for component in (*parts, path):
        if os.path.lexists(component) and _unsafe_path(component):
            raise ValueError(f"unsafe project memory path: {component}")
    if create:
        os.makedirs(path, exist_ok=True)
    if os.path.exists(path) and not os.path.isdir(path):
        raise ValueError("project memory records path must be a directory")
    return path


def record_filename(record_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", record_id.lower()).strip("-")[:64] or "record"
    digest = hashlib.sha256(record_id.encode()).hexdigest()[:24]
    return f"record-{slug}--{digest}.md"


def _record_from_payload(payload: object, *, content: str | None = None) -> ProjectRecord:
    if not isinstance(payload, dict) or payload.get("schema") != RECORD_SCHEMA:
        raise ValueError("unsupported project memory record schema")
    data = cast(dict[str, Any], payload)
    fields = (
        "record_id",
        "kind",
        "title",
        "source",
        "source_revision",
        "importance",
        "confidence",
        "status",
        "scope",
    )
    if any(not isinstance(data.get(field), str) for field in fields):
        raise ValueError("malformed project memory record metadata")
    raw_relations = data.get("relations", [])
    if not isinstance(raw_relations, list) or not all(
        isinstance(row, dict) and isinstance(row.get("type"), str) and isinstance(row.get("target"), str)
        for row in raw_relations
    ):
        raise ValueError("malformed project memory record relations")
    relations = cast(list[dict[str, Any]], raw_relations)
    body = data.get("content") if content is None else content
    if not isinstance(body, str):
        raise ValueError("malformed project memory record content")
    record = ProjectRecord(
        record_id=data["record_id"],
        kind=data["kind"],
        title=data["title"],
        content=body.strip(),
        source=data["source"],
        source_revision=data["source_revision"],
        importance=data["importance"],
        confidence=data["confidence"],
        status=data["status"],
        scope=str(data.get("scope") or "project"),
        relations=tuple({"type": row["type"], "target": row["target"]} for row in relations),
    )
    validation = validate_record(record)
    if not validation.accepted:
        raise ValueError("invalid project memory record: " + "; ".join(validation.reasons))
    return record


def _frontmatter(record: ProjectRecord) -> dict:
    return {
        "schema": RECORD_SCHEMA,
        "record_id": record.record_id,
        "kind": record.kind,
        "title": record.title,
        "source": record.source,
        "source_revision": record.source_revision,
        "importance": record.importance,
        "confidence": record.confidence,
        "status": record.status,
        "scope": "project",
        "relations": [dict(row) for row in record.relations],
    }


def render_canonical_record(record: ProjectRecord) -> str:
    metadata = yaml.safe_dump(_frontmatter(record), allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{metadata}\n---\n\n{record.content.strip()}\n"


def _parse_canonical_record(text: str) -> ProjectRecord:
    if not text.startswith("---\n"):
        raise ValueError("project memory record is missing YAML frontmatter")
    boundary = text.find("\n---\n", 4)
    if boundary < 0:
        raise ValueError("project memory record has unterminated YAML frontmatter")
    try:
        metadata = yaml.safe_load(text[4:boundary])
    except yaml.YAMLError as exc:
        raise ValueError("project memory record YAML is invalid") from exc
    return _record_from_payload(metadata, content=text[boundary + 5 :])


def _read_record_file(path: str) -> tuple[ProjectRecord, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_RECORD_FILE_BYTES:
            raise ValueError("project memory record must be a small singly-linked regular file")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise ValueError("project memory record must be owned by the current user")
        with os.fdopen(fd, "rb") as source:
            raw = source.read(MAX_RECORD_FILE_BYTES + 1)
        fd = -1
    finally:
        if fd >= 0:
            os.close(fd)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("project memory record must be UTF-8") from exc
    return _parse_canonical_record(text), hashlib.sha256(raw).hexdigest()


def save_canonical_record(root: str, record: ProjectRecord) -> str:
    validation = validate_record(record, root)
    if not validation.accepted:
        raise ValueError("project memory rejected: " + "; ".join(validation.reasons))
    directory = records_dir(root, create=True)
    path = os.path.join(directory, record_filename(record.record_id))
    if os.path.lexists(path) and _unsafe_path(path):
        raise ValueError("project memory record path must not be a symlink or junction")
    data = render_canonical_record(record).encode()
    if len(data) > MAX_RECORD_FILE_BYTES:
        raise ValueError(f"project memory record exceeds {MAX_RECORD_FILE_BYTES} bytes")
    tmp = os.path.join(directory, f".{os.path.basename(path)}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(tmp, flags, 0o644)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        os.replace(tmp, path)
        os.chmod(path, 0o644)
        if os.name != "nt":
            directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)
    return path


def load_canonical_records(root: str) -> list[tuple[ProjectRecord, str, str]]:
    directory = records_dir(root)
    if not os.path.isdir(directory):
        return []
    loaded: list[tuple[ProjectRecord, str, str]] = []
    seen: set[str] = set()
    with os.scandir(directory) as entries:
        for entry in sorted(entries, key=lambda row: row.name):
            if not entry.name.endswith(".md"):
                continue
            if entry.is_symlink():
                raise ValueError(f"project memory record must not be a symlink: {entry.name}")
            record, digest = _read_record_file(entry.path)
            if entry.name != record_filename(record.record_id):
                raise ValueError(f"project memory record filename does not match record_id: {entry.name}")
            if record.record_id in seen:
                raise ValueError(f"duplicate project memory record_id: {record.record_id}")
            seen.add(record.record_id)
            loaded.append((record, os.path.relpath(entry.path, os.path.realpath(root)), digest))
    return loaded


def commit_approved_record(root: str, cfg: dict, approval_id: str) -> dict:
    """승인 claim → Git 정본 → backend replace → 승인 소비 순서를 집행한다."""
    target = backend_target(cfg)
    claimed = claim_retain(root, approval_id, target=target)
    if claimed is None:
        raise ValueError("invalid, expired, claimed, or already consumed approval id")
    staged, token = claimed
    canonical_path = ""
    try:
        item = staged if isinstance(staged, dict) else {"content": staged}
        raw_record = item.get("record") if isinstance(item, dict) else None
        if raw_record is not None:
            record = _record_from_payload(raw_record)
            expected = record_item(
                record,
                str(target["project_id"]),
                project_uid=str(target.get("project_uid") or ""),
                binding_id=str(target.get("binding_id") or ""),
            )
            if item != expected:
                raise ValueError("approved project record does not match its canonical payload")
            canonical_path = save_canonical_record(root, record)
            item = expected
        result = server_retain_items(cfg, [item])
        if result.get("success") is not True:
            raise ValueError(str(result.get("error") or "project memory retain rejected"))
    except Exception as exc:
        finish_retain(root, approval_id, token, success=False)
        if canonical_path:
            relative = os.path.relpath(canonical_path, os.path.realpath(root))
            raise ValueError(
                f"canonical saved → {relative}; backend pending: {exc}; 같은 approval id로 재시도 가능"
            ) from exc
        raise
    # 여기부터는 **이미 적힌 뒤**다 — 정본도 backend도 끝났고 남은 것은 승인 파일의 뒷정리뿐이다.
    # 그 뒷정리가 던지는 것을 그대로 올리면 성공한 쓰기가 실패로 보고되고, 더 나쁘게는 승인이
    # claim에 묶인 채 PENDING_TTL(1시간)만큼 잠긴다: 사람은 "실패했다"는 말을 듣고 재시도하는데
    # 그 재시도마다 같은 id가 거절된다. 그래서 정리 실패는 경고로 내린다.
    #
    # 되돌려 받는 위험은 중복 커밋 하나인데, record는 update_mode=replace에 document_id가
    # 안정적이고 정본 파일명은 record_id에서 나온다 — 같은 승인을 두 번 태워도 같은 자리에
    # 같은 것이 다시 적힌다. 잠긴 승인과 값이 다르다.
    cleanup: dict = {}
    try:
        finish_retain(root, approval_id, token, success=True)
    except Exception as exc:
        cleanup = {"status": "pending", "error": f"{type(exc).__name__}: {exc}"}
    learning: dict = {}
    if raw_record is not None:
        # 정본·backend 저장 성공이 먼저다. observation 예약은 파생 학습층이라 실패해도 승인된
        # 기록을 실패로 되돌리지 않는다 — 다음 project-learn 패스가 미통합 record를 다시 줍는다.
        try:
            learning = server_consolidate(cfg, [["record"]])
        except Exception as exc:
            learning = {"status": "pending", "error": type(exc).__name__}
    return {
        **result,
        "canonical_path": os.path.relpath(canonical_path, os.path.realpath(root)) if canonical_path else "",
        "learning": learning,
        # 빈 dict가 "정리까지 끝났다"이다. 차 있으면 쓰기는 성공했고 승인 파일만 남았다는 뜻이다.
        "approval_cleanup": cleanup,
    }


def rehydration_plan(root: str, cfg: dict) -> dict:
    target = backend_target(cfg)
    loaded = load_canonical_records(root)
    records = [{"record_id": record.record_id, "path": path, "sha256": digest} for record, path, digest in loaded]
    items = [
        record_item(
            record,
            str(target["project_id"]),
            project_uid=str(target.get("project_uid") or ""),
            binding_id=str(target.get("binding_id") or ""),
        )
        for record, _path, _digest in loaded
    ]
    canonical_digest = hashlib.sha256(
        json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    approved = {"schema": 1, "target": target, "canonical_digest": canonical_digest, "records": records, "items": items}
    plan_id = hashlib.sha256(
        json.dumps(approved, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**approved, "plan_id": plan_id}


def rehydrate_records(root: str, cfg: dict, expected_plan_id: str, *, tags_only: bool = False) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_plan_id):
        raise ValueError("invalid rehydrate plan id")
    plan = rehydration_plan(root, cfg)
    if not secrets.compare_digest(expected_plan_id, plan["plan_id"]):
        raise ValueError("rehydrate plan changed; run preview again")
    if not plan["items"]:
        return {**_empty_plan_result(cfg), "plan_id": plan["plan_id"]}
    if tags_only:
        return {**_retag_items(cfg, plan["items"]), "plan_id": plan["plan_id"]}
    result = server_retain_items(cfg, plan["items"])
    return {**result, "plan_id": plan["plan_id"]}


def _empty_plan_result(cfg: dict) -> dict:
    """정본이 0건일 때 뱅크 문서 수로 상태를 가른다 — 어느 갈래에서도 뱅크에 쓰지 않는다."""
    from ..project_memory_backends import get_backend

    count: int | None = None
    detail = ""
    try:
        backend = get_backend(cfg)
        try:
            count = backend.namespace_document_count()
        finally:
            backend.close()
    except Exception as exc:
        code = "bank-unreachable"
        detail = f"{type(exc).__name__}: {exc}"
    else:
        code = "canonical-and-bank-empty" if count == 0 else "canonical-empty-bank-holds-records"
    message = EMPTY_PLAN_MESSAGES[code].format(count=count, records_dir=RECORDS_RELATIVE_DIR, detail=detail)
    return {"success": False, "items_count": 0, "code": code, "bank_documents": count, "error": message}


def _retag_items(cfg: dict, items: list[dict]) -> dict:
    """본문은 그대로 두고 태그만 현재 스키마로 맞춘다 (backend 가 지원할 때만).

    태그 축이 늘어난 뒤 기존 뱅크를 따라오게 하는 값싼 길이다 — 전체 retain 은 항목마다
    서버 추출을 다시 돌리지만 이쪽은 문서 메타데이터만 고친다."""
    from ..project_memory_backends import get_backend

    backend = get_backend(cfg)
    try:
        # 태그만 고치는 것은 backend 계약이 아니라 선택 기능이다 — 없는 backend 는 전체 retain 이
        # 유일한 길이므로 여기서 조용히 성공을 내지 않는다.
        set_tags = getattr(backend, "set_document_tags", None)
        if not callable(set_tags):
            return {"success": False, "items_count": 0, "error": "backend cannot update tags without re-ingesting"}
        failed: dict[str, str] = {}
        done = 0
        for item in items:
            document_id = str(item.get("document_id") or "")
            try:
                if set_tags(document_id, list(item.get("tags") or [])):
                    done += 1
                else:
                    failed[document_id] = "backend rejected the tag update"
            except Exception as exc:
                failed[document_id] = f"{type(exc).__name__}: {exc}"
    finally:
        backend.close()
    return {"success": not failed, "items_count": done, "rejected": failed, "error": ""}
