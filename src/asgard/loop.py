"""loop — 컨트롤러. 센서가 잰 오차를 **다음 한 걸음**으로 바꾼다.

왜 `health` 안이 아닌가. 센서와 컨트롤러는 다른 부품이다. `health` 는 "지금 어떤가"를 재고
아무것도 고르지 않는다 — 그 모듈의 명시 계약이다. 고르는 일에는 판단이 들어가고, 판단은
튜닝 대상이다. 측정과 같은 파일에 있으면 문턱을 만질 때마다 측정값이 따라 움직이는 것처럼
보인다. 그래서 여기서 고른다.

**set point.** 컨트롤러는 오차 없이 못 돈다. 오차는 목표가 있어야 존재하고, `health` 의 추세
(두 스냅샷의 차)는 오차가 아니라 방향일 뿐이다. 기본 목표는 **이 나무가 기록한 가장 좋은
값**이다. 사람이 숫자를 지어낼 필요가 없고, 설정이 비어도 계층이 돈다. 이것은 `craft` 의
래칫을 나무 수준으로 올린 것이다 — `craft` 는 "이번 변경이 더 나쁘게 만든 것"을 막고,
여기는 "이 나무가 한 번 도달했던 곳"으로 되돌린다. 설정이 있으면 설정이 이긴다.

**선택 규칙은 위험 최소다.** 점수는 하나뿐이다:

    점수 = 값 / 위험 = (지표 상대오차 × 변경빈도 가중) / **이 걸음을 검증하려고 사람이 읽어야 하는 줄 수**

분모가 이 모듈의 요지다. 큰 것부터 고치는 컨트롤러는 리뷰 불가능한 걸음을 루프에 넣는다 —
그게 정확히 blind 루프가 4만 줄 PR 을 만드는 경로다. 읽을 줄 수로 나누면 "같은 지표를 같은
크기만큼 움직이는 후보 중 가장 작은 것"이 저절로 이긴다. 분자의 변경빈도는 핫스팟 분석
(복잡 × 빈번 = 결함 확률 최선 예측자)에서 온다 — 안 건드리는 파일을 예쁘게 만드는 것은
값이 없다.

걸음 종류를 나누는 이유도 같다. 함수 추출은 파일 안에서 끝나 호출부가 안 움직이고, 모듈
분할은 import 를 따라 밖으로 번진다. 둘을 같은 줄자로 재면 컨트롤러가 위험을 못 본다.

**못 본 것은 못 봤다고 적는다.** 목표를 받았지만 후보를 못 내는 지표(`cycles` — 개수만 알고
순환 경로를 모른다)는 `undetermined` 로 싣는다. 0 건이 "안 봤다"를 뜻하면 컨트롤러가 아니라
알리바이다 (`thor_gate`·`health.borrowed` 와 같은 규약).

**아무것도 막지 않는다.** `health` 와 같은 등급이다. 컨트롤러는 제안만 하고, 적용은 액추에이터
(사람이든 에이전트든)의 몫이며, 적용된 변경은 `craft` 래칫과 `tutor` 되짚기를 그대로 지난다.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

from . import craft_rules, health, settings
from .io_files import read_json, write_json

SIGNAL_PATH = ("health", "next.json")

# 걸음 종류 — 이름이 곧 "무엇이 움직이는가"다.
EXTRACT = "extract"  # 파일 안에서 끝난다. 호출부 불변.
SPLIT = "split"  # 모듈을 가른다. import 가 따라 움직인다.
DEDUPE = "dedupe"  # 복제를 합친다. 여러 파일이 함께 움직인다.
DECOUPLE = "decouple"  # 의존 방향을 바꾼다. 가장 멀리 번진다.

# 지표 → 그 지표를 움직이는 걸음. 여기 없는 지표는 후보를 못 낸다.
METRIC_STEP = {
    "big_units": EXTRACT,
    "deep_units": EXTRACT,
    "severe_files": SPLIT,
    "big_files": SPLIT,
    "dup_share": DEDUPE,
    "max_fan_in": DECOUPLE,
    "max_fan_out": DECOUPLE,
}
# 목표는 받되 후보를 못 내는 지표와 그 사유 — 조용히 빠지면 "깨끗하다"로 읽힌다.
NO_CANDIDATES = {
    "cycles": "순환 개수만 발행되고 순환 경로가 없다 — 지목할 자리를 못 만든다",
}

MAX_SURVEY_FILES = 4000  # 후보 조사 상한 — 초과분은 잘린 사실로 싣는다
MAX_RUNNERS_UP = 5


@dataclass(frozen=True)
class Target:
    """set point 1개와 그에 대한 measured error."""

    metric: str
    current: float
    target: float
    source: str  # "설정" | "기록 최선"

    @property
    def error(self) -> float:
        return round(self.current - self.target, 4)

    @property
    def rel_error(self) -> float:
        """상대 오차 — 척도가 다른 지표를 한 줄에 세우려면 정규화가 필요하다."""
        base = self.target if self.target > 0 else 1.0
        return round(max(0.0, self.current - self.target) / base, 4)


@dataclass(frozen=True)
class Candidate:
    """다음 걸음 후보 1개. `read` 가 위험이고, 점수의 분모다."""

    metric: str
    step: str
    path: str
    unit: str
    line: int
    size: int  # 이 걸음이 건드리는 크기 (함수 행 수 / 파일 행 수 / 복제 행 수)
    read: int  # **검증하려고 사람이 읽어야 하는 줄 수** = 위험
    churn: int
    value: float
    score: float
    why: str

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}" + (f" {self.unit}" if self.unit else "")


@dataclass(frozen=True)
class Signal:
    """control signal — 액추에이터에게 보내는 것 전부."""

    commit: str
    targets: tuple[Target, ...]
    picked: tuple[Candidate, ...]
    runners_up: tuple[Candidate, ...]
    undetermined: tuple[tuple[str, str], ...]

    @property
    def actionable(self) -> bool:
        return bool(self.picked)


# ── set point ──────────────────────────────────────────────────────


def _configured(root: str) -> dict:
    raw = settings.section("health", root).get("targets")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        name = str(key)
        if name not in health._WORSE_WHEN_UP:
            continue
        try:
            out[name] = float(value)
        except TypeError, ValueError:
            continue
    return out


def best_recorded(root: str) -> dict:
    """이력에서 각 지표의 최선값. 기록이 없으면 빈 dict — 목표를 지어내지 않는다."""
    rows = health._history(root)
    if not rows:
        return {}
    out: dict[str, float] = {}
    for metric in health._WORSE_WHEN_UP:
        seen = [float(row[metric]) for row in rows if isinstance(row.get(metric), (int, float))]
        if seen:
            out[metric] = min(seen)
    return out


def targets(root: str, snap: health.Snapshot) -> tuple[Target, ...]:
    """현재 상태 대비 set point. 오차가 0 이하인 지표는 싣지 않는다 — 할 일이 없다."""
    configured, recorded = _configured(root), best_recorded(root)
    current = asdict(snap)
    out: list[Target] = []
    for metric in health._WORSE_WHEN_UP:
        if metric in configured:
            goal, source = configured[metric], "설정"
        elif metric in recorded:
            goal, source = recorded[metric], "기록 최선"
        else:
            continue
        now = float(current.get(metric) or 0)
        if now <= goal:
            continue
        out.append(Target(metric=metric, current=now, target=goal, source=source))
    return tuple(sorted(out, key=lambda t: (-t.rel_error, t.metric)))


# ── 후보 조사 ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class _FileFact:
    """파일 1개에 대해 컨트롤러가 쓰는 사실 전부. 단위 수준은 `_survey` 의 두 번째 반환값이
    따로 진다 — 정밀 측정이 되는 언어가 Python 뿐이라, 한 자료형에 섞으면 나머지 언어에서
    빈 칸을 "단위가 없다"로 읽게 된다."""

    path: str
    lines: int
    churn: int


def _survey(root: str) -> tuple[list[_FileFact], dict[str, dict[str, craft_rules.Unit]], int]:
    """센서와 **같은 파일 집합**을 본다 — 컨트롤러가 벤더링에 일을 배정하면 안 된다.

    `health.scan` 의 제외 규칙(`_iter_files`)을 그대로 물려받는 것이 계약이다. 여기서 따로
    걸러내면 두 목록이 갈라져, 센서가 안 세는 파일에 컨트롤러가 작업을 낸다.
    """
    listing, _ = health._iter_files(root)
    churn, _window = health._churn(root)
    facts: list[_FileFact] = []
    units: dict[str, dict[str, craft_rules.Unit]] = {}
    truncated = max(0, len(listing) - MAX_SURVEY_FILES)
    for rel, lang in listing[:MAX_SURVEY_FILES]:
        if health._is_test(rel):
            continue
        text = health._read(root, rel)
        if text is None:
            continue
        facts.append(_FileFact(path=rel, lines=len(health._code_lines(text, lang)), churn=churn.get(rel, 0)))
        if os.path.splitext(rel)[1] in health._PRECISE_SUFFIX and (found := craft_rules.units(text)):
            units[rel] = found
    return facts, units, truncated


def _value(target: Target, churn: int, max_churn: int) -> float:
    """값 = 상대오차 × 변경빈도 가중. 안 건드리는 파일을 예쁘게 만드는 것은 값이 없다."""
    weight = 1.0 + (churn / max_churn if max_churn else 0.0)
    return round(target.rel_error * weight, 6)


def _score(value: float, read: int) -> float:
    return round(value / max(read, 1), 8)


def _unit_candidates(target: Target, facts: list[_FileFact], units: dict, max_churn: int) -> list[Candidate]:
    """함수 추출 후보 — 파일 안에서 끝나므로 읽을 줄 수는 그 함수의 행 수다.

    두 지표의 **셈 단위가 다르다**는 것이 이 함수의 요지다. `big_units` 는 단위를 세므로
    하나 내리면 하나 준다. `deep_units` 는 **파일을 센다** — 한 파일에 깊은 함수가 둘이면
    하나만 내려도 그 파일은 여전히 깊은 파일이라 지표가 **전혀 안 움직인다**.

    그래서 파일 단위 지표는 후보도 파일 단위로 묶고, 읽을 줄 수를 그 파일의 위반 단위 **전부**로
    잡는다. 안 그러면 컨트롤러가 "22행만 읽으면 지표가 준다"고 말하고 실제로는 안 주는데,
    거짓 약속을 한 번 하는 루프는 두 번째 회전부터 아무도 안 본다.
    """
    by_path = {f.path: f for f in facts}
    out: list[Candidate] = []
    for path, found in units.items():
        fact = by_path.get(path)
        if fact is None:
            continue
        value = _value(target, fact.churn, max_churn)
        if target.metric == "deep_units":
            deep = sorted(
                (u for u in found.values() if u.depth > health.DEPTH_WARN), key=lambda u: (-u.depth, -u.lines, u.line)
            )
            if not deep:
                continue
            read = sum(u.lines for u in deep)
            anchor = deep[0]
            tail = "" if len(deep) == 1 else f" (이 파일에 {len(deep)}개 — 전부 내려야 지표가 움직인다)"
            out.append(
                Candidate(
                    metric=target.metric,
                    step=EXTRACT,
                    path=path,
                    unit=anchor.qualname,
                    line=anchor.line,
                    size=anchor.depth,
                    read=read,
                    churn=fact.churn,
                    value=value,
                    score=_score(value, read),
                    why=f"중첩 {anchor.depth} (예산 {health.DEPTH_WARN}) · 합계 {read}행{tail}"
                    f" · 최근 {fact.churn}회 변경 · 파일 안에서 끝난다",
                )
            )
            continue
        for qualname, unit in found.items():
            if unit.lines <= health.UNIT_LINES_WARN:
                continue
            out.append(
                Candidate(
                    metric=target.metric,
                    step=EXTRACT,
                    path=path,
                    unit=qualname,
                    line=unit.line,
                    size=unit.lines,
                    read=unit.lines,
                    churn=fact.churn,
                    value=value,
                    score=_score(value, unit.lines),
                    why=f"{unit.lines}행 (예산 {health.UNIT_LINES_WARN}) · 중첩 {unit.depth}"
                    f" · 최근 {fact.churn}회 변경 · 파일 안에서 끝난다",
                )
            )
    return out


def _file_candidates(target: Target, facts: list[_FileFact], snap: health.Snapshot, max_churn: int) -> list[Candidate]:
    """모듈 분할·결합 해소 후보 — import 가 따라 움직이므로 읽을 줄 수는 파일 전체다."""
    threshold = health.FILE_LINES_SEVERE if target.metric == "severe_files" else health.FILE_LINES_WARN
    coupling = {str(c.get("path")): c for c in snap.coupling_top}
    step = METRIC_STEP[target.metric]
    out: list[Candidate] = []
    for fact in facts:
        info = coupling.get(fact.path)
        if step == SPLIT:
            if fact.lines <= threshold:
                continue
            over = fact.lines - threshold
            why = f"{fact.lines}행 (문턱 {threshold}, 초과 {over}) · 최근 {fact.churn}회 변경"
        else:
            if info is None:
                continue
            side = "fan_in" if target.metric == "max_fan_in" else "fan_out"
            degree = int(info.get(side) or 0)
            if degree < target.current:
                continue
            why = f"{side} {degree} (목표 {target.target:.0f}) · {fact.lines}행"
        if info:
            why += f" · fan-in {info.get('fan_in')} 모듈이 이 파일을 본다"
        value = _value(target, fact.churn, max_churn)
        out.append(
            Candidate(
                metric=target.metric,
                step=step,
                path=fact.path,
                unit="",
                line=1,
                size=fact.lines,
                read=fact.lines,
                churn=fact.churn,
                value=value,
                score=_score(value, fact.lines),
                why=why,
            )
        )
    return out


def _dup_candidates(target: Target, facts: list[_FileFact], snap: health.Snapshot, max_churn: int) -> list[Candidate]:
    """복제 제거 후보 — 사본 전부를 읽어야 하므로 읽을 줄 수는 행 수 × 사본 수다."""
    by_path = {f.path: f for f in facts}
    out: list[Candidate] = []
    for group in snap.dup_top:
        paths = [str(p) for p in (group.get("paths") or [])]
        source = [p for p in paths if p in by_path]
        if not source:
            continue
        lines, copies = int(group.get("lines") or 0), int(group.get("copies") or len(paths))
        read = max(lines * copies, 1)
        churn = max((by_path[p].churn for p in source), default=0)
        value = _value(target, churn, max_churn)
        out.append(
            Candidate(
                metric=target.metric,
                step=DEDUPE,
                path=sorted(source)[0],
                unit="",
                line=1,
                size=lines,
                read=read,
                churn=churn,
                value=value,
                score=_score(value, read),
                why=f"{lines}행 × 사본 {copies} · " + ", ".join(sorted(source)[:3]),
            )
        )
    return out


# ── control signal ─────────────────────────────────────────────────


def next_signal(root: str, snap: health.Snapshot | None = None, limit: int = 1) -> Signal:
    """오차 → 다음 걸음. 순수 관측 — 파일을 쓰지 않는다 (`record` 가 쓴다)."""
    snapshot = snap if snap is not None else health.scan(root)
    goals = targets(root, snapshot)
    undetermined: list[tuple[str, str]] = []
    if not goals:
        why = (
            "기록이 없다 — `asgard health --snapshot` 으로 첫 점을 찍어야 목표가 생긴다"
            if not health._history(root)
            else "모든 지표가 목표 이하 — 되돌릴 오차가 없다"
        )
        return Signal(snapshot.commit, (), (), (), ((("set point"), why),))

    facts, units, truncated = _survey(root)
    if truncated:
        undetermined.append(("survey", f"파일 {truncated}개를 못 봤다 — 조사 상한 {MAX_SURVEY_FILES}"))
    max_churn = max((f.churn for f in facts), default=0)

    pool: list[Candidate] = []
    for goal in goals:
        if goal.metric in NO_CANDIDATES:
            undetermined.append((goal.metric, NO_CANDIDATES[goal.metric]))
            continue
        step = METRIC_STEP.get(goal.metric)
        if step == EXTRACT:
            found = _unit_candidates(goal, facts, units, max_churn)
        elif step == DEDUPE:
            found = _dup_candidates(goal, facts, snapshot, max_churn)
        elif step in (SPLIT, DECOUPLE):
            found = _file_candidates(goal, facts, snapshot, max_churn)
        else:
            undetermined.append((goal.metric, "이 지표를 움직이는 걸음이 정의되지 않았다"))
            continue
        if not found:
            undetermined.append((goal.metric, "오차는 있는데 지목할 후보가 없다 — 센서 커버리지 밖일 수 있다"))
        pool.extend(found)

    pool.sort(key=lambda c: (-c.score, c.path, c.unit))
    return Signal(
        commit=snapshot.commit,
        targets=goals,
        picked=tuple(pool[: max(limit, 0)]),
        runners_up=tuple(pool[max(limit, 0) : max(limit, 0) + MAX_RUNNERS_UP]),
        undetermined=tuple(undetermined),
    )


def signal_path(root: str) -> str:
    return os.path.join(root, ".asgard", *SIGNAL_PATH)


def record(root: str, signal: Signal) -> str:
    """control signal 을 정본으로 남긴다 — 튜터가 "왜 이 자리인가"를 여기서 읽는다."""
    payload = {
        "commit": signal.commit,
        "targets": [asdict(t) | {"error": t.error, "rel_error": t.rel_error} for t in signal.targets],
        "picked": [asdict(c) for c in signal.picked],
        "runners_up": [asdict(c) for c in signal.runners_up],
        "undetermined": [list(u) for u in signal.undetermined],
    }
    path = signal_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json(path, payload)
    return path


def load(root: str) -> dict | None:
    """기록된 control signal — 없거나 깨졌으면 None (fail-open: 소비처는 침묵한다)."""
    data = read_json(signal_path(root), None)
    return data if isinstance(data, dict) and data.get("picked") else None


def mandate_for(root: str, paths: object) -> tuple[dict, ...]:
    """지목된 경로 중 **컨트롤러가 고른 자리**의 선택 근거. 없으면 빈 튜플.

    튜터가 쓰는 자리다. 이것은 답이 아니라 사실이다 — 사람이 diff 만 보고는 "왜 하필 이
    파일인가"를 유도할 수 없다. 루프가 쓴 변경에는 그 물음에 답할 저자가 없어서, 기계가
    아는 것을 기계가 실어야 한다 (`tutor` 계약 ③ 의 빈칸이 비어 있는 유일한 경우).
    """
    signal = load(root)
    if signal is None:
        return ()
    wanted = {str(p).strip().replace(os.sep, "/") for p in paths} if isinstance(paths, (list, tuple, set)) else set()
    goals = {str(t.get("metric")): t for t in signal.get("targets") or [] if isinstance(t, dict)}
    out = []
    for pick in signal.get("picked") or []:
        if not isinstance(pick, dict):
            continue
        if wanted and str(pick.get("path")) not in wanted:
            continue
        goal = goals.get(str(pick.get("metric"))) or {}
        out.append(
            {
                "metric": pick.get("metric"),
                "step": pick.get("step"),
                "path": pick.get("path"),
                "unit": pick.get("unit") or "",
                "line": pick.get("line") or 1,
                "current": goal.get("current"),
                "target": goal.get("target"),
                "source": goal.get("source"),
                "read": pick.get("read"),
                "score": pick.get("score"),
                "why": pick.get("why") or "",
                "runners_up": [
                    f"{r.get('path')}{(' ' + str(r.get('unit'))) if r.get('unit') else ''} — 읽을 줄 {r.get('read')}"
                    for r in (signal.get("runners_up") or [])
                    if isinstance(r, dict) and r.get("metric") == pick.get("metric")
                ][:3],
            }
        )
    return tuple(out)
