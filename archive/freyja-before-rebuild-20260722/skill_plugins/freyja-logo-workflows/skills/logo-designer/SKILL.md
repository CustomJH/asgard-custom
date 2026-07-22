---
name: logo-designer
description: 저장소의 실제 제품·색·서체·기존 자산을 읽고 로고 브리프, 독립 시안, 사용자 선택, 정련, 축소 프리뷰, SVG/PNG 내보내기까지 운영하는 Freyja 로고 디렉팅 워크플로.
---

# Logo Designer — repo-aware direction and iteration

로고 요청에서 `asgard-freyja-logo-studio`와 함께 쓰는 **작업 순서 정본**이다. 조형 레시피는
`logo-generator`, 레퍼런스는 `asgard-freyja-reference-atlas`, 최종 실측은
`asgard-freyja-hildisvini`가 소유한다.

## 1. 이미 아는 것은 묻지 않는다

저장소가 있으면 README, 패키지 메타데이터, CSS/토큰, 폰트 로딩, 현재 favicon·앱 아이콘·로고,
제품 화면을 먼저 읽는다. 다음을 `BRIEF.md`에 `observed / provided / inferred`로 구분해 적는다.

- 정확한 브랜드명과 철자, 제품이 하는 일, 사용자, 주요 터치포인트
- 실제 팔레트와 서체·웨이트, 기존 디자인 언어와 보존할 취향 앵커
- 필요한 형식(icon / wordmark / combination), 최소 크기, 납품 대상
- 핵심 개념 2–3개, 피할 1차 클리셰, 왜 이 브랜드만 가질 수 있는지 한 문장

결정에 꼭 필요한 빈칸만 한 번에 묻는다. 상세 브리프가 이미 있으면 질문 없이 진행한다.

## 2. 탐색은 방향부터 분리한다

첫 웨이브는 **3–5개 의미적으로 독립된 방향, 총 6개 이상 후보**다. 같은 심볼의 색·회전·숫자만
바꾼 것은 별도 방향이 아니다. 각 방향에 서로 다른 메타포·실루엣·타입 관계를 배정하고 모든 제작자에게
같은 브리프, SVG 계약, 출력 경로를 준다.

복수 시안이 과업의 핵심이면 Freyja Lead가 `asgard-freyja-valkyrja`를 로드하고 서로 겹치지 않는 축으로
편대를 나눈다. 단일 수치 수정은 편대를 다시 열지 않고 선택한 SVG에 순차 적용한다.

산출 구조:

```text
deliverables/logo/
  BRIEF.md
  REFERENCE-BOARD.md
  concepts/<direction>/mark.svg
  concepts/<direction>/NOTES.md
  preview.html
  iterations/
  final/
```

## 3. 프리뷰가 선택 표면이다

`preview.html`은 후보를 같은 크기·같은 조건에서 나란히 보여준다.

- light / dark / monochrome 전환
- icon, wordmark, combination lockup 구분
- 각 후보의 512·64·32·16 CSS px 실렌더 스트립
- 후보별 의미 1문장, 고유 제스처, 예상 실패, 레퍼런스에서 일부러 다르게 한 점

큰 목업만으로 고르지 않는다. 16/32px, 흑백, 역상에서 직접 보지 못한 후보는 `UNVERIFIED`다.
대화형 작업은 사용자가 방향을 고르기 전에 임의로 `final/`을 만들지 않는다. 무인 실행이면 생성자와
분리된 visual verdict가 같은 비교면을 보고 선택한다.

## 4. 정련은 한 번에 한 변수

선택한 방향을 `iterations/iteration-N.svg`로 보존한다. 단일 피드백은 크기·간격·획·각도·색 중 한 축만
바꾸고, 3개 이상 비교가 필요한 피드백만 배치 변주한다. 매 반복에서 중요한 불변식과 작은 크기 스트립을
다시 확인한다. 문제가 사라질 때까지 전체 프롬프트를 갈아엎지 않는다.

## 5. 내보내기와 통합

최종 SVG는 자기완결이어야 한다: 외부 이미지·폰트·파일 참조 없음, 고정 width/height 없음, 논리 그룹 ID,
정확한 텍스트 또는 검증된 outline. 현재 환경의 기존 SVG 래스터라이저를 사용해 16, 32, 48, 192,
512, 1024, 2048 PNG를 만들고 실제 치수·알파·가독성을 확인한다. macOS에서는 설치 전 먼저
`qlmanage -t -s <px> -o <dir> <logo.svg>`도 확인한다. 변환기가 없으면 새 의존성을 자동 설치하지 말고
SVG와 미검증 상태를 보고한다.

프로젝트 통합은 이미 소비되는 favicon/PWA/app-icon 경로만 교체한다. 새 플랫폼 자산이나 PR·배포는 사용자가
요청했을 때만 한다. `MANIFEST.md`에 source SVG, 폰트·에셋 라이선스, 생성 도구·프롬프트, 선택·탈락 근거,
상표 유사성 검색 범위와 한계를 남긴다.

## 완료 게이트

- [ ] 저장소에서 확인 가능한 정보를 다시 묻지 않았다
- [ ] 3–5개 독립 방향과 총 6개 이상 후보가 있다
- [ ] 같은 조건의 프리뷰와 16/32/64/512 실렌더를 열어 봤다
- [ ] 사용자 선택 또는 독립 visual verdict 없이 승자를 확정하지 않았다
- [ ] 최종 SVG·PNG·MANIFEST의 파일·치수·철자·출처를 확인했다

출처: neonwatty/logo-designer-skill `8f9a4b04009c15b05eeb47b4608d5502abafa609` (MIT),
2026-02-24 원문 워크플로. Asgard의 Freyja 편대·검증 경계에 맞게 재서술했다.
