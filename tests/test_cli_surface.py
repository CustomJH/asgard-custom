#!/usr/bin/env python3
"""명령 표면 규칙 — 산문이 아니라 실행 가능한 형태로.

리프 명령이 140개를 넘는 표면에서 규칙을 문서로만 적어 두면 다음 커밋이 다시 흩뜨린다. 여기서 셋을 봉인한다.

  (a) `-q`는 `--quiet` 전용이다
  (b) 리프 명령은 `--json`을 가진다
  (c) 같은 단축 플래그가 서로 다른 긴 이름에 붙지 않는다

셋 다 **오늘의 상태를 기준선**으로 삼고 예외를 명시한다. 한 번에 전부 고치면 표면이 통째로 흔들리고,
그러면 규칙이 아니라 대공사가 된다. 예외 목록의 크기가 다음 작업의 척도다.

예외 항목마다 왜 예외인지 한 줄이 붙어 있다. 이유를 못 적는 항목은 예외가 아니라 결함이다. 이유 줄에는
두 종류가 있다 — 규칙 밖이라 영구히 예외인 것과, 아직 안 고쳤을 뿐인 것(줄 끝에 "아직"으로 적는다).

세 검사 모두 **양방향**이다: 새 위반이 생겨도 깨지고, 예외에 적힌 명령이 규칙을 이미 지켜도 깨진다.
후자가 없으면 목록이 낡은 채로 남아 "예외 56건"이 영원히 56건으로 보인다.

여기서 리프란 하위 명령이 없는 가시 명령이다. `mode`·`ticket`처럼 인자 없이도 도는 그룹은 제외한다 —
그 자리의 플래그는 그룹 콜백이 선언하므로 리프와 같은 규칙으로 판정하면 결과가 어긋난다.

실행: uv run pytest tests/test_cli_surface.py
"""

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
    # 산출물이 JSON으로 감쌀 것이 아니거나, 화면 자체가 결과인 자리
    "start": "대화형 터미널 — 세션 화면이 산출물이다",
    "init": "스캐폴딩 진행 화면 — 결과물은 파일이고 요약은 `doctor --json`이 낸다",
    "update": "uv tool 출력을 그대로 흘린다 — 감쌀 구조가 없다",
    "sync": "update와 같은 자리 — 설치 갱신 로그를 흘린다",
    "uninstall": "확인 프롬프트가 본체다",
    "completions": "산출물이 셸 스크립트 그 자체다",
    "auth login": "브라우저 OAuth 왕복 — 대화형",
    "mode pick": "선택 패널 — 사람이 고르는 자리다",
    "memory mcp": "stdio MCP 브리지 — stdout이 프로토콜 채널이라 JSON을 더 얹을 수 없다",
    "memory snapshot": "출력이 이미 주입용 텍스트 블록이다",
    "memory recall": "memory snapshot과 같은 자리 — 주입용 텍스트",
    "open studio": "창을 여는 명령 — 결과는 프로세스지 값이 아니다",
    "open memory": "open studio와 같은 자리",
    "office render": "산출물이 PDF·이미지 파일이다",
    "office template": "템플릿 레지스트리 조작 — 조회는 `office outline --json`이 낸다",
    # 조회·변경인데 아직 안 붙은 자리 — 여기가 다음 작업의 몫이다
    "auth status": "조회인데 아직",
    "auth logout": "변경인데 아직",
    "role list": "도움말이 (JSON)이라 적혀 있고 항상 JSON을 내는데 플래그가 없다 — 아직",
    "role model": "조회 겸 변경인데 아직",
    "role run": "역할 턴 결과가 퀘스트 로그로만 간다 — 아직",
    "mode set": "변경인데 아직",
    "mode reset": "변경인데 아직",
    "skills show": "조회인데 아직",
    "skills run": "헬퍼 실행 결과가 사람 화면으로만 간다 — 아직",
    "skills assign": "변경인데 아직",
    "skills unassign": "변경인데 아직",
    "skills enable": "변경인데 아직",
    "skills disable": "변경인데 아직",
    "plugins install": "변경인데 아직",
    "memory add": "변경인데 아직",
    "memory ingest": "변경인데 아직",
    "memory contradiction-seen": "변경인데 아직",
    "memory discard": "변경인데 아직",
    "memory reindex": "변경인데 아직",
    "memory export-okf": "번들 경로를 값으로 돌려줘야 한다 — 아직",
    "memory show": "조회인데 아직",
    "memory remove": "변경인데 아직",
    "memory merge": "변경인데 아직",
    "memory path": "조회 겸 변경인데 아직",
    "memory norn-restore": "변경인데 아직",
    "memory connect": "변경인데 아직",
    "memory project-approve": "변경인데 아직",
    "ticket comment": "변경인데 아직",
    "ticket link": "변경인데 아직",
    "ticket delete": "변경인데 아직",
    "evolve scan": "변경인데 아직",
    "evolve nudge": "훅용 한 줄 알림 — 아직",
    "evolve list": "조회인데 아직",
    "evolve show": "조회인데 아직",
    "evolve approve": "변경인데 아직",
    "evolve reject": "변경인데 아직",
    "evolve polish": "변경인데 아직",
    "evolve bench": "A/B 수치를 값으로 돌려줘야 한다 — 아직",
    "evolve curate": "조회인데 아직",
    "evolve archive": "변경인데 아직",
    "evolve restore": "변경인데 아직",
}

# ── (c) 같은 단축이 서로 다른 긴 이름에 붙은 자리 — 단축 글자마다 이유 한 줄 ─────────────
#
# `-q`는 여기 없다. 26개 명령이 `--quiet`로 쓰는 글자를 두 명령이 `--query`로 쓰고 있었고, 근육기억이
# 그대로 오작동했다 — 소수 쪽(`map context`·`ticket list`)에서 단축을 뗐다. 나머지 다섯은 아직이다.
_SHORT_CONFLICTS = {
    "-c": "start `--continue` vs ticket `--cycle` — 겹치는 명령이 없어 오작동은 안 나지만 뜻이 둘이다, 아직",
    "-e": "k6 `--env` vs ticket `--estimate` — 아직",
    "-k": "memory `--limit` vs ticket link `--kind` — 긴 이름은 갈랐고 단축만 남았다, 아직",
    "-o": "office `--output` vs office render `--outdir` — 같은 그룹 안에서 갈린다, 아직",
    "-p": "open `--port` vs ticket `--priority` — 아직",
}


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
        self.assertLessEqual(len(_NO_JSON), 56, "`--json` 예외는 늘릴 수 없다 — 줄이는 방향만 있다")


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
