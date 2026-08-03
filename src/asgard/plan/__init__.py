"""기획 — 한 줄에서 시작해 문서 셋으로 끝나는 대화.

  한 줄 →  온보딩 문답  →  PRD  →  기능 명세서  →  유저 플로우

앞이 뒤의 입력이다. 그래서 순서를 건너뛸 수 없고, 건너뛰지 못하는 이유는 규칙이 아니라
**재료가 없기 때문**이다(`store.readiness`). 사람이 드는 것은 말 한 가지고, 구조는 이
계층이 조립한다 — 갈래와 상태를 고르고 항목끼리 손으로 잇는 일은 여기서 사라졌다.

  store    문서의 형상과 검사, 워크스페이스 정본(`<에이전트 홈>/studio/plans.json`)
  edits    손으로 고치는 연산 표 — 표에 없는 편집은 존재하지 않는다
  planner  모델과의 계약(짓기만 한다, 저장하지 않는다)
  build    지은 것을 문서에 앉히는 규칙 — 초안은 앉히고 수정은 제안한다
  review   PRD 심사 — 모델 없이 잴 수 있는 것만. 점수는 보여 줄 뿐 뒤 문서를 막지 않는다
  export   PRD 한 장을 마크다운으로 — 창 밖으로 나가는 형식

표면(창·CLI)은 `commands.plan_api`가 진다. 이 패키지는 표면을 모른다.
"""

from .build import (
    ask,
    converse,
    draft_flow,
    draft_prd,
    draft_spec,
    propose_document,
    propose_section,
    propose_selection,
)
from .edits import OPS, UnknownOp
from .edits import apply as apply_edit
from .export import to_markdown
from .folders import import_root, pending_roots
from .intake import INTAKE_AXES, INTAKE_STAGES

# `plan.review` 는 이 줄 뒤로 **함수**다 — 같은 이름의 모듈을 가린다. 모듈 안의 다른 값이
# 필요하면 `from .review import ...` 처럼 모듈에서 직접 들여온다.
from .review import GRADE_LABEL, GRADES, REVIEW_CHECKS, review
from .store import (
    BLOCKED_TEXT,
    CHAT_ROLES,
    ITEM_STATUSES,
    NODE_TYPES,
    PHASES,
    PRD_SECTION_IDS,
    PRD_SECTIONS,
    PRIORITIES,
    SCHEMA_VERSION,
    SPEC_LEVELS,
    PlanNotReady,
    RevisionConflict,
    append_chat,
    create_plan,
    delete_plan,
    legacy_path,
    list_plans,
    load_plan,
    load_state,
    mutate,
    new_id,
    new_plan,
    next_step,
    project_store_path,
    readiness,
    require_ready,
    save_plan,
    set_engine,
    set_mode,
    set_phase,
    spec_tree,
    store_path,
    validate_plan,
)

__all__ = [
    "BLOCKED_TEXT",
    "CHAT_ROLES",
    "GRADES",
    "GRADE_LABEL",
    "INTAKE_AXES",
    "INTAKE_STAGES",
    "ITEM_STATUSES",
    "NODE_TYPES",
    "OPS",
    "PHASES",
    "PRD_SECTIONS",
    "PRD_SECTION_IDS",
    "PRIORITIES",
    "REVIEW_CHECKS",
    "SCHEMA_VERSION",
    "SPEC_LEVELS",
    "PlanNotReady",
    "RevisionConflict",
    "UnknownOp",
    "append_chat",
    "apply_edit",
    "ask",
    "converse",
    "create_plan",
    "delete_plan",
    "draft_flow",
    "draft_prd",
    "draft_spec",
    "import_root",
    "legacy_path",
    "list_plans",
    "load_plan",
    "load_state",
    "mutate",
    "new_id",
    "new_plan",
    "next_step",
    "pending_roots",
    "project_store_path",
    "propose_document",
    "propose_section",
    "propose_selection",
    "readiness",
    "require_ready",
    "review",
    "save_plan",
    "set_engine",
    "set_mode",
    "set_phase",
    "spec_tree",
    "store_path",
    "to_markdown",
    "validate_plan",
]
