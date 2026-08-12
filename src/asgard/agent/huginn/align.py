"""경계 정렬 — 요약이 잘라낼 중간 구간의 앞뒤를 역할 교대가 맞는 자리로 옮긴다."""

from __future__ import annotations

from .handoff import is_handoff
from .tokens import _blocks, _role


def _align_head_end(messages: list, n: int) -> int:
    """head는 assistant로 끝나야 한다 — 뒤에 붙는 핸드오프(user)와 역할이 겹치지 않게."""
    n = max(0, min(n, len(messages)))
    if n == 0:
        return 0
    while n < len(messages) and _role(messages[n - 1]) != "assistant":
        n += 1
    return n if n <= len(messages) and _role(messages[n - 1]) == "assistant" else 0


def _is_real_user_turn(msg: object) -> bool:
    """사람이 친 턴인가 — tool_result만 실린 user 메시지는 전송 규약상의 껍데기다."""
    if not isinstance(msg, dict) or _role(msg) != "user":
        return False
    if is_handoff(msg):
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return any(
        isinstance(b, dict) and b.get("type") in {"text", "image"} or isinstance(b, str) for b in _blocks(content)
    )


def _align_tail_start(messages: list, start: int, floor: int) -> int:
    """tail은 진짜 user 턴에서 시작해야 한다 — 앞에 붙는 ack(assistant)와 교대가 맞고,
    tool_result로 시작해 고아가 되는 일도 없다. 보존 쪽(뒤로)을 먼저 찾는다."""
    for i in range(min(start, len(messages) - 1), floor - 1, -1):
        if _is_real_user_turn(messages[i]):
            return i
    for i in range(max(start, floor), len(messages)):
        if _is_real_user_turn(messages[i]):
            return i
    return -1
