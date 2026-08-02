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
        self.assertTrue(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py replay q"))
        self.assertTrue(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py close"))
        self.assertTrue(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py ticket-claim --unit 1 --worker w1"))
        self.assertTrue(
            is_readonly_bash_safe(
                "python3 .claude/hooks/quest-log.py ticket-finish --unit 1 --claim-token opaque --status done"
            )
        )
        self.assertTrue(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py ticket-recover"))
        self.assertTrue(is_readonly_bash_safe("python3 .claude/hooks/quest-log.py verify-baseline"))
        # close --force는 관리적 해제(Odin 동의) — read-only 역할 권한이 아니다
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

    def test_readonly_allows_chained_observation(self):
        # 26-07-26 helios 실측: 허용 읽기끼리의 연결이 통째로 차단돼 차단 39건의 최다 사유였다.
        # 세그먼트마다 독립 판정하므로 연결은 새 권한을 만들지 않는다.
        self.assertTrue(is_readonly_bash_safe("ls && ls src"))
        self.assertTrue(is_readonly_bash_safe("ls; ls src"))
        self.assertTrue(is_readonly_bash_safe("git status --porcelain && echo marker && git diff"))
        self.assertTrue(is_readonly_bash_safe("ls src ||  ls ."))
        self.assertTrue(is_readonly_bash_safe("ls;"))
        self.assertTrue(is_readonly_bash_safe("find . -name '*.py' 2>/dev/null | head -20"))
        # 모노레포의 기본 관측 형태 — `cd sub && <읽기>`
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "sub"))
            self.assertTrue(is_readonly_bash_safe("cd sub && ls -la", root))
            self.assertTrue(is_readonly_bash_safe("cd sub; grep -rn x .", root))
            self.assertFalse(is_readonly_bash_safe("cd /etc && ls", root))  # 경로 이탈은 그대로 차단
            self.assertFalse(is_readonly_bash_safe("cd sub && rm -rf .", root))
        self.assertTrue(is_readonly_bash_safe('python3 -c "print(1)" < /dev/null'))
        self.assertTrue(is_readonly_bash_safe("cat x 2>&1 | head -3"))
        self.assertTrue(
            is_readonly_bash_safe("echo '{}' | python3 .claude/hooks/quest-log.py append --event work 2>&1 | head -5")
        )
        # 연결이 열려도 각 세그먼트 판정은 그대로 — 하나라도 쓰기면 전체 차단
        self.assertFalse(is_readonly_bash_safe("ls && rm -rf src"))
        self.assertFalse(is_readonly_bash_safe("ls; echo x > out.txt"))
        self.assertFalse(is_readonly_bash_safe("ls & sleep 5"))
        self.assertFalse(is_readonly_bash_safe("cat x > /etc/passwd"))
        self.assertFalse(is_readonly_bash_safe("ls && cat /etc/passwd"))

    def test_quest_bookkeeping_survives_host_path_and_trailing_line(self):
        # 26-07-26 실측: Worker가 quest를 열지 못해 같은 명령을 형태만 바꿔 5회 재시도했다 —
        # ① 호스트가 넘긴 절대경로 형태 ② 관측 뒤에 붙은 `\necho "EXIT:$?"` 한 줄.
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".claude", "hooks"))
            absolute = os.path.join(root, ".claude", "hooks", "quest-log.py")
            self.assertTrue(is_readonly_bash_safe(f'python3 {absolute} open q1 --criteria "x"', root))
            self.assertTrue(
                is_readonly_bash_safe('python3 .claude/hooks/quest-log.py open q1 --criteria "a"\necho "EXIT:$?"', root)
            )
            # 프로젝트 밖 같은 이름의 스크립트는 신뢰 대상이 아니다
            self.assertFalse(is_readonly_bash_safe("python3 /etc/hooks/quest-log.py open q1", root))
            # 줄바꿈이 구분자가 되어도 히어독과 쓰기 세그먼트는 그대로 막힌다
            self.assertFalse(is_readonly_bash_safe("cat <<EOF\nx\nEOF", root))
            self.assertFalse(is_readonly_bash_safe("ls\nrm -rf src", root))
            self.assertFalse(is_readonly_bash_safe("python3 -c \"import os\nos.remove('x')\"", root))

    def test_readonly_stream_editors(self):
        # sed/awk는 -i 없이는 stdout 전용 관측이다. 스크립트 인자를 경로로 오독해 `/`로 시작하는
        # 정규식이 차단됐던 것도 함께 봉합 (26-07-26 실측).
        self.assertTrue(is_readonly_bash_safe("sed -n '1,5p' README.md"))
        self.assertTrue(is_readonly_bash_safe("sed -n '/error/p' README.md"))
        self.assertTrue(is_readonly_bash_safe("awk '/^\\.dark \\{/,0' app.css"))
        self.assertTrue(is_readonly_bash_safe("awk -v n=1 '{print $1}' README.md"))
        self.assertFalse(is_readonly_bash_safe("sed -i 's/a/b/' README.md"))
        self.assertFalse(is_readonly_bash_safe("sed -i.bak 's/a/b/' README.md"))
        self.assertFalse(is_readonly_bash_safe("sed '1w /tmp/leak' README.md"))  # w = 파일 쓰기
        self.assertFalse(is_readonly_bash_safe("sed '1r /etc/passwd' README.md"))  # r = 경로 검사 우회
        self.assertFalse(is_readonly_bash_safe("sed -f script.sed README.md"))  # 스크립트 파일 = 판정 불가
        self.assertFalse(is_readonly_bash_safe("awk '{print > \"out.txt\"}' README.md"))
        self.assertFalse(is_readonly_bash_safe("awk '{system(\"rm x\")}' README.md"))
        self.assertFalse(is_readonly_bash_safe("awk '{getline x < \"/etc/passwd\"; print x}' README.md"))
        self.assertFalse(is_readonly_bash_safe("sed -n '1,5p' /etc/passwd"))
        self.assertFalse(is_readonly_bash_safe("awk '{print}' /etc/passwd"))

    def test_readonly_node_and_unit_workspace(self):
        import tempfile

        # 다중 테스트 경로 = pytest 다중 인자와 동형
        self.assertTrue(is_readonly_bash_safe("node --test tests/a.check.mjs tests/b.check.mjs"))
        self.assertFalse(is_readonly_bash_safe("node --test tests/a.check.mjs scripts/build.mjs"))
        self.assertFalse(is_readonly_bash_safe("node scripts/build.mjs"))
        # 하네스가 만든 격리 배정 작업공간은 프로젝트 밖이지만 하네스 소유 — 관측을 막지 않는다
        workspace = os.path.join(tempfile.gettempdir(), "asgard-unit-u1-abcdef", "tests", "a.check.mjs")
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(is_readonly_bash_safe(f"node --test {workspace}", root))
            self.assertTrue(is_readonly_bash_safe(f"ls {os.path.dirname(workspace)}", root))
            other = os.path.join(tempfile.gettempdir(), "not-a-unit-ws", "a.check.mjs")
            self.assertFalse(is_readonly_bash_safe(f"node --test {other}", root))

    def test_readonly_python_smoke_lane(self):
        # Verifier 계약("대표 함수 호출 스모크")의 실행 통로 — 쓰기 없는 python -c는 허용,
        # 쓰기·프로세스·네트워크 API는 fail-closed (26-07-21: 차단 변형 재시도로 턴 소진 봉합)
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

    def test_role_owns_the_policy_not_the_thread(self):
        """규율은 역할에 붙는다 — 읽기전용 역할은 어떤 명령이든 차단, 메인 세션은 배정된 역할을
        직접 수행하는 자리(MAIN_WORKER)라 쓰기가 그 역할의 몫이다.

        개인 메모리 계약 명령(query·ingest)만 메인 스레드에 뚫어 주던 예외(26-07-23)는 이 규칙에
        흡수돼 사라졌다 — 예외가 필요했던 이유가 "신원 없음 = 읽기전용"이라는 전제였고, 그 전제가
        모드 B의 단일 변경을 교착시켰다 (subagent-gate가 유닛 마커 없는 Worker 디스패치를 거부해
        우회로도 없다). 퀘스트 귀속은 write-sentinel + Stop 게이트 소관이다."""
        import io
        import json as j
        from unittest import mock

        from asgard.hooks import readonly_guard

        def verdict(agent: str, command: str) -> bool:
            payload = j.dumps({"agent_type": agent, "tool_name": "Bash", "tool_input": {"command": command}})
            with mock.patch("sys.stdin", io.StringIO(payload)):
                try:
                    readonly_guard.main()
                except SystemExit as exc:
                    return exc.code != 2
            return True

        self.assertTrue(verdict("", 'asgard memory query "닉네임"'))  # 메인 세션 = 배정된 역할 수행
        self.assertTrue(verdict("", "asgard memory ingest '사실' --kind decision"))
        self.assertTrue(verdict("", "asgard memory remove page"))
        self.assertTrue(verdict("asgard-worker", "touch new_file.py"))  # 쓰기 역할은 쓴다
        self.assertFalse(verdict("asgard-verifier", 'asgard memory query "닉네임"'))  # 게이트 역할 불변
        self.assertFalse(verdict("asgard-loki", "asgard memory ingest '사실'"))
        self.assertFalse(verdict("asgard-mimir", "touch new_file.py"))

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

    def test_readonly_role_has_a_node_verification_lane(self):
        """JS/TS 저장소에서 판정자가 아무것도 실행하지 못하면 배달물은 늘 "실행 증거 없음"이다.

        실측(26-07-26 helios): node·npm·python -c subprocess 전 레인이 막혀 판정이 정적 읽기로
        후퇴했다. Python 쪽 `python tests/x.py`와 대칭인 통로만 연다 — 인라인 실행(-e/--eval)은
        쓰기 휴리스틱이 없어 계속 막힌다."""
        from asgard.hooks.readonly_guard import is_readonly_bash_safe

        for command in (
            "node --check scripts/build.mjs",
            "node --test tests/unit/build.check.mjs",
            "node tests/unit/build.check.mjs",
            "node --test",
        ):
            self.assertTrue(is_readonly_bash_safe(command), command)
        for command in (
            "node scripts/build.mjs",  # tests/ 밖 스크립트 실행 = 임의 실행
            "node -e \"require('fs').writeFileSync('x','y')\"",
            "node --eval 1",
            "node --check a.mjs b.mjs",
        ):
            self.assertFalse(is_readonly_bash_safe(command), command)

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

        from cli_boundary import run_cli

        result = run_cli("tools", "list", "--role", "worker", "--json")
        self.assertEqual(result.exit_code, 0, result.stderr)
        self.assertEqual(result.stderr, "")  # --json은 stdout 하나로 답한다
        data = json.loads(result.stdout)
        self.assertEqual(data["role"], "worker")
        self.assertIn("bash", data["native"])
        self.assertIn("str_replace_based_edit_tool", data["native"])
        self.assertIn("Write", data["claude_code"])
        self.assertIn("mutate", data["capabilities"])

    def test_tools_list_rejects_unknown_role(self):
        """`CliRunner`가 아니라 사용자 경계로 잰다 — 전자는 예외를 삼켜 1로 적고, 사용자는 2를 받는다."""
        import json

        from cli_boundary import run_cli

        result = run_cli("tools", "list", "--role", "odin", "--json")
        self.assertEqual(result.exit_code, 2)
        # --json을 받은 실행은 실패도 stdout의 봉투로 답한다 — 사람 문장이 stderr로 새면 파서가 둘을 봐야 한다.
        self.assertEqual(result.stderr, "")
        self.assertIn("error", json.loads(result.stdout))

    def test_tools_list_supports_installed_ullr_role(self):
        from cli_boundary import run_cli

        result = run_cli("tools", "list", "--role", "ullr", "--json")
        self.assertEqual(result.exit_code, 0, result.stderr)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
