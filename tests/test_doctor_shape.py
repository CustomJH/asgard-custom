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
from contextlib import redirect_stdout
from pathlib import Path

from asgard.commands import doctor

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


if __name__ == "__main__":
    unittest.main()
