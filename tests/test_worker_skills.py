#!/usr/bin/env python3
"""Worker 공통 스킬 자가 검증 — 양 스코프 스캐폴드 배선 + 본문 계약 앵커 + 리졸버 오발 방어
+ 네이티브 Worker 주입 배선 (게이트 무결성: Verifier/loki 무주입).

실행: uv run pytest tests/test_worker_skills.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.templates.worker import WORKER_SKILLS, resolve_worker_skills  # noqa: E402

_SKILL_NAMES = ("asgard-worker-debugging", "asgard-worker-testing")
_COMMON_AGENTS = ("worker", "thor", "thor-lead")


def _names(task: str) -> list[str]:
    return [n for n, _ in resolve_worker_skills(task)]


class TestScaffold(unittest.TestCase):
    def test_plan_contains_worker_skills_cc(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=False, root="/tmp/x")
        paths = [p for p, _ in files]
        for sname in _SKILL_NAMES:
            self.assertTrue(any(p.endswith(os.path.join(sname, "SKILL.md")) for p in paths), sname)

    def test_plan_contains_worker_skills_agents_scope(self):
        from asgard.commands.setup import plan_files

        for flags in ({"cc": False, "cursor": True, "codex": False}, {"cc": False, "cursor": False, "codex": True}):
            files, _ = plan_files(root="/tmp/x", **flags)
            agents_paths = [p for p, _ in files if f"{os.sep}.agents{os.sep}" in p]
            for sname in _SKILL_NAMES:
                self.assertTrue(any(sname in p for p in agents_paths), (sname, flags))


class TestSkillBodies(unittest.TestCase):
    """본문 계약 — 설계로 확정한 핵심 앵커가 빠지면 스킬의 존재 이유가 사라진다."""

    def setUp(self):
        self.by_name = dict(WORKER_SKILLS)

    def test_frontmatter(self):
        for sname, body in WORKER_SKILLS:
            self.assertTrue(body.startswith(f"---\nname: {sname}\n"), sname)

    def test_debugging_anchors(self):
        d = self.by_name["asgard-worker-debugging"]
        self.assertIn("Reproduce first (no reproduction, no fix)", d)
        self.assertIn("One hypothesis = one change", d)  # 동시 다중 변경 금지
        self.assertIn("Make hypotheses falsifiable", d)
        self.assertIn("git bisect", d)  # 이분 탐색 — 커밋 축
        self.assertIn("concealment", d)  # 증상 덧대기 ≠ 수정
        self.assertIn("Leave a test that fails before the fix and passes after", d)  # 회귀 고정
        self.assertIn("Stop after 3 attempts", d)  # 상한 — 무근거 반복 방지
        self.assertIn("asgard-worker-testing", d)  # 상호 참조

    def test_testing_anchors(self):
        t = self.by_name["asgard-worker-testing"]
        self.assertIn("public behavior", t)  # 구현 세부 고정 금지
        self.assertIn("must be seen to fail once", t)  # 실패 먼저
        self.assertIn("Vertical slice", t)
        self.assertIn("Determinism", t)
        for axis in ("Time", "Random", "Network", "Filesystem", "Order"):  # flaky 5축
            self.assertIn(axis, t)
        self.assertIn("weak assertions", t)
        self.assertIn("a metric, not a goal", t)  # 커버리지
        self.assertIn("asgard-eitri-draupnir", t)  # CI 층 상호 참조

    def test_worker_and_thor_roles_use_generated_discovery_catalog(self):
        from asgard.commands.setup import plan_files
        from asgard.templates.roles import ROLE_AGENTS

        role = dict(ROLE_AGENTS)["asgard-worker.md"]
        self.assertIn("load_skill", role)
        files, _ = plan_files(cc=True, cursor=False, codex=False, root="/tmp/x")
        by_path = dict(files)
        for agent in _COMMON_AGENTS:
            generated = by_path[f"/tmp/x/.claude/agents/asgard-{agent}.md"]
            for sname in _SKILL_NAMES:
                self.assertIn(sname, generated)


class TestSkillResolver(unittest.TestCase):
    """0-LLM 리졸버 — 단어 경계 (latest→test·majestic→jest 오발 방어)."""

    def test_domain_triggers(self):
        self.assertEqual(_names("로그인 버그 재현해서 수정"), ["asgard-worker-debugging"])
        self.assertEqual(_names("단위 테스트 커버리지 보강"), ["asgard-worker-testing"])
        self.assertEqual(_names("crash 스택트레이스 분석"), ["asgard-worker-debugging"])

    def test_regression_injects_both(self):
        # 회귀 = 원인 규명(디버깅) + 재발 방지 고정(테스트) — 한 과업의 두 표면
        got = _names("회귀 원인 규명하고 고정")
        self.assertEqual(got, list(_SKILL_NAMES))

    def test_false_positive_counterexamples(self):
        self.assertEqual(_names("latest 버전 확인 문서"), [])
        self.assertEqual(_names("majestic 한 landing 카피"), [])
        self.assertEqual(_names("ladybug 아이콘 추가"), [])
        self.assertEqual(_names("README 오탈자 수정"), [])

    def test_stripped_frontmatter(self):
        for _, body in resolve_worker_skills("버그 테스트"):
            self.assertFalse(body.startswith("---"))


class TestNativeWiring(unittest.TestCase):
    """네이티브 progressive disclosure — 메타데이터 색인 + 선택된 본문만 도구 로드."""

    def test_worker_and_thor_support_defer_full_body_until_selected(self):
        from asgard.agent.heimdall.roles import _skill_support
        from asgard.skill_registry import resolve_skills

        for agent in _COMMON_AGENTS:
            with self.subTest(agent=agent):
                note, tools, handlers = _skill_support(agent)
                self.assertIn("<available_skills>", note)
                self.assertIn("asgard-worker-debugging", note)
                self.assertIn("asgard-worker-testing", note)
                self.assertNotIn("Reproduce first (no reproduction, no fix)", note)
                self.assertEqual([tool["name"] for tool in tools], ["load_skill"])
                loaded = handlers["load_skill"]({"name": "asgard-worker-testing"})
                self.assertIn("must be seen to fail once", loaded)
                routed = {name for name, _ in resolve_skills(".", "회귀 버그 테스트", agent)}
                self.assertTrue(set(_SKILL_NAMES) <= routed)

    def test_both_worker_paths_expose_loader(self):
        # wave 병렬 경로 + 단일 WORKER 경로 둘 다 — 한쪽만 배선되면 경로에 따라 지식이 사라진다
        import inspect

        from asgard.agent.heimdall import TrinityRun, WaveRunner

        # 앵커는 클래스 전체 — 메서드가 쪼개져도 "wave 경로에 로더가 있다"는 불변식은 그대로다
        self.assertIn("_skill_support", inspect.getsource(WaveRunner))
        self.assertIn("_skill_support", inspect.getsource(TrinityRun._worker_turn))

    def test_verifier_and_loki_not_injected(self):
        """게이트 무결성 — advisory 지식은 판정 표면 금지 (skill_bank 헌법과 동일).

        호출부를 훑는 대신 **결과**를 잰다. 판정 역할로 부르면 빈 손이 돌아온다는 것 하나라,
        지금 있는 호출부뿐 아니라 앞으로 생길 호출부까지 같이 덮는다.

        변이로 확인한 경계 (26-08-02):
          verifier→worker 별칭   새 판정 실패 ✓ / 옛 줄훑기 판정은 통과 — 이것 때문에 바꿨다
          허용 목록만 개방        양쪽 다 통과. 게이트가 두 겹(목록 + 빈 카탈로그)이라 목록을
                                 열어도 verifier용 스킬이 레지스트리에 없어 여전히 빈 손이다.
                                 관측되는 유출이 없으니 잡을 것도 없다 — 이 판정은 **문이
                                 열렸는가**가 아니라 **지식이 나갔는가**를 잰다."""
        from asgard.agent.heimdall.roles import _skill_support

        for role in ("verifier", "loki", "thinker", "ullr", "delivery"):
            with self.subTest(role=role):
                note, tools, handlers = _skill_support(role)
                # 튜플 통째로 비교하면 실패 시 5천 자짜리 diff 가 나와 읽히지 않는다
                self.assertEqual([t["name"] for t in tools], [], f"{role} 에 로더가 열렸다")
                self.assertEqual(handlers, {}, f"{role} 에 핸들러가 열렸다")
                self.assertEqual(note, "", f"{role} 에 카탈로그 {len(note)}자가 주입됐다")

    def test_bundled_names_reserve_worker_skills(self):
        from asgard.evolution import _bundled_names

        for sname in _SKILL_NAMES:
            self.assertIn(sname, _bundled_names())


if __name__ == "__main__":
    unittest.main()
