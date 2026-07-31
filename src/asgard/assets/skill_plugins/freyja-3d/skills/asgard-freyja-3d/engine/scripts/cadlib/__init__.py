"""cadlib — 프레이야 3D 엔진의 CAD 런타임.

이 패키지가 존재하는 이유는 하나다. **엔진이 자기 능력을 남에게 빌리지 않는다.**

이전 판은 상류 스킬 라이브러리를 통째로 벤더링해서 그 CLI를 격리 실행했다. 동작은 했지만
셋이 걸렸다. ① 능력의 경계가 남의 저장소에 있어서, 무엇이 되는지 알려면 벤더 트리를 읽어야
했다. ② 커널(OpenCASCADE)이 없으면 아무것도 못 했다 — 사실을 하나도 못 내는 상태와 커널이
없는 상태가 같았다. ③ 상류 공백이 그대로 우리 공백이었다(뷰어 런처 부재 등).

여기서 뒤집는다:

- **커널은 선택이지 전제가 아니다.** `stepfile`·`drawing`·`slicing`·`robot`은 순수 파이썬이라
  설치 없이 즉시 돈다. 커널이 필요한 것은 형상을 **만들 때**(`kernel`)뿐이고, 이미 만들어진
  산출물에서 사실을 읽는 일은 커널 없이 끝난다.
- **못 하는 것을 통과로 세지 않는다.** 모든 판정은 `report.Check`를 거치고, 측정 불능은
  `warn`(미확인)이지 `pass`가 아니다. 침묵은 통과가 아니라는 규율이 자료구조에 박혀 있다.
- **산출물이 사실을 말한다.** 소스는 의도를 말한다. 검증 동사는 전부 파일을 읽지 소스를 읽지
  않는다.

계층 (아래가 하위):

    report          판정 어휘 — 무의존
    stepfile        ISO 10303-21 무커널 판독 — report만
    topology        위상 산출물(.step.glb) 읽기·쓰기 — report·stepfile
    kernel          build123d/OCP 어댑터 — 있으면 쓰고 없으면 정직하게 죽는다
    verbs           refs·measure·align·frame·diff — 위 전부
    drawing         DXF 생성·무커널 검증
    slicing         슬라이서 발견·슬라이싱·무커널 G-code 검증
    robot           URDF·SRDF·SDF 생성 계약과 교차 검증
    catalog         기성품 STEP 조달

진입점은 `engine/scripts/cad.py` 하나다. 이 패키지를 직접 실행하지 않는다.
"""

from __future__ import annotations

__all__ = ["VERSION"]

# 엔진 판올림과 함께 움직인다. 보고에 찍혀서 "어느 런타임이 낸 숫자인가"를 답한다.
VERSION = "3.0.0"
