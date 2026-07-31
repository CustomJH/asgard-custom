"""검증 동사 — refs · measure · align · frame · diff.

## 왜 이 동사들이 커널을 안 부르는가

셀렉터 표는 STEP을 만들 때 이미 커널이 훑어서 위상 산출물에 적어 뒀다. 면의 법선·중심·면적,
에지의 길이, 부품의 부피가 전부 거기 있다. 그러니 **재는 일에는 커널이 다시 필요 없다.**

이 사실이 실무에서 갖는 뜻은 크다. 검증 한 번에 수백 MB 휠과 수십 초를 쓰던 것이, 파일 하나를
읽는 일이 된다. 대화 중에 치수를 열 번 확인하는 것이 부담이 아니게 되고, 부담이 아니어야 실제로
열 번 확인한다.

## 서수의 위험과 그 대응

`#f7`은 안정된 이름이 아니다. 파라미터를 바꿔 STEP을 다시 뽑으면 7번 면은 다른 면이 된다.
그래서 규칙 하나가 문서 전체를 관통한다: **셀렉터는 쓰기 직전에 `refs`로 다시 딴다.**

여기서는 자료구조로도 받친다 — 모든 동사가 먼저 `stepHash`를 대조하고, 표가 STEP보다 낡았으면
측정값을 내기 전에 그 사실을 말한다. 낡은 표로 잰 숫자는 틀린 숫자가 아니라 **다른 형상의 맞는
숫자**라 더 위험하다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from . import stepfile, topology
from .report import Report

_SELECTOR = re.compile(r"^#?(?P<body>[A-Za-z0-9.]+)$")
_TOKEN = re.compile(r"^(?P<kind>[osfev])(?P<ordinal>\d+)$")

KINDS = {"o": "occurrences", "s": "shapes", "f": "faces", "e": "edges", "v": "vertices"}
AXES = {"x": 0, "y": 1, "z": 2}


class SelectorError(ValueError):
    """셀렉터가 문법에 안 맞거나 표에 없다. 호출부가 미확인으로 적을 수 있게 예외로 낸다."""


@dataclass
class Resolved:
    """셀렉터가 가리킨 실체와, 그것에서 뽑은 위치·방향."""

    selector: str
    kind: str
    entry: dict

    @property
    def label(self) -> str:
        return str(self.entry.get("label") or self.entry.get("id") or self.selector)

    @property
    def point(self) -> list[float] | None:
        for key in ("center", "point"):
            value = self.entry.get(key)
            if isinstance(value, list) and len(value) == 3:
                return [float(item) for item in value]
        box = self.entry.get("bbox")
        if isinstance(box, dict) and isinstance(box.get("min"), list) and isinstance(box.get("max"), list):
            return [(float(box["min"][i]) + float(box["max"][i])) / 2 for i in range(3)]
        return None

    @property
    def normal(self) -> list[float] | None:
        value = self.entry.get("normal")
        return [float(item) for item in value] if isinstance(value, list) and len(value) == 3 else None

    @property
    def is_planar(self) -> bool:
        return str(self.entry.get("type", "")).upper() == "PLANE"


def parse(selector: str) -> tuple[str, str]:
    """`#o1.2.f3` → ('f', 'o1.2.f3'). 마지막 토큰이 종류를 정하고, 앞은 소속 경로다."""
    match = _SELECTOR.match(selector.strip())
    if not match:
        raise SelectorError(f"셀렉터 문법이 아니다: {selector!r} (예: #f13, #o1.2.f1, #e7)")
    body = match.group("body")
    tail = body.split(".")[-1]
    token = _TOKEN.match(tail)
    if not token:
        raise SelectorError(f"셀렉터 끝 토큰을 읽지 못했다: {selector!r} (o/s/f/e/v + 숫자)")
    return token.group("kind"), body


def resolve(sidecar: topology.Sidecar, selector: str) -> Resolved:
    """셀렉터를 표에서 찾는다. 못 찾으면 가까운 후보를 곁들여 던진다 — 서수 착오가 흔해서다."""
    kind, body = parse(selector)
    entries = sidecar.entries(KINDS[kind])
    if not entries:
        raise SelectorError(
            f"위상 산출물에 {KINDS[kind]} 표가 없다 — `cad.py step`을 --detail 없이 돌렸거나 표가 비었다."
        )

    for entry in entries:
        if str(entry.get("id")) == body:
            return Resolved(selector=f"#{body}", kind=kind, entry=entry)

    # 어커런스가 하나뿐인 모델은 `#f13`과 `#o1.f13`을 같게 취급한다 — 문서가 그렇게 쓴다.
    tail = body.split(".")[-1]
    matches = [entry for entry in entries if str(entry.get("id", "")).split(".")[-1] == tail]
    if len(matches) == 1:
        return Resolved(selector=f"#{body}", kind=kind, entry=matches[0])
    if len(matches) > 1:
        owners = ", ".join(f"#{entry['id']}" for entry in matches[:6])
        raise SelectorError(f"{selector}는 어커런스가 여럿이라 모호하다 — 하나를 고르라: {owners}")

    available = ", ".join(f"#{entry['id']}" for entry in entries[:8])
    raise SelectorError(f"{selector}를 표에서 찾지 못했다. 있는 것: {available}{' …' if len(entries) > 8 else ''}")


def freshness(report: Report, step_path: str, sidecar: topology.Sidecar | None) -> topology.Sidecar | None:
    """표가 이 STEP의 것인지 먼저 묻는다. 아니면 측정을 계속하되 그 사실을 판정에 남긴다."""
    if sidecar is None:
        report.unverified(
            "topology-missing",
            f"위상 산출물({topology.sidecar_path(step_path).name})이 없다 — 이 STEP에 대한 셀렉터 측정을 할 수 없다. "
            "`cad.py step`으로 생성하라.",
        )
        return None
    digest = stepfile.sha256_file(step_path)
    if not sidecar.step_hash:
        report.unverified("topology-unreadable", "위상 산출물에 stepHash가 없다 — 신선도를 판정하지 못한다.")
    elif not sidecar.is_fresh_for(digest):
        report.fail(
            "topology-stale",
            "위상 산출물이 이 STEP보다 낡았다. 지금 재면 **다른 형상의 숫자**가 나온다 — "
            "`cad.py step`으로 다시 생성하라.",
            {"stepHash": digest, "artifactHash": sidecar.step_hash},
        )
    return sidecar


# ─────────────────────────────────────────────────────────────────────────────
# refs
# ─────────────────────────────────────────────────────────────────────────────


def refs(
    step_path: str,
    *,
    selectors: list[str],
    facts: bool,
    planes: bool,
    positioning: bool,
    detail: bool,
    show_topology: bool,
) -> Report:
    """이 형상에 무엇이 있는가. 모든 생성물에 예외 없이 먼저 도는 동사다."""
    report = Report(tool="inspect refs", target=step_path)
    static = stepfile.read(step_path)
    sidecar = freshness(report, step_path, topology.load_for(step_path))

    if facts or not (selectors or planes or positioning or detail or show_topology):
        report.facts.update(
            {
                "schema": static.schema_family or static.schema or "미상",
                "단위": f"{static.length_unit or '미상'} (1 = {static.length_scale_mm}mm)"
                if static.length_scale_mm
                else "미상 — 치수 보고 금지",
                "엔티티": static.entities,
                "솔리드": static.solids,
                "면 / 에지 / 버텍스": f"{static.faces} / {static.edges} / {static.vertices}",
                "부품": ", ".join(static.products) or "(이름 없음)",
            }
        )
        # 치수는 **커널이 잰 값**을 먼저 쓴다. 위상 산출물의 부품 bbox를 합치면 그것이 진짜
        # bbox 이고, 무커널 추정은 산출물이 없을 때의 차선이다. 어느 쪽을 냈는지 항상 표시한다.
        size, note = _measured_size(sidecar), "위상 산출물 — 커널이 잰 값"
        if size is None:
            size, note = static.best_size_mm()
        if size:
            report.facts["치수(mm)"] = f"{size[0]:g} × {size[1]:g} × {size[2]:g}  [{note}]"
        for problem in static.problems:
            report.unverified("step-static", problem)
        if static.solids == 0 and not static.problems:
            report.fail("no-solid", "솔리드가 없다 — 스케치나 서피스만 남은 STEP 이다.")

    if sidecar is not None:
        if planes:
            for entry in _major_planes(sidecar):
                report.facts[f"평면 #{entry['id']}"] = (
                    f"법선 {_vector(entry.get('normal'))}  중심 {_vector(entry.get('center'))}  면적 {entry.get('area')}"
                )
        if positioning:
            for shape in sidecar.entries("shapes"):
                box = shape.get("bbox") or {}
                report.facts[f"배치 {shape.get('label', shape.get('id'))}"] = (
                    f"min {_vector(box.get('min'))}  max {_vector(box.get('max'))}"
                )
        if show_topology:
            for kind, key in (("면", "faces"), ("에지", "edges")):
                ids = [f"#{entry['id']}" for entry in sidecar.entries(key)]
                report.facts[f"{kind} 서수"] = ", ".join(ids[:60]) + (" …" if len(ids) > 60 else "")

        for selector in selectors:
            try:
                found = resolve(sidecar, selector)
            except SelectorError as error:
                report.unverified("selector", str(error))
                continue
            if detail:
                report.facts[f"{found.selector}"] = (
                    f"{found.entry.get('type', '')} 법선 {_vector(found.normal)} "
                    f"중심 {_vector(found.point)} 면적 {found.entry.get('area')} "
                    f"bbox {_vector((found.entry.get('bbox') or {}).get('size'))}"
                )
            else:
                report.facts[f"{found.selector}"] = found.label
        if not report.checks:
            report.ok("refs", f"기준을 읽었다 — 면 {len(sidecar.entries('faces'))}개, 에지 {len(sidecar.entries('edges'))}개.")
    return report


def _measured_size(sidecar: topology.Sidecar | None) -> tuple[float, float, float] | None:
    """위상 산출물에 커널이 적어 둔 부품 bbox 들을 합쳐 전체 bbox를 낸다."""
    if sidecar is None:
        return None
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    seen = False
    for shape in sidecar.entries("shapes"):
        box = shape.get("bbox")
        if not isinstance(box, dict) or not isinstance(box.get("min"), list) or not isinstance(box.get("max"), list):
            continue
        seen = True
        for axis in range(3):
            lo[axis] = min(lo[axis], float(box["min"][axis]))
            hi[axis] = max(hi[axis], float(box["max"][axis]))
    if not seen:
        return None
    return tuple(round(hi[axis] - lo[axis], 6) for axis in range(3))  # type: ignore[return-value]


def _major_planes(sidecar: topology.Sidecar, limit: int = 8) -> list[dict]:
    """면적 큰 평면부터. 사람이 "윗면"이라 부르는 것은 거의 항상 이 목록 위쪽에 있다."""
    planes = [entry for entry in sidecar.entries("faces") if str(entry.get("type", "")).upper() == "PLANE"]
    planes.sort(key=lambda entry: -(entry.get("area") or 0))
    return planes[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# measure · align · frame · diff
# ─────────────────────────────────────────────────────────────────────────────


def measure(step_path: str, *, source: str, target: str, axis: str | None) -> Report:
    """두 참조 사이 거리. 측정 방법을 결과에 같이 적는다 — 같은 숫자도 뜻이 다르다."""
    report = Report(tool="inspect measure", target=step_path)
    sidecar = freshness(report, step_path, topology.load_for(step_path))
    if sidecar is None:
        return report
    try:
        first, second = resolve(sidecar, source), resolve(sidecar, target)
    except SelectorError as error:
        report.unverified("selector", str(error))
        return report

    a, b = first.point, second.point
    if a is None or b is None:
        report.unverified("measure", f"{source} 또는 {target}에 좌표가 없다 — 잴 수 없다.")
        return report

    if axis:
        key = axis.lower()
        if key not in AXES:
            report.unverified("measure", f"모르는 축이다: {axis} (x/y/z)")
            return report
        index = AXES[key]
        distance = abs(a[index] - b[index])
        exact = first.is_planar and second.is_planar and _parallel(first.normal, second.normal)
        method = (
            f"{key} 축 평면 간격 — 두 면이 평행 평면이라 정확하다"
            if exact
            else f"{key} 축 중심 간 델타 — 평행 평면이 아니므로 면 간 최단거리가 아니다"
        )
    else:
        distance = math.dist(a, b)
        method = "중심 간 직선거리 — 면 간 최단거리가 아니다"

    report.facts.update(
        {
            "from": f"{first.selector} ({first.entry.get('type', '')})",
            "to": f"{second.selector} ({second.entry.get('type', '')})",
            "거리(mm)": round(distance, 6),
            "방법": method,
        }
    )
    report.ok("measure", f"{first.selector} → {second.selector} = {round(distance, 4)}mm ({method})")
    return report


def align(step_path: str, *, moving: str, target: str, mode: str, axis: str) -> Report:
    """두 참조가 맞닿아야 하는데 얼마나 어긋났는가. **읽기 전용 델타다** — STEP을 고치지 않는다."""
    report = Report(tool="inspect align", target=step_path)
    sidecar = freshness(report, step_path, topology.load_for(step_path))
    if sidecar is None:
        return report
    try:
        first, second = resolve(sidecar, moving), resolve(sidecar, target)
    except SelectorError as error:
        report.unverified("selector", str(error))
        return report
    key = axis.lower()
    if key not in AXES:
        report.unverified("align", f"모르는 축이다: {axis} (x/y/z)")
        return report
    index = AXES[key]

    if mode == "center":
        a, b = first.point, second.point
        if a is None or b is None:
            report.unverified("align", "중심 좌표가 없다 — 정렬 델타를 못 낸다.")
            return report
        delta = a[index] - b[index]
    else:  # flush — bbox 면끼리 맞춘다
        boxes = [(entry.entry.get("bbox") or {}) for entry in (first, second)]
        if not all(isinstance(box.get("min"), list) and isinstance(box.get("max"), list) for box in boxes):
            report.unverified("align", "bbox가 없어 flush 정렬을 못 낸다 — center 모드를 쓰라.")
            return report
        delta = float(boxes[0]["min"][index]) - float(boxes[1]["max"][index])

    report.facts.update({"moving": first.selector, "target": second.selector, "mode": mode, "축": key})
    report.facts["델타(mm)"] = round(delta, 6)
    if abs(delta) <= 1e-4:
        report.ok("align", f"{first.selector}와 {second.selector}가 {key} 축으로 맞닿아 있다 (델타 {round(delta, 6)}mm).")
    else:
        report.fail(
            "align",
            f"{first.selector}가 {second.selector}에서 {key} 축으로 {round(delta, 4)}mm 어긋났다. "
            "소스에서 고치고 다시 생성하라 — 이 동사는 고치지 않는다.",
        )
    return report


def frame(step_path: str, selector: str) -> Report:
    """이 참조의 월드 좌표계. 방향이 맞는가, 축이 X/Y/Z와 정렬됐는가."""
    report = Report(tool="inspect frame", target=step_path)
    sidecar = freshness(report, step_path, topology.load_for(step_path))
    if sidecar is None:
        return report
    try:
        found = resolve(sidecar, selector)
    except SelectorError as error:
        report.unverified("selector", str(error))
        return report

    report.facts.update({"참조": found.selector, "종류": found.entry.get("type", ""), "중심": _vector(found.point)})
    normal = found.normal
    if normal is None:
        report.unverified("frame", f"{found.selector}에 법선이 없다 — 방향을 판정하지 못한다.")
        return report
    report.facts["법선"] = _vector(normal)
    axis, cosine = _dominant_axis(normal)
    report.facts["주축"] = f"{axis} (정렬도 {round(cosine, 4)})"
    if cosine > 0.9999:
        report.ok("frame", f"{found.selector}의 법선이 {axis} 축과 정렬돼 있다.")
    else:
        report.unverified(
            "frame",
            f"{found.selector}의 법선이 어느 주축과도 정렬돼 있지 않다(최근접 {axis}, 정렬도 {round(cosine, 4)}). "
            "의도한 기울기인지 소스에서 확인하라.",
        )
    return report


def diff(before_path: str, after_path: str, *, planes: bool) -> Report:
    """고치기 전후로 **의도하지 않은 곳**이 변했는가. 수정 과업의 마지막 관문이다."""
    report = Report(tool="inspect diff", target=f"{before_path} → {after_path}")
    before, after = stepfile.read(before_path), stepfile.read(after_path)

    if before.sha256 == after.sha256:
        report.unverified("diff", "두 파일이 바이트로 같다 — 비교할 변화가 없다(고치기 전 파일을 넘겼는가?).")
        return report

    for label, key in (("솔리드", "solids"), ("면", "faces"), ("에지", "edges"), ("버텍스", "vertices")):
        old, new = getattr(before, key), getattr(after, key)
        report.facts[label] = f"{old} → {new}" + (f" ({new - old:+d})" if new != old else "")

    # diff는 두 파일을 **같은 방법으로** 재는 것이 중요하다. 한쪽만 커널 값을 쓰면 변화가
    # 아니라 방법 차이를 변화로 읽는다. 그래서 양쪽 모두 무커널 경계로 통일한다.
    (old_size, method), (new_size, _) = before.best_size_mm(), after.best_size_mm()
    if old_size and new_size:
        report.facts["치수 측정법"] = method
        deltas = [round(new_size[i] - old_size[i], 6) for i in range(3)]
        report.facts["치수 변화(mm)"] = " / ".join(f"{value:+g}" for value in deltas)
        moved = [axis for axis, value in zip("xyz", deltas, strict=True) if abs(value) > 1e-6]
        if moved:
            report.unverified(
                "bounds-changed",
                f"바깥 치수가 {', '.join(moved)} 축에서 변했다 — 의도한 변경인지 명세와 대조하라.",
            )
        else:
            report.ok("bounds", "바깥 치수는 그대로다.")

    if before.products != after.products:
        report.unverified(
            "products-changed",
            f"부품 이름 구성이 변했다: {before.products} → {after.products}",
        )
    if planes:
        report.unverified(
            "planes",
            "평면 단위 대조는 두 파일의 위상 산출물이 모두 있어야 한다 — 무커널 diff는 인구조사까지만 낸다.",
        )
    if not report.checks:
        report.ok("diff", "인구조사와 치수가 모두 같다 — 바이트만 달라졌다(생성 시각 등).")
    return report


# ─────────────────────────────────────────────────────────────────────────────


def _vector(value: object) -> str:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return "—"
    return "(" + ", ".join(f"{float(item):g}" for item in value) + ")"


def _parallel(first: list[float] | None, second: list[float] | None, tolerance: float = 1e-4) -> bool:
    if not first or not second:
        return False
    length = math.dist([0, 0, 0], first) * math.dist([0, 0, 0], second)
    if length == 0:
        return False
    cosine = sum(a * b for a, b in zip(first, second, strict=True)) / length
    return abs(abs(cosine) - 1.0) <= tolerance


def _dominant_axis(normal: list[float]) -> tuple[str, float]:
    length = math.dist([0, 0, 0], normal) or 1.0
    best, cosine = "x", 0.0
    for name, index in AXES.items():
        value = abs(normal[index]) / length
        if value > cosine:
            best, cosine = name, value
    return best, cosine
