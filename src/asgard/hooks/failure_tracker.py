#!/usr/bin/env python3
# Asgard failure-tracker — Canon Law 9 (무한 루프 방지). "같은 종류" 실패를 툴+오류 시그니처 단위로
# 세고, 3회부터 SOFT 경고를 컨텍스트에 주입한다.
#
# 왜 차단이 아니라 경고인가: PostToolUse 시점엔 이미 실행이 끝났고, Law 9의 목적은 금지가 아니라
# 전략 전환 유도다. 재시도가 정당한 경우(간헐적 네트워크 오류 등)도 있어 차단은 오히려 해롭다.
# 왜 시그니처 정규화인가: 에이전트가 경로·숫자만 바꿔 "다른 시도인 척" 재시도하는 것을 무력화하기
# 위해 — 가변 부분을 지우면 같은 실패는 같은 key로 모인다 (sig() 참조).
# 왜 상태가 툴 중립 .asgard/ 인가: 크로스툴 연속성 — Claude에서 3회 실패하고 Cursor로 갈아타도
# 카운트가 이어진다. 파일은 세션별 — 지난 세션의 실패가 새 세션을 오염시키지 않고, 동시 세션끼리
# 파일 lock 없이도 안 부딪힌다.
# 스크립트 하나로 모든 툴 지원 — 페이로드 모양으로 프로토콜 자동 감지 (read_failure() 참조):
#   • Claude Code / Codex (PostToolUse):     {tool_name, tool_response:{error|is_error}} → additionalContext.
#   • Cursor (postToolUseFailure, 실패시만):  {tool_name, error_message, failure_type}     → agentMessage.
#   • Claude Code (Stop, 도구 이름 없음):     {transcript_path, session_id}                → systemMessage.
#
# 마지막 줄이 이 훅의 두 번째 관측원이다. Claude Code 는 **도구 호출이 실패하면 PostToolUse 를
# 아예 안 부른다** (26-08-12 계수기 실측: 일부러 실패시킨 Bash 2건에 PreToolUse `readonly-guard`
# 는 3331→3333 으로 올랐는데 PostToolUse 인 이쪽은 3749 에 멈춘 채 `last_call` 도 안 움직였다.
# `firing.record` 가 `finally` 안이라 시작만 한 훅도 반드시 세어지므로, 시작조차 안 했다는 뜻이다).
# 그래서 그 호스트에서는 실패 페이로드가 이 훅에 닿은 적이 없고, Canon 9 의 도구 실패 레인이
# 통째로 죽어 있었다 — read_failure 를 아무리 넓혀도 안 살아난다.
#
# 관측 자리를 페이로드 밖으로 옮겨 되살린다: 턴이 끝날 때 Stop 이 세션 기록(transcript) 꼬리를
# 읽고, 아직 안 센 `is_error` tool_result 를 주워 같은 카운터에 넣는다. 기록은 호스트가 어차피
# 디스크에 적는 정본이고, 훅을 부르든 말든 실패가 거기 남는다 (budget-guard 가 토큰을 재는 근거도
# 같은 파일이다). 값: 턴당 프로세스 하나 — 도구 호출당이 아니다.
#
# 그 대신 경고는 턴이 끝난 뒤에 온다. 도구 호출 사이에 끼워 넣으려면 PreToolUse 를 매 호출마다
# 띄워야 하는데, 그 값이 이 경고 하나보다 비싸다. 턴 안에서 못 잡은 몫은 다음 턴이 받는다 —
# log_fail 이 적은 fail 이벤트를 전이 함수가 읽어 THINKER_REPLAN 을 내주기 때문이다.
# Fail-open + stdlib-only: 사용자 repo 안에서 의존성 없이 돌아야 하고, 관측용 훅이 오류로
# 세션을 방해하면 본말전도라 어떤 오류든 조용히 exit 0.
import contextlib
import json
import os
import re
import subprocess
import sys

# 발화 계측은 훅과 함께 깔리는 공용 라이브러리가 쥔다 — 이 훅은 자기 이름만 넘긴다.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.firing import run  # noqa: E402

# 기록 파싱은 공용 라이브러리가 쥔다 — 판정자에게 실행 기록을 넘기는 verifier-context 가 같은
# 파일을 읽으므로, 파서가 둘이면 갈라진다. `GUARD_OPENER`·`never_ran` 은 여기서 다시 내보낸다:
# 부르는 쪽이 이 훅의 이름으로 찾고 있고, 옮긴 것은 구현이지 계약이 아니다.
from asgard_hooklib.transcript import (  # noqa: E402
    GUARD_OPENER,
    calls,
    never_ran,
    tail_rows,
)

__all__ = ["GUARD_OPENER", "never_ran", "scan_transcript", "sweep"]

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass


WARN = (
    "Repeated failure: `{tool}` failed {n}× with the same error kind this session. "
    "Canon Law 9 (infinite-loop prevention) + Trinity: Worker retries are forbidden — switch to Thinker "
    "replanning or escalate to Odin (the transition function also returns THINKER_REPLAN: quest-log next)."
)


def _quest_log_script() -> str:
    """옆에 놓인 기장 스크립트의 실제 이름.

    같은 파일이 두 이름으로 산다 — 패키지에서는 `quest_log.py`(임포트되는 모듈이라 밑줄),
    배포된 훅 디렉터리에서는 `quest-log.py`(훅 파일 규약이 붙임표). 한쪽만 찾던 판은 배포
    디렉터리에서 **매번 빗나갔고**, 이 호출은 `check=False` 에 바깥 `except` 까지 있어 아무
    말도 없이 사라졌다 — Canon 9 의 3연속 실패 사건이 호스트 3모드에서 퀘스트 로그에 한 번도
    안 적혔고, 전이 함수의 `failure_count` 소비자는 그것을 영영 못 봤다 (26-08-05 감사).

    없으면 밑줄 이름을 돌려준다 — 호출자가 어차피 조용히 실패하므로 새 예외를 만들지 않는다."""
    here = os.path.dirname(__file__)
    for name in ("quest-log.py", "quest_log.py"):
        candidate = os.path.join(here, name)
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(here, "quest_log.py")


def sig(text: str) -> str:
    """오류문을 안정된 시그니처로 정규화 — 표현만 바꾼 재시도가 같은 key로 모이게.

    지우는 것들이 곧 "시도마다 달라지는 부분"이다: hex/해시(주소·커밋), 경로(파일명 바꿔 재시도),
    숫자(라인 번호·포트·PID). 80자 cap: 오류 종류 구분엔 앞부분이면 충분하고 key 폭주를 막는다."""
    s = text.lower()
    s = re.sub(r"0x[0-9a-f]+|\b[0-9a-f]{6,}\b", "", s)  # hex / 해시
    s = re.sub(r"[\\/]\S+", "", s)  # 경로 (가변 부분 제거)
    s = re.sub(r"\d+", "#", s)  # 숫자 -> #
    return re.sub(r"\s+", " ", s).strip()[:80]


def state_dir(proj: str) -> str:
    """repo 루트의 공유(툴 중립) 상태 디렉터리 — 툴별 디렉터리(.claude/ 등)에 두면 크로스툴
    카운트 공유가 깨진다. 첫 사용 때 '*' .gitignore를 스스로 심는 이유: 사용자 repo의
    .gitignore를 건드리지 않고 자기 완결로 커밋 오염을 막기 위해."""
    d = os.path.join(proj, ".asgard")
    os.makedirs(d, exist_ok=True)
    gi = os.path.join(d, ".gitignore")
    if not os.path.exists(gi):
        try:
            with open(gi, "w", encoding="utf-8") as handle:
                handle.write("*\n")
        except Exception:
            pass
    return d


def read_failure(data: dict) -> tuple[str, bool]:
    """(error_text, is_cursor) 반환. error_text가 비면 인식된 실패가 아님 (스킵).

    판별 근거: Cursor의 postToolUseFailure는 실패시에만 불리므로 error_message/failure_type 키의
    존재 자체가 실패 신호. Claude/Codex의 PostToolUse는 성공에도 불리므로 실패 표식으로만 고른다.

    **표식과 본문을 갈라 읽는다** — 실패인지는 `is_error`/`error` 표식이 최상위든 `tool_response`
    안이든 정하고, 무엇이 실패했는지는 dict면 `error`/`stderr`, 문자열이면 그 문자열에서 읽는다.
    모양을 하나씩 늘리는 대신 표식 이름을 입구로 삼는다.

    **이 함수는 Claude Code 에서 실패를 한 번도 못 본다.** 그 호스트는 도구 호출이 실패하면
    PostToolUse 를 아예 안 부른다 (계수기 실측은 이 파일 머리말에 있다). 그쪽 실패는
    `scan_transcript` 가 기록에서 줍는다.

    그러면 넓힌 갈래는 누가 쓰는가 — Cursor 는 위 첫 갈래에서 끝나므로 수혜자가 아니고, 남는
    후보는 Codex 하나다. 그 호스트의 실물 페이로드는 아직 안 쟀다. 그래도 남겨 두는 것은 값이
    분기 하나이고, 성공을 실패로 오판하지 않는 것은 확인했기 때문이다 (문자열·dict 응답,
    `error: ""`·`False`·`None` 전부 무시)."""
    if "error_message" in data or "failure_type" in data:  # Cursor
        return str(data.get("error_message") or data.get("failure_type") or "error"), True
    resp = data.get("tool_response")  # Claude Code / Codex
    marks = [data, resp if isinstance(resp, dict) else {}]
    if not any(mark.get("is_error") or mark.get("error") for mark in marks):
        return "", False
    if isinstance(resp, dict):
        body = resp.get("error") or resp.get("stderr") or data.get("error")
    else:
        body = resp or data.get("error")
    return str(body or "error"), False


TAIL = 1000  # 기록 꼬리에서 볼 줄 수 — 방금 끝난 턴을 덮으면 된다
SEEN_CAP = 1000  # 기억할 tool_use_id 수 — 꼬리에 들어올 수 있는 실패 수보다 크면 충분하다


def scan_transcript(path: str, seen: set) -> list:
    """기록 꼬리에서 아직 안 센 도구 실패를 `[(tool_use_id, 도구 이름, 오류문), ...]` 로.

    호스트가 훅을 부르든 말든 실패는 이 파일에 남는다 — `is_error` 가 붙은 tool_result 가 그것이다.
    도구 이름은 그 결과에 없고 짝이 되는 assistant 의 `tool_use` 블록에 있으므로, 같은 꼬리에서
    `tool_use_id → 이름` 을 먼저 모은다. 짝을 못 찾은 실패는 건너뛴다 — 이름 없는 key 는 시그니처
    단위 집계를 무너뜨린다. 실행되기 전에 거절된 호출도 뺀다 (`never_ran`).

    꼬리만 보므로 한 턴이 TAIL 줄을 넘기면 가장 오래된 실패는 놓친다. 놓치는 쪽으로 틀린 것은
    의도다 — 안 센 실패는 경고가 늦을 뿐이고, 두 번 센 실패는 없는 루프를 신고한다."""
    return [
        (call.id, call.tool, call.output or "error")
        for call in calls(tail_rows(path, TAIL))
        if call.failed and call.id not in seen and not never_ran(call.output)
    ]


def seen_path(state: str, sid: str) -> str:
    """이미 센 실패의 자리 — 카운트 파일과 갈라 둔다.

    카운트는 툴을 넘나드는 계약이고(크로스툴 공유), 이 목록은 기록을 다시 읽는 이쪽만의 장부다.
    한 파일에 섞으면 `{key: 횟수}` 라는 카운트 파일의 모양이 깨진다.

    이름이 `failures-` 로 시작하지 않는 것도 그래서다 — 카운트 파일을 `failures-*.json` 으로
    긁는 손이 이 장부까지 열면 `{key: 횟수}` 를 기대한 자리에 id 목록이 온다."""
    return os.path.join(state, "seen-failures-" + sid + ".json")


def read_seen(path: str) -> set:
    try:
        with open(path, encoding="utf-8") as handle:
            return set(json.load(handle))
    except Exception:
        return set()  # 깨진 장부는 빈 장부 — 최악이라도 이번 꼬리를 한 번 더 세는 정도다


def write_seen(path: str, seen: set, order: list) -> None:
    """센 id 를 SEEN_CAP 개만 남긴다 — 최근 것이 뒤로 가게 이번 회차를 뒤에 붙인다."""
    kept = [i for i in seen if i not in set(order)] + list(order)
    with contextlib.suppress(OSError, TypeError, ValueError):
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(kept[-SEEN_CAP:], handle)
        os.replace(tmp, path)


def bump(counts: dict, tool: str, err: str) -> tuple:
    """실패 하나를 카운터에 넣고 (key, 누적 횟수) 반환."""
    key = tool + "|" + sig(err)
    counts[key] = int(counts.get(key, 0)) + 1
    return key, counts[key]


def save_counts(path: str, counts: dict) -> None:
    """temp+rename — 크래시 절단이 카운트를 리셋하지 않게. 저장 실패해도 이번 판정은 진행한다."""
    with contextlib.suppress(OSError, TypeError, ValueError):
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(counts, handle)
        os.replace(tmp, path)


def read_counts(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            counts = json.load(handle)
        return counts if isinstance(counts, dict) else {}
    except Exception:
        return {}  # 깨진 상태 파일은 카운트 리셋 — 훅을 죽이는 것보다 낫다


def log_fail(proj: str, sid: str, key: str, n: int) -> None:
    """Trinity 배선: 임계 도달을 활성 퀘스트 로그에도 fail 이벤트로 남긴다 — 전이 함수
    (quest-log next)가 failure_count를 로그에서 관찰해 THINKER_REPLAN을 결정하게. 임계 도달
    시에만 쓰는 이유: 매 실패를 로그에 넣으면 노이즈만 늘고 소비자(전이 함수)는 임계만 본다.
    fail-open: 로그가 없거나(quest 미사용) 어떤 오류든 조용히 넘어간다 — 경고 주입은 계속된다."""
    try:
        qdir = os.path.join(proj, ".asgard", "quest")
        pointers = (
            os.path.join(qdir, "sessions", sid + ".active"),
            os.path.join(qdir, "ACTIVE"),  # legacy single-session fallback
        )
        qid = ""
        for pointer in pointers:
            try:
                with open(pointer, encoding="utf-8") as handle:
                    qid = handle.read().strip()
            except OSError:
                continue
            if qid:
                break
        if not qid:
            return
        ev = {
            "role": "worker",
            "event": "fail",
            "failure_sig": key,
            "failure_count": n,
        }
        # quest-log owns locking, monotonic turns and the v2 hash chain. A second writer that
        # reimplements the JSONL schema would make replay unverifiable.
        subprocess.run(
            [
                sys.executable,
                _quest_log_script(),
                "append",
                qid,
                "--session",
                sid,
            ],
            input=json.dumps(ev, ensure_ascii=False),
            text=True,
            cwd=proj,
            capture_output=True,
            timeout=10,
            env={**os.environ, "CLAUDE_PROJECT_DIR": proj},
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        pass


def sweep(data: dict, proj: str, sid: str) -> None:
    """턴 경계에서 기록 꼬리를 훑어 못 본 실패를 센다 — Claude Code 의 실패는 여기로만 들어온다.

    PostToolUse 갈래와 카운터·임계·fail 이벤트를 공유한다. 다른 것은 발화 채널뿐이다: 턴이 이미
    끝났으므로 `additionalContext` 로 모델에게 밀어 넣을 자리가 없어 사람이 보는 `systemMessage`
    로 낸다. 모델 쪽 몫은 **퀘스트가 열려 있을 때** 다음 턴의 전이 함수가 받는다 — log_fail 이
    적은 fail 이벤트를 읽고 THINKER_REPLAN 을 내준다. 퀘스트가 없으면 log_fail 이 조용히 빠지고
    사람이 보는 문장만 남는다. 절대 막지 않는다 (Law 9 는 금지가 아니라 전략 전환 유도다).

    **한 턴 경계는 fail 이벤트를 하나만 낸다.** 한 번 훑는 데 임계를 넘는 실패가 여럿 나올 수
    있고(배선을 처음 깐 턴은 이미 지나간 실패까지 소급해 센다 — 실측 120세션 중 12세션이 첫
    훑기에서 임계를 넘었고 최대 6건이었다), 그때마다 적으면 퀘스트 로그가 한 Stop 에 fail 로
    덮인다. 전이 함수는 가장 큰 failure_count 만 보므로 제일 심한 것 하나로 족하다.

    lagom: 되짚기 장부는 이쪽이 센 것만 안다. PostToolUse 갈래는 id 를 안 남기므로, 실패에도
    PostToolUse 를 부르는 호스트에 이 Stop 배선을 같이 걸면 한 실패가 두 번 세어진다. 지금
    Stop 에 걸린 호스트는 Claude Code 하나이고 그 호스트는 실패에 PostToolUse 를 안 부른다 —
    겹치는 배선이 생기면 그때 양쪽이 같은 id 장부를 쓰게 하면 된다."""
    seen_file = seen_path(state_dir(proj), sid)
    seen = read_seen(seen_file)
    found = scan_transcript(str(data.get("transcript_path") or ""), seen)
    if not found:
        return
    path = os.path.join(state_dir(proj), "failures-" + sid + ".json")
    counts = read_counts(path)
    worst = ("", "", 0)
    for _, tool, err in found:
        key, n = bump(counts, tool, err)
        if n >= 3 and n > worst[2]:
            worst = (key, tool, n)
    save_counts(path, counts)
    write_seen(seen_file, seen, [use_id for use_id, _, _ in found])
    if worst[2]:
        log_fail(proj, sid, worst[0], worst[2])
        sys.stdout.write(json.dumps({"systemMessage": WARN.format(tool=worst[1], n=worst[2])}, separators=(",", ":")))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        tool = str(data.get("tool_name") or "").strip() or "unknown"
        # repo 루트 찾기: Claude는 CLAUDE_PROJECT_DIR env를 주고, Codex/Cursor는 페이로드 cwd로
        # 온다. getcwd는 마지막 안전망 — 상태를 엉뚱한 곳에 두더라도 죽는 것보단 낫다.
        proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        # session_id는 외부 입력인데 파일명에 들어간다 — 경로 문자를 지워 traversal을 차단.
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("session_id") or "default"))[:64]
        if tool == "unknown":
            # 도구 이름이 없는 이벤트 = 턴 경계(Stop). 여기서만 기록을 읽는다.
            sweep(data, proj, sid)
            sys.exit(0)
        err, cursor = read_failure(data)
        if not err:
            sys.exit(0)  # not a recognized failure -> no-op

        path = os.path.join(state_dir(proj), "failures-" + sid + ".json")
        counts = read_counts(path)
        key, n = bump(counts, tool, err)
        save_counts(path, counts)
        if n >= 3:  # Law 9의 "같은 접근 3회+" 임계와 일치
            log_fail(proj, sid, key, n)  # Trinity: 로그에 fail 이벤트 → 전이 함수가 재계획 결정
            msg = WARN.format(tool=tool, n=n)
            if cursor:
                out = {"agentMessage": msg}  # Cursor는 agentMessage로 에이전트에게 전달
            else:
                # Claude/Codex: additionalContext로 소프트 주입. 태그로 감싸 모델이
                # 훅 경고임을 구분하게 한다 (사용자 발화와 혼동 방지).
                out = {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": "<asgard-failure-warning>\n" + msg + "\n</asgard-failure-warning>",
                    }
                }
            sys.stdout.write(json.dumps(out, separators=(",", ":")))
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    run("failure-tracker", main)
