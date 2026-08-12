"""조절·재방문 (사실을 사람에 맞춰 줄인다).

판정이 만든 사실은 누구에게나 같고, 그 사실을 **몇 건이나 어떤 각도로** 놓을지만 여기서
사람에 맞춰 줄인다. 나누는 이유는 하나다: 사실이 사람에 따라 달라지기 시작하면 `--json`이
두 사람에게 다른 답을 내게 된다.
"""

from __future__ import annotations

from dataclasses import replace

from .. import tutor_growth
from ..health import _read
from ..tutor_model import Checkpoint

# 다시 물을 때의 **각도**. 같은 문장을 네 번째로 놓는 것은 재방문이 아니라 반복이고, 반복은
# 답을 못 받은 이유를 그대로 한 번 더 재현한다. 인출이 실패한 자리에서 바꿀 것은 목소리 크기가
# 아니라 각도다 — 결과를 묻던 것을 신호로, 신호를 묻던 것을 복구로 옮긴다. 0번은 최초 문장이라
# 여기 없다(Checkpoint.ask가 갖는다). 각도가 떨어지면 마지막 각도를 유지한다.
ANGLES: dict[str, tuple[str, ...]] = {
    "contract-break": (
        "이 계약을 쓰던 코드를 지금 처음 보는 사람은 무엇부터 실행해 봐야 할까요?",
        "되돌려야 한다면 어디를 되돌리나요? 한 줄로 말할 수 있나요?",
    ),
    "behavior-removed": (
        "이 동작이 없어서 깨지는 상황을 하나만 들어 볼까요? 하나도 못 대겠다면 그건 왜일까요?",
        "이걸 다시 살려야 할 날이 온다면 무엇을 근거로 판단하나요?",
    ),
    "test-removed": (
        "이 테스트가 잡던 실패를 지금 일부러 만들면 무엇이 빨개지나요?",
        "지운 판정을 대신하는 게 없다면, 없어도 되는 이유를 한 줄로 적어 볼까요?",
    ),
    "silent-failure": (
        "이 예외가 지금 하루에 100번씩 일어나고 있다면 그걸 어떻게 알아차리나요?",
        "여기서 삼키는 대신 위로 올렸다면 무엇이 깨지나요? 그게 삼키는 이유인가요?",
    ),
    "new-dependency": (
        "이게 내일 폐기되거나 라이선스가 바뀐다면 무엇을 해야 하나요?",
        "이 의존이 하는 일 중 실제로 쓰는 건 얼마나 되나요? 나머지도 같이 짊어질 값인가요?",
    ),
    "untested-surface": (
        "다음 사람이 이걸 반대로 고쳐 놓으면 무엇이 그 사실을 알려 주나요?",
        "판정을 안 붙이기로 했다면 그 결정은 지금 어디에 적혀 있나요?",
    ),
    "todo-left": (
        "이 표식을 지우려면 그 전에 무엇이 끝나야 하나요?",
        "여섯 달 뒤 이 줄을 처음 보는 사람이 무엇을 해야 하는지 알 수 있을까요?",
    ),
}


def angled(point: Checkpoint, asks: int) -> Checkpoint:
    """같은 물음을 다시 놓을 때 각도를 바꾼 문장으로 갈아 끼운다. 1회차는 원문 그대로."""
    turns = ANGLES.get(point.kind, ())
    index = tutor_growth.angle(point.kind, asks) - 1
    if index < 0 or not turns:
        return point
    return replace(point, ask=turns[min(index, len(turns) - 1)])


def shaped(root: str, points: tuple[Checkpoint, ...]) -> list[tuple[Checkpoint, str]]:
    """(물음, 크기) 목록 — 크기는 `full` · `ask` · `fold` · `quiet`.

    이 저장소에서 이미 세 번 답한 종류를 네 번째에도 같은 분량으로 설명하면, 그건 배려가 아니라
    사용자 시간을 쓰는 일이다(안내는 줄어쓰는 것이 목표다). 반대로 접는다고 지우지는 않는다 —
    접힌 줄은 화면에 남아서 "이 종류도 이번에 있었다"는 사실을 계속 말한다.

    문장의 각도도 여기서 정해진다: 같은 물음을 두 번째로 놓는 자리면 두 번째 각도로 갈아 끼운다.
    `record` 뒤에 부르는 것이 계약이다 — 회차를 세기 전에 각도를 고르면 한 박자씩 밀린다.
    """
    data = tutor_growth.load(root)
    out: list[tuple[Checkpoint, str]] = []
    for point in points:
        entry = data["open"].get(point.cid)
        asks = int(entry.get("asks") or 1) if isinstance(entry, dict) else 1
        out.append((angled(point, asks), tutor_growth.form(data, point.kind)))
    return out


def revisits(root: str, now: float | None = None, cap: int = 2, skip: object = ()) -> list[tutor_growth.Revisit]:
    """때가 됐고 **코드가 아직 거기 있는** 물음 — 각도를 바꿔서, 다음 회차 예약까지 끝내서 준다.

    없는 자리를 열어 보라고 두 번 말하면 사용자는 이 카드를 통째로 안 믿는다. 그래서 재방문은
    기록만으로 결정하지 않고 매번 나무를 한 번 본다 — 되짚기가 유일하게 파일을 다시 읽는 자리다.
    죽은 좌표는 여기서 만료로 닫힌다(조용히 지우지 않는다).

    `skip`은 이번 턴이 방금 물은 자리다. 같은 물음이 위(이번 변경)와 아래(재방문)에 두 번 들어가면
    읽는 쪽은 그걸 두 건으로 세고, 두 번 실린 화면은 한 번도 안 읽힌다.
    """
    seen = {str(s) for s in skip} if isinstance(skip, (list, tuple, set, frozenset)) else set()
    alive, dead = [], []
    for row in tutor_growth.due(root, now, cap=max(cap * 4, 8)):
        if row.cid in seen:
            continue
        (alive if _alive(root, row) else dead).append(row)
    if dead:
        tutor_growth.expire(root, [row.cid for row in dead], "gone", now)
    out = []
    for row in alive[:cap]:
        turns = ANGLES.get(row.kind, ())
        index = row.asks - 1  # asks는 아래 record에서 곧 +1 된다 — 그 회차의 각도를 미리 고른다
        ask = turns[min(index, len(turns) - 1)] if turns and index >= 0 else row.ask
        out.append(replace(row, ask=ask, asks=row.asks + 1))
    if out:
        record(
            root,
            [{"kind": r.kind, "path": r.path, "unit": r.unit, "key": r.key, "ask": r.ask} for r in out],
            now,
        )
    return out


def _alive(root: str, row: tutor_growth.Revisit) -> bool:
    """좌표가 아직 살아 있는가. **모르면 살아 있다고 본다** — 물음을 조용히 지우는 쪽이 더 나쁘다.

    단위 이름이 본문 어디에도 없으면 확실히 사라진 것이다. 이름이 있으면(다른 곳에서 언급만 하는
    경우 포함) 살아 있다고 친다. 단위가 없는 물음(표식 등)은 파일 존재만 본다 — 표식 한 줄의
    생사까지 여기서 다시 판정하면 판정기가 두 벌이 된다.
    """
    text = _read(root, row.path)
    if text is None:
        return False
    return True if not row.unit else row.unit.rsplit(".", 1)[-1] in text


def hand_back(
    root: str,
    points: tuple[Checkpoint, ...],
    limit: int = 3,
    count: bool = True,
    now: float | None = None,
) -> tuple[list[tuple[Checkpoint, str]], list[tutor_growth.Revisit]]:
    """화면에 들어갈 모양 + 되돌아온 물음. 두 도달 경로(훅·네이티브)가 같은 함수를 쓴다.

    **화면에 실린 것만 센다.** 판정이 119건을 찾아도 카드에 셋이 올라갔으면 물은 것은 셋이다 —
    나머지를 세면 사용자가 본 적 없는 물음이 "건너뛴 것"으로 기록되고, 그러면 조절이 사람이 아닌
    판정기의 크기를 따라간다(실측: 400파일 넓은 진단 한 번이 기록을 119건으로 부풀렸다).

    세는 것이 먼저이고 문장을 고르는 것이 나중이다 — 회차를 센 뒤라야 그 회차의 각도가 나온다.
    """
    data = tutor_growth.load(root)
    shown = [p for p in points if tutor_growth.form(data, p.kind) not in ("fold", "quiet")][:limit]
    if count and shown:
        record(root, shown, now)
    rows = shaped(root, points)
    # 이번 변경과 재방문을 합쳐도 `limit`을 넘지 않는다. 새 질문 셋 뒤에 옛 질문 둘을 붙이면
    # 화면 상한은 사실상 다섯이 되고, 무엇에 답해야 하는지가 다시 사라진다.
    back_cap = min(2, max(0, limit - len(shown)))
    back = revisits(root, now, cap=back_cap, skip=[p.cid for p in points]) if count and back_cap else []
    return (rows, back)


def record(root: str, points: object, now: float | None = None) -> dict[str, str]:
    """놓은 물음을 성장 기록에 남긴다 — 중복 호출에 안전(같은 턴에 훅과 네이티브가 겹쳐 돈다).

    `now`를 그대로 넘기는 것이 계약이다. 여기서 시계를 갈아 끼우면 재방문 사다리가 제자리를
    맴돈다 — 예약은 미래 시각으로 재고 판정은 현재 시각으로 하면 영원히 "아직 때가 아니다"가 된다.
    """
    try:
        return tutor_growth.note_asked(root, points, now)
    except Exception:
        return {}  # 기록 실패가 화면을 막지 않는다 — 되짚기는 규율이지 관문이 아니다
