# fabricate 레인 — 도면·슬라이싱·발주

형상이 맞는 것과 **만들어져 나오는 것**은 다른 문제다. 이 레인은 그 사이를 덮는다: 2D 도면(DXF), FDM 슬라이싱(G-code), 절단 서비스 사전 검사, 프린터 작업 전송.

cad 레인이 STEP 을 검증한 **다음에** 온다. 검증 안 된 형상을 발주에 태우지 않는다.

## DXF — 2D 도면·절단 레이아웃

판금·레이저·플라즈마·워터젯·CNC 라우팅은 **도면이 최종 산출물**이다.

소스는 `gen_dxf()` 를 정의한 파이썬이고, 출력 경로는 CLI 가 갖는다.

```python
import ezdxf

WIDTH, HEIGHT = 80.0, 50.0

def gen_dxf():
    doc = ezdxf.new(setup=True)
    doc.units = ezdxf.units.MM          # 이 줄이 없으면 발주가 막힌다
    msp = doc.modelspace()
    doc.layers.add("cut")
    msp.add_lwpolyline([(0, 0), (WIDTH, 0), (WIDTH, HEIGHT), (0, HEIGHT)],
                       close=True, dxfattribs={"layer": "cut"})
    return doc
```

```bash
python engine/scripts/cad.py dxf drawing.py
python engine/scripts/cad.py dxf drawing.py -o out/drawing.dxf
```

기본값과 규율:

- **단위는 문서에 명시한다**(`doc.units = ezdxf.units.MM`). `$INSUNITS` 가 없거나 모르는 값이면 절단 서비스는 치수를 신뢰하지 않는다 — `cad_gate` 의 `dxf-units` 가 막는다.
- 형상은 모델스페이스에 1:1 로 둔다.
- 절단 프로파일은 **닫힌** 폴리라인/루프다. 열린 컨투어는 각인·참조 형상에만.
- **레이어가 의도를 나른다.** 절단 형상과 굽힘선을 다른 레이어로 두고, 굽힘 레이어 이름에 `bend` 를 넣는다 — 하류 도구가 그것으로 굽힘과 절단을 가른다.
- **3D 부품에서 나온 도면이면 실제 위상에서 투영한다.** STEP 을 먼저 만들고 검증한 다음, 같은 소스에 `gen_dxf()` 를 더해 실제 평면 면을 골라 펴서 닫힌 컨투어를 낸다. 손으로 다시 그린 외곽선은 부품이 바뀌면 조용히 어긋난다.
- 도면에는 **기준면(datum)과 공차**를 적는다. 공차 없는 도면은 "알아서 하라"는 뜻이고, 그러면 안 맞는다.

`scripts/dxf` 는 생성기이지 기존 `.dxf` 조사기가 아니다. 이미 있는 DXF 를 검사하려면 `ezdxf` 로 직접 읽는다:

```python
doc = ezdxf.readfile("out/drawing.dxf")
msp = doc.modelspace()
closed = [e for e in msp.query("LWPOLYLINE") if e.closed]
```

엔티티 수·레이어별 분포·닫힘 여부·도면 범위, 그리고 **사용자가 말한 치수 전부**를 확인한다. 눈으로 보고 넘기지 않는다.

## G-code — FDM 슬라이싱

실제 슬라이서 CLI 를 부르는 래퍼다. 프린터 비의존이고, 업로드·작업 시작·패키징을 하지 않는다.

```bash
CAD=engine/scripts/cad.py
python $CAD gcode discover                                    # 이 기계의 백엔드
python $CAD gcode inspect --input model.stl --json            # 슬라이스 가능한 메시인가
python $CAD gcode slice --input model.stl --output out.gcode \
       --profile printer.json --backend auto --dry-run        # 명령을 먼저 본다
python $CAD gcode slice ... --execute                         # 그 다음에 실행
python $CAD gcode validate --gcode out.gcode --profile printer.json --json
```

- **프로파일 JSON 을 반드시 요구한다.** 실제 프린터 프로파일을 지어내지 않는다. 래퍼는 `backend`·`native_config`(절대경로)·`machine`(bed 크기, z 높이, 선택적 motion bounds)·`filament` 를 담는다.
- 입력은 `.stl`·`.obj`·미슬라이스 `.3mf`·`.ply`·`.glb`·`.gltf`. **`.step`·`.dxf`·`.svg`·`.urdf`·`.sdf` 는 받지 않는다** — cad 레인에서 메시로 먼저 내린다.
- 백엔드 선호 순서는 OrcaSlicer → PrusaSlicer → CuraEngine. Bambu Studio 는 감지되어도 선호하지 않는다(macOS CLI 내보내기 불안정).
- **드라이런을 먼저 본다.** 생성될 명령과 프로파일이 맞는지 확인한 다음에만 `--execute`.
- **검증은 프린터로 넘기기 전에 항상.** 내용 유무·온도 명령·이동 명령·압출·XYZ 범위·미지 명령을 본다.

## 절단 서비스 사전 검사 (SendCutSend)

`vendor/text-to-cad/skills/sendcutsend/` 에 워크플로와 보고 서식이 있다. 요지만:

- **공식 소스를 매번 새로 받는다.** 주문 가이드·카탈로그 JSON·스펙 JSON 은 API 가 아니라 증거 피드다. 필드가 없거나 파싱이 안 되거나 `N/A` 인 것을 **통과나 실패로 바꾸지 않는다.**
- 파일 사실은 **업로드할 그 파일**에서 잰다. 소스 생성기나 콘솔 요약을 대신 보지 않는다.
- 판정 라벨은 셋: 통과 / 실패 / **정보 부족**. 세 번째를 없애려고 두 번째나 첫 번째로 밀지 않는다.
- 굽힘이 걸리면 **굽힘선마다 국부 플랜지 깊이**를 양쪽에서 잰다. 노치·슬롯·탭이 굽힘 구간을 끊는 자리가 실패의 단골이고, 전체 평균값으로는 잡히지 않는다.
- DXF 단위(`$INSUNITS`)가 없거나 예상 밖이면 **스케일 오류로 보고**한다. 조용히 재스케일하지 않는다.
- 재료/SKU 가 특정되지 않으면 후보를 제시하고 사용자에게 고르게 한다. 정확한 SKU 만이 카탈로그·스펙 조인의 권위 있는 키다.

## 프린터 작업 전송 (Bambu)

`vendor/text-to-cad/skills/bambu-labs/` — 검증된 plain `.gcode` 를 받아 LAN 으로 넘긴다. **이 레인의 마지막 칸이고, 실물 장비가 움직인다.**

- 프린터를 실제로 움직이는 동작은 **사용자 승인 없이 하지 않는다.** 아스가르드 전역 규약(되돌리기 어렵거나 바깥으로 나가는 동작은 먼저 확인)이 여기에 그대로 걸린다.
- G-code 검증을 통과하지 않은 것을 전송하지 않는다.
- 프린터가 응답하지 않는 것과 작업이 실패한 것은 다르다. 둘을 구분해서 보고한다.

## 배달 게이트

```bash
node engine/scripts/cad_gate.mjs <납품 경로>
```

이 레인에서 기계가 막는 것: 단위 없는 DXF(`dxf-units`), 검증 없는 G-code(`gcode-unvalidated`, 경고), 0 바이트 산출물.

기계가 **판정하지 못하는 것**: 재료 선택이 용도에 맞는가, 공차가 그 공정에서 실제로 나오는가, 굽힘 순서가 물리적으로 가능한가. 이것들은 사람이 판단하고, 판단했다고 적는다.
