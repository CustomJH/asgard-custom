"""프로젝트 공유 메모리 브릿지 — 선택된 project-memory backend를 소비하는 stdio MCP 서버.

설계 (26-07-15 확정):
  등록 = user 스코프 1회 (`claude mcp add --scope user asgard-memory -- asgard memory mcp`)
  프로젝트 구분 = cwd 에서 걸어 올라가며 찾는 통합 memory 설정 (engine·project_id)
  → repo 루트 파일 0개, 설정 없는 프로젝트에선 툴 미노출 (전역 등록의 소음 제거).

서버는 무뇌 저장소 (provider=none, 키 0) — 정제는 클라이언트 몫:
  recall  = 서버 내장 임베딩 검색 패스스루 (LLM 0). 결과는 오염 스캔 + 경계 무력화 후 전달.
  retain  = 2단 승인 (개인 위키 plan-id 계약과 동일 철학): retain 이 미리보기+승인 id 를
            반환하고, 사용자 승인 후 retain_commit(id) 만 서버에 쓴다. id 는 1회 소비·1시간 만료.
            호출 모델(= 사용자의 기존 세션 모델)이 정제·용어 방화벽 재서술을 마친 내용만 넘긴다.
  파괴 툴 = backend native delete/clear 표면은 비노출.

프로토콜: MCP stdio — 개행 구분 JSON-RPC 2.0. 로그는 stderr (stdout 은 프로토콜 전용).
전 경로 fail-safe: 서버 불능·설정 파손은 툴 오류 텍스트로 — 브릿지가 세션을 죽이지 않는다.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error

from . import __version__
from .memory import scan_threats
from .project_memory_backends import (
    BackendWriteResult,
    ProjectMemoryHit,
    ProjectMemoryBinding,
    ProjectMemoryRecord,
    get_backend,
    parse_settings,
)

CONFIG_NAME = "memory-server.json"
PENDING_NAME = "memory-pending.json"
TRUST_NAME = "project-memory-trust.json"
TRUST_LOCK_WAIT = 5.0
TRUST_LOCK_STALE = 30.0
PENDING_TTL = 3600  # 승인 id 만료 (초) — 승인과 실행 사이가 길면 재계획이 맞다
CLAIM_TTL = 60  # commit 중 프로세스가 죽은 경우 claim 자동 회수
RECALL_OUTPUT_BUDGET = 2000
PROTOCOL_VERSION = "2025-03-26"


def _neutralize(s: str) -> str:
    """경계 무력화 — memory._neutralize 와 동일 유지 (단일 출처 원칙)."""
    return s.replace("<", "‹").replace(">", "›")


# ── 설정 탐색 — cwd 에서 상향 (모노레포·서브디렉토리 실행 대응) ─────────────────────


def find_config(start: str | None = None) -> tuple[str, dict] | None:
    """프로젝트 memory 섹션(engine·project_id)을 위로 걸어가며 탐색한다.

    구 server·bank 설정은 Hindsight로 정규화한다. 반환 dict에는 전환 기간 동안 기존 호출부를
    위한 server·bank alias도 제공하지만, 저장 정본은 engine·endpoint·project_id다.
    깨진 JSON·필수 키 누락은 없음과 동일 (fail-safe — 툴 미노출이 오동작보다 낫다)."""
    from .settings import PROJECT_FILE

    d = os.path.realpath(start or os.getcwd())
    while True:
        asg = os.path.join(d, ".asgard")
        if os.path.isfile(os.path.join(asg, PROJECT_FILE)) or os.path.isfile(os.path.join(asg, CONFIG_NAME)):
            try:
                from .settings import load_project

                mem = load_project(d).get("memory") or {}
                settings = parse_settings(mem)
                normalized = dict(mem)
                normalized.update(
                    {
                        "engine": settings.engine,
                        "project_id": settings.project_id,
                        "endpoint": settings.endpoint,
                        "timeout": settings.timeout,
                        "options": dict(settings.options),
                        "project_uid": settings.project_uid,
                        "binding_id": settings.binding_id,
                        # 기존 정책/manifest 코드가 쓰는 호환 alias. backend에는 canonical key가 전달된다.
                        "bank": settings.project_id,
                        "server": settings.endpoint,
                    }
                )
                return d, normalized
            except Exception:
                pass
            return None
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def write_config(
    root: str,
    endpoint: str,
    project_id: str,
    *,
    engine: str = "hindsight",
    timeout: int | None = None,
    options: dict | None = None,
    project_uid: str = "",
    binding_id: str = "",
) -> str:
    from .settings import save_project

    config = {
        "engine": engine.strip().lower(),
        "endpoint": endpoint.rstrip("/"),
        "project_id": project_id.strip(),
        "timeout": timeout,
        "options": options or None,
        "project_uid": project_uid or None,
        "binding_id": binding_id or None,
    }
    parse_settings({key: value for key, value in config.items() if value is not None})
    return save_project(root, "memory", config)


# ── backend-neutral 소비 표면 — recall·retain 둘뿐 ───────────────────────────────


def server_recall(cfg: dict, query: str, max_results: int = 8) -> list[dict]:
    """Exact binding을 확인한 뒤 backend-neutral hit을 반환한다."""
    if not is_backend_trusted(cfg):
        raise PermissionError("project memory backend target is not trusted")
    backend = get_backend(cfg)
    try:
        verify_backend_binding(cfg, backend=backend)
        hits = backend.recall(query, max_results=max_results)
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
    return server_retain_items(cfg, [{"content": content}])


def server_retain_items(cfg: dict, items: list[dict]) -> dict:
    """Exact binding을 확인한 뒤 canonical item을 선택 backend에 쓴다."""
    if not is_backend_trusted(cfg):
        raise PermissionError("project memory backend target is not trusted")
    records = []
    for item in items:
        text = str(item.get("content") or "")
        record_id = str(item.get("document_id") or "") or "asgard:legacy:" + hashlib.sha256(text.encode()).hexdigest()[:24]
        metadata = item.get("metadata")
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


def _trust_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".asgard", TRUST_NAME)


def _load_trust() -> dict:
    try:
        with open(_trust_path(), encoding="utf-8") as source:
            value = json.load(source)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def is_backend_trusted(cfg: dict) -> bool:
    try:
        target = backend_target(cfg)
    except Exception:
        return False
    if not target["project_uid"] or not target["binding_id"]:
        return False
    entry = _load_trust().get(target["fingerprint"])
    return (
        isinstance(entry, dict)
        and entry.get("engine") == target["engine"]
        and entry.get("project_id") == target["project_id"]
        and entry.get("project_uid") == target["project_uid"]
        and entry.get("binding_id") == target["binding_id"]
    )


def expected_backend_binding(cfg: dict) -> ProjectMemoryBinding:
    settings = parse_settings(cfg)
    if not settings.project_uid or not settings.binding_id:
        raise PermissionError("project memory binding is not configured; reconnect or explicitly adopt the bank")
    return ProjectMemoryBinding(
        project_uid=settings.project_uid,
        binding_id=settings.binding_id,
        project_id=settings.project_id,
    )


def verify_backend_binding(cfg: dict, *, backend=None) -> ProjectMemoryBinding:
    """Read the reserved control document exactly and fail closed on drift."""
    expected = expected_backend_binding(cfg)
    owns_backend = backend is None
    adapter = get_backend(cfg) if owns_backend else backend
    try:
        observed = adapter.read_binding()
        if observed is None:
            raise PermissionError("project memory binding is missing from the selected namespace")
        if (
            observed.project_id != expected.project_id
            or not secrets.compare_digest(observed.project_uid, expected.project_uid)
            or not secrets.compare_digest(observed.binding_id, expected.binding_id)
        ):
            raise PermissionError("foreign or drifted project memory binding")
        return observed
    finally:
        if owns_backend:
            with contextlib.suppress(Exception):
                adapter.close()


@contextlib.contextmanager
def _trust_guard():
    """machine-local trust read-modify-write를 프로세스 간 직렬화한다."""
    path = _trust_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    lock_path = f"{path}.lock"
    deadline = time.monotonic() + TRUST_LOCK_WAIT
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                stale = time.time() - os.path.getmtime(lock_path) > TRUST_LOCK_STALE
            except OSError:
                stale = False
            if stale:
                with contextlib.suppress(OSError):
                    os.remove(lock_path)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for project-memory trust lock")
            time.sleep(0.01)
    try:
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            os.remove(lock_path)


def trust_backend(cfg: dict) -> str:
    """Explicit connect가 승인한 backend target을 repo 밖 machine-local store에 기록한다."""
    verify_backend_binding(cfg)
    target = backend_target(cfg)
    path = _trust_path()
    with _trust_guard():
        data = _load_trust()
        data[target["fingerprint"]] = {
            "engine": target["engine"],
            "project_id": target["project_id"],
            "project_uid": target["project_uid"],
            "binding_id": target["binding_id"],
            "trusted_at": int(time.time()),
        }
        tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as output:
                json.dump(data, output, ensure_ascii=False, sort_keys=True, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            with contextlib.suppress(OSError):
                os.remove(tmp)
    return path


# ── 승인 대기 (2단 retain) — 개인 위키 plan-id 와 동일 계약 ───────────────────────────


def _pending_path(root: str) -> str:
    return os.path.join(root, ".asgard", "state", PENDING_NAME)  # 런타임 상태 — state/ 격리


@contextlib.contextmanager
def _pending_guard(root: str):
    """프로세스/스레드 공통 lock — approval JSON의 lost update·double commit 방지."""
    path = _pending_path(root) + ".lock"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    deadline = time.monotonic() + 5
    fd = None
    while fd is None:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > CLAIM_TTL:
                    os.remove(path)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("project memory approval lock timeout")
            time.sleep(0.01)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            os.remove(path)


def _load_pending_unlocked(root: str) -> dict:
    try:
        d = json.load(open(_pending_path(root), encoding="utf-8"))
        now = time.time()
        return {k: v for k, v in d.items() if now - v.get("ts", 0) < PENDING_TTL}
    except Exception:
        return {}


def _load_pending(root: str) -> dict:
    with _pending_guard(root):
        return _load_pending_unlocked(root)


def _save_pending_unlocked(root: str, d: dict) -> None:
    p = _pending_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    with contextlib.suppress(OSError):
        os.chmod(p, 0o600)


def _save_pending(root: str, d: dict) -> None:
    with _pending_guard(root):
        _save_pending_unlocked(root, d)


def stage_retain(root: str, item: str | dict, *, target: dict | None = None) -> str:
    """승인 대기 등록 — 반환 = approval id (1회 소비)."""
    with _pending_guard(root):
        pend = _load_pending_unlocked(root)
        document_id = str(item.get("document_id") or "") if isinstance(item, dict) else ""
        item_hash = hashlib.sha256(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if document_id:
            for existing_id, entry in pend.items():
                existing = entry.get("item")
                if (
                    isinstance(existing, dict)
                    and existing.get("document_id") == document_id
                    and entry.get("item_hash") == item_hash
                    and entry.get("target") == target
                ):
                    return existing_id
        aid = secrets.token_hex(4)
        pend[aid] = {"item": item, "item_hash": item_hash, "target": target, "ts": time.time(), "schema": 2}
        _save_pending_unlocked(root, pend)
    return aid


def pop_retain(root: str, aid: str) -> str | dict | None:
    """승인 id 소비 — 없거나 만료면 None. 소비 후 재사용 불가."""
    with _pending_guard(root):
        pend = _load_pending_unlocked(root)
        item = pend.pop(aid, None)
        _save_pending_unlocked(root, pend)
    if not item:
        return None
    # 구 pending 파일 호환: 이전 버전은 content 문자열만 저장했다.
    return item.get("item", item.get("content"))


def claim_retain(root: str, aid: str, *, target: dict | None = None) -> tuple[str | dict, str] | None:
    """approval을 원격 write 동안 독점 claim한다. 실패 시 같은 ID를 재사용할 수 있다."""
    with _pending_guard(root):
        pend = _load_pending_unlocked(root)
        entry = pend.get(aid)
        if not entry:
            return None
        expected_target = entry.get("target")
        if target is not None:
            if not isinstance(expected_target, dict):
                return None
            expected_fingerprint = str(expected_target.get("fingerprint") or "")
            actual_fingerprint = str(target.get("fingerprint") or "")
            if (
                expected_target.get("engine") != target.get("engine")
                or expected_target.get("project_id") != target.get("project_id")
                or not expected_fingerprint
                or not secrets.compare_digest(expected_fingerprint, actual_fingerprint)
            ):
                return None
        now = time.time()
        if entry.get("claim") and now - float(entry.get("claimed_at") or 0) < CLAIM_TTL:
            return None
        token = secrets.token_hex(8)
        entry["claim"] = token
        entry["claimed_at"] = now
        _save_pending_unlocked(root, pend)
        item = entry.get("item", entry.get("content"))
        return (item, token) if item is not None else None


def finish_retain(root: str, aid: str, token: str, *, success: bool) -> None:
    with _pending_guard(root):
        pend = _load_pending_unlocked(root)
        entry = pend.get(aid)
        if not entry or entry.get("claim") != token:
            return
        if success:
            pend.pop(aid, None)
        else:
            entry.pop("claim", None)
            entry.pop("claimed_at", None)
        _save_pending_unlocked(root, pend)


# ── MCP 툴 정의 — 최소 표면 (파괴 툴 비노출) ─────────────────────────────────────────

_TOOLS = [
    {
        "name": "memory_recall",
        "description": (
            "선택된 프로젝트 공유 메모리 backend 검색. 팀이 축적한 결정·사실을 "
            "의미 검색한다. 결과는 힌트다 — 완료 증거·검증 근거로 쓰지 마라."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색 질의 (한국어/영어)"},
                "max_results": {"type": "integer", "description": "최대 결과 수 (기본 8)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_retain",
        "description": (
            "프로젝트 공유 메모리 저장 1단계 — 즉시 저장되지 않는다. 미리보기와 approval_id 를 "
            "반환하니, 내용을 사용자에게 보여주고 승인받은 뒤 memory_retain_commit 을 호출하라. "
            "넘기기 전에 반드시: 자립적인 사실 한 건으로 정제하고, 개인 약어·세계관 용어는 "
            "프로젝트 공용 어휘로 재서술한다 (용어 방화벽)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "record_id": {"type": "string", "description": "안정적인 프로젝트 고유 ID"},
                "kind": {
                    "type": "string",
                    "enum": ["decision", "policy", "contract", "component", "incident", "experiment", "migration", "runbook"],
                },
                "title": {"type": "string"},
                "content": {"type": "string", "description": "자립적인 검증된 사실 한 건"},
                "source": {"type": "string", "description": "repo 경로·commit·test·ADR 등 provenance"},
                "source_revision": {"type": "string", "description": "commit SHA 또는 검증 revision"},
                "importance": {"type": "string", "enum": ["normal", "high", "critical"]},
                "confidence": {"type": "string", "enum": ["observed", "verified"]},
                "status": {"type": "string", "enum": ["active", "superseded", "historical"]},
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"type": {"type": "string"}, "target": {"type": "string"}},
                        "required": ["type", "target"],
                    },
                },
            },
            "required": ["record_id", "kind", "title", "content", "source", "source_revision", "importance", "confidence", "status"],
        },
    },
    {
        "name": "memory_retain_commit",
        "description": "저장 2단계 — 사용자가 승인한 approval_id 로만 실행. id 는 1회 소비·1시간 만료.",
        "inputSchema": {
            "type": "object",
            "properties": {"approval_id": {"type": "string"}},
            "required": ["approval_id"],
        },
    },
]


# ── JSON-RPC 처리 — 순수 함수 (테스트 표면) ────────────────────────────────────────


def _text_result(rid, text: str, is_error: bool = False) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": rid,
        "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
    }


def _call_tool(name: str, args: dict, root: str, cfg: dict) -> tuple[str, bool]:
    """툴 실행 — 반환 = (텍스트, is_error). 서버 오류는 텍스트로 (세션 불사)."""
    try:
        if name == "memory_recall":
            hits = server_recall(cfg, str(args.get("query", "")), int(args.get("max_results") or 8))
            from .memory_context import filter_project_hits

            filtered, dropped = filter_project_hits(root, cfg, hits, max_results=int(args.get("max_results") or 8))
            clean, used = [], 0
            for h in filtered:
                t = str(h["text"])
                source = _neutralize(str(h["metadata"].get("source") or "").strip())[:160]
                source_note = f" [source: {source}]" if source else ""
                row = f"- {_neutralize(t)[:300]}{source_note}"
                if used + len(row) + 1 > RECALL_OUTPUT_BUDGET:
                    break
                clean.append(row)
                used += len(row) + 1
            note = f"\n(오염 의심 {dropped}건 제외)" if dropped else ""
            return (
                ("검색 결과 (힌트 — 완료 증거 아님):\n" + "\n".join(clean) + note)
                if clean
                else "관련 기억 없음" + note,
                False,
            )
        if name == "memory_retain":
            content = str(args.get("content", "")).strip()
            if not content:
                return "content 가 비어 있다", True
            required = ("record_id", "kind", "title", "source", "source_revision", "importance", "confidence", "status")
            missing = [field for field in required if not str(args.get(field) or "").strip()]
            if missing:
                return "프로젝트 메모리 등록 필수 항목 누락: " + ", ".join(missing), True
            from .project_memory import ProjectRecord, record_item, validate_record

            record = ProjectRecord(
                record_id=str(args["record_id"]),
                kind=str(args["kind"]),
                title=str(args["title"]),
                content=content,
                source=str(args["source"]),
                source_revision=str(args["source_revision"]),
                importance=str(args["importance"]),
                confidence=str(args["confidence"]),
                status=str(args["status"]),
                relations=tuple(args.get("relations") or ()),
            )
            validation = validate_record(record, root)
            if not validation.accepted:
                reasons = "; ".join(validation.reasons)
                prefix = "injection scan: " if any("prompt injection" in r for r in validation.reasons) else "등록 기준 위반: "
                return prefix + reasons + " — 저장 거부", True
            item = record_item(
                record,
                cfg["project_id"],
                project_uid=str(cfg.get("project_uid") or ""),
                binding_id=str(cfg.get("binding_id") or ""),
            )
            aid = stage_retain(root, item, target=backend_target(cfg))
            return (
                f"승인 대기 (즉시 저장 안 됨) — approval_id: {aid}\n---\n{item['content']}\n---\n"
                "이 내용을 사용자에게 보여주고 승인받은 뒤 memory_retain_commit 을 호출하라.",
                False,
            )
        if name == "memory_retain_commit":
            aid = str(args.get("approval_id", ""))
            claimed = claim_retain(root, aid, target=backend_target(cfg))
            if claimed is None:
                return "유효하지 않은 approval_id (미존재·만료·이미 소비) — memory_retain 부터 다시", True
            item, token = claimed
            try:
                out = server_retain_items(cfg, [item] if isinstance(item, dict) else [{"content": item}])
                if out.get("success") is not True:
                    raise ValueError(str(out.get("error") or "project memory retain rejected"))
            except Exception as e:
                finish_retain(root, aid, token, success=False)
                return f"메모리 backend 저장 실패: {type(e).__name__} — 같은 approval_id로 재시도 가능", True
            finish_retain(root, aid, token, success=True)
            return (
                f"저장 완료 (engine={cfg['engine']}, project_id={cfg['project_id']}): "
                f"{json.dumps(out, ensure_ascii=False)[:200]}",
                False,
            )
        return f"unknown tool: {name}", True
    except urllib.error.URLError as e:
        return f"메모리 backend({cfg.get('endpoint')}) 접속 실패: {e.reason} — 힌트 부재로 진행 (fail-open)", True
    except Exception as e:  # 브릿지가 세션을 죽이지 않는다
        return f"{type(e).__name__}: {e}", True


def handle(msg: dict, start_dir: str | None = None) -> dict | None:
    """JSON-RPC 메시지 1건 처리 — 응답 dict 또는 None(notification). 순수 진입점 (테스트 표면)."""
    method, rid = msg.get("method", ""), msg.get("id")
    found = find_config(start_dir)
    trusted = bool(found and is_backend_trusted(found[1]))
    bound = False
    binding_error = ""
    if trusted and found:
        try:
            verify_backend_binding(found[1])
            bound = True
        except Exception as exc:
            binding_error = str(exc) or type(exc).__name__
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": msg.get("params", {}).get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "asgard-memory", "version": __version__},
            },
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        # 설정이 없거나 machine-local trust가 없는 프로젝트는 툴 미노출.
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": _TOOLS if bound else []}}
    if method == "tools/call":
        if not found:
            return _text_result(
                rid,
                "이 프로젝트에는 공유 메모리 설정(.asgard/memory-server.json)이 없다 — asgard memory connect 로 연결",
                True,
            )
        if not trusted:
            return _text_result(
                rid,
                "이 프로젝트의 공유 메모리 backend가 이 machine에서 trusted 상태가 아니다 — asgard memory connect 로 명시 승인",
                True,
            )
        if not bound:
            return _text_result(
                rid,
                "이 프로젝트의 공유 메모리 binding이 없거나 foreign/drift 상태다 — "
                + (binding_error or "asgard memory connect로 재검증"),
                True,
            )
        root, cfg = found
        params = msg.get("params") or {}
        text, err = _call_tool(str(params.get("name", "")), params.get("arguments") or {}, root, cfg)
        return _text_result(rid, text, err)
    if rid is not None:  # 미지원 요청 — 표준 오류
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None  # 모르는 notification 은 무시


def serve(start_dir: str | None = None) -> int:
    """stdio 루프 — 개행 구분 JSON-RPC. EOF 로 종료. 파싱 불능 행은 무시 (fail-safe)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        try:
            resp = handle(msg, start_dir)
        except Exception as e:  # 최후 방어 — 프로토콜 오류로 변환
            resp = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": str(e)[:200]}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0
