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

from asgard_hooklib import workspace as workspace_lib

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
        # 이 스위트를 무인 실행(`asgard start`, 스튜디오)에서 돌리면 그 신호가 프로세스에 남아
        # 있다 — 거부문의 "묻는가 / 스스로 진행하는가"가 러너의 환경에 따라 갈리면 안 된다.
        os.environ.pop("ASGARD_UNATTENDED", None)
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
        self.assertIn(self.repo, err)  # 지금 서 있는 뿌리를 같이 말해야 어디가 밖인지 안다

    def test_refusal_names_a_command_the_reader_can_run(self) -> None:
        """처방은 여기서 실행할 수 있어야 한다 — 설정 파일 편집만 지목하면 아래 갈래가 그걸 막는다."""
        _, _, err = self.edit(os.path.join(self.stranger, "app.js"))
        self.assertIn("asgard root add", err)

    def test_refusal_fills_in_the_directory_instead_of_a_placeholder(self) -> None:
        """어디를 열지는 막힌 경로 하나로 정해진다 — 자리표시자를 내면 읽는 쪽이 고르고, 좁게
        고르면 다음 파일에서 또 막히고 넓게 고르면 이웃 저장소까지 딸려 온다."""
        os.makedirs(os.path.join(self.stranger, ".git"))
        deep = os.path.join(self.stranger, "app", "components", "Toggle.vue")
        _, _, err = self.edit(deep)
        self.assertIn(f"asgard root add {self.stranger} --yes", err)
        self.assertNotIn("<dir>", err)

    def test_the_named_directory_is_the_project_not_the_leaf_folder(self) -> None:
        os.makedirs(os.path.join(self.stranger, ".git"))
        nested = os.path.join(self.stranger, "packages", "web")
        os.makedirs(nested)
        _, _, err = self.edit(os.path.join(nested, "main.ts"))
        self.assertIn(f"asgard root add {self.stranger} --yes", err)

    def test_a_directory_with_no_project_marker_still_gets_a_concrete_command(self) -> None:
        _, _, err = self.edit(os.path.join(self.stranger, "loose", "app.js"))
        self.assertIn(f"asgard root add {os.path.join(self.stranger, 'loose')} --yes", err)

    def test_the_prescribed_directory_is_one_root_add_accepts(self) -> None:
        """거부문이 지목하는 자리와 명령이 받아 주는 자리는 같아야 한다.

        26-08-11 판정이 잡은 반례: 세션 뿌리가 다른 프로젝트 안에 든 배치(이 저장소의 `ref/*`)
        에서 가장 가까운 마커가 **뿌리의 조상**이라, 거부문이 그것을 열라고 처방하는데
        `_reject_target` 은 "이 프로젝트를 품는 자리"라며 거절했다. 오딘의 승인 한 번을 받아 낸
        뒤에 명령이 실패한다."""
        from asgard.commands.workroots import _reject_target

        inner = os.path.join(self.stranger, "inner")
        os.makedirs(os.path.join(self.stranger, ".git"))
        os.makedirs(os.path.join(inner, ".git"))
        _, _, err = self.edit(os.path.join(self.stranger, "docs", "note.md"), cwd=inner)
        prescribed = [line for line in err.splitlines() if "asgard root add" in line]
        self.assertEqual(len(prescribed), 1, err)  # 처방이 없으면 아래 검사가 공짜로 통과한다
        target = prescribed[0].split("asgard root add ", 1)[1].split(" --yes")[0]
        self.assertEqual(_reject_target(os.path.realpath(inner), target), "")

    def test_a_folder_that_does_not_exist_yet_gets_a_command_that_runs(self) -> None:
        """저장소 옆에 새 폴더를 만들며 쓰는 형상 — `run_root_add` 는 없는 자리를 거절하므로,
        만드는 줄이 처방에 없으면 오딘의 승인을 받아 낸 뒤에 명령이 끊긴다 (26-08-11 2차 판정)."""
        import subprocess

        from asgard.commands.workroots import _reject_target

        target = os.path.join(os.path.dirname(self.repo), "newapp")
        _, _, err = self.edit(os.path.join(target, "README.md"))
        prescribed = next(line.strip() for line in err.splitlines() if "asgard root add" in line)
        self.assertEqual(prescribed, f"mkdir -p {target} && asgard root add {target} --yes")
        # 처방을 글자로 맞추는 데서 그치지 않고, 만드는 절반을 실제로 돌려 나머지 절반이 받는지 본다.
        subprocess.run(prescribed.split("&&")[0].strip(), shell=True, check=True)
        self.assertTrue(os.path.isdir(target))
        self.assertEqual(_reject_target(os.path.realpath(self.repo), target), "")

    def test_an_existing_directory_is_not_told_to_create_itself(self) -> None:
        os.makedirs(os.path.join(self.stranger, ".git"))
        _, _, err = self.edit(os.path.join(self.stranger, "src", "app.js"))
        self.assertIn(f"asgard root add {self.stranger} --yes", err)
        self.assertNotIn("mkdir", err)

    def test_a_path_above_the_session_root_says_so_instead_of_prescribing(self) -> None:
        """선언으로 못 여는 경로다 — 담는 디렉터리가 전부 세션 뿌리를 함께 담는다.
        열 수 없는 자리를 지목하느니 그 프로젝트를 직접 열라고 말한다."""
        inner = os.path.join(self.stranger, "inner")
        os.makedirs(inner)
        _, _, err = self.edit(os.path.join(self.stranger, "note.md"), cwd=inner)
        self.assertIn("No declaration reaches that path", err)
        self.assertNotIn("asgard root add", err)

    def test_the_refusal_never_prescribes_a_file_this_guard_blocks(self) -> None:
        """26-08-07 교착의 두 번째 결: 처방이 `.claude/settings.json` 을 두 번째 길로 내밀면
        읽는 쪽이 그리로 가고 통제 표면 규칙에 다시 막힌다."""
        _, _, err = self.edit(os.path.join(self.stranger, "app.js"))
        self.assertNotIn("additionalDirectories", err)
        prescription = err.split("Do not write")[0]
        self.assertNotIn(".claude/settings.json", prescription)

    def test_the_refusal_names_how_to_ask_in_this_host(self) -> None:
        """ "물어보라"만 있으면 물을 채널이 있는 모드에서도 안 묻는다 — 무엇으로 묻는지까지 댄다."""
        blocked = os.path.join(self.stranger, "app.js")
        self.assertIn("AskUserQuestion", self.edit(blocked)[2])
        payload = {"cwd": self.repo, "tool_name": "Edit", "tool_input": {"file_path": blocked}}
        _, out, _ = _run(payload, argv=["cursor"])
        self.assertIn("Ask Odin in your reply", json.loads(out)["agent_message"])

    def test_an_unattended_session_is_told_to_proceed_rather_than_wait(self) -> None:
        """Canon 8 — 물을 사람이 없는 세션에 "오딘에게 물어라"만 주면 거기서 턴이 끝난다."""
        payload = {
            "cwd": self.repo,
            "permission_mode": "bypassPermissions",
            "tool_name": "Edit",
            "tool_input": {"file_path": os.path.join(self.stranger, "app.js")},
        }
        err = _run(payload)[2]
        self.assertNotIn("AskUserQuestion", err)
        self.assertIn("run it yourself", err)
        self.assertIn("asgard root add", err)

    def test_the_prescribed_file_is_itself_blocked_so_the_command_is_the_way_in(self) -> None:
        """26-08-07 교착의 회귀 못 — 뿌리 밖 차단이 지목한 파일을 통제 표면 차단이 막았다."""
        code, _, err = self.edit(os.path.join(self.repo, ".asgard", "asgard-setting-project.json"))
        self.assertEqual(code, 2)
        self.assertIn("control-surface policy blocked", err)
        self.assertIn("asgard root add", err)

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
        self.assertIn("control-surface policy blocked", err)

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
        self.workspace = workspace_lib._studio_workspace()
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
        self.assertIn("control-surface policy blocked", err)

    def test_the_studio_state_next_to_it_stays_blocked(self) -> None:
        target = os.path.join(os.path.dirname(self.workspace), "workspace.db")
        self.assertEqual(self.edit(target, cwd=self.workspace)[0], 2)

    def test_a_command_climbing_out_of_the_workspace_stays_blocked(self) -> None:
        code, _, err = self.bash(f"rm -rf {self.workspace}/../workspace.db", cwd=self.workspace)
        self.assertEqual(code, 2)
        self.assertIn("control-surface policy blocked", err)


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


class TestAReadOnlyRoleCanSpeakAboutItsOwnAttempt(Sandboxed):
    """배차 장부는 트리가 아니다 — 자기 시도에 대해 말하는 것까지 막으면 실패가 사라진다.

    26-08-13 실측: asgard-ullr 에게 주입된 `<asgard-dispatch>` 블록이 알려 준 실패 보고 명령이
    이 가드에서 exit 1 로 막혔다. 주입은 없는 길을 알려 주고 있었고, 그동안 읽기 전용 역할의
    배차는 결과와 무관하게 전부 `succeeded` 로 접혔다.
    """

    def test_reporting_a_failure_is_allowed(self) -> None:
        self.assertTrue(
            readonly_guard.is_readonly_bash_safe(
                'asgard siege done --quest q1 --agent asgard-ullr --outcome failed --body "못 찾았어요"', self.repo
            )
        )

    def test_leaving_a_question_and_reading_the_ledger_are_allowed(self) -> None:
        for command in (
            'asgard siege ask run_abc "어느 단위가 이 파일을 쥐나요?" --sender asgard-loki',
            "asgard siege escalate run_abc '막혔어요'",
            "asgard siege heartbeat run_abc task_1 disp_1 --phase investigating",
            "asgard siege show run_abc --json",
            "asgard siege watch run_abc",
            "asgard siege",
        ):
            self.assertTrue(readonly_guard.is_readonly_bash_safe(command, self.repo), command)

    def test_done_only_opens_in_its_self_naming_form(self) -> None:
        """위치 인자 dispatch id 는 남의 시도다 — 판정자가 자기가 판정하는 Run 을 정산하게 된다.

        같은 변경이 `dispatch_context` 에서 판정자를 빼는 이유가 그것이라, 이 자리를 넓게 열면
        두 결정이 서로 어긋난다."""
        self.assertFalse(readonly_guard.is_readonly_bash_safe("asgard siege done disp_1 succeeded", self.repo))
        self.assertFalse(
            readonly_guard.is_readonly_bash_safe("asgard siege done disp_1 --outcome failed", self.repo),
            "위치 dispatch id 가 플래그와 섞이면 통과했다",
        )
        self.assertFalse(
            readonly_guard.is_readonly_bash_safe("asgard siege done --quest q1 --outcome failed", self.repo),
            "자기 이름 없이 통과했다 — 그러면 무엇을 접는지가 안 정해진다",
        )
        self.assertTrue(
            readonly_guard.is_readonly_bash_safe("asgard siege done --quest=q1 --agent=asgard-loki --json", self.repo),
            "`--flag=value` 형태를 위치 인자로 읽었다",
        )

    def test_done_must_name_the_caller_when_the_caller_is_known(self) -> None:
        """`--agent` 를 안 보면 위치 인자를 막은 것이 무의미하다 — 판정자가 워커라고 적으면 그만이다."""
        mine = 'asgard siege done --quest q1 --agent asgard-loki --outcome failed --body "막혔어요"'
        theirs = "asgard siege done --quest q1 --agent asgard-worker --outcome failed"
        self.assertTrue(readonly_guard.is_readonly_bash_safe(mine, self.repo, agent="asgard-loki"))
        self.assertFalse(readonly_guard.is_readonly_bash_safe(theirs, self.repo, agent="asgard-loki"))
        # 이름을 모르는 호출자(통제 표면 갈래)는 대조를 건너뛴다 — 거기 판정 대상은 이 축이 아니다.
        self.assertTrue(readonly_guard.is_readonly_bash_safe(theirs, self.repo))

    def test_reading_the_ledger_survives_a_leading_flag(self) -> None:
        """`asgard siege --json` 의 첫 토큰은 동사가 아니다 — 그것을 동사로 읽으면 목록 조회가 막힌다."""
        self.assertTrue(readonly_guard.is_readonly_bash_safe("asgard siege --json", self.repo))

    def test_driving_someone_elses_state_stays_blocked(self) -> None:
        """자기 시도에 대해 말하는 것과 그래프를 미는 것은 다르다 — 뒤쪽은 코디네이터의 손이다."""
        for command in (
            "asgard siege reset --all",
            "asgard siege answer msg_1 '그렇게 하세요'",
            "asgard siege decide gate_1 A",
            "asgard siege force task_1 completed",
            "asgard siege settle disp_1 succeeded",
            "asgard siege start '새 목표'",
        ):
            self.assertFalse(readonly_guard.is_readonly_bash_safe(command, self.repo), command)

    def test_the_refusal_still_teaches_where_the_lane_is(self) -> None:
        from asgard.hooks.asgard_hooklib.readonly import READONLY_BASH_HINT

        self.assertIn("asgard siege done --quest", READONLY_BASH_HINT)


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
        self.assertIn("control-surface policy blocked", err)

    def test_deleting_harness_state_is_still_blocked(self) -> None:
        self.assertEqual(self.bash("rm -rf .asgard/state")[0], 2)

    def test_editing_harness_state_is_still_blocked(self) -> None:
        self.assertEqual(self.edit(os.path.join(self.repo, ".asgard", ".gitignore"))[0], 2)


class TestNamingIsNotOpening(Sandboxed):
    """경로를 **입에 올리는 것**은 여는 것이 아니다.

    26-08-13 평가에서 이 저장소를 조사하는 읽기 명령이 네 번 하드 블록됐다. 넷 다 아무것도
    고치지 않았고, 걸린 이유는 하나다 — 통제 표면 판정의 글자 그물이 명령문 어디든 경로 이름이
    보이면 쓰기로 읽었다. 외부 도구에 넘긴 프롬프트 안의 경로, 파이프 끝에 붙은 `sort` 때문에
    읽기 전용 인정을 못 받은 명령, 퀘스트 기장을 세는 스크립트가 그렇게 막혔다.

    아래 두 축을 함께 고정한다. 이름만 오르내리는 명령은 지나가고, 같은 파일을 실제로 고치는
    명령은 그대로 막힌다."""

    MENTION_ONLY = [
        "codex exec 'audit the hooks listed in .claude/settings.json'",
        "codex exec 'the ledger lives in .asgard/quest — explain the format'",
        'grep -n "hook" .claude/settings.json | sort -u',
        'grep -rn "quest" .asgard/quest | sort | uniq -c',
        # 버리는 리다이렉션은 파일을 만들지 않는다. 조각을 재조립해 판정하던 판에서는 꺾쇠가
        # 인용돼 `/dev/null` 이 뿌리 밖 경로로 남았고, 같은 읽기가 `2>/dev/null` 한 마디
        # 때문에 통제 표면 쓰기로 뒤집혔다 (26-08-13 2차 판정).
        'grep -n "hook" .claude/settings.json 2>/dev/null | sort -u',
        "grep x .asgard/quest/q.jsonl 2>/dev/null | cut -c1-9",
        "grep x .asgard/quest/q.jsonl 2>&1 | cut -c1-9",
        "echo 'write it to .asgard/state/x later'",
        "python3 -c \"print('.asgard/state is the harness state directory')\"",
    ]

    # 여는 쪽은 **이름 목록으로 물으면 반드시 샌다**. 26-08-13 판정이 그 반례를 들었다:
    # `sed -i` 는 막히는데 `gsed -i` 는 통과했고, `perl -pi` 와 `sqlite3` 도 같이 새고 있었다.
    # 아래 목록은 그 셋을 고정한다 — 새 편집기 이름이 목록에 없어도 막혀야 통과다.
    OPENING = [
        ("echo x > .claude/settings.json", "리다이렉션"),
        ("rm .asgard/state/gate-events.jsonl", "삭제"),
        ("cp /tmp/x .claude/settings.local.json", "덮어쓰기"),
        ("echo forged >> .asgard/quest/q.jsonl", "덧붙이기"),
        ("./w -m .asgard/quest/f.jsonl", "미지 프로그램이 기장 경로를 인자로 받는 자리"),
        ("sed -i 's/hooks/x/' .claude/settings.json", "제자리 편집"),
        ("gsed -i 's/hooks/x/' .claude/settings.json", "이름만 다른 제자리 편집"),
        ("perl -pi -e 's/hooks/x/' .asgard/asgard-setting-project.json", "다른 인터프리터의 제자리 편집"),
        ("sqlite3 .asgard/orchestration.db 'delete from dispatches'", "DB 클라이언트가 상태 파일을 연다"),
        ("ex -s -c '%s/a/b/|x' .claude/settings.json", "목록에 없는 편집기"),
        ("gsed -ni 's/hooks/x/' .claude/settings.json", "뭉친 낱글자 안의 제자리 편집 플래그"),
        ("sed --in-place=bak 's/hooks/x/' .claude/settings.json", "= 로 값을 받는 제자리 편집"),
        (
            "python3 -c \"import fileinput; [print(l) for l in fileinput.input('.claude/settings.json', inplace=True)]\"",
            "여는 모드가 안 드러나는 표준 라이브러리 제자리 편집",
        ),
    ]

    def test_mentioning_a_control_path_is_not_a_write(self) -> None:
        for command in self.MENTION_ONLY:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], 0, f"읽기 명령을 막았다: {command}")

    def test_actually_opening_it_is_still_blocked(self) -> None:
        for command, why in self.OPENING:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], 2, f"{why} 를 통과시켰다: {command}")


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
    """호스트가 이 프로젝트에 내준 임시 자리 — 시스템 프롬프트가 "여기를 쓰라"고 지정하는 폴더다.

    프로젝트 밖이라 경로 이탈로 막혀서, 역할이 계측 스크립트를 저장소 안에 쓰거나 포기했다.
    여는 열쇠는 프로젝트 슬러그다: 세션 id 로 좁히면 이어받은 세션이 통째로 닫힌다 — 호스트가
    이어받기마다 새 id 를 내주는데 문맥에 남아 다시 쓰이는 경로는 처음 세션의 것이다."""

    def _scratch(self, project: str, session: str) -> str:
        slug = project.replace(os.sep, "-").replace("_", "-")
        return os.path.join(tempfile.gettempdir(), "claude-501", slug, session, "scratchpad")

    def test_this_projects_scratchpad_opens(self) -> None:
        path = os.path.join(self._scratch(self.repo, "39f84a83-abcd"), "probe.py")
        self.assertEqual(self.edit(path)[0], 0)

    def test_a_resumed_session_keeps_the_first_sessions_scratchpad(self) -> None:
        """이어받기가 남긴 경로는 처음 세션의 id 를 달고 있다 — 그 경로로도 계속 써야 한다."""
        first = os.path.join(self._scratch(self.repo, "35a5a493-first"), "findings", "notes.md")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "9995e4dd-resumed"}, clear=False):
            self.assertEqual(self.edit(first)[0], 0)

    def test_another_projects_scratchpad_stays_closed(self) -> None:
        path = os.path.join(self._scratch(self.stranger, "39f84a83-abcd"), "probe.py")
        self.assertEqual(self.edit(path)[0], 2)

    def test_the_temp_root_itself_stays_closed(self) -> None:
        slug = self.repo.replace(os.sep, "-").replace("_", "-")
        path = os.path.join(tempfile.gettempdir(), "claude-501", slug, "session", "probe.py")
        self.assertEqual(self.edit(path)[0], 2)

    def test_without_a_root_nothing_opens(self) -> None:
        self.assertFalse(workspace_lib._within_host_scratchpad(self._scratch(self.repo, "s"), ()))


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

    def test_force_staging_is_not_on_the_index_lane(self) -> None:
        """`-f` 는 무시 규칙을 끄는 플래그다 — 이 레인의 근거가 그 규칙이라 함께 열 수 없다."""
        for command in ("git add -f -- .asgard", "git add --force .asgard"):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], 2)

    def test_config_injection_does_not_ride_in_on_the_index_lane(self) -> None:
        """`-c` 는 임의 헬퍼를 실행한다 — 읽기 레인에서 거르는 것을 여기서도 거른다."""
        for command in ("git -c core.pager=sh add -- .asgard", "git --work-tree=/tmp add -- .asgard"):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], 2)


class TestTheRefusalNamesTheRealReason(Sandboxed):
    """차단 사유가 둘로 갈린다 — 아무도 못 고치는 자리(`control`)와 선언 한 줄로 열리는
    자리(`escape`). 처방이 다르므로 진단이 틀리면 읽는 쪽이 엉뚱한 자리를 고치러 간다.

    26-08-11 실측: 짝 저장소를 조사하는 순수 읽기가 네 번 `control` 로 막혔고, 그 처방
    (`asgard init` / `asgard sync`)에는 고칠 자리가 아예 없었다. 진짜 사유는 뿌리 밖이었다."""

    def test_reading_another_repo_state_is_an_escape_not_a_control_surface(self) -> None:
        outside = os.path.join(self.stranger, ".asgard", "state")
        code, _, err = self.bash(f"ls -la {outside}")
        self.assertEqual(code, 2)
        self.assertIn("outside every work root", err)
        # 이탈 문장도 본문에서 통제 표면 규칙을 언급한다 — 사유를 가르는 것은 첫 줄이다.
        self.assertNotIn("control-surface policy blocked", err)

    def test_the_escape_refusal_still_prescribes_the_declaration(self) -> None:
        os.makedirs(os.path.join(self.stranger, ".git"))
        _, _, err = self.bash(f"cat {os.path.join(self.stranger, '.asgard', 'quest', 'q.jsonl')}")
        self.assertIn(f"asgard root add {self.stranger} --yes", err)

    def test_this_repo_control_surface_still_reads_as_control(self) -> None:
        """뿌리 **안**의 통제 표면은 그대로다 — 이 완화가 사려던 것은 사유의 정확도지 접근이 아니다."""
        code, _, err = self.bash("rm -rf .asgard/state")
        self.assertEqual(code, 2)
        self.assertIn("control-surface policy blocked", err)

    def test_a_boundary_file_named_anywhere_stays_a_control_refusal(self) -> None:
        """뿌리를 정하는 파일은 남의 저장소 경로로 적혀도 통제 표면이다 — 글자로 찾는 그물이
        여기서 느슨해지면 경계를 정하는 자리가 이탈 진단 뒤로 숨는다."""
        code, _, err = self.bash(f"cp x {os.path.join(self.stranger, '.claude', 'settings.json')}")
        self.assertEqual(code, 2)
        self.assertIn("control-surface policy blocked", err)

    def test_an_interpreter_living_outside_the_root_is_not_an_escape(self) -> None:
        """명령 이름 자리는 뿌리 판정의 대상이 아니다 — 아니면 모든 훅 호출이 이탈이 된다."""
        command = "/usr/local/bin/uv run --no-project python .claude/hooks/quest-log.py state"
        self.assertEqual(self.bash(command)[0], 0)


if __name__ == "__main__":
    unittest.main()
