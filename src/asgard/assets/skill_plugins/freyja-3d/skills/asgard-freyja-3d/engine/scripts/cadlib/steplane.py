"""step — 소스에서 STEP을 내고, 위상 산출물을 붙이고, 커널 수준으로 진단한다.

## 왜 한 도구인가

이전 판에는 STEP을 내는 도구와 조립 진단을 내는 도구가 따로 있었다. 둘은 서로 다른 STEP을
만들었고, 그중 하나에만 위상 산출물이 붙었다. 그래서 문서에 이런 경고가 실려 있었다 —
*"진단 도구가 낸 STEP 에는 위상 산출물이 없으니 그 STEP에 셀렉터 측정을 했다고 말하지 말라."*

경고로 막는 함정은 언젠가 빠진다. 여기서는 함정을 없앤다. **한 도구가 한 STEP을 내고, 그
STEP에 위상 산출물과 간섭 진단이 함께 붙는다.** 고를 것이 없으면 잘못 고를 수도 없다.

## 산출물

    build/bracket.step        납품물
    build/.bracket.step.glb   위상 산출물 — 셀렉터 표 + 렌더 메시 (숨김, 납품 아님)
    build/bracket.stl / .glb  요청했을 때만
    build/diagnostics.json이 실행의 전체 보고
"""

from __future__ import annotations

import json
from pathlib import Path

from . import kernel, stepfile, topology
from .report import Report


def run(
    script: str | Path,
    *,
    out: str | Path,
    formats: list[str],
    deflection: float,
    angular: float,
    clearance: float,
    detail: bool = True,
) -> Report:
    script = Path(script).resolve()
    report = Report(tool="step", target=str(script))
    if not script.is_file():
        report.fail("source-missing", f"모델 소스가 없다: {script}")
        return report

    bd = kernel.load()
    namespace = kernel.run_source(script)
    parts = kernel.collect_parts(bd, namespace)
    if not parts:
        report.fail(
            "no-shape",
            "내보낼 형상을 찾지 못했다. `gen_step()`을 정의하거나 PARTS 딕셔너리를 남겨라.",
        )
        return report

    report.facts["부품"] = ", ".join(parts)

    # ── 측정 ──────────────────────────────────────────────────────────────────
    measurements = [kernel.measure_shape(bd, name, shape) for name, shape in parts.items()]
    for entry in measurements:
        size = (entry.get("bbox") or {}).get("size")
        report.facts[entry["name"]] = (
            f"부피 {entry['volume']} mm³   치수 {' × '.join(f'{value:g}' for value in size) if size else '—'}   "
            f"솔리드 {entry['solids']}  면 {entry['faces']}"
        )
        if not entry["valid"]:
            report.fail(f"valid:{entry['name']}", f"{entry['name']} 형상이 커널 검증을 통과하지 못했다.")
        if entry["solids"] == 0:
            report.fail(f"solid:{entry['name']}", f"{entry['name']}에 솔리드가 없다 — 스케치나 서피스만 남았다.")
        if entry["volume"] in (None, 0):
            report.fail(f"volume:{entry['name']}", f"{entry['name']}의 부피를 측정할 수 없다 — 닫힌 솔리드가 아니다.")

    # ── 내보내기 ──────────────────────────────────────────────────────────────
    out_dir = Path(out)
    stem = script.stem
    if "step" not in formats:
        formats = ["step", *formats]  # STEP은 이 레인의 정본이다 — 뺄 수 없다
    written = kernel.export(bd, parts, out_dir, stem, formats, deflection, angular)
    for name, path in written.items():
        report.facts[f"내보냄 {name}"] = path
    if isinstance(written.get("3mfError"), str):
        report.unverified("export-3mf", str(written["3mfError"]))

    step_path = written.get("step")
    if not isinstance(step_path, str):
        report.fail("export-step", "STEP을 쓰지 못했다.")
        return report

    # ── 위상 산출물 ───────────────────────────────────────────────────────────
    digest = stepfile.sha256_file(step_path)
    index = kernel.build_index(bd, parts, step_hash=digest, version=_version(), detail=detail)
    mesh = kernel.tessellate(bd, kernel.assemble(bd, parts), deflection, angular)
    artifact = topology.write(
        step_path,
        index,
        positions=mesh[0] if mesh else None,
        indices=mesh[1] if mesh else None,
    )
    report.facts["위상 산출물"] = str(artifact)
    report.facts["셀렉터"] = (
        f"면 {len(index['faces'])} · 에지 {len(index['edges'])} · 버텍스 {len(index['vertices'])}"
    )
    if mesh is None:
        report.unverified(
            "tessellate",
            "삼각분할에 실패했다 — 셀렉터 측정은 되지만 스냅샷·뷰어가 그림을 내지 못한다.",
        )
    else:
        report.ok("topology", f"위상 산출물을 붙였다 (삼각형 {len(mesh[1]) // 3}개).")

    # ── 조립 진단 ─────────────────────────────────────────────────────────────
    if len(parts) > 1:
        for pair in kernel.pair_checks(parts, clearance):
            report.add(f"fit:{'-'.join(pair['pair'])}", pair["level"], pair["message"])

    # ── STEP 왕복 ─────────────────────────────────────────────────────────────
    roundtrip = kernel.step_roundtrip(bd, parts, step_path)
    report.add(roundtrip["id"], roundtrip["level"], roundtrip["message"])

    # ── 무커널 판독으로 자기 산출물 대조 ──────────────────────────────────────
    static = stepfile.read(step_path)
    if static.length_scale_mm != 1.0:
        report.fail(
            "step-units",
            f"내보낸 STEP의 길이 단위가 mm가 아니다({static.length_unit or '미상'}) — 하류가 치수를 잘못 읽는다.",
        )
    if static.solids != sum(entry["solids"] for entry in measurements):
        report.fail(
            "step-census",
            f"STEP 표면의 솔리드 수({static.solids})가 커널 측정({sum(entry['solids'] for entry in measurements)})과 다르다.",
        )

    diagnostics = out_dir / "diagnostics.json"
    diagnostics.parent.mkdir(parents=True, exist_ok=True)
    payload = report.as_dict() | {"parts": measurements, "exports": written}
    diagnostics.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report.facts["진단"] = str(diagnostics)
    return report


def _version() -> str:
    from . import VERSION  # noqa: PLC0415

    return VERSION
