"""Cursor templates: the always-apply rule bridge + the hooks manifest + skeleton folder READMEs.
The hook SCRIPTS live in `asgard.hooks` (cursor_git_guard / cursor_failure_tracker); this file only
emits config that points at them."""

import json

from ..platform import hook_python
from .agent_models import agent_model
from .roles import role_document

_CURSOR_RULE = """\
---
description: Canonical project instructions (Asgard)
alwaysApply: true
---

Follow the canonical project instructions in `AGENTS.md` at the repo root.
"""

CURSOR_FOLDERS = [
    (
        "skills",
        "Skills — each in `<name>/SKILL.md`; frontmatter: name, description, paths.\nDocs: https://cursor.com/docs/context/commands",
    ),
    (
        "agents",
        "Project subagents — one `.md` each; frontmatter: name, description, model, readonly.\nDocs: https://cursor.com/docs/subagents",
    ),
    (
        "hooks",
        "Hook scripts, wired from `.cursor/hooks.json` (events: beforeShellExecution, postToolUseFailure, …).\nDocs: https://cursor.com/docs/hooks",
    ),
]


def cursor_rule() -> str:
    return _CURSOR_RULE


def cursor_agent(content: str, root: str) -> str:
    """Adapt the canonical Claude-compatible role file to Cursor's agent schema."""
    metadata, body = role_document(content)
    model = agent_model(root, "cursor", metadata["name"])["model"]
    readonly = "Write" not in str(metadata.get("tools") or "")
    return (
        "---\n"
        f"name: {metadata['name']}\n"
        f"description: {json.dumps(str(metadata['description']), ensure_ascii=False)}\n"
        f"model: {json.dumps(model)}\n"
        f"readonly: {str(readonly).lower()}\n"
        "---\n\n" + body
    )


def cursor_hooks_json() -> str:
    # Project hooks run from repo root and load only in a trusted workspace (cursor.com/docs/hooks).
    py = hook_python()
    return (
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    # 주입 계층(lagom·charter·무인 계약)은 sessionStart 에 모인다 — Cursor 의
                    # beforeSubmitPrompt 는 컨텍스트 주입 통로가 없다 (cursor.com/docs/hooks,
                    # 26-07-27 확인: 출력이 continue/user_message 뿐).
                    "sessionStart": [
                        {"command": f"{py} .cursor/hooks/lagom-activate.py cursor"},
                        {"command": f"{py} .cursor/hooks/memory-activate.py cursor"},
                        {"command": f"{py} .cursor/hooks/charter-activate.py cursor"},
                        {"command": f"{py} .cursor/hooks/manual-activate.py cursor"},
                        {"command": f"{py} .cursor/hooks/agent-activate.py cursor"},
                        {"command": f"{py} .cursor/hooks/map-activate.py cursor"},
                        {"command": f"{py} .cursor/hooks/unattended-context.py cursor"},
                    ],
                    "beforeSubmitPrompt": [
                        # 소비 상한 — 주입 통로는 없지만 차단(continue:false)은 된다.
                        {"command": f"{py} .cursor/hooks/budget-guard.py cursor prompt"},
                        {"command": f"{py} .cursor/hooks/lagom-tracker.py cursor"},
                        {"command": f"{py} .cursor/hooks/memory-activate.py cursor"},
                        {"command": f"{py} .cursor/hooks/map-activate.py cursor"},
                        # 되짚기의 앞쪽 절반 — 주입 통로가 없어도 `user_message` 로 **사용자에게**는
                        # 닿는다. 원래 모델에 넣지 않을 층이라 이 제약이 여기서는 제약이 아니다.
                        {"command": f"{py} .cursor/hooks/tutor-note.py cursor brief"},
                    ],
                    "beforeShellExecution": [
                        # Canon 4 읽기 절반 — shell 우회 credential 덤프 차단
                        {"command": f"{py} .cursor/hooks/secret-guard.py cursor"},
                        {"command": f"{py} .cursor/hooks/git-guard.py"},
                        {"command": f"{py} .cursor/hooks/release-guard.py"},
                        {"command": f"{py} .cursor/hooks/readonly-guard.py cursor"},
                    ],
                    "preToolUse": [
                        {
                            "matcher": "Task",
                            "command": f"{py} .cursor/hooks/budget-guard.py cursor task",
                        },
                        {
                            "matcher": "Task",
                            "command": f"{py} .cursor/hooks/subagent-gate.py pre",
                        },
                        {
                            "matcher": "Task",
                            "command": f"{py} .cursor/hooks/memory-activate.py cursor",
                        },
                        {
                            "matcher": "Task",
                            "command": f"{py} .cursor/hooks/map-activate.py cursor",
                        },
                        # Canon 4 + 통제 표면 보호 — 판정에 역할 신원이 필요 없는 규율만 여기서 돈다
                        # (preToolUse 페이로드엔 agent_type 이 없다; 읽기전용 역할은 에이전트
                        # 프론트매터 `readonly: true` 가 네이티브로 막는다).
                        {
                            "matcher": "Write|Edit|Delete",
                            "command": f"{py} .cursor/hooks/readonly-guard.py cursor",
                        },
                        {
                            "matcher": "Write|Edit|Delete",
                            "command": f"{py} .cursor/hooks/secret-guard.py cursor",
                        },
                        # Canon 4 읽기 절반 — 자격 저장소는 이름만으로 판정 (읽은 뒤엔 늦다)
                        {
                            "matcher": "Read|Grep|Glob",
                            "command": f"{py} .cursor/hooks/secret-guard.py cursor",
                        },
                    ],
                    "subagentStart": [
                        {
                            "matcher": "^asgard-(thinker|worker|verifier)$",
                            "command": f"{py} .cursor/hooks/subagent-gate.py start",
                        },
                        {"command": f"{py} .cursor/hooks/lagom-subagent.py cursor"},
                        {"command": f"{py} .cursor/hooks/charter-activate.py cursor"},
                        {"command": f"{py} .cursor/hooks/manual-activate.py cursor"},
                        {"command": f"{py} .cursor/hooks/agent-activate.py cursor"},
                        {"command": f"{py} .cursor/hooks/map-activate.py cursor"},
                    ],
                    "subagentStop": [
                        {
                            "matcher": "^asgard-(thinker|worker|verifier)$",
                            "command": f"{py} .cursor/hooks/subagent-gate.py stop",
                        },
                        # 미시 형상 래칫 — 매처 없음: 규율은 역할이 아니라 쓴 코드를 따라간다
                        {"command": f"{py} .cursor/hooks/craft-gate.py cursor"},
                    ],
                    "postToolUse": [
                        {
                            "matcher": "Write|Edit|Delete",
                            "command": f"{py} .cursor/hooks/write-sentinel.py cursor",
                        }
                    ],
                    "stop": [
                        {"command": f"{py} .cursor/hooks/verifier-gate.py cursor"},
                        {"command": f"{py} .cursor/hooks/memory-activate.py cursor"},
                        {"command": f"{py} .cursor/hooks/map-activate.py cursor"},
                        {"command": f"{py} .cursor/hooks/tutor-note.py cursor"},
                    ],
                    "postToolUseFailure": [{"command": f"{py} .cursor/hooks/failure-tracker.py"}],
                },
            },
            indent=2,
        )
        + "\n"
    )
