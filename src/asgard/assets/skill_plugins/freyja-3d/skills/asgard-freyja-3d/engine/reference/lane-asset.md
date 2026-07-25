# asset 레인 — 3D 자산의 확보와 정리

모델을 만드는 것과 **쓸 수 있는 모델을 얻는 것**은 다른 문제다. 생성형 3D 는 형태를 빨리 주지만 위상(topology)은 주지 않는다.

## 어디서 얻는가

| 경로 | 강점 | 실제 비용 |
|---|---|---|
| 프로시저럴 코드 | 파라메트릭, 가볍고 버전 관리됨, 라이선스 문제 없음 | 유기적 형상에 약하다 |
| 생성형 3D (이미지/텍스트 → 메시) | 초안 속도가 압도적 | 50만~60만 삼각형의 과분할 메시, 리토폴로지 전제 |
| 스캔(포토그래메트리·LiDAR) | 실물 정확도 | 노이즈·구멍·거대 텍스처, 정리 작업이 본체 |
| 라이브러리 구매·무료 | 즉시 사용 가능 | 라이선스 확인이 필수, 품질 편차가 크다 |
| 규격 부품 STEP | 정확하고 공짜 | 기계 부품에 한정 |

## 생성형 3D 를 쓸 때

현재 계열은 크게 셋이다. 구조화 잠재(TRELLIS 계열)는 까다로운 위상에 강하고, 고해상도 지오메트리(Hunyuan3D 2.5 계열, 1024 해상도)는 디테일에 강하며, 부품 분해형(PartCrafter 계열)은 팔·바퀴·패널을 **분리된 파트로** 내보낸다 — 애니메이션이나 조립이 필요하면 이 차이가 결정적이다.

**공통 함정**:
- 출력 메시는 게임·웹에 그대로 못 쓴다. 50만+ 삼각형, 균일하지 않은 삼각형, UV 없음. 리토폴로지와 UV 언랩이 필요하다.
- 치수가 없다. 생성 메시는 "대충 그 모양"이지 측정된 물건이 아니다. **제조용으로 쓰지 않는다.**
- 내부가 비어 있거나 자기교차한다. 수밀 검사(`mesh_audit`)를 반드시 통과시킨다.
- 학습 데이터 출처와 상업적 사용 조건을 확인한다.

판단 기준: **보여주기용이면 생성형, 만들거나 맞물릴 것이면 파라메트릭.**

## 정리 파이프라인

```bash
# 1. 실측 — 무엇이 문제인지 숫자로 먼저 본다
node engine/scripts/mesh_audit.mjs raw.glb --process fdm
node engine/scripts/shoot.mjs raw.glb --out shots --views front,right,top,iso

# 2. 웹 배달용 최적화 (네트워크 필요)
npx @gltf-transform/cli optimize raw.glb out.glb \
    --texture-compress ktx2 --compress meshopt --simplify 0.75

# 3. 예산 재확인
node engine/scripts/scene_audit.mjs out.glb --target mobile
```

- **meshopt vs Draco**: 압축률은 Draco 가 조금 높고, 디코드 속도는 meshopt 가 크게 빠르다. 모바일 초기 로딩이 중요하면 meshopt.
- **KTX2/Basis 는 선택이 아니다.** JPEG/PNG 는 GPU 에 올라갈 때 압축이 풀려 VRAM 을 그대로 먹는다. KTX2 는 압축 상태로 남는다.
- **단순화(simplify)는 마지막에, 눈으로 확인하며.** 실루엣이 무너지는 지점이 있다. 자동 비율 하나로 전 자산을 처리하지 않는다.
- LOD 는 실제로 카메라 거리 편차가 큰 씬에서만 값을 한다. 고정 시점 씬에 LOD 는 복잡도만 늘린다.

## 엔진 프리뷰 — CAD 산출물을 안전한 출발점으로

커널이 내보낸 지오메트리는 그대로 쓰면 조잡해 보인다. 면마다 프리미티브가 쪼개져 있고(드로우콜 낭비),
법선이 평면 셰이딩이라 곡면이 각져 보이고, 머티리얼이 없다. 다음은 **무텍스처 CAD/메시 프리뷰**의 최소 사다리다. UV·텍스처·리깅까지 갖춘 game-ready 자산이라는 뜻은 아니다.

```bash
# 1단 — 무의존 폴리시: 부품 병합 + 크리스 스무딩 + PBR 머티리얼 (여기까지는 이 엔진 안에서 끝난다)
node engine/scripts/mesh_polish.mjs build/part.stl --out preview.glb --crease 40 \
     --materials '{"body":"steel","grip":"leather"}'    # 프리셋 또는 "#RRGGBB,metallic,roughness"
node engine/scripts/scene_audit.mjs preview.glb --target mobile   # 폴리시 후 예산 재확인

# 2단 — 압축·단순화: gltf-transform (pipeline 레인, 네트워크 필요)
# 3단 — UV 전개·텍스처 베이크·유기 조형·리깅: Blender 헤드리스 (escalation.md)
```

- 크리스 각 40° 가 하드서피스 기본값이다. 기계 부품의 모서리는 살리고 곡면은 잇는다. 둥근 유기형은 60~80°.
- `mesh_polish` 는 같은 이름의 부품 조각을 병합한다 — 부품당 드로우콜 1, 스무딩이 조각 경계를 넘는다.
- STL·OBJ·3MF는 기본적으로 mm로 읽어 glTF 규격의 m로 바꾼다. 미터 OBJ라면 `--unit m`을 명시한다.
- `mesh_polish`는 UV·텍스처·스킨·모프·애니메이션이 있는 glTF를 기본 거부한다. 그 데이터를 보존하는 최적화는 glTF-Transform/Blender로 한다.
- 여기까지로 안 되는 것(노멀맵 베이크, 스컬프트 디테일, 스킨 리깅)은 승급 대상이지 이 레인에서 흉내 낼 일이 아니다.

## 예제 수렵 — 없는 것은 만들지 말고 찾아라

프로덕션 씬은 주인공 메시 하나로 안 된다. 환경·소품·HDRI·텍스처는 검증된 CC0 팩을 가져와
파이프라인(실측→최적화→예산)에 태우는 것이 만들기보다 항상 빠르고 항상 좋아 보인다.

**실명 카탈로그가 `engine/data/asset_catalog.json` 에 있다** — Poly Haven HDRI(무드별 슬러그)·PBR 텍스처, ambientCG 머티리얼 ID, Kenney/Quaternius 팩, Khronos 샘플 모델의 검증된 URL 패턴·라이선스까지. 소스를 기억으로 더듬지 말고 카탈로그에서 고른다. 없는 것은 Sketchfab(CC0/CC-BY 필터)에서 모델별 라이선스를 확인하고 쓴다.

도구·내보내기·판정 자체를 검증할 때는 `specimens.md`의 로컬 `inspection-prop`과 목적별 Khronos 표본을 먼저 쓴다. 로컬 표본은 형상·단위 기준이고, PBR·애니메이션 기준을 대신하지 않는다.

| 소스 | 무엇 | 라이선스 |
|---|---|---|
| Khronos glTF-Sample-Assets | 규격 검증된 레퍼런스 모델(재질·애니메이션 포함) | 모델별 — 카탈로그에 실검증 값(DamagedHelmet 은 비상업) |
| Poly Haven | HDRI·PBR 텍스처·모델 | CC0 |
| ambientCG | PBR 텍스처·머티리얼 | CC0 |
| Kenney | 게임 소품·환경 팩(로우폴리) | CC0 |
| Quaternius | 게임 캐릭터·환경 팩 | CC0 |
| Sketchfab (CC 필터) | 개별 모델 — 필터를 CC0/CC-BY 로 걸고 쓴다 | 모델별 |

수렵 규약: ① 내려받은 자산도 **반드시 파이프라인을 태운다** — `mesh_audit`(치수·단위)·`scene_audit`(예산)을 통과 못 하는 자산은 예쁜 쓰레기다. ② 출처·라이선스를 `ASSETS.md` 에 한 줄씩 적는다(아래 라이선스 절). ③ 스타일 충돌은 머티리얼 통일(`mesh_polish` 재머티리얼)로 절반은 잡힌다.

## 엔진 통합 표준 — 넘길 곳의 규칙으로 내보낸다

| 항목 | Unreal | Unity |
|---|---|---|
| 단위 | 1uu = **1cm** (FBX 기본도 cm) | 1unit = **1m** (물리가 가정) |
| 명명 | `SM_`(스태틱 메시)·`SK_`·`T_..._D/_N`·`M_`/`MI_` 접두 | 강제 규약 없음 — UE 식 접두를 관행으로 |
| 피벗 | FBX 원점이 곧 피벗 — 모듈러 부품은 **모서리 원점**으로 그리드 스냅 | 자유 — 바닥 중심이 관례 |
| 콜리전 | `UCX_<렌더메시명>_##` (이름 정확 일치, 진짜 볼록) | 별도 메시 지정 |
| LOD | 단마다 −50%, 3–4단 | LOD1 50% · LOD2 25% · LOD3 10% (공식 가이드) |
| 라이트맵 UV | 전용 채널, 겹침 0, 차트 간 **4텍셀+ 패딩** | UV2 자동 생성 가능, 같은 무겹침 규칙 |

glTF 로 배달할 때 알아야 하는 확장: **KHR_texture_basisu**(KTX2 — 노멀·히어로는 UASTC, 알베도·보조는 ETC1S), **KHR_draco_mesh_compression**(정적 히어로) vs **EXT_meshopt_compression**(애니메이션·스트리밍 — 모프·애니메이션까지 압축, 디코드가 빠르다), **KHR_texture_transform**(트림 시트·아틀라스 전제), **KHR_materials_variants**(제품 구성기 — 한 자산에 여러 재질 구성). 수입 시 받아들일 PBR 확장: transmission/volume(유리), clearcoat, sheen, ior, specular. 내보내기 전 삼각화는 여기서도 규칙이다 — 베이커와 엔진의 자동 삼각화는 다르다.

## 좌표계와 단위 — 가장 흔한 사고

| 형식 | 업 축 | 단위 |
|---|---|---|
| glTF/GLB | Y-up | 미터 |
| STL/OBJ (CAD 유래) | 관례상 Z-up | 밀리미터 |
| Blender | Z-up | 미터(설정 가능) |
| USD | Y-up 또는 Z-up(파일 선언) | 파일 선언 |

CAD 에서 나온 40mm 브래킷은 glTF 로 내보내면 0.04 단위가 된다. 웹 씬에서 "모델이 안 보인다"의 절반은 이 문제다. `mesh_audit` 은 확장자로 단위를 추정해 mm 로 환산하고(`--unit` 으로 강제), `shoot` 은 헤더에 단위를 함께 적는다.

## 라이선스

- 자산마다 출처와 라이선스를 파일 옆에 기록한다(`ASSETS.md` 한 줄이면 된다). 나중에 추적할 수 없는 자산은 상업 배포에서 제거 대상이다.
- CC-BY 는 크레딧 표기가 **의무**다. 표기 위치를 정하지 않은 채 넣지 않는다.
- 생성형 서비스는 출력물의 상업적 권리를 플랜별로 다르게 준다. 무료 플랜 출력물을 상업 배포에 넣지 않는다.
