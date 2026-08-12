"""되짚기 엔진에 닿는 자리 — 늦게 부르고, 없으면 침묵한다.

`--debt`·`--tip`·`--explain` 이 없는 모듈 때문에 죽으면 그건 관문이다(튜터 계약 ②). 표면이
엔진보다 먼저 배송될 수 있다는 전제가 이 모듈 전체의 계약이다.
"""

from __future__ import annotations

from dataclasses import asdict
from importlib import import_module
from typing import Any


def _engine(name: str) -> Any:
    """되짚기 엔진 하나를 늦게 부른다. 없으면 None — 표면이 엔진보다 먼저 배송될 수 있다.

    `--debt`·`--tip`·`--explain`이 없는 모듈 때문에 죽으면 그건 관문이다(튜터 계약 ②). 없을 때
    할 일은 실패가 아니라 침묵이다.
    """
    try:
        # 점 셋이다 — 엔진은 `asgard.tutor_debt` 처럼 `commands` 밖, 두 단 위에 있다.
        return import_module("..." + name, __package__)
    except Exception:
        return None


def _explanation(root: str, base: str, paths: tuple[str, ...], depth: str) -> Any:
    """설명 재료 하나. 엔진이 없거나 던지면 None — 침묵이지 실패가 아니다(튜터 계약 ②)."""
    teach = _engine("tutor_teach")
    if teach is None:
        return None
    try:
        return teach.explain(root, base, paths, depth)
    except Exception:
        return None


def _learned(root: str, exp: Any) -> None:
    """카드에 실린 말을 용어집에 더한다 — 다음 회차부터 그 말은 설명에서 빠진다(계약 ③).

    부르는 자리를 `explain()` 안이 아니라 표면에 두는 이유는 `tutor.hand_back`과 같다: **사람
    앞에 나간 것만 센다.** 기계가 훑어보는 호출(`--json`만)까지 병합하면 사람이 본 적 없는 말이
    "이미 설명한 말"이 되고, 그때부터 이 층은 설명해야 할 것을 조용히 건너뛴다.

    무엇이 실렸는지 아는 것은 엔진의 `shown_terms` 하나뿐이라 목록도 거기서 받는다. 카드가 상한
    아래로 자른 말과 `owned`·`familiar` 깊이에서 안 그린 말은 그래서 안 들어간다. `--explain`
    화면과 보고서는 그보다 더 많이 넣지만 적립은 카드 목록에만 맞춘다 — 덜 적립하면 그 말이 다음
    회차에 한 번 더 설명될 뿐이고, 더 적립하면 영영 설명 안 된다.

    엔진이 없거나 못 적으면 그냥 지나간다 — 튜터는 관문이 아니다.
    """
    teach = _engine("tutor_teach")
    if teach is None or exp is None:
        return
    try:
        teach.glossary_merge(root, teach.shown_terms(exp))
    except Exception:
        return


def _as_dict(exp: Any) -> dict | None:
    """`Explanation` → dict. 모양이 계약과 다르면 None — 반쯤 펴진 칸을 훅에 넘기지 않는다."""
    if exp is None:
        return None
    try:
        return asdict(exp)
    except Exception:
        return None


def _rationale_dict(why: Any) -> dict | None:
    """`Rationale` → dict. 변환은 엔진이 갖는다 — 칸 이름이 둘이면 훅 화면이 조용히 빈다."""
    engine = _engine("tutor_rationale")
    if why is None or engine is None:
        return None
    try:
        return engine.as_dict(why)
    except Exception:
        return None


def _rationale_lines(why: Any) -> list[str]:
    """ "왜 이렇게 했는가" 절의 줄. 규칙은 엔진 하나가 갖는다(훅 `_why` 와 같은 자를 쓴다)."""
    engine = _engine("tutor_rationale")
    if why is None or engine is None:
        return []
    try:
        return list(engine.lines(why))
    except Exception:
        return []


def _rationale(root: str, paths: object, quiz: bool, session: str = "") -> Any:
    """이 변경을 만든 퀘스트의 기록. `quiz` 모드에서는 안 읽는다 — 그쪽은 이 칸을 빈칸으로 둔다.

    `session` 은 활성 포인터를 이 세션의 것으로 좁히는 자다. 포인터는 저장소마다 하나라 옆 세션이
    연 퀘스트를 가리킬 수 있고, 그 기장의 목표가 이 변경의 이유 자리에 그대로 나온다. 훅은
    `--sid` 로 호스트 세션을 이미 알고 있어서 여기까지 넘기기만 하면 된다.

    엔진이 없거나 기록을 못 읽으면 None 이고, 그러면 화면과 보고서는 종전처럼 빈칸을 남긴다
    (`_explanation` 과 같은 계약 — 표면이 엔진보다 먼저 배송될 수 있다).
    """
    if quiz:
        return None
    engine = _engine("tutor_rationale")
    if engine is None:
        return None
    try:
        row = engine.rationale(root, paths, session)
    except TypeError:
        row = engine.rationale(root, paths)  # 세션 인자 이전의 엔진 — 표면이 먼저 배송될 수 있다
    except Exception:
        return None
    return row if row else None
