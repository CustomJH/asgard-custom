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
        self.assertIn("재현 없으면 수정 없다", d)
        self.assertIn("가설 1개 = 변경 1개", d)  # 동시 다중 변경 금지
        self.assertIn("반증 가능하게", d)
        self.assertIn("git bisect", d)  # 이분 탐색 — 커밋 축
        self.assertIn("은폐", d)  # 증상 덧대기 ≠ 수정
        self.assertIn("수정 전 실패하고 수정 후 통과하는 테스트", d)  # 회귀 고정
        self.assertIn("시도 3회면 중단", d)  # 상한 — 무근거 반복 방지
        self.assertIn("asgard-worker-testing", d)  # 상호 참조

    def test_testing_anchors(self):
        t = self.by_name["asgard-worker-testing"]
        self.assertIn("공개 행동", t)  # 구현 세부 고정 금지
        self.assertIn("실패를 한 번 봐야 한다", t)  # 실패 먼저
        self.assertIn("결정론", t)
        for axis in ("시간", "랜덤", "네트워크", "파일시스템", "순서"):  # flaky 5축
            self.assertIn(axis, t)
        self.assertIn("약한 단언", t)
        self.assertIn("지표이지 목표가 아니다", t)  # 커버리지
        self.assertIn("asgard-eitri-draupnir", t)  # CI 층 상호 참조
        self.assertIn("asgard-freyja-hildisvini", t)  # 브라우저 E2E 상호 참조

    def test_worker_role_uses_generated_discovery_catalog(self):
        from asgard.commands.setup import plan_files
        from asgard.templates.roles import ROLE_AGENTS

        role = dict(ROLE_AGENTS)["asgard-worker.md"]
        self.assertIn("load_skill", role)
        files, _ = plan_files(cc=True, cursor=False, codex=False, root="/tmp/x")
        generated = dict(files)["/tmp/x/.claude/agents/asgard-worker.md"]
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

    def test_worker_support_defers_full_body_until_selected(self):
        from asgard.agent.heimdall import _skill_support

        note, tools, handlers = _skill_support("worker")
        self.assertIn("<available_skills>", note)
        self.assertIn("asgard-worker-debugging", note)
        self.assertNotIn("재현 없으면 수정 없다", note)
        self.assertEqual([tool["name"] for tool in tools], ["load_skill"])
        loaded = handlers["load_skill"]({"name": "asgard-worker-debugging"})
        self.assertIn("재현 없으면 수정 없다", loaded)

    def test_both_worker_paths_expose_loader(self):
        # wave 병렬 경로 + 단일 WORKER 경로 둘 다 — 한쪽만 배선되면 경로에 따라 지식이 사라진다
        import inspect

        from asgard.agent.heimdall import TrinityRun, WaveRunner

        self.assertIn("_skill_support", inspect.getsource(WaveRunner.run))
        self.assertIn("_skill_support", inspect.getsource(TrinityRun._worker_turn))

    def test_verifier_and_loki_not_injected(self):
        # 게이트 무결성 — advisory 지식은 판정 표면(Verifier/loki) 금지 (skill_bank 헌법과 동일)
        import inspect

        from asgard.agent.heimdall import DeliveryDispatch, TrinityRun

        trinity_src = inspect.getsource(TrinityRun)
        for line in trinity_src.splitlines():
            if "_skill_support(" in line and "def " not in line:
                self.assertNotIn("verifier", line.lower())
        dispatch_src = inspect.getsource(DeliveryDispatch)
        self.assertNotIn('_skill_support("loki"', dispatch_src)

    def test_bundled_names_reserve_worker_skills(self):
        from asgard.evolution import _bundled_names

        for sname in _SKILL_NAMES:
            self.assertIn(sname, _bundled_names())


if __name__ == "__main__":
    unittest.main()
