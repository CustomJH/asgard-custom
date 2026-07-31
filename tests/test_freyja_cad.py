"""프레이야 CAD 레인 — 네이티브 런타임 형상·능력·배달 게이트.

이 파일이 지키는 것은 넷이다.

1. **런타임이 이 엔진 것으로 남는다.** 이전 판은 상류 스킬 라이브러리를 통째로 벤더링해
   그 CLI를 격리 실행했다. 지금은 `engine/scripts/cadlib/`이 정본이고, 상류 흔적(벤더 트리·
   라이선스 파일·상류 경로 문자열)이 되살아나면 여기서 죽는다.
2. **커널 없이 되는 것이 실제로 커널 없이 된다.**이 엔진의 핵심 설계는 "판독·검증은 공짜,
   생성만 비싸다"이고, 그 약속이 깨지면 검증을 안 하게 된다. 그래서 무커널 경로를 실행으로 잰다.
3. **못 잰 것을 통과로 세지 않는다.** `Report`의 세 등급(pass/warn=미확인/fail)이 자료구조로
   지켜지는지 본다.
4. **배달 게이트가 실제로 막는다.** 통과만 시키는 게이트는 게이트가 아니라 장식이다.

여기서 커널(build123d/OCP)을 요구하지 않는다 — 500MB 휠을 받는 테스트는 CI에서 살지 못한다.
커널이 실제로 도는지는 실주행으로 확인했고, 여기서는 **형상(shape)**과 무커널 능력을 지킨다.
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
_CADLIB = _SCRIPTS / "cadlib"

# 엔진 런타임은 패키지가 아니라 스킬 자산이라 여기서 경로를 얹어 연다. 그래서 아래 지역
# 임포트들은 정적으로 해석되지 않고, 한 줄씩 unresolved-import 억제 주석을 단다.
sys.path.insert(0, str(_SCRIPTS))

# 실제 STEP 물리 파일의 첫 줄. 게이트가 가짜 STEP을 가르는 기준이라 테스트도 같은 토큰을 쓴다.
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
        # SKILL.md는 레인 문서를 직접 가리키고, 세부 문서는 lane-cad가 이어받는다.
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

    def test_launcher_exposes_every_lane_tool(self):
        from cad import TOOLS  # ty: ignore[unresolved-import]

        self.assertEqual(
            {"step", "inspect", "dxf", "gcode", "parts", "urdf", "srdf", "sdf"},
            set(TOOLS),
            "cad.py 의 도구 목록이 레인 문서와 어긋난다",
        )

    def test_only_shape_generation_needs_isolation(self):
        """검증이 싸다는 것이 이 엔진의 설계다. 판독 도구가 uv 뒤로 넘어가면 아무도 검증하지 않는다."""
        from cad import INSTANT, ISOLATED  # ty: ignore[unresolved-import]

        self.assertEqual({"step", "dxf"}, set(ISOLATED), "커널을 요구하는 도구가 늘었다")
        for tool in ("inspect", "gcode", "urdf", "srdf", "sdf", "parts"):
            self.assertIn(tool, INSTANT, f"{tool} 이 격리 실행으로 밀려났다")

    def test_launcher_reports_missing_runtime_instead_of_pretending(self):
        result = subprocess.run(
            [sys.executable, str(_SCRIPTS / "cad.py"), "nope"], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("모르는 도구다", result.stderr)


class WindowsConsoleEncoding(unittest.TestCase):
    """한국어 Windows(cp949) 콘솔에서 죽지 않는가.

    이 저장소가 두 번 고친 결함이다(v0.6.31·32). 스킬 플러그인 스크립트는 그 청소에서
    빠져 있었고, `cad.py --help`는 엠대시 한 글자 때문에 UnicodeEncodeError로 죽었다.
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

    def test_the_shared_utf8_helper_actually_reconfigures(self):
        """아래 형상 검사가 이 헬퍼를 인정하므로, 헬퍼가 비면 가드 전체가 빈 껍데기가 된다."""
        body = (_CADLIB / "report.py").read_text(encoding="utf-8")
        self.assertIn("def utf8_console()", body)
        self.assertIn('reconfigure(encoding="utf-8")', body)

    def test_engine_python_scripts_force_utf8_output(self):
        """실행 없이도 지킨다 — 새 스크립트가 가드 없이 들어오는 것을 막는 형상 검사.

        직접 `reconfigure` 하거나 공유 헬퍼 `utf8_console()`을 부르거나 둘 중 하나면 된다.
        헬퍼 쪽 경로는 바로 위 테스트가 속이 빈 것이 아님을 따로 지킨다.
        """
        for script in sorted(_SCRIPTS.glob("*.py")):
            text = script.read_text(encoding="utf-8")
            if "stdout.write" not in text and "stderr.write" not in text and "print(" not in text:
                continue
            with self.subTest(script=script.name):
                self.assertTrue(
                    'reconfigure(encoding="utf-8")' in text or "utf8_console()" in text,
                    f"{script.name} 이 사람이 읽는 출력을 내면서 UTF-8 을 강제하지 않는다",
                )


class PartCollection(unittest.TestCase):
    """소스 규약(`gen_step()` → PARTS → 단일 전역)이 그대로 지켜지는가.

    커널 없이 판정한다 — `is_shape`가 `isinstance(value, bd.Shape)` 하나만 보므로
    가짜 build123d 모듈로 규약을 그대로 재현할 수 있다.
    """

    @staticmethod
    def _harness():
        import types

        from cadlib import kernel  # ty: ignore[unresolved-import]

        class Shape:
            def __init__(self, label="", children=()):
                self.label = label
                self.children = list(children)

        return kernel, types.SimpleNamespace(Shape=Shape), Shape

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
        """이름 없는 조각을 part_0/part_1로 불러봐야 간섭 보고를 읽을 수 없다."""
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


class NoUpstreamResidue(unittest.TestCase):
    """상류 벤더링을 걷어낸 상태가 유지되는가.

    이 스킬은 상류 스킬 라이브러리를 9.7MB 벤더링해서 쓰다가 네이티브로 다시 구현했다.
    되살아나기 쉬운 것은 코드가 아니라 **문자열** 이다 — 문서에 남은 경로 하나가 다음 사람에게
    "그 트리가 아직 있다"고 말한다. 그리고 벤더 트리가 돌아오면 라이선스 의무도 같이 돌아온다.
    """

    def test_no_vendor_tree(self):
        self.assertFalse((_SKILL / "engine" / "vendor").exists(), "벤더 트리가 되살아났다")

    def test_no_license_or_notice_files(self):
        found = [
            path.relative_to(_PLUGIN).as_posix()
            for path in _PLUGIN.rglob("*")
            if path.is_file() and path.name.upper().split(".")[0] in ("LICENSE", "NOTICE", "COPYING", "UPSTREAM")
        ]
        self.assertEqual([], found, f"라이선스/고지 파일이 돌아왔다: {found}")

    def test_no_upstream_path_strings_in_docs_or_code(self):
        residue = []
        for path in _SKILL.rglob("*"):
            if not path.is_file() or path.suffix not in (".md", ".py", ".mjs", ".json"):
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            # `벤더링` 이라는 낱말 자체는 막지 않는다 — cadlib의 설계 이유가 그 역사이고,
            # dfm 문서의 "벤더 데이터시트"는 하드웨어 제조사를 뜻한다. 막는 것은 **경로와 파일명**,
            # 즉 "그 트리가 아직 있다"고 다음 사람에게 말하는 문자열뿐이다.
            for token in ("text-to-cad", "engine/vendor", "vendor/text-to-cad", "cad_build.py", "UPSTREAM.md"):
                if token in body:
                    residue.append(f"{path.relative_to(_SKILL).as_posix()}: {token}")
        self.assertEqual([], residue, "상류/구도구 경로 문자열이 남아 있다:\n" + "\n".join(residue))


class KernelFreeStepReader(unittest.TestCase):
    """커널 없이 STEP에서 사실을 읽는가 — 이 엔진이 상류보다 늘린 몫."""

    @staticmethod
    def _step(**overrides) -> str:
        schema = overrides.get("schema", "AUTOMOTIVE_DESIGN { 1 0 10303 214 -1 1 5 4 }")
        unit = overrides.get("unit", ".MILLI.")
        points = overrides.get("points", [(0, 0, 0), (40, 0, 0), (40, 20, 0), (0, 20, 6)])
        lines = [
            "ISO-10303-21;", "HEADER;", "FILE_DESCRIPTION((''),'2;1');",
            "FILE_NAME('bracket','2026-07-28T00:00:00',(''),(''),'','','');",
            f"FILE_SCHEMA(('{schema}'));", "ENDSEC;", "DATA;",
            "#1=PRODUCT('bracket','bracket','',(#2));",
            f"#3=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT({unit},.METRE.));",
        ]  # fmt: skip
        cursor = 10
        for point in points:
            lines.append(f"#{cursor}=CARTESIAN_POINT('',({point[0]}.,{point[1]}.,{point[2]}.));")
            cursor += 1
        for _ in range(overrides.get("faces", 6)):
            lines.append(f"#{cursor}=ADVANCED_FACE('',(),#3,.T.);")
            cursor += 1
        # 버텍스는 실제 좌표에 묶는다 — 버텍스 경계를 재려면 참조가 이어져야 한다.
        for order in range(len(points)):
            lines.append(f"#{cursor}=VERTEX_POINT('',#{10 + order});")
            cursor += 1
        for _ in range(overrides.get("solids", 1)):
            lines.append(f"#{cursor}=MANIFOLD_SOLID_BREP('bracket',#1);")
            cursor += 1
        return "\n".join([*lines, "ENDSEC;", "END-ISO-10303-21;"]) + "\n"

    def _read(self, body: str):
        from cadlib import stepfile  # ty: ignore[unresolved-import]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.step"
            path.write_text(body, encoding="utf-8")
            return stepfile.read(path)

    def test_reads_schema_units_and_census(self):
        facts = self._read(self._step())
        self.assertEqual("AP214", facts.schema_family)
        self.assertEqual("millimetre", facts.length_unit)
        self.assertEqual(1.0, facts.length_scale_mm)
        self.assertEqual(1, facts.solids)
        self.assertEqual(6, facts.faces)
        self.assertEqual(["bracket"], facts.products)

    def test_the_coordinate_hull_never_reaches_the_reported_size(self):
        """실측 사고: 구멍 하나 뚫린 40×20×9.3 조립체의 z 상한이 45.12로 나왔다.

        범인은 원통면 축 배치(AXIS2_PLACEMENT_3D)가 쓰는 좌표였다 — 자유곡면 유무와 무관하고,
        "곡면이 없으면 헐이 정확하다"는 전제 자체가 틀렸다. 헐은 이제 상한으로만 쓰고, 보고 치수는
        형상 위의 점(VERTEX_POINT)에서 나온다.
        """
        body = self._step().replace(
            "ENDSEC;\nEND-ISO",
            "#900=CARTESIAN_POINT('',(20.,10.,45.12));\n#901=AXIS2_PLACEMENT_3D('',#900,#3,#3);\nENDSEC;\nEND-ISO",
        )
        facts = self._read(body)
        self.assertEqual(45.12, facts.hull_max[2], "헐이 배치 좌표를 포함해야 상한 노릇을 한다")
        size, note = facts.best_size_mm()
        self.assertEqual(6.0, size[2], "보고 치수가 배치 좌표에 오염됐다")
        self.assertIn("실제 bbox와 같다", note, "곡면이 없으면 버텍스 경계가 곧 실제 bbox다")

    def test_a_curved_solid_reports_its_bound_as_a_lower_one(self):
        """버텍스는 형상 위에 있으므로 곡면 실루엣은 그 밖으로 나간다 — 하한이라고 적는다."""
        body = self._step().replace("ENDSEC;\nEND-ISO", "#910=CIRCLE('',#3,2.5);\nENDSEC;\nEND-ISO")
        _, note = self._read(body).best_size_mm()
        self.assertIn("하한", note)

    def test_unknown_units_are_not_silently_assumed_to_be_millimetres(self):
        """모르는 배율을 1로 놓는 것이 스케일 사고의 출발이다."""
        facts = self._read(self._step().replace("#3=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));", ""))
        self.assertIsNone(facts.length_scale_mm)
        self.assertIsNone(facts.hull_size_mm())
        self.assertTrue(any("단위" in problem for problem in facts.problems))

    def test_metre_units_scale_instead_of_being_reported_raw(self):
        facts = self._read(self._step(unit="$"))
        self.assertEqual(1000.0, facts.length_scale_mm)
        self.assertEqual((40000.0, 20000.0, 6000.0), facts.hull_size_mm())

    def test_a_mesh_renamed_as_step_is_rejected_by_content(self):
        facts = self._read("solid exported\nfacet normal 0 0 1\nendsolid\n")
        self.assertTrue(any("ISO-10303-21" in problem for problem in facts.problems))
        self.assertEqual(0, facts.solids)

    def test_part_names_with_parentheses_do_not_break_the_parser(self):
        """STEP 문자열 안에는 괄호·쉼표가 얼마든지 들어온다. 걷어내지 않으면 이름이 구조로 읽힌다."""
        body = self._step().replace("PRODUCT('bracket'", "PRODUCT('bracket (rev B), left'")
        self.assertEqual(["bracket (rev B), left"], self._read(body).products)


class TopologyArtifact(unittest.TestCase):
    """위상 산출물을 파이썬이 쓰고 노드 게이트가 읽는가 — 두 언어가 한 파일을 공유한다."""

    def _write(self, root: Path, *, stale: bool = False):
        from cadlib import stepfile, topology  # ty: ignore[unresolved-import]

        step = root / "part.step"
        step.write_text(_STEP_HEAD, encoding="utf-8")
        digest = stepfile.sha256_file(step)
        index = {
            "version": "3.0.0",
            "stepHash": "0" * 64 if stale else digest,
            "faces": [
                {"id": "f1", "shape": "s1", "type": "PLANE", "area": 800.0, "center": [20, 10, 0], "normal": [0, 0, -1]},
                {"id": "f2", "shape": "s1", "type": "PLANE", "area": 800.0, "center": [20, 10, 6], "normal": [0, 0, 1]},
            ],
            "edges": [], "vertices": [], "shapes": [], "occurrences": [],
        }  # fmt: skip
        topology.write(step, index, positions=[0.0, 0, 0, 1, 0, 0, 0, 1, 0], indices=[0, 1, 2])
        return step

    def test_python_writes_a_glb_that_the_node_gate_accepts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root)
            (root / "iso.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            result = _gate(root)
            self.assertNotIn("topology-missing", _rules(result))
            self.assertNotIn("topology-stale", _rules(result))
            self.assertNotIn("topology-unreadable", _rules(result))

    def test_the_node_gate_catches_a_stale_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, stale=True)
            (root / "iso.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            self.assertIn("topology-stale", _rules(_gate(root)))

    def test_the_python_verbs_agree_with_the_node_gate_on_staleness(self):
        """두 판정기가 어긋나면 사용자는 둘 중 하나를 믿게 되고, 그때부터 게이트는 소음이다."""
        from cadlib import verbs  # ty: ignore[unresolved-import]

        with tempfile.TemporaryDirectory() as tmp:
            step = self._write(Path(tmp), stale=True)
            report = verbs.measure(str(step), source="#f1", target="#f2", axis="z")
            self.assertEqual("fail", report.verdict)
            self.assertIn("topology-stale", [check.id for check in report.checks])

    def test_measurement_says_how_it_measured(self):
        """같은 숫자도 뜻이 다르다 — 평행 평면 간격과 중심 간 거리를 구분해서 적는다."""
        from cadlib import verbs  # ty: ignore[unresolved-import]

        with tempfile.TemporaryDirectory() as tmp:
            step = self._write(Path(tmp))
            report = verbs.measure(str(step), source="#f1", target="#f2", axis="z")
            self.assertEqual("pass", report.verdict)
            self.assertEqual(6.0, report.facts["거리(mm)"])
            self.assertIn("평행 평면이라 정확하다", report.facts["방법"])

    def test_a_missing_artifact_is_unverified_not_a_pass(self):
        from cadlib import verbs  # ty: ignore[unresolved-import]

        with tempfile.TemporaryDirectory() as tmp:
            step = Path(tmp) / "bare.step"
            step.write_text(_STEP_HEAD, encoding="utf-8")
            report = verbs.measure(str(step), source="#f1", target="#f2", axis="z")
            self.assertEqual("warn", report.verdict)
            self.assertIn("미확인", report.render())


class RobotCrossValidation(unittest.TestCase):
    """SRDF는 URDF 위의 계층이다. 둘을 같이 보지 않으면 '그럴듯한데 틀린' 파일이 통과한다."""

    _URDF = """<robot name="arm">
      <link name="base"><inertial><mass value="2"/><inertia ixx="0.01" iyy="0.01" izz="0.01"/></inertial></link>
      <link name="tool"><inertial><mass value="1"/><inertia ixx="0.01" iyy="0.01" izz="0.01"/></inertial></link>
      <joint name="j1" type="revolute"><parent link="base"/><child link="tool"/>
        <axis xyz="0 0 1"/><limit effort="10" velocity="1" lower="-1.57" upper="1.57"/></joint>
    </robot>"""

    def _check(self, kind, body, *, urdf=None):
        from cadlib import robot  # ty: ignore[unresolved-import]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"model.{kind}"
            path.write_text(body, encoding="utf-8")
            urdf_path = None
            if urdf is not None:
                urdf_path = Path(tmp) / "robot.urdf"
                urdf_path.write_text(urdf, encoding="utf-8")
            return robot.validate(kind, path, urdf=urdf_path)

    def _ids(self, report, level=None):
        return {c.id for c in report.checks if level is None or c.level == level}

    def test_a_sound_urdf_passes(self):
        report = self._check("urdf", self._URDF)
        self.assertEqual("pass", report.verdict, report.render())

    def test_element_with_no_children_is_not_treated_as_absent(self):
        """ElementTree의 Element는 자식이 없으면 falsy 다. `find() or 기본값`은 실재하는
        <parent link="..."/> 를 삼키고, 그러면 멀쩡한 URDF가 통째로 FAIL이 된다. 실제로 겪었다."""
        report = self._check("urdf", self._URDF)
        self.assertNotIn("urdf-joint-link", self._ids(report))
        self.assertNotIn("urdf-forest", self._ids(report))

    def test_impossible_inertia_is_blocked(self):
        body = self._URDF.replace(
            'ixx="0.01" iyy="0.01" izz="0.01"/></inertial></link>\n      <link name="tool">',
            'ixx="1" iyy="1" izz="9"/></inertial></link>\n      <link name="tool">',
        )
        self.assertIn("urdf-inertia", self._ids(self._check("urdf", body), "fail"))

    def test_zero_mass_is_blocked(self):
        self.assertIn("urdf-mass", self._ids(self._check("urdf", self._URDF.replace('value="2"', 'value="0"')), "fail"))

    def test_missing_limit_on_a_revolute_joint_is_blocked(self):
        body = self._URDF.replace('<limit effort="10" velocity="1" lower="-1.57" upper="1.57"/>', "")
        self.assertIn("urdf-limit", self._ids(self._check("urdf", body), "fail"))

    def test_srdf_group_pointing_at_a_missing_link_is_blocked(self):
        body = '<robot name="arm"><group name="m"><chain base_link="base" tip_link="ghost"/></group></robot>'
        self.assertIn("srdf-chain", self._ids(self._check("srdf", body, urdf=self._URDF), "fail"))

    def test_degrees_smuggled_into_a_radian_field_are_blocked(self):
        body = (
            '<robot name="arm"><group name="m"><chain base_link="base" tip_link="tool"/></group>'
            '<group_state name="home" group="m"><joint name="j1" value="90"/></group_state></robot>'
        )
        self.assertIn("srdf-degrees", self._ids(self._check("srdf", body, urdf=self._URDF), "fail"))

    def test_a_group_state_outside_the_urdf_limits_is_blocked(self):
        body = (
            '<robot name="arm"><group name="m"><chain base_link="base" tip_link="tool"/></group>'
            '<group_state name="home" group="m"><joint name="j1" value="3.0"/></group_state></robot>'
        )
        self.assertIn("srdf-state-limit", self._ids(self._check("srdf", body, urdf=self._URDF), "fail"))

    def test_srdf_without_a_urdf_reports_unverified_rather_than_passing(self):
        body = '<robot name="arm"><group name="m"><chain base_link="ghost" tip_link="ghost"/></group></robot>'
        report = self._check("srdf", body)
        self.assertEqual("warn", report.verdict)
        self.assertIn("srdf-cross", self._ids(report, "warn"))

    def test_structure_smuggled_into_srdf_is_blocked(self):
        body = '<robot name="arm"><link name="base"/><group name="m"><link name="base"/></group></robot>'
        self.assertIn("srdf-scope", self._ids(self._check("srdf", body, urdf=self._URDF), "fail"))


class GcodeStaticValidation(unittest.TestCase):
    """프린터로 넘기기 전에 정적으로 막는가. 실물 장비가 움직이는 마지막 칸이다."""

    _PROFILE = {"backend": "prusaslicer", "native_config": "/abs/p.ini",
                "machine": {"bed_x": 250, "bed_y": 210, "max_z": 210}}  # fmt: skip
    _GOOD = "M104 S210\nM140 S60\nG21\nG90\nG28\nG1 X10 Y10 Z0.2 E0.5\nG1 X240 Y200 Z50 E12.5\n"

    def _validate(self, gcode, profile=None):
        from cadlib import slicing  # ty: ignore[unresolved-import]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.gcode"
            path.write_text(gcode, encoding="utf-8")
            profile_path = Path(tmp) / "p.json"
            profile_path.write_text(json.dumps(profile or self._PROFILE), encoding="utf-8")
            loaded, error = slicing.load_profile(profile_path)
            self.assertIsNotNone(loaded, error)
            return slicing.validate(path, loaded)

    def _ids(self, report, level):
        return {c.id for c in report.checks if c.level == level}

    def test_a_sound_gcode_passes(self):
        self.assertEqual("pass", self._validate(self._GOOD).verdict)

    def test_motion_outside_the_bed_is_blocked(self):
        self.assertIn("bed-bounds", self._ids(self._validate(self._GOOD + "G1 X400 Y10 Z5 E13\n"), "fail"))

    def test_motion_above_the_machine_z_limit_is_blocked(self):
        self.assertIn("z-bounds", self._ids(self._validate(self._GOOD + "G1 X10 Y10 Z300 E13\n"), "fail"))

    def test_a_cold_nozzle_is_blocked(self):
        cold = "\n".join(line for line in self._GOOD.splitlines() if not line.startswith(("M104", "M140")))
        self.assertIn("gcode-no-heat", self._ids(self._validate(cold + "\n"), "fail"))

    def test_a_foreign_dialect_is_reported_as_unverified(self):
        """모르는 명령을 통과로 세면 다른 기종용 G-code가 조용히 나간다."""
        self.assertIn("gcode-unknown", self._ids(self._validate(self._GOOD + "Q42 fancy\n"), "warn"))

    def test_relative_moves_are_accumulated_not_read_as_absolute(self):
        """G91 뒤의 좌표는 증분이다. 절대값으로 읽으면 베드 밖 이동을 놓친다."""
        report = self._validate("M104 S210\nG90\nG1 X200 Y10 Z1 E1\nG91\nG1 X100 Y0 Z0 E1\n")
        self.assertIn("bed-bounds", self._ids(report, "fail"))

    def test_a_profile_is_mandatory(self):
        from cadlib import slicing  # ty: ignore[unresolved-import]

        loaded, error = slicing.load_profile(Path("/nonexistent/profile.json"))
        self.assertIsNone(loaded)
        self.assertTrue(error)


class DxfAudit(unittest.TestCase):
    """DXF는 평문 그룹코드다. 검사에 라이브러리가 필요 없고, 필요 없어야 실제로 검사한다."""

    @staticmethod
    def _dxf(*, units="4", closed=True, layers=("cut", "bend")) -> str:
        head = ["0", "SECTION", "2", "HEADER"]
        if units is not None:
            head += ["9", "$INSUNITS", "70", units]
        head += ["9", "$EXTMIN", "10", "0.0", "20", "0.0", "30", "0.0"]
        head += ["9", "$EXTMAX", "10", "80.0", "20", "50.0", "30", "0.0"]
        head += ["0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
        for layer in layers:
            head += ["0", "LWPOLYLINE", "8", layer, "70", "1" if closed else "0"]
        head += ["0", "ENDSEC", "0", "EOF"]
        return "\n".join(head) + "\n"

    def _inspect(self, body):
        from cadlib import drawing  # ty: ignore[unresolved-import]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cut.dxf"
            path.write_text(body, encoding="utf-8")
            return drawing.inspect(path)

    def _ids(self, report, level):
        return {c.id for c in report.checks if c.level == level}

    def test_a_sound_drawing_passes(self):
        report = self._inspect(self._dxf())
        self.assertEqual("pass", report.verdict, report.render())
        self.assertIn("80", str(report.facts["도면 범위(mm)"]))

    def test_missing_units_are_blocked(self):
        self.assertIn("dxf-units", self._ids(self._inspect(self._dxf(units=None)), "fail"))

    def test_inch_units_are_accepted_and_scaled(self):
        report = self._inspect(self._dxf(units="1"))
        self.assertNotIn("dxf-units", self._ids(report, "fail"))
        self.assertIn("2032", str(report.facts["도면 범위(mm)"]))  # 80 inch → 2032 mm

    def test_open_contours_are_reported_as_unverified(self):
        self.assertIn("dxf-open-contour", self._ids(self._inspect(self._dxf(closed=False)), "warn"))

    def test_a_single_layer_drawing_is_flagged(self):
        self.assertIn("dxf-single-layer", self._ids(self._inspect(self._dxf(layers=("cut",))), "warn"))

    def test_binary_dxf_is_unjudged_rather_than_failed(self):
        from cadlib import drawing  # ty: ignore[unresolved-import]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.dxf"
            path.write_bytes(b"AutoCAD Binary DXF\r\n\x1a\x00" + b"\x00" * 64)
            report = drawing.inspect(path)
            self.assertEqual("warn", report.verdict)
            self.assertIn("dxf-binary", {c.id for c in report.checks})


class ReportDiscipline(unittest.TestCase):
    """'못 잰 것'이 '통과'와 섞이지 않는가 — 이 엔진의 규율이 자료구조에 박혀 있는지 본다."""

    @staticmethod
    def _report_module():
        import importlib  # noqa: PLC0415

        return importlib.import_module("cadlib.report")

    def test_unverified_never_becomes_pass(self):
        Report = self._report_module().Report

        report = Report(tool="t")
        report.ok("a", "쟀다")
        report.unverified("b", "못 쟀다")
        self.assertEqual("warn", report.verdict)
        self.assertEqual(0, report.exit_code, "미확인은 실패가 아니다")
        self.assertIn("미확인 1건", report.render(), "미확인이 보고문에서 사라졌다")

    def test_a_single_failure_dominates(self):
        Report = self._report_module().Report

        report = Report(tool="t")
        for index in range(20):
            report.ok(f"ok{index}", "쟀다")
        report.fail("bad", "틀렸다")
        self.assertEqual("fail", report.verdict)
        self.assertEqual(1, report.exit_code)

    def test_an_unknown_level_cannot_be_constructed(self):
        Check = self._report_module().Check

        with self.assertRaises(ValueError):
            Check(id="x", level="probably-fine", message="")


class NativeRenderStack(unittest.TestCase):
    """벤더 번들을 대체한 렌더 경로가 실제로 산출물을 내는가 (node, 무의존)."""

    def _node(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["node", str(_SCRIPTS / script), *args], capture_output=True, text=True, timeout=180)

    def test_snapshot_draws_feature_edges_and_an_orbit_gif(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "cube.implicit.mjs"
            model.write_text(
                "export default { schema:'implicit/1.0', name:'cube',"
                " bounds:{min:[-12,-12,-12],max:[12,12,12]}, resolution:24,"
                " sdf(x,y,z){const d=[Math.abs(x)-8,Math.abs(y)-8,Math.abs(z)-8];"
                " return Math.hypot(...d.map(v=>Math.max(v,0)))+Math.min(Math.max(...d),0);} };",
                encoding="utf-8",
            )
            built = self._node("implicit.mjs", str(model), "--out", tmp, "--json")
            self.assertEqual(0, built.returncode, built.stderr)
            payload = json.loads(built.stdout)
            self.assertTrue(payload["watertight"], "서피스 넷 출력이 수밀이 아니다")
            self.assertGreater(payload["triangles"], 0)

            stl = payload["outputs"][0]
            shot = self._node("snapshot.mjs", stl, "--out", str(Path(tmp) / "shots"), "--orbit", "6", "--json")
            self.assertEqual(0, shot.returncode, shot.stderr)
            shots = json.loads(shot.stdout)
            self.assertGreater(shots["featureEdges"], 0, "특징 에지가 하나도 안 나왔다 — 라인워크가 죽었다")
            gif = Path(shots["orbit"]).read_bytes()
            self.assertTrue(gif.startswith(b"GIF89a"), "GIF 머리표가 아니다")
            self.assertEqual(0x3B, gif[-1], "GIF 트레일러가 없다")

    def test_snapshot_refuses_a_step_without_its_topology_artifact(self):
        """그릴 것이 없는데 빈 이미지를 내면 '봤다'가 거짓이 된다."""
        with tempfile.TemporaryDirectory() as tmp:
            step = Path(tmp) / "bare.step"
            step.write_text(_STEP_HEAD, encoding="utf-8")
            result = self._node("snapshot.mjs", str(step))
            self.assertEqual(3, result.returncode)
            self.assertIn("위상 산출물이 없다", result.stderr)

    def test_the_viewer_confines_itself_to_its_root(self):
        body = (_SCRIPTS / "view.mjs").read_text(encoding="utf-8")
        self.assertIn("safeJoin", body)
        self.assertIn("디렉터리 밖 경로", body)

    def test_the_viewer_ships_no_bundled_3d_library(self):
        """뷰어가 다시 무거워지는 것을 막는다 — 서버가 그리는 설계가 이 스킬 크기의 근거다."""
        heavy = [
            path.relative_to(_SKILL).as_posix()
            for path in _SKILL.rglob("*")
            if path.is_file() and path.stat().st_size > 512 * 1024 and path.suffix in (".js", ".mjs", ".html", ".css")
        ]
        self.assertEqual([], heavy, f"번들이 되살아났다: {heavy}")


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
            # 위상 산출물이 있어야 STEP이 검증 가능한 상태다.
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

        메시 경로(mesh_audit + 렌더)로 검증한 STEP은 셀렉터 측정을 못 할 뿐 정당한
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
