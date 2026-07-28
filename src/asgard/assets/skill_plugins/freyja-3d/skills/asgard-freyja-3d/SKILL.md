---
name: asgard-freyja-3d
description: "Freyja's 3D engine — Brisingamen (브리싱가멘/브리싱아멘). Use for parametric and precision CAD (build123d/CadQuery/OpenSCAD, STEP-first generation with addressable selector refs, measurement, assembly joints and mating datums, DFM and tolerance), fabrication handoff (DXF cut layouts and kernel-free DXF audit, FDM G-code slicing and static validation, sheet-cutting preflight), off-the-shelf STEP part sourcing from a configured catalog, robot description files (URDF/SRDF/SDF with URDF-SRDF cross-validation), implicit signed-distance-field modelling (JavaScript fields, native surface-nets mesher), industrial electrical and telecom enclosures, realtime web 3D (Three.js WebGPU/TSL/WebGL2, React Three Fiber, TresJS, Threlte, glTF delivery and performance budgets), camera and interaction motion, procedural or sourced static assets, product visualization, and mesh diagnosis. Runs fully on Asgard-native code: a kernel-free ISO 10303-21 STEP reader, an offline software rasteriser with feature-edge linework and orbit GIF, and a server-side review viewer that ships no browser 3D library. Provides CAD-workbench snapshot rendering, kernel and mesh measurement, interference and clearance checks, scene budget audit, a static defect detector, a local review viewer, and a blocking delivery gate. Escalate electrical safety/certification, sculpting, character rigging, FEA/CFD simulation, cinematic rendering, artist UVs, and texture painting to the responsible expert pipeline."
---

# Brisingamen — Freyja의 3D 엔진

난쟁이 넷이 벼려 만든 목걸이의 이름을 쓴다. 이 엔진의 전제도 같다: **3D 는 보기 좋게 만드는 일이 아니라 치수가 맞는 물건을 만드는 일이다.**

엔진 1(`asgard-freyja-design`)과 엔진 2(`asgard-freyja2`)는 화면을 만든다. 이 엔진은 형상을 만든다. 세 엔진은 배타적이지 않다 — 3D 를 품은 웹 화면이면 이 엔진이 형상·성능·모션을 맡고, 레이아웃·타이포·카피는 엔진 1 또는 2 가 맡는다.

## 레인 선택

| 레인 | 언제 | 문서 |
|---|---|---|
| **cad** | 실제로 만들 물건. 치수·공차·조립·제조(3D 프린트, CNC, 판금, 사출). STEP 이 필요하면 무조건 이 레인. | `engine/reference/lane-cad.md` |
| **fabricate** | 만들어져 나오게 하는 일. 2D 도면·절단 레이아웃(DXF), FDM 슬라이싱(G-code), 절단 서비스 사전 검사. | `engine/reference/lane-fabricate.md` |
| **robot** | 로봇 기술 파일. URDF 구조, SRDF 계획 의미론(MoveIt2), SDF 시뮬레이터·월드. | `engine/reference/lane-robot.md` |
| **implicit** | 부호 거리장 조형(자바스크립트 필드). 부드러운 불리언, TPMS 격자, 절차적 형상. 실험적이고 기본이 아니다. | `engine/reference/lane-implicit.md` |
| **realtime** | 브라우저·앱에서 도는 3D. 씬 구성, 머티리얼·라이팅, WebGPU/TSL, 로딩, 성능 예산. | `engine/reference/lane-realtime.md` |
| **motion** | 카메라 연출, 스크롤 구동, 타임라인, 인터랙션, 물리. | `engine/reference/lane-motion.md` |
| **asset** | 모델을 확보·정리하는 일. 생성형 3D, 리토폴로지, 압축, 라이선스. | `engine/reference/lane-asset.md` |
| **art** | 히어로 자산을 현업 공정으로. 실루엣→하이폴리→베이크→마스크 텍스처→룩뎁, 예산·텍셀 밀도 기준. | `engine/reference/lane-art.md` |

한 요청이 두 레인을 넘나드는 것이 정상이다(예: 제품 구성기 = cad + realtime + motion, 발주 가능한 케이스 = cad + fabricate). 레인을 고르는 것은 순서를 고르는 것이지 배제하는 것이 아니다.

**순서는 고정이다: cad 가 검증을 끝낸 다음에 fabricate 가 온다.** 검증 안 된 형상을 절단이나 프린터에 태우지 않는다.

레인 공통 보조 문서: `engine/reference/lane-viewer.md`(로컬 리뷰 서버 — 모든 레인의 산출물을 연다).

## 고정 순서

1. **명세 확정** — `engine/reference/clarify.md`. 치수·단위·용도·공정·대상 기기 중 결과를 바꾸는 항목이 비어 있으면 **먼저 묻는다**. 묻지 않고 채운 치수는 환각이다. 근거: ProCAD(arXiv 2602.03045)는 사전 확인만으로 Chamfer 거리 79.9% 감소, 무효율 4.8%→0.9%.
2. **환경 확인** — `node engine/scripts/preflight.mjs [프로젝트]`. 막힌 레인이 있으면 지금 말한다. 나중에 "안 됐다"고 말하지 않는다.
3. **레인 문서 적재** — 해당 레인 문서 + `engine/reference/verify.md`. cad 레인은 `engine/reference/dfm.md` 와 `cad-refs.md`·`cad-snapshot.md` 를, 조립체면 `cad-assembly.md` 를, 참조 이미지나 2D 도면을 받았으면 `cad-brief.md` 를, realtime 레인은 `engine/reference/budgets.md` 를 같이 적재한다. 미터·모뎀·게이트웨이·전원 장치처럼 활선/통신/RF가 있는 외함은 `engine/reference/electrical-enclosures.md` 도 적재하고, 안전 입력이 없으면 외관/배치 표본에서 멈춘다. 룩이 보이는 산출물(렌더 납품·realtime·art)은 만들기 직전 `engine/reference/look-floor.md` 를 적재한다 — 치수가 맞아도 초보 티가 나면 배달이 아니다. 조명·카메라·재질을 고르는 단계면 `engine/reference/lookdev.md` 와 `engine/data/` 카탈로그를 같이 적재한다. 새 파이프라인·도구를 검증하거나 표본이 필요하면 `engine/reference/specimens.md` 의 로컬 기준 자산부터 돌린다.
4. **만든다** — 코드가 곧 모델이다. 파라메트릭 변수는 상단에 모으고, 마법의 숫자를 형상 안에 묻지 않는다. cad 레인은 `gen_step()` 규약을 쓴다.
5. **측정한다** — 커널·메시가 낸 숫자로. cad 레인은 `cad.py inspect refs --facts --planes --positioning` 을 **모든 생성물에 예외 없이** 돌리고, 사용자가 말한 치수마다 `measure`/`align`/`frame` 을 건다. 그 위에 `cad.py step`(쌍별 간섭·간극) / `mesh_audit.mjs`(공정) / `scene_audit.mjs` / `detect3d.mjs`.
6. **본다** — `node engine/scripts/snapshot.mjs` 로 CAD 워크벤치 뷰(면 + 에지 라인워크, 단면, 궤도 GIF)를 만들고 PNG 를 **실제로 연다**. 스냅샷은 의무이고, 결정론 검사 통과는 건너뛸 이유가 되지 못한다(`cad-snapshot.md`). 무의존 대체가 필요하면 `shoot.mjs` — 다만 그것은 위치와 법선만 그리므로 룩 판정에 쓰지 않는다. 룩이 납품물인 경우 Blender/실제 엔진/브라우저의 뷰티 렌더도 따로 열어 본다. 근거: CADCodeVerify(ICLR 2025)·EvoCAD·3DCodeBench 모두, 렌더를 되먹이는 루프가 있을 때만 형상 오류가 잡힌다고 보고한다.
7. **고친다** — 검출된 항목을 코드에서 고친다. 판정 기준을 낮춰서 통과시키지 않는다. 절차는 `cad-repair.md`.
8. **기계에 배달 자격을 묻는다** — `node engine/scripts/cad_gate.mjs <납품 경로>`. 막히면 고친다.
9. **배달한다** — 아래 배달 게이트를 이름으로 하나씩 보고한다.

## 배달 게이트 (3D)

산출물에서 확인하고, **항목 이름을 그대로 적어 보고**한다. 침묵은 통과가 아니라 미확인이다.

기계가 지는 몫과 사람이 지는 몫이 갈린다. `cad_gate.mjs` 가 바이트로 증명되는 것을 막고(가짜 STEP, 신선하지 않은 위상 산출물, 아무것으로도 검증되지 않은 형상, 렌더 증거 없음, 간섭 부피 > 0, 단위 없는 DXF), 그 위의 판단은 아래 네 항목이 진다. **게이트 통과는 아래 네 항목의 면제가 아니다** — 게이트는 못 재는 것을 `unjudged` 로 이름 붙여 같이 낸다.

- **형상이 맞는가.** 렌더 이미지를 직접 열어서, 요청한 형상의 특징(구멍 위치, 벽 두께, 조립 방향, 비율)을 하나씩 대조했다. "코드상 맞다"는 확인이 아니다.
- **명세를 다 쟀는가.** 사용자가 말한 치수·간극·관계마다 `measure`/`align`/`frame` 결과가 있다. 안 잰 것은 "미확인"으로 적었다. 도면에서 딴 치수도 같은 기준이다.
- **만들 수 있는가 / 돌아가는가.** cad 레인은 `mesh_audit` 판정(수밀·살두께·오버행)과 조립 간섭이 통과했다. realtime 레인은 `scene_audit` 예산과 `detect3d` FAIL 0 이다.
- **움직임이 살아 있는가.** 선언한 모션을 실제로 트리거해서 봤다. `enableDamping` 을 켜고 `controls.update()` 를 부르지 않은 코드는 정지 화면이다 — `detect3d` 의 `inert-controls` 가 이것만 잡는다. 저감 모션(prefers-reduced-motion) 경로도 같은 기준으로 확인한다.
- **초보 티가 없는가.** 실제 DCC/엔진/브라우저의 뷰티 렌더에서 `look-floor.md` 의 검증 항목(조명·접지·카메라·재질·실루엣·톤·스케일)을 대조했고, 거부 목록과 겹치는 선택이 브리프 근거 없이 남아 있지 않다. `shoot.mjs` 형상 시트만으로 매긴 룩 판정은 미확인이다.

자기 산출물에 대해 스스로 매긴 점수는 리뷰가 아니다. 리뷰라고 부르지 말고 자기 보고라고 적는다. 리뷰·품질 평가를 요청받으면 `engine/reference/critique3d.md` 를 적재해 서로 못 보는 두 평가(룩 리뷰 + 결정론 측정)로 판정하고, 스냅샷을 남겨 추세를 잰다.

## 런타임

두 층이다.

**① 무의존 층** — `engine/scripts/*.mjs`. node 내장 모듈만 쓴다(node 18+). 설치·네트워크·브라우저·GPU 를 요구하지 않는다. 다만 `scene_audit` 는 성능 예산 감사이지 glTF 규격 적합성 검사기가 아니다. 납품 GLB/glTF 는 Khronos glTF Validator도 통과시킨다.

**② CAD 층** — `engine/scripts/cad.py` 가 입구다. 실행체는 `engine/scripts/cadlib/` 에 있고 전부 이 엔진의 코드다.

이 층은 다시 둘로 갈린다. **산출물을 판독·검증하는 일**(`inspect`·`gcode`·`urdf`·`srdf`·`sdf`·`dxf check`)은 표준 라이브러리만 쓰므로 설치 없이 즉시 돈다 — STEP·DXF·G-code·로봇 파일이 전부 텍스트고, 위상 산출물은 우리가 쓴 파일이기 때문이다. **형상을 만드는 일**(`step`·`dxf` 생성)만 B-Rep 커널이 필요해서 uv 로 격리 실행한다(python 3.12 고정, 저장소 환경 무개입). **그 첫 실행은 커널 휠을 받느라 오래 걸린다 — 그 사실을 사용자에게 먼저 말한다.**

검증이 싸다는 것이 이 설계의 요점이다. 대화 중에 치수를 열 번 확인하는 것이 부담이 아니어야 실제로 열 번 확인한다.

```bash
CAD=engine/scripts/cad.py                                   # ② CAD 층 입구
python $CAD step     <model.py>                             # STEP + 위상 산출물 + 간섭·왕복 진단 [커널]
python $CAD inspect  refs <target> [#선택자...] --facts --planes --positioning
python $CAD inspect  measure|align|frame|diff <target> ...  # 셀렉터 기반 검증 (cad-refs.md)
node   engine/scripts/snapshot.mjs <target> --out shots --orbit 24   # 워크벤치 렌더 — 에지·단면·궤도 GIF
python $CAD dxf      <drawing.py>                           # 2D 도면·절단 레이아웃
python $CAD gcode    discover|inspect|slice|validate ...    # FDM 슬라이싱
python $CAD parts    search "M3 socket head 12"             # 기성 STEP 조달 (카탈로그 설정 필요)
python $CAD urdf|srdf|sdf <source.py>                       # 로봇 기술 파일 (srdf 는 --urdf 로 교차 검증)
node engine/scripts/cad_gate.mjs <납품 경로>                  # 배달 자격 판정 (막는다)

node engine/scripts/view.mjs --dir <산출물> --port 4178      # 로컬 리뷰 뷰어 (서버측 렌더)
node engine/scripts/implicit.mjs <model.implicit.mjs>       # SDF 조형 → 메시·렌더 (실험적)
node engine/scripts/preflight.mjs [경로]                    # 이 기계에서 되는 레인 확인
node engine/scripts/shoot.mjs <model> --out shots \         # 오프라인 다면 렌더 → PNG 증거
     --views front,right,top,iso --highlight overhang|thick
node engine/scripts/mesh_audit.mjs <model> --process fdm    # 수밀·살두께·오버행·셸 (--shell N, --unit mm|m)
node engine/scripts/scene_audit.mjs <scene.glb> --target mobile   # 삼각형·드로우콜·VRAM·압축 예산
node engine/scripts/mesh_polish.mjs <model> --out preview.glb \   # 무텍스처 CAD/메시 프리뷰 — mm→m·Y-up·스무딩·단색 PBR
     --crease 40 --materials '{"blade":"steel","grip":"leather"}' \
     --bake --ao-samples 24                                       # 정점 AO·커버처 베이크 → COLOR_0 (마모·그라임 원료)
node engine/scripts/detect3d.mjs <소스경로>                  # 실시간 3D 코드 정적 결함 + 룩 슬롭
node engine/scripts/critique_store.mjs slug|write|latest|trend <대상>   # 판정 스냅샷·추세 (critique3d.md)
```

- 모든 스크립트는 `--json` 으로 기계용 출력을 낸다. 판정이 fail 이면 종료 코드 1 이다. 예외: `preflight` 와 `shoot` 는 판정이 아니라 보고·증거라 항상 0 이다(막힌 레인은 `blockers` 로 읽는다).
- `shoot.mjs` 와 `mesh_audit.mjs` 는 STL·OBJ·GLB·glTF·3MF 를 읽는다. Draco/meshopt 압축 지오메트리는 디코드하지 않고 그렇다고 보고한다 — 조용히 빈 결과를 내지 않는다. 3MF 는 선언 단위를 mm 로 환산해 읽는다.
- `shoot.mjs` 는 위치와 면 법선만 그리는 형상 검사기다. PBR·UV·텍스처·스킨·모프·애니메이션·룩 판정은 실제 DCC/런타임의 렌더 증거가 필요하다.
- `mesh_polish.mjs` 는 STL·OBJ·무텍스처 CAD GLB용이다. UV·텍스처·스킨·모프·애니메이션이 있는 glTF는 손실 변환을 거부한다. 원본 glTF 최적화는 glTF-Transform/Blender를 쓰고, 의도적으로 버릴 때만 `--force-lossy`를 명시한다.
- 단위: 제조 판정은 전부 mm 다. glTF 는 규격상 미터라 `mesh_audit` 이 자동 환산한다(`--unit` 으로 강제 지정).
- `cad.py step` 는 `gen_step()` 을 먼저 보고, 없으면 `PARTS = {"이름": 형상}` 규약을 읽는다. 라벨 붙은 `Compound` 는 자식을 부품으로 펴서 **쌍마다 간섭 부피와 최소 간극**을 잰다. 그 두 숫자는 셀렉터 동사(`refs`·`measure`·`align`)가 내지 않는다 — 그래서 한 실행이 둘 다 낸다.
- `cad.py` 중 **형상을 만드는 도구**(`step`·`dxf` 생성)만 uv 를 요구한다. 없으면 설치 방법을 말하고 종료코드 3 으로 멈춘다 — 되는 척하지 않고, 검증 실패(1)와 다른 코드를 쓴다. 판독·검증 도구는 uv 없이 돈다.

## 산출물 금고

이 엔진이 남기는 중간 산출물(렌더 시트, 진단 JSON, 빌드 결과)은 `.asgard/.vanadis/3d/` 아래에 쓴다. `.asgard/.vanadis/` 는 Freyja 엔진들의 공용 지붕이다(엔진 1 은 `engine1/`, 엔진 2 는 `engine2/`). `asgard init` 이 만든 `.asgard/` 는 이미 git 밖이므로 **별도 ignore 항목을 만들지 않고, 커밋을 제안하지도 않는다.**

사용자에게 넘기는 최종 산출물(STEP, GLB, 소스)은 금고가 아니라 프로젝트의 정상 경로에 둔다. 금고는 증거지 납품물이 아니다.

## 불변

- 사용자 표면의 언어·이모지 규약, 접근성 바닥(대비, 키보드 포커스, prefers-reduced-motion), 증거 우선 보고는 Asgard 전역 규약 그대로다.
- 3D 는 접근성 면제 구역이 아니다. 3D 로만 전달되는 정보에는 텍스트 대안이 있어야 하고, 카메라 자동 이동에는 정지 경로가 있어야 한다.
- 상류 도구(cad-khana, synaps-cad, 상용 CAD, FEA/CFD, Blender, 생성형 3D 서비스)로 넘길 시점과 방법은 `engine/reference/escalation.md` 에 있다. 이 엔진으로 안 되는 일을 되는 척하지 않는다.
- CAD 런타임은 **이 엔진의 코드**다(`engine/scripts/cadlib/`, `engine/scripts/*.mjs`). 고칠 일이 생기면 그냥 고친다 — 상류에 물어볼 것도, 다음 동기화에 맞춰 미룰 것도 없다. 대신 능력의 경계를 이 문서와 레인 문서가 정확히 적고 있어야 한다.
- fabricate 레인의 마지막 칸(프린터 전송, 절단 발주)은 **실물과 돈이 움직인다.** 되돌리기 어렵거나 바깥으로 나가는 동작은 사용자 승인을 먼저 받는다는 전역 규약이 그대로 걸린다.
- 이 엔진의 판단 근거가 된 논문·벤치마크·실측은 `engine/reference/research.md` 에 출처와 함께 있다. 규칙을 바꾸려면 그 근거부터 확인한다.
