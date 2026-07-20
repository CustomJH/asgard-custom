#!/usr/bin/env python3
"""Central skill/plugin catalog: one router, thin client adapters, safe resource plugins."""

import json
import os
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
        self.assertNotIn(
            "ui-ux-pro-max",
            {name for name, _ in skill_registry.resolve_skills(self.root, "반응형 대시보드 UI", "worker")},
        )
        with mock.patch("asgard.skill_registry.subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertEqual(skill_registry.run_skill(self.root, "ui-ux-pro-max", ["dashboard", "--json"]), 0)
        command = run.call_args.args[0]
        self.assertTrue(command[1].endswith("ui-ux-pro-max/scripts/search.py"))
        self.assertEqual(command[-2:], ["dashboard", "--json"])
        self.assertEqual(run.call_args.kwargs["cwd"], self.root)

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
