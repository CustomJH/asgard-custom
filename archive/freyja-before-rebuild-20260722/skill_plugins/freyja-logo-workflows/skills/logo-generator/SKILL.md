---
name: logo-generator
description: 6개 이상 로고 후보의 조형 분산, 정밀 SVG 구축, 워드마크, 옵티컬 보정, 반응형 세트, 쇼케이스와 상표 유사성 점검을 다루는 Freyja 로고 제작 방법론.
---

# Logo Generator — form, SVG, and evaluation method

`logo-designer`가 작업 순서를, 이 스킬이 **무엇을 어떻게 그려 판정할지**를 소유한다. 고정 숫자는 탐색
출발점과 탈락 바닥이지 미감 점수나 만능 공식이 아니다.

## 조형 탐색

후보 총수는 6개 이상이며 topology를 분산한다. 다음 계열에서 브리프에 맞는 축을 고르되
메뉴의 첫 항목을 기본값으로 쓰지 않는다.

1. solid geometry + rounded negative cut
2. modular lattice / geometric monogram
3. dense line system that forms visual mass
4. dot matrix with a deliberate void or removal
5. arc, capsule, or offset-ribbon flow derived from guides
6. symbol + wordmark relation or mixed composition

핵심 요소 1–2개, 초점 1개, 충분한 빈 공간에서 시작한다. `viewBox="0 0 100 100"` 기준 주 획 2.5–4,
요소 간격 8–12, 빈 공간 40–50%는 초기 안전선이다. 브리프가 신뢰·인장을 요구하면 대칭이 맞을 수 있고,
동세가 필요하면 의도적 비대칭을 쓴다. 비대칭 자체를 고급스러움의 증거로 삼지 않는다.

일반 전구·로켓·뇌·방패·공유·전원·네트워크 노드, 평범한 A/Y/C/G로 첫 독해되는 후보는 설명으로
구제하지 않는다. 브랜드명과 색을 가린 실루엣에 고유 제스처가 남아야 한다.

## SVG 정본 계약

- icon은 `viewBox="0 0 100 100"` 또는 512 정방형, wordmark/combination은 가로 viewBox를 쓴다.
- 고정 width/height 없음, 외부 파일·폰트·런타임 URL 없음, 의미 단위 `<g id="...">` 사용.
- 플랫 단색과 `currentColor`가 1차 정본. 그라디언트·질감·그림자는 형태가 통과한 뒤 쇼케이스에 격리.
- 단순 기하·원호 유도 곡선은 직접 SVG, 자유 유기 곡선·캐릭터는 생성 후보 후 anchor·곡률·교차를 수리해
  편집 가능한 벡터로 승격한다. 래스터 자동 추적만으로 끝내지 않는다.
- 반복 기하는 `<defs>/<use>` 또는 실제 불리언 계산으로 만들고, 최종 납품은 자기완결 path로 봉인한다.
- SVG 내부 애니메이션은 넣지 않는다. 모션 시드는 별도 데모가 source geometry를 재사용한다.

## 워드마크

생성 이미지의 글자를 정본으로 쓰지 않는다. 정확한 철자와 실제 폰트 control을 먼저 렌더하고, symbol과
wordmark의 광학 무게·cap height·간격·곡률·terminal을 맞춘다. outline이 필요하면 실제 글리프에서 만들고
font 이름·버전·라이선스·outline 변환 계보를 기록한다. 커스텀 레터폼은 적은 수의 terminal 또는 spacing
수정으로 시작하며 모든 글자를 임의 sci-fi path로 다시 그리지 않는다.

## 옵티컬·반응형 시스템

기하 중심과 시각 중심을 구분한다. 원·삼각형·뾰족점은 1–5% overshoot 후보를 비교하고, 밝은 마크가 어두운
배경에서 더 굵어 보이는 irradiation 때문에 positive/reverse 버전을 별도 실측한다. 하나의 SVG가 모든 크기를
억지로 버티게 하지 않는다.

- primary mark / compact mark / bold favicon crop
- horizontal combination / wordmark
- full color / mono / inverse
- clear space, minimum size, 금지 사용례

16px 성립은 favicon 변형의 책임이며 full mark의 섬세함을 무조건 죽이는 우승 기준이 아니다.

## 생성 모델과 쇼케이스

이미지·벡터 모델은 레퍼런스 탐색, topology 후보, 목업에 사용할 수 있다. 현재 연결된 도구와 실제 모델
카탈로그를 확인하고, 프롬프트에는 구조 장치·복제 금지·정확한 텍스트를 명시한다. 생성 결과는 SVG 정본 게이트를
통과한 뒤에만 source가 된다.

쇼케이스는 승자 확정 **후** 만든다. 먼저 white/black/mono/small-size 중립 보드에서 마크를 판정하고, 그 다음
제품 문맥에 맞는 2–4개 표면만 고른다: flat Swiss, editorial paper, dark void/studio, UI container 등. 화려한
배경이 약한 로고를 가리거나 mark geometry·색·비율을 바꾸면 실패다.

## 판정 게이트

1. XML/viewBox/외부 참조/철자/폰트 provenance 기계 검사
2. 16·24·32·64·512 실제 브라우저 또는 래스터 렌더
3. 흑백·역상·복잡 배경에서 legibility와 optical weight 비교
4. 이름·색을 가린 silhouette 기억성과 common glyph/object 충돌 검사
5. 후보끼리와 reference board 원본의 contour 근접성 검사
6. 별도 판정자의 브랜드 정합·제품 성숙도·워드마크 결속 verdict

상표 검색은 이름뿐 아니라 주요 design element와 관련 상품·서비스를 함께 본다. 자체 검색은 clearance의
한 단계일 뿐 법적 클리어런스가 아니며, 고위험 출시는 관할권 전문가 검토가 필요하다.

출처: op7418/logo-generator-skill `bf4e9ac4d4428bda261afcfe981871ceb92d94e6`
(upstream README의 MIT 선언), IBM 8-bar와 Atlassian 공식 logo usage, USPTO federal trademark searching.
원본의 6+ variant·SVG pattern·showcase 방법을 Asgard 품질 게이트에 맞게 재서술했다.
