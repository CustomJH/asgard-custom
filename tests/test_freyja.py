#!/usr/bin/env python3
"""프레이야 전용 스킬 자가 검증 — 양 스코프 스캐폴드 배선 + 본문 계약 앵커 + 코어 스킬 단일 소스.

실행: uv run pytest tests/test_freyja.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.templates.freyja import FREYJA_SKILLS, freyja_core_skill, resolve_freyja_skills  # noqa: E402

_SKILL_NAMES = (
    "asgard-freyja-brisingamen",
    "asgard-freyja-motion",
    "asgard-freyja-video",
    "asgard-freyja-folkvangr",
    "asgard-freyja-hildisvini",
    "asgard-freyja-seidr",
    "asgard-freyja-valshamr",
    "asgard-freyja-valkyrja",
)


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
        self.assertIn("판정 위계", taste)  # 수치=바닥, 미감=승부처 (26-07-17 굿하트 교훈)
        self.assertIn("극단 제약은 가변 세트가 흡수한다", taste)  # 16px 이 풀 마크를 지배하면 오판
        self.assertIn("취향 선언(앵커)", taste)  # 오딘이 반응한 자산은 밀어낼 기본값이 아니다
        self.assertIn("트렌드는 이동한다", taste)  # 재조사 의무
        self.assertIn("의미 1문장", taste)  # 형상의 존재 이유
        # 인쇄물 절 (26-07-15 QC 스윕 유보 사항 종결 — 팜플렛 실증에서 증류)
        self.assertIn("콜로폰 동봉 의무", taste)  # CMYK 근사·용지·교정쇄 명시
        self.assertIn("브라우저는 실인쇄를 검증 못 한다", taste)  # 한계 정직 보고

    def test_taste_pixel_craft_anchors(self):
        # 26-07-16 강화 — impeccable·brandkit·figma-implement·designer-skills·실측 기준선 증류
        taste = self.by_name["asgard-freyja-brisingamen"]
        self.assertIn("2차 반사 검사", taste)  # 카테고리 반사 — 회피의 정형화도 반사
        self.assertIn("placeholder 텍스트도 대비 4.5:1", taste)  # 가독성 파괴 1위 실측
        self.assertIn("999/9999", taste)  # z-index 시맨틱 스케일
        self.assertIn("드리프트 3분류", taste)  # 폴리시 순서 — 분류별 수리법
        self.assertIn("8상태", taste)  # 인터랙티브 전수 점검
        self.assertIn("−2%~−6%", taste)  # 디스플레이 트래킹 실측 대역
        self.assertIn("표면 명도 사다리", taste)  # 다크 무섀도 — 실측 드롭섀도 0
        self.assertIn("5질문", taste)  # 브랜드 서사 전략 게이트
        self.assertIn("브랜드 킷 문서", taste)  # 보드 패널 시퀀스
        self.assertIn("핸드오프 문서", taste)  # 전달 문서 5섹션 계약
        self.assertIn("해피패스만 적힌 스펙은 스펙이 아니다", taste)
        self.assertIn("스크린샷 기준선", taste)  # 디자인 컨텍스트 구현 — 기준선 선확보
        self.assertIn("placeholder 생성 금지", taste)  # figma-implement 금지 조항

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

    def test_motion_review_anchors(self):
        # 26-07-16 강화 — design-motion-principles(3렌즈·빈도)·impeccable animate·MoVer 절차화
        motion = self.by_name["asgard-freyja-motion"]
        self.assertIn("빈도 게이트", motion)
        self.assertIn("키보드 개시 동작", motion)  # 키보드 = 애니메이션 금지
        self.assertIn("80ms", motion)  # 즉시 지각 임계
        self.assertIn("절제 렌즈", motion)  # 3렌즈 — 컨텍스트 가중
        self.assertIn("모션 갭 감사", motion)  # 없는 모션도 결함
        self.assertIn("슬롭 지문", motion)  # 빈도 임계 달린 7종
        self.assertIn("93.6%", motion)  # MoVer 검증-반복 실측
        self.assertIn("실패한 술어만", motion)  # 표적 수정 — 전체 재생성 금지

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

    def test_hildisvini_anchors(self):
        hv = self.by_name["asgard-freyja-hildisvini"]
        self.assertIn("도구 사다리", hv)  # 세션 도구 → 기존 스택 → 신규(Canon 7 동의)
        self.assertIn("고정 sleep 금지", hv)  # 조건 기반 대기
        self.assertIn("test-id", hv)  # 셀렉터 위계
        self.assertIn("nth-child", hv)  # 구조 의존 셀렉터 경고
        self.assertIn("콘솔 오류 0", hv)  # 증거 수집 — 관찰 없는 주장 금지
        self.assertIn("2뷰포트", hv)
        self.assertIn("해피패스만은 검증이 아니다", hv)  # 파괴 경로 골격
        self.assertIn("핸들러를 선등록", hv)  # dialog 함정
        self.assertIn("쿠키·스토리지·세션을 시나리오마다 초기화", hv)  # 상태 격리
        self.assertIn("판정은 Verifier 몫", hv)  # 게이트 경계
        self.assertIn("asgard-worker-testing", hv)  # 테스트 계층 상호 참조
        # 26-07-16 강화 — webapp-testing·playwright-skill 조사 증류
        self.assertIn("모드 이분법", hv)  # 검증 headless vs 시각 반복 headed
        self.assertIn("network idle", hv)  # 하이드레이션 전 스냅샷 = 유령 화면
        self.assertIn("서버 수명주기", hv)  # 기동·대기·정리 책임

    def test_seidr_anchors(self):
        # 인터랙티브 피규어 (26-07-16 신설) — Victor/Case/Distill 캐논 + 구현 불변식
        sd = self.by_name["asgard-freyja-seidr"]
        self.assertIn("존재 이유 게이트", sd)  # 5효용 중 하나에만 해당해야 인터랙션
        self.assertIn("5효용", sd)
        self.assertIn("10–15%", sd)  # NYT 실측 — 핵심 정보 호버 은닉 금지의 근거
        self.assertIn("추상화 사다리", sd)
        self.assertIn("멱등 render()", sd)  # 중앙 state — 핸들러는 상태만 갱신
        self.assertIn("setPointerCapture", sd)  # 마우스·터치·펜 통합
        self.assertIn("touch-action: none", sd)  # 모바일 스크롤 충돌 방지
        self.assertIn("dirty 플래그", sd)  # Canvas — 변화 없으면 그리지 않는다
        self.assertIn("IntersectionObserver", sd)  # 스크롤리텔링 폴백 계층
        self.assertIn("스크롤은 항상 사용자 소유", sd)  # 하이재킹 금지
        self.assertIn("빈 화면·0값 시작 금지", sd)  # 초기 상태 유의미
        self.assertIn("APG", sd)  # 커스텀 슬라이더 접근성 패턴
        self.assertIn("asgard-freyja-motion", sd)  # 수치 캐논 상속 상호 참조

    def test_valshamr_anchors(self):
        # 채점 루브릭·판정 반복 루프 (26-07-16 신설) — 논문 근거 보상 신호 절차
        vs = self.by_name["asgard-freyja-valshamr"]
        self.assertIn("8축 실측 루브릭", vs)
        self.assertIn("−2~−6%", vs)  # 디스플레이 트래킹 실측 대역 (Stripe/Linear/Geist)
        self.assertIn("자기선호 편향", vs)  # 자기채점 금지의 근거
        self.assertIn("렌더 스크린샷", vs)  # 채점 입력은 코드가 아니라 렌더
        self.assertIn("실패 축·실패 술어만", vs)  # 표적 수정
        self.assertIn("최고안", vs)  # 역대 최고안 보존 + 하락 롤백
        self.assertIn("어떤 축도 하락 없음", vs)  # 수락 조건
        self.assertIn("2–4회 캡", vs)  # LLM 판정 수확체감
        self.assertIn("Awwwards", vs)  # 총점 해석 캘리브레이션
        self.assertIn("기계로 잴 수 있는 것을 인상으로 채점하지 않는다", vs)
        self.assertIn("게이트 통과 후에 잰다", vs)  # role 13축 게이트와의 관계
        self.assertIn("판정은 Verifier 몫", vs)  # 검증 독립성 — 게이트 경계
        self.assertIn("arXiv 2403.03163", vs)  # 논문 실명 인용 실존

    def test_valkyrja_anchors(self):
        # 발키리 편대 (26-07-17 신설) — 팀 시각 작업 프로토콜, 멀티에이전트 논문 근거
        vk = self.by_name["asgard-freyja-valkyrja"]
        self.assertIn("구조(서브 N기 편성)로 강제한다", vk)  # 절차는 지시문이 아니라 구조
        self.assertIn("0.877 → 3턴 0.707", vk)  # Multi-IF 지시 이행률 감쇠 — 단독 실패의 근거
        self.assertIn("편성 판정", vk)  # 효과 배분 — 토큰 ~15배 세금 정당화
        self.assertIn("~15배", vk)
        self.assertIn("N=3–5", vk)  # 변주 병렬 포화
        self.assertIn("변주 병렬(안전) vs 부품 분담(위험)", vk)  # Cognition 경계 조건
        self.assertIn("변주 축 지정", vk)  # 같은 브리프 N벌 금지 — 축 분배
        self.assertIn("새 컨텍스트", vk)  # 대장 히스토리 미상속 — context rot
        self.assertIn("MANIFEST.md", vk)  # 파일 기반 핸드오프 + 결정 복제
        self.assertIn("계획 장부", vk)  # Magentic-One 이중 장부
        self.assertIn("계획 자체를 재작성", vk)  # 정체 2회 → 재계획
        self.assertIn("생성자≠판정자", vk)  # 자기선호 편향 방어
        self.assertIn("상호참조 정련", vk)  # MoA — 1단 선택으로 끝내지 않는다
        self.assertIn("외부 모델 연계", vk)  # codex 류 CLI — 자문 + 산출 위임 양 경로
        self.assertIn("산출 위임", vk)  # 외부 모델을 변주 생성 서브로 편성 (26-07-17 오딘 지시)
        self.assertIn("기준을 세우는 손과 그리는 손이 달라도 계약은 하나다", vk)
        self.assertIn("codex", vk)
        self.assertIn("판정 권한은 이양되지 않는다", vk)
        self.assertIn("로고 캐논 레시피", vk)  # 아트 디렉팅 루프의 편대 구조화
        self.assertIn("패턴 축 분배", vk)
        # 판정 위계 (26-07-17 로고 편대 실측 교훈 — 굿하트 방어)
        self.assertIn("바닥(탈락 기준)이지 우승 기준이 아니다", vk)
        self.assertIn("취향 앵커 의무", vk)  # 오딘이 반응한 방향의 정련 계승 축 1기
        self.assertIn("편대의 최종 보상 신호는 기계가 아니라 오딘의 눈이다", vk)
        self.assertIn("깊이 1", vk)  # 편대의 편대는 없다
        self.assertIn("Verifier 가 부르지 않는다", vk)  # 검증 독립성
        self.assertIn("단독 폴백", vk)  # 편대 불가 환경 — 체크리스트 게이트
        self.assertIn("2411.04468", vk)  # 논문 실명 인용 실존

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


class TestMarkdownTables(unittest.TestCase):
    """GFM 표 구조 검사 — 헤더/구분/본문 열 수 불일치는 렌더링에서 열이 통째로 잘린다
    (26-07-15 리뷰: 디자인 시스템 표 4열 본문이 2열 헤더로 절반 소실). 문자열 앵커로 못 잡는 부류."""

    @staticmethod
    def _table_blocks(text: str):
        block: list[str] = []
        for line in text.splitlines() + [""]:
            s = line.strip()
            if s.startswith("|") and s.endswith("|"):
                block.append(s)
            else:
                if len(block) >= 2:
                    yield block
                block = []

    def _assert_consistent(self, name: str, text: str):
        for block in self._table_blocks(text):
            widths = {len(row.strip("|").split("|")) for row in block}
            self.assertEqual(len(widths), 1, f"{name}: 표 열 수 불일치 {sorted(widths)} — {block[0][:60]}")

    def test_all_skill_bodies(self):
        for sname, body in FREYJA_SKILLS:
            self._assert_consistent(sname, body)

    def test_role_body(self):
        from asgard.templates.roles import ROLE_AGENTS

        self._assert_consistent("asgard-freyja.md", dict(ROLE_AGENTS)["asgard-freyja.md"])

    def test_design_system_rows_survive(self):
        # 리뷰에서 잘려나가던 4개 매핑이 각자 온전한 행으로 실존
        taste = dict(FREYJA_SKILLS)["asgard-freyja-brisingamen"]
        for row in ("| Google·Material 제품 | Material 3 |", "| GitHub 풍 devtool | Primer |"):
            self.assertIn(row, taste)


class TestSkillResolver(unittest.TestCase):
    """네이티브 디스패치 스킬 주입 (26-07-15 리뷰 [높음]) — asgard start 에는 파일 스킬 로더가
    없으므로 task 매칭 본문을 system 에 직접 주입한다. 리졸버가 그 라우팅 계약이다."""

    def test_routing(self):
        cases = {
            "랜딩 페이지 히어로를 수려하게": "asgard-freyja-brisingamen",
            "카드 호버 전환 애니메이션 추가": "asgard-freyja-motion",
            "설명 영상 mp4 렌더": "asgard-freyja-video",
            "3D 제품 뷰어 셰이더": "asgard-freyja-folkvangr",
            "playwright e2e 시나리오 작성": "asgard-freyja-hildisvini",
            "브라우저에서 화면 실측 검증": "asgard-freyja-hildisvini",
            "설명용 인터렉티브 피규어 제작": "asgard-freyja-seidr",
            "파라미터 슬라이더로 조작하는 시뮬레이션 도표": "asgard-freyja-seidr",
            "산출물 루브릭 채점과 반복 개선": "asgard-freyja-valshamr",
            "히어로 퀄리티 벤치마크 비교": "asgard-freyja-valshamr",
            "로고 시스템을 변주 편대로 제작": "asgard-freyja-valkyrja",
            "codex 교차 자문으로 시안 비교": "asgard-freyja-valkyrja",
        }
        for task, expected in cases.items():
            names = [n for n, _ in resolve_freyja_skills(task)]
            self.assertIn(expected, names, task)

    def test_fail_open_on_no_match(self):
        self.assertEqual(resolve_freyja_skills("버튼 라벨 오타 수정"), [])

    def test_no_false_positive_on_generic_three(self):
        # "three" 단독 부분 일치가 일반 문장에 3D 스킬을 주입하던 오탐 (26-07-15 리뷰 실측)
        self.assertEqual(resolve_freyja_skills("three files need merging"), [])
        names = [n for n, _ in resolve_freyja_skills("three.js 씬에 파티클")]
        self.assertEqual(names, ["asgard-freyja-folkvangr"])  # 구체화된 표기는 여전히 매칭

    def test_design_context_routes_to_brisingamen(self):
        # 이미지→코드 경로 누락 (26-07-15 리뷰) — Figma·시안·스크린샷·목업 구현
        for task in ("Figma 시안을 React로 구현", "스크린샷대로 만들어줘", "목업 그대로 코딩"):
            names = [n for n, _ in resolve_freyja_skills(task)]
            self.assertIn("asgard-freyja-brisingamen", names, task)

    def test_injected_body_has_no_frontmatter(self):
        for _, body in resolve_freyja_skills("히어로 모션 영상 3d 전부"):
            self.assertFalse(body.startswith("---"))
            self.assertNotIn("\nname: asgard-freyja-", body.split("\n\n")[0])

    def test_multi_domain_injects_all(self):
        names = [n for n, _ in resolve_freyja_skills("3D 히어로에 스크롤 모션")]
        self.assertIn("asgard-freyja-brisingamen", names)
        self.assertIn("asgard-freyja-motion", names)
        self.assertIn("asgard-freyja-folkvangr", names)

    def test_heimdall_dispatch_wired(self):
        # 배선 실존 — 디스패치 핸들러가 리졸버 레지스트리를 실제로 사용한다 (주입 계약의 소비 지점)
        import inspect

        from asgard.agent import heimdall
        from asgard.agent.heimdall import Heimdall

        self.assertIn("_skill_resolver", inspect.getsource(Heimdall._dispatch_handler))
        registry_src = inspect.getsource(heimdall._skill_resolver)
        self.assertIn("resolve_freyja_skills", registry_src)
        self.assertIn("resolve_thor_skills", registry_src)


class TestQualityGateSurfaces(unittest.TestCase):
    """게이트 표면 분리 (26-07-15 리뷰 [중간]) — 브랜드 표면 13축 vs 실무 표면(10·11·앰비언트 면제)."""

    def setUp(self):
        from asgard.templates.roles import ROLE_AGENTS

        self.role = dict(ROLE_AGENTS)["asgard-freyja.md"]

    def test_surface_split_declared(self):
        self.assertIn("브랜드 표면", self.role)
        self.assertIn("실무 표면", self.role)

    def test_brand_verdict_formula_explicit(self):
        # 총점만으론 10·11 동시 실패가 통과 가능 — 판정식이 AND 를 명시해야 한다 (26-07-15 리뷰)
        self.assertIn("총점 ≥11/13 AND 축 10·11·12 전부 통과", self.role)
        self.assertIn("점수로 상쇄 불가", self.role)

    def test_practical_surface_exemption(self):
        self.assertIn("면제", self.role)
        self.assertIn("③ 인터랙션 응답과 나머지 축(1–9, 13)은 그대로", self.role)  # 면제는 앰비언트류만

    def test_report_format_carries_surface(self):
        self.assertIn("`품질 게이트 N/13 (브랜드)` 또는 `N/11 (실무)`", self.role)


class TestPrintBleedContract(unittest.TestCase):
    """도련 산출 계약 (26-07-15 리뷰 [중간]) — 선언만으론 미완: 확장 + 출력면 실측 검증까지."""

    def setUp(self):
        self.taste = dict(FREYJA_SKILLS)["asgard-freyja-brisingamen"]

    def test_bleed_output_contract(self):
        self.assertIn("도련 산출 계약", self.taste)
        self.assertIn("216×303mm", self.taste)  # A4 + 3mm 도련 출력면
        self.assertIn("TrimBox/BleedBox", self.taste)
        self.assertIn("도련 끝까지 실제로 확장", self.taste)

    def test_delivery_line_includes_bleed(self):
        self.assertIn("(풀블리드면) 위 도련 산출 계약 실측까지", self.taste)


class TestFreyjaLead(unittest.TestCase):
    """시각 편대장 (26-07-17 신설) — 대장 프레이야만 재위임 봉인을 연다. 서브는 봉인 유지."""

    def setUp(self):
        from asgard.templates.roles import ROLE_AGENTS

        self.roles = dict(ROLE_AGENTS)
        self.lead = self.roles["asgard-freyja-lead.md"]

    def test_role_registered_with_delivery_tier(self):
        from asgard.templates.roles import delivery_agents

        self.assertEqual(delivery_agents().get("freyja-lead"), "standard")  # 네이티브 디스패치 enum 자동 편입

    def test_lead_frontmatter_has_agent_tool(self):
        frontmatter = self.lead.split("---", 2)[1]
        self.assertIn("Agent", frontmatter)  # 편성 권한 — 봉인의 유일한 예외
        self.assertIn("Verifier 는 금지", frontmatter)  # 검증 독립성은 동일

    def test_cc_whitelist_lead_open_sub_sealed(self):
        from asgard.agent.tool_kernel import ROLE_CAPABILITIES, cc_tools_for_role

        self.assertIn("Agent", cc_tools_for_role("freyja-lead"))
        self.assertNotIn("Agent", cc_tools_for_role("freyja"))  # 서브 프레이야 재위임 봉인 유지
        self.assertIn("coordinate", ROLE_CAPABILITIES["freyja-lead"])
        self.assertNotIn("coordinate", ROLE_CAPABILITIES["freyja"])

    def test_lead_contract_anchors(self):
        for anchor in (
            "asgard-freyja-valkyrja",  # 팀 프로토콜 단일 소스 로드 의무
            "편성 판정 먼저",  # 소형 과업 편대 금지 — 토큰 세금
            "MANIFEST.md",  # 결정 복제 핸드오프
            "판정 분리",  # 생성자≠판정자
            "깊이 1",  # 서브 재위임 불가
            "완료 선언 금지",
        ):
            self.assertIn(anchor, self.lead)

    def test_sub_freyja_squad_membership_contract(self):
        sub = self.roles["asgard-freyja.md"]
        self.assertIn("편대 소속 시", sub)  # MANIFEST 상속·변주 축 준수·반환 규격
        self.assertIn("편대는 asgard-freyja-lead 의 표면", sub)  # 직접 편성 금지 — 판단 반환
        self.assertIn("재위임 불가 — 하위 에이전트를 만들지 않는다", sub)  # 봉인 문구 보존

    def test_heimdall_resolver_covers_lead(self):
        import inspect

        from asgard.agent import heimdall

        src = inspect.getsource(heimdall._skill_resolver)
        self.assertIn('"freyja-lead"', src)  # 편대장 디스패치에도 전용 스킬 주입

    def test_routing_agents_md_and_worker(self):
        from asgard.templates.agents import agents_md

        md = agents_md("p")
        self.assertIn("asgard-freyja-lead", md)  # 대형 시각 과업 라우팅
        self.assertIn("asgard-freyja-valkyrja", md)  # 모드 A 편대 스킬 경로
        self.assertIn("예외 1개: asgard-freyja-lead", md)  # 재위임 불가 예외의 명시적 한정
        worker = self.roles["asgard-worker.md"]
        self.assertIn("asgard-freyja-lead", worker)
        self.assertIn("발키리 스킬을 로드해 대장 역할", worker)  # 네이티브 순차 편대 경로


class TestModeAWiring(unittest.TestCase):
    def test_agents_md_routes_visual_work_to_freyja_skill(self):
        from asgard.templates.agents import agents_md

        md = agents_md("p")
        self.assertIn("시각·프론트 하위작업이면 `asgard-freyja`", md)  # 모드 A 인라인 수행 경로
        self.assertIn("백엔드 하위작업이면 `asgard-thor`", md)
        self.assertIn("빌드·CI 하위작업이면 `asgard-eitri`", md)
        self.assertIn("브라우저 UI·시각·모션·3D·영상", md)  # 변경 표면 기준 도메인 라벨

    def test_verifier_dispatch_isolated(self):
        # 26-07-15 리뷰 [높음] — 공통 문구가 Verifier 에 freyja/thor 를 허용하면 검증 독립성 붕괴
        from asgard.templates.agents import agents_md

        md = agents_md("p")
        self.assertNotIn("Worker·Verifier 는 하위 딜리버리", md)  # 합쳐진 라우팅 문구 재발 방지
        self.assertIn("asgard-loki(adversarial, read-only)만", md)
        self.assertIn("Verifier 의 freyja/thor/eitri 디스패치는 금지", md)

    def test_freyja_frontmatter_excludes_verifier(self):
        # 26-07-15 3차 리뷰 — CC 에이전트 선택 메타데이터(frontmatter description)가
        # Verifier 디스패치를 다시 허용하면 공통 계약 분리가 무력화된다
        from asgard.templates.roles import ROLE_AGENTS

        role = dict(ROLE_AGENTS)["asgard-freyja.md"]
        frontmatter = role.split("---", 2)[1]
        self.assertNotIn("Worker/Verifier", frontmatter)
        self.assertIn("Verifier 는 금지", frontmatter)
        self.assertIn("Verifier 의 프레이야 디스패치는 금지", role)  # 본문도 동일 계약


if __name__ == "__main__":
    unittest.main(verbosity=1)
