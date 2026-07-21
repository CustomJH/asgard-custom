---
name: threejs-skills
description: three.js API 정본 레퍼런스 팩(CloudAI-X threejs-skills 포트, 업스트림이 r160+ 공식 문서 대조를 주장) — 씬·지오메트리·재질·조명·텍스처·애니메이션·로더·셰이더·포스트프로세싱·인터랙션 10룸 지연 로드. three.js/WebGL/R3F 코드를 실제로 작성·수정하며 정확한 생성자 시그니처·임포트 경로·API 표면이 필요할 때 로드. 원칙·불변식·예산은 asgard-freyja-folkvangr 가 우선.
---

# threejs-skills — 📐 three.js API 정본 레퍼런스

이 팩은 **원칙이 아니라 표면**이다. `asgard-freyja-folkvangr`가 "왜 그렇게 하는가"(렌더 파이프라인 계약·예산 게이트·메모리 규율)를 말한다면, 이 팩은 "정확히 어떻게 쓰는가"(생성자 시그니처·프로퍼티 이름·임포트 경로·작동 예제)를 담는다. 충돌하면 folkvangr 의 계약이 이기고, 시그니처는 이 팩이 이긴다.

## 적용 위계

1. **folkvangr 계약 > 이 팩.** 예산·색공간·dispose·검증 루프는 folkvangr 불변식이 지배한다. 이 팩의 예제가 계약과 어긋나면(예: 예제 편의상 그림자 전 라이트 활성) 계약 쪽으로 교정해 쓴다.
2. **이 팩 > 기억.** three.js API 는 릴리스마다 표류한다 — 시그니처·프로퍼티 이름을 기억으로 쓰지 말고 해당 룸을 연다.
3. **현 버전 문서 > 이 팩 (Canon 12).** 이 팩은 리비전 고정 스냅샷이다. 프로젝트의 three.js 버전이 다르거나 표기가 의심되면 현 버전 공식 문서가 최종 정본이다. 알려진 표류 예: aoMap 의 두 번째 UV 채널 규약은 r151 에서 `uv2` 속성 → `uv1`+`Texture.channel` 로 바뀌었다 — 룸 스냅샷에는 구표기가 남아 있다.

## 방 안내 — 겹치는 방만 연다

과업 표면에 해당하는 룸만 리소스로 로드한다: `asgard skills show threejs-skills --resource references/<파일>` (네이티브에서는 load_skill 리소스 로더).

| 룸 | 열 때 | 담긴 것 |
|---|---|---|
| `references/fundamentals.md` | 씬·카메라·렌더러 셋업, Object3D 계층, 수학 유틸 | Scene/카메라 4종/WebGLRenderer 옵션, Vector3·Matrix4·Quaternion, Clock·resize·dispose 패턴 |
| `references/geometry.md` | 형상 생성, 커스텀 지오메트리, 대량 반복 | 빌트인 지오메트리 전 시그니처, BufferGeometry·속성 배열, InstancedMesh, 병합 유틸 |
| `references/materials.md` | 재질 선택·설정, 유리·차 도장 류 표현 | 재질 10종 비교표, Standard/Physical 전 프로퍼티, ShaderMaterial 기초, 환경맵 적용 |
| `references/lighting.md` | 라이트 추가, 그림자 설정, IBL | 라이트 6종 시그니처, 그림자 카메라·bias, 3점 조명·야외·스튜디오 프리셋, 헬퍼 |
| `references/textures.md` | 이미지·비디오·데이터 텍스처, 렌더 타깃 | 로딩·색공간·래핑·필터링, Data/Canvas/Video/압축 텍스처, 큐브맵·HDR, WebGLRenderTarget |
| `references/animation.md` | 키프레임·스켈레탈·모프, 클립 블렌딩 | KeyframeTrack 종류, AnimationMixer/Action, 본·모프 타깃, 감쇠·스프링 절차 패턴 |
| `references/loaders.md` | glTF/Draco/KTX2, OBJ·FBX·STL, 비동기 로딩 | 로더별 배선 코드, LoadingManager, Promise 래핑, 캐싱, 에러 처리 |
| `references/shaders.md` | GLSL 작성, uniform 배선, 기존 재질 확장 | uniform 타입표, varying, 프레넬·디졸브·노이즈 패턴, onBeforeCompile 주입점, GLSL 내장 함수 |
| `references/postprocessing.md` | 블룸·DOF·AA·화면 효과 | EffectComposer 배선, 이펙트 패스 15종, 커스텀 ShaderPass, resize 처리 |
| `references/interaction.md` | 클릭·호버 판정, 카메라 컨트롤, 드래그 | Raycaster·NDC 변환·터치, 컨트롤 6종, TransformControls, 선택·박스 셀렉션, 좌표 변환 |

통상 1–2룸이면 족하다. 전 룸 로드는 낭비다 — 룸을 연 근거(과업 표면)가 말이 되는지 스스로 검사한다. 룸 말미의 See Also 는 이 팩 내부 상호 참조다.

## 완료 계약

- 이 팩을 근거로 쓴 API 표면이 있으면 보고에 1줄 남긴다 — "레퍼런스: 〈룸 이름〉, 〈스냅샷 채택 | 현 버전 문서로 교정〉".
- 렌더 결과 검증(스크린샷 대조·`renderer.info` 실측·콘솔 셰이더 오류 0)은 folkvangr 검증 루프를 그대로 따른다 — 룸을 읽었다는 사실은 검증을 대체하지 않는다.

> 출처: [CloudAI-X/threejs-skills](https://github.com/cloudai-x/threejs-skills) — plugin.json 에 리비전 고정. 라이선스는 업스트림 README 의 MIT 선언(정식 LICENSE 파일 부재)에 근거한다.
