"""ISO 10303-21 무커널 판독 — 커널 없이 STEP에서 사실을 읽는다.

## 왜 이것이 따로 있는가

이전 판에서는 STEP에 관한 모든 질문이 OpenCASCADE를 요구했다. 결과적으로 커널 휠(수백 MB)을
받기 전에는 **"이 파일이 STEP이 맞긴 한가"조차 답하지 못했다.** 그런데 배달 사고의 상당수는
커널이 필요 없는 자리에서 난다 — 확장자만 STEP 인 메시, 스키마가 없는 파일, 단위가 미터인데
치수는 밀리미터로 보고된 파일, 솔리드가 하나도 없는 껍데기.

STEP 물리 파일은 텍스트 교환 포맷이고, 그 사실들은 전부 파일 표면에 적혀 있다. 여기서 읽는다.

## 이 모듈이 답하는 것 / 답하지 못하는 것

답한다: 스키마(AP203/214/242), 길이 단위와 그 배율, 부품 이름과 조립 트리, 위상 인구조사
(면·에지·버텍스·셸·솔리드 수), 두 종류의 좌표 경계, 파일 해시.

답하지 못한다: **정확한 부피·면적·질량중심·bbox**. 그것들은 B-Rep 평가가 필요하고 평가에는
커널이 든다. 이 모듈은 그 숫자를 추정해서 내지 않는다 — 추정치를 측정값 자리에 놓는 것이 이
레인에서 가장 비싼 거짓말이다.

## 경계를 둘로 나눠 내는 이유 (실측으로 배운 것)

처음에는 모든 `CARTESIAN_POINT`의 최소·최대를 내고 "자유곡면이 없으면 실제 bbox와 같다"고
표시했다. **틀렸다.** 실측: 구멍 하나 뚫린 40×20×9.3mm 조립체에서 z 상한이 45.12mm로 나왔다.
범인은 원통면의 축 배치(`AXIS2_PLACEMENT_3D`)가 쓰는 좌표였다 — 커널이 파라미터화 원점을 형상
바깥 임의의 자리에 놓고, 그 점도 `CARTESIAN_POINT` 다. 자유곡면 유무와 무관한 문제였다.

그래서 두 경계를 따로 내고, 각각이 어느 쪽으로 틀리는지를 이름에 박는다:

    vertex_*  VERTEX_POINT가 실제로 가리키는 점만. 형상 **위**의 점이므로 다면체에서는 정확하고,
              곡면이 있으면 실루엣이 버텍스 밖으로 나가므로 **하한**이다.
    hull_*    모든 CARTESIAN_POINT. 배치·축 좌표가 섞이므로 언제나 **상한**이다.

둘 중 어느 것도 "정확한 bbox"라고 부르지 않는다. 진짜 bbox가 필요하면 위상 산출물에 커널이
적어 둔 값을 읽는다(`verbs.refs`가 그렇게 한다) — 그것이 유일하게 잰 숫자다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = "ISO-10303-21;"

# 실제 형상을 이루는 위상 요소. 인구조사의 대상이고, 이 중 하나도 없으면 STEP이 비어 있다.
TOPOLOGY_TYPES = (
    "ADVANCED_FACE",
    "FACE_SURFACE",
    "EDGE_CURVE",
    "VERTEX_POINT",
    "CLOSED_SHELL",
    "OPEN_SHELL",
    "MANIFOLD_SOLID_BREP",
    "BREP_WITH_VOIDS",
    "SHELL_BASED_SURFACE_MODEL",
)

# SI 접두사 → 미터 대비 배율. STEP은 길이 단위를 SI_UNIT의 접두사로 적는다.
_SI_PREFIX = {
    "EXA": 1e18, "PETA": 1e15, "TERA": 1e12, "GIGA": 1e9, "MEGA": 1e6,
    "KILO": 1e3, "HECTO": 1e2, "DECA": 1e1, "DECI": 1e-1, "CENTI": 1e-2,
    "MILLI": 1e-3, "MICRO": 1e-6, "NANO": 1e-9, "PICO": 1e-12,
}

_INSTANCE = re.compile(r"#(\d+)\s*=\s*([A-Z_0-9]+)\s*\(", re.I)
_SI_UNIT = re.compile(r"SI_UNIT\s*\(\s*(?:\.([A-Z]+)\.|\$)\s*,\s*\.([A-Z]+)\.\s*\)", re.I)
# 문자열은 이미 자리표시자로 바뀐 뒤라 따옴표가 아니라 \x00N\x00을 찾는다.
_CONVERSION = re.compile(r"CONVERSION_BASED_UNIT\s*\(\s*\x00(\d+)\x00", re.I)
_MEASURE_WITH_UNIT = re.compile(r"LENGTH_MEASURE\s*\(\s*([-+0-9.eE]+)\s*\)", re.I)


@dataclass
class StepFacts:
    """무커널로 읽어낸 STEP의 사실. 측정값이 아닌 것은 이름으로 구분된다."""

    path: str
    sha256: str
    bytes: int
    schema: str = ""
    schema_family: str = ""
    length_unit: str = ""
    length_scale_mm: float | None = None  # 파일 단위 1이 몇 mm 인가
    products: list[str] = field(default_factory=list)
    assembly_edges: list[tuple[str, str]] = field(default_factory=list)
    census: dict[str, int] = field(default_factory=dict)
    entities: int = 0
    hull_min: tuple[float, float, float] | None = None
    hull_max: tuple[float, float, float] | None = None
    vertex_min: tuple[float, float, float] | None = None
    vertex_max: tuple[float, float, float] | None = None
    curved_geometry: bool = False
    problems: list[str] = field(default_factory=list)

    @property
    def solids(self) -> int:
        return self.census.get("MANIFOLD_SOLID_BREP", 0) + self.census.get("BREP_WITH_VOIDS", 0)

    @property
    def faces(self) -> int:
        return self.census.get("ADVANCED_FACE", 0) + self.census.get("FACE_SURFACE", 0)

    @property
    def edges(self) -> int:
        return self.census.get("EDGE_CURVE", 0)

    @property
    def vertices(self) -> int:
        return self.census.get("VERTEX_POINT", 0)

    @staticmethod
    def _size(low, high) -> tuple[float, float, float] | None:
        if low is None or high is None:
            return None
        return tuple(round(hi - lo, 6) for lo, hi in zip(low, high, strict=True))  # type: ignore[return-value]

    @property
    def hull_size(self) -> tuple[float, float, float] | None:
        """모든 좌표의 경계 — 배치·축 좌표를 포함하므로 **상한**이다."""
        return self._size(self.hull_min, self.hull_max)

    @property
    def vertex_size(self) -> tuple[float, float, float] | None:
        """버텍스만의 경계 — 다면체면 정확하고, 곡면이 있으면 **하한**이다."""
        return self._size(self.vertex_min, self.vertex_max)

    @property
    def polyhedral(self) -> bool:
        """곡면이 하나도 없으면 버텍스 경계가 곧 실제 bbox 다."""
        return not any(
            self.census.get(key) for key in ("CIRCLE", "B_SPLINE_SURFACE_WITH_KNOTS", "B_SPLINE_CURVE_WITH_KNOTS")
        ) and not self.curved_geometry

    def _mm(self, size) -> tuple[float, float, float] | None:
        if size is None or self.length_scale_mm is None:
            return None
        return tuple(round(value * self.length_scale_mm, 6) for value in size)  # type: ignore[return-value]

    def hull_size_mm(self) -> tuple[float, float, float] | None:
        """상한 치수를 mm로. 배율을 모르면 None — 모르는 배율을 1로 가정하지 않는다."""
        return self._mm(self.hull_size)

    def vertex_size_mm(self) -> tuple[float, float, float] | None:
        return self._mm(self.vertex_size)

    def best_size_mm(self) -> tuple[tuple[float, float, float] | None, str]:
        """낼 수 있는 가장 좋은 치수와, 그 숫자가 어느 쪽으로 틀리는지의 설명.

        커널이 잰 진짜 bbox는 위상 산출물에 있다. 그것이 없을 때 쓰는 차선이고, 차선이라는
        사실을 문자열로 같이 낸다 — 숫자만 내면 측정값 행세를 한다.
        """
        vertex = self.vertex_size_mm()
        if vertex and self.polyhedral:
            return vertex, "버텍스 경계 — 곡면이 없어 실제 bbox와 같다"
        if vertex:
            return vertex, "버텍스 경계 — 곡면 실루엣이 빠져 실제보다 작을 수 있다(하한)"
        hull = self.hull_size_mm()
        if hull:
            return hull, "좌표 상한 — 배치·축 좌표가 섞여 실제보다 크다(상한)"
        return None, ""

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "schema": self.schema,
            "schemaFamily": self.schema_family,
            "lengthUnit": self.length_unit,
            "lengthScaleMm": self.length_scale_mm,
            "products": self.products,
            "assemblyEdges": [list(edge) for edge in self.assembly_edges],
            "entities": self.entities,
            "census": self.census,
            "solids": self.solids,
            "faces": self.faces,
            "edges": self.edges,
            "vertices": self.vertices,
            "bounds": {
                "vertex": {
                    "min": list(self.vertex_min) if self.vertex_min else None,
                    "max": list(self.vertex_max) if self.vertex_max else None,
                    "size": list(self.vertex_size) if self.vertex_size else None,
                    "sizeMm": list(self.vertex_size_mm() or ()) or None,
                    "exactness": "정확" if self.polyhedral else "하한",
                },
                "hull": {
                    "min": list(self.hull_min) if self.hull_min else None,
                    "max": list(self.hull_max) if self.hull_max else None,
                    "size": list(self.hull_size) if self.hull_size else None,
                    "sizeMm": list(self.hull_size_mm() or ()) or None,
                    "exactness": "상한",
                },
                "note": (
                    "어느 쪽도 커널이 잰 bbox가 아니다. 진짜 bbox는 위상 산출물(.step.glb)에 있다."
                ),
            },
            "problems": self.problems,
        }


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def looks_like_step(path: str | Path) -> bool:
    """확장자가 아니라 내용으로 판정한다. 확장자만 바꾼 메시가 이 레인의 1번 사고다."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
    except OSError:
        return False
    # 선행 공백·BOM을 허용한다. 규격은 첫 토큰을 고정하지만 실물 파일은 BOM을 달고 온다.
    text = head.lstrip(b"\xef\xbb\xbf").lstrip()
    return text.upper().startswith(MAGIC.encode())


def _strip_strings(text: str) -> tuple[str, list[str]]:
    """작은따옴표 문자열을 제거하고 자리표시자로 바꾼다.

    STEP 문자열 안에는 괄호·쉼표·엔티티처럼 생긴 바이트가 얼마든지 들어갈 수 있다(부품 이름이
    대표적이다). 제거하지 않고 정규식을 돌리면 이름 안의 괄호가 구조로 읽힌다. `''`는 규격상
    escape 된 따옴표 한 글자다.
    """
    out: list[str] = []
    literals: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char != "'":
            out.append(char)
            index += 1
            continue
        index += 1
        buffer: list[str] = []
        while index < length:
            if text[index] == "'":
                if index + 1 < length and text[index + 1] == "'":
                    buffer.append("'")
                    index += 2
                    continue
                index += 1
                break
            buffer.append(text[index])
            index += 1
        literals.append("".join(buffer))
        out.append(f"\x00{len(literals) - 1}\x00")
    return "".join(out), literals


def read(path: str | Path) -> StepFacts:
    """STEP 물리 파일을 커널 없이 읽는다. 읽지 못한 것은 `problems`에 이름으로 남는다."""
    path = Path(path)
    facts = StepFacts(path=str(path), sha256=sha256_file(path), bytes=path.stat().st_size)

    raw = path.read_text(encoding="utf-8", errors="replace")
    if not looks_like_step(path):
        facts.problems.append(
            f"ISO-10303-21 머리표가 없다 — STEP 물리 파일이 아니다(첫 24바이트: {raw[:24]!r})."
        )
        return facts

    body, literals = _strip_strings(raw)

    # ── 스키마 ────────────────────────────────────────────────────────────────
    schema = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*\x00(\d+)\x00", body, re.I)
    if schema:
        facts.schema = literals[int(schema.group(1))]
        upper = facts.schema.upper()
        for family, mark in (("AP242", "10303 242"), ("AP214", "10303 214"), ("AP203", "10303 203")):
            if mark in upper or family in upper:
                facts.schema_family = family
                break
        if not facts.schema_family and "CONFIG_CONTROL_DESIGN" in upper:
            facts.schema_family = "AP203"
        if not facts.schema_family and "AUTOMOTIVE_DESIGN" in upper:
            facts.schema_family = "AP214"
    else:
        facts.problems.append("FILE_SCHEMA를 읽지 못했다 — 하류 도구가 스키마를 못 고른다.")

    data_start = body.upper().find("DATA;")
    data = body[data_start:] if data_start >= 0 else body
    if data_start < 0:
        facts.problems.append("DATA 섹션이 없다 — 헤더만 있는 파일이다.")

    # ── 엔티티 인구조사 ───────────────────────────────────────────────────────
    census: dict[str, int] = {}
    for match in _INSTANCE.finditer(data):
        name = match.group(2).upper()
        census[name] = census.get(name, 0) + 1
    facts.entities = sum(census.values())
    facts.census = {key: census[key] for key in TOPOLOGY_TYPES if key in census}
    # 위상 목록에 없지만 세어두면 진단에 쓰이는 것들.
    for extra in ("CARTESIAN_POINT", "CIRCLE", "B_SPLINE_SURFACE_WITH_KNOTS", "B_SPLINE_CURVE_WITH_KNOTS"):
        if extra in census:
            facts.census[extra] = census[extra]
    facts.curved_geometry = any(
        key in census
        for key in ("B_SPLINE_SURFACE_WITH_KNOTS", "B_SPLINE_CURVE_WITH_KNOTS", "RATIONAL_B_SPLINE_SURFACE")
    )

    # ── 길이 단위 ─────────────────────────────────────────────────────────────
    facts.length_unit, facts.length_scale_mm = _length_unit(data, literals)
    if facts.length_scale_mm is None:
        facts.problems.append(
            "길이 단위를 읽지 못했다 — 이 파일의 숫자를 mm로 환산할 근거가 없다(치수 보고 금지)."
        )

    # ── 부품 이름과 조립 트리 ─────────────────────────────────────────────────
    for match in re.finditer(r"PRODUCT\s*\(\s*\x00(\d+)\x00\s*,", data, re.I):
        name = literals[int(match.group(1))]
        if name and name not in facts.products:
            facts.products.append(name)
    facts.assembly_edges = _assembly(data, literals)

    # ── 좌표 경계 둘 ──────────────────────────────────────────────────────────
    facts.hull_min, facts.hull_max = _hull(data)
    facts.vertex_min, facts.vertex_max = _vertex_bounds(data)

    if facts.entities and not any(facts.census.get(key) for key in TOPOLOGY_TYPES):
        facts.problems.append("위상 요소가 하나도 없다 — 형상이 비었거나 지원하지 않는 표현이다.")
    return facts


def _length_unit(data: str, literals: list[str]) -> tuple[str, float | None]:
    """길이 단위와 mm 배율을 찾는다.

    두 갈래를 본다. ① `SI_UNIT(.MILLI.,.METRE.)` — 접두사가 곧 배율이다. ② 인치처럼 SI가
    아닌 단위는 `CONVERSION_BASED_UNIT`이 이름과 환산계수를 함께 적는다. 둘 다 못 읽으면
    **1로 가정하지 않고 None을 낸다** — 모르는 배율을 1로 놓는 것이 스케일 사고의 출발이다.
    """
    for match in _SI_UNIT.finditer(data):
        prefix, unit = (match.group(1) or "").upper(), match.group(2).upper()
        if unit != "METRE":
            continue
        scale = _SI_PREFIX.get(prefix, 1.0) if prefix else 1.0
        label = f"{prefix.lower()}metre" if prefix else "metre"
        return label, scale * 1000.0  # 미터 → mm

    for match in _CONVERSION.finditer(data):
        name = literals[int(match.group(1))]
        tail = data[match.end() : match.end() + 400]
        measure = _MEASURE_WITH_UNIT.search(tail)
        if not measure:
            continue
        try:
            factor = float(measure.group(1))
        except ValueError:
            continue
        # 환산 대상이 미터면 factor는 "이 단위 1 = factor 미터". 접두사 있는 SI가 뒤따르면
        # 그 배율까지 곱해야 하지만, 실물 파일에서는 거의 항상 metre 기준이다.
        si = _SI_UNIT.search(tail)
        base = 1000.0
        if si and si.group(2).upper() == "METRE":
            base = _SI_PREFIX.get((si.group(1) or "").upper(), 1.0) * 1000.0
        return name or "conversion_based", factor * base
    return "", None


def _assembly(data: str, literals: list[str]) -> list[tuple[str, str]]:
    """NEXT_ASSEMBLY_USAGE_OCCURRENCE로 부모→자식 관계를 읽는다.

    참조가 `#N`이라 이름을 바로 주지 않는다. PRODUCT_DEFINITION 체인을 전부 되짚는 대신,
    같은 엔티티가 통상 함께 주는 id/이름 문자열을 쓴다. 이름이 비면 그 간선은 버린다 —
    `('', '')` 짝은 트리를 그리는 데 아무 도움이 안 되면서 있는 것처럼 보인다.
    """
    edges: list[tuple[str, str]] = []
    for match in re.finditer(
        r"NEXT_ASSEMBLY_USAGE_OCCURRENCE\s*\(\s*\x00(\d+)\x00\s*,\s*\x00(\d+)\x00\s*,\s*\x00(\d+)\x00",
        data,
        re.I,
    ):
        identifier = literals[int(match.group(1))]
        name = literals[int(match.group(2))]
        if identifier or name:
            edges.append((identifier, name))
    return edges


def _points_by_id(data: str) -> dict[str, tuple[float, float, float]]:
    """`#N -> (x, y, z)` 색인. 버텍스 경계를 뽑으려면 참조를 되짚어야 한다."""
    found: dict[str, tuple[float, float, float]] = {}
    for match in re.finditer(
        r"#(\d+)\s*=\s*CARTESIAN_POINT\s*\(\s*\x00\d+\x00\s*,\s*\(([^)]*)\)", data, re.I
    ):
        parts = match.group(2).split(",")
        if len(parts) < 3:
            continue
        try:
            found[match.group(1)] = (float(parts[0]), float(parts[1]), float(parts[2]))
        except ValueError:
            continue
    return found


def _vertex_bounds(data: str) -> tuple[tuple[float, float, float] | None, tuple[float, float, float] | None]:
    """VERTEX_POINT가 가리키는 점만의 경계.

    이 점들은 **형상 위에 있다**. 배치·축 좌표가 섞이지 않으므로 다면체에서는 실제 bbox와 같고,
    곡면이 있으면 실루엣이 버텍스 밖으로 나가므로 하한이 된다. 어느 쪽인지는 호출부가 표시한다.
    """
    points = _points_by_id(data)
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    seen = False
    for match in re.finditer(r"VERTEX_POINT\s*\(\s*\x00\d+\x00\s*,\s*#(\d+)", data, re.I):
        point = points.get(match.group(1))
        if point is None:
            continue
        seen = True
        for axis in range(3):
            lo[axis] = min(lo[axis], point[axis])
            hi[axis] = max(hi[axis], point[axis])
    if not seen:
        return None, None
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def _hull(data: str) -> tuple[tuple[float, float, float] | None, tuple[float, float, float] | None]:
    """CARTESIAN_POINT 좌표 전체의 최소·최대 — 언제나 상한이다."""
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    seen = False
    for match in re.finditer(
        r"CARTESIAN_POINT\s*\(\s*\x00\d+\x00\s*,\s*\(([^)]*)\)", data, re.I
    ):
        parts = match.group(1).split(",")
        if len(parts) < 3:
            continue
        try:
            values = [float(item.strip()) for item in parts[:3]]
        except ValueError:
            continue
        seen = True
        for axis in range(3):
            lo[axis] = min(lo[axis], values[axis])
            hi[axis] = max(hi[axis], values[axis])
    if not seen:
        return None, None
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])
