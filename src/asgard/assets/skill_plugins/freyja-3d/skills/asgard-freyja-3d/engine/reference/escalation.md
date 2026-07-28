# 승급 경로 — 이 엔진 밖으로 넘겨야 할 때

이 엔진은 "코드로 형상을 만들고, 측정하고, 눈으로 확인하는" 범위를 덮는다. 그 밖의 일은 다른 도구가 낫다. **되는 척하지 않고 넘긴다.**

넘길 때는 세 가지를 함께 말한다: 무엇이 부족한가, 무엇으로 넘길 것인가, 그 도구가 요구하는 비용(설치·계정·네트워크·학습).

## 상류 도구

| 도구 | 언제 넘기는가 | 비용 |
|---|---|---|
| **cad-khana** (Apache-2.0) | build123d 진단 루프를 CLI 로 굳히고 싶을 때. 정투상 라인아트 도면 생성, 진단 diff | uv, OCP 뷰어(선택) |
| **synaps-cad** (MIT/Apache-2.0) | OpenSCAD 소스를 정확 유리수 연산으로 다뤄야 할 때, 브라우저 내 CAD IDE 가 필요할 때 | Rust 빌드 또는 웹 데모, 초기 프로토타입 단계 |
| **WebGPU/TSL 전용 스킬** (dgreenheck, MIT) | TSL 셰이더·컴퓨트를 깊게 파야 할 때. r183+ API 예제 모음 | Claude Code 스킬 설치 |
| 상용 CAD (Fusion, SolidWorks, Onshape) | GD&T/PMI, 대형 어셈블리, 판금 정확 전개, 클래스-A 곡면, 도면 승인 워크플로 | 라이선스, 사람의 조작 |
| FEA/CFD (CalculiX, Elmer, 상용) | 강도·열·유동 검증 | 해석 지식 필요 — 숫자를 낼 수는 있어도 해석은 별개다 |
| Blender | 유기적 모델링, 리깅·스키닝, 시네마틱 렌더, 리토폴로지 | 설치, Python API 는 자동화 가능 |
| 생성형 3D 서비스 | 텍스트/이미지에서 초안 메시 | 계정·네트워크, 상업 이용 조건 확인 필수 |

## Blender 헤드리스 브리지 — 게임 자산 승급의 실무 경로

경계선부터: 병합·크리스 스무딩·PBR 머티리얼·GLB 재작성까지는 `mesh_polish.mjs` 가 무의존으로 한다.
Blender 로 넘기는 것은 그 너머다 — **UV 전개, 텍스처·노멀맵 베이크, 스컬프트/유기 조형, 리깅·스키닝, 시네마틱 라이팅**.

`preflight` 가 blender 를 감지하면 art/asset 레인의 반복 가능한 변환을 헤드리스로 실행할 수 있다:

```bash
blender -b --python job.py -- in.glb out.glb    # -b = UI 없이, -- 뒤가 스크립트 인자
```

```python
# job.py 골격 — 임포트→가공→글TF 내보내기. bpy 버전에 따라 오퍼레이터 이름이 흔들리니
# 실패 메시지를 그대로 읽고 고친다. 결과는 반드시 scene_audit 로 되검사한다.
import bpy, sys
src, dst = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
for obj in bpy.data.objects:
    if obj.type != "MESH":
        continue
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.shade_smooth_by_angle(angle=0.6981)      # 40° — mesh_polish 와 같은 기준
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB")
```

- 위 코드는 브리지 골격이지 프로덕션 UV나 베이크 레시피가 아니다. Smart Project 결과를 아티스트 UV라고 부르지 않는다.
- 산출물은 반드시 이 엔진으로 되돌아온다: Khronos glTF Validator(규격)·`scene_audit`(예산)·`shoot`(형상 증거)·실제 렌더러의 뷰티 캡처(룩). Blender 를 거쳤다는 사실은 검증이 아니다.
- Blender 가 없으면 되는 척하지 않는다 — game 레인 preflight 문구대로 설치를 안내하고, 그동안 1단(mesh_polish)과 예제 수렵(lane-asset)으로 진행한다.

## 넘기기 전에 확인할 것

- **정말 부족한가.** "복잡해 보인다"는 이유로 넘기지 않는다. 이 엔진의 스크립트는 조립체 간섭·오버행·예산까지 덮는다.
- **결과를 되돌려 받을 수 있는가.** 상류 도구가 STEP/GLB 를 내면 이 엔진의 검증 루프로 다시 들어올 수 있다. 그렇게 설계한다.
- **사용자가 그 비용을 낼 준비가 됐는가.** 설치·계정이 필요한 경로는 먼저 말하고 승인을 받는다.

## 예전에 넘기던 것 — 이제 이 엔진 안에 있다

로봇 기술 파일(URDF/SRDF/SDF), G-code 슬라이싱과 정적 검증, 시트 절단 사전 검사, 셀렉터 기반 STEP 검증, 조립 간섭·간극, CAD 워크벤치 스냅샷, 암시적 SDF 조형, 로컬 리뷰 뷰어. **더 이상 승급 대상이 아니다.**

런타임은 `engine/scripts/cadlib/`(파이썬)과 `engine/scripts/*.mjs`(노드)에 있고 전부 이 엔진의 코드다. 입구는 `engine/scripts/cad.py`, 레인 문서는 `lane-cad.md`·`lane-fabricate.md`·`lane-robot.md`·`lane-implicit.md`·`lane-viewer.md`. 이것들을 "설치가 필요한 외부 도구"라고 말하지 않는다 — **판독·검증은 아무것도 필요 없고**, 형상 생성에만 uv 가 든다.

## 넘기지 않아도 되는 흔한 오해

- "STEP 을 만들려면 상용 CAD 가 필요하다" — build123d/CadQuery 가 OpenCASCADE 커널로 직접 낸다.
- "3D 렌더를 보려면 GPU 나 브라우저가 필요하다" — `shoot.mjs` 는 node 만으로 다면 렌더를 만든다.
- "웹 3D 성능은 실기기에서만 알 수 있다" — 자산 예산은 정적으로 판정된다. 프레임률만 실기기 영역이다.
- "생성형 3D 가 CAD 를 대체한다" — 치수가 없는 메시는 제조 산출물이 아니다.
- "나사·베어링·모터는 직접 모델링해야 한다" — 나사산을 그리면 파일만 무거워지고 정확도는 오히려 떨어진다. 카탈로그가 설정돼 있으면 `cad.py parts` 로 실제 STEP 을 받고, 없으면 **치수를 명시한 자리표시자**를 만들고 보고에 그렇게 적는다(`lane-cad.md`).
