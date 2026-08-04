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


class TestReadingTheControlSurfaceIsNotWriting(Sandboxed):
    """통제 표면은 **위조**를 막는 자리지 열람을 막는 자리가 아니다.

    26-08-04 실측: 한 진단 세션에서 읽기만 하는 명령이 네 번 하드 블록됐다 — 자기 퀘스트 기장을
    세는 `ls`, 설정 파일 크기를 재는 `wc`, 그리고 저장소 **밖**에 있는 호스트 세션 디렉터리를
    읽는 `cat` 까지. 마지막 것은 이 프로젝트의 통제 표면이 아예 아니다."""

    def test_listing_the_quest_ledger_is_allowed(self) -> None:
        self.assertEqual(self.bash("ls .asgard/quest")[0], 0)
        self.assertEqual(self.bash("cat .asgard/quest/x.jsonl")[0], 0)

    def test_measuring_a_scaffold_file_is_allowed(self) -> None:
        self.assertEqual(self.bash("wc -c .claude/settings.json")[0], 0)

    def test_a_host_directory_outside_the_repo_is_not_this_control_surface(self) -> None:
        outside = os.path.join(self.stranger, ".claude", "projects", "s", "journal.jsonl")
        self.assertEqual(self.bash(f"cat {outside}")[0], 0)

    def test_forging_the_ledger_is_still_blocked(self) -> None:
        code, _, err = self.bash("echo x > .asgard/quest/forged.jsonl")
        self.assertEqual(code, 2)
        self.assertIn("control-surface", err)

    def test_deleting_a_scaffold_is_still_blocked(self) -> None:
        self.assertEqual(self.bash("rm -rf .claude/hooks")[0], 2)

    def test_editing_a_scaffold_is_still_blocked(self) -> None:
        self.assertEqual(self.edit(os.path.join(self.repo, ".asgard", ".gitignore"))[0], 2)


class TestShellControlFlowClassifies(Sandboxed):
    """읽기 전용 명령만 담은 반복문이 미분류로 막히지 않는다.

    `for f in a b; do wc -c "$f"; done` 은 실행하는 것이 전부 관측인데, 제어문 낱말을 명령으로
    읽는 바람에 통째로 차단됐다. 명령 치환(`$(…)`)은 여전히 판정 불가라 막힌다."""

    def test_a_loop_of_read_only_commands_is_readonly(self) -> None:
        self.assertTrue(readonly_guard.is_readonly_bash_safe('for f in a b; do wc -c "$f"; done', self.repo))
        self.assertTrue(readonly_guard.is_readonly_bash_safe("if git status; then git log; fi", self.repo))

    def test_a_loop_with_a_destructive_body_is_not(self) -> None:
        self.assertFalse(readonly_guard.is_readonly_bash_safe('for f in a; do rm -rf "$f"; done', self.repo))
        self.assertFalse(readonly_guard.is_readonly_bash_safe("for f in a; do git reset --hard; done", self.repo))

    def test_command_substitution_stays_unclassifiable(self) -> None:
        self.assertFalse(readonly_guard.is_readonly_bash_safe('wc -c "$(ls)"', self.repo))


class TestHostScratchpadIsAWorkTarget(Sandboxed):
    """호스트가 이 세션에 내준 임시 자리 — 시스템 프롬프트가 "여기를 쓰라"고 지정하는 폴더다.

    프로젝트 밖이라 경로 이탈로 막혀서, 역할이 계측 스크립트를 저장소 안에 쓰거나 포기했다."""

    def _scratch(self, session: str) -> str:
        return os.path.join(tempfile.gettempdir(), "claude-501", "proj", session, "scratchpad")

    def test_this_session_scratchpad_opens(self) -> None:
        session = "39f84a83-abcd"
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": session}, clear=False):
            self.assertEqual(self.edit(os.path.join(self._scratch(session), "probe.py"))[0], 0)

    def test_another_sessions_scratchpad_stays_closed(self) -> None:
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "mine"}, clear=False):
            self.assertEqual(self.edit(os.path.join(self._scratch("someone-else"), "probe.py"))[0], 2)

    def test_without_a_session_identity_nothing_opens(self) -> None:
        env = {name: "" for name in readonly_guard._HOST_SESSION_ENV}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(self.edit(os.path.join(self._scratch("mine"), "probe.py"))[0], 2)


class TestJudgedTextMustBeExecutedText(Sandboxed):
    """텍스트를 읽어 판정하는 레인은 셸 변수를 만나면 기권한다.

    `python -c "$PAYLOAD"` 에서 쓰기 휴리스틱이 보는 것은 `$PAYLOAD` 라는 네 글자뿐이고, 셸이
    그 자리에 넣는 것은 무엇이든 될 수 있다. 26-08-04 교차검증(codex)이 이 형태로 기장 파일을
    실제로 만들어 보였다:
        for PAYLOAD in "…write_text('forged')"; do python -c "$PAYLOAD"; done
    같은 이유로 sed·awk 의 스크립트 인자도 변수면 판정하지 않는다."""

    def test_a_variable_python_snippet_is_not_readonly(self) -> None:
        body = "from pathlib import Path; Path('.asgard/quest/forged.jsonl').write_text('x')"
        for command in (
            f'for PAYLOAD in "{body}"; do python -c "$PAYLOAD"; done',
            f'env PAYLOAD="{body}" python -c "$PAYLOAD"',
            f'for P in "{body}"; do python -c "${{P}}"; done',
        ):
            with self.subTest(command=command[:40]):
                self.assertFalse(readonly_guard.is_readonly_bash_safe(command, self.repo))
                self.assertEqual(self.bash(command)[0], 2)

    def test_a_variable_stream_editor_script_is_not_readonly(self) -> None:
        self.assertFalse(readonly_guard.is_readonly_bash_safe('sed "$SCRIPT" AGENTS.md', self.repo))
        self.assertFalse(readonly_guard.is_readonly_bash_safe('awk "$PROG" AGENTS.md', self.repo))

    def test_a_literal_snippet_still_runs(self) -> None:
        for command in (
            'python -c "import asgard; print(asgard.__file__)"',
            'sed -n "1,5p" AGENTS.md',
        ):
            with self.subTest(command=command):
                self.assertTrue(readonly_guard.is_readonly_bash_safe(command, self.repo))


class TestHostProjectStateIsAWorkTarget(Sandboxed):
    """호스트가 **이 프로젝트** 몫으로 내준 상태 폴더 — 자동 기억이 사는 자리다.

    경로에 `.claude` 가 들어 있다는 이유로 막던 동안, 에이전트가 자기 기억을 한 줄도 못 남겼다.
    여는 것은 슬러그가 맞는 폴더 하나뿐이다 (`~/.claude/projects/<뿌리의 구분자를 - 로>`)."""

    def _host(self, slug: str, *parts: str) -> str:
        return os.path.join(os.environ["HOME"], ".claude", "projects", slug, *parts)

    def test_this_projects_memory_opens(self) -> None:
        # 호스트 규칙 — 절대경로의 `/` 와 `_` 를 둘 다 `-` 로 바꾼다
        # (`/Users/yun/…/personal_space/…` → `-Users-yun-…-personal-space-…`).
        slug = self.repo.replace(os.sep, "-").replace("_", "-")
        self.assertEqual(self.edit(self._host(slug, "memory", "note.md"))[0], 0)

    def test_an_underscore_in_the_project_path_still_matches(self) -> None:
        repo = os.path.join(os.path.dirname(self.repo), "my_project")
        os.makedirs(repo, exist_ok=True)
        slug = repo.replace(os.sep, "-").replace("_", "-")
        self.assertEqual(self.edit(self._host(slug, "memory", "note.md"), cwd=repo)[0], 0)

    def test_another_projects_state_stays_closed(self) -> None:
        self.assertEqual(self.edit(self._host("-some-other-project", "memory", "note.md"))[0], 2)

    def test_the_host_settings_file_stays_closed(self) -> None:
        outside = os.path.join(os.environ["HOME"], ".claude", "settings.json")
        self.assertEqual(self.edit(outside)[0], 2)

    def test_the_repo_scaffold_stays_closed(self) -> None:
        self.assertEqual(self.edit(os.path.join(self.repo, ".claude", "settings.json"))[0], 2)


if __name__ == "__main__":
    unittest.main()
