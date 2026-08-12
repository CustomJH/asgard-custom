#!/usr/bin/env python3
"""Central skill/plugin catalog: one router, thin client adapters, safe resource plugins."""

import json
import os
import re
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

    def test_planning_skill_is_bundled_and_worker_routed(self):
        plugin = skill_registry.bundled_plugins()["asgard-planning"]
        self.assertEqual(plugin["skills"], ["asgard-planning"])
        names = {
            name
            for name, _ in skill_registry.resolve_skills(
                self.root,
                "기획 에이전트로 PRD와 유저 플로우를 순서대로 설계해줘",
                "worker",
            )
        }
        self.assertIn("asgard-planning", names)
        body = skill_registry.load_skill_for_agent(self.root, "worker", "asgard-planning")
        self.assertIn("근거 → 문제/기회", body)
        self.assertIn("정상·빈·오류·권한·복구·접근성", body)

    def test_catalog_prioritizes_matches_without_hiding_other_skills(self):
        matched = {name for name, _ in skill_registry.resolve_skills(self.root, "로그인 폼 접근성 개선", "freyja")}
        catalog = skill_registry.skill_catalog(self.root, "freyja", matched=matched)

        self.assertEqual(matched, {"asgard-freyja-design"})
        self.assertIn("[task-match] asgard-freyja-design", catalog)

    def test_the_baked_catalog_sends_the_agent_to_the_runtime_resolver_first(self):
        """파일로 구워지는 갈래는 구운 시점의 목록이라, 그 뒤 설치된 학습 스킬이 없다.

        26-08-12 실측: 배포된 워커 명단 17개 옆에서 라이브 목록은 18개였고, 빠진 하나가 그날
        자동 설치된 스킬이었다. 그래서 이 갈래는 목록을 읽기 전에 디스크를 다시 보게 한다."""
        baked = skill_registry.skill_catalog(self.root, "worker", loader="cli")
        self.assertIn("asgard skills resolve --agent", baked)
        self.assertIn("installed after this file was written", baked)
        # 매 턴 계산되는 갈래는 이 문제가 없으므로 같은 지시를 안 진다
        live = skill_registry.skill_catalog(self.root, "worker", matched={"asgard-worker-testing"})
        self.assertNotIn("asgard skills resolve --agent", live)

    def test_bare_catalog_commands_list_current_inventory(self):
        from cli_boundary import run_cli

        from asgard.commands import skills as command

        with mock.patch.object(command.ui, "term_cols", return_value=140):
            skills_result = run_cli("skills")
            plugins_result = run_cli("plugins")
            json_result = run_cli("plugins", "list", "--json")
        self.assertEqual(skills_result.exit_code, 0, skills_result.stderr)
        self.assertIn("╭─ Skills ·", skills_result.stdout)
        self.assertIn("asgard-worker-testing", skills_result.stdout)
        self.assertEqual(plugins_result.exit_code, 0, plugins_result.stderr)
        self.assertIn("╭─ Plugins ·", plugins_result.stdout)
        self.assertIn("╰", plugins_result.stdout)
        self.assertIn("playwright-cli", plugins_result.stdout)
        self.assertEqual(json.loads(json_result.stdout), skill_registry.plugins())
        # 목록은 산출물이다 — 셋 다 stdout 하나로 나가고 stderr는 비어 있어야 한다.
        for result in (skills_result, plugins_result, json_result):
            self.assertEqual(result.stderr, "")

    def test_resolve_reads_the_task_from_stdin_and_splits_the_two_streams(self):
        """인자를 생략하면 과업은 stdin에서 온다 — 파이프로 부르는 호스트가 쓰는 통로다.

        거부 둘(미지의 역할, 빈 과업)은 호출자가 고칠 수 있는 잘못이라 2이고, 사유는 stderr로
        나간다. stdout이 비어 있어야 `asgard skills resolve < task.txt > out.json`이 실패한
        실행에서 데이터 스트림에 사람 말을 받지 않는다."""
        from cli_boundary import run_cli

        resolved = run_cli("skills", "resolve", "--agent", "freyja", "--json", stdin="로그인 폼 접근성 개선")
        self.assertEqual(resolved.exit_code, 0, resolved.stderr)
        self.assertEqual(resolved.stderr, "")
        self.assertIn("asgard-freyja-design", [row["name"] for row in json.loads(resolved.stdout)["skills"]])

        for argv, stdin, reason in (
            (("skills", "resolve", "--agent", "odin"), "무엇이든", "invalid agent"),
            (("skills", "resolve", "--agent", "freyja"), "   \n", "task is required"),
        ):
            with self.subTest(reason=reason):
                refused = run_cli(*argv, stdin=stdin)
                self.assertEqual(refused.exit_code, 2)
                self.assertEqual(refused.stdout, "")
                self.assertIn(reason, refused.stderr)

    def test_catalog_renderer_is_readable_without_changing_json(self):
        from cli_boundary import run_cli

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
            plain = run_cli("skills", "list")
            json_result = run_cli("skills", "list", "--json")
        self.assertEqual(plain.exit_code, 0, plain.stderr)
        self.assertEqual(plain.stderr, "")
        self.assertEqual(json_result.stderr, "")
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
            wide = run_cli("plugins", "list")
        self.assertEqual(wide.exit_code, 0, wide.stderr)
        self.assertEqual(wide.stderr, "")
        self.assertIn("Plugins · 3", wide.stdout)
        self.assertIn("╭", wide.stdout)
        self.assertIn("╰", wide.stdout)
        self.assertIn("0 skills", wide.stdout)
        self.assertIn("1 skill", wide.stdout)
        self.assertIn("2 skills", wide.stdout)

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

        from asgard.agent.heimdall.roles import _skill_support

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
        self.assertIn("Architecture opt-in gate", role)
        self.assertIn("the default is `asgard-thor-bilskirnir`'s 4 layers", role)
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

    def test_freyja_fjadrhamr_example_pack_is_freyja_scoped(self):
        name = "asgard-freyja-fjadrhamr"
        plugin = skill_registry.bundled_plugins()["freyja-fjadrhamr"]
        self.assertEqual(plugin["skills"], [name])
        self.assertIn(name, {row["name"] for row in skill_registry.available_skills(self.root, "freyja")})
        self.assertNotIn(name, {row["name"] for row in skill_registry.available_skills(self.root, "worker")})
        self.assertIn(
            name,
            {
                skill
                for skill, _ in skill_registry.resolve_skills(
                    self.root, "히어로 배경 애니메이션 컴포넌트 예제 가져와줘", "freyja"
                )
            },
        )
        # 기존 배타 앵커 보존 — 일반 프레이야 과제 프로브에 침입하지 않는다
        self.assertNotIn(
            name,
            {skill for skill, _ in skill_registry.resolve_skills(self.root, "로그인 폼 접근성 개선", "freyja")},
        )
        body = skill_registry.load_skill_for_agent(self.root, "freyja", name)
        self.assertIn("capture protocol", body)
        self.assertIn("Commons Clause", body)
        for catalog in (
            "catalog-magicui.json",
            "catalog-reactbits.json",
            "catalog-animata.json",
            "catalog-aceternity.json",
            "catalog-motionprimitives.json",
            "catalog-21st.json",
            "catalog-originkit.json",
            "catalog-uiverse.json",
        ):
            resource = skill_registry.show_skill_resource(self.root, name, catalog)
            self.assertIn('"components"', resource)
        recipes = skill_registry.show_skill_resource(self.root, name, "SOURCES.md")
        self.assertIn("ORIGINKIT_API_KEY", recipes)
        self.assertIn("cdn.21st.dev", recipes)

    def test_cc_settings_preapprove_skill_loads(self):
        """헤드리스 CC에서 스킬 로드 경로·quest-log 루프가 자동 거부되지 않도록 사전 승인."""
        from asgard.templates.claude import cc_settings

        allow = json.loads(cc_settings())["permissions"]["allow"]
        self.assertIn("Bash(asgard skills show *)", allow)
        self.assertIn("Bash(asgard skills resolve *)", allow)
        self.assertIn("Bash(asgard skills list*)", allow)
        self.assertTrue(any(".claude/hooks/quest-log.py" in rule for rule in allow))
        self.assertFalse(any("skills assign" in rule or "skills disable" in rule for rule in allow))

    def test_every_builtin_skill_separates_allowed_tools_with_commas(self):
        """26-08-04 회귀 — allowed-tools 를 공백으로 이으면 그 스킬의 사전 승인이 통째로 죽는다.

        쉼표 구분 목록이라 공백으로 이은 줄은 항목 **하나**로 파싱되고, 그 하나는
        `Bash(git status *) Bash(git diff *) …` 라는 없는 명령과의 정확 일치라 어느 호출도
        안 맞힌다. `asgard-seal` 이 이 상태였고, 봉인 절차의 git 명령이 전부 승인 프롬프트를
        띄워 단순 커밋 한 번이 5분 넘게 걸렸다. 스킬 하나를 고쳐도 다음 스킬이 같은 자리를
        밟으므로 표를 통째로 본다."""
        from asgard.skill_registry import _builtin_plugins

        for plugin in _builtin_plugins().values():
            for name, text in plugin["skills"]:
                line = next((ln for ln in text.splitlines() if ln.startswith("allowed-tools:")), None)
                if line is None:
                    continue
                for rule in line.split(":", 1)[1].split(","):
                    self.assertLessEqual(
                        rule.count("Bash("), 1, f"{name}: 한 항목에 규칙이 여럿 뭉쳤어요 — {rule.strip()}"
                    )

    def test_moving_landing_composes_freyja_policy_with_external_specialists(self):
        task = "아스가르드에 대한 현대적이고 모던한 스타일의 움직이는 랜딩페이지를 구성해줘"
        self.assertIn(
            "asgard-freyja-design",
            {name for name, _ in skill_registry.resolve_skills(self.root, task, "freyja")},
        )

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
        self.assertIn("asgard-freyja-design", freyja_role)

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
            skill_registry.assign_skill(self.root, "asgard-thor-bilskirnir", "worker", assigned=True)

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
        from asgard.agent.heimdall.roles import _skill_support

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
        for name in ("council", "blueprint", "quests", "expedition"):
            self.assertEqual(rows[name]["invocation"], "user")
        available = {row["name"] for row in skill_registry.available_skills(self.root, "worker")}
        self.assertNotIn("council", available)
        self.assertIn("domain-modeling", available)
        self.assertEqual(rows["prototype"]["invocation"], "model")
        self.assertIn("prototype", available)
        self.assertNotIn("prototype", {row["name"] for row in skill_registry.available_skills(self.root, "freyja")})

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
