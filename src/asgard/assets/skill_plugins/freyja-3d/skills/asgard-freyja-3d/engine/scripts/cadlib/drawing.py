"""DXF — 2D 도면·절단 레이아웃의 생성과 무의존 검증.

## 두 몫이 한 파일에 있는 이유

생성은 `ezdxf` 가 필요하다(만들려면 라이브러리가 든다). 그런데 **검사는 아니다.** ASCII DXF 는
그룹코드 쌍의 평문 나열이라, 단위·레이어·엔티티·닫힘 여부·도면 범위가 전부 표면에서 읽힌다.

이전 판에서는 "이미 있는 .dxf 를 검사하려면 ezdxf 로 직접 읽어라"가 문서의 답이었다. 그 말은
검사가 사람 손에 맡겨졌다는 뜻이고, 손에 맡겨진 검사는 바쁠 때 건너뛴다. 여기서는 설치 없이 도는
검사를 붙여서 건너뛸 이유를 없앤다.

## 절단 발주에서 실제로 사고를 내는 것

순서대로: ① 단위 미상(`$INSUNITS` 없음) — 서비스가 치수를 신뢰하지 않거나, 더 나쁘게는 인치로
읽는다. ② 열린 컨투어 — 절단 경로가 되지 못한다. ③ 굽힘선과 절단선이 같은 레이어 — 하류가
가르지 못한다. ④ 중복 엔티티 — 같은 선을 두 번 태운다.

넷 다 여기서 잡는다.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .report import Report

# $INSUNITS 값. 1=inch, 4=mm 만 치수를 신뢰한다 — 나머지는 절단 서비스가 되묻는다.
UNITS = {
    0: ("미지정", None),
    1: ("inch", 25.4),
    2: ("feet", 304.8),
    4: ("mm", 1.0),
    5: ("cm", 10.0),
    6: ("m", 1000.0),
}
TRUSTED_UNITS = (1, 4)

# 절단 프로파일이 될 수 있는 엔티티.
CONTOUR_TYPES = ("LWPOLYLINE", "POLYLINE", "CIRCLE", "ELLIPSE", "SPLINE", "ARC", "LINE")


def generate(script: str | Path, out: str | Path | None) -> Report:
    """`gen_dxf()` 를 정의한 파이썬 소스를 실행해 DXF 를 쓴다. 출력 경로는 CLI 가 소유한다."""
    import runpy  # noqa: PLC0415 — 소스 실행 경로에서만 필요하다

    script = Path(script).resolve()
    report = Report(tool="dxf", target=str(script))
    try:
        import ezdxf  # noqa: F401, PLC0415
    except ImportError as error:
        report.fail("ezdxf-missing", f"ezdxf 를 찾지 못했다 — 런처(`cad.py dxf`)로 실행하라. 원인: {error}")
        return report

    namespace = runpy.run_path(str(script), run_name="__dxf_model__")
    generator = namespace.get("gen_dxf")
    if not callable(generator):
        report.fail("contract", "소스에 `gen_dxf()` 가 없다 — DXF 레인의 정본 진입점이다.")
        return report

    document: Any = generator()
    if not hasattr(document, "saveas"):
        report.fail("contract", f"`gen_dxf()` 가 ezdxf 문서를 돌려주지 않았다: {type(document).__name__}")
        return report

    target = Path(out) if out else script.parent / f"{script.stem}.dxf"
    target.parent.mkdir(parents=True, exist_ok=True)
    document.saveas(str(target))
    report.facts["산출물"] = str(target)

    written = inspect(target)
    report.facts.update(written.facts)
    report.checks.extend(written.checks)
    return report


def inspect(path: str | Path) -> Report:
    """DXF 를 그룹코드로 직접 읽어 검사한다. 의존성 없음 — 어떤 DXF 에나 돈다."""
    path = Path(path)
    report = Report(tool="dxf inspect", target=str(path))
    raw = path.read_bytes()

    if raw[:18].decode("latin-1", "replace").startswith("AutoCAD Binary DXF"):
        report.unverified("dxf-binary", "바이너리 DXF 다 — 이 검사는 ASCII DXF 만 읽는다. 판정 불능이다.")
        return report

    pairs = _pairs(raw.decode("utf-8", errors="replace"))
    if not pairs:
        report.fail("dxf-empty", "그룹코드 쌍을 하나도 읽지 못했다 — DXF 가 아니거나 손상됐다.")
        return report

    header = _header(pairs)
    entities, layers = _entities(pairs)

    # ── 단위 ──────────────────────────────────────────────────────────────────
    insunits = header.get("$INSUNITS")
    name, scale = UNITS.get(int(insunits), (f"코드 {insunits}", None)) if insunits is not None else ("없음", None)
    report.facts["단위"] = f"{name}" + (f" (1 = {scale}mm)" if scale else "")
    if insunits is None or int(insunits) not in TRUSTED_UNITS:
        report.fail(
            "dxf-units",
            f"$INSUNITS 가 {name} 다 — 절단 서비스가 치수를 신뢰하지 않는다. "
            "소스에 `doc.units = ezdxf.units.MM` 을 넣어라. 조용히 재스케일하지 않는다.",
        )
    else:
        report.ok("dxf-units", f"단위가 {name} 로 명시돼 있다.")

    # ── 엔티티·레이어 ─────────────────────────────────────────────────────────
    total = sum(entities.values())
    report.facts["엔티티"] = f"{total}개 — " + ", ".join(f"{key} {value}" for key, value in sorted(entities.items()))
    report.facts["레이어"] = ", ".join(sorted(layers)) or "(없음)"
    if total == 0:
        report.fail("dxf-empty", "모델스페이스에 엔티티가 없다 — 빈 도면이다.")
        return report

    contours = sum(entities.get(key, 0) for key in CONTOUR_TYPES)
    if contours == 0:
        report.fail("dxf-no-contour", "절단 경로가 될 엔티티가 하나도 없다(폴리라인·원·호·선).")

    # ── 닫힘 ──────────────────────────────────────────────────────────────────
    closed, open_count = _polyline_closure(pairs)
    if closed or open_count:
        report.facts["폴리라인"] = f"닫힘 {closed} / 열림 {open_count}"
        if open_count:
            report.unverified(
                "dxf-open-contour",
                f"열린 폴리라인이 {open_count}개 있다. 절단 프로파일은 닫혀야 한다 — "
                "각인·참조 형상으로 의도한 것이면 그렇게 보고하라.",
            )
        else:
            report.ok("dxf-closed", f"폴리라인 {closed}개가 모두 닫혀 있다.")

    # ── 굽힘 레이어 ───────────────────────────────────────────────────────────
    bend = sorted(layer for layer in layers if "bend" in layer.lower() or "굽힘" in layer)
    if bend:
        report.facts["굽힘 레이어"] = ", ".join(bend)
        report.ok("dxf-bend-layer", f"굽힘 의도가 레이어로 분리돼 있다: {', '.join(bend)}")
    elif len(layers) <= 1:
        report.unverified(
            "dxf-single-layer",
            f"레이어가 {len(layers)}개뿐이다 — 굽힘·각인이 섞여 있으면 하류가 절단과 가르지 못한다.",
        )

    # ── 범위 ──────────────────────────────────────────────────────────────────
    extents = _extents(header, scale)
    if extents:
        report.facts["도면 범위(mm)"] = f"{extents[0]:g} × {extents[1]:g}"
        if min(extents) <= 0:
            report.fail("dxf-degenerate", "도면 범위의 한 변이 0 이다 — 형상이 한 직선 위에 있다.")
    else:
        report.unverified("dxf-extents", "$EXTMIN/$EXTMAX 를 읽지 못했다 — 도면 크기를 판정하지 못한다.")

    return report


# ─────────────────────────────────────────────────────────────────────────────


def _pairs(text: str) -> list[tuple[int, str]]:
    """DXF 는 (그룹코드, 값)이 한 줄씩 번갈아 나온다. 그 구조만 믿고 읽는다."""
    lines = text.splitlines()
    out: list[tuple[int, str]] = []
    for index in range(0, len(lines) - 1, 2):
        code = lines[index].strip()
        if not code.lstrip("-").isdigit():
            # 줄 짝이 어긋났다 — 한 줄 밀어 재동기화를 시도한다.
            continue
        out.append((int(code), lines[index + 1].strip()))
    return out


def _header(pairs: list[tuple[int, str]]) -> dict[str, float]:
    """HEADER 섹션의 변수. 코드 9 가 이름이고 바로 다음 쌍이 값이다."""
    header: dict[str, float] = {}
    for position, (code, value) in enumerate(pairs):
        if code != 9 or position + 1 >= len(pairs):
            continue
        following = pairs[position + 1]
        try:
            header[value] = float(following[1])
        except ValueError:
            continue
        # 좌표형 변수($EXTMIN 등)는 10/20/30 으로 이어진다 — 축마다 따로 담는다.
        for axis_offset, suffix in ((1, ".x"), (2, ".y"), (3, ".z")):
            if position + axis_offset < len(pairs):
                axis_code, axis_value = pairs[position + axis_offset]
                if axis_code in (10, 20, 30):
                    try:
                        header[f"{value}{suffix}"] = float(axis_value)
                    except ValueError:
                        pass
    return header


def _entities(pairs: list[tuple[int, str]]) -> tuple[dict[str, int], set[str]]:
    """ENTITIES 섹션의 종류별 개수와 등장한 레이어 이름."""
    counts: dict[str, int] = {}
    layers: set[str] = set()
    inside = False
    for code, value in pairs:
        if code == 2 and value == "ENTITIES":
            inside = True
            continue
        if code == 0 and value == "ENDSEC":
            inside = False
            continue
        if not inside:
            continue
        if code == 0:
            counts[value] = counts.get(value, 0) + 1
        elif code == 8 and value:
            layers.add(value)
    return counts, layers


def _polyline_closure(pairs: list[tuple[int, str]]) -> tuple[int, int]:
    """LWPOLYLINE 의 코드 70 비트 0 이 닫힘 플래그다. 엔티티마다 첫 70 만 본다."""
    closed = open_count = 0
    current: str | None = None
    seen_flag = False
    for code, value in pairs:
        if code == 0:
            if current in ("LWPOLYLINE", "POLYLINE") and not seen_flag:
                open_count += 1  # 플래그가 아예 없으면 열린 것으로 읽는 것이 규격 기본값이다
            current = value if value in ("LWPOLYLINE", "POLYLINE") else None
            seen_flag = False
            continue
        if current and code == 70 and not seen_flag:
            seen_flag = True
            try:
                flag = int(value)
            except ValueError:
                continue
            if flag & 1:
                closed += 1
            else:
                open_count += 1
    if current in ("LWPOLYLINE", "POLYLINE") and not seen_flag:
        open_count += 1
    return closed, open_count


def _extents(header: dict[str, float], scale: float | None) -> tuple[float, float] | None:
    keys = ("$EXTMIN.x", "$EXTMIN.y", "$EXTMAX.x", "$EXTMAX.y")
    if not all(key in header for key in keys):
        return None
    width = header["$EXTMAX.x"] - header["$EXTMIN.x"]
    height = header["$EXTMAX.y"] - header["$EXTMIN.y"]
    if not all(math.isfinite(value) for value in (width, height)):
        return None
    factor = scale or 1.0
    return round(width * factor, 4), round(height * factor, 4)
