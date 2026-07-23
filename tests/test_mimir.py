#!/usr/bin/env python3
"""미미르(코드 안내) 자가 검증 — 양 스코프 스캐폴드 배선 + 본문 계약 앵커 + 리졸버 오발 방어
+ read-only 3층(frontmatter·guard·heimdall 파생) + DIRECT 인라인 주입.

실행: uv run pytest tests/test_mimir.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.templates.mimir import MIMIR_SKILLS, mimir_note, resolve_mimir_skills  # noqa: E402

_SKILL_NAMES = ("asgard-mimir-brunnr", "asgard-mimir-hofud")


def _names(task: str) -> list[str]:
    return [n for n, _ in resolve_mimir_skills(task)]


class TestScaffold(unittest.TestCase):
    def test_plan_contains_mimir_skills_cc(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=False, root="/tmp/x")
        paths = [p for p, _ in files]
        for sname in _SKILL_NAMES:
            self.assertTrue(any(p.endswith(os.path.join(sname, "SKILL.md")) for p in paths), sname)
        # role 에이전트 자동 배치 — 디렉토리 리스팅 레지스트리
        self.assertTrue(any(p.endswith(os.path.join("agents", "asgard-mimir.md")) for p in paths))

    def test_plan_contains_mimir_skills_agents_scope(self):
        from asgard.commands.setup import plan_files

        for flags in ({"cc": False, "cursor": True, "codex": False}, {"cc": False, "cursor": False, "codex": True}):
            files, _ = plan_files(root="/tmp/x", **flags)
            agents_paths = [p for p, _ in files if f"{os.sep}.agents{os.sep}" in p]
            for sname in (*_SKILL_NAMES, "asgard-mimir"):  # 모드 A 는 코어 계약 스킬 포함
                self.assertTrue(any(sname in p for p in agents_paths), (sname, flags))


class TestSkillBodies(unittest.TestCase):
    """본문 계약 — 설계로 확정한 핵심 앵커가 빠지면 스킬의 존재 이유가 사라진다."""

    def setUp(self):
        self.by_name = dict(MIMIR_SKILLS)

    def test_frontmatter(self):
        for sname, body in MIMIR_SKILLS:
            self.assertTrue(body.startswith(f"---\nname: {sname}\n"), sname)

    def test_brunnr_anchors(self):
        b = self.by_name["asgard-mimir-brunnr"]
        self.assertIn("Pin down the entry point first", b)  # 실행 흐름 서사의 출발점
        self.assertIn("one-sentence overview", b)  # 전역 먼저, 국소 나중
        self.assertIn("one value's journey", b)  # 구체 값 하나가 닻
        self.assertIn("No line-by-line recitation", b)  # 과잉 저수준 방어
        self.assertIn("re-explaining the known wastes trust", b)  # 전문성 역전 — 아는 것 재설명 금지
        self.assertIn(".asgard/map/", b)  # 지도 통합 (읽기 우선)
        self.assertIn("read-only execution only", b)  # 실측은 하되 수정 금지
        self.assertIn("reusable document", b)  # 투어 산출물 — 1회용 채팅 아님

    def test_hofud_anchors(self):
        h = self.by_name["asgard-mimir-hofud"]
        self.assertIn("Order is the switch", h)  # Brain-first — 예측 선행
        self.assertIn("Transfer (closing)", h)  # 전이 질문이 성공 기준
        self.assertIn("a self-generated explanation lasts longer", h)  # 자기설명 유도
        self.assertIn("the goal of guidance is to make guidance unnecessary", h)  # 페이딩
        self.assertIn("is not a metric", h)  # 유창성 착각 방어
        self.assertIn("never repeat the same explanation", h)  # 재설명 대신 각도 전환

    def test_role_declares_skills(self):
        from asgard.templates.roles import ROLE_AGENTS

        role = dict(ROLE_AGENTS)["asgard-mimir.md"]
        for sname in _SKILL_NAMES:
            self.assertIn(sname, role)  # 모드 B 로드 경로 — role 이 스킬을 가리켜야 로드된다


class TestSkillResolver(unittest.TestCase):
    """0-LLM 리졸버 — 단순 사실 질의는 fail-open, 학습·안내 단독어 비트리거."""

    def test_domain_triggers(self):
        self.assertEqual(_names("setup 명령이 어떻게 동작하는지 설명해줘"), ["asgard-mimir-brunnr"])
        self.assertEqual(_names("인증 모듈 코드 투어"), ["asgard-mimir-brunnr"])
        self.assertEqual(_names("신규 입사자 인수인계 자료"), ["asgard-mimir-hofud"])
        self.assertEqual(_names("주니어 멘토링용 이해도 문답"), ["asgard-mimir-hofud"])

    def test_composition_multi_match(self):
        got = _names("온보딩용 아키텍처 설명 워크스루")
        self.assertIn("asgard-mimir-brunnr", got)
        self.assertIn("asgard-mimir-hofud", got)

    def test_false_positive_counterexamples(self):
        # 단순 사실 질의·타 도메인 과업 — role 본문만으로 충분 (fail-open)
        self.assertEqual(_names("restore 함수 반환 타입이 뭔가"), [])
        self.assertEqual(_names("학습률 하이퍼파라미터 튜닝"), [])  # "학습" 단독 비트리거
        self.assertEqual(_names("안내 문구 오탈자 수정"), [])  # "안내" 단독 비트리거
        self.assertEqual(_names("detour 경로 계산 버그"), [])  # \btour\b 단어 경계
        self.assertEqual(_names("quizzical 문자열 파싱"), [])  # \bquiz\b 단어 경계

    def test_no_match_fail_open(self):
        self.assertEqual(_names("README 오탈자 수정"), [])

    def test_stripped_frontmatter(self):
        for _, body in resolve_mimir_skills("온보딩 워크스루"):
            self.assertFalse(body.startswith("---"))


class TestRoleContract(unittest.TestCase):
    """role 파일 — 딜리버리 선언 + read-only 3층의 1층(frontmatter tools)."""

    def test_delivery_declared_standard(self):
        from asgard.templates.roles import delivery_agents, role_writable

        self.assertEqual(delivery_agents()["mimir"], "standard")
        self.assertFalse(role_writable("asgard-mimir.md"))  # Write 부재 = read-only 파생

    def test_role_body_anchors(self):
        from asgard.templates.roles import ROLE_AGENTS

        role = dict(ROLE_AGENTS)["asgard-mimir.md"]
        self.assertIn("entry point → call chain", role)  # 실행 흐름 서사
        self.assertIn("Cap of 3-4 new names", role)  # 청크당 신규 개념 상한
        self.assertIn("prediction question", role)  # Brain-first
        self.assertIn("retrieval question", role)  # 재읽기 대신 인출
        self.assertIn("leaving execution and judgment to the reader", role)  # 검증·디버깅 위임 금지
        self.assertIn("Map candidate:", role)  # .asgard/map/ 통합 (ullr 계약 이식)
        self.assertIn("No code edits", role)


class TestWiring(unittest.TestCase):
    def test_heimdall_resolver_registry_includes_mimir(self):
        import inspect

        from asgard.agent import heimdall

        registry_src = inspect.getsource(heimdall._skill_support)
        self.assertIn("load_skill_for_agent", registry_src)
        self.assertIn('"mimir"', registry_src)

    def test_heimdall_direct_injects_mimir_note(self):
        # DIRECT 설명 턴도 코어만 인라인, 전용 스킬은 읽기 전용 loader 로 지연 로드한다.
        import inspect

        from asgard.agent import heimdall

        self.assertIn("_mimir_note", inspect.getsource(heimdall.Heimdall._direct))
        self.assertIn("_skill_support", inspect.getsource(heimdall.Heimdall._direct))

    def test_mimir_note_match_and_fail_open(self):
        note = mimir_note("결제 흐름이 어떻게 동작하는지 설명해줘")
        self.assertIn("Code Guide Contract", note)
        self.assertNotIn("The well is deep", note)  # 전용 스킬(brunnr) 본문은 지연 로드 — 코어만 주입
        self.assertNotIn("name:", note.split("# Mimir — Code Guide Contract")[1].split("#")[0])  # frontmatter 누출 없음
        self.assertEqual(mimir_note("버튼 색을 파랑으로 바꿔줘"), "")  # 일반 과업은 무주입

    def test_heimdall_delivery_includes_mimir_readonly(self):
        from asgard.agent.heimdall import _DELIVERY, _DELIVERY_READONLY, _DELIVERY_TIERS

        self.assertIn("mimir", _DELIVERY)
        self.assertEqual(_DELIVERY_TIERS["mimir"], "standard")
        self.assertIn("mimir", _DELIVERY_READONLY)  # read-only 3층의 3층(네이티브 파생)

    def test_tier_mirrors_include_mimir(self):
        # 3중 미러 — templates/trinity.py · hooks/quest_log.py · heimdall (동기 이탈 방지)
        from asgard.hooks.quest_log import DEFAULT_POLICY
        from asgard.templates.trinity import trinity_policy

        self.assertEqual(DEFAULT_POLICY["delivery"]["mimir"], "standard")
        self.assertIn('"mimir": "standard"', trinity_policy())

    def test_tool_kernel_scopes_mimir(self):
        from asgard.agent.tool_kernel import ROLE_CAPABILITIES, cc_tools_for_role

        self.assertEqual(ROLE_CAPABILITIES["mimir"], ROLE_CAPABILITIES["loki"])  # read-only 등가
        self.assertEqual(cc_tools_for_role("mimir"), ("Read", "Grep", "Glob", "Bash"))

    def test_readonly_guard_covers_mimir(self):
        # read-only 3층의 2층 — CC 훅이 asgard-mimir 의 write 를 차단
        from asgard.hooks.readonly_guard import _READONLY_AGENTS

        self.assertIn("asgard-mimir", _READONLY_AGENTS)

    def test_dispatch_tool_describes_mimir(self):
        from asgard.agent.heimdall import DISPATCH_TOOL

        self.assertIn("mimir", DISPATCH_TOOL["input_schema"]["properties"]["agent"]["enum"])
        self.assertIn("mimir=code explanation", DISPATCH_TOOL["description"])

    def test_bundled_names_reserve_mimir_skills(self):
        # learned 스킬이 번들 이름을 가로채지 못한다 — 충돌 방지 레지스트리
        from asgard.evolution import _bundled_names

        for sname in _SKILL_NAMES:
            self.assertIn(sname, _bundled_names())

    def test_agents_md_routes_mimir(self):
        from asgard.templates.agents import agents_md

        md = agents_md("p")
        self.assertIn("asgard-mimir", md)  # 모드 B 디스패치 + 모드 A 스킬 로드 양 경로 선언


if __name__ == "__main__":
    unittest.main()
