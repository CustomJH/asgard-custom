"""asgard health — 나무 침식 신호의 사람 표면. 판정하지 않는다: 세고, 추세를 보여준다.

절대값으로 차단하지 않는 이유는 `health` 모듈 docstring 에 있다. 이 표면의 계약은 두 줄이다:
① 측정하지 못한 것을 측정한 것처럼 보이게 하지 않는다(미측정·제외 수를 항상 함께 싣는다),
② 나빠진 지표를 화면 위쪽에 올린다 — 좋아진 지표를 세는 것은 이 도구의 일이 아니다.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from .. import health, ui


def _project_root(start: str) -> str:
    """git 루트 — 없으면 현재 디렉터리. code_map 과 같은 규칙."""
    import os

    cur = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(start)
        cur = parent


_LABEL = {
    "big_files": f"큰 파일 (>{health.FILE_LINES_WARN}행)",
    "severe_files": f"심각 (>{health.FILE_LINES_SEVERE}행)",
    "big_units": f"큰 함수 (>{health.UNIT_LINES_WARN}행)",
    "deep_units": f"깊은 함수 (>{health.DEPTH_WARN}중첩)",
    "dup_share": "중복 비율",
    "cycles": "import 순환",
    "max_fan_in": "최대 fan-in",
    "max_fan_out": "최대 fan-out",
}


def _num(value: float) -> str:
    return f"{value:.2%}" if 0 < value < 1 else f"{value:,.0f}"


def run_health(*, snapshot: bool = False, json_out: bool = False, quiet: bool = False) -> int:
    """현재 상태 + 마지막 기록과의 추세. `snapshot=True` 면 현재 상태를 이력에 기록한다."""
    import os

    root = _project_root(os.getcwd())
    ui.set_quiet(json_out or quiet)
    snap = health.scan(root)
    # 추세는 기록 **전에** 계산한다 — 방금 찍은 점과 자기를 비교하면 항상 flat 이 된다
    tr = health.trend(root, snap)
    if snapshot:
        health.record(root)

    if json_out:
        payload: dict = {"snapshot": asdict(snap), "recorded": snapshot}
        if tr:
            payload["trend"] = {
                "from": tr.from_commit,
                "to": tr.to_commit,
                "deltas": [{**asdict(d), "change": d.change} for d in tr.deltas if d.direction != "flat"],
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    ui.head("health · 나무 상태")
    scope = f"기준 {snap.commit} · 소스 {snap.files}파일 {snap.code_lines:,}행 · 테스트 {snap.test_files}파일"
    ui.step(scope)
    limits = []
    if snap.excluded_files:
        limits.append(f"제외 {snap.excluded_files}")
    if snap.unmeasured_files:
        limits.append(f"함수·결합 미측정 {snap.unmeasured_files} (Python 아님)")
    if limits:
        ui.step(ui.dim("커버리지 한계: " + " · ".join(limits)))

    ui.phase("지표")
    ui.step(
        f"크기   {_LABEL['big_files']} {snap.big_files} · {_LABEL['severe_files']} {snap.severe_files}"
        f" · {_LABEL['big_units']} {snap.big_units} · {_LABEL['deep_units']} {snap.deep_units}"
    )
    ui.step(f"중복   소스 {snap.dup_lines:,}행 {snap.dup_share:.2%} (테스트 {snap.test_dup_lines:,}행 — 참고)")
    ui.step(f"결합   순환 {snap.cycles} · 최대 fan-in {snap.max_fan_in} · 최대 fan-out {snap.max_fan_out}")

    if tr:
        ui.phase(f"추세 ({tr.from_commit} → {tr.to_commit})")
        worse = tr.regressed
        better = [d for d in tr.deltas if d.direction == "improved"]
        if not worse and not better:
            ui.step("변동 없음")
        for d in worse:
            ui.warn(f"{_LABEL.get(d.metric, d.metric)} {_num(d.before)} → {_num(d.after)}")
        for d in better:
            ui.step(ui.dim(f"{_LABEL.get(d.metric, d.metric)} {_num(d.before)} → {_num(d.after)}"))
    else:
        ui.phase("추세")
        ui.step(ui.dim("기록이 없다 — `asgard health --snapshot` 으로 첫 점을 찍으면 다음 실행부터 델타가 나온다"))

    if snap.hotspots:
        ui.phase(f"핫스팟 — 변경빈도 × 크기 (최근 {snap.churn_window}커밋)")
        for spot in snap.hotspots[:5]:
            ui.step(f"{spot['churn']:>3}회 × {spot['lines']:>5,}행  {spot['path']}")
    if snap.worst_units:
        ui.phase("최장 함수")
        for unit in snap.worst_units[:5]:
            ui.step(f"{unit['lines']:>4}행 중첩 {unit['depth']}  {unit['path']}")
    if snap.dup_top:
        ui.phase("클론 군 — 소스를 포함한 것만")
        for group in snap.dup_top[:5]:
            ui.step(f"{group['copies']}회  {', '.join(group['paths'])}")

    if snapshot:
        ui.ok(f"기록됨 — {health.history_path(root)}")
    ui.done()
    return 0
