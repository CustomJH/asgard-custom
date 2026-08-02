#!/usr/bin/env python3
"""명령 표면 규칙 — 산문이 아니라 실행 가능한 형태로.

리프 명령이 140개를 넘는 표면에서 규칙을 문서로만 적어 두면 다음 커밋이 다시 흩뜨린다. 여기서 넷을 봉인한다.

  (a) `-q`는 `--quiet` 전용이다
  (b) 리프 명령은 `--json`을 가진다
  (c) 같은 단축 플래그가 서로 다른 긴 이름에 붙지 않는다
  (d) 기계 JSON을 내는 명령은 그것을 요청할 플래그를 가진다 — 기본으로 내주지 않는다

넷 다 **오늘의 상태를 기준선**으로 삼고 예외를 명시한다. 예외 목록의 크기가 다음 작업의 척도다.

(d)가 (b)의 반대 방향이다. (b)만 있으면 "JSON을 낼 수 있는가"만 보고, 플래그 없이 **항상** 내주는
자리는 통과한다 — 실제로 `role list`·`mode set`·`mode reset`·`mode pick` 넷이 그렇게 통과하고 있었다.
그 상태를 테스트가 다시 굳혀 놓아(항상 JSON을 단언) 사람 표면을 되찾는 쪽이 회귀로 보였다.

예외 항목마다 왜 예외인지 한 줄이 붙어 있다. 이유를 못 적는 항목은 예외가 아니라 결함이다. 남은 아홉은
전부 성질상 예외다 — 되묻는 자리(start·init·auth login·mode pick), stdout이 이미 다른 것의 채널인 자리
(completions·memory mcp·skills run), 결과가 값이 아니라 프로세스인 자리(open studio·open memory).
"아직 안 고쳤을 뿐"인 항목은 남아 있지 않다.

세 검사 모두 **양방향**이다: 새 위반이 생겨도 깨지고, 예외에 적힌 명령이 규칙을 이미 지켜도 깨진다.
후자가 없으면 목록이 낡은 채로 남아 "예외 56건"이 영원히 56건으로 보인다.

여기서 리프란 하위 명령이 없는 가시 명령이다. `mode`·`ticket`처럼 인자 없이도 도는 그룹은 제외한다 —
그 자리의 플래그는 그룹 콜백이 선언하므로 리프와 같은 규칙으로 판정하면 결과가 어긋난다.

실행: uv run pytest tests/test_cli_surface.py
"""

import ast
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from typer.main import get_command

from asgard import cli, ui
from asgard.commands import completions as comp

# ── (b) `--json`이 없는 리프 — 명령마다 이유 한 줄 ──────────────────────────────────
_NO_JSON = {
    "start": "대화형 터미널 — 세션 화면이 산출물이다",
    "init": "온보딩 — 프로파일 선택과 덮어쓰기 확인을 되묻는다. 계획은 `--dry-run`이, 결과는 `doctor --json`이 낸다",
    "completions": "산출물이 셸 스크립트 그 자체다",
    "auth login": "브라우저 OAuth 왕복 — 대화형",
    "mode pick": "선택 패널 — 사람이 고르는 자리다",
    "skills run": "스킬이 딸려 보낸 헬퍼를 그대로 실행한다 — stdout은 그 헬퍼의 것이다",
    "memory mcp": "stdio MCP 브리지 — stdout이 프로토콜 채널이라 JSON을 더 얹을 수 없다",
    "open studio": "창을 여는 명령 — 결과는 프로세스지 값이 아니다",
    "open memory": "open studio와 같은 자리",
}

# ── (c) 같은 단축이 서로 다른 긴 이름에 붙은 자리 — 단축 글자마다 이유 한 줄 ─────────────
#
# 비어 있다. 여섯 충돌을 다 닫았다: `-q`(quiet vs query)를 먼저, 그다음 `-c`·`-e`·`-k`·`-o`·`-p`.
# 물러난 쪽은 긴 이름을 그대로 갖는다 — 단축만 옮겼으므로 옛 스크립트는 `--cycle`·`--estimate`·
# `--priority`·`--kind`·`--outdir`로 계속 닿는다. 판정 기준은 두 개다: 그 뜻을 쓰는 명령이 더 많은
# 쪽이 글자를 갖고, 수가 비슷하면 CLI 전체에서 통하는 뜻을 한 그룹 안에서만 통하는 필드 이름보다
# 우선한다 (`-c` 이어가기·`-e` 환경변수·`-p` 포트 vs 티켓의 주기·추정·우선순위).
_SHORT_CONFLICTS: dict[str, str] = {}


def _leaves() -> dict[str, Any]:
    """가시 리프 명령 — 경로 문자열("map update") → click 명령."""
    root = get_command(cli.app)
    found: dict[str, Any] = {}

    def walk(command, path: list[str]) -> None:
        subs = getattr(command, "commands", None)
        if subs:
            for name, sub in subs.items():
                if not getattr(sub, "hidden", False):
                    walk(sub, [*path, name])
            return
        found[" ".join(path)] = command

    walk(root, [])
    return found


def _long_names(param) -> list[str]:
    return [opt for opt in param.opts if opt.startswith("--")]


def _shorts(param) -> list[str]:
    return [opt for opt in param.opts if len(opt) == 2 and opt.startswith("-") and not opt.startswith("--")]


# ── (d) 기계 JSON을 내는 자리는 플래그를 가진다 — 이름은 셋 중 하나 ──────────────────
#
# `--json`이 없던 시절, 기계가 읽을 자리가 필요한 명령은 플래그를 만드는 대신 **기본 출력을**
# JSON으로 내줬다. `role list`·`mode set`·`mode reset`·`mode pick` 넷이 전부 그 모양이었고,
# 그 상태를 테스트가 다시 굳혀 두어(항상 JSON을 단언) 되돌리기 어려워져 있었다. 개별 실수가
# 아니라 반복되는 형태라, 자리를 고치는 것만으로는 다음 명령에서 또 생긴다.
_JSON_PARAMS = {"json_out", "json_", "json", "as_json"}

# 기계 채널이 stdout **그 자체**라 플래그로 가를 것이 없는 자리. 훅·프로토콜 표면뿐이다.
_ALWAYS_MACHINE = {
    "run_sync_turn": "훅 전용 stdin/stdout 프로토콜 — 사람이 부르는 표면이 아니다 (`memory sync-turn`, hidden)",
}


def _emits_json(function: ast.AST) -> bool:
    """이 함수가 기계 JSON을 stdout으로 내보내는가 — `json.dumps`를 **출력 자리에서** 쓰는가.

    `dumps` 호출이 있다는 것만으로는 부족하다. `role run`은 퀘스트 로그에 넘길 stdin payload를
    같은 함수 안에서 만든다 — 그건 출력이 아니다. 그래서 `print(...)`·`sys.stdout.write(...)`의
    인자이거나, 이 저장소가 `--json` 산출물에 쓰는 `_emit`/`_emitted` 경유점일 때만 센다."""

    def dumps_inside(node: ast.AST) -> bool:
        return any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "dumps"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id in {"json", "_json"}
            for n in ast.walk(node)
        )

    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if name in {"_emit", "_emitted"}:
            return True
        if name == "print" and any(dumps_inside(arg) for arg in node.args):
            return True
        if (
            name == "write"
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "stdout"
            and any(dumps_inside(arg) for arg in node.args)
        ):
            return True
    return False


class TestMachineOutputNeedsAFlag(unittest.TestCase):
    """기계 JSON을 내는 명령 함수는 그것을 켜고 끄는 매개변수를 가진다.

    플래그 없이 항상 JSON을 내면 두 사용자가 한 자리를 두고 다툰다: 사람은 읽을 수 없는 덩어리를
    받고, 그 덩어리를 파싱하는 쪽은 사람 표면을 고치는 순간 조용히 깨진다. 플래그가 있으면 둘 다
    자기 얼굴을 갖는다 — 이 저장소의 `skills list`·`plugins list`·`ticket list`가 그 형태다.
    """

    def test_no_command_prints_json_without_a_way_to_ask_for_it(self):
        offenders = {}
        for path in sorted(Path("src/asgard/commands").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for function in tree.body:
                if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if not function.name.startswith("run_") or function.name in _ALWAYS_MACHINE:
                    continue
                arguments = function.args
                names = {a.arg for a in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]}
                if names & _JSON_PARAMS or not _emits_json(function):
                    continue
                offenders[f"{path.as_posix()}:{function.lineno}"] = function.name
        self.assertEqual(
            offenders,
            {},
            "기계 JSON을 내는데 그것을 요청할 매개변수가 없다 — `--json`을 달고 기본은 사람 표면으로",
        )

    def test_every_always_machine_exception_carries_a_reason(self):
        for name, reason in _ALWAYS_MACHINE.items():
            with self.subTest(function=name):
                self.assertTrue(reason.strip(), f"'{name}'에 이유가 없다 — 이유 없는 예외는 결함이다")


class TestQuietOwnsDashQ(unittest.TestCase):
    """`-q`는 `--quiet`다 — 예외 없음.

    예외를 안 두는 이유: 26개 명령이 이 글자를 "조용히"로 쓴다. 두 명령에서만 뜻이 다르면 사용자는
    그 둘을 기억하는 게 아니라 매번 틀린다. 검색어는 `--query` 긴 이름으로 받는다.
    """

    def test_dash_q_never_means_anything_but_quiet(self):
        offenders = {}
        for path, command in _leaves().items():
            for param in command.params:
                if "-q" in param.opts and _long_names(param) != ["--quiet"]:
                    offenders[path] = _long_names(param) or [param.name]
        self.assertEqual(offenders, {}, "`-q`는 `--quiet` 전용이다 — 다른 뜻이면 긴 이름만 주라")

    def test_quiet_keeps_its_short(self):
        """반대 방향 — `--quiet`가 단축을 잃으면 규칙을 지킬 이유가 사라진다."""
        naked = [
            path
            for path, command in _leaves().items()
            for param in command.params
            if "--quiet" in param.opts and "-q" not in param.opts
        ]
        self.assertEqual(naked, [], "`--quiet`에는 `-q`가 함께 있어야 한다")


class TestJsonCoverage(unittest.TestCase):
    """리프 명령은 `--json`을 가진다 — 스튜디오·훅·CI가 CLI를 자식 프로세스로 부르기 때문이다.

    `--json`이 없는 명령은 출력 파싱이 불가능하거나, 사람용 문장이 바뀌는 순간 조용히 깨진다.
    """

    def test_exception_list_is_exactly_todays_gap(self):
        missing = {
            path for path, command in _leaves().items() if "--json" not in {o for p in command.params for o in p.opts}
        }
        self.assertEqual(
            missing,
            set(_NO_JSON),
            "`--json` 결측 목록이 움직였다 — 고쳤으면 _NO_JSON에서 빼고, 새 명령이면 붙이거나 이유를 적으라",
        )

    def test_every_exception_carries_a_reason(self):
        for path, reason in _NO_JSON.items():
            with self.subTest(command=path):
                self.assertTrue(reason.strip(), f"'{path}'에 이유가 없다 — 이유 없는 예외는 결함이다")

    def test_the_gap_does_not_grow(self):
        """상한을 못박는다 — 예외를 늘리는 커밋은 이유를 적는 것만으로는 통과하지 못한다."""
        self.assertLessEqual(len(_NO_JSON), 9, "`--json` 예외는 늘릴 수 없다 — 줄이는 방향만 있다")


class TestShortFlagMeansOneThing(unittest.TestCase):
    """같은 단축이 명령마다 다른 뜻이면 근육기억이 오작동한다."""

    def _by_short(self) -> dict[str, dict[str, list[str]]]:
        table: dict[str, dict[str, list[str]]] = {}
        for path, command in _leaves().items():
            for param in command.params:
                for short in _shorts(param):
                    longs = _long_names(param)
                    key = longs[0] if longs else f"<{param.name}>"
                    table.setdefault(short, {}).setdefault(key, []).append(path)
        return table

    def test_conflict_list_is_exactly_todays_conflicts(self):
        conflicts = {short: names for short, names in self._by_short().items() if len(names) > 1}
        self.assertEqual(
            set(conflicts),
            set(_SHORT_CONFLICTS),
            f"단축 충돌이 움직였다 — 지금: { {s: sorted(n) for s, n in conflicts.items()} }",
        )

    def test_every_short_has_a_long_name(self):
        """단축만 있고 긴 이름이 없으면 도움말을 읽어도 뜻을 모르고, 같은 개념이 다른 곳과 어긋나도 안 보인다.

        실제로 `memory ask/query/episodes`의 결과 개수가 긴 이름 없는 `-k`였고, 같은 개념이 다른
        명령에서는 `--limit`이었다. 그래서 두 이름이 한 개념을 가리키는지 아무도 몰랐다.
        """
        naked = {
            f"{path} -{param.name}"
            for path, command in _leaves().items()
            for param in command.params
            if _shorts(param) and not _long_names(param)
        }
        self.assertEqual(naked, set(), "단축에는 긴 이름이 함께 있어야 한다")

    def test_limit_is_the_name_for_a_result_count(self):
        """결과 개수의 이름은 `--limit` 하나다 — memory 셋이 여기에 합류했다."""
        for path in ("memory query", "memory episodes", "memory ask", "map why"):
            with self.subTest(command=path):
                opts = {opt for param in _leaves()[path].params for opt in param.opts}
                self.assertIn("--limit", opts)


class TestOneNamePerBehaviour(unittest.TestCase):
    """한 동작에 이름이 여럿이면 사용자는 그것들이 서로 다른 일을 한다고 읽는다.

    `map generate`·`map update`·`setup map`이 같은 함수를 불렀다. 근육기억은 살리되 도움말에서는
    한 이름만 보이게 한다 — `upgrade`→`update`, `einherjar`→`agent`, `yggdrasil`→`memory`와 같은 처리.
    """

    def _map_group(self):
        return getattr(get_command(cli.app), "commands")["map"]

    def test_map_generate_is_a_hidden_alias_of_update(self):
        commands = self._map_group().commands
        self.assertTrue(commands["generate"].hidden, "`map generate`는 숨은 별칭이다")
        self.assertFalse(commands["update"].hidden, "`map update`가 정본이다")
        # Typer는 등록마다 콜백을 새로 감싼다 — 같은 함수인지는 원본(__wrapped__)으로 봐야 한다.
        # 별칭이 몸통을 복제하면 여기서 갈라지고, 그때가 셋으로 다시 흩어지기 시작하는 순간이다.
        self.assertIs(
            commands["generate"].callback.__wrapped__,
            commands["update"].callback.__wrapped__,
        )

    def test_hidden_aliases_are_not_offered_by_completion(self):
        visible = {name for name, sub in self._map_group().commands.items() if not sub.hidden}
        self.assertEqual(visible, set(comp._surface().subs["map"]))

    def test_the_documented_aliases_still_run(self):
        """숨겼다고 지운 것은 아니다 — 옛 이름으로도 여전히 닿아야 한다."""
        top = getattr(get_command(cli.app), "commands")
        self.assertTrue(top["upgrade"].hidden)
        self.assertTrue(top["einherjar"].hidden)
        self.assertTrue(top["yggdrasil"].hidden)


class TestPowerShellCompletion(unittest.TestCase):
    """Windows 사용자도 140개 넘는 명령을 자동완성으로 친다.

    이 검사가 test_completions.py가 아니라 여기 있는 이유는 그 파일이 이번 수리의 소유 밖이기 때문이다.
    셸 3벌의 기능 시험은 그쪽에 있고, 여기는 새로 생긴 네 번째 벌만 본다.
    """

    def _script(self) -> str:
        script = comp._render("powershell")
        self.assertIsNotNone(script)
        return script or ""

    def test_powershell_is_a_known_shell(self):
        self.assertIn("powershell", comp._SHELLS)
        self.assertIn("Register-ArgumentCompleter -Native -CommandName asgard", self._script())

    def test_script_is_ascii_only(self):
        """Windows PowerShell 5.1은 BOM 없는 .ps1을 시스템 ANSI 코드페이지로 읽는다.

        비ASCII가 한 글자라도 들어가면 한국어 Windows에서 스크립트가 깨진 채 로드되고, 증상은
        "자동완성이 아무것도 안 나옴"이라 원인이 안 보인다. install.ps1이 ASCII-only인 것과 같은 이유다.
        """
        offenders = [char for char in self._script() if ord(char) > 127]
        self.assertEqual(offenders, [], "생성된 .ps1에 비ASCII 문자가 있다")

    def test_every_top_level_command_is_offered(self):
        script = self._script()
        for name in comp._surface().commands:
            with self.subTest(command=name):
                self.assertIn(f"'{name}'", script)

    def test_install_targets_powershell_on_windows(self):
        """`$SHELL`은 Windows에서 보통 비어 있다 — 그걸 셸 이름으로 읽던 것이 결측의 정체였다."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHELL", None)
            with mock.patch.object(comp.os, "name", "nt"):
                self.assertEqual(comp._login_shell(), "powershell")
        with mock.patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
            self.assertEqual(comp._login_shell(), "zsh", "POSIX에서는 `$SHELL`이 여전히 답이다")

    def test_install_writes_the_script_and_wires_the_profile_once(self):
        """재실행해도 프로파일 줄은 하나여야 한다 — 두 줄이면 셸이 같은 completer를 두 번 등록한다.

        실제 `$PROFILE`은 묻지 않고 대역으로 바꿔 둔다. 물으면 이 기계의 진짜 프로파일에 줄을 쓴다.
        """
        with tempfile.TemporaryDirectory(prefix="asgard-ps-home-") as home:
            profile = os.path.join(home, "Documents", "PowerShell", "profile.ps1")
            with (
                mock.patch.dict(os.environ, {"HOME": home}),
                mock.patch.object(comp, "_powershell_profile", return_value=profile),
            ):
                ui.set_quiet(True)
                try:
                    self.assertEqual(comp.run_completions("powershell", install=True), 0)
                    self.assertEqual(comp.run_completions("powershell", install=True), 0)
                finally:
                    ui.set_quiet(False)
                script = os.path.join(home, ".asgard", "completions", "asgard.ps1")
                self.assertTrue(os.path.exists(script))
                with open(profile, encoding="utf-8") as f:
                    wiring = f.read()
            self.assertEqual(wiring.count(comp._RC_MARKER), 1)
            self.assertIn(f'. "{script}"', wiring)

    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"), "no PowerShell on PATH")
    def test_script_parses(self):
        exe = shutil.which("pwsh") or shutil.which("powershell")
        with tempfile.TemporaryDirectory(prefix="asgard-ps-") as d:
            path = Path(d, "asgard.ps1")
            path.write_text(self._script(), encoding="utf-8")
            probe = (
                "$e = $null; "
                f"$null = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$null, [ref]$e); "
                "if ($e) { $e | ForEach-Object { $_.Message }; exit 1 }"
            )
            assert exe is not None
            result = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-Command", probe],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestHelpMentionsTheRealShells(unittest.TestCase):
    def test_completions_help_lists_every_renderer(self):
        """도움말이 셸 목록을 손으로 다시 적는 자리 — 렌더러가 늘면 여기가 먼저 낡는다."""
        command = getattr(get_command(cli.app), "commands")["completions"]
        listed = set(re.findall(r"[a-z]+", (command.help or "").split("(")[-1]))
        self.assertTrue(set(comp._SHELLS) <= listed, f"`completions` 도움말이 {comp._SHELLS}를 다 담지 않는다")


if __name__ == "__main__":
    unittest.main()
