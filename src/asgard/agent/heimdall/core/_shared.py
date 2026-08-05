"""Heimdall 이 쓰는 프로토콜 하나와 순수 헬퍼 — 조정자 상태를 안 든다."""

from __future__ import annotations

import threading
from typing import Callable, Protocol

from ....providers import ResolvedProvider
from ...session import AgentSession, SessionResult


class SessionLike(Protocol):
    """_run_turn이 요구하는 표면 — run() 하나. 테스트 대역(FakeSession)이 AgentSession 상속 없이 만족."""

    def run(self, user_content: str) -> SessionResult: ...


class _HeimdallState:
    """믹스인 넷이 공유하는 조정자 상태의 선언 — 값은 `Heimdall.__init__` 이 채운다.

    선언만 있고 대입이 없어서 런타임에는 아무 속성도 안 만든다 (`__annotations__` 항목뿐).
    믹스인은 자기가 정의하지 않은 이름을 읽는데, 그 이름이 어디서 오는지 적힌 자리가 여태
    없었다 — 분해 전에는 한 클래스였으므로 물을 일이 아니었고, 분해 뒤에는 검사기가 믹스인
    하나를 홀로 읽으면서 307건을 냈다. 여기가 그 답이다.

    형제 믹스인이 정의하는 메서드는 `Callable[..., T]` 로 적는다 — `def` 스텁으로 적으면
    MRO 끝자리에 안 부르는 구현이 하나 더 생긴다. 이쪽은 선언이라 그 몸통이 아예 없다."""

    # ── 세션 좌표 ──
    rp: ResolvedProvider
    root: str
    on_text: Callable[[str], None]
    on_status: Callable[[str | None], None]
    policy: dict
    role_rp: dict[str, ResolvedProvider]
    _explicit_agent: str
    _sleep: Callable[[float], None]

    # ── 동시 실행 상태 (모두 _state_lock 아래) ──
    _state_lock: threading.Lock
    cancel_event: threading.Event
    _session_seq: int
    _sessions: dict[str, dict]
    _clients: dict[tuple, object]

    # ── 프롬프트 계층 ──
    lagom: str
    bragi: str
    direct_identity: str
    map_note: str
    _map_warnings: set[str]
    _role_agent: dict[str, str]
    _session_agent: str
    _agent_note_cache: dict[str, str]

    # ── 턴 누적 ──
    total_tokens: int
    cache_read_tokens: int
    cache_prompt_tokens: int
    turn_recap: dict
    last_response_text: str
    _explore_cmds: int
    _memory_session_id: str
    _memory_turn_seq: int
    _last_quest_id: str | None
    _last_completion: dict | None

    # ── 형제 믹스인·`Heimdall` 이 정의하는 메서드 ──
    _complete_text: Callable[..., str]
    _recap_event: Callable[..., None]
    _session: Callable[..., AgentSession]
    _track_cache: Callable[..., None]
    _persist_turn: Callable[..., None]
    _trinity: Callable[..., str]


def _new_recap() -> dict:
    """턴 recap 집계 그릇 — 메타 이벤트(기억 저장·보존·제안 등 백그라운드 부수 작업, 표시 1순위)
    + 활동 집계(툴 횟수·파일별 생성/수정·커맨드 첫 단어·에이전트 역할, 이벤트 없을 때 폴백)
    + recall_chars(결정론 회상으로 프롬프트에 실제 주입된 문자수 — 답변 소스 배지 원천)."""
    from collections import Counter

    return {
        "events": [],
        "tools": Counter(),
        "files": {},
        "cmds": Counter(),
        "agents": Counter(),
        "recall_chars": 0,
    }


def _invoked_command(request: str) -> str | None:
    """이 턴이 `/skill args` 확장인지 — 맞으면 그 원문, 아니면 None (fail-open)."""
    try:
        from ....skill_registry import invoked_skill_command

        return invoked_skill_command(request)
    except Exception:
        return None


def _concurrent_label(rows: list[dict]) -> str:
    """지금 도는 세션들을 독의 한 줄로 접는다.

    여태는 마지막 하나만 적고 나머지는 `+2`라는 숫자로 뭉갰다. 편대(thor 2~4기)와 wave에서는
    그 뭉갠 쪽이 정보의 대부분이다 — 셋이 도는데 화면은 하나만 말하고, 그 하나가 제일 빨리
    끝나는 놈이면 남은 둘이 뭘 하는지는 끝까지 안 나온다.

    그래서 전부 적되 **자리를 공평하게 나눈다**: 뒤쪽을 통째로 잘라 내는 대신 각 몫을 좁힌다.
    한 기만 돌 때는 종전과 같은 문장이라 흔한 경우의 화면은 안 변한다."""
    from .... import ui

    if len(rows) == 1:
        row = rows[0]
        return row["role"] + (f" · {row['status']}" if row["status"] else "")
    head = f"×{len(rows)}"
    # 독 상태 행은 단일 물리 행이라 넘치면 랩이 프레임을 깬다. 등불·경과초·여백을 뺀 나머지를
    # 세션 수로 나눠 각 몫을 정한다 (최소 14 — 그 아래면 역할 이름조차 안 남는다).
    share = max(14, (ui.term_cols() - len(head) - 12) // len(rows) - 3)
    parts = [ui.oneline(row["role"] + (f" · {row['status']}" if row["status"] else ""), share) for row in rows]
    return head + " " + " ⋮ ".join(parts)
