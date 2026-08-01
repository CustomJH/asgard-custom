"""MCP stdio 서버 표면 — 툴 정의·JSON-RPC 처리·stdio 루프 (파괴 툴 비노출)."""

from __future__ import annotations

import json
import sys
import urllib.error

from .. import __version__
from .client import (
    PROTOCOL_VERSION,
    RECALL_OUTPUT_BUDGET,
    backend_target,
    server_recall,
)
from .config import autosave_enabled, find_config, stage_retain
from .trust import is_backend_trusted, verify_backend_binding

# ── MCP 툴 정의 — 최소 표면 (파괴 툴 비노출) ─────────────────────────────────────────

# 개인 기억 툴 — **프로젝트 binding과 무관하게** 노출된다. 이 메모리는 프로젝트가 아니라
# 에이전트에 붙으므로(profiles.home()), 프로젝트 backend가 없거나 신뢰되지 않은 저장소에서도
# 에이전트는 자기 기억을 제안할 수 있어야 한다. 아래 _TOOLS(프로젝트 전용)와 게이트가 다르다.
_PERSONAL_TOOLS = [
    {
        "name": "memory_propose",
        "description": (
            "Record one durable fact in your own tier-1 memory — the memory that survives across "
            "sessions and belongs to this agent alone. Whether it is stored at once or queued for "
            "the user's approval is the user's setting (memory.autosave); the response says which "
            "happened, so read it before telling the user anything.\n\n"
            "PROPOSE WHEN: the user corrects you or states how they want work done; the user shares "
            "a preference or a fact about themselves; you settle a decision that still binds you next "
            "session; you learn a durable fact about this environment or convention.\n\n"
            "DO NOT PROPOSE: task progress, what you just finished, temporary state, anything "
            "rediscoverable by reading a file, or facts about the repository's code (that is project "
            "memory — use memory_retain). Secrets are rejected outright.\n\n"
            "One self-contained sentence that still makes sense a year from now."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The fact, as one self-contained sentence."},
                "kind": {
                    "type": "string",
                    "enum": ["user", "feedback", "decision", "insight", "reference", "note"],
                    "description": (
                        "'user' who the user is · 'feedback' how they want you to work · "
                        "'decision' a settled call · 'insight' something you worked out · "
                        "'reference' a durable lookup fact · 'note' anything else."
                    ),
                },
            },
            "required": ["text", "kind"],
        },
    }
]

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
            "프로젝트 공유 메모리 저장. 기본은 2단계다 — 미리보기와 approval_id를 반환하니 "
            "내용을 사용자에게 보여주고 승인받은 뒤 memory_retain_commit을 호출하라. "
            "사용자가 자동저장(project_memory.autosave)을 켜 뒀으면 이 호출로 커밋까지 끝난다 — "
            "어느 쪽인지는 응답이 말하니 그것을 읽고 사용자에게 전하라. "
            "넘기기 전에 반드시: 자립적인 사실 한 건으로 정제하고, 개인 약어·세계관 용어는 "
            "프로젝트 공용 어휘로 재서술한다 (용어 방화벽)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "record_id": {"type": "string", "description": "안정적인 프로젝트 고유 ID"},
                "kind": {
                    "type": "string",
                    "enum": [
                        "decision",
                        "policy",
                        "contract",
                        "component",
                        "incident",
                        "experiment",
                        "migration",
                        "runbook",
                    ],
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
            "required": [
                "record_id",
                "kind",
                "title",
                "content",
                "source",
                "source_revision",
                "importance",
                "confidence",
                "status",
            ],
        },
    },
    {
        "name": "memory_retain_commit",
        "description": (
            "저장 2단계 — 사용자가 승인한 approval_id 로만 실행. 프로젝트 Git 정본을 먼저 기록한 뒤 "
            "backend에 반영한다. id는 1회 소비·1시간 만료."
        ),
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


def _call_personal_tool(name: str, args: dict) -> tuple[str, bool]:
    """개인 기억 툴 — 프로젝트 설정·binding을 안 본다 (이 기억은 에이전트의 것이다)."""
    if name != "memory_propose":
        return f"unknown tool: {name}", True
    from ..memory import propose

    try:
        outcome = propose.submit(str(args.get("text") or ""), kind=str(args.get("kind") or "note"))
    except ValueError as exc:
        return f"{exc}", True
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}", True
    return propose.outcome_text(outcome), False


def _call_tool(name: str, args: dict, root: str, cfg: dict) -> tuple[str, bool]:
    """툴 실행 — 반환 = (텍스트, is_error). 서버 오류는 텍스트로 (세션 불사)."""
    try:
        if name == "memory_recall":
            hits = server_recall(cfg, str(args.get("query", "")), int(args.get("max_results") or 8))
            from ..memory_context import filter_project_hits

            filtered, dropped = filter_project_hits(
                root,
                cfg,
                hits,
                max_results=int(args.get("max_results") or 8),
                query=str(args.get("query", "")),
            )
            from ..memory_context import drop_note, hit_body, hit_provenance

            clean, used = [], 0
            for h in filtered:
                # ambient 주입과 같은 렌더러다. 이전의 300자 상한은 backend 온톨로지 머리글
                # (약 321자)에 통째로 먹혀 본문을 한 글자도 못 실었다 — 응답이 항상
                # "Title/Status/Importance/Confidence/Source@해시" 로만 끝났다.
                body = hit_body(h)
                if not body:
                    continue
                row = f"- {body}{hit_provenance(h['metadata'])}"
                if used + len(row) + 1 > RECALL_OUTPUT_BUDGET:
                    break
                clean.append(row)
                used += len(row) + 1
            # 사유를 갈라 말한다 — 대부분의 drop은 오염이 아니라 정본 불일치인데, 한 마디로
            # 뭉치면 사용자가 없는 보안 사고를 읽는다.
            note = drop_note(dropped)
            return (
                ("검색 결과 (힌트 — 완료 증거 아님):\n" + "\n".join(clean) + note)
                if clean
                else "관련 기억 없음" + note,
                False,
            )
        if name == "memory_retain":
            content = str(args.get("content", "")).strip()
            if not content:
                return "content가 비어 있다", True
            required = ("record_id", "kind", "title", "source", "source_revision", "importance", "confidence", "status")
            missing = [field for field in required if not str(args.get(field) or "").strip()]
            if missing:
                return "프로젝트 메모리 등록 필수 항목 누락: " + ", ".join(missing), True
            from ..project_memory import ProjectRecord, record_item, validate_record

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
                prefix = (
                    "injection scan: "
                    if any("prompt injection" in r for r in validation.reasons)
                    else "등록 기준 위반: "
                )
                return prefix + reasons + " — 저장 거부", True
            item = record_item(
                record,
                cfg["project_id"],
                project_uid=str(cfg.get("project_uid") or ""),
                binding_id=str(cfg.get("binding_id") or ""),
            )
            aid = stage_retain(root, item, target=backend_target(cfg))
            if autosave_enabled(cfg):
                # 스테이징은 건너뛰지 않는다 — 커밋 경로가 approval_id를 요구하고, 그 경로가
                # Git 정본 선기록·digest 대조를 들고 있다. 자동저장이 없애는 것은 **왕복**이지
                # 검증이 아니다. 커밋이 실패하면 id는 그대로 살아 있으니 사람이 이어받으면 된다.
                try:
                    from ..project_memory import commit_approved_record

                    out = commit_approved_record(root, cfg, aid)
                except Exception as exc:
                    return (
                        f"자동저장 실패 ({type(exc).__name__}: {exc})\n"
                        f"승인 대기로 남겨 뒀다 — approval_id: {aid}\n---\n{item['content']}\n---\n"
                        "사용자에게 사정을 알리고, 승인받은 뒤 memory_retain_commit을 호출하라.",
                        False,
                    )
                canonical = f" · canonical={out['canonical_path']}" if out.get("canonical_path") else ""
                return (
                    f"저장 완료 (project_memory.autosave=on, engine={cfg['engine']}, "
                    f"project_id={cfg['project_id']}){canonical}\n---\n{item['content']}\n---\n"
                    "사용자에게 저장했다고 알려라. memory_retain_commit을 부르지 마라 — 이미 커밋됐다.",
                    False,
                )
            return (
                f"승인 대기 (즉시 저장 안 됨) — approval_id: {aid}\n---\n{item['content']}\n---\n"
                "이 내용을 사용자에게 보여주고 승인받은 뒤 memory_retain_commit을 호출하라.",
                False,
            )
        if name == "memory_retain_commit":
            aid = str(args.get("approval_id", ""))
            try:
                from ..project_memory import commit_approved_record

                out = commit_approved_record(root, cfg, aid)
            except Exception as e:
                return f"프로젝트 메모리 저장 실패: {e}", True
            canonical = f" · canonical={out['canonical_path']}" if out.get("canonical_path") else ""
            return (
                f"저장 완료 (engine={cfg['engine']}, project_id={cfg['project_id']}): "
                f"{json.dumps(out, ensure_ascii=False)[:200]}{canonical}",
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
    if method not in ("tools/list", "tools/call"):
        if rid is not None:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
        return None

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
    if method == "tools/list":
        # 프로젝트 툴은 설정·trust·binding 셋을 다 통과해야 노출된다. 개인 기억 툴은 그
        # 게이트 **밖**이다 — 이 기억은 프로젝트가 아니라 에이전트에 붙으므로, 공유 backend가
        # 없는 저장소에서도 에이전트는 자기 기억을 제안할 수 있어야 한다.
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {"tools": [*_PERSONAL_TOOLS, *(_TOOLS if bound else [])]},
        }
    if method == "tools/call":
        params = msg.get("params") or {}
        if str(params.get("name", "")) in {tool["name"] for tool in _PERSONAL_TOOLS}:
            text, err = _call_personal_tool(str(params.get("name", "")), params.get("arguments") or {})
            return _text_result(rid, text, err)
        if not found:
            return _text_result(
                rid,
                "이 프로젝트에는 공유 메모리 설정(.asgard/memory-server.json)이 없다 — asgard memory connect로 연결",
                True,
            )
        if not trusted:
            return _text_result(
                rid,
                "이 프로젝트의 공유 메모리 backend가 이 machine에서 trusted 상태가 아니다 — asgard memory connect로 명시 승인",
                True,
            )
        if not bound:
            return _text_result(
                rid,
                "이 프로젝트의 공유 메모리 binding이 없거나 foreign/drift 상태다 — "
                + (binding_error or "asgard memory connect로 재검증")
                + " — 메모리 힌트 없이 작업은 계속 가능 (fail-open)",
                True,
            )
        root, cfg = found
        text, err = _call_tool(str(params.get("name", "")), params.get("arguments") or {}, root, cfg)
        return _text_result(rid, text, err)
    return None


def serve(start_dir: str | None = None) -> int:
    """stdio 루프 — 개행 구분 JSON-RPC. EOF로 종료. 파싱 불능 행은 무시 (fail-safe)."""
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
