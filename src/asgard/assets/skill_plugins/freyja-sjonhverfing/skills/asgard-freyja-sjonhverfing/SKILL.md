---
name: asgard-freyja-sjonhverfing
description: "Freyja's depth-on-a-plane technique layer — Sjónhverfing (시욘흐베르핑, 눈속임). Use for pseudo-3D on 2D surfaces: perspective and preserve-3d space building, pointer tilt, flip cards, coverflow rings, layered parallax, extruded type, isometric projection, scroll-driven depth, and anime.js v4 (animate / createTimeline / createAnimatable / onScroll / createScope) as the value engine. Ships a dependency-free deterministic depth gate. This is a technique layer, not a delivery engine: whichever Freyja engine owns the surface keeps its own gates and closes the work."
---

# Sjónhverfing — 평면 위의 깊이

세이드의 눈속임에서 이름을 가져왔다. 사가에서 sjónhverfing 은 없는 것을 보이게 하는 술법이다. 이 스킬의 전제도 같다: **화면은 끝까지 평면이고, 깊이는 평면 위에 만든 믿음이다.**

한 문장으로 된 정신 모형이 이 스킬의 전부다.

> **CSS 가 공간을 짓고, anime.js 는 값을 움직인다.**

공간이 지어지지 않은 곳에서 `rotateY` 를 애니메이션하면 요소는 회전하지 않는다. 그냥 가로로 눌린다. 이 한 가지가 의사 3D 결함의 대부분이다.

## 이 스킬이 아닌 것

배달 엔진이 아니다. 화면을 소유한 엔진(1·2·4)이나 형상을 소유한 엔진(3)의 게이트를 대체하지 않는다. 여기서 고르는 것은 **기법**이고, 배달 여부는 그 엔진이 정한다. 충돌하면 이 스킬이 진다 — `engine/reference/compose.md`.

## 고정 순서

1. **사다리에서 칸을 고른다** — `engine/reference/depth-ladder.md`. 깊이는 0단부터 5단까지 있고, 뜻을 전달하는 **가장 낮은 칸**을 고른다. 5단(진짜 3D)이면 여기서 멈추고 엔진 3(`asgard-freyja-3d`)으로 넘긴다.
2. **공간을 짓는다** — `engine/reference/css-3d.md`. 원근 뿌리, 유지할 3D 문맥, 평면화 목록, 뒷면, 적중 영역, 글자 선명도. 값을 움직이기 전에 공간이 먼저다.
3. **값을 움직인다** — `engine/reference/animejs.md`. v4 API(`animate` · `createTimeline` · `createAnimatable` · `onScroll` · `createScope`), 변환 순서 함정, v3 와의 차이, three.js 어댑터 경계.
4. **형태를 고른다** — `engine/reference/recipes.md`. 층 시차·기울기 카드·뒤집기·고리·상자·두께 글자·아이소메트릭·스크롤 달리. 각 레시피는 사다리의 칸과 필요한 공간을 함께 적는다.
5. **잰다** — `node engine/scripts/depth_gate.mjs <경로>`. 판정 10개, 미판정 5개. 침묵은 통과가 아니다.
6. **배달 엔진의 게이트를 돌린다** — `engine/reference/compose.md` 의 조합표대로. 이 스킬의 게이트를 통과한 것은 "깊이가 죽지 않았다"는 뜻이지 "배달해도 된다"는 뜻이 아니다.
7. **본다** — `engine/reference/verify.md`. 소스로 판정할 수 없는 네 가지를 이름으로 보고한다.

## 런타임

```bash
node engine/scripts/depth_gate.mjs <파일|디렉터리> [...] [--json] [--report] [--severity warn|fail]
```

의존성 없음(node 내장 모듈만, node 18+). 설치·네트워크·브라우저를 요구하지 않는다. CSS·HTML·JS/TS·Vue·Svelte·Astro 를 읽는다.

| 게이트 | 무엇을 잡는가 |
|---|---|
| **D1** fail | 원근 없는 깊이 — `rotateX/Y`·`translateZ` 가 있는데 `perspective` 가 어디에도 없다. 눌린 2D 축소로 보인다 |
| **D2** fail | 같은 규칙이 `preserve-3d` 와 평면화 속성(`overflow`·`filter`·`opacity<1`·`clip-path`·`contain`…)을 함께 선다 |
| **D3** fail | 깊이 모션에 `prefers-reduced-motion` 경로가 없다 |
| **D4** fail | v4 를 임포트해 놓고 v3 전역 API(`anime.timeline()`)를 부른다 — 런타임에서 죽는다 |
| **D5** warn | 180° 뒤집기에 `backface-visibility` 가 없다 — 두 면이 겹쳐 보인다 |
| **D6** warn | 포인터 이벤트마다 `style.transform` 을 직접 쓴다 — 프레임 배칭이 없다 |
| **D7** warn | 원근 거리 400px 미만 — UI 크기 요소가 어안렌즈로 일그러진다 |
| **D8** warn | `will-change` 가 `*`·`body` 같은 광역 선택자에 걸려 있다 |
| **D9** warn | 멈출 길 없는 3D 무한 회전 |
| **D10** warn | v3 전용 API — v4 가 현행 메이저다 |

`--report` 는 `.asgard/.vanadis/sjonhverfing/` 에 JSON 을 남긴다. `.asgard/` 는 이미 git 밖이므로 **별도 ignore 항목을 만들지 않고, 커밋을 제안하지도 않는다.**

## 판정할 수 없는 것

게이트가 `unjudged` 로 내보내는 다섯은 기계가 못 보는 것이다. 조상 체인의 평면화(캐스케이드가 정한다), 회전한 글자의 선명도, 회전한 적중 영역과 초점 순서, 대상 기기의 프레임 예산, 그리고 **그 깊이가 값을 하는가**. 마지막 하나는 배달 엔진의 절제·슬롭 게이트가 판정한다. 나머지는 눈으로 본다.

자기 산출물에 스스로 매긴 점수는 리뷰가 아니다. 리뷰라고 부르지 말고 자기 보고라고 적는다.

## 불변

- 접근성 바닥은 내려가지 않는다. 깊이 모션에는 저감 경로가 있고, 저감은 삭제가 아니라 **평면으로의 대체**다 — 정보를 함께 지우지 않는다.
- 깊이로만 전달되는 정보는 없어야 한다. 기울여야 읽히는 글자, 돌려야 보이는 상태는 깊이가 아니라 숨김이다.
- 콘텐츠가 먼저 칠해지고 깊이는 그 위에 더해진다. JS 없이도, 애니메이션 클래스 없이도 기본 상태가 보여야 한다.
- 사용자 표면의 언어·이모지 규약, 증거 우선 보고는 Asgard 전역 규약 그대로다.
