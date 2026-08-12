"""Sjónhverfing — 평면 위 깊이(의사 3D) 기법 계층.

이 스킬의 값어치는 두 곳에 있고, 테스트도 그 둘을 고정한다.

① **깊이가 죽었는지 소스에서 판정한다.** 그래서 문서 문자열이 아니라 실제 CSS/HTML/JS를
   게이트에 물려 판정이 맞는지 본다. 특히 오탐 앵커를 규칙마다 둔다 — 판정기가 짖기만 하면
   사람은 곧 게이트를 끈다.
② **엔진의 독립을 깨지 않는다.** 기법 계층이 엔진을 참조하거나 엔진이 기법 계층을 참조하면
   그것은 계층이 아니라 결합이다. 파일 수준에서 양방향으로 확인한다.

조합 검증은 실물로 한다. 표본을 엔진 2·3·4의 **각자의 런타임**에 물려, 깊이 기법이
남의 게이트를 건드리지 않는다는 것을 판정으로 보인다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from asgard import skill_registry

_NODE = shutil.which("node")
# 번들 뿌리는 skill_registry 가 이미 계산해 둔 것을 쓴다. `skill_registry.__file__` 의 부모로
# 재면 그 모듈이 패키지가 되는 순간 한 단 깊어져 없는 경로를 가리킨다.
_PLUGINS = skill_registry._BUNDLED_PLUGINS_DIR
_PLUGIN = _PLUGINS / "freyja-sjonhverfing"
_SKILL = _PLUGIN / "skills" / "asgard-freyja-sjonhverfing"
_GATE = _SKILL / "engine" / "scripts" / "depth_gate.mjs"
_SPECIMEN = _SKILL / "references" / "specimen" / "tilt-card.html"
_HANDOFF = _SKILL / "references" / "specimen" / "handoff-three.js"

_ENGINE2_DETECT = _PLUGINS / "freyja2" / "skills" / "asgard-freyja2" / "engine" / "scripts" / "detect.mjs"
_ENGINE3_DETECT = _PLUGINS / "freyja-3d" / "skills" / "asgard-freyja-3d" / "engine" / "scripts" / "detect3d.mjs"
_ENGINE4_GATE = _PLUGINS / "freyja4" / "skills" / "asgard-freyja4" / "engine" / "scripts" / "slop_gate.mjs"

# 원근·저감 경로가 갖춰진 최소 공간. 규칙 하나만 떼어 시험할 때 나머지 게이트가
# 함께 울리지 않도록 이것을 바탕으로 깐다.
_SOUND = """
.stage { perspective: 900px; }
.card { transform: rotateY(9deg); transition: transform 200ms; }
@media (prefers-reduced-motion: reduce) { .card { transform: none } }
"""


def _run(script: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [str(_NODE), str(script), *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _gate(target: Path, *args: str) -> tuple[dict, int]:
    proc = _run(_GATE, str(target), "--json", *args)
    if not proc.stdout.strip():
        raise AssertionError(f"depth_gate produced no output: {proc.stderr}")
    return json.loads(proc.stdout), proc.returncode


def _by_id(payload: dict, gate_id: str) -> dict:
    for gate in payload["gates"]:
        if gate["id"] == gate_id:
            return gate
    raise AssertionError(f"gate {gate_id} not reported")


def _judge(source: str, name: str = "case.css") -> dict:
    """임시 파일 하나를 게이트에 물리고 판정을 돌려준다."""
    with tempfile.TemporaryDirectory() as raw:
        target = Path(raw) / name
        target.write_text(source, encoding="utf-8")
        payload, _ = _gate(target)
        return payload


class SjonhverfingContract(unittest.TestCase):
    def test_plugin_is_discovered_and_routed_to_freyja(self) -> None:
        plugin = skill_registry.bundled_plugins().get("freyja-sjonhverfing")
        self.assertIsNotNone(plugin, "플러그인이 번들 목록에 없다")
        assert plugin is not None
        self.assertEqual(plugin["skills"], ["asgard-freyja-sjonhverfing"])
        route = plugin["routing"]["asgard-freyja-sjonhverfing"]
        self.assertEqual(route["defaults"], ["freyja"])
        self.assertEqual(route["agents"], ["freyja"])
        self.assertTrue(route["implicit"], "모델 발견 대상이어야 한다")

    def test_skill_reaches_the_catalog(self) -> None:
        rows = {row["name"]: row for row in skill_registry.skills(".")}
        row = rows.get("asgard-freyja-sjonhverfing")
        self.assertIsNotNone(row, "스킬이 카탈로그에 없다")
        assert row is not None
        self.assertEqual(row["plugin"], "freyja-sjonhverfing")
        self.assertEqual(row["invocation"], "model")

    def test_depth_task_routes_here_without_stealing_the_3d_engine(self) -> None:
        depth = [name for name, _ in skill_registry.resolve_skills(".", "카드 틸트를 anime.js 로", "freyja")]
        self.assertIn("asgard-freyja-sjonhverfing", depth)
        # 조형 요청은 엔진 3의 것이다. 트리거가 겹쳐 형상 작업을 가로채면 안 된다.
        shape = [name for name, _ in skill_registry.resolve_skills(".", "3d 프린팅용 외함 설계", "freyja")]
        self.assertIn("asgard-freyja-3d", shape)
        self.assertNotIn("asgard-freyja-sjonhverfing", shape)

    def test_every_document_the_skill_names_exists(self) -> None:
        text = (_SKILL / "SKILL.md").read_text(encoding="utf-8")
        named = {
            "engine/reference/depth-ladder.md",
            "engine/reference/css-3d.md",
            "engine/reference/animejs.md",
            "engine/reference/recipes.md",
            "engine/reference/compose.md",
            "engine/reference/verify.md",
            "engine/scripts/depth_gate.mjs",
        }
        for relative in named:
            self.assertIn(relative, text, f"SKILL.md 가 {relative} 를 가리키지 않는다")
            self.assertTrue((_SKILL / relative).is_file(), f"파일이 없다: {relative}")


class EngineIndependence(unittest.TestCase):
    """기법 계층은 엔진을 참조하지 않고, 엔진도 기법 계층을 모른다."""

    def test_no_engine_knows_about_this_skill(self) -> None:
        for engine in ("freyja-design", "freyja2", "freyja-3d", "freyja4", "freyja-fjadrhamr"):
            root = _PLUGINS / engine
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() in {".png", ".glb", ".stl", ".step"}:
                    continue
                try:
                    body = path.read_text(encoding="utf-8")
                except UnicodeDecodeError, OSError:
                    continue
                self.assertNotIn(
                    "sjonhverfing",
                    body.lower(),
                    f"{engine} 가 기법 계층을 참조한다 — 독립이 깨졌다: {path}",
                )

    def test_this_skill_executes_nothing_from_another_engine(self) -> None:
        for path in _SKILL.rglob("*"):
            if not path.is_file() or path.suffix not in {".mjs", ".js", ".json"}:
                continue
            body = path.read_text(encoding="utf-8")
            for engine in ("freyja2", "freyja4", "freyja-3d", "freyja-design"):
                self.assertNotIn(
                    f"skill_plugins/{engine}",
                    body,
                    f"{path.name} 이 다른 엔진의 경로를 들고 있다",
                )
            self.assertNotIn("../../../", body, f"{path.name} 이 스킬 밖으로 올라간다")

    def test_the_gate_runtime_has_no_dependency(self) -> None:
        body = _GATE.read_text(encoding="utf-8")
        imports = [line for line in body.splitlines() if line.startswith("import ")]
        self.assertTrue(imports, "임포트를 찾지 못했다")
        for line in imports:
            self.assertIn("node:", line, f"내장 모듈이 아닌 의존성: {line}")

    def test_composition_contract_names_every_engine(self) -> None:
        compose = (_SKILL / "engine" / "reference" / "compose.md").read_text(encoding="utf-8")
        for skill in ("asgard-freyja-design", "asgard-freyja2", "asgard-freyja-3d", "asgard-freyja4"):
            self.assertIn(skill, compose, f"조합 계약에 {skill} 이 없다")
        # 우선순위가 뒤집히면 기법 계층이 엔진을 이기게 된다.
        self.assertIn("충돌하면 이 스킬이 진다", compose)


@unittest.skipIf(_NODE is None, "node 없음")
class DepthGateRuntime(unittest.TestCase):
    def test_specimen_passes_every_judged_gate(self) -> None:
        payload, code = _gate(_SPECIMEN)
        self.assertEqual(code, 0, json.dumps(payload["gates"], ensure_ascii=False)[:800])
        self.assertEqual(payload["verdict"], "pass")
        self.assertEqual(payload["summary"]["fail"], 0)
        self.assertEqual(payload["summary"]["warn"], 0)
        self.assertGreater(payload["summary"]["pass"], 0, "판정된 게이트가 하나도 없다")

    def test_unjudged_gates_are_never_counted_as_passes(self) -> None:
        payload, _ = _gate(_SPECIMEN)
        self.assertEqual(payload["summary"]["unjudged"], 5)
        statuses = {gate["status"] for gate in payload["gates"]}
        self.assertNotIn("manual", statuses, "미판정 항목이 게이트 목록에 섞였다")
        judged = payload["summary"]["pass"] + payload["summary"]["fail"] + payload["summary"]["warn"]
        self.assertEqual(judged + payload["summary"]["notApplicable"], len(payload["gates"]))

    # ── FAIL 규칙 넷 ────────────────────────────────────────────────
    def test_d1_catches_depth_with_no_perspective(self) -> None:
        payload = _judge(
            ".c { transform: rotateY(12deg); transition: transform 200ms }\n"
            "@media (prefers-reduced-motion: reduce) { .c { transform: none } }"
        )
        self.assertEqual(_by_id(payload, "D1")["status"], "fail")

    def test_d2_catches_a_rule_that_flattens_its_own_3d_context(self) -> None:
        payload = _judge(_SOUND + ".card { transform-style: preserve-3d; overflow: hidden }")
        gate = _by_id(payload, "D2")
        self.assertEqual(gate["status"], "fail")
        self.assertIn("overflow", gate["hits"][0]["evidence"])

    def test_d3_catches_depth_motion_with_no_reduced_path(self) -> None:
        payload = _judge(".stage { perspective: 900px } .c { transform: rotateX(10deg); transition: transform 200ms }")
        self.assertEqual(_by_id(payload, "D3")["status"], "fail")

    def test_d4_catches_the_v3_api_under_a_v4_import(self) -> None:
        payload = _judge(
            'import { animate } from "animejs";\nconst tl = anime.timeline({ easing: "easeOutQuad" });\n',
            name="motion.js",
        )
        self.assertEqual(_by_id(payload, "D4")["status"], "fail")

    # ── WARN 규칙 여섯 ──────────────────────────────────────────────
    def test_d5_warns_when_a_flipped_face_shows_its_back(self) -> None:
        payload = _judge(_SOUND + ".card { transform-style: preserve-3d } .back { transform: rotateY(180deg) }")
        self.assertEqual(_by_id(payload, "D5")["status"], "warn")

    def test_d6_warns_when_pointer_events_write_transform_directly(self) -> None:
        payload = _judge(
            'document.addEventListener("mousemove", (e) => {\n'
            "  card.style.transform = `perspective(900px) rotateY(${e.clientX}deg)`;\n});\n",
            name="tilt.js",
        )
        self.assertEqual(_by_id(payload, "D6")["status"], "warn")

    def test_d7_warns_on_a_fisheye_perspective(self) -> None:
        payload = _judge(_SOUND.replace("900px", "320px"))
        self.assertEqual(_by_id(payload, "D7")["status"], "warn")

    def test_d8_warns_on_page_wide_will_change(self) -> None:
        payload = _judge("* { will-change: transform }" + _SOUND)
        self.assertEqual(_by_id(payload, "D8")["status"], "warn")

    def test_d9_warns_on_an_unstoppable_3d_loop(self) -> None:
        payload = _judge(
            'import { animate } from "animejs";\nanimate(".coin", { rotateY: 360, loop: true, perspective: 900 });\n',
            name="spin.js",
        )
        self.assertEqual(_by_id(payload, "D9")["status"], "warn")

    def test_d10_warns_on_v3_only_code(self) -> None:
        payload = _judge('const tl = anime.timeline({ easing: "easeOutQuad" });\n', name="legacy.js")
        self.assertEqual(_by_id(payload, "D10")["status"], "warn")

    # ── 오탐 앵커 ───────────────────────────────────────────────────
    def test_layer_promotion_idiom_is_not_depth(self) -> None:
        """translateZ(0)은 합성 레이어 관용구다. 이것을 깊이로 세면 모든 페이지가 D1에 걸린다."""
        payload = _judge(".p { transform: translateZ(0) } .q { transform: rotateX(0deg) translate3d(0, 12px, 0) }")
        self.assertEqual(_by_id(payload, "D1")["status"], "n/a")

    def test_a_variable_named_perspective_is_not_a_perspective(self) -> None:
        """`--depth-perspective: 900px`는 선언이 아니라 이름이다. 이름을 선언으로 세면 D1이 조용히 통과한다."""
        payload = _judge(
            ":root { --depth-perspective: 900px }\n"
            ".c { transform: rotateY(10deg); transition: transform 200ms }\n"
            "@media (prefers-reduced-motion: reduce) { .c { transform: none } }"
        )
        self.assertEqual(_by_id(payload, "D1")["status"], "fail")

    def test_a_perspective_behind_a_token_resolves(self) -> None:
        payload = _judge(
            ":root { --depth: 900px }\n.stage { perspective: var(--depth) }\n"
            ".c { transform: rotateY(9deg); transition: transform 200ms }\n"
            "@media (prefers-reduced-motion: reduce) { .c { transform: none } }"
        )
        self.assertEqual(_by_id(payload, "D1")["status"], "pass")
        self.assertEqual(_by_id(payload, "D7")["status"], "pass", "토큰 뒤의 900px 를 어안으로 오판했다")

    def test_a_flattener_in_another_rule_is_not_a_finding(self) -> None:
        payload = _judge(
            ".scroller { overflow: hidden }\n" + _SOUND + ".card { transform-style: preserve-3d; overflow: visible }"
        )
        self.assertEqual(_by_id(payload, "D2")["status"], "pass")

    def test_reduced_motion_declared_through_animejs_scope_counts(self) -> None:
        payload = _judge(
            'import { animate, createScope } from "animejs";\n'
            'createScope({ mediaQueries: { reduceMotion: "(prefers-reduced-motion: reduce)" } })\n'
            '  .add(() => animate(".c", { rotateY: 10, perspective: 900 }));\n',
            name="scope.js",
        )
        self.assertEqual(_by_id(payload, "D3")["status"], "pass")

    def test_two_dimensional_transforms_are_out_of_scope(self) -> None:
        payload = _judge(".c { transform: rotate(45deg) scale(1.02); transition: transform 200ms }")
        self.assertEqual(_by_id(payload, "D1")["status"], "n/a")
        self.assertEqual(_by_id(payload, "D3")["status"], "n/a")

    def test_a_url_on_the_declaration_line_does_not_blank_the_rule(self) -> None:
        """`url(https://…)`의 `//`를 주석으로 지우면 같은 줄의 perspective가 함께 사라진다."""
        payload = _judge(
            "<style>\n.hero { background: url(https://example.com/a.png) center; perspective: 900px }\n"
            ".c { transform: rotateY(9deg); transition: transform 200ms }\n"
            "@media (prefers-reduced-motion: reduce) { .c { transform: none } }\n</style>",
            name="page.html",
        )
        self.assertEqual(_by_id(payload, "D1")["status"], "pass")

    def test_a_data_uri_does_not_split_the_rule(self) -> None:
        payload = _judge(
            '.icon { background-image: url("data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=") }\n'
            + _SOUND
            + ".card { transform-style: preserve-3d; overflow: visible }"
        )
        self.assertEqual(_by_id(payload, "D2")["status"], "pass")

    def test_scoped_will_change_is_not_a_finding(self) -> None:
        payload = _judge(_SOUND + ".card:hover { will-change: transform }")
        self.assertEqual(_by_id(payload, "D8")["status"], "pass")

    def test_a_three_js_file_is_not_judged_for_a_css_perspective(self) -> None:
        """실시간 3D는 카메라가 원근을 쥔다. CSS perspective를 요구하면 L5 코드가 전부 걸린다."""
        payload, code = _gate(_HANDOFF)
        gate = _by_id(payload, "D1")
        self.assertEqual(gate["status"], "n/a")
        self.assertTrue(any("engine 3" in note for note in gate["notes"]), gate["notes"])
        self.assertEqual(code, 0)

    def test_large_json_survives_a_pipe(self) -> None:
        """`process.exit()`은 파이프의 비동기 stdout 버퍼를 버린다 — 64KB에서 잘린다.

        조용히 잘린 JSON은 빈 결과보다 나쁘다. 판정이 사라진 자리를 통과로 읽게 된다.
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "corpus"
            root.mkdir()
            # 목록 항목은 절대 경로다 — tmpdir 접두사가 짧은 리눅스에서는 같은 개수로도
            # 64KB를 못 넘겨 전제가 무너진다. 고정 개수 대신 경로 길이에서 되짚는다.
            stem = "surface-{:04d}-with-a-long-enough-name.css"
            per_file = len(str(root / stem.format(0))) + 3  # 따옴표 둘 + 쉼표
            count = max(900, 65536 * 3 // (per_file * 2))
            for index in range(count):
                (root / stem.format(index)).write_text(_SOUND, encoding="utf-8")
            payload, code = _gate(root)  # capture_output이 파이프라 조건이 그대로 재현된다
            self.assertEqual(len(payload["files"]), count, "파일 목록이 잘렸다")
            self.assertGreater(len(json.dumps(payload)), 65536, "64KB 를 넘지 않아 시험이 성립하지 않는다")
            self.assertEqual(code, 0)

    # ── 종료 코드 ───────────────────────────────────────────────────
    def test_exit_code_follows_the_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            broken = Path(raw) / "broken.css"
            broken.write_text(".c { transform: rotateY(12deg); transition: transform 200ms }", encoding="utf-8")
            _, code = _gate(broken)
            self.assertEqual(code, 1, "fail 인데 0 을 돌려줬다")

            warned = Path(raw) / "warned.css"
            warned.write_text(_SOUND.replace("900px", "320px"), encoding="utf-8")
            _, warn_code = _gate(warned)
            self.assertEqual(warn_code, 0, "warn 이 기본에서 차단으로 올라갔다")
            _, strict_code = _gate(warned, "--severity", "warn")
            self.assertEqual(strict_code, 1, "--severity warn 이 경고를 올리지 않았다")


@unittest.skipIf(_NODE is None, "node 없음")
class EngineCombination(unittest.TestCase):
    """표본을 각 엔진의 런타임에 물린다. 깊이 기법이 남의 게이트를 건드리면 조합이 아니다."""

    def test_engine2_detector_finds_nothing_in_the_specimen(self) -> None:
        # 먼저 이 검출기가 이 조건에서 실제로 짖는다는 것을 보인다 — 그래야 침묵이 증거가 된다.
        with tempfile.TemporaryDirectory() as raw:
            noisy = Path(raw) / "noisy.html"
            noisy.write_text(
                '<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>대조</title><style>'
                "body{font-family:Inter,sans-serif;font-size:16px;color:#999;background:#fff;padding:40px}"
                "h1{font-size:18px}h2{font-size:17px}p{font-size:15px}"
                ".btn{background:linear-gradient(90deg,#7c3aed,#ec4899);border-radius:9999px;"
                "transition:all .3s ease;padding:12px 24px;color:#fff}"
                "</style></head><body><h1>제목입니다</h1><h2>부제입니다</h2>"
                "<p>본문 문단이 여기에 들어갑니다. 충분한 길이의 문장을 둡니다.</p>"
                '<a class="btn" href="#">시작하기</a></body></html>',
                encoding="utf-8",
            )
            control = _run(_ENGINE2_DETECT, str(noisy), "--json")
            self.assertNotEqual(json.loads(control.stdout), [], "대조군이 조용하다 — 검출기가 돌지 않았다")

        proc = _run(_ENGINE2_DETECT, str(_SPECIMEN), "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout), [], proc.stdout)

    def test_engine3_detector_is_clean_on_the_handoff_specimen(self) -> None:
        proc = _run(_ENGINE3_DETECT, str(_HANDOFF), "--json")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["scannedFiles"], 1, "표본을 읽지 않았다 — 빈 결과는 통과가 아니다")
        self.assertEqual(payload["findings"], [], proc.stdout)
        self.assertEqual(proc.returncode, 0)

    def test_engine4_objects_only_to_its_own_provenance_stamp(self) -> None:
        """마르될은 자기가 배달한 페이지에 자기 도장을 요구한다. 표본은 마르될의 산출물이 아니다.

        그러므로 게이트 20은 **걸리는 것이 맞다** — 기법 계층이 남의 엔진 도장을 위조하지
        않는다는 뜻이다. 중요한 것은 그 하나 말고는 걸리는 것이 없다는 사실이다: 깊이 기법
        자체는 58항 슬롭 테스트의 어느 항목도 건드리지 않는다.
        """
        proc = _run(_ENGINE4_GATE, str(_SPECIMEN), "--json")
        payload = json.loads(proc.stdout)
        failed = [str(gate["id"]) for gate in payload["gates"] if gate["status"] == "fail"]
        self.assertEqual(failed, ["20"], f"기대 밖의 판정: {failed}")
        motion = next(gate for gate in payload["gates"] if str(gate["id"]) == "27")
        self.assertEqual(motion["status"], "pass", "저감 모션 게이트가 깨졌다")

    def test_the_depth_gate_stays_quiet_on_engine4_output(self) -> None:
        """반대 방향. 우리 게이트가 남의 엔진 산출물을 물어뜯으면 조합이 성립하지 않는다."""
        examples = _PLUGINS / "freyja4" / "skills" / "asgard-freyja4" / "references" / "examples"
        payload, code = _gate(examples)
        self.assertEqual(code, 0, json.dumps(payload["summary"], ensure_ascii=False))
        self.assertEqual(payload["summary"]["fail"], 0)
        self.assertEqual(payload["summary"]["warn"], 0)


if __name__ == "__main__":
    unittest.main()
