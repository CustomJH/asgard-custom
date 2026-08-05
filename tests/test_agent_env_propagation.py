"""자식 프로세스가 어느 에이전트로 도는가 — 조용한 교차 오염을 막는 계약.

`profiles.scoped()`는 **contextvar**다. 그래서 자식 프로세스에 자동으로 안 따라간다. 스코프 안에서
`env=` 없이 자식을 띄우면 그 자식은 끈끈한 활성 에이전트로 떨어진다 — 에이전트 A로 돌던 세션이
B의 홈에 쓴다. hermes 이슈 18594가 정확히 이 사고였고, 발견까지 며칠이 걸린 종류다.

`profiles.subprocess_env()`가 그 전파의 정본이다. 이 파일은 **어느 자리가 그걸 쓰고 어느 자리가
안 쓰는지**를 못 박는다. 안 쓰는 자리도 시험에 적는 이유는, 그것이 빠뜨림이 아니라 판단이었음을
다음 사람이 알아야 하기 때문이다.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from asgard import profiles


class EnvPropagationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        env = {key: value for key, value in os.environ.items() if not key.startswith("ASGARD_")}
        env["HOME"] = self._tmp.name
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)
        profiles.create("alpha")
        profiles.create("beta")
        profiles.set_active("beta")  # 끈끈한 활성은 beta — 전파가 없으면 여기로 샌다

    # ── 기억 자동 통합 — 가장 날카로운 자리 ────────────────────────────────────

    def test_norn_auto_child_carries_the_scoped_agent(self) -> None:
        """턴마다 도는 기억 쓰기 자식이 그 세션의 에이전트로 돈다."""
        from asgard.memory import norn

        with mock.patch("subprocess.Popen") as popen:
            with profiles.scoped("alpha"):
                norn._spawn_auto(self._tmp.name)
        env = popen.call_args.kwargs["env"]
        self.assertEqual(env["ASGARD_PROFILE"], "alpha")
        self.assertEqual(env["ASGARD_HOME"], profiles.profile_dir("alpha"))

    def test_norn_auto_child_is_unchanged_without_a_scope(self) -> None:
        """스코프가 없으면 끈끈한 활성 그대로 — 에이전트를 안 쓰는 설치에 회귀가 없다."""
        from asgard.memory import norn

        with mock.patch("subprocess.Popen") as popen:
            norn._spawn_auto(self._tmp.name)
        self.assertEqual(popen.call_args.kwargs["env"]["ASGARD_PROFILE"], "beta")

    def test_an_explicit_home_survives(self) -> None:
        """컨테이너 흐름 무파손 — ASGARD_HOME이 서 있으면 그것이 이긴다."""
        from asgard.memory import norn

        container = os.path.join(self._tmp.name, "agent-data")
        os.makedirs(container, exist_ok=True)
        with mock.patch.dict(os.environ, {"ASGARD_HOME": container}):
            with mock.patch("subprocess.Popen") as popen:
                norn._spawn_auto(self._tmp.name)
        self.assertEqual(popen.call_args.kwargs["env"]["ASGARD_HOME"], container)

    # ── 가드 훅 — 아스가르드 자신이라 전파한다 ──────────────────────────────────

    def test_guard_hook_runs_as_the_scoped_agent(self) -> None:
        from asgard.agent import tools

        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            with profiles.scoped("alpha"):
                tools._hook_guard(self._tmp.name, "asgard.hooks.nothing", {})
        self.assertEqual(run.call_args.kwargs["env"]["ASGARD_PROFILE"], "alpha")

    # ── bash 도구 — 에이전트를 대신해 도는 명령이라 전파한다 ────────────────────

    def test_bash_tool_runs_as_the_scoped_agent(self) -> None:
        """도구 안에서 `asgard …`를 부르면 같은 에이전트로 가야 한다."""
        import io

        from asgard.agent import tools

        with mock.patch("subprocess.Popen") as popen:
            # 펌프 스레드가 실제로 읽으므로 파일 같은 것을 줘야 한다 — None이면 스레드가
            # 예외를 뱉고 시험이 경고로 시끄러워진다(단언과는 무관하지만 다음 사람이 헷갈린다).
            popen.return_value = mock.Mock(stdout=io.StringIO(""), stderr=io.StringIO(""), returncode=0)
            with profiles.scoped("alpha"), mock.patch.object(tools, "validate_bash_command", return_value=None):
                try:
                    tools.run_bash(self._tmp.name, {"command": "true"})
                except Exception:
                    pass  # 펌프 스레드까지는 안 간다 — 여기서 재는 것은 env 하나다
        self.assertIsNotNone(popen.call_args, "run_bash가 Popen까지 안 갔어요")
        self.assertEqual(popen.call_args.kwargs["env"]["ASGARD_PROFILE"], "alpha")

    # ── 전파하지 **않기로** 한 자리 ─────────────────────────────────────────────

    def test_the_document_converter_is_deliberately_not_scoped(self) -> None:
        """한글 문서 변환 스크립트는 에이전트 상태를 안 읽는다 — 전파할 것이 없다.

        이 시험은 기능이 아니라 **판단**을 지킨다. 빠뜨린 것으로 보고 나중에 누가 env를 얹으면,
        읽지도 않는 값을 넘기는 자리가 하나 늘 뿐이고 "어디까지 전파하는가"의 경계가 흐려진다.
        경계는 하나다: **자식이 아스가르드의 상태를 읽는가.**"""
        import inspect

        from asgard.agent import tools

        source = inspect.getsource(tools.knowledge)
        marker = source.index("convert_hwp.py")
        window = source[marker : marker + 700]
        self.assertNotIn("subprocess_env", window)


if __name__ == "__main__":
    unittest.main()
