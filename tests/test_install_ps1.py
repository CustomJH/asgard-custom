"""install.ps1 불변식 — 부트스트랩 스크립트는 스스로를 설명할 수 있어야 한다.

실행: uv run pytest tests/test_install_ps1.py

이 파일은 `irm … | iex`로 **텍스트째 내려받아 실행**되는 유일한 진입점이다. 그래서 보통
스크립트라면 사소한 것이 여기서는 치명적이다:

  · `exit`는 이 세션이 아니라 **호스트 셸**을 끝낸다. 파이프로 먹인 스크립트 안의 `exit 1`은
    사용자의 PowerShell 창을 통째로 닫아버려서, 실패 이유가 화면에 남을 시간이 없다.
    (실측 증상: "파이썬 없으면 그냥 픽하고 꺼짐" — 창이 닫힌 것이지 설치가 조용히 끝난 게 아니다.)
  · 파스 에러는 어떤 핸들러보다 먼저 일어난다. PS7 전용 연산자 하나, 잘못 디코드된 바이트 하나면
    스크립트 전체가 실행되기 전에 죽고, 그때는 안에 적어둔 어떤 안내도 출력되지 않는다.
  · 남의 부트스트랩 스크립트(astral.sh/uv/install.ps1)를 이 세션에서 `iex` 하면 그쪽의 `exit`가
    똑같이 우리 창을 닫는다. 자식 프로세스에 격리해야 한다.

그래서 여기서 막는 것은 "스타일"이 아니라 **창이 닫히는 경로**다. 각 검사는 실제로 관측된
실패 하나에 대응한다.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_PS1 = os.path.join(ROOT, "install.ps1")
INSTALL_SH = os.path.join(ROOT, "install.sh")

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


def _sh() -> str:
    with open(INSTALL_SH, encoding="utf-8") as fh:
        return fh.read()


def _statements() -> list[tuple[int, str]]:
    """코드 줄을 **문장** 단위로 접은 것 — 인자 목록이 다음 줄로 넘어간 호출도 한 덩어리로 본다.

    (`Invoke-Native 'winget' @('install', …,\\n  '--accept-…') -Spin …`처럼 꼬리에 붙은
    `-Spin`이 둘째 줄에 있으면, 줄 단위 검사는 그 호출을 "스피너 없음"으로 오독한다.)
    """
    out: list[tuple[int, str]] = []
    buf, start, prev = "", 0, -2
    for num, line in _code_lines():
        stripped = line.strip()
        # 줄이 붙어 있지 않으면(주석·문자열 페이로드가 사이에 걸러졌으면) 잇지 않는다 —
        # 이으면 남남인 두 문장이 한 덩어리가 되어 검사가 엉뚱한 것을 읽는다 (실측: winget 호출의
        # 둘째 줄이 걸러져 다음 문장과 붙었고, 그 바람에 -Spin이 "없는" 것으로 보였다).
        if buf and num != prev + 1:
            out.append((start, buf))
            buf = ""
        if not buf:
            start = num
        buf = (buf + " " + stripped).strip() if buf else stripped
        prev = num
        if stripped.endswith(",") or stripped.endswith("+"):
            continue  # 인자 목록·문자열 연결이 이어진다
        out.append((start, buf))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


def _bare(line: str) -> str:
    """문자열 리터럴 안쪽을 비운 줄 — 사람에게 보여줄 메시지에 들어간 `exit`·`||`는 문법이 아니다.

    (실측: `"present but exit " + $code` 라는 안내 문구가 `exit` 금지 규칙에 걸렸다.)
    """
    return re.sub(r"'[^']*'|\"[^\"]*\"", '""', line)


class InstallPs1Encoding(unittest.TestCase):
    def test_ascii_only(self) -> None:
        """비ASCII 한 바이트가 파스 에러가 된다.

        `Invoke-RestMethod`는 응답 charset을 보고 디코드한다. 헤더가 없거나 프록시가 갈아끼우면
        UTF-8 한글 주석이 cp949로 읽히고, 그 깨진 바이트 중 하나가 따옴표나 백틱으로 해석되는
        순간 스크립트는 실행되기 전에 죽는다. install.sh는 파일로 저장돼 bash가 읽으므로
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
        """pwsh이 있으면 진짜 파서로 확인한다 (정적 검사의 상한을 올린다)."""
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

    tests/install_ps1_smoke.ps1이 진입 블록을 가짜 Main과 함께 자식 셸에서 구동한다
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
        """`exit`는 창을 붙잡아 둔 뒤에만. 그 위에서는 전부 throw로 올려보낸다."""
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

        이 세션에서 iex 하면 이유를 찍은 **직후** 그 `exit`가 사용자 창을 닫는다 — 글자가 한 번
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

        Windows PowerShell은 리다이렉트된 네이티브 stderr를 ErrorRecord로 바꾼다. 'Stop' 이면
        그게 종료 오류가 되어, **성공한 단계에서도** 스크립트를 끊는다. uv는 진행 상황을
        stderr에 쓴다 — 즉 정상 동작이 곧 중단 사유였다.
        """
        for num, line in _code_lines():
            if re.search(r"2>\s*\$null|2>&1\s*\|\s*Out-Null", _bare(line)):
                self.fail(
                    f"install.ps1:{num} redirects native stderr; route it through Invoke-Native "
                    f"(which forces $ErrorActionPreference='Continue') instead:\n  {line.strip()}"
                )


class InstallPs1Diagnostics(unittest.TestCase):
    def test_web_calls_use_basic_parsing(self) -> None:
        """-UseBasicParsing 없으면 IE 엔진에 의존한다 — 초기 설정 전 Windows에서 통째로 실패."""
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
        """node는 프레이야 엔진용이지 설치 전제가 아니다 — 경고 한 줄로 끝나야 한다."""
        hits = [line.strip() for _, line in _code_lines() if "node not found" in line]
        self.assertEqual(len(hits), 1, f"expected exactly one 'node not found' surface, got {hits}")
        self.assertTrue(hits[0].startswith("Write-Warn2"), f"node absence must be a warning, not a Fail:\n  {hits[0]}")
        self.assertIn("installs fine without it", hits[0])


class InstallPs1SurfaceParity(unittest.TestCase):
    """윈도우 설치 화면은 install.sh와 **같은 화면**이어야 한다.

    사용자 요구가 그것이다 — "리눅스나 맥에서 설치하는 것처럼 똑같이". 그런데 ps1은 ASCII만
    담을 수 있어(위 Encoding 참조) 같은 글리프를 코드포인트와 base64로 우회해 싣는다. 우회한
    사본은 원본이 바뀌어도 안 따라간다 — **그 드리프트가 여기서 잡히지 않으면 아무 데서도 안
    잡힌다.** 아래 검사는 전부 "두 파일이 같은 것을 그리는가"만 묻는다.
    """

    def _sh_art(self) -> str:
        m = re.search(r"cat <<'ART'\n(.*?)\nART\n", _sh(), re.S)
        self.assertIsNotNone(m, "install.sh no longer carries an ART block to mirror")
        assert m is not None
        return m.group(1)

    def _ps_glyphs(self) -> dict[str, str]:
        """install.ps1의 **리치** 글리프 표 (두 번째 AsgardGlyph 할당) → {이름: 실제 글자}."""
        blocks = re.findall(r"\$script:AsgardGlyph = @\{(.*?)^\s*\}", _text(), re.S | re.M)
        self.assertGreaterEqual(len(blocks), 2, "install.ps1 lost its ASCII/Unicode glyph pair")
        rich = blocks[1]
        out: dict[str, str] = {}
        for name, cp in re.findall(r"(\w+) = \[string\]\[char\](0x[0-9A-Fa-f]+)", rich):
            out[name] = chr(int(cp, 16))
        for name, lit in re.findall(r"(\w+) = '([^']*)'", rich):
            out.setdefault(name, lit)
        return out

    def _sh_mark(self, fn: str) -> str:
        """install.sh의 ok/warn/info/die가 찍는 글리프 — printf 서식의 첫 %s…%s 사이 한 글자."""
        m = re.search(rf"^{fn}\(\)\s+\{{ printf '[^']*?%s(.)%s", _sh(), re.M)
        self.assertIsNotNone(m, f"install.sh:{fn}() no longer looks like a mark printer")
        assert m is not None
        return m.group(1)

    def test_logo_is_byte_identical_to_install_sh(self) -> None:
        """브랜드 락업은 base64로 실려 있다 — 디코드하면 install.sh의 ART와 **바이트가 같아야** 한다.

        같은 그림을 두 파일에 손으로 두 번 적으면 한쪽만 고쳐진다. 여기서는 한쪽을 고치면 이
        검사가 즉시 빨개진다.
        """
        m = re.search(r"\$script:AsgardLogo = @\((.*?)\n\)", _text(), re.S)
        self.assertIsNotNone(m, "install.ps1 lost its logo payload")
        assert m is not None
        blob = "".join(re.findall(r"'([A-Za-z0-9+/=]*)'", m.group(1)))
        try:
            art = base64.b64decode(blob, validate=True).decode("utf-8")
        except Exception as e:  # noqa: BLE001 — 어떤 실패든 "그림이 안 나온다"로 같다
            self.fail(f"install.ps1's logo payload does not decode: {e}")
        self.assertEqual(
            art,
            self._sh_art(),
            "install.ps1's logo has drifted from install.sh's. Regenerate it:\n"
            '  python -c "import re,base64,textwrap;'
            "s=open('install.sh',encoding='utf-8').read();"
            "a=re.search(chr(34)+r'cat <<.ART.\\n(.*?)\\nART\\n'+chr(34),s,re.S).group(1);"
            'print(textwrap.wrap(base64.b64encode(a.encode()).decode(),108))"',
        )

    def test_logo_width_matches_the_art(self) -> None:
        """버전 꼬리표는 락업 오른쪽 끝에 맞춰 흘려 쓴다 — 폭이 틀리면 허공에 뜬다."""
        m = re.search(r"\$script:AsgardLogoWidth = (\d+)", _text())
        self.assertIsNotNone(m, "install.ps1 lost its logo width")
        assert m is not None
        widths = {len(line) for line in self._sh_art().splitlines()}
        self.assertEqual({int(m.group(1))}, widths, "the version line is aligned to the wrong column")

    def test_spinner_frames_match_install_sh(self) -> None:
        """스피너는 같은 점자 바퀴여야 한다 (ps1은 코드포인트로 싣는다)."""
        m = re.search(r"local fr=\(([^)]*)\)", _sh())
        self.assertIsNotNone(m, "install.sh no longer has a spinner frame list")
        assert m is not None
        sh_frames = [ord(c) for c in m.group(1).split()]
        cps = re.search(r"\$script:AsgardSpinCp = @\(([^)]*)\)", _text())
        self.assertIsNotNone(cps, "install.ps1 lost its spinner code points")
        assert cps is not None
        ps_frames = [int(h.strip(), 16) for h in cps.group(1).split(",")]
        self.assertEqual(ps_frames, sh_frames, "the two installers spin different wheels")

    def test_result_marks_match_install_sh(self) -> None:
        """✔ / ! / · / ✗ — 결과 한 줄의 어휘가 같아야 같은 화면으로 읽힌다."""
        rich = self._ps_glyphs()
        for ps_name, sh_fn in (("ok", "ok"), ("warn", "warn"), ("info", "info"), ("fail", "die")):
            self.assertEqual(
                rich.get(ps_name),
                self._sh_mark(sh_fn),
                f"install.ps1's '{ps_name}' glyph differs from install.sh's {sh_fn}()",
            )

    def test_phases_match_install_sh(self) -> None:
        """단계 수와 제목이 같아야 한다 — [n/3]의 분모가 갈리면 진행 감각부터 달라진다."""
        titles = re.findall(r'^\s*phase "([^"]+)"', _sh(), re.M)
        self.assertEqual(len(titles), 3, f"install.sh no longer has three phases: {titles}")
        steps = re.search(r"^STEP=0; STEPS=(\d+)", _sh(), re.M)
        self.assertIsNotNone(steps, "install.sh lost its phase denominator")
        assert steps is not None
        self.assertEqual(int(steps.group(1)), len(titles))

        calls = [s for _, s in _statements() if s.startswith("Phase ")]
        self.assertEqual(len(calls), len(titles), f"install.ps1 has {len(calls)} phases, install.sh has {len(titles)}")
        self.assertIn('"/3"' if '"/3"' in _text() else "/3", _text(), "install.ps1's phase denominator is not 3")
        for title, call in zip(titles, calls, strict=True):
            for half in title.split("·"):
                self.assertIn(
                    half.strip(),
                    call,
                    f"install.ps1's phase reads differently from install.sh's {title!r}:\n  {call}",
                )

    def test_slow_steps_animate(self) -> None:
        """오래 걸리는 단계는 전부 스피너를 단다 — 이 설치기가 고치려는 증상이 그것이다.

        (신고: "프로그레스 바나 이런 게 안 보인다". 정체는 uv 부트스트랩·인터프리터 내려받기·휠
        설치·~1GB 모델 내려받기 넷이 아무 표시 없이 조용했던 것.)
        """
        slow = {
            "-EncodedCommand": "uv bootstrap (astral.sh child shell)",
            "'winget'": "uv via winget",
            "'-m', 'pip'": "uv via pip",
            "'python', 'install'": "uv python install",
            "'tool', 'install'": "uv tool install",
            "'memory', 'semantic', 'warmup'": "memory search model",
        }
        for num, stmt in _statements():
            if "Invoke-Native" not in stmt:
                continue
            for marker, what in slow.items():
                if marker in stmt and "-Spin" not in stmt:
                    self.fail(
                        f"install.ps1:{num} runs a slow step ({what}) with no spinner - the screen "
                        f"sits dead while it works:\n  {stmt}"
                    )

    def test_terminal_state_is_handed_back(self) -> None:
        """콘솔 출력 인코딩은 프로세스 전역이고, `irm | iex`에서 그 프로세스는 **사용자 셸**이다.

        ErrorActionPreference와 같은 이유로 반드시 되돌려야 하고, 되돌리는 자리는 창을 붙잡기
        전이어야 한다 (붙잡는 동안 사용자 콘솔이 우리 코드페이지로 남아 있으면 안 된다).
        """
        text = _text()
        self.assertIn("function Restore-Terminal", text, "nothing puts the console encoding back")
        self.assertRegex(text, r"\$script:AsgardPrevOutEnc = \[Console\]::OutputEncoding")
        entry_line = next(i for i, line in enumerate(_lines(), start=1) if line.startswith(ENTRY_MARK))
        tail = [(n, s) for n, s in _statements() if n > entry_line]
        restores = [n for n, s in tail if "Restore-Terminal" in s]
        holds = [n for n, s in tail if "Hold-Window" in s]
        self.assertTrue(restores, "the guarded tail never restores the console")
        self.assertTrue(holds, "the guarded tail never holds the window")
        self.assertLess(min(restores), min(holds), "the console is restored after the window hold, not before")

    def test_capability_probe_runs_inside_the_handler(self) -> None:
        """능력 판정이 Main 밖에서 던지면 아무 안내 없이 죽는다 — 판정은 try 안쪽에 있어야 한다."""
        body = _text().split("function Main {", 1)
        self.assertEqual(len(body), 2, "Main is gone")
        first = [line.strip() for line in body[1].splitlines() if line.strip()][0]
        self.assertEqual(first, "Initialize-Terminal", f"Main must probe the terminal first, got: {first}")

    def test_spinner_always_clears_its_line(self) -> None:
        """스피너 줄을 안 지우면 다음 ✔ 가 그 위에 겹쳐 찍힌다 — 실패로 빠져나갈 때도 마찬가지."""
        self.assertRegex(
            _text(),
            r"\} finally \{\s*\n\s*Clear-SpinLine\s*\n\s*\}",
            "Invoke-Spun must clear the spinner line in a finally block (a throw leaves it on screen)",
        )
        self.assertRegex(
            _text(),
            r"function Show-Failure[^\n]*\n(?:.*\n)*?\s*Clear-SpinLine",
            "the failure handler must wipe a spinner still on screen before printing the reason",
        )

    def test_tls_is_raised_before_the_first_request(self) -> None:
        """배너의 버전 조회가 이 스크립트의 **첫 https 요청**이다.

        Windows PowerShell 5.1은 TLS 1.0으로 나가고 github는 그걸 거절한다 — 순서가 뒤집히면
        버전 줄이 조용히 사라진다(실패가 try 안에서 삼켜지므로 아무도 이유를 못 본다).
        """
        body = _text().split("function Main {", 1)[1]
        web = body.find("Initialize-Web")
        banner = body.find("Write-Banner")
        self.assertGreater(web, -1, "Main never configures TLS")
        self.assertGreater(banner, -1, "Main never draws the banner")
        self.assertLess(web, banner, "the banner's version lookup runs before TLS 1.2 is enabled")

    def test_the_font_probe_still_asks_the_terminal_to_name_itself(self) -> None:
        """리치 글리프의 진짜 전제는 **폰트**인데, 폰트는 물어볼 수가 없다.

        그래서 "터미널이 자기 이름을 대는가"로 대신 묻는다 — Windows Terminal·ConEmu·VS Code·
        서드파티 에뮬레이터는 전부 자기를 밝히고, 글리프를 박스로 그리는 레거시 conhost만
        아무 이름도 대지 않는다. 이 목록이 사라지면 그 conhost에 점자 박스가 뜬다.
        (행동 스모크로는 못 잡는 자리다: 스모크는 FORCE_UI로 이 관문을 항상 통과시킨다.)
        """
        m = re.search(r"foreach \(\$v in @\(([^)]*)\)\) \{\s*\n\s*if \(\$v\) \{ \$named = \$true \}", _text())
        self.assertIsNotNone(m, "install.ps1 no longer asks the terminal to identify itself")
        assert m is not None
        for signal in ("$env:WT_SESSION", "$env:ConEmuANSI", "$env:TERM_PROGRAM", "$env:TERM"):
            self.assertIn(signal, m.group(1), f"{signal} dropped from the terminal probe")
        self.assertIn(
            "if ($env:ASGARD_ASCII) { return }",
            _text(),
            "ASGARD_ASCII is the escape hatch for a console that names itself and still cannot draw",
        )

    def test_network_calls_cannot_hang_the_install(self) -> None:
        """배너의 버전 조회까지 포함해 모든 HTTP 호출에 타임아웃 — 기본값은 무한대에 가깝다.

        장식 한 줄 때문에 설치가 안 끝나는 것은 "진행 표시가 없다"의 최악형이다.
        """
        for num, stmt in _statements():
            if re.search(r"\bInvoke-(WebRequest|RestMethod)\b", stmt):
                self.assertIn("-TimeoutSec", stmt, f"install.ps1:{num} can block forever:\n  {stmt}")


if __name__ == "__main__":
    unittest.main()
