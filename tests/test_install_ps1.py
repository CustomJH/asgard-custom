"""install.ps1 불변식 — 부트스트랩 스크립트는 스스로를 설명할 수 있어야 한다.

실행: uv run pytest tests/test_install_ps1.py

이 파일은 `irm … | iex` 로 **텍스트째 내려받아 실행**되는 유일한 진입점이다. 그래서 보통
스크립트라면 사소한 것이 여기서는 치명적이다:

  · `exit` 는 이 세션이 아니라 **호스트 셸**을 끝낸다. 파이프로 먹인 스크립트 안의 `exit 1` 은
    사용자의 PowerShell 창을 통째로 닫아버려서, 실패 이유가 화면에 남을 시간이 없다.
    (실측 증상: "파이썬 없으면 그냥 픽하고 꺼짐" — 창이 닫힌 것이지 설치가 조용히 끝난 게 아니다.)
  · 파스 에러는 어떤 핸들러보다 먼저 일어난다. PS7 전용 연산자 하나, 잘못 디코드된 바이트 하나면
    스크립트 전체가 실행되기 전에 죽고, 그때는 안에 적어둔 어떤 안내도 출력되지 않는다.
  · 남의 부트스트랩 스크립트(astral.sh/uv/install.ps1)를 이 세션에서 `iex` 하면 그쪽의 `exit` 가
    똑같이 우리 창을 닫는다. 자식 프로세스에 격리해야 한다.

그래서 여기서 막는 것은 "스타일"이 아니라 **창이 닫히는 경로**다. 각 검사는 실제로 관측된
실패 하나에 대응한다.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_PS1 = os.path.join(ROOT, "install.ps1")

# `# -- entry` 아래는 일이 다 끝난 뒤의 꼬리다 — 창을 붙잡아 둔 다음에만 프로세스를 끝낼 수 있다.
ENTRY_MARK = "# -- entry"


def _text() -> str:
    with open(INSTALL_PS1, encoding="utf-8") as fh:
        return fh.read()


def _lines() -> list[str]:
    return _text().splitlines()


def _is_string_literal(line: str) -> bool:
    """홑따옴표로 시작하는 줄 = 자식 셸로 넘길 페이로드 문자열의 한 조각."""
    return line.strip().startswith("'")


def _code_lines() -> list[tuple[int, str]]:
    """주석·문자열 페이로드를 뺀 실제 코드 줄만 (1-indexed)."""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(_lines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or _is_string_literal(stripped):
            continue
        out.append((i, line))
    return out


def _bare(line: str) -> str:
    """문자열 리터럴 안쪽을 비운 줄 — 사람에게 보여줄 메시지에 들어간 `exit`·`||` 는 문법이 아니다.

    (실측: `"present but exit " + $code` 라는 안내 문구가 `exit` 금지 규칙에 걸렸다.)
    """
    return re.sub(r"'[^']*'|\"[^\"]*\"", '""', line)


class InstallPs1Encoding(unittest.TestCase):
    def test_ascii_only(self) -> None:
        """비ASCII 한 바이트가 파스 에러가 된다.

        `Invoke-RestMethod` 는 응답 charset 을 보고 디코드한다. 헤더가 없거나 프록시가 갈아끼우면
        UTF-8 한글 주석이 cp949 로 읽히고, 그 깨진 바이트 중 하나가 따옴표나 백틱으로 해석되는
        순간 스크립트는 실행되기 전에 죽는다. install.sh 는 파일로 저장돼 bash 가 읽으므로
        같은 위험이 없다 — 이 제약은 ps1 에만 건다.
        """
        raw = open(INSTALL_PS1, "rb").read()
        bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        if bad:
            off = bad[0][0]
            around = raw[max(0, off - 40) : off + 40].decode("utf-8", "replace")
            self.fail(f"install.ps1 must stay ASCII-only; first non-ASCII byte at {off}: …{around}…")


class InstallPs1Syntax(unittest.TestCase):
    """Windows PowerShell 5.1 전용 — 사용자 기본 셸이 5.1 이고, 거기서 파스돼야 한다."""

    # PS7 에서만 파싱되는 것들. 5.1 에서는 전부 파스 에러 → 스크립트 통째 소멸.
    PS7_ONLY = [
        (r"(?<![|`])\|\|(?!\|)", "|| (PS7 pipeline chain)"),
        (r"(?<!&)&&(?!&)", "&& (PS7 pipeline chain)"),
        (r"\?\?", "?? / ??= (PS7 null-coalescing)"),
        (r"\$\w+\?\.", "?. (PS7 null-conditional)"),
        (r"\$IsWindows|\$IsLinux|\$IsMacOS", "$Is* automatic variable (PS7 only; $null in 5.1)"),
        (r"\bForEach-Object\s+-Parallel\b", "ForEach-Object -Parallel (PS7)"),
        (r"\bGet-Error\b", "Get-Error (PS7)"),
        (r"\$PSStyle\b", "$PSStyle (PS7)"),
    ]

    def test_no_ps7_only_syntax(self) -> None:
        for num, line in _code_lines():
            for pattern, label in self.PS7_ONLY:
                if re.search(pattern, _bare(line)):
                    self.fail(f"install.ps1:{num} uses {label}, which PowerShell 5.1 cannot parse:\n  {line.strip()}")

    def test_parses_when_powershell_available(self) -> None:
        """pwsh 이 있으면 진짜 파서로 확인한다 (정적 검사의 상한을 올린다)."""
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if not pwsh:
            self.skipTest("no pwsh/powershell on this host")
        script = (
            "$errs = $null; $toks = $null; "
            f"$null = [System.Management.Automation.Language.Parser]::ParseFile('{INSTALL_PS1}', "
            "[ref]$toks, [ref]$errs); "
            "if ($errs) { $errs | ForEach-Object { $_.Extent.StartLineNumber.ToString() + ': ' + $_.Message }; exit 2 }"
        )
        proc = subprocess.run([pwsh, "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, f"install.ps1 does not parse:\n{proc.stdout}\n{proc.stderr}")


class InstallPs1Behaviour(unittest.TestCase):
    """정적 검사는 형상만 본다 — 실패 경로가 실제로 무엇을 남기는지는 돌려봐야 안다.

    tests/install_ps1_smoke.ps1 이 진입 블록을 가짜 Main 과 함께 자식 셸에서 구동한다
    (설치는 하지 않는다). pwsh 없는 호스트에서는 건너뛴다.
    """

    def test_smoke(self) -> None:
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if not pwsh:
            self.skipTest("no pwsh/powershell on this host")
        smoke = os.path.join(ROOT, "tests", "install_ps1_smoke.ps1")
        self.assertTrue(os.path.exists(smoke), "install_ps1_smoke.ps1 is missing")
        env = dict(os.environ)
        env["ASGARD_NO_PAUSE"] = "1"
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", smoke], capture_output=True, text=True, timeout=300, env=env
        )
        self.assertEqual(proc.returncode, 0, f"install.ps1 smoke failed:\n{proc.stdout}\n{proc.stderr}")


class InstallPs1WindowSurvival(unittest.TestCase):
    """창이 닫히는 세 경로 — 각각이 실제로 사용자 터미널을 죽였던 자리다."""

    def test_exit_only_after_the_hold(self) -> None:
        """`exit` 는 창을 붙잡아 둔 뒤에만. 그 위에서는 전부 throw 로 올려보낸다."""
        text = _text()
        self.assertIn(ENTRY_MARK, text, "entry marker missing — the guarded tail must be identifiable")
        entry_line = next(i for i, line in enumerate(_lines(), start=1) if line.startswith(ENTRY_MARK))
        for num, line in _code_lines():
            if not re.search(r"(^|[;{(\s])exit\b", _bare(line)):
                continue
            self.assertGreater(
                num,
                entry_line,
                f"install.ps1:{num} exits while work is in flight — under `irm | iex` that closes the "
                f"user's terminal before the reason can be read. Use Fail (throw) instead:\n  {line.strip()}",
            )

    def test_failures_hold_the_window(self) -> None:
        text = _text()
        self.assertIn("function Hold-Window", text, "no Hold-Window — a failure would flash and vanish")
        tail = text.split(ENTRY_MARK, 1)[1]
        self.assertRegex(
            tail,
            r"if \(\$script:AsgardFailed\)\s*\{\s*\n\s*Hold-Window",
            "the failure branch must hold the window before anything else",
        )
        # 창을 붙잡기 전에 exit 하면 붙잡는 의미가 없다 — 코드 줄 기준으로만 본다(주석 무관).
        entry_line = next(i for i, line in enumerate(_lines(), start=1) if line.startswith(ENTRY_MARK))
        holds = [n for n, line in _code_lines() if n > entry_line and "Hold-Window" in line]
        exits = [n for n, line in _code_lines() if n > entry_line and re.search(r"(^|[;{(\s])exit\b", _bare(line))]
        self.assertTrue(holds, "the guarded tail never holds the window")
        for e in exits:
            self.assertTrue(
                any(h < e for h in holds),
                f"install.ps1:{e} exits before any Hold-Window — the reason would flash and vanish",
            )

    def test_top_level_handler_wraps_main(self) -> None:
        tail = _text().split(ENTRY_MARK, 1)[1]
        self.assertRegex(
            tail,
            r"try \{\s*\n\s*Main\s*\n\}\s*catch \{",
            "Main must run inside a try/catch — an unhandled terminating error prints nothing useful",
        )

    def test_foreign_bootstrap_runs_in_a_child_shell(self) -> None:
        """astral.sh 설치 스크립트 꼬리는 `catch { Write-Information $_; exit 1 }` 다 (26-07-27 확인).

        이 세션에서 iex 하면 이유를 찍은 **직후** 그 `exit` 가 사용자 창을 닫는다 — 글자가 한 번
        번쩍이고 사라지는 게 그거다. 자식 셸이면 자식만 끝난다.
        """
        text = _text()
        self.assertIn("-EncodedCommand", text, "the child shell call must use -EncodedCommand (no quoting hazards)")
        for num, line in _code_lines():
            bare = _bare(line)
            if "Invoke-Expression" in bare or re.search(r"\|\s*iex\b", bare):
                self.fail(
                    f"install.ps1:{num} runs a foreign script in this session — its `exit` would close "
                    f"the user's window. Hand it to a child powershell instead:\n  {line.strip()}"
                )

    def test_no_redirected_native_stderr(self) -> None:
        """`native.exe 2>$null` + $ErrorActionPreference='Stop' = NativeCommandError.

        Windows PowerShell 은 리다이렉트된 네이티브 stderr 를 ErrorRecord 로 바꾼다. 'Stop' 이면
        그게 종료 오류가 되어, **성공한 단계에서도** 스크립트를 끊는다. uv 는 진행 상황을 stderr
        에 쓴다 — 즉 정상 동작이 곧 중단 사유였다.
        """
        for num, line in _code_lines():
            if re.search(r"2>\s*\$null|2>&1\s*\|\s*Out-Null", _bare(line)):
                self.fail(
                    f"install.ps1:{num} redirects native stderr; route it through Invoke-Native "
                    f"(which forces $ErrorActionPreference='Continue') instead:\n  {line.strip()}"
                )


class InstallPs1Diagnostics(unittest.TestCase):
    def test_web_calls_use_basic_parsing(self) -> None:
        """-UseBasicParsing 없으면 IE 엔진에 의존한다 — 초기 설정 전 Windows 에서 통째로 실패."""
        for num, line in _code_lines():
            if re.search(r"\bInvoke-(WebRequest|RestMethod)\b", line):
                self.assertIn(
                    "-UseBasicParsing",
                    line,
                    f"install.ps1:{num} omits -UseBasicParsing:\n  {line.strip()}",
                )

    def test_failure_report_has_environment_and_log(self) -> None:
        text = _text()
        for needed in ("function Show-Failure", "function Get-EnvReport", "function Save-Transcript"):
            self.assertIn(needed, text, f"{needed} missing — a failure would leave nothing to report")

    def test_python_absence_is_explained_not_fatal(self) -> None:
        """시스템 파이썬은 전제조건이 아니다. 없다고 죽지도, 침묵하지도 않아야 한다."""
        text = _text()
        self.assertRegex(
            text,
            r"no system python[^\n]*not required",
            "preflight must say out loud that a missing system Python is fine — that guess is the "
            "first place users land when the installer dies",
        )

    def test_node_absence_is_a_warning_only(self) -> None:
        """node 는 프레이야 엔진용이지 설치 전제가 아니다 — 경고 한 줄로 끝나야 한다."""
        hits = [line.strip() for _, line in _code_lines() if "node not found" in line]
        self.assertEqual(len(hits), 1, f"expected exactly one 'node not found' surface, got {hits}")
        self.assertTrue(hits[0].startswith("Write-Warn2"), f"node absence must be a warning, not a Fail:\n  {hits[0]}")
        self.assertIn("installs fine without it", hits[0])


if __name__ == "__main__":
    unittest.main()
