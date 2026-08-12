"""토큰 추정 — 전송 전 판단용 근사. 과소계상만 아니면 되므로 문자 수를 나눈다.

메시지 형상 판별(_role·_blocks·_is_image)도 여기 산다. 이 패키지의 어느 모듈도 부르지 않는다."""

from __future__ import annotations

import json

_CHARS_PER_TOKEN = 4
_IMAGE_TOKENS = 1600  # provider 별로 다르지만 예산 계산이 낙관적이면 안 된다 — 상한 쪽 값


def _role(msg: object) -> str:
    return str(msg.get("role", "")) if isinstance(msg, dict) else ""


def _blocks(content: object) -> list:
    if isinstance(content, list):
        return content
    return [] if content is None else [content]


def _is_image(block: object) -> bool:
    kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", "")
    return str(kind or "") == "image"


def _block_chars(block: object) -> int:
    if _is_image(block):
        return _IMAGE_TOKENS * _CHARS_PER_TOKEN
    if isinstance(block, str):
        return len(block)
    if isinstance(block, dict):
        try:
            return len(json.dumps(block, ensure_ascii=False, default=str))
        except TypeError, ValueError:
            return len(str(block))
    dump = getattr(block, "model_dump_json", None)
    if callable(dump):
        try:
            return len(dump())
        except Exception:
            pass
    return len(str(block))


def message_tokens(msg: object) -> int:
    """메시지 1건의 대략 토큰 — 전송 전 판단용이라 정확할 필요는 없고 과소계상만 아니면 된다."""
    if not isinstance(msg, dict):
        return _block_chars(msg) // _CHARS_PER_TOKEN
    chars = len(_role(msg)) + sum(_block_chars(b) for b in _blocks(msg.get("content")))
    return chars // _CHARS_PER_TOKEN + 4  # 메시지 프레이밍 오버헤드


def estimate_tokens(messages: list) -> int:
    return sum(message_tokens(m) for m in messages)
