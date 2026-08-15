"""memory 커맨드 — 개인 위키(LLM Wiki) 운영면. 로직은 asgard.memory, 여기는 표면만.

승인 게이트: ingest는 계획(create/merge 대상)을 먼저 보여주고 확인받은 뒤, **그 동일
계획을 그대로** 실행에 넘긴다 (TOCTOU 차단 — 승인 대상과 실행 대상이 갈라지지 않음).
비대화형(파이프·CI)에서는 --yes 없이는 저장하지 않는다.

모든 run_*는 예외를 안정적인 종료 코드(사용자 메시지 + 1)로 변환한다 — traceback 노출 금지.

명령 본문은 표면별 모듈이 지고 이 파일은 그것들을 다시 내보낸다: `from asgard.commands.memory
import run_ingest` 가 파일 하나였을 때와 똑같이 닿아야 한다. 계획 선점 헬퍼와 `memory` 자체도
같이 내보낸다 — 시험이 이 모듈의 속성으로 쥔다.

**이름을 물을 때 그 모듈만 등록한다** (`cli/__init__.py` 의 `__getattr__` 과 같은 형태). 일곱을
한꺼번에 임포트하면 `asgard memory snapshot` 하나가 `autosave`·`project` 를 타고
`asgard.project_memory`·`asgard.memory_bridge` 까지 끌고 온다 — 그 둘은 개인 메모리 스냅샷이
쓰지 않는다. 26-08-14 실측: `import asgard.project_memory` 가 새 인터프리터의 RSS 를 7.5MB
올리고, `memory-activate` 훅(SessionStart)이 그 값을 매 세션 낸다. `memory recall` 처럼 실제로
프로젝트 메모리를 읽는 명령은 `memory_context` 를 거쳐 그대로 임포트하므로 달라지지 않는다."""

from importlib import import_module
from typing import Any

# 공개 이름 → 그 이름을 정의한 모듈. `memory` 만 패키지 바깥(`asgard.memory`)을 가리킨다.
_SOURCE: dict[str, str] = {
    name: module
    for module, names in {
        "_core": (
            "PERSONAL_CLAIM_LEASE_SECONDS",
            "_claim_plan",
            "_claimed_path",
            "_finish_plan",
            "_pending_dir",
            "_save_plan",
        ),
        "autosave": ("run_autosave", "run_sync_turn"),
        "backends": (
            "_semantic_nudge_line",
            "run_connect",
            "run_mcp",
            "run_provider",
            "run_semantic",
            "run_tick",
        ),
        "evolution": ("run_ask", "run_backup", "run_norn", "run_norn_restore", "run_pattern", "run_sync"),
        "hygiene": ("run_contradiction_seen", "run_contradictions", "run_lint", "run_proposals"),
        "personal": (
            "run_add",
            "run_approve",
            "run_discard",
            "run_episodes",
            "run_export_okf",
            "run_ingest",
            "run_merge",
            "run_obsidian",
            "run_path",
            "run_query",
            "run_recall",
            "run_reindex",
            "run_remove",
            "run_show",
            "run_snapshot",
        ),
        "project": (
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
        ),
    }.items()
    for name in names
}


def __getattr__(name: str) -> Any:
    """이름 하나를 정의한 모듈까지만 등록해서 그 값을 돌려준다 (PEP 562).

    돌려준 값을 이 모듈의 전역에 적어 둔다 — 두 번째 조회부터는 `__getattr__` 이 아예 안 불리고,
    `mock.patch("asgard.commands.memory.run_tick")` 이 원래 값을 되돌릴 자리도 예전과 같아진다."""
    if name == "memory":
        value: Any = import_module("...memory", __name__)
    else:
        module = _SOURCE.get(name)
        if module is None:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value


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
