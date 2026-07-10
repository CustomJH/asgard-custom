#!/usr/bin/env python3
# Asgard failure-tracker — Canon Law 9 (무한 루프 방지). "같은 종류" 실패를 툴+오류 시그니처 단위로
# 세고, 3회부터 SOFT 경고를 컨텍스트에 주입한다.
#
# 왜 차단이 아니라 경고인가: PostToolUse 시점엔 이미 실행이 끝났고, Law 9 의 목적은 금지가 아니라
# 전략 전환 유도다. 재시도가 정당한 경우(간헐적 네트워크 오류 등)도 있어 차단은 오히려 해롭다.
# 왜 시그니처 정규화인가: 에이전트가 경로·숫자만 바꿔 "다른 시도인 척" 재시도하는 것을 무력화하기
# 위해 — 가변 부분을 지우면 같은 실패는 같은 key 로 모인다 (sig() 참조).
# 왜 상태가 툴 중립 .asgard/ 인가: 크로스툴 연속성 — Claude 에서 3회 실패하고 Cursor 로 갈아타도
# 카운트가 이어진다. 파일은 세션별 — 지난 세션의 실패가 새 세션을 오염시키지 않고, 동시 세션끼리
# 파일 lock 없이도 안 부딪힌다.
# 스크립트 하나로 모든 툴 지원 — 페이로드 모양으로 프로토콜 자동 감지 (read_failure() 참조):
#   • Claude Code / Codex (PostToolUse):     {tool_name, tool_response:{error|is_error}} → additionalContext.
#   • Cursor (postToolUseFailure, 실패시만):  {tool_name, error_message, failure_type}     → agentMessage.
# Fail-open + stdlib-only: 사용자 repo 안에서 의존성 없이 돌아야 하고, 관측용 훅이 오류로
# 세션을 방해하면 본말전도라 어떤 오류든 조용히 exit 0.
import json
import os
import re
import sys

WARN = (
    "Repeated failure: `{tool}` failed {n}× with the same error kind this session. "
    "Canon Law 9 (무한 루프 방지) + Trinity: Worker 재시도 금지 — Thinker 재계획으로 전환하거나 "
    "Odin 에게 에스컬레이션하세요 (전이 함수도 THINKER_REPLAN 을 반환합니다: quest-log next)."
)


def sig(text: str) -> str:
    """오류문을 안정된 시그니처로 정규화 — 표현만 바꾼 재시도가 같은 key 로 모이게.

    지우는 것들이 곧 "시도마다 달라지는 부분"이다: hex/해시(주소·커밋), 경로(파일명 바꿔 재시도),
    숫자(라인 번호·포트·PID). 80자 cap: 오류 종류 구분엔 앞부분이면 충분하고 key 폭주를 막는다."""
    s = text.lower()
    s = re.sub(r"0x[0-9a-f]+|\b[0-9a-f]{6,}\b", "", s)  # hex / 해시
    s = re.sub(r"[\\/]\S+", "", s)  # 경로 (가변 부분 제거)
    s = re.sub(r"\d+", "#", s)  # 숫자 -> #
    return re.sub(r"\s+", " ", s).strip()[:80]


def state_dir(proj: str) -> str:
    """repo 루트의 공유(툴 중립) 상태 디렉터리 — 툴별 디렉터리(.claude/ 등)에 두면 크로스툴
    카운트 공유가 깨진다. 첫 사용 때 '*' .gitignore 를 스스로 심는 이유: 사용자 repo 의
    .gitignore 를 건드리지 않고 자기 완결로 커밋 오염을 막기 위해."""
    d = os.path.join(proj, ".asgard")
    os.makedirs(d, exist_ok=True)
    gi = os.path.join(d, ".gitignore")
    if not os.path.exists(gi):
        try:
            open(gi, "w").write("*\n")
        except Exception:
            pass
    return d


def read_failure(data: dict) -> tuple[str, bool]:
    """(error_text, is_cursor) 반환. error_text 가 비면 인식된 실패가 아님 (스킵).

    판별 근거: Cursor 의 postToolUseFailure 는 실패시에만 불리므로 error_message/failure_type 키의
    존재 자체가 실패 신호. Claude/Codex 의 PostToolUse 는 성공에도 불리므로 tool_response 안의
    is_error/error 로 실패만 골라낸다."""
    if "error_message" in data or "failure_type" in data:  # Cursor
        return str(data.get("error_message") or data.get("failure_type") or "error"), True
    resp = data.get("tool_response")  # Claude Code / Codex
    if isinstance(resp, dict) and (resp.get("is_error") or resp.get("error")):
        return str(resp.get("error") or resp.get("stderr") or "error"), False
    if data.get("error"):  # 일부 툴은 error 를 최상위에 싣는다 — 방어적 수용
        return str(data.get("error")), False
    return "", False


def log_fail(proj: str, sid: str, key: str, n: int) -> None:
    """Trinity 배선 (CUS-123): 임계 도달을 활성 퀘스트 로그에도 fail 이벤트로 남긴다 — 전이 함수
    (quest-log next)가 failure_count 를 로그에서 관찰해 THINKER_REPLAN 을 결정하게. 임계 도달
    시에만 쓰는 이유: 매 실패를 로그에 넣으면 노이즈만 늘고 소비자(전이 함수)는 임계만 본다.
    fail-open: 로그가 없거나(quest 미사용) 어떤 오류든 조용히 넘어간다 — 경고 주입은 계속된다."""
    try:
        qdir = os.path.join(proj, ".asgard", "quest")
        qid = open(os.path.join(qdir, "ACTIVE")).read().strip()
        if not qid:
            return
        path = os.path.join(qdir, qid + ".jsonl")
        turn = sum(1 for _ in open(path, encoding="utf-8")) + 1
        import time

        ev = {
            "schema": 1,
            "quest_id": qid,
            "session_id": sid,
            "turn": turn,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "role": "worker",
            "event": "fail",
            "base_ref": None,
            "risk": {},
            "criteria": [],
            "changed_files": [],
            "diff_hash": None,
            "commands": [],
            "verdict": "NA",
            "failure_sig": key,
            "failure_count": n,
        }
        line = (json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(path, os.O_APPEND | os.O_WRONLY)  # quest-log 와 같은 O_APPEND 단일 write
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:
        pass


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        tool = str(data.get("tool_name") or "").strip() or "unknown"
        err, cursor = read_failure(data)
        if not err or tool == "unknown":
            sys.exit(0)  # not a recognized failure -> no-op

        # repo 루트 찾기: Claude 는 CLAUDE_PROJECT_DIR env 를 주고, Codex/Cursor 는 페이로드 cwd 로
        # 온다. getcwd 는 마지막 안전망 — 상태를 엉뚱한 곳에 두더라도 죽는 것보단 낫다.
        proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        # session_id 는 외부 입력인데 파일명에 들어간다 — 경로 문자를 지워 traversal 을 차단.
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("session_id") or "default"))[:64]
        path = os.path.join(state_dir(proj), "failures-" + sid + ".json")
        counts = {}
        if os.path.exists(path):
            try:
                counts = json.load(open(path))
            except Exception:
                counts = {}  # 깨진 상태 파일은 카운트 리셋 — 훅을 죽이는 것보다 낫다
        key = tool + "|" + sig(err)
        counts[key] = int(counts.get(key, 0)) + 1
        n = counts[key]
        try:
            tmp = "%s.%d.tmp" % (path, os.getpid())  # temp+rename — 크래시 절단이 카운트를 리셋하지 않게
            json.dump(counts, open(tmp, "w"))
            os.replace(tmp, path)
        except Exception:
            pass  # 저장 실패해도 이번 경고 판정은 진행 (fail-open)
        if n >= 3:  # Law 9 의 "같은 접근 3회+" 임계와 일치
            log_fail(proj, sid, key, n)  # Trinity: 로그에 fail 이벤트 → 전이 함수가 재계획 결정
            msg = WARN.format(tool=tool, n=n)
            if cursor:
                out = {"agentMessage": msg}  # Cursor 는 agentMessage 로 에이전트에게 전달
            else:
                # Claude/Codex: additionalContext 로 소프트 주입. 태그로 감싸 모델이
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
    main()
