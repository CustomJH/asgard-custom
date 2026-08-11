#!/usr/bin/env python3
"""completions 자가 검증 — (1) 파생 표면이 cli.py 앱과 일치하고 차례표가 이름을 못 바꾸는지,
(2) 렌더러가 가시 명령·서브커맨드를 네 셸 산출물에 실제로 내는지, (3) 생성 스크립트의 셸별 기능
검증(bash는 COMPREPLY 직접, zsh/fish는 있으면 실행), (4) --install 배선 멱등성.

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
    # TyperGroup은 이 환경에서 click.Group의 서브클래스가 아니다 — isinstance 대신 duck-typing.
    commands = getattr(get_command(cli.app), "commands")
    return {n: c for n, c in commands.items() if not c.hidden}


def _visible_subcommands(name: str):
    group = _visible_commands()[name]
    return {n: c for n, c in getattr(group, "commands", {}).items() if not c.hidden}


def _app_flags(command):
    return [o for p in command.params for o in p.opts if o.startswith("--")]


def _script(shell: str) -> str:
    s = comp._render(shell)
    assert s is not None
    return s


class TestSurfaceDerivation(unittest.TestCase):
    """표면은 cli.py의 Typer 앱에서 나온다 — 손으로 적은 복제본이 아니다.

    여태 이 자리에 있던 것은 '표가 앱과 같은가'를 묻는 드리프트 검사였다. 표를 파생으로 바꾼
    지금 그 질문은 늘 참이라 아무것도 못 잡는다. 대신 파생 자체가 명령을 흘리거나 숨긴 이름을
    끌어오지 않는지, 그리고 사람이 쥔 차례표가 이름을 더하거나 뺄 수 없는지를 잰다.
    """

    def test_commands_are_the_apps_visible_commands(self):
        self.assertEqual(set(comp._surface().commands), set(_visible_commands()))

    def test_flags_are_the_apps_flags(self):
        flags = comp._surface().flags
        for name, command in _visible_commands().items():
            self.assertEqual(flags[name], _app_flags(command), f"command '{name}' flags drifted")

    def test_subcommands_are_the_apps_subcommands(self):
        s = comp._surface()
        for name in _visible_commands():
            subs = _visible_subcommands(name)
            if not subs:
                self.assertNotIn(name, s.subs)
                continue
            self.assertEqual(set(s.subs[name]), set(subs), f"group '{name}' subcommands drifted")
            for sub, command in subs.items():
                self.assertEqual(s.sub_flags[name][sub], _app_flags(command), f"'{name} {sub}' flags drifted")

    def test_hidden_names_are_never_offered(self):
        """숨긴 이름은 제안하지 않는다 — `upgrade`, `map generate` 같은 별칭."""
        s = comp._surface()
        self.assertNotIn("upgrade", s.commands)
        self.assertNotIn("generate", s.subs["map"])

    def test_every_name_carries_a_description(self):
        s = comp._surface()
        for name, desc in s.commands.items():
            self.assertTrue(desc.strip(), f"command '{name}' has no description")
        for group, subs in s.subs.items():
            for sub, desc in subs.items():
                self.assertTrue(desc.strip(), f"'{group} {sub}' has no description")

    def test_the_order_table_cannot_add_or_remove_a_command(self):
        """사람이 쥔 표는 **차례만** 정한다 — 이름을 더하지도 빼지도 못한다.

        드리프트가 실제로 난 자리가 여기다: 표에 손을 안 대면 새 명령이 자동완성에서 통째로
        빠졌다. 표를 낡게(있는 이름 하나를 지우고, 없는 이름 하나를 넣어) 바꾼 뒤에도 표면이
        앱과 같은지를 본다 — 차례표가 낡아도 명령은 그대로 나와야 한다.
        """
        stale = {k: v for k, v in comp._DESC.items() if k != "doctor"}
        stale["a-command-that-was-deleted"] = "gone"
        with mock.patch.object(comp, "_DESC", stale):
            s = comp._surface()
        self.assertEqual(set(s.commands), set(_visible_commands()))
        self.assertNotIn("a-command-that-was-deleted", s.commands)
        self.assertTrue(s.commands["doctor"].strip())  # 설명이 없으면 앱 help로 채운다

    def test_the_order_table_cannot_add_or_remove_a_subcommand(self):
        stale = dict(comp._SUB_DESC)
        stale["memory"] = {"a-sub-that-was-deleted": "gone"}
        with mock.patch.object(comp, "_SUB_DESC", stale):
            s = comp._surface()
        self.assertEqual(set(s.subs["memory"]), set(_visible_subcommands("memory")))
        self.assertNotIn("a-sub-that-was-deleted", s.subs["memory"])

    def test_curated_order_leads_and_new_names_follow(self):
        """차례표에 있는 이름이 앞에, 없는 이름이 뒤에 — 메뉴 차례는 사람이 정한 대로 남는다."""
        self.assertEqual(list(comp._surface().commands)[:3], ["doctor", "manual", "start"])
        self.assertEqual(comp._ordered(["b", "a", "z"], ["a", "b"]), ["a", "b", "z"])
        self.assertEqual(comp._ordered(["a"], ["a", "deleted"]), ["a"])

    def test_enum_reads_only_enumerations(self):
        """metavar가 열거일 때만 후보로 읽는다 — 산문에 섞인 파이프를 후보로 오독하면 안 된다."""
        self.assertEqual(comp._enum("<thinker|worker|verifier>"), ["thinker", "worker", "verifier"])
        self.assertEqual(comp._enum("[native|claude-code]"), ["native", "claude-code"])
        self.assertEqual(comp._enum("docx|pptx|xlsx"), ["docx", "pptx", "xlsx"])
        self.assertIsNone(comp._enum("use this provider instead: anthropic | openai"))
        self.assertIsNone(comp._enum("lagom default mode: off | lite | full (default full)"))
        self.assertIsNone(comp._enum("just one thing"))
        self.assertIsNone(comp._enum(None))

    def test_enum_values_match_cli_help(self):
        """손으로 남긴 값 후보가 해당 옵션의 help 문구와 어긋나지 않는지 (값 하나하나 존재 확인).

        --provider·--kind는 도메인 상수에서 읽지만 --profile·--lagom은 앱이 열거로 말하지 않아
        _MANUAL_VALUES에 남아 있다 — 남은 것들이 실제로 유효한지는 여기서 계속 본다.
        """
        cmds = _visible_commands()
        helps = {
            "--provider": next(p for p in cmds["start"].params if "--provider" in p.opts).help,
            "--profile": next(p for p in cmds["init"].params if "--profile" in p.opts).help,
            "--lagom": next(p for p in cmds["init"].params if "--lagom" in p.opts).help,
            "--kind": next(p for p in cmds["memory"].commands["add"].params if "--kind" in p.opts).help,
        }
        for opt, values in comp._surface().values.items():
            for v in values:
                self.assertIn(v, helps[opt] or "", f"{opt} value '{v}' not in cli help")

    def test_placeable_roles_cover_every_host(self):
        """`role model <host> <role>` 후보는 host별 유효 집합의 합집합이어야 한다."""
        from asgard.commands.role import MODEL_HOSTS, _native_roles
        from asgard.templates.agent_models import AGENT_MODEL_DEFAULTS

        expected = set(_native_roles())
        for host in MODEL_HOSTS:
            if host != "native":
                expected |= set(AGENT_MODEL_DEFAULTS[host])
        self.assertEqual(set(comp._surface().model_roles), expected)


class TestRendererCoversTheApp(unittest.TestCase):
    """네 셸 산출물이 가시 명령·서브커맨드를 실제로 내는지 — 파생 로직 자체의 버그를 잡는 자리.

    표면이 옳아도 렌더러가 어떤 그룹을 아예 안 적으면 그 셸에서만 조용히 사라진다. 실제로
    그랬다: fish는 k6·mode·siege 그룹을 등록하는 줄이 없어 서브커맨드가 하나도 안 나왔다.
    """

    # 셸마다 이름이 산출물에 나타나는 꼴이 다르다 — 부분문자열 우연 일치를 피해 꼴로 찾는다.
    def _appears(self, script: str, shell: str, name: str) -> bool:
        if shell == "bash":
            return f'"{name}' in script or f" {name} " in script or f"    {name})" in script
        if shell == "zsh":
            return f"'{name}:" in script or f" {name} " in script or f"    {name})" in script
        if shell == "fish":
            return f"-a {name} -d" in script or f'-a "{name}' in script or f" {name} " in script
        return f"'{name}'" in script

    def test_every_visible_command_is_in_every_shell(self):
        for shell in comp._SHELLS:
            script = _script(shell)
            for name in _visible_commands():
                with self.subTest(shell=shell, command=name):
                    self.assertTrue(self._appears(script, shell, name), f"{shell}: command '{name}' missing")

    def test_every_visible_subcommand_is_in_every_shell(self):
        for shell in comp._SHELLS:
            script = _script(shell)
            for name in _visible_commands():
                for sub in _visible_subcommands(name):
                    with self.subTest(shell=shell, group=name, sub=sub):
                        self.assertTrue(self._appears(script, shell, sub), f"{shell}: '{name} {sub}' missing")

    def test_every_group_is_registered_in_fish(self):
        """fish는 그룹마다 등록 줄을 따로 낸다 — 한 그룹이 빠지면 그 그룹만 조용히 죽는다."""
        script = _script("fish")
        for name in _visible_commands():
            if _visible_subcommands(name):
                with self.subTest(group=name):
                    self.assertIn(f"__fish_seen_subcommand_from {name}; and not", script)

    def test_hidden_command_is_in_no_shell(self):
        for shell in comp._SHELLS:
            with self.subTest(shell=shell):
                self.assertNotIn("upgrade", _script(shell))


class TestOneDoorForWindows(unittest.TestCase):
    """창을 여는 문은 `asgard open` 하나다.

    여태는 넷이었다: `asgard desktop`, 그리고 `map`·`memory`·`plan`을 서브커맨드 없이 치는 것.
    앞의 셋은 **운영 커맨드 그룹이기도** 해서, 같은 단어가 문맥에 따라 창을 열거나 도움말을
    냈다 — 치기 전에는 무엇이 일어날지 알 수 없었다. 동사를 문 앞에 세워 그걸 끝냈다.

    이 검사가 지키는 것은 문의 **개수**다. 편의를 이유로 옛 문을 하나만 되살려도, 같은 창을
    부르는 이름이 다시 둘이 된다.
    """

    def test_open_carries_exactly_the_three_surfaces(self):
        surfaces = _visible_commands()["open"].commands
        self.assertEqual(set(surfaces), {"studio", "map", "memory"})

    def test_no_other_command_opens_a_window(self):
        """`invoke_without_command`로 창을 열던 그룹들이 되살아나면 여기서 걸린다."""
        for name in ("map", "memory"):
            group = _visible_commands()[name]
            self.assertFalse(
                group.invoke_without_command,
                f"`asgard {name}` 이 다시 창을 연다 — 창은 `asgard open {name}` 하나여야 한다",
            )
        self.assertNotIn("view", _visible_commands()["map"].commands)
        self.assertNotIn("dashboard", _visible_commands()["memory"].commands)

    def test_planning_has_no_door_of_its_own(self):
        """기획은 스튜디오 안에서만 쓴다 — 딥링크는 `open studio --view plan`이다."""
        self.assertNotIn("plan", _visible_commands())
        view = next(p for p in _visible_commands()["open"].commands["studio"].params if "--view" in p.opts)
        self.assertIn("plan", view.help or "")

    def test_the_old_name_is_gone(self):
        self.assertNotIn("desktop", _visible_commands())


class TestRenderAnchors(unittest.TestCase):
    def test_smoke_anchors(self):
        self.assertIn("complete -F _asgard asgard", _script("bash"))
        self.assertIn("#compdef asgard", _script("zsh"))
        self.assertIn("complete -c asgard", _script("fish"))
        self.assertIn("Register-ArgumentCompleter", _script("powershell"))

    def test_unknown_shell(self):
        self.assertIsNone(comp._render("pwsh"))
        self.assertEqual(comp.run_completions("pwsh"), 2)
        self.assertEqual(comp.run_completions(None), 2)


class TestBashFunctional(unittest.TestCase):
    """bash 함수를 직접 구동 — COMP_WORDS/COMP_CWORD를 세팅하고 COMPREPLY를 검사한다."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="asgard-comp-")
        cls.script = os.path.join(cls.dir, "asgard.bash")
        with open(cls.script, "w", encoding="utf-8") as f:
            f.write(_script("bash"))
        cls.surface = comp._surface()

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
        """앱이 아는 가시 명령과 bash가 실제로 내는 후보가 같은지 — 파생을 끝에서 끝까지 잰다."""
        out = self._complete('asgard ""', 1)
        self.assertEqual(set(out), set(_visible_commands()))

    def test_every_group_offers_its_subcommands(self):
        """그룹마다 둘째 낱말에서 앱의 서브커맨드가 전부 나오는지.

        `k6 sync`·`evolve nudge`가 표에 빠져 자동완성에 안 나오던 것이 여기서 걸린다.
        """
        for name in _visible_commands():
            subs = _visible_subcommands(name)
            if not subs:
                continue
            with self.subTest(group=name):
                out = set(self._complete(f'asgard {name} ""', 2))
                self.assertTrue(set(subs) <= out, f"'{name}' missing {sorted(set(subs) - out)}")

    def test_top_level_prefix(self):
        """접두사가 실제로 거르는가.

        기대값은 앱에서 뽑는다 — 이름을 박아 두면 `ro` 로 시작하는 명령이 하나 늘 때마다 이
        시험이 자동완성 결함처럼 빨개진다 (26-08-07: `root` 가 늘면서 `{"role"}` 이 깨졌다)."""
        commands = set(_visible_commands())
        expected = {name for name in commands if name.startswith("ro")}
        self.assertTrue(expected)
        self.assertLess(expected, commands)  # 거르기가 실제로 줄였는지 — 전량 통과를 막는다
        self.assertEqual(set(self._complete("asgard ro", 1)), expected)

    def test_subcommand_flags(self):
        out = self._complete('asgard init ""', 2)
        self.assertIn("--profile", out)
        self.assertIn("--lagom", out)
        self.assertNotIn("--check", out)  # start 전용 플래그가 새면 안 된다

    def test_enum_option_values(self):
        values = self.surface.values
        self.assertEqual(set(self._complete('asgard init --profile ""', 3)), set(values["--profile"]))
        self.assertEqual(set(self._complete('asgard start --provider ""', 3)), set(values["--provider"]))

    def test_free_option_offers_nothing(self):
        self.assertEqual(self._complete('asgard start --model ""', 3), [])

    def test_role_subcommands_and_args(self):
        s = self.surface
        self.assertEqual(set(self._complete('asgard role ""', 2)), set(s.subs["role"]) | {"--help"})
        self.assertEqual(set(self._complete('asgard role run ""', 3)), set(s.roles))
        self.assertEqual(set(self._complete('asgard role model ""', 3)), set(s.model_hosts))
        self.assertEqual(set(self._complete('asgard role model cursor ""', 4)), set(s.model_roles))
        self.assertEqual(
            set(self._complete('asgard role model cursor worker ""', 5)),
            set(s.sub_flags["role"]["model"]) | {"--help"},
        )

    def test_tools_list_options_and_role_values(self):
        self.assertEqual(set(self._complete('asgard tools list ""', 3)), {"--role", "--json", "--help"})
        self.assertEqual(set(self._complete('asgard tools list --role ""', 4)), set(self.surface.tool_roles))

    def test_map_subcommand_flags_come_from_the_app(self):
        """map은 여덟 서브커맨드 모두 플래그를 갖는데 셋만 완성됐다 — 이제 전부 앱에서 나온다."""
        for sub, flags in self.surface.sub_flags["map"].items():
            with self.subTest(sub=sub):
                out = set(self._complete(f'asgard map {sub} ""', 3))
                self.assertTrue(set(flags) <= out, f"'map {sub}' missing {sorted(set(flags) - out)}")

    def test_group_with_its_own_flags_offers_both(self):
        """`mode`·`siege`는 서브커맨드와 자기 `--json`을 함께 받는다 — 둘 다 나와야 한다."""
        for name in ("mode", "siege"):
            with self.subTest(group=name):
                out = set(self._complete(f'asgard {name} ""', 2))
                self.assertTrue(set(_visible_subcommands(name)) <= out)
                self.assertIn("--json", out)

    def test_completions_args(self):
        out = self._complete('asgard completions ""', 2)
        for shell in comp._SHELLS:
            self.assertIn(shell, out)
        self.assertIn("--install", out)


@unittest.skipUnless(shutil.which("zsh"), "zsh not on PATH")
class TestZshFunctional(unittest.TestCase):
    """zsh는 compadd/_describe 스텁으로 분기 로직을 검증 + compinit 환경에서 compdef 등록 확인."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="asgard-comp-")
        cls.script = os.path.join(cls.dir, "_asgard")
        with open(cls.script, "w", encoding="utf-8") as f:
            f.write(_script("zsh"))
        cls.surface = comp._surface()

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
        self.assertEqual(set(self._complete('asgard ""', 2)), set(_visible_commands()))

    def test_every_group_offers_its_subcommands(self):
        for name in _visible_commands():
            subs = _visible_subcommands(name)
            if not subs:
                continue
            with self.subTest(group=name):
                out = set(self._complete(f'asgard {name} ""', 3))
                self.assertTrue(set(subs) <= out, f"'{name}' missing {sorted(set(subs) - out)}")

    def test_subcommand_flags(self):
        out = self._complete('asgard init ""', 3)
        self.assertIn("--profile", out)
        self.assertNotIn("--check", out)

    def test_enum_option_values(self):
        self.assertEqual(set(self._complete('asgard init --lagom ""', 4)), set(self.surface.values["--lagom"]))

    def test_role_subcommands_and_args(self):
        s = self.surface
        self.assertEqual(set(self._complete('asgard role ""', 3)), set(s.subs["role"]) | {"--help"})
        self.assertEqual(set(self._complete('asgard role run ""', 4)), set(s.roles))
        self.assertEqual(set(self._complete('asgard role model ""', 4)), set(s.model_hosts))
        self.assertEqual(set(self._complete('asgard role model cursor ""', 5)), set(s.model_roles))
        self.assertEqual(
            set(self._complete('asgard role model cursor worker ""', 6)),
            set(s.sub_flags["role"]["model"]) | {"--help"},
        )

    def test_map_subcommands_and_flags(self):
        s = self.surface
        self.assertEqual(set(self._complete('asgard map ""', 3)), set(s.subs["map"]) | {"--help"})
        for sub, flags in s.sub_flags["map"].items():
            with self.subTest(sub=sub):
                out = set(self._complete(f'asgard map {sub} ""', 4))
                self.assertTrue(set(flags) <= out, f"'map {sub}' missing {sorted(set(flags) - out)}")

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
        for name in _visible_commands():
            self.assertIn(name, out)

    def test_every_group_offers_its_subcommands(self):
        for name in _visible_commands():
            subs = _visible_subcommands(name)
            if not subs:
                continue
            out = self._complete(f"asgard {name} ")
            for sub in subs:
                with self.subTest(group=name, sub=sub):
                    self.assertIn(sub, out)

    def test_role_args(self):
        s = comp._surface()
        out = self._complete("asgard role run ")
        for r in s.roles:
            self.assertIn(r, out)
        hosts = self._complete("asgard role model ")
        for host in s.model_hosts:
            self.assertIn(host, hosts)


@unittest.skipUnless(shutil.which("pwsh"), "pwsh not on PATH")
class TestPowerShellParses(unittest.TestCase):
    """생성한 .ps1이 PowerShell 파서를 통과하는지 — 파스가 깨지면 프로파일 로드가 통째로 죽는다."""

    def test_script_parses(self):
        with tempfile.TemporaryDirectory(prefix="asgard-ps-") as d:
            path = os.path.join(d, "asgard.ps1")
            with open(path, "w", encoding="utf-8") as f:
                f.write(_script("powershell"))
            probe = (
                "$err = $null; "
                f"[System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$null, [ref]$err) > $null; "
                "if ($err.Count -eq 0) { 'OK' } else { $err | ForEach-Object { $_.ToString() } }"
            )
            r = subprocess.run(["pwsh", "-NoProfile", "-Command", probe], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "OK", r.stdout)


class TestInstall(unittest.TestCase):
    def setUp(self):
        ui.set_quiet(True)

    def tearDown(self):
        ui.set_quiet(False)

    def test_zsh_install_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="asgard-home-") as home:
            with mock.patch.dict(os.environ, {"HOME": home, "SHELL": "/bin/zsh"}):
                os.environ.pop("ZDOTDIR", None)  # patch.dict가 원복
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
                os.environ.pop("XDG_CONFIG_HOME", None)  # patch.dict가 원복
                comp.ensure_installed()
            shells = sorted(c.args[0][2] for c in run.call_args_list)
            self.assertEqual(shells, ["bash", "zsh"])  # zsh=로그인 셸(흔적 무), bash=흔적, fish=호출 안 됨


class TestDescriptionEscaping(unittest.TestCase):
    """설명문에 셸 메타문자가 들어가도 스크립트가 살아야 한다.

    이 가드가 없을 때 실제로 일어난 일: 설명에 아포스트로피(`verb's`)와 백틱을 넣었더니 zsh 기능
    시험 6개가 한 번에 죽었고, 증상이 "모든 명령이 사라짐"이라 원인이 안 보였다. 저자가 특수문자를
    피하기를 기대하는 대신 생성기가 막고, 그걸 여기서 증명한다.

    서브커맨드 설명도 같이 본다: 여태 이스케이프는 최상위 설명에만 걸려 있었고, 그래서 fish의
    `agent use` 설명(`the machine's active agent`)이 홑따옴표를 안 닫은 채 나가고 있었다.
    """

    HOSTILE = "a verb's playbook, `gate`, and a colon: plus a backslash \\ end"

    def _with_hostile(self, shell: str, *, sub: bool = False) -> str:
        if sub:
            subs = {group: dict(table) for group, table in comp._SUB_DESC.items()}
            subs["agent"]["use"] = self.HOSTILE
            with mock.patch.object(comp, "_SUB_DESC", subs):
                return _script(shell)
        desc = dict(comp._DESC)
        desc["doctor"] = self.HOSTILE
        with mock.patch.object(comp, "_DESC", desc):
            return _script(shell)

    @unittest.skipUnless(shutil.which("zsh"), "zsh not installed")
    def test_zsh_script_still_parses(self):
        for sub in (False, True):
            with self.subTest(subcommand=sub):
                script = self._with_hostile("zsh", sub=sub)
                with tempfile.TemporaryDirectory(prefix="asgard-esc-") as d:
                    path = os.path.join(d, "_asgard")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(script)
                    r = subprocess.run(["zsh", "-n", path], capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr)

    @unittest.skipUnless(shutil.which("zsh"), "zsh not installed")
    def test_zsh_still_lists_every_command(self):
        """파싱만 되고 목록이 비면 그것도 파손이다 — 명령이 전부 나오는지까지 본다."""
        script = self._with_hostile("zsh")
        with tempfile.TemporaryDirectory(prefix="asgard-esc-") as d:
            path = os.path.join(d, "_asgard")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            harness = textwrap.dedent(f"""\
                typeset -ga RESULT; RESULT=()
                compadd() {{ :; }}
                _describe() {{
                  local name=${{@[-1]}}
                  local -a pairs; pairs=(${{(P)name}})
                  RESULT+=(${{pairs%%:*}})
                }}
                source "{path}"
                words=(asgard ""); CURRENT=2
                _asgard
                print -rl -- $RESULT
            """)
            r = subprocess.run(["zsh", "-fc", harness], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual({x for x in r.stdout.splitlines() if x}, set(_visible_commands()))

    @unittest.skipUnless(shutil.which("fish"), "fish not installed")
    def test_fish_script_still_parses(self):
        for sub in (False, True):
            with self.subTest(subcommand=sub):
                script = self._with_hostile("fish", sub=sub)
                with tempfile.TemporaryDirectory(prefix="asgard-esc-") as d:
                    path = os.path.join(d, "asgard.fish")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(script)
                    r = subprocess.run(["fish", "-n", path], capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr)

    def test_every_apostrophe_is_escaped_in_fish(self):
        """fish 산출물의 홑따옴표 문자열이 전부 닫혀 있는지 — fish 없이도 도는 검사.

        `agent use`의 설명에 든 아포스트로피가 이스케이프 없이 나가던 것이 이 검사가 잡는 것이다.
        """
        for line in _script("fish").splitlines():
            if " -d '" not in line:
                continue
            body = line.split(" -d '", 1)[1]
            self.assertTrue(body.endswith("'"), line)
            inner = body[:-1]
            unescaped = [i for i, ch in enumerate(inner) if ch == "'" and (i == 0 or inner[i - 1] != "\\")]
            self.assertEqual(unescaped, [], f"unescaped quote in fish description: {line}")

    def test_escaping_is_a_no_op_for_todays_descriptions(self):
        """오늘의 설명문엔 특수문자가 없다 — 이스케이프를 넣어도 출력이 바이트 동일해야 한다."""
        for name, desc in comp._DESC.items():
            with self.subTest(name=name):
                self.assertEqual(desc, comp._zsh_desc(desc))
                self.assertEqual(desc, comp._fish_desc(desc))


if __name__ == "__main__":
    unittest.main()
