"""에인헤랴르 — 여러 에이전트가 한 기계에서 서로를 안 밟는가.

이 레인의 약속은 하나로 압축된다: **한 에이전트가 쓴 것을 다른 에이전트가 못 본다.**
그래서 여기서 제일 길게 보는 것도 그 하나다 — 1차 기억·세션·이력·스킬·설정이 각각 갈리는지,
그리고 갈렸다고 **믿게 만드는 우회로**가 없는지 (설정 한 줄로 격리가 풀리는 자리가 있었다:
뿌리의 `memory.directory` 상속. 그 자리를 따로 세워 둔다).

나머지 절반은 반대 방향이다: 프로파일을 안 쓰는 사람에게 이 계층이 **보이지 않아야** 한다.
기존 설치는 그대로 default 이고, 경로도 프롬프트도 예전과 같아야 한다.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from asgard import profiles, settings, swarm


def _clean_env(home: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ASGARD_")}
    env["HOME"] = home
    env["ASGARD_MEMORY_SEMANTIC"] = "off"  # 임베딩 모델 다운로드 밀폐 (conftest 와 같은 규율)
    return env


class ProfileBase(unittest.TestCase):
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


class TestHomeLadder(ProfileBase):
    def test_default_is_the_root_itself(self):
        """기존 설치 = default. 프로파일을 안 만든 사람에게 경로가 하나도 안 바뀐다."""
        self.assertEqual(profiles.root(), os.path.join(self.home, ".asgard"))
        self.assertEqual(profiles.home(), profiles.root())
        self.assertEqual(profiles.active(), "default")

    def test_ladder_order(self):
        """스코프 > ASGARD_HOME > ASGARD_PROFILE > 끈끈한 활성 > default."""
        profiles.create("alpha")
        profiles.create("beta")
        profiles.set_active("alpha")
        self.assertEqual(profiles.active(), "alpha")  # 끈끈한 활성

        os.environ["ASGARD_PROFILE"] = "beta"
        self.assertEqual(profiles.active(), "beta")  # env 이름이 끈끈한 것을 이긴다

        os.environ["ASGARD_HOME"] = profiles.profile_dir("alpha")
        self.assertEqual(profiles.active(), "alpha")  # 경로가 이름을 이긴다

        with profiles.scoped("beta"):
            self.assertEqual(profiles.active(), "beta")  # 스코프가 전부를 이긴다
        self.assertEqual(profiles.active(), "alpha")  # 블록을 나가면 원복

    def test_unknown_home_is_custom_not_a_made_up_name(self):
        """모르는 경로에 이름을 지어내면 그 이름으로 설정이 저장된다 — custom 으로 못 박는다."""
        os.environ["ASGARD_HOME"] = os.path.join(self.home, "somewhere-else")
        self.assertEqual(profiles.active(), "custom")

    def test_scope_is_context_local_not_environ(self):
        """스코프가 os.environ 을 건드리면 스웜(한 프로세스 여러 에이전트)에서 서로를 덮는다."""
        profiles.create("alpha")
        with profiles.scoped("alpha"):
            self.assertNotIn("ASGARD_PROFILE", os.environ)
            self.assertNotIn("ASGARD_HOME", os.environ)


class TestMemoryIsolation(ProfileBase):
    """이 레인의 존재 이유 — 1차 기억이 에이전트마다 따로인가."""

    def _write(self, agent: str, slug_seed: str) -> None:
        from asgard.memory import add, ensure_home

        with profiles.scoped(agent):
            ensure_home()
            add(slug_seed, kind="note")

    def _pages(self, agent: str) -> list[str]:
        from asgard.memory import _pages, memory_dir

        with profiles.scoped(agent):
            return sorted(_pages(memory_dir()))

    def test_pages_never_cross(self):
        profiles.create("alpha")
        profiles.create("beta")
        # 각자 자기 것 하나씩 — 셋 다 같은 기계, 셋 다 서로를 못 본다.
        for agent, seed in (("alpha", "alpha owns this"), ("beta", "beta owns this"), ("default", "root owns this")):
            self._write(agent, seed)
        self.assertEqual(self._pages("alpha"), ["alpha-owns-this"])
        self.assertEqual(self._pages("beta"), ["beta-owns-this"])
        self.assertEqual(self._pages("default"), ["root-owns-this"])

    def test_memory_dir_follows_the_agent(self):
        from asgard.memory import memory_dir

        profiles.create("alpha")
        self.assertEqual(memory_dir(), os.path.join(profiles.root(), "memory"))
        with profiles.scoped("alpha"):
            self.assertEqual(memory_dir(), os.path.join(profiles.profile_dir("alpha"), "memory"))

    def test_root_memory_directory_is_not_inherited(self):
        """격리를 푸는 유일한 우회로 — 뿌리의 `memory.directory` 상속.

        병합 뷰로 읽으면 뿌리에 경로 한 줄만 있어도 **모든** 에이전트가 그 디렉터리를 쓴다.
        예산·게이트 같은 값은 물려받아야 하지만 경로는 아니다. 이 갈림을 못 지키면 위 테스트가
        전부 통과하면서도 실사용에서 기억이 섞인다."""
        from asgard.memory import memory_dir

        shared = os.path.join(self.home, "shared-memory")
        os.makedirs(profiles.root(), exist_ok=True)
        with open(os.path.join(profiles.root(), settings.GLOBAL_FILE), "w", encoding="utf-8") as handle:
            json.dump({"memory": {"directory": shared, "index_budget": {"note": 99}}}, handle)
        profiles.create("alpha")

        self.assertEqual(memory_dir(), os.path.abspath(shared))  # 기본 에이전트는 자기 선언대로
        with profiles.scoped("alpha"):
            self.assertEqual(
                memory_dir(),
                os.path.join(profiles.profile_dir("alpha"), "memory"),
                "뿌리의 memory.directory 가 프로파일로 상속되면 1차 기억 격리가 무너진다",
            )
            # 반면 경로가 아닌 값은 물려받아야 한다 — 에이전트마다 예산을 다시 맞출 이유가 없다.
            from asgard.memory.policy import _memory_settings

            self.assertEqual(_memory_settings().get("index_budget"), {"note": 99})

    def test_own_directory_declaration_still_wins(self):
        """물려받지 않을 뿐, 자기가 적은 경로는 이긴다."""
        from asgard.memory import memory_dir

        profiles.create("alpha")
        mine = os.path.join(self.home, "alpha-memory")
        with open(os.path.join(profiles.profile_dir("alpha"), settings.GLOBAL_FILE), "w", encoding="utf-8") as handle:
            json.dump({"memory": {"directory": mine}}, handle)
        with profiles.scoped("alpha"):
            self.assertEqual(memory_dir(), os.path.abspath(mine))


class TestPrivateSurfaces(ProfileBase):
    """기억 말고도 에이전트에 붙어야 하는 것들 — 세션·이력·스킬."""

    def test_sessions_history_and_skills_follow_the_agent(self):
        from asgard.agent.turn_store import _dir as turn_dir
        from asgard.skill_bank import skill_dirs

        profiles.create("alpha")
        root = self.project()
        base_turns, base_skills = turn_dir(root), skill_dirs(root)[-1]
        with profiles.scoped("alpha"):
            self.assertTrue(turn_dir(root).startswith(profiles.profile_dir("alpha")))
            self.assertEqual(skill_dirs(root)[-1], os.path.join(profiles.profile_dir("alpha"), "skills"))
            self.assertNotEqual(turn_dir(root), base_turns)
            self.assertNotEqual(skill_dirs(root)[-1], base_skills)

    def test_project_skill_dir_stays_shared(self):
        """프로젝트 스킬은 프로젝트의 것 — 에이전트를 갈라도 안 갈린다 (공유 세계)."""
        from asgard.skill_bank import skill_dirs

        profiles.create("alpha")
        root = self.project()
        with profiles.scoped("alpha"):
            self.assertEqual(skill_dirs(root)[0], os.path.join(root, ".asgard", "skills"))


class TestSettingsMerge(ProfileBase):
    def test_root_values_are_inherited_and_overridden_key_by_key(self):
        os.makedirs(profiles.root(), exist_ok=True)
        with open(os.path.join(profiles.root(), settings.GLOBAL_FILE), "w", encoding="utf-8") as handle:
            json.dump({"ui": {"lang": "ko"}, "provider": {"name": "anthropic", "model": "opus"}}, handle)
        profiles.create("alpha")
        with open(os.path.join(profiles.profile_dir("alpha"), settings.GLOBAL_FILE), "w", encoding="utf-8") as handle:
            json.dump({"provider": {"model": "haiku"}}, handle)

        with profiles.scoped("alpha"):
            loaded = settings.load_global()
            self.assertEqual(loaded["ui"], {"lang": "ko"})  # 한 번 맞춘 취향은 물려받는다
            self.assertEqual(loaded["provider"], {"name": "anthropic", "model": "haiku"})  # 키 단위 승리

    def test_save_writes_only_the_agents_own_file(self):
        """병합 뷰를 저장하면 뿌리 값이 프로파일로 복제돼 유령 사본이 된다."""
        os.makedirs(profiles.root(), exist_ok=True)
        with open(os.path.join(profiles.root(), settings.GLOBAL_FILE), "w", encoding="utf-8") as handle:
            json.dump({"ui": {"lang": "ko"}}, handle)
        profiles.create("alpha")
        with profiles.scoped("alpha"):
            settings.save_global("provider", {"name": "ollama"})
        with open(os.path.join(profiles.profile_dir("alpha"), settings.GLOBAL_FILE), encoding="utf-8") as handle:
            own = json.load(handle)
        self.assertEqual(own, {"provider": {"name": "ollama"}}, "뿌리의 ui 가 프로파일 파일로 복제되면 안 된다")


class TestCrud(ProfileBase):
    def test_reserved_and_malformed_names_are_refused(self):
        # `custom` 은 active() 가 "모르는 ASGARD_HOME" 에 쓰는 표지 — 같은 이름의 에이전트가
        # 생기면 진짜 프로파일과 표지를 구분할 수 없다.
        for bad in ("memory", "agent", "einherjar", "custom", "Ábc", "-lead", "a" * 64, "a b"):
            with self.assertRaises(ValueError, msg=f"{bad!r} 이 통과했다"):
                profiles.validate(bad)

    def test_default_validates_but_cannot_be_created(self):
        """`default` 는 유효한 **참조**다 (`agent use default`) — 다만 새로 지을 수는 없다.
        뿌리 자신이므로 만드는 순간 `~/.asgard/profiles/default` 라는 유령이 생긴다."""
        self.assertEqual(profiles.validate("default"), "default")
        with self.assertRaises(ValueError):
            profiles.create("default")

    def test_builtin_seed_carries_identity_and_description(self):
        profiles.create("qa", based_on="loki")
        body = profiles.identity("qa")
        self.assertIn("asgard-loki", body)
        self.assertTrue(profiles._meaningful(body))
        self.assertIn("adversarial", profiles.manifest("qa")["description"].lower())

    def test_blank_identity_is_comments_only_so_it_stays_silent(self):
        """씨앗 없이 만든 에이전트의 AGENT.md 는 안내 주석뿐 — 주석뿐이면 없는 것으로 친다
        (manual.py 와 같은 규율). 안내문을 배송해도 프롬프트가 안 늘어나는 근거."""
        profiles.create("plain")
        self.assertEqual(profiles._meaningful(profiles.identity("plain")), "")

    def test_clone_copies_configuration_but_never_memory(self):
        """남의 기억을 물려받은 에이전트는 자기 일지의 주어가 누구인지 모른다."""
        from asgard.memory import add, ensure_home

        profiles.create("source")
        with profiles.scoped("source"):
            ensure_home()
            add("source secret", "only source knows", kind="note")
        with open(os.path.join(profiles.profile_dir("source"), settings.GLOBAL_FILE), "w", encoding="utf-8") as handle:
            json.dump({"provider": {"name": "ollama"}}, handle)

        profiles.create("copy", clone_from="source")
        self.assertTrue(os.path.exists(os.path.join(profiles.profile_dir("copy"), settings.GLOBAL_FILE)))
        from asgard.memory import _pages, memory_dir

        with profiles.scoped("copy"):
            self.assertEqual(_pages(memory_dir()), [])

    def test_delete_resets_a_dangling_sticky_pointer(self):
        """죽은 이름을 가리키는 active_profile 은 이후 모든 프로세스를 custom 으로 떨어뜨린다."""
        profiles.create("alpha")
        profiles.set_active("alpha")
        profiles.delete("alpha")
        self.assertEqual(profiles.sticky(), "default")
        self.assertEqual(profiles.active(), "default")

    def test_ensure_raises_a_builtin_on_demand(self):
        """`agent use freyja` — 내장 이름을 고르는 행위가 곧 그 에이전트의 기억을 여는 행위."""
        self.assertFalse(profiles.exists("freyja"))
        profiles.ensure("freyja")
        self.assertTrue(profiles.exists("freyja"))
        self.assertEqual(profiles.manifest("freyja")["based_on"], "freyja")

    def test_listing_marks_the_active_one_and_counts_pages(self):
        from asgard.memory import add, ensure_home

        profiles.create("alpha")
        with profiles.scoped("alpha"):
            ensure_home()
            add("a fact", "body", kind="note")
        profiles.set_active("alpha")
        rows = {row["id"]: row for row in profiles.listing()}
        self.assertTrue(rows["alpha"]["active"])
        self.assertFalse(rows["default"]["active"])
        self.assertEqual(rows["alpha"]["memory_pages"], 1)


class TestSubprocessPropagation(ProfileBase):
    def test_env_carries_the_active_agent(self):
        profiles.create("alpha")
        profiles.set_active("alpha")
        env = profiles.subprocess_env()
        self.assertEqual(env["ASGARD_PROFILE"], "alpha")
        self.assertEqual(env["ASGARD_HOME"], profiles.profile_dir("alpha"))

    def test_fallback_warning_fires_exactly_when_the_child_would_write_to_the_wrong_home(self):
        """조용한 교차 오염이 이 계층에서 제일 비싼 사고다 — 떨어지는 순간을 문장으로 남긴다."""
        self.assertEqual(profiles.fallback_warning(), "")  # default — 떨어질 곳이 없다
        profiles.create("alpha")
        profiles.set_active("alpha")
        self.assertIn("alpha", profiles.fallback_warning())  # env 없음 = 기본으로 떨어진다
        os.environ["ASGARD_PROFILE"] = "alpha"
        self.assertEqual(profiles.fallback_warning(), "")  # 전파됐으면 조용하다


class TestContainerHome(ProfileBase):
    """이름 없는 홈 — 도커처럼 볼륨 하나를 통째로 `ASGARD_HOME` 으로 주는 경우.

    그 홈은 `~/.asgard/profiles/` 아래 있지 않아 **이름으로 되짚을 수 없다**. 그걸 `custom`
    이라는 표지로만 다루고 경로를 안 이어주면, 그 프로세스는 기억은 제대로 쓰면서 정체성만
    조용히 잃는다 (실측 26-07-29 — `profiles/custom` 이라는 없는 자리를 읽고 있었다).
    컨테이너로 에이전트를 띄우는 흐름 전체가 이 한 갈래에 달려 있다."""

    def setUp(self) -> None:
        super().setUp()
        self.container = os.path.join(self.home, "opt", "agent-data")
        os.makedirs(self.container, exist_ok=True)
        os.environ["ASGARD_HOME"] = self.container

    def test_the_volume_is_that_process_home(self):
        self.assertEqual(profiles.home(), self.container)
        self.assertEqual(profiles.active(), profiles.CUSTOM)

    def test_tier1_memory_is_that_volume(self):
        """컨테이너에게는 그 홈의 memory/ 가 곧 '디폴트 메모리'다."""
        from asgard.memory import add, ensure_home, memory_dir

        self.assertEqual(memory_dir(), os.path.join(self.container, "memory"))
        ensure_home()
        add("the container agent recorded this", kind="note")
        self.assertTrue(os.listdir(os.path.join(self.container, "memory", "pages")))
        # 호스트의 뿌리는 안 건드린다
        self.assertFalse(os.path.isdir(os.path.join(profiles.root(), "memory", "pages")))

    def test_identity_in_the_volume_is_injected(self):
        with open(os.path.join(self.container, profiles.IDENTITY), "w", encoding="utf-8") as handle:
            handle.write("나는 컨테이너 전용 에이전트다. 로그 분석만 한다.")
        note = profiles.note()
        self.assertIn("로그 분석만 한다", note)

    def test_the_header_names_the_volume_not_the_word_custom(self):
        """컨테이너를 여럿 띄우면 전부 'custom' 이라 로그에서 누가 누군지 구분이 안 된다."""
        with open(os.path.join(self.container, profiles.IDENTITY), "w", encoding="utf-8") as handle:
            handle.write("body")
        self.assertIn("agent-data", profiles.note())

    def test_manifest_name_wins_over_the_directory_name(self):
        with open(os.path.join(self.container, profiles.IDENTITY), "w", encoding="utf-8") as handle:
            handle.write("body")
        with open(os.path.join(self.container, profiles.MANIFEST), "w", encoding="utf-8") as handle:
            json.dump({"name": "로그 분석가"}, handle)
        self.assertIn("로그 분석가", profiles.note())

    def test_scoping_to_custom_does_not_recurse(self):
        """`profile_dir('custom')` 이 `home()` 을 부르면 스코프 안에서 서로를 되불러 죽는다."""
        with profiles.scoped(profiles.CUSTOM):
            self.assertEqual(profiles.home(), self.container)

    def test_env_overlay_propagates_the_volume_to_children(self):
        overlay = profiles.env_overlay()
        self.assertEqual(overlay["ASGARD_HOME"], self.container)
        self.assertEqual(overlay["ASGARD_PROFILE"], "")  # 상속된 낡은 이름을 지운다


class TestSwarmBinding(ProfileBase):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.project()
        for name in ("thinker-agent", "worker-agent", "verifier-agent"):
            profiles.create(name)

    def test_narrow_declaration_beats_wide(self):
        swarm.bind(self.root, "worker-agent")  # 프로젝트 대표
        swarm.bind(self.root, "thinker-agent", mode="native")
        swarm.bind(self.root, "verifier-agent", role="verifier")

        self.assertEqual(swarm.resolve(self.root, role="verifier"), "verifier-agent")
        self.assertEqual(swarm.resolve(self.root, mode="native"), "thinker-agent")
        self.assertEqual(swarm.resolve(self.root), "worker-agent")

    def test_unset_default_does_not_masquerade_as_the_default_agent(self):
        """빈 값이 `default` 로 접히면 배치 없는 프로젝트가 루트의 활성 에이전트를 덮는다."""
        profiles.set_active("worker-agent")
        swarm.bind(self.root, "thinker-agent", role="thinker")  # role 만 선언
        self.assertEqual(swarm.binding(self.root)["default"], "")
        self.assertEqual(swarm.resolve(self.root), "worker-agent", "루트의 활성 에이전트가 이겨야 한다")

    def test_missing_agent_fails_open_and_is_reported(self):
        """프로젝트 설정은 리포에 실려 남의 기계로 간다 — 없는 이름이 세션을 막으면 순손실."""
        swarm.bind(self.root, "worker-agent", role="worker")
        path = settings.project_path(self.root)
        data = json.load(open(path, encoding="utf-8"))
        data["agents"]["roles"]["worker"] = "ghost"
        json.dump(data, open(path, "w", encoding="utf-8"))

        self.assertEqual(swarm.resolve(self.root, role="worker"), "default")  # 안 막는다
        self.assertEqual(swarm.missing(self.root), [{"scope": "role", "key": "worker", "agent": "ghost"}])

    def test_bind_refuses_an_unknown_agent_at_write_time(self):
        """런타임은 fail-open 이어야 하지만, 적는 순간엔 사람이 보고 있다 — 오타를 그때 잡는다."""
        with self.assertRaises(FileNotFoundError):
            swarm.bind(self.root, "never-made", role="worker")

    def test_mode_and_role_together_is_refused(self):
        with self.assertRaises(ValueError):
            swarm.bind(self.root, "worker-agent", mode="native", role="worker")

    def test_is_swarm_needs_two_distinct_agents(self):
        swarm.bind(self.root, "worker-agent", role="worker")
        self.assertFalse(swarm.is_swarm(self.root))
        swarm.bind(self.root, "worker-agent", role="thinker")  # 같은 에이전트 둘 = 스웜 아님
        self.assertFalse(swarm.is_swarm(self.root))
        swarm.bind(self.root, "verifier-agent", role="verifier")
        self.assertTrue(swarm.is_swarm(self.root))

    def test_roles_run_on_their_own_memory(self):
        """스웜의 값어치 — Verifier 가 Worker 의 일지를 못 본다 (자기 확증의 구조적 차단)."""
        from asgard.memory import _pages, add, ensure_home, memory_dir

        swarm.bind(self.root, "worker-agent", role="worker")
        swarm.bind(self.root, "verifier-agent", role="verifier")

        with swarm.scoped_for(self.root, role="worker"):
            ensure_home()
            add("worker did this", "the worker's own log", kind="note")
        with swarm.scoped_for(self.root, role="verifier"):
            ensure_home()
            self.assertEqual(_pages(memory_dir()), [], "Verifier 가 Worker 의 기억을 보면 게이트가 무의미해진다")


class TestNativeCompositionEndToEnd(ProfileBase):
    """네이티브 루프의 **실제** `_session` 조립 — 역할마다 맞는 정체성·기억·홈이 붙는가.

    기존 Heimdall 테스트는 `_session` 을 통째로 대역으로 갈아끼우므로 이 조립을 안 지나간다.
    여기서는 진짜 메서드를 태우고 `AgentSession` 생성 인자만 가로챈다 — 조립이 빠지면
    "배치는 했는데 프롬프트엔 아무것도 안 실리는" 무증상 결함이 되기 때문이다."""

    def _heimdall(self, root: str):
        """진짜 Heimdall — `AgentSession` 생성만 가로채 조립 결과를 본다."""
        from asgard.agent.heimdall import core as core_mod
        from asgard.providers import PROVIDERS, ResolvedProvider

        captured: list[dict] = []

        class _Stub:
            def __init__(self, *args, **kwargs):
                # _session 은 (client, rp, root, system) 을 위치로 넘긴다
                captured.append({**kwargs, "system": args[3] if len(args) > 3 else kwargs.get("system", "")})

        self.addCleanup(mock.patch.stopall)
        mock.patch.object(core_mod, "AgentSession", _Stub).start()
        mock.patch.object(core_mod, "make_client", lambda _rp: object()).start()
        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="claude-x", api_key="k")
        return core_mod.Heimdall(rp, root, on_text=lambda _s: None), captured

    def test_each_role_gets_its_own_agents_identity_and_home(self):
        root = self.project()
        profiles.create("arch")
        profiles.create("qa")
        for who, text in (("arch", "나는 설계만 한다."), ("qa", "나는 반례만 찾는다.")):
            with open(os.path.join(profiles.profile_dir(who), profiles.IDENTITY), "w", encoding="utf-8") as handle:
                handle.write(text)
        swarm.bind(root, "arch", role="thinker")
        swarm.bind(root, "qa", role="verifier")

        hd, captured = self._heimdall(root)
        hd._session("BASE-PROMPT", role="thinker")
        hd._session("BASE-PROMPT", role="verifier")

        thinker, verifier = captured[-2], captured[-1]
        self.assertIn("나는 설계만 한다.", thinker["system"])
        self.assertNotIn("나는 반례만 찾는다.", thinker["system"])
        self.assertIn("나는 반례만 찾는다.", verifier["system"])
        self.assertEqual(thinker["agent"], "arch")
        self.assertEqual(verifier["agent"], "qa")

    def test_no_placement_leaves_the_prompt_untouched(self):
        """배치도 정체성도 없는 설치 — 이 계층이 통째로 없는 것과 같아야 한다."""
        root = self.project()
        hd, captured = self._heimdall(root)
        hd._session("BASE-PROMPT", role="worker")
        self.assertEqual(captured[-1]["system"], "BASE-PROMPT")

    def test_role_memory_snapshot_follows_the_placed_agent(self):
        """Verifier 가 Worker 의 일지를 못 보는 것이 이 레인의 값어치 — 스냅샷 단계에서 갈린다."""
        from asgard.memory import add, ensure_home

        root = self.project()
        profiles.create("worker-agent")
        profiles.create("verifier-agent")
        with profiles.scoped("worker-agent"):
            ensure_home()
            add("the worker wrote this into its own log", kind="note")
        with profiles.scoped("verifier-agent"):
            ensure_home()
        swarm.bind(root, "worker-agent", role="worker")
        swarm.bind(root, "verifier-agent", role="verifier")

        hd, _ = self._heimdall(root)
        self.assertIn("the worker wrote this", hd._memory_snap_for("worker"))
        self.assertNotIn("the worker wrote this", hd._memory_snap_for("verifier"))


class TestSessionCarriesTheAgent(ProfileBase):
    def test_run_opens_the_agents_home_for_the_whole_turn(self):
        """생성자가 아니라 run() 에서 열어야 한다 — 메모리 툴은 턴 **안**에서 돈다."""
        from asgard.agent.session import AgentSession

        profiles.create("alpha")
        seen: list[str] = []

        session = AgentSession.__new__(AgentSession)  # 프로바이더 없이 run 래퍼만 검사
        session.agent = "alpha"
        session._run = lambda _content: seen.append(profiles.home()) or "ok"  # type: ignore[method-assign]

        AgentSession.run(session, "hi")
        self.assertEqual(seen, [profiles.profile_dir("alpha")])
        self.assertEqual(profiles.home(), profiles.root(), "턴이 끝나면 원복돼야 한다")

    def test_no_agent_means_no_scope_change(self):
        """배치가 없는 설치는 이 계층이 통째로 없는 것과 같아야 한다."""
        from asgard.agent.session import AgentSession

        seen: list[str] = []
        session = AgentSession.__new__(AgentSession)
        session.agent = None
        session._run = lambda _content: seen.append(profiles.home()) or "ok"  # type: ignore[method-assign]

        AgentSession.run(session, "hi")
        self.assertEqual(seen, [profiles.root()])


if __name__ == "__main__":
    unittest.main()
