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


_MAX_DECLARED_ENTITIES = 40
_DEFAULT_ENTITY_TYPE = "CODE_SYMBOL"
# 우리 심볼 표기는 "class:Foo" / "function:bar" 다. 서버에는 **이름만** 보내고 종류는 type 으로
# 넘긴다 — 26-07-28 실서버 실측: 접두사째 보냈더니 자동 추출된 `LedgerRenderer` 옆에
# `class:LedgerRenderer` 가 따로 서서 같은 것이 그래프에 둘로 앉았다. 엔티티 해소가 할 일을
# 우리가 망친 것이다.
_SYMBOL_KINDS = {"class": "CLASS", "function": "FUNCTION", "method": "METHOD", "const": "CONSTANT"}


def _declared_entities(metadata: dict) -> tuple[tuple[str, str], ...]:
    """아티팩트 메타데이터의 심볼을 확정 엔티티로 올린다.

    서버는 본문에서 엔티티를 자동 추출하는데, digest 계층은 본문이 머리글뿐이라 추출할 산문이
    거의 없다. 그런데 그 파일이 무슨 함수·클래스를 가졌는지는 우리가 이미 파싱해서 안다 —
    추측이 아니라 결정론 사실이므로 확정 엔티티로 넘기는 편이 정확하고 싸다."""
    raw = str(metadata.get("symbols") or "")
    seen: list[tuple[str, str]] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        prefix, separator, remainder = token.partition(":")
        name, kind = (
            (remainder.strip(), _SYMBOL_KINDS[prefix])
            if separator and prefix in _SYMBOL_KINDS
            else (token, _DEFAULT_ENTITY_TYPE)
        )
        if not name or len(name) > 128 or any(ch in name for ch in "\n\r<>"):
            continue
        if (name, kind) not in seen:
            seen.append((name, kind))
        if len(seen) >= _MAX_DECLARED_ENTITIES:
            break
    return tuple(seen)


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
                # 결정론 projection(코드·문서 아티팩트)은 발생 시각이 없는 사실이다 —
                # 시점은 source_revision 이 진다. 대화 turn 은 실제로 그때 일어난 일이라 제외.
                timeless=(metadata or {}).get("origin") == "deterministic" if isinstance(metadata, dict) else False,
                entities=_declared_entities(metadata if isinstance(metadata, dict) else {}),
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
