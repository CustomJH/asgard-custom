"""backend-neutral 소비 표면 — 선택 backend에 대한 recall·retain·target fingerprint.

trust 검증 함수(is_backend_trusted·verify_backend_binding·expected_backend_binding)는
호출 시점에 패키지 파사드에서 lazy import 한다 — 소비자 테스트가
`asgard.memory_bridge.*` 네임스페이스를 patch 하는 계약(파사드 단일 표면)을
분할 후에도 그대로 보존하기 위함이다.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import secrets
import threading
import time

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

# ── 읽기 경로의 원격 왕복 (M4) ────────────────────────────────────────────────
#
# `server_recall` 한 번이 왕복 세 번이었다: binding 검증 → recall → binding 재검증. 이 레인은
# 턴 시작 자동 주입에서 순차로 돌기 때문에 그 지연이 그대로 사람에게 간다. 신뢰됐는데 접속이
# 안 되는 backend 에서는 매 턴 타임아웃(최대 5초)만큼 대화가 멈춘다.
#
# 완화는 **읽기 경로에만** 건다. 쓰기(`server_retain_items`)와 예약(`server_consolidate`)의
# 앞뒤 검증은 한 글자도 안 바뀐다 — 드리프트를 성공으로 보고하는 것이 이 층에서 가장 나쁜
# 실패이고, 쓰기는 턴마다 도는 일도 아니다.
#
# 두 손잡이가 각각 다른 문제를 본다:
#
#   ① 검증 캐시 — 앞 검증만 짧게 건너뛴다. **뒤 검증은 절대 안 건너뛴다**: 모델 경계로
#      나가는 결과가 검증받지 않은 binding 에서 온 것이 되면 안 된다. 대신 앞 검증은 직전
#      호출의 뒤 검증과 같은 문서를 잠깐 사이에 다시 읽는 일이라, 그 시간만큼 미룬다.
#      대가는 명시적이다 — TTL 안에 드리프트가 일어나면 질의문이 그 저장소까지 갔다가 뒤
#      검증에서 결과가 거절된다. 나가는 쪽(질의)의 창은 열리고 들어오는 쪽(결과)은 그대로
#      닫혀 있다는 뜻이고, 둘 중 위험한 쪽은 들어오는 쪽이다. 뒤 검증이 실패하면 캐시를
#      즉시 버려 다음 호출이 앞 검증부터 다시 한다.
#      TTL 60초의 뜻은 "읽기 경로는 적어도 1분에 한 번 앞 검증을 다시 한다"이다. 이보다
#      짧으면 턴 간격이 대개 그보다 길어 캐시가 늘 식어 있고(아끼는 것이 없다), 길면 나가는
#      쪽 창만 넓어진다.
#   ② 회로차단기 — 접속 실패가 연달아 나면 이 레인을 잠시 통째로 건너뛴다. 죽은 backend 는
#      기다려도 줄 것이 없으므로 이쪽은 방어를 하나도 안 깎는다. 세는 것은 **접속 실패**
#      (OSError — urllib·소켓 계열)뿐이다: 드리프트(PermissionError)나 규약 위반은 판정이지
#      장애가 아니고, 판정을 기억해 두면 사람이 고친 뒤에도 그 시간만큼 벌을 받는다.
RECALL_BINDING_TTL = 60.0
RECALL_BREAKER_FAILURES = 2
RECALL_BREAKER_COOLDOWN = 60.0

_RECALL_HEALTH: dict[str, dict[str, float]] = {}
_RECALL_HEALTH_GUARD = threading.Lock()


def _recall_health_key(cfg: dict) -> str:
    """이 backend target 하나의 신원 — 캐시·차단기가 같은 칸을 보게 하는 값.

    fingerprint 는 engine·project_id·project_uid·binding_id 를 다 덮으므로, 설정이 조금이라도
    바뀌면 캐시도 차단기도 남의 것을 물려받지 않는다. 못 만들면 빈 문자열 — 그때는 완화 없이
    옛 경로 그대로 돈다 (fail-closed)."""
    try:
        return str(backend_target(cfg)["fingerprint"])
    except Exception:
        return ""


def _binding_fresh(key: str, now: float) -> bool:
    """이 target 의 binding 을 방금 확인했는가 — 앞 검증을 건너뛸 근거."""
    if not key:
        return False
    with _RECALL_HEALTH_GUARD:
        return now - _RECALL_HEALTH.get(key, {}).get("verified_at", 0.0) < RECALL_BINDING_TTL


def _breaker_open(key: str, now: float) -> bool:
    if not key:
        return False
    with _RECALL_HEALTH_GUARD:
        return now < _RECALL_HEALTH.get(key, {}).get("open_until", 0.0)


def _recall_succeeded(key: str, now: float) -> None:
    if not key:
        return
    with _RECALL_HEALTH_GUARD:
        _RECALL_HEALTH[key] = {"verified_at": now, "failures": 0.0, "open_until": 0.0}


def _recall_failed(key: str, error: BaseException, now: float) -> None:
    """실패 하나를 기록한다 — 검증 캐시는 버리고, 접속 실패면 차단기 계수를 올린다."""
    if not key:
        return
    # PermissionError 는 OSError 의 하위형이지만 여기서는 판정이다 (드리프트·미신뢰).
    outage = isinstance(error, OSError) and not isinstance(error, PermissionError)
    with _RECALL_HEALTH_GUARD:
        entry = _RECALL_HEALTH.setdefault(key, {"verified_at": 0.0, "failures": 0.0, "open_until": 0.0})
        entry["verified_at"] = 0.0  # 검증하지 못했으니 "방금 확인함"을 유지할 근거가 없다
        if not outage:
            return
        entry["failures"] += 1
        if entry["failures"] >= RECALL_BREAKER_FAILURES:
            entry["open_until"] = now + RECALL_BREAKER_COOLDOWN


def reset_recall_health(cfg: dict | None = None) -> None:
    """검증 캐시와 차단기를 비운다 — cfg 를 주면 그 target 만. 테스트·재연결의 손잡이다."""
    key = _recall_health_key(cfg) if cfg is not None else ""
    with _RECALL_HEALTH_GUARD:
        if key:
            _RECALL_HEALTH.pop(key, None)
        elif cfg is None:
            _RECALL_HEALTH.clear()


def _neutralize(s: str) -> str:
    """경계 무력화 — memory._neutralize와 동일 유지 (단일 출처 원칙)."""
    return s.replace("<", "‹").replace(">", "›")


# ── backend-neutral 소비 표면 — recall·retain 둘뿐 ───────────────────────────────


def server_recall(cfg: dict, query: str, max_results: int = 8, *, operation_timeout: int | None = None) -> list[dict]:
    """Exact binding을 확인한 뒤 backend-neutral hit을 반환한다.

    턴마다 도는 유일한 원격 읽기라 왕복 수와 장애 시 지연을 여기서 재단한다 — 손잡이 둘의
    근거는 모듈 상단 주석에 있다."""
    from . import is_backend_trusted, verify_backend_binding

    if not is_backend_trusted(cfg):
        raise PermissionError("project memory backend target is not trusted")
    key = _recall_health_key(cfg)
    now = time.monotonic()
    if _breaker_open(key, now):
        # 여기서 raise 하는 것이 요점이다 — 호출측(`memory_context.project_recall_rows`)은
        # 이 레인의 예외를 이미 fail-open 으로 받는다. 원격을 안 건드리고 즉시 돌아간다.
        raise TimeoutError(
            f"project memory recall is skipped for {RECALL_BREAKER_COOLDOWN:.0f}s "
            f"after {RECALL_BREAKER_FAILURES} consecutive connection failures"
        )
    backend_cfg = {**cfg, "timeout": operation_timeout} if operation_timeout is not None else cfg
    backend = get_backend(backend_cfg)
    try:
        if not _binding_fresh(key, now):
            verify_backend_binding(cfg, backend=backend)
        hits = backend.recall(query, max_results=max_results)
        # Hindsight에는 compare-and-recall transaction/CAS가 없다. 반환 직전 재검증으로
        # 요청 사이 binding drift가 발생한 결과가 모델 경계로 나가는 것은 막는다.
        # 이 한 번은 캐시가 아무리 신선해도 건너뛰지 않는다.
        verify_backend_binding(cfg, backend=backend)
        if not isinstance(hits, list) or not all(isinstance(hit, ProjectMemoryHit) for hit in hits):
            raise TypeError("project memory backend recall() must return list[ProjectMemoryHit]")
        rows = [
            {
                "text": hit.text,
                "metadata": dict(hit.metadata),
                "document_id": hit.document_id,
                "score": hit.score,
            }
            for hit in hits
        ]
    except BaseException as error:
        _recall_failed(key, error, time.monotonic())
        raise
    else:
        _recall_succeeded(key, time.monotonic())
        return rows
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
# 우리 심볼 표기는 "class:Foo" / "function:bar" 다. 서버에는 **이름만** 보내고 종류는 type으로
# 넘긴다 — 26-07-28 실서버 실측: 접두사째 보냈더니 자동 추출된 `LedgerRenderer` 옆에
# `class:LedgerRenderer`가 따로 서서 같은 것이 그래프에 둘로 앉았다. 엔티티 해소가 할 일을
# 우리가 망친 것이다.
_SYMBOL_KINDS = {"class": "CLASS", "function": "FUNCTION", "method": "METHOD", "const": "CONSTANT"}
_RETAIN_STRATEGY = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_OBSERVATION_SCOPE_MODES = {"per_tag", "combined", "all_combinations", "shared"}


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


def _retain_entities(item: dict, metadata: dict) -> tuple[tuple[str, str], ...]:
    """명시 엔티티와 결정론 artifact 심볼을 하나의 검증된 목록으로 합친다."""
    seen = list(_declared_entities(metadata))
    raw = item.get("entities")
    if raw is None:
        return tuple(seen)
    if not isinstance(raw, list):
        raise ValueError("project memory entities must be a list")
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("project memory entity must be an object")
        name = str(row.get("text") or "").strip()
        kind = str(row.get("type") or _DEFAULT_ENTITY_TYPE).strip().upper()
        if (
            not name
            or len(name) > 128
            or len(kind) > 64
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", kind)
            or any(ch in name for ch in "\n\r<>")
        ):
            raise ValueError("invalid project memory entity")
        pair = (name, kind)
        if pair not in seen:
            seen.append(pair)
        if len(seen) >= _MAX_DECLARED_ENTITIES:
            break
    return tuple(seen)


def _observation_scopes(item: dict) -> str | tuple[tuple[str, ...], ...] | None:
    raw = item.get("observation_scopes")
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw not in _OBSERVATION_SCOPE_MODES:
            raise ValueError("invalid project memory observation scope")
        return raw
    if not isinstance(raw, list) or not raw:
        raise ValueError("project memory observation scopes must be a non-empty list")
    scopes: list[tuple[str, ...]] = []
    for scope in raw:
        if not isinstance(scope, list) or not scope:
            raise ValueError("project memory observation scope must be a non-empty tag list")
        tags = tuple(str(tag).strip() for tag in scope)
        if any(not tag or len(tag) > 128 or any(ch in tag for ch in "\n\r<>") for tag in tags):
            raise ValueError("invalid project memory observation scope tag")
        scopes.append(tags)
    return tuple(scopes)


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
        strategy = str(item.get("strategy") or "").strip()
        if strategy and not _RETAIN_STRATEGY.fullmatch(strategy):
            raise ValueError("invalid project memory retain strategy")
        timestamp = item.get("timestamp")
        if timestamp not in (None, "", "unset"):
            raise ValueError("project memory timestamp must be 'unset' when explicitly supplied")
        records.append(
            ProjectMemoryRecord(
                record_id=record_id,
                text=text,
                metadata=dict(metadata) if isinstance(metadata, dict) else {},
                tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
                context=str(item.get("context") or ""),
                # 결정론 projection(코드·문서 아티팩트)은 발생 시각이 없는 사실이다 —
                # 시점은 source_revision이 진다. 대화 turn은 실제로 그때 일어난 일이라 제외.
                timeless=timestamp == "unset" or metadata.get("origin") == "deterministic",
                entities=_retain_entities(item, metadata),
                strategy=strategy,
                observation_scopes=_observation_scopes(item),
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


def server_consolidate(cfg: dict, tag_scopes: list[list[str]]) -> dict:
    """Exact binding을 확인한 뒤 backend가 지원하는 observation 작업을 예약한다."""
    from . import is_backend_trusted, verify_backend_binding

    if not is_backend_trusted(cfg):
        raise PermissionError("project memory backend target is not trusted")
    backend = get_backend(cfg)
    try:
        verify_backend_binding(cfg, backend=backend)
        consolidate = getattr(backend, "consolidate", None)
        if not callable(consolidate):
            return {"status": "unsupported"}
        output = consolidate(tag_scopes)
        verify_backend_binding(cfg, backend=backend)
        return dict(output)
    finally:
        with contextlib.suppress(Exception):
            backend.close()


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
