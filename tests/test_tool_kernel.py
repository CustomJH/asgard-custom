"""Canonical Tool Kernel contracts shared by native and Claude Code modes."""

import os
import tempfile
import unittest

from asgard.agent.tool_kernel import (
    ToolContext,
    ToolRegistry,
    ToolSpec,
    build_session_registry,
    cc_tools_for_role,
    execute_tool,
    to_openai_tool,
)
from asgard.hooks.readonly_guard import _path_token_targets_control, is_readonly_bash_safe


class TestRegistry(unittest.TestCase):
    def test_control_plane_alias_is_detected_after_symlink_resolution(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".claude"))
            os.symlink(".claude", os.path.join(root, "control"))
            self.assertTrue(_path_token_targets_control(root, "control/settings.json", (".claude", ".asgard")))
            self.assertTrue(_path_token_targets_control(root, "--output=control/settings.json", (".claude", ".asgard")))

    def test_readonly_shell_parser_respects_quoted_pipes_and_trinity_metadata(self):
        self.assertTrue(is_readonly_bash_safe('grep -nE "add_parser|next_role" hook.py | head -20'))
        self.assertTrue(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py open q --criteria x"))
        self.assertTrue(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py close"))
        self.assertTrue(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py ticket-claim --unit 1 --worker w1"))
        self.assertTrue(
            is_readonly_bash_safe(
                "python3 .claude/hooks/quest-log.py ticket-finish --unit 1 --claim-token opaque --status done"
            )
        )
        self.assertTrue(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py ticket-recover"))
        self.assertTrue(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py verify-baseline"))
        # close --force 는 관리적 해제(Odin 동의) — read-only 역할 권한이 아니다
        self.assertFalse(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py close --force"))
        self.assertFalse(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py close q1 --force"))
        self.assertTrue(is_readonly_bash_safe("python3 .claude/hooks/verifier-gate.py"))
        self.assertFalse(is_readonly_bash_safe("echo x | tee changed.py"))
        self.assertFalse(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py state | tee changed.py"))
        self.assertFalse(is_readonly_bash_safe("cat file |& tee changed.py"))
        self.assertFalse(is_readonly_bash_safe("cat $(printf secret)"))
        self.assertFalse(is_readonly_bash_safe("python3 -c \"open('PWNED', 'w').write('x')\" quest-log.py open"))
        self.assertFalse(is_readonly_bash_safe("python3 malicious.py quest-log.py open q"))
        self.assertFalse(is_readonly_bash_safe("python3 /tmp/.claude/hooks/quest-log.py open q"))
        self.assertTrue(is_readonly_bash_safe("asgard skills show asgard-mimir-flow"))
        self.assertTrue(is_readonly_bash_safe("asgard skills show asgard-worker-testing"))
        self.assertFalse(is_readonly_bash_safe("asgard skills resolve --agent mimir task"))
        self.assertFalse(is_readonly_bash_safe("asgard skills show ../escape"))

    def test_readonly_python_smoke_lane(self):
        # Verifier 계약("대표 함수 호출 스모크")의 실행 통로 — 쓰기 없는 python -c 는 허용,
        # 쓰기·프로세스·네트워크 API 는 fail-closed (26-07-21: 차단 변형 재시도로 턴 소진 봉합)
        self.assertTrue(is_readonly_bash_safe("python3 -c \"import ast; ast.parse(open('x.py').read())\""))
        self.assertTrue(is_readonly_bash_safe('python3 -c "from asgard import ui; print(ui.stream_width())"'))
        self.assertTrue(is_readonly_bash_safe("python3 --version"))
        self.assertTrue(is_readonly_bash_safe("python3 -m py_compile src/mod.py"))
        self.assertTrue(is_readonly_bash_safe('uv run python -c "print(1)"'))
        self.assertTrue(
            is_readonly_bash_safe('COLUMNS=130 python3 -c "import shutil; print(shutil.get_terminal_size())"')
        )
        self.assertTrue(is_readonly_bash_safe('env COLUMNS=500 LINES=40 python3 -c "print(1)"'))
        self.assertFalse(is_readonly_bash_safe("python3 -c \"open('x','w').write('hi')\""))
        self.assertFalse(is_readonly_bash_safe("python3 -c \"import shutil; shutil.rmtree('src')\""))
        self.assertFalse(is_readonly_bash_safe("python3 -c \"import subprocess; subprocess.run(['rm','x'])\""))
        self.assertFalse(is_readonly_bash_safe("python3 -c \"import os; os.remove('x')\""))
        self.assertFalse(is_readonly_bash_safe("python3 -c \"import pathlib; pathlib.Path('x').write_text('y')\""))

    def test_readonly_git_rejects_executable_diff_helpers(self):
        self.assertTrue(is_readonly_bash_safe("git diff -- README.md"))
        self.assertFalse(is_readonly_bash_safe("git diff --ext-diff"))
        self.assertFalse(is_readonly_bash_safe("git show --textconv HEAD"))
        self.assertFalse(is_readonly_bash_safe("git -c diff.external='touch PWNED' diff"))
        self.assertFalse(is_readonly_bash_safe("git -cdiff.demo.textconv='touch PWNED' diff"))
        self.assertFalse(is_readonly_bash_safe("git --config-env=diff.external=HELPER diff"))
        self.assertFalse(is_readonly_bash_safe("git grep --open-files-in-pager='touch PWNED' needle"))
        self.assertFalse(is_readonly_bash_safe("git grep --open-files-in-pager 'touch PWNED' needle"))
        self.assertFalse(is_readonly_bash_safe("git --paginate log"))

    def test_duplicate_name_is_rejected(self):
        registry = ToolRegistry()
        spec = ToolSpec("x", "inspect", {"name": "x", "input_schema": {"type": "object"}}, lambda c, a: "ok")
        registry.register(spec)
        with self.assertRaises(ValueError):
            registry.register(spec)

    def test_unavailable_tool_is_not_exposed(self):
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                "missing",
                "inspect",
                {"name": "missing", "input_schema": {"type": "object"}},
                lambda c, a: "no",
                available=lambda _ctx: False,
            )
        )
        self.assertEqual(registry.schemas(ToolContext(root="/tmp", role="worker")), [])

    def test_schema_order_is_stable(self):
        registry = ToolRegistry()
        for name in ("z", "a"):
            registry.register(
                ToolSpec(name, "inspect", {"name": name, "input_schema": {"type": "object"}}, lambda c, a: name)
            )
        names = [s["name"] for s in registry.schemas(ToolContext(root="/tmp", role="worker"))]
        self.assertEqual(names, ["a", "z"])

    def test_resolved_schema_is_a_deep_frozen_copy(self):
        registry = ToolRegistry()
        source_schema = {
            "name": "x",
            "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
        registry.register(
            ToolSpec(
                "x",
                "inspect",
                source_schema,
                lambda _ctx, _args: "ok",
            )
        )
        source_schema["input_schema"]["properties"]["q"]["type"] = "boolean"
        exposed = registry.schemas(ToolContext(root="/tmp", role="worker"))
        exposed[0]["input_schema"]["properties"]["q"]["type"] = "integer"
        fresh = registry.schemas(ToolContext(root="/tmp", role="worker"))
        self.assertEqual(fresh[0]["input_schema"]["properties"]["q"]["type"], "string")

    def test_broken_dynamic_policy_fails_closed(self):
        registry = ToolRegistry()

        def broken(_args):
            raise RuntimeError("bad policy")

        registry.register(
            ToolSpec("broken", broken, {"name": "broken", "input_schema": {"type": "object"}}, lambda _c, _a: "no")
        )
        ctx = ToolContext(root="/tmp", role="worker")
        self.assertFalse(registry.state("broken", ctx).callable)
        self.assertEqual(registry.schemas(ctx), [])

    def test_registered_available_enabled_visible_callable_are_distinct(self):
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                "disabled",
                "inspect",
                {"name": "disabled", "input_schema": {"type": "object"}},
                lambda _ctx, _args: "no",
                enabled=False,
            )
        )
        state = registry.state("disabled", ToolContext(root="/tmp", role="worker"))
        self.assertTrue(state.registered)
        self.assertTrue(state.available)
        self.assertFalse(state.enabled)
        self.assertTrue(state.visible)
        self.assertFalse(state.callable)
        self.assertEqual(registry.schemas(ToolContext(root="/tmp", role="worker")), [])


class TestCapabilityPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        with open(os.path.join(self.root, "base.txt"), "w", encoding="utf-8") as f:
            f.write("base\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_thinker_can_view_but_cannot_mutate(self):
        registry = build_session_registry()
        ctx = ToolContext(root=self.root, role="thinker")
        viewed = execute_tool(
            registry,
            "str_replace_based_edit_tool",
            {"command": "view", "path": "base.txt"},
            ctx,
        )
        self.assertFalse(viewed.is_error)
        self.assertIn("base", viewed.content)

        denied = execute_tool(
            registry,
            "str_replace_based_edit_tool",
            {"command": "create", "path": "x.txt", "file_text": "x"},
            ctx,
        )
        self.assertTrue(denied.is_error)
        self.assertEqual(denied.status, "blocked")
        self.assertFalse(os.path.exists(os.path.join(self.root, "x.txt")))

    def test_worker_mutation_records_write(self):
        registry = build_session_registry()
        writes: list[str] = []
        ctx = ToolContext(root=self.root, role="worker", writes=writes)
        result = execute_tool(
            registry,
            "str_replace_based_edit_tool",
            {"command": "create", "path": "x.txt", "file_text": "x"},
            ctx,
        )
        self.assertFalse(result.is_error)
        self.assertEqual(writes, ["x.txt"])

    def test_readonly_role_bash_is_allowlist_enforced(self):
        registry = build_session_registry()
        ctx = ToolContext(root=self.root, role="verifier", readonly=True)
        safe = execute_tool(registry, "bash", {"command": "pwd"}, ctx)
        self.assertEqual(safe.status, "ok")
        denied = execute_tool(registry, "bash", {"command": "printf hacked > base.txt"}, ctx)
        self.assertEqual(denied.status, "blocked")
        for command in ("find . -delete", "git branch new-name", "ruff check --fix", "cargo fmt"):
            self.assertEqual(execute_tool(registry, "bash", {"command": command}, ctx).status, "blocked", command)
        with open(os.path.join(self.root, "base.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "base\n")

    def test_builtin_input_validation_runs_before_handlers(self):
        registry = build_session_registry()
        ctx = ToolContext(root=self.root, role="worker")
        self.assertEqual(execute_tool(registry, "bash", {"command": 42}, ctx).status, "invalid_input")
        self.assertEqual(
            execute_tool(registry, "str_replace_based_edit_tool", {"command": "view"}, ctx).status,
            "invalid_input",
        )

    def test_unknown_custom_tool_defaults_to_mutate_unless_declared(self):
        schema = {"name": "custom", "input_schema": {"type": "object"}}
        registry = build_session_registry([schema], {"custom": lambda _args: "ok"})
        readonly = ToolContext(root=self.root, role="verifier", readonly=True)
        self.assertEqual(execute_tool(registry, "custom", {}, readonly).status, "blocked")
        declared = {**schema, "x-asgard-capability": "inspect"}
        registry = build_session_registry([declared], {"custom": lambda _args: "ok"})
        self.assertEqual(execute_tool(registry, "custom", {}, readonly).status, "ok")

    def test_thinker_alt_has_same_inspection_surface_as_thinker(self):
        registry = build_session_registry()

        def names(role):
            return {s["name"] for s in registry.schemas(ToolContext(root=self.root, role=role))}

        self.assertEqual(names("thinker_alt"), names("thinker"))

    def test_unknown_and_crashing_tools_are_normalized(self):
        registry = ToolRegistry()
        ctx = ToolContext(root=self.root, role="worker")
        missing = execute_tool(registry, "none", {}, ctx)
        self.assertTrue(missing.is_error)
        self.assertEqual(missing.status, "not_found")

        def boom(_ctx, _args):
            raise RuntimeError("boom")

        registry.register(ToolSpec("boom", "inspect", {"name": "boom", "input_schema": {"type": "object"}}, boom))
        crashed = execute_tool(registry, "boom", {}, ctx)
        self.assertTrue(crashed.is_error)
        self.assertEqual(crashed.status, "error")
        self.assertIn("boom", crashed.content)

    def test_invalid_arguments_are_rejected_before_handler(self):
        calls = []
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                "checked",
                "inspect",
                {
                    "name": "checked",
                    "input_schema": {
                        "type": "object",
                        "properties": {"count": {"type": "integer"}},
                        "required": ["count"],
                    },
                },
                lambda _ctx, args: calls.append(args) or "ok",
            )
        )
        missing = execute_tool(registry, "checked", {}, ToolContext(root=self.root, role="worker"))
        wrong = execute_tool(
            registry,
            "checked",
            {"count": "one"},
            ToolContext(root=self.root, role="worker"),
        )
        self.assertEqual((missing.status, wrong.status), ("invalid_input", "invalid_input"))
        self.assertEqual(calls, [])


class TestProviderAdapters(unittest.TestCase):
    def test_openai_adapter_uses_canonical_schema(self):
        schema = {
            "name": "verdict",
            "description": "submit",
            "input_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        }
        self.assertEqual(
            to_openai_tool(schema),
            {
                "type": "function",
                "function": {
                    "name": "verdict",
                    "description": "submit",
                    "parameters": schema["input_schema"],
                },
            },
        )


class TestAgentSessionIntegration(unittest.TestCase):
    TOOL = {
        "name": "verdict",
        "description": "submit",
        "input_schema": {"type": "object", "properties": {}},
    }

    def _session(self, role="worker", readonly=False):
        from asgard.agent.session import AgentSession
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        return AgentSession(
            None,
            rp,
            "/tmp",
            "sys",
            extra_tools=[self.TOOL],
            tool_handlers={"verdict": lambda _args: "ok"},
            role=role,
            readonly=readonly,
        )

    def test_session_owns_registry_and_freezes_visible_schemas(self):
        worker = self._session("worker")
        verifier = self._session("verifier", readonly=True)
        self.assertIsInstance(worker.registry, ToolRegistry)
        self.assertNotIn("verdict", [tool["name"] for tool in worker.tools])
        self.assertIn("verdict", [tool["name"] for tool in verifier.tools])

    def test_session_execute_uses_canonical_result(self):
        from asgard.agent.session import SessionResult, _Call

        session = self._session("verifier", readonly=True)
        result = SessionResult(text="", stop_reason="")
        out, error = session._execute(_Call("1", "verdict", {}), result)
        self.assertEqual((out, error), ("ok", False))
        self.assertEqual(result.tool_calls, [{"name": "verdict", "input": {}}])

    def test_readonly_remains_enforced_even_with_mutating_role(self):
        from asgard.agent.session import SessionResult, _Call

        session = self._session("worker", readonly=True)
        result = SessionResult(text="", stop_reason="")
        path = "asgard-readonly-kernel-test.txt"
        full = os.path.join("/tmp", path)
        if os.path.exists(full):
            os.unlink(full)
        out, error = session._execute(
            _Call("1", "str_replace_based_edit_tool", {"command": "create", "path": path, "file_text": "no"}),
            result,
        )
        self.assertTrue(error)
        self.assertIn("mutate", out)
        self.assertFalse(os.path.exists(full))


class TestClaudeCodePolicy(unittest.TestCase):
    def test_role_tool_surfaces_are_least_privilege(self):
        self.assertEqual(cc_tools_for_role("thinker"), ("Read", "Grep", "Glob", "Bash", "Agent"))
        self.assertEqual(
            cc_tools_for_role("worker"),
            ("Read", "Grep", "Glob", "Bash", "Write", "Edit", "NotebookEdit", "Agent"),
        )
        self.assertEqual(cc_tools_for_role("verifier"), ("Read", "Grep", "Glob", "Bash", "Agent"))
        self.assertEqual(cc_tools_for_role("loki"), ("Read", "Grep", "Glob", "Bash"))
        self.assertNotIn("Agent", cc_tools_for_role("freyja"))
        self.assertNotIn("Agent", cc_tools_for_role("thor"))

    def test_role_markdown_matches_canonical_policy(self):
        from asgard.templates.roles import ROLE_AGENTS

        roles = dict(ROLE_AGENTS)
        for role in ("thinker", "worker", "verifier", "freyja", "thor", "loki", "ullr"):
            frontmatter = roles[f"asgard-{role}.md"].split("---", 2)[1]
            expected = "tools: " + ", ".join(cc_tools_for_role(role))
            self.assertIn(expected, frontmatter, role)


class TestToolCLI(unittest.TestCase):
    def test_tools_list_reports_native_and_cc_surfaces(self):
        import json

        from typer.testing import CliRunner

        from asgard.cli import app

        result = CliRunner().invoke(app, ["tools", "list", "--role", "worker", "--json"])
        self.assertEqual(result.exit_code, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["role"], "worker")
        self.assertIn("bash", data["native"])
        self.assertIn("str_replace_based_edit_tool", data["native"])
        self.assertIn("Write", data["claude_code"])
        self.assertIn("mutate", data["capabilities"])

    def test_tools_list_rejects_unknown_role(self):
        from typer.testing import CliRunner

        from asgard.cli import app

        result = CliRunner().invoke(app, ["tools", "list", "--role", "odin", "--json"])
        self.assertEqual(result.exit_code, 2)

    def test_tools_list_supports_installed_ullr_role(self):
        from typer.testing import CliRunner

        from asgard.cli import app

        result = CliRunner().invoke(app, ["tools", "list", "--role", "ullr", "--json"])
        self.assertEqual(result.exit_code, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
