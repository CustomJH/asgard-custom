#!/usr/bin/env python3
"""토르 전용 스킬 자가 검증 — 양 스코프 스캐폴드 배선 + 본문 계약 앵커 + 리졸버 오발 방어.

실행: uv run pytest tests/test_thor.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.templates.thor import (  # noqa: E402
    THOR_SKILLS,
    eitri_core_skill,
    resolve_thor_skills,
    thor_core_skill,
)

# role 본문의 합성 규칙에 열거되는 도메인 스킬 — 편대 프로토콜(einherjar)은 lead role 이 참조한다
_DOMAIN_SKILLS = (
    "asgard-thor-mjollnir",
    "asgard-thor-lightning",
    "asgard-thor-megingjord",
    "asgard-thor-jarngreipr",
    "asgard-thor-gridarvol",
    "asgard-thor-tanngrisnir",
)
_SKILL_NAMES = (*_DOMAIN_SKILLS, "asgard-thor-einherjar")


def _names(task: str) -> list[str]:
    return [n for n, _ in resolve_thor_skills(task)]


class TestScaffold(unittest.TestCase):
    def test_plan_contains_thor_skills_cc(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=False, root="/tmp/x")
        paths = [p for p, _ in files]
        for sname in _SKILL_NAMES:
            self.assertTrue(any(p.endswith(os.path.join(sname, "SKILL.md")) for p in paths), sname)
        # CC 는 서브에이전트(role)가 실체 — 코어 스킬은 .agents 스코프 전용 (중복 배치 금지)
        for core in ("asgard-thor", "asgard-eitri"):
            self.assertFalse(any(p.endswith(os.path.join(core, "SKILL.md")) for p in paths), core)

    def test_plan_contains_thor_skills_agents_scope(self):
        from asgard.commands.setup import plan_files

        for flags in ({"cc": False, "cursor": True, "codex": False}, {"cc": False, "cursor": False, "codex": True}):
            files, _ = plan_files(root="/tmp/x", **flags)
            agents_paths = [p for p, _ in files if f"{os.sep}.agents{os.sep}" in p]
            # 모드 A 는 코어 계약 스킬(thor·eitri) 포함
            for sname in (*_SKILL_NAMES, "asgard-thor", "asgard-eitri"):
                self.assertTrue(any(sname in p for p in agents_paths), (sname, flags))

    def test_eitri_role_scaffolded_cc(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=False, root="/tmp/x")
        self.assertTrue(any(p.endswith(os.path.join(".claude", "agents", "asgard-eitri.md")) for p, _ in files))


class TestCoreSkillSingleSource(unittest.TestCase):
    def test_cores_derive_from_role_bodies(self):
        from asgard.templates.roles import ROLE_AGENTS

        for core, fname in ((thor_core_skill(), "asgard-thor.md"), (eitri_core_skill(), "asgard-eitri.md")):
            role_body = dict(ROLE_AGENTS)[fname].split("---", 2)[2].lstrip()
            self.assertTrue(core.startswith(f"---\nname: {fname.removesuffix('.md')}\n"))
            self.assertTrue(core.endswith(role_body))  # 본문 = role 파일 그대로 (단일 소스)
            self.assertNotIn("model:", core.split("---", 2)[1])  # role frontmatter 누출 없음


class TestRoleBodies(unittest.TestCase):
    """역할 본문 계약 — 설계(26-07-16, Codex 교차검증 10건 반영)의 핵심 앵커."""

    def setUp(self):
        from asgard.templates.roles import ROLE_AGENTS

        roles = dict(ROLE_AGENTS)
        self.thor = roles["asgard-thor.md"]
        self.eitri = roles["asgard-eitri.md"]
        self.worker = roles["asgard-worker.md"]

    def test_thor_is_backend_not_build(self):
        self.assertIn("Backend specialist", self.thor)
        self.assertIn("belong to asgard-eitri", self.thor)  # 빌드·CI 는 에이트리로 경계 명시
        self.assertNotIn("build/infra specialist", self.thor)  # 구 정체 잔존 금지

    def test_thor_diagnosis_gate_scoped_to_defects(self):
        # Codex #8 — 게이트는 버그·회귀·장애 한정, STOP 조건은 검증 가능한 사실
        self.assertIn("bugs/regressions/performance incidents only", self.thor)
        for cond in ("reproduction failed", "actual call path unconfirmed", "conflicting evidence unresolved"):
            self.assertIn(cond, self.thor)

    def test_thor_side_effect_approval_model(self):
        # Codex #2 — 승인 축 = 환경 × 외부 부작용, Worker 배정 ≠ 승인
        self.assertIn("environment × external side effect", self.thor)
        self.assertIn("A Worker task assignment is not approval", self.thor)

    def test_thor_skill_composition_not_exclusion(self):
        # Codex #5 — 혼용 금지가 아니라 합성 규칙 (야른그레이프르 = 오버레이)
        self.assertIn("not mutually exclusive but **compose**", self.thor)
        self.assertIn("safety overlay", self.thor)
        self.assertIn("diagnosis overlay", self.thor)  # 그리다르뵐 = 결함 과업에 겹치는 층
        for sname in _DOMAIN_SKILLS:
            self.assertIn(sname, self.thor)

    def test_thor_frontmatter_excludes_verifier(self):
        frontmatter = self.thor.split("---", 2)[1]
        self.assertIn("Verifier is forbidden", frontmatter)

    def test_eitri_contracts(self):
        self.assertIn("Local-CI parity", self.eitri)
        self.assertIn("Cap of 5", self.eitri)  # verify-fix 루프 상한
        self.assertIn("up to local artifact generation and verification", self.eitri)  # 릴리스 경계 (Codex #2)
        self.assertIn("belong to asgard-thor", self.eitri)  # 런타임 경계
        self.assertIn("disallowedTools: Agent", self.eitri)

    def test_worker_routes_by_change_surface(self):
        # Codex #1 — Worker 라우팅 계약이 단일 소스: 이걸 안 고치면 과업이 계속 구 토르로 간다
        self.assertIn("asgard-thor", self.worker)
        self.assertIn("asgard-eitri", self.worker)
        self.assertIn("by change surface", self.worker)
        self.assertNotIn("build/CI/infra = asgard-thor", self.worker)  # 구 라우팅 잔존 금지


class TestSkillBodies(unittest.TestCase):
    """본문 계약 — 설계로 확정한 핵심 앵커가 빠지면 스킬의 존재 이유가 사라진다."""

    def setUp(self):
        self.by_name = dict(THOR_SKILLS)

    def test_frontmatter(self):
        for sname, body in THOR_SKILLS:
            self.assertTrue(body.startswith(f"---\nname: {sname}\n"), sname)

    def test_mjollnir_anchors(self):
        m = self.by_name["asgard-thor-mjollnir"]
        self.assertIn("Batch Durability Contract", m)  # 재시작 생존 계약
        for anchor in ("Checkpoint", "Re-entry point", "Partial failure"):
            self.assertIn(anchor, m)
        self.assertIn("outbox", m)  # 메시징 신뢰성 (Codex #7)
        self.assertIn("DLQ", m)
        self.assertIn("idempoten", m)
        self.assertIn("N+1", m)
        self.assertIn("Consistent lock ordering", m)

    def test_lightning_anchors(self):
        li = self.by_name["asgard-thor-lightning"]
        self.assertIn("Layered timeouts", li)
        self.assertIn("Circuit breaker", li)
        self.assertIn("Realtime Ladder", li)  # 폴링 → SSE → WebSocket
        self.assertIn("If you cannot write the invalidation strategy first, do not introduce a cache", li)
        self.assertIn("SSRF", li)  # 서버 보안 경계 (Codex #7)
        self.assertIn("IDOR", li)
        self.assertIn(
            "External Integrations (without timeouts, partial-failure handling, and compensation it is not an "
            "external call)",
            li,
        )

    def test_megingjord_anchors(self):
        mg = self.by_name["asgard-thor-megingjord"]
        self.assertIn("liveness", mg)
        self.assertIn("readiness", mg)
        self.assertIn("No dependency cascades", mg)
        self.assertIn("graceful shutdown", mg)
        self.assertIn("Stateless First", mg)
        self.assertIn("Observability Minimum Contract", mg)  # Codex #7
        self.assertIn("belong to asgard-eitri", mg)  # 빌드 경계 상호 참조

    def test_jarngreipr_anchors(self):
        j = self.by_name["asgard-thor-jarngreipr"]
        self.assertIn("overlay", j)  # 단독 아닌 합성 (Codex #5)
        for grade in ("🟢", "🟡", "🔴", "⚫"):  # 안전 등급 매트릭스
            self.assertIn(grade, j)
        self.assertIn("expand-contract", j)
        self.assertIn("approval belongs to Odin", j)  # Codex #2
        self.assertIn("measured query plan", j)

    def test_gridarvol_anchors(self):
        g = self.by_name["asgard-thor-gridarvol"]
        self.assertIn("overlay", g)  # 공통 디버깅 위에 겹치는 백엔드 층
        self.assertIn("asgard-worker-debugging", g)  # 공통 층과의 경계 상호 참조
        self.assertIn("Reproduction Loop Ladder", g)  # 빨강→초록 명령 우선
        self.assertIn("bisect", g)
        self.assertIn("Layer Isolation", g)  # 연결→타임아웃→…→의미
        self.assertIn("Status-code playbook", g)
        self.assertIn("Premise Verification", g)  # 의도된 설계·하중 받치는 부재
        self.assertIn("absence bears load", g)
        self.assertIn("rule of three", g)  # 3회 실패 = 구조 신호

    def test_tanngrisnir_anchors(self):
        t = self.by_name["asgard-thor-tanngrisnir"]
        self.assertIn("Masking fallback", t)  # 결함 은폐 폴백 = 차단
        self.assertIn("Justified fallback", t)  # 허용 조건 4가지
        self.assertIn("pipefail", t)  # 실패 보존 증거 형식
        self.assertIn("Running ≠ evaluating", t)  # 명령 실행과 기준 충족의 분리
        self.assertIn("regression case", t)  # 라이브 버그 = 수정+케이스 한 쌍
        self.assertIn("Slop Sweep", t)
        self.assertIn("asgard-worker-testing", t)  # 테스트 작성 규율 경계

    def test_einherjar_anchors(self):
        e = self.by_name["asgard-thor-einherjar"]
        self.assertIn("delegation threshold", e)  # 편성 판정 — 토큰 세금 정당화
        self.assertIn("Split squad", e)
        self.assertIn("Tournament squad", e)
        self.assertIn("Contracts first", e)  # 공유 계약은 병렬 전에 확정
        self.assertIn("fresh context", e)  # 서브에 히스토리 무상속
        self.assertIn("Cap of 3–5 files", e)
        self.assertIn("Depth 1", e)
        self.assertIn("Verification independence", e)
        self.assertIn("No declaring completion", e)
        self.assertIn("Solo fallback", e)  # 편대 불가 환경의 체크리스트 게이트


class TestSkillResolver(unittest.TestCase):
    """0-LLM 리졸버 — 단어 경계 + 동반어 조건 (26-07-16 Codex #3 오발 반례가 회귀 케이스)."""

    def test_domain_triggers(self):
        self.assertEqual(_names("결제 트랜잭션 경계 수정"), ["asgard-thor-mjollnir"])
        self.assertEqual(_names("REST API rate limit 추가"), ["asgard-thor-lightning"])
        self.assertEqual(_names("graceful shutdown 드레이닝 구현"), ["asgard-thor-megingjord"])
        self.assertEqual(_names("ALTER TABLE 로 컬럼 추가"), ["asgard-thor-jarngreipr"])

    def test_composition_multi_match(self):
        # 합성 규칙 — 대용량 마이그레이션 = 묠니르 + 야른그레이프르(오버레이)
        got = _names("대용량 데이터 마이그레이션을 배치로 처리")
        self.assertIn("asgard-thor-mjollnir", got)
        self.assertIn("asgard-thor-jarngreipr", got)
        got = _names("WebSocket 실시간 알림 + autoscaling")
        self.assertIn("asgard-thor-lightning", got)
        self.assertIn("asgard-thor-megingjord", got)

    def test_codex_false_positive_counterexamples(self):
        # 26-07-16 교차검증 반례 — 부분 일치였다면 전부 오발했을 문장들
        self.assertEqual(_names("Next.js index.ts drag-and-drop animation 최적화"), [])
        self.assertEqual(_names("CI Docker layer cache 최적화"), [])
        self.assertEqual(_names("RESTORE capital alternative healthcare 문서 수정"), [])
        self.assertEqual(_names("scalar 값 처리 로직"), [])

    def test_companion_conditions(self):
        # index → DB 문맥 동반 시만, schema → graphql 이면 lightning 만, cache → 서버 응답 문맥만
        self.assertEqual(_names("목차 index 페이지 갱신"), [])
        self.assertEqual(_names("테이블 인덱스 추가로 조회 개선"), ["asgard-thor-jarngreipr"])
        self.assertEqual(_names("GraphQL schema 를 프론트에 연결"), ["asgard-thor-lightning"])
        self.assertEqual(_names("redis 응답 캐시 무효화 전략"), ["asgard-thor-lightning"])
        self.assertEqual(_names("브라우저 캐시 정책 문서화"), [])

    def test_new_domain_triggers(self):
        self.assertEqual(_names("간헐 크래시 장애 원인 규명"), ["asgard-thor-gridarvol"])
        self.assertEqual(_names("결제 모듈 에러 처리 폴백 정리"), ["asgard-thor-tanngrisnir"])
        self.assertEqual(_names("토너먼트 편대 편성"), ["asgard-thor-einherjar"])

    def test_diagnosis_overlay_composes(self):
        # 그리다르뵐은 오버레이 — API 결함 과업이면 번개 위에 겹친다
        got = _names("API 타임아웃 버그 재현")
        self.assertIn("asgard-thor-lightning", got)
        self.assertIn("asgard-thor-gridarvol", got)

    def test_new_skill_false_positives(self):
        self.assertEqual(_names("문서 목차 정리"), [])  # "정리" 단독은 탕그리스니르 비발화
        self.assertEqual(_names("ladybug 컴포넌트 스타일"), [])  # \\bbugs?\\b 단어 경계
        self.assertEqual(_names("편성표 문서 갱신"), [])  # "편대" 아님

    def test_no_match_fail_open(self):
        self.assertEqual(_names("README 오탈자 수정"), [])

    def test_stripped_frontmatter(self):
        for _, body in resolve_thor_skills("트랜잭션 API 스케일링 마이그레이션 테이블"):
            self.assertFalse(body.startswith("---"))


class TestWiring(unittest.TestCase):
    def test_heimdall_delivery_includes_eitri(self):
        from asgard.agent.heimdall import _DELIVERY, _DELIVERY_TIERS

        self.assertIn("eitri", _DELIVERY)
        self.assertEqual(_DELIVERY_TIERS["eitri"], "standard")

    def test_tier_mirrors_include_eitri(self):
        # 3중 미러 — templates/trinity.py · hooks/quest_log.py · heimdall (동기 이탈 방지)
        from asgard.hooks.quest_log import DEFAULT_POLICY
        from asgard.templates.trinity import trinity_policy

        self.assertEqual(DEFAULT_POLICY["delivery"]["eitri"], "standard")
        self.assertIn('"eitri": "standard"', trinity_policy())

    def test_tool_kernel_scopes_eitri(self):
        from asgard.agent.tool_kernel import ROLE_CAPABILITIES, cc_tools_for_role

        self.assertEqual(ROLE_CAPABILITIES["eitri"], ROLE_CAPABILITIES["thor"])
        self.assertEqual(cc_tools_for_role("eitri"), cc_tools_for_role("thor"))
        self.assertNotIn("Agent", cc_tools_for_role("eitri"))  # 재위임 불가

    def test_dispatch_tool_routes_all_four(self):
        from asgard.agent.heimdall import DISPATCH_TOOL

        # 순서는 role 파일 delivery: 선언 파생(정렬) — 계약은 구성원 집합이지 순서가 아니다
        self.assertEqual(
            set(DISPATCH_TOOL["input_schema"]["properties"]["agent"]["enum"]),
            {"freyja", "thor", "thor-lead", "eitri", "loki", "mimir"},
        )
        for label in ("thor=backend", "eitri=build"):
            self.assertIn(label, DISPATCH_TOOL["description"])


class TestThorLead(unittest.TestCase):
    """백엔드 편대장 — 대장 토르만 재위임 봉인을 연다. 서브는 봉인 유지."""

    def setUp(self):
        from asgard.templates.roles import ROLE_AGENTS

        self.roles = dict(ROLE_AGENTS)
        self.lead = self.roles["asgard-thor-lead.md"]

    def test_role_registered_with_delivery_tier(self):
        from asgard.templates.roles import delivery_agents

        self.assertEqual(delivery_agents().get("thor-lead"), "standard")  # 네이티브 디스패치 enum 자동 편입

    def test_lead_frontmatter_has_agent_tool(self):
        frontmatter = self.lead.split("---", 2)[1]
        self.assertIn("Agent", frontmatter)  # 편성 권한 — 봉인의 예외
        self.assertIn("Verifier is forbidden", frontmatter)  # 검증 독립성은 동일

    def test_cc_whitelist_lead_open_sub_sealed(self):
        from asgard.agent.tool_kernel import ROLE_CAPABILITIES, cc_tools_for_role

        self.assertIn("Agent", cc_tools_for_role("thor-lead"))
        self.assertNotIn("Agent", cc_tools_for_role("thor"))  # 서브 토르 재위임 봉인 유지
        self.assertIn("coordinate", ROLE_CAPABILITIES["thor-lead"])
        self.assertNotIn("coordinate", ROLE_CAPABILITIES["thor"])

    def test_lead_contract_anchors(self):
        for anchor in (
            "asgard-thor-einherjar",  # 팀 프로토콜 단일 소스 로드 의무
            "asgard-thor-jarngreipr",  # 데이터 위험 단위 브리프 동봉
            "asgard-thor-gridarvol",  # 진단 단위 브리프 동봉
            "Judge squad formation first",  # 위임 문턱 미달 = 편대 금지
            "delegation threshold",
            "contract-first",  # 공유 계약 병렬 전 확정
            "Tournament",  # N-버전 승자 적용
            "Separate the verdict",  # 생성자≠판정자
            "Two ledgers",
            "Depth 1",  # 서브 재위임 불가
            "No completion claims",
        ):
            self.assertIn(anchor, self.lead)

    def test_sub_thor_squad_membership_contract(self):
        sub = self.roles["asgard-thor.md"]
        self.assertIn("When part of a squad", sub)  # 브리프 분계선·단위 한정 검증·반환 규격
        self.assertIn("Squad formation is asgard-thor-lead's surface", sub)  # 직접 편성 금지 — 판단 반환
        self.assertIn("No re-delegation — does not spawn subagents", sub)  # 봉인 문구 보존
        self.assertIn("global builds/full test suites are the lead's job", sub)  # 전역 게이트 단일 실행 계약

    def test_heimdall_resolver_covers_lead(self):
        import inspect

        from asgard.agent import heimdall

        src = inspect.getsource(heimdall._skill_support)
        self.assertIn('"thor-lead"', src)  # 편대장 디스패치에도 전용 스킬 주입

    def test_subagent_gate_targets(self):
        from asgard.hooks.subagent_gate import AGENT_TARGETS

        self.assertEqual(AGENT_TARGETS["asgard-thor-lead"], frozenset({"asgard-thor", "asgard-loki"}))
        self.assertEqual(AGENT_TARGETS["asgard-thor"], frozenset())  # 서브 토르 완전 봉인

    def test_routing_agents_md_and_worker(self):
        from asgard.templates.agents import agents_md

        md = agents_md("p")
        self.assertIn("asgard-thor-lead", md)  # 대형 백엔드 과업 라우팅
        self.assertIn("asgard-thor-einherjar", md)  # 모드 A 편대 스킬 경로
        self.assertIn("exception: asgard-thor-lead", md)  # 재위임 예외의 명시적 한정
        worker = self.roles["asgard-worker.md"]
        self.assertIn("asgard-thor-lead", worker)
        self.assertIn("asgard-thor-einherjar", worker)


if __name__ == "__main__":
    unittest.main()
