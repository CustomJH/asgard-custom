"""작업 뿌리 — 저장소 하나가 곧 작업 경계라는 가정이 깨지는 자리들.

여기서 보는 것은 셋이다. 선언되지 않은 저장소 밖 경로는 그대로 막히는가, 선언된 자리는
열리는가, 그리고 열린 자리 안에서도 스캐폴드(`.claude`/`.asgard`)는 여전히 막히는가.
스튜디오의 개인 작업 공간은 `~/.asgard/studio/workspace`라 경로에 `.asgard`가 들어 있다 —
그 한 글자 때문에 창의 기본 자리에서 쓰기가 한 건도 안 통하던 것이 이 파일의 출발점이다.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from unittest import mock

from asgard.hooks import readonly_guard


def _run(payload: dict, argv: list[str] | None = None) -> tuple[int, str, str]:
    """훅을 in-process로 돌린 (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
        mock.patch("sys.stdout", out),
        mock.patch("sys.stderr", err),
        mock.patch("sys.argv", ["hook", *(argv or [])]),
    ):
        try:
            readonly_guard.main()
            code = 0
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


def _write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


class Sandboxed(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.repo = os.path.join(base, "repo")
        self.pair = os.path.join(base, "pair-repo")
        self.stranger = os.path.join(base, "stranger")
        for directory in (self.repo, self.pair, self.stranger):
            os.makedirs(directory)
        self.addCleanup(self.tmp.cleanup)
        # 훅은 세션 뿌리 없이도 CLAUDE_PROJECT_DIR을 뿌리로 집는다 — 테스트가 사용자의 실제
        # 프로젝트를 뿌리로 끌어들이지 않게 지운다.
        patch = mock.patch.dict(os.environ, {"HOME": base}, clear=False)
        patch.start()
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        self.addCleanup(patch.stop)

    def edit(self, path: str, cwd: str | None = None) -> tuple[int, str, str]:
        return _run({"cwd": cwd or self.repo, "tool_name": "Edit", "tool_input": {"file_path": path}})

    def bash(self, command: str, cwd: str | None = None) -> tuple[int, str, str]:
        return _run({"cwd": cwd or self.repo, "tool_name": "Bash", "tool_input": {"command": command}})


class TestUndeclaredStaysClosed(Sandboxed):
    def test_outside_path_is_blocked(self) -> None:
        code, _, err = self.edit(os.path.join(self.stranger, "app.js"))
        self.assertEqual(code, 2)
        self.assertIn("outside every work root", err)

    def test_refusal_names_the_declaration(self) -> None:
        _, _, err = self.edit(os.path.join(self.stranger, "app.js"))
        self.assertIn("additional_roots", err)
        self.assertIn("additionalDirectories", err)
        self.assertIn(self.repo, err)  # 지금 서 있는 뿌리를 같이 말해야 어디가 밖인지 안다

    def test_inside_path_is_allowed(self) -> None:
        self.assertEqual(self.edit(os.path.join(self.repo, "src", "app.js"))[0], 0)


class TestDeclaredRootOpens(Sandboxed):
    def test_asgard_setting_opens_a_second_repo(self) -> None:
        blocked = self.edit(os.path.join(self.pair, "src", "api.py"))
        self.assertEqual(blocked[0], 2)
        _write(
            os.path.join(self.repo, ".asgard", "asgard-setting-project.json"),
            {"paths": {"additional_roots": [self.pair]}},
        )
        self.assertEqual(self.edit(os.path.join(self.pair, "src", "api.py"))[0], 0)

    def test_claude_additional_directories_open_it_too(self) -> None:
        _write(
            os.path.join(self.repo, ".claude", "settings.json"),
            {"permissions": {"additionalDirectories": [self.pair]}},
        )
        self.assertEqual(self.edit(os.path.join(self.pair, "src", "api.py"))[0], 0)

    def test_relative_declaration_resolves_against_the_session_root(self) -> None:
        _write(
            os.path.join(self.repo, ".asgard", "asgard-setting-project.json"),
            {"paths": {"additional_roots": ["../pair-repo"]}},
        )
        self.assertEqual(self.edit(os.path.join(self.pair, "src", "api.py"))[0], 0)

    def test_declared_root_scaffold_stays_protected(self) -> None:
        _write(
            os.path.join(self.repo, ".asgard", "asgard-setting-project.json"),
            {"paths": {"additional_roots": [self.pair]}},
        )
        code, _, err = self.edit(os.path.join(self.pair, ".claude", "settings.json"))
        self.assertEqual(code, 2)
        self.assertIn("control-surface", err)

    def test_bash_reaches_the_declared_root(self) -> None:
        _write(
            os.path.join(self.repo, ".asgard", "asgard-setting-project.json"),
            {"paths": {"additional_roots": [self.pair]}},
        )
        self.assertTrue(readonly_guard.is_readonly_bash_safe(f"ls {self.pair}", self.repo))
        self.assertFalse(readonly_guard.is_readonly_bash_safe(f"ls {self.stranger}", self.repo))


class TestStudioWorkspaceIsAWorkTarget(Sandboxed):
    """`~/.asgard/studio/workspace` — `.asgard` 아래지만 하네스 상태가 아니라 작업 대상이다."""

    def setUp(self) -> None:
        super().setUp()
        # conftest는 테스트가 사용자의 홈을 더럽히지 않게 ASGARD_STUDIO_STATE를 임시 자리로 돌린다.
        # 여기서 보려는 것은 **기본 배치**(`~/.asgard/studio/workspace`)라 그 우회를 걷는다 —
        # HOME 자체가 이미 임시 자리라 실제 홈은 여전히 안 건드린다.
        os.environ.pop("ASGARD_STUDIO_STATE", None)
        self.workspace = readonly_guard._studio_workspace()
        os.makedirs(self.workspace, exist_ok=True)

    def test_workspace_is_under_a_control_directory(self) -> None:
        self.assertIn(".asgard", self.workspace.split(os.sep))  # 이 전제가 깨지면 이 검사는 무의미하다

    def test_write_inside_the_workspace_is_allowed(self) -> None:
        target = os.path.join(self.workspace, "app", "main.py")
        self.assertEqual(self.edit(target, cwd=self.workspace)[0], 0)

    def test_bash_inside_the_workspace_is_allowed(self) -> None:
        code, _, err = self.bash(f"npm run build --prefix {self.workspace}/app", cwd=self.workspace)
        self.assertEqual(code, 0, err)

    def test_harness_state_inside_the_workspace_stays_blocked(self) -> None:
        target = os.path.join(self.workspace, ".asgard", "asgard-setting-project.json")
        code, _, err = self.edit(target, cwd=self.workspace)
        self.assertEqual(code, 2)
        self.assertIn("control-surface", err)

    def test_the_studio_state_next_to_it_stays_blocked(self) -> None:
        target = os.path.join(os.path.dirname(self.workspace), "workspace.db")
        self.assertEqual(self.edit(target, cwd=self.workspace)[0], 2)

    def test_a_command_climbing_out_of_the_workspace_stays_blocked(self) -> None:
        code, _, err = self.bash(f"rm -rf {self.workspace}/../workspace.db", cwd=self.workspace)
        self.assertEqual(code, 2)
        self.assertIn("control-surface", err)


class TestNativeLaneAgrees(Sandboxed):
    """네이티브 도구 격리(`agent.tools._confine`)와 훅이 같은 뿌리를 본다."""

    def test_confine_follows_the_declared_roots(self) -> None:
        from asgard.agent.tools import ToolError, _confine

        target = os.path.join(self.pair, "src", "api.py")
        with self.assertRaises(ToolError):
            _confine(self.repo, target)
        _write(
            os.path.join(self.repo, ".asgard", "asgard-setting-project.json"),
            {"paths": {"additional_roots": [self.pair]}},
        )
        self.assertEqual(_confine(self.repo, target), os.path.realpath(target))
        with self.assertRaises(ToolError):
            _confine(self.repo, os.path.join(self.stranger, "app.js"))


class TestExistingDisciplineUnchanged(Sandboxed):
    def test_repo_scaffold_blocked(self) -> None:
        for scaffold in (".claude/settings.json", ".cursor/hooks.json", ".codex/config.toml", ".asgard/state/x.json"):
            code, _, err = self.edit(os.path.join(self.repo, scaffold))
            self.assertEqual(code, 2, scaffold)
            self.assertIn("control-surface", err, scaffold)

    def test_readonly_role_still_cannot_write(self) -> None:
        payload = {
            "cwd": self.repo,
            "agent_type": "asgard-verifier",
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(self.repo, "src", "app.py")},
        }
        code, _, err = _run(payload)
        self.assertEqual(code, 2)
        self.assertIn("read-only role", err)

    def test_readonly_role_bash_allowlist_unchanged(self) -> None:
        self.assertTrue(readonly_guard.is_readonly_bash_safe("git status --porcelain && git diff", self.repo))
        self.assertFalse(readonly_guard.is_readonly_bash_safe("rm -rf src", self.repo))
        self.assertTrue(
            readonly_guard.is_readonly_bash_safe(f"python3 {self.repo}/.claude/hooks/quest-log.py state", self.repo)
        )


if __name__ == "__main__":
    unittest.main()
