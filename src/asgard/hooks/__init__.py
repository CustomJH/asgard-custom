"""Asgard hook library — the single home for hook code (grows as we add hooks).

Each `*.py` here is a REAL, standalone, stdlib-only script: runnable directly (`python3 <file>`) and
testable in isolation, with no escaping and no `asgard` import (it runs inside the *user's* repo). setup
scaffolds a hook by reading its source verbatim via `script(name)` — this package is the abstraction
boundary, so command/template code never embeds hook bodies as escaped strings.

Registry maps a logical hook name → module filename. Add a hook = drop a file here + one REGISTRY entry."""

from importlib import resources

# logical name → filename (without .py). Each script is tool-agnostic: it auto-detects the hook
# protocol (Claude Code / Codex / Cursor) from the payload, so one file serves every tool.
REGISTRY: dict[str, str] = {
    "git-guard": "git_guard",  # Law 3/6 — Pre-shell (Claude/Codex exit2, Cursor permission JSON)
    "secret-guard": "secret_guard",  # Law 4 — Write/Edit (Claude/Codex)
    "failure-tracker": "failure_tracker",  # Law 9 — Post/failure, cross-tool shared .asgard/ state
    "quest-log": "quest_log",  # Trinity — 퀘스트 로그 + 전이 함수 CLI (CUS-118/120), 훅 아님
    "verifier-gate": "verifier_gate",  # Trinity — Canon 10 훅 강제, Stop 시점 diff-hash 물리 대조 (CUS-122)
    "write-sentinel": "write_sentinel",  # Trinity — Post-Write/Edit 기록, quest 미개설 write 우회 봉합
    "unattended-context": "unattended_context",  # Canon 8 — 무인 세션 감지·계약 주입 (CUS-169)
    "subagent-gate": "subagent_gate",  # Trinity — SubagentStop 역할 로그 규율 강제 (CC 전용, CUS-197)
    "lagom-activate": "lagom_activate",  # Lagom — SessionStart 모드 초기화·룰 주입 (CUS-208)
    "lagom-tracker": "lagom_tracker",  # Lagom — UserPromptSubmit 전환·영속·비활성·보상 (CUS-213)
    "lagom-subagent": "lagom_subagent",  # Lagom — SubagentStart 재주입, verifier 제외 (CC 전용, CUS-214)
    "memory-activate": "memory_activate",  # Memory v3 — SessionStart 스냅샷 주입 + Thinker 한정 SubagentStart
}


def script(name: str) -> str:
    """Return a hook's source text verbatim (to write into a user project). `name` is a REGISTRY key
    or a bare module name. Raises KeyError for an unknown logical name."""
    module = REGISTRY.get(name, name)
    return resources.files(__package__).joinpath(module + ".py").read_text(encoding="utf-8")
