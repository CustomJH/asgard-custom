"""장부가 아직 안 선 경로가 쓰는 비활성 장부와, 형상 판정을 먼저 두는 진입점."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....orchestration import choose_shape
from .ledger import BifrostLedger
from .shape import _NullLedgerShapeMixin

if TYPE_CHECKING:
    from ..core import Heimdall


class _NullLedger(_NullLedgerShapeMixin):
    """장부가 아직 안 선 경로가 쓰는 비활성 장부.

    Heimdall 은 퀘스트 밖에서도 wave 를 돌릴 수 있고(재개 경로), 테스트 대역은 TrinityRun 을
    거치지 않는다. 그 경로마다 `if ledger:` 를 두는 대신 아무 일도 안 하는 대역을 기본값으로
    세운다 — 분기가 없으면 어느 갈래를 빠뜨릴 일도 없다.
    """

    enabled = False
    run_id = ""
    root = ""
    notes: list[str] = []

    def _note(self, where: str, exc: BaseException) -> None:
        return None

    def matched_specialists(self) -> list[str]:
        return []

    def spend_model_answer(self) -> bool:
        return False

    def open_turn(self, *args, **kwargs) -> str:
        return ""

    def settle_turn(self, *args, **kwargs) -> None:
        return None

    def register_units(self, *args, **kwargs) -> None:
        return None

    def open_unit(self, *args, **kwargs) -> str:
        return ""

    def settle_unit(self, *args, **kwargs) -> None:
        return None

    def stop_unit(self, *args, **kwargs) -> None:
        return None

    def ready_tasks(self) -> list[dict] | None:
        return None  # 장부가 없다 — "준비된 일감이 없다"(빈 목록)와 다른 답이다

    def drain(self, *args, **kwargs) -> list[dict]:
        return []

    def blocked_on(self) -> list[dict]:
        return []

    def gate(self, *args, **kwargs) -> str:
        return ""

    def escalate(self, *args, **kwargs) -> None:
        return None

    def close(self) -> None:
        return None

    def ask_handler(self, *args, **kwargs):
        def handler(inp: dict) -> str:
            return BifrostLedger._unanswered()

        return handler


NULL_LEDGER = _NullLedger()


def open_ledger(hd: Heimdall, qid: str, request: str, cls: dict):
    """이 퀘스트의 배차 장부를 연다 — 형상이 direct 면 안 연다.

    형상 판정을 장부보다 **먼저** 두는 자리다. direct 는 "오케스트레이션을 세우지 않는다" 는
    뜻이므로 Run 을 묶는 것부터가 그 판정과 어긋난다 — 쓰기가 없는 요청에 DB 를 열고 Task 를
    쌓으면 무세금 경로가 아니게 된다.

    Returns:
        `BifrostLedger`, 또는 direct 형상이면 아무것도 안 적는 비활성 장부. 어느 쪽이든
        호출부는 같은 표면을 쓴다 — 분기가 없으면 어느 갈래를 빠뜨릴 일도 없다.
    """
    if choose_shape(write_expected=bool(cls.get("write_expected", True)))["shape"] == "direct":
        return _NullLedger()
    return BifrostLedger(hd, qid, request)
