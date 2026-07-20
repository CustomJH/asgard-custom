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

from ..memory_bridge import backend_target, claim_retain, finish_retain, server_retain_items
from .records import ProjectRecord, record_item, validate_record

RECORD_SCHEMA = "asgard-project-memory-v1"
RECORDS_RELATIVE_DIR = os.path.join(".asgard", "memory", "records")
MAX_RECORD_FILE_BYTES = 1_000_000


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
    finish_retain(root, approval_id, token, success=True)
    return {
        **result,
        "canonical_path": os.path.relpath(canonical_path, os.path.realpath(root)) if canonical_path else "",
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


def rehydrate_records(root: str, cfg: dict, expected_plan_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_plan_id):
        raise ValueError("invalid rehydrate plan id")
    plan = rehydration_plan(root, cfg)
    if not secrets.compare_digest(expected_plan_id, plan["plan_id"]):
        raise ValueError("rehydrate plan changed; run preview again")
    if not plan["items"]:
        return {"success": True, "items_count": 0, "plan_id": plan["plan_id"]}
    result = server_retain_items(cfg, plan["items"])
    return {**result, "plan_id": plan["plan_id"]}
