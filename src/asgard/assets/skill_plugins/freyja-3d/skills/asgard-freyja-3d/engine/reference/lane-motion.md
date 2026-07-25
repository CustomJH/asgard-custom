# motion 레인 — 3D 모션과 카메라 연출

3D 모션의 목적은 "움직이는 것"이 아니다. **공간을 이해시키는 것**이다. 회전하는 물체가 사용자에게 새 정보를 주지 않으면 그것은 배터리를 쓰는 장식이다.

## 원칙

1. **콘텐츠가 먼저 칠해지고, 연출은 그 위에 더해진다.** 첫 페인트를 진입 시퀀스 뒤에 두지 않는다. JS 없이도, 애니메이션 클래스 없이도 기본 상태가 보여야 한다. (엔진 2 의 모션 불변조항과 동일 — 벤치로 확인된 규칙이다.)
2. **카메라는 사람의 눈처럼 움직인다.** 순간이동하지 않고, 축을 여러 개 동시에 흔들지 않으며, 감속으로 끝난다. 관심 대상을 화면 중앙에 고정한 채 궤도를 도는 것이 기본형이다.
3. **모션에는 되돌아갈 길이 있어야 한다.** 스크롤로 진행한 연출은 스크롤을 되돌리면 되돌아와야 한다. 되돌아오지 않으면 그것은 상태 손실이다.
4. **저감 모션은 삭제가 아니라 대체다.** `prefers-reduced-motion: reduce` 에서는 최종 상태로 즉시 전환한다. 정보를 함께 지우지 않는다.

## 구현 형태별 선택

| 필요 | 도구 | 이유 |
|---|---|---|
| 스크롤 스크럽·핀·스냅 | GSAP ScrollTrigger | 대체재가 사실상 없다. 스크롤 위치 → 타임라인 진행률 매핑이 정확하다 |
| 짧은 상태 전환 | 프레임워크 기본(Framer Motion, Vue Transition) + three 쪽은 lerp | 3D 라이브러리를 새로 얹을 이유가 없다 |
| 프레임 단위 물리감 | 프레임 루프 내 지수 감쇠 | 시간 독립적이고 프레임률에 흔들리지 않는다 |
| 복잡한 씬 타임라인 | GSAP timeline 또는 자체 시퀀서 | 되감기·시크가 필요하면 타임라인이 필수 |
| 물리 시뮬레이션 | rapier(@dimforge) | 결정적 시뮬레이션이 필요할 때만. 시각 효과라면 물리 없이 만드는 편이 싸다 |

## 프레임률 독립 보간

`lerp(current, target, 0.1)` 은 프레임률에 따라 속도가 달라진다. 120Hz 기기에서 두 배 빨라진다.

```js
// 지수 감쇠 — delta 를 반영해 어떤 프레임률에서도 같은 체감 속도
const smoothing = 1 - Math.pow(0.001, delta);   // 0.001 = 1초 후 남는 비율
camera.position.lerp(target, smoothing);
```

## 카메라 리그

```js
const TMP = new THREE.Vector3();          // 루프 밖에서 한 번만 만든다
const reduced = matchMedia("(prefers-reduced-motion: reduce)");

function tick(delta) {
  if (reduced.matches) { camera.position.copy(target); camera.lookAt(focus); return; }
  TMP.copy(target);
  camera.position.lerp(TMP, 1 - Math.pow(0.01, delta));
  camera.lookAt(focus);
}
```

- **`OrbitControls` 에 `enableDamping` 을 켰다면 루프에서 `controls.update()` 를 부른다.** 부르지 않으면 관성은 코드에만 존재한다. `detect3d` 의 `inert-controls` 가 이 한 가지를 잡는다.
- 자동 회전에는 정지 버튼을 둔다. 사용자가 조작을 시작하면 자동 연출은 멈춘다(다시 시작하려면 명시적 트리거).
- 시야각(FOV)을 애니메이션하면 멀미를 유발한다. 거리로 움직이는 편이 안전하다.

## 스크롤 구동

```js
ScrollTrigger.create({
  trigger: section, start: "top top", end: "+=200%", scrub: 1, pin: true,
  onUpdate: (self) => { timeline.progress(self.progress); },   // 타임라인 진행률만 건드린다
});
```

- 스크롤 핸들러 안에서 렌더를 직접 호출하지 않는다. 진행률만 갱신하고 렌더는 루프에 맡긴다.
- `scrub` 없이 스크롤에 즉시 반응시키면 트랙패드의 관성 때문에 끊긴다.
- 핀 구간의 길이는 콘텐츠 양이 아니라 **읽는 데 걸리는 시간**으로 정한다. 긴 핀은 스크롤을 고장 난 것처럼 느끼게 한다.
- 모바일에서 스크롤 구동 3D 는 비싸다. 뷰포트 밖에서는 렌더를 멈추고, 저사양에서는 정지 이미지로 대체하는 경로를 만든다.

## 검증

모션은 소스로 판정할 수 없다. 다음을 실제로 하고 보고한다.

- 선언한 전환을 **모두 트리거**해서 본다. 값이 한 번만 쓰이고 갱신되지 않는 전환은 정지 화면이다.
- 스크롤 연출은 **되감아** 본다.
- `prefers-reduced-motion: reduce` 를 켜고 다시 본다. 최종 상태가 보이는지, 정보가 사라지지 않았는지.
- 저사양 조건(CPU 스로틀 4배, 모바일 뷰포트)에서 프레임을 본다.

`node engine/scripts/detect3d.mjs src/` 는 정적으로 잡을 수 있는 것(죽은 관성, 저감 모션 분기 누락, 프레임 루프 내 할당, 배경 루프)만 잡는다. 나머지는 눈으로 봐야 한다.
