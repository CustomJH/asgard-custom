"""T3 서버측 압축 (anthropic compact-2026-01-12) — 요청 필드와 응답 판별."""

from __future__ import annotations

from .contract import _PREAMBLE, _SCHEMA
from .policy import CompressPolicy
from .tokens import _blocks

SERVER_BETA = "compact-2026-01-12"
_SERVER_EDIT_TYPE = "compact_20260112"
_SERVER_MIN_TRIGGER = 50_000  # API 최소치 — 그 아래는 요청이 거절된다


def server_side_kwargs(pol: CompressPolicy, window: int) -> dict:
    """서버측 압축 요청 필드. 미사용이면 빈 dict — 호출자는 그대로 전개하면 된다.

    요약 지시는 우리 핸드오프 계약을 그대로 넘긴다: instructions는 기본 프롬프트를 '대체'하므로
    (보완이 아니다) 비워두면 provider 기본 요약이 우리 규율을 무시한다."""
    if not pol.server_side:
        return {}
    trigger = pol.server_trigger_tokens or int(window * pol.summary_at)
    return {
        "betas": [SERVER_BETA],
        "context_management": {
            "edits": [
                {
                    "type": _SERVER_EDIT_TYPE,
                    "trigger": {"type": "input_tokens", "value": max(_SERVER_MIN_TRIGGER, int(trigger))},
                    "instructions": f"{_PREAMBLE}\n\nUse this exact structure:\n\n{_SCHEMA}",
                }
            ]
        },
    }


def has_compaction_block(content: object) -> bool:
    """응답에 서버측 압축 블록이 들어 있는가 — 계측·표면 통지용."""
    for block in _blocks(content):
        kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", "")
        if str(kind or "") == "compaction":
            return True
    return False
