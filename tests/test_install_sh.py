"""install.sh 불변식 — 이 스크립트는 두 가지를 절대 하면 안 된다.

실행: uv run pytest tests/test_install_sh.py

정식 설치 경로는 `curl -fsSL … | bash` 다. 스트림으로 실행되면 스크립트에 대응하는 **파일이
없다** — `BASH_SOURCE` 는 비고 `$0` 는 "bash" 다. 그래서 파일로 실행할 때만 성립하는 가정
두 개가 여기서 무너졌고, 둘 다 사용자에게 조용히 잘못된 결과를 줬다:

  · `dirname "${BASH_SOURCE[0]:-$0}"` 는 "." 로 접혀 **사용자가 서 있던 디렉터리**가 됐다.
    거기 pyproject.toml 이 있으면 그 자리를 asgard 체크아웃으로 오인해, 남의 파이썬 프로젝트를
    `uv tool install` 했다.
  · `asgard --version 2>/dev/null || echo '?'` 는 CLI 가 아예 안 돌아도 초록 ✔ 와 `v?` 를 찍었다.
    설치가 깨졌는데 화면은 성공으로 읽혔다.

아래 검사는 전부 install.sh 를 **실제로 실행**해서 본다 (uv·curl·asgard·node 는 스텁으로
갈아끼우고 HOME 도 임시 디렉터리로 돌려, 이 호스트에는 아무것도 설치되지 않는다).
`uv tool install` 이 받은 인자를 파일에 적어 두고, 그 한 줄로 "무엇을 설치하려 했는가"를 잰다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_SH = os.path.join(ROOT, "install.sh")

# uv 스텁 — `tool install` 의 인자만 로그에 남기고 나머지는 성공으로 흘린다.
STUB_UV = """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then echo "uv 0.0.0-stub"; exit 0; fi
if [ "$1" = "tool" ] && [ "$2" = "install" ]; then
  shift 2; printf '%s\\n' "$*" >> "$ASGARD_TEST_LOG"
fi
exit 0
"""

# curl 스텁 — 최신 릴리스 태그 조회와 __init__.py 버전 조회만 답한다 (네트워크를 타지 않는다).
STUB_CURL = """#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in
    *releases/latest) echo "https://github.com/CustomJH/asgard-custom/releases/tag/v9.9.9"; exit 0 ;;
    *__init__.py) echo '__version__ = "9.9.9"'; exit 0 ;;
  esac
done
exit 0
"""

# asgard 스텁 — ASGARD_TEST_VERSION_FAIL 이면 `--version` 이 깨진 설치처럼 실패한다.
STUB_ASGARD = """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  if [ -n "${ASGARD_TEST_VERSION_FAIL:-}" ]; then
    echo "ImportError: cannot import name 'app'" >&2; exit 1
  fi
  echo "9.9.9"; exit 0
fi
exit 0
"""

WHEEL = "asgard-9.9.9-py3-none-any.whl"


class InstallShHarness(unittest.TestCase):
    """install.sh 를 스텁 PATH 위에서 돌리는 공용 하니스."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="asgard-install-sh-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = os.path.join(self.tmp, "bin")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.bin)
        os.makedirs(self.home)
        for name, body in (("uv", STUB_UV), ("curl", STUB_CURL), ("asgard", STUB_ASGARD)):
            path = os.path.join(self.bin, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            os.chmod(path, 0o755)
        self.log = os.path.join(self.tmp, "uv-tool-install.log")

    def _decoy(self, name: str = "victim") -> str:
        """사용자가 서 있을 법한 **남의** 파이썬 프로젝트. asgard 가 아니다."""
        d = os.path.join(self.tmp, "decoy")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "pyproject.toml"), "w", encoding="utf-8") as fh:
            fh.write(f'[project]\nname = "{name}"\nversion = "0.1.0"\n')
        return d

    def _env(self, **extra: str) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "PATH": self.bin + os.pathsep + "/usr/bin" + os.pathsep + "/bin",
                "HOME": self.home,
                "ASGARD_TEST_LOG": self.log,
                "NO_COLOR": "1",
                "ASGARD_NO_IMAGE": "1",
            }
        )
        for key in ("ASGARD_VERSION", "ASGARD_INSTALL_SPEC", "ASGARD_INSTALL_LOCAL"):
            env.pop(key, None)
        env.update(extra)
        return env

    def _run_streamed(self, cwd: str, **extra: str) -> subprocess.CompletedProcess[str]:
        """`curl … | bash` 와 같은 모양 — 스크립트를 stdin 으로 먹이고 $0 는 "bash" 가 된다.

        argv[0] 을 그대로 두려면 셸에게 파이프를 시켜야 한다. `bash install.sh` 로 부르면
        $0 가 경로가 되어 재현이 안 된다.
        """
        return subprocess.run(
            ["/bin/sh", "-c", f'cat "{INSTALL_SH}" | bash'],
            cwd=cwd,
            env=self._env(**extra),
            capture_output=True,
            text=True,
            timeout=300,
        )

    def _run_file(self, script: str, cwd: str, **extra: str) -> subprocess.CompletedProcess[str]:
        """파일로 실행 — 개발자가 체크아웃 안에서 `bash install.sh` 하는 경로."""
        return subprocess.run(
            ["/bin/bash", script],
            cwd=cwd,
            env=self._env(**extra),
            capture_output=True,
            text=True,
            timeout=300,
        )

    def _installed_spec(self) -> str:
        """`uv tool install` 이 실제로 받은 인자 한 줄. 아무것도 안 불렸으면 빈 문자열."""
        if not os.path.exists(self.log):
            return ""
        with open(self.log, encoding="utf-8") as fh:
            return fh.read().strip()


class InstallShSyntax(InstallShHarness):
    def test_parses(self) -> None:
        proc = subprocess.run(["/bin/bash", "-n", INSTALL_SH], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"install.sh does not parse:\n{proc.stderr}")

    def test_script_dir_is_not_guessed_from_argv0(self) -> None:
        """`${BASH_SOURCE[0]:-$0}` 는 스트림 실행에서 "bash" 로 접힌다 — 되살아나면 안 된다.

        (주석은 뺀다 — script_dir() 의 설명이 지워진 그 식을 인용하고 있고, 그건 기록이다.)
        """
        with open(INSTALL_SH, encoding="utf-8") as fh:
            code = [ln for ln in fh.read().splitlines() if not ln.lstrip().startswith("#")]
        hits = [ln.strip() for ln in code if "BASH_SOURCE[0]:-$0" in ln]
        self.assertEqual(
            hits,
            [],
            "the script directory is being guessed from $0 again; under curl|bash that is the "
            f"user's cwd, not a checkout: {hits}",
        )


class InstallShSourceResolution(InstallShHarness):
    """ "무엇을 설치하는가" — 판정이 틀리면 사용자는 asgard 아닌 것을 받는다."""

    def test_streamed_run_ignores_the_directory_the_user_stands_in(self) -> None:
        """H4 회귀: 남의 프로젝트 안에서 curl|bash 해도 그 프로젝트를 설치하지 않는다."""
        decoy = self._decoy()
        proc = self._run_streamed(decoy)
        self.assertEqual(proc.returncode, 0, f"install failed:\n{proc.stdout}\n{proc.stderr}")
        spec = self._installed_spec()
        self.assertNotIn(decoy, spec, f"install.sh tried to install the user's own project: {spec}")
        self.assertIn(WHEEL, spec, f"expected the release wheel, got: {spec}")

    def test_a_foreign_pyproject_next_to_the_script_is_not_a_checkout(self) -> None:
        """H4 두 번째 가드: 스크립트 옆에 pyproject.toml 이 있어도 이름이 asgard 여야 한다."""
        decoy = self._decoy()
        copied = os.path.join(decoy, "install.sh")
        shutil.copy2(INSTALL_SH, copied)
        proc = self._run_file(copied, decoy)
        self.assertEqual(proc.returncode, 0, f"install failed:\n{proc.stdout}\n{proc.stderr}")
        spec = self._installed_spec()
        self.assertNotIn(decoy, spec, f"a pyproject named 'victim' was taken for asgard: {spec}")
        self.assertIn(WHEEL, spec, f"expected the release wheel, got: {spec}")

    def test_the_real_checkout_is_still_installed_from_source(self) -> None:
        """가드가 개발 경로를 막아서는 안 된다 — 진짜 체크아웃은 그대로 소스 설치."""
        proc = self._run_file(INSTALL_SH, ROOT)
        self.assertEqual(proc.returncode, 0, f"install failed:\n{proc.stdout}\n{proc.stderr}")
        spec = self._installed_spec()
        self.assertIn(ROOT, spec, f"the asgard checkout was not recognised: {spec}")
        self.assertIn("--refresh-package", spec, f"path installs need --refresh-package: {spec}")

    def test_explicit_opt_in_installs_the_current_directory(self) -> None:
        """스트림 실행에서도 사용자가 명시하면(ASGARD_INSTALL_LOCAL=1) 그 자리를 설치한다."""
        decoy = self._decoy()
        proc = self._run_streamed(decoy, ASGARD_INSTALL_LOCAL="1")
        self.assertEqual(proc.returncode, 0, f"install failed:\n{proc.stdout}\n{proc.stderr}")
        self.assertIn(decoy, self._installed_spec())

    def test_explicit_opt_in_with_no_project_is_a_failure_not_a_silent_fallback(self) -> None:
        """명시했는데 거기 프로젝트가 없으면, 조용히 휠로 새지 말고 이유를 대고 멈춘다."""
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty, exist_ok=True)
        proc = self._run_streamed(empty, ASGARD_INSTALL_LOCAL="1")
        self.assertNotEqual(proc.returncode, 0, f"expected a failure:\n{proc.stdout}")
        self.assertIn("ASGARD_INSTALL_LOCAL", proc.stderr)
        self.assertEqual(self._installed_spec(), "", "nothing should have been installed")


class InstallShVerify(InstallShHarness):
    """ "설치가 됐는가" — 여기서 거짓말하면 사용자는 깨진 설치를 성공으로 읽는다."""

    def test_a_broken_cli_fails_the_install(self) -> None:
        """H5 회귀: `asgard --version` 이 실패하면 ✔ 가 아니라 실패다."""
        proc = self._run_streamed(self.tmp, ASGARD_TEST_VERSION_FAIL="1")
        self.assertNotEqual(proc.returncode, 0, f"a broken CLI reported success:\n{proc.stdout}")
        combined = proc.stdout + proc.stderr
        self.assertIn("does not run yet", combined, f"no reason was given:\n{combined}")
        self.assertNotIn("v?", combined, f"the unknown version was still printed as a result:\n{combined}")
        self.assertNotIn("✔ installed", proc.stdout, "the closing success banner was printed anyway")

    def test_a_broken_cli_surfaces_the_reason_and_the_next_step(self) -> None:
        """실패 화면은 install.ps1 과 같은 것을 준다 — 원문 로그 + 다음에 할 일."""
        proc = self._run_streamed(self.tmp, ASGARD_TEST_VERSION_FAIL="1")
        combined = proc.stdout + proc.stderr
        self.assertIn("ImportError", combined, "the CLI's own output was swallowed")
        self.assertIn("uv tool update-shell", combined, "no recovery hint")

    def test_a_working_cli_reports_its_real_version(self) -> None:
        proc = self._run_streamed(self.tmp)
        self.assertEqual(proc.returncode, 0, f"install failed:\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("asgard v9.9.9", proc.stdout, f"the verified version is missing:\n{proc.stdout}")


class InstallShInstallsOnlyAsgard(InstallShHarness):
    """설치기는 asgard 하나만 깐다 — 사용자가 안 시킨 도구는 안 깐다.

    목록이 아니라 **횟수**로 재는 이유가 있다. 26-08-17 에 실행 표면 러너(`rust-just`)를 여기서
    같이 깔았고, 그 도구를 쓸지는 저장소가 고를 일이라 뺐다. 이름 하나를 금지 목록에 적으면
    다음에 추가되는 이름은 그 목록에 없다 — 재는 축은 "무엇을 안 깔았나"가 아니라
    "몇 개를 깔았나"다."""

    def test_uv_tool_install_is_called_exactly_once(self) -> None:
        proc = self._run_streamed(self.tmp)
        self.assertEqual(proc.returncode, 0, f"install failed:\n{proc.stdout}\n{proc.stderr}")
        calls = [line for line in self._installed_spec().splitlines() if line.strip()]
        self.assertEqual(len(calls), 1, f"the installer installed more than asgard: {calls}")
        self.assertIn("asgard", calls[0], f"the one install was not asgard: {calls[0]}")


if __name__ == "__main__":
    unittest.main()
