"""asgard style init/list/check — 규격을 설정에 적고, 읽어서 돌리는 왕복.

엔진과 게이트는 따로 시험한다(`test_code_style.py`·`test_style_gate.py`). 여기서 지키는 것은
그 둘을 잇는 글루다: **적은 것이 그대로 다시 읽히는가**, **덮어쓰기가 사고로 안 일어나는가**,
**JSON 형식이 게이트가 읽는 계약과 같은가**.

실행: uv run pytest tests/test_style_command.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest

from asgard import code_style
from asgard.commands.style import run_check, run_init, run_list


@contextlib.contextmanager
def _repo(**files: str):
    """이 저장소를 cwd 로 연다 — 명령들이 `_project_root(os.getcwd())` 로 뿌리를 찾는다."""
    root = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", root], check=True, capture_output=True)
    for rel, body in files.items():
        path = os.path.join(root, rel.replace("|", "/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
    was = os.getcwd()
    os.chdir(root)
    try:
        yield root
    finally:
        os.chdir(was)


def _json(call) -> dict:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        call()
    return json.loads(out.getvalue())


def _settings(root: str) -> dict:
    with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), encoding="utf-8") as handle:
        return json.load(handle)


_PYPROJECT = "[tool.ruff]\nline-length = 100\n"


class Init(unittest.TestCase):
    def test_what_was_detected_is_what_gets_written(self):
        with _repo(**{"pyproject.toml": _PYPROJECT}) as root:
            written = _json(lambda: run_init(json_out=True))
            self.assertTrue(written["written"])
            section = _settings(root)["code_style"]
            self.assertTrue(section["enabled"])
            self.assertEqual([t["name"] for t in section["tools"]], [t["name"] for t in written["tools"]])
            self.assertEqual([t.name for t in code_style.declared(root)], ["ruff", "ruff-format"])

    def test_nothing_detected_writes_nothing(self):
        with _repo(**{"README.md": "# x"}) as root:
            self.assertFalse(_json(lambda: run_init(json_out=True))["written"])
            self.assertFalse(os.path.exists(os.path.join(root, ".asgard", "asgard-setting-project.json")))

    def test_a_hand_edited_declaration_is_not_overwritten(self):
        with _repo(**{"pyproject.toml": _PYPROJECT}) as root:
            run_init(json_out=True)
            os.makedirs(os.path.join(root, ".asgard"), exist_ok=True)
            path = os.path.join(root, ".asgard", "asgard-setting-project.json")
            config = _settings(root)
            config["code_style"]["tools"] = [{"name": "mine", "check": "my-linter"}]
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(config, handle)
            again = _json(lambda: run_init(json_out=True))
            self.assertEqual((again["written"], again["why"]), (False, "already-declared"))
            self.assertEqual([t["name"] for t in _settings(root)["code_style"]["tools"]], ["mine"])

    def test_force_replaces_it_and_keeps_the_comment_keys(self):
        with _repo(**{"pyproject.toml": _PYPROJECT}) as root:
            os.makedirs(os.path.join(root, ".asgard"), exist_ok=True)
            path = os.path.join(root, ".asgard", "asgard-setting-project.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"code_style": {"_comment": "keep me", "tools": [{"name": "old", "check": "x"}]}}, handle)
            self.assertTrue(_json(lambda: run_init(json_out=True, force=True))["written"])
            section = _settings(root)["code_style"]
            self.assertEqual(section["_comment"], "keep me")
            self.assertEqual([t["name"] for t in section["tools"]], ["ruff", "ruff-format"])


class List(unittest.TestCase):
    def test_detected_but_undeclared_is_a_separate_column(self):
        with _repo(**{"pyproject.toml": _PYPROJECT}):
            before = _json(lambda: run_list(json_out=True))
            self.assertFalse(before["configured"])
            self.assertEqual([t["name"] for t in before["detected_not_declared"]], ["ruff", "ruff-format"])
            run_init(json_out=True)
            after = _json(lambda: run_list(json_out=True))
            self.assertTrue(after["configured"] and after["enabled"])
            self.assertEqual(after["detected_not_declared"], [])


class Check(unittest.TestCase):
    """`--json` 은 게이트가 읽는 계약이다 — `blocking` 목록 하나 (craft 와 같은 형식)."""

    def _declare(self, root: str, tools: list[dict], enabled: bool = True) -> None:
        os.makedirs(os.path.join(root, ".asgard"), exist_ok=True)
        with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
            json.dump({"code_style": {"enabled": enabled, "tools": tools}}, handle)

    def test_nothing_declared_is_not_a_failure(self):
        with _repo():
            payload = _json(lambda: run_check(json_out=True))
            self.assertEqual((payload["configured"], payload["blocking"]), (False, []))

    def test_a_violation_in_a_scoped_path_blocks_and_exits_one(self):
        with _repo(**{"src|bad.py": "import os\n"}) as root:
            self._declare(root, [{"name": "fake", "check": "echo 'src/bad.py:1:1: F401 unused'", "languages": [".py"]}])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = run_check(paths=("src/bad.py",), json_out=True)
            payload = json.loads(out.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(
                [(f["rule"], f["path"], f["line"]) for f in payload["blocking"]], [("fake", "src/bad.py", 1)]
            )

    def test_a_violation_outside_the_scope_is_inherited_debt(self):
        with _repo(**{"src|bad.py": "import os\n"}) as root:
            self._declare(root, [{"name": "fake", "check": "echo 'src/old.py:9:1: F401 unused'", "languages": [".py"]}])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = run_check(paths=("src/bad.py",), json_out=True)
            payload = json.loads(out.getvalue())
            self.assertEqual((code, payload["blocking"], payload["inherited"]), (0, [], 1))

    def test_the_lane_being_off_does_not_stop_a_hand_run(self):
        with _repo(**{"src|bad.py": "import os\n"}) as root:
            self._declare(root, [{"name": "fake", "check": "echo 'src/bad.py:1:1: E1 x'", "languages": [".py"]}], False)
            payload = _json(lambda: run_check(paths=("src/bad.py",), json_out=True))
            self.assertEqual(len(payload["blocking"]), 1)

    def test_autofix_runs_only_what_declared_it(self):
        with _repo(**{"src|bad.py": "import os\n"}) as root:
            marker = os.path.join(root, "fixed")
            rows = [
                {"name": "off", "check": "true", "fix": "touch off-marker", "languages": [".py"]},
                {"name": "on", "check": "true", "fix": "touch fixed", "languages": [".py"], "autofix": True},
            ]
            self._declare(root, rows)
            plain = _json(lambda: run_check(paths=("src/bad.py",), json_out=True))
            self.assertEqual(plain["repaired"], [])  # 게이트가 --autofix 를 붙여야 돈다
            payload = _json(lambda: run_check(paths=("src/bad.py",), json_out=True, repair="auto"))
            self.assertEqual(payload["repaired"], ["touch fixed"])
            self.assertTrue(os.path.exists(marker))
            self.assertFalse(os.path.exists(os.path.join(root, "off-marker")))

    def test_a_tool_that_cannot_run_is_reported_as_unmeasured(self):
        with _repo(**{"src|bad.py": "import os\n"}) as root:
            self._declare(root, [{"name": "gone", "check": "no-such-binary-xyz", "languages": [".py"]}])
            payload = _json(lambda: run_check(paths=("src/bad.py",), json_out=True))
            self.assertEqual(payload["blocking"], [])
            self.assertEqual([r["tool"] for r in payload["runs"] if r["exit_code"] != 0], ["gone"])


if __name__ == "__main__":
    unittest.main()
