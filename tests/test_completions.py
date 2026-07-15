#!/usr/bin/env python3
"""completions 자가 검증 — (1) cli.py 명령 표면과 completion 테이블의 동기 강제(인트로스펙션),
(2) 생성 스크립트의 셸별 기능 검증(bash 는 COMPREPLY 직접, zsh/fish 는 있으면 실행), (3) --install 배선 멱등성.

실행: uv run pytest tests/test_completions.py
"""

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock

from typer.main import get_command

from asgard import cli, ui
from asgard.commands import completions as comp


def _visible_commands():
    # TyperGroup 은 이 환경에서 click.Group 의 서브클래스가 아니다 — isinstance 대신 duck-typing.
    commands = getattr(get_command(cli.app), "commands")
    return {n: c for n, c in commands.items() if not c.hidden}


def _script(shell: str) -> str:
    s = comp._render(shell)
    assert s is not None
    return s


class TestSurfaceSync(unittest.TestCase):
    """cli.py 에 명령/플래그가 늘거나 줄면 여기가 깨진다 — completion 테이블을 같이 고치라는 신호."""

    def test_commands_match(self):
        self.assertEqual(set(_visible_commands()), set(comp._SUMMARY))

    def test_flags_match(self):
        for name, c in _visible_commands().items():
            opts = sorted(o for p in c.params for o in p.opts if o.startswith("--"))
            self.assertEqual(opts, sorted(comp._FLAGS[name]), f"command '{name}' flags drifted")

    def test_role_subcommands_match(self):
        role = _visible_commands()["role"]
        self.assertEqual(set(role.commands), set(comp._ROLE_SUB))
        arg = next(p for p in role.commands["run"].params if p.name == "role")
        for r in comp._ROLES:
            self.assertIn(r, arg.metavar or "")

    def test_memory_subcommands_match(self):
        mem = _visible_commands()["memory"]
        self.assertEqual(set(mem.commands), set(comp._MEM_SUB))

    def test_enum_values_match_help(self):
        """열거형 옵션 후보가 해당 옵션의 help 문구와 어긋나지 않는지 (값 하나하나 존재 확인)."""
        cmds = _visible_commands()
        helps = {
            "--provider": next(p for p in cmds["start"].params if "--provider" in p.opts).help,
            "--profile": next(p for p in cmds["init"].params if "--profile" in p.opts).help,
            "--lagom": next(p for p in cmds["init"].params if "--lagom" in p.opts).help,
            "--kind": next(p for p in cmds["memory"].commands["add"].params if "--kind" in p.opts).help,
        }
        for opt, values in comp._VALUES.items():
            for v in values:
                self.assertIn(v, helps[opt] or "", f"{opt} value '{v}' not in cli help")


class TestRenderAnchors(unittest.TestCase):
    def test_smoke_anchors(self):
        self.assertIn("complete -F _asgard asgard", _script("bash"))
        self.assertIn("#compdef asgard", _script("zsh"))
        self.assertIn("complete -c asgard", _script("fish"))

    def test_unknown_shell(self):
        self.assertIsNone(comp._render("pwsh"))
        self.assertEqual(comp.run_completions("pwsh"), 2)
        self.assertEqual(comp.run_completions(None), 2)


class TestBashFunctional(unittest.TestCase):
    """bash 함수를 직접 구동 — COMP_WORDS/COMP_CWORD 를 세팅하고 COMPREPLY 를 검사한다."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="asgard-comp-")
        cls.script = os.path.join(cls.dir, "asgard.bash")
        with open(cls.script, "w", encoding="utf-8") as f:
            f.write(_script("bash"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _complete(self, words: str, cword: int) -> list[str]:
        cmd = (
            f'source "{self.script}"; COMP_WORDS=({words}); COMP_CWORD={cword}; _asgard; '
            'printf "%s\\n" "${COMPREPLY[@]}"'
        )
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [x for x in r.stdout.splitlines() if x]

    def test_top_level_commands(self):
        out = self._complete('asgard ""', 1)
        self.assertEqual(set(out), set(comp._SUMMARY))

    def test_top_level_prefix(self):
        self.assertEqual(set(self._complete("asgard ro", 1)), {"role"})

    def test_subcommand_flags(self):
        out = self._complete('asgard init ""', 2)
        self.assertIn("--profile", out)
        self.assertIn("--lagom", out)
        self.assertNotIn("--check", out)  # start 전용 플래그가 새면 안 된다

    def test_enum_option_values(self):
        self.assertEqual(set(self._complete('asgard init --profile ""', 3)), set(comp._VALUES["--profile"]))
        self.assertEqual(set(self._complete('asgard start --provider ""', 3)), set(comp._VALUES["--provider"]))

    def test_free_option_offers_nothing(self):
        self.assertEqual(self._complete('asgard start --model ""', 3), [])

    def test_role_subcommands_and_args(self):
        self.assertEqual(set(self._complete('asgard role ""', 2)), set(comp._ROLE_SUB) | {"--help"})
        self.assertEqual(set(self._complete('asgard role run ""', 3)), set(comp._ROLES))

    def test_completions_args(self):
        out = self._complete('asgard completions ""', 2)
        for shell in comp._SHELLS:
            self.assertIn(shell, out)
        self.assertIn("--install", out)


@unittest.skipUnless(shutil.which("zsh"), "zsh not on PATH")
class TestZshFunctional(unittest.TestCase):
    """zsh 는 compadd/_describe 스텁으로 분기 로직을 검증 + compinit 환경에서 compdef 등록 확인."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="asgard-comp-")
        cls.script = os.path.join(cls.dir, "_asgard")
        with open(cls.script, "w", encoding="utf-8") as f:
            f.write(_script("zsh"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _complete(self, words: str, current: int) -> list[str]:
        harness = textwrap.dedent(f"""\
            typeset -ga RESULT; RESULT=()
            compadd() {{
              local seen=0 a
              for a in "$@"; do
                if (( seen )); then RESULT+=("$a"); elif [[ $a == -- ]]; then seen=1; fi
              done
            }}
            _describe() {{
              local name=${{@[-1]}}
              local -a pairs; pairs=(${{(P)name}})
              RESULT+=(${{pairs%%:*}})
            }}
            source "{self.script}"
            words=({words}); CURRENT={current}
            _asgard
            print -rl -- $RESULT
        """)
        r = subprocess.run(["zsh", "-fc", harness], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [x for x in r.stdout.splitlines() if x]

    def test_top_level_commands(self):
        self.assertEqual(set(self._complete('asgard ""', 2)), set(comp._SUMMARY))

    def test_subcommand_flags(self):
        out = self._complete('asgard init ""', 3)
        self.assertIn("--profile", out)
        self.assertNotIn("--check", out)

    def test_enum_option_values(self):
        self.assertEqual(set(self._complete('asgard init --lagom ""', 4)), set(comp._VALUES["--lagom"]))

    def test_role_subcommands_and_args(self):
        self.assertEqual(set(self._complete('asgard role ""', 3)), set(comp._ROLE_SUB) | {"--help"})
        self.assertEqual(set(self._complete('asgard role run ""', 4)), set(comp._ROLES))

    def test_source_registers_compdef(self):
        cmd = f'autoload -Uz compinit; compinit -u; source "{self.script}"; print -r -- $_comps[asgard]'
        r = subprocess.run(["zsh", "-fc", cmd], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "_asgard")


@unittest.skipUnless(shutil.which("fish"), "fish not on PATH")
class TestFishFunctional(unittest.TestCase):
    def _complete(self, line: str) -> list[str]:
        with tempfile.TemporaryDirectory(prefix="asgard-comp-") as d:
            path = os.path.join(d, "asgard.fish")
            with open(path, "w", encoding="utf-8") as f:
                f.write(_script("fish"))
            r = subprocess.run(["fish", "-c", f'source "{path}"; complete -C"{line}"'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return [x.split("\t")[0] for x in r.stdout.splitlines() if x]

    def test_top_level_commands(self):
        out = self._complete("asgard ")
        for name in comp._SUMMARY:
            self.assertIn(name, out)

    def test_role_args(self):
        out = self._complete("asgard role run ")
        for r in comp._ROLES:
            self.assertIn(r, out)


class TestInstall(unittest.TestCase):
    def setUp(self):
        ui.set_quiet(True)

    def tearDown(self):
        ui.set_quiet(False)

    def test_zsh_install_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="asgard-home-") as home:
            with mock.patch.dict(os.environ, {"HOME": home, "SHELL": "/bin/zsh"}):
                os.environ.pop("ZDOTDIR", None)  # patch.dict 가 원복
                self.assertEqual(comp.run_completions("zsh", install=True), 0)
                dest = os.path.join(home, ".asgard", "completions", "_asgard")
                rc = os.path.join(home, ".zshrc")
                self.assertTrue(os.path.exists(dest))
                with open(rc, encoding="utf-8") as f:
                    content = f.read()
                self.assertEqual(content.count(comp._RC_MARKER), 1)
                self.assertEqual(comp.run_completions("zsh", install=True), 0)  # 재실행 = 멱등
                with open(rc, encoding="utf-8") as f:
                    self.assertEqual(f.read().count(comp._RC_MARKER), 1)

    def test_shell_detected_from_env(self):
        with tempfile.TemporaryDirectory(prefix="asgard-home-") as home:
            with mock.patch.dict(os.environ, {"HOME": home, "SHELL": "/bin/bash"}):
                self.assertEqual(comp.run_completions(None, install=True), 0)
                self.assertTrue(os.path.exists(os.path.join(home, ".asgard", "completions", "asgard.bash")))
                with open(os.path.join(home, ".bashrc"), encoding="utf-8") as f:
                    self.assertIn(comp._RC_MARKER, f.read())

    def test_fish_install_no_rc(self):
        with tempfile.TemporaryDirectory(prefix="asgard-home-") as home:
            xdg = os.path.join(home, "xdg")
            with mock.patch.dict(os.environ, {"HOME": home, "XDG_CONFIG_HOME": xdg}):
                self.assertEqual(comp.run_completions("fish", install=True), 0)
                self.assertTrue(os.path.exists(os.path.join(xdg, "fish", "completions", "asgard.fish")))

    def test_unknown_shell(self):
        with mock.patch.dict(os.environ, {"SHELL": "/bin/pwsh"}):
            self.assertEqual(comp.run_completions(None, install=True), 2)

    def test_ensure_installed_defaults_to_login_shell(self):
        """흔적이 없어도 로그인 셸엔 기본 설치, 흔적 있는 다른 셸은 재생성 — 새 바이너리 서브프로세스로."""
        with tempfile.TemporaryDirectory(prefix="asgard-home-") as home:
            os.makedirs(os.path.join(home, ".asgard", "completions"))
            with open(os.path.join(home, ".asgard", "completions", "asgard.bash"), "w") as f:
                f.write("# stale artifact\n")
            with (
                mock.patch.dict(os.environ, {"HOME": home, "SHELL": "/bin/zsh"}),
                mock.patch.object(comp.subprocess, "run") as run,
            ):
                os.environ.pop("XDG_CONFIG_HOME", None)  # patch.dict 가 원복
                comp.ensure_installed()
            shells = sorted(c.args[0][2] for c in run.call_args_list)
            self.assertEqual(shells, ["bash", "zsh"])  # zsh=로그인 셸(흔적 무), bash=흔적, fish=호출 안 됨


if __name__ == "__main__":
    unittest.main()
