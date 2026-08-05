"""세션 정본 — 에이전트가 키 안에 있는가, 그리고 사다리 순서가 지켜지는가.

이 레인이 막는 결함은 하나다: **정체가 프로세스 주변 상태에 있으면 세션이 서로를 덮어쓴다.**
그래서 여기서 제일 길게 보는 것도 그 하나다 — 에이전트가 다르면 키가 다른가, explicit 이
`ASGARD_PROFILE` 보다 우선하는가, 그리고 실제 Heimdall 세션 좌표가 에이전트를 포함하는가.

나머지 절반은 fail-open 이다. 배치 해석이 실패해도 세션은 열려야 한다 — 정체 해석의 결함이
시동을 막으면 이 계층은 순손실이다.

실행: uv run pytest tests/test_sessions.py
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from asgard import profiles, sessions, swarm


def _clean_env(home: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ASGARD_")}
    env["HOME"] = home
    env["ASGARD_MEMORY_SEMANTIC"] = "off"  # 임베딩 모델 다운로드 밀폐 (conftest와 같은 규율)
    return env


class SessionBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self._env = mock.patch.dict(os.environ, _clean_env(self.home), clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)

    def project(self, name: str = "proj") -> str:
        root = os.path.join(self.home, name)
        os.makedirs(os.path.join(root, ".asgard"), exist_ok=True)
        return root


class TestKeyShape(SessionBase):
    def test_the_key_names_the_agent_and_round_trips(self):
        key = sessions.session_key("loki-qa", "native")
        self.assertEqual(key, "agent:loki-qa:native")
        self.assertEqual(sessions.parse_key(key), {"agent": "loki-qa", "scope": "native", "suffix": ""})

    def test_a_suffix_is_a_fourth_slot_not_a_new_format(self):
        key = sessions.session_key("loki-qa", "native", "ab12")
        self.assertEqual(key, "agent:loki-qa:native:ab12")
        self.assertEqual(sessions.parse_key(key), {"agent": "loki-qa", "scope": "native", "suffix": "ab12"})

    def test_the_default_scope_is_main(self):
        self.assertEqual(sessions.session_key("qa"), "agent:qa:main")

    def test_different_agents_never_share_a_key(self):
        """같은 scope 라도 에이전트가 다르면 키가 다르다 — 두 세션의 기록이 안 겹치는 근거."""
        a, b = sessions.session_key("arch", "main"), sessions.session_key("qa", "main")
        self.assertNotEqual(a, b)
        self.assertEqual(sessions.parse_key(a)["agent"], "arch")
        self.assertEqual(sessions.parse_key(b)["agent"], "qa")

    def test_a_separator_inside_a_slot_cannot_break_the_round_trip(self):
        """scope 에 `:` 가 남으면 칸 경계가 어긋나 왕복이 깨진다 — 치환이 왕복의 전제다."""
        key = sessions.session_key("qa", "a:b", "c:d")
        self.assertEqual(sessions.parse_key(key), {"agent": "qa", "scope": "a-b", "suffix": "c-d"})

    def test_an_unusable_name_becomes_default_not_a_made_up_id(self):
        """지어낸 이름으로 키를 만들면 그 이름으로 기록이 쌓이고 되짚을 홈이 없다."""
        self.assertEqual(sessions.session_key("Not A Name!"), "agent:default:main")
        self.assertEqual(sessions.session_key(""), "agent:default:main")

    def test_a_malformed_key_reads_as_nothing(self):
        for bad in ("", "native-abc", "agent:qa", "session:qa:main", "agent::main", "agent:Q A:main"):
            self.assertEqual(sessions.parse_key(bad), {}, bad)


class TestLadder(SessionBase):
    """explicit > 프로젝트 배치 > 끈끈한 활성 — 셋을 다 세워 놓고 순서를 확인한다."""

    def _three(self) -> str:
        root = self.project()
        profiles.create("chosen")
        profiles.create("placed")
        profiles.create("stuck")
        swarm.bind(root, "placed", mode="native")
        profiles.set_active("stuck")
        return root

    def test_explicit_wins_over_binding_and_sticky(self):
        root = self._three()
        self.assertEqual(sessions.resolve_agent(root, "chosen", mode="native"), "chosen")

    def test_binding_wins_when_nothing_is_chosen(self):
        root = self._three()
        self.assertEqual(sessions.resolve_agent(root, mode="native"), "placed")

    def test_sticky_answers_when_there_is_no_binding(self):
        root = self._three()
        swarm.unbind(root, mode="native")
        self.assertEqual(sessions.resolve_agent(root, mode="native"), "stuck")

    def test_a_narrow_role_placement_beats_the_mode_placement(self):
        root = self._three()
        profiles.create("verifier-agent")
        swarm.bind(root, "verifier-agent", role="verifier")
        self.assertEqual(sessions.resolve_agent(root, mode="native", role="verifier"), "verifier-agent")
        self.assertEqual(sessions.resolve_agent(root, mode="native", role="worker"), "placed")

    def test_an_uninstalled_explicit_name_drops_to_the_next_rung(self):
        """없는 이름으로 세션을 열면 홈도 기억도 없다 — 부른 쪽은 source 로 그 사실을 판정한다."""
        root = self._three()
        self.assertEqual(sessions.resolve_agent(root, "ghost", mode="native"), "placed")
        self.assertEqual(sessions.describe(root, "ghost", mode="native")["source"], "binding")

    def test_a_plain_install_answers_default(self):
        root = self.project()
        self.assertEqual(sessions.resolve_agent(root), profiles.DEFAULT)


class TestDescribe(SessionBase):
    def test_the_source_says_which_rung_decided(self):
        root = self.project()
        profiles.create("chosen")
        profiles.create("placed")
        profiles.create("stuck")

        profiles.set_active("stuck")
        self.assertEqual(sessions.describe(root, mode="native")["source"], "sticky")

        swarm.bind(root, "placed", mode="native")
        self.assertEqual(
            sessions.describe(root, mode="native"),
            {
                "agent": "placed",
                "source": "binding",
                "key": "agent:placed:native",
            },
        )

        self.assertEqual(
            sessions.describe(root, "chosen", mode="native"),
            {
                "agent": "chosen",
                "source": "explicit",
                "key": "agent:chosen:native",
            },
        )

    def test_the_keys_scope_takes_the_narrow_declaration(self):
        root = self.project()
        profiles.create("qa")
        self.assertEqual(sessions.describe(root, "qa", mode="native", role="verifier")["key"], "agent:qa:verifier")
        self.assertEqual(sessions.describe(root, "qa", mode="native")["key"], "agent:qa:native")
        self.assertEqual(sessions.describe(root, "qa")["key"], "agent:qa:main")


class TestEnvIsNotTheSourceOfTruth(SessionBase):
    def test_explicit_ignores_the_profile_environment_variable(self):
        """`ASGARD_PROFILE` 은 아무것도 안 고른 세션의 출발값이지 정체의 근거가 아니다."""
        root = self.project()
        profiles.create("chosen")
        profiles.create("from-env")
        os.environ["ASGARD_PROFILE"] = "from-env"

        self.assertEqual(profiles.active(), "from-env")  # 프로세스 주변 상태는 그대로다
        self.assertEqual(sessions.resolve_agent(root, "chosen"), "chosen")
        self.assertEqual(sessions.describe(root, "chosen")["key"], "agent:chosen:main")

    def test_without_an_explicit_choice_the_environment_is_the_bootstrap(self):
        """env 를 무시하는 것이 아니라 **아래 칸**에 둔다 — 사다리의 3번이다."""
        root = self.project()
        profiles.create("from-env")
        os.environ["ASGARD_PROFILE"] = "from-env"
        self.assertEqual(
            sessions.describe(root),
            {
                "agent": "from-env",
                "source": "sticky",
                "key": "agent:from-env:main",
            },
        )

    def test_an_unnamed_home_folds_to_default(self):
        """`custom` 은 이름이 아니라 표지라 키에 적히면 다른 기계에서 되짚을 자리가 없다."""
        root = self.project()
        os.environ["ASGARD_HOME"] = os.path.join(self.home, "somewhere-else")
        self.assertEqual(profiles.active(), "custom")
        self.assertEqual(sessions.resolve_agent(root), profiles.DEFAULT)


class TestFailOpen(SessionBase):
    def test_a_broken_binding_does_not_raise(self):
        root = self.project()
        profiles.create("stuck")
        profiles.set_active("stuck")
        with mock.patch.object(sessions, "binding", side_effect=RuntimeError("설정 파손")):
            self.assertEqual(sessions.resolve_agent(root, mode="native"), "stuck")
            self.assertEqual(sessions.describe(root, mode="native")["source"], "sticky")


class TestHeimdallSessionId(SessionBase):
    """세션 좌표가 에이전트를 포함하는가 — 진짜 Heimdall 을 세워서 잰다.

    `AgentSession` 생성과 클라이언트 조립만 대역으로 갈아끼운다 (tests/test_profiles.py 의
    TestNativeCompositionEndToEnd 와 같은 패턴). 모델 호출은 0이다."""

    def _heimdall(self, root: str, **kwargs):
        from asgard.agent.heimdall import core as core_mod
        from asgard.providers import PROVIDERS, ResolvedProvider

        self.addCleanup(mock.patch.stopall)
        mock.patch.object(core_mod.sessions, "AgentSession", lambda *a, **k: object()).start()
        mock.patch.object(core_mod.sessions, "make_client", lambda _rp: object()).start()
        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="claude-x", api_key="k")
        return core_mod.Heimdall(rp, root, on_text=lambda _s: None, **kwargs)

    def test_the_session_id_carries_the_placed_agent(self):
        root = self.project()
        profiles.create("loki-qa")
        swarm.bind(root, "loki-qa", mode="native")

        read = sessions.parse_key(self._heimdall(root)._memory_session_id)
        self.assertEqual(read["agent"], "loki-qa")
        self.assertEqual(read["scope"], "native")
        self.assertTrue(read["suffix"], "세션마다 다른 꼬리표가 있어야 두 세션이 안 겹친다")

    def test_two_agents_open_two_different_session_ids(self):
        root = self.project()
        profiles.create("arch")
        profiles.create("qa")
        swarm.bind(root, "arch", mode="native")
        first = self._heimdall(root)._memory_session_id
        swarm.bind(root, "qa", mode="native")
        second = self._heimdall(root)._memory_session_id

        self.assertEqual(sessions.parse_key(first)["agent"], "arch")
        self.assertEqual(sessions.parse_key(second)["agent"], "qa")

    def test_an_explicit_agent_beats_the_project_placement(self):
        root = self.project()
        profiles.create("arch")
        profiles.create("qa")
        swarm.bind(root, "arch", mode="native")
        hd = self._heimdall(root, agent="qa")
        self.assertEqual(hd._session_agent, "qa")
        self.assertEqual(sessions.parse_key(hd._memory_session_id)["agent"], "qa")

    def test_a_plain_install_still_opens_a_readable_key(self):
        read = sessions.parse_key(self._heimdall(self.project())._memory_session_id)
        self.assertEqual(read["agent"], profiles.DEFAULT)

    def test_a_broken_placement_still_opens_the_session(self):
        """배치 해석이 터져도 세션은 열린다 (fail-open 회귀) — 좌표는 default 로 떨어진다."""
        from asgard.agent.heimdall import core as core_mod

        root = self.project()
        profiles.create("loki-qa")
        swarm.bind(root, "loki-qa", mode="native")
        with mock.patch.object(core_mod.recall, "_resolve_agent", side_effect=RuntimeError("배치 파손")):
            hd = self._heimdall(root)
        self.assertEqual(hd._session_agent, "")
        self.assertEqual(sessions.parse_key(hd._memory_session_id)["agent"], profiles.DEFAULT)


if __name__ == "__main__":
    unittest.main()
