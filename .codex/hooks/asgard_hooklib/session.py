"""세션과 ACTIVE 포인터 — 지금 어느 퀘스트가 열려 있는가.

호스트가 세션 식별자를 주는 방식이 클라이언트마다 달라서 후보를 여러 환경변수에서 읽는다.
포인터 쓰기는 원자 교체 + 디렉터리 fsync 다: 중간에 죽은 포인터는 "열려 있는데 아무도 모르는
퀘스트"가 되고, 그 상태에서 Stop 게이트는 막을 근거를 못 찾는다.
"""

from __future__ import annotations

import os
import re

from .paths import fsync_dir, quest_dir, read_text

_SESSION_ENV = (
    "CLAUDE_CODE_SESSION_ID",  # Claude Code 가 실제로 내보내는 이름
    "CLAUDE_SESSION_ID",  # 종전에 이 파일이 찾던 이름 — 다른 호스트가 줄 수 있으니 남긴다
    "CURSOR_SESSION_ID",
    "CODEX_SESSION_ID",
)


def host_session_id() -> str:
    """호스트가 준 세션 신원. 없으면 `"-"` — 신원이 아니라 신원 부재의 표시다.

    verifier_gate.py 의 같은 이름 함수와 동일 유지 (단일 출처 원칙 — 어긋나면 포인터를 쓰는
    쪽과 읽는 쪽이 다른 이름을 본다). 종전에는 `CLAUDE_SESSION_ID` 하나만 봤는데 Claude Code 가
    내보내는 이름은 `CLAUDE_CODE_SESSION_ID` 라 조회가 늘 빗나갔고, 그래서 한 저장소의 모든
    세션과 서브에이전트가 포인터 파일 하나(`sessions/-.active`)를 공유했다. 나중에 open 한
    쪽이 앞선 쪽의 포인터를 가져가, 판정이 남의 퀘스트에 적혔다 (26-08-04 실측 3건)."""
    for name in _SESSION_ENV:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return "-"


UNATTENDED_MODES = {"bypassPermissions", "dontAsk"}


def unattended(data: dict | None = None) -> bool:
    """사람이 승인 루프에 있는가 — 없으면 참.

    모델은 headless 여부를 스스로 알 수 없다. 아는 것은 훅뿐이다: `permission_mode` 가 모든 훅
    stdin 에 공통으로 오고, 네이티브 headless 진입은 `ASGARD_UNATTENDED` 를 세운다. 판정이
    갈리면 한쪽은 물어도 되는 줄 알고 멈추고 다른 쪽은 진행하므로 정의를 여기 하나만 둔다
    (종전에는 `unattended_context.py` 와 `verifier_gate.py` 가 각자 적고 주석으로 맞췄다)."""
    if os.environ.get("ASGARD_UNATTENDED") == "1":
        return True
    return str((data or {}).get("permission_mode") or "") in UNATTENDED_MODES


def _session_key(session: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(session or "default"))[:64] or "default"


def session_pointer(root: str, session: str, kind: str = "active") -> str:
    directory = os.path.join(quest_dir(root), "sessions")
    return os.path.join(directory, f"{_session_key(session)}.{kind}")


def write_pointer(path: str, qid: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(qid + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    fsync_dir(os.path.dirname(path))


def active_quest(root: str, session: str | None = None) -> str | None:
    """이 session이 보고 있는 quest.

    남은 결함 — `--session` 기본값은 `host_session_id()` 라서 호스트가 세션 이름을 내주는 동안은
    세션마다 포인터가 갈린다. 하지만 아무 이름도 없으면 그 함수는 `"-"` 를 주고, 여기서는 그것이
    신원처럼 쓰인다: 그 기계에서 도는 모든 세션과 서브에이전트가 포인터 파일 하나
    (`sessions/-.active`)를 공유하고, 나중에 `open` 한 쪽이 앞선 쪽의 포인터까지 가져간다.
    이름을 못 찾던 시절의 실측 26-08-04, 같은 원인으로 두 건: Verifier 서브에이전트의 PASS 가
    남의 `verifier-latency-cut` turn 2 에 적혔고(그 quest 는 아무도 검증한 적이 없다), 한 세션의
    append 가 남의 `uv-hook-defects` turn 3 으로 들어갔다. 회수를 뒤에 붙여도 `last_verdict` 는
    안 돌아온다.

    신원 부재를 신원에서 떼어내려면 gate 의 "무퀘스트" 판정이 같이 움직인다
    (`TestAdversarialSuite` · `TestQuestScopedStale` 가 그 자리를 잡는다) — 별도 퀘스트다.
    그때까지 이름 없는 호스트에서의 회피책은 하나뿐이다: 쓰기 명령에 quest id 를 **명시**한다
    (`quest-log append <quest-id> …`). 역할 계약들은 아직 맨 `append` 를 안내한다."""
    paths = []
    if session is not None:
        session_path = session_pointer(root, session)
        try:
            qid = read_text(session_path).strip()
            if qid:
                return qid
        except Exception:
            pass
        sessions = os.path.dirname(session_path)
        if os.path.exists(session_pointer(root, session, "known")):
            return None  # 이 session은 이미 닫혔음 — 다른 session으로 fallback 금지
        # 구 scaffold는 quest-log CLI와 hook session id를 결속하지 않았다. 알려지지 않은 hook
        # session은 active Quest가 정확히 하나일 때만 안전하게 승계한다. 둘 이상이면 fail closed.
        try:
            active = {
                read_text(os.path.join(sessions, name)).strip()
                for name in os.listdir(sessions)
                if name.endswith(".active")
            }
            active.discard("")
            if len(active) == 1:
                return next(iter(active))
        except Exception:
            pass
        if os.path.isdir(sessions):
            return None
    paths.append(os.path.join(root, ".asgard", "quest", "ACTIVE"))  # v1 fallback
    for path in paths:
        try:
            qid = read_text(path).strip()
            if qid:
                return qid
        except Exception:
            continue
    return None


def set_active_quest(root: str, session: str, qid: str) -> None:
    write_pointer(session_pointer(root, session), qid)
    write_pointer(session_pointer(root, session, "known"), qid)
    write_pointer(os.path.join(quest_dir(root), "ACTIVE"), qid)  # v1 readers 호환


def clear_active_quest(root: str, session: str, qid: str) -> None:
    for path in (session_pointer(root, session), os.path.join(quest_dir(root), "ACTIVE")):
        try:
            if read_text(path).strip() == qid:  # compare-and-delete
                os.remove(path)
                fsync_dir(os.path.dirname(path))
        except FileNotFoundError:
            pass


def pointer_qid(path: str) -> str:
    try:
        return read_text(path).strip()
    except Exception:
        return ""
