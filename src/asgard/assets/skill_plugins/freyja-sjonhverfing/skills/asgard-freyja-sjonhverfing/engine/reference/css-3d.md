# 공간을 짓는다 — CSS 3D 기질

anime.js 는 값을 움직일 뿐이다. 요소가 어느 공간 안에 있는지는 전적으로 CSS 가 정한다. 공간이 없으면 `rotateY(30deg)` 는 회전이 아니라 가로 축소로 보인다(`scaleX(0.87)` 과 구분되지 않는다).

## 원근 — 뿌리는 하나

두 가지 방법이 있고, 뜻이 다르다.

```css
/* ① 무대에 건다 — 형제 요소가 하나의 소실점을 공유한다. 이것이 기본형이다. */
.stage { perspective: 900px; perspective-origin: 50% 40%; }

/* ② 요소 자신의 변환에 넣는다 — 요소마다 제 소실점을 갖는다. */
.card { transform: perspective(900px) rotateY(20deg); }
```

②로 만든 카드 세 장을 나란히 두면 셋 다 자기 정면에 소실점을 갖는다. 같은 공간에 있는 것처럼 보이지 않는다. **형제가 한 공간에 있어야 하면 ①**, 요소가 독립된 무대이면 ②.

- 거리 감각: **요소 폭의 2~4배**가 자연스럽다. 320px 카드면 800~1200px. 400px 미만은 UI 크기에서 어안렌즈가 된다(게이트 D7).
- `perspective-origin` 이 소실점의 위치다. 요소가 화면 상단에 있으면 원점을 위로 올려야 아래에서 올려다보는 느낌이 사라진다.
- `perspective: none` 은 3D 를 평행 투영으로 되돌린다. **저감 모션에서 한 줄로 깊이를 끄는 탈출구**다.

## 3D 문맥 — 상속되지 않는다

`transform-style: preserve-3d` 는 "내 자식들을 내 3D 공간 안에 둔다"는 선언이다. 자식이 다시 자식을 3D 로 두려면 자식도 선언해야 한다. **원근 뿌리와 3D 자식 사이의 모든 요소가 선언해야 한다.** 하나라도 빠지면 그 지점에서 납작해진다.

## 평면화 — 결함의 절반이 여기서 나온다

`preserve-3d` 를 선언해도, 같은 요소에 아래 속성이 하나라도 걸리면 사용값이 `flat` 으로 강제된다. 스펙상 "그룹핑" 속성이고, 조용히 일어난다.

| 속성 | 평면화 조건 |
|---|---|
| `overflow` / `-x` / `-y` | `visible` 이 아닌 모든 값(`hidden`·`clip`·`auto`·`scroll`) |
| `filter` / `backdrop-filter` | `none` 이 아닌 값 |
| `opacity` | 1 미만 |
| `mask` / `mask-image` / `clip-path` | `none` 이 아닌 값 |
| `mix-blend-mode` | `normal` 이 아닌 값 |
| `contain` | `layout` · `paint` · `strict` · `content` |
| `isolation` | `isolate` |
| `will-change` | 위 속성 중 하나를 예고할 때 |

가장 흔한 사고는 **둥근 모서리 + `overflow: hidden`** 이다. 카드 이미지를 잘라내려고 붙인 한 줄이 카드 전체의 3D 를 꺼 버린다. 해법은 자르는 일과 3D 를 다른 요소로 나누는 것이다 — 바깥은 `preserve-3d`, 안쪽 래퍼가 자른다.

게이트 D2 는 **같은 규칙 안**의 충돌만 판정한다. 조상 체인은 캐스케이드가 정하므로 기계가 확정할 수 없다(미판정 M3). 3D 가 이유 없이 납작하면 조상부터 위로 훑는다.

## 뒷면

```css
.card { transform-style: preserve-3d; }
.card .face { backface-visibility: hidden; }   /* 면에 건다. 컨테이너가 아니다 */
.card .back { transform: rotateY(180deg); }
```

`backface-visibility` 는 3D 문맥 안에서만 뜻이 있다. 없으면 앞면과 뒷면이 겹쳐 보이고, 뒤집힌 면이 클릭을 먼저 먹는다. 숨긴 면은 `pointer-events` 도 함께 확인한다(미판정 M2).

## 변환 함수의 순서

CSS 변환은 왼쪽부터 좌표계를 갈아 끼운다. 순서가 다르면 결과가 다르다.

```css
transform: rotateY(30deg) translateZ(200px);   /* 회전한 축을 따라 밀어냄 → 고리 위의 한 자리 */
transform: translateZ(200px) rotateY(30deg);   /* 앞으로 나온 뒤 제자리 회전 → 고리가 아니다 */
```

anime.js 는 키를 쓴 순서와 무관하게 **고정 순서**(`perspective` → `translate` → `rotate` → `scale` → `skew`)로 변환을 조립한다. 즉 위 첫째 형태는 anime.js 의 단축 키로는 표현되지 않는다. 회전 후 이동이 필요하면 **요소를 겹쳐 나눈다** — 바깥이 회전하고 안쪽이 밀려난다(`recipes.md` R4). 이 방식은 어떤 라이브러리에서도 옳다.

## 고정 위치가 부서지는 자리

변환이 걸린 요소는 자손의 **포함 블록**이 된다. 그래서 3D 카드 안의 `position: fixed` 모달·드롭다운·툴팁은 뷰포트가 아니라 카드에 고정된다. `filter`·`backdrop-filter`·`will-change: transform`·`contain: paint` 도 같은 일을 한다.

해법은 하나뿐이다: 띄우는 것을 3D 문맥 **밖**으로 옮긴다(포털, `<dialog>`, popover API). 카드 안에서 고치려는 시도는 전부 실패한다.

## 글자와 적중 영역

- **글자 선명도.** 3D 변환은 합성 레이어를 만들고, 레이어는 한 번 래스터화된 뒤 확대된다. 정지 상태에서 흐릿하면 변환이 남아 있는 것이다 — 애니메이션이 끝나면 `transform` 과 `will-change` 를 걷어 낸다. 소수점 `translateZ` 도 흐림을 만든다. 지속 상태의 크기 변화는 변환이 아니라 `font-size` 로 준다.
- **회전 한계.** 본문 글자는 `rotateX/Y` 15° 부근부터 자간이 무너져 보인다. 그 이상 기울여야 하면 그 면에는 글자를 두지 않는다.
- **적중 영역.** 브라우저는 변환된 기하로 적중을 판정하므로 시각과 클릭이 어긋나지는 않는다. 다만 원근 때문에 레이아웃 상자와 보이는 상자가 달라, 겹친 형제의 우선순위가 뒤바뀔 수 있다. 초점 순서는 변환과 무관하게 DOM 순서 그대로다 — 시각적으로 재배치했으면 DOM 도 재배치한다.

## 정렬과 z-fighting

같은 평면에 놓인 두 면은 정렬 순서가 프레임마다 튈 수 있다. **최소 1px 이상 `translateZ` 로 떨어뜨린다.** 교차하는(서로를 관통하는) 두 면은 브라우저가 나눌 수 없다 — 그 형태가 필요하면 L5 다.

## 저감 모션

```css
@media (prefers-reduced-motion: reduce) {
  .stage { perspective: none; }              /* 깊이만 끈다 */
  .card, .face { transform: none; transition-duration: 1ms; }
}
```

정보를 함께 지우지 않는다. 뒤집기 카드라면 뒷면 내용이 저감 경로에서도 **도달 가능해야** 한다 — 회전 대신 교차 페이드나 펼침으로 바꾼다.
