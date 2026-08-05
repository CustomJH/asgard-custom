"""작업 뿌리 — 저장소 하나가 곧 작업 경계라는 가정이 깨지는 자리들.

여기서 보는 것은 셋이다. 선언되지 않은 저장소 밖 경로는 그대로 막히는가, 선언된 자리는
열리는가, 그리고 열린 자리 안에서도 하네스 상태(`.asgard`)와 이 가드의 뿌리를 정하는 파일
(`.claude/settings*.json`)은 여전히 막히는가.
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

    def test_declared_root_boundary_file_stays_protected(self) -> None:
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
    def test_harness_state_and_the_guards_own_boundary_stay_blocked(self) -> None:
        for scaffold in (".claude/settings.json", ".claude/settings.local.json", ".asgard/state/x.json"):
            code, _, err = self.edit(os.path.join(self.repo, scaffold))
            self.assertEqual(code, 2, scaffold)
            self.assertIn("control-surface", err, scaffold)

    def test_the_rest_of_the_scaffold_is_an_ordinary_work_target(self) -> None:
        # 판정의 물리 대조가 닿는 자리다 (`diff_state` 는 `.asgard` 만 뺀다) — 거기 쓴 것은
        # 판정 해시에 묶여 Odin 이 diff 로 본다. 스캐폴드가 곧 산출물인 저장소에서 이 자리를
        # 닫아 두면 관측도 편집도 통째로 막힌다 (26-08-05: 한 세션의 첫 세 명령이 그렇게 막혔다).
        for scaffold in (".claude/hooks/quest-log.py", ".claude/agents/asgard-worker.md", ".cursor/hooks.json"):
            self.assertEqual(self.edit(os.path.join(self.repo, scaffold))[0], 0, scaffold)

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

    def test_deleting_harness_state_is_still_blocked(self) -> None:
        self.assertEqual(self.bash("rm -rf .asgard/state")[0], 2)

    def test_editing_harness_state_is_still_blocked(self) -> None:
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


class TestOnlyArgumentsAreTreatedAsPaths(Sandboxed):
    """셸이 인자로 넘기지 않는 글은 경로 후보가 아니다.

    이 자리가 어긋나면 규칙이 아니라 표기 요령을 가르친다: 3차 세션은 같은 관측을 세 번
    표기만 바꿔 통과시켰고, 그중 하나는 정본 기장 명령이었다 (26-08-05)."""

    def test_a_line_continuation_does_not_split_the_command(self) -> None:
        # `\` + 줄바꿈은 셸이 지우는 것이지 구분자가 아니다. 조각으로 쪼개지면 정본 기장
        # 명령이 미분류로 떨어지고, 그 뒤 `.claude/hooks/quest-log.py` 인자가 통제 표면
        # 갈래에 걸려 퀘스트가 안 열린다.
        one_line = 'uv run --no-project python .claude/hooks/quest-log.py open q1 --criteria "a b"'
        wrapped = 'uv run --no-project python .claude/hooks/quest-log.py open q1 \\\n  --criteria "a b"'
        for command in (one_line, wrapped):
            with self.subTest(command=command[:40]):
                self.assertTrue(readonly_guard.is_readonly_bash_safe(command, self.repo))
                self.assertEqual(self.bash(command)[0], 0)

    def test_a_private_path_named_in_a_commit_message_is_not_a_write(self) -> None:
        command = 'git commit -m "fix(gate): .asgard/quest 기장이 두 번 열리던 것"'
        self.assertEqual(self.bash(command)[0], 0)

    def test_a_scaffold_path_named_in_a_commit_message_is_not_a_write(self) -> None:
        self.assertEqual(self.bash('git commit -m "docs: .claude/hooks/verifier-gate.py 설명"')[0], 0)

    def test_a_heredoc_body_is_not_a_path_argument(self) -> None:
        command = 'python3 - <<EOF\nprint("compare .claude/hooks/quest-log.py with the shipped copy")\nEOF'
        self.assertEqual(self.bash(command)[0], 0)

    def test_a_heredoc_body_is_still_code_for_the_forgery_net(self) -> None:
        # 본문은 인자가 아니지만 코드일 수는 있다 — 기장을 쓰는 본문은 여전히 막힌다.
        command = "python3 - <<EOF\nopen('.asgard/quest/forged.jsonl','w').write('x')\nEOF"
        self.assertEqual(self.bash(command)[0], 2)

    def test_an_unterminated_heredoc_does_not_hide_the_arguments_after_it(self) -> None:
        self.assertEqual(self.bash("cat <<EOF ; rm -rf .asgard/quest")[0], 2)

    def test_a_real_path_operand_is_still_a_write(self) -> None:
        for command in ("rm -rf .asgard/quest", "cp x .asgard/receipts/r.json", "touch .asgard/state/forged"):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], 2)

    def test_the_forgery_net_over_executable_text_stays(self) -> None:
        # 인자로는 경로가 아니지만 나중에 실행돼 기장을 쓰는 형태 — 여기서만 잡힌다.
        body = "from pathlib import Path; Path('.asgard/quest/forged.jsonl').write_text('x')"
        for command in (f'python -c "{body}"', f'for P in "{body}"; do python -c "$P"; done'):
            with self.subTest(command=command[:40]):
                self.assertEqual(self.bash(command)[0], 2)


class TestSharedMapIsAWorkTarget(Sandboxed):
    """`.asgard/map/` 는 통제 표면 안에 있지만 팀이 함께 쓰는 지도라 작업 대상이다.

    Canon 이 역할에게 영역 지도를 넓히라고 시키는데 막혀 있으면 그 지시를 아무도 수행할 수
    없다 (26-08-05: doctor 가 유령 경로를 손으로 지우라고 안내하는데 지울 도구가 없었다)."""

    def setUp(self) -> None:
        super().setUp()
        os.makedirs(os.path.join(self.repo, ".asgard", "map"))  # 지도 자리가 실재해야 판정이 성립한다

    def test_the_area_map_opens(self) -> None:
        self.assertEqual(self.edit(os.path.join(self.repo, ".asgard", "map", "orchestrator.md"))[0], 0)

    def test_the_rest_of_the_harness_state_stays_closed(self) -> None:
        for rel in (("asgard-setting-project.json",), ("quest", "q1.jsonl"), ("state", "x.json")):
            with self.subTest(rel=rel):
                self.assertEqual(self.edit(os.path.join(self.repo, ".asgard", *rel))[0], 2)

    def test_climbing_out_of_the_map_stays_closed(self) -> None:
        self.assertEqual(self.edit(os.path.join(self.repo, ".asgard", "map", "..", "quest", "q1.jsonl"))[0], 2)

    def test_an_aliased_map_directory_does_not_move_the_base(self) -> None:
        # 기준을 realpath 로 구하던 판은 링크가 기준 **자체를** 옮겼다: `.asgard/map -> .asgard`
        # 이면 기장·상태까지 별칭으로 통과했다 (26-08-05 교차검토 재현).
        os.rmdir(os.path.join(self.repo, ".asgard", "map"))
        os.symlink(".", os.path.join(self.repo, ".asgard", "map"))
        self.assertEqual(self.edit(os.path.join(self.repo, ".asgard", "map", "quest", "q1.jsonl"))[0], 2)
        self.assertEqual(self.edit(os.path.join(self.repo, ".asgard", "map", "orchestrator.md"))[0], 2)

    def test_a_declared_extra_root_does_not_bring_its_own_map(self) -> None:
        # `diff_state` 는 세션 뿌리의 지도 하나만 다시 읽는다 — 추가 뿌리까지 열면 해시 밖에
        # 쓰기 가능한 지도가 뿌리 수만큼 생긴다 (26-08-05 2차 교차검토).
        os.makedirs(os.path.join(self.pair, ".asgard", "map"))
        _write(
            os.path.join(self.repo, ".asgard", "asgard-setting-project.json"),
            {"paths": {"additional_roots": [self.pair]}},
        )
        self.assertEqual(self.edit(os.path.join(self.pair, "src", "api.py"))[0], 0)  # 뿌리 자체는 열린다
        self.assertEqual(self.edit(os.path.join(self.pair, ".asgard", "map", "area.md"))[0], 2)

    def test_the_first_area_map_can_be_created(self) -> None:
        # 아직 없는 자리를 닫으면 첫 영역 지도를 아무도 못 만든다 (`mkdir .asgard/map` 도 막힌다).
        import shutil as _shutil

        _shutil.rmtree(os.path.join(self.repo, ".asgard", "map"))
        self.assertEqual(self.edit(os.path.join(self.repo, ".asgard", "map", "orchestrator.md"))[0], 0)

    def test_only_what_the_hash_binds_is_writable(self) -> None:
        # 판정 해시는 지도 디렉터리 바로 아래의 `*.md` 만 다시 읽는다 — 여는 폭을 그보다 넓히면
        # 증거로 안 묶이는 자리에 쓰기가 생긴다.
        self.assertEqual(self.edit(os.path.join(self.repo, ".asgard", "map", "PROJECT.md"))[0], 0)
        self.assertEqual(self.edit(os.path.join(self.repo, ".asgard", "map", "areas", "deep.md"))[0], 2)
        self.assertEqual(self.edit(os.path.join(self.repo, ".asgard", "map", "notes.txt"))[0], 2)


class TestTheGuardsOwnBoundaryStaysClosed(Sandboxed):
    """이 가드의 경계를 정하는 파일은 인자가 아닌 글에서도 막는다.

    거기에 쓸 수 있으면 `work_roots` 가 뿌리를 다시 읽어 나머지 판정이 통째로 무의미해지는데,
    `.asgard/**` 는 판정 스냅샷에서 빠져 있어 뒤에서 잡아 줄 물리 대조도 없다."""

    def test_a_heredoc_that_writes_the_boundary_file_is_blocked(self) -> None:
        for target in ("asgard-setting-project.json", ".claude/settings.json"):
            with self.subTest(target=target):
                command = f"python3 - <<PY\nopen('.asgard/{target}','w').write('{{}}')\nPY"
                self.assertEqual(self.bash(command)[0], 2)

    def test_naming_it_in_a_commit_message_is_still_fine(self) -> None:
        self.assertEqual(self.bash('git commit -m "chore: asgard-setting-project.json 정리"')[0], 0)


class TestTheMessageOperandIsNotAnEscapeHatch(Sandboxed):
    def test_a_command_substitution_in_the_message_is_still_code(self) -> None:
        command = "git commit -m \"$(python3 -c \\\"open('.asgard/quest/forged.jsonl','w')\\\")\""
        self.assertEqual(self.bash(command)[0], 2)

    def test_the_combined_and_inline_spellings_are_inert_too(self) -> None:
        for command in (
            'git commit -am "fix: .asgard/quest 기장 표기 수정"',
            'git commit --message=".asgard/state 정리"',
            'git tag -m ".asgard/receipts 보관" v1',
        ):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], 0)

    def test_a_flag_that_takes_no_message_does_not_swallow_the_next_path(self) -> None:
        # `git checkout -m <경로>` 의 `-m` 은 피연산자를 안 받는다 — 하위 명령을 안 보고
        # 낱글자만 보면 바로 뒤 경로가 통째로 사라져 통제 표면 쓰기가 통과한다.
        for command in ("git checkout -m .asgard", "git checkout -m .claude/settings.json"):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], 2)

    def test_a_dangling_message_flag_does_not_swallow_the_separator(self) -> None:
        # 구분자를 메시지로 삼키면 프로그램 판정이 `git commit` 에 붙박여 뒤 세그먼트의 경로가
        # 두 검사 모두에서 사라진다 (26-08-05 Verifier 가 재현).
        self.assertEqual(self.bash("git commit -m ; ./w -m .asgard/quest/f.jsonl")[0], 2)

    def test_a_newline_reads_like_a_semicolon(self) -> None:
        # 같은 명령이 `;` 로는 통과하고 줄바꿈으로는 막히면, 규칙이 아니라 표기 요령을 가르친다.
        for joiner in (" ; ", "\n"):
            command = f'ls -la{joiner}git commit -m "fix: .asgard/state 가드"'
            with self.subTest(joiner=repr(joiner)):
                self.assertEqual(self.bash(command)[0], 0)


class TestStagingTheControlSurfaceIsNotWriting(Sandboxed):
    """`.asgard` 를 커밋 경계 안으로 들이는 연산은 이 갈래가 막지 않는다.

    표면이 닫혀 있는 이유는 거기 쓴 것이 판정의 물리 대조 밖에 남는다는 것이다. 색인에 담는
    것은 그 이유를 지운다 — 담기고 나면 Odin 이 diff 로 본다. 무엇이 실제로 담기는지는
    `.asgard` 자신의 무시 규칙이 정하므로 가드가 그 경계를 다시 적지 않는다."""

    def test_staging_and_committing_the_shared_assets_passes(self) -> None:
        for command in (
            "git add -- .asgard",
            "git add -- .asgard/map .asgard/memory/binding.json",
            # 뿌리를 정하는 파일도 담을 수는 있다 — 담는 것은 고치는 것이 아니다.
            "git add -- .asgard/asgard-setting-project.json",
            'git add -- .asgard && git commit -m "chore: 팀 자산을 Git 안으로"',
        ):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], 0)

    def test_git_verbs_that_touch_the_working_tree_are_still_blocked(self) -> None:
        """작업 트리를 바꾸는 git 은 그대로 막힌다 — 열린 것은 색인 하나다."""
        for command in ("git checkout -- .asgard", "git restore .asgard", "git rm -r .asgard", "git stash -- .asgard"):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], 2)

    def test_plain_writes_to_the_control_surface_are_untouched(self) -> None:
        for command in ("rm -rf .asgard/state", "echo x > .asgard/asgard-setting-project.json"):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], 2)

    def test_the_forgery_surface_is_not_stageable_either(self) -> None:
        """기장·영수증·상태는 담는 것도 막는다 — 위조 갈래는 이 완화를 안 본다."""
        for command in ("git add -- .asgard/quest", "git add -- .asgard/state/lagom-mode.json"):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], 2)

    def test_config_injection_does_not_ride_in_on_the_index_lane(self) -> None:
        """`-c` 는 임의 헬퍼를 실행한다 — 읽기 레인에서 거르는 것을 여기서도 거른다."""
        for command in ("git -c core.pager=sh add -- .asgard", "git --work-tree=/tmp add -- .asgard"):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], 2)


if __name__ == "__main__":
    unittest.main()
