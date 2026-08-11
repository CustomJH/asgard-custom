"""memory 커맨드 — 개인 위키(LLM Wiki) 운영면. 로직은 asgard.memory, 여기는 표면만.

승인 게이트: ingest는 계획(create/merge 대상)을 먼저 보여주고 확인받은 뒤, **그 동일
계획을 그대로** 실행에 넘긴다 (TOCTOU 차단 — 승인 대상과 실행 대상이 갈라지지 않음).
비대화형(파이프·CI)에서는 --yes 없이는 저장하지 않는다.

모든 run_*는 예외를 안정적인 종료 코드(사용자 메시지 + 1)로 변환한다 — traceback 노출 금지.

명령 본문은 표면별 모듈이 지고 이 파일은 그것들을 다시 내보낸다: `from asgard.commands.memory
import run_ingest` 가 파일 하나였을 때와 똑같이 닿아야 한다. 계획 선점 헬퍼와 `memory` 자체도
같이 내보낸다 — 시험이 이 모듈의 속성으로 쥔다."""

from ... import memory
from ._core import (
    PERSONAL_CLAIM_LEASE_SECONDS,
    _claim_plan,
    _claimed_path,
    _finish_plan,
    _pending_dir,
    _save_plan,
)
from .autosave import (
    run_autosave,
    run_sync_turn,
)
from .backends import (
    _semantic_nudge_line,
    run_connect,
    run_mcp,
    run_provider,
    run_semantic,
    run_tick,
)
from .evolution import (
    run_ask,
    run_backup,
    run_norn,
    run_norn_restore,
    run_pattern,
    run_sync,
)
from .hygiene import (
    run_contradiction_seen,
    run_contradictions,
    run_lint,
    run_proposals,
)
from .personal import (
    run_add,
    run_approve,
    run_discard,
    run_episodes,
    run_export_okf,
    run_ingest,
    run_merge,
    run_obsidian,
    run_path,
    run_query,
    run_recall,
    run_reindex,
    run_remove,
    run_show,
    run_snapshot,
)
from .project import (
    run_project_approve,
    run_project_evolve,
    run_project_ingest,
    run_project_learn,
    run_project_recall,
    run_project_reflect,
    run_project_rehydrate,
    run_project_retain,
    run_project_scan,
    run_project_sync,
)

__all__ = [
    "memory",
    "PERSONAL_CLAIM_LEASE_SECONDS",
    "_pending_dir",
    "_save_plan",
    "_claim_plan",
    "_claimed_path",
    "_finish_plan",
    "_semantic_nudge_line",
    "run_add",
    "run_approve",
    "run_ask",
    "run_autosave",
    "run_backup",
    "run_connect",
    "run_contradiction_seen",
    "run_contradictions",
    "run_discard",
    "run_episodes",
    "run_export_okf",
    "run_ingest",
    "run_lint",
    "run_mcp",
    "run_merge",
    "run_norn",
    "run_norn_restore",
    "run_obsidian",
    "run_path",
    "run_pattern",
    "run_project_approve",
    "run_project_evolve",
    "run_project_ingest",
    "run_project_learn",
    "run_project_recall",
    "run_project_reflect",
    "run_project_rehydrate",
    "run_project_retain",
    "run_project_scan",
    "run_project_sync",
    "run_proposals",
    "run_provider",
    "run_query",
    "run_recall",
    "run_reindex",
    "run_remove",
    "run_semantic",
    "run_show",
    "run_snapshot",
    "run_sync",
    "run_sync_turn",
    "run_tick",
]
