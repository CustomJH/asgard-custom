"""Bifrost — 에이전트 오케스트레이션 계층 (Run · Task · Dispatch · 우편 · 게이트).

Trinity 는 여태 **역할 순환**은 갖췄지만 **배차 통제**가 없었다. thinker→worker→verifier 의
전이는 결정론이었어도, 병렬 워커가 여럿 돌기 시작하면 코디네이터가 할 수 있는 일이 없었다:
워커는 반환값으로만 말했고(막혀도 물을 수 없다), 재시도는 티켓 lease 안에 갇혀 있었고
(어느 시도가 왜 실패했는지 남지 않는다), 의존은 파일 겹침에서 추론될 뿐 선언할 수 없었다.

이 패키지가 그 통제를 세운다. 형상은 Orca 의 오케스트레이션 계약에서 가져왔다:

  Run       이름 공간이자 코디네이터 우편함. **일정을 짜지 않는다** — 배치는 부르는 쪽 몫이다.
  Task      일감. `deps` 로 DAG 를 이루고 상태는 의존에서 도출된다.
  Dispatch  Task 한 번의 시도. 수명 권한이 여기 있고, 연속 실패 3회면 회로를 끊는다.
  우편      typed 메시지 + FIFO 배달(ack 까지 재생) + 왕복 `ask`/`reply`.
  게이트    코디네이터가 DAG 를 멈추고 내리는 결정. 워커의 질문과 구분된다.

**저장소는 파생이다.** 정본은 퀘스트 로그(`.asgard/quest/*.jsonl`)이고 이 DB
(`.asgard/orchestration.db`)는 그 위의 배차 장부다. 열기 실패는 fail-open 한다 — 장부를 얻으려다
작업을 잃지 않는다.

계층: domain. 위(agent·commands)에서 부르고, 아래(settings·errors)만 본다.
"""

from .board import (
    gate_create,
    gate_list,
    gate_resolve,
    reclaim,
    refresh,
    run_bind,
    run_close,
    run_create,
    run_for_quest,
    run_list,
    run_shape,
    run_show,
    task_create,
    task_for_unit,
    task_list,
    task_show,
    task_update,
)
from .dispatch import heartbeat, open_dispatch
from .dispatch import history as dispatch_history
from .dispatch import mark as dispatch_mark
from .dispatch import settle as dispatch_settle
from .dispatch import show as dispatch_show
from .mail import (
    ask,
    check,
    escalate,
    inbox,
    pending_questions,
    reply,
    send,
    wait_answer,
    worker_done,
)
from .model import (
    ACTIONABLE_TYPES,
    DELIVERY_CAP,
    DISPATCH_STATES,
    MAX_ATTEMPTS,
    MESSAGE_TYPES,
    TASK_STATUSES,
    OrchestrationError,
    circuit_broken,
    task_status_for,
    topo_waves,
)
from .roster import close_agent, consume_self_report, live_agents, live_dispatch, note_agent
from .store import META_MAX_ATTEMPTS, db_path, exists, reset, reset_messages, reset_tasks, set_meta
from .strategy import SHAPES
from .strategy import choose as choose_shape

__all__ = [
    "SHAPES",
    "choose_shape",
    "run_shape",
    "ACTIONABLE_TYPES",
    "DELIVERY_CAP",
    "DISPATCH_STATES",
    "MAX_ATTEMPTS",
    "META_MAX_ATTEMPTS",
    "MESSAGE_TYPES",
    "TASK_STATUSES",
    "OrchestrationError",
    "ask",
    "check",
    "circuit_broken",
    "close_agent",
    "consume_self_report",
    "db_path",
    "dispatch_history",
    "dispatch_mark",
    "dispatch_settle",
    "dispatch_show",
    "escalate",
    "exists",
    "gate_create",
    "gate_list",
    "gate_resolve",
    "heartbeat",
    "inbox",
    "live_agents",
    "live_dispatch",
    "note_agent",
    "open_dispatch",
    "pending_questions",
    "reclaim",
    "refresh",
    "reply",
    "reset",
    "reset_messages",
    "reset_tasks",
    "run_bind",
    "run_close",
    "run_create",
    "run_for_quest",
    "run_list",
    "run_show",
    "send",
    "set_meta",
    "task_create",
    "task_for_unit",
    "task_list",
    "task_show",
    "task_status_for",
    "task_update",
    "topo_waves",
    "wait_answer",
    "worker_done",
]
