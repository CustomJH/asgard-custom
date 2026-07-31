"""기획 — 한 줄에서 시작해 문서 셋으로 끝나는 대화.

  한 줄 →  온보딩 문답  →  PRD  →  기능 명세서  →  유저 플로우

앞이 뒤의 입력이다. 그래서 순서를 건너뛸 수 없고, 건너뛰지 못하는 이유는 규칙이 아니라
**재료가 없기 때문**이다(`store.readiness`). 사람이 드는 것은 말 한 가지고, 구조는 이
계층이 조립한다 — 갈래와 상태를 고르고 항목끼리 손으로 잇는 일은 여기서 사라졌다.

  store    문서의 형상과 검사, 워크스페이스 정본(`<에이전트 홈>/studio/plans.json`)
  edits    손으로 고치는 연산 표 — 표에 없는 편집은 존재하지 않는다
  planner  모델과의 계약(짓기만 한다, 저장하지 않는다)
  build    지은 것을 문서에 앉히는 규칙 — 초안은 앉히고 수정은 제안한다

표면(창·CLI)은 `commands.plan_dashboard`가 진다. 이 패키지는 표면을 모른다.
"""

from .build import ask, converse, draft_flow, draft_prd, draft_spec, propose_section
from .edits import OPS, UnknownOp
from .edits import apply as apply_edit
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
    import_root,
    legacy_path,
    list_plans,
    load_plan,
    load_state,
    mutate,
    new_id,
    new_plan,
    next_step,
    pending_roots,
    project_store_path,
    readiness,
    require_ready,
    save_plan,
    set_phase,
    spec_tree,
    store_path,
    validate_plan,
)

__all__ = [
    "BLOCKED_TEXT",
    "CHAT_ROLES",
    "ITEM_STATUSES",
    "NODE_TYPES",
    "OPS",
    "PHASES",
    "PRD_SECTIONS",
    "PRD_SECTION_IDS",
    "PRIORITIES",
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
    "propose_section",
    "readiness",
    "require_ready",
    "save_plan",
    "set_phase",
    "spec_tree",
    "store_path",
    "validate_plan",
]
