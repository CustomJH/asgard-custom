"""G-code — 슬라이서 발견·슬라이싱·무의존 정적 검증.

## 이 모듈이 하는 일과 안 하는 일

한다: 이 기계에 깔린 슬라이서를 찾고, 메시가 슬라이스 가능한지 보고, 슬라이서 명령을 만들고,
생성된 `.gcode` 를 프린터로 넘기기 전에 정적으로 검증한다.

안 한다: 업로드, 작업 시작, 패키징, 프로파일 창작. **프린터 프로파일을 지어내지 않는다** —
지어낸 온도로 실물 장비가 움직이면 그것은 소프트웨어 버그가 아니라 화재다.

## 검증이 프로파일을 요구하는 이유

"이 G-code 가 유효한가"는 답할 수 없는 질문이다. 유효성은 항상 **어느 기계에 대해서** 유효한가
이고, 베드 크기·최대 Z·노즐·필라멘트가 없으면 XYZ 범위 위반을 판정할 근거가 없다. 그래서
프로파일이 필수 인자다. 프로파일 없이 통과를 내는 검증기는 통과를 파는 것이다.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .report import Report

# 선호 순서. Bambu Studio 는 감지돼도 선호하지 않는다 — macOS CLI 내보내기가 불안정하다.
BACKENDS = (
    ("orcaslicer", ("orcaslicer", "orca-slicer", "OrcaSlicer", "orca_slicer")),
    ("prusaslicer", ("prusa-slicer", "prusaslicer", "PrusaSlicer", "prusa-slicer-console")),
    ("curaengine", ("CuraEngine", "curaengine")),
    ("bambustudio", ("bambu-studio", "bambustudio", "BambuStudio")),
)
PREFERRED = ("orcaslicer", "prusaslicer", "curaengine")

# 슬라이스 입력으로 받는 것. STEP·DXF·SVG·URDF 는 받지 않는다 — cad 레인에서 메시로 먼저 내린다.
MESH_INPUTS = (".stl", ".obj", ".3mf", ".ply", ".glb", ".gltf")
REJECTED_INPUTS = (".step", ".stp", ".dxf", ".svg", ".urdf", ".sdf", ".srdf", ".scad")

_MOVE = re.compile(r"^G[01]\b", re.I)
_WORD = re.compile(r"([A-Za-z])\s*(-?\d+\.?\d*)")
# 명령 워드는 문자+숫자다. G/M/T 만 훑으면 다른 기종 방언(예: Q42)이 조용히 통과하므로
# 첫 워드를 통째로 받고, 아는 목록에 없으면 그대로 미지 명령으로 센다.
_COMMAND = re.compile(r"^([A-Za-z]\d+)", re.I)

# 이 명령들은 실물 장비를 뜨겁게 하거나 움직인다. 하나라도 없으면 그 사실을 말한다.
TEMPERATURE_COMMANDS = ("M104", "M109", "M140", "M190")
KNOWN_COMMANDS = {
    "G0", "G1", "G2", "G3", "G4", "G10", "G11", "G20", "G21", "G28", "G29", "G90", "G91", "G92",
    "M17", "M18", "M73", "M82", "M83", "M84", "M104", "M105", "M106", "M107", "M109", "M140",
    "M190", "M201", "M203", "M204", "M205", "M220", "M221", "M400", "M486", "M500", "M501",
    "M600", "M601", "M602", "M900", "M991", "T0", "T1", "T2", "T3",
}


@dataclass
class Profile:
    """프린터 프로파일. 지어내지 않고 사용자가 준 파일에서만 온다."""

    path: str
    backend: str
    native_config: str
    machine: dict
    filament: dict
    raw: dict

    @property
    def bed(self) -> tuple[float, float] | None:
        x, y = self.machine.get("bed_x"), self.machine.get("bed_y")
        return (float(x), float(y)) if x and y else None

    @property
    def max_z(self) -> float | None:
        value = self.machine.get("max_z") or self.machine.get("z_height")
        return float(value) if value else None


def load_profile(path: str | Path) -> tuple[Profile | None, str]:
    """프로파일을 읽는다. 빠진 필드는 채워 넣지 않고 이름으로 보고한다."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return None, f"프로파일을 읽지 못했다: {error}"
    if not isinstance(raw, dict):
        return None, "프로파일이 JSON 객체가 아니다."
    missing = [key for key in ("backend", "machine") if key not in raw]
    if missing:
        return None, f"프로파일에 필수 항목이 없다: {', '.join(missing)}"
    return (
        Profile(
            path=str(path),
            backend=str(raw.get("backend", "")),
            native_config=str(raw.get("native_config", "")),
            machine=raw.get("machine") or {},
            filament=raw.get("filament") or {},
            raw=raw,
        ),
        "",
    )


# ─────────────────────────────────────────────────────────────────────────────
# discover · inspect
# ─────────────────────────────────────────────────────────────────────────────


def discover(search_path: str | None = None) -> Report:
    """이 기계의 슬라이서 백엔드. 없는 것을 있다고 말하지 않는다."""
    report = Report(tool="gcode discover")
    found: dict[str, str] = {}
    for name, candidates in BACKENDS:
        for candidate in candidates:
            location = shutil.which(candidate, path=search_path)
            if location:
                found[name] = location
                break
    for name, _ in BACKENDS:
        report.facts[name] = found.get(name, "없음")
    if not found:
        report.fail(
            "no-backend",
            "슬라이서를 하나도 찾지 못했다. OrcaSlicer·PrusaSlicer·CuraEngine 중 하나를 설치하고 "
            "CLI 가 PATH 에 있는지 확인하라.",
        )
        return report
    preferred = next((name for name in PREFERRED if name in found), next(iter(found)))
    report.facts["선택"] = preferred
    if preferred == "bambustudio":
        report.unverified("backend-choice", "Bambu Studio 만 있다 — macOS CLI 내보내기가 불안정하니 결과를 반드시 검증하라.")
    else:
        report.ok("backend", f"{preferred} 를 쓴다 ({found[preferred]}).")
    return report


def inspect_mesh(path: str | Path) -> Report:
    """슬라이스 가능한 입력인가. 형식·크기·삼각형 수만 본다(수밀은 mesh_audit.mjs 몫이다)."""
    path = Path(path)
    report = Report(tool="gcode inspect", target=str(path))
    suffix = path.suffix.lower()
    report.facts["형식"] = suffix or "(확장자 없음)"

    if suffix in REJECTED_INPUTS:
        report.fail(
            "input-format",
            f"{suffix} 는 슬라이스 입력이 아니다 — cad 레인에서 메시(.stl/.3mf)로 먼저 내려라.",
        )
        return report
    if suffix not in MESH_INPUTS:
        report.fail("input-format", f"모르는 입력 형식이다: {suffix} (받는 것: {', '.join(MESH_INPUTS)})")
        return report
    if not path.is_file():
        report.fail("input-missing", f"입력 파일이 없다: {path}")
        return report

    size = path.stat().st_size
    report.facts["크기"] = f"{size / 1024:.1f} KiB"
    if size == 0:
        report.fail("input-empty", "입력 파일이 비었다.")
        return report

    if suffix == ".stl":
        triangles = _stl_triangles(path)
        if triangles is None:
            report.unverified("stl-parse", "STL 헤더를 읽지 못했다 — 삼각형 수를 판정하지 못한다.")
        else:
            report.facts["삼각형"] = triangles
            if triangles == 0:
                report.fail("mesh-empty", "삼각형이 0개다 — 빈 메시다.")
            else:
                report.ok("mesh", f"삼각형 {triangles}개 — 슬라이스 입력으로 받는다.")
    else:
        report.ok("mesh", f"{suffix} 를 슬라이스 입력으로 받는다.")

    report.unverified(
        "watertight",
        "수밀·살두께·오버행은 여기서 판정하지 않는다 — `node engine/scripts/mesh_audit.mjs` 를 돌려라.",
    )
    return report


def _stl_triangles(path: Path) -> int | None:
    try:
        with open(path, "rb") as handle:
            head = handle.read(84)
    except OSError:
        return None
    if len(head) < 84:
        return None
    if head[:5].lower().startswith(b"solid") and b"facet" in path.read_bytes()[:2048].lower():
        return path.read_text(encoding="utf-8", errors="replace").lower().count("facet normal")
    return int.from_bytes(head[80:84], "little")


# ─────────────────────────────────────────────────────────────────────────────
# slice
# ─────────────────────────────────────────────────────────────────────────────


def slice_command(profile: Profile, source: str, output: str, backend: str, search_path: str | None) -> tuple[list[str], str]:
    """슬라이서 명령을 만든다. 실행하지 않는다 — 드라이런이 먼저라는 규율이 여기 박혀 있다."""
    name = backend if backend != "auto" else profile.backend or "auto"
    if name == "auto":
        found = discover(search_path)
        name = str(found.facts.get("선택") or "")
    if not name:
        return [], "백엔드를 정하지 못했다 — `gcode discover` 로 먼저 확인하라."

    executable = None
    for candidate_name, candidates in BACKENDS:
        if candidate_name != name:
            continue
        for candidate in candidates:
            executable = shutil.which(candidate, path=search_path)
            if executable:
                break
    if not executable:
        return [], f"{name} 를 PATH 에서 찾지 못했다."
    if not profile.native_config:
        return [], "프로파일에 `native_config`(슬라이서 자체 설정 파일 절대경로)가 없다."

    if name == "curaengine":
        command = [executable, "slice", "-j", profile.native_config, "-l", source, "-o", output]
    else:  # Orca·Prusa·Bambu 는 PrusaSlicer 계열 CLI 문법을 공유한다
        command = [executable, "--load", profile.native_config, "--export-gcode", "--output", output, source]
    return command, ""


# ─────────────────────────────────────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────────────────────────────────────


def validate(gcode_path: str | Path, profile: Profile) -> Report:
    """생성된 G-code 를 프린터로 넘기기 전에 정적으로 본다. 의존성 없음.

    보는 것: 내용 유무, 온도 명령, 이동 명령, 압출, XYZ 범위, 미지 명령. 마지막 항목이 특히
    중요한데, 슬라이서가 다른 기종용 방언을 뱉으면 프린터가 무시하거나 오작동한다.
    """
    path = Path(gcode_path)
    report = Report(tool="gcode validate", target=str(path))
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        report.fail("gcode-read", f"G-code 를 읽지 못했다: {error}")
        return report

    lines = text.splitlines()
    report.facts["줄 수"] = len(lines)
    if not lines:
        report.fail("gcode-empty", "G-code 가 비었다.")
        return report

    seen: dict[str, int] = {}
    unknown: dict[str, int] = {}
    extrusion = 0.0
    moves = 0
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    position = [0.0, 0.0, 0.0]
    absolute = True

    for line in lines:
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        command = _COMMAND.match(code)
        if command:
            name = command.group(1).upper()
            seen[name] = seen.get(name, 0) + 1
            if name not in KNOWN_COMMANDS:
                unknown[name] = unknown.get(name, 0) + 1
            if name == "G90":
                absolute = True
            elif name == "G91":
                absolute = False
        if not _MOVE.match(code):
            continue
        moves += 1
        words = dict(_WORD.findall(code))
        for axis, index in (("X", 0), ("Y", 1), ("Z", 2)):
            if axis in words:
                try:
                    value = float(words[axis])
                except ValueError:
                    continue
                position[index] = value if absolute else position[index] + value
                lo[index] = min(lo[index], position[index])
                hi[index] = max(hi[index], position[index])
        if "E" in words:
            try:
                extrusion = max(extrusion, abs(float(words["E"])))
            except ValueError:
                pass

    report.facts["이동 명령"] = moves
    report.facts["명령 종류"] = len(seen)
    if moves == 0:
        report.fail("gcode-no-motion", "이동 명령(G0/G1)이 하나도 없다 — 빈 작업이다.")

    temperature = [name for name in TEMPERATURE_COMMANDS if name in seen]
    report.facts["온도 명령"] = ", ".join(temperature) or "없음"
    if not temperature:
        report.fail("gcode-no-heat", "온도 명령이 없다 — 차가운 노즐로 압출을 시도하게 된다.")
    else:
        report.ok("gcode-heat", f"온도 명령이 있다: {', '.join(temperature)}")

    report.facts["최대 E"] = round(extrusion, 3)
    if extrusion <= 0:
        report.fail("gcode-no-extrusion", "압출 값이 0 이다 — 아무것도 뽑지 않는 경로다.")

    if moves and all(value != float("inf") for value in lo):
        size = [round(hi[i] - lo[i], 3) for i in range(3)]
        report.facts["이동 범위(mm)"] = f"{size[0]:g} × {size[1]:g} × {size[2]:g}"
        report.facts["원점 오프셋"] = f"({lo[0]:g}, {lo[1]:g}, {lo[2]:g})"
        _bounds_check(report, lo, hi, profile)
    else:
        report.unverified("gcode-bounds", "이동 좌표를 읽지 못했다 — 범위를 판정하지 못한다.")

    if unknown:
        listed = ", ".join(f"{name}×{count}" for name, count in sorted(unknown.items())[:10])
        report.unverified(
            "gcode-unknown",
            f"모르는 명령이 {len(unknown)}종 있다({listed}). 다른 기종용 방언일 수 있으니 프린터 문서와 대조하라.",
        )
    else:
        report.ok("gcode-dialect", "모르는 명령이 없다.")
    return report


def _bounds_check(report: Report, lo: list[float], hi: list[float], profile: Profile) -> None:
    bed = profile.bed
    if bed is None:
        report.unverified("bed-bounds", "프로파일에 bed_x/bed_y 가 없다 — 베드 밖 이동을 판정하지 못한다.")
    else:
        violations = []
        if lo[0] < 0 or lo[1] < 0:
            violations.append(f"음수 좌표 ({lo[0]:g}, {lo[1]:g})")
        if hi[0] > bed[0] or hi[1] > bed[1]:
            violations.append(f"베드 {bed[0]:g}×{bed[1]:g} 초과 ({hi[0]:g}, {hi[1]:g})")
        if violations:
            report.fail("bed-bounds", "이동이 베드를 벗어난다 — " + "; ".join(violations))
        else:
            report.ok("bed-bounds", f"모든 이동이 베드 {bed[0]:g}×{bed[1]:g}mm 안에 있다.")

    max_z = profile.max_z
    if max_z is None:
        report.unverified("z-bounds", "프로파일에 max_z 가 없다 — 최대 높이를 판정하지 못한다.")
    elif hi[2] > max_z:
        report.fail("z-bounds", f"최대 Z {hi[2]:g}mm 가 기계 한계 {max_z:g}mm 를 넘는다.")
    else:
        report.ok("z-bounds", f"최대 Z {hi[2]:g}mm — 한계 {max_z:g}mm 안이다.")
