#!/usr/bin/env python3
# Asgard memory-activate — 개인 스냅샷 + 개인/프로젝트 관련 회수 (클라이언트 공용 배선).
#
# 배선 매처: SessionStart startup|resume|clear|compact (lagom-activate 와 동일 —
# compact/clear 는 컨텍스트 소실 지점이라 재주입 필수) + UserPromptSubmit 관련 회수 +
# SubagentStart ^asgard-thinker$
# (감사 매트릭스: Thinker 한정. Worker/딜리버리 기본 무주입, Verifier/Loki 영구 무주입 —
# lagom 처럼 전 서브에이전트 보상 주입하는 패턴은 메모리에 적용 금지).
#
# 동작: SessionStart/SubagentStart 는 `asgard memory snapshot`, UserPromptSubmit 은
# `asgard memory recall`을 subprocess 로 소비한다. 스캔·오염 제외·예산·provider gate는
# 전부 CLI(단일 출처)가 수행하고, 이 훅은 출력 전달만 한다 (로직 재구현 금지).
# asgard 미설치·빈 출력·타임아웃·어떤 오류든 무주입 통과 (fail-open, 항상 exit 0).
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
    except Exception:
        pass


NEVER_INJECT = ("asgard-verifier", "asgard-loki")  # 게이트·반례 탐색 오염 방지 — 매처가 바뀌어도 불변
MODES = {"claude-code", "codex", "cursor"}


def _mode() -> str:
    value = str(sys.argv[1] if len(sys.argv) > 1 else "claude-code")
    return value if value in MODES else "claude-code"


def _event(data: dict) -> str:
    """Cursor lower-camel 이벤트를 공용 Claude/Codex 계약으로 정규화한다."""
    event = str(data.get("hook_event_name") or "")
    return {
        "sessionStart": "SessionStart",
        "beforeSubmitPrompt": "UserPromptSubmit",
        "subagentStart": "SubagentStart",
        # Cursor의 SubagentStart 응답에는 context 필드가 없다. Task 실행 직전 preToolUse에서
        # Thinker snapshot을 싣고 동일한 격리 경계를 유지한다.
        "preToolUse": "SubagentStart",
        "stop": "Stop",
    }.get(event, event)


def _agent(data: dict) -> str:
    raw_input = data.get("tool_input")
    tool_input = raw_input if isinstance(raw_input, dict) else {}
    return str(
        data.get("agent_type")
        or data.get("agent_name")
        or data.get("subagent_type")
        or tool_input.get("agent_type")
        or tool_input.get("subagent_type")
        or ""
    )


def _message_text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(part.get("text") or "") for part in value if isinstance(part, dict)).strip()
    return ""


def _latest_turn(data: dict) -> tuple[str, str]:
    user = str(data.get("prompt") or "").strip()
    assistant = str(data.get("last_assistant_message") or "").strip()
    path = str(data.get("transcript_path") or "")
    if (not user or not assistant) and path:
        try:
            latest_user = ""
            for line in open(path, encoding="utf-8"):
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                message = row.get("message") if isinstance(row.get("message"), dict) else row
                role = str(message.get("role") or row.get("role") or row.get("type") or "")
                text = _message_text(message.get("content"))
                if role == "user" and text:
                    latest_user = text
                elif role == "assistant" and text:
                    user, assistant = latest_user or user, text
        except Exception:
            pass
    return user, assistant


def _completion_context(root: str, session_id: str) -> dict:
    """close가 검증을 강제한 동일 session quest만 완료 사건 후보로 전달한다."""
    quest_dir = os.path.join(root, ".asgard", "quest")
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id or "default"))[:64] or "default"
    last_ids: set[str] = set()
    for pointer in (
        os.path.join(quest_dir, "sessions", sid + ".last"),
        os.path.join(quest_dir, "LAST"),
    ):
        try:
            qid = open(pointer, encoding="utf-8").read().strip()
            if qid:
                last_ids.add(qid)
        except Exception:
            continue
    matches = []
    for qid in last_ids:
        name = qid + ".jsonl"
        events = []
        try:
            events = [
                json.loads(line) for line in open(os.path.join(quest_dir, name), encoding="utf-8") if line.strip()
            ]
        except Exception:
            continue
        if not events or not any(str(event.get("session_id")) == session_id for event in events):
            continue
        closed = events[-1] if events and events[-1].get("event") == "quest_closed" else None
        close_risk = (closed.get("risk") or {}) if closed else {}
        if (
            not closed
            or str(closed.get("session_id")) != session_id
            or close_risk.get("decision") != "APPROVED"
            or close_risk.get("forced")
        ):
            continue
        try:
            from asgard.hooks import quest_log

            summary = quest_log.summarize(root, qid, events, quest_log.load_policy(root))
            if quest_log.completion_decision(summary)[0] != "APPROVED":
                continue
            verified = next(
                event
                for event in reversed(events)
                if event.get("event") == "verify"
                and event.get("verdict") == "PASS"
                and str(event.get("session_id")) == session_id
            )
        except Exception:
            continue
        matches.append((os.path.getmtime(os.path.join(quest_dir, name)), summary, verified))
    if not matches:
        return {"verified": False, "changed_files": [], "evidence": []}
    _, summary, verified = max(matches, key=lambda row: row[0])
    changed = sorted(str(path) for path in (summary.get("changed_files") or []) if str(path))
    return {"verified": True, "changed_files": changed, "evidence": verified.get("commands") or []}


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    try:
        mode = _mode()
        event = _event(data)
        # SubagentStart 이중 방어 — settings 매처(^asgard-thinker$)가 느슨해져도 스크립트가 지킨다
        agent = _agent(data)
        if event == "SubagentStart":
            if agent in NEVER_INJECT or agent != "asgard-thinker":
                sys.exit(0)
        exe = shutil.which("asgard")
        if not exe:
            sys.exit(0)  # asgard CLI 부재 = 메모리 기능 없음 — 조용히 통과
        if event == "Stop":
            user, assistant = _latest_turn(data)
            if not user or not assistant:
                sys.exit(0)
            root = (
                os.environ.get("CLAUDE_PROJECT_DIR")
                or os.environ.get("CURSOR_PROJECT_DIR")
                or str(data.get("cwd") or os.getcwd())
            )
            session_id = str(data.get("session_id") or data.get("conversation_id") or mode)
            turn_id = str(data.get("turn_id") or hashlib.sha256((user + "\0" + assistant).encode()).hexdigest()[:24])
            payload = {
                "session_id": session_id,
                "turn_id": turn_id,
                "user_text": user,
                "assistant_text": assistant,
                **_completion_context(root, session_id),
            }
            r = subprocess.run(
                [exe, "memory", "sync-turn", "--mode", mode],
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=15,
                cwd=root,
            )
            try:
                result = json.loads(r.stdout or "{}") if r.returncode == 0 else {}
            except Exception:
                result = {}
            messages = []
            preview = str((result.get("proposal") or {}).get("preview") or "")
            if preview:
                messages.append("⠶ 프로젝트 메모리 승인 제안\n" + preview)
            # 자가발전 넛지 — 미채굴 hard-won 신호가 새로 생겼을 때만 한 줄 (latch 는 CLI 가 관리).
            # 네이티브 루프는 quest close 시점에 직접 넛지하므로 이 경로는 외부 클라이언트 훅 전용이다.
            try:
                n = subprocess.run([exe, "evolve", "nudge"], capture_output=True, text=True, timeout=10, cwd=root)
                nudge = (n.stdout or "").strip()
                if n.returncode == 0 and nudge:
                    messages.append("⠶ " + nudge.splitlines()[0])
            except Exception:
                pass  # 넛지 불능이 Stop 을 막지 않는다
            if messages:
                key = "followup_message" if mode == "cursor" else "systemMessage"
                sys.stdout.write(json.dumps({key: "\n\n".join(messages)}, ensure_ascii=False) + "\n")
            sys.exit(0)
        if event == "UserPromptSubmit":
            prompt = str(data.get("prompt") or "").strip()
            if not prompt:
                sys.exit(0)
            cmd = [exe, "memory", "recall", "--provider", mode, "--", prompt]
        else:
            cmd = [exe, "memory", "snapshot", "--provider", mode]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        note = (r.stdout or "").strip()
        if r.returncode == 0 and note:
            if mode == "cursor":
                sys.stdout.write(json.dumps({"additional_context": note}, ensure_ascii=False) + "\n")
            elif event == "UserPromptSubmit":
                sys.stdout.write(
                    json.dumps(
                        {
                            "hookSpecificOutput": {
                                "hookEventName": "UserPromptSubmit",
                                "additionalContext": note,
                            }
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            else:
                sys.stdout.write(note + "\n")
    except Exception:
        pass  # fail-open — 메모리 불능이 세션을 막지 않는다
    sys.exit(0)


if __name__ == "__main__":
    main()
