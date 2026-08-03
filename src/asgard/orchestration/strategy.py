"""오케스트레이션 형상 선택 — 이 요청을 어떤 모양으로 돌릴 것인가.

여태 이 선택은 **네 군데에 흩어져** 있었다. 분류기가 DIRECT 와 Trinity 를 가르고, Thinker 계획의
units 블록이 wave 병렬을 켜고, Worker 의 dispatch 툴이 딜리버리 전문가를 부르고, thor-lead 의
squad 툴이 편대를 띄웠다. 넷 다 합리적이었지만 **한 번도 같이 놓이지 않아서**, "이 요청은 왜
이 모양으로 돌았는가" 에 답할 자리가 없었다.

이 모듈이 그 선택에 이름을 준다. 판정은 순수 함수 하나이고, 입력은 이미 계산된 신호들이다 —
새로 모델을 부르지 않는다. 고른 형상은 Run 에 적혀서 나중에 되읽을 수 있고, **분기보다 먼저**
불려서 어느 갈래로 갈지를 정한다 (`trinity.TrinityRun._worker_turn`).

형상 넷:

  direct  쓰기가 없다. 오케스트레이션을 세우지 않는다 — 배차 장부도 안 연다.
  single  일감 하나, 손 하나. Trinity 순환은 돌지만 DAG 가 없다.
  graph   일감 여럿이 의존으로 묶인다. wave 병렬 + `access` 의존 = 그래프 실행.
  squad   한 일감을 전문가 여럿이 나눠 든다. 딜리버리 fan-out 이 주된 일인 요청.

`graph` 와 `squad` 의 경계가 헷갈리기 쉽다. 기준은 **일감이 여럿인가, 손이 여럿인가** 다:
파일이 갈리고 순서가 있으면 graph 이고, 일은 하나인데 그 일이 전문 영역을 걸치면 squad 다.

**계획이 배정 단위 수를 쥔다.** 분류 신호만 본 판정과 Thinker 계획이 엇갈릴 때 — 신호는 병렬을
가리켰는데 계획이 단위를 하나만 냈거나, 신호는 squad 인데 계획이 넷을 냈거나 — 이길 쪽은
계획이다. 계획은 요청 원문과 저장소를 읽고 나온 값이고 신호는 그 전의 추정이다. 다만 엇갈린
사실 자체는 `disagreement` 로 돌려주고 호출부가 Run 에 적는다: 감사할 수 없는 라우터는 이
계층이 없애려던 바로 그것이다.
"""

from __future__ import annotations

SHAPES = ("direct", "single", "graph", "squad")

# 딜리버리 fan-out 이 주된 일이라고 볼 최소 전문가 수. 하나만 걸리면 Worker 가 자기 dispatch
# 툴로 부르는 편이 싸다 — 편대를 세울 이유는 영역이 둘 이상 걸릴 때 생긴다.
_SQUAD_MIN_SPECIALISTS = 2

# 그래프 실행으로 볼 최소 배정 단위 수. `planning._parse_units` 도 같은 하한을 쓴다 — 단위가
# 하나인 계획은 wave 가 아니라 단일 Worker 턴이다.
_GRAPH_MIN_UNITS = 2


def _by_signals(task_class: str, parallel_requested: bool, specialists: list[str]) -> str:
    """계획을 보기 전, 분류 신호만으로 고른 형상 (direct 는 여기서 안 나온다)."""
    if len(specialists) >= _SQUAD_MIN_SPECIALISTS:
        return "squad"
    if parallel_requested and task_class == "deep":
        return "graph"
    return "single"


def _why(shape: str, task_class: str, unit_count: int, specialists: list[str]) -> str:
    """이 형상을 고른 이유 한 문장 — 그대로 Run 의 `shape_why` 가 된다."""
    if shape == "graph":
        if unit_count >= _GRAPH_MIN_UNITS:
            return f"배정 단위 {unit_count}개가 의존으로 묶여요 — wave 그래프로 실행해요"
        return "요청이 병렬을 명시했고 깊은 과업이에요 — Thinker가 배정 단위를 내요"
    if shape == "squad":
        return "전문 영역 " + "·".join(specialists[:4]) + "을 걸쳐요 — 딜리버리 fan-out이에요"
    return f"단일 손으로 충분해요 ({task_class})"


def choose(
    *,
    write_expected: bool = True,
    task_class: str = "deep",
    parallel_requested: bool = False,
    unit_count: int = 0,
    specialists: list[str] | None = None,
    planned: bool = False,
) -> dict:
    """이 요청의 오케스트레이션 형상을 고른다.

    Args:
        write_expected: 쓰기가 예상되는가. False 면 Trinity 자체가 안 선다.
        task_class: trivial / standard / deep — 퀘스트 로그의 예산 축과 같은 어휘.
        parallel_requested: 요청문이 병렬을 명시했는가(`classify._PARALLEL_WORK_PAT`).
        unit_count: Thinker 계획이 낸 배정 단위 수. 계획 전에는 0 이다.
        specialists: 이 과업에 매칭된 딜리버리 전문가 이름들.
        planned: 계획을 이미 읽었는가. True 면 `unit_count` 가 추정이 아니라 사실이라,
            신호가 graph 를 가리켜도 단위가 둘 미만이면 그래프로 돌 일감이 없다고 본다.

    Returns:
        `{"shape": str, "why": str, "parallel": bool, "disagreement": str}`. `why` 는 사람이
        읽을 한 문장이고 그대로 Run 에 적힌다. `disagreement` 는 신호와 계획이 엇갈렸을 때만
        차 있고, 그렇지 않으면 빈 문자열이다.
    """
    specialists = list(specialists or [])
    if not write_expected:
        return {
            "shape": "direct",
            "why": "쓰기가 없어서 오케스트레이션을 쓰지 않아요",
            "parallel": False,
            "disagreement": "",
        }
    signal = _by_signals(task_class, parallel_requested, specialists)
    if unit_count >= _GRAPH_MIN_UNITS:
        shape = "graph"
    elif planned:
        # 계획이 단위를 둘 이상 안 냈다. 신호가 무엇을 가리켰든 나눠 돌릴 일감이 없다.
        shape = "squad" if len(specialists) >= _SQUAD_MIN_SPECIALISTS else "single"
    else:
        shape = signal
    disagreement = ""
    if planned and shape != signal:
        disagreement = (
            f"신호는 {signal}를 가리켰지만 계획이 낸 배정 단위는 {unit_count}개예요 — 단위 수는 계획이 정해요"
        )
    return {
        "shape": shape,
        "why": _why(shape, task_class, unit_count, specialists),
        "parallel": shape in ("graph", "squad"),
        "disagreement": disagreement,
    }
