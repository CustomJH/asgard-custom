"""craft-gate 실 host E2E — **배포되는 훅 파일을 실제로 실행한다**.

실행: uv run pytest tests/test_craft_gate_e2e.py

`test_craft_gate_hook.py` 와 역할이 다르다. 저쪽은 훅 모듈을 import 하고 `subprocess.run` 을 목킹해서
합쳐진 판정의 **모양**을 고정한다. 그 방식으로는 절대 못 잡는 것이 넷 있고, 이 파일은 그 넷만 잡는다:

① **배포본이 실제로 도는가.** 훅은 사용자 저장소로 복사되어 stdlib 만으로 돌아야 한다. import 로
   부르는 시험은 엔진이 이미 `sys.path` 에 있는 프로세스에서 돌기 때문에, 훅이 실수로 엔진을
   import 해도 초록으로 통과한다 — 정작 사용자 저장소에서만 죽는다.
② **stdin/stdout 규약.** 호스트는 JSON 을 stdin 으로 먹이고 stdout 을 JSON 으로 읽는다. 목킹은
   이 경로를 통째로 건너뛴다.
③ **호스트별 차단 payload 모양.** cursor 는 `followup_message`, codex 는 `continue`/`stopReason`,
   claude 는 `decision`/`reason`. 셋이 다르고, 틀리면 차단이 조용히 무시된다.
④ **스캐폴드가 훅을 실제로 놓는가.** 판정기가 완벽해도 파일이 안 놓이면 게이트는 없는 것이다.

엔진을 가리는 방법은 `python -S` 다. site-packages 를 안 붙이므로 `import asgard` 가 실패하고,
stdlib 은 그대로 산다 — 사용자 저장소에서 훅이 처하는 상황과 같고, 인터프리터 경로를 찾아다니지
않아도 되어 어느 플랫폼에서나 같게 돈다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

# 두 게이트가 각각 하나씩 잡는 원문 — 합쳐진 판정이 출처를 잃지 않는지까지 한 번에 본다.
DEFECT = "def load(path):\n    try:\n        return open(path).read()\n    except Exception:\n        pass\n"
CLEAN = "def load(path):\n    with open(path) as handle:\n        return handle.read()\n"

# (스캐폴드 플래그, 훅 경로, argv, 세션 id, 차단 payload 에서 사유가 들어가는 칸)
HOSTS = (
    ("--cursor", os.path.join(".cursor", "hooks", "craft-gate.py"), ["cursor"], "cursor", "followup_message"),
    ("--codex", os.path.join(".codex", "hooks", "craft-gate.py"), ["codex"], "default", "stopReason"),
    ("--cc", os.path.join(".claude", "hooks", "craft-gate.py"), [], "s1", "reason"),
)


def _asgard_bin() -> str | None:
    """이 시험이 쓰는 CLI. 훅은 `shutil.which("asgard")` 로 찾으므로 PATH 에 얹어 준다."""
    candidate = os.path.join(os.path.dirname(sys.executable), "asgard")
    return candidate if os.path.exists(candidate) else shutil.which("asgard")


@unittest.skipIf(_asgard_bin() is None, "asgard CLI 가 PATH 에 없다 — 훅이 판정기를 못 부른다")
class ShippedHookRuns(unittest.TestCase):
    """스캐폴드 → 결함 작성 → 배포본 훅 실행 → 호스트 규약대로 차단. 한 줄도 목킹하지 않는다."""

    def setUp(self):
        self.bin = _asgard_bin()
        assert self.bin is not None
        self.root = tempfile.mkdtemp(prefix="craftgate-e2e-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self._git("init")
        self._git("config", "user.email", "t@t")
        self._git("config", "user.name", "t")

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, capture_output=True, check=False)

    def _scaffold(self, flag: str) -> None:
        done = subprocess.run(
            [self.bin, "init", flag, "--yes", "-q"], cwd=self.root, capture_output=True, text=True, timeout=180
        )
        self.assertEqual(0, done.returncode, done.stderr)

    def _write(self, rel: str, body: str) -> None:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)

    def _sentinel(self, sid: str, rels: list[str]) -> None:
        """훅이 판정하는 것은 **이 세션이 쓴 경로**다 — 그 목록을 write_sentinel 과 같은 자리에 둔다."""
        self._write(os.path.join(".asgard", "state", f"writes-{sid}.json"), json.dumps(rels))

    def _run_hook(self, hook: str, argv: list[str], payload: dict) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PATH"] = os.path.dirname(self.bin) + os.pathsep + env.get("PATH", "")
        env.pop("CLAUDE_PROJECT_DIR", None)  # payload 의 cwd 로만 뿌리를 정하게 한다
        return subprocess.run(
            # `-S` = site-packages 없이. 엔진을 import 하면 여기서 죽는다 (배포본의 계약).
            [sys.executable, "-S", os.path.join(self.root, hook), *argv],
            input=json.dumps(payload),
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )

    def test_every_host_blocks_a_real_regression_through_its_own_protocol(self):
        for flag, hook, argv, sid, field in HOSTS:
            with self.subTest(host=flag):
                self.setUp()
                self._scaffold(flag)
                self.assertTrue(os.path.exists(os.path.join(self.root, hook)), f"{hook} 이 스캐폴드되지 않았다")
                self._write("src/leak.py", DEFECT)
                self._sentinel(sid, ["src/leak.py"])
                done = self._run_hook(hook, argv, {"cwd": self.root, "session_id": sid})

                self.assertEqual(0, done.returncode, done.stderr)  # 훅은 언제나 0 — 차단은 payload 로 말한다
                self.assertNotIn("ModuleNotFoundError", done.stderr)  # stdlib 전용 계약
                payload = json.loads(done.stdout)
                self.assertIn(field, payload, f"{flag} 의 차단 칸이 없다 — 호스트가 차단을 무시한다")
                reason = str(payload[field])
                self.assertIn("craft-gate", reason)
                self.assertIn("[craft/unclosed-acquire]", reason)  # 형상 게이트
                self.assertIn("[thor gate/swallowed-exception]", reason)  # 정확성 게이트
                if flag == "--codex":
                    self.assertIs(False, payload.get("continue"))
                if flag == "--cc":
                    self.assertEqual("block", payload.get("decision"))

    def test_clean_code_is_not_blocked(self):
        """막는 쪽만 시험하면 훅을 '항상 차단'으로 바꿔도 초록이다 — 음성 대조군이 짝으로 있어야 한다."""
        self._scaffold("--cursor")
        self._write("src/ok.py", CLEAN)
        self._sentinel("cursor", ["src/ok.py"])
        done = self._run_hook(HOSTS[0][1], ["cursor"], {"cwd": self.root, "session_id": "cursor"})
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual("", done.stdout.strip())

    def test_a_session_that_wrote_nothing_is_not_judged(self):
        """판정 대상은 이 세션의 쓰기다 — 센티넬이 없으면 대상이 없고, 없는 것은 통과다."""
        self._scaffold("--cursor")
        self._write("src/leak.py", DEFECT)  # 결함은 있지만 이 세션이 쓴 것이 아니다
        done = self._run_hook(HOSTS[0][1], ["cursor"], {"cwd": self.root, "session_id": "cursor"})
        self.assertEqual("", done.stdout.strip())

    def test_the_shipped_hook_never_imports_the_engine(self):
        """`-S` 로 도는 것을 봤더라도 형상으로 한 번 더 못박는다.

        다음 사람이 무심코 `from ..craft import judge` 를 넣으면 이 저장소 안에서는 계속 초록이고,
        사용자 저장소에서만 죽는다 — 그 종류의 결함은 실행 시험만으로 못 막는다.
        """
        from asgard.hooks import craft_gate

        with open(craft_gate.__file__, encoding="utf-8") as handle:
            body = handle.read()
        for forbidden in ("import asgard", "from asgard", "from .", "from .."):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body)

    def test_the_scaffolded_copy_is_the_engine_source_byte_for_byte(self):
        """복사 배포본이 원본과 어긋나면 판정이 두 벌이 되고, 두 벌은 곧 다르게 판정한다.

        훅 표가 세 호스트에 다 있는지는 `test_mode_parity` 가 본다. 여기서만 볼 수 있는 것은
        **디스크에 실제로 놓인 바이트**다 — 절단·인코딩 변환·개행 변환은 표를 봐서는 안 보인다.
        """
        from asgard.hooks import craft_gate

        with open(craft_gate.__file__, "rb") as handle:
            origin = handle.read()
        for flag, hook, _argv, _sid, _field in HOSTS:
            with self.subTest(host=flag):
                self.setUp()
                self._scaffold(flag)
                with open(os.path.join(self.root, hook), "rb") as handle:
                    self.assertEqual(origin, handle.read())


if __name__ == "__main__":
    unittest.main()
