"""B-Rep 커널 어댑터 — 형상을 만들고, 재고, 셀렉터 표를 뽑는다.

## 커널을 대하는 원칙

이 모듈은 커널(build123d 위의 OpenCASCADE)을 **필요할 때만** 부른다. 나머지 모듈은 커널 없이
돈다. 그래서 여기서 지키는 규율이 둘이다:

1. **커널 부재는 정직한 종료다.** import 실패를 예외 문자열로 흘리지 않고, 무엇을 어떻게 깔면
   되는지 한 줄로 말하고 종료코드 3 으로 죽는다. 3 은 "환경이 없다"를 뜻하고 1(검증 실패)과
   다르다 — 이 둘을 섞으면 CI 가 설치 문제를 품질 문제로 읽는다.
2. **커널이 못 잰 것을 우리가 추정하지 않는다.** 부피가 안 나오면 None 이고, 그 None 은 하류에서
   `warn`(미확인)이 된다. 0 으로 채우거나 근사치를 넣지 않는다.

## 소스 규약

한 소스 파일이 STEP 파이프라인과 진단 파이프라인을 다 먹인다. 위에서부터 먼저 찾은 것을 쓴다:

    def gen_step(): ...                        # 정본 진입점 — 반환값이 곧 형상
    PARTS = {"housing": housing, "lid": lid}   # 이름 있는 조립체
    result / part / assembly = <Shape>         # 단일 부품
    (없으면) 모듈 전역에서 Shape 를 수집한다

라벨 붙은 `Compound` 를 반환하면 자식이 곧 부품 이름이 되어 그대로 쌍별 간섭 검사에 들어간다.
"""

from __future__ import annotations

import runpy
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any

EXPORT_NAMES = ("PARTS", "parts", "result", "part", "assembly", "model", "shape")

INSTALL_HINT = (
    "build123d 를 찾지 못했다. CAD 커널 레인은 격리 실행을 전제로 한다:\n"
    "  python engine/scripts/cad.py step <model.py>\n"
    "런처가 uv 로 python 3.12 + build123d 를 매번 격리해 부른다(저장소 환경을 건드리지 않는다).\n"
    "첫 실행은 커널 휠을 받느라 오래 걸린다."
)


class KernelMissing(RuntimeError):
    """커널이 없다. 검증 실패가 아니라 환경 부재다 — 종료코드를 다르게 쓰려고 따로 둔다."""


def load() -> Any:
    try:
        import build123d as bd  # noqa: PLC0415
    except ImportError as error:
        raise KernelMissing(f"{INSTALL_HINT}\n원인: {error}") from error
    return bd


def is_shape(bd: Any, value: object) -> bool:
    return isinstance(value, bd.Shape)


def _explode_compound(bd: Any, name: str, shape: Any) -> dict[str, Any]:
    """라벨 붙은 Compound 는 자식을 부품으로 편다 — 쌍별 검사의 단위가 부품이라서다.

    자식이 하나뿐이거나 라벨이 없으면 펴지 않는다. 이름 없는 조각 둘을 part_0/part_1 로
    불러봐야 간섭 보고를 읽을 수 없다.
    """
    children = [child for child in getattr(shape, "children", ()) or () if is_shape(bd, child)]
    if len(children) < 2:
        return {name: shape}
    labels = [str(getattr(child, "label", "") or "") for child in children]
    if not all(labels) or len(set(labels)) != len(labels):
        return {name: shape}
    return dict(zip(labels, children, strict=True))


def collect_parts(bd: Any, namespace: dict) -> dict[str, Any]:
    """소스의 전역에서 내보낼 형상을 규약 순서대로 찾는다."""
    generator = namespace.get("gen_step")
    if callable(generator):
        produced = generator()
        if isinstance(produced, dict) and produced and all(is_shape(bd, item) for item in produced.values()):
            return {str(key): item for key, item in produced.items()}
        if is_shape(bd, produced):
            label = str(getattr(produced, "label", "") or "") or "part"
            return _explode_compound(bd, label, produced)

    for name in EXPORT_NAMES:
        value = namespace.get(name)
        if isinstance(value, dict) and value and all(is_shape(bd, item) for item in value.values()):
            return {str(key): item for key, item in value.items()}
        if is_shape(bd, value):
            return {name if name not in ("result", "part", "model", "shape") else "part": value}
    return {
        key: value
        for key, value in namespace.items()
        if not key.startswith("_") and is_shape(bd, value) and not isinstance(value, type)
    }


def run_source(script: str | Path) -> dict:
    """모델 소스를 실행해 전역을 돌려준다. 실패하면 예외가 그대로 올라간다 — 트레이스백이 단서다."""
    script = Path(script).resolve()
    sys.path.insert(0, str(script.parent))
    return runpy.run_path(str(script), run_name="__cad_model__")


# ─────────────────────────────────────────────────────────────────────────────
# 측정
# ─────────────────────────────────────────────────────────────────────────────


def _valid(shape: Any) -> bool:
    """is_valid 는 build123d 버전에 따라 속성이거나 메서드다 — 둘 다 받는다."""
    attribute = getattr(shape, "is_valid", None)
    return bool(attribute()) if callable(attribute) else bool(attribute)


def _try(callable_: Any, digits: int = 6) -> float | None:
    try:
        value = float(callable_())
    except Exception:
        return None
    return round(value, digits) if value == value else None  # NaN 배제


def _point(vector: Any, digits: int = 6) -> list[float] | None:
    try:
        return [round(float(vector.X), digits), round(float(vector.Y), digits), round(float(vector.Z), digits)]
    except Exception:
        return None


def _bbox(shape: Any, digits: int = 6) -> dict | None:
    try:
        box = shape.bounding_box()
    except Exception:
        return None
    lo, hi = _point(box.min, digits), _point(box.max, digits)
    if lo is None or hi is None:
        return None
    return {"min": lo, "max": hi, "size": [round(hi[i] - lo[i], digits) for i in range(3)]}


def _geom_type(entity: Any) -> str:
    value = getattr(entity, "geom_type", None)
    if value is None:
        return ""
    name = getattr(value, "name", None)
    return str(name or value)


def measure_shape(bd: Any, name: str, shape: Any) -> dict:
    """부품 하나의 커널 측정치. 못 잰 항목은 None 으로 남고 하류에서 미확인이 된다."""
    entry: dict = {
        "name": name,
        "valid": _valid(shape),
        "solids": len(shape.solids()),
        "faces": len(shape.faces()),
        "edges": len(shape.edges()),
        "vertices": len(shape.vertices()),
        "bbox": _bbox(shape),
        "volume": _try(lambda: shape.volume),
        "area": _try(lambda: shape.area),
    }
    entry["centerOfMass"] = _point(shape.center(bd.CenterOf.MASS)) if entry["volume"] else None
    return entry


def pair_checks(parts: dict[str, Any], clearance_limit: float) -> list[dict]:
    """조립체의 간섭(부피가 겹침)과 간극(가장 가까운 거리)을 쌍마다 확인한다.

    이 둘은 셀렉터 측정(refs·measure·align)이 **내지 않는 숫자**다. 조립체 판정의 실질은 여기 있다.
    """
    results: list[dict] = []
    names = list(parts)
    for position, first in enumerate(names):
        for second in names[position + 1 :]:
            entry: dict = {"pair": [first, second]}
            try:
                overlap = parts[first].intersect(parts[second])
                volume = 0.0
                if overlap is not None:
                    for piece in overlap if isinstance(overlap, list) else [overlap]:
                        try:
                            volume += float(piece.volume)
                        except Exception:
                            continue
                entry["interferenceVolume"] = round(volume, 6)
            except Exception as error:
                entry["interferenceVolume"] = None
                entry["interferenceError"] = str(error)
            entry["clearance"] = _try(lambda: parts[first].distance_to(parts[second]), 4)
            if entry["clearance"] is None:
                entry["clearanceError"] = "거리 계산이 커널에서 실패했다"

            interference, clearance = entry.get("interferenceVolume"), entry.get("clearance")
            if interference is None or clearance is None:
                reasons = "; ".join(str(entry[key]) for key in ("interferenceError", "clearanceError") if key in entry)
                entry["level"] = "warn"
                entry["message"] = f"{first}–{second} 간섭·간극을 재지 못했다 — 커널 오류: {reasons}"
            elif interference > 1e-6:
                entry["level"] = "fail"
                entry["message"] = f"{first} 와 {second} 가 {interference}mm³ 만큼 서로를 파고든다."
            elif clearance < clearance_limit:
                entry["level"] = "warn"
                entry["message"] = f"{first}–{second} 간극 {clearance}mm 가 목표 {clearance_limit}mm 미만이다."
            else:
                entry["level"] = "pass"
                entry["message"] = f"{first}–{second} 간섭 없음, 간극 {clearance}mm."
            results.append(entry)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 셀렉터 표
# ─────────────────────────────────────────────────────────────────────────────


def build_index(bd: Any, parts: dict[str, Any], *, step_hash: str, version: str, detail: bool = True) -> dict:
    """위상 산출물에 실을 셀렉터 표를 만든다.

    서수는 여기서 정해진다: 어커런스는 부품 순서, 면·에지·버텍스는 커널이 훑은 순서. 그 순서가
    이 파일에 박히는 순간 안정된 이름이 되고, 다음에 STEP 을 다시 뽑으면 이 파일도 같이 갱신되어
    새 순서를 얻는다. **이 파일을 안 갱신하고 STEP 만 갱신하는 것**이 이 레인의 조용한 오답이라
    `stepHash` 가 같이 들어간다.
    """
    occurrences: list[dict] = []
    shapes: list[dict] = []
    faces: list[dict] = []
    edges: list[dict] = []
    vertices: list[dict] = []

    for order, (name, shape) in enumerate(parts.items(), start=1):
        occurrence_id = f"o{order}"
        shape_id = f"s{order}"
        occurrences.append({"id": occurrence_id, "label": name, "shapes": [shape_id]})
        shapes.append(
            {
                "id": shape_id,
                "occurrence": occurrence_id,
                "label": name,
                "volume": _try(lambda: shape.volume),
                "area": _try(lambda: shape.area),
                "bbox": _bbox(shape),
                "solids": len(shape.solids()),
            }
        )
        if not detail:
            continue
        for face_order, face in enumerate(shape.faces(), start=1):
            entry = {
                "id": f"f{face_order}" if len(parts) == 1 else f"{occurrence_id}.f{face_order}",
                "ordinal": face_order,
                "shape": shape_id,
                "occurrence": occurrence_id,
                "type": _geom_type(face),
                "area": _try(lambda: face.area),
                "center": _point(face.center()),
                "bbox": _bbox(face),
            }
            try:
                entry["normal"] = _point(face.normal_at(face.center()))
            except Exception:
                entry["normal"] = None
            faces.append(entry)
        for edge_order, edge in enumerate(shape.edges(), start=1):
            edges.append(
                {
                    "id": f"e{edge_order}" if len(parts) == 1 else f"{occurrence_id}.e{edge_order}",
                    "ordinal": edge_order,
                    "shape": shape_id,
                    "occurrence": occurrence_id,
                    "type": _geom_type(edge),
                    "length": _try(lambda: edge.length),
                    "center": _point(edge.center()),
                }
            )
        for vertex_order, vertex in enumerate(shape.vertices(), start=1):
            vertices.append(
                {
                    "id": f"v{vertex_order}" if len(parts) == 1 else f"{occurrence_id}.v{vertex_order}",
                    "ordinal": vertex_order,
                    "shape": shape_id,
                    "occurrence": occurrence_id,
                    "point": _point(vertex.center()),
                }
            )

    return {
        "version": version,
        "stepHash": step_hash,
        "unit": "millimetre",
        "scaleMm": 1.0,
        "name": next(iter(parts), "part"),
        "occurrences": occurrences,
        "shapes": shapes,
        "faces": faces,
        "edges": edges,
        "vertices": vertices,
        "detail": detail,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 삼각분할과 내보내기
# ─────────────────────────────────────────────────────────────────────────────


def tessellate(bd: Any, shape: Any, deflection: float, angular: float) -> tuple[list[float], list[int]] | None:
    """렌더용 삼각망. 커널 API 를 먼저 쓰고, 없으면 STL 을 거쳐 간다.

    build123d 는 판올림에서 `tessellate` 의 시그니처를 바꾼 적이 있다. 한 경로만 믿으면 판올림
    때 조용히 그림이 사라지므로 STL 경유를 폴백으로 둔다 — 느리지만 항상 된다.
    """
    for attempt in (
        lambda: shape.tessellate(deflection, angular),
        lambda: shape.tessellate(deflection),
    ):
        try:
            raw_vertices, triangles = attempt()
        except Exception:
            continue
        positions: list[float] = []
        for vertex in raw_vertices:
            point = _point(vertex)
            if point is None:
                positions = []
                break
            positions.extend(point)
        if not positions:
            continue
        indices = [int(value) for triangle in triangles for value in triangle]
        if indices and max(indices) < len(positions) // 3:
            return positions, indices

    with tempfile.TemporaryDirectory() as temp:
        stl = Path(temp) / "tess.stl"
        try:
            bd.export_stl(shape, str(stl), tolerance=deflection, angular_tolerance=angular)
        except Exception:
            return None
        return _read_binary_stl(stl)


def _read_binary_stl(path: Path) -> tuple[list[float], list[int]] | None:
    """바이너리 STL 을 읽어 정점 중복을 접는다. glTF 는 인덱스 메시를 원한다."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) < 84:
        return None
    count = struct.unpack_from("<I", raw, 80)[0]
    if 84 + count * 50 > len(raw):
        return None
    positions: list[float] = []
    indices: list[int] = []
    lookup: dict[tuple[int, int, int], int] = {}
    offset = 84
    for _ in range(count):
        values = struct.unpack_from("<12f", raw, offset)
        for corner in range(3):
            point = values[3 + corner * 3 : 6 + corner * 3]
            # 부동소수 그대로는 같은 정점이 안 접힌다. 1e-6 mm 격자로 반올림해 키를 만든다.
            key = tuple(int(round(value * 1e6)) for value in point)
            found = lookup.get(key)  # type: ignore[arg-type]
            if found is None:
                found = len(positions) // 3
                lookup[key] = found  # type: ignore[index]
                positions.extend(float(value) for value in point)
            indices.append(found)
        offset += 50
    return (positions, indices) if indices else None


def assemble(bd: Any, parts: dict[str, Any]) -> Any:
    """부품 묶음을 하나의 내보내기 대상으로 만든다. 라벨은 유지된다 — 위상 추적이 거기 붙는다."""
    if len(parts) == 1:
        return next(iter(parts.values()))
    for name, shape in parts.items():
        shape.label = name
    return bd.Compound(children=list(parts.values()))


def export(
    bd: Any,
    parts: dict[str, Any],
    out_dir: Path,
    stem: str,
    formats: list[str],
    deflection: float,
    angular: float,
) -> dict:
    """요청한 형식으로 내보낸다. 실패한 형식은 None + 오류 문자열로 남는다(조용히 빠지지 않는다)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    assembly = assemble(bd, parts)
    written: dict[str, object] = {}

    if "step" in formats:
        path = out_dir / f"{stem}.step"
        bd.export_step(assembly, str(path))
        written["step"] = str(path)
    if "stl" in formats:
        path = out_dir / f"{stem}.stl"
        bd.export_stl(assembly, str(path), tolerance=deflection, angular_tolerance=angular)
        written["stl"] = str(path)
    if "glb" in formats:
        path = out_dir / f"{stem}.glb"
        bd.export_gltf(assembly, str(path), binary=True, linear_deflection=deflection, angular_deflection=angular)
        written["glb"] = str(path)
    if "3mf" in formats:
        try:
            mesher = bd.Mesher()
            for name, shape in parts.items():
                mesher.add_shape(shape, part_number=name)
            path = out_dir / f"{stem}.3mf"
            mesher.write(str(path))
            written["3mf"] = str(path)
        except Exception as error:
            written["3mf"] = None
            written["3mfError"] = f"{error} (lib3mf 가 필요하다 — 런처에 --with lib3mf 를 더하라)"
    return written


def step_roundtrip(bd: Any, parts: dict[str, Any], step_path: str) -> dict:
    """내보낸 STEP 을 도로 읽어 커널 수준으로 대조한다.

    파일이 써졌다는 사실과 그 파일이 맞다는 사실은 다르다. 내보내기가 조용히 형상을 잃는 사고
    (열린 셸, 라벨 소실, 단위 뒤바뀜)가 여기서만 잡힌다.
    """
    try:
        reimported = bd.import_step(step_path)
        solids = len(reimported.solids())
        volume = float(reimported.volume)
    except Exception as error:
        return {"id": "step-roundtrip", "level": "warn", "message": f"STEP 재임포트 실패 — 납품 전 대조 불가: {error}"}

    expected_solids = sum(len(shape.solids()) for shape in parts.values())
    expected_volume = 0.0
    for shape in parts.values():
        measured = _try(lambda: shape.volume)
        if measured:
            expected_volume += measured

    if solids != expected_solids:
        return {
            "id": "step-roundtrip",
            "level": "fail",
            "message": f"STEP 왕복에서 솔리드 수가 다르다 — 원본 {expected_solids}개, 재임포트 {solids}개.",
        }
    if expected_volume > 0:
        drift = abs(volume - expected_volume) / expected_volume
        if drift > 0.005:
            return {
                "id": "step-roundtrip",
                "level": "fail",
                "message": (
                    f"STEP 왕복 부피가 어긋난다 — 원본 {round(expected_volume, 3)}mm³, "
                    f"재임포트 {round(volume, 3)}mm³ (차 {round(drift * 100, 2)}%)."
                ),
            }
        return {
            "id": "step-roundtrip",
            "level": "pass",
            "message": f"STEP 왕복 일치 — 솔리드 {solids}개, 부피 차 {round(drift * 100, 4)}%.",
        }
    return {"id": "step-roundtrip", "level": "pass", "message": f"STEP 왕복 일치 — 솔리드 {solids}개."}
