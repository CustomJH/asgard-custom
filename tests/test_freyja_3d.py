"""Freyja 3D 엔진(브리싱아멘) — 계약과 검증 런타임.

이 엔진의 값어치는 "형상을 측정해서 판정한다"에 있으므로, 테스트도 문서 문자열이 아니라
실제 지오메트리에 스크립트를 돌려 판정이 맞는지 본다. 특히 두 가지를 고정한다.
① 빌드 플레이트에 붙은 평평한 바닥면을 오버행으로 세지 않는다(상류 도구에서 발견된 오탐).
② 잘 쓴 실시간 3D 코드에서 정적 검출기가 거짓 경보를 내지 않는다.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from asgard import skill_registry

_NODE = shutil.which("node")
_PLUGIN = Path(skill_registry.__file__).parent / "assets" / "skill_plugins" / "freyja-3d"
_SKILL = _PLUGIN / "skills" / "asgard-freyja-3d"
_SCRIPTS = _SKILL / "engine" / "scripts"


def _node(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [str(_NODE), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _write_box_stl(path: Path, size: tuple[float, float, float], origin=(0.0, 0.0, 0.0)) -> None:
    """감김이 일관된 닫힌 육면체 STL — 판정 기준을 아는 픽스처."""
    _write_boxes_stl(path, [(size, origin)])


def _write_boxes_stl(path: Path, boxes: list[tuple[tuple[float, float, float], tuple[float, float, float]]]) -> None:
    triangles = []
    for size, origin in boxes:
        x0, y0, z0 = origin
        x1, y1, z1 = (origin[axis] + size[axis] for axis in range(3))
        quads = [
            ((x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)),
            ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)),
            ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)),
            ((x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)),
            ((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)),
            ((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)),
        ]
        for a, b, c, d in quads:
            triangles.append((a, b, c))
            triangles.append((a, c, d))
    payload = bytearray(b"asgard freyja 3d fixture".ljust(80, b"\0"))
    payload += struct.pack("<I", len(triangles))
    for a, b, c in triangles:
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        normal = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        length = math.hypot(*normal) or 1.0
        payload += struct.pack("<3f", *(value / length for value in normal))
        for point in (a, b, c):
            payload += struct.pack("<3f", *point)
        payload += struct.pack("<H", 0)
    path.write_bytes(bytes(payload))


class FreyjaThreeDContract(unittest.TestCase):
    def test_plugin_is_bundled_and_routed_to_freyja(self):
        plugin = skill_registry.bundled_plugins()["freyja-3d"]
        self.assertEqual(plugin["skills"], ["asgard-freyja-3d"])
        routing = plugin["routing"]["asgard-freyja-3d"]
        self.assertEqual(routing["defaults"], ["freyja"])
        self.assertEqual(routing["agents"], ["freyja"])
        for trigger in ("3d", "cad", "three.js", "webgpu", "stl", "브리싱가멘"):
            self.assertIn(trigger, routing["triggers"])

    def test_skill_is_reachable_only_through_freyja(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIn("asgard-freyja-3d", [name for name, _ in skill_registry.client_skill_bodies("freyja", root)])
            self.assertNotIn(
                "asgard-freyja-3d", {name for name, _ in skill_registry.client_skill_bodies("worker", root)}
            )
            resolved = {name for name, _ in skill_registry.resolve_skills(root, "STL 3D 모델 만들어줘", "freyja")}
            self.assertIn("asgard-freyja-3d", resolved)
            resolved = {name for name, _ in skill_registry.resolve_skills(root, "브리싱가멘으로 해줘", "freyja")}
            self.assertIn("asgard-freyja-3d", resolved)

    def test_delivery_gates_and_vault_are_declared(self):
        body = (_SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(".asgard/.vanadis/3d/", body)
        self.assertIn("배달 게이트", body)
        for phrase in ("형상이 맞는가", "만들 수 있는가", "움직임이 살아 있는가"):
            self.assertIn(phrase, body)
        # 금고는 자체 ignore 를 만들지 않는다 — 엔진 1·2 와 같은 규약.
        self.assertIn("별도 ignore 항목을 만들지 않고", body)

    def test_every_referenced_document_exists(self):
        body = (_SKILL / "SKILL.md").read_text(encoding="utf-8")
        reference = _SKILL / "engine" / "reference"
        for name in (
            "clarify",
            "lane-cad",
            "lane-realtime",
            "lane-motion",
            "lane-asset",
            "lane-art",
            "verify",
            "dfm",
            "budgets",
            "escalation",
            "research",
            "specimens",
            "electrical-enclosures",
        ):
            self.assertIn(f"{name}.md", body, f"SKILL.md 가 {name}.md 로 라우팅하지 않는다")
            self.assertTrue((reference / f"{name}.md").is_file(), f"{name}.md 문서가 없다")
        for script in (
            "preflight.mjs",
            "shoot.mjs",
            "mesh_audit.mjs",
            "scene_audit.mjs",
            "detect3d.mjs",
            "cad_build.py",
        ):
            self.assertIn(script, body)
            self.assertTrue((_SCRIPTS / script).is_file(), f"{script} 스크립트가 없다")

    def test_cad_command_is_project_isolated(self):
        """uv run 은 --no-project 필수 — 상위 프로젝트의 requires-python 에 붙잡히면 CAD 레인이 죽는다."""
        for name in ("SKILL.md", "engine/reference/lane-cad.md", "engine/scripts/preflight.mjs"):
            body = (_SKILL / name).read_text(encoding="utf-8")
            for line in body.splitlines():
                if "uv run" in line:
                    self.assertIn("--no-project", line, f"{name} 의 uv run 에 --no-project 가 없다: {line.strip()}")

    def test_process_rules_are_machine_readable(self):
        data = json.loads((_SKILL / "engine" / "data" / "processes.json").read_text(encoding="utf-8"))
        self.assertEqual(data["units"], "mm")
        for process in ("fdm", "sla", "sls", "cnc", "sheet", "injection"):
            self.assertIn(process, data["processes"])
        self.assertEqual(data["processes"]["fdm"]["overhangDeg"], 45)
        # 분말 공정은 서포트 제약이 없다 — null 이어야 오버행 검사가 통과로 빠진다.
        self.assertIsNone(data["processes"]["sls"]["overhangDeg"])

    def test_look_floor_and_critique_are_wired(self):
        """엔진 2 반슬롭 장치의 이식이 배선까지 됐는지 — 문서가 존재하고 SKILL 이 이름으로 가리킨다."""
        body = (_SKILL / "SKILL.md").read_text(encoding="utf-8")
        for anchor in ("look-floor.md", "lookdev.md", "critique3d.md", "critique_store.mjs", "초보 티가 없는가"):
            self.assertIn(anchor, body)
        look = (_SKILL / "engine" / "reference" / "look-floor.md").read_text(encoding="utf-8")
        for phrase in ("거부 목록", "렌더에서 판정한다"):
            self.assertIn(phrase, look)
        critique = (_SKILL / "engine" / "reference" / "critique3d.md").read_text(encoding="utf-8")
        self.assertIn("critique_store.mjs", critique)
        self.assertIn("강등", critique)  # 조용한 강등 금지 — 엔진 2 와 같은 배너 계약
        self.assertTrue((_SKILL / "engine" / "reference" / "lookdev.md").is_file())

    @staticmethod
    def _linear_luminance(rgb: list[float]) -> float:
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

    def test_material_presets_stay_inside_pbr_calibration(self):
        """재질 라이브러리 전 프리셋이 lane-art 보정 범위 안 — 비금속 알베도 30–240 sRGB, 순금속 반사율 70%+."""
        data = json.loads((_SKILL / "engine" / "data" / "materials.json").read_text(encoding="utf-8"))
        presets = data["presets"]
        self.assertGreaterEqual(len(presets), 20)
        for name in ("steel", "gold", "bronze", "leather", "plastic", "resin", "slate", "ivory"):
            self.assertIn(name, presets, "기존 프리셋 하위 호환이 깨졌다")
        dielectric_floor = ((30 / 255 + 0.055) / 1.055) ** 2.4
        dielectric_ceiling = ((240 / 255 + 0.055) / 1.055) ** 2.4
        metal_floor = ((180 / 255 + 0.055) / 1.055) ** 2.4
        for name, preset in presets.items():
            self.assertEqual(len(preset["baseColor"]), 4, name)
            self.assertTrue(all(0.0 <= value <= 1.0 for value in preset["baseColor"]), name)
            self.assertTrue(0.0 <= preset["metallic"] <= 1.0, name)
            self.assertTrue(0.05 <= preset["roughness"] <= 1.0, name)
            luminance = self._linear_luminance(preset["baseColor"])
            if preset["metallic"] >= 0.95:
                self.assertGreaterEqual(luminance, metal_floor, f"{name}: 금속 반사율이 70% 미만")
            elif preset["metallic"] <= 0.5:
                self.assertGreaterEqual(luminance, dielectric_floor, f"{name}: 알베도가 30 sRGB 아래")
                self.assertLessEqual(luminance, dielectric_ceiling, f"{name}: 알베도가 240 sRGB 위")

    def test_reference_specimen_has_source_provenance_and_real_outputs(self):
        specimen = _SKILL / "assets" / "inspection-prop"
        for relative in (
            "inspection-prop.py",
            "ASSETS.md",
            "build/inspection-prop.step",
            "build/inspection-prop.stl",
            "build/inspection-prop.glb",
            "evidence/inspection-prop-sheet.png",
            "build/diagnostics.json",
            "evidence/mesh-audit.json",
            "evidence/scene-audit.json",
            "evidence/gltf-validator.json",
        ):
            path = specimen / relative
            self.assertTrue(path.is_file(), f"기준 자산 누락: {relative}")
            self.assertGreater(path.stat().st_size, 0, f"빈 기준 자산: {relative}")
        diagnostics = json.loads((specimen / "build" / "diagnostics.json").read_text(encoding="utf-8"))
        self.assertEqual(diagnostics["verdict"], "pass")
        self.assertEqual(diagnostics["parts"][0]["bbox"]["size"], [60.0, 36.0, 52.0])
        validator = json.loads((specimen / "evidence" / "gltf-validator.json").read_text(encoding="utf-8"))
        self.assertEqual(validator["errors"], 0)
        self.assertTrue((specimen / "evidence" / "inspection-prop-sheet.png").read_bytes().startswith(b"\x89PNG"))

    def test_field_telemetry_specimen_has_two_verified_parts(self):
        specimen = _SKILL / "assets" / "field-telemetry-kit"
        for relative in (
            "field-telemetry-kit.py",
            "ASSETS.md",
            "build/field-telemetry-kit.step",
            "build/field-telemetry-kit.stl",
            "build/field-telemetry-kit.glb",
            "build/field-telemetry-kit-preview.glb",
            "evidence/field-telemetry-kit-sheet.png",
            "build/diagnostics.json",
            "evidence/mesh-audit-meter.json",
            "evidence/mesh-audit-gateway.json",
            "evidence/mesh-polish.json",
            "evidence/scene-audit.json",
            "evidence/gltf-validator.json",
        ):
            path = specimen / relative
            self.assertTrue(path.is_file(), f"전기·통신 기준 자산 누락: {relative}")
            self.assertGreater(path.stat().st_size, 0, f"빈 전기·통신 기준 자산: {relative}")
        diagnostics = json.loads((specimen / "build" / "diagnostics.json").read_text(encoding="utf-8"))
        self.assertEqual(diagnostics["verdict"], "pass")
        self.assertEqual([part["name"] for part in diagnostics["parts"]], ["energy_meter", "rs485_lte_gateway"])
        self.assertEqual(diagnostics["parts"][0]["bbox"]["size"], [90.0, 69.0, 95.0])
        self.assertEqual(diagnostics["assembly"][0]["level"], "pass")
        self.assertGreaterEqual(diagnostics["assembly"][0]["clearance"], 10.0)
        for name in ("mesh-audit-meter.json", "mesh-audit-gateway.json", "scene-audit.json"):
            report = json.loads((specimen / "evidence" / name).read_text(encoding="utf-8"))
            self.assertEqual(report["verdict"], "pass", name)
        scene = json.loads((specimen / "evidence" / "scene-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(scene["drawCalls"], 2)
        validator = json.loads((specimen / "evidence" / "gltf-validator.json").read_text(encoding="utf-8"))
        self.assertEqual(validator["errors"], 0)
        self.assertEqual(validator["warnings"], 0)
        self.assertTrue((specimen / "evidence" / "field-telemetry-kit-sheet.png").read_bytes().startswith(b"\x89PNG"))

    def test_lookdev_catalog_is_consistent(self):
        """조명 리그·카메라 카탈로그의 내부 정합 — 리그가 가리키는 카메라 프리셋은 존재해야 한다."""
        data = json.loads((_SKILL / "engine" / "data" / "lookdev.json").read_text(encoding="utf-8"))
        self.assertEqual(data["tone"]["realtime_default"], "AgX")
        self.assertEqual(data["tone"]["bloom_threshold"], 1.0)
        self.assertEqual(data["turntable"]["frames"], 288)
        self.assertEqual(data["turntable"]["fps"], 24)
        self.assertGreaterEqual(len(data["rigs"]), 7)
        for name, rig in data["rigs"].items():
            self.assertTrue(rig.get("lights"), f"{name}: 조명 없는 리그")
            camera = rig.get("camera")
            if camera is not None:
                self.assertIn(camera, data["cameras"], f"{name}: 존재하지 않는 카메라 프리셋 참조")
        self.assertEqual(data["cameras"]["product_packshot"]["focal_mm_equiv"], [85, 100])

    def test_asset_catalog_carries_licenses_and_https(self):
        """수렵 카탈로그 계약: 전 소스에 라이선스, 전 URL 은 https, 비상업 모델은 표시된 채로."""
        data = json.loads((_SKILL / "engine" / "data" / "asset_catalog.json").read_text(encoding="utf-8"))
        sources = data["sources"]
        for name in ("polyhaven", "ambientcg", "kenney", "quaternius", "khronos_gltf_samples"):
            self.assertIn(name, sources)
        for name, source in sources.items():
            if name == "khronos_gltf_samples":
                for model in source["models"]:
                    self.assertTrue(model.get("license"), f"라이선스 없는 모델: {model.get('name')}")
            else:
                self.assertTrue(source.get("license"), f"라이선스 없는 소스: {name}")
        urls: list[str] = []

        def walk(node) -> None:
            if isinstance(node, dict):
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
            elif isinstance(node, str) and node.startswith("http"):
                urls.append(node)

        walk(sources)
        self.assertTrue(urls)
        self.assertEqual([url for url in urls if not url.startswith("https://")], [])
        for mood in ("studio_neutral", "golden_hour", "night"):
            self.assertTrue(sources["polyhaven"]["hdris"][mood], f"HDRI 무드 비어 있음: {mood}")
        damaged = next(model for model in sources["khronos_gltf_samples"]["models"] if model["name"] == "DamagedHelmet")
        self.assertIn("NC", damaged["license"], "비상업 제약이 카탈로그에서 지워졌다")


@unittest.skipIf(_NODE is None, "node 부재 — 3D 검증 런타임 검사 생략")
class FreyjaThreeDRuntime(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.project = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)

    def _audit(self, path: Path, *extra: str) -> dict:
        proc = _node(str(_SCRIPTS / "mesh_audit.mjs"), str(path), "--json", *extra, cwd=self.project)
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        return json.loads(proc.stdout)

    def test_thin_wall_fails_and_thick_wall_passes(self):
        thin = self.project / "thin.stl"
        thick = self.project / "thick.stl"
        _write_box_stl(thin, (20.0, 10.0, 0.5))
        _write_box_stl(thick, (20.0, 10.0, 3.0))

        thin_report = self._audit(thin, "--process", "fdm")
        self.assertEqual(thin_report["verdict"], "fail")
        wall = next(check for check in thin_report["checks"] if check["id"] == "wall")
        self.assertEqual(wall["level"], "fail")
        self.assertAlmostEqual(thin_report["wall"]["min"], 0.5, delta=0.02)

        thick_report = self._audit(thick, "--process", "fdm")
        self.assertEqual(next(check for check in thick_report["checks"] if check["id"] == "wall")["level"], "pass")
        self.assertTrue(thick_report["topology"]["watertight"])
        self.assertEqual(thick_report["topology"]["inconsistentEdges"], 0)
        self.assertAlmostEqual(thick_report["volume"], 600.0, delta=1.0)

    def test_flat_bottom_is_not_reported_as_overhang(self):
        """빌드 플레이트에 놓인 평평한 바닥은 서포트가 필요 없다 — 상류 도구의 알려진 오탐."""
        box = self.project / "block.stl"
        _write_box_stl(box, (20.0, 20.0, 10.0))
        report = self._audit(box, "--process", "fdm")
        self.assertEqual(report["overhang"]["ratio"], 0)
        self.assertEqual(next(check for check in report["checks"] if check["id"] == "overhang")["level"], "pass")

    def _write_mushroom(self, path: Path) -> None:
        """가는 기둥 위에 넓은 갓 — 갓의 아랫면 바깥쪽이 진짜 0° 오버행이다."""
        _write_boxes_stl(path, [((6.0, 6.0, 12.0), (7.0, 7.0, 0.0)), ((20.0, 20.0, 4.0), (0.0, 0.0, 12.0))])

    def test_floating_slab_is_reported_as_overhang(self):
        box = self.project / "mushroom.stl"
        self._write_mushroom(box)
        report = self._audit(box, "--process", "fdm")
        self.assertGreater(report["overhang"]["ratio"], 0.15)
        self.assertEqual(report["overhang"]["worst"]["tiltDeg"], 0)

    def test_powder_process_waives_overhang(self):
        box = self.project / "mushroom.stl"
        self._write_mushroom(box)
        report = self._audit(box, "--process", "sls")
        self.assertEqual(next(check for check in report["checks"] if check["id"] == "overhang")["level"], "pass")

    def test_render_writes_readable_png_evidence(self):
        box = self.project / "block.stl"
        _write_box_stl(box, (20.0, 12.0, 6.0))
        proc = _node(
            str(_SCRIPTS / "shoot.mjs"),
            str(box),
            "--out",
            "shots",
            "--views",
            "front,iso",
            "--size",
            "160",
            "--json",
            cwd=self.project,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(len(payload["views"]), 2)
        for name in [*payload["views"], payload["sheet"]]:
            data = (self.project / name).read_bytes()
            self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"), f"{name} 이 PNG 가 아니다")
            self.assertGreater(len(data), 200)
        self.assertEqual(payload["bbox"]["size"], [20, 12, 6])

    def test_detector_flags_dead_motion_and_spares_clean_code(self):
        source = self.project / "src"
        source.mkdir()
        (source / "bad.js").write_text(
            "import * as THREE from 'three';\n"
            "const renderer = new THREE.WebGLRenderer();\n"
            "renderer.setPixelRatio(window.devicePixelRatio);\n"
            "renderer.outputEncoding = THREE.sRGBEncoding;\n"
            "const controls = new OrbitControls(camera, renderer.domElement);\n"
            "controls.enableDamping = true;\n"
            "function animate() {\n"
            "  requestAnimationFrame(animate);\n"
            "  camera.position.lerp(new THREE.Vector3(0, 1, 0), 0.1);\n"
            "  renderer.render(scene, camera);\n"
            "}\n",
            encoding="utf-8",
        )
        (source / "good.jsx").write_text(
            "import { Canvas, useFrame } from '@react-three/fiber';\n"
            "import * as THREE from 'three';\n"
            "const TMP = new THREE.Vector3();\n"
            "const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;\n"
            "function Rig() {\n"
            "  useFrame((state, delta) => {\n"
            "    if (reduced) return;\n"
            "    state.camera.position.lerp(TMP, 1 - Math.pow(0.01, delta));\n"
            "  });\n"
            "  return null;\n"
            "}\n"
            "export default function Scene() {\n"
            "  return <Canvas dpr={[1, 2]} frameloop='demand'><Rig /></Canvas>;\n"
            "}\n",
            encoding="utf-8",
        )
        proc = _node(str(_SCRIPTS / "detect3d.mjs"), "src", "--json", cwd=self.project)
        payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 1)
        rules = {finding["rule"] for finding in payload["findings"]}
        self.assertIn("inert-controls", rules)
        self.assertIn("pixelratio-unclamped", rules)
        self.assertIn("deprecated-api", rules)
        self.assertIn("reduced-motion-missing", rules)
        self.assertEqual(
            [finding for finding in payload["findings"] if finding["file"].endswith("good.jsx")],
            [],
            "잘 쓴 코드에서 거짓 경보가 나면 검출기를 아무도 켜지 않는다",
        )

    def test_corrupt_stl_fails_cleanly(self):
        """깨진 모델은 스택트레이스가 아니라 진단 문장으로 죽어야 한다."""
        broken = self.project / "broken.stl"
        broken.write_bytes(bytes(range(100)))
        proc = _node(str(_SCRIPTS / "mesh_audit.mjs"), str(broken), "--json", cwd=self.project)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("모델을 읽지 못했다", proc.stderr)
        self.assertNotIn("ERR_OUT_OF_RANGE", proc.stderr)

    def test_comment_cannot_suppress_detection(self):
        """주석 속 controls.update() 언급이 inert-controls 판정을 뒤집으면 안 된다."""
        source = self.project / "src"
        source.mkdir()
        (source / "scene.js").write_text(
            "import * as THREE from 'three';\n"
            "// note: controls.update() is intentionally never called here\n"
            "const controls = new OrbitControls(camera, renderer.domElement);\n"
            "controls.enableDamping = true;\n",
            encoding="utf-8",
        )
        proc = _node(str(_SCRIPTS / "detect3d.mjs"), "src", "--json", cwd=self.project)
        payload = json.loads(proc.stdout)
        self.assertIn("inert-controls", {finding["rule"] for finding in payload["findings"]})

    def test_severity_filter_drops_warnings(self):
        source = self.project / "src"
        source.mkdir()
        (source / "scene.js").write_text(
            "import * as THREE from 'three';\n"
            "const renderer = new THREE.WebGLRenderer();\n"
            "renderer.setPixelRatio(window.devicePixelRatio);\n",
            encoding="utf-8",
        )
        proc = _node(str(_SCRIPTS / "detect3d.mjs"), "src", "--severity", "fail", "--json", cwd=self.project)
        payload = json.loads(proc.stdout)
        self.assertGreater(payload["counts"]["fail"], 0)
        self.assertEqual(payload["counts"]["warn"], 0)
        self.assertTrue(all(finding["severity"] == "fail" for finding in payload["findings"]))

    def test_inert_controls_spares_updated_and_disabled_damping(self):
        """대문자 변수명(orbitControls.update)과 damping 끈 코드는 오탐하면 안 된다."""
        source = self.project / "src"
        source.mkdir()
        (source / "updated.js").write_text(
            "import * as THREE from 'three';\n"
            "const orbitControls = new OrbitControls(camera, el);\n"
            "orbitControls.enableDamping = true;\n"
            "renderer.setAnimationLoop(() => { orbitControls.update(); renderer.render(scene, camera); });\n",
            encoding="utf-8",
        )
        (source / "disabled.jsx").write_text(
            "import { OrbitControls } from '@react-three/drei';\n"
            "import * as THREE from 'three';\n"
            "export const Rig = () => <OrbitControls enableDamping={false} />;\n",
            encoding="utf-8",
        )
        proc = _node(str(_SCRIPTS / "detect3d.mjs"), "src", "--json", cwd=self.project)
        payload = json.loads(proc.stdout)
        inert = [finding for finding in payload["findings"] if finding["rule"] == "inert-controls"]
        self.assertEqual(inert, [], "정상 코드에서 inert-controls 오탐")

    def test_meshopt_glb_is_reported_not_garbled(self):
        """meshopt 는 bufferView 레벨 확장 — 무경고로 압축 바이트를 생 float 로 읽으면 안 된다."""

        def mark_meshopt(gltf):
            gltf["extensionsUsed"] = ["EXT_meshopt_compression"]
            gltf["bufferViews"][0]["extensions"] = {
                "EXT_meshopt_compression": {"buffer": 0, "byteLength": 1, "count": 1, "mode": "ATTRIBUTES"}
            }

        glb = self.project / "meshopt.glb"
        _write_minimal_glb(glb, triangles=4, mutate=mark_meshopt)
        proc = _node(str(_SCRIPTS / "mesh_audit.mjs"), str(glb), "--json", cwd=self.project)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("압축 지오메트리", proc.stderr)

    def test_sceneless_gltf_does_not_double_count(self):
        """scenes 가 없으면 루트만 순회한다 — 자식 노드 이중 방문은 삼각형을 복제한다."""

        def drop_scenes(gltf):
            del gltf["scenes"]
            del gltf["scene"]
            gltf["nodes"] = [{"children": [1]}, {"mesh": 0}]

        glb = self.project / "sceneless.glb"
        _write_minimal_glb(glb, triangles=5, mutate=drop_scenes)
        proc = _node(str(_SCRIPTS / "mesh_audit.mjs"), str(glb), "--json", cwd=self.project)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["triangles"], 5)

    def test_overhang_waiver_message_matches_process(self):
        """분말 배출홀 안내는 분말 공정에만 — CNC 에 나가면 오정보다."""
        box = self.project / "block.stl"
        _write_box_stl(box, (20.0, 20.0, 10.0))
        for process, expect_powder in (("sls", True), ("cnc", False)):
            report = self._audit(box, "--process", process)
            message = next(check for check in report["checks"] if check["id"] == "overhang")["message"]
            self.assertEqual("분말" in message, expect_powder, f"{process}: {message}")

    def test_up_axis_flag_matches_shoot_semantics(self):
        """--up y 는 형식과 무관하게 Y-up→Z-up 변환한다 — shoot 와 같은 의미."""
        box = self.project / "block.stl"
        _write_box_stl(box, (20.0, 12.0, 6.0))
        report = self._audit(box, "--up", "y")
        self.assertEqual(report["bbox"]["size"], [20, 6, 12])

    def test_threemf_roundtrip_with_units_and_transform(self):
        """3MF 는 ZIP+XML — 선언 단위 환산과 build item 변환까지 읽어야 제조 왕복이 닫힌다."""
        verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
        quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
        triangles = [tri for a, b, c, d in quads for tri in ((a, b, c), (a, c, d))]
        vertex_xml = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in verts)
        triangle_xml = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in triangles)
        model = (
            '<?xml version="1.0"?>'
            '<model unit="inch" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
            f'<resources><object id="1" type="model"><mesh><vertices>{vertex_xml}</vertices>'
            f"<triangles>{triangle_xml}</triangles></mesh></object></resources>"
            '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 2 0 0"/></build></model>'
        )
        path = self.project / "cube.3mf"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("3D/3dmodel.model", model)
        report = self._audit(path, "--process", "fdm")
        # 1인치 큐브, X+2인치 이동 → mm: 25.4³ 부피, bbox min X = 50.8
        self.assertTrue(report["topology"]["watertight"])
        self.assertAlmostEqual(report["volume"], 25.4**3, delta=1.0)
        self.assertAlmostEqual(report["bbox"]["min"][0], 50.8, delta=0.01)

    def test_quantized_and_sparse_accessors_decode(self):
        """KHR_mesh_quantization(normalized int16)과 sparse accessor 는 조용히 틀린 좌표의 단골이다."""
        # 양자화: 노드 scale 10, 정점 (0,0,0)(1,0,0)(0,1,0) 정규화 int16
        full = 32767
        binary = b"".join(struct.pack("<3h2x", *v) for v in [(0, 0, 0), (full, 0, 0), (0, full, 0)])
        quantized = {
            "asset": {"version": "2.0"},
            "extensionsUsed": ["KHR_mesh_quantization"],
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0, "scale": [10, 10, 10]}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
            "accessors": [{"bufferView": 0, "componentType": 5122, "normalized": True, "count": 3, "type": "VEC3"}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(binary), "byteStride": 8}],
            "buffers": [{"byteLength": len(binary)}],
        }
        path = self.project / "quantized.glb"
        _write_raw_glb(path, quantized, binary)
        proc = _node(str(_SCRIPTS / "mesh_audit.mjs"), str(path), "--unit", "mm", "--json", cwd=self.project)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["bbox"]["size"], [10, 0, 10])  # Y-up→Z-up 후 한 변 10

        sparse_binary = struct.pack("<3H2x", 0, 1, 2) + struct.pack("<9f", 0, 0, 0, 2, 0, 0, 0, 2, 0)
        sparse = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
            "accessors": [
                {
                    "componentType": 5126,
                    "count": 3,
                    "type": "VEC3",
                    "sparse": {
                        "count": 3,
                        "indices": {"bufferView": 0, "componentType": 5123},
                        "values": {"bufferView": 1},
                    },
                }
            ],
            "bufferViews": [
                {"buffer": 0, "byteOffset": 0, "byteLength": 8},
                {"buffer": 0, "byteOffset": 8, "byteLength": 36},
            ],
            "buffers": [{"byteLength": len(sparse_binary)}],
        }
        path = self.project / "sparse.glb"
        _write_raw_glb(path, sparse, sparse_binary)
        proc = _node(str(_SCRIPTS / "mesh_audit.mjs"), str(path), "--unit", "mm", "--json", cwd=self.project)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["bbox"]["size"], [2, 0, 2])

    def test_injection_flags_thick_solid(self):
        """사출은 두꺼운 살이 싱크 마크를 만든다 — min 만 보면 솔리드 블록이 통과해 버린다."""
        box = self.project / "block.stl"
        _write_box_stl(box, (20.0, 20.0, 10.0))
        report = self._audit(box, "--process", "injection")
        wallmax = next(check for check in report["checks"] if check["id"] == "wallmax")
        self.assertEqual(wallmax["level"], "warn")

    def test_webgpu_render_without_init_is_flagged(self):
        source = self.project / "src"
        source.mkdir()
        (source / "bad.js").write_text(
            "import * as THREE from 'three/webgpu';\n"
            "const renderer = new THREE.WebGPURenderer();\n"
            "renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));\n"
            "renderer.render(scene, camera);\n",
            encoding="utf-8",
        )
        (source / "good.js").write_text(
            "import * as THREE from 'three/webgpu';\n"
            "const renderer = new THREE.WebGPURenderer();\n"
            "renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));\n"
            "renderer.setAnimationLoop(() => renderer.render(scene, camera));\n",
            encoding="utf-8",
        )
        proc = _node(str(_SCRIPTS / "detect3d.mjs"), "src", "--json", cwd=self.project)
        payload = json.loads(proc.stdout)
        flagged = [finding["file"] for finding in payload["findings"] if finding["rule"] == "webgpu-init-missing"]
        self.assertEqual(len(flagged), 1)
        self.assertTrue(flagged[0].endswith("bad.js"))

    def test_scene_audit_reads_glb_and_judges_budget(self):
        glb = self.project / "scene.glb"
        _write_minimal_glb(glb, triangles=200)
        proc = _node(str(_SCRIPTS / "scene_audit.mjs"), str(glb), "--target", "mobile", "--json", cwd=self.project)
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["triangles"], 200)
        self.assertEqual(payload["drawCalls"], 1)
        self.assertEqual(
            {check["id"] for check in payload["checks"]} & {"filesize", "triangles", "drawcalls"},
            {"filesize", "triangles", "drawcalls"},
        )

    def _read_glb_json(self, path: Path) -> dict:
        data = path.read_bytes()
        json_length = struct.unpack("<I", data[12:16])[0]
        return json.loads(data[20 : 20 + json_length])

    def test_polish_preserves_creases_and_welds_curves(self):
        """게임 준비의 핵심: 90° 모서리는 갈라진 채(하드), 완만한 곡면은 이어진 채(스무스)."""
        cube = self.project / "cube.stl"
        _write_box_stl(cube, (10.0, 10.0, 10.0))
        proc = _node(
            str(_SCRIPTS / "mesh_polish.mjs"),
            str(cube),
            "--out",
            "cube.glb",
            "--material",
            "steel",
            "--json",
            cwd=self.project,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        # 큐브: 8꼭짓점 × 인접면 3 = 24 정점이어야 크리스가 살아 있다.
        self.assertEqual(payload["vertices"], 24)
        self.assertEqual(payload["inputUnit"], "mm")
        self.assertEqual(payload["outputUnit"], "m")
        gltf = self._read_glb_json(self.project / "cube.glb")
        material = gltf["materials"][0]["pbrMetallicRoughness"]
        self.assertEqual(material["metallicFactor"], 1.0)
        roundtrip = self._audit(self.project / "cube.glb")
        self.assertEqual(roundtrip["bbox"]["size"], [10, 10, 10], "mm→m→mm 왕복 스케일이 깨졌다")

        # 16각 기둥: 옆면 사이 각 22.5° < 크리스 40° → 옆면 정점이 용접된다.
        import math as _math

        sides = 16
        triangles = []
        ring = [
            (_math.cos(2 * _math.pi * i / sides) * 5, _math.sin(2 * _math.pi * i / sides) * 5) for i in range(sides)
        ]
        for i in range(sides):
            (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % sides]
            triangles.append(((x0, y0, 0.0), (x1, y1, 0.0), (x1, y1, 8.0)))
            triangles.append(((x0, y0, 0.0), (x1, y1, 8.0), (x0, y0, 8.0)))
            triangles.append(((0.0, 0.0, 0.0), (x1, y1, 0.0), (x0, y0, 0.0)))
            triangles.append(((0.0, 0.0, 8.0), (x0, y0, 8.0), (x1, y1, 8.0)))
        payload_bytes = bytearray(b"prism".ljust(80, b"\0"))
        payload_bytes += struct.pack("<I", len(triangles))
        for a, b, c in triangles:
            payload_bytes += struct.pack("<3f", 0, 0, 0)
            for point in (a, b, c):
                payload_bytes += struct.pack("<3f", *point)
            payload_bytes += struct.pack("<H", 0)
        prism = self.project / "prism.stl"
        prism.write_bytes(bytes(payload_bytes))
        proc = _node(str(_SCRIPTS / "mesh_polish.mjs"), str(prism), "--out", "prism.glb", "--json", cwd=self.project)
        payload = json.loads(proc.stdout)
        corners = payload["triangles"] * 3
        self.assertLess(payload["vertices"], corners * 0.5, "곡면 정점이 용접되지 않았다")

    def test_bake_writes_masks_and_darkens_occluded(self):
        """베이크의 최소 계약: COLOR_0 이 실리고, 차폐가 만든 AO 차이가 남는다."""
        open_box = self.project / "open.stl"
        _write_box_stl(open_box, (20.0, 20.0, 4.0))
        shroom = self.project / "shroom.stl"
        self._write_mushroom(shroom)
        ao_means = {}
        for path in (open_box, shroom):
            proc = _node(
                str(_SCRIPTS / "mesh_polish.mjs"),
                str(path),
                "--out",
                f"{path.stem}.glb",
                "--bake",
                "--json",
                cwd=self.project,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            ao_means[path.stem] = payload["parts"][0]["bake"]["aoMean"]
            gltf = self._read_glb_json(self.project / f"{path.stem}.glb")
            self.assertIn("COLOR_0", gltf["meshes"][0]["primitives"][0]["attributes"])
        self.assertLess(ao_means["shroom"], ao_means["open"], "갓 아래 차폐가 AO 에 반영되지 않았다")

    def test_polish_merges_fragmented_parts(self):
        """CAD 내보내기는 부품 하나를 면 단위 프리미티브로 쪼갠다 — 같은 이름은 병합해야 드로우콜 1 이다."""

        def duplicate_node(gltf):
            gltf["meshes"].append(gltf["meshes"][0])
            gltf["nodes"] = [
                {"mesh": 0, "name": "body"},
                {"mesh": 1, "name": "body", "translation": [10, 0, 0]},
            ]
            gltf["scenes"] = [{"nodes": [0, 1]}]

        glb = self.project / "fragmented.glb"
        _write_minimal_glb(glb, triangles=3, mutate=duplicate_node)
        proc = _node(str(_SCRIPTS / "mesh_polish.mjs"), str(glb), "--out", "merged.glb", "--json", cwd=self.project)
        payload = json.loads(proc.stdout)
        self.assertEqual(len(payload["parts"]), 1)
        self.assertEqual(payload["triangles"], 6)
        gltf = self._read_glb_json(self.project / "merged.glb")
        self.assertEqual(len(gltf["meshes"]), 1)

    def test_polish_refuses_to_destroy_animated_gltf(self):
        def add_animation(gltf):
            gltf["animations"] = [{"name": "idle", "channels": [], "samplers": []}]

        glb = self.project / "animated.glb"
        _write_minimal_glb(glb, triangles=3, mutate=add_animation)
        proc = _node(str(_SCRIPTS / "mesh_polish.mjs"), str(glb), "--out", "lossy.glb", cwd=self.project)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("손실 변환 거부", proc.stderr)
        self.assertFalse((self.project / "lossy.glb").exists())

    def test_preflight_reports_lane_readiness(self):
        proc = _node(str(_SCRIPTS / "preflight.mjs"), str(self.project), "--json", cwd=self.project)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        lanes = {lane["lane"]: lane for lane in payload["lanes"]}
        self.assertEqual(set(lanes), {"verify", "cad", "realtime", "motion", "pipeline", "game"})
        self.assertTrue(lanes["verify"]["ready"], "검증 런타임은 의존성이 없어 항상 준비 상태여야 한다")
        self.assertTrue(lanes["game"]["ready"], "폴리시 경로는 무의존이라 항상 준비 상태여야 한다")

    _LOOK_RULES = {"env-missing", "ambient-only-lighting", "debug-look-shipped", "primary-color-material"}

    def test_look_slop_rules_fire_and_spare_lit_scene(self):
        """초보 티 4규칙: 씬 루트의 슬롭에서 발화하고, 환경·키 라이트를 갖춘 씬은 건드리지 않는다."""
        source = self.project / "src"
        source.mkdir()
        (source / "slop.js").write_text(
            "import * as THREE from 'three';\n"
            "const renderer = new THREE.WebGLRenderer({ antialias: true });\n"
            "renderer.toneMapping = THREE.AgXToneMapping;\n"
            "const scene = new THREE.Scene();\n"
            "scene.add(new THREE.AmbientLight(0xffffff, 1));\n"
            "const hero = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0xff0000 }));\n"
            "const debug = new THREE.Mesh(geometry, new THREE.MeshNormalMaterial());\n",
            encoding="utf-8",
        )
        (source / "lit.js").write_text(
            "import * as THREE from 'three';\n"
            "import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';\n"
            "const renderer = new THREE.WebGLRenderer({ antialias: true });\n"
            "renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));\n"
            "renderer.toneMapping = THREE.AgXToneMapping;\n"
            "const pmrem = new THREE.PMREMGenerator(renderer);\n"
            "scene.environment = pmrem.fromScene(new RoomEnvironment()).texture;\n"
            "scene.add(new THREE.DirectionalLight(0xfff2e0, 3));\n"
            "scene.add(new THREE.AmbientLight(0x404040, 0.3));\n"
            "const hero = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: '#8d98a7' }));\n"
            "new ResizeObserver(() => camera.updateProjectionMatrix()).observe(canvas);\n",
            encoding="utf-8",
        )
        proc = _node(str(_SCRIPTS / "detect3d.mjs"), "src", "--json", cwd=self.project)
        payload = json.loads(proc.stdout)
        slop_rules = {finding["rule"] for finding in payload["findings"] if finding["file"].endswith("slop.js")}
        self.assertEqual(self._LOOK_RULES - slop_rules, set(), "슬롭 씬에서 안 잡힌 룩 규칙")
        lit_rules = {finding["rule"] for finding in payload["findings"] if finding["file"].endswith("lit.js")}
        self.assertEqual(lit_rules & self._LOOK_RULES, set(), "제대로 조명한 씬에서 룩 규칙 오탐")

    def test_polish_reads_presets_from_material_catalog(self):
        """프리셋 정본은 materials.json 하나 — 카탈로그의 신규 프리셋이 실제 GLB 재질로 배선된다."""
        catalog = json.loads((_SKILL / "engine" / "data" / "materials.json").read_text(encoding="utf-8"))
        preset = catalog["presets"]["copper"]
        cube = self.project / "cube.stl"
        _write_box_stl(cube, (10.0, 10.0, 10.0))
        proc = _node(
            str(_SCRIPTS / "mesh_polish.mjs"),
            str(cube),
            "--out",
            "copper.glb",
            "--material",
            "copper",
            "--json",
            cwd=self.project,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        material = self._read_glb_json(self.project / "copper.glb")["materials"][0]["pbrMetallicRoughness"]
        self.assertAlmostEqual(material["metallicFactor"], preset["metallic"], delta=0.01)
        self.assertAlmostEqual(material["roughnessFactor"], preset["roughness"], delta=0.01)
        for channel, expected in zip(material["baseColorFactor"], preset["baseColor"], strict=True):
            self.assertAlmostEqual(channel, expected, delta=0.01)

    def test_critique_store_roundtrip_trend_and_retention(self):
        """판정 스냅샷 계약: 슬러그 안정, 메타 왕복, 추세 조회, 대상당 최근 5개 보존."""
        store = str(_SCRIPTS / "critique_store.mjs")
        proc = _node(store, "slug", "build/model.glb", cwd=self.project)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "build-model-glb")

        body = self.project / "body.md"
        body.write_text("판정 본문", encoding="utf-8")
        env = {**os.environ, "FREYJA3D_CRITIQUE_META": '{"total_score":26,"max_score":32,"p0_count":0}'}
        proc = subprocess.run(  # noqa: S603
            [str(_NODE), store, "write", "build/model.glb", str(body)],
            cwd=str(self.project),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        written = Path(proc.stdout.strip())
        self.assertTrue(written.is_file())
        self.assertIn(".vanadis", written.parts)

        proc = _node(store, "latest", "build/model.glb", cwd=self.project)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("total_score: 26", proc.stdout)
        self.assertIn("판정 본문", proc.stdout)
        rows = json.loads(_node(store, "trend", "build/model.glb", cwd=self.project).stdout)
        self.assertEqual(rows[-1]["total_score"], 26)
        self.assertEqual(rows[-1]["max_score"], 32)

        # 보존 5 — CLI 타임스탬프는 초 단위라 API 로 초를 벌려 7개를 쓴다.
        script = (
            "import { pathToFileURL } from 'node:url';\n"
            # argv[1] 에 스토어 경로를 두면 isMainModule 판별이 참이 되어 CLI 가 실행된다 — argv[2] 로 민다.
            "const { writeSnapshot } = await import(pathToFileURL(process.argv[2]).href);\n"
            "for (let i = 0; i < 7; i += 1) {\n"
            "  writeSnapshot({ slug: 'retention-target', meta: { total_score: i }, body: `run ${i}`,\n"
            "    now: new Date(Date.UTC(2026, 0, 1, 0, 0, i)) });\n"
            "}\n"
        )
        proc = _node("--input-type=module", "-e", script, "argv-shim", store, cwd=self.project)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        kept = sorted((self.project / ".asgard" / ".vanadis" / "3d" / "critique").glob("*__retention-target.md"))
        self.assertEqual(len(kept), 5, "보존 상한이 지켜지지 않았다")
        self.assertIn("run 6", kept[-1].read_text(encoding="utf-8"))


def _write_raw_glb(path: Path, gltf: dict, binary: bytes) -> None:
    """임의 glTF JSON + BIN 청크를 GLB 로 포장한다 — 양자화·sparse 픽스처용."""
    json_chunk = json.dumps(gltf).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    binary += b"\0" * ((4 - len(binary) % 4) % 4)
    body = (
        struct.pack("<I", len(json_chunk)) + b"JSON" + json_chunk + struct.pack("<I", len(binary)) + b"BIN\0" + binary
    )
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)


def _write_minimal_glb(path: Path, triangles: int, mutate=None) -> None:
    """POSITION 만 가진 최소 GLB — 예산 감사가 삼각형·드로우콜을 세는지 확인용."""
    count = triangles * 3
    vertices = bytearray()
    for index in range(count):
        vertices += struct.pack("<3f", float(index % 7), float(index % 5), float(index % 3))
    padding = (4 - len(vertices) % 4) % 4
    vertices += b"\0" * padding
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": count,
                "type": "VEC3",
                "min": [0.0, 0.0, 0.0],
                "max": [6.0, 4.0, 2.0],
            }
        ],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(vertices)}],
        "buffers": [{"byteLength": len(vertices)}],
    }
    if mutate is not None:
        mutate(gltf)
    json_chunk = json.dumps(gltf).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    body = (
        struct.pack("<I", len(json_chunk))
        + b"JSON"
        + json_chunk
        + struct.pack("<I", len(vertices))
        + b"BIN\0"
        + bytes(vertices)
    )
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)


if __name__ == "__main__":
    unittest.main()
