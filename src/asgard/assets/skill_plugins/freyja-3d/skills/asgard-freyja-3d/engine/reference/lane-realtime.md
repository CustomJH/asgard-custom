# realtime 레인 — 브라우저에서 도는 3D

판정 기준은 "예쁜 스크린샷"이 아니라 **대상 기기에서 예산 안에 들어오고, 로드되고, 안 깨지는가**다. 데스크톱 개발기에서 60fps 인 씬은 아무것도 증명하지 않는다.

## 렌더러 기본선

색 관리와 톤 매핑을 지정하지 않은 씬은 무조건 플라스틱처럼 보인다. 이건 취향이 아니라 설정 누락이다.

```js
import * as THREE from "three";

const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));   // 상한 없이 넘기면 고DPI 에서 픽셀이 4~9배
renderer.toneMapping = THREE.AgXToneMapping;                     // 또는 ACESFilmicToneMapping
renderer.toneMappingExposure = 1.0;
// 색공간은 r152 부터 기본이 SRGBColorSpace 다. outputEncoding/sRGBEncoding 은 제거된 API.

const texture = await loader.loadAsync(url);
texture.colorSpace = THREE.SRGBColorSpace;   // 색상 맵에만. 노멀·러프니스·AO 에는 지정하지 않는다.
texture.anisotropy = Math.min(4, renderer.capabilities.getMaxAnisotropy());
```

- **환경광이 재질을 만든다.** `MeshStandardMaterial` 은 환경 맵 없이는 금속을 표현하지 못한다. HDRI 한 장(또는 `RoomEnvironment`)이 라이트 세 개보다 낫다.
- **그림자는 비싸다.** 필요한 오브젝트만 `castShadow`, 그림자 카메라 절두체를 형상에 딱 맞춘다. 넓은 절두체는 해상도를 낭비해 계단을 만든다.
- **`setAnimationLoop` 을 쓴다.** `requestAnimationFrame` 직접 호출은 XR 에서 동작하지 않고, 탭이 가려져도 도는 루프를 만들기 쉽다.

## WebGPU 와 TSL

- three r171+ 에서 `import { WebGPURenderer } from "three/webgpu"` 로 쓰고, WebGPU 가 없으면 **자동으로 WebGL2 로 폴백**한다. 별도 코드 경로를 만들지 않는다.
- 초기화는 비동기다. `await renderer.init()` 을 건너뛰면 첫 렌더가 조용히 실패한다.
- **`ShaderMaterial`·`RawShaderMaterial`·`onBeforeCompile` 은 WebGPU 경로에서 동작하지 않는다.** 커스텀 셰이딩은 TSL(노드 머티리얼)로 써야 하고, TSL 은 WGSL 과 GLSL 양쪽으로 컴파일되므로 폴백까지 한 코드로 덮는다.
- WebGPU 가 항상 빠른 것은 아니다. 이득이 확실한 곳은 **드로우콜이 많은 씬**(바인딩 모델이 CPU 부담을 줄인다)과 **컴퓨트 셰이더**(파티클, GPU 시뮬레이션)다. 단순 씬을 WebGPU 로 옮겨도 프레임은 그대로다.
- 포팅 비용 감각: 표준 머티리얼만 쓰는 씬은 한두 시간, 커스텀 GLSL 이 있으면 하루이틀, 대형 포스트프로세싱 파이프라인은 주 단위다. 이 비용을 먼저 말하고 시작한다.

## 성능 — 순서대로 본다

1. **드로우콜.** 삼각형보다 이 숫자가 프레임을 결정한다. 같은 지오메트리는 `InstancedMesh`, 다른 지오메트리·같은 재질은 `BatchedMesh`, 정적 배경은 병합(`mergeGeometries`).
2. **셰이더 컴파일 스톨.** 첫 등장에서 프레임이 멈추는 원인. `renderer.compileAsync(scene, camera)` 로 미리 컴파일한다.
3. **텍스처 메모리.** KTX2/Basis 로 압축하면 GPU 에 올라간 뒤에도 압축 상태를 유지한다(JPEG/PNG 는 디코드되어 원본 크기로 VRAM 을 먹는다). 모바일에서 이게 가장 흔한 크래시 원인이다.
4. **오버드로우.** 반투명 레이어를 쌓는 것은 모바일 GPU 에서 가장 비싼 일 중 하나다. 파티클·글래스·블룸을 동시에 쓰지 않는다.
5. **정점 수.** 대개 마지막 문제다. 화면에서 4px 인 구에 128×128 세그먼트를 쓰지 않는다.

예산 숫자와 측정 방법은 `budgets.md`.

## 로딩

```js
const draco = new DRACOLoader().setDecoderPath("/draco/");   // 경로 미지정 = 런타임 실패
const ktx2 = new KTX2Loader().setTranscoderPath("/basis/").detectSupport(renderer);
const gltf = new GLTFLoader().setDRACOLoader(draco).setKTX2Loader(ktx2);
```

- 디코더 파일을 **함께 배포**한다. CDN 경로를 그대로 두면 오프라인·사내망에서 죽는다.
- 첫 화면은 3D 없이도 의미가 통해야 한다. 모델 로딩을 히어로 콘텐츠의 첫 페인트 앞에 두지 않는다(엔진 2 의 모션 불변조항과 같은 규칙).
- 로딩 상태를 만든다: 진행률, 실패 시 폴백(정지 이미지), 저사양 기기 감지 시 축소 씬.

## 자원 해제

라우트를 오가는 SPA 에서 GPU 메모리 누수는 시간 문제다. `dispose()` 는 자동으로 불리지 않는다.

```js
function disposeTree(root) {
  root.traverse((object) => {
    object.geometry?.dispose();
    for (const material of [object.material].flat().filter(Boolean)) {
      for (const value of Object.values(material)) value?.isTexture && value.dispose();
      material.dispose();
    }
  });
}
// 앱 전체를 내릴 때만: renderer.dispose() — 부분 해제에서 부르면 살아 있는 씬까지 죽는다.
// 컨트롤·포스트프로세싱 패스도 각각 해제한다.
```

## 프레임워크 어댑터

| 스택 | 진입점 | 주의 |
|---|---|---|
| 바닐라 three | 직접 씬 구성 | 리사이즈·해제·루프를 직접 관리 |
| React Three Fiber | `<Canvas dpr={[1,2]} frameloop="demand">` | `useFrame` 안에서 객체를 새로 만들지 않는다(모듈 스코프 상수 재사용). 정적 씬은 `frameloop="demand"` |
| TresJS (Vue) | `<TresCanvas>` | 반응형 프록시가 매 프레임 도는 곳에 들어가지 않게 `shallowRef` |
| Threlte (Svelte) | `<Canvas>` | 스토어 구독을 프레임 루프 밖에 둔다 |

프레임워크가 이미 정해져 있으면 그것을 쓴다. 3D 때문에 프레임워크를 바꾸자고 제안하지 않는다.

## 견고성

- **컨텍스트 손실**: 모바일 백그라운드 복귀·드라이버 리셋에서 캔버스가 검게 남는다. `webglcontextlost`/`webglcontextrestored`(WebGPU 는 `device.lost`)를 받아 재초기화 경로를 만든다.
- **리사이즈**: `ResizeObserver` 로 캔버스 크기를 보고 `setSize` + `camera.aspect` + `updateProjectionMatrix`. 창 리사이즈 이벤트만으로는 레이아웃 변화에 반응하지 못한다.
- **보이지 않을 때 멈춘다**: `IntersectionObserver` 또는 `visibilitychange`. 배터리와 발열은 사용자가 즉시 체감한다.
- **접근성**: 3D 로만 전달되는 정보(제품 색상, 상태, 수치)에는 텍스트 대안을 둔다. 자동 회전에는 정지 수단을, 카메라 연출에는 `prefers-reduced-motion` 경로를 둔다.

## 검증

```bash
node engine/scripts/detect3d.mjs src/           # 정적 결함 — FAIL 0 이 배달 조건
node engine/scripts/scene_audit.mjs public/model.glb --target mobile
```

`detect3d` 가 잡는 것은 코드 리뷰를 통과하고 화면에서 죽는 것들이다: 관성만 켜고 갱신하지 않는 컨트롤, 초기화를 기다리지 않는 WebGPU 렌더(`await renderer.init()` 누락), 상한 없는 픽셀 비율, 제거된 API, 저감 모션 분기 없는 카메라 연출, 디코더 경로 없는 Draco 로더, 해제되지 않는 자원, 프레임 루프 안의 할당.
