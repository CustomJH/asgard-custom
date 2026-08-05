"""티켓 — 스튜디오가 스스로 발급하고 관리하는 일감 한 건.

형상은 Linear를 따른다. 그 도구가 옳아서가 아니라, **일을 세는 어휘가 이미 그 모양으로
합의돼 있어서**다: 상태 이름은 팀이 짓되 범주는 다섯으로 접히고, 우선순위는 '없음'이 맨
뒤로 가라앉으며, 하위 티켓과 차단 관계는 별개의 축이다([[vocab]]).

  워크스페이스 ── 팀 ── **티켓**        번호의 주인은 팀이다 (`NOR-12`)
        ├─ 프로젝트 ── 마일스톤         팀을 가로지르는 축 — 티켓은 프로젝트 하나에만
        └─ 이니셔티브

**번호는 한 번만 발급된다.** `NOR-12`는 그 팀에서 영원히 그 티켓이다 — 지워도 번호는
재사용하지 않는다. 사람이 대화에서 부르는 이름이라, 같은 이름이 두 번 나오면 대화가 깨진다.

**상태 변경은 시각을 남긴다.** 진행으로 옮기면 `started_at`, 완료면 `completed_at`. 되돌리면
지운다 — 완료 표시가 남아 있는 '진행 중' 티켓은 리드타임 통계를 조용히 거짓말하게 만든다.

**보이는 범위는 폴더가 정한다, 사는 곳은 워크스페이스다.** 저장소 안에서 부르면 그 저장소에
매인 팀의 일감을 본다(여태와 같은 손맛). 아직 안 매인 자리거나 `team="*"` 면 워크스페이스
전체를 본다 — 폴더를 안 열고도 "지금 뭘 해야 하지"에 답할 수 있어야 하기 때문이다.

정본은 `<에이전트 홈>/studio/workspace.db` ([[db]]). 이 모듈은 그 위의 어휘와 규칙만 진다.
동사는 면별 모듈이 지고 여기는 그것들을 한 이름 아래 모은다 — 부르는 자리는 여태와 같다."""

from __future__ import annotations

# 어휘와 저장소 오류는 여기서 나지 않는다 — 부르는 쪽이 `tickets.STATUSES` 로 닿아 온 이름이라
# 같은 자리에 그대로 둔다 (아래 `__all__` 이 그 계약이다).
from ..db import StoreError
from ..vocab import (
    LINK_KINDS,
    OPEN_STATUSES,
    PRIORITIES,
    PRIORITY_LABEL,
    SOURCES,
    STATUS_LABEL,
    STATUS_TYPE,
    STATUSES,
)
from ._core import EVIDENCE_VERDICTS, TicketError, prefix
from .crud import add_comment, create_ticket, delete_ticket, link_tickets, move_ticket, unlink_tickets, update_ticket
from .cycles import active_cycle, close_cycle, create_cycle, list_cycles
from .evidence import attach_evidence, detach_evidence, list_evidence
from .labels import create_label, delete_label, list_labels
from .triage import triage_accept, triage_decline, triage_queue, triage_snooze
from .views import board, find_ticket, get_ticket, list_tickets, sort_key, summary, tickets_for_task

__all__ = [
    "StoreError",
    "STATUSES",
    "STATUS_LABEL",
    "STATUS_TYPE",
    "OPEN_STATUSES",
    "PRIORITIES",
    "PRIORITY_LABEL",
    "SOURCES",
    "LINK_KINDS",
    "TicketError",
    "create_ticket",
    "update_ticket",
    "move_ticket",
    "delete_ticket",
    "get_ticket",
    "find_ticket",
    "list_tickets",
    "add_comment",
    "link_tickets",
    "unlink_tickets",
    "EVIDENCE_VERDICTS",
    "attach_evidence",
    "list_evidence",
    "detach_evidence",
    "list_labels",
    "create_label",
    "delete_label",
    "list_cycles",
    "create_cycle",
    "close_cycle",
    "active_cycle",
    "tickets_for_task",
    "triage_queue",
    "triage_accept",
    "triage_decline",
    "triage_snooze",
    "summary",
    "board",
    "prefix",
    "sort_key",
]
