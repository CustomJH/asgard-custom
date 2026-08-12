"""요약 입력 직렬화 — 메시지를 텍스트로 펴고, 비밀을 지우고, 길이를 자르고, 프롬프트를 짓는다."""

from __future__ import annotations

import json

from .contract import _PREAMBLE, _SCHEMA
from .tokens import _blocks, _is_image, _role

_SUMMARY_INPUT_MAX_CHARS = 120_000  # 요약 프롬프트 입력 상한 (~30k 토큰)
_SUMMARY_TURN_MAX_CHARS = 4_000  # 메시지 1건이 요약 입력을 독식하지 못하게
_PREV_SUMMARY_MAX_CHARS = 12_000


def _block_text(block: object) -> str:
    if isinstance(block, str):
        return block
    if _is_image(block):
        return "[image]"
    if isinstance(block, dict):
        kind = str(block.get("type") or "")
        if kind == "text":
            return str(block.get("text") or "")
        if kind == "tool_result":
            body = block.get("content")
            if isinstance(body, str):
                return f"[tool result] {body}"
            return "[tool result] " + " ".join(_block_text(b) for b in _blocks(body))
        if kind == "tool_use":
            return f"[tool call] {block.get('name')} {_json(block.get('input'))}"
        return _json(block)
    kind = str(getattr(block, "type", "") or "")
    if kind == "text":
        return str(getattr(block, "text", "") or "")
    if kind == "tool_use":
        return f"[tool call] {getattr(block, 'name', '')} {_json(getattr(block, 'input', None))}"
    if kind == "thinking":
        return ""  # 사고 블록은 요약 재료가 아니다 — 결론만 남기면 된다
    return ""


def _json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError, ValueError:
        return str(value)


def _message_text(msg: object) -> str:
    if not isinstance(msg, dict):
        return ""
    parts = [t for t in (_block_text(b) for b in _blocks(msg.get("content"))) if t]
    return " ".join(parts).strip()


def _redact(text: str) -> str:
    try:
        from ...memory.policy import redact_secrets

        return redact_secrets(text)
    except Exception:
        return text  # fail-open — 편집 불능이 압축을 막지 않는다


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.7)
    return text[:head].rstrip() + f"\n...[{len(text) - limit}자 생략]...\n" + text[-(limit - head) :].lstrip()


def serialize_turns(messages: list) -> str:
    lines: list[str] = []
    for msg in messages:
        text = _message_text(msg)
        if not text:
            continue
        lines.append(f"[{_role(msg) or 'unknown'}] {_clip(_redact(text), _SUMMARY_TURN_MAX_CHARS)}")
    body = "\n\n".join(lines)
    return _clip(body, _SUMMARY_INPUT_MAX_CHARS)


def build_prompt(turns: str, previous: str | None, lessons: str = "") -> str:
    if previous:
        return (
            f"{_PREAMBLE}{lessons}\n\n"
            "You are UPDATING an existing handoff. Preserve everything still relevant, add the "
            "new completed actions to the numbered list (continue the numbering), move finished "
            "items out of Blocked, and refresh Active State and Active Task. Drop an item only "
            "when it is clearly obsolete.\n\n"
            f"EXISTING HANDOFF:\n{_clip(previous, _PREV_SUMMARY_MAX_CHARS)}\n\n"
            f"NEW TURNS TO FOLD IN:\n{turns}\n\n"
            f"Use this exact structure:\n\n{_SCHEMA}\n\n"
            "Write only the handoff body. No preamble, no prefix, no closing remarks."
        )
    return (
        f"{_PREAMBLE}{lessons}\n\n"
        f"TURNS TO COMPACT:\n{turns}\n\n"
        f"Use this exact structure:\n\n{_SCHEMA}\n\n"
        "Write only the handoff body. No preamble, no prefix, no closing remarks."
    )
