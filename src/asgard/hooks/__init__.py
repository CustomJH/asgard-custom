"""Asgard hook library — the single home for hook code (grows as we add hooks).

Each `*.py` here is a REAL, standalone, stdlib-only script: runnable directly (`<hook-python> <file>`,
canonically `uv run --no-project python <file>` — see `platform.hook_python`) and
testable in isolation, with no escaping and no `asgard` import (it runs inside the *user's* repo). setup
scaffolds a hook by reading its source verbatim via `script(name)` — this package is the abstraction
boundary, so command/template code never embeds hook bodies as escaped strings.

Registry maps a logical hook name → module filename. Add a hook = drop a file here + one REGISTRY entry.

`asgard_hooklib/` is the shared substrate the bigger hooks stand on, and setup lays it down in the SAME
folder as the hooks (`library_files`). Deployment stays self-contained: a hook imports `asgard_hooklib`,
never `asgard`. Before that package existed the substrate was copy-pasted — 26-08-06 measurement: of 49
definitions shared by quest-log and verifier-gate, 9 had already drifted apart in meaning while both
files carried a "keep identical" comment."""

import os
import sys
from importlib import resources

LIBRARY = "asgard_hooklib"

# 라이브러리의 이름은 하나여야 한다. 훅은 배포 이름(`import asgard_hooklib`)으로 부르고, 저장소
# 안에서도 그 이름으로 서게 여기서 경로를 얹는다 — 안 그러면 `asgard.hooks.asgard_hooklib` 라는
# 두 번째 정체가 생기고, 시험이 그쪽을 패치하면 훅이 쓰는 쪽은 그대로라 패치가 조용히 빗나간다.
# 각 훅에도 같은 세 줄이 있다: 배포본에는 이 파일이 안 깔리기 때문이다.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

# logical name → filename (without .py). Each script is tool-agnostic: it auto-detects the hook
# protocol (Claude Code / Codex / Cursor) from the payload, so one file serves every tool.
REGISTRY: dict[str, str] = {
    "git-guard": "git_guard",  # Law 3/6 — Pre-shell (Claude/Codex exit2, Cursor permission JSON)
    "release-guard": "release_guard",  # 부작용 승인 — publish/이미지 push/태그 push/deploy 차단
    "readonly-guard": "readonly_guard",  # Trinity read-only roles — Bash allowlist
    "secret-guard": "secret_guard",  # Law 4 — Write/Edit (Claude/Codex)
    "failure-tracker": "failure_tracker",  # Law 9 — Post/failure, cross-tool shared .asgard/ state
    "quest-log": "quest_log",  # Trinity — 퀘스트 로그 + 전이 함수 CLI, 훅 아님
    "verifier-gate": "verifier_gate",  # Trinity — Canon 10 훅 강제, Stop 시점 diff-hash 물리 대조
    "write-sentinel": "write_sentinel",  # Trinity — Post-Write/Edit 기록, quest 미개설 write 우회 봉합
    "unattended-context": "unattended_context",  # Canon 8 — 무인 세션 감지·계약 주입
    "subagent-gate": "subagent_gate",  # Trinity — SubagentStop 역할 로그 규율 강제 (3클라이언트 공통)
    "craft-gate": "craft_gate",  # 미시 형상 래칫 — SubagentStop, 이 세션의 쓰기만 판정
    "style-gate": "style_gate",  # 저장소가 정한 코드 스타일 — Stop/SubagentStop, 안 들인 저장소는 무개입
    "budget-guard": "budget_guard",  # 소비 상한 — UserPromptSubmit/PreToolUse(Task), 쓰기 전 차단
    "tutor-note": "tutor_note",  # 되짚기 — Stop, 사용자에게 물음을 넘긴다 (막지 않는다)
    "lagom-activate": "lagom_activate",  # Lagom — SessionStart 모드 초기화·룰 주입
    "lagom-tracker": "lagom_tracker",  # Lagom — UserPromptSubmit 전환·영속·비활성·보상
    "lagom-subagent": "lagom_subagent",  # Lagom — SubagentStart 재주입, verifier 제외 (3클라이언트 공통)
    "memory-activate": "memory_activate",  # Memory v3 — SessionStart 스냅샷 주입 + Thinker 한정 SubagentStart
    "charter-activate": "charter_activate",  # Charter — 프로젝트 북극성 주입 (모드 B: Session/UserPrompt/Subagent)
    "manual-activate": "manual_activate",  # 커스텀 매뉴얼 — 오딘이 쓴 프로젝트 규칙 주입 (루트 MANUAL.md)
    "agent-activate": "agent_activate",  # 에인헤랴르 — 이 세션을 도는 에이전트의 정체성 주입 (배치 해석 포함)
    "map-activate": "map_activate",  # Project map — turn-start refresh + bounded role context
    "scope-activate": "scope_activate",  # 작업 형상·전문가 표면 — UserPromptSubmit/SubagentStart
    "verifier-context": "verifier_context",  # 판정자 입력 — SubagentStart, 하네스 관측 실행 기록 (메모리는 여전히 차단)
    "dispatch-context": "dispatch_context",  # 배차받은 쪽의 통로 — SubagentStart, 배차 주소·질문·실패 보고
    "siege-inbox": "siege_inbox",  # 배차 장부 우편함 — 이 세션 앞으로 온 메일을 턴 머리에 주입
    "hook-dispatch": "hook_dispatch",  # 주입 훅 묶음 실행 — 이벤트당 프로세스 하나 (가드·증거 훅 제외)
}


def script(name: str) -> str:
    """Return a hook's source text verbatim (to write into a user project). `name` is a REGISTRY key
    or a bare module name. Raises KeyError for an unknown logical name."""
    module = REGISTRY.get(name, name)
    return resources.files(__package__).joinpath(module + ".py").read_text(encoding="utf-8")


def library_files() -> list[tuple[str, str]]:
    """[(relative path under the hooks dir, source text)] for the shared library — scaffolded verbatim
    alongside the hooks.

    The path is relative on purpose: the three clients scaffold into different directories
    (`.claude/hooks/`, `.cursor/hooks/`, `.codex/hooks/`) and the library has to land next to the
    hooks in each of them, because that adjacency is what makes `import asgard_hooklib` resolve in a
    deployed copy (a script's own folder is `sys.path[0]`)."""
    base = resources.files(__package__).joinpath(LIBRARY)
    return sorted(
        (LIBRARY + "/" + entry.name, entry.read_text(encoding="utf-8"))
        for entry in base.iterdir()
        if entry.name.endswith(".py")
    )
