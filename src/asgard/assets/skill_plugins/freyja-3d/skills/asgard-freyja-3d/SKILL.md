---
name: asgard-freyja-3d
description: "Freyja's 3D engine — Brisingamen. Use for every 3D task: parametric and precision CAD (build123d/CadQuery/OpenSCAD, STEP/STL/3MF/GLB, DFM and tolerance), realtime 3D on the web (Three.js WebGPU/TSL/WebGL2, React Three Fiber, TresJS, Threlte, glTF pipeline and performance budgets), 3D motion and camera choreography, generative 3D assets, product renders, and mesh repair. Ships a dependency-free verification runtime: offline multi-view rendering, kernel and mesh measurement, scene budget audit, and a static 3D defect detector."
---

# Brisingamen — Freyja의 3D 엔진

난쟁이 넷이 벼려 만든 목걸이의 이름을 쓴다. 이 엔진의 전제도 같다: **3D 는 보기 좋게 만드는 일이 아니라 치수가 맞는 물건을 만드는 일이다.**

엔진 1(`asgard-freyja-design`)과 엔진 2(`asgard-freyja2`)는 화면을 만든다. 이 엔진은 형상을 만든다. 세 엔진은 배타적이지 않다 — 3D 를 품은 웹 화면이면 이 엔진이 형상·성능·모션을 맡고, 레이아웃·타이포·카피는 엔진 1 또는 2 가 맡는다.

## 레인 선택

| 레인 | 언제 | 문서 |
|---|---|---|
| **cad** | 실제로 만들 물건. 치수·공차·조립·제조(3D 프린트, CNC, 판금, 사출). STEP 이 필요하면 무조건 이 레인. | `engine/reference/lane-cad.md` |
| **realtime** | 브라우저·앱에서 도는 3D. 씬 구성, 머티리얼·라이팅, WebGPU/TSL, 로딩, 성능 예산. | `engine/reference/lane-realtime.md` |
| **motion** | 카메라 연출, 스크롤 구동, 타임라인, 인터랙션, 물리. | `engine/reference/lane-motion.md` |
| **asset** | 모델을 확보·정리하는 일. 생성형 3D, 리토폴로지, 압축, 라이선스. | `engine/reference/lane-asset.md` |
| **art** | 히어로 자산을 현업 공정으로. 실루엣→하이폴리→베이크→마스크 텍스처→룩뎁, 예산·텍셀 밀도 기준. | `engine/reference/lane-art.md` |

한 요청이 두 레인을 넘나드는 것이 정상이다(예: 제품 구성기 = cad + realtime + motion). 레인을 고르는 것은 순서를 고르는 것이지 배제하는 것이 아니다.

## 고정 순서

1. **명세 확정** — `engine/reference/clarify.md`. 치수·단위·용도·공정·대상 기기 중 결과를 바꾸는 항목이 비어 있으면 **먼저 묻는다**. 묻지 않고 채운 치수는 환각이다. 근거: ProCAD(arXiv 2602.03045)는 사전 확인만으로 Chamfer 거리 79.9% 감소, 무효율 4.8%→0.9%.
2. **환경 확인** — `node engine/scripts/preflight.mjs [프로젝트]`. 막힌 레인이 있으면 지금 말한다. 나중에 "안 됐다"고 말하지 않는다.
3. **레인 문서 적재** — 해당 레인 문서 + `engine/reference/verify.md`. cad 레인은 `engine/reference/dfm.md`, realtime 레인은 `engine/reference/budgets.md` 를 같이 적재한다. 룩이 보이는 산출물(렌더 납품·realtime·art)은 만들기 직전 `engine/reference/look-floor.md` 를 적재한다 — 치수가 맞아도 초보 티가 나면 배달이 아니다. 조명·카메라·재질을 고르는 단계면 `engine/reference/lookdev.md` 와 `engine/data/` 카탈로그를 같이 적재한다.
4. **만든다** — 코드가 곧 모델이다. 파라메트릭 변수는 상단에 모으고, 마법의 숫자를 형상 안에 묻지 않는다.
5. **측정한다** — 커널·메시가 낸 숫자로. `cad_build.py` / `mesh_audit.mjs` / `scene_audit.mjs` / `detect3d.mjs`.
6. **본다** — `shoot.mjs` 로 여러 방향에서 렌더하고 **PNG 를 실제로 연다**. 근거: CADCodeVerify(ICLR 2025)·EvoCAD·3DCodeBench 모두, 렌더를 되먹이는 루프가 있을 때만 형상 오류가 잡힌다고 보고한다.
7. **고친다** — 검출된 항목을 코드에서 고친다. 판정 기준을 낮춰서 통과시키지 않는다.
8. **배달한다** — 아래 배달 게이트를 이름으로 하나씩 보고한다.

## 배달 게이트 (3D)

세 가지는 소스를 읽어서는 절대 판정할 수 없다. 산출물에서 확인하고, **항목 이름을 그대로 적어 보고**한다. 침묵은 통과가 아니라 미확인이다.

- **형상이 맞는가.** 렌더 이미지를 직접 열어서, 요청한 형상의 특징(구멍 위치, 벽 두께, 조립 방향, 비율)을 하나씩 대조했다. "코드상 맞다"는 확인이 아니다.
- **만들 수 있는가 / 돌아가는가.** cad 레인은 `mesh_audit` 판정(수밀·살두께·오버행)과 조립 간섭이 통과했다. realtime 레인은 `scene_audit` 예산과 `detect3d` FAIL 0 이다.
- **움직임이 살아 있는가.** 선언한 모션을 실제로 트리거해서 봤다. `enableDamping` 을 켜고 `controls.update()` 를 부르지 않은 코드는 정지 화면이다 — `detect3d` 의 `inert-controls` 가 이것만 잡는다. 저감 모션(prefers-reduced-motion) 경로도 같은 기준으로 확인한다.
- **초보 티가 없는가.** `look-floor.md` 의 검증 항목(조명·접지·카메라·재질·실루엣·톤·스케일)을 렌더에서 대조했고, 거부 목록과 겹치는 선택이 브리프 근거 없이 남아 있지 않다. 렌더를 열지 않고 매긴 룩 판정은 판정이 아니다.

자기 산출물에 대해 스스로 매긴 점수는 리뷰가 아니다. 리뷰라고 부르지 말고 자기 보고라고 적는다. 리뷰·품질 평가를 요청받으면 `engine/reference/critique3d.md` 를 적재해 서로 못 보는 두 평가(룩 리뷰 + 결정론 측정)로 판정하고, 스냅샷을 남겨 추세를 잰다.

## 런타임

전부 `engine/scripts/` 아래에 있고, 검증 스크립트는 **의존성이 없다**(node 내장 모듈만; node 18+). 설치·네트워크·브라우저·GPU 를 요구하지 않는다.

```bash
node engine/scripts/preflight.mjs [경로]                    # 이 기계에서 되는 레인 확인
node engine/scripts/shoot.mjs <model> --out shots \         # 오프라인 다면 렌더 → PNG 증거
     --views front,right,top,iso --highlight overhang|thick
node engine/scripts/mesh_audit.mjs <model> --process fdm    # 수밀·살두께·오버행·셸 (--shell N, --unit mm|m)
node engine/scripts/scene_audit.mjs <scene.glb> --target mobile   # 삼각형·드로우콜·VRAM·압축 예산
node engine/scripts/mesh_polish.mjs <model> --out game.glb \      # 게임 준비 — 부품 병합·크리스 스무딩·PBR 머티리얼
     --crease 40 --materials '{"blade":"steel","grip":"leather"}' \
     --bake --ao-samples 24                                       # 정점 AO·커버처 베이크 → COLOR_0 (마모·그라임 원료)
node engine/scripts/detect3d.mjs <소스경로>                  # 실시간 3D 코드 정적 결함 + 룩 슬롭
node engine/scripts/critique_store.mjs slug|write|latest|trend <대상>   # 판정 스냅샷·추세 (critique3d.md)
uv run --no-project --python 3.12 --with build123d \
   python engine/scripts/cad_build.py <model.py> --out build # 파라메트릭 빌드·내보내기·간섭 검사
```

- 모든 스크립트는 `--json` 으로 기계용 출력을 낸다. 판정이 fail 이면 종료 코드 1 이다. 예외: `preflight` 와 `shoot` 는 판정이 아니라 보고·증거라 항상 0 이다(막힌 레인은 `blockers` 로 읽는다).
- `shoot.mjs` 와 `mesh_audit.mjs` 는 STL·OBJ·GLB·glTF·3MF 를 읽는다. Draco/meshopt 압축 지오메트리는 디코드하지 않고 그렇다고 보고한다 — 조용히 빈 결과를 내지 않는다. 3MF 는 선언 단위를 mm 로 환산해 읽는다.
- 단위: 제조 판정은 전부 mm 다. glTF 는 규격상 미터라 `mesh_audit` 이 자동 환산한다(`--unit` 으로 강제 지정).
- `cad_build.py` 는 `PARTS = {"이름": 형상}` 규약을 읽고, 부품이 둘 이상이면 쌍마다 간섭 부피와 최소 간극을 잰다.

## 산출물 금고

이 엔진이 남기는 중간 산출물(렌더 시트, 진단 JSON, 빌드 결과)은 `.asgard/.vanadis/3d/` 아래에 쓴다. `.asgard/.vanadis/` 는 Freyja 엔진들의 공용 지붕이다(엔진 1 은 `engine1/`, 엔진 2 는 `engine2/`). `asgard init` 이 만든 `.asgard/` 는 이미 git 밖이므로 **별도 ignore 항목을 만들지 않고, 커밋을 제안하지도 않는다.**

사용자에게 넘기는 최종 산출물(STEP, GLB, 소스)은 금고가 아니라 프로젝트의 정상 경로에 둔다. 금고는 증거지 납품물이 아니다.

## 불변

- 사용자 표면의 언어·이모지 규약, 접근성 바닥(대비, 키보드 포커스, prefers-reduced-motion), 증거 우선 보고는 Asgard 전역 규약 그대로다.
- 3D 는 접근성 면제 구역이 아니다. 3D 로만 전달되는 정보에는 텍스트 대안이 있어야 하고, 카메라 자동 이동에는 정지 경로가 있어야 한다.
- 상류 도구(text-to-cad, cad-khana, synaps-cad, 상용 CAD, 생성형 3D 서비스)로 넘길 시점과 방법은 `engine/reference/escalation.md` 에 있다. 이 엔진으로 안 되는 일을 되는 척하지 않는다.
- 이 엔진의 판단 근거가 된 논문·벤치마크·실측은 `engine/reference/research.md` 에 출처와 함께 있다. 규칙을 바꾸려면 그 근거부터 확인한다.
