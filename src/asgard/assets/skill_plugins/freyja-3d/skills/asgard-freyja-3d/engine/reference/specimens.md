# 기준 자산 — 도구와 판정을 먼저 보정한다

자산 표본은 예쁜 예시 모음이 아니라 **파이프라인의 눈금**이다. 새 도구·내보내기 설정·렌더러를 도입할 때 같은 자산을 통과시켜 이전 결과와 비교한다.

## 로컬 기준 자산

`assets/inspection-prop/` 는 이 스킬에 포함된 소형 자가 제작 자산이다.

| 파일 | 역할 |
|---|---|
| `inspection-prop.py` | 치수·구멍·결합된 복수 형상을 가진 build123d 정본 |
| `build/inspection-prop.step` | B-Rep 왕복과 실측 기준 |
| `build/inspection-prop.stl` | 수밀·벽 두께·오버행·형상 렌더 기준 |
| `build/inspection-prop.glb` | glTF 미터 단위·Y-up·성능 예산 기준 |
| `evidence/inspection-prop-sheet.png` | front/right/top/iso 형상 기준 |
| `build/diagnostics.json`, `evidence/*.json` | 커널·메시·씬 감사 기준값 |

재생성:

```bash
uv run --no-project --python 3.12 --with build123d \
  python engine/scripts/cad.py step assets/inspection-prop/inspection-prop.py \
  --out assets/inspection-prop/build
node engine/scripts/shoot.mjs assets/inspection-prop/build/inspection-prop.stl \
  --out assets/inspection-prop/evidence --views front,right,top,iso --json
node engine/scripts/mesh_audit.mjs assets/inspection-prop/build/inspection-prop.stl \
  --process fdm --json
node engine/scripts/scene_audit.mjs assets/inspection-prop/build/inspection-prop.glb \
  --target mobile --json
```

생성 뒤 PNG를 열고, STEP/STL/GLB의 경계 상자 크기가 모두 60×36×52mm로 왕복하는지 확인한다. GLB 좌표는 미터여야 하므로 accessor 범위는 대략 0.06×0.036×0.052이다.

## 전기·통신 외함 표본

`assets/field-telemetry-kit/`는 90×95×69mm DIN 레일 미터와 좁은 방향으로 장착한 74.5×25×64.4mm RS485/LTE 게이트웨이를 한 마스터 모델에서 내보낸다. 공식 제품의 외형·인터페이스 범주만 참고한 원본 형상이며, 로고·내부 PCB·절연/인증 구조는 복제하거나 추정하지 않는다.

```bash
uv run --no-project --python 3.12 --with build123d \
  python engine/scripts/cad.py step assets/field-telemetry-kit/field-telemetry-kit.py \
  --out assets/field-telemetry-kit/build --clearance 10
node engine/scripts/shoot.mjs assets/field-telemetry-kit/build/field-telemetry-kit.stl \
  --out assets/field-telemetry-kit/evidence --views front,right,back,top,iso --json
node engine/scripts/mesh_audit.mjs assets/field-telemetry-kit/build/field-telemetry-kit.stl \
  --process sls --shell 1 --json
node engine/scripts/mesh_audit.mjs assets/field-telemetry-kit/build/field-telemetry-kit.stl \
  --process sls --shell 0 --json
node engine/scripts/mesh_polish.mjs assets/field-telemetry-kit/build/field-telemetry-kit.glb \
  --out assets/field-telemetry-kit/build/field-telemetry-kit-preview.glb --crease 38 \
  --materials '{"energy_meter":"plastic","rs485_lte_gateway":"aluminum"}' --bake --ao-samples 12
```

이 표본은 다부품 STEP·간섭/간극·서비스 포트·DIN 방향과 CAD GLB의 면 단위 드로우콜을 2개로 병합하는 납품 경로를 검증한다. 셸 0은 게이트웨이, 셸 1은 미터다. SLS는 형상 표본 제작 공정일 뿐 생산 외함 재료·공정 주장이 아니다. 생산 외함으로 승급하려면 `electrical-enclosures.md`의 PCB/커넥터/안전 입력이 별도로 필요하다.

## 외부 표본 — 목적별로 하나만 받는다

실제 PBR·애니메이션·확장 호환성은 로컬 형상 자산으로 판정할 수 없다. `engine/data/asset_catalog.json`의 URL과 모델별 라이선스를 다시 확인한 뒤 다음 중 목적에 맞는 하나만 받는다.

| 목적 | 표본 | 확인할 것 |
|---|---|---|
| 기본 metal/rough PBR | Khronos `WaterBottle` (CC0) | ORM 채널, tangent-space normal, 실제 뷰티 렌더 |
| 재질 보정 구 | Khronos `MetalRoughSpheres` (CC-BY 4.0) | metallic/roughness 응답과 톤매핑 |
| 확장 호환성 | Khronos `ToyCar` (CC0) | sheen·transmission·texture transform 지원 |
| 스킨·클립 | Khronos `Fox` (모델 metadata 확인) | joint influence, rest pose, clip 이름·루프 |
| HDRI·PBR 텍스처 | Poly Haven (CC0) | 선형/색상 채널, 해상도, 실제 파일 라이선스 |

Khronos Sample Assets는 모델별 `metadata.json`이 라이선스 정본이다. 저장소 전체의 라이선스로 개별 모델을 추정하지 않는다. Poly Haven 자산은 CC0지만 사이트 로고·썸네일·문구는 같은 조건이 아니다.

## 표본 게이트

1. 원본 해시·URL·라이선스를 프로젝트 `ASSETS.md`에 기록한다.
2. Khronos glTF Validator로 규격 오류 0을 확인한다.
3. `scene_audit`으로 대상 기기 예산을 확인한다. 규격 통과와 예산 통과는 서로 대체하지 않는다.
4. 형상은 `shoot` 시트, 룩은 실제 PBR 뷰어/DCC의 뷰티 렌더로 각각 판정한다.
5. 최적화 전후 같은 카메라에서 A/B 캡처한다. 파일 크기 감소만으로 품질 보존을 주장하지 않는다.
