#!/usr/bin/env python3
"""Windows 크로스플랫폼 슬라이스 — POSIX 호스트에서 Windows 분기를 목킹으로 검증.

실환경 Windows 검증은 CI 매트릭스 몫 — 여기서는 플랫폼 분기 로직 자체만 고정한다.

실행: uv run pytest tests/test_windows.py
"""

import json
import os
import stat
import tempfile
import unittest
from unittest import mock

from asgard import platform as asg_platform
from asgard import providers
from asgard.agent import claude_native
from asgard.templates import cc_settings, codex_config, cursor_hooks_json


def _win(module):
    """모듈이 참조하는 sys.platform을 win32로 — sys는 단일 모듈이라 어디서 갈아도 동일."""
    return mock.patch.object(module.sys, "platform", "win32")


class TestHookPython(unittest.TestCase):
    """hook_python — uv 가 정본, 시스템 파이썬은 폴백.

    설치 경로(install.sh·install.ps1)가 uv → uv 관리 CPython → asgard 순이라, 설치가 끝난
    기계에서 존재가 보장된 런타임은 uv 뿐이다. 시스템 python3 는 없을 수도(Windows 는 없는
    쪽이 보통) 낡았을 수도 있다 — 그래서 우선순위가 뒤다.

    배선(`hook_python`)은 절대 경로, 안내문·허용목록(`hook_python_token`)은 맨 토큰이다."""

    def test_uv_wins_on_posix(self):
        with mock.patch.object(asg_platform.sys, "platform", "linux"):
            with mock.patch.object(asg_platform.shutil, "which", side_effect=lambda c: f"/usr/local/bin/{c}"):
                self.assertEqual(asg_platform.hook_python(), "/usr/local/bin/uv run --no-project python")
                self.assertEqual(asg_platform.hook_python_token(), "uv run --no-project python")

    def test_uv_wins_on_windows(self):
        with _win(asg_platform):
            with mock.patch.object(asg_platform.shutil, "which", side_effect=lambda c: rf"C:\bin\{c}.exe"):
                # 역슬래시는 따옴표 안에서도 셸마다 다르게 읽힌다 — 정방향 슬래시로 넘긴다.
                self.assertEqual(asg_platform.hook_python(), "C:/bin/uv.exe run --no-project python")
                self.assertEqual(asg_platform.hook_python_token(), "uv run --no-project python")

    def test_a_path_that_cannot_be_quoted_falls_back_to_the_bare_token(self):
        """작은따옴표가 든 경로는 codex 의 TOML 리터럴 문자열 안에서 탈출할 방법이 없다."""
        with mock.patch.object(asg_platform.sys, "platform", "linux"):
            with mock.patch.object(asg_platform.shutil, "which", side_effect=lambda c: f"/home/o'brien/bin/{c}"):
                self.assertEqual(asg_platform.hook_python(), "uv run --no-project python")

    def test_posix_without_uv_is_python3(self):
        with mock.patch.object(asg_platform.sys, "platform", "linux"):
            with mock.patch.object(
                asg_platform.shutil, "which", side_effect=lambda c: "/usr/bin/python3" if c == "python3" else None
            ):
                self.assertEqual(asg_platform.hook_python(), "python3")

    def test_windows_without_uv_prefers_python(self):
        with _win(asg_platform):
            with mock.patch.object(
                asg_platform.shutil, "which", side_effect=lambda c: r"C:\Python\python.exe" if c == "python" else None
            ):
                self.assertEqual(asg_platform.hook_python(), "python")

    def test_windows_without_uv_falls_back_to_py_launcher(self):
        with _win(asg_platform):
            with mock.patch.object(
                asg_platform.shutil, "which", side_effect=lambda c: r"C:\Windows\py.exe" if c == "py" else None
            ):
                self.assertEqual(asg_platform.hook_python(), "py")

    def test_windows_nothing_found_defaults_python(self):
        with _win(asg_platform):
            with mock.patch.object(asg_platform.shutil, "which", return_value=None):
                self.assertEqual(asg_platform.hook_python(), "python")

    def test_posix_nothing_found_defaults_python3(self):
        with mock.patch.object(asg_platform.sys, "platform", "linux"):
            with mock.patch.object(asg_platform.shutil, "which", return_value=None):
                self.assertEqual(asg_platform.hook_python(), "python3")


class TestDetectAuthWindows(unittest.TestCase):
    """detect_auth가 Windows에서 os.uname AttributeError 없이 폴백해야 한다."""

    def test_no_crash_and_falls_to_unknown(self):
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")}
        with mock.patch.dict("os.environ", env, clear=True):
            with _win(claude_native):
                with mock.patch.object(claude_native.os.path, "exists", return_value=False):
                    kind, _ = claude_native.detect_auth()
        self.assertEqual(kind, "unknown")  # darwin 분기(keychain 조회)를 안 탄다 — 크래시 없음이 본체

    def test_darwin_branch_still_uses_sys_platform(self):
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")}
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(claude_native.sys, "platform", "darwin"):
                with mock.patch.object(claude_native.os.path, "exists", return_value=False):
                    with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run:
                        kind, _ = claude_native.detect_auth()
        self.assertEqual(kind, "keychain")
        self.assertEqual(run.call_args[0][0][0], "security")


class TestTemplatesWindowsWiring(unittest.TestCase):
    """스캐폴드 훅 배선이 생성 시점의 플랫폼 인터프리터를 쓴다."""

    @staticmethod
    def _hook_cmds(settings: dict) -> list[str]:
        return [h["command"] for event in settings["hooks"].values() for entry in event for h in entry["hooks"]]

    def test_cc_settings_windows_swaps_interpreter(self):
        with mock.patch("asgard.templates.claude.hook_python", return_value="py"):
            s = json.loads(cc_settings())
        cmds = self._hook_cmds(s)
        self.assertTrue(cmds and all(c.startswith('py "$CLAUDE_PROJECT_DIR') for c in cmds))

    def test_cc_settings_posix_stays_python3(self):
        with mock.patch("asgard.templates.claude.hook_python", return_value="python3"):
            s = json.loads(cc_settings())
        self.assertTrue(all(c.startswith('python3 "') for c in self._hook_cmds(s)))

    def test_cursor_hooks_windows(self):
        # 계약은 "Windows 면 py 접두"이지 "n번째 훅이 무엇인가"가 아니다 — 위치로 재면 레인 앞에
        # 훅을 하나 더할 때마다 무관한 Windows 테스트가 깨진다 (26-07-27 secret-guard 읽기 측이 그랬다).
        with mock.patch("asgard.templates.cursor.hook_python", return_value="py"):
            h = json.loads(cursor_hooks_json())
        shell = [entry["command"] for entry in h["hooks"]["beforeShellExecution"]]
        self.assertTrue(shell and all(c.startswith("py .cursor/hooks/") for c in shell))
        self.assertIn("py .cursor/hooks/git-guard.py", shell)
        self.assertEqual(h["hooks"]["postToolUseFailure"][0]["command"], "py .cursor/hooks/failure-tracker.py")

    def test_codex_config_windows(self):
        with mock.patch("asgard.templates.codex.hook_python", return_value="py"):
            cfg = codex_config()
        self.assertIn('py "$(git rev-parse --show-toplevel)/.codex/hooks/git-guard.py"', cfg)
        self.assertNotIn("python3", cfg)

    def test_codex_config_posix_unchanged(self):
        with mock.patch("asgard.templates.codex.hook_python", return_value="python3"):
            cfg = codex_config()
        self.assertIn('python3 "$(git rev-parse --show-toplevel)/.codex/hooks/git-guard.py"', cfg)


class TestCredentialLockdown(unittest.TestCase):
    """키 파일 잠금: POSIX는 chmod 600, Windows는 icacls 소유자 단독 ACL."""

    def test_windows_uses_icacls(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "credentials.json")
            open(path, "w").write("{}")
            with mock.patch.object(providers.os, "name", "nt"):
                with mock.patch.dict("os.environ", {"USERNAME": "odin"}):
                    with mock.patch("subprocess.run") as run:
                        providers._lock_down(path)
        args = run.call_args[0][0]
        self.assertEqual(args[0], "icacls")
        self.assertIn("/inheritance:r", args)
        self.assertIn("odin:F", args)

    def test_windows_no_username_is_noop(self):
        env = {k: v for k, v in os.environ.items() if k != "USERNAME"}
        with mock.patch.object(providers.os, "name", "nt"):
            with mock.patch.dict("os.environ", env, clear=True):
                with mock.patch("subprocess.run") as run:
                    providers._lock_down("whatever")
        run.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX 권한 비트 검증")
    def test_posix_chmod_600(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "credentials.json")
            open(path, "w").write("{}")
            os.chmod(path, 0o644)
            providers._lock_down(path)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


class TestDoctorWindows(unittest.TestCase):
    """doctor의 인터프리터 체크·fix 안내가 플랫폼을 따른다."""

    def test_python_check_uses_hook_python(self):
        from asgard.commands import doctor

        # `shutil.which` 를 자리에서 막는다. win32 로 가장한 호스트에서 진짜 which 를 부르면
        # CPython 3.14.6 의 Windows 분기가 `_winapi` 를 만지는데, POSIX 에서 그 모듈은 None 이다.
        # `on_path` 셋(파사드·engines·platform 내부의 raw 호출)을 각각 씌우는 대신 그 셋이
        # 공통으로 닿는 한 자리를 막는다 — 새 호출부가 생겨도 여기서 같이 막힌다.
        with mock.patch.object(doctor.wiring, "hook_python_token", return_value="py"):
            with (
                mock.patch("shutil.which", side_effect=lambda b, *a, **k: f"C:\\bin\\{b}.exe"),
                mock.patch.object(doctor, "on_path", side_effect=lambda b: f"C:\\bin\\{b}.exe"),
                mock.patch.object(doctor.engines, "on_path", side_effect=lambda b: f"C:\\bin\\{b}.exe"),
            ):
                with mock.patch.object(doctor.sys, "platform", "win32"):
                    import io
                    from contextlib import redirect_stdout

                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        doctor.run_doctor(json_out=True)
        out = json.loads(buf.getvalue())
        names = [c["name"] for c in out["checks"]]
        self.assertIn("py (hooks)", names)
        path_check = next(c for c in out["checks"] if c["name"] == "asgard on PATH")
        self.assertIn("uv tool update-shell", path_check["fix"])


class TestTextIOCarriesItsEncoding(unittest.TestCase):
    """텍스트 입출력은 인코딩을 스스로 들고 다녀야 한다 — 안 주면 로케일 기본값으로 열린다.

    문이 둘이다. 파일(`open`/`read_text`/`write_text`)과 **자식 프로세스 파이프**
    (`subprocess.run(..., text=True)`). 처음엔 파일만 봤다가 `asgard update`가 같은 로케일에서
    `UnicodeDecodeError: 'cp949' codec can't decode byte 0xec`로 죽었다 — uv가 UTF-8로 낸
    출력을 cp949로 디코딩한 것이다. 한쪽만 막은 가드는 막았다는 착각만 준다.

    왜 형상으로 재는가: POSIX 호스트의 기본값은 utf-8이라 인코딩을 빠뜨린 코드가 여기서는
    언제나 통과한다. 목킹으로도 못 잡는다 — 바꿔야 하는 것이 인터프리터가 시작할 때 정해지는
    로케일이기 때문이다. 그래서 실행이 아니라 호출 형상을 본다.

    26-07-27 실기(한국어 Windows, 로케일 cp949): `asgard init --cc`가 93파일 중 앞쪽에서
    UnicodeEncodeError로 죽었다. 원인은 스캐폴드 본문의 엠대시 한 글자였고, 죽은 자리는
    인코딩을 안 준 `Path.write_text` 였다. 게다가 그 시점엔 파일이 이미 열려 잘려 있어
    사용자 프로젝트에 반쪽 파일이 남았다.

    벤더링 자산(assets/)은 상류 사본이라 제외한다 — 여기서 고치면 다음 동기화에 되돌아온다.
    """

    def _offenders(self) -> list[str]:
        import ast

        import asgard

        root = os.path.dirname(os.path.abspath(asgard.__file__))
        out: list[str] = []
        for dirpath, dirnames, files in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "assets"]
            for fname in sorted(files):
                if not fname.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fname)
                with open(path, encoding="utf-8") as handle:
                    tree = ast.parse(handle.read())
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    hit = self._verdict(node)
                    if hit:
                        out.append(f"{os.path.relpath(path, root)}:{node.lineno} {hit}")
        return out

    @staticmethod
    def _verdict(node) -> str:
        import ast

        func = node.func
        if "encoding" in {kw.arg for kw in node.keywords}:
            return ""
        first = node.args[0] if node.args else None
        if isinstance(func, ast.Name) and func.id == "open":
            mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else "r"
            return "" if "b" in str(mode) else "open()"
        if isinstance(func, ast.Attribute) and func.attr == "open":
            # os.open은 fd라 인코딩이 없고, urlopen 계열의 `.open(req)`은 첫 인자가 모드가 아니다.
            if isinstance(func.value, ast.Name) and func.value.id in ("os", "webbrowser", "sys"):
                return ""
            if first is not None and not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                return ""
            mode = first.value if isinstance(first, ast.Constant) else "r"
            return "" if "b" in str(mode) else "Path.open()"
        if isinstance(func, ast.Attribute) and func.attr in ("read_text", "write_text"):
            # io_files의 동명 함수는 인코딩을 자기 안에서 준다 (그게 그 모듈의 존재 이유다).
            if isinstance(func.value, ast.Name) and func.value.id == "io_files":
                return ""
            return f"Path.{func.attr}()"
        # 두 번째 문 — 자식 프로세스의 stdout/stderr도 텍스트 모드면 로케일로 디코딩된다.
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in ("run", "Popen", "check_output", "check_call", "call"):
            module = getattr(getattr(func, "value", None), "id", "") if isinstance(func, ast.Attribute) else ""
            if module not in ("subprocess", "sp", ""):
                return ""
            keywords = {kw.arg for kw in node.keywords}
            # `encoding=`을 같이 준 텍스트 모드는 로케일을 안 탄다 — 그게 바로 이 검사가 요구하는 형태다.
            # 이걸 안 보면 정답을 오답으로 잡는다 (실측: commands/office.py는 이미 utf-8로 고정돼 있다).
            if keywords & {"text", "universal_newlines"} and "encoding" not in keywords:
                return f"subprocess.{name}(text=True)"
        return ""

    def test_no_text_io_relies_on_the_locale_default(self):
        offenders = self._offenders()
        self.assertEqual(offenders, [], "인코딩 없는 텍스트 입출력 — cp949 호스트에서 깨진다:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
