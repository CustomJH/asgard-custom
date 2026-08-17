#!/usr/bin/env python3
"""가드 배선 — 파괴적 bash·비밀·읽기 전용 세션.

실행: uv run pytest tests/agent  (asgard 패키지 임포트 필요 — subprocess가 -m으로 훅 실행)
"""

import os
import unittest

from agent.agent_base import Base
from asgard.agent import tools as T


class TestBashDestructiveGuard(Base):
    """비-git 파괴 명령 가드 (Canon 3) — 루트 밖 rm -rf 차단, 루트 안은 허용."""

    def test_rm_rf_outside_root_blocked(self):
        for cmd in ("rm -rf /tmp/x", "rm -rf ~/stuff", "rm -rf ../sibling", "cd sub && rm -rf /"):
            with self.assertRaises(T.ToolError, msg=cmd):
                T.run_bash(self.root, {"command": cmd})

    def test_rm_rf_inside_root_allowed(self):
        os.makedirs(os.path.join(self.root, "build"))
        _, code = T.run_bash(self.root, {"command": "rm -rf build"})
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, "build")))

    def test_device_destruction_blocked(self):
        for cmd in ("mkfs.ext4 /dev/sda1", "dd if=/dev/zero of=/dev/sda"):
            with self.assertRaises(T.ToolError, msg=cmd):
                T.run_bash(self.root, {"command": cmd})

    def test_scope_escape_and_obfuscated_control_path_blocked(self):
        os.makedirs(os.path.join(self.root, ".asgard"))
        for cmd in (
            "printf escaped > ../outside.txt",
            "printf bypassed > .as''gard/policy.txt",
            'target=../outside.txt; printf escaped > "$target"',
        ):
            with self.assertRaises(T.ToolError, msg=cmd):
                T.run_bash(self.root, {"command": cmd})
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.root), "outside.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "policy.txt")))

    def test_single_quoted_dollar_remains_literal(self):
        out, code = T.run_bash(self.root, {"command": "printf '%s' 'value$'"})
        self.assertEqual((out, code), ("value$", 0))


class TestSecretGuardWiring(Base):
    """secret-guard 훅 배선 (Canon Law 4) — 네이티브 editor write도 mode B와 같은 차단 지점."""

    def test_env_file_write_blocked(self):
        with self.assertRaises(T.ToolError):
            T.run_editor(self.root, {"command": "create", "path": ".env", "file_text": "X=1\n"}, [])

    def test_secret_content_blocked(self):
        with self.assertRaises(T.ToolError):
            T.run_editor(
                self.root,
                {"command": "create", "path": "config.py", "file_text": 'KEY = "AKIA' + "A" * 16 + '"\n'},
                [],
            )

    def test_template_env_allowed(self):
        w = []
        T.run_editor(self.root, {"command": "create", "path": ".env.example", "file_text": "X=placeholder\n"}, w)
        self.assertEqual(w, [".env.example"])


class TestReadonlySession(Base):
    """역할→도구 구조 강제 — readonly 세션은 editor write를 거부한다 (thinker/verifier/loki)."""

    def _session(self, readonly):
        from asgard.agent.session import AgentSession
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        return AgentSession(None, rp, self.root, "sys", readonly=readonly)

    def test_readonly_rejects_editor_write_allows_view(self):
        from asgard.agent.session import SessionResult, _Call

        s = self._session(readonly=True)
        r = SessionResult(text="", stop_reason="")
        call = _Call("1", "str_replace_based_edit_tool", {"command": "create", "path": "x.txt", "file_text": "x"})
        out, err = s._execute(call, r)
        self.assertTrue(err)
        self.assertEqual(r.writes, [])
        self.assertFalse(os.path.exists(os.path.join(self.root, "x.txt")))
        out, err = s._execute(_Call("2", "str_replace_based_edit_tool", {"command": "view", "path": "f.txt"}), r)
        self.assertFalse(err)
        self.assertIn("base", out)

    def test_session_cwd_is_tool_workspace_while_root_remains_canonical(self):
        from asgard.agent.session import AgentSession, SessionResult, _Call
        from asgard.providers import PROVIDERS, ResolvedProvider

        workspace = os.path.join(self.root, "unit-workspace")
        os.makedirs(workspace)
        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        session = AgentSession(None, rp, self.root, "sys", cwd=workspace)
        result = SessionResult(text="", stop_reason="")
        _, error = session._execute(
            _Call("1", "str_replace_based_edit_tool", {"command": "create", "path": "unit.txt", "file_text": "x"}),
            result,
        )
        self.assertFalse(error)
        self.assertEqual(session.root, self.root)
        self.assertEqual(session.cwd, workspace)
        self.assertFalse(os.path.exists(os.path.join(self.root, "unit.txt")))
        self.assertEqual(open(os.path.join(workspace, "unit.txt")).read(), "x")

    def test_tool_preview_keeps_live_status_specific_and_single_line(self):
        session = self._session(readonly=False)
        self.assertEqual(session._tool_preview("Read", {"file_path": "src/app.py"}), ("→", "read src/app.py"))
        self.assertEqual(
            session._tool_preview("Grep", {"pattern": "needle", "path": "src"}),
            ("✱", 'grep "needle" in src'),
        )
        self.assertEqual(session._tool_preview("apply_patch", {"patch_text": "many\nlines"}), ("✎", "apply patch"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
