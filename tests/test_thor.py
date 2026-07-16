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

_SKILL_NAMES = (
    "asgard-thor-mjollnir",
    "asgard-thor-lightning",
    "asgard-thor-megingjord",
    "asgard-thor-jarngreipr",
)


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
        self.assertIn("백엔드 전문가", self.thor)
        self.assertIn("asgard-eitri 소관", self.thor)  # 빌드·CI 는 에이트리로 경계 명시
        self.assertNotIn("빌드·인프라 전문가", self.thor)  # 구 정체 잔존 금지

    def test_thor_diagnosis_gate_scoped_to_defects(self):
        # Codex #8 — 게이트는 버그·회귀·장애 한정, STOP 조건은 검증 가능한 사실
        self.assertIn("버그·회귀·성능 장애 한정", self.thor)
        for cond in ("재현 실패", "실제 호출 경로 미확인", "상충하는 증거 미해소"):
            self.assertIn(cond, self.thor)

    def test_thor_side_effect_approval_model(self):
        # Codex #2 — 승인 축 = 환경 × 외부 부작용, Worker 배정 ≠ 승인
        self.assertIn("환경 × 외부 부작용", self.thor)
        self.assertIn("Worker 의 과업 배정은 승인이 아니다", self.thor)

    def test_thor_skill_composition_not_exclusion(self):
        # Codex #5 — 혼용 금지가 아니라 합성 규칙 (야른그레이프르 = 오버레이)
        self.assertIn("배타가 아니라 **합성**", self.thor)
        self.assertIn("안전 오버레이", self.thor)
        for sname in _SKILL_NAMES:
            self.assertIn(sname, self.thor)

    def test_thor_frontmatter_excludes_verifier(self):
        frontmatter = self.thor.split("---", 2)[1]
        self.assertIn("Verifier 는 금지", frontmatter)

    def test_eitri_contracts(self):
        self.assertIn("로컬-CI 패리티", self.eitri)
        self.assertIn("상한 5회", self.eitri)  # verify-fix 루프 상한
        self.assertIn("로컬 아티팩트 생성·검증까지", self.eitri)  # 릴리스 경계 (Codex #2)
        self.assertIn("asgard-thor 소관", self.eitri)  # 런타임 경계
        self.assertIn("disallowedTools: Agent", self.eitri)

    def test_worker_routes_by_change_surface(self):
        # Codex #1 — Worker 라우팅 계약이 단일 소스: 이걸 안 고치면 과업이 계속 구 토르로 간다
        self.assertIn("asgard-thor", self.worker)
        self.assertIn("asgard-eitri", self.worker)
        self.assertIn("변경 표면 기준", self.worker)
        self.assertNotIn("빌드·CI·인프라 = asgard-thor", self.worker)  # 구 라우팅 잔존 금지


class TestSkillBodies(unittest.TestCase):
    """본문 계약 — 설계로 확정한 핵심 앵커가 빠지면 스킬의 존재 이유가 사라진다."""

    def setUp(self):
        self.by_name = dict(THOR_SKILLS)

    def test_frontmatter(self):
        for sname, body in THOR_SKILLS:
            self.assertTrue(body.startswith(f"---\nname: {sname}\n"), sname)

    def test_mjollnir_anchors(self):
        m = self.by_name["asgard-thor-mjollnir"]
        self.assertIn("배치 내구성 계약", m)  # 재시작 생존 계약
        for anchor in ("체크포인트", "재진입점", "부분 실패"):
            self.assertIn(anchor, m)
        self.assertIn("outbox", m)  # 메시징 신뢰성 (Codex #7)
        self.assertIn("DLQ", m)
        self.assertIn("멱등", m)
        self.assertIn("N+1", m)
        self.assertIn("락 순서 일관성", m)

    def test_lightning_anchors(self):
        li = self.by_name["asgard-thor-lightning"]
        self.assertIn("타임아웃 계층화", li)
        self.assertIn("서킷 브레이커", li)
        self.assertIn("실시간 사다리", li)  # 폴링 → SSE → WebSocket
        self.assertIn("무효화 전략을 먼저 쓰지 못하면 캐시 도입 금지", li)
        self.assertIn("SSRF", li)  # 서버 보안 경계 (Codex #7)
        self.assertIn("IDOR", li)
        self.assertIn("타임아웃·부분 실패·보상 없이는 외부 호출이 아니다", li)

    def test_megingjord_anchors(self):
        mg = self.by_name["asgard-thor-megingjord"]
        self.assertIn("liveness", mg)
        self.assertIn("readiness", mg)
        self.assertIn("의존성 캐스케이드 금지", mg)
        self.assertIn("graceful shutdown", mg)
        self.assertIn("무상태 우선", mg)
        self.assertIn("관측성 최소 계약", mg)  # Codex #7
        self.assertIn("asgard-eitri 소관", mg)  # 빌드 경계 상호 참조

    def test_jarngreipr_anchors(self):
        j = self.by_name["asgard-thor-jarngreipr"]
        self.assertIn("오버레이", j)  # 단독 아닌 합성 (Codex #5)
        for grade in ("🟢", "🟡", "🔴", "⚫"):  # 안전 등급 매트릭스
            self.assertIn(grade, j)
        self.assertIn("expand-contract", j)
        self.assertIn("승인은 Odin 몫", j)  # Codex #2
        self.assertIn("실측 쿼리 계획", j)


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
            {"freyja", "freyja-lead", "thor", "eitri", "loki", "mimir"},
        )
        for label in ("thor=백엔드", "eitri=빌드"):
            self.assertIn(label, DISPATCH_TOOL["description"])


if __name__ == "__main__":
    unittest.main()
