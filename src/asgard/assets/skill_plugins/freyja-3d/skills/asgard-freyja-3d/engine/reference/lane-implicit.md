# implicit 레인 — SDF 조형 (실험적)

브라우저에서 바로 도는 암시적 CAD. 형상을 경계 표현(B-Rep)이 아니라 **GLSL 부호 거리장(signed distance field)** 으로 적고, 레이마칭으로 그린다.

**기본이 아니다.** 사용자가 명시적으로 암시 모델을 원할 때만 이 레인을 탄다. 그 외에는 STEP 우선 워크플로가 정본이다 — 이유는 아래 "무엇을 못 하는가".

## 왜 있는가

B-Rep 이 어려워하는 것들을 SDF 는 한 줄로 한다:

- 부드러운 불리언(`implicit_union_round`) — 필렛을 따로 걸 필요가 없다
- TPMS(자이로이드 같은 삼중 주기 최소 곡면) 격자, 절차적 반복, 무한 패턴
- 필드 연산으로 표현되는 유기적·연속적 형상

반대로 **치수 계약이 있는 제조물에는 쓰지 않는다.**

## 파일 형식

`.implicit.js` / `.implicit.mjs` — `implicit.js/0.1.0` 객체를 기본 내보내기 하는 ES 모듈.

```js
export default {
  schema: "implicit.js/0.1.0",
  name: "rounded capsule block",
  glsl: `
float sdf(vec3 p) {
  float sphere = implicit_sphere(p, vec3(0.0), 22.0);
  float block  = implicit_box_centered(p, vec3(34.0, 18.0, 18.0), vec3(0.0));
  return implicit_union_round(sphere, block, 3.0);
}
vec3 color(vec3 p, vec3 normal) {
  return mix(vec3(0.20, 0.55, 0.95), vec3(0.95, 0.45, 0.20), smoothstep(-15.0, 20.0, p.z));
}
`,
};
```

- 내장 GLSL 헬퍼는 `implicit_*` 이름공간(`implicit_sphere`, `implicit_box_centered`, `implicit_union_round` …).
- 스키마 정본은 `vendor/text-to-cad/packages/implicitjs/src/lib/implicitCad/schema.js`. 헬퍼 모듈 `skills/implicit-cad/scripts/lib/implicit-cad.mjs` 가 `SCHEMA` 로 재수출한다.
- `params` 는 `number`·`boolean`·`enum`/`select`·`color`·`string`·`button`. number·boolean·color·button 은 **같은 이름의 GLSL 유니폼이 자동 생성**된다 — 별도 `uniforms` 객체를 만들지 않는다.
- `bounds` 는 선택이다. 생략하면 SDF 에서 추정한다. 추정이 너무 넓거나 느리거나 특이한 필드를 놓칠 때만 명시한다.

## 도구

```bash
V=engine/vendor/text-to-cad/skills/implicit-cad
node $V/scripts/snapshot.mjs <model.implicit.js> [...]   # 레이마칭 렌더 증거
node $V/scripts/export.mjs   <model.implicit.js> [...]   # 메시로 내린다
```

node 18+ 만 있으면 되고, 스냅샷은 playwright 를 쓴다.

## 무엇을 못 하는가

이 레인의 한계를 먼저 말하지 않으면 사용자가 나중에 발견한다.

- **STEP 이 나오지 않는다.** SDF 는 B-Rep 이 아니다. 발주·정밀 공차·조립 간섭 검사가 걸리면 cad 레인으로 간다.
- **메시로 내린 결과는 근사다.** 마칭 해상도가 곧 정확도이고, 얇은 벽이나 날카로운 모서리는 뭉갠다. 내린 메시를 "치수가 맞는 모델"이라고 부르지 않는다.
- **셀렉터 참조가 없다.** `#o1.f3` 로 면을 부를 수 없으므로 `measure`·`align`·`frame` 검증이 통째로 없다. 검증 수단이 렌더와 메시 감사뿐이다.
- 실험적이다. 스키마가 바뀔 수 있다.

## 배달

- 렌더 증거를 남기고 **실제로 연다.** 셀렉터 검증이 없는 만큼 눈이 더 무겁다.
- 메시로 내렸으면 `mesh_audit.mjs` 로 수밀·살두께를 잰다 — 마칭이 만든 구멍은 흔하다.
- 리뷰는 `lane-viewer.md` 의 뷰어에서 `.implicit.js` 를 직접 연다.
- **제조 주장을 하지 않는다.** 이 레인의 산출물로 "3D 프린트 가능"을 말하려면 메시를 내리고 cad/fabricate 레인의 판정을 통과해야 한다.
