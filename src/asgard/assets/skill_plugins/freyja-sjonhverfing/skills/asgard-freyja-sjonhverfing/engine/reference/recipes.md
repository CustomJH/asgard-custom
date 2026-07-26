# 형태 — 여덟 가지 레시피

각 레시피는 사다리의 칸과 필요한 공간을 함께 적는다. 공간을 안 짓고 값만 움직이면 전부 실패한다(`css-3d.md`).

---

## R1 · 층 시차 — L2, 원근 불필요

앞뒤 관계만 말하면 되는 경우의 정답. 3D 문맥도 원근도 필요 없고, 평면화 사고에서 자유롭다.

```js
import { animate, onScroll, createScope } from "animejs";

createScope({ mediaQueries: { reduceMotion: "(prefers-reduced-motion: reduce)" } }).add((self) => {
  if (self.matches.reduceMotion) return;
  for (const [layer, depth] of [[".sky", 0.15], [".ridge", 0.4], [".fore", 0.8]]) {
    animate(layer, { y: `${depth * -120}px`, ease: "linear", autoplay: onScroll({ sync: 0.3 }) });
  }
});
```

멀리 있는 것이 **덜** 움직인다. 반대로 하면 무대가 뒤집힌다. 총 이동량은 뷰포트 높이의 15% 를 넘기지 않는다 — 그 이상은 스크롤이 고장 난 느낌을 준다.

> 엔진 4(마르될)가 배달하면 시차는 금지 목록에 있다. `compose.md` 를 먼저 본다.

---

## R2 · 기울기 카드 — L3

포인터 위치를 각도로 옮긴다. 완성형은 `references/specimen/tilt-card.html` 에 있고, 값 엔진 부분은 `animejs.md` 의 정본과 같다.

```css
.stage { perspective: 900px; }                 /* 형제가 소실점을 공유한다 */
.card  { transform-style: preserve-3d; }       /* 여기에 overflow·filter·opacity 를 얹지 않는다 */
.face  { transform: translateZ(28px); }        /* 층을 나눠야 기울일 때 시차가 생긴다 */
```

- 최대 각도는 **8~12°**. 그 이상은 본문 글자가 무너진다.
- 깊이는 기하가 아니라 빛이 만든다. 각도에 그림자와 광택을 함께 묶는다(R8 아래 「빛」).
- 키보드 사용자에게는 각도가 없다. **기울기가 정보를 옮기면 안 되는 이유**가 이것이다.

---

## R3 · 뒤집기 — L3

```css
.scene { perspective: 1000px; }
.card  { transform-style: preserve-3d; transition: transform 420ms cubic-bezier(0.16, 1, 0.3, 1); }
.card[data-flipped="true"] { transform: rotateY(180deg); }
.face  { backface-visibility: hidden; }        /* 컨테이너가 아니라 면에 건다 */
.face--back { transform: rotateY(180deg); }
```

- 상태는 `data-flipped` 같은 **속성**으로 둔다. 클래스 토글을 JS 가 매번 계산하면 되돌릴 길이 사라진다.
- 뒷면 내용은 저감 모션 경로와 스크린리더 경로에서 **도달 가능**해야 한다. 회전으로만 도달하는 정보는 숨긴 정보다.
- 뒤집힌 면의 포커스 가능한 요소에는 `inert` 를 건다. 안 걸면 보이지 않는 버튼에 탭이 들어간다.

---

## R4 · 고리 · 코버플로 — L4, 겹쳐 나누기

변환 순서 때문에 **한 요소로는 만들 수 없다**(`css-3d.md` 「변환 함수의 순서」). 회전과 이동을 두 요소로 나눈다.

```html
<div class="ring">
  <div class="slot" style="--i: 0"><article class="panel">…</article></div>
  <div class="slot" style="--i: 1"><article class="panel">…</article></div>
</div>
```

```css
.ring { perspective: 1400px; transform-style: preserve-3d; }
.slot { position: absolute; inset: 0; transform-style: preserve-3d;
        transform: rotateY(calc(var(--i) * 40deg)); }   /* ① 바깥이 돈다 */
.panel { transform: translateZ(420px); }                 /* ② 안쪽이 밀려난다 */
```

돌리는 것은 `.ring` 의 `rotateY` 하나뿐이다. anime.js 는 그 값 하나만 움직인다.

```js
animate(".ring", { rotateY: -40 * index, ease: "out(3)", duration: 520 });
```

반지름은 `slot` 폭 / (2·tan(π/n)) 이면 면끼리 정확히 맞물린다. 눈으로 맞추지 않는다.

---

## R5 · 상자 — L4

여섯 면을 각각 회전시켜 절반 크기만큼 밀어낸다. 면이 **20장을 넘어가면 부피가 아니라 레이아웃 부채**다 — L5 로 올린다.

```css
.box { transform-style: preserve-3d; }
.box > .side { position: absolute; inset: 0; backface-visibility: hidden; }
.side--front { transform: translateZ(60px); }
.side--back  { transform: rotateY(180deg) translateZ(60px); }
.side--right { transform: rotateY(90deg) translateZ(60px); }
.side--left  { transform: rotateY(-90deg) translateZ(60px); }
.side--top   { transform: rotateX(90deg) translateZ(60px); }
.side--bottom{ transform: rotateX(-90deg) translateZ(60px); }
```

각 면의 `transform` 은 CSS 가 소유한다(회전 후 이동이므로 anime.js 단축 키로 표현되지 않는다). anime.js 는 `.box` 의 `rotateX/rotateY` 만 움직인다.

---

## R6 · 두께 있는 글자 — L4

같은 글자를 여러 겹 쌓고 `translateZ` 로 벌린다. 겹 수는 **8겹 이하**, 뒤로 갈수록 어둡게.

```css
.extrude { transform-style: preserve-3d; }
.extrude span { position: absolute; inset: 0; transform: translateZ(calc(var(--l) * -1px));
                color: oklch(calc(0.62 - var(--l) * 0.03) 0.02 260); }
```

각도가 하나로 고정된다면 이 전부가 낭비다 — 그때는 `text-shadow` 사다리(L1)로 같은 그림을 훨씬 싸게 얻는다. 사용자가 각도를 바꿀 수 있을 때만 L4 다.

---

## R7 · 아이소메트릭 — L3, 원근 없음

평행 투영이다. 소실점이 없으므로 `perspective` 를 걸지 않는다. 대시보드·다이어그램·지도처럼 **거리와 무관하게 크기가 같아야** 하는 곳에 쓴다.

```css
.iso { transform: rotateX(54.736deg) rotateZ(45deg); transform-style: preserve-3d; }
.iso .layer { transform: translateZ(var(--z, 0px)); }
```

`54.736°` 가 진짜 등각(isometric)이다. 더 납작하게 보이고 싶으면 30~45° 사이에서 고르되, 그것은 이등각(dimetric)이지 등각이 아니다. 이 레시피에서는 D1(원근 없음)이 정상 상태다 — 게이트가 아니라 사람이 판단한다.

---

## R8 · 스크롤 달리 — L3

카메라가 다가오는 것처럼 보이게 한다. 요소를 키우는 것(`scale`)과 다르다 — 원근 안에서 `translateZ` 로 다가오면 주변 요소와의 관계가 함께 변한다.

```js
animate(".hero-plane", {
  translateZ: [-300, 0],
  ease: "linear",
  autoplay: onScroll({ target: ".hero", enter: "bottom bottom", leave: "top top", sync: 0.35 }),
});
```

핀 구간의 길이는 콘텐츠 양이 아니라 **읽는 데 걸리는 시간**으로 정한다. 되감으면 되돌아와야 한다.

---

## 빛 — 여덟 레시피 전부에 붙는 조항

기하만으로는 평면으로 읽힌다. 깊이를 믿게 만드는 것은 각도와 함께 움직이는 **그림자와 광택**이다.

```js
const shade = createAnimatable(card, { boxShadow: 260 });   // 각도와 같은 지속 시간으로 따라온다
tilt.rotateY(deg);
shade.boxShadow(`${-deg * 1.2}px ${18 + Math.abs(deg)}px ${28}px oklch(0.22 0.02 260 / 0.18)`);
```

- 그림자는 기울기의 **반대쪽**으로 간다. 같은 쪽으로 가면 물체가 아니라 스티커로 보인다.
- 광택(`background: linear-gradient(...)` 의 각도)은 기울기와 **같은 쪽**으로 간다.
- 어두운 배경에서 광택을 세게 주면 엔진 4 의 발광 금지에 걸린다. 세기는 배달 엔진의 규약을 따른다.
