"""role — Trinity 역할 브릿지 CLI (claude-code / codex / cursor → 배치 provider 위임).

호스트 도구가 자기 내부 모델 대신 `[trinity.<role>]` 배치 provider 로 역할 턴을 실행할 때
부른다 (asgard-provider 스킬이 안내). 퀘스트 로그 기록은 CLI 가 수행 — 프로토콜 준수가 모델 순응이
아니라 코드 경로다 (네이티브 루프와 같은 원칙, heimdall.py 참조). 게이트 판정은 그대로
verifier-gate 몫. `[bridge]` 게이트 판단은 호스트 몫 — 이 CLI 는 사실(list)과 실행(run)만.
"""

import json
import os
import sys
from typing import Callable

from ..providers import TRINITY_ROLES, bridge_flags, resolve, resolve_trinity


def run_role_list() -> int:
    root = os.getcwd()
    default = resolve(root)
    out = {
        "bridge": bridge_flags(root),
        "roles": {
            r: {"provider": rp.profile.name, "model": rp.model, "placed": rp is not default, "missing": rp.missing}
            for r, rp in resolve_trinity(root, default).items()
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def run_role_run(role: str, task: str) -> int:
    from ..agent.heimdall import VERDICT_TOOL, _record_writes, _role_prompt
    from ..agent.session import AgentSession, make_client, ql

    root = os.getcwd()
    if role not in TRINITY_ROLES:
        print(json.dumps({"error": f"role 은 {'/'.join(TRINITY_ROLES)} 중 하나"}), file=sys.stderr)
        return 2
    sid = os.environ.get("CLAUDE_SESSION_ID") or "bridge"
    try:
        state = json.loads(ql(root, "state", session=sid).stdout or "{}")
    except Exception:
        state = {}
    if not state.get("quest_id"):
        print(json.dumps({"error": "활성 quest 없음 — 호스트가 먼저 quest-log open 을 실행해야 한다"}), file=sys.stderr)
        return 1

    default = resolve(root)
    rrp = resolve_trinity(root, default)[role]
    if rrp.missing:
        print(json.dumps({"error": f"[trinity.{role}] 미충족: " + "; ".join(rrp.missing)}), file=sys.stderr)
        return 1

    criteria = state.get("criteria") or []
    level = "full" if state.get("full_required") else "micro"  # gate 와 동일 기준 (결정론 도출)
    extra: list[dict] | None = None
    handlers: dict[str, Callable[[dict], str]] | None = None
    if role == "verifier":
        changed = ", ".join((state.get("changed_files") or [])[:20]) or "(없음)"
        prompt = (
            f"검증하라. 요청: {task}\ncriteria: {criteria}\nrequired level: {level}\n"
            f"하니스 관측 변경 파일: {changed} (diff_lines={state.get('diff_lines', '?')}) — "
            "`git diff` / 파일 열람 / 실행으로 직접 확인하라.\n"
            "Worker 해설은 입력이 아니다 — diff 와 명령 실행으로만 판정. 판정은 반드시 verdict 툴로 제출."
        )

        def _ack(_i: dict) -> str:
            return "판정 접수"

        extra = [VERDICT_TOOL]
        handlers = {"verdict": _ack}
    else:
        prompt = f"과업: {task}"

    def _out(s: str) -> None:
        sys.stdout.write(s)
        sys.stdout.flush()

    sess = AgentSession(
        make_client(rrp),
        rrp,
        root,
        _role_prompt(f"asgard-{role}.md"),
        extra_tools=extra,
        tool_handlers=handlers,
        on_text=_out,
        role=role,
        readonly=role != "worker",
    )
    r = sess.run(prompt)

    result: dict = {
        "role": role,
        "provider": rrp.profile.name,
        "model": rrp.model,
        "placed": rrp is not default,
        "writes": r.writes,
        "verdict": None,
    }
    if role == "thinker":
        ql(root, "append", session=sid, stdin=json.dumps({"role": "thinker", "event": "plan", "criteria": criteria}))
        result["appended"] = "plan"
    elif role == "worker":
        _record_writes(root, sid, r.writes)  # write-sentinel 미러 — sid 가 호스트 세션과 일치할 때 증거가 된다
        ql(
            root,
            "append",
            session=sid,
            stdin=json.dumps(
                {"role": "worker", "event": "work", "changed_files": r.writes[:50], "commands": r.commands[-20:]}
            ),
        )
        result["appended"] = "work"
    else:
        v = next((c["input"] for c in r.tool_calls if c["name"] == "verdict"), None) or {
            "verdict": "FAIL",
            "criteria": criteria,
            "commands": [],
            "failure_sig": "no-verdict-submitted",
        }
        ev = {
            "role": "verifier",
            "event": "verify",
            "criteria": v.get("criteria") or criteria,
            "commands": v.get("commands") or [],
        }
        if v.get("failure_sig"):
            ev["failure_sig"] = v["failure_sig"]
        ql(root, "append", "--verdict", str(v["verdict"]), "--level", level, session=sid, stdin=json.dumps(ev))
        result["verdict"] = v
        result["appended"] = "verify"
    print("\n" + json.dumps(result, ensure_ascii=False))
    return 0
