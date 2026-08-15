"""컨텍스트 주입의 와이어 포맷 — 호스트가 무엇을 읽는가.

주입 훅 아홉이 각자 이 JSON 리터럴을 손으로 적고 있었고, 아홉 개 주석이 전부 "동일 유지
(단일 규약)"이라고 적혀 있었다. 실제로는 같지 않았다 — 한 훅만 codex 분기가 있었고, 한 훅은
평문에만 개행을 붙였다. 스키마 오타는 조용히 죽는 종류다 (호스트가 파싱에 실패하면 그 주입은
없던 일이 되고 훅 계약은 fail-open 이다).

그래서 **스키마는 여기, 정책은 훅에** 둔다. 아래 네 함수가 와이어 포맷이고, `emit_context` 는
그중 일곱 훅이 실제로 쓰는 조합이다. Cursor 의 beforeSubmitPrompt 처럼 컨텍스트 통로 자체가
없는 자리(budget-guard·lagom-tracker)는 자기 정책을 자기 파일에 그대로 두고 이 조각들만 쓴다 —
그 차이는 드리프트가 아니라 호스트가 강제한 것이라서 한 함수로 접으면 오히려 사라진다.
"""

from __future__ import annotations

import json
import sys

CLIENTS = {"claude-code", "codex", "cursor"}
# `hookSpecificOutput` 로 받는 이벤트 — 나머지(SessionStart)는 평문 stdout 이 곧 주입이다.
JSON_EVENTS = {"UserPromptSubmit", "SubagentStart"}


def client() -> str:
    """배선이 첫 인자로 넘긴 호스트 이름. 모르는 값은 claude-code 로 (fail-open — 오타 하나가
    주입 계층을 통째로 끄지 않게)."""
    raw = str(sys.argv[1] if len(sys.argv) > 1 else "claude-code")
    return raw if raw in CLIENTS else "claude-code"


def cursor_context(text: str) -> None:
    """Cursor 의 컨텍스트 주입 — 이 키 하나가 통로다."""
    sys.stdout.write(json.dumps({"additional_context": text}, ensure_ascii=False) + "\n")


def cursor_message(text: str) -> None:
    """Cursor 의 사람 표면 — 컨텍스트가 아니라 사용자에게 보이는 문장이다."""
    sys.stdout.write(json.dumps({"user_message": text}, ensure_ascii=False) + "\n")


def host_context(event: str, text: str) -> None:
    """Claude Code·Codex 의 구조화 주입. 이벤트 이름이 틀리면 호스트가 그대로 버린다."""
    sys.stdout.write(
        json.dumps(
            {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
            ensure_ascii=False,
        )
        + "\n"
    )


def emit_context(current_client: str, text: str, event: str = "SessionStart") -> None:
    """주입 한 건 — 스키마는 (호스트, 이벤트)가 정한다.

    `event` 는 이 훅이 매달린 자리를 그대로 적는다. SessionStart 는 평문 stdout 이 주입 통로라
    JSON 을 쓰지 않고, UserPromptSubmit·SubagentStart 는 구조화 출력을 쓴다."""
    if current_client == "cursor":
        cursor_context(text)
    elif event in JSON_EVENTS:
        host_context(event, text)
    else:
        sys.stdout.write(text)
