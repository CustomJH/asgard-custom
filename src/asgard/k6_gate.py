"""asgard-k6 기록과 성능 회귀 게이트 — 끝난 실행을 남기고, 기준선과 견준다.

`k6` 는 부하를 걸고 그 한 판을 판정한다. 여기가 묻는 것은 다른 것이다: **지난번보다
나빠졌는가**. 그 판정에는 견줄 대상(`.asgard/k6/baseline.json`)과 견줄 자격
(`GATE_AXES` — 러너·k6 판·표적·부하 형상이 같은가)이 먼저 있어야 한다. 자격을 안 보고
수치만 견주면 그 판정은 거짓이고, 거짓 회귀 하나면 사람이 이 게이트를 끈다.

부하는 여기서 안 돈다 — 파일 둘을 읽고 끝난다.
"""

from __future__ import annotations

import json
import os
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .k6 import Report, SummaryError, lane_dir, parse_summary, runs_dir

# ─────────────────────────────────────────────────────────────────── 기록


def record_run(root: str | os.PathLike[str], report: Report, stamp: str) -> Path:
    """실행 결과를 프로젝트에 남긴다 — 부하 수치는 기억이 아니라 파일이어야 재현을 논한다."""
    target = runs_dir(root) / stamp
    target.mkdir(parents=True, exist_ok=True)
    path = target / "report.json"
    path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


@dataclass(frozen=True)
class RunRecord:
    """기록된 실행 하나 — 스탬프와 그때 남긴 report.json 본문."""

    stamp: str
    payload: dict
    path: Path


def recorded_runs(root: str | os.PathLike[str]) -> list[RunRecord]:
    """기록된 실행 전부, 오래된 것부터. 스탬프가 `%Y%m%dT%H%M%S-<시나리오>` 라 사전순이 시간순이다.

    못 읽는 파일은 건너뛴다 — 기록 하나가 깨졌다고 나머지 이력 전체를 못 보게 되면, 게이트를
    쓰는 사람이 하는 일은 `runs/` 를 통째로 지우는 것이다."""
    runs = runs_dir(root)
    if not runs.is_dir():
        return []
    out: list[RunRecord] = []
    for path in sorted(runs.glob("*/report.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        if isinstance(payload, dict):
            out.append(RunRecord(path.parent.name, payload, path))
    return out


def find_recorded_run(root: str | os.PathLike[str], stamp: str = "", *, scenario: str = "") -> RunRecord | None:
    """스탬프로 지목하거나, 안 주면 가장 최근 기록. `scenario` 를 주면 그 시나리오로 돈 것만 본다.

    시나리오를 스탬프 접미사가 아니라 요약 본문에서 읽는 이유: 직접 경로로 돌린 실행
    (`asgard k6 run ./mine.js`)은 스탬프 접미사가 파일 이름이라 시나리오 이름과 다를 수 있다."""
    if stamp:
        return next((record for record in recorded_runs(root) if record.stamp == stamp), None)
    for record in reversed(recorded_runs(root)):
        if not scenario or str(record.payload.get("scenario") or "") == scenario:
            return record
    return None


# ────────────────────────────────────────────────── 기준선과 성능 회귀 게이트

BASELINE_NAME = "baseline.json"
BASELINE_SCHEMA = "asgard-k6-baseline-v1"
GATE_SCHEMA = "asgard-k6-gate-v1"

# 오차를 덮어쓰는 자리. `[tool.asgard.health-gate]` 와 같은 관례다 — 게이트의 느슨함은 코드가
# 아니라 저장소가 정하고, 그 결정이 diff 에 남아 리뷰 대상이 된다.
GATE_TABLE = ("tool", "asgard", "k6-gate")

# 비교 가능성을 정하는 축. 이 중 하나라도 다르면 두 수치는 **같은 것을 잰 값이 아니고**, 그런
# 값끼리의 판정은 거짓이다. 그래서 수치를 보기 전에 여기부터 대조한다.
#
# `vus_max` 가 들어간 이유: 같은 시나리오라도 `--vus 1` 로 잰 값과 `--vus 10` 으로 잰 값을
# 견주는 것은 러너가 다른 것과 정확히 같은 종류의 거짓 판정이다. `vus_max` 는 설정에서 나오는
# 값이라 같은 부하 형상이면 같은 값이 된다.
#
# `iterations` 는 **일부러 뺐다.** 기간 기반 시나리오에서 반복 수는 설정이 아니라 결과다. 같기를
# 요구하면 그런 시나리오는 영영 판정을 못 받고, 더 나쁘게는 우리가 잡으려는 처리량 악화 자체가
# "견줄 수 없음"으로 둔갑한다.
GATE_AXES = ("scenario", "runner", "k6_version", "target", "vus_max")


# ── 허용 오차의 근거 (실측) ──
#
# 부하 수치는 같은 기계·같은 코드에서도 흔들린다. 그 흔들림보다 좁은 오차를 걸면 게이트는
# 아무것도 안 바뀐 커밋을 막고, 그다음에 일어나는 일은 게이트를 끄는 것이다. 그래서 기본값을
# 짐작이 아니라 실측으로 정했다 (2026-08-03 · native k6 v2.1.0 · darwin/arm64 · 표적은 키트 pacer).
#
#   평평한 표적 (고정 80ms sleep, 꼬리가 없다)    p95 재현 편차  n=690 0.23% · n=40 0.38%
#   줄서는 표적 (동시성 상한 2 에 VU 5, 대기열)   p95 재현 편차  n≈357 **9.25%** (5회 반복)
#                                                  같은 실행의 med 1.71% · req/s 0.57%
#
# 읽는 법: 평평한 표적의 0.2~0.4% 는 하네스 자체의 잡음 하한이지 표적의 잡음이 아니다. 고정
# 지연에는 꼬리가 없어서 어느 분위수를 재도 같은 값이 나온다. 대기열이 생기는 순간 같은 코드가
# 9.25% 를 오갔고(225.03~247.13ms), 그동안 중앙값은 1.71% 안에 있었다 — 움직인 것은 꼬리다.
# 부하 게이트가 재는 것이 바로 그 꼬리다.
DEFAULT_P95_PCT = 20.0
# 측정된 9.25% 에 약 2배 여유. 여유가 필요한 이유가 둘 더 있다.
#   ① 위 측정은 놀고 있는 기계에서 서비스 시간이 상수인 표적으로 잰 값이다. 실제 표적에는
#      GC 정지·캐시 예열·연결 재수립이 더해진다.
#   ② p95 는 순서통계량이다. n 건에서 95분위 순위의 표준편차는 √(n·0.95·0.05) 이고, n=357 이면
#      4.1위, n=40 이면 1.4위(= n 의 3.45%)다. 표본이 작을수록 아무것도 안 바뀌어도 추정치가
#      꼬리를 더 크게 오르내린다.
# 10% 로 잡으면 위 실측 잡음이 그대로 회귀로 잡힌다.

DEFAULT_RATE_PER_S_PCT = 10.0
# 처리량은 꼬리가 아니라 실행 전체의 평균이라 훨씬 안정적이다 — 같은 실측에서 0.57%(n≈357)와
# 1.50%(n=40)였고, 10% 는 최악 관측의 약 7배다. p95(20%)와 다른 수인 것은 임의가 아니라 이
# 차이 때문이다.

DEFAULT_FAILED_RATE_PP = 1.0
# 실패는 잡음이 아니라 사건이다 — 위 16회 실행에서 실패는 전부 0.0000 이었고, 그래서 이 축에는
# 잴 잡음 하한 자체가 없다. 단위가 비율(%)이 아니라 **퍼센트포인트**인 이유도 거기 있다: 건강한
# 기준선의 failed_rate 는 0.0 이고 0 의 20% 는 0 이라, 비율 오차를 걸면 한 건짜리 전송 실패가
# 곧바로 회귀가 된다. 1.0pp 는 이 레인이 실제로 도는 규모(40~700건)에서 딸꾹질 한 건을 봐주는
# 폭이다. **알려진 한계**: n=10,000 이면 1.0pp 는 실패 100건이다. 큰 실행을 상시로 도는
# 저장소는 [tool.asgard.k6-gate] 에서 이 값을 좁혀야 한다.


@dataclass(frozen=True)
class Tolerance:
    """회귀라고 부르기 전에 봐주는 폭. 축마다 단위가 다르고, 그 차이가 요점이다."""

    p95_pct: float = DEFAULT_P95_PCT
    failed_rate_pp: float = DEFAULT_FAILED_RATE_PP
    rate_per_s_pct: float = DEFAULT_RATE_PER_S_PCT

    def as_dict(self) -> dict:
        return {
            "p95_pct": self.p95_pct,
            "failed_rate_pp": self.failed_rate_pp,
            "rate_per_s_pct": self.rate_per_s_pct,
        }


def gate_tolerance(root: str | os.PathLike[str]) -> Tolerance:
    """`pyproject.toml` 의 `[tool.asgard.k6-gate]` 로 기본 오차를 덮는다. 없으면 기본값 그대로.

    수치(기준선)는 기계마다 다르므로 `.asgard/` 에 두지만, 정책(오차)은 기계와 무관하므로
    추적되는 파일에 둔다. 그래야 게이트를 푸는 일이 diff 에 남는다.

    못 쓸 값(bool·문자열·음수)은 무시하고 기본값으로 내려간다 — 0 으로 읽으면 오타 하나가
    오차를 없애 버려서, 아무것도 안 바뀐 실행이 회귀로 나온다."""
    try:
        with open(os.path.join(str(root), "pyproject.toml"), "rb") as handle:
            table: object = tomllib.load(handle)
    except OSError, tomllib.TOMLDecodeError:
        return Tolerance()
    for key in GATE_TABLE:
        if not isinstance(table, dict):
            return Tolerance()
        table = table.get(key, {})
    if not isinstance(table, dict):
        return Tolerance()
    values: dict[str, float] = {}
    for name, fallback in (
        ("p95_pct", DEFAULT_P95_PCT),
        ("failed_rate_pp", DEFAULT_FAILED_RATE_PP),
        ("rate_per_s_pct", DEFAULT_RATE_PER_S_PCT),
    ):
        raw = table.get(name)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 0:
            values[name] = fallback
        else:
            values[name] = float(raw)
    return Tolerance(**values)


def baseline_path(root: str | os.PathLike[str]) -> Path:
    """`.asgard/k6/baseline.json` — 이 프로젝트가 표적으로 삼은 실행.

    `[tool.asgard.health-gate]` 는 기준선을 추적되는 파일에 두었는데, 부하는 그 논리가 뒤집힌다.
    p95 는 코드의 성질이 아니라 코드와 기계와 표적이 함께 만드는 값이다. 노트북의 85ms 를
    추적되는 파일에 새기면 CI 러너가 그 값과 자기 수치를 견주게 되고, 그 판정은 코드가 아니라
    하드웨어를 재는 것이 된다. 부하 기준선은 잰 자리에 있어야 한다."""
    return lane_dir(root) / BASELINE_NAME


def baseline_blocker(payload: dict) -> str:
    """이 실행을 기준선으로 못 삼는 이유 코드. 삼을 수 있으면 빈 문자열.

    기준선은 앞으로의 실행을 통과시키는 **표준**이라, 대조군보다 요구가 높다. 아무도 검증하지
    않은 실행을 표준으로 삼으면 이 레인이 실제로 겪었던 사고 — 40건이 전부 죽었는데
    `verdict pass` · exit 0 으로 나간 실행 — 가 그대로 정본이 되고, 그 뒤로는 똑같이 망가진
    실행이 영원히 게이트를 통과한다.

    거절 셋:
      unreadable      요약 계약을 안 지킨 기록. 이 수치가 무엇인지부터 알 수 없다.
      empty           요청 0건. 잰 것이 없는 실행은 표준이 될 수 없다.
      unjudged        임계값이 없어 판정할 것이 없었던 실행 (`Report.judged`).
      exit-disagrees  종료 코드와 임계값 판정이 어긋난 실행. 레인이 이미 못 믿는다고 말한 값이다.
    """
    try:
        report = parse_summary(payload, exit_code=int(payload.get("exit_code") or 0))
    except SummaryError, TypeError, ValueError:
        return "unreadable"
    if report.requests <= 0:
        return "empty"
    if not report.judged:
        return "unjudged"
    if not report.exit_agrees:
        return "exit-disagrees"
    return ""


@dataclass(frozen=True)
class Baseline:
    """지금 표적으로 삼고 있는 실행. `run` 은 그때 기록한 report.json 본문 그대로다."""

    stamp: str
    set_at: str
    run: dict
    path: Path

    @property
    def scenario(self) -> str:
        return str(self.run.get("scenario") or "")


def write_baseline(root: str | os.PathLike[str], record: RunRecord, *, set_at: str = "") -> Baseline:
    """어느 실행을 표적으로 삼았는지를 통째로 새긴다.

    수치만 뽑아 적지 않고 요약 본문을 그대로 넣는 이유: 나중에 이 파일 하나만 열어도 "어떤
    시나리오를, 어떤 러너와 k6 판으로, 어떤 표적에" 걸어 나온 값인지 물을 수 있어야 한다.
    `runs/<stamp>/` 는 보존 정책에 따라 지워질 수 있고, 그때 기준선만 남으면 근거가 사라진다."""
    path = baseline_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = set_at or time.strftime("%Y-%m-%dT%H:%M:%S")
    body = {
        "schema": BASELINE_SCHEMA,
        "stamp": record.stamp,
        "set_at": stamped,
        "run": record.payload,
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return Baseline(record.stamp, stamped, record.payload, path)


def read_baseline(root: str | os.PathLike[str]) -> Baseline | None:
    """세워 둔 기준선. 없으면 None, 있는데 계약을 안 지켰으면 `SummaryError`.

    없음과 깨짐을 가르는 이유: 없음은 정상 상태(아직 표적을 안 정했다)이고, 깨짐은 사람이
    알아야 할 사고다. 둘을 None 하나로 합치면 손상된 기준선이 "아직 안 세웠다"로 읽힌다.

    사유 문장이 해요체인 것은 이 예외가 그대로 화면에 찍히기 때문이다 — `baseline show` 는
    이 문장 말고 다른 설명을 내지 않는다."""
    path = baseline_path(root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SummaryError(f"기준선을 읽을 수 없어요: {exc}") from exc
    schema = payload.get("schema") if isinstance(payload, dict) else None
    if schema != BASELINE_SCHEMA:
        raise SummaryError(f"기준선 스키마가 달라요: {schema!r} (기대: {BASELINE_SCHEMA})")
    run = payload.get("run")
    if not isinstance(run, dict):
        raise SummaryError("기준선에 실행 본문이 없어요 — asgard k6 baseline set으로 다시 세워 주세요.")
    return Baseline(str(payload.get("stamp") or ""), str(payload.get("set_at") or ""), run, path)


def clear_baseline(root: str | os.PathLike[str]) -> bool:
    """기준선을 치운다. 치울 것이 있었으면 True."""
    path = baseline_path(root)
    if not path.is_file():
        return False
    path.unlink()
    return True


@dataclass(frozen=True)
class Axis:
    """비교 가능성 축 하나 — 두 실행이 같은 것을 잰 값인지를 정하는 값."""

    name: str
    baseline: str
    current: str

    @property
    def same(self) -> bool:
        return self.baseline == self.current


@dataclass(frozen=True)
class Delta:
    """수치 축 하나의 변화와 판정.

    `higher_is_better` 가 부등호를 뒤집는다 — 처리량은 떨어지는 것이 악화이고 지연은 오르는
    것이 악화다. 이 값을 안 보고 한 방향으로만 재면 처리량 회귀가 전부 통과한다."""

    metric: str
    baseline: float
    current: float
    limit: float  # 넘으면(높을수록 좋은 축이면 밑돌면) 회귀
    higher_is_better: bool
    unit: str

    @property
    def regressed(self) -> bool:
        return self.current < self.limit if self.higher_is_better else self.current > self.limit

    @property
    def change_pct(self) -> float:
        """기준선 대비 변화율. 기준선이 0 이면 비율이 없다 — 화면은 이 값 대신 절대값을 쓴다."""
        return 0.0 if self.baseline == 0 else (self.current - self.baseline) / self.baseline * 100.0

    def as_dict(self) -> dict:
        return {
            "metric": self.metric,
            "baseline": self.baseline,
            "current": self.current,
            "limit": self.limit,
            "higher_is_better": self.higher_is_better,
            "unit": self.unit,
            "change_pct": self.change_pct,
            "regressed": self.regressed,
        }


# 판정 셋. `undecidable` 이 `pass` 와 다른 낱말인 것이 이 게이트의 계약이다 — 종료 코드는 둘 다
# 0 이지만(못 견줄 때 막는 것은 소음이다) 판정문은 절대 같지 않다.
VERDICT_PASS = "pass"
VERDICT_REGRESSED = "regressed"
VERDICT_UNDECIDABLE = "undecidable"


@dataclass(frozen=True)
class GateVerdict:
    """게이트 판정 1회."""

    verdict: str
    reason: str  # undecidable 일 때의 이유 코드
    baseline_stamp: str = ""
    current_stamp: str = ""
    scenario: str = ""
    axes: tuple[Axis, ...] = ()
    deltas: tuple[Delta, ...] = ()
    tolerance: Tolerance = field(default_factory=Tolerance)

    @property
    def blocked(self) -> bool:
        return self.verdict == VERDICT_REGRESSED

    @property
    def mismatched(self) -> tuple[Axis, ...]:
        return tuple(axis for axis in self.axes if not axis.same)

    @property
    def regressions(self) -> tuple[Delta, ...]:
        return tuple(delta for delta in self.deltas if delta.regressed)

    def as_dict(self) -> dict:
        return {
            "schema": GATE_SCHEMA,
            "verdict": self.verdict,
            "reason": self.reason,
            "baseline_stamp": self.baseline_stamp,
            "current_stamp": self.current_stamp,
            "scenario": self.scenario,
            "tolerance": self.tolerance.as_dict(),
            "axes": [{"name": a.name, "baseline": a.baseline, "current": a.current, "same": a.same} for a in self.axes],
            "deltas": [d.as_dict() for d in self.deltas],
        }


def axis_values(payload: dict) -> dict[str, str]:
    """비교 가능성 축의 값. 전부 문자열로 맞춰 두면 대조가 한 줄이 된다."""
    return {
        "scenario": str(payload.get("scenario") or ""),
        "runner": str(payload.get("runner") or ""),
        "k6_version": str(payload.get("k6_version") or ""),
        "target": str(payload.get("target") or ""),
        "vus_max": str(int(payload.get("vus_max") or 0)),
    }


def _measurements(payload: dict) -> tuple[float, float, float, int]:
    reqs = payload.get("requests") or {}
    latency = payload.get("latency_ms") or {}
    return (
        float(latency.get("p95") or 0.0),
        float(reqs.get("failed_rate") or 0.0),
        float(reqs.get("rate_per_s") or 0.0),
        int(reqs.get("count") or 0),
    )


def compare_to_baseline(baseline: Baseline, current: RunRecord, tolerance: Tolerance) -> GateVerdict:
    """기준선과 마지막 기록을 견준다. 부하는 안 돈다 — 파일 둘을 읽고 끝난다.

    **비교 가능성이 판정보다 먼저다.** 다른 시나리오·다른 러너·다른 k6 판·다른 표적·다른 부하
    형상에서 나온 수치를 견주면 그 판정은 거짓이다. 그런 때는 회귀라고 말하지 않고 "견줄 수
    없다"고 말한다 — 거짓 회귀 하나가 이 게이트를 끄게 만드는 데는 한 번이면 충분하다."""
    base_axes, cur_axes = axis_values(baseline.run), axis_values(current.payload)
    axes = tuple(Axis(name, base_axes[name], cur_axes[name]) for name in GATE_AXES)
    scenario = base_axes["scenario"]

    def _verdict(name: str, reason: str, deltas: tuple[Delta, ...] = ()) -> GateVerdict:
        """세 갈래가 공유하는 칸을 한 자리에서 채운다 — 판정과 이유만 부르는 쪽이 정한다."""
        return GateVerdict(
            name,
            reason,
            baseline_stamp=baseline.stamp,
            current_stamp=current.stamp,
            scenario=scenario,
            axes=axes,
            deltas=deltas,
            tolerance=tolerance,
        )

    if any(not axis.same for axis in axes):
        return _verdict(VERDICT_UNDECIDABLE, "not-comparable")

    base_p95, base_failed, base_rate, base_count = _measurements(baseline.run)
    cur_p95, cur_failed, cur_rate, cur_count = _measurements(current.payload)
    # 요청 0건인 실행에는 견줄 수치가 없다. 여기서 안 막으면 기준선 p95 0ms 가 허용치 0ms 가
    # 되어, 정상으로 돈 실행이 전부 회귀로 나온다.
    if base_count <= 0 or cur_count <= 0:
        return _verdict(VERDICT_UNDECIDABLE, "no-measurement")

    deltas = (
        Delta("p95", base_p95, cur_p95, base_p95 * (1 + tolerance.p95_pct / 100.0), False, "ms"),
        # 퍼센트포인트를 비율로 되돌린다 — 요약의 failed_rate 는 0~1 이다.
        Delta("failed_rate", base_failed, cur_failed, base_failed + tolerance.failed_rate_pp / 100.0, False, "rate"),
        Delta("rate_per_s", base_rate, cur_rate, base_rate * (1 - tolerance.rate_per_s_pct / 100.0), True, "req/s"),
    )
    verdict = VERDICT_REGRESSED if any(delta.regressed for delta in deltas) else VERDICT_PASS
    return _verdict(verdict, "", deltas)
