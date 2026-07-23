#!/usr/bin/env python3
"""에이트리 전용 스킬 자가 검증 — 양 스코프 스캐폴드 배선 + 본문 계약 앵커 + 리졸버 오발 방어.

실행: uv run pytest tests/test_eitri.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.templates.eitri import EITRI_SKILLS, resolve_eitri_skills  # noqa: E402

_SKILL_NAMES = ("asgard-eitri-draupnir", "asgard-eitri-gullinbursti")


def _names(task: str) -> list[str]:
    return [n for n, _ in resolve_eitri_skills(task)]


class TestScaffold(unittest.TestCase):
    def test_plan_contains_eitri_skills_cc(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=False, root="/tmp/x")
        paths = [p for p, _ in files]
        for sname in _SKILL_NAMES:
            self.assertTrue(any(p.endswith(os.path.join(sname, "SKILL.md")) for p in paths), sname)

    def test_plan_contains_eitri_skills_agents_scope(self):
        from asgard.commands.setup import plan_files

        for flags in ({"cc": False, "cursor": True, "codex": False}, {"cc": False, "cursor": False, "codex": True}):
            files, _ = plan_files(root="/tmp/x", **flags)
            agents_paths = [p for p, _ in files if f"{os.sep}.agents{os.sep}" in p]
            for sname in (*_SKILL_NAMES, "asgard-eitri"):  # 모드 A 는 코어 계약 스킬 포함
                self.assertTrue(any(sname in p for p in agents_paths), (sname, flags))


class TestSkillBodies(unittest.TestCase):
    """본문 계약 — 설계로 확정한 핵심 앵커가 빠지면 스킬의 존재 이유가 사라진다."""

    def setUp(self):
        self.by_name = dict(EITRI_SKILLS)

    def test_frontmatter(self):
        for sname, body in EITRI_SKILLS:
            self.assertTrue(body.startswith(f"---\nname: {sname}\n"), sname)

    def test_draupnir_anchors(self):
        d = self.by_name["asgard-eitri-draupnir"]
        self.assertIn("fail fast", d)
        self.assertIn("Cache key = hash of inputs", d)  # 브랜치명·날짜 키 금지의 근거
        self.assertIn("not a repair but defect concealment", d)  # flaky 규율 — 은폐 금지
        self.assertIn("Quarantine", d)
        self.assertIn("Multi-stage", d)
        self.assertIn("latest is a declaration that reproducibility has been abandoned", d)
        self.assertIn("Never put secrets in build args or layers", d)  # 시크릿 경계
        self.assertIn("Fork-PR", d)
        self.assertIn("actual runner execution log", d)  # 검증 = 실측 (Canon 8)
        self.assertIn("Thor's canon", d)  # 런타임 경계 상호 참조

    def test_gullinbursti_anchors(self):
        g = self.by_name["asgard-eitri-gullinbursti"]
        self.assertIn("One single source of truth for the version", g)
        self.assertIn("install smoke test", g)  # 만들었다 ≠ 설치된다
        self.assertIn("a pasted commit log is not a changelog", g)
        self.assertIn(
            "All gates green → version bump → artifact build & verification → tag", g
        )  # 게이트 → 범프 → 아티팩트 → 태그
        self.assertIn("approval is Odin's share", g)  # 릴리스 경계 (role 계약 상속)
        self.assertIn("rollback path", g)  # 롤백
        self.assertIn("Idempotent", g)  # 설치 스크립트 재실행 안전

    def test_role_declares_skills(self):
        from asgard.templates.roles import ROLE_AGENTS

        role = dict(ROLE_AGENTS)["asgard-eitri.md"]
        for sname in _SKILL_NAMES:
            self.assertIn(sname, role)  # 모드 B 로드 경로 — role 이 스킬을 가리켜야 로드된다


class TestSkillResolver(unittest.TestCase):
    """0-LLM 리졸버 — 단어 경계(\\bci\\b) + 배포·런타임 비트리거 (토르 경계 존중)."""

    def test_domain_triggers(self):
        self.assertEqual(_names("GitHub Actions CI 파이프라인에 빌드 캐시 추가"), ["asgard-eitri-draupnir"])
        self.assertEqual(_names("릴리스 태그와 체인지로그 갱신"), ["asgard-eitri-gullinbursti"])
        self.assertEqual(_names("설치 스크립트 멱등성 수정"), ["asgard-eitri-gullinbursti"])
        self.assertEqual(_names("flaky 테스트 검역 처리"), ["asgard-eitri-draupnir"])

    def test_composition_multi_match(self):
        got = _names("Dockerfile 멀티스테이지 전환 후 release 아티팩트 생성")
        self.assertIn("asgard-eitri-draupnir", got)
        self.assertIn("asgard-eitri-gullinbursti", got)

    def test_false_positive_counterexamples(self):
        # ci 부분 일치였다면 오발했을 문장들 + 런타임(토르 소관) 비트리거
        self.assertEqual(_names("certificate 발급 로직 수정"), [])
        self.assertEqual(_names("pencil 아이콘 교체"), [])
        self.assertEqual(_names("k8s readiness probe 튜닝"), [])
        self.assertEqual(_names("서비스 deploy 후 오토스케일 정책"), [])

    def test_no_match_fail_open(self):
        self.assertEqual(_names("README 오탈자 수정"), [])

    def test_stripped_frontmatter(self):
        for _, body in resolve_eitri_skills("ci 파이프라인 릴리스"):
            self.assertFalse(body.startswith("---"))


class TestWiring(unittest.TestCase):
    def test_heimdall_resolver_registry_includes_eitri(self):
        import inspect

        from asgard.agent import heimdall

        registry_src = inspect.getsource(heimdall._skill_support)
        self.assertIn("load_skill_for_agent", registry_src)
        self.assertIn('"eitri"', registry_src)

    def test_bundled_names_reserve_eitri_skills(self):
        # learned 스킬이 번들 이름을 가로채지 못한다 — 충돌 방지 레지스트리
        from asgard.evolution import _bundled_names

        for sname in _SKILL_NAMES:
            self.assertIn(sname, _bundled_names())


if __name__ == "__main__":
    unittest.main()
