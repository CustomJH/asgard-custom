#!/usr/bin/env python3
"""역할 배차 — 역할 제공자와 전문가 에이전트.

실행: uv run pytest tests/agent  (asgard 패키지 임포트 필요 — subprocess가 -m으로 훅 실행)
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from agent.agent_base import Base
from asgard.agent.quest_bridge import ql


class TestRoleProviders(Base):
    """[trinity.<role>] 역할별 provider 배치 — Trinity 모델 융합 축 (API 호출 없음)."""

    def setUp(self):
        super().setUp()
        self._home = os.environ.get("HOME")  # 글로벌 ~/.asgard/config.toml 오염 차단
        os.environ["HOME"] = self.root

    def tearDown(self):
        if self._home is not None:
            os.environ["HOME"] = self._home
        super().tearDown()

    def _default(self):
        from asgard.providers import PROVIDERS, ResolvedProvider

        return ResolvedProvider(profile=PROVIDERS["anthropic"], model="claude-x", api_key="k")

    def _write_config(self, body: str):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(body)

    def test_no_config_all_roles_default(self):
        from asgard.providers import resolve_trinity

        default = self._default()
        m = resolve_trinity(self.root, default)
        self.assertEqual(sorted(m), ["thinker", "verifier", "worker"])
        self.assertTrue(all(rp is default for rp in m.values()))

    def test_role_section_places_provider(self):
        from asgard.providers import resolve_trinity

        self._write_config('[trinity.worker]\nprovider = "ollama"\nmodel = "m1"\n')
        default = self._default()
        m = resolve_trinity(self.root, default)
        self.assertIs(m["thinker"], default)
        self.assertEqual(m["worker"].profile.name, "ollama")
        self.assertEqual(m["worker"].model, "m1")
        self.assertEqual(m["worker"].missing, [])  # ollama는 keyless — 배치 즉시 유효

    def test_heimdall_session_routes_by_role(self):
        from asgard.agent.heimdall import Heimdall

        self._write_config('[trinity.worker]\nprovider = "ollama"\nmodel = "m1"\n')
        h = Heimdall(self._default(), self.root, on_text=lambda s: None)
        self.assertEqual(h._session("sys", role="worker").rp.profile.name, "ollama")
        self.assertEqual(h._session("sys", role="thinker").rp.profile.name, "anthropic")
        self.assertEqual(h._session("sys").rp.profile.name, "anthropic")  # 딜리버리/DIRECT = 기본

    def test_heimdall_missing_role_falls_back(self):
        from asgard.agent.heimdall import Heimdall

        # openai_compat는 base_url·키 필수 — 미충족이면 경고 + 기본 provider 폴백
        self._write_config('[trinity.verifier]\nprovider = "openai_compat"\nmodel = "m2"\n')
        warns = []
        h = Heimdall(self._default(), self.root, on_text=warns.append)
        self.assertEqual(h._session("sys", role="verifier").rp.profile.name, "anthropic")
        self.assertTrue(any("trinity.verifier" in w for w in warns))

    def test_save_config_section_roundtrip_preserves_others(self):
        from asgard.providers import project_section, save_config_section

        self._write_config('[provider]\nname = "anthropic"\n')
        save_config_section(self.root, "trinity.worker", {"provider": "ollama", "model": "m1"})
        save_config_section(self.root, "bridge", {"claude-code": True, "codex": False})
        txt = open(os.path.join(self.root, ".asgard", "config.toml")).read()
        self.assertIn("[provider]", txt)  # 기존 섹션 보존
        self.assertEqual(project_section(self.root, "trinity"), {"worker": {"provider": "ollama", "model": "m1"}})
        self.assertEqual(project_section(self.root, "bridge"), {"claude-code": True, "codex": False})
        # 섹션 교체 (중복 없이) + 제거
        save_config_section(self.root, "trinity.worker", {"provider": "nvidia"})
        self.assertEqual(project_section(self.root, "trinity"), {"worker": {"provider": "nvidia"}})
        save_config_section(self.root, "trinity.worker", None)
        self.assertEqual(project_section(self.root, "trinity"), {})
        self.assertIn("[provider]", open(os.path.join(self.root, ".asgard", "config.toml")).read())

    def test_bridge_flags_default_off_and_config(self):
        from asgard.providers import bridge_flags

        self.assertEqual(bridge_flags(self.root), {"claude-code": False, "codex": False, "cursor": False})
        self._write_config("[bridge]\nclaude-code = true\ncursor = true\n")
        flags = bridge_flags(self.root)
        self.assertTrue(flags["claude-code"] and flags["cursor"])
        self.assertFalse(flags["codex"])

    def test_role_list_reports_placements(self):
        """`--json`이면 배치가 기계가 읽는 형태로 나온다 — 이 명령의 소비자는 호스트 도구다."""
        from cli_boundary import run_cli

        self._write_config('[trinity.worker]\nprovider = "ollama"\nmodel = "m1"\n[bridge]\ncodex = true\n')
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            listed = run_cli("role", "list", "--json")
        finally:
            os.chdir(cwd)

        self.assertEqual(listed.exit_code, 0, listed.stderr)
        out = json.loads(listed.stdout)
        self.assertTrue(out["bridge"]["codex"])
        self.assertTrue(out["roles"]["worker"]["placed"])
        self.assertEqual(out["roles"]["worker"]["provider"], "ollama")
        self.assertFalse(out["roles"]["thinker"]["placed"])
        self.assertEqual(out["agent_models"]["cursor"]["worker"]["model"], "gpt-5.6-terra-medium")

    def test_role_list_without_the_flag_is_a_human_surface(self):
        """플래그 없이 부르면 사람 문장이다 — stdout에 기계 JSON을 붓지 않는다.

        여태 이 명령은 플래그와 무관하게 JSON만 냈고 도움말이 그것을 "(JSON)"으로 적어 두었다.
        같은 저장소의 `skills list`·`plugins list`·`ticket list`는 전부 사람 표면이 기본이라,
        하나만 다른 규칙을 갖고 있었던 셈이다. 그 규칙을 되돌리지 못하게 여기서 잠근다."""
        from cli_boundary import run_cli

        self._write_config('[trinity.worker]\nprovider = "ollama"\nmodel = "m1"\n[bridge]\ncodex = true\n')
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            listed = run_cli("role", "list")
        finally:
            os.chdir(cwd)

        self.assertEqual(listed.exit_code, 0, listed.stderr)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(listed.stdout)
        self.assertIn("worker", listed.stdout)  # 같은 사실을 사람 쪽으로도 낸다
        self.assertIn("ollama", listed.stdout)

    def test_role_model_command_sets_syncs_and_resets_hosted_override(self):
        from asgard.commands.role import configure_role_model
        from asgard.providers import project_section

        os.makedirs(os.path.join(self.root, ".cursor"))
        out = configure_role_model(self.root, "cursor", "worker", model="cursor-user-model")

        self.assertEqual(out["effective"]["model"], "cursor-user-model")
        self.assertIsNotNone(out["synced"])
        self.assertEqual(
            project_section(self.root, "agent_models.cursor.worker"),
            {"model": "cursor-user-model"},
        )
        agent = open(os.path.join(self.root, ".cursor", "agents", "asgard-worker.md")).read()
        self.assertIn('model: "cursor-user-model"', agent)

        reset = configure_role_model(self.root, "cursor", "worker", reset=True)
        self.assertEqual(reset["effective"]["model"], "gpt-5.6-terra-medium")
        self.assertEqual(project_section(self.root, "agent_models.cursor.worker"), {})
        agent = open(os.path.join(self.root, ".cursor", "agents", "asgard-worker.md")).read()
        self.assertIn('model: "gpt-5.6-terra-medium"', agent)

    def test_role_model_command_configures_native_provider_and_model(self):
        from asgard.commands.role import configure_role_model
        from asgard.providers import project_section

        out = configure_role_model(
            self.root,
            "native",
            "worker",
            model="native-user-model",
            provider="ollama",
        )

        self.assertEqual(out["effective"]["provider"], "ollama")
        self.assertEqual(out["effective"]["model"], "native-user-model")
        self.assertIsNone(out["synced"])
        self.assertEqual(
            project_section(self.root, "trinity.worker"),
            {"provider": "ollama", "model": "native-user-model"},
        )

    def test_role_model_command_rejects_inert_or_conflicting_options(self):
        from asgard.commands.role import configure_role_model

        with self.assertRaisesRegex(ValueError, "model slug"):
            configure_role_model(self.root, "cursor", "worker", effort="high")
        with self.assertRaisesRegex(ValueError, "같이 쓸 수 없어요"):
            configure_role_model(self.root, "codex", "worker", model="x", reset=True)
        with self.assertRaisesRegex(ValueError, "model ID"):
            configure_role_model(self.root, "codex", "worker", model="bad\x1b[31m")
        with self.assertRaisesRegex(ValueError, "provider"):
            configure_role_model(self.root, "native", "worker", provider="unknown")

    def test_role_model_cli_lists_and_validates_arguments(self):
        # 종료 코드를 단언하는 자리는 전부 사용자 경계로 잰다 — `CliRunner`는 예외를 삼켜
        # 1로 적고, 터미널에서 친 사람은 2를 받는다 (tests/cli_boundary.py).
        from cli_boundary import run_cli

        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            listed = run_cli("role", "model", "--json")
            human = run_cli("role", "model")
            changed = run_cli("role", "model", "codex", "thinker", "custom-sol", "--effort", "max", "--json")
            invalid = run_cli("role", "model", "unknown", "worker", "x")
        finally:
            os.chdir(cwd)

        self.assertEqual(listed.exit_code, 0, listed.stderr)
        self.assertIn('"claude-code"', listed.stdout)
        # `role list`와 같은 계약 — 플래그 없이 부르면 사람 표면이고 stdout은 JSON이 아니다.
        self.assertEqual(human.exit_code, 0, human.stderr)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(human.stdout)
        self.assertEqual(changed.exit_code, 0, changed.stderr)
        self.assertIn('"model": "custom-sol"', changed.stdout)
        self.assertIn('"effort": "max"', changed.stdout)
        self.assertEqual(invalid.exit_code, 2)
        self.assertEqual(invalid.stdout, "")  # 사람 화면에 기계 JSON을 붓지 않는다
        self.assertNotEqual(invalid.stderr, "")  # 사유는 그 대신 stderr로 나간다

    def test_role_run_rejects_bad_role_and_no_quest(self):
        """둘 다 호출자가 고칠 수 있는 잘못이다 — 정본대로 2 (`errors.py`).

        quest 없음이 여태 1이었다: 같은 "네가 고치면 되는 일"이 명령마다 1과 2로 갈리면
        스크립트는 "내 잘못"과 "환경 문제"를 구별할 수 없다."""
        from cli_boundary import run_cli

        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            self.assertEqual(run_cli("role", "run", "odin", "t").exit_code, 2)  # 미지의 역할
            self.assertEqual(run_cli("role", "run", "worker", "t").exit_code, 2)  # 활성 quest 없음
        finally:
            os.chdir(cwd)

    def test_escalate_records_verdict(self):
        from asgard.agent.heimdall import Heimdall

        sid = "native-esc"
        ql(self.root, "open", "q-esc", "--criteria", "c", session=sid)
        h = Heimdall(self._default(), self.root, on_text=lambda s: None)
        h._escalate(sid)
        log = open(os.path.join(self.root, ".asgard", "quest", "q-esc.jsonl")).read()
        self.assertIn('"ESCALATE"', log)  # verdict 없던 기존 append는 조용히 거부되던 경로
        # ESCALATE 후 close 허용 (quest_log 계약)
        self.assertEqual(ql(self.root, "close", session=sid).returncode, 0)


class TestDeliveryAgents(unittest.TestCase):
    """딜리버리 계층 호스트 배선 — 템플릿 계약·소스 단일화, API 호출 없음."""

    def _tpl(self, name):
        from asgard.templates.roles import ROLE_AGENTS

        return dict(ROLE_AGENTS)[name]

    def test_library_has_roles_and_delivery(self):
        from asgard.templates.agent_models import AGENT_MODEL_DEFAULTS
        from asgard.templates.roles import ROLE_AGENTS

        names = {f for f, _ in ROLE_AGENTS}
        self.assertLessEqual(
            {
                f"asgard-{n}.md"
                for n in ("thinker", "worker", "verifier", "freyja", "thor", "eitri", "loki", "ullr", "mimir")
            },
            names,
        )
        roles = {name.removeprefix("asgard-").removesuffix(".md") for name in names}
        for host, defaults in AGENT_MODEL_DEFAULTS.items():
            self.assertEqual(set(defaults), roles, host)

    def test_claude_code_roles_pin_model_and_effort_by_work_type(self):
        # 사고·구현·판정하는 손은 inherit(세션 모델 추종), 읽기 전용 정찰·안내만 저비용 고정.
        expected = {
            "thinker": ("inherit", "high"),
            "worker": ("inherit", "high"),
            "verifier": ("inherit", "high"),
            "freyja": ("inherit", "high"),
            "thor-lead": ("inherit", "high"),
            "thor": ("inherit", "high"),
            "eitri": ("inherit", "high"),
            "loki": ("opus", "low"),
            "mimir": ("sonnet", "high"),
        }
        for role, (model, effort) in expected.items():
            fm = self._tpl(f"asgard-{role}.md").split("---")[1]
            self.assertIn(f"model: {model}", fm)
            self.assertIn(f"effort: {effort}", fm)

        ullr = self._tpl("asgard-ullr.md").split("---")[1]
        self.assertIn("model: haiku", ullr)
        self.assertNotIn("effort:", ullr)

    def test_caller_sweep_contract(self):
        # 숨은 caller 파손 방어 — worker는 편집 전 전수 나열, verifier는 diff 밖 증거 없는 PASS 무효.
        self.assertIn("Exhaustive usage sweep", self._tpl("asgard-worker.md"))
        v = self._tpl("asgard-verifier.md")
        self.assertIn("A PASS trapped in the diff is void", v)
        self.assertIn("even a 0-result finding is evidence", v)

    def test_delivery_frontmatter_matches_the_delegation_table(self):
        """도구 허용목록과 위임 표는 같은 사실을 두 자리에 적는다 — 갈리면 한쪽이 거짓말이다.

        표가 목표를 가진 역할에 `Agent` 가 없으면 계약만 있고 문이 없고, 표가 빈 역할에
        `Agent` 가 있으면 문만 있고 계약이 없다. 종전에는 프런트매터가 `disallowedTools: Agent`
        로 딜리버리 전문가를 봉인했고 표도 빈 집합이었다 — 이제 둘 다 아래층을 연다."""
        from asgard.hooks.subagent_gate import AGENT_TARGETS
        from asgard.templates.roles import ROLE_AGENTS

        for fname, body in ROLE_AGENTS:
            name = fname.removesuffix(".md")
            fm = body.split("---")[1]
            tools = fm.split("tools:")[1].splitlines()[0] if "tools:" in fm else ""
            self.assertNotIn("disallowedTools", fm, f"{name}: 봉인 대신 위임 표가 경계를 진다")
            has_agent = "Agent" in tools
            self.assertEqual(has_agent, bool(AGENT_TARGETS[name]), f"{name}: tools 의 Agent 유무와 위임 표가 어긋난다")
        # 읽기 전용 층은 Write·Edit 을 계속 못 든다 — 위임이 열려도 손은 안 열린다.
        for n in ("loki", "ullr", "mimir", "verifier", "thinker"):
            tools = self._tpl(f"asgard-{n}.md").split("---")[1].split("tools:")[1].splitlines()[0]
            self.assertNotIn("Write", tools)
            self.assertNotIn("Edit", tools)

    def test_trinity_agents_can_nest(self):
        # 모든 역할은 canonical least-privilege allowlist를 명시한다. Worker는 mutation + Agent,
        # verifier/thinker는 read/execute + Agent만 (CC 모드 B).
        self.assertIn("tools: Read, Grep, Glob, Bash, Write, Edit, NotebookEdit, Agent", self._tpl("asgard-worker.md"))
        self.assertIn("Agent", self._tpl("asgard-verifier.md").split("---")[1])
        thinker_fm = self._tpl("asgard-thinker.md").split("---")[1]
        self.assertIn("Agent", thinker_fm.split("tools:")[1].splitlines()[0])
        self.assertNotIn("tools:", thinker_fm.replace("tools: Read", ""))

    def test_heimdall_delivery_derives_from_templates(self):
        from asgard.agent.heimdall.roles import _DELIVERY

        self.assertEqual(sorted(_DELIVERY), ["eitri", "freyja", "loki", "mimir", "thor", "thor-lead"])
        for g, body in _DELIVERY.items():
            self.assertIn(f"asgard-{g}", body)
            self.assertNotIn("name:", body)  # frontmatter 누출 없음

    def test_agents_md_starts_main_worker_but_dispatches_conditional_roles(self):
        from asgard.templates.agents import agents_md

        guide = agents_md("p")
        self.assertIn("MAIN_WORKER", guide)
        self.assertIn("asgard-worker.md", guide)
        self.assertIn(
            "A separate Thinker is invoked only for explicit parallel decomposition and failure replanning", guide
        )
        self.assertIn(
            "the Verifier and parallel/separate Workers are invoked as the host's independent subagents", guide
        )
        self.assertIn("BASELINE_VERIFY", guide)

    def test_cursor_init_scaffolds_native_agents_and_lower_camel_hooks(self):
        from asgard.commands.setup import plan_files
        from asgard.templates.roles import ROLE_AGENTS

        with (
            mock.patch("asgard.templates.agent_models.load_global", return_value={}),
            mock.patch("asgard.templates.agent_models.load_project", return_value={}),
        ):
            files = dict(plan_files(cc=False, cursor=True, codex=False, root="/workspace")[0])
        agents = {path: body for path, body in files.items() if "/.cursor/agents/asgard-" in path}
        self.assertEqual(len(agents), len(ROLE_AGENTS))
        expected = {
            "thinker": "claude-fable-5-thinking-xhigh",
            "worker": "gpt-5.6-terra-medium",
            "verifier": "claude-opus-4-8-thinking-high",
            "freyja": "claude-sonnet-5-thinking-high",
            "thor-lead": "gpt-5.6-sol-high",
            "thor": "gpt-5.6-terra-high",
            "eitri": "gpt-5.6-terra-high",
            "loki": "claude-opus-4-8-thinking-high",
            "ullr": "gpt-5.6-terra-low",
            "mimir": "gpt-5.6-terra-medium",
        }
        for role, model in expected.items():
            self.assertIn(f'model: "{model}"', agents[f"/workspace/.cursor/agents/asgard-{role}.md"])
        worker = agents["/workspace/.cursor/agents/asgard-worker.md"]
        verifier = agents["/workspace/.cursor/agents/asgard-verifier.md"]
        self.assertIn("\nreadonly: false\n", worker)
        self.assertIn("\nreadonly: true\n", verifier)
        hooks = json.loads(files["/workspace/.cursor/hooks.json"])["hooks"]
        self.assertLessEqual({"preToolUse", "subagentStart", "subagentStop", "stop"}, set(hooks))
        self.assertIn("subagent-gate.py start", hooks["subagentStart"][0]["command"])
        self.assertIn("verifier-gate.py cursor", hooks["stop"][0]["command"])

    def test_codex_init_scaffolds_toml_agents_and_native_hooks(self):
        import tomllib

        from asgard.commands.setup import plan_files
        from asgard.templates.roles import ROLE_AGENTS

        with (
            mock.patch("asgard.templates.agent_models.load_global", return_value={}),
            mock.patch("asgard.templates.agent_models.load_project", return_value={}),
        ):
            files = dict(plan_files(cc=False, cursor=False, codex=True, root="/workspace")[0])
        agents = {path: body for path, body in files.items() if "/.codex/agents/asgard-" in path}
        self.assertEqual(len(agents), len(ROLE_AGENTS))
        parsed = {path.rsplit("/", 1)[-1].removesuffix(".toml"): tomllib.loads(body) for path, body in agents.items()}
        expected = {
            "asgard-thinker": ("gpt-5.6-sol", "xhigh"),
            "asgard-worker": ("gpt-5.6-terra", "medium"),
            "asgard-verifier": ("gpt-5.6-sol", "high"),
            "asgard-freyja": ("gpt-5.6-sol", "high"),
            "asgard-thor-lead": ("gpt-5.6-sol", "high"),
            "asgard-thor": ("gpt-5.6-terra", "high"),
            "asgard-eitri": ("gpt-5.6-terra", "high"),
            "asgard-loki": ("gpt-5.6-sol", "high"),
            "asgard-ullr": ("gpt-5.6-terra", "low"),
            "asgard-mimir": ("gpt-5.6-terra", "medium"),
        }
        for role, (model, effort) in expected.items():
            self.assertEqual(parsed[role]["model"], model)
            self.assertEqual(parsed[role]["model_reasoning_effort"], effort)

        worker = parsed["asgard-worker"]
        verifier = parsed["asgard-verifier"]
        self.assertNotIn("sandbox_mode", worker)
        self.assertEqual(verifier["sandbox_mode"], "read-only")
        self.assertIn("# asgard-worker", worker["developer_instructions"])
        config = tomllib.loads(files["/workspace/.codex/config.toml"])
        self.assertEqual(config["agents"]["max_depth"], 2)
        self.assertTrue(config["hooks"]["SubagentStart"])
        self.assertIn("verifier-gate.py", config["hooks"]["Stop"][0]["hooks"][0]["command"])

    def test_user_agent_model_overrides_apply_to_every_host(self):
        import tomllib

        from asgard import settings
        from asgard.commands.setup import plan_files

        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ, {"HOME": root}):
            os.makedirs(os.path.join(root, ".asgard"))
            settings.save_project(
                root,
                "agent_models",
                {
                    "claude-code": {"worker": {"model": "claude-custom", "effort": "low"}},
                    "cursor": {"worker": "cursor-custom"},
                    "codex": {"worker": {"model": "codex-custom", "effort": "xhigh"}},
                },
            )
            files = dict(plan_files(cc=True, cursor=True, codex=True, root=root)[0])
            claude = files[os.path.join(root, ".claude", "agents", "asgard-worker.md")]
            cursor = files[os.path.join(root, ".cursor", "agents", "asgard-worker.md")]
            codex = tomllib.loads(files[os.path.join(root, ".codex", "agents", "asgard-worker.toml")])

        self.assertIn('model: "claude-custom"', claude)
        self.assertIn('effort: "low"', claude)
        self.assertIn('model: "cursor-custom"', cursor)
        self.assertEqual((codex["model"], codex["model_reasoning_effort"]), ("codex-custom", "xhigh"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
