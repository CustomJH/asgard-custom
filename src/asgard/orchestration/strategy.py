"""오케스트레이션 형상 선택 — 이 요청을 어떤 모양으로 돌릴 것인가.

여태 이 선택은 **네 군데에 흩어져** 있었다. 분류기가 DIRECT 와 Trinity 를 가르고, Thinker 계획의
units 블록이 wave 병렬을 켜고, Worker 의 dispatch 툴이 딜리버리 전문가를 부르고, thor-lead 의
squad 툴이 편대를 띄웠다. 넷 다 합리적이었지만 **한 번도 같이 놓이지 않아서**, "이 요청은 왜
이 모양으로 돌았는가" 에 답할 자리가 없었다.

이 모듈이 그 선택에 이름을 준다. 판정은 순수 함수 하나이고, 입력은 이미 계산된 신호들이다 —
새로 모델을 부르지 않는다. 고른 형상은 Run 에 적혀서 나중에 되읽을 수 있다.

형상 넷:

  direct  쓰기가 없다. 오케스트레이션을 세우지 않는다 — 무세금 경로.
  single  일감 하나, 손 하나. Trinity 순환은 돌지만 DAG 가 없다.
  graph   일감 여럿이 의존으로 묶인다. wave 병렬 + `access` 의존 = 그래프 실행.
  squad   한 일감을 전문가 여럿이 나눠 든다. 딜리버리 fan-out 이 주된 일인 요청.

`graph` 와 `squad` 의 경계가 헷갈리기 쉽다. 기준은 **일감이 여럿인가, 손이 여럿인가** 다:
파일이 갈리고 순서가 있으면 graph 이고, 일은 하나인데 그 일이 전문 영역을 걸치면 squad 다.
"""

from __future__ import annotations

SHAPES = ("direct", "single", "graph", "squad")

# 딜리버리 fan-out 이 주된 일이라고 볼 최소 전문가 수. 하나만 걸리면 Worker 가 자기 dispatch
# 툴로 부르는 편이 싸다 — 편대를 세울 이유는 영역이 둘 이상 걸릴 때 생긴다.
_SQUAD_MIN_SPECIALISTS = 2


def choose(
    *,
    write_expected: bool = True,
    task_class: str = "deep",
    parallel_requested: bool = False,
    unit_count: int = 0,
    specialists: list[str] | None = None,
) -> dict:
    """이 요청의 오케스트레이션 형상을 고른다.

    Args:
        write_expected: 쓰기가 예상되는가. False 면 Trinity 자체가 안 선다.
        task_class: trivial / standard / deep — 퀘스트 로그의 예산 축과 같은 어휘.
        parallel_requested: 요청문이 병렬을 명시했는가(`classify._PARALLEL_WORK_PAT`).
        unit_count: Thinker 계획이 낸 배정 단위 수. 계획 전에는 0 이다.
        specialists: 이 과업에 매칭된 딜리버리 전문가 이름들.

    Returns:
        `{"shape": str, "why": str, "parallel": bool}`. `why` 는 사람이 읽을 한 문장이고
        그대로 Run 에 적힌다 — 나중에 "왜 이 모양이었나" 에 답하는 것이 이 값이다.
    """
    specialists = list(specialists or [])
    if not write_expected:
        return {"shape": "direct", "why": "쓰기 없음 — 오케스트레이션 미사용", "parallel": False}
    if unit_count >= 2:
        return {
            "shape": "graph",
            "why": f"배정 단위 {unit_count}개가 의존으로 묶인다 — wave 그래프 실행",
            "parallel": True,
        }
    if len(specialists) >= _SQUAD_MIN_SPECIALISTS:
        return {
            "shape": "squad",
            "why": "전문 영역 " + "·".join(specialists[:4]) + " 을 걸친다 — 딜리버리 fan-out",
            "parallel": True,
        }
    if parallel_requested and task_class == "deep":
        return {
            "shape": "graph",
            "why": "요청이 병렬을 명시했고 깊은 과업이다 — Thinker 가 배정 단위를 낸다",
            "parallel": True,
        }
    return {
        "shape": "single",
        "why": f"단일 손으로 충분하다 ({task_class})",
        "parallel": False,
    }
