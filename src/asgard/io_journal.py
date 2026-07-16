"""로컬 I/O 저널 — provider 호출별 메타데이터 append-only 기록.

provider 회귀(지연·오류율 비교)와 라곰 비용 실측의 상시 데이터 소스. 기록은 메타데이터만 —
프롬프트/응답 원문은 싣지 않는다. 이것은 계측이지 기억이 아니다 — semantic 메모리(개인 위키·
Hindsight)와 절대 혼합하지 않는다.

계약:
  - 기록 실패는 실행을 막지 않는다 (fail-open — 관측이 실행을 인질로 잡지 않는다).
  - started 기록이 실패하면 call_id 를 반환하지 않아 returned 도 억제된다 (반쪽 레코드 방지).
  - env ASGARD_IO_JOURNAL=off 로 전체 비활성.
"""

from __future__ import annotations

import json
import os
import time

SCHEMA = 1
MAX_BYTES = 10_000_000  # 초과 시 .1 로 1세대 로테이션 — 무한 성장 방지 (~5만 호출 분량)


def journal_path(root: str) -> str:
    return os.path.join(root, ".asgard", "state", "io-journal.jsonl")


def enabled() -> bool:
    return os.environ.get("ASGARD_IO_JOURNAL", "").lower() not in {"0", "off", "false"}


def _append(root: str, entry: dict) -> bool:
    try:
        os.makedirs(os.path.join(root, ".asgard", "state"), exist_ok=True)
        gi = os.path.join(root, ".asgard", ".gitignore")
        if not os.path.exists(gi):  # quest_dir 와 동일한 자가 설치 — 저널이 첫 기록자일 수 있다
            open(gi, "w").write("*\n")
        path = journal_path(root)
        try:
            if os.path.getsize(path) > MAX_BYTES:
                os.replace(path, path + ".1")
        except OSError:
            pass
        line = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(path, os.O_APPEND | os.O_WRONLY | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
        return True
    except Exception:
        return False  # fail-open


def _base(event: str, call_id: str) -> dict:
    return {
        "schema": SCHEMA,
        "event": event,
        "call_id": call_id,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def call_started(root: str, *, provider: str, model: str, transport: str, role: str | None = None) -> str | None:
    """호출 직전 기록. 반환된 call_id 를 call_returned 에 넘긴다 — None 이면 기록 억제."""
    if not enabled():
        return None
    cid = "%016x-%x" % (time.time_ns(), os.getpid())  # 시간순 정렬 가능
    entry = _base("started", cid)
    entry.update({"provider": provider, "model": model, "transport": transport})
    if role:
        entry["role"] = role
    return cid if _append(root, entry) else None


def call_returned(root: str, call_id: str | None, *, duration_ms: float, error: str | None = None, **counts) -> None:
    """호출 종료 기록 — counts 는 토큰 계측(0/None 은 생략). error 는 예외 요약 문자열."""
    if not call_id:
        return
    entry = _base("returned", call_id)
    entry["duration_ms"] = int(duration_ms)
    if error:
        entry["error"] = str(error)[:200]
    for key, value in counts.items():
        if value:
            entry[key] = int(value)
    _append(root, entry)
