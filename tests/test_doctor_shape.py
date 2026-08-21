"""doctor 의 형상 — 표면 스키마·조각의 독립성·함수 길이 상한.

실행: uv run pytest tests/test_doctor_shape.py

`_trinity_checks` 는 288줄 단일 함수였다. 책임별로 쪼개면서 판정이 바뀌지 않았는지를
여기서 봉인한다. 세 축을 잰다:

1. `--json` 표면의 스키마 — 항목 이름과 필수 키. 분해가 표면을 흔들면 여기서 깨진다.
2. 쪼갠 조각이 각각 혼자 불릴 수 있는가 — 못 부르면 쪼갠 게 아니라 옮겨 적은 것이다.
3. 함수 길이 회귀 — 지금 값을 기준선으로 못박는다. 저장소 자신의 craft 게이트는 diff
   래칫이라 기존 위반을 넘겨서 안 막는다. 그 구멍을 이 앵커가 막는다.
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

from asgard.commands import doctor
from asgard.commands.doctor import wiring

# doctor.py 안에서 70행(craft 예산)을 넘는 함수의 수. 남은 하나는 `_shared_memory_check`(125행).
# **이 수를 올리려면 근거가 있어야 한다** — 새 긴 함수를 들이는 대신 쪼개는 것이 기본값이다.
MAX_LONG_FUNCTIONS = 1
LINE_BUDGET = 70

# doctor 항목 하나가 반드시 들고 있어야 하는 키. `--json` 소비자와 화면 렌더가 같이 읽는다.
REQUIRED_KEYS = {"name", "ok", "detail", "fix"}


def _write(root: str, rel: str, body: str) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def _scaffolded(root: str) -> None:
    """AGENTS.md 가 있는 최소 스캐폴드 — Trinity 레인이 켜지는 조건."""
    _write(root, "AGENTS.md", "# project\n<!-- asgard:trinity -->\n")


class TestDoctorJsonShape(unittest.TestCase):
    """`--json` 표면의 계약. 항목 이름은 소비자가 grep 하는 문자열이라 오타가 곧 결함이다."""

    def _run_json(self) -> dict:
        buf = io.StringIO()
        with redirect_stdout(buf):
            doctor.run_doctor(json_out=True)
        return json.loads(buf.getvalue())

    def test_envelope_keys(self):
        payload = self._run_json()
        for key in ("version", "runtime", "ok", "blocking_ok", "wants_attention", "freyja2_engine", "checks"):
            self.assertIn(key, payload, f"봉투에서 {key} 가 사라졌다")
        self.assertIsInstance(payload["checks"], list)
        self.assertIsInstance(payload["ok"], bool)
        self.assertIsInstance(payload["blocking_ok"], bool)
        self.assertIsInstance(payload["wants_attention"], list)

    def test_ok_counts_every_check(self):
        """ok 가 PATH·security 만 세던 시절에는 다른 항목이 몇 개 빨갛든 done 이 찍혔다."""
        payload = self._run_json()
        self.assertEqual(payload["ok"], all(c["ok"] for c in payload["checks"]))
        self.assertEqual(
            sorted(payload["wants_attention"]),
            sorted(c["name"] for c in payload["checks"] if not c["ok"]),
        )

    def test_every_check_carries_the_required_keys(self):
        for check in self._run_json()["checks"]:
            missing = REQUIRED_KEYS - set(check)
            self.assertFalse(missing, f"{check.get('name')!r} 에 {missing} 가 없다")
            self.assertIsInstance(check["ok"], bool, f"{check['name']!r} 의 ok 가 bool 이 아니다")
            self.assertIsInstance(check["name"], str)

    def test_check_names_are_unique(self):
        names = [c["name"] for c in self._run_json()["checks"]]
        self.assertEqual(len(names), len(set(names)), "항목 이름이 겹치면 소비자가 어느 쪽인지 못 고른다")

    def test_exit_code_separates_unusable_from_degraded(self):
        """0=전부 초록 · 1=이 설치를 못 쓴다 · 2=쓸 수는 있고 손볼 항목이 있다.

        2 를 따로 두지 않으면 지도 하나가 git-ignore 됐다는 이유로 install 스크립트가
        멀쩡한 설치를 실패로 읽는다."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = doctor.run_doctor(json_out=True)
        payload = json.loads(buf.getvalue())
        expected = 0 if payload["ok"] else (1 if not payload["blocking_ok"] else 2)
        self.assertEqual(code, expected)
        self.assertEqual(code == 0, not payload["wants_attention"])


class TestTrinityRowNames(unittest.TestCase):
    """분해 전 `_trinity_checks` 가 내던 항목 이름이 그대로 나온다."""

    def test_scaffolded_root_emits_the_known_rows(self):
        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            names = [c["name"] for c in doctor._trinity_checks(td)]
        for expected in (
            "trinity block (AGENTS.md)",
            "central skill manager adapters",
            "trinity policy",
            "trinity role agents",
            "trinity hooks + Stop gate",
            ".asgard quest-log writable",
        ):
            self.assertIn(expected, names)

    def test_no_agents_md_skips_the_trinity_lane(self):
        with tempfile.TemporaryDirectory() as td:
            rows = doctor._trinity_checks(td)
        self.assertTrue(all(not r["name"].startswith("trinity") for r in rows))

    def test_no_agents_md_still_reports_client_wiring(self):
        """AGENTS.md 는 배선의 조건이 아니다 — `.claude/` 가 있는데 훅이 안 걸린 것을 말해야 한다.

        말 안 하던 동안 doctor 는 정책값(`personal memory inject on`)만 초록으로 보였고,
        스냅샷·회수·Stop 동기화가 한 번도 안 도는 프로젝트가 정상으로 읽혔다."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".claude"))
            rows = {c["name"]: c for c in doctor._trinity_checks(td)}
        self.assertIn("memory wiring (CC)", rows)
        self.assertFalse(rows["memory wiring (CC)"]["ok"])
        self.assertIn("hook file", rows["memory wiring (CC)"]["detail"])

    def test_client_rows_appear_only_for_installed_clients(self):
        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            self.assertEqual([], [c for c in doctor._trinity_checks(td) if "wiring (" in c["name"]])
            os.makedirs(os.path.join(td, ".cursor"), exist_ok=True)
            names = [c["name"] for c in doctor._trinity_checks(td)]
        self.assertIn("memory wiring (Cursor)", names)
        self.assertIn("map wiring (Cursor)", names)
        self.assertNotIn("memory wiring (CC)", names)


class TestDocumentLaneRow(unittest.TestCase):
    """로컬 문서 레인의 유일한 소비처는 턴 시작 주입이라, 고장과 무적중이 화면에서 같아 보였다.

    이 행이 그 둘을 가른다. 레인을 안 쓰는 저장소에는 행 자체가 없어야 한다 — 쓰지도 않는
    파생 인덱스를 온 저장소에 심지 않는 `documents.lane_present` 계약과 같은 이유다."""

    @staticmethod
    def _with_a_document(root: str) -> None:
        from asgard.project_memory import documents

        class Doc:
            document_id = "d1"
            name = "release.md"
            kind = "spec"
            strategy = "local"
            content_hash = "a" * 64
            text = "# 릴리스 절차\n\n배포는 스테이징을 거친 뒤 운영으로 올린다\n"
            entities: list = []

        documents.save_document(root, Doc())

    def test_a_repo_without_the_lane_gets_no_row(self):
        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            names = [c["name"] for c in doctor._trinity_checks(td)]
        self.assertNotIn("project document lane", names)

    def test_the_row_reports_the_size_of_what_was_ingested(self):
        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            self._with_a_document(td)
            rows = {c["name"]: c for c in doctor._trinity_checks(td)}
        self.assertIn("project document lane", rows)
        row = rows["project document lane"]
        self.assertTrue(row["ok"])
        self.assertIn("문서 1건", row["detail"])
        self.assertIn("조각", row["detail"])

    def test_an_unreadable_index_is_named_instead_of_read_as_no_hits(self):
        import sqlite3

        from asgard.project_memory import documents

        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            self._with_a_document(td)
            with unittest.mock.patch.object(
                documents, "_db", side_effect=sqlite3.OperationalError("database is locked")
            ):
                rows = {c["name"]: c for c in doctor._trinity_checks(td)}
        row = rows["project document lane"]
        self.assertFalse(row["ok"])
        self.assertIn("database is locked", row["detail"])
        self.assertTrue(row["fix"])


class TestTemplateRegisteredHooksAreWired(unittest.TestCase):
    """`trinity hooks + Stop gate` 는 정본 템플릿이 등록하는 훅 전부를 잰다.

    손으로 적은 9개 목록과 Stop·SubagentStop 게이트 둘만 보던 판은 목록 밖의 훅을 통째로
    못 봤다: `verifier-context.py` 가 `.claude/settings.json` 에 한 줄도 없는데 이 행은
    `wired` 를 냈다 (26-08-12 실측). 그 훅은 판정자에게 실행 기록을 넘기는 자리라, 안 걸리면
    판정 입력이 빈 채로 초록이 나온다."""

    @staticmethod
    def _template_names(settings: dict) -> set[str]:
        """설정의 `hooks` 아래에서만 훅 이름을 모은다 — `permissions` 의 허용목록에도
        `.claude/hooks/quest-log.py` 가 적혀 있지만 그건 배선이 아니라 승인 규칙이다."""
        return set(re.findall(r"hooks/([a-z0-9-]+)\.py", json.dumps(settings["hooks"])))

    @staticmethod
    def _drop_segment(command: str, name: str) -> str:
        """디스패처 명령에서 훅 하나의 `-- <경로> [인자...]` 조각만 뺀다.

        주입 훅 여럿이 명령 하나를 공유하므로, 항목째 지우면 "이 훅 하나의 배선을 지웠다"가
        아니라 "그 이벤트의 주입을 통째로 지웠다"가 된다 — 사람이 손으로 하는 일과 다르다."""
        head, _, rest = command.partition(" -- ")
        kept = [chunk for chunk in rest.split(" -- ") if f"/{name}.py" not in chunk]
        return head + "".join(" -- " + chunk for chunk in kept) if kept else ""

    @classmethod
    def _without(cls, node, name: str):
        """`name` 을 부르는 배선만 뺀 설정 — 사람이 손으로 지운 배선의 재현."""
        if isinstance(node, list):
            out = []
            for value in node:
                command = str(value.get("command")) if isinstance(value, dict) else ""
                if name not in command:
                    out.append(cls._without(value, name))
                elif "hook-dispatch.py" in command and name != "hook-dispatch":
                    trimmed = cls._drop_segment(command, name)
                    if trimmed:
                        out.append({**value, "command": trimmed})
            return out
        if isinstance(node, dict):
            return {key: cls._without(value, name) for key, value in node.items()}
        return node

    @classmethod
    def _install_cc(cls, root: str, drop_wiring: str = "", drop_file: str = "") -> dict:
        """정본 스캐폴드를 그대로 깐다 — 설정도 훅 파일도 템플릿이 부르는 이름 그대로."""
        from asgard.templates.claude import cc_settings

        _scaffolded(root)
        settings = json.loads(cc_settings())
        for name in cls._template_names(settings):
            if name != drop_file:
                _write(root, os.path.join(".claude", "hooks", f"{name}.py"), "# hook\n")
        if drop_wiring:
            settings["hooks"] = cls._without(settings["hooks"], drop_wiring)
        _write(root, os.path.join(".claude", "settings.json"), json.dumps(settings))
        return settings

    def test_a_fully_wired_scaffold_is_green(self):
        with tempfile.TemporaryDirectory() as td:
            self._install_cc(td)
            row = doctor._trinity_hooks_check(td)
        self.assertTrue(row["ok"], row["detail"])

    def test_the_hook_that_started_this_is_caught(self):
        with tempfile.TemporaryDirectory() as td:
            self._install_cc(td, drop_wiring="verifier-context")
            row = doctor._trinity_hooks_check(td)
        self.assertFalse(row["ok"], "정본이 등록하는 훅이 설정에 없는데 초록이다")
        self.assertIn("verifier-context", row["detail"])
        self.assertIn("SubagentStart", row["detail"])

    def test_every_hook_the_template_registers_is_covered(self):
        """축이 템플릿이라는 것의 판정 — 어느 하나를 빼도 빨개진다. 목록을 손으로 늘리면
        다음에 추가된 훅에서 같은 결함이 다시 난다."""
        with tempfile.TemporaryDirectory() as td:
            names = sorted(self._template_names(self._install_cc(td)))
        self.assertGreater(len(names), 9, "정본은 손목록(9개)보다 많은 훅을 등록한다")
        for name in names:
            with self.subTest(hook=name), tempfile.TemporaryDirectory() as td:
                self._install_cc(td, drop_wiring=name)
                row = doctor._trinity_hooks_check(td)
                self.assertFalse(row["ok"], f"{name} 배선이 빠졌는데 초록이다")
                self.assertIn(name, row["detail"])

    def test_a_registered_hook_with_no_file_is_named(self):
        with tempfile.TemporaryDirectory() as td:
            self._install_cc(td, drop_file="map-activate")
            row = doctor._trinity_hooks_check(td)
        self.assertFalse(row["ok"])
        self.assertIn("map-activate.py", row["detail"])

    def test_a_client_folder_with_no_asgard_wiring_is_not_drift(self):
        """클라이언트가 스스로 만드는 폴더가 있다 — 거기에 경고를 세우면 sync 로 안 사라진다."""
        with tempfile.TemporaryDirectory() as td:
            self._install_cc(td)
            os.makedirs(os.path.join(td, ".cursor"), exist_ok=True)
            self.assertTrue(doctor._trinity_hooks_check(td)["ok"])

    def test_cursor_wiring_is_measured_against_its_own_template(self):
        with tempfile.TemporaryDirectory() as td:
            from asgard.templates.cursor import cursor_hooks_json

            self._install_cc(td)
            hooks = self._without(json.loads(cursor_hooks_json())["hooks"], "verifier-context")
            _write(td, os.path.join(".cursor", "hooks.json"), json.dumps({"version": 1, "hooks": hooks}))
            row = doctor._trinity_hooks_check(td)
        self.assertFalse(row["ok"])
        self.assertIn("Cursor", row["detail"])
        self.assertIn("verifier-context", row["detail"])


class TestDeployedHookCopies(unittest.TestCase):
    """배선이 옳아도 파일이 낡으면 그 훅은 낡은 판정을 한다.

    26-08-20 에 한 세션에서 두 번 났다 — 치환 가드가 없는 프리플라이트 사본이 남았고, 함수를 옮긴
    뒤 옛 자리를 가리키는 안내가 사본에 그대로 실려 있었다. 두 번 다 배선 검사는 초록이었다."""

    def _deploy(self, root: str) -> list:
        from asgard.commands.setup import hook_files

        files = hook_files(os.path.join(root, ".claude", "hooks"), "claude-code")
        for path, body in files:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(body)
        return files

    def test_a_fresh_deploy_is_current(self):
        from asgard.commands.doctor.wiring import _hook_files_check

        with tempfile.TemporaryDirectory() as root:
            self._deploy(root)
            row = _hook_files_check(root)
        self.assertTrue(row["ok"], row["detail"])
        self.assertEqual(REQUIRED_KEYS, REQUIRED_KEYS & set(row))

    def test_a_drifted_copy_is_caught_and_sync_is_prescribed(self):
        from asgard.commands.doctor.wiring import _hook_files_check

        with tempfile.TemporaryDirectory() as root:
            files = self._deploy(root)
            victim = next(p for p, _ in files if p.endswith("env-setup.sh"))
            with open(victim, "a", encoding="utf-8") as handle:
                handle.write("# 옛 판이 남긴 줄\n")
            row = _hook_files_check(root)
        self.assertFalse(row["ok"])
        self.assertIn("env-setup.sh", row["detail"])
        self.assertIn("asgard sync", row["fix"])

    def test_a_client_only_file_is_compared_too(self):
        """`hook_files` 는 클라이언트마다 표가 갈린다 — 이름을 잘못 넘기면 그 파일이 조용히 빠진다."""
        from asgard.commands.doctor.wiring import _hook_files_check

        with tempfile.TemporaryDirectory() as root:
            files = self._deploy(root)
            victim = next(p for p, _ in files if p.endswith("lagom-statusline.sh"))
            with open(victim, "a", encoding="utf-8") as handle:
                handle.write("# drift\n")
            row = _hook_files_check(root)
        self.assertFalse(row["ok"], "CC 전용 파일이 비교에서 빠졌다")
        self.assertIn("lagom-statusline.sh", row["detail"])

    def test_a_missing_library_module_is_caught_here(self):
        """배선 검사의 존재 확인은 배선된 `.py` 만 덮는다 — 56개 중 26개다 (26-08-20 실측).

        나머지 30개에 `asgard_hooklib/` 24개가 들어 있고 그 자리를 아무도 안 보고 있었다. 희생자로
        고른 `paths.py` 는 임포트 폐포로 훅 27개를 전부 죽인다 — 이 층에서 가장 넓은 모듈이다."""
        from asgard.commands.doctor.wiring import _hook_files_check

        with tempfile.TemporaryDirectory() as root:
            files = self._deploy(root)
            os.remove(next(p for p, _ in files if p.endswith(os.path.join("asgard_hooklib", "paths.py"))))
            row = _hook_files_check(root)
        self.assertFalse(row["ok"], "훅 라이브러리가 빠졌는데 초록이다")
        self.assertIn("paths.py", row["detail"])

    def test_an_undecodable_copy_does_not_kill_the_diagnosis(self):
        """이 행 하나가 진단 전체를 끝내면 안 된다 — 프로젝트 검사는 권고다.

        UTF-8 이 아닌 사본은 `OSError` 가 아니라 `UnicodeDecodeError` 를 낸다. 좁은 except 로
        받던 판에서는 그 예외가 `run_doctor` 까지 올라가 doctor 가 한 줄도 못 그렸다."""
        from asgard.commands.doctor.wiring import _hook_files_check

        with tempfile.TemporaryDirectory() as root:
            files = self._deploy(root)
            victim = next(p for p, _ in files if p.endswith("quest-log.py"))
            with open(victim, "wb") as handle:
                handle.write(b"\xff\xfe\x00\x00 not utf-8")
            row = _hook_files_check(root)
        self.assertFalse(row["ok"])
        self.assertIn("quest-log.py", row["detail"])

    def test_an_unknown_client_folder_is_skipped_not_fatal(self):
        """표에 없는 폴더를 대괄호로 찾으면 클라이언트가 하나 늘 때 진단이 통째로 죽는다."""
        from asgard.commands.doctor import wiring

        with tempfile.TemporaryDirectory() as root:
            self._deploy(root)
            os.makedirs(os.path.join(root, ".newhost", "hooks"))
            extra = wiring._Client("New", ".newhost", "x.json", "SessionStart", "UserPromptSubmit", ".agents")
            with unittest.mock.patch.object(wiring, "_MEMORY_CLIENTS", (*wiring._MEMORY_CLIENTS, extra)):
                row = wiring._hook_files_check(root)
        self.assertTrue(row["ok"], row["detail"])


class TestPiecesStandAlone(unittest.TestCase):
    """쪼갠 조각을 각각 혼자 부른다 — 못 부르면 분해가 아니라 재배치다."""

    def test_row_builders_return_one_well_formed_row(self):
        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            for build in (
                doctor._trinity_block_check,
                doctor._skill_adapter_check,
                doctor._trinity_policy_check,
                doctor._role_agents_check,
                doctor._trinity_hooks_check,
                doctor._quest_log_writable_check,
            ):
                with self.subTest(fn=build.__name__):
                    row = build(td)
                    self.assertEqual(REQUIRED_KEYS, REQUIRED_KEYS & set(row))
                    self.assertIsInstance(row["ok"], bool)

    def test_optional_builders_return_a_row_or_none(self):
        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            for build in (doctor._custom_manual_check, doctor._einherjar_check, doctor._lagom_mode_check):
                with self.subTest(fn=build.__name__):
                    row = build(td)
                    self.assertTrue(row is None or REQUIRED_KEYS <= set(row))

    def test_client_wiring_checks_returns_a_list(self):
        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            self.assertEqual([], doctor._client_wiring_checks(td))

    def test_trinity_block_check_reads_the_marker(self):
        with tempfile.TemporaryDirectory() as td:
            _write(td, "AGENTS.md", "no marker in here\n")
            self.assertFalse(doctor._trinity_block_check(td)["ok"])
            _scaffolded(td)
            self.assertTrue(doctor._trinity_block_check(td)["ok"])


class TestHookInterpreterIsExecuted(unittest.TestCase):
    """훅 인터프리터 줄은 PATH 조회가 아니라 실행으로 판정한다.

    조회만 하던 동안 doctor 는 자기 PATH 에서 `uv` 를 찾고 초록을 찍었다. 정작 훅이 도는
    프로세스(독·Finder·launchd)는 `/usr/bin:/bin:/usr/sbin:/sbin` 넉 줄만 물려받아 exit 127 이
    났고, 훅 계약이 fail-open 이라 가드가 전부 꺼진 채로 아무도 그 사실을 몰랐다."""

    @staticmethod
    def _wire(root: str, command: str) -> None:
        settings = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": command}]}]}}
        _write(root, os.path.join(".claude", "settings.json"), json.dumps(settings))

    def test_a_dead_wired_interpreter_is_red_with_an_actionable_fix(self):
        with tempfile.TemporaryDirectory() as td:
            self._wire(td, '/nonexistent/bin/uv run --no-project python "$CLAUDE_PROJECT_DIR/.claude/hooks/x.py"')
            row = doctor._hook_interpreter_check(td)
        self.assertFalse(row["ok"])
        self.assertIn("/nonexistent/bin/uv", row["detail"] + row["fix"])
        self.assertIn("asgard sync", row["fix"])

    def test_a_live_wired_interpreter_is_green(self):
        with tempfile.TemporaryDirectory() as td:
            self._wire(td, '%s "$CLAUDE_PROJECT_DIR/.claude/hooks/x.py"' % sys.executable)
            row = doctor._hook_interpreter_check(td)
        self.assertTrue(row["ok"], row["detail"])
        self.assertEqual([sys.executable], doctor._wired_hook_argv(td) or [sys.executable])

    def test_arguments_after_the_hook_path_do_not_reach_the_interpreter(self):
        """인터프리터는 첫 훅 경로 **앞까지**다 — 뒤에 오는 것은 훅의 인자다.

        훅 경로만 걸러내던 판은 나머지를 전부 인터프리터에 넘겼다. 주입 훅을 묶어 부르는 줄
        (`hook-dispatch.py -- <경로> -- <경로>`)에서 `python -- -c pass` 가 되어, 인터프리터는
        멀쩡한데 이 행이 빨개졌다 (26-08-14 실측)."""
        with tempfile.TemporaryDirectory() as td:
            self._wire(
                td,
                '%s "$CLAUDE_PROJECT_DIR/.claude/hooks/hook-dispatch.py"'
                ' -- "$CLAUDE_PROJECT_DIR/.claude/hooks/a.py"'
                ' -- "$CLAUDE_PROJECT_DIR/.claude/hooks/b.py" claude brief' % sys.executable,
            )
            self.assertEqual(doctor._wired_hook_argv(td), [sys.executable])
            self.assertTrue(doctor._hook_interpreter_check(td)["ok"])

    def test_no_wiring_falls_back_to_the_interpreter_this_machine_would_wire(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(doctor._wired_hook_argv(td))
            self.assertTrue(doctor._hook_interpreter_check(td)["ok"])


class TestConfigReading(unittest.TestCase):
    """설정 읽기의 실패 모드. 읽을 수 없는 설정은 '배선 없음'이지 예외가 아니다."""

    def test_missing_config_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual({}, doctor._client_config(td, ".claude", "settings.json"))

    def test_unparseable_config_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            _write(td, ".claude/settings.json", "{not json")
            self.assertEqual({}, doctor._client_config(td, ".claude", "settings.json"))

    def test_non_mapping_config_is_empty(self):
        """최상위가 리스트인 설정 — `.get` 을 부르면 터지던 자리."""
        with tempfile.TemporaryDirectory() as td:
            _write(td, ".claude/settings.json", "[1, 2, 3]")
            self.assertEqual({}, doctor._client_config(td, ".claude", "settings.json"))

    def test_hook_wired_survives_a_malformed_hooks_value(self):
        self.assertFalse(doctor._hook_wired({"hooks": "not a mapping"}, "Stop", "x"))
        self.assertFalse(doctor._hook_wired({}, "Stop", "x"))
        self.assertTrue(doctor._hook_wired({"hooks": {"Stop": [{"command": "x.py"}]}}, "Stop", "x"))

    def test_hook_wired_survives_a_non_serializable_value(self):
        """tomllib 은 datetime 을 돌려준다 — json.dumps 가 거기서 터진다."""
        import datetime

        config = {"hooks": {"SessionStart": datetime.datetime(1979, 5, 27), "Stop": ["map-activate"]}}
        self.assertFalse(doctor._hook_wired(config, "SessionStart", "map-activate"))
        self.assertTrue(doctor._hook_wired(config, "Stop", "map-activate"), "성한 키까지 같이 죽으면 안 된다")


class TestClientConfigIsolation(unittest.TestCase):
    """클라이언트마다 자기 설정만 본다.

    쪼개기 전에는 설정 읽기가 실패하면 `config` 가 **이전 반복의 값**으로 남아, 맵 배선 판정이
    옆 클라이언트의 설정을 근거로 녹색을 냈다. 진단기의 거짓 녹색은 가장 나쁜 실패다."""

    def test_a_broken_config_does_not_borrow_the_previous_client(self):
        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            # CC 는 맵 훅이 전부 걸려 있고, Codex 는 폴더만 있고 설정이 깨져 있다.
            _write(
                td,
                ".claude/settings.json",
                json.dumps(
                    {
                        "hooks": {
                            "SessionStart": [{"command": "map-activate"}],
                            "UserPromptSubmit": [{"command": "map-activate"}],
                            "SubagentStart": [{"command": "map-activate"}],
                            "Stop": [{"command": "map-activate"}],
                        }
                    }
                ),
            )
            _write(td, ".codex/config.toml", "this is [not valid toml\n")
            rows = {c["name"]: c for c in doctor._trinity_checks(td)}
        codex = rows["map wiring (Codex)"]
        self.assertFalse(codex["ok"])
        for event in ("SessionStart", "UserPromptSubmit", "SubagentStart", "Stop refresh"):
            self.assertIn(event, codex["detail"], "옆 클라이언트 설정을 근거로 녹색을 내면 안 된다")


class TestFixCommandsAreRunnable(unittest.TestCase):
    """doctor 가 내미는 `asgard …` 는 실행되는 명령이어야 한다.

    `_TRINITY_FIX` 는 배선이 빠진 모든 행의 유일한 손짓이었는데 `asgard setup --force` 라고
    적혀 있었다. `setup` 은 `setup map` 하나만 가진 그룹이라 그 줄은 exit 2 를 낸다 — 진단이
    내민 명령이 안 돌면 사람은 스스로 명령을 추측하고, 그 추측이 틀려도 아무도 안 막는다.

    판정 대상은 산문이 아니라 **지시**다: 독스트링은 뺀다 (코드를 읽는 사람 몫). 괄호 안에
    이름만 적힌 형태(`(또는 setup --force)`)는 `asgard` 접두가 없어 이 검사가 못 본다."""

    _TOKEN = re.compile(r"asgard ((?:[a-z][a-z0-9-]*)(?: [a-z][a-z0-9-]*)*(?: --[a-z][a-z0-9-]*)*)")

    @staticmethod
    def _resolve(words: list[str]):
        """CLI 트리를 실제로 걸어간다 — 이름 목록을 복사해 두면 그 목록이 다음 결함이 된다."""
        import typer

        from asgard.cli import app

        node = typer.main.get_command(app)
        walked: list[str] = []
        for word in words:
            commands = getattr(node, "commands", None)
            if not commands or word not in commands:
                break
            node, _ = commands[word], walked.append(word)
        return node, walked

    @classmethod
    def _problems(cls, text: str) -> list[str]:
        found: list[str] = []
        for match in cls._TOKEN.finditer(text):
            parts = match.group(1).split()
            node, walked = cls._resolve([p for p in parts if not p.startswith("--")])
            if not walked:
                continue  # 명령이 아니라 산문이다 ("asgard on PATH")
            if getattr(node, "commands", None):
                found.append(f"{match.group(0)!r} — `asgard {' '.join(walked)}` 는 그룹이라 하위 명령이 필요")
                continue
            options = {opt for param in node.params for opt in param.opts}
            found += [
                f"{match.group(0)!r} — `asgard {' '.join(walked)}` 에 {flag} 없음"
                for flag in parts
                if flag.startswith("--") and flag not in options
            ]
        return found

    @staticmethod
    def _instruction_strings(path: Path) -> list[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = {
            id(holder.body[0].value)
            for holder in ast.walk(tree)
            if isinstance(holder, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and holder.body
            and isinstance(holder.body[0], ast.Expr)
            and isinstance(holder.body[0].value, ast.Constant)
        }
        return [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
        ]

    def test_the_checker_catches_the_command_that_started_this(self):
        self.assertTrue(self._problems("asgard setup --force로 Trinity 에셋 재설치"))
        self.assertEqual([], self._problems("asgard init --force 로 Trinity 에셋 재설치"))

    def test_every_named_command_in_the_doctor_package_resolves(self):
        bad: list[str] = []
        for path in sorted(Path(doctor.__file__).parent.glob("*.py")):
            bad += [
                f"{path.name}: {problem}"
                for text in self._instruction_strings(path)
                for problem in self._problems(text)
            ]
        self.assertEqual([], bad, "doctor 가 없는 명령을 안내한다")


class TestBankReachability(unittest.TestCase):
    """연결된 뱅크를 이 저장소의 세션이 읽을 수 있는가 — 두 사실을 잇는 행.

    26-08-07 실측한 형상: 뱅크는 A 저장소에 등록됐고 회수 배선은 B 저장소에 있었다. 행 둘은
    각각 자기 사실만 맞게 말했고, "등록된 뱅크가 어떤 프롬프트에도 안 들어간다"는 결론은
    아무도 말하지 않았다. 클라이언트 폴더가 아예 없으면 배선 행 자체가 안 나와서 초록이었다."""

    @staticmethod
    def _bank(root: str, project_id: str = "vn_onm_yun") -> None:
        _write(
            root,
            os.path.join(".asgard", "asgard-setting-project.json"),
            json.dumps(
                {"project_memory": {"engine": "hindsight", "endpoint": "http://127.0.0.1:9", "project_id": project_id}}
            ),
        )

    @staticmethod
    def _wired_cc(root: str) -> None:
        _write(root, os.path.join(".claude", "hooks", "memory-activate.py"), "# hook\n")
        _write(root, os.path.join(".claude", "skills", "asgard-memory", "SKILL.md"), "# skill\n")
        entry = [{"hooks": [{"type": "command", "command": "python .claude/hooks/memory-activate.py"}]}]
        _write(
            root,
            os.path.join(".claude", "settings.json"),
            json.dumps({"hooks": {"SessionStart": entry, "UserPromptSubmit": entry, "Stop": entry}}),
        )

    def _row(self, root: str) -> dict:
        row = doctor._bank_reachability_check(root)
        self.assertIsNotNone(row, "뱅크가 안 읽히는데 행이 없다")
        assert row is not None  # 아래 첨자 접근의 타입 좁히기 (ty)
        return row

    def test_a_bank_with_no_client_at_all_is_named(self):
        with tempfile.TemporaryDirectory() as td:
            self._bank(td)
            row = self._row(td)
        self.assertIn("vn_onm_yun", row["detail"])
        self.assertIn("클라이언트 배선이 하나도 없어요", row["detail"])
        self.assertEqual([], self._fix_problems(row["fix"]))

    def test_a_half_wired_client_names_what_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self._bank(td)
            os.makedirs(os.path.join(td, ".claude"))
            row = self._row(td)
        self.assertIn("hook file", row["detail"])
        self.assertIn("CC", row["detail"])

    def test_one_fully_wired_client_is_enough(self):
        with tempfile.TemporaryDirectory() as td:
            self._bank(td)
            self._wired_cc(td)
            self.assertIsNone(doctor._bank_reachability_check(td))

    def test_no_bank_means_no_row(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(doctor._bank_reachability_check(td))
            os.makedirs(os.path.join(td, ".claude"))
            self.assertIsNone(doctor._bank_reachability_check(td))

    def test_the_row_reaches_the_doctor_surface(self):
        with tempfile.TemporaryDirectory() as td:
            self._bank(td)
            names = [row["name"] for row in doctor._trinity_checks(td)]
        self.assertIn("project memory reachability", names)

    @staticmethod
    def _fix_problems(text: str) -> list[str]:
        return TestFixCommandsAreRunnable._problems(text)


class TestFunctionLengthAnchor(unittest.TestCase):
    """함수 길이 회귀 방지. craft 는 diff 래칫이라 이미 있는 위반을 넘겨서 안 막는다."""

    @staticmethod
    def _long_functions() -> list[tuple[str, int]]:
        """doctor 패키지 전체를 훑는다 — 한 파일만 보면 검사를 옆 모듈로 옮기는 것이 곧 감량이 된다."""
        long: list[tuple[str, int]] = []
        for path in sorted(Path(doctor.__file__).parent.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                span = (node.end_lineno or node.lineno) - node.lineno + 1  # end_lineno 는 선택 필드다
                if span > LINE_BUDGET:
                    long.append((node.name, span))
        return sorted(long, key=lambda pair: -pair[1])

    def test_long_function_count_does_not_grow(self):
        long = self._long_functions()
        self.assertLessEqual(
            len(long),
            MAX_LONG_FUNCTIONS,
            f"{LINE_BUDGET}행을 넘는 함수가 늘었다: {long} — 늘리지 말고 쪼개라",
        )

    def test_trinity_checks_stays_a_composer(self):
        """조립기는 목록을 읽는 자리다 — 여기에 판정 로직이 다시 쌓이면 원점이다."""
        long = dict(self._long_functions())
        self.assertNotIn("_trinity_checks", long)


class TestScaffoldDriftDirection(unittest.TestCase):
    """어긋난 훅 사본을 두고 doctor 가 어느 방향을 권하는가.

    26-08-21 에 0.10.19 설치본이 0.10.22 로 깔린 훅 18개를 보고 "판본 뒤처짐"이라 적고
    `asgard sync --here` 를 권했다. 그대로 돌렸으면 `quest-log.py` 가 50,737B 에서
    47,530B 로 줄고, `.claude` 는 gitignore 뒤라 되돌릴 수도 없었다. 이 클래스는 그
    방향이 도장으로만 주장되는지를 잰다."""

    SYNC = "asgard sync --here — 이 프로젝트의 훅 표를 다시 깐다"

    @staticmethod
    def _stamp(root: str, version: str) -> None:
        from asgard.settings import write_scaffold_version

        write_scaffold_version(root, version)

    def test_no_stamp_claims_no_direction(self):
        """도장을 남기기 전에 깔린 프로젝트가 있다 — 모르면 아무 방향도 말하지 않는다."""
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(wiring._drift_fix(td, self.SYNC), self.SYNC)

    def test_a_newer_stamp_sends_you_to_update_not_sync(self):
        from asgard import __version__

        newer = "%d.0.0" % (int(__version__.split(".")[0]) + 1)
        with tempfile.TemporaryDirectory() as td:
            self._stamp(td, newer)
            fix = wiring._drift_fix(td, self.SYNC)
        self.assertIn("asgard update", fix)
        self.assertIn(newer, fix)
        self.assertNotIn("asgard sync", fix)

    def test_the_engines_own_version_is_not_newer_than_itself(self):
        from asgard import __version__

        with tempfile.TemporaryDirectory() as td:
            self._stamp(td, __version__)
            self.assertNotIn("asgard update", wiring._drift_fix(td, self.SYNC))

    def test_the_same_version_number_does_not_settle_the_direction(self):
        """번호가 같아도 빌드는 다를 수 있다 — 그러면 sync 를 권하면 안 된다.

        26-08-22 실측: 설치본과 소스가 둘 다 0.10.22 를 답하는데 `verifier_gate.py` 가
        32,673B 대 36,785B 였다. 태그와 다음 태그 사이의 체크아웃이 늘 그 상태다. 번호만
        비교하던 판은 그 자리에서 "안 뒤처졌다"로 읽고 `asgard sync --here` 를 다시 권했다 —
        하루 전에 막으려던 바로 그 되감는 조언이다."""
        from asgard import __version__

        with tempfile.TemporaryDirectory() as td:
            self._stamp(td, __version__)
            fix = wiring._drift_fix(td, self.SYNC)
        self.assertNotEqual(fix, self.SYNC, "방향을 모르는데 sync 를 권한다")
        self.assertIn(__version__, fix, "어느 번호가 겹쳤는지를 안 적는다")

    def test_a_stamp_one_release_below_still_sends_you_to_sync(self):
        """같은 번호만 모르는 것이다 — 바로 아래 판이면 방향은 여전히 도장이 답한다.

        도장을 `0.0.1` 로 두는 형제 시험과 달리 여기는 **붙어 있는** 판을 쓴다. 그래야 판을
        앞 두 마디까지만 비교하는 판이 `0.10.21` 을 같은 번호로 읽는 자리를 잡는다. 멀리 떨어진
        도장은 그 오독을 못 본다 — `0.0` 과 `0.10` 은 잘라도 다르기 때문이다.

        도장을 `version_tuple` 로 만들지 않는다. 시험이 자기가 재는 함수로 자기 입력을 만들면
        그 함수가 깨질 때 입력도 같이 틀어져 시험이 초록으로 남는다. 26-08-22 판정이 그 자리를
        잡았다 — `version_tuple` 을 자르는 변이에서 도장이 `0.10.21` 이 아니라 `0.9` 가 됐고,
        표적과 형제가 둘 다 통과했다."""
        from asgard import __version__

        chunks = __version__.split(".")
        older = __version__  # 뺄 마디가 없으면 그대로 남아 아래 가드가 터진다
        for i in range(len(chunks) - 1, -1, -1):
            if chunks[i].isdigit() and int(chunks[i]):
                older = ".".join([*chunks[:i], str(int(chunks[i]) - 1), *chunks[i + 1 :]])
                break
        self.assertNotEqual(older, __version__, "이 엔진 판에서는 아래 판을 못 만든다 — 시험이 헛돈다")
        with tempfile.TemporaryDirectory() as td:
            self._stamp(td, older)
            self.assertEqual(wiring._drift_fix(td, self.SYNC), self.SYNC)

    def test_an_older_stamp_still_sends_you_to_sync(self):
        with tempfile.TemporaryDirectory() as td:
            self._stamp(td, "0.0.1")
            self.assertEqual(wiring._drift_fix(td, self.SYNC), self.SYNC)

    def test_an_unreadable_stamp_is_read_as_no_stamp(self):
        from asgard.settings import SCAFFOLD_STAMP, ensure_state_dir

        with tempfile.TemporaryDirectory() as td:
            ensure_state_dir(td)
            _write(td, os.path.join(".asgard", "state", SCAFFOLD_STAMP), "{not json")
            self.assertEqual(wiring._drift_fix(td, self.SYNC), self.SYNC)

    def test_both_drift_rows_go_through_the_same_direction(self):
        """두 행이 같은 사실을 다르게 처방하면 하나는 틀린 것이다."""
        from asgard import __version__

        newer = "%d.0.0" % (int(__version__.split(".")[0]) + 1)
        with tempfile.TemporaryDirectory() as td:
            TestTemplateRegisteredHooksAreWired._install_cc(td)
            self._stamp(td, newer)
            rows = {row["name"]: row for row in doctor._trinity_checks(td)}
            rows.update({row["name"]: row for row in wiring._mode_parity_check(td)})
        for name in ("hook files (deployed copies)", "mode parity (CC)"):
            with self.subTest(row=name):
                self.assertIn(name, rows)
                self.assertNotIn("판본 뒤처짐", rows[name]["detail"], "측정하지 않은 방향을 주장한다")
                if not rows[name]["ok"]:
                    self.assertIn("asgard update", rows[name]["fix"], "새 사본을 옛 템플릿으로 덮으라고 한다")

    def test_version_tuple_orders_by_the_leading_parts(self):
        from asgard.settings import version_tuple

        self.assertGreater(version_tuple("0.10.22"), version_tuple("0.10.19"))
        self.assertGreater(version_tuple("0.10.0"), version_tuple("0.9.99"))
        self.assertEqual(version_tuple("1.2.3rc1"), (1, 2, 3))
        self.assertEqual(version_tuple("not-a-version"), ())


class TestDriftPathsPointAtRealFiles(unittest.TestCase):
    """안내가 부르는 경로는 열 수 있어야 한다 — `.claude/asgard_hooklib/baseline.py` 는 없다."""

    def test_a_drifted_copy_is_named_by_a_path_that_exists(self):
        from asgard.commands.setup import hook_files

        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            hooks_dir = os.path.join(td, ".claude", "hooks")
            os.makedirs(hooks_dir, exist_ok=True)
            for path, body in hook_files(hooks_dir, "claude-code"):
                _write(td, os.path.relpath(path, td), body)
            nested = os.path.join(hooks_dir, "asgard_hooklib", "baseline.py")
            self.assertTrue(os.path.isfile(nested), "중첩 사본이 있어야 이 축을 잰다")
            _write(td, os.path.relpath(nested, td), "# drifted\n")
            named = wiring._stale_hook_files(td)
        self.assertTrue(named, "내용이 다른데 아무것도 안 적혔다")
        self.assertIn(".claude/hooks/asgard_hooklib/baseline.py", named)


class TestSyncStampsItsVersion(unittest.TestCase):
    """도장을 남기는 쪽이 없으면 방향 판정은 영영 어둡다."""

    def test_a_real_sync_leaves_the_version_it_wrote(self):
        from asgard import __version__
        from asgard.commands.sync import sync_project
        from asgard.settings import read_scaffold_version

        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            os.makedirs(os.path.join(td, ".claude"), exist_ok=True)
            sync_project(td, cc=True, cursor=False, codex=False)
            self.assertEqual(read_scaffold_version(td), __version__)

    def test_a_dry_run_leaves_nothing_behind(self):
        from asgard.commands.sync import sync_project
        from asgard.settings import read_scaffold_version

        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            os.makedirs(os.path.join(td, ".claude"), exist_ok=True)
            sync_project(td, cc=True, cursor=False, codex=False, dry_run=True)
            self.assertEqual(read_scaffold_version(td), "")


class TestFrozenDefaultsAreNamed(unittest.TestCase):
    """설정 파일이 코드 기본값을 베껴 두면, 기본값이 움직여도 그 프로젝트만 옛 값에 남는다.

    26-08-21 실측: `ticket_runtime.lease_seconds` 기본값을 300 에서 1800 으로 올렸는데
    유효값이 300 그대로였다. 그 저장소의 설정은 `trinity_policy` 키 15개 중 12개가 기본값과
    글자까지 같았다 — 고른 것이 아니라 통째로 베낀 것이다. 병합을 한 겹 깊게 해도 이 자리는
    안 풀린다(적힌 값이 이기는 것이 맞으므로). 그래서 진단이 이름을 대야 한다."""

    def _root_with(self, policy: dict) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.makedirs(os.path.join(tmp.name, ".asgard"), exist_ok=True)
        with open(os.path.join(tmp.name, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as fh:
            json.dump({"trinity_policy": policy}, fh)
        return tmp.name

    def test_a_copied_default_is_named(self):
        from asgard_hooklib.policy import DEFAULT_POLICY

        root = self._root_with({"ticket_runtime": dict(DEFAULT_POLICY["ticket_runtime"])})
        row = wiring._trinity_policy_check(root)
        self.assertIn("ticket_runtime", row["detail"], "베껴 둔 기본값을 이름 대지 않았다")
        self.assertIn("기본값이 바뀌어도", row["detail"])

    def test_a_chosen_value_is_not_named(self):
        """고른 값을 경고하면 그 경고는 곧 무시된다."""
        root = self._root_with({"baseline_timeout": 999})
        row = wiring._trinity_policy_check(root)
        self.assertNotIn("baseline_timeout", row["detail"])
        self.assertNotIn("기본값이 바뀌어도", row["detail"])

    def test_the_count_is_the_number_of_copied_keys(self):
        from asgard_hooklib.policy import DEFAULT_POLICY

        copied = {k: DEFAULT_POLICY[k] for k in ("quest_retention", "verify_level", "failure_threshold")}
        row = wiring._trinity_policy_check(self._root_with({**copied, "baseline_timeout": 999}))
        self.assertIn("3개", row["detail"], row["detail"])

    def test_the_row_stays_green_because_nothing_is_broken_yet(self):
        """아직 값이 같으므로 동작은 정상이다 — 이 행은 경고가 아니라 안내다."""
        from asgard_hooklib.policy import DEFAULT_POLICY

        row = wiring._trinity_policy_check(self._root_with({"quest_retention": DEFAULT_POLICY["quest_retention"]}))
        self.assertTrue(row["ok"])

    def test_the_guidance_sits_in_the_line_people_actually_read(self):
        """화면 렌더는 `ok=False` 인 행의 `fix` 만 찍는다.

        이 행은 초록으로 남으므로, 무엇을 하면 되는지를 `fix` 에 적으면 `--json` 에서만 보이고
        터미널에서는 아무도 못 읽는다. 시험이 안 보이는 칸을 재면 그 안내는 없는 것과 같다."""
        from asgard_hooklib.policy import DEFAULT_POLICY

        row = wiring._trinity_policy_check(self._root_with({"quest_retention": DEFAULT_POLICY["quest_retention"]}))
        self.assertTrue(row["ok"], "초록이 아니면 이 시험의 전제가 다르다")
        self.assertIn("지우면", row["detail"], "안내가 화면에 안 나오는 칸에 있다")

    def test_the_renderer_really_hides_the_fix_line_on_a_green_row(self):
        """위 시험의 전제 자체를 잰다 — 렌더가 바뀌면 여기서 먼저 깨져야 한다.

        처음 판은 `ast.Attribute` 로 `fix` 를 찾았는데 렌더는 `ch["fix"]` 로 읽는다. 그것은
        `ast.Subscript` 라 매칭이 0건이었고, 빈 제너레이터의 `any()` 는 False 이므로 단언이
        무조건 통과했다 — 아무것도 안 재는 시험이었다. 그래서 먼저 **몇 개를 찾았는지** 세고,
        0건이면 그 자체를 실패로 본다."""
        tree = ast.parse(Path("src/asgard/commands/doctor/__init__.py").read_text(encoding="utf-8"))
        reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "fix"
        ]
        self.assertTrue(reads, "렌더에서 fix 를 읽는 자리를 못 찾았다 — 이 시험이 헛돌고 있다")
        for node in reads:
            with self.subTest(line=node.lineno):
                self.assertTrue(
                    _guarded_by_ok(tree, node),
                    "fix 가 ok 를 안 보고 찍힌다 — 그렇다면 안내를 fix 에 둬도 되고, 이 시험의 전제가 바뀐 것이다",
                )

    @staticmethod
    def _fix_read(tree: ast.AST) -> ast.AST:
        """그 코드에서 `...["fix"]` 를 읽는 첨자 노드 — 술어에 넣을 표적."""
        return next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "fix"
        )

    def test_the_guard_predicate_rejects_a_name_that_merely_contains_ok(self):
        """술어가 재던 것이 참조가 아니라 글자였다 — `"ok" not in ast.dump(...)` 는 부분일치다.

        `if hook:` 의 덤프에는 `Name(id='hook')` 이 들어 있어 `ok` 를 포함한다. 그러면 `ok` 를
        아예 안 보는 렌더가 이 시험을 통과한다. `doctor/__init__.py` 에서는 아직 재현되지
        않지만(그 자리를 가리는 `if` 가 하나뿐), 통과시키는 모양이 있다는 것 자체가 구멍이다."""
        tree = ast.parse("if hook:\n    print(ch['fix'])\n")
        self.assertFalse(_guarded_by_ok(tree, self._fix_read(tree)))

    def test_the_guard_predicate_still_matches_the_real_guard(self):
        """조인 술어가 진짜 가드까지 놓치면 반대쪽으로 헛돈다 — 두 방향을 같이 잰다."""
        tree = ast.parse("if not ch['ok']:\n    print(ch['fix'])\n")
        self.assertTrue(_guarded_by_ok(tree, self._fix_read(tree)))

    def test_a_project_with_no_copies_says_nothing_extra(self):
        row = wiring._trinity_policy_check(self._root_with({"baseline_timeout": 999}))
        self.assertNotIn("지우면", row["detail"])


def _reads_ok(test: ast.AST) -> bool:
    """이 조건식이 `ok` 라는 이름·속성·문자열 키를 실제로 읽는가.

    `ast.dump(...)` 문자열에 `ok` 가 들어 있는지로 물으면 글자 부분일치라 `hook`·`token`·
    `lookup` 같은 이름이 우연히 통과한다. 재야 하는 것은 글자가 아니라 참조라, 노드를 걸어
    이름이 정확히 `ok` 인 자리만 센다."""
    for node in ast.walk(test):
        if isinstance(node, ast.Name) and node.id == "ok":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "ok":
            return True
        if isinstance(node, ast.Constant) and node.value == "ok":
            return True
    return False


def _guarded_by_ok(tree: ast.AST, target: ast.AST) -> bool:
    """이 노드가 `ok` 를 보는 `if` 의 본문 안에 있는가.

    "어떤 `if` 안인가" 만 물으면 `if True:` 도 통과한다 — 그러면 조건이 사라진 렌더를
    잡지 못한다. 재야 하는 것은 자리가 아니라 **무엇을 보고 감추는가** 다."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not _reads_ok(node.test):
            continue
        if any(target is inner for body in (node.body, node.orelse) for stmt in body for inner in ast.walk(stmt)):
            return True
    return False


if __name__ == "__main__":
    unittest.main()
