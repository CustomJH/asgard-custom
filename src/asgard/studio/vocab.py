"""일을 세는 어휘 — 상태·우선순위·관계·건강도.

형상은 Linear 를 따른다. 그 도구가 옳아서가 아니라, **일을 세는 어휘가 이미 그 모양으로
합의돼 있어서**다: 상태 이름은 팀이 짓되 **범주는 다섯으로 고정**이고(그래야 "열린 건수"를
셀 수 있다), 우선순위는 '없음'이 맨 뒤로 가라앉으며, 하위 티켓과 차단 관계는 별개의 축이다.
새 어휘를 지어내면 사람은 배우고 에이전트는 헷갈린다.

이 표가 따로 사는 이유: 팀(워크플로 상태를 정의한다)과 티켓(그 상태를 쓴다)이 둘 다 이걸
봐야 하는데, 한쪽 안에 두면 다른 쪽이 그쪽을 임포트해야 해서 고리가 생긴다.
"""

from __future__ import annotations

# 범주 다섯 — 팀이 상태 이름을 몇 개를 짓든 전부 이 중 하나로 접힌다.
STATUS_TYPES = ("backlog", "unstarted", "started", "completed", "canceled")
STATUS_TYPE_LABEL = {
    "backlog": "백로그",
    "unstarted": "미착수",
    "started": "진행",
    "completed": "완료",
    "canceled": "취소",
}

# 새 팀이 받는 기본 워크플로. (slug, 이름, 범주, 색)
DEFAULT_STATES = (
    ("backlog", "백로그", "backlog", "slate"),
    ("todo", "할 일", "unstarted", "blue"),
    ("in_progress", "진행 중", "started", "gold"),
    ("in_review", "검토 중", "started", "amber"),
    ("done", "완료", "completed", "green"),
    ("canceled", "취소", "canceled", "rose"),
)

STATUSES = tuple(slug for slug, *_ in DEFAULT_STATES)
STATUS_LABEL = {slug: name for slug, name, *_ in DEFAULT_STATES}
STATUS_TYPE = {slug: kind for slug, _, kind, _ in DEFAULT_STATES}
OPEN_TYPES = frozenset({"backlog", "unstarted", "started"})
OPEN_STATUSES = tuple(s for s in STATUSES if STATUS_TYPE[s] in OPEN_TYPES)
STARTED_STATUSES = tuple(s for s in STATUSES if STATUS_TYPE[s] == "started")

PRIORITIES = (0, 1, 2, 3, 4)
PRIORITY_LABEL = {0: "없음", 1: "긴급", 2: "높음", 3: "보통", 4: "낮음"}
# 정렬 순서 — 긴급이 먼저, '없음'은 맨 뒤. 숫자 오름차순으로는 '없음'이 1등이 된다.
PRIORITY_RANK = {1: 0, 2: 1, 3: 2, 4: 3, 0: 4}

SOURCES = ("user", "agent", "plan", "quest")
LINK_KINDS = ("blocks", "relates", "duplicates")
LABEL_COLORS = ("slate", "gold", "amber", "green", "blue", "violet", "rose")

# 프로젝트 상태 — 티켓 상태와 다른 축이다(프로젝트는 '검토 중'이 아니라 '멈춤'이 있다).
PROJECT_STATUSES = ("backlog", "planned", "started", "paused", "completed", "canceled")
PROJECT_STATUS_LABEL = {
    "backlog": "백로그",
    "planned": "계획됨",
    "started": "진행 중",
    "paused": "멈춤",
    "completed": "완료",
    "canceled": "취소",
}
PROJECT_OPEN = ("backlog", "planned", "started", "paused")

# 건강도는 **사람이 적는다**. 진척률에서 자동으로 뽑으면 '늦고 있지만 괜찮은' 과
# '빠르지만 틀린' 을 구분하지 못한다 — 계기가 아니라 위안이 된다.
HEALTHS = ("on_track", "at_risk", "off_track")
HEALTH_LABEL = {"on_track": "순항", "at_risk": "주의", "off_track": "이탈"}

INITIATIVE_STATUSES = ("proposed", "planned", "active", "completed", "canceled")
INITIATIVE_STATUS_LABEL = {
    "proposed": "제안됨",
    "planned": "계획됨",
    "active": "진행 중",
    "completed": "완료",
    "canceled": "취소",
}

# 추정 눈금 — 팀이 고른다. 빈 문자열이면 추정을 안 쓴다.
ESTIMATE_SCALES = {
    "": (),
    "linear": (0, 1, 2, 3, 4, 5),
    "fibonacci": (0, 1, 2, 3, 5, 8),
    "exponential": (0, 1, 2, 4, 8, 16),
    "tshirt": (0, 1, 2, 3, 4, 5),  # XS~XL — 저장은 숫자, 표시는 표면이 한다
}
TSHIRT_LABEL = {0: "-", 1: "XS", 2: "S", 3: "M", 4: "L", 5: "XL"}
