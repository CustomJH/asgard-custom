"""도중 개입·서사 되짚기 — 작업 중 한 번 놓는 팁과 세션·하루·한 주의 서사.

`review` 가 이번 변경 하나를 보는 자리라면 여기는 그 위로 쌓인 것을 본다: 답 없이 남은 물음,
부채 계측(`tutor_debt`)이 잡은 신호, 구간 안에서 닫힌 물음.
"""

from __future__ import annotations

import importlib
import os
import time

from .. import tutor_growth
from ..io_files import read_json, write_json
from .labels import _folded_line

# 늦게 읽는 엔진은 이 패키지 밖, 한 단 위(`asgard`)에 있다 — `tutor` 가 패키지가 되면서
# `__package__` 가 `asgard.tutor` 로 한 단 깊어졌다. 기준을 `__name__` 으로 잡는 이유는
# `__package__` 가 `str | None` 이라 타입 검사기가 `.rsplit` 을 거절하기 때문이다.
_ENGINES = __name__.rsplit(".", 2)[0]

TIPS_REL = os.path.join(".asgard", "tutor", "tips.json")
_SIGNAL_LABEL = {
    "acceptance-latency": "답 수용 속도",
    "unanswered-backlog": "답 없는 물음",
    "review-ratio": "검토 비율",
    "skip-streak": "연속 건너뜀",
    "session-load": "세션 부하",
}
_TIP_ASK = {
    "acceptance-latency": "방금 받아들인 답을 반대로 깨뜨리는 예를 하나 떠올려 보셨나요?",
    "unanswered-backlog": "계속 진행하기 전에 답 없는 물음 하나를 골라 직접 설명해 볼까요?",
    "review-ratio": "가장 큰 변경 하나를 열고, 왜 이렇게 됐는지 말로 다시 확인해 볼까요?",
    "skip-streak": "이 물음은 정말 버릴 물음인가요, 아니면 지금 닫을 답이 있나요?",
    "session-load": "다음 변경 전에 지금까지의 결정을 한 줄로 다시 말해 볼까요?",
}
_SPAN_LABEL = {"session": "이번 세션", "day": "오늘", "week": "이번 주"}
_SPAN_DAYS = {"day": 1.0, "week": 7.0}


def tips(root: str, sid: str = "", cap: int = 1, now: float | None = None) -> list[str]:
    """작업 **도중** 놓을 팁. 없으면 빈 목록 — 대부분의 턴은 빈 목록이어야 한다."""
    try:
        limit = max(0, int(cap))
    except TypeError, ValueError:
        return []
    if limit <= 0:
        return []
    ledger = _debt_ledger(root, sid, now)
    seen = _tips_seen(root, sid)
    signals = [s for s in _active_signals(ledger) if _signal_name(s) not in seen]
    picked = signals[:limit]
    if not picked:
        return []
    _tips_mark(root, sid, [_signal_name(s) for s in picked])
    return [_tip_card(s) for s in picked]


def recap(root: str, sid: str = "", span: str = "session", now: float | None = None) -> str:
    """세션/일 단위 서사. span = "session" | "day" | "week". 없으면 빈 문자열."""
    name = str(span or "session")
    if name not in _SPAN_LABEL:
        return ""
    stamp = time.time() if now is None else now
    ledger = _debt_ledger(root, sid, stamp)
    data = tutor_growth.load(root)
    closed = _closed_in_span(data, name, stamp)
    open_rows = tutor_growth.open_points(root)
    if not _recap_has_material(ledger, closed, open_rows, name == "session"):
        return ""
    work_ledger = ledger if name == "session" else None
    parts = [_recap_work(_SPAN_LABEL[name], work_ledger, closed), _recap_open(open_rows, ledger, stamp)]
    debt = _recap_debt(ledger)
    if debt:
        parts.append(debt)
    return "\n\n".join(p for p in parts if p)


def _debt_ledger(root: str, sid: str, now: float | None):
    """부채 계측은 늦게 읽는다 — 같은 시각에 만드는 모듈이 없어도 튜터 시작은 깨지면 안 된다."""
    try:
        module = importlib.import_module(f"{_ENGINES}.tutor_debt")
        return module.ledger(root, sid, now)
    except Exception:
        return None


def _active_signals(ledger: object) -> list[object]:
    rows = []
    for signal in getattr(ledger, "signals", ()) or ():
        if _signal_name(signal) and _signal_level(signal) > 0:
            rows.append(signal)
    return sorted(rows, key=lambda s: (-_signal_level(s), _signal_name(s)))


def _signal_name(signal: object) -> str:
    return str(getattr(signal, "name", "") or "")


def _signal_level(signal: object) -> int:
    try:
        return int(getattr(signal, "level", 0) or 0)
    except TypeError, ValueError:
        return 0


def _tip_card(signal: object) -> str:
    name = _signal_name(signal)
    fact = " ".join(str(getattr(signal, "fact", "") or "").split())
    head = f"⠶ 도중 점검 — {_SIGNAL_LABEL.get(name, name)}"
    if fact:
        head += f": {fact}"
    ask = _TIP_ASK.get(name, "이 신호를 보고 지금 사람이 직접 확인해야 할 판단은 무엇인가요?")
    return f"{head}\n    ▸ {ask}"


def _tips_path(root: str) -> str:
    return os.path.join(root, TIPS_REL)


def _sid(sid: str) -> str:
    return str(sid or "").strip() or "(default)"


def _tips_seen(root: str, sid: str) -> set[str]:
    data = read_json(_tips_path(root), {})
    sessions = data.get("sessions") if isinstance(data, dict) else {}
    row = sessions.get(_sid(sid), []) if isinstance(sessions, dict) else []
    return {str(name) for name in row} if isinstance(row, list) else set()


def _tips_mark(root: str, sid: str, names: list[str]) -> None:
    data = read_json(_tips_path(root), {})
    if not isinstance(data, dict):
        data = {}
    sessions = data.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        sessions = {}
        data["sessions"] = sessions
    key = _sid(sid)
    row = sessions.get(key, [])
    seen = {str(name) for name in row if name} if isinstance(row, list) else set()
    seen.update(names)
    sessions[key] = sorted(seen)
    data["version"] = 1
    try:
        write_json(_tips_path(root), data)
    except OSError:
        pass  # 못 적었으면 같은 팁이 한 번 더 나올 수 있다 — 기록 실패가 작업을 막으면 안 된다


def _closed_in_span(data: dict, span: str, stamp: float) -> list[dict]:
    rows = [r for r in data.get("closed", []) if isinstance(r, dict)]
    if span == "session":
        return []
    cutoff = stamp - _SPAN_DAYS[span] * tutor_growth.DAY
    return [r for r in rows if _row_float(r, "at") >= cutoff]


def _row_float(row: dict, name: str) -> float:
    try:
        return float(row.get(name) or 0.0)
    except TypeError, ValueError:
        return 0.0


def _recap_has_material(
    ledger: object, closed: list[dict], open_rows: list[tutor_growth.Revisit], include_work: bool
) -> bool:
    if closed or open_rows or _active_signals(ledger):
        return True
    names = ("open_debt", "oldest_days", "turns", "added") if include_work else ("open_debt", "oldest_days")
    return any(_ledger_int(ledger, name) for name in names)


def _ledger_int(ledger: object, name: str) -> int:
    try:
        return int(getattr(ledger, name, 0) or 0)
    except TypeError, ValueError:
        return 0


def _recap_work(label: str, ledger: object, closed: list[dict]) -> str:
    turns, added = _ledger_int(ledger, "turns"), _ledger_int(ledger, "added")
    if turns or added:
        return (
            f"⠶ 되짚기 — {label}에는 튜터가 {turns}턴을 보았고, 변경은 +{added:,}행까지 쌓였어요. "
            "닫힌 물음은 세션별로 나뉘어 있지 않아서, 아래에는 지금 남은 것과 부채 신호를 중심으로 적어요."
        )
    if closed:
        kinds = _kind_summary([str(r.get("kind") or "") for r in closed])
        return f"⠶ 되짚기 — {label}에는 물음 {len(closed)}건이 닫혔어요. 최근에는 {kinds} 쪽을 처리했어요."
    return f"⠶ 되짚기 — {label}에 새로 닫힌 물음은 아직 확인하지 못했어요. 그래서 남은 질문을 먼저 봐요."


def _recap_open(open_rows: list[tutor_growth.Revisit], ledger: object, stamp: float) -> str:
    if open_rows:
        oldest = min(open_rows, key=lambda r: r.opened)
        return (
            f"⠶ 답 없이 남은 것 — 열린 물음 {len(open_rows)}건이 그대로 남아 있어요. "
            f"가장 오래된 것은 {oldest.where}에서 {oldest.days(stamp)}일째 기다리고 있고, "
            f'질문은 "{oldest.ask}"예요.'
        )
    debt = _ledger_int(ledger, "open_debt")
    if debt:
        days = _ledger_int(ledger, "oldest_days")
        return (
            f"⠶ 답 없이 남은 것 — 계측에는 답 없는 물음 {debt}건이 잡혔지만 좌표 기록은 못 읽었어요. "
            f"가장 오래된 것은 {days}일째 남아 있어요."
        )
    return "⠶ 답 없이 남은 것 — 지금 열린 물음은 없어요. 기록에 안 드러난 채 남은 물음도 없다는 뜻이에요."


def _recap_debt(ledger: object) -> str:
    if ledger is None:
        return "⠶ 부채 위치 — 부채 계측을 읽지 못했어요. 못 본 값을 0으로 적지 않고 이 구간은 비워 둬요."
    signals = _active_signals(ledger)
    if not signals:
        return "⠶ 부채 위치 — 지금 경고 신호는 없어요. 그래도 새 물음이 생기면 답을 숨기지 않고 남겨 둬야 해요."
    signal = signals[0]
    name, fact = _signal_name(signal), " ".join(str(getattr(signal, "fact", "") or "").split())
    source = " ".join(str(getattr(signal, "source", "") or "").split())
    why = " ".join(str(getattr(signal, "why", "") or "").split())
    # 경로 뒤에 서술어를 붙이지 않는다 — `debt.json예요` 는 파일명의 일부처럼 읽히고, 사람이
    # 그 자리를 복사해 열 때 조사까지 딸려 간다. 좌표는 좌표로 끝낸다.
    tail = f" 출처: {source}." if source else ""
    if why:
        tail += f" 근거는 {why}" + ("" if why.endswith((".", "?", "!")) else ".")
    return (
        f"⠶ 부채 위치 — 지금 가장 큰 신호는 {_SIGNAL_LABEL.get(name, name)} 쪽이에요"
        + (f": {fact}." if fact else ".")
        + tail
        + " 여기서 답을 정하지 말고, 사람이 다시 설명할 수 있는지 먼저 확인해요."
    )


def _kind_summary(kinds: list[str]) -> str:
    counts: dict[str, int] = {}
    for kind in kinds:
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    return _folded_line(counts) if counts else "종류 없는 물음"
