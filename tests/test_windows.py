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
    """모듈이 참조하는 sys.platform 을 win32 로 — sys 는 단일 모듈이라 어디서 갈아도 동일."""
    return mock.patch.object(module.sys, "platform", "win32")


class TestHookPython(unittest.TestCase):
    """hook_python — POSIX 는 python3 고정, Windows 는 python → py 런처 탐지."""

    def test_posix_is_python3(self):
        with mock.patch.object(asg_platform.sys, "platform", "linux"):
            self.assertEqual(asg_platform.hook_python(), "python3")

    def test_windows_prefers_python(self):
        with _win(asg_platform):
            with mock.patch.object(
                asg_platform.shutil, "which", side_effect=lambda c: r"C:\Python\python.exe" if c == "python" else None
            ):
                self.assertEqual(asg_platform.hook_python(), "python")

    def test_windows_falls_back_to_py_launcher(self):
        with _win(asg_platform):
            with mock.patch.object(
                asg_platform.shutil, "which", side_effect=lambda c: r"C:\Windows\py.exe" if c == "py" else None
            ):
                self.assertEqual(asg_platform.hook_python(), "py")

    def test_windows_nothing_found_defaults_python(self):
        with _win(asg_platform):
            with mock.patch.object(asg_platform.shutil, "which", return_value=None):
                self.assertEqual(asg_platform.hook_python(), "python")

    def test_posix_no_python3_falls_back_to_uv(self):
        with mock.patch.object(asg_platform.sys, "platform", "linux"):
            with mock.patch.object(
                asg_platform.shutil, "which", side_effect=lambda c: "/usr/local/bin/uv" if c == "uv" else None
            ):
                self.assertEqual(asg_platform.hook_python(), "uv run --no-project python")

    def test_windows_no_python_falls_back_to_uv(self):
        with _win(asg_platform):
            with mock.patch.object(
                asg_platform.shutil, "which", side_effect=lambda c: r"C:\uv\uv.exe" if c == "uv" else None
            ):
                self.assertEqual(asg_platform.hook_python(), "uv run --no-project python")


class TestDetectAuthWindows(unittest.TestCase):
    """detect_auth 가 Windows 에서 os.uname AttributeError 없이 폴백해야 한다."""

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
        # statusline 은 bash 유지 — Claude Code Windows 는 Git Bash 필수라 셸 계약이 성립한다
        self.assertTrue(s["statusLine"]["command"].startswith("bash "))

    def test_cc_settings_posix_stays_python3(self):
        with mock.patch("asgard.templates.claude.hook_python", return_value="python3"):
            s = json.loads(cc_settings())
        self.assertTrue(all(c.startswith('python3 "') for c in self._hook_cmds(s)))

    def test_cursor_hooks_windows(self):
        with mock.patch("asgard.templates.cursor.hook_python", return_value="py"):
            h = json.loads(cursor_hooks_json())
        self.assertEqual(h["hooks"]["beforeShellExecution"][0]["command"], "py .cursor/hooks/git-guard.py")
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
    """키 파일 잠금: POSIX 는 chmod 600, Windows 는 icacls 소유자 단독 ACL."""

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
    """doctor 의 인터프리터 체크·fix 안내가 플랫폼을 따른다."""

    def test_python_check_uses_hook_python(self):
        from asgard.commands import doctor

        with mock.patch.object(doctor, "hook_python", return_value="py"):
            with mock.patch.object(doctor, "on_path", side_effect=lambda b: f"C:\\bin\\{b}.exe"):
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


if __name__ == "__main__":
    unittest.main()
