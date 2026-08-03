"""프로젝트 자동화 — 무엇이 지금 due인지 판단하고 실행 결과를 적는 작은 엔진.

이 레인은 데몬이 아니다. 백그라운드 프로세스를 조용히 띄워 놓고 죽지 않았다고 믿게 만들면
자동화가 없는 것보다 나쁘다. 여기서는 **무엇이 due인가**만 결정하고, **언제 물을 것인가**는
cron·launchd·Task Scheduler 같은 운영체제 스케줄러가 `asgard automations due --run`을
호출해 맡는다. 데몬이 없다는 사실을 숨기지 않는 것이 이 레인이 사용자에게 지는 정직성이다.

저장은 이 프로젝트의 `.asgard/automations.json` 한 파일이다. 이웃한 기획 저장소처럼
`io_files`의 fail-open JSON 읽기와 원자적 쓰기를 그대로 쓴다. 읽을 수 없거나 계약이 깨진
파일은 자동화를 하나도 승인하지 않은 상태로 본다 — 파생 실행 장부 하나 때문에 CLI가
죽거나, 검증하지 못한 프롬프트를 실행하는 쪽보다 안전하다.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .io_files import read_json, write_json

SCHEMA_VERSION = 1
STATE_FILE = "automations.json"
NAMED_SCHEDULES = ("hourly", "daily", "weekdays", "weekly")

_MAX_NAME = 100
_MAX_PROMPT = 32_000
_CRON_LOOKBACK_DAYS = 8 * 366  # 윤일도 세기 경계에서 최대 8년 안에는 다시 온다.
_LOCK = threading.Lock()


@dataclass(frozen=True)
class Cron:
    """검증을 마친 5-field cron. 날짜의 DOM/DOW 결합 규칙도 여기 한 곳에 둔다."""

    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    day_wildcard: bool
    weekday_wildcard: bool

    def matches_date(self, value: date) -> bool:
        if value.month not in self.months:
            return False
        day = value.day in self.days
        weekday = ((value.weekday() + 1) % 7) in self.weekdays  # cron: 일요일=0
        if self.day_wildcard:
            return weekday
        if self.weekday_wildcard:
            return day
        return day or weekday  # Vixie cron 계약: 두 필드가 제한되면 OR


def state_path(root: str | Path) -> Path:
    return Path(root).resolve() / ".asgard" / STATE_FILE


def normalize_schedule(value: str) -> str:
    """사람이 준 별칭 또는 cron을 저장할 한 모양으로 바꾸고, 틀리면 거부한다."""
    text = " ".join(str(value or "").lower().split())
    if text in NAMED_SCHEDULES:
        return text
    parse_cron(text)
    return text


def parse_cron(value: str) -> Cron:
    """5-field cron을 stdlib 집합으로 푼다 — 목록·범위·step까지가 지원 계약이다."""
    fields = str(value or "").split()
    if len(fields) != 5:
        raise ValueError("schedule은 hourly/daily/weekdays/weekly 또는 5-field cron이어야 해요")
    minute, hour, day, month, weekday = fields
    minutes, _ = _field(minute, 0, 59)
    hours, _ = _field(hour, 0, 23)
    days, day_wildcard = _field(day, 1, 31)
    months, _ = _field(month, 1, 12)
    weekdays, weekday_wildcard = _field(weekday, 0, 7, weekday=True)
    cron = Cron(minutes, hours, days, months, weekdays, day_wildcard, weekday_wildcard)
    if (
        weekday_wildcard
        and not day_wildcard
        and not any(wanted <= _month_days(month_value) for month_value in months for wanted in days)
    ):
        raise ValueError("그 cron은 달력에 존재하는 날짜를 가리키지 않아요")
    return cron


def _field(value: str, low: int, high: int, *, weekday: bool = False) -> tuple[frozenset[int], bool]:
    if not value:
        raise ValueError("cron field가 비어 있어요")
    out: set[int] = set()
    for part in value.split(","):
        if not part:
            raise ValueError("cron 목록에 빈 값이 있어요")
        base, slash, step_text = part.partition("/")
        try:
            step = int(step_text) if slash else 1
        except ValueError as exc:
            raise ValueError(f"cron step이 숫자가 아니에요: {part}") from exc
        if step < 1:
            raise ValueError("cron step은 1 이상이어야 해요")
        if base == "*":
            start, stop = low, high
        elif "-" in base:
            left, right = base.split("-", 1)
            try:
                start, stop = int(left), int(right)
            except ValueError as exc:
                raise ValueError(f"cron 범위가 잘못됐어요: {part}") from exc
        else:
            try:
                start = int(base)
            except ValueError as exc:
                raise ValueError(f"cron 값이 숫자가 아니에요: {part}") from exc
            stop = high if slash else start
        if start < low or stop > high or start > stop:
            raise ValueError(f"cron 값이 범위를 벗어났어요: {part}")
        out.update(range(start, stop + 1, step))
    if weekday and 7 in out:
        out.remove(7)
        out.add(0)
    return frozenset(out), value == "*"


def _month_days(month: int) -> int:
    if month == 2:
        return 29
    return 30 if month in {4, 6, 9, 11} else 31


def due(entry: dict[str, Any], now: datetime) -> bool:
    """이 항목이 지금 due인가 — 저장도 실행도 하지 않는 순수 판정 함수."""
    _aware(now)
    if not entry.get("enabled"):
        return False
    schedule = normalize_schedule(str(entry.get("schedule") or ""))
    baseline = _timestamp(entry.get("last_run") or entry.get("created_at")).astimezone(now.tzinfo)
    if baseline >= now:
        return False
    if schedule == "hourly":
        return baseline.replace(minute=0, second=0, microsecond=0) < now.replace(minute=0, second=0, microsecond=0)
    if schedule == "daily":
        return baseline.date() < now.date()
    if schedule == "weekdays":
        return now.weekday() < 5 and baseline.date() < now.date()
    if schedule == "weekly":
        return _week_start(baseline) < _week_start(now)
    return _cron_due(parse_cron(schedule), baseline, now)


def due_automations(entries: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """due 항목만 입력 순서대로 돌려준다. 호출자는 파일이나 실행기를 몰라도 된다."""
    return [copy.deepcopy(entry) for entry in entries if due(entry, now)]


def _cron_due(cron: Cron, baseline: datetime, now: datetime) -> bool:
    """마지막 실행 뒤의 가장 최근 cron minute가 있는지 날짜 단위로 거슬러 찾는다."""
    today = now.date()
    span = min((today - baseline.date()).days, _CRON_LOOKBACK_DAYS)
    for offset in range(span + 1):
        day = today - timedelta(days=offset)
        if not cron.matches_date(day):
            continue
        for hour in sorted(cron.hours, reverse=True):
            for minute in sorted(cron.minutes, reverse=True):
                moment = datetime.combine(day, time(hour, minute), tzinfo=now.tzinfo)
                if baseline < moment <= now:
                    return True
    return False


def _week_start(value: datetime) -> date:
    return value.date() - timedelta(days=value.weekday())


def load_state(root: str | Path) -> dict[str, Any]:
    """없거나 손상된 파일은 빈 상태다 — 읽기 때문에 자동화 명령 전체가 죽지 않는다."""
    with _LOCK:
        return copy.deepcopy(_load_state(root))


def list_automations(root: str | Path) -> list[dict[str, Any]]:
    return load_state(root)["automations"]


def add(root: str | Path, name: str, prompt: str, schedule: str, now: datetime) -> dict[str, Any]:
    """명시적인 add만 실행 가능한 항목을 만든다. 파일 발견이나 프롬프트 추측 경로는 없다."""
    _aware(now)
    clean_name = " ".join(str(name or "").split())
    clean_prompt = str(prompt or "").strip()
    if not clean_name or len(clean_name) > _MAX_NAME:
        raise ValueError(f"name은 1..{_MAX_NAME}자여야 해요")
    if not clean_prompt or len(clean_prompt) > _MAX_PROMPT:
        raise ValueError(f"prompt는 1..{_MAX_PROMPT}자여야 해요")
    normalized = normalize_schedule(schedule)
    with _LOCK:
        state = _load_state(root)
        if any(row["name"].casefold() == clean_name.casefold() for row in state["automations"]):
            raise ValueError(f"이미 같은 이름의 자동화가 있어요: {clean_name}")
        entry = {
            "id": uuid4().hex,
            "name": clean_name,
            "prompt": clean_prompt,
            "schedule": normalized,
            "enabled": True,
            "created_at": _iso(now),
            "last_run": None,
            "last_outcome": None,
        }
        state["automations"].append(entry)
        _write_state(root, state)
        return copy.deepcopy(entry)


def remove(root: str | Path, name: str) -> dict[str, Any] | None:
    with _LOCK:
        state = _load_state(root)
        index = _find(state, name)
        if index is None:
            return None
        entry = state["automations"].pop(index)
        _write_state(root, state)
        return copy.deepcopy(entry)


def set_enabled(root: str | Path, name: str, enabled: bool) -> dict[str, Any] | None:
    with _LOCK:
        state = _load_state(root)
        index = _find(state, name)
        if index is None:
            return None
        state["automations"][index]["enabled"] = bool(enabled)
        _write_state(root, state)
        return copy.deepcopy(state["automations"][index])


def history(root: str | Path, name: str = "", limit: int = 20) -> list[dict[str, Any]]:
    rows = load_state(root)["history"]
    if name:
        rows = [row for row in rows if row["name"].casefold() == name.casefold()]
    return list(reversed(rows))[: max(1, limit)]


def run_due(
    root: str | Path,
    now: datetime,
    executor: Callable[[str], int],
    clock: Callable[[], datetime],
) -> list[dict[str, Any]]:
    """지금 due인 항목을 기존 실행기에 하나씩 넘기고, 시작과 최종 판정을 모두 적는다.

    시작 전에 `running`을 먼저 쓰는 것이 핵심이다. 프로세스가 실행 중 죽으면 성공이나 이전
    실패가 마지막 결과로 남아 조용히 거짓말하지 않고, 끝나지 않은 실행으로 남는다.
    """
    _aware(now)
    candidates = due_automations(list_automations(root), now)
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        started = clock()
        _aware(started)
        run_id = uuid4().hex
        if not _begin(root, candidate["id"], run_id, started, now):
            continue
        try:
            code = int(executor(candidate["prompt"]))
            outcome = _finish(root, candidate, run_id, clock(), "succeeded" if code == 0 else "failed", code)
        except KeyboardInterrupt:
            _finish(root, candidate, run_id, clock(), "interrupted", 130)
            raise
        except Exception as exc:
            outcome = _finish(root, candidate, run_id, clock(), "failed", 1, f"{type(exc).__name__}: {exc}")
        results.append(outcome)
    return results


def _begin(root: str | Path, automation_id: str, run_id: str, started: datetime, due_at: datetime) -> bool:
    with _LOCK:
        state = _load_state(root)
        entry = next((row for row in state["automations"] if row["id"] == automation_id), None)
        if entry is None or not due(entry, due_at):
            return False
        outcome = {"status": "running", "started_at": _iso(started)}
        entry["last_run"] = outcome["started_at"]
        entry["last_outcome"] = outcome
        state["history"].append({"id": run_id, "automation_id": automation_id, "name": entry["name"], **outcome})
        _write_state(root, state)
        return True


def _finish(
    root: str | Path,
    candidate: dict[str, Any],
    run_id: str,
    finished: datetime,
    status: str,
    exit_code: int,
    error: str = "",
) -> dict[str, Any]:
    _aware(finished)
    with _LOCK:
        state = _load_state(root)
        entry = next((row for row in state["automations"] if row["id"] == candidate["id"]), None)
        row = next((row for row in state["history"] if row["id"] == run_id), None)
        outcome: dict[str, Any] = {
            "status": status,
            "started_at": row["started_at"] if row is not None else _iso(finished),
            "exit_code": exit_code,
            "finished_at": _iso(finished),
        }
        if error:
            outcome["error"] = error[:500]
        if entry is not None:
            entry["last_outcome"] = outcome
        if row is not None:
            row.update(outcome)
        _write_state(root, state)
    return {"id": run_id, "automation_id": candidate["id"], "name": candidate["name"], **outcome}


def _find(state: dict[str, Any], name: str) -> int | None:
    wanted = str(name or "").strip().casefold()
    return next((index for index, row in enumerate(state["automations"]) if row["name"].casefold() == wanted), None)


def _load_state(root: str | Path) -> dict[str, Any]:
    try:
        return _validate_state(read_json(str(state_path(root)), None))
    except TypeError, ValueError:
        return _empty_state()


def _write_state(root: str | Path, state: dict[str, Any]) -> None:
    write_json(str(state_path(root)), _validate_state(state), indent=2)


def _empty_state() -> dict[str, Any]:
    return {"schema": SCHEMA_VERSION, "automations": [], "history": []}


def _validate_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA_VERSION:
        raise ValueError("automation state schema가 달라요")
    automations, history_rows = raw.get("automations"), raw.get("history")
    if not isinstance(automations, list) or not isinstance(history_rows, list):
        raise ValueError("automation state가 목록을 잃었어요")
    clean, ids, names = [], set(), set()
    for row in automations:
        entry = _validate_entry(row)
        if entry["id"] in ids or entry["name"].casefold() in names:
            raise ValueError("automation id 또는 name이 겹쳐요")
        ids.add(entry["id"])
        names.add(entry["name"].casefold())
        clean.append(entry)
    history = [_validate_history(row) for row in history_rows]
    return {"schema": SCHEMA_VERSION, "automations": clean, "history": history}


def _validate_entry(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("automation entry는 object여야 해요")
    automation_id, name, prompt = row.get("id"), row.get("name"), row.get("prompt")
    if not isinstance(automation_id, str) or not automation_id or len(automation_id) > 64:
        raise ValueError("automation id가 잘못됐어요")
    if not isinstance(name, str) or not name.strip() or len(name) > _MAX_NAME:
        raise ValueError("automation name이 잘못됐어요")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > _MAX_PROMPT:
        raise ValueError("automation prompt가 잘못됐어요")
    if type(row.get("enabled")) is not bool:
        raise ValueError("automation enabled가 bool이 아니에요")
    created = row.get("created_at")
    _timestamp(created)
    last_run = row.get("last_run")
    if last_run is not None:
        _timestamp(last_run)
    outcome = row.get("last_outcome")
    if outcome is not None:
        outcome = _validate_outcome(outcome)
        if last_run is None:
            raise ValueError("automation outcome에는 last_run이 있어야 해요")
    return {
        "id": automation_id,
        "name": name.strip(),
        "prompt": prompt.strip(),
        "schedule": normalize_schedule(str(row.get("schedule") or "")),
        "enabled": row["enabled"],
        "created_at": _iso(_timestamp(created)),
        "last_run": _iso(_timestamp(last_run)) if last_run is not None else None,
        "last_outcome": outcome,
    }


def _validate_history(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("automation history는 object여야 해요")
    required = ("id", "automation_id", "name", "status", "started_at")
    if not all(isinstance(row.get(key), str) and row[key] for key in required):
        raise ValueError("automation history 필드가 비었어요")
    if row["status"] not in {"running", "succeeded", "failed", "interrupted"}:
        raise ValueError("automation history status가 잘못됐어요")
    _timestamp(row["started_at"])
    if row["status"] != "running":
        if type(row.get("exit_code")) is not int:
            raise ValueError("끝난 automation history에 exit_code가 없어요")
        _timestamp(row.get("finished_at"))
    return copy.deepcopy(row)


def _validate_outcome(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("status") not in {
        "running",
        "succeeded",
        "failed",
        "interrupted",
    }:
        raise ValueError("automation outcome이 잘못됐어요")
    _timestamp(value.get("started_at"))
    if value["status"] != "running":
        if type(value.get("exit_code")) is not int:
            raise ValueError("끝난 automation outcome에 exit_code가 없어요")
        _timestamp(value.get("finished_at"))
    return copy.deepcopy(value)


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("시간이 비어 있어요")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("시간 형식이 잘못됐어요") from exc
    _aware(parsed)
    return parsed


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("시간에는 timezone이 있어야 해요")


def _iso(value: datetime) -> str:
    _aware(value)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
