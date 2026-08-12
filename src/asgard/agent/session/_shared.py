"""믹스인 넷이 공유하는 세션 상태의 선언 — 값은 `AgentSession.__init__` 이 채운다.

선언만 있고 대입이 없어서 런타임에는 아무 속성도 안 만든다 (`__annotations__` 항목뿐).
믹스인은 자기가 정의하지 않은 이름을 읽는데, 그 이름이 어디서 오는지 적힌 자리가 여태
없었다 — 분해 전에는 한 클래스였으므로 물을 일이 아니었고, 분해 뒤에는 검사기가 믹스인
하나를 홀로 읽으면서 126건을 냈다. 여기가 그 답이다.

형제 믹스인·`AgentSession` 이 정의하는 메서드는 `Callable[..., T]` 로 적는다 — `def` 스텁으로
적으면 MRO 끝자리에 안 부르는 구현이 하나 더 생긴다. 이쪽은 선언이라 그 몸통이 아예 없다.
(`heimdall/core/_shared.py` 의 `_HeimdallState` 와 같은 형상이다.)"""

from __future__ import annotations

import threading
from typing import Any, Callable

from ...providers import ResolvedProvider
from .types import SessionResult, _Call


class _SessionState:
    """세션 상태 선언 — 인스턴스는 `AgentSession` 하나뿐이고 이 클래스는 값을 안 든다."""

    # ── provider 좌표 ──
    # client 는 트랜스포트마다 다른 벤더 SDK 객체다 (anthropic·openai·codex·claude_cli 마커).
    # 분해 전에도 생성자 인자에 어노테이션이 없었으므로 좁히면 없던 제약이 생긴다.
    client: Any
    rp: ResolvedProvider
    root: str
    system: str
    role: str
    tools: list[dict]
    max_iterations: int

    # ── 표면·취소 ──
    on_text: Callable[[str], None]
    on_status: Callable[[str | None], None]
    cancel_event: threading.Event

    # ── 턴 상태 ──
    messages: list[dict]
    cache_enabled: bool
    cache_ttl: str
    _codex_session_id: str

    # ── 형제 믹스인·`AgentSession` 이 정의하는 메서드 ──
    _cancelled: Callable[..., bool]
    _execute: Callable[[_Call, SessionResult], tuple[str, bool]]
    _fence_tail: Callable[..., None]
    _journal_started: Callable[..., tuple[str | None, float]]
    _journal_error: Callable[..., None]
    _thought_line: Callable[..., None]
    _throttle: Callable[..., None]
    _tool_line: Callable[..., None]
    emit_text: Callable[..., None]
    _anthropic_stream: Callable[..., Any]
    _maybe_compress: Callable[..., None]
    _maybe_compress_codex: Callable[..., list]
    _note_server_compaction: Callable[..., None]
    _server_compaction_retry: Callable[..., bool]
