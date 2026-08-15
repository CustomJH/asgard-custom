"""siege roundtable — 좌석을 앉히고 회차를 돌린 뒤 전사를 낸다.

토론 자체는 `asgard.roundtable` 이 한다. 이 모듈이 지는 것은 그 바깥 셋이다: 좌석 명세를
읽고, 전사를 남길 장부 Run 을 정하고, 사람이 읽을 형태로 찍는다.
"""

from __future__ import annotations

import json
import os

from .. import orchestration as orc
from .. import ui
from ..roundtable import auto_seats, convene, parse_seats
from .health import _project_root

_LINE_CAP = 2000  # 화면에 찍는 한 발언의 상한. 전문은 `--json` 이나 장부에 남는다
# 좌석 표기에 쓰는 사람이 읽는 이름. peer 이름을 그대로 찍으면 `cc` 가 무엇인지 안 보인다.
_BACKEND_LABEL = {"cc": "claude", "codex": "codex", "cursor": "cursor", "": "기본 모델"}


def run_roundtable(
    agenda: str,
    *,
    seats: list[str] | None = None,
    rounds: int = 2,
    auto_cli: bool = False,
    quest_id: str = "",
    run_id: str = "",
    record: bool = True,
    json_out: bool = False,
) -> int:
    """원탁을 열고 전사를 낸다.

    Args:
        seats: `name[=role][:backend[:model]]` 목록. 비면 기본 세 좌석(연구원·비평가·도전자)이
            이 프로젝트의 기본 모델로 앉고, 이 기계에서 찾은 에이전트 CLI 는 안내만 한다.
        rounds: 총 회차. 1이면 각자 입장만 내고 끝난다.
        auto_cli: 찾은 에이전트 CLI 를 좌석에 배정한다. 기본이 꺼짐인 이유는 동의다 — CLI
            좌석은 이 저장소를 읽고 그 내용이 그 벤더로 나가므로, 설치되어 있다는 사실이
            보낸다는 결정을 대신할 수 없다.
        record: 전사를 장부에 남길지. `run_id`/`quest_id` 를 주면 그쪽에 붙는다.

    Returns:
        0 이면 좌석이 하나라도 말했고, 2 면 인자가 틀렸거나 전원이 답하지 못했다.
    """
    ui.set_quiet(json_out)
    root = _project_root(os.getcwd())
    agenda = (agenda or "").strip()
    if not agenda:
        ui.fail("안건이 필요해요 — 무엇을 토론할지 한 문단으로 적어 주세요")
        return 2
    try:
        table = parse_seats(list(seats)) if seats else auto_seats(available=None if auto_cli else [])
    except ValueError as exc:
        ui.fail(str(exc))
        return 2

    try:
        run_id = _run_for(root, run_id, quest_id, agenda) if record else ""
    except orc.OrchestrationError as exc:
        ui.fail(str(exc))
        return 2

    ui.step(f"원탁 {len(table)}석 · {rounds}회차 — {', '.join(_seated(seat) for seat in table)}")
    for line in _seating_notes(table, offer=not seats and not auto_cli):
        ui.step(ui.dim(f"    {line}"))
    try:
        result = convene(root, agenda, table, rounds=rounds, run_id=run_id)
    except ValueError as exc:
        ui.fail(str(exc))
        return 2

    if json_out:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print(result)
    return 0 if any(turn["ok"] for turn in result["turns"]) else 2


def _seated(seat) -> str:
    """`비평가=codex` — 누가 어느 뒷단에 앉았는지 한 조각. 배정이 자동이라 보여야 한다."""
    backend = _BACKEND_LABEL.get(seat.provider, seat.provider)
    return f"{seat.name}={backend}{':' + seat.model if seat.model else ''}"


def _seating_notes(table, *, offer: bool) -> list[str]:
    """배정에 대해 화면이 말해야 하는 사실 — 없는 다양성을 있는 것처럼 두지 않는다.

    좌석이 전부 같은 뒷단이면 그것은 관점 셋이 아니라 같은 모델을 세 번 부른 것이다. 합의처럼
    읽히면 실제보다 센 근거로 오해되므로 그 사실을 적는다.

    `offer` 가 참이면 이 기계에서 찾은 에이전트 CLI 를 알리고 앉히는 방법을 준다. 찾았다고
    앉히지는 않는다 — CLI 좌석은 저장소를 읽고 그 내용이 벤더로 나가므로, 설치되어 있다는
    사실이 보낸다는 결정을 대신할 수 없다 (26-08-14 원탁의 판정).
    """
    notes: list[str] = []
    if len({seat.provider for seat in table}) == 1 and len(table) > 1:
        notes.append("좌석이 모두 같은 뒷단이에요 — 관점이 아니라 같은 모델을 여러 번 부르는 것이니 합의로 읽지 마세요")
    if offer:
        from ..agent.runtime import peers_present

        found = [_BACKEND_LABEL.get(kind, kind) for kind in peers_present()]
        if found:
            notes.append(f"이 기계에서 {', '.join(found)} 를 찾았어요 — `--auto-cli` 로 좌석에 앉힙니다")
    return notes


def _run_for(root: str, run_id: str, quest_id: str, agenda: str) -> str:
    """전사를 남길 Run — 준 것이 있으면 그것, 퀘스트가 있으면 그 Run, 없으면 새로 연다."""
    if run_id:
        if orc.run_show(root, run_id) is None:
            raise orc.OrchestrationError(f"그런 Run이 없어요: {run_id}")
        return run_id
    if quest_id:
        return orc.run_bind(root, quest_id, f"원탁: {agenda[:120]}")["id"]
    return orc.run_create(root, f"원탁: {agenda[:120]}")["id"]


def _print(result: dict) -> None:
    for round_no in sorted({turn["round"] for turn in result["turns"]}):
        ui.phase(f"Round {round_no}" if round_no > 1 else "Round 1 — 각자의 입장")
        for turn in result["turns"]:
            if turn["round"] != round_no:
                continue
            if not turn["ok"]:
                ui.warn(f"{turn['seat']} — 답하지 못했어요: {turn['error']}")
                continue
            ui.step(ui.bold(turn["seat"]))
            print(turn["text"][:_LINE_CAP])
    stances = {seat: stance for seat, stance in result["stances"].items() if stance}
    if stances:
        ui.phase("입장")
        for seat, stance in stances.items():
            ui.step(f"{seat}: {stance}")
        silent = [seat for seat, stance in result["stances"].items() if not stance]
        if silent:
            ui.step(ui.dim(f"입장 줄을 안 적은 좌석: {', '.join(silent)}"))
    for line in _cost_notes(result):
        ui.step(ui.dim(line))
    if result["run_id"]:
        ui.ok(f"전사는 장부에 있어요 — `asgard siege inbox {result['run_id']}`")


def _cost_notes(result: dict) -> list[str]:
    """이 판이 얼마를 썼고 무엇을 바꿨는지 — 값과 값어치를 같은 화면에 둔다.

    좌석을 늘려 산 것이 길이뿐일 때가 있다. 그 판단은 부른 쪽이 해야 하는데 화면이 값을 안
    적으면 할 수가 없다 — 산출물은 6배 길어지고 값은 안 보인다. 얼마나 자주 그런지는
    `benchmarks/roundtable/REPORT.md` 가 재는 중이고, 첫 회차는 좌석이 답을 미리 알아 무효였다.

    아무도 입장을 안 바꾼 판을 따로 적는 이유도 같다. 전원 MAINTAIN 은 합의처럼 보이지만 실은
    교차 회차가 아무것도 안 움직인 것이고, 그 판에서 값을 한 것은 1회차뿐이다.
    """
    turns = result.get("turns") or []
    spoken = [turn for turn in turns if turn.get("ok")]
    line = f"모델 호출 {len(turns)}회 · 발언 {len(spoken)}건 · 좌석 {len(result.get('seats') or [])}석"
    secs = result.get("secs")
    if secs is not None:
        line += f" · {secs:g}초"
    notes = [line]
    stances = [stance for stance in (result.get("stances") or {}).values() if stance]
    if stances and set(stances) == {"MAINTAIN"} and len(stances) > 1:
        notes.append(
            "교차 회차에서 아무도 입장을 안 바꿨어요 — 값을 한 것은 1회차이고, 다음엔 `--rounds 1` 로 충분해요"
        )
    return notes
