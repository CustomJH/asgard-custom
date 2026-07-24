"""완결 턴 영속 — Heimdall 층의 (요청, 최종 응답)만 기록한다.

트랜스포트 메시지는 영속하지 않는다: SDK 객체·tool 쌍·암호화 reasoning 은 와이어별로 달라
복원이 불가능하거나 위험하고, 대화 맥락으로 유효한 것은 transport-독립인 최상위 문답뿐이다.
권위는 여기 없다 — Git·퀘스트 로그·게이트 증거가 소유한다. 복원은 대화 맥락(history)만 되살린다.

저장소: ~/.asgard/sessions/<root-sha16>/turns.jsonl
  - 루트는 realpath 의 sha256 16자리 — 같은 basename 프로젝트 간 충돌 없음
  - dir 0700 / file 0600, append-only, 손상 라인은 조용히 스킵 (마지막 줄 절단 내성)
모든 실패는 fail-open — 영속 문제로 본 세션이 죽으면 안 된다.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

_TAIL_BYTES = 256 * 1024  # 복원 시 파일 꼬리만 읽는다 — 장수 파일도 복원 비용 상수
_RESPONSE_CAP = 4000  # history 소비 계약(500자 절단)보다 넉넉하게 — 전문 보존은 목적 아님
_MAX_BYTES: int = (
    2 * 1024 * 1024
)  # 보존 정책 — 초과 시 최근 _KEEP_TURNS 만 남기고 재작성. 테스트가 치환하는 가변 정책값
_KEEP_TURNS: int = 400


def _dir(root: str) -> str:
    key = hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:16]
    return os.path.join(os.path.expanduser("~"), ".asgard", "sessions", key)


def _path(root: str) -> str:
    return os.path.join(_dir(root), "turns.jsonl")


def store_path(root: str) -> str:
    """세션 원문 파일 경로 — 파생 소비자(에피소드 인덱스)용 공개 표면."""
    return _path(root)


def _redact(text: str) -> str:
    """세션 원문은 폐기 대신 편집한다 — credential 스팬만 치환, 실패는 원문 보존 (fail-open)."""
    try:
        from ..memory.policy import redact_secrets

        return redact_secrets(text)
    except Exception:
        return text


def append_turn(
    root: str,
    request: str,
    response: str,
    quest_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """완결 턴 1건 append. 빈 응답·실패는 조용히 무시.

    quest_id/session_id 는 에피소드 계층의 귀속 신호 — 없으면 필드 자체를 생략해
    구 소비자(load_turns)와 라인 호환을 유지한다."""
    if not (request.strip() and response.strip()):
        return
    try:
        d = _dir(root)
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)  # exist_ok 경로는 mode 미적용 — 기존 느슨한 권한도 매번 보정
        record: dict = {
            "ts": time.time(),
            "request": _redact(request),
            "response": _redact(response[:_RESPONSE_CAP]),
        }
        if quest_id:
            record["quest"] = str(quest_id)
        if session_id:
            record["sid"] = str(session_id)
        line = json.dumps(record, ensure_ascii=False)
        fd = os.open(_path(root), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            if hasattr(os, "fchmod"):  # Windows 미존재 — POSIX 만 보정
                os.fchmod(fd, 0o600)  # O_CREAT 은 기존 파일 권한을 안 고친다 — 소유자 전용 강제
            f.write(line + "\n")
        _prune(root)
    except OSError:
        pass


def _prune(root: str) -> None:
    """보존 정책 — 파일이 _MAX_BYTES 를 넘으면 최근 _KEEP_TURNS 만 남기고 원자 재작성.
    실패는 무해 (다음 append 가 재시도). 파일 축소는 에피소드 인덱스가 전체 재구축으로 감지."""
    try:
        p = _path(root)
        if os.path.getsize(p) <= _MAX_BYTES:
            return
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        keep = lines[-_KEEP_TURNS:]
        tmp = p + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(keep) + "\n")
        os.replace(tmp, p)
    except OSError:
        pass


def load_turns(root: str, limit: int = 6) -> list[tuple[str, str]]:
    """최근 limit 턴 — (요청, 응답) 목록. 손상 라인(중단 절단 포함)은 스킵."""
    try:
        p = _path(root)
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            if size > _TAIL_BYTES:
                f.seek(size - _TAIL_BYTES)
                f.readline()  # 경계 걸친 부분 라인 폐기
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    turns: list[tuple[str, str]] = []
    for line in raw.splitlines():
        try:
            d = json.loads(line)
            q, a = str(d["request"]), str(d["response"])
        except ValueError, KeyError, TypeError:
            continue
        if q and a:
            turns.append((q, a))
    return turns[-limit:]
