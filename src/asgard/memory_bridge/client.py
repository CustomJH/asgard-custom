"""backend-neutral 소비 표면 — 선택 backend 에 대한 recall·retain·target fingerprint.

trust 검증 함수(is_backend_trusted·verify_backend_binding·expected_backend_binding)는
호출 시점에 패키지 파사드에서 lazy import 한다 — 소비자 테스트가
`asgard.memory_bridge.*` 네임스페이스를 patch 하는 계약(파사드 단일 표면)을
분할 후에도 그대로 보존하기 위함이다.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import secrets

from ..project_memory_backends import (
    BINDING_DOCUMENT_ID,
    BackendWriteResult,
    ProjectMemoryHit,
    ProjectMemoryRecord,
    get_backend,
    parse_settings,
)

RECALL_OUTPUT_BUDGET = 2000
PROTOCOL_VERSION = "2025-03-26"


def _neutralize(s: str) -> str:
    """경계 무력화 — memory._neutralize 와 동일 유지 (단일 출처 원칙)."""
    return s.replace("<", "‹").replace(">", "›")


# ── backend-neutral 소비 표면 — recall·retain 둘뿐 ───────────────────────────────


def server_recall(cfg: dict, query: str, max_results: int = 8, *, operation_timeout: int | None = None) -> list[dict]:
    """Exact binding을 확인한 뒤 backend-neutral hit을 반환한다."""
    from . import is_backend_trusted, verify_backend_binding

    if not is_backend_trusted(cfg):
        raise PermissionError("project memory backend target is not trusted")
    backend_cfg = {**cfg, "timeout": operation_timeout} if operation_timeout is not None else cfg
    backend = get_backend(backend_cfg)
    try:
        verify_backend_binding(cfg, backend=backend)
        hits = backend.recall(query, max_results=max_results)
        # Hindsight에는 compare-and-recall transaction/CAS가 없다. 반환 직전 재검증으로
        # 요청 사이 binding drift가 발생한 결과가 모델 경계로 나가는 것은 막는다.
        verify_backend_binding(cfg, backend=backend)
        if not isinstance(hits, list) or not all(isinstance(hit, ProjectMemoryHit) for hit in hits):
            raise TypeError("project memory backend recall() must return list[ProjectMemoryHit]")
        return [
            {
                "text": hit.text,
                "metadata": dict(hit.metadata),
                "document_id": hit.document_id,
                "score": hit.score,
            }
            for hit in hits
        ]
    finally:
        with contextlib.suppress(Exception):
            backend.close()


def server_retain(cfg: dict, content: str) -> dict:
    from . import expected_backend_binding

    expected = expected_backend_binding(cfg)
    return server_retain_items(
        cfg,
        [
            {
                "content": content,
                "metadata": {
                    "project_uid": expected.project_uid,
                    "binding_id": expected.binding_id,
                },
            }
        ],
    )


def server_retain_items(cfg: dict, items: list[dict]) -> dict:
    """Exact binding을 확인한 뒤 canonical item을 선택 backend에 쓴다."""
    from . import expected_backend_binding, is_backend_trusted, verify_backend_binding

    if not is_backend_trusted(cfg):
        raise PermissionError("project memory backend target is not trusted")
    expected = expected_backend_binding(cfg)
    records = []
    for item in items:
        text = str(item.get("content") or "")
        record_id = (
            str(item.get("document_id") or "") or "asgard:legacy:" + hashlib.sha256(text.encode()).hexdigest()[:24]
        )
        metadata = item.get("metadata")
        if record_id == BINDING_DOCUMENT_ID or record_id.startswith("asgard:project-binding:"):
            raise ValueError("reserved control document ID is not writable through the data plane")
        if not isinstance(metadata, dict):
            raise ValueError("project memory write is missing its ownership envelope")
        project_uid = str(metadata.get("project_uid") or "")
        binding_id = str(metadata.get("binding_id") or "")
        if (
            not project_uid
            or not binding_id
            or not secrets.compare_digest(project_uid, expected.project_uid)
            or not secrets.compare_digest(binding_id, expected.binding_id)
        ):
            raise ValueError("project memory write ownership envelope does not match the active binding")
        tags = item.get("tags")
        records.append(
            ProjectMemoryRecord(
                record_id=record_id,
                text=text,
                metadata=dict(metadata) if isinstance(metadata, dict) else {},
                tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
                context=str(item.get("context") or ""),
            )
        )
    backend = get_backend(cfg)
    try:
        verify_backend_binding(cfg, backend=backend)
        result = backend.retain(records)
        # 쓰기는 서버 측 compare-and-operate가 없어 원자적 보장은 못 하지만, drift를
        # 성공으로 보고하거나 후속 manifest/approval 상태를 전진시키지는 않는다.
        verify_backend_binding(cfg, backend=backend)
    finally:
        with contextlib.suppress(Exception):
            backend.close()
    if not isinstance(result, BackendWriteResult):
        raise TypeError("project memory backend retain() must return BackendWriteResult")
    requested_ids = [record.record_id for record in records]
    requested_set = set(requested_ids)
    if set(result.accepted_ids) - requested_set or set(result.rejected) - requested_set:
        raise ValueError("project memory backend returned an inconsistent write result with unknown record IDs")
    if result.success and (result.rejected or sorted(result.accepted_ids) != sorted(requested_ids)):
        raise ValueError("project memory backend returned an inconsistent write result for a successful publication")
    output = dict(result.details)
    output.update({"success": result.success, "items_count": result.items_count})
    if result.rejected:
        output["rejected"] = dict(result.rejected)
    if result.error:
        output["error"] = result.error
    return output


def backend_target(cfg: dict) -> dict:
    """Approval/projection에 묶을 선택 backend identity. 자격증명 값은 포함하지 않는다."""
    settings = parse_settings(cfg)
    payload = {
        "engine": settings.engine,
        "project_id": settings.project_id,
        "endpoint": settings.endpoint,
        "timeout": settings.timeout,
        "options": dict(settings.options),
        "project_uid": settings.project_uid,
        "binding_id": settings.binding_id,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema": 2,
        "engine": settings.engine,
        "project_id": settings.project_id,
        "project_uid": settings.project_uid,
        "binding_id": settings.binding_id,
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
    }
