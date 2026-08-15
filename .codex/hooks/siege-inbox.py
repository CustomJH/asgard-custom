#!/usr/bin/env python3
# Asgard siege-inbox — 배차 장부의 우편함에서 이 세션 앞으로 온 메일을 턴 머리에 꽂는다.
#
# 호스트 세 모드(Claude Code·Cursor·Codex)에는 우편함을 훑는 자리가 없었다. 네이티브 루프는
# `agent/heimdall/bifrost/coordinator.py` 의 데몬 스레드가 훑지만, 호스트 모드는 그 루프가 없고
# 에이전트가 제 손으로 `asgard siege check` 를 칠 때만 메일을 읽었다. 그래서 다른 세션이나
# `siege serve` 가 보낸 답은 아무도 안 부르면 우편함에 그대로 남았다.
#
# 이 훅이 그 자리를 맡는다. 받는 이름은 코디네이터 이름 하나(`heimdall`)다 — 장부의 Run 이
# 이미 그 이름으로 열리므로(`orchestration/roster.py` 의 run_bind) 새 정체를 만들지 않는다.
#
# **주소를 안 적고 온 메일은 안 건드린다.** `--as` 를 준 조회는 그 이름 앞으로 온 것만 잡으므로,
# 코디네이터가 나중에 `siege check` 로 받을 메일을 이 훅이 먼저 접는 일이 없다.
#
# 무엇을 먼저 하느냐가 이 훅의 요지다. 매 프롬프트마다 CLI 를 띄우면 그 기동 시간이 그대로
# 지연이 된다. 그래서 먼저 stdlib sqlite3 로 읽기 전용 조회 한 번을 하고, 받을 것이 있을 때만
# CLI 를 부른다. 우편함이 비어 있는 보통의 턴에서는 조회 하나로 끝난다.
#
# fail-open: 장부 부재·파손·CLI 부재·시간 초과는 전부 무개입 통과 (exit 0).
import json
import os
import sqlite3
import sys

_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.firing import run  # noqa: E402
from asgard_hooklib.inject import client, emit_context  # noqa: E402
from asgard_hooklib.siege import ledger_read  # noqa: E402

# 호스트 세션이 답하는 이름. `run_bind` 가 Run 을 여는 coordinator 이름과 같은 값이라,
# 보내는 쪽은 `--recipient heimdall` 하나만 알면 된다.
INBOX_NAME = "heimdall"
CAP = 5  # 한 턴에 꽂을 메일 수 — 넘치면 남는 것은 다음 턴에 다시 온다
BODY_CAP = 1200
SUBJECT_CAP = 120


def event(data):
    raw = str(data.get("hook_event_name") or "")
    return {
        "sessionStart": "SessionStart",
        "beforeSubmitPrompt": "UserPromptSubmit",
        "subagentStart": "SubagentStart",
    }.get(raw, raw or "UserPromptSubmit")


def pending_run(root):
    """이 이름 앞으로 미확인 메일이 있는 열린 Run — 없으면 빈 문자열.

    읽기 전용 URI 로 연다. 훅이 장부 파일을 새로 만들거나 쓰기 잠금을 잡으면, 정작 일하는
    쪽(코디네이터·serve)이 그 잠금을 기다린다.
    """
    db = os.path.join(root, ".asgard", "orchestration.db")
    if not os.path.exists(db):
        return ""
    conn = None
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db.replace("?", "%3f"), uri=True, timeout=0.5)
        row = conn.execute(
            "SELECT m.run_id FROM messages m JOIN runs r ON r.id=m.run_id"
            " WHERE r.status='open' AND m.recipient=? AND m.acked_at IS NULL"
            " ORDER BY m.created_at LIMIT 1",
            (INBOX_NAME,),
        ).fetchone()
        return str(row[0]) if row else ""
    except Exception:
        return ""
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def render(run_id, messages):
    """받은 메일을 그대로 보여 준다 — 요약하지 않는다. 판단은 읽는 쪽이 한다."""
    lines = [
        '<asgard-inbox run="%s">' % run_id,
        "배차 장부 우편함에 이 세션 앞으로 온 메일이다. 답할 것이 있으면 "
        '`asgard siege send %s status --recipient <보낸 쪽> --body "..."` 로 보낸다.' % run_id,
    ]
    for message in messages[:CAP]:
        sender = str(message.get("sender") or "(이름 없음)")
        subject = str(message.get("subject") or "")[:SUBJECT_CAP]
        body = str(message.get("body") or "")[:BODY_CAP]
        lines.append("")
        lines.append("- from %s · %s · %s" % (sender, message.get("type") or "status", subject))
        if body:
            lines.append("  %s" % body.replace("\n", "\n  "))
    if len(messages) > CAP:
        lines.append("")
        lines.append("… %d건이 더 있다 (`asgard siege check %s --as %s`)." % (len(messages) - CAP, run_id, INBOX_NAME))
    lines.append("</asgard-inbox>")
    return "\n".join(lines)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    try:
        root = (
            os.environ.get("CLAUDE_PROJECT_DIR")
            or os.environ.get("CURSOR_PROJECT_DIR")
            or data.get("cwd")
            or os.getcwd()
        )
        run_id = pending_run(root)
        if not run_id:
            sys.exit(0)  # 보통의 턴 — 조회 하나로 끝난다
        found = ledger_read(root, ["check", run_id, "--as", INBOX_NAME])
        if not isinstance(found, dict) or not found.get("count"):
            sys.exit(0)
        emit_context(client(), render(run_id, found.get("messages") or []), event(data))
        # 주입한 뒤에 확인 처리한다. 순서를 뒤집으면 주입이 실패한 턴의 메일이 사라지고,
        # 이 순서면 최악이 같은 메일을 다음 턴에 한 번 더 보는 것이다.
        delivery = str(found.get("delivery_id") or "")
        if delivery:
            ledger_read(root, ["check", run_id, "--as", INBOX_NAME, "--ack", delivery])
    except Exception:
        pass  # fail-open — 어떤 실패도 세션을 막지 않는다
    sys.exit(0)


if __name__ == "__main__":
    run("siege-inbox", main)
