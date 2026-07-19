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


def _dir(root: str) -> str:
    key = hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:16]
    return os.path.join(os.path.expanduser("~"), ".asgard", "sessions", key)


def _path(root: str) -> str:
    return os.path.join(_dir(root), "turns.jsonl")


def append_turn(root: str, request: str, response: str) -> None:
    """완결 턴 1건 append. 빈 응답·실패는 조용히 무시."""
    if not (request.strip() and response.strip()):
        return
    try:
        d = _dir(root)
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)  # exist_ok 경로는 mode 미적용 — 기존 느슨한 권한도 매번 보정
        line = json.dumps(
            {"ts": time.time(), "request": request, "response": response[:_RESPONSE_CAP]},
            ensure_ascii=False,
        )
        fd = os.open(_path(root), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            if hasattr(os, "fchmod"):  # Windows 미존재 — POSIX 만 보정
                os.fchmod(fd, 0o600)  # O_CREAT 은 기존 파일 권한을 안 고친다 — 소유자 전용 강제
            f.write(line + "\n")
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
