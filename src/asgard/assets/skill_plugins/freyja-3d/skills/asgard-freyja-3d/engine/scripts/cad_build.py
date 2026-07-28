#!/usr/bin/env python3
"""cad_build — 파라메트릭 CAD 스크립트를 실행하고, 내보내고, 커널 수준으로 진단한다.

사용:
    uv run --no-project --python 3.12 --with build123d python cad_build.py model.py --out build
    uv run --no-project --python 3.12 --with build123d --with lib3mf python cad_build.py model.py --formats step,stl,glb,3mf

모델 스크립트 규약(위에서부터 먼저 찾은 것을 쓴다):
    def gen_step(): ...                         # STEP 파이프라인 정본 — 반환값이 곧 형상이다
    PARTS = {"housing": housing, "lid": lid}   # 이름 있는 조립체 — 간섭·간극 검사를 받는다
    result / part / assembly = <Shape>          # 단일 부품
    (없으면) 모듈 전역에서 build123d Shape 를 수집한다

`gen_step()` 을 먼저 보는 이유: STEP 레인의 정본 진입점이 `vendor/text-to-cad/skills/cad/scripts/step`
이고 그 규약이 `gen_step()` 이다. 한 소스 파일이 두 파이프라인을 다 먹이게 해서, 조립체를 간섭
검사하려고 형상을 두 번 적는 일이 없게 한다. 라벨 붙은 Compound 를 반환하면 자식이 곧 부품 이름이
되어 그대로 쌍별 간섭 검사에 들어간다.

에이전트가 이 도구를 쓰는 이유는 하나다. 코드가 실행됐다는 사실과 형상이 맞다는 사실은 다르며,
후자는 커널이 측정한 숫자로만 확인된다. 이 스크립트가 STEP 레인에서 갖는 고유 몫은 **쌍별 간섭
부피와 최소 간극**이다 — cadpy 의 refs/measure/align 은 그 둘을 내지 않는다.
"""

from __future__ import annotations

import argparse
import json
import runpy
import sys
import traceback
from pathlib import Path

# 한국어 Windows(cp949)·서구권 Windows(cp1252) 콘솔은 이 파일의 엠대시·엔대시를 싣지 못하고,
# stdout 기본 오류 처리기가 strict 라 진단 보고를 다 만들어놓고 마지막 write 에서 죽는다
# (실측: `'cp949' codec can't encode character '—' in position 408`). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
    except Exception:
        pass

EXPORT_NAMES = ("PARTS", "parts", "result", "part", "assembly", "model", "shape")


def _load_build123d():
    try:
        import build123d as bd  # noqa: PLC0415
    except ImportError as error:  # pragma: no cover - 실행 환경 안내가 목적이다.
        sys.stderr.write(
            "build123d 를 찾지 못했다. 다음처럼 격리 실행하라:\n"
            "  uv run --no-project --python 3.12 --with build123d python cad_build.py <model.py>\n"
            f"원인: {error}\n"
        )
        raise SystemExit(3) from error
    return bd


def _is_shape(bd, value) -> bool:
    return isinstance(value, bd.Shape)


def _explode_compound(bd, name: str, shape) -> dict:
    """라벨 붙은 Compound 는 자식을 부품으로 편다 — 쌍별 간섭 검사의 단위가 부품이라서다.

    자식이 하나뿐이거나 라벨이 없으면 펴지 않는다. 이름 없는 조각 둘을 part_0/part_1 로
    불러봐야 간섭 보고를 읽을 수 없다.
    """
    children = [child for child in getattr(shape, "children", ()) or () if _is_shape(bd, child)]
    if len(children) < 2:
        return {name: shape}
    labels = [str(getattr(child, "label", "") or "") for child in children]
    if not all(labels) or len(set(labels)) != len(labels):
        return {name: shape}
    return dict(zip(labels, children, strict=True))


def collect_parts(bd, namespace: dict) -> dict:
    """모델 스크립트의 전역에서 내보낼 형상을 규약 순서대로 찾는다."""
    generator = namespace.get("gen_step")
    if callable(generator):
        produced = generator()
        if isinstance(produced, dict) and produced and all(_is_shape(bd, item) for item in produced.values()):
            return {str(key): item for key, item in produced.items()}
        if _is_shape(bd, produced):
            label = str(getattr(produced, "label", "") or "") or "part"
            return _explode_compound(bd, label, produced)

    for name in EXPORT_NAMES:
        value = namespace.get(name)
        if isinstance(value, dict) and value and all(_is_shape(bd, item) for item in value.values()):
            return {str(key): item for key, item in value.items()}
        if _is_shape(bd, value):
            return {name if name not in ("result", "part", "model", "shape") else "part": value}
    found = {
        key: value
        for key, value in namespace.items()
        if not key.startswith("_") and _is_shape(bd, value) and not isinstance(value, type)
    }
    return found


def _is_valid(shape) -> bool:
    """is_valid 는 build123d 버전에 따라 속성이거나 메서드다 — 둘 다 받는다."""
    attribute = getattr(shape, "is_valid", None)
    if callable(attribute):
        return bool(attribute())
    return bool(attribute)


def measure(bd, name: str, shape) -> dict:
    box = shape.bounding_box()
    entry = {
        "name": name,
        "valid": _is_valid(shape),
        "solids": len(shape.solids()),
        "faces": len(shape.faces()),
        "edges": len(shape.edges()),
        "bbox": {
            "min": [round(box.min.X, 4), round(box.min.Y, 4), round(box.min.Z, 4)],
            "max": [round(box.max.X, 4), round(box.max.Y, 4), round(box.max.Z, 4)],
            "size": [round(box.size.X, 4), round(box.size.Y, 4), round(box.size.Z, 4)],
        },
    }
    try:
        entry["volume"] = round(shape.volume, 4)
        entry["area"] = round(shape.area, 4)
    except Exception as error:  # noqa: BLE001 - 열린 셸이면 커널이 던진다.
        entry["volume"] = None
        entry["area"] = None
        entry["measureError"] = str(error)
    try:
        center = shape.center(bd.CenterOf.MASS)
        entry["centerOfMass"] = [round(center.X, 4), round(center.Y, 4), round(center.Z, 4)]
    except Exception:  # noqa: BLE001
        entry["centerOfMass"] = None
    return entry


def pair_checks(parts: dict, clearance_limit: float) -> list[dict]:
    """조립체의 간섭(부피가 겹침)과 간극(가장 가까운 거리)을 쌍마다 확인한다."""
    results = []
    names = list(parts)
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            entry = {"pair": [first, second]}
            try:
                overlap = parts[first].intersect(parts[second])
                volume = 0.0
                if overlap is not None:
                    shapes = overlap if isinstance(overlap, list) else [overlap]
                    for shape in shapes:
                        try:
                            volume += float(shape.volume)
                        except Exception:  # noqa: BLE001
                            continue
                entry["interferenceVolume"] = round(volume, 6)
            except Exception as error:  # noqa: BLE001
                entry["interferenceVolume"] = None
                entry["interferenceError"] = str(error)
            try:
                entry["clearance"] = round(float(parts[first].distance_to(parts[second])), 4)
            except Exception as error:  # noqa: BLE001
                entry["clearance"] = None
                entry["clearanceError"] = str(error)
            interference = entry.get("interferenceVolume")
            clearance = entry.get("clearance")
            if interference is None or clearance is None:
                # 측정 불능은 통과가 아니다 — 실행하지 못한 검사를 pass 로 적지 않는다.
                reasons = "; ".join(str(entry[key]) for key in ("interferenceError", "clearanceError") if key in entry)
                entry["level"] = "warn"
                entry["message"] = f"{first}–{second} 간섭·간극을 재지 못했다 — 커널 오류: {reasons}"
            elif interference > 1e-6:
                entry["level"] = "fail"
                entry["message"] = f"{first} 와 {second} 가 {entry['interferenceVolume']}mm³ 만큼 서로를 파고든다."
            elif clearance < clearance_limit:
                entry["level"] = "warn"
                entry["message"] = f"{first}–{second} 간극 {clearance}mm 가 목표 {clearance_limit}mm 미만이다."
            else:
                entry["level"] = "pass"
                entry["message"] = f"{first}–{second} 간섭 없음, 간극 {clearance}mm."
            results.append(entry)
    return results


def step_roundtrip(bd, parts: dict, step_path: str) -> dict:
    """내보낸 STEP 을 도로 읽어 커널 수준에서 대조한다 — 파일이 써졌다는 사실과 맞다는 사실은 다르다."""
    try:
        reimported = bd.import_step(step_path)
        solids = len(reimported.solids())
        volume = float(reimported.volume)
    except Exception as error:  # noqa: BLE001
        return {"id": "step-roundtrip", "level": "warn", "message": f"STEP 재임포트 실패 — 납품 전 대조 불가: {error}"}
    expected_solids = sum(len(shape.solids()) for shape in parts.values())
    expected_volume = 0.0
    for shape in parts.values():
        try:
            expected_volume += float(shape.volume)
        except Exception:  # noqa: BLE001
            continue
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


def export_all(bd, parts: dict, out_dir: Path, stem: str, formats: list[str], deflection: float, angular: float) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    assembly = list(parts.values())[0] if len(parts) == 1 else bd.Compound(children=list(parts.values()))
    if len(parts) > 1:
        for name, shape in parts.items():
            shape.label = name
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
        except Exception as error:  # noqa: BLE001
            written["3mf"] = None
            written["3mfError"] = (
                f"{error} (lib3mf 가 필요하다: uv run --no-project --with build123d --with lib3mf ...)"
            )
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="파라메트릭 CAD 스크립트 실행·내보내기·진단")
    parser.add_argument("script", help="build123d 모델 스크립트")
    parser.add_argument("--out", default="build", help="산출물 디렉터리 (기본 build)")
    parser.add_argument("--formats", default="step,stl,glb", help="쉼표 구분 (step,stl,glb,3mf)")
    parser.add_argument("--deflection", type=float, default=0.05, help="메시 선형 편차 mm (기본 0.05)")
    parser.add_argument(
        "--angular", type=float, default=0.3, help="메시 각도 편차 rad (기본 0.3 — 곡면 삼각형 수를 지배한다)"
    )
    parser.add_argument("--clearance", type=float, default=0.2, help="조립 간극 목표 mm (기본 0.2)")
    parser.add_argument("--json", action="store_true", help="JSON 만 출력")
    args = parser.parse_args()

    bd = _load_build123d()
    script = Path(args.script).resolve()
    if not script.is_file():
        sys.stderr.write(f"모델 스크립트가 없다: {script}\n")
        return 2

    sys.path.insert(0, str(script.parent))
    try:
        namespace = runpy.run_path(str(script), run_name="__cad_model__")
    except Exception:  # noqa: BLE001 - 실패한 스크립트의 트레이스백이 곧 수리 단서다.
        report = {"script": str(script), "status": "error", "traceback": traceback.format_exc()}
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return 1

    parts = collect_parts(bd, namespace)
    if not parts:
        sys.stderr.write(
            "내보낼 형상을 찾지 못했다. PARTS 딕셔너리나 result/part 전역을 남겨라.\n",
        )
        return 1

    stem = script.stem
    formats = [item.strip().lower() for item in args.formats.split(",") if item.strip()]
    measurements = [measure(bd, name, shape) for name, shape in parts.items()]
    written = export_all(bd, parts, Path(args.out), stem, formats, args.deflection, args.angular)
    pairs = pair_checks(parts, args.clearance) if len(parts) > 1 else []

    checks = []
    for entry in measurements:
        if not entry["valid"]:
            checks.append(
                {
                    "id": f"valid:{entry['name']}",
                    "level": "fail",
                    "message": f"{entry['name']} 형상이 커널 검증을 통과하지 못했다.",
                }
            )
        if entry.get("volume") in (None, 0):
            checks.append(
                {
                    "id": f"volume:{entry['name']}",
                    "level": "fail",
                    "message": f"{entry['name']} 의 부피를 측정할 수 없다 — 닫힌 솔리드가 아니다.",
                }
            )
        if entry["solids"] == 0:
            checks.append(
                {
                    "id": f"solid:{entry['name']}",
                    "level": "fail",
                    "message": f"{entry['name']} 에 솔리드가 없다 — 스케치나 서피스만 남았다.",
                }
            )
    checks.extend(
        {"id": f"fit:{'-'.join(pair['pair'])}", "level": pair["level"], "message": pair["message"]}
        for pair in pairs
        if pair["level"] != "pass"
    )

    roundtrip = None
    if isinstance(written.get("step"), str):
        roundtrip = step_roundtrip(bd, parts, written["step"])
        if roundtrip["level"] != "pass":
            checks.append(roundtrip)

    report = {
        "script": str(script),
        "status": "ok",
        "parts": measurements,
        "exports": written,
        "assembly": pairs,
        "stepRoundtrip": roundtrip,
        "checks": checks,
        "verdict": "fail" if any(check["level"] == "fail" for check in checks) else ("warn" if checks else "pass"),
    }

    if args.json:
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    else:
        lines = [f"스크립트 {script}"]
        for entry in measurements:
            lines.append(
                f"  {entry['name']:<16} 부피 {entry['volume']} mm³   치수 {' × '.join(str(value) for value in entry['bbox']['size'])}   "
                f"솔리드 {entry['solids']}  면 {entry['faces']}  유효 {entry['valid']}"
            )
        for pair in pairs:
            lines.append(f"  조립 {' ↔ '.join(pair['pair']):<24} {pair['message']}")
        for name, path in written.items():
            lines.append(f"  내보냄 {name:<6} {path}")
        if roundtrip:
            lines.append(f"  STEP 왕복 [{roundtrip['level'].upper()}] {roundtrip['message']}")
        lines.append(f"  판정 {report['verdict'].upper()}")
        lines.append("  이제 shoot.mjs 로 렌더해 형상을 눈으로 확인하고, mesh_audit.mjs 로 공정 규칙을 확인하라.")
        sys.stdout.write("\n".join(lines) + "\n")

    diagnostics = Path(args.out) / "diagnostics.json"
    diagnostics.parent.mkdir(parents=True, exist_ok=True)
    diagnostics.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if report["verdict"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
