"""튜터 인지적 항복 계측.

이 모듈은 답을 판정하지 않는다. 튜터 질문을 얼마나 빨리 닫았는지, 답 없이 남은 질문이 얼마나
쌓였는지, 한 답이 떠안은 변경 줄 수가 얼마나 큰지만 센다. 기록 실패는 작업을 막지 않는다.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass

from . import tutor_growth
from .io_files import read_json, write_json

SIGNALS = ("acceptance-latency", "unanswered-backlog", "review-ratio", "skip-streak", "session-load")

DEBT_REL = os.path.join(".asgard", "tutor", "debt.json")
VERSION = 1
LATENCY_FLOOR = 90.0  # 90초 미만은 주의, 절반 미만은 경고로 두어 빠를수록 단계를 높인다.
BACKLOG_WARN = 8  # 열린 질문이 한 화면을 넘기기 시작하는 첫 구간이라 놓치는 질문이 생긴다.
BACKLOG_ALARM = 20  # 재방문 사다리 여러 묶음이 밀린 상태라 사람이 직렬로 검토하기 어렵다.
REVIEW_LINES = 400  # Osmani의 PR 100줄 기준을 4배로 둬도 답 1건이 떠안기엔 이미 크다.
STREAK_WARN = 4  # tutor_growth.QUIET_AT과 같은 자리라 네 번째부터 질문이 닿지 않았다고 본다.
LOAD_TURNS = 12  # 다섯 번째 PR 무렵 검토가 약해진다는 관찰을 세션 턴으로 보수적으로 잡았다.


@dataclass(frozen=True)
class Signal:
    name: str
    level: int
    fact: str
    why: str
    source: str


@dataclass(frozen=True)
class Ledger:
    signals: tuple[Signal, ...]
    open_debt: int
    oldest_days: int
    turns: int
    added: int

    @property
    def level(self) -> int:
        return max((signal.level for signal in self.signals), default=0)

    @property
    def worst(self) -> Signal | None:
        return max(self.signals, key=lambda signal: signal.level, default=None)


def ledger(root: str, sid: str = "", now: float | None = None) -> Ledger:
    stamp = time.time() if now is None else now
    data = _load(root)
    session = _session(data, sid, stamp, _answer_times(root))
    _reconcile(root, session)
    _save(root, data)
    open_rows = _open_points(root)
    open_debt = len(open_rows)
    oldest_days = max((row.days(stamp) for row in open_rows), default=0)
    signals = (
        _latency_signal(session),
        _backlog_signal(open_debt, oldest_days),
        _review_signal(session),
        _skip_signal(root),
        _load_signal(session),
    )
    return Ledger(signals, open_debt, oldest_days, _int(session.get("turns")), _int(session.get("added")))


def note_turn(
    root: str,
    sid: str,
    files: int,
    added: int,
    removed: int,
    asked: int = 0,
    now: float | None = None,
) -> None:
    stamp = time.time() if now is None else now
    data = _load(root)
    session = _session(data, sid, stamp, _answer_times(root))
    _reconcile(root, session)
    session["turns"] = _int(session.get("turns")) + 1
    session["files"] = _int(session.get("files")) + max(0, int(files or 0))
    session["added"] = _int(session.get("added")) + max(0, int(added or 0))
    session["removed"] = _int(session.get("removed")) + max(0, int(removed or 0))
    session["asked"] = _int(session.get("asked")) + max(0, int(asked or 0))
    pending = _float_list(session.get("pending"))
    pending.extend([stamp] * max(0, int(asked or 0)))
    session["pending"] = pending[-200:]
    _save(root, data)


def expect(root: str, sid: str, text: str, now: float | None = None) -> str:
    stamp = time.time() if now is None else now
    body = " ".join(str(text or "").split())
    data = _load(root)
    key = _expect_key(data, sid, body, stamp)
    data["expects"][key] = {"key": key, "sid": str(sid or ""), "text": body, "at": stamp}
    _save(root, data)
    return key


def expectations(root: str, sid: str = "", open_only: bool = True) -> list[dict]:
    rows = []
    wanted = str(sid or "")
    for key, row in _load(root)["expects"].items():
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item.setdefault("key", key)
        if wanted and item.get("sid") != wanted:
            continue
        if open_only and item.get("verdict"):
            continue
        rows.append(item)
    rows.sort(key=lambda row: (_float(row.get("at")), str(row.get("key") or "")))
    return rows


def settle(root: str, key: str, verdict: str, now: float | None = None) -> tuple[bool, str]:
    stamp = time.time() if now is None else now
    data = _load(root)
    found = _resolve_expect(data, key)
    if found is None:
        return (False, f"열린 예상 중에 `{key}`로 시작하는 것이 없어요")
    full, row = found
    row["verdict"] = " ".join(str(verdict or "").split())
    row["settled_at"] = stamp
    data["expects"][full] = row
    if not _save(root, data):
        return (False, "예상을 닫지 못했어요")
    return (True, "예상을 닫았어요")


def _path(root: str) -> str:
    return os.path.join(root, DEBT_REL)


def _load(root: str) -> dict:
    data = read_json(_path(root), {})
    if not isinstance(data, dict):
        data = {}
    return {
        "version": VERSION,
        "sessions": data.get("sessions") if isinstance(data.get("sessions"), dict) else {},
        "expects": data.get("expects") if isinstance(data.get("expects"), dict) else {},
    }


def _save(root: str, data: dict) -> bool:
    try:
        data["version"] = VERSION
        write_json(_path(root), data, indent=2, sort_keys=True)
        return True
    except OSError, TypeError, ValueError:  # 저장 실패가 작업을 막으면 계측이 관문이 되므로 이 경계만 삼킨다.
        return False


def _session(data: dict, sid: str, stamp: float, answer_times: list[float]) -> dict:
    key = str(sid or "")
    session = data["sessions"].get(key)
    if not isinstance(session, dict):
        session = {
            "sid": key,
            "started": stamp,
            "turns": 0,
            "files": 0,
            "added": 0,
            "removed": 0,
            "asked": 0,
            "answered": 0,
            "answered_seen": len(answer_times),
            "pending": [],
            "latencies": [],
        }
        data["sessions"][key] = session
    session.setdefault("sid", key)
    session.setdefault("started", stamp)
    session.setdefault("answered_seen", len(answer_times))
    session.setdefault("pending", [])
    session.setdefault("latencies", [])
    return session


def _reconcile(root: str, session: dict) -> None:
    answer_times = _answer_times(root)
    seen = max(0, min(_int(session.get("answered_seen")), len(answer_times)))
    new_times = answer_times[seen:]
    if not new_times:
        session["answered_seen"] = len(answer_times)
        return
    pending = _float_list(session.get("pending"))
    latencies = _float_list(session.get("latencies"))
    for closed_at in new_times:
        if pending:
            opened_at = pending.pop(0)
            latencies.append(max(0.0, closed_at - opened_at))
    session["answered"] = _int(session.get("answered")) + len(new_times)
    session["answered_seen"] = len(answer_times)
    session["pending"] = pending[-200:]
    session["latencies"] = latencies[-200:]


def _answer_times(root: str) -> list[float]:
    closed = _growth(root).get("closed", [])
    return _float_list([row.get("at") for row in closed if isinstance(row, dict) and row.get("reason") == "answered"])


def _growth(root: str) -> dict:
    try:
        return tutor_growth.load(root)
    except TypeError, ValueError:  # 손상된 저장 스키마만 빈 기록으로 낮추고 계산 오류는 그대로 올린다.
        return {"version": tutor_growth.VERSION, "topics": {}, "open": {}, "closed": []}


def _open_points(root: str) -> list[tutor_growth.Revisit]:
    try:
        return tutor_growth.open_points(root)
    except TypeError, ValueError:  # 숫자 필드가 깨진 성장 기록은 계측을 막지 않되 다른 오류는 숨기지 않는다.
        return []


def _latency_signal(session: dict) -> Signal:
    latencies = _float_list(session.get("latencies"))
    if not latencies:
        return Signal(
            "acceptance-latency",
            0,
            "닫힌 답 0건이라 수용 속도를 아직 못 재요",
            "답을 너무 빨리 닫으면 모델의 확신을 자기 견해로 바꾼 흔적을 보기 어려워요",
            ".asgard/tutor/debt.json",
        )
    fastest = min(latencies)
    level = 2 if fastest < LATENCY_FLOOR / 2 else 1 if fastest < LATENCY_FLOOR else 0
    return Signal(
        "acceptance-latency",
        level,
        f"가장 빠른 답 닫힘은 {int(fastest)}초였어요",
        "답을 너무 빨리 닫으면 모델의 확신을 자기 견해로 바꾼 흔적을 보기 어려워요",
        ".asgard/tutor/debt.json",
    )


def _backlog_signal(open_debt: int, oldest_days: int) -> Signal:
    level = 2 if open_debt >= BACKLOG_ALARM else 1 if open_debt >= BACKLOG_WARN else 0
    return Signal(
        "unanswered-backlog",
        level,
        f"답 없는 물음 {open_debt}건, 가장 오래된 물음 {oldest_days}일이에요",
        "답 없는 물음이 쌓이면 모델이 낸 결론을 자기 말로 확인하는 일이 뒤로 밀려요",
        "tutor_growth.open_points",
    )


def _review_signal(session: dict) -> Signal:
    added = _int(session.get("added"))
    answered = _int(session.get("answered"))
    if answered <= 0:
        level = 2 if added >= REVIEW_LINES else 0
        fact = f"답한 물음 0건에 추가행 {added}줄이에요"
    else:
        ratio = added / answered
        level = 2 if ratio >= REVIEW_LINES * 2 else 1 if ratio >= REVIEW_LINES else 0
        fact = f"답한 물음 {answered}건당 추가행 비율은 {ratio:.1f}줄이에요"
    return Signal(
        "review-ratio",
        level,
        fact,
        "검토 단위가 이해 단위라서 답 1건이 너무 많은 줄을 떠안으면 자기 견해를 만들기 어려워요",
        ".asgard/tutor/debt.json",
    )


def _skip_signal(root: str) -> Signal:
    topics = _growth(root).get("topics", {})
    worst_kind = ""
    worst = 0
    for kind, row in topics.items() if isinstance(topics, dict) else ():
        if not isinstance(row, dict) or _int(row.get("deep")) > 0:
            continue
        skipped = _int(row.get("skipped"))
        if skipped > worst:
            worst_kind, worst = str(kind), skipped
    level = 2 if worst >= STREAK_WARN * 2 else 1 if worst >= STREAK_WARN else 0
    label = f"`{worst_kind}` " if worst_kind else ""
    return Signal(
        "skip-streak",
        level,
        f"가장 긴 연속 건너뜀은 {label}{worst}번이에요",
        "같은 종류를 계속 건너뛰면 답을 자기 언어로 묶는 일이 비어 있었다는 뜻이에요",
        "tutor_growth.topics",
    )


def _load_signal(session: dict) -> Signal:
    turns = _int(session.get("turns"))
    level = 2 if turns >= LOAD_TURNS * 2 else 1 if turns >= LOAD_TURNS else 0
    return Signal(
        "session-load",
        level,
        f"이 세션 누적 턴은 {turns}턴이에요",
        "세션이 길어질수록 피로 때문에 검토를 줄이고 모델 판단을 그대로 받을 가능성이 커져요",
        ".asgard/tutor/debt.json",
    )


def _expect_key(data: dict, sid: str, text: str, stamp: float) -> str:
    seed = f"{sid}|{text}|{stamp}"
    for index in range(100):
        key = hashlib.sha256(f"{seed}|{index}".encode()).hexdigest()[:8]
        if key not in data["expects"]:
            return key
    return hashlib.sha256(f"{seed}|overflow".encode()).hexdigest()[:8]


def _resolve_expect(data: dict, key: str) -> tuple[str, dict] | None:
    raw = str(key or "").strip().lower()
    if not raw:
        return None
    hits = [(k, v) for k, v in data["expects"].items() if k.startswith(raw) and isinstance(v, dict)]
    return hits[0] if len(hits) == 1 else None


def _int(raw: object) -> int:
    if not raw:
        return 0
    if not isinstance(raw, int | float | str):  # 저장 스키마가 깨져 수가 아닌 값이 온 자리
        return 0
    try:
        return int(raw)
    except TypeError, ValueError:
        return 0


def _float_list(raw: object) -> list[float]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        value = _float(item, None)
        if value is not None:
            out.append(value)
    return out


def _float(raw: object, default: float | None = 0.0) -> float | None:
    if not raw:
        return 0.0
    if not isinstance(raw, int | float | str):
        return default
    try:
        return float(raw)
    except TypeError, ValueError:
        return default
