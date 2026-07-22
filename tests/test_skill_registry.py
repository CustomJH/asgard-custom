#!/usr/bin/env python3
"""Central skill/plugin catalog: one router, thin client adapters, safe resource plugins."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import skill_bank, skill_registry  # noqa: E402


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = os.path.join(self.root, "home")
        skill_bank._cache.clear()

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        skill_bank._cache.clear()
        self.tmp.cleanup()

    def test_builtin_router_and_gate_isolation(self):
        names = [name for name, _ in skill_registry.resolve_skills(self.root, "회귀 버그 테스트", "worker")]
        self.assertEqual(names, ["asgard-worker-debugging", "asgard-worker-testing"])
        self.assertEqual(skill_registry.resolve_skills(self.root, "회귀 버그 테스트", "verifier"), [])
        self.assertIn("worker", {plugin["name"] for plugin in skill_registry.plugins()})

    def test_catalog_prioritizes_matches_without_hiding_other_skills(self):
        matched = {name for name, _ in skill_registry.resolve_skills(self.root, "로그인 폼 접근성 개선", "freyja")}
        catalog = skill_registry.skill_catalog(self.root, "freyja", matched=matched)

        self.assertIn("[task-match] asgard-freyja-syn", catalog)
        self.assertIn("asgard-freyja-motion", catalog)
        self.assertIn("scan the remaining descriptions", catalog)

    def test_common_frontend_words_match_general_ui_skills(self):
        for task, expected in (
            ("기존 버튼 패딩 수정", {"ui-styling", "ui-ux-pro-max"}),
            ("React component spacing", {"ui-styling", "ui-ux-pro-max"}),
            ("CSS margin 조정", {"ui-styling"}),
        ):
            matched = {name for name, _ in skill_registry.resolve_skills(self.root, task, "freyja")}
            self.assertTrue(expected <= matched, task)

    def test_bare_catalog_commands_list_current_inventory(self):
        from typer.testing import CliRunner

        from asgard.cli import app
        from asgard.commands import skills as command

        with mock.patch.object(command.ui, "term_cols", return_value=140):
            skills_result = CliRunner().invoke(app, ["skills"])
            plugins_result = CliRunner().invoke(app, ["plugins"])
            json_result = CliRunner().invoke(app, ["plugins", "list", "--json"])
        self.assertEqual(skills_result.exit_code, 0)
        self.assertIn("╭─ Skills ·", skills_result.stdout)
        self.assertIn("design-md-review", skills_result.stdout)
        self.assertEqual(plugins_result.exit_code, 0)
        self.assertIn("╭─ Plugins ·", plugins_result.stdout)
        self.assertIn("╰", plugins_result.stdout)
        self.assertIn("google-design-md", plugins_result.stdout)
        self.assertEqual(json.loads(json_result.stdout), skill_registry.plugins())

    def test_catalog_renderer_is_readable_without_changing_json(self):
        from asgard.commands import skills as command

        skill_rows = [
            {
                "name": "narrow-check",
                "plugin": "visual-tools",
                "origin": "project",
                "invocation": "user",
                "description": "좁은 터미널에서도 설명을 생략하지 않는다.",
            }
        ]
        plugin_rows = [
            {"name": "empty", "version": "bundled", "origin": "bundled", "skills": [], "description": "none"},
            {"name": "one", "version": "1", "origin": "installed", "skills": ["a"], "description": "single"},
            {
                "name": "many",
                "version": "2",
                "origin": "installed",
                "skills": ["a", "b"],
                "description": "multiple",
            },
        ]
        with (
            mock.patch.object(command.ui, "_COLOR", False),
            mock.patch.object(command.ui, "term_cols", return_value=80),
            mock.patch.object(command, "skills", return_value=skill_rows),
        ):
            from typer.testing import CliRunner

            from asgard.cli import app

            plain = CliRunner().invoke(app, ["skills", "list"])
            json_result = CliRunner().invoke(app, ["skills", "list", "--json"])
        self.assertEqual(plain.exit_code, 0)
        self.assertIn("Skills · 1", plain.stdout)
        self.assertNotIn("\x1b[", plain.stdout)
        self.assertIn("narrow-check", plain.stdout)
        self.assertIn("visual-tools", plain.stdout)
        self.assertIn("project · user", plain.stdout)
        self.assertIn("좁은터미널에서도설명을생략하지않는다.", "".join(plain.stdout.split()))
        self.assertEqual(json.loads(json_result.stdout), skill_rows)

        with (
            mock.patch.object(command.ui, "_COLOR", False),
            mock.patch.object(command.ui, "term_cols", return_value=100),
            mock.patch.object(command, "plugins", return_value=plugin_rows),
        ):
            wide = CliRunner().invoke(app, ["plugins", "list"])
        self.assertEqual(wide.exit_code, 0)
        self.assertIn("Plugins · 3", wide.stdout)
        self.assertIn("╭", wide.stdout)
        self.assertIn("╰", wide.stdout)
        self.assertIn("0 skills", wide.stdout)
        self.assertIn("1 skill", wide.stdout)
        self.assertIn("2 skills", wide.stdout)

    def test_bundled_uiux_resource_is_freyja_assigned_and_runnable(self):
        expected = {
            "banner-design",
            "brand",
            "design",
            "design-system",
            "slides",
            "ui-styling",
            "ui-ux-pro-max",
        }
        plugin = skill_registry.bundled_plugins()["ui-ux-pro-max"]
        self.assertEqual(set(plugin["skills"]), expected)
        self.assertEqual(plugin["revision"], "5c0946f66120079258e1efc8e436d78ec793877c")
        catalog = {row["name"]: row for row in skill_registry.skills(self.root)}
        self.assertEqual(catalog["ui-ux-pro-max"]["plugin"], "ui-ux-pro-max")
        self.assertNotIn(
            "ui-ux-pro-max",
            {name for name, _ in skill_registry.resolve_skills(self.root, "백엔드와 무관한 일반 과업", "freyja")},
        )
        self.assertIn(
            "ui-ux-pro-max",
            {name for name, _ in skill_registry.resolve_skills(self.root, "반응형 대시보드 UI", "freyja")},
        )
        self.assertIn(
            "ui-ux-pro-max",
            {row["name"] for row in skill_registry.available_skills(self.root, "freyja")},
        )
        visible = {row["name"] for row in skill_registry.available_skills(self.root, "freyja")}
        self.assertEqual(visible & expected, expected - {"design"})
        self.assertIn("design", {row["name"] for row in skill_registry.invocable_skills(self.root)})
        self.assertFalse(expected & {row["name"] for row in skill_registry.available_skills(self.root, "worker")})
        self.assertNotIn(
            "ui-ux-pro-max",
            {name for name, _ in skill_registry.resolve_skills(self.root, "반응형 대시보드 UI", "worker")},
        )
        for task, specialist in (
            ("배너 디자인", "banner-design"),
            ("디자인 토큰", "design-system"),
            ("Tailwind 스타일링", "ui-styling"),
            ("HTML 슬라이드", "slides"),
        ):
            self.assertIn(
                specialist,
                {name for name, _ in skill_registry.resolve_skills(self.root, task, "freyja")},
                task,
            )
        self.assertIn(
            "brand-context",
            skill_registry.show_skill_resource(self.root, "brand", "scripts/inject-brand-context.cjs"),
        )
        self.assertIn(
            "Token Architecture",
            skill_registry.show_skill_resource(self.root, "design-system", "references/token-architecture.md"),
        )
        self.assertIn(
            "name: design",
            skill_registry.show_skill_resource(self.root, "design", "references/upstream-skill.md"),
        )
        with mock.patch("asgard.skill_registry.subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertEqual(skill_registry.run_skill(self.root, "ui-ux-pro-max", ["dashboard", "--json"]), 0)
        command = run.call_args.args[0]
        self.assertTrue(command[1].endswith("ui-ux-pro-max/scripts/search.py"))
        self.assertEqual(command[-2:], ["dashboard", "--json"])
        self.assertEqual(run.call_args.kwargs["cwd"], self.root)

    def test_instruction_compiler_bundles_all_upstream_knowledge_rooms_lazily(self):
        expected_skills = {
            "ai-alignment-reasoning": {
                "bias-detection-design",
                "consent-and-agency",
                "escalation-design",
                "guardrail-design",
                "harm-anticipation",
                "transparency-patterns",
                "trust-calibration",
                "value-specification",
            },
            "design-agent-orchestration": {
                "agent-role-design",
                "failure-recovery",
                "handoff-protocols",
                "human-in-the-loop",
                "observability-design",
                "state-management",
                "task-decomposition",
            },
            "evaluation": {
                "comparative-evaluation",
                "failure-taxonomy",
                "heuristic-evaluation-ai",
                "longitudinal-measurement",
                "output-quality-rubrics",
                "task-success-metrics",
                "user-satisfaction-signals",
            },
            "model-interaction-design": {
                "context-window-design",
                "conversation-patterns",
                "feedback-loops",
                "frustration-detection",
                "generative-ui",
                "mixed-initiative-flow",
                "multimodal-orchestration",
                "progressive-disclosure",
            },
            "prompt-architecture": {
                "chain-of-thought-design",
                "constraint-specification",
                "context-engineering",
                "few-shot-patterns",
                "prompt-versioning",
                "system-prompt-structure",
                "template-design",
            },
            "system-behavior-shaping": {
                "behavioral-consistency",
                "cultural-adaptation",
                "domain-voice",
                "emotional-design",
                "error-personality",
                "persona-architecture",
                "tone-calibration",
            },
        }
        expected_workflows = {
            "ai-alignment-reasoning": {"design-guardrails", "red-team", "write-policy"},
            "design-agent-orchestration": {"design-oversight", "design-workflow", "map-agents"},
            "evaluation": {"create-rubric", "design-benchmark", "run-evaluation"},
            "model-interaction-design": {"audit-interaction", "design-conversation", "map-initiative"},
            "prompt-architecture": {"audit-prompt", "build-chain", "design-prompt"},
            "system-behavior-shaping": {"calibrate-tone", "design-persona", "stress-test"},
        }
        plugin = skill_registry.bundled_plugins()["asgard-instruction-compiler"]
        room_root = Path(plugin["root"], "skills", "asgard-instruction-compiler", "references", "upstream")
        actual_skills = {
            domain.name: {path.parent.name for path in domain.glob("*/SKILL.md")}
            for domain in (room_root / "skills").iterdir()
            if domain.is_dir()
        }
        actual_workflows = {
            domain.name: {path.stem for path in domain.glob("*.md")}
            for domain in (room_root / "workflows").iterdir()
            if domain.is_dir()
        }
        self.assertEqual(actual_skills, expected_skills)
        self.assertEqual(actual_workflows, expected_workflows)
        self.assertEqual(sum(map(len, actual_skills.values())), 44)
        self.assertEqual(sum(map(len, actual_workflows.values())), 18)
        self.assertIn(
            "System Prompt Structure",
            skill_registry.show_skill_resource(
                self.root,
                "asgard-instruction-compiler",
                "references/upstream/skills/prompt-architecture/system-prompt-structure/SKILL.md",
            ),
        )
        self.assertIn(
            "Create a structured system prompt",
            skill_registry.show_skill_resource(
                self.root,
                "asgard-instruction-compiler",
                "references/upstream/workflows/prompt-architecture/design-prompt.md",
            ),
        )
        worker_names = {row["name"] for row in skill_registry.available_skills(self.root, "worker")}
        self.assertIn("asgard-instruction-compiler", worker_names)
        self.assertFalse(set().union(*expected_skills.values()) & worker_names)

    def test_bundled_skill_bodies_do_not_reference_missing_local_resources(self):
        local_path = re.compile(r"(?<![\w./-])((?:references|scripts|assets|examples)/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+)")
        missing = []
        for plugin in skill_registry.bundled_plugins().values():
            for skill_name in plugin["skills"]:
                skill_root = Path(plugin["root"], "skills", skill_name)
                body = (skill_root / "SKILL.md").read_text(encoding="utf-8")
                for relative in local_path.findall(body):
                    if not (skill_root / relative).is_file():
                        missing.append(f"{skill_name}/{relative}")
        self.assertEqual(missing, [])

    def test_freyja_restraint_is_native_and_freyja_only(self):
        name = "asgard-freyja-restraint"
        catalog = {row["name"]: row for row in skill_registry.skills(self.root)}
        self.assertEqual(catalog[name]["plugin"], name)
        self.assertIn(name, {row["name"] for row in skill_registry.available_skills(self.root, "freyja")})
        self.assertNotIn(name, {row["name"] for row in skill_registry.available_skills(self.root, "worker")})
        self.assertIn(
            name,
            {skill for skill, _ in skill_registry.resolve_skills(self.root, "랜딩 페이지 UI 디자인", "freyja")},
        )
        body = skill_registry.load_skill_for_agent(self.root, "freyja", name)
        self.assertIn("Leave empty regions quiet", body)
        self.assertIn("Do not use Unicode emoji", body)
        from asgard.agent.heimdall import _skill_support

        note, tools, handlers = _skill_support("freyja", self.root)
        self.assertIn(name, note)
        self.assertEqual([tool["name"] for tool in tools], ["load_skill"])
        self.assertEqual(handlers["load_skill"]({"name": name}), body)

    def test_thor_bilskirnir_policy_pack_is_thor_scoped(self):
        name = "asgard-thor-bilskirnir"
        catalog = {row["name"]: row for row in skill_registry.skills(self.root)}
        self.assertEqual(catalog[name]["plugin"], name)
        for agent in ("thor", "thor-lead"):
            self.assertIn(name, {row["name"] for row in skill_registry.available_skills(self.root, agent)})
        self.assertNotIn(name, {row["name"] for row in skill_registry.available_skills(self.root, "worker")})
        self.assertIn(
            name,
            {
                skill
                for skill, _ in skill_registry.resolve_skills(
                    self.root, "신규 백엔드 API 설계 — 하우스 룰 준수", "thor"
                )
            },
        )
        self.assertNotIn(
            name,
            {skill for skill, _ in skill_registry.resolve_skills(self.root, "프론트 버튼 색상 교체", "thor")},
        )
        body = skill_registry.load_skill_for_agent(self.root, "thor", name)
        self.assertIn("적용 위계", body)
        for resource in (
            "ARCHITECTURE.md",
            "API-DESIGN.md",
            "CODING.md",
            "DATABASE.md",
            "SECURITY.md",
            "INTEGRATION.md",
            "WORKFLOW.md",
        ):
            self.assertIn(resource, body)
        envelope = skill_registry.show_skill_resource(self.root, name, "API-DESIGN.md")
        self.assertIn("resultCode", envelope)

    def test_thor_clean_hexagonal_skill_is_mapped_loaded_and_composed(self):
        name = "asgard-thor-clean-hexagonal"
        catalog = {row["name"]: row for row in skill_registry.skills(self.root)}
        self.assertEqual(catalog[name]["plugin"], "asgard-thor-bilskirnir")
        for agent in ("thor", "thor-lead"):
            self.assertIn(name, {row["name"] for row in skill_registry.available_skills(self.root, agent)})
        for agent in ("worker", "freyja"):
            self.assertNotIn(name, {row["name"] for row in skill_registry.available_skills(self.root, agent)})

        resolved = {
            skill
            for skill, _ in skill_registry.resolve_skills(
                self.root,
                "주문 API를 Clean Architecture와 헥사고날 포트와 어댑터로 리팩터링",
                "thor",
            )
        }
        self.assertIn(name, resolved)
        audit_resolved = {
            skill
            for skill, _ in skill_registry.resolve_skills(
                self.root, "헥사고날 아키텍처 리뷰 — port 경계와 의존성 방향 감사", "thor"
            )
        }
        self.assertIn(name, audit_resolved)
        self.assertIn("asgard-hlidskjalf", audit_resolved)
        self.assertNotIn(
            name,
            {skill for skill, _ in skill_registry.resolve_skills(self.root, "기존 CRUD 오탈자 수정", "thor")},
        )
        self.assertNotIn(
            name,
            {
                skill
                for skill, _ in skill_registry.resolve_skills(
                    self.root, "신규 백엔드의 의존성 역전과 바운디드 컨텍스트를 설계", "thor"
                )
            },
        )

        body = skill_registry.load_skill_for_agent(self.root, "thor", name)
        for resource in ("references/BOUNDARIES.md", "references/TOOLING.md", "references/SOURCES.md"):
            self.assertIn(resource, body)
        tooling = skill_registry.load_skill_for_agent(self.root, "thor", name, resource="references/TOOLING.md")
        self.assertIn("import-linter", tooling)
        self.assertIn("ArchUnit", tooling)

        from asgard.agent.heimdall import _skill_support

        note, tools, handlers = _skill_support("thor", self.root)
        self.assertIn(name, note)
        self.assertEqual([tool["name"] for tool in tools], ["load_skill"])
        self.assertEqual(handlers["load_skill"]({"name": name}), body)
        self.assertIn(
            "outbound adapter",
            handlers["load_skill"]({"name": name, "resource": "references/BOUNDARIES.md"}),
        )

        from asgard.templates.roles import ROLE_AGENTS

        role = dict(ROLE_AGENTS)["asgard-thor.md"]
        self.assertIn("아키텍처 opt-in 게이트", role)
        self.assertIn("기본은 `asgard-thor-bilskirnir`의 4레이어", role)
        self.assertIn("Specialist trace", role)

    def test_hlidskjalf_architecture_pack_spans_backend_and_guide_agents(self):
        # 시스템 아키텍처 검증 팩 (26-07-21) — 계층·결합도·경계 감사 정본
        name = "asgard-hlidskjalf"
        catalog = {row["name"]: row for row in skill_registry.skills(self.root)}
        self.assertEqual(catalog[name]["plugin"], name)
        for agent in ("worker", "thor", "thor-lead", "mimir"):
            self.assertIn(name, {row["name"] for row in skill_registry.available_skills(self.root, agent)})
        self.assertNotIn(name, {row["name"] for row in skill_registry.available_skills(self.root, "freyja")})
        self.assertIn(
            name,
            {
                skill
                for skill, _ in skill_registry.resolve_skills(
                    self.root, "시스템 아키텍처 검증 — 순환 의존·계층 위반 감사", "thor"
                )
            },
        )
        self.assertNotIn(
            name,
            {skill for skill, _ in skill_registry.resolve_skills(self.root, "프론트 버튼 색상 교체", "thor")},
        )
        body = skill_registry.load_skill_for_agent(self.root, "thor", name)
        self.assertIn("검증 계약", body)
        self.assertIn("판정 불능 = 미판정", body)
        for resource in ("LAYERING.md", "COUPLING.md", "BOUNDARIES.md"):
            self.assertIn(resource, body)
        layering = skill_registry.show_skill_resource(self.root, name, "LAYERING.md")
        self.assertIn("역류 검출", layering)

    def test_official_scrapling_skill_is_bundled_and_assigned(self):
        name = "scrapling-official"
        plugin = skill_registry.bundled_plugins()[name]
        self.assertEqual(plugin["version"], "0.4.11")
        self.assertEqual(plugin["revision"], "07a548362ff904a2837f503ed9d9f6b9dcef0195")
        self.assertIn(name, {row["name"] for row in skill_registry.available_skills(self.root, "worker")})
        for agent in ("thor", "thor-lead", "freyja"):
            self.assertNotIn(name, {row["name"] for row in skill_registry.available_skills(self.root, agent)})
        skill_registry.assign_skill(self.root, name, "thor", assigned=True)
        self.assertIn(name, {row["name"] for row in skill_registry.available_skills(self.root, "thor")})
        self.assertIn(
            name,
            {skill for skill, _ in skill_registry.resolve_skills(self.root, "웹 스크래핑 크롤러 작성", "worker")},
        )
        body = skill_registry.load_skill_for_agent(self.root, "thor", name)
        self.assertIn("--ai-targeted", body)
        self.assertIn("Respect robots.txt and ToS", body)
        reference = skill_registry.show_skill_resource(self.root, name, "references/fetching/choosing.md")
        self.assertIn("Fetchers Overview", reference)

    def test_threejs_reference_pack_is_freyja_scoped(self):
        name = "threejs-skills"
        plugin = skill_registry.bundled_plugins()[name]
        self.assertEqual(plugin["revision"], "b1c623076c661fc9b03dac19292e825a5d106823")
        catalog = {row["name"]: row for row in skill_registry.skills(self.root)}
        self.assertEqual(catalog[name]["plugin"], name)
        for agent in ("freyja", "freyja-lead"):
            self.assertIn(name, {row["name"] for row in skill_registry.available_skills(self.root, agent)})
        self.assertNotIn(name, {row["name"] for row in skill_registry.available_skills(self.root, "worker")})
        resolved = {
            skill for skill, _ in skill_registry.resolve_skills(self.root, "three.js 3D 제품 뷰어 씬", "freyja")
        }
        self.assertIn(name, resolved)
        self.assertIn("asgard-freyja-folkvangr", resolved)  # 원칙 스킬과 합성 — 레퍼런스 팩은 대체가 아니다
        self.assertNotIn(
            name,
            {skill for skill, _ in skill_registry.resolve_skills(self.root, "three files need merging", "freyja")},
        )
        body = skill_registry.load_skill_for_agent(self.root, "freyja", name)
        self.assertIn("적용 위계", body)
        for room in (
            "references/fundamentals.md",
            "references/geometry.md",
            "references/materials.md",
            "references/lighting.md",
            "references/textures.md",
            "references/animation.md",
            "references/loaders.md",
            "references/shaders.md",
            "references/postprocessing.md",
            "references/interaction.md",
        ):
            self.assertIn(room, body)
        shaders = skill_registry.show_skill_resource(self.root, name, "references/shaders.md")
        self.assertIn("onBeforeCompile", shaders)
        self.assertIn("`references/postprocessing.md`", shaders)  # See Also 가 팩 내부 리소스 경로로 재배선됨

    def test_cc_settings_preapprove_skill_loads(self):
        """헤드리스 CC 에서 스킬 로드 경로·quest-log 루프가 자동 거부되지 않도록 사전 승인."""
        from asgard.templates.claude import cc_settings

        allow = json.loads(cc_settings())["permissions"]["allow"]
        self.assertIn("Bash(asgard skills show *)", allow)
        self.assertIn("Bash(asgard skills resolve *)", allow)
        self.assertIn("Bash(asgard skills list*)", allow)
        self.assertTrue(any(".claude/hooks/quest-log.py" in rule for rule in allow))
        self.assertFalse(any("skills assign" in rule or "skills disable" in rule for rule in allow))

    def test_bundled_design_md_python_linter(self):
        plugin = skill_registry.bundled_plugins()["google-design-md"]
        script = Path(plugin["root"], "skills", "design-md-review", "scripts", "design_md.py")
        design = Path(self.root, "DESIGN.md")
        design.write_text(
            """---
name: Demo
colors:
  primary: "oklch(62% 0.18 250)"
  mixed: "color-mix(in srgb, #ffffff 40%, #000000)"
  broken-color: nope
typography:
  body:
    fontFamily: Inter
    fontSize: 16px
components:
  button:
    backgroundColor: "#777777"
    textColor: "#888888"
  broken:
    backgroundColor: "{colors.missing}"
---

## Colors
## Typography
""",
            encoding="utf-8",
        )
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(
            [sys.executable, str(script), "lint", str(design)], capture_output=True, text=True, env=env, check=False
        )
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertGreaterEqual(report["summary"]["errors"], 2)
        self.assertTrue(any("contrast ratio" in finding["message"] for finding in report["findings"]))
        self.assertFalse(any("color-mix" in finding["message"] for finding in report["findings"]))
        self.assertIn(
            "design-md-review",
            {name for name, _ in skill_registry.resolve_skills(self.root, "DESIGN.md 디자인 시스템 검수", "freyja")},
        )

    def test_emil_motion_skills_compose_after_existing_freyja_policy(self):
        catalog = {row["name"]: row for row in skill_registry.skills(self.root)}
        self.assertEqual(catalog["review-animations"]["plugin"], "emil-design-engineering")
        self.assertEqual(catalog["apple-design"]["origin"], "bundled")

        review = skill_registry.resolve_skills(self.root, "애니메이션 리뷰", "freyja")
        names = [name for name, _ in review]
        self.assertLess(names.index("asgard-freyja-motion"), names.index("review-animations"))
        self.assertNotIn("improve-animations", names)

        physical = dict(skill_registry.resolve_skills(self.root, "스프링 애니메이션 제스처 UI", "freyja"))
        self.assertIn("apple-design", physical)
        self.assertIn("asgard skills show apple-design", physical["apple-design"])
        self.assertIn("asgard skills show apple-design --resource", physical["apple-design"])
        self.assertNotIn(
            "apple-design",
            {name for name, _ in skill_registry.resolve_skills(self.root, "스프링 애니메이션 제스처 UI", "worker")},
        )

    def test_jitter_motion_reference_is_freyja_scoped(self):
        name = "jitter-motion-reference"
        plugin = skill_registry.bundled_plugins()[name]
        self.assertEqual(plugin["source"], "https://jitter.video/templates/all/")
        for agent in ("freyja", "freyja-lead"):
            self.assertIn(name, {row["name"] for row in skill_registry.available_skills(self.root, agent)})
        self.assertNotIn(name, {row["name"] for row in skill_registry.available_skills(self.root, "worker")})

        resolved = [name for name, _ in skill_registry.resolve_skills(self.root, "Jitter 모션 예제 적용", "freyja")]
        self.assertIn("asgard-freyja-motion", resolved)
        self.assertIn(name, resolved)
        body = skill_registry.load_skill_for_agent(self.root, "freyja", name)
        self.assertIn("references/pattern-atlas.md", body)
        atlas = skill_registry.show_skill_resource(self.root, name, "references/pattern-atlas.md")
        self.assertIn("https://jitter.video/template/card-flip/", atlas)
        self.assertIn("분석 레퍼런스", atlas)

    def test_moving_landing_composes_freyja_policy_with_external_specialists(self):
        task = "아스가르드에 대한 현대적이고 모던한 스타일의 움직이는 랜딩페이지를 구성해줘"
        resolved = dict(skill_registry.resolve_skills(self.root, task, "freyja"))
        self.assertIn("asgard-freyja-motion", resolved)
        for name in (
            "ui-ux-pro-max",
            "jitter-motion-reference",
            "micro-interaction",
            "asgard-freyja-restraint",
        ):
            self.assertIn(name, resolved)
        self.assertIn("asgard-freyja-brisingamen", resolved["asgard-freyja-deferred"])
        self.assertNotIn("emil-design-eng", resolved)  # explicit-only broad skill stays out of model discovery

    def test_skill_resource_loader_exposes_references_without_path_escape(self):
        standards = skill_registry.show_skill_resource(self.root, "review-animations", "STANDARDS.md")
        self.assertIn("Animation Standards Reference", standards)
        with self.assertRaisesRegex(ValueError, "escapes"):
            skill_registry.show_skill_resource(self.root, "review-animations", "../SKILL.md")

        from typer.testing import CliRunner

        from asgard.cli import app

        result = CliRunner().invoke(app, ["skills", "show", "review-animations", "--resource", "STANDARDS.md"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Animation Standards Reference", result.stdout)

    def test_scaffold_uses_native_discovery_and_direct_canonical_loaders(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=True, root=self.root)
        by_path = dict(files)
        cc = by_path[os.path.join(self.root, ".claude", "skills", "asgard-worker-debugging", "SKILL.md")]
        codex = by_path[os.path.join(self.root, ".agents", "skills", "asgard-worker-debugging", "SKILL.md")]
        self.assertNotIn("disable-model-invocation: true", cc)
        self.assertIn("disable-model-invocation: true", codex)
        self.assertIn("asgard skills show asgard-worker-debugging", cc)
        self.assertIn("asgard skills show asgard-worker-debugging", codex)
        self.assertNotIn("재현 없으면 수정 없다", cc)
        self.assertIn(os.path.join(self.root, ".agents", "skills", "asgard-skills", "SKILL.md"), by_path)
        for name in ("ui-ux-pro-max", "design-md-review", "review-animations", "asgard-freyja-motion"):
            adapter = by_path[os.path.join(self.root, ".agents", "skills", name, "SKILL.md")]
            self.assertIn(f"asgard skills show {name}", adapter)
        core = by_path[os.path.join(self.root, ".agents", "skills", "asgard-freyja", "SKILL.md")]
        self.assertIn("asgard skills show asgard-freyja", core)
        router = by_path[os.path.join(self.root, ".agents", "skills", "asgard-skills", "SKILL.md")]
        self.assertIn('skills resolve --agent <role> "<current task>"', router)
        self.assertIn("Do not prefix the command with", router)
        self.assertIn("`MAIN_WORKER` and agent names are not valid role values", router)
        self.assertNotIn("disable-model-invocation: true", router)
        self.assertNotIn(
            os.path.join(self.root, ".agents", "skills", "asgard-skills", "agents", "openai.yaml"), by_path
        )
        metadata = by_path[
            os.path.join(self.root, ".agents", "skills", "asgard-worker-debugging", "agents", "openai.yaml")
        ]
        self.assertIn("allow_implicit_invocation: false", metadata)
        freyja_role = by_path[os.path.join(self.root, ".claude", "agents", "asgard-freyja.md")]
        self.assertIn("<available_skills>", freyja_role)
        self.assertIn("ui-ux-pro-max", freyja_role)

    def test_project_assignment_and_disable_overrides(self):
        from asgard.settings import load_project

        skill_registry.assign_skill(self.root, "asgard-worker-testing", "worker", assigned=False)
        names = {name for name, _ in skill_registry.resolve_skills(self.root, "회귀 버그 테스트", "worker")}
        self.assertNotIn("asgard-worker-testing", names)
        skill_registry.assign_skill(self.root, "asgard-worker-testing", "worker", assigned=True)
        names = {name for name, _ in skill_registry.resolve_skills(self.root, "회귀 버그 테스트", "worker")}
        self.assertIn("asgard-worker-testing", names)
        skill_registry.set_skill_enabled(self.root, "asgard-worker-testing", enabled=False)
        names = {name for name, _ in skill_registry.resolve_skills(self.root, "회귀 버그 테스트", "worker")}
        self.assertNotIn("asgard-worker-testing", names)
        self.assertEqual(load_project(self.root)["skills"]["disabled"], ["asgard-worker-testing"])
        with self.assertRaisesRegex(ValueError, "not compatible"):
            skill_registry.assign_skill(self.root, "ui-ux-pro-max", "worker", assigned=True)

    def test_install_and_resolve_data_only_plugin(self):
        source = os.path.join(self.root, "source")
        skill = os.path.join(source, "skills", "acme-db")
        os.makedirs(skill)
        Path(os.path.join(source, "plugin.json")).write_text(
            json.dumps(
                {
                    "schema": 1,
                    "name": "acme",
                    "version": "1.0.0",
                    "description": "Acme policy",
                    "skills": ["acme-db"],
                }
            ),
            encoding="utf-8",
        )
        Path(os.path.join(skill, "SKILL.md")).write_text(
            "---\nname: acme-db\ndescription: DB rule\ntriggers: vacuum, database\nagent: thor\n---\n\nACME_DB_POLICY\n",
            encoding="utf-8",
        )

        installed = skill_registry.install_plugin(source)
        self.assertEqual(installed["name"], "acme")
        hits = skill_registry.resolve_skills(self.root, "database vacuum", "thor")
        self.assertIn(("acme-db", "ACME_DB_POLICY\n"), hits)
        self.assertIn("ACME_DB_POLICY", skill_registry.show_skill(self.root, "acme-db") or "")
        from asgard.agent.heimdall import _skill_support

        note, tools, handlers = _skill_support("thor", self.root)
        self.assertIn("acme-db", note)
        self.assertEqual([tool["name"] for tool in tools], ["load_skill"])
        self.assertEqual(handlers["load_skill"]({"name": "acme-db"}), "ACME_DB_POLICY\n")

    def test_user_invoked_plugin_stays_out_of_model_context_but_manual_load_works(self):
        source = os.path.join(self.root, "explicit-source")
        skill = os.path.join(source, "skills", "manual-check")
        automatic = os.path.join(source, "skills", "automatic-check")
        os.makedirs(skill)
        os.makedirs(automatic)
        Path(os.path.join(source, "plugin.json")).write_text(
            json.dumps({"schema": 1, "name": "explicit", "skills": ["manual-check", "automatic-check"]}),
            encoding="utf-8",
        )
        Path(os.path.join(skill, "SKILL.md")).write_text(
            "---\nname: manual-check\ndescription: Manual check\ntriggers: check\nagent: worker\n"
            "disable-model-invocation: true\n---\n\nMANUAL_ONLY\n",
            encoding="utf-8",
        )
        Path(os.path.join(automatic, "SKILL.md")).write_text(
            "---\nname: automatic-check\ndescription: Automatic check\ntriggers: check\nagent: worker\n"
            "---\n\nAUTOMATIC\n",
            encoding="utf-8",
        )
        skill_registry.install_plugin(source)

        row = next(row for row in skill_registry.skills(self.root) if row["name"] == "manual-check")
        self.assertEqual(row["invocation"], "user")
        self.assertNotIn("manual-check", {row["name"] for row in skill_registry.available_skills(self.root, "worker")})
        self.assertEqual(
            skill_registry.resolve_skills(self.root, "check", "worker"), [("automatic-check", "AUTOMATIC\n")]
        )
        self.assertIn("MANUAL_ONLY", skill_registry.show_skill(self.root, "manual-check") or "")

        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=True, root=self.root)
        by_path = dict(files)
        adapter = by_path[os.path.join(self.root, ".agents", "skills", "manual-check", "SKILL.md")]
        metadata = by_path[os.path.join(self.root, ".agents", "skills", "manual-check", "agents", "openai.yaml")]
        self.assertIn("disable-model-invocation: true", adapter)
        self.assertIn("allow_implicit_invocation: false", metadata)

    def test_bundled_workflows_have_real_manual_invocation_and_zero_discovery_load(self):
        rows = {row["name"]: row for row in skill_registry.skills(self.root)}
        for name in ("council", "blueprint", "quests", "expedition", "emil-design-eng"):
            self.assertEqual(rows[name]["invocation"], "user")
        available = {row["name"] for row in skill_registry.available_skills(self.root, "worker")}
        self.assertNotIn("council", available)
        self.assertIn("domain-modeling", available)
        self.assertEqual(rows["prototype"]["invocation"], "model")
        self.assertIn("prototype", available)
        self.assertIn("prototype", {row["name"] for row in skill_registry.available_skills(self.root, "freyja")})

        prompt = skill_registry.invoked_skill_prompt(self.root, "/council checkout flow")
        self.assertIn('<user_invoked_skill name="council">', prompt or "")
        self.assertIn("Ask exactly one decision question per turn", prompt or "")
        self.assertIn("Arguments: checkout flow", prompt or "")
        for route in ("prototype", "domain-modeling", "blueprint", "quests", "expedition"):
            self.assertIn(route, prompt or "")
        self.assertIsNone(skill_registry.invoked_skill_prompt(self.root, "/missing-skill"))
        skill_registry.set_skill_enabled(self.root, "council", enabled=False)
        self.assertIsNone(skill_registry.invoked_skill_prompt(self.root, "/council checkout flow"))
        skill_registry.set_skill_enabled(self.root, "council", enabled=True)

        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=True, root=self.root)
        by_path = dict(files)
        adapter = by_path[os.path.join(self.root, ".agents", "skills", "council", "SKILL.md")]
        metadata = by_path[os.path.join(self.root, ".agents", "skills", "council", "agents", "openai.yaml")]
        self.assertIn("disable-model-invocation: true", adapter)
        self.assertIn("allow_implicit_invocation: false", metadata)

    def test_invocable_catalog_does_not_enumerate_canonical_bodies_per_role(self):
        with mock.patch.object(
            skill_registry,
            "client_skill_bodies",
            side_effect=AssertionError("body enumeration is not a catalog operation"),
        ):
            names = {row["name"] for row in skill_registry.invocable_skills(self.root)}
        self.assertIn("council", names)
        self.assertIn("domain-modeling", names)

    def test_skillcraft_keeps_detailed_rubric_in_a_lazy_resource(self):
        row = next(row for row in skill_registry.skills(self.root) if row["name"] == "asgard-skillcraft")
        self.assertEqual((row["plugin"], row["invocation"]), ("asgard-skillcraft", "model"))
        body = skill_registry.load_skill_for_agent(self.root, "worker", "asgard-skillcraft")
        self.assertIn("load `CHECKLIST.md`", body)
        self.assertNotIn("Pick 3-5 representative prompts", body)
        resource = skill_registry.load_skill_for_agent(
            self.root, "worker", "asgard-skillcraft", resource="CHECKLIST.md"
        )
        self.assertIn("Pick 3-5 representative prompts", resource)

    def test_install_preserves_declared_skill_resources(self):
        source = os.path.join(self.root, "resource-source")
        skill = os.path.join(source, "skills", "acme-search")
        os.makedirs(os.path.join(skill, "scripts"))
        os.makedirs(os.path.join(skill, "data"))
        Path(os.path.join(source, "plugin.json")).write_text(
            json.dumps(
                {
                    "schema": 1,
                    "name": "acme-resource",
                    "skills": ["acme-search"],
                    "entrypoints": {"acme-search": "scripts/search.py"},
                }
            ),
            encoding="utf-8",
        )
        Path(os.path.join(skill, "SKILL.md")).write_text(
            "---\nname: acme-search\ndescription: Search\ntriggers: lookup\nagent: worker\n---\n\nSEARCH\n",
            encoding="utf-8",
        )
        Path(os.path.join(skill, "scripts", "search.py")).write_text("print('ok')\n", encoding="utf-8")
        Path(os.path.join(skill, "data", "index.csv")).write_text("term,value\na,b\n", encoding="utf-8")

        skill_registry.install_plugin(source)
        plugin = skill_registry.installed_plugins()["acme-resource"]
        self.assertEqual(
            Path(plugin["root"], "skills", "acme-search", "data", "index.csv").read_text(), "term,value\na,b\n"
        )

    def test_plugin_rejects_nested_resource_symlink(self):
        source = os.path.join(self.root, "source")
        skill = os.path.join(source, "skills", "escape")
        os.makedirs(skill)
        Path(os.path.join(source, "plugin.json")).write_text(
            json.dumps({"schema": 1, "name": "bad-nested", "skills": ["escape"]}), encoding="utf-8"
        )
        Path(os.path.join(skill, "SKILL.md")).write_text(
            "---\nname: escape\ndescription: Escape\ntriggers: escape\nagent: worker\n---\n\nBAD\n",
            encoding="utf-8",
        )
        os.symlink(os.path.join(self.root, "outside"), os.path.join(skill, "data"))
        with self.assertRaisesRegex(ValueError, "cannot contain symlinks"):
            skill_registry.install_plugin(source)

    def test_plugin_rejects_symlinked_skills_directory(self):
        source = os.path.join(self.root, "source")
        outside = os.path.join(self.root, "outside")
        os.makedirs(outside)
        os.makedirs(source)
        os.symlink(outside, os.path.join(source, "skills"))
        Path(os.path.join(source, "plugin.json")).write_text(
            json.dumps({"schema": 1, "name": "bad", "skills": ["escape"]}), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "regular directory"):
            skill_registry.install_plugin(source)


if __name__ == "__main__":
    unittest.main()
