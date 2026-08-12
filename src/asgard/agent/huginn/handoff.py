"""핸드오프 식별 — 트랜스크립트에 핸드오프 쌍을 하나만 남기기 위한 판별과 분리."""

from __future__ import annotations

from .contract import HANDOFF_ACK, HANDOFF_END, HANDOFF_PREFIX
from .text import _message_text
from .tokens import _role


def is_handoff(msg: object) -> bool:
    """이 메시지가 이전 압축이 남긴 핸드오프인가 — 재압축이 요약을 쌓지 않게 하는 판정."""
    if not isinstance(msg, dict) or _role(msg) != "user":
        return False
    return _message_text(msg).lstrip().startswith(HANDOFF_PREFIX[:60])


def _is_ack(msg: object) -> bool:
    return isinstance(msg, dict) and _role(msg) == "assistant" and _message_text(msg).strip() == HANDOFF_ACK


def extract_handoff(messages: list) -> tuple[str | None, list]:
    """기존 핸드오프 쌍을 히스토리에서 떼어내고 (본문, 나머지)를 준다.

    쌓기 금지가 핵심이다 — 핸드오프가 여럿 살아 있으면 낡은 지시가 계속 살아남고, 요약이
    요약을 요약하며 원문에서 멀어진다. 트랜스크립트에는 항상 최신 1건만 존재한다."""
    body: str | None = None
    out: list = []
    skip_ack = False
    for msg in messages:
        if is_handoff(msg):
            text = _message_text(msg)
            core = text.split(HANDOFF_END)[0]
            if core.lstrip().startswith(HANDOFF_PREFIX[:60]):
                core = core.lstrip()[len(HANDOFF_PREFIX) :] if core.lstrip().startswith(HANDOFF_PREFIX) else core
            body = core.strip() or body
            skip_ack = True
            continue
        if skip_ack and _is_ack(msg):
            skip_ack = False
            continue
        skip_ack = False
        out.append(msg)
    return body, out


def _handoff_pair(summary: str) -> list[dict]:
    return [
        {"role": "user", "content": f"{HANDOFF_PREFIX}\n\n{summary.strip()}\n\n{HANDOFF_END}"},
        {"role": "assistant", "content": HANDOFF_ACK},
    ]
