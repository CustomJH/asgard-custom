"""Freyja clean-rebuild baseline."""

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from asgard import skill_registry
from asgard.templates.freyja import FREYJA_SKILLS, freyja_core_skill, resolve_freyja_skills
from asgard.templates.roles import ROLE_AGENTS, delivery_agents


class TestFreyjaBaseline(unittest.TestCase):
    def test_only_initial_freyja_role_is_active(self):
        roles = dict(ROLE_AGENTS)
        self.assertIn("asgard-freyja.md", roles)
        self.assertNotIn("asgard-freyja-lead.md", roles)
        self.assertEqual(delivery_agents()["freyja"], "standard")
        self.assertNotIn("freyja-lead", delivery_agents())

    def test_core_contract_is_the_only_builtin_freyja_skill(self):
        self.assertEqual(FREYJA_SKILLS, [])
        self.assertEqual(resolve_freyja_skills("랜딩 페이지"), [])
        core = freyja_core_skill()
        self.assertIn("name: asgard-freyja", core)
        self.assertIn("Default behavior — Freyja Design", core)
        self.assertIn("asgard-freyja-design", core)
        self.assertIn("establish the visual system and feel first", core)
        self.assertIn("strip only the elements with no meaning", core)
        self.assertIn("default to an atomic design system", core)
        self.assertIn("components/atoms|molecules|organisms", core)

    def test_design_engine_carries_atomic_structure_canon(self):
        with tempfile.TemporaryDirectory() as root:
            bodies = dict(skill_registry.client_skill_bodies("freyja", root))
        body = bodies["asgard-freyja-design"]
        self.assertIn("Atomic design project structure", body)
        self.assertIn("components/atoms|molecules|organisms", body)
        self.assertIn("Atomic: <level>", body)
        self.assertIn("lower levels never import higher levels", body)

    def test_complete_freyja_design_engine_is_freyja_only(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                [name for name, _ in skill_registry.client_skill_bodies("freyja", root)],
                [
                    "asgard-freyja-3d",
                    "asgard-freyja-design",
                    "asgard-freyja-fjadrhamr",
                    "asgard-freyja2",
                    "asgard-freyja4",
                    # 프레임워크 불문 모듈 설계 규율 — 컴포넌트 경계도 같은 문법이라 의도적으로 공유.
                    # 프레이야 전용 엔진이 다른 표면으로 새지 않는다는 불변식은 아래 assertNotIn 이 진다.
                    "codebase-design",
                ],
            )
            self.assertNotIn(
                "asgard-freyja-design",
                {name for name, _ in skill_registry.client_skill_bodies("worker", root)},
            )
            self.assertIn(
                "asgard-freyja-design",
                {name for name, _ in skill_registry.resolve_skills(root, "랜딩 페이지 디자인", "freyja")},
            )

    def test_complete_upstream_snapshot_and_restraint_gate_are_byte_locked(self):
        plugin = skill_registry.bundled_plugins()["freyja-design"]
        skill_root = Path(plugin["root"], "skills", "asgard-freyja-design")
        upstream_root = skill_root / "references" / "vanadis"
        files = [item for item in upstream_root.rglob("*") if item.is_file()]
        digest = hashlib.sha256()
        for item in sorted(files, key=lambda value: value.relative_to(upstream_root).as_posix()):
            relative = item.relative_to(upstream_root).as_posix().encode()
            digest.update(relative + b"\0" + item.read_bytes())

        # 봉인 갱신 이력. 파일 수는 불변이고 내용만 바뀌었을 때만 다시 찍는다 —
        # 개수가 함께 움직였다면 그건 재봉인이 아니라 스냅샷 오염이다.
        #   d3e8445… → 09f68722…  산출물 루트 이관(.vanadis/ → .asgard/.vanadis/engine1/):
        #   skills·agents 20파일의 경로 지시 + vanadis-harness 의 .gitignore 자가 설치 제거.
        #   09f68722… → 09389c99…  같은 이관의 누락분 봉합: .claude/skills·.claude/agents·
        #   .codex/agents 미러 26파일, 실제로 경로를 만드는 .claude/hooks·scripts 코드 7파일,
        #   AGENTS.md·web 문서. 첫 회차가 skills/·agents/ 만 훑어 미러를 통째로 빠뜨렸다.
        #   09389c99… → 181cbf44…  독립 재검이 잡은 마지막 잔재: vanadis-sync 심 템플릿
        #   (본체+.claude 미러) 4줄이 은퇴 루트 ./.vanadis/preferences.md 를 안내하고 있었다.
        self.assertEqual(len(files), 3238)
        self.assertEqual(digest.hexdigest(), "181cbf44714bfc5475e630a25ad125034b2c7ad6a4929cd41fe4b8dd7f7c5b8b")
        self.assertEqual(len(list((upstream_root / "skills").glob("*/SKILL.md"))), 21)
        self.assertEqual(len(list((upstream_root / "agents").glob("vanadis-*.md"))), 18)
        restraint = skill_registry.show_skill_resource(
            "",
            "asgard-freyja-design",
            "references/vanadis-restraint/SKILL.md",
        )
        self.assertEqual(
            hashlib.sha256(restraint.encode()).hexdigest(),
            "9bbcbb2a23555b0184dff3ae10ec652da06a7746d35582785959f2a2883e935f",
        )

    def test_design_runtime_reads_references_and_extracts_binary_assets(self):
        plugin = skill_registry.bundled_plugins()["freyja-design"]
        self.assertEqual(plugin["entrypoints"], {"asgard-freyja-design": "freyja_design.py"})
        runner = Path(plugin["root"], "skills", "asgard-freyja-design", "freyja_design.py")

        listed = subprocess.run(
            [sys.executable, str(runner), "reference", "list", "toss"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("toss", listed.stdout.splitlines())

        shown = subprocess.run(
            [sys.executable, str(runner), "reference", "show", "toss"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("Toss", shown.stdout)

        with tempfile.TemporaryDirectory() as destination:
            output = Path(destination, "logo-bg.png")
            extracted = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "extract",
                    ".github/assets/logo-bg.png",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            self.assertTrue(output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
