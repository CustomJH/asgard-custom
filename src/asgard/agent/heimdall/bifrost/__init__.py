"""Trinity 를 배차 장부에 비추는 어댑터 — 역할 턴과 배정 단위를 Run·Task·Dispatch 로.

여태 Trinity 의 통제는 **전이 함수 하나**였다. `quest-log next` 가 다음 역할을 정하고, 그
역할이 돌고, 결과가 퀘스트 로그에 붙는다. 결정론이라는 점에서 좋았지만 배차를 모른다:
어느 턴이 몇 번째 시도인지, 어느 모델이 그 턴을 돌았는지, 병렬 단위 중 무엇이 아직 답을
기다리는지를 물을 자리가 없었다. 그 물음은 wave 병렬이 켜지는 순간 실무가 된다.

이 어댑터가 두 가지를 장부에 적는다:

  역할 턴    THINKER·WORKER·VERIFIER 각각이 Task 하나 + Dispatch 하나. 마지막으로 **성공한**
             턴을 의존으로 달아 순환의 순서가 DAG 로 남는다. 실패한 턴을 의존으로 달면 다음
             턴이 `blocked` 이 되어 순환의 수리 전이 자체가 막힌다.
  배정 단위  wave 의 각 단위가 Worker 턴 Task 의 자식 Task. 의존은 `planning._plan_waves` 가
             짠 실행 일정 그대로다 — 실행자와 같은 함수를 부르므로 장부의 wave 와 실제로 돈
             wave 가 갈라지지 않는다. `access` 는 그 일정의 입력 절반이고, 나머지 절반은
             파일 겹침이다.

그리고 두 가지를 **정한다**. 적기만 하던 계층이 아니다:

  형상       `choose_shape` 가 분기보다 먼저 불려서 갈래를 고른다. direct 면 장부 자체를 안
             연다(`open_ledger`), graph 면 wave, squad 면 딜리버리 fan-out, single 이면 손 하나.
  배차       `CoordinatorLoop.supervise` 가 `task_list(ready=True)` 를 읽어 준비된 일감만
             실행자에게 넘기고, 정산을 기다린 뒤 다음 묶음을 본다 (Orca 의 감독 고리).

**정본은 DB 다.** 프로세스를 재시작해 같은 퀘스트를 이어 받으면 `_resume` 이 이 Run 의 Task 를
읽어 장부 상태를 되살리고, 정산 없이 남은 시도를 회수한다. 중복 방지가 메모리에만 있으면
재개한 퀘스트는 배정 단위 Task 를 두 벌 갖고 시도 횟수가 갈린다.

**전부 fail-open 이다.** 장부가 못 서면 `enabled` 가 내려가고 Trinity 는 종전과 같이 돈다.
정본은 퀘스트 로그(`.asgard/quest/*.jsonl`)이고 이것은 그 위의 파생 기록이라, 장부를 얻으려다
작업을 잃는 교환은 성립하지 않는다. 다만 fail-open 은 fail-silent 가 아니다 — 삼킨 실패는
`_note` 가 `notes` 와 stderr 에 한 줄씩 남긴다.

파사드다. 본문은 아래 모듈들이 나눠 진다 — 부르는 쪽은 종전대로 `…heimdall.bifrost` 하나만
보면 되고, 밑줄로 시작하는 이름도 여기서 그대로 다시 내보낸다 (시험이 직접 임포트한다).

**이름을 갈아 끼우려면 정의한 모듈에 꽂아라.** 장부 함수(`run_bind`·`task_create`·`task_list`·
`gate_create`·`ask` 등)는 `bifrost.ledger` 가, 형상 판정(`_by_policy`)은 `bifrost.shape` 가
자기 이름으로 들고 있다. 여기 재수출된 이름을 바꿔도 그 모듈 안의 호출자는 자기 모듈에서
찾으므로 바뀐 것을 못 본다 — 죽지 않고 조용히 옛 함수를 계속 부른다.
"""

from __future__ import annotations

# 분해 전 `bifrost` 가 들고 있던 이름 — 이 파사드 안에서는 안 쓰지만 부르는 쪽이 이 이름으로
# 닿을 수 있어 그대로 남긴다 (표준 라이브러리 모듈까지).
import sys  # noqa: F401
import threading  # noqa: F401
from typing import TYPE_CHECKING  # noqa: F401

from ....orchestration import (  # noqa: F401
    ACTIONABLE_TYPES,
    META_MAX_ATTEMPTS,
    ask,
    choose_shape,
    dispatch_mark,
    dispatch_settle,
    escalate,
    gate_create,
    open_dispatch,
    pending_questions,
    reclaim,
    reply,
    run_bind,
    run_close,
    run_shape,
    set_meta,
    task_create,
    task_list,
    task_update,
    worker_done,
)
from ....orchestration import check as mail_check  # noqa: F401
from ..planning import _plan_waves  # noqa: F401
from .coordinator import _SUPERVISE_ROUNDS, CoordinatorLoop  # noqa: F401
from .ledger import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _DRAIN_TIMEOUT_MS,
    _MAX_MODEL_ANSWERS,
    _NOTE_CAP,
    _TURN_UNIT_IDS,
    BifrostLedger,
)
from .null import NULL_LEDGER, _NullLedger, open_ledger  # noqa: F401
from .shape import _by_policy, _NullLedgerShapeMixin, _shape_why  # noqa: F401

__all__ = [
    "NULL_LEDGER",
    "BifrostLedger",
    "CoordinatorLoop",
    "open_ledger",
]
