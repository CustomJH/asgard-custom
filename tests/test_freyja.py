#!/usr/bin/env python3
"""프레이야 전용 스킬 자가 검증 — 양 스코프 스캐폴드 배선 + 본문 계약 앵커 + 코어 스킬 단일 소스.

실행: uv run pytest tests/test_freyja.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.templates.freyja import (  # noqa: E402
    _SKILL_BODY_BUDGET,
    FREYJA_SKILLS,
    freyja_core_skill,
    resolve_freyja_skills,
)

_SKILL_NAMES = (
    "asgard-freyja-brisingamen",
    "asgard-freyja-hnoss",
    "asgard-freyja-gersemi",
    "asgard-freyja-print",
    "asgard-freyja-hmi",
    "asgard-freyja-syn",
    "asgard-freyja-reference-atlas",
    "asgard-freyja-logo-studio",
    "asgard-freyja-gullveig",
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
        for archetype in ("정밀 미니멀", "다크 터미널", "럭셔리 절제"):  # 아키타입 카드 실존
            self.assertIn(archetype, taste)
        # taste-skill v2 전수 발굴분 (26-07-14) — 정량 규율·리디자인·카피 이진 금지
        self.assertIn("⌈섹션 수/3⌉", taste)  # eyebrow 정량 상한 (실측 1위 위반 항목)
        self.assertIn("엠대시 0개", taste)  # 이진 금지 ("아껴 쓰라"는 무시된다)
        self.assertIn("침묵 변경 금지", taste)  # 리디자인 모드 — URL/폼 필드/애널리틱스 보호
        self.assertIn("선언한 모션은 보여야 한다", taste)  # 다이얼 선언≠실행 방지
        self.assertIn("Geist+Geist Mono", taste)  # 서체 출발 페어링 — 금지 일변도에 양성 가이드 보강
        self.assertIn("2차 반사 검사", taste)  # 카테고리 반사 — 회피의 정형화도 반사
        self.assertIn("−2%~−6%", taste)  # 디스플레이 트래킹 실측 대역
        self.assertIn("핸드오프 문서", taste)  # 전달 문서 5섹션 계약
        self.assertIn("해피패스만 적힌 스펙은 스펙이 아니다", taste)
        # 심화 위임 라우팅 (26-07-17 분해) — 코어가 자매 스킬을 지명
        self.assertIn("심화 위임", taste)
        for sibling in ("asgard-freyja-hnoss", "asgard-freyja-gersemi", "asgard-freyja-print"):
            self.assertIn(sibling, taste)
        self.assertIn("로고는 그림이 아니라 기하다", taste)  # 위임 포인터에도 핵심 계약 1줄 유지
        self.assertIn("원샷 수용 금지", taste)

    def test_gersemi_surface_anchors(self):
        # 표면·마감 (26-07-17 분해 — 브리싱가멘에서 이관): 색 엔진·그림자·깊이·광학 감사
        g = self.by_name["asgard-freyja-gersemi"]
        self.assertIn("밋밋함 방지", g)  # 분위기·깊이 기법 카탈로그
        self.assertIn("해독제는 일괄 장식이 아니라 다이얼 정합", g)
        self.assertIn("100dvh", g)  # 풀높이 히어로 주소창 함정 (광학 감사)
        self.assertIn("placeholder 텍스트도 대비 4.5:1", g)  # 가독성 파괴 1위 실측
        self.assertIn("999/9999", g)  # z-index 시맨틱 스케일
        self.assertIn("드리프트 3분류", g)  # 폴리시 순서 — 분류별 수리법
        self.assertIn("8상태", g)  # 인터랙티브 전수 점검
        self.assertIn("표면 명도 사다리", g)  # 다크 무섀도 — 실측 드롭섀도 0
        self.assertIn("스크린샷 기준선", g)  # 디자인 컨텍스트 구현 — 기준선 선확보
        self.assertIn("placeholder 생성 금지", g)  # figma-implement 금지 조항

    def test_gersemi_material_ladder(self):
        # 그래픽 재료 사다리 (26-07-17 — "SVG 만능주의 표현 부자연" 오딘 피드백 교정)
        g = self.by_name["asgard-freyja-gersemi"]
        self.assertIn("그래픽 재료 사다리", g)
        self.assertIn("직접 그리기의 경계는 기하다", g)  # 유기 곡선·장면부터 재료를 가져온다
        self.assertIn("api.iconify.design", g)  # 아이콘은 완성 SVG 인라인 박제 (라이브 검증 URL)
        self.assertIn("currentColor", g)  # 색 주입 대신 CSS 상속 — 다크 공짜
        self.assertIn("feTurbulence", g)  # 노이즈는 data-URI
        self.assertIn("2408.08313", g)  # SGP-Bench — 코드→시각 역상상 불능 실증
        self.assertIn("자기완결 납품 = 재료도 파일 안에", g)
        # 로고 스튜디오에도 손 SVG 경계 명시 (26-07-17 확장: 단순 기하 → 기하 유도 조형까지)
        self.assertIn("손 SVG 정본은 기하 유도 조형 한정", self.by_name["asgard-freyja-logo-studio"])

    def test_logo_canon_merged_into_studio(self):
        # 로고 조형·아트 디렉팅 캐논 (26-07-17 분해 — 브리싱가멘에서 logo-studio 로 병합)
        logo = self.by_name["asgard-freyja-logo-studio"]
        self.assertIn("변형 6종 강제", logo)  # 같은 아이디어 6벌 금지
        self.assertIn("여백 ≥40%", logo)  # 조형 수치 계약
        self.assertIn("옵티컬 보정", logo)  # 오버슛·시각적 중심·조사 현상
        self.assertIn("마스코트화", logo)  # 유치함의 공식
        self.assertIn("가변 아이덴티티 세트", logo)  # 2026 트렌드
        self.assertIn("판정 위계", logo)  # 수치=바닥, 미감=승부처 (26-07-17 굿하트 교훈)
        self.assertIn("극단 제약은 가변 세트가 흡수한다", logo)
        self.assertIn("취향 선언(앵커)", logo)  # 오딘이 반응한 자산은 밀어낼 기본값이 아니다
        self.assertIn("트렌드는 이동한다", logo)  # 재조사 의무
        self.assertIn("의미 1문장", logo)  # 형상의 존재 이유
        self.assertIn("소유 가능성 충돌 검사", logo)
        self.assertIn("16px·32px·64px·512px 실제 CSS 픽셀 렌더", logo)
        self.assertIn("법적 클리어런스가 아님", logo)
        self.assertIn("5질문", logo)  # 브랜드 서사 전략 게이트
        self.assertIn("브랜드 킷 문서", logo)  # 보드 패널 시퀀스

    def test_print_skill_anchors(self):
        # 인쇄물 (26-07-17 분해 — 전용 스킬로 이관)
        pr = self.by_name["asgard-freyja-print"]
        self.assertIn("콜로폰 동봉 의무", pr)  # CMYK 근사·용지·교정쇄 명시
        self.assertIn("브라우저는 실인쇄를 검증 못 한다", pr)  # 한계 정직 보고

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

    def test_generated_asset_adapter_boundaries(self):
        gen = self.by_name["asgard-freyja-gullveig"]
        self.assertIn("필터 없는 전체 목록", gen)
        self.assertIn("Recraft V4.1", gen)
        self.assertIn("후보를 정본으로 승격할 수 있다", gen)
        self.assertIn("워드마크는 생성 결과를 그대로 확정하지 않는다", gen)
        self.assertIn("추가 유료 웨이브·영상·배포·마켓 공개", gen)
        self.assertIn("토르", gen)
        self.assertIn("에이트리", gen)
        self.assertIn("commit 9ab6483", gen)

    def test_logo_studio_imported_workflow(self):
        logo = self.by_name["asgard-freyja-logo-studio"]
        for anchor in (
            "최소 6개",
            "순수 기하",
            "점 매트릭스",
            "선 시스템",
            "노드 네트워크",
            'viewBox="0 0 100 100"',
            "currentColor",
            "interactive showcase",
            "16·32·64·512",
            "reference-assisted vectorization",
            "최소 하나를 고르지 않는다",
            "좌표 산술은 실제 래스터 검사가 아니다",
            "일반 글자나 사물로 읽힌다고 NOTES가 인정하면 자동 탈락",
            "질량·곡률·terminal",
            "IBM Plex Sans·Inter",
            "font·license·버전·outline 변환 계보",
        ):
            self.assertIn(anchor, logo)
        self.assertIn("asgard-freyja-reference-atlas", logo)

    def test_reference_atlas_requires_diverse_evidence_board(self):
        atlas = self.by_name["asgard-freyja-reference-atlas"]
        for anchor in (
            "세계관 일치가 아니라",
            "3개 이상의 서로 다른 산업",
            "docs/design/freyja-reference-atlas.md",
            "REFERENCE-BOARD.md",
            "공식 브랜드 가이드",
            "형태를 복제하지 않는다",
            "참조 축",
        ):
            self.assertIn(anchor, atlas)
        # 26-07-18 강화 (Open Design reference-design-contract·brand-extract 증류)
        self.assertIn("신뢰도 라벨", atlas)  # observed/provided/inferred — 브랜드 사실 발명 금지
        self.assertIn("observed", atlas)
        self.assertIn("형용사는 구체 제약으로 번역", atlas)  # "프리미엄" → 실행 가능한 제약
        self.assertIn("기존 브랜드 실측 추출", atlas)  # 기억 추측 = Inter·인디고 회귀
        self.assertIn("7 시맨틱 역할", atlas)

    def test_syn_state_and_form_anchors(self):
        # 26-07-18 신설 — Open Design craft(state-coverage·form-validation) 증류
        syn = self.by_name["asgard-freyja-syn"]
        self.assertIn("5상태", syn)  # 로딩/빈/에러/채워짐/엣지 전수
        self.assertIn("무한 스피너 금지", syn)
        self.assertIn("빈 상태 4종", syn)
        self.assertIn("에러 3질문 순서", syn)
        self.assertIn("재시도 규율", syn)  # 백오프 2/4/8s + 에러 ID
        self.assertIn("첫 blur 후 검사", syn)  # 검증 타이밍의 정본
        self.assertIn(":user-invalid", syn)  # :invalid 스타일링 금지
        self.assertIn("붙여넣기 차단 절대 금지", syn)  # WCAG 3.3.8
        self.assertIn('setCustomValidity("")', syn)  # null 은 미해제
        self.assertIn("이중 낭독", syn)  # 요약 컨테이너 role=alert 금지

    def test_syn_laws_a11y_rtl_anchors(self):
        syn = self.by_name["asgard-freyja-syn"]
        for law in ("Hick", "Miller/Cowan", "Peak-End", "Zeigarnik", "Postel", "Tesler"):
            self.assertIn(law, syn)
        self.assertIn("24×24 CSS px", syn)  # AA 바닥 (44 는 AAA — 통설 교정)
        self.assertIn("18pt(≈24px)", syn)  # "큰 텍스트" 경계값 교정
        self.assertIn("ARIA 는 정확성 빚", syn)  # WebAIM 실측 — 네이티브 우선 4단
        self.assertIn("letter-spacing 절대 금지", syn)  # 아랍어 연결 문자
        self.assertIn('<bdi dir="ltr">', syn)  # 전화·IBAN 약문자 강제
        self.assertIn("미러 X", syn)  # 시계·미디어 스크러버·차트 축은 불변

    def test_craft_distillation_anchors(self):
        # 26-07-18 강화 — Open Design craft 코퍼스의 기존-스킬 편입분
        taste = self.by_name["asgard-freyja-brisingamen"]
        self.assertIn("#6366f1", taste)  # 인디고 하드코딩 대역 = 최다 검증 티
        self.assertIn("압박 부사", taste)  # "쉽게·간단히·빠르게" 금지
        self.assertIn("3역할 명명", taste)  # 웨이트 400–450/500–550/600
        hnoss = self.by_name["asgard-freyja-hnoss"]
        self.assertIn("위계 5벡터", hnoss)  # 지배 요소 1 + 벡터 ≥2
        self.assertIn("에디토리얼 타이포 캐논", hnoss)  # 디스플레이/데크 ≥1.5× 낙차
        self.assertIn("표준 시퀀스", hnoss)  # Hero→…→CTA 무변주 = 템플릿 골격
        gersemi = self.by_name["asgard-freyja-gersemi"]
        self.assertIn("필(배경) 전용", gersemi)  # 저대비 액센트 역할 분리
        self.assertIn("overscroll-behavior", gersemi)  # 마감 감사 확장
        motion = self.by_name["asgard-freyja-motion"]
        self.assertIn("교육용 모션은 실증 기각", motion)  # Tversky 2002 메타분석
        self.assertIn("루프 상한", motion)  # WCAG 2.2.2·2.3.1 법적 바닥
        self.assertIn("명명 함정 2종", motion)  # M2/M3 이징·스프링 default 상반
        self.assertIn("View Transitions API 는 reduced-motion 을 자동 존중하지 않는다", motion)

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
        # 26-07-17 관문 대조 실측 — 요약 전달 편대가 쇼케이스 문법·옵티컬 보정을 잃고 퇴화
        self.assertIn("도메인 스킬 원문 동봉", vk)  # 브리프 ⑦ — 재서술은 손실 압축
        self.assertIn("손실 압축", vk)
        self.assertIn("폴백에서도 심화 스킬 원문을 로드", vk)  # 단독 폴백도 원문 실행
        self.assertIn("예산은 폭이 아니라 깊이로 마감한다", vk)  # 승자 정련·연출 몫 보존
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
        self.assertIn("일반 Y/A/가지/그래프 아이콘으로 환원", vk)
        self.assertIn("NOTES 자기평가를 독립 판정 증거로 사용하지 않는다", vk)
        self.assertIn("깊이 1", vk)  # 편대의 편대는 없다
        self.assertIn("Verifier 가 부르지 않는다", vk)  # 검증 독립성
        self.assertIn("단독 폴백", vk)  # 편대 불가 환경 — 체크리스트 게이트
        self.assertIn("2411.04468", vk)  # 논문 실명 인용 실존

    def test_domain_isolation_declared(self):
        # 영상↔웹모션 규칙 혼용 금지가 양쪽 본문에 명시 — 상호 오염 방지의 핵심 계약
        self.assertIn("섞지 않는다", self.by_name["asgard-freyja-motion"])
        self.assertIn("웹 모션 규칙이 무효", self.by_name["asgard-freyja-video"])


class TestUiSkillsRework(unittest.TestCase):
    """ui-skills.com 181종 전수 정독 재설계 (26-07-17) — 양성 레시피·레지스터·시드 변주·OKLCH 엔진.
    금지 일변도가 아니라 실행 가능한 수치 레시피가 결핍이었다는 진단의 계약 앵커."""

    def setUp(self):
        self.by_name = dict(FREYJA_SKILLS)
        self.taste = self.by_name["asgard-freyja-brisingamen"]
        self.motion = self.by_name["asgard-freyja-motion"]

    def test_design_plan_block_procedure(self):
        # 코드 전 플랜 블록: 레지스터 → 디자인 리드+장면 문장 → 다이얼 → 시드 변주 → 색 전략 → 플랜 검증
        self.assertIn("레지스터 판정", self.taste)
        self.assertIn("fluid clamp 비율 ≥1.25", self.taste)  # 브랜드 스케일
        self.assertIn("1.125–1.2", self.taste)  # 프로덕트 스케일
        self.assertIn("장면 문장", self.taste)  # 테마는 취향이 아니라 장면
        self.assertIn("변주 강제 (시드 셔플 + 전형성 탈출)", self.taste)
        self.assertIn("해시를 시드로", self.taste)
        self.assertNotIn("글자 수를 시드로", self.taste)
        self.assertIn("최종 선택 기준은 순서가 아니라 브리프 적합성 게이트", self.taste)
        self.assertIn("색 전략 4단", self.taste)
        self.assertIn("Restrained", self.taste)
        self.assertIn("플랜 자가 검증", self.taste)  # H1 수학·벤토 수학 사전 증명

    def test_layout_blueprints(self):
        # 양성 레시피 — 빈 캔버스에서 출발하지 않는다 (26-07-17 분해: hnoss 로 이관)
        hn = self.by_name["asgard-freyja-hnoss"]
        self.assertIn("레이아웃 청사진", hn)
        self.assertIn("AIDA", hn)
        self.assertIn("히어로 아키타입", hn)
        self.assertIn("grid-auto-flow: dense", hn)
        self.assertIn("이중 베젤", hn)  # 구조 장치 카탈로그
        self.assertIn("min-h-[100dvh]", hn)
        self.assertIn("인지부하 수치", hn)  # 내비 ≤5·지표 ≤4·티어 ≤3
        self.assertIn("분할 정복 생성", hn)  # DCGen — 섹션별 생성·검수 후 조립
        self.assertIn("2406.16386", hn)  # 논문 실명 인용 실존

    def test_oklch_color_engine(self):
        g = self.by_name["asgard-freyja-gersemi"]
        self.assertIn("색 엔진 (OKLCH", g)
        self.assertIn("대비 수리는 L 채널만", g)
        self.assertIn(">10°", g)  # 휴 드리프트 판정
        self.assertIn("L 매핑 역전", g)  # 다크 모드는 손으로 고르지 않는다
        self.assertIn("0.005–0.015", g)  # 틴트 뉴트럴 크로마 대역
        self.assertIn("60-30-10", g)

    def test_shadow_surface_recipes(self):
        g = self.by_name["asgard-freyja-gersemi"]
        self.assertIn("그림자·표면 캐논", g)
        self.assertIn("0 2px 3px -1px rgba(0,0,0,.1)", g)  # sm 정확 레시피
        self.assertIn("고스트카드 금지", g)  # 1px 보더 + blur ≥16px 동시 금지
        self.assertIn("표면 깊이 전략은 하나만", g)

    def test_weight_caps(self):
        # 무게 상한 (26-07-17 분해의 존재 이유) — "800줄 프롬프트가 40줄보다 나쁘다"(실무 실측)
        # + Context Rot: 입력 길이 증가만으로 성능 저하. 코어 재비대는 회귀다.
        sizes = {name: len(body) for name, body in FREYJA_SKILLS}
        self.assertLessEqual(sizes["asgard-freyja-brisingamen"], 10_500, "브리싱가멘 재비대 — 자매 스킬로 분해하라")
        for name, n in sizes.items():
            self.assertLessEqual(n, 10_500, f"{name} 과적재 — 스킬은 얇고 전부 현역이어야 한다")
        # role 은 상시 주입 계약 — 정본은 스킬로 위임하고 role 은 계약·게이트만 (26-07-17 다이어트)
        role_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "asgard", "templates", "roles", "asgard-freyja.md"
        )
        self.assertLessEqual(len(open(role_path).read()), 8_000, "role 재비대 — 정본을 스킬로 위임하라")

    def test_seed_variation_includes_atypicality(self):
        # Verbalized Sampling (2510.01171) — 전형성 편향 탈출이 시드 변주에 명문화
        self.assertIn("전형성", self.taste)
        self.assertIn("2510.01171", self.taste)

    def test_valshamr_research_reinforcement(self):
        vs = self.by_name["asgard-freyja-valshamr"]
        self.assertIn("하드 필터 선행", vs)  # 렌더 실패·오버플로·콘솔 에러는 미감 채점 전 탈락
        self.assertIn("인터랙션 미감", vs)  # 3축 분리 (WebGen-R1)
        self.assertIn("과제별 체크리스트", vs)  # 전역 인상 점수 금지 (ArtifactsBench)
        self.assertIn("피드백 형식", vs)  # 점수·순위가 아니라 코멘트·지목

    def test_motion_choreography_canon(self):
        # LottieFiles/motion-design-skill 증류 (26-07-17) — 강제 아닌 "채택 시 레시피"로 편입
        m = self.by_name["asgard-freyja-motion"]
        self.assertIn("거리-시간 스케일", m)  # 거리 2배 ≠ 시간 2배
        self.assertIn("오버슈트는 문맥 예산", m)  # 에러 0%·축하 15–25%
        self.assertIn("재질 은유", m)  # 종이/고무/물/금속
        self.assertIn("카운터모션이 무게를 만든다", m)
        self.assertIn("4막 구조", m)  # 예고→본동작→반응→정착
        self.assertIn("앰비언트 자격선", m)  # ±5% 초과 펄스는 주의 요구
        self.assertIn("텍스트 패럴랙스 절대 금지", m)
        self.assertIn("ease-out 이 더 빠르게 느껴진다", m)
        # 3레이어: 전면 의무화 기각, 브랜드 표면 기본값(옵트아웃)으로 절충 채택 (26-07-17 오딘 지시)
        self.assertIn("레이어 진폭비 — 브랜드 표면 기본값", m)
        self.assertIn("전면 의무화는 기각", m)
        self.assertIn("LottieFiles/motion-design-skill", m)

    def test_logo_organic_construction(self):
        # 유기·다이내믹 조형 구성법 (26-07-17 — 컨셉 B 계열 불합격 교정: 프리핸드 아닌 기하 유도)
        logo = self.by_name["asgard-freyja-logo-studio"]
        self.assertIn("유기·다이내믹 구성법", logo)
        self.assertIn("중첩 원 구성", logo)  # 반지름 2–3종 호 가족 + G1 접선 연속
        self.assertIn("두 원 빼기 스우시", logo)
        self.assertIn("오프셋 곡선 리본", logo)  # 가변 굵기 테이퍼
        self.assertIn("회전 복제", logo)  # rotate(360/n)
        self.assertIn("로그 나선", logo)  # 성장 서사의 기하 근거
        self.assertIn("하이브리드 그리드 선행", logo)
        self.assertIn("납품 매트릭스", logo)  # 레이아웃×색 + 금지 사용례
        # 모티프 메뉴 탈기본화 — 양 세대 동시 수렴 실측 (에코 아크)
        self.assertIn("같은 모티프 연속 2회 = 수렴 티", logo)

    def test_logo_asset_pipeline(self):
        # 에셋 조립 파이프라인 (26-07-17 — manus/Brandmark/op7418 리서치: 품질 = 에셋+페어링+채점 게이트)
        logo = self.by_name["asgard-freyja-logo-studio"]
        self.assertIn("에셋 조립 파이프라인", logo)
        self.assertIn("opentype.js", logo)  # 워드마크는 실제 폰트 아웃라인
        self.assertIn("불리언 실계산", logo)  # paper.js — 라이브러리 티 제거·좌표 환각 제거
        self.assertIn("흔한 모양 감점", logo)  # Brandmark 고유성 점수 등가물
        self.assertIn("무게 페어링", logo)  # 심볼-워드마크 광학 무게 정합
        self.assertIn("대량 생성 후 선별", logo)  # 후보 ≥8 → 게이트 선별
        self.assertIn("패턴 좌표 레시피", logo)  # op7418 — 동심원 점·캡슐 흐름·회전 스택
        self.assertIn("할당제 + 4차원 분산", logo)
        self.assertIn("쇼케이스 미세 타이포", logo)  # 6–9pt 3점 배치

    def test_logo_3d_showcase(self):
        fk = self.by_name["asgard-freyja-folkvangr"]
        self.assertIn("로고 3D 쇼케이스", fk)
        self.assertIn("SVGLoader.createShapes", fk)  # 압출 파이프라인 순서
        self.assertIn("scale.y *= -1", fk)  # SVG Y축 반전 필수
        self.assertIn("크게, 기울여, 잘라, 천천히", fk)  # 성숙 문법
        self.assertIn("검은 덩어리", fk)  # metalness 1 + no envmap 함정
        logo = self.by_name["asgard-freyja-logo-studio"]
        self.assertIn("로고 3D 쇼케이스", logo)  # 상호 참조

    def test_hero_living_element_mandate(self):
        # three.js 활용 경로 (26-07-17 오딘 피드백 "히어로 수려한 모션 부재")
        hn = self.by_name["asgard-freyja-hnoss"]
        self.assertIn("히어로 살아있는 요소 실장 의무", hn)
        self.assertIn("asgard-freyja-folkvangr", hn)  # 3D 앰비언트 경로 지명
        fk = self.by_name["asgard-freyja-folkvangr"]
        self.assertIn("히어로 앰비언트 씬", fk)  # 경량 공식 (파티클·자전·시차·reduced-motion 정지)
        self.assertIn("three.js CDN", fk)  # 단일 파일 데모 허용

    def test_hildisvini_interaction_operation(self):
        hv = self.by_name["asgard-freyja-hildisvini"]
        self.assertIn("인터랙션 실조작 검증", hv)  # 기능이 최대 실패 모드 (WebGen-Bench 27.8%)
        self.assertIn("27.8%", hv)

    def test_hmi_skill_extracted(self):
        # 산업 HMI (26-07-17 분해 — role 에서 이관, role 은 포인터만)
        from asgard.templates.roles import ROLE_AGENTS

        hmi = self.by_name["asgard-freyja-hmi"]
        for anchor in (
            "회색 캔버스",
            "채도는 알람의 전유물",
            "안전색은 예약어",
            "미확인 알람만 점멸",
            "≥15mm",
            "2단 확인",
            "380%",
            "적록 토글 금지",
        ):
            self.assertIn(anchor, hmi)
        role = dict(ROLE_AGENTS)["asgard-freyja.md"]
        self.assertIn("asgard-freyja-hmi", role)  # role 은 로드 포인터 유지
        self.assertNotIn("미확인 알람만 점멸", role)  # 본문은 이관 완료 (중복 금지)

    def test_typography_scale_canon(self):
        self.assertIn("clamp 상한 ≤6rem", self.taste)
        self.assertIn("타입 스케일은 5단이면 충분", self.taste)
        self.assertIn("font-synthesis: none", self.taste)
        self.assertIn("text-wrap: balance", self.taste)

    def test_self_gates_and_slop_test(self):
        self.assertIn("Swap 테스트", self.taste)
        self.assertIn("Squint 테스트", self.taste)
        self.assertIn("Signature 테스트", self.taste)
        self.assertIn("슬롭 테스트 2단", self.taste)
        self.assertIn("'AI 가 만들었네'라고 말할 수 있다면 실패다", self.taste)

    def test_output_completeness(self):
        self.assertIn("출력 완전성", self.taste)
        self.assertIn("[PAUSED — X of Y]", self.taste)
        self.assertIn("for brevity", self.taste)

    def test_new_decoration_tells(self):
        self.assertIn("스케치풍 SVG", self.taste)
        self.assertIn("32px+ 라운딩", self.taste)
        self.assertIn("Herding pixels", self.taste)  # 클리셰 로딩 카피
        self.assertIn("동사+목적어", self.taste)  # OK·Submit 금지

    def test_motion_named_curves_and_springs(self):
        self.assertIn("이징·스프링 명명 캐논", self.motion)
        self.assertIn("cubic-bezier(0.22, 1, 0.36, 1)", self.motion)
        self.assertIn("cubic-bezier(0.32, 0.72, 0, 1)", self.motion)  # 드로어·시트
        self.assertIn("stiffness 400 / damping 30", self.motion)
        self.assertIn("스프링 판단 기준은 하나다", self.motion)  # 사용자 반응 vs 시스템 통보

    def test_motion_reduced_motion_tiers_and_flags(self):
        self.assertIn("3계층 강등", self.motion)  # reduced-motion 은 킬스위치가 아니다
        self.assertIn("0.01ms", self.motion)  # 0s 는 transitionend 파손
        self.assertIn("transition: all", self.motion)  # 즉시 플래그
        self.assertIn("즉시 플래그", self.motion)
        self.assertIn("수정 우선순위 위계", self.motion)
        self.assertIn("닫힘에 delay 절대 금지", self.motion)
        self.assertIn("transform-origin", self.motion)  # 트리거에서 자란다

    def test_hildisvini_observation_surface(self):
        hv = self.by_name["asgard-freyja-hildisvini"]
        self.assertIn("접근성 트리 스냅샷", hv)  # 기본 관측면 — 스크린샷은 보조
        self.assertIn("가시적 델타", hv)  # 컴파일 통과는 기준이 아니다
        self.assertIn("DOM 안정화", hv)  # 고정 딜레이는 렌더 중간 샘플링

    def test_folkvangr_material_light_recipes(self):
        fk = self.by_name["asgard-freyja-folkvangr"]
        self.assertIn("transmission 1", fk)  # 유리 레시피
        self.assertIn("clearcoatRoughness 0.1", fk)  # 코팅 레시피
        self.assertIn("scene.environment", fk)  # IBL 이 라이트 추가보다 먼저

    def test_valshamr_negative_clauses_and_report(self):
        vs = self.by_name["asgard-freyja-valshamr"]
        self.assertIn("지적하지 말 것", vs)  # 음성 조항 — 과잉 교정 차단
        self.assertIn("근거 없는 발견보다 무발견이 낫다", vs)
        self.assertIn("Before/After/Why 표", vs)

    def test_role_carries_register_and_gates(self):
        from asgard.templates.roles import ROLE_AGENTS

        role = dict(ROLE_AGENTS)["asgard-freyja.md"]
        self.assertIn("레지스터 판정", role)
        self.assertIn("장면 문장", role)
        self.assertIn("Swap", role)  # 자기 게이트가 role 에서도 선언


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

    def test_industrial_hmi_pointer(self):
        # 산업 환경 (26-07-17 분해) — 본문은 asgard-freyja-hmi 스킬로 이관, role 은 로드 포인터
        self.assertIn("산업 환경", self.role)
        self.assertIn("asgard-freyja-hmi", self.role)
        self.assertIn("채도는 알람의 전유물", self.role)  # 포인터에도 핵심 1줄 유지
        self.assertIn("상황 인식", self.role)  # 목표는 예쁨이 아니다


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
            "Remotion 설명 영상 프레임 렌더": "asgard-freyja-video",
            "3D 제품 뷰어 셰이더": "asgard-freyja-folkvangr",
            "playwright UI e2e visual regression": "asgard-freyja-hildisvini",
            "브라우저에서 화면 실측 검증": "asgard-freyja-hildisvini",
            "설명용 인터렉티브 피규어 제작": "asgard-freyja-seidr",
            "파라미터 슬라이더로 조작하는 시뮬레이션 도표": "asgard-freyja-seidr",
            "산출물 루브릭 채점과 반복 개선": "asgard-freyja-valshamr",
            "히어로 퀄리티 벤치마크 비교": "asgard-freyja-valshamr",
            "로고 시스템을 변주 편대로 제작": "asgard-freyja-valkyrja",
            "제품 로고 SVG 6개와 interactive showcase 제작": "asgard-freyja-logo-studio",
            "다양한 로고 레퍼런스 리서치와 reference board 준비": "asgard-freyja-reference-atlas",
            "codex 교차 자문으로 시안 비교": "asgard-freyja-valkyrja",
            "Recraft로 로고 쇼케이스 이미지 생성": "asgard-freyja-gullveig",
            "Higgsfield 이미지 모델로 브랜드 목업": "asgard-freyja-gullveig",
            "gullveig 계약을 적용한 로고 제작": "asgard-freyja-gullveig",
            "굴베이그 계약을 적용한 로고 제작": "asgard-freyja-gullveig",
        }
        for task, expected in cases.items():
            names = [n for n, _ in resolve_freyja_skills(task)]
            self.assertIn(expected, names, task)

    def test_negative_routing_respects_declared_scope(self):
        cases = {
            "분기별 매출 정적 BI 차트 작성": "asgard-freyja-seidr",
            "paragraph typography spacing": "asgard-freyja-seidr",
            "브라우저로 상품 가격 수집 자동화": "asgard-freyja-hildisvini",
            "촬영한 광고 영상 편집": "asgard-freyja-video",
            "GLB 모델 생성": "asgard-freyja-folkvangr",
        }
        for task, excluded in cases.items():
            self.assertNotIn(excluded, [name for name, _ in resolve_freyja_skills(task)], task)

    def test_compound_visual_triggers_still_route(self):
        cases = {
            "interactive chart with a slider": "asgard-freyja-seidr",
            "UI e2e visual regression": "asgard-freyja-hildisvini",
            "Remotion frame render": "asgard-freyja-video",
            "three.js 3D scene integration": "asgard-freyja-folkvangr",
        }
        for task, expected in cases.items():
            self.assertIn(expected, [name for name, _ in resolve_freyja_skills(task)], task)

    def test_split_skill_routing(self):
        # 26-07-17 분해 — 자매 스킬이 과업 성격대로 붙는다
        cases = {
            # "수려하게" 류 모호 미감 요청은 코어(브리싱가멘)만 — 표면 스킬은 명시 키워드 시 (다이어트)
            "랜딩 페이지 히어로를 수려하게": {
                "asgard-freyja-brisingamen",
                "asgard-freyja-hnoss",
            },
            "다크 모드 팔레트 대비 폴리시": {"asgard-freyja-gersemi"},
            "행사 포스터 인쇄용 pdf 제작": {"asgard-freyja-print"},
            "scada 제어실 hmi 화면 설계": {"asgard-freyja-hmi"},
        }
        for task, expected in cases.items():
            names = {n for n, _ in resolve_freyja_skills(task)}
            self.assertTrue(expected.issubset(names), (task, names))

    def test_split_skill_negative_routing(self):
        # 부분 과업에 무관 청사진·표면 스킬이 끌려오지 않는다 (분해의 존재 이유)
        cases = {
            "버튼 컴포넌트 focus 상태 접근성 수정": {"asgard-freyja-hnoss", "asgard-freyja-print", "asgard-freyja-hmi"},
            "검색 결과 목록 정렬 로직 수정": {"asgard-freyja-gersemi"},  # "검색"이 "색" 오탐 금지
            "알람 시계 앱 UI": {"asgard-freyja-hmi"},  # 일반 앱 오탐 금지
        }
        for task, excluded in cases.items():
            names = {n for n, _ in resolve_freyja_skills(task)}
            self.assertFalse(excluded & names, (task, names))

    def test_fail_open_on_no_match(self):
        self.assertEqual(resolve_freyja_skills("버튼 라벨 오타 수정"), [])

    def test_no_false_positive_on_generic_three(self):
        # "three" 단독 부분 일치가 일반 문장에 3D 스킬을 주입하던 오탐 (26-07-15 리뷰 실측)
        self.assertEqual(resolve_freyja_skills("three files need merging"), [])
        names = [n for n, _ in resolve_freyja_skills("three.js 씬에 파티클")]
        self.assertEqual(names, ["asgard-freyja-folkvangr"])  # 구체화된 표기는 여전히 매칭

    def test_syn_routing(self):
        # 26-07-18 신설 — 실무 UX 캐논: 상태·폼·사용성·RTL 과업이 syn 을 부른다
        for task in (
            "회원가입 폼 검증 흐름 개선",
            "빈 상태 화면 디자인",
            "form validation UX",
            "아랍어 rtl 레이아웃 대응",
            "체크아웃 로딩 상태와 스켈레톤",
        ):
            names = [n for n, _ in resolve_freyja_skills(task)]
            self.assertIn("asgard-freyja-syn", names, task)
        # "플랫폼"·일반 문장이 syn 을 끌지 않는다 ("폼"·"상태" 단독 미채택의 존재 이유)
        for task in ("크로스 플랫폼 빌드 상태 점검", "버튼 라벨 오타 수정"):
            self.assertNotIn("asgard-freyja-syn", [n for n, _ in resolve_freyja_skills(task)], task)

    def test_design_context_routes_to_brisingamen(self):
        # 이미지→코드 경로 누락 (26-07-15 리뷰) — Figma·시안·스크린샷·목업 구현
        for task in ("Figma 시안을 React로 구현", "스크린샷대로 만들어줘", "목업 그대로 코딩"):
            names = [n for n, _ in resolve_freyja_skills(task)]
            self.assertIn("asgard-freyja-brisingamen", names, task)

    def test_injected_body_has_no_frontmatter(self):
        for _, body in resolve_freyja_skills("히어로 모션 영상 3d 전부"):
            self.assertFalse(body.startswith("---"))
            self.assertNotIn("\nname: asgard-freyja-", body.split("\n\n")[0])

    def test_multi_domain_prioritizes_specialists_within_budget(self):
        hits = dict(resolve_freyja_skills("3D 히어로에 스크롤 모션"))
        self.assertIn("asgard-freyja-motion", hits)
        self.assertIn("asgard-freyja-folkvangr", hits)
        self.assertIn("asgard-freyja-brisingamen", hits["asgard-freyja-deferred"])

    def test_composite_skill_injection_has_combined_cap(self):
        from asgard.agent.heimdall import _DELIVERY

        tasks = (
            "3D 히어로에 스크롤 모션",
            "웹사이트 UI UX 애니메이션 영상 3D 로고 포스터 HMI 편대",
            "Figma 시안 웹사이트 모션 다크 모드",
            "브랜드 로고 아이콘 워드마크 심볼 영상 모션 3D",
        )
        for task in tasks:
            with self.subTest(task=task):
                hits = resolve_freyja_skills(task)
                injected = sum(len(body) for name, body in hits if name != "asgard-freyja-deferred")
                self.assertLessEqual(injected, _SKILL_BODY_BUDGET)
                self.assertLessEqual(len(_DELIVERY["freyja-lead"]) + sum(len(body) for _, body in hits), 26_000)

    def test_budget_overflow_is_visible_as_redelegation_pointer(self):
        hits = dict(resolve_freyja_skills("웹사이트 UI UX 애니메이션 영상 3D 로고 포스터 HMI 편대"))
        pointer = hits["asgard-freyja-deferred"]
        self.assertIn("합산 예산 초과", pointer)
        self.assertIn("상위 Worker", pointer)
        self.assertIn("단독 재위임", pointer)

    def test_heimdall_dispatch_wired(self):
        # 배선 실존 — 디스패치 핸들러가 리졸버 레지스트리를 실제로 사용한다 (주입 계약의 소비 지점)
        import inspect

        from asgard.agent import heimdall
        from asgard.agent.heimdall import DeliveryDispatch

        self.assertIn("_skill_resolver", inspect.getsource(DeliveryDispatch.dispatch_handler))
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
        # 바닥 축은 무조건, 풍부함 축은 다이얼 정합 판정 (26-07-17 재설계 — 강제 장식이 새 AI 티를 만든다:
        # 참조 스킬 전부가 절제·다이얼 연동을 마감 원칙으로 둔다. 무조건 풍부함 강제는 다크 미니멀·공공
        # 브리프에서 과잉 장식을 생산하던 실측 결함)
        self.assertIn("바닥 축(1–9·13) 전부 통과 AND 풍부함 축(10–12)은 선언한 다이얼에 정합", self.role)
        self.assertIn("점수로 상쇄 불가", self.role)
        self.assertIn("강제 장식은 그 자체가 새로운 AI 티다", self.role)
        # 회피 양방향 봉쇄 — 선언 없는 정적 출고도, 근거 없는 하향 선언도 회피
        self.assertIn("프리셋 대비 −2 초과", self.role)

    def test_dark_surface_shadow_axis(self):
        # 축1 그림자가 다크 표면에 라이트 레시피를 강제하던 모순 해소 (브리싱가멘·발샴르의
        # "다크 무섀도+표면 사다리" 캐논과 게이트가 충돌 — 26-07-17 정합)
        self.assertIn("다크 표면은 무섀도 + 표면 명도 사다리", self.role)

    def test_role_declares_dial_source(self):
        # 게이트가 참조하는 다이얼의 출처 — 브리싱가멘 정본 + 스킬 미로드 폴백
        self.assertIn("변주·모션·밀도 다이얼(1–10)을 함께 선언", self.role)

    def test_practical_surface_exemption(self):
        self.assertIn("면제", self.role)
        self.assertIn("③ 인터랙션 응답과 나머지 축(1–9, 13)은 그대로", self.role)  # 면제는 앰비언트류만

    def test_report_format_carries_surface(self):
        self.assertIn("`품질 게이트 N/13 (브랜드)` 또는 `N/11 (실무)`", self.role)


class TestPrintBleedContract(unittest.TestCase):
    """도련 산출 계약 (26-07-15 리뷰 [중간]) — 선언만으론 미완: 확장 + 출력면 실측 검증까지.
    26-07-17 분해로 asgard-freyja-print 스킬이 정본."""

    def setUp(self):
        self.taste = dict(FREYJA_SKILLS)["asgard-freyja-print"]

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
            "asgard-freyja-logo-studio",
            "asgard-freyja-reference-atlas",
            "편성 판정 먼저",  # 소형 과업 편대 금지 — 토큰 세금
            "MANIFEST.md",  # 결정 복제 핸드오프
            "판정 분리",  # 생성자≠판정자
            "VISUAL-VERDICT.md",
            "NOTES 자기반증 우선",
            "deliverables/variations/<candidate-id>/mark.svg",
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
        self.assertIn("예외 2개: asgard-freyja-lead·asgard-thor-lead", md)  # 재위임 불가 예외의 명시적 한정
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
