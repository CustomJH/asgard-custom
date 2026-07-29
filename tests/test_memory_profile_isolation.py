"""에이전트별 기억 격리 — **주입면**에서 증명한다.

`tests/test_profiles.py` 는 저장 격리를 잰다 (pages/·sessions/·skills/ 가 프로파일마다
따로인가). 여기서 재는 것은 그 뒤의 층이다: **여섯 레인이 합쳐져 프롬프트가 되는 자리**에서
남의 기억이 한 글자도 안 새는가.

왜 따로 재는가. 저장이 갈려 있다는 것과 주입이 안 섞인다는 것은 다른 명제다. 회수는 이제
개인 위키·프로젝트 record·문서·종합·스킬·에피소드 여섯 레인을 하나의 예산 위에서 조립하고
(`memory.assemble`), 그 레인 중 일부는 **프로젝트에 붙는다**(공유가 정상). 그러니 "무엇이
갈리고 무엇이 안 갈리는가"는 조립 결과에서 확인해야 실제 계약이 된다.

경계는 이렇다:
  · 에이전트에 붙는다 (갈린다)  — 1차 개인 위키 · 세션/에피소드 · 글로벌 스킬 · 제안 대기열
  · 프로젝트에 붙는다 (공유)    — 프로젝트 record · 문서 · 종합 · 프로젝트 스킬
"""

from __future__ import annotations

import os
import tempfile
import unittest

from asgard import profiles


class ProfileMemoryBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home, exist_ok=True)
        self._saved = {
            key: os.environ.get(key)
            for key in (
                "HOME",
                "ASGARD_HOME",
                "ASGARD_PROFILE",
                "ASGARD_MEMORY_DIR",
                "ASGARD_MEMORY_SEMANTIC",
                "ASGARD_MEMORY_INJECT",
            )
        }
        os.environ["HOME"] = self.home
        for key in ("ASGARD_HOME", "ASGARD_PROFILE", "ASGARD_MEMORY_DIR"):
            os.environ.pop(key, None)
        os.environ["ASGARD_MEMORY_SEMANTIC"] = "off"  # 결정론 — 격리를 재지 검색을 재지 않는다
        os.environ["ASGARD_MEMORY_INJECT"] = "on"
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def project(self) -> str:
        path = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(path, ".asgard"), exist_ok=True)
        return path

    def remember(self, agent: str, fact: str, kind: str = "note") -> None:
        from asgard.memory import add, ensure_home

        with profiles.scoped(agent):
            ensure_home()
            add(fact, kind=kind)

    def recall(self, agent: str, query: str, **kwargs) -> str:
        from asgard import memory_context

        with profiles.scoped(agent):
            return memory_context.recall_note(query, start=self.project(), **kwargs)


class TestInjectionSurfaceIsolation(ProfileMemoryBase):
    ALPHA = "알파는 배포 전에 스테이징에서 스모크를 먼저 돌린다"
    BETA = "베타는 배포 전에 카나리아를 먼저 올린다"

    def test_one_agent_never_sees_the_others_fact_in_its_prompt(self):
        profiles.create("alpha")
        profiles.create("beta")
        self.remember("alpha", self.ALPHA, kind="feedback")
        self.remember("beta", self.BETA, kind="feedback")

        note_a = self.recall("alpha", "배포 전에 무엇을 먼저 하나")
        note_b = self.recall("beta", "배포 전에 무엇을 먼저 하나")

        self.assertIn("스테이징", note_a)
        self.assertNotIn("카나리아", note_a)
        self.assertIn("카나리아", note_b)
        self.assertNotIn("스테이징", note_b)

    def test_the_default_agent_is_isolated_too(self):
        """`default` 는 뿌리 자신이라 경로가 특별하다 — 그래서 따로 잰다."""
        profiles.create("alpha")
        self.remember("default", "기본 에이전트는 릴리스 태그를 수동으로 찍는다", kind="feedback")
        self.remember("alpha", "알파는 릴리스 태그를 자동으로 찍는다", kind="feedback")

        self.assertIn("수동", self.recall("default", "릴리스 태그"))
        self.assertNotIn("자동", self.recall("default", "릴리스 태그"))
        self.assertIn("자동", self.recall("alpha", "릴리스 태그"))
        self.assertNotIn("수동", self.recall("alpha", "릴리스 태그"))

    def test_the_frozen_session_snapshot_is_also_per_agent(self):
        """턴마다 붙는 회수만이 아니라 세션에 한 번 얼어붙는 카탈로그도 갈려야 한다."""
        from asgard.memory import snapshot_note

        profiles.create("alpha")
        self.remember("default", "기본 에이전트만의 사실이다 이것은", kind="note")
        self.remember("alpha", "알파만의 사실이다 이것은", kind="note")
        with profiles.scoped("default"):
            base = snapshot_note()
        with profiles.scoped("alpha"):
            alpha = snapshot_note()
        self.assertIn("기본 에이전트만의", base)
        self.assertNotIn("알파만의", base)
        self.assertIn("알파만의", alpha)
        self.assertNotIn("기본 에이전트만의", alpha)


class TestEpisodeIsolation(ProfileMemoryBase):
    def test_past_turns_do_not_cross_agents_in_the_same_repo(self):
        """같은 리포에서 두 에이전트가 일해도 서로의 대화를 회상하지 않는다."""
        from asgard.agent import turn_store

        profiles.create("alpha")
        root = self.project()
        for agent, mark in (("default", "기본이 만진 인덱스 캐시"), ("alpha", "알파가 만진 인덱스 캐시")):
            with profiles.scoped(agent):
                for index in range(6):  # _EXCLUDE_TAIL 을 넘겨야 과거로 인정된다
                    turn_store.append_turn(root, f"질문 {index} 인덱스 캐시", f"{mark} {index}")

        note_default = self.recall("default", "인덱스 캐시", include_episodes=True)
        note_alpha = self.recall("alpha", "인덱스 캐시", include_episodes=True)
        self.assertIn("기본이 만진", note_default)
        self.assertNotIn("알파가 만진", note_default)
        self.assertIn("알파가 만진", note_alpha)
        self.assertNotIn("기본이 만진", note_alpha)


class TestProposalIsolation(ProfileMemoryBase):
    def test_a_proposal_staged_by_one_agent_is_invisible_to_the_other(self):
        from asgard.memory import ensure_home, propose

        profiles.create("alpha")
        with profiles.scoped("default"):
            ensure_home()
            staged = propose.stage("기본 에이전트가 올린 제안이다 이것은", kind="note")
        with profiles.scoped("alpha"):
            ensure_home()
            self.assertEqual(propose.pending(), [])
        with profiles.scoped("default"):
            self.assertEqual([row["id"] for row in propose.pending()], [staged["id"]])


class TestSharedLanesStayShared(ProfileMemoryBase):
    """격리가 지나치면 팀 지식이 죽는다 — 프로젝트에 붙은 레인은 갈리면 **안** 된다."""

    def test_the_project_document_lane_is_shared_between_agents(self):
        from asgard.project_memory import documents

        profiles.create("alpha")
        root = self.project()

        class Doc:
            document_id = "d1"
            name = "release.md"
            kind = "spec"
            strategy = "local"
            content_hash = "a" * 64
            text = "# 릴리스 절차\n\n배포는 반드시 스테이징을 거친 뒤 운영으로 올린다\n"
            entities: list = []

        documents.save_document(root, Doc())
        documents.sync(root)
        for agent in ("default", "alpha"):
            with profiles.scoped(agent):
                self.assertTrue(documents.rows("릴리스 절차 배포", root), f"{agent} 가 팀 문서를 못 본다")


if __name__ == "__main__":
    unittest.main()
