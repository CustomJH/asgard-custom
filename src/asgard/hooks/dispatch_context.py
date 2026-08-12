#!/usr/bin/env python3
# Asgard dispatch-context — 배차받은 에이전트에게 자기 배차의 주소와 두 통로를 준다 (SubagentStart).
#
# 네이티브 루프에서 워커는 두 가지를 할 수 있다. 막히면 `ask_coordinator` 로 묻고
# (agent/heimdall/bifrost/coordinator.py 의 데몬 스레드가 답한다), 실패로 끝나면 그 실패가
# 장부에 `failed` 로 적힌다 (bifrost.settle_turn). 호스트 모드(Claude Code·Cursor·Codex)에는
# 그 두 길이 없었다. 워커 계약(templates/roles/asgard-worker.md)이 `ask_coordinator` 를
# "native only" 로 못박고, SubagentStop 의 자동 접기는 결과를 언제나 `succeeded` 로 적는다
# (commands/siege_act.run_unnote). 그래서 호스트 모드의 장부는 실패한 배차를 성공으로 적고,
# 막힌 워커는 아무 데도 못 묻는다.
#
# 이 훅이 그 둘을 CLI 로 준다. 블로킹 질문은 안 준다 — 호스트 모드에서 코디네이터는
# 서브에이전트가 돌아올 때까지 자기 턴 안에 갇혀 있어서 답할 수 없고, `run_ask` 도크스트링이
# 같은 이유로 기다림을 기본값에서 뺐다. 대신 Canon 8 의 형태로 준다: 질문을 장부에 남기고,
# 가정을 밝히고, 진행한다. 코디네이터는 반환 뒤 `siege blocked` 로 읽는다.
#
# 판정자는 대상이 아니다. 그 자리는 verifier-context 가 쓰고, 판정자의 결론은 verdict 로 이미
# 장부에 간다 (subagent_gate._role_summary). 판정자에게 배차를 접는 손잡이를 주면 자기 판정의
# 대상인 Run 을 스스로 정산하게 된다.
#
# Fail-open + stdlib-only: 주입이 실패해서 배차가 죽으면 본말전도라 어떤 오류든 조용히 exit 0.
import json
import os
import sqlite3
import sys

_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.firing import run  # noqa: E402
from asgard_hooklib.inject import client, emit_context  # noqa: E402
from asgard_hooklib.session import active_quest  # noqa: E402

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 주입이 통째로 증발한다. UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용
    except Exception:
        pass

# 이 훅이 말을 거는 상대 — 배차로 뜨는 Asgard 역할 전부에서 판정자만 뺀다. 목록이 아니라
# 접두사로 고르는 이유는 배포 주기다: 역할이 하나 늘 때마다 훅을 고쳐야 하면, 안 고친 사이에
# 새 역할만 통로 없이 돈다.
PREFIX = "asgard-"
EXCLUDED = frozenset({"asgard-verifier"})


def agent(data: dict) -> str:
    """이 SubagentStart 가 띄우는 에이전트 이름 — 호스트마다 필드가 다르다."""
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    return str(
        data.get("agent_type")
        or data.get("agent_name")
        or data.get("subagent_type")
        or tool_input.get("agent_type")
        or tool_input.get("subagent_type")
        or ""
    )


def open_run(root: str, qid: str) -> str:
    """이 퀘스트의 열린 Run id — 없거나 못 읽으면 빈 문자열.

    `board.run_bind` 와 같은 줄을 읽는다 (퀘스트당 열린 Run 은 하나라는 것이 그쪽 유니크
    인덱스가 지키는 불변식이다). 여기서 만들지는 않는다: Run 을 세우는 것은 배차를 세우는
    쪽의 일이고(hooks/subagent_gate.siege_open), 주입이 장부에 행을 남기면 뜨지 못한
    호출까지 Run 을 얻는다.

    읽기 전용으로 연다. 배차 길목이라 쓰기 잠금을 기다리는 값이 배차마다 얹히면 안 된다.
    """
    path = os.path.join(root, ".asgard", "orchestration.db")
    if not os.path.exists(path):
        return ""
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=0.5)
    except Exception:
        return ""
    try:
        row = conn.execute(
            "SELECT id FROM runs WHERE quest_id=? AND status='open' ORDER BY created_at DESC LIMIT 1",
            (qid,),
        ).fetchone()
    except Exception:
        return ""
    finally:
        conn.close()
    return str(row[0]) if row else ""


def render(name: str, qid: str, run_id: str) -> str:
    """배차받은 쪽이 읽을 블록 — 이 배차의 주소와, 그 주소로 부를 수 있는 명령."""
    lines = [
        "<asgard-dispatch>",
        "You are a dispatched agent. This attempt is on the dispatch ledger, and the coordinator",
        "reads it after you return — what you leave there is what it knows about your run.",
        "",
        "  quest  %s" % qid,
        "  agent  %s" % name,
    ]
    if run_id:
        lines.append("  run    %s" % run_id)
        lines += [
            "",
            "Blocked on a decision that is not yours — a scope boundary, a conflict with another",
            "unit's files, an ambiguity in the assignment? Leave the question on the ledger and",
            "carry on under a stated assumption. Do not wait for an answer and do not end your turn",
            "on one: the coordinator is inside its own turn until you return, so nobody can answer",
            "while you run (Canon 8).",
            '  asgard siege ask %s "<question>" --sender %s' % (run_id, name),
            "Record the assumption you took as a `가정:` line in your summary. This is for decisions",
            "only — facts you can read, you read.",
        ]
    lines += [
        "",
        "Did not reach the goal? Say so before you return. An attempt that reports nothing is",
        "recorded as succeeded, and a silent failure is one the coordinator cannot see:",
        '  asgard siege done --quest %s --agent %s --outcome failed --body "<what stopped you>"' % (qid, name),
        "Report it once. Reporting a success is not needed — that is what returning already means.",
        "</asgard-dispatch>",
    ]
    return "\n".join(lines)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        name = agent(data)
        if not name.startswith(PREFIX) or name in EXCLUDED:
            sys.exit(0)
        root = os.environ.get("CLAUDE_PROJECT_DIR") or str(data.get("cwd") or "") or os.getcwd()
        qid = active_quest(root, str(data.get("session_id") or "") or None)
        if not qid:
            sys.exit(0)  # 퀘스트가 없으면 장부에 이 배차의 자리도 없다
        emit_context(client(), render(name, qid, open_run(root, qid)), "SubagentStart")
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    run("dispatch-context", main)
