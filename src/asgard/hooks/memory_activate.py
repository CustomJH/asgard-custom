#!/usr/bin/env python3
# Asgard memory-activate — 개인 스냅샷 + 개인/프로젝트 관련 회수 (클라이언트 공용 배선).
#
# 배선 매처: SessionStart startup|resume|clear|compact (lagom-activate와 동일 —
# compact/clear는 컨텍스트 소실 지점이라 재주입 필수) + UserPromptSubmit 관련 회수 +
# SubagentStart ^asgard-thinker$
# (감사 매트릭스: Thinker 한정. Worker/딜리버리 기본 무주입, Verifier/Loki 영구 무주입 —
# lagom처럼 전 서브에이전트 보상 주입하는 패턴은 메모리에 적용 금지).
#
# 동작: SessionStart/SubagentStart는 `asgard memory snapshot`, UserPromptSubmit은
# `asgard memory recall`을 subprocess로 소비한다. 스캔·오염 제외·예산·provider gate는
# 전부 CLI(단일 출처)가 수행하고, 이 훅은 출력 전달만 한다 (로직 재구현 금지).
# asgard 미설치·빈 출력·타임아웃·어떤 오류든 무주입 통과 (fail-open, 항상 exit 0).
#
# `ASGARD_MEMORY_NO_DOWNLOAD` 는 자식 넷에게만 뜻이 있다 (이 프로세스는 안 쓴다). `sync-turn`
# 은 켜든 끄든 같다 — 26-08-05 격리 홈 실측 101ms vs 100ms, 양쪽 페이지 0·벡터 0. 그 명령은
# 개인 위키를 안 써서 `_vec_upsert` 에 안 닿는다. 위키를 쓰며 벡터가 필요한 자리는 분리 스폰
# 되는 `memory norn --auto` 하나고, 거기서는 `memory_semantic.detached_env` 가 표식을 뗀다.
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass

# 주입 스키마는 훅과 함께 깔리는 공용 라이브러리가 쥔다. 이 훅에 남는 정책은 Stop 갈래 하나다 —
# 되짚기 문장은 컨텍스트가 아니라 사람에게 보이는 채널로 나간다 (systemMessage/followup_message).
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.firing import run  # noqa: E402
from asgard_hooklib.inject import emit_context  # noqa: E402

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


def _read_text(path: str) -> str:
    """파일을 통째로 읽는다. 오류는 그대로 올린다 — 호출부마다 삼킬 범위가 다르다. quest_log.py와 동일 유지.

    핸들 수명을 여기서 끝내는 것이 요점이다. `open(p).read()`는 CPython의 참조 계수에 기대
    곧장 닫히는 것이고, 그 기댐은 코드에 안 적혀 있어서 다른 런타임에서 조용히 깨진다."""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _transcript_turn(path: str, user: str, assistant: str) -> tuple[str, str]:
    """대화 기록에서 마지막 (사용자, 어시스턴트) 짝. 못 읽으면 받은 값을 그대로 돌려준다.

    `_latest_turn`에서 갈라 나온 이유는 깊이다 — 조건·try·with·루프·try가 한 함수에 겹치면
    읽는 사람이 어느 실패가 어디로 가는지 못 따라간다."""
    latest_user = ""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except Exception:
                    continue  # 찢어진 줄 하나 — 기록 전체를 버리는 것보다 그 줄만 건너뛰는 편이 낫다
                message = row.get("message") if isinstance(row.get("message"), dict) else row
                role = str(message.get("role") or row.get("role") or row.get("type") or "")
                text = _message_text(message.get("content"))
                if role == "user" and text:
                    latest_user = text
                elif role == "assistant" and text:
                    user, assistant = latest_user or user, text
    except Exception:
        pass  # 기록을 못 읽어도 훅은 무개입으로 통과한다 — 여기서 올리면 세션 시작이 막힌다
    return user, assistant


def _latest_turn(data: dict) -> tuple[str, str]:
    user = str(data.get("prompt") or "").strip()
    assistant = str(data.get("last_assistant_message") or "").strip()
    path = str(data.get("transcript_path") or "")
    if (not user or not assistant) and path:
        return _transcript_turn(path, user, assistant)
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
            qid = _read_text(pointer).strip()
            if qid:
                last_ids.add(qid)
        except Exception:
            continue
    matches = []
    for qid in last_ids:
        name = qid + ".jsonl"
        events = []
        try:
            with open(os.path.join(quest_dir, name), encoding="utf-8") as handle:
                events = [json.loads(line) for line in handle if line.strip()]
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
        matches.append((os.path.getmtime(os.path.join(quest_dir, name)), qid, summary, verified))
    if not matches:
        return {"verified": False, "changed_files": [], "evidence": [], "quest_id": _active_quest(root)}
    _, qid, summary, verified = max(matches, key=lambda row: row[0])
    changed = sorted(str(path) for path in (summary.get("changed_files") or []) if str(path))
    return {
        "verified": True,
        "changed_files": changed,
        "evidence": verified.get("commands") or [],
        "quest_id": qid,
    }


def _active_quest(root: str) -> str:
    """완료 사건이 없을 때의 귀속 좌표 — 에피소드 계층은 미완 퀘스트의 턴도 찾을 수 있어야 한다."""
    try:
        from asgard.hooks.quest_log import active_quest

        return str(active_quest(root) or "")
    except Exception:
        return ""


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
        # 아래 네 자식은 10~20초 상한 안에서 돈다. 신규 설치의 첫 회수가 그 안에서 임베딩
        # 모델(수십 초)을 받기 시작하면 상한에 잘려 죽고 다음 프롬프트도 같은 자리에서 죽는다 —
        # 시맨틱이 영영 안 켜진다. 그래서 "받지 마라"를 알린다: 시맨틱만 빠지고 어휘·그래프
        # 회수는 그대로 돈다. 준비는 warmup 이 맡는다 (표식이 무엇에 닿는지는 파일 머리에).
        os.environ["ASGARD_MEMORY_NO_DOWNLOAD"] = "1"
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
                encoding="utf-8",
                errors="replace",
            )
            try:
                result = json.loads(r.stdout or "{}") if r.returncode == 0 else {}
            except Exception:
                result = {}
            messages = []
            preview = str((result.get("proposal") or {}).get("preview") or "")
            if preview:
                messages.append("⠶ Project memory approval proposal\n" + preview)
            automation = str(result.get("automation") or "").strip()
            if automation:
                messages.append("⠶ " + automation)
            # 턴 끝 신호 — 자가발전·노른·패턴·2차 진화·프로젝트 학습·시맨틱 준비. 판정과 latch는
            # 전부 CLI 소유고 (`asgard memory tick`), 훅은 낸 줄을 전달만 한다. 넷을 각각 띄우던
            # 동안 값의 대부분이 인터프리터 부팅이었다 — 26-08-04 실측 460ms → 218ms.
            try:
                n = subprocess.run(
                    [exe, "memory", "tick"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    cwd=root,
                    encoding="utf-8",
                    errors="replace",
                )
                if n.returncode == 0:
                    messages += ["⠶ " + line for line in (n.stdout or "").splitlines() if line.strip()]
            except Exception:
                pass  # 넛지 불능이 Stop을 막지 않는다
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
        # 바깥 상한은 한 레인이 아니라 **여섯 레인 전부**를 덮는다 (memory_context 의 조립기가 개인·
        # 프로젝트·문서·에피소드·요약을 한 프로세스 안에서 차례로 돈다). 그래서 프로젝트 레인 하나의
        # 상한(`INJECT_TIMEOUT_DEFAULT`)과 같은 값이면 그 레인이 자기 몫을 다 쓰는 순간 바깥이 먼저
        # 터지고, 아래 except 가 **주입 전체를** 조용히 버린다 — 프로젝트만 빠지는 것이 아니다.
        # 형제 호출인 `memory tick` 과 같은 20 으로 둬서 나머지 다섯 레인의 자리를 남긴다.
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace")
        note = (r.stdout or "").strip()
        if r.returncode == 0 and note:
            emit_context(mode, note, event)
    except Exception:
        pass  # fail-open — 메모리 불능이 세션을 막지 않는다
    sys.exit(0)


if __name__ == "__main__":
    run("memory-activate", main)
