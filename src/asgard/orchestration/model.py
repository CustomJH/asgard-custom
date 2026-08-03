"""오케스트레이션 어휘와 순수 판정 — 저장소를 모르는 절반.

이 모듈에는 IO가 없다. 상태 이름과 전이 규칙만 있고, 어느 것도 SQLite나 파일을 보지 않는다.
갈라 둔 이유는 시험 비용이다: DAG 준비도·회로 차단·배달 묶기는 오케스트레이션에서 가장
자주 틀리는 판정인데, 저장소와 붙어 있으면 그 판정 하나를 확인하려고 매번 DB를 세워야 한다.

용어는 Orca 의 오케스트레이션 계약에서 가져왔다. 세 층으로 나뉜다:

  Run       이름 공간이자 코디네이터의 우편함. 일정을 짜지 않고 워커를 배치하지도 않는다.
  Task      일감. 의존(`deps`)으로 DAG 를 이루고, 상태는 아래 TASK_STATUSES 다섯이다.
  Dispatch  Task 한 번의 **시도**를 워커 하나에 묶은 것. 수명 권한은 여기 있다 —
            워커의 완료 보고(`worker_done`)는 Task 가 아니라 이 Dispatch 에 귀속된다.

Task 와 Dispatch 를 가르는 이유는 재시도다. 한 Task 가 세 번 시도되면 Dispatch 가 셋 생기고,
각각 다른 워커·다른 결과를 갖는다. 둘을 한 행에 합치면 두 번째 시도가 첫 번째의 결과를
덮어써서 "왜 실패했는가" 를 잃는다.
"""

from __future__ import annotations

# 일감의 상태. `ready` 와 `pending` 을 가르는 것은 의존뿐이다 — 의존이 전부 완료면 ready,
# 하나라도 안 끝났으면 pending, 하나라도 실패면 blocked.
TASK_STATUSES = ("pending", "ready", "dispatched", "completed", "failed", "blocked")
TASK_OPEN = frozenset({"pending", "ready", "dispatched"})
TASK_RESOLVED = frozenset({"completed", "failed"})

# 시도의 상태. `outcome_unknown` 은 실패가 아니다 — 워커가 보고 없이 사라져서 결과를 모르는
# 것이고, 자원이 아직 살아 있을 수 있다. 실패로 접으면 살아 있는 워커를 죽은 것으로 세게 된다.
DISPATCH_STATES = ("ready", "settled", "failed", "stopped", "outcome_unknown")
DISPATCH_TERMINAL = frozenset({"settled", "failed", "stopped"})

OUTCOMES = ("succeeded", "failed")

# 메시지 종류. `question` 만 답을 기다리고(blocking), 나머지는 단방향이다.
MESSAGE_TYPES = (
    "status",
    "dispatch",
    "worker_done",
    "merge_ready",
    "escalation",
    "handoff",
    "question",
    "decision_gate",
    "heartbeat",
)
# 코디네이터가 기다릴 값이 있는 종류. `check(wait=True)` 의 기본 필터다 — heartbeat 나
# status 로 대기가 깨면 코디네이터가 아무 할 일 없이 매번 깨어난다.
ACTIONABLE_TYPES = ("worker_done", "escalation", "question")

PRIORITIES = ("low", "normal", "high")

GATE_STATUSES = ("open", "resolved")

# 한 배달 묶음의 상한. 코디네이터는 이 묶음을 통째로 처리한 뒤에야 ack 하므로, 상한이 없으면
# 밀린 메일 수천 건이 한 번에 컨텍스트로 들어간다.
DELIVERY_CAP = 50

# 한 Task 가 연속으로 이만큼 실패하면 회로를 끊고 failed 로 접는다. **기본값일 뿐이다** —
# 프로젝트가 `ticket_runtime.max_attempts` 를 정해 두면 장부가 그 값을 meta 에 적고
# (`store.META_MAX_ATTEMPTS`) 배차·정산이 둘 다 그것을 읽는다. 두 계층이 다른 횟수로
# 포기하면 티켓은 살아 있는데 Task 는 죽은 상태가 생긴다.
MAX_ATTEMPTS = 3


class OrchestrationError(RuntimeError):
    """오케스트레이션 계약 위반 — 없는 Task 에 배차하거나, 순환 의존을 만들거나."""


def task_status_for(current: str, dep_statuses: list[str]) -> str:
    """의존 상태 목록으로부터 이 Task 의 상태를 도출한다.

    이미 끝난 Task(`completed`/`failed`)와 배차 중인 Task 는 그대로 둔다 — 의존이 나중에
    실패해도 이미 돌고 있는 워커를 상태 표기로 되돌릴 수는 없다. 되돌리려면 dispatch 쪽에서
    중지시켜야 한다.
    """
    if current in TASK_RESOLVED or current == "dispatched":
        return current
    if any(status == "failed" for status in dep_statuses):
        return "blocked"
    if any(status == "blocked" for status in dep_statuses):
        return "blocked"
    if all(status == "completed" for status in dep_statuses):
        return "ready"
    return "pending"


def circuit_broken(failed_outcomes: int, max_attempts: int = MAX_ATTEMPTS) -> bool:
    """연속 실패 결과가 상한에 닿아 이 Task 를 접어야 하는가."""
    return failed_outcomes >= max(1, max_attempts)


def topo_waves(
    task_ids: list[str],
    deps: dict[str, list[str]],
    conflicts: dict[str, set[str]] | None = None,
) -> list[list[str]]:
    """의존 DAG 를 동시 실행 가능한 묶음의 순열로 편다.

    같은 묶음 안의 Task 들은 서로 의존하지 않으므로 병렬로 돌 수 있다. 목록 밖의 의존
    (아직 만들지 않은 Task 를 가리키는 id)은 무시한다 — 부분 DAG 를 펼 때 정상이다.

    Args:
        conflicts: `conflicts[a]` 는 a 와 같은 묶음에 두면 안 되는 id 들. 대칭은 호출측이
            보장한다. 의존과 달리 순서를 정하지 않는다 — 준비된 것 중 먼저 담긴 쪽이 이번
            묶음에 남고 충돌하는 쪽은 다음 묶음으로 밀린다. None 이면 의존만으로 편다.
            heimdall.planning._plan_waves 가 파일 경로 겹침을 이 인자로 넘긴다.

    Raises:
        OrchestrationError: 순환 의존이 있을 때. 순환은 조용히 넘기면 그 Task 들이 영영
            pending 으로 남아 코디네이터가 이유 없이 대기한다.
    """
    known = set(task_ids)
    pending = {tid: {d for d in deps.get(tid, []) if d in known} for tid in task_ids}
    waves: list[list[str]] = []
    done: set[str] = set()
    while pending:
        ready = sorted(tid for tid, need in pending.items() if not (need - done))
        if not ready:
            raise OrchestrationError(f"순환 의존이에요: {', '.join(sorted(pending))}")
        wave: list[str] = []
        taken: set[str] = set()
        for tid in ready:
            blocked = conflicts.get(tid) if conflicts else None
            if blocked and blocked & taken:
                continue
            wave.append(tid)
            taken.add(tid)
        if not wave:
            # 준비된 것을 하나도 안 담으면 다음 반복이 같은 집합을 다시 보고 끝나지 않는다.
            wave = [ready[0]]
        waves.append(wave)
        done.update(wave)
        for tid in wave:
            del pending[tid]
    return waves


def valid_transition(before: str, after: str) -> bool:
    """Task 상태 전이가 허용되는가. 끝난 것은 되살아나지 않는다."""
    if before == after:
        return True
    if before in TASK_RESOLVED:
        return False
    return after in TASK_STATUSES
