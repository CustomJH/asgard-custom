"""와이어 어댑터 — Asgard 정본 스키마와 provider 형식 사이의 변환, 그리고 Responses 호출 1회.

여기 있는 것은 전부 순수 변환이거나 전송 한 줄이다. 루프도 상태도 없어서 트랜스포트 믹스인
셋이 같은 함수를 나눠 쓴다."""

from __future__ import annotations

import json

from ..tool_kernel import to_openai_tool


def _responses_create(client, kwargs: dict, *, codex_backend: bool):
    """Responses 호출 1회 — codex 백엔드만 스트리밍 전송으로 보낸다.

    ChatGPT Codex 엔드포인트는 ``stream=true`` 가 아니면 요청을 400 으로 거절한다.
    api.openai.com 은 논스트리밍을 그대로 받으므로 전송만 갈라두고 응답 형상은 같다."""
    if not codex_backend:
        return client.responses.create(**kwargs)
    from ...openai_codex import create_response

    return create_response(client, **kwargs)


def _to_openai_tool(t: dict) -> dict:
    return to_openai_tool(t)


def _to_responses_tool(t: dict) -> dict:
    """Canonical Asgard schema → OpenAI Responses function tool schema."""
    return {
        "type": "function",
        "name": t["name"],
        "description": t.get("description", ""),
        "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
        "strict": False,
    }


def _codex_replay_item(item: object) -> dict | None:
    """Convert a Codex output item into a store=false input item without server IDs."""
    kind = str(getattr(item, "type", "") or "")
    if kind == "function_call":
        return {
            "type": "function_call",
            "call_id": str(getattr(item, "call_id", "")),
            "name": str(getattr(item, "name", "")),
            "arguments": str(getattr(item, "arguments", "") or "{}"),
        }
    if kind == "reasoning":
        encrypted = str(getattr(item, "encrypted_content", "") or "")
        if not encrypted:
            return None
        return {
            "type": "reasoning",
            "encrypted_content": encrypted,
            "summary": getattr(item, "summary", None) or [],
        }
    if kind == "message":
        content = getattr(item, "content", None)
        dump = getattr(item, "model_dump", None)
        if dump is not None:
            content = dump(exclude={"id", "status"}, exclude_none=True).get("content", content)
        return {"type": "message", "role": "assistant", "content": content or []}
    return None


def _invalid_encrypted_content(error: Exception) -> bool:
    if getattr(error, "status_code", None) != 400:
        return False
    body = getattr(error, "body", None)
    try:
        rendered = json.dumps(body, sort_keys=True) if body is not None else ""
    except TypeError, ValueError:
        rendered = ""
    return "invalid_encrypted_content" in f"{rendered} {error}".lower()
