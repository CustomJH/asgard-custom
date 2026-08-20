"""환경 프리플라이트 — 아스가르드 없이 저장소를 연 기계에서 훅이 조용히 죽는 자리를 말로 바꾼다.

여기서 지키는 것은 셋이다. ① 스크립트가 세 호스트의 훅 폴더에 깔린다. ② 세 호스트 모두
SessionStart 의 **첫** 줄로 배선된다 (뒤에 오는 줄들이 부를 런타임을 그 앞에서 봐야 한다).
③ 스크립트 자체가 파이썬 없이 판정한다 — 런타임이 없으면 말하고, 있으면 아무 말도 안 하며,
어느 쪽이든 세션을 막지 않는다.

배선은 인터프리터를 직접 적지 않고 훅 폴더의 런처(`platform.HOOK_LAUNCHER`)를 부른다. 그래서
"이 기계에 런타임이 있는가"를 묻는 정확한 형태는 그 런처를 한 번 돌려 보는 것이고, 아래 시험은
런처 자리에 서는 것과 안 서는 것을 각각 놓아 두 갈래를 다 밟는다. 런처를 안 부르는 옛 배선
(절대 경로가 박힌 것)도 아직 세상에 있어서 그 갈래를 따로 남긴다.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from unittest import mock  # noqa: E402

from asgard import platform as asg_platform  # noqa: E402
from asgard.commands.doctor.wiring import _wired_hook_argv  # noqa: E402
from asgard.commands.setup import hook_files  # noqa: E402
from asgard.platform import HOOK_LAUNCHER, PREFLIGHT_PS1, PREFLIGHT_SH, PYTHON_PIN  # noqa: E402
from asgard.templates import cc_settings, codex_config, cursor_hooks_json  # noqa: E402
from asgard.templates.env import env_setup_ps1, env_setup_sh, hook_launcher_sh  # noqa: E402

_CC_WIRING = os.path.join(".claude", "settings" + ".json")
# PowerShell 쌍둥이를 실제로 돌릴 수 있는가. Windows 는 `powershell`(5.1), 그 밖의 기계는
# `pwsh`(7) 이 있으면 잡힌다 — 없으면 그 층은 통째로 건너뛴다.
_PWSH = shutil.which("pwsh") or shutil.which("powershell")

# 옛 배선 한 벌 — 권한 허용목록과 훅 줄이 한 파일에 같이 산다. 허용목록이 파일 앞쪽이라, 문구만
# 보고 첫 줄을 집는 추출은 인터프리터를 `Bash(uv` 로 읽는다. 그 함정을 시험이 직접 들고 있어야
# 한다: 지금 생성되는 배선에는 절대 경로가 아예 없어서 그쪽으로는 재현되지 않는다.
_LEGACY_WIRING = json.dumps(
    {
        "permissions": {"allow": ["Bash(uv run --no-project python .claude/hooks/quest-log.py *)"]},
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": '%s run --no-project python "$CLAUDE_PROJECT_DIR/.claude/hooks/hook-dispatch.py"',
                        }
                    ]
                }
            ]
        },
    },
    indent=2,
)


def _write(path: str, body: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)


class TestScaffold(unittest.TestCase):
    def test_pin_comes_from_platform(self):
        """CPython 핀의 정본은 한 자리다 — 스크립트가 자기 숫자를 따로 들면 배선과 갈린다."""
        self.assertIn('PIN="%s"' % PYTHON_PIN, env_setup_sh())

    def test_no_placeholder_survives_rendering(self):
        """자리표시자가 남으면 그 자리의 함수가 통째로 빠진 채 스크립트가 돈다."""
        leftovers = [w for w in env_setup_sh().split() if w.startswith("__") and w.endswith("__")]
        self.assertEqual(leftovers, [])

    def test_the_deploy_table_takes_the_names_from_platform(self):
        """파일 이름이 두 자리에 살면 한쪽을 고칠 때 다른 쪽이 조용히 뒤처진다."""
        names = [os.path.basename(path) for path, _ in hook_files("H", "claude-code")]
        self.assertIn(PREFLIGHT_SH, names)
        self.assertIn(PREFLIGHT_PS1, names)
        source = pathlib.Path("src/asgard/commands/setup.py").read_text(encoding="utf-8")
        table = source.split("def hook_files(")[1].split("\ndef ")[0]
        for literal in ('"%s"' % PREFLIGHT_SH, '"%s"' % PREFLIGHT_PS1):
            self.assertNotIn(literal, table, "이름을 platform 상수 대신 다시 적었다")

    def test_deployed_to_every_client(self):
        for client in ("claude-code", "codex", "cursor"):
            names = [os.path.basename(path) for path, _ in hook_files("H", client)]
            self.assertIn("env-setup.sh", names, client)


class TestWiring(unittest.TestCase):
    """세 호스트 모두 SessionStart 의 첫 줄이어야 한다 — 뒤 줄들의 전제를 재는 줄이다."""

    def test_claude_code_first(self):
        entry = json.loads(cc_settings())["hooks"]["SessionStart"][0]["hooks"][0]
        self.assertIn("env-setup.sh", entry["command"])
        self.assertTrue(entry["command"].startswith("sh "), entry["command"])

    def test_codex_first(self):
        block = codex_config().split("[[hooks.SessionStart.hooks]]")[1]
        self.assertIn("env-setup.sh", block)
        self.assertIn("command = 'sh ", block)

    def test_cursor_first(self):
        first = json.loads(cursor_hooks_json())["hooks"]["sessionStart"][0]["command"]
        self.assertIn("env-setup.sh", first)
        self.assertTrue(first.startswith("sh "), first)

    def test_doctor_reads_the_launcher_not_the_preflight(self):
        """프리플라이트 줄을 인터프리터로 읽으면 doctor 는 `sh -c pass` 로 늘 초록을 낸다."""
        with tempfile.TemporaryDirectory() as root:
            _write(os.path.join(root, _CC_WIRING), cc_settings())
            argv = _wired_hook_argv(root) or []
            self.assertNotIn("env-setup.sh", " ".join(argv))
            self.assertEqual(os.path.basename(argv[-1]), HOOK_LAUNCHER, argv)


@unittest.skipIf(sys.platform == "win32", "POSIX sh 로 도는 스크립트")
class TestScriptBehaviour(unittest.TestCase):
    """스크립트를 실제로 돌린다 — 이 층의 값은 파이썬 없이 답한다는 것 하나다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.hooks = os.path.join(self.root, ".claude", "hooks")
        # 실제로 깔리는 자리에 둔다 — 스크립트는 `$0` 에서 두 칸 올라가 저장소 뿌리를 찾는다.
        self.script = os.path.join(self.hooks, "env-setup.sh")
        _write(self.script, env_setup_sh())
        _write(os.path.join(self.root, _CC_WIRING), cc_settings())

    def launcher(self, body: str) -> None:
        _write(os.path.join(self.hooks, HOOK_LAUNCHER), body)

    def run_check(self, client: str = "claude-code") -> subprocess.CompletedProcess:
        return subprocess.run(
            ["sh", self.script, client],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "CLAUDE_PROJECT_DIR": self.root},
        )

    def run_install(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["sh", self.script, "--install"],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ, "CLAUDE_PROJECT_DIR": self.root},
        )

    def test_a_launcher_that_stands_says_nothing(self):
        self.launcher("#!/bin/sh\nexit 0\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_a_launcher_that_cannot_run_offers_the_install(self):
        """런처가 못 서는 것은 uv 도 python 도 없다는 뜻이고, 그 침묵을 문단으로 바꾸는 자리다."""
        self.launcher("#!/bin/sh\nexit 127\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(HOOK_LAUNCHER, result.stdout)
        self.assertIn("--install", result.stdout)

    def test_cursor_gets_its_own_channel(self):
        """Cursor 의 컨텍스트 통로는 `additional_context` 하나다 — 평문은 그대로 버려진다."""
        self.launcher("#!/bin/sh\nexit 127\n")
        payload = json.loads(self.run_check("cursor").stdout)
        self.assertIn("additional_context", payload)
        self.assertIn("--install", payload["additional_context"])

    def test_root_comes_from_argv0_without_the_host_env(self):
        """Codex·Cursor 는 `CLAUDE_PROJECT_DIR` 을 안 준다 — 뿌리는 스크립트 자기 자리에서 나온다."""
        self.launcher("#!/bin/sh\nexit 127\n")
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        result = subprocess.run(
            ["sh", self.script, "codex"],
            cwd=os.path.expanduser("~"),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        self.assertIn("--install", result.stdout)

    def test_no_wiring_says_nothing(self):
        os.remove(os.path.join(self.root, _CC_WIRING))
        self.launcher("#!/bin/sh\nexit 127\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_legacy_wiring_is_read_past_the_allowlist(self):
        """옛 배선에서 허용목록의 맨 토큰을 인터프리터로 읽으면 고장난 배선이 초록으로 지나간다."""
        _write(os.path.join(self.root, _CC_WIRING), _LEGACY_WIRING % "/nonexistent/bin/uv")
        stdout = self.run_check().stdout
        self.assertIn("/nonexistent/bin/uv", stdout)
        self.assertNotIn("Bash(uv", stdout)

    def test_install_leaves_a_runtime_the_launcher_can_use(self):
        """수리의 결과는 한 줄로 판정된다 — 그 뒤 프리플라이트가 조용해야 한다."""
        if not shutil.which("uv"):
            self.skipTest("uv 가 없는 기계 — 이 시험은 망을 타지 않는다")
        self.launcher(hook_launcher_sh())
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(PYTHON_PIN, result.stdout)
        self.assertEqual(self.run_check().stdout, "")

    def test_install_leaves_a_bare_token_wiring_alone(self):
        """맨 토큰 배선은 PATH 가 푸는 값이다 — 파일 전체 치환이 허용목록까지 절대 경로로 바꾼다.

        그러면 모델이 안내문대로 친 `uv run --no-project python …` 이 허용목록과 어긋나 헤드리스에서
        자동 거부된다. Windows 스캐폴드가 실제로 이 형태를 만든다 (`platform.hook_python` 은 win32
        에서 런처를 안 쓰고 맨 토큰을 낸다)."""
        if not shutil.which("uv"):
            self.skipTest("uv 가 없는 기계 — 이 시험은 망을 타지 않는다")
        wiring = os.path.join(self.root, _CC_WIRING)
        _write(wiring, _LEGACY_WIRING % "uv")
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with open(wiring, encoding="utf-8") as handle:
            allow = json.load(handle)["permissions"]["allow"]
        self.assertIn("Bash(uv run --no-project python .claude/hooks/quest-log.py *)", allow)

    def test_install_repoints_legacy_wiring_to_this_machine(self):
        """옛 배선에는 아직 남의 기계 경로가 박혀 있다 — 수리는 그것을 여기 것으로 돌려놓는다."""
        uv = shutil.which("uv")
        if not uv:
            self.skipTest("uv 가 없는 기계 — 이 시험은 망을 타지 않는다")
        wiring = os.path.join(self.root, _CC_WIRING)
        _write(wiring, _LEGACY_WIRING % "/nonexistent/bin/uv")
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with open(wiring, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("/nonexistent/bin/uv", text)
        self.assertIn(uv, text)


@unittest.skipIf(_PWSH is None, "PowerShell 이 없는 기계")
class TestWindowsScript(unittest.TestCase):
    """PowerShell 쌍둥이를 실제로 돌린다 — 이 기계에 pwsh 가 있으면 목킹이 아니라 실행으로 잰다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.script = os.path.join(self.root, ".claude", "hooks", "env-setup.ps1")
        _write(self.script, env_setup_ps1())

    def wire(self, interpreter: str) -> None:
        _write(os.path.join(self.root, _CC_WIRING), _LEGACY_WIRING % interpreter)

    def run_check(self, client: str = "claude-code", cwd: str | None = None) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        return subprocess.run(
            [str(_PWSH), "-NoProfile", "-File", self.script, client],
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )

    def test_it_parses(self):
        """구문 오류는 조용히 죽는다 — 훅 계약이 fail-open 이라 화면에 아무것도 안 뜬다."""
        probe = (
            "$errs = $null; "
            "[System.Management.Automation.Language.Parser]::ParseFile('%s', [ref]$null, [ref]$errs) | Out-Null; "
            "if ($errs) { $errs | ForEach-Object { $_.Message }; exit 1 }" % self.script
        )
        result = subprocess.run(
            [str(_PWSH), "-NoProfile", "-Command", probe], capture_output=True, text=True, timeout=120
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_interpreter_offers_the_install(self):
        self.wire("/nonexistent/bin/uv")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/nonexistent/bin/uv", result.stdout)
        self.assertIn("-Install", result.stdout)

    def test_cursor_gets_its_own_channel(self):
        self.wire("/nonexistent/bin/uv")
        payload = json.loads(self.run_check("cursor").stdout)
        self.assertIn("additional_context", payload)
        self.assertIn("-Install", payload["additional_context"])

    def test_a_runnable_interpreter_says_nothing(self):
        self.wire(sys.executable)
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_no_wiring_says_nothing(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_root_comes_from_the_script_location(self):
        """호스트가 `CLAUDE_PROJECT_DIR` 을 안 줘도 자기 자리에서 뿌리를 찾는다."""
        self.wire("/nonexistent/bin/uv")
        result = self.run_check(cwd=os.path.expanduser("~"))
        self.assertIn("/nonexistent/bin/uv", result.stdout)

    def test_the_allowlist_line_is_not_read_as_the_interpreter(self):
        self.wire("/nonexistent/bin/uv")
        self.assertNotIn("Bash(uv", self.run_check().stdout)


class TestWindowsWiring(unittest.TestCase):
    """스캐폴드 시점 플랫폼이 러너를 정한다 — 한 기계에 프리플라이트 줄은 하나뿐이다."""

    @staticmethod
    def _preflight_lines(settings: dict) -> list:
        return [
            h["command"]
            for event in settings["hooks"].values()
            for entry in event
            for h in entry["hooks"]
            if "env-setup." in h["command"]
        ]

    def test_windows_wires_powershell_on_all_three_hosts(self):
        with mock.patch.object(asg_platform.sys, "platform", "win32"):
            with mock.patch.object(asg_platform.shutil, "which", side_effect=lambda c: "C:/bin/%s.exe" % c):
                claude = self._preflight_lines(json.loads(cc_settings()))
                cursor = json.loads(cursor_hooks_json())["hooks"]["sessionStart"][0]["command"]
                codex = [line for line in codex_config().splitlines() if "env-setup" in line]
        self.assertEqual(len(claude), 1, claude)
        self.assertIn("env-setup.ps1", claude[0])
        self.assertTrue(claude[0].startswith("powershell "), claude[0])
        self.assertIn("env-setup.ps1", cursor)
        self.assertEqual(len(codex), 1, codex)
        self.assertIn("env-setup.ps1", codex[0])

    def test_posix_wires_sh_and_only_one_line(self):
        claude = TestWindowsWiring._preflight_lines(json.loads(cc_settings()))
        self.assertEqual(len(claude), 1, claude)
        self.assertIn("env-setup.sh", claude[0])
        self.assertNotIn("env-setup.ps1", json.dumps(json.loads(cc_settings())))

    def test_both_bodies_ship_so_sync_can_switch_the_runner(self):
        """배선은 하나만 고르지만 본문 두 벌은 저장소에 있어야 반대편 기계에서 sync 가 살린다."""
        for client in ("claude-code", "codex", "cursor"):
            names = [os.path.basename(path) for path, _ in hook_files("H", client)]
            self.assertIn("env-setup.ps1", names, client)

    def test_doctor_skips_the_powershell_preflight_line(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(asg_platform.sys, "platform", "win32"):
                with mock.patch.object(asg_platform.shutil, "which", side_effect=lambda c: "C:/bin/%s.exe" % c):
                    body = cc_settings()
            _write(os.path.join(root, _CC_WIRING), body)
            argv = _wired_hook_argv(root) or []
        self.assertNotIn("env-setup", " ".join(argv))

    def test_the_script_avoids_powershell_7_only_syntax(self):
        """Windows 에 실려 오는 판은 5.1 이다 — `??` 하나면 파싱 단계에서 통째로 죽는다."""
        body = env_setup_ps1()
        for token in ("??", "?.", "-Parallel"):
            self.assertNotIn(token, body, token)

    def test_pin_and_placeholders(self):
        body = env_setup_ps1()
        self.assertIn("$PIN = '%s'" % PYTHON_PIN, body)
        leftovers = [w for w in body.split() if w.startswith("__") and w.endswith("__")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
