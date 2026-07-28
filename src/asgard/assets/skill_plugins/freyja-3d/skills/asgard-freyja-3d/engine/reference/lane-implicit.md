# implicit 레인 — SDF 조형 (실험적)

형상을 경계 표현(B-Rep)이 아니라 **부호 거리장(signed distance field)** 으로 적는다. 공간의 한 점을 받아 표면까지의 부호 있는 거리를 돌려주는 함수 하나가 곧 형상이고, 메싱은 그 함수를 격자에서 평가해 등치면을 뽑는다.

**기본이 아니다.** 사용자가 명시적으로 암시 모델을 원할 때만 이 레인을 탄다. 그 외에는 STEP 우선 워크플로가 정본이다 — 이유는 아래 "무엇을 못 하는가".

## 왜 있는가

B-Rep 이 어려워하는 것들을 SDF 는 한 줄로 한다:

- 부드러운 불리언(`unionRound`) — 필렛을 따로 걸 필요가 없다
- TPMS(자이로이드 같은 삼중 주기 최소 곡면) 격자, 절차적 반복, 무한 패턴
- 필드 연산으로 표현되는 유기적·연속적 형상

반대로 **치수 계약이 있는 제조물에는 쓰지 않는다.**

## 파일 형식

`.implicit.mjs` / `.implicit.js` — 기본 내보내기가 `sdf(x, y, z)` 를 갖는 ES 모듈.

```js
export default {
  schema: "implicit/1.0",
  name: "rounded capsule block",
  bounds: { min: [-40, -25, -25], max: [40, 25, 25] },   // 선택
  resolution: 64,                                        // 선택
  sdf(x, y, z) {
    const sphere = Math.hypot(x, y, z) - 22;
    return unionRound(sphere, box(x, y, z, 34, 18, 18), 3);
  },
};
```

**필드는 자바스크립트 함수다.** 예전 판은 GLSL 문자열이었는데, 그것은 브라우저 레이마처가 유일한 실행체였기 때문이다. 그 실행체가 빠진 지금 GLSL 을 고집하면 셋을 잃는다 — 노드에서 필드를 평가할 수 없어 메싱에 브라우저가 필요하고, 문법 오류가 런타임까지 안 잡히고, 값을 하나 찍어 보는 일조차 못 한다.

- 헬퍼(`box`·`sphere`·`cylinderZ`·`union`·`subtract`·`unionRound`·`gyroid`)는 `node engine/scripts/implicit.mjs --helpers` 로 찍어서 모델 파일에 붙인다. 라이브러리를 임포트하지 않으므로 모델 한 파일이 자기완결이다.
- `bounds` 는 선택이다. 생략하면 원점에서 넓혀 가며 추정한다. 추정이 너무 넓거나 느리거나 특이한 필드를 놓칠 때 명시한다.
- `resolution` 은 격자 한 변의 칸 수(기본 64, 16–256). **이 값이 곧 정확도다.**

## 도구

```bash
node engine/scripts/implicit.mjs model.implicit.mjs --out build --res 96
node engine/scripts/implicit.mjs model.implicit.mjs --json
node engine/scripts/implicit.mjs --helpers > helpers.js
```

한 번에 메시(STL)·렌더 4장·컨택트 시트·수밀 판정을 낸다. node 18+ 외에 아무것도 필요 없다 — 브라우저도 playwright 도 GPU 도 쓰지 않는다.

메싱은 나이브 서피스 넷이다. 부호가 바뀌는 셀마다 정점 하나를 두고 이웃과 잇는 방식이라 출력이 수밀 매니폴드로 나온다. 마칭 큐브와 달리 큰 표가 필요 없고, 대신 **날카로운 모서리를 격자 해상도만큼 뭉갠다.**

## 무엇을 못 하는가

이 레인의 한계를 먼저 말하지 않으면 사용자가 나중에 발견한다.

- **STEP 이 나오지 않는다.** SDF 는 B-Rep 이 아니다. 발주·정밀 공차·조립 간섭 검사가 걸리면 cad 레인으로 간다.
- **메시로 내린 결과는 근사다.** 격자 해상도가 곧 정확도이고, 셀 한 칸보다 얇은 벽이나 날카로운 모서리는 뭉갠다. 도구가 셀 크기를 mm 로 찍어 주니 그 숫자를 보고서에 같이 적는다. 내린 메시를 "치수가 맞는 모델"이라고 부르지 않는다.
- **셀렉터 참조가 없다.** `#o1.f3` 로 면을 부를 수 없으므로 `measure`·`align`·`frame` 검증이 통째로 없다. 검증 수단이 렌더와 메시 감사뿐이다.
- 실험적이다. 스키마가 바뀔 수 있다.

## 배달

- 렌더 증거를 남기고 **실제로 연다.** 셀렉터 검증이 없는 만큼 눈이 더 무겁다.
- 메시로 내렸으면 `mesh_audit.mjs` 로 살두께·오버행을 잰다. 수밀은 도구가 이미 판정해 찍는다.
- 리뷰는 `lane-viewer.md` 의 뷰어에서 내려진 `.stl` 을 연다.
- **제조 주장을 하지 않는다.** 이 레인의 산출물로 "3D 프린트 가능"을 말하려면 메시를 내리고 cad/fabricate 레인의 판정을 통과해야 한다.
