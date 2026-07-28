# 조립 — 데이텀·조인트·정렬

## 핵심 규칙

**배치는 소스에서 저작하고, 생성 후에 검증한다.** 내보낸 STEP 을 손으로 옮기거나, 뷰어에서 끌어서 맞추지 않는다. 파라미터·지역 좌표계·`Location`·`Plane`/`Axis` 데이텀·조인트로 표현하고, 그 결과를 `frame`·`align`·`measure` 로 확인한다.

숫자 하나짜리 `Location(...)` 은 대개 **명시된 데이텀·오프셋·간극·나사축·면 접촉**에 대응해야 한다. 대응하는 것이 없는 좌표는 나중에 아무도 못 고친다.

## 용어

헷갈리면 틀린 것을 고치게 된다.

- **AssemblyHelper** — `cadpy.assembly` 의 래퍼. `face_to_face`·`coaxial`·`revolute`·`linear` 같은 **의미 관계**를 기록하고, 내부에서 네이티브 build123d 조인트로 실현한다.
- **build123d 조인트** — `RigidJoint`·`RevoluteJoint`·`LinearJoint`·`CylindricalJoint`·`BallJoint`. 소스 수준 객체이고 `connect_to()` 로 부품을 옮긴다.
- **`inspect align`** — 셀렉터 쌍의 **읽기 전용 델타 계산기**. 소스를 고치지도, STEP 을 패치하지도 않는다. 저작된 메이트가 아니다.

가장 중요한 구분: **조인트는 소스 생성 시점의 일회성 배치 연산이지, STEP 안에 남는 지속 제약이 아니다.** 내보낸 STEP 에는 계산이 끝난 정적 배치와 네이티브 라벨만 들어간다. 이것을 오해하면 "STEP 을 열었더니 힌지가 안 움직인다"는 잘못된 기대가 생긴다.

## 구조

```text
루트 부품(고정)
→ 부품별 지역 좌표계
→ 이름 붙은 데이텀 / 조인트 위치
→ AssemblyHelper 의미 관계 (네이티브 조인트가 뒤를 받친다)
→ 라벨 붙은 Compound
→ refs / measure / frame / align 검증
```

```python
from build123d import *
from cadpy.assembly import AssemblyHelper

BASE_H = 30.0
LID_T = 3.0
GASKET_GAP = 0.5

def gen_step():
    asm = AssemblyHelper("enclosure")
    base = asm.add(make_base(), "base")
    lid = asm.add(make_lid(), "lid")

    seat = asm.rigid_frame(base, "lid_seat", Location((0, 0, BASE_H)))
    under = asm.rigid_frame(lid, "underside", Location((0, 0, -LID_T / 2)))

    asm.face_to_face(seat, under, offset=GASKET_GAP)
    return asm.build()
```

**고정 쪽을 먼저, 움직이는 쪽을 나중에 적는다.** 위에서는 base 가 고정이고 lid 가 움직인다. 순서를 뒤집으면 고정하려던 부품이 움직인다 — 조립 오류의 단골이다.

프레임 메서드는 네이티브 조인트 입력과 짝이 맞는다: `rigid_frame()`·`ball_frame()` 은 `Location` 을, `revolute_frame()`·`linear_frame()`·`cylindrical_frame()` 은 `Axis` 를 받는다.

베어링·기어단·체결 세트처럼 **단위로 배치되거나 반복되는 기능 묶음**은 `asm.add_module(name, children)` 으로 서브어셈블리 노드를 만든다. 그래야 `#o1.12.1` 같은 중첩 참조가 의미를 유지한다.

## 라벨

```python
asm.add(make_lid(), "lid")
asm.feature(Cylinder(radius=3.0, height=12.0), "m3_standoff", "front_left")
```

- 루트 조립체, 모든 부품, 서브어셈블리, **반복되는 부품의 각 어커런스**에 라벨을 붙인다.
- 반복 부품은 역할·위치로: `m3_screw:front_left`, `m3_screw:rear_right`. 그래야 위상과 뷰어 선택이 추적된다.
- 라벨에 `assembly`·`component`·`feature`·`datum`·`hardware` 같은 **위상 범주 이름을 접두사로 붙이지 않는다.** 그 범주는 트리가 이미 드러낸다. 라벨은 위상이 추론하지 못하는 것 — 역할·배치·인터페이스·반복·메이팅 목적 — 에 쓴다.
- 피처 라벨은 그 형상이 `Compound` 의 자식으로 **남아 있을 때만** STEP 을 건너 살아남는다. 불리언으로 빼거나 합친 피처 이력은 지속되지 않는다. 그런 의도는 소스 파라미터·이름 붙은 데이텀·검증 참조로 표현한다.

## 조인트 고르기

가장 단순한 것으로 관계를 표현한다.

| 조인트 | 언제 |
|---|---|
| `RigidJoint` / `rigid_frame()` | 고정 배치, 면 접촉 안착, 마운팅 데이텀, 인터페이스를 아는 수입 부품 |
| `RevoluteJoint` / `revolute_frame()` | 힌지·회전 자세. `Axis` 로 정의하고 각도 파라미터로 정적 포즈를 준다 |
| `LinearJoint` / `linear_frame()` | 슬라이더·래치·텔레스코픽 |
| `CylindricalJoint` / `cylindrical_frame()` | 축방향 이동 + 회전(나사, 핀-슬롯) |
| `BallJoint` / `ball_frame()` | 짐벌·구면 방향 |

최종 정적 배치만 중요하고 의미 있는 데이텀이 없으면, 파라미터화된 `Location` 을 그냥 쓰고 검증한다. 조인트를 위한 조인트를 만들지 않는다.

## 수입 부품

```python
from build123d import import_step
servo = asm.add(import_step("models/parts/sg90_servo.step"), "servo")
```

수입 형상은 여기서 저작한 것이 아니다. **원점과 방향을 가정하지 않는다.** `refs --facts --planes --positioning` 과 `measure` 로 실제 면·축·볼트 패턴을 재고, 그 측정값에서 `rigid_frame(...)` 위치를 유도한다. 검증은 저작 부품과 똑같이 한다.

## 검증

```bash
CAD=engine/scripts/cad.py
python $CAD inspect refs   assembly.step --facts --planes --positioning
python $CAD inspect align  assembly.step --moving '#o1.2.f1' --target '#o1.1.f3' --mode flush --axis z
python $CAD inspect frame  assembly.step '#o1.2'
python $CAD inspect measure assembly.step --from '#o1.1.f3' --to '#o1.2.f1' --axis z
```

그리고 **간섭은 선택이 아니다**:

```bash
uv run --no-project --python 3.12 --with build123d python engine/scripts/cad_build.py assembly.py --json
```

눈으로 보면 붙어 보이는 것이 커널에서는 73mm³ 겹쳐 있을 수 있다. 이 숫자는 사람이 볼 수 없고, refs·measure·align 도 내지 않는다. **간섭 부피 > 0 은 그냥 실패다** — "조금 겹친다"는 상태는 존재하지 않는다. `cad_gate` 의 `interference` 규칙이 이것을 막는다.

결합면에는 반드시 간극을 넣는다. 0 간극은 조립 불가와 같은 말이다(공정별 값은 `dfm.md`). 다만 리드가 얹히는 안착면처럼 **flush 가 의도인 곳은 0 이 맞다** — `cad_build.py` 가 목표 간극 미만이라고 WARN 을 내면, 의도한 0 인지 실수인지 사람이 판단해서 적는다.

## 어긋났을 때 고칠 자리

델타가 나오면 STEP 이 아니라 **소스에서** 고친다:

자식 `Location` 이동·회전 · `AssemblyHelper` 고정/이동 순서 · 오프셋 · 조인트 위치와 축 · 부품 지역 원점 규약 · 피처 오프셋 파라미터 · 스케치 평면 · 조립 계층 · 대칭 배치의 부호.

고친 뒤 재생성하고 실패했던 검사를 다시 돌린다. 그리고 무관한 형상이 변하지 않았는지 `diff` 로 본다.

## 보고

돌린 검사만 적는다.

```text
배치/조인트:
- 소스: RigidJoint lid_seat → underside (base 고정)
- base/lid Z 메이트 flush, 델타 0.00mm
- 나사 보스 축 정렬: XY 측정으로 확인
- lid 어커런스 좌표계: +Z 상방, 원점 조립 중심선
- 간섭: 쌍 base–lid 0mm³
```

배치가 걸리는 형상이 없으면 그렇게 적는다. 의도했지만 확인하지 않은 메이트는 **"미확인"** 으로 적는다 — 성공을 암시하지 않는다.
