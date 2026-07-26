# anime.js v4 — 값 엔진

MIT. 현행 메이저는 **v4** 이고, v3 와는 임포트부터 다르다. v4 에는 기본 내보내기가 없다 — `import anime from "animejs"` 는 v4 에서 `undefined` 다.

```js
import { animate, createTimeline, createAnimatable, createScope, onScroll,
         createSpring, stagger, utils, svg, waapi, engine, text } from "animejs";
```

의존성을 새로 들이기 전에 확인한다. 상태 하나 바뀌는 전환은 CSS `transition` 이 더 싸고 더 안전하다. anime.js 를 들이는 이유는 **중단·시퀀싱·동적 값·스크롤 동기화** 중 하나여야 한다.

## 깊이 작업에 쓰는 표면

| 필요 | API | 왜 |
|---|---|---|
| 한 번 일어나는 전환 | `animate(target, {…})` | 중단 가능하고 값이 동적일 때 |
| 여러 요소의 순서 | `createTimeline({ defaults })` + `.add()` | 되감기·시크가 필요하면 필수 |
| 포인터가 미는 값 | `createAnimatable(target, {…})` | **틸트의 정답** — 이벤트마다 스타일을 쓰지 않고 엔진의 한 프레임 루프에 모은다 |
| 스크롤이 미는 값 | `autoplay: onScroll({ sync })` | 스크롤 위치 → 진행률. 자체 스크롤 핸들러를 쓰지 않는다 |
| 저감 모션·정리 | `createScope({ mediaQueries }).add(fn)` | 미디어 쿼리를 일급으로 받고 `revert()` 로 통째로 되돌린다 |
| 목록의 시차 | `stagger(65, { from: "center" })` | 값·지연 어디에나 |
| 물리감 | `createSpring({ mass, stiffness, damping, velocity })` | `ease` 자리에 넣는다 |
| 값 계산 | `utils.clamp` · `remap` · `set` · `get` · `random` · `round` | 손으로 만든 보간 대신 |

## 변환 키

개별 변환을 이름으로 애니메이션한다. `perspective` 도 애니메이션 대상이다.

```
x (translateX) · y (translateY) · z (translateZ) · translateX/Y/Z
rotate · rotateX · rotateY · rotateZ
scale · scaleX/Y/Z · skew · skewX/Y · perspective
```

각도 기본 단위는 `deg`, 이동 기본 단위는 `px`. 문자열로 단위를 명시할 수 있다(`x: "15rem"`, `rotate: "1turn"`).

**순서는 고정이다.** anime.js 는 키를 쓴 순서와 무관하게 `perspective → translate → rotate → scale → skew` 로 조립한다. "회전한 뒤 밀어내기"(고리·궤도)는 이 단축 키로 표현되지 않는다 — 요소를 겹쳐 나눈다(`recipes.md` R4). `transform` 문자열을 통째로 다루고 싶으면 `waapi.animate(el, { transform: "…" })` 를 쓴다.

**anime.js 는 공간을 짓지 않는다.** `perspective` 를 애니메이션할 수는 있어도 `transform-style: preserve-3d` 나 `backface-visibility` 를 대신 걸어 주지 않는다. 그것은 CSS 의 일이다(`css-3d.md`).

## 포인터 틸트의 정본

```js
import { createAnimatable, createScope, utils } from "animejs";

createScope({ mediaQueries: { reduceMotion: "(prefers-reduced-motion: reduce)" } }).add((self) => {
  if (self.matches.reduceMotion) return;             // 저감 경로: 깊이를 걸지 않는다
  const card = document.querySelector(".card");
  const tilt = createAnimatable(card, { rotateX: 260, rotateY: 260, ease: "out(3)" });
  //                                    └ 속성별 지속 시간(ms). 값이 아니라 따라오는 속도다

  document.querySelector(".stage").addEventListener("pointermove", (event) => {
    const box = card.getBoundingClientRect();
    const px = utils.clamp((event.clientX - box.left) / box.width, 0, 1);
    const py = utils.clamp((event.clientY - box.top) / box.height, 0, 1);
    tilt.rotateY((px - 0.5) * 18);
    tilt.rotateX((0.5 - py) * 18);
  });
});
```

- `createAnimatable` 의 세터는 **호출 즉시 값을 목표로 설정**하고, 실제 갱신은 엔진 루프가 한다. `pointermove` 마다 `style.transform` 을 쓰는 코드와 다른 점이 이것이다(게이트 D6).
- 세터 없이 호출하면 게터다: `tilt.rotateY()`.
- 프레임워크 안에서는 `createScope(...).add(...)` 로 감싸고 정리 시 `scope.revert()` 를 부른다(React `useEffect` 반환, Vue `onUnmounted`). 부르지 않으면 리스너와 애니메이션이 남는다.

## 스크롤 동기

```js
animate(".panel", {
  rotateX: [12, 0],
  autoplay: onScroll({ container: ".scroller", enter: "bottom top", leave: "top bottom", sync: 0.25 }),
});
```

`sync: true`(=1)는 스크롤 위치에 정확히 붙고, `0~1` 사이 값은 그만큼 늦게 따라온다(작을수록 느리게 따라잡는다). 트랙패드 관성 때문에 `sync` 없이 즉시 반응시키면 끊겨 보인다. `debug: true` 로 경계선을 화면에 그린다.

스크롤 핸들러를 직접 만들지 않는다. 이미 만들어 놓았다면 그것을 지우는 것이 이 API 를 쓰는 이유다.

## v3 → v4

| v3 | v4 |
|---|---|
| `import anime from "animejs"` | `import { animate } from "animejs"` |
| `anime({ targets: el, … })` | `animate(el, { … })` |
| `easing: "easeOutQuad"` | `ease: "outQuad"` (기본값 `out(2)`) |
| `direction: "reverse"` / `"alternate"` | `reversed: true` / `alternate: true` |
| `loop: 1` = 1회 재생 | `loop: 1` = 1회 **반복**(총 2회) |
| `endDelay` | `loopDelay` |
| 키프레임 `{ value: … }` | `{ to: … }` |
| `round: 100` | `modifier: utils.round(2)` |
| `anime.timeline()` | `createTimeline({ defaults: { … } })` |
| `anime.stagger()` · `anime.random()` · `anime.set()` · `anime.remove()` | `stagger()` · `utils.random()` · `utils.set()` · `utils.remove()` |
| `easing: "spring(1, 80, 10, 0)"` | `ease: createSpring({ mass: 1, stiffness: 80, damping: 10, velocity: 0 })` |
| `update` · `begin` · `complete` | `onUpdate` · `onBegin` · `onComplete` (모든 콜백에 `on` 접두) |
| `.finished.then()` | `.then()` |
| `anime.suspendWhenDocumentHidden` | `engine.pauseOnDocumentHidden` |

게이트 D4 는 v4 임포트와 v3 전역 호출이 같은 파일에 있는 경우를 잡는다. 섞이면 코드 리뷰는 통과하고 런타임에서 죽는다.

## three.js 어댑터 — 여기가 경계다

v4 는 three.js 어댑터를 부수 효과 임포트로 싣는다(`animejs/adapters/three`). 실으면 `Object3D`·`Material`·`Texture`·`Color`·`Vector2~4`·TSL 유니폼을 `animate()` 와 `utils.set()` 에 그대로 넘길 수 있고, 회전 필드는 도(degree) 로 읽고 쓴다.

**이 어댑터를 쓰는 순간 작업은 L5 다.** 씬·예산·자산·`detect3d`·`scene_audit` 은 엔진 3(`asgard-freyja-3d`)이 소유한다. 이 스킬이 소유하는 것은 트윈 계층뿐이고, 캔버스를 여는 결정은 여기서 하지 않는다(`compose.md`).

## 성능

- 엔진은 **단일 메인 루프**다. anime.js 옆에 자체 `requestAnimationFrame` 루프를 하나 더 돌리면 두 루프가 같은 프레임을 두 번 만진다. 값이 필요하면 `onUpdate` 에서 읽는다.
- `engine.pauseOnDocumentHidden` 은 기본으로 켜져 있는 방어다. 뷰포트 밖 정지는 별도로 `IntersectionObserver` 가 필요하다.
- 애니메이션이 끝나면 `will-change` 를 걷어 낸다. 켜 둔 채 두면 합성 레이어가 남아 글자가 흐려진다.
