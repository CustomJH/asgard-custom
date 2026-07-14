#!/usr/bin/env python3
"""프레이야 전용 스킬 자가 검증 — 양 스코프 스캐폴드 배선 + 본문 계약 앵커 + 코어 스킬 단일 소스.

실행: uv run pytest tests/test_freyja.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.templates.freyja import FREYJA_SKILLS, freyja_core_skill  # noqa: E402

_SKILL_NAMES = ("asgard-freyja-brisingamen", "asgard-freyja-motion", "asgard-freyja-video", "asgard-freyja-folkvangr")


class TestScaffold(unittest.TestCase):
    def test_plan_contains_freyja_skills_cc(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=False, root="/tmp/x")
        paths = [p for p, _ in files]
        for sname in _SKILL_NAMES:
            self.assertTrue(any(p.endswith(os.path.join(sname, "SKILL.md")) for p in paths), sname)
        # CC 는 서브에이전트(role)가 실체 — 코어 스킬은 .agents 스코프 전용 (중복 배치 금지)
        self.assertFalse(any(p.endswith(os.path.join("asgard-freyja", "SKILL.md")) for p in paths))

    def test_plan_contains_freyja_skills_agents_scope(self):
        from asgard.commands.setup import plan_files

        for flags in ({"cc": False, "cursor": True, "codex": False}, {"cc": False, "cursor": False, "codex": True}):
            files, _ = plan_files(root="/tmp/x", **flags)
            agents_paths = [p for p, _ in files if f"{os.sep}.agents{os.sep}" in p]
            for sname in (*_SKILL_NAMES, "asgard-freyja"):  # 모드 A 는 코어 계약 스킬 포함
                self.assertTrue(any(sname in p for p in agents_paths), (sname, flags))


class TestCoreSkillSingleSource(unittest.TestCase):
    def test_core_derives_from_role_body(self):
        from asgard.templates.roles import ROLE_AGENTS

        core = freyja_core_skill()
        role_body = dict(ROLE_AGENTS)["asgard-freyja.md"].split("---", 2)[2].lstrip()
        self.assertTrue(core.startswith("---\nname: asgard-freyja\n"))
        self.assertTrue(core.endswith(role_body))  # 본문 = role 파일 그대로 (단일 소스)
        self.assertNotIn("model:", core.split("---", 2)[1])  # role frontmatter 누출 없음


class TestSkillBodies(unittest.TestCase):
    """본문 계약 — 조사로 확정한 핵심 앵커가 빠지면 스킬의 존재 이유가 사라진다."""

    def setUp(self):
        self.by_name = dict(FREYJA_SKILLS)

    def test_frontmatter(self):
        for sname, body in FREYJA_SKILLS:
            self.assertTrue(body.startswith(f"---\nname: {sname}\n"), sname)

    def test_taste_anchors(self):
        taste = self.by_name["asgard-freyja-brisingamen"]
        self.assertIn("브리프 해석 선언", taste)
        self.assertIn("제네릭 자기점검", taste)
        for cliche in ("#F4F1EA", "01/02/03", "eyebrow"):  # 세대별 AI 티 목록 실존
            self.assertIn(cliche, taste)
        self.assertIn("액센트 화면당 ≤3회", taste)
        self.assertIn("Discovery Trace", taste)  # 레퍼런스 참조 보고 의무
        self.assertIn("밋밋함 방지", taste)  # 분위기·깊이 기법 카탈로그
        for archetype in ("정밀 미니멀", "다크 터미널", "럭셔리 절제"):  # 아키타입 카드 실존
            self.assertIn(archetype, taste)
        # taste-skill v2 전수 발굴분 (26-07-14) — 정량 규율·리디자인·카피 이진 금지
        self.assertIn("⌈섹션 수/3⌉", taste)  # eyebrow 정량 상한 (실측 1위 위반 항목)
        self.assertIn("엠대시 0개", taste)  # 이진 금지 ("아껴 쓰라"는 무시된다)
        self.assertIn("침묵 변경 금지", taste)  # 리디자인 모드 — URL/폼 필드/애널리틱스 보호
        self.assertIn("선언한 모션은 보여야 한다", taste)  # 다이얼 선언≠실행 방지
        self.assertIn("100dvh", taste)  # 풀높이 히어로 주소창 함정
        # 로고·브랜드 자산 (26-07-15 실증 + 오딘 레퍼런스 3종 증류 — "유치함" 피드백 교정)
        self.assertIn("로고는 그림이 아니라 기하다", taste)  # 벡터 우선
        self.assertIn("원샷 수용 금지", taste)  # 아트 디렉팅 루프
        self.assertIn("변형 6종 강제", taste)  # 같은 아이디어 6벌 금지
        self.assertIn("여백 ≥40%", taste)  # 조형 수치 계약
        self.assertIn("옵티컬 보정", taste)  # 오버슛·시각적 중심·조사 현상
        self.assertIn("마스코트화", taste)  # 유치함의 공식
        self.assertIn("가변 아이덴티티 세트", taste)  # 2026 트렌드
        self.assertIn("트렌드는 이동한다", taste)  # 재조사 의무
        self.assertIn("의미 1문장", taste)  # 형상의 존재 이유

    def test_motion_anchors(self):
        motion = self.by_name["asgard-freyja-motion"]
        self.assertIn("65–75%", motion)  # 퇴장 = 진입의 65-75%
        self.assertIn("transform / opacity 만", motion)
        self.assertIn("prefers-reduced-motion", motion)
        self.assertIn("asgard-freyja-video", motion)  # 도메인 상호 참조 (오염 방지)
        self.assertIn("연출 3막", motion)  # 진입/앰비언트/인터랙션 층 분리
        # taste-skill v2 GSAP 캐논 발굴분 — 스크롤 내러티브 함정
        self.assertIn('start: "top top"', motion)  # 핀 시작점 대표 실패
        self.assertIn("scrollWidth - innerWidth", motion)  # 수평 팬 거리 공식
        self.assertIn("엔진 혼용 금지", motion)  # 같은 트리 프레임 경합

    def test_video_anchors(self):
        video = self.by_name["asgard-freyja-video"]
        self.assertIn("CSS transition/animation 은 렌더에 반영되지 않는다", video)
        self.assertIn("상용 라이선스", video)  # Remotion 도입 전 라이선스 게이트
        self.assertIn("정지 프레임 검증", video)
        self.assertIn("asgard-freyja-motion", video)

    def test_folkvangr_anchors(self):
        fk = self.by_name["asgard-freyja-folkvangr"]
        self.assertIn("색공간 이분법", fk)  # 색 텍스처만 sRGB, 데이터 맵 금지
        self.assertIn("min(devicePixelRatio, 2)", fk)  # 픽셀비 클램프
        self.assertIn("bias -0.0001", fk)  # 그림자 acne 수치
        self.assertIn("드로우콜 ≤100", fk)  # 자체 설계 예산 게이트 (원본에 없던 축)
        self.assertIn("dispose", fk)  # GPU 메모리 규율
        self.assertIn("AA 항상 마지막", fk)  # 포스트 패스 순서 계약
        self.assertIn("asgard-freyja-video", fk)  # 영상 산출 시 결정론 우선 (오염 방지)
        self.assertIn("씬이 상속한다", fk)  # 통합 원칙 — 토큰 계획이 씬을 지배

    def test_domain_isolation_declared(self):
        # 영상↔웹모션 규칙 혼용 금지가 양쪽 본문에 명시 — 상호 오염 방지의 핵심 계약
        self.assertIn("섞지 않는다", self.by_name["asgard-freyja-motion"])
        self.assertIn("웹 모션 규칙이 무효", self.by_name["asgard-freyja-video"])


class TestA11yCanon(unittest.TestCase):
    """접근성 캐논 (26-07-15 고도화) — 표본 3종 실측(Lighthouse 100×2 + 행동 검증 14항)으로 증류한 계약.
    role 이 단일 소스이므로 코어 스킬(모드 A)에도 자동 상속된다."""

    def setUp(self):
        from asgard.templates.roles import ROLE_AGENTS

        self.role = dict(ROLE_AGENTS)["asgard-freyja.md"]

    def test_canon_section_exists(self):
        self.assertIn("접근성 캐논", self.role)

    def test_form_contract(self):
        for anchor in ("aria-describedby", "aria-invalid", "첫 오류 필드로 포커스 이동", 'role="status"'):
            self.assertIn(anchor, self.role)

    def test_widget_patterns(self):
        for anchor in ("roving tabindex", 'role="switch"', "포커스 복귀", "<dialog>"):
            self.assertIn(anchor, self.role)

    def test_document_skeleton(self):
        for anchor in ("<html lang>", "skip 링크"):
            self.assertIn(anchor, self.role)

    def test_dual_encoding_and_limits(self):
        self.assertIn("색으로만 전하지 않는다", self.role)
        self.assertIn("3–4할만 잡는다", self.role)  # 자동 감사 한계 — 키보드 실측 의무의 근거

    def test_industrial_hmi_extension(self):
        # 산업 환경 확장 (26-07-15 goal) — ISA-101/18.2·ISO 3864·9241-303 증류, HMI 벤치 실측 통과
        self.assertIn("산업 환경 확장", self.role)
        self.assertIn("회색 캔버스", self.role)
        self.assertIn("채도는 알람의 전유물", self.role)
        self.assertIn("안전색은 예약어", self.role)
        self.assertIn("미확인 알람만 점멸", self.role)
        self.assertIn("≥15mm", self.role)  # 타깃은 px 가 아니라 mm
        self.assertIn("2단 확인", self.role)  # 파괴 조작
        self.assertIn("380%", self.role)  # ASM 실증 — 목표는 예쁨이 아니라 상황 인식
        self.assertIn("적록 토글 금지", self.role)


class TestModeAWiring(unittest.TestCase):
    def test_agents_md_routes_visual_work_to_freyja_skill(self):
        from asgard.templates.agents import agents_md

        md = agents_md("p")
        self.assertIn("`asgard-freyja` 스킬", md)  # 모드 A 인라인 수행 경로
        self.assertIn("디자인·프론트엔드·모션", md)  # 확장된 도메인 라벨


if __name__ == "__main__":
    unittest.main(verbosity=1)
