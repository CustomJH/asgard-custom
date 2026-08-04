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
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

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
        for key in ("version", "runtime", "ok", "freyja2_engine", "checks"):
            self.assertIn(key, payload, f"봉투에서 {key} 가 사라졌다")
        self.assertIsInstance(payload["checks"], list)
        self.assertIsInstance(payload["ok"], bool)

    def test_every_check_carries_the_required_keys(self):
        for check in self._run_json()["checks"]:
            missing = REQUIRED_KEYS - set(check)
            self.assertFalse(missing, f"{check.get('name')!r} 에 {missing} 가 없다")
            self.assertIsInstance(check["ok"], bool, f"{check['name']!r} 의 ok 가 bool 이 아니다")
            self.assertIsInstance(check["name"], str)

    def test_check_names_are_unique(self):
        names = [c["name"] for c in self._run_json()["checks"]]
        self.assertEqual(len(names), len(set(names)), "항목 이름이 겹치면 소비자가 어느 쪽인지 못 고른다")

    def test_exit_code_follows_ok(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = doctor.run_doctor(json_out=True)
        self.assertEqual(code, 0 if json.loads(buf.getvalue())["ok"] else 1)


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

    def test_client_rows_appear_only_for_installed_clients(self):
        with tempfile.TemporaryDirectory() as td:
            _scaffolded(td)
            self.assertEqual([], [c for c in doctor._trinity_checks(td) if "wiring (" in c["name"]])
            os.makedirs(os.path.join(td, ".cursor"), exist_ok=True)
            names = [c["name"] for c in doctor._trinity_checks(td)]
        self.assertIn("memory wiring (Cursor)", names)
        self.assertIn("map wiring (Cursor)", names)
        self.assertNotIn("memory wiring (CC)", names)


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


class TestFunctionLengthAnchor(unittest.TestCase):
    """함수 길이 회귀 방지. craft 는 diff 래칫이라 이미 있는 위반을 넘겨서 안 막는다."""

    @staticmethod
    def _long_functions() -> list[tuple[str, int]]:
        path = os.path.join(os.path.dirname(doctor.__file__), "doctor.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        long: list[tuple[str, int]] = []
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
