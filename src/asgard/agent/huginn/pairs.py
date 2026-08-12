"""툴 쌍 무결성 — 압축이 경계를 자를 때 생기는 고아 호출·고아 결과를 제거한다."""

from __future__ import annotations

from .tokens import _blocks, _role


def _tool_use_ids(msg: object) -> set[str]:
    ids: set[str] = set()
    if not isinstance(msg, dict):
        return ids
    for block in _blocks(msg.get("content")):
        if isinstance(block, dict):
            if block.get("type") == "tool_use" and block.get("id"):
                ids.add(str(block["id"]))
        elif str(getattr(block, "type", "") or "") == "tool_use" and getattr(block, "id", None):
            ids.add(str(block.id))
    calls = msg.get("tool_calls")  # openai 와이어
    for call in calls if isinstance(calls, list) else []:
        cid = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
        if cid:
            ids.add(str(cid))
    return ids


def sanitize_tool_pairs(messages: list) -> list:
    """고아 tool_result / tool 메시지를 제거한다.

    압축은 경계를 자르는 일이라 tool_use는 앞에 남고 tool_result만 잘려나가거나 그 반대가
    생긴다. 그대로 보내면 anthropic·openai 모두 400 이다 — 압축이 세션을 죽이는 가장 흔한 길."""
    available: set[str] = set()
    for msg in messages:
        available |= _tool_use_ids(msg)

    out: list = []
    for msg in messages:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        if _role(msg) == "tool":
            if str(msg.get("tool_call_id") or "") in available:
                out.append(msg)
            continue
        content = msg.get("content")
        if _role(msg) == "user" and isinstance(content, list):
            kept = [
                b
                for b in content
                if not (isinstance(b, dict) and b.get("type") == "tool_result")
                or str(b.get("tool_use_id") or "") in available
            ]
            if not kept:
                continue  # tool_result만 있던 메시지가 통째로 고아가 됐다
            if len(kept) != len(content):
                msg = {**msg, "content": kept}
        out.append(msg)

    # 반대 방향 — 결과가 사라진 tool_use가 남았는지. assistant content는 SDK 객체라 블록
    # 단위 수술을 하지 않는다: 짝 없는 호출이 남은 메시지는 통째로 뺀다.
    answered: set[str] = set()
    for msg in out:
        if not isinstance(msg, dict):
            continue
        if _role(msg) == "tool" and msg.get("tool_call_id"):
            answered.add(str(msg["tool_call_id"]))
        for block in _blocks(msg.get("content")):
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id"):
                answered.add(str(block["tool_use_id"]))
    final = []
    for msg in out:
        ids = _tool_use_ids(msg)
        if ids and not ids <= answered:
            continue
        final.append(msg)
    return final
