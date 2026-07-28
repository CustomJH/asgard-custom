"""프레이야 CAD 레인 — 벤더링 무결성·라우팅·배달 게이트.

이 파일이 지키는 것은 셋이다.

1. **벤더링이 조용히 깨지지 않는다.** 중복 제거로 끊은 상대 경로가 다시 끊기면 여기서 죽는다.
   이 저장소는 벤더 자산이 gitignore 블랭킷에 먹혀 소실된 적이 있다(freyja2 lib/ 15모듈).
2. **새 능력이 라우팅에 닿는다.** 런타임이 있어도 프레이야가 부르지 못하면 없는 것과 같다.
3. **배달 게이트가 실제로 막는다.** 통과만 시키는 게이트는 게이트가 아니라 장식이다.

여기서 커널(build123d/OCP)을 요구하지 않는다 — 500MB 휠을 받는 테스트는 CI 에서 살지 못한다.
커널이 실제로 도는지는 실주행으로 확인했고, 여기서는 **형상(shape)** 을 지킨다.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from asgard import skill_registry

_PLUGIN = Path(skill_registry.__file__).parent / "assets" / "skill_plugins" / "freyja-3d"
_SKILL = _PLUGIN / "skills" / "asgard-freyja-3d"
_SCRIPTS = _SKILL / "engine" / "scripts"
_REFERENCE = _SKILL / "engine" / "reference"
_VENDOR = _SKILL / "engine" / "vendor" / "text-to-cad"

# 실제 STEP 물리 파일의 첫 줄. 게이트가 가짜 STEP 을 가르는 기준이라 테스트도 같은 토큰을 쓴다.
_STEP_HEAD = "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


def _gate(*paths: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(_SCRIPTS / "cad_gate.mjs"), *[str(p) for p in paths], "--json"],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _rules(result: subprocess.CompletedProcess[str]) -> set[str]:
    return {finding["rule"] for finding in json.loads(result.stdout)["findings"]}


class VendorIntegrity(unittest.TestCase):
    """상류 런타임이 통째로, 그리고 실행 가능한 상태로 들어와 있는가."""

    def test_all_eleven_upstream_skills_are_vendored(self):
        expected = {
            "cad", "cad-viewer", "dxf", "gcode", "implicit-cad",
            "sdf", "sendcutsend", "srdf", "step-parts", "urdf", "bambu-labs",
        }  # fmt: skip
        present = {path.name for path in (_VENDOR / "skills").iterdir() if path.is_dir()}
        self.assertEqual(expected, present)

    def test_shared_runtime_packages_are_vendored_once(self):
        for package in ("cadpy", "cadpy_metadata", "cadjs", "implicitjs"):
            self.assertTrue((_VENDOR / "packages" / package).is_dir(), f"{package} 가 없다")
        # 스킬별 중복 사본이 되살아나면 용량이 두 배가 되고 어느 쪽이 정본인지 알 수 없어진다.
        duplicates = [
            path
            for path in (_VENDOR / "skills").rglob("packages")
            if path.is_dir()
            and any(child.name.startswith("cad") or child.name == "implicitjs" for child in path.iterdir())
        ]
        self.assertEqual([], duplicates, f"스킬 안에 런타임 사본이 되살아났다: {duplicates}")

    def test_cli_entrypoints_exist(self):
        for relative in (
            "skills/cad/scripts/step",
            "skills/cad/scripts/inspect",
            "skills/cad/scripts/snapshot",
            "skills/dxf/scripts/dxf",
            "skills/gcode/scripts/gcode_tool.py",
            "skills/step-parts/scripts/download_step_part.py",
            "skills/urdf/scripts/urdf",
            "skills/srdf/scripts/srdf",
            "skills/sdf/scripts/sdf",
            "skills/cad-viewer/scripts/viewer/backend/server.mjs",
            "skills/cad-viewer/scripts/viewer/dist/index.html",
        ):
            self.assertTrue((_VENDOR / relative).exists(), f"{relative} 가 없다")

    def test_deduplication_did_not_orphan_relative_imports(self):
        """중복 제거로 끊었던 경로가 실제로 이어지는가 — 파일 존재로 확인한다.

        상대 경로가 틀리면 import 시점까지 아무도 모른다. 그래서 경로를 문자열로
        읽어 실제 파일로 resolve 해본다.
        """
        schema = _VENDOR / "skills/implicit-cad/scripts/lib/implicit-cad.mjs"
        body = schema.read_text(encoding="utf-8")
        self.assertIn("../../../../packages/implicitjs", body)
        self.assertTrue(
            (schema.parent / "../../../../packages/implicitjs/src/lib/implicitCad/schema.js").resolve().is_file()
        )

        for name in ("export", "snapshot"):
            launcher = _VENDOR / f"skills/implicit-cad/scripts/{name}.mjs"
            self.assertIn('"..", "..", "..", "packages", "implicitjs"', launcher.read_text(encoding="utf-8"))
            self.assertTrue((_VENDOR / f"packages/implicitjs/scripts/{name}.mjs").is_file())

    def test_requirements_point_at_the_shared_packages(self):
        for relative, package in (
            ("skills/cad/requirements.txt", "cadpy"),
            ("skills/dxf/requirements.txt", "cadpy"),
            ("skills/cad-viewer/requirements.txt", "cadpy"),
            ("skills/urdf/requirements.txt", "cadpy_metadata"),
            ("skills/srdf/requirements.txt", "cadpy_metadata"),
            ("skills/sdf/requirements.txt", "cadpy_metadata"),
        ):
            path = _VENDOR / relative
            line = path.read_text(encoding="utf-8").splitlines()[0]
            self.assertTrue(line.startswith("--editable "), f"{relative}: {line}")
            target = (path.parent / line.removeprefix("--editable ").strip()).resolve()
            self.assertEqual(
                (_VENDOR / "packages" / package).resolve(), target, f"{relative} 가 공유 패키지를 안 가리킨다"
            )

    def test_license_and_deviation_ledger_are_present(self):
        """MIT 는 저작권 고지 보존을 요구한다. 편차 목록은 다음 동기화의 유일한 단서다."""
        self.assertIn("MIT License", (_VENDOR / "LICENSE").read_text(encoding="utf-8"))
        notice = (_PLUGIN / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("MIT License", notice)
        self.assertIn("earthtojake", notice)
        upstream = (_VENDOR / "UPSTREAM.md").read_text(encoding="utf-8")
        self.assertIn("fdbb4b4fb62d95ae298cfe9a46fdc7092bdaf423", upstream)
        for heading in ("Deviations from upstream", "Known upstream gaps", "Re-syncing"):
            self.assertIn(heading, upstream)


class LaneRouting(unittest.TestCase):
    """새 능력이 프레이야에게 실제로 닿는가."""

    def test_new_capability_prompts_resolve_to_the_engine(self):
        with tempfile.TemporaryDirectory() as root:
            for prompt in (
                "STEP 조립체 만들어줘",
                "DXF 도면 뽑아줘",
                "URDF 로봇 기술 파일 만들어줘",
                "G-code 슬라이싱 해줘",
                "M3 나사 규격 부품 찾아줘",
                "implicit SDF 조형 해줘",
            ):
                names = {name for name, _ in skill_registry.resolve_skills(root, prompt, "freyja")}
                self.assertIn("asgard-freyja-3d", names, f"라우팅 실패: {prompt}")

    def test_new_lane_documents_exist_and_are_routed(self):
        body = (_SKILL / "SKILL.md").read_text(encoding="utf-8")
        for name in (
            "lane-fabricate",
            "lane-robot",
            "lane-implicit",
            "lane-viewer",
            "cad-refs",
            "cad-snapshot",
            "cad-assembly",
            "cad-brief",
            "cad-repair",
        ):
            self.assertTrue((_REFERENCE / f"{name}.md").is_file(), f"{name}.md 가 없다")
        # SKILL.md 는 레인 문서를 직접 가리키고, 세부 문서는 lane-cad 가 이어받는다.
        for name in ("lane-fabricate", "lane-robot", "lane-implicit", "lane-viewer", "cad-refs", "cad-snapshot"):
            self.assertIn(f"{name}.md", body, f"SKILL.md 가 {name}.md 로 라우팅하지 않는다")
        lane_cad = (_REFERENCE / "lane-cad.md").read_text(encoding="utf-8")
        for name in ("cad-refs", "cad-assembly", "cad-brief", "cad-repair", "lane-fabricate"):
            self.assertIn(f"{name}.md", lane_cad, f"lane-cad.md 가 {name}.md 로 이어주지 않는다")

    def test_escalation_no_longer_defers_absorbed_capabilities(self):
        """흡수한 능력을 계속 '외부 도구로 넘겨라'라고 적어두면 그 능력은 죽은 채로 남는다."""
        body = (_REFERENCE / "escalation.md").read_text(encoding="utf-8")
        table = body.split("## 예전에 넘기던 것")[0]
        self.assertNotIn("text-to-cad", table, "승급 표가 아직 흡수된 도구를 가리킨다")
        self.assertIn("더 이상 승급 대상이 아니다", body)

    def test_launcher_covers_every_vendored_cli(self):
        body = (_SCRIPTS / "cad.py").read_text(encoding="utf-8")
        for tool in ("step", "inspect", "snapshot", "dxf", "gcode", "parts", "urdf", "srdf", "sdf"):
            self.assertIn(f'"{tool}":', body, f"cad.py 가 {tool} 을 노출하지 않는다")

    def test_launcher_reports_missing_runtime_instead_of_pretending(self):
        result = subprocess.run(
            [sys.executable, str(_SCRIPTS / "cad.py"), "nope"], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("모르는 도구다", result.stderr)


class WindowsConsoleEncoding(unittest.TestCase):
    """한국어 Windows(cp949) 콘솔에서 죽지 않는가.

    이 저장소가 두 번 고친 결함이다(v0.6.31·32). 스킬 플러그인 스크립트는 그 청소에서
    빠져 있었고, `cad.py --help` 는 엠대시 한 글자 때문에 UnicodeEncodeError 로 죽었다.
    개발기(POSIX·utf-8)에서는 영원히 초록이라 실행으로만 잡힌다 — 그래서 자식 프로세스에
    인코딩을 실제로 주입해서 돌린다.
    """

    def _run(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        import os

        env = {**os.environ, "PYTHONIOENCODING": "cp949"}
        return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, timeout=60, env=env)

    def test_launcher_help_survives_a_cp949_console(self):
        result = self._run(_SCRIPTS / "cad.py", "--help")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("UnicodeEncodeError", result.stderr)

    def test_launcher_errors_survive_a_cp949_console(self):
        result = self._run(_SCRIPTS / "cad.py", "nope")
        self.assertEqual(2, result.returncode)
        self.assertNotIn("UnicodeEncodeError", result.stderr)

    def test_engine_python_scripts_force_utf8_output(self):
        """실행 없이도 지킨다 — 새 스크립트가 가드 없이 들어오는 것을 막는 형상 검사."""
        for script in sorted(_SCRIPTS.glob("*.py")):
            text = script.read_text(encoding="utf-8")
            if "stdout.write" not in text and "stderr.write" not in text and "print(" not in text:
                continue
            with self.subTest(script=script.name):
                self.assertIn(
                    'reconfigure(encoding="utf-8")',
                    text,
                    f"{script.name} 이 사람이 읽는 출력을 내면서 UTF-8 을 강제하지 않는다",
                )


class PartCollection(unittest.TestCase):
    """cad_build.py 가 STEP 레인과 같은 소스 파일을 먹는가.

    커널 없이 판정한다 — `_is_shape` 가 `isinstance(value, bd.Shape)` 하나만 보므로
    가짜 build123d 모듈로 규약을 그대로 재현할 수 있다.
    """

    @staticmethod
    def _harness():
        import importlib.util
        import types

        spec = importlib.util.spec_from_file_location("cad_build_probe", _SCRIPTS / "cad_build.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class Shape:
            def __init__(self, label="", children=()):
                self.label = label
                self.children = list(children)

        return module, types.SimpleNamespace(Shape=Shape), Shape

    def test_gen_step_wins_over_the_legacy_parts_dict(self):
        module, bd, Shape = self._harness()
        preferred, legacy = Shape("from_gen_step"), Shape("from_parts")
        collected = module.collect_parts(bd, {"gen_step": lambda: preferred, "PARTS": {"legacy": legacy}})
        self.assertEqual([preferred], list(collected.values()))

    def test_a_labelled_compound_explodes_into_named_parts(self):
        """조립체의 간섭 검사 단위는 부품이다 — 자식을 펴지 않으면 쌍이 생기지 않는다."""
        module, bd, Shape = self._harness()
        base, lid = Shape("base"), Shape("lid")
        collected = module.collect_parts(bd, {"gen_step": lambda: Shape("enclosure", [base, lid])})
        self.assertEqual({"base": base, "lid": lid}, collected)

    def test_an_unlabelled_compound_stays_whole(self):
        """이름 없는 조각을 part_0/part_1 로 불러봐야 간섭 보고를 읽을 수 없다."""
        module, bd, Shape = self._harness()
        whole = Shape("thing", [Shape(""), Shape("")])
        self.assertEqual({"thing": whole}, module.collect_parts(bd, {"gen_step": lambda: whole}))

    def test_duplicate_child_labels_stay_whole(self):
        module, bd, Shape = self._harness()
        whole = Shape("pair", [Shape("same"), Shape("same")])
        self.assertEqual({"pair": whole}, module.collect_parts(bd, {"gen_step": lambda: whole}))

    def test_the_legacy_parts_convention_still_works(self):
        """기존 소스를 깨지 않는다 — 이 규약으로 쓰인 기준 표본이 저장소에 들어 있다."""
        module, bd, Shape = self._harness()
        base, lid = Shape("base"), Shape("lid")
        collected = module.collect_parts(bd, {"PARTS": {"base": base, "lid": lid}})
        self.assertEqual({"base": base, "lid": lid}, collected)


class DeliveryGate(unittest.TestCase):
    """게이트가 통과시켜야 할 것을 통과시키고, 막아야 할 것을 막는가."""

    def _delivery(self, tmp: Path, *, step: bool = True, shot: bool = True) -> Path:
        root = tmp / "delivery"
        root.mkdir()
        if step:
            (root / "part.step").write_text(_STEP_HEAD, encoding="utf-8")
        if shot:
            (root / "iso.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return root

    def test_healthy_delivery_passes(self):
        """오탐이 하나라도 있으면 게이트는 즉시 무시당한다 — 통과 경로를 먼저 지킨다."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._delivery(Path(tmp))
            # 위상 산출물이 있어야 STEP 이 검증 가능한 상태다.
            (root / ".part.step.glb").write_bytes(b"not-a-glb")
            result = _gate(root)
            self.assertEqual(0, result.returncode, result.stdout)
            self.assertEqual("pass", json.loads(result.stdout)["status"])

    def test_blocks_a_mesh_renamed_as_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._delivery(Path(tmp), step=False)
            (root / "part.step").write_text("solid exported\nfacet normal 0 0 1\n", encoding="utf-8")
            result = _gate(root)
            self.assertEqual(1, result.returncode)
            self.assertIn("fake-step", _rules(result))

    def test_blocks_geometry_delivered_without_any_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._delivery(Path(tmp), shot=False)
            (root / ".part.step.glb").write_bytes(b"not-a-glb")
            result = _gate(root)
            self.assertEqual(1, result.returncode)
            self.assertIn("snapshot-missing", _rules(result))

    def test_blocks_a_step_verified_by_nothing_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._delivery(Path(tmp))
            result = _gate(root)
            self.assertEqual(1, result.returncode)
            self.assertIn("topology-missing", _rules(result))

    def test_mesh_verified_delivery_warns_instead_of_blocking(self):
        """막아야 하는 것은 '다르게 검증된' 배달이 아니라 '검증되지 않은' 배달이다.

        메시 경로(mesh_audit + 렌더)로 검증한 STEP 은 셀렉터 측정을 못 할 뿐 정당한
        배달이다. 이 엔진이 들고 다니는 기준 표본 둘이 실제로 그 경로로 만들어졌고,
        여기서 막으면 게이트는 첫날부터 무시당한다.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self._delivery(Path(tmp))
            (root / "mesh-audit.json").write_text(
                json.dumps({"tool": "mesh_audit", "status": "pass", "watertight": True}), encoding="utf-8"
            )
            result = _gate(root)
            self.assertEqual(0, result.returncode, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual("pass", payload["status"])
            self.assertEqual(["warn"], [f["severity"] for f in payload["findings"] if f["rule"] == "topology-missing"])

    def test_shipped_reference_specimens_are_not_false_positives(self):
        """실코퍼스 오탐 0 — 엔진이 들고 다니는 실제 배달물에 게이트를 그대로 겨눈다."""
        specimens = _SKILL / "assets"
        for name in ("inspection-prop", "field-telemetry-kit"):
            with self.subTest(specimen=name):
                result = _gate(specimens / name)
                self.assertEqual(0, result.returncode, f"{name} 에서 오탐:\n{result.stdout}")

    def test_blocks_interference_reported_in_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._delivery(Path(tmp))
            (root / ".part.step.glb").write_bytes(b"not-a-glb")
            (root / "diagnostics.json").write_text(
                json.dumps({"assembly": [{"pair": ["base", "lid"], "interferenceVolume": 1950.0}]}),
                encoding="utf-8",
            )
            result = _gate(root)
            self.assertEqual(1, result.returncode)
            self.assertIn("interference", _rules(result))

    def test_touching_zero_interference_is_not_a_failure(self):
        """딱 맞닿은 면(0mm³)은 정상이다. 여기서 오탐이 나면 모든 조립체가 막힌다."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._delivery(Path(tmp))
            (root / ".part.step.glb").write_bytes(b"not-a-glb")
            (root / "diagnostics.json").write_text(
                json.dumps({"assembly": [{"pair": ["base", "lid"], "interferenceVolume": 0.0, "clearance": 0.0}]}),
                encoding="utf-8",
            )
            self.assertEqual(0, _gate(root).returncode)

    def test_blocks_a_dxf_without_declared_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._delivery(Path(tmp), step=False)
            (root / "cut.dxf").write_text("0\nSECTION\n2\nHEADER\n0\nENDSEC\n", encoding="utf-8")
            result = _gate(root)
            self.assertEqual(1, result.returncode)
            self.assertIn("dxf-units", _rules(result))

    def test_accepts_a_dxf_that_declares_millimetres(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._delivery(Path(tmp), step=False)
            (root / "cut.dxf").write_text("0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n", encoding="utf-8")
            self.assertEqual(0, _gate(root).returncode)

    def test_declares_what_it_cannot_judge(self):
        """침묵은 통과가 아니다 — 못 재는 것을 이름으로 남기는지 확인한다."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._delivery(Path(tmp))
            (root / ".part.step.glb").write_bytes(b"not-a-glb")
            payload = json.loads(_gate(root).stdout)
            self.assertGreaterEqual(len(payload["unjudged"]), 4)
            self.assertTrue(any("닮았는가" in item for item in payload["unjudged"]))

    def test_requires_a_target(self):
        result = subprocess.run(["node", str(_SCRIPTS / "cad_gate.mjs")], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
