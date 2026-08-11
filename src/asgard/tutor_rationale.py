"""되짚기의 "왜 이렇게 했는가" — 퀘스트 기록에서 사실로 읽는다.

튜터 계약 ③ 은 이 칸을 빈칸으로 남긴다: "왜 그렇게 했나"의 답은 코드를 쓴 쪽에만 있고, 기계가
채우려 들면 사용자는 이미 채워진 칸으로 읽고 넘긴다. 그 계약이 전제하는 것은 **저자가 사람**
이라는 것이다. 에이전트가 Trinity 루프로 쓴 변경에서는 그 전제가 깨진다 — 저자가 사람이 아니고,
사람은 그 자리에서 답할 수 없는 것을 답하라고 요구받는다. `loop.mandate_for` 가 "왜 하필 이
자리였나"에 대해 먼저 낸 예외와 같은 근거다.

그래서 이 모듈이 채우는 것은 추측이 아니라 **기록**이다. `.asgard/quest/<id>.jsonl` 에는 그 턴이
무엇을 맞추려 했는지(criteria), 무엇을 가정했는지(`가정:` 항목), 무엇으로 확인했는지(verify
이벤트의 commands 와 exit code)가 이미 적혀 있다. 여기서 하는 일은 그 셋을 골라 오는 것뿐이고,
기록이 없으면 아무것도 안 만든다 — 빈칸은 빈칸으로 남는다(계약 ③ 이 그대로 있는 자리).

무엇을 안 읽는가도 계약이다. 모델이 쓴 산문(최종 보고, 커밋 메시지, 세션 기록)은 여기 안 들어
온다. 그것은 기록이 아니라 주장이고, 주장을 사실 칸에 넣으면 이 절은 "기계가 지어낸 이유"가 된다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

_QUEST_REL = os.path.join(".asgard", "quest")
_ASSUME = ("가정:", "Assumption:", "assumption:")
_GOAL_CAP = 4  # 카드는 지도다 — 기준 전체는 보고서와 퀘스트 로그가 갖는다
_EVIDENCE_CAP = 3
_SCAN_CAP = 40  # 최근 퀘스트 몇 개까지 뒤질 것인가 — 오래된 기장은 이번 diff 와 겹칠 수 없다
_ANON = "-"  # 기장이 "세션 이름을 못 받았다" 를 적는 자리표시자 (`asgard_hooklib.session`)


@dataclass(frozen=True)
class Rationale:
    """한 변경이 무엇을 맞추려 했고 무엇으로 닫혔는가. 전부 퀘스트 로그의 원문이다."""

    quest_id: str = ""
    request: str = ""
    goals: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    evidence: tuple[tuple[str, int], ...] = ()  # (명령, exit code)
    verdict: str = ""
    goals_total: int = 0

    def __bool__(self) -> bool:
        return bool(self.goals or self.assumptions or self.evidence or self.request)


def rationale(root: str, paths: object = (), session: str = "") -> Rationale:
    """이 변경을 만든 퀘스트의 기록. 못 찾으면 빈 Rationale — 없는 이유를 지어내지 않는다.

    고르는 순서는 **활성 포인터 → 겹치는가 → 열려 있는가 → 얼마나 겹치는가 → 최신인가**다.
    포인터가 먼저인 이유는 그것이 유일하게 확실한 신호라서다: `.asgard/quest/ACTIVE` 는 지금 도는
    퀘스트를 가리키고, 아직 커밋 안 된 워킹트리를 만든 것이 바로 그 퀘스트다. 겹침만으로 고르면
    오래된 릴리스 기장이 이번 변경의 이유로 들어간다 — 릴리스는 저장소를 넓게 건드려서 어느
    경로든 겹치고, 닫는 것을 잊은 기장이 하나라도 있으면 그쪽이 계속 우선한다 (26-08-07 실측:
    `release-0-10-8`). 겹침을 **몇 곳인가**가 아니라 **한 곳이라도 있는가**로 먼저 보는 것도 같은
    이유다: 개수로 재면 저장소를 넓게 건드린 기장이 이번 변경의 한 파일을 정확히 짚은 기장보다
    앞자리를 차지한다.

    순위만으로는 모자란다는 것이 뒤에 드러났다. 포인터가 없고(지금 도는 퀘스트가 없다) 최근
    퀘스트가 전부 닫혀 있으면, 닫는 것을 잊은 옛 기장이 "열려 있다"는 이유 하나로 앞자리를
    차지한다 — 경로가 한 곳도 안 겹쳐도 그렇다. 26-08-11 에 그렇게 됐다: 워킹트리는 workroots·tutor 를
    건드리고 있었는데 카드는 `ql-inproc-fastpath` 의 기준을 이 변경의 이유로 실었다. 그래서
    순위 뒤에 문턱을 하나 둔다 — **포인터가 가리키거나 경로가 실제로 겹칠 때만** 답한다. 둘 다
    아니면 빈 Rationale 이고, 화면은 이 칸을 빈칸으로 남긴다(계약: 없는 이유는 안 지어낸다).
    """
    wanted = _normalise(paths)
    rows = [(path, events) for path in _quest_files(root) if (events := _read(path))]
    session = _known(rows, session)
    live = _live(rows, _active(root), session)
    # 점수는 여섯 축이다 — 포인터·세션 주인·경로 겹침·열려 있음·겹친 개수·수정 시각. 앞의 셋을
    # 아래에서 문턱으로 다시 읽으므로 길이가 어긋나면 그 자리가 조용히 다른 축을 읽는다.
    best: tuple[tuple[int, int, int, int, int, float], list[dict]] | None = None
    for path, events in rows:
        qid = str(events[0].get("quest_id") or "")
        overlap = len(wanted & _touched(events)) if wanted else 0
        owners = _owners(events)
        score = (
            1 if live and qid == live else 0,
            # 세션을 아는데 그 기장이 남의 것이면 뒤로 민다. 포인터만 좁히면 모자란다 — 옆 세션의
            # 기장은 대개 아직 안 닫혀 있어서 "열려 있는가" 축에서 이쪽 닫힌 기장을 앞선다.
            -1 if session and owners and session not in owners else 0,
            1 if overlap else 0,
            0 if any(e.get("event") == "quest_closed" for e in events) else 1,
            overlap,
            _mtime(path),
        )
        if best is None or score > best[0]:
            best = (score, events)
    if best is None:
        return Rationale()
    pointed, mine, touches = best[0][0], best[0][1], best[0][2]
    if not pointed and not touches:
        return Rationale()
    if mine < 0 and not pointed:
        return Rationale()  # 남은 후보가 전부 남의 세션 것이다 — 그건 이 변경의 이유가 아니다
    return _shape(best[1])


def _known(rows: list[tuple[str, list[dict]]], session: str) -> str:
    """이 이름이 정말 세션 이름인가. 기장 어디에도 없으면 빈 문자열 — 모르는 이름으로는 안 거른다.

    훅이 넘기는 이름과 기장이 적는 이름이 **다른 통에서 나온다**. 훅은 호스트 payload 의
    `session_id` 를 쓰고 없으면 `default`, Cursor 에서는 아예 리터럴 `cursor` 다
    (`hooks/tutor_note.py`). 기장은 `asgard_hooklib.session.host_session_id()` 가 환경 변수에서
    읽은 값을 적고, 없으면 `-` 다. 두 통이 어긋나면 세션 축이 **모든** 후보를 남의 것으로 밀어
    내고 이 칸이 통째로 빈다 — 26-08-11 판정이 Cursor 에서 그 형상을 잡았다.

    `_owners` 와 같은 규율이다: 모르는 것은 남의 것이 아니다. 이름을 못 알아보면 세션 축을 접고
    포인터와 겹침만으로 고른다.
    """
    if not session:
        return ""
    return session if any(session in _owners(events) for _, events in rows) else ""


def _live(rows: list[tuple[str, list[dict]]], qid: str, session: str) -> str:
    """포인터를 그대로 믿을 수 있는가. 못 믿으면 빈 문자열 — 그러면 겹침이 고른다.

    포인터는 저장소마다 하나인데 세션은 여럿일 수 있다. 그래서 옆 세션이 연 퀘스트가 이쪽 턴의
    이유 자리에 들어간다 (26-08-11 실측: 두 세션이 같은 트리에서 돌던 중 다른 퀘스트의 기준·가정이
    이 변경의 이유 자리에 그대로 나왔다).

    가르는 축은 **경로가 아니라 세션**이다. 경로로 가르려던 첫 판은 안 섰다: 하네스는
    `changed_files` 를 워킹트리 전체에서 뜨므로 같은 트리에서 도는 두 퀘스트는 서로의 파일을 다
    적는다 (그 실측에서 옆 기장이 적은 파일이 39개였고 이쪽 파일도 그 안에 있었다). 겹침이 0이
    되는 일이 없으니 그 문턱은 아무것도 안 걸렀다. 반면 `session_id` 는 이벤트마다 적히고 두
    세션이 절대 같은 값을 안 쓴다.

    세션을 모르면(사람이 직접 친 `asgard tutor`) 포인터를 그대로 믿는다 — 그 자리에서는 옆
    세션과 구별할 근거가 없고, 근거 없이 버리면 정상 단일 세션의 카드까지 빈칸이 된다.
    """
    if not qid or not session:
        return qid
    for _, events in rows:
        if str(events[0].get("quest_id") or "") != qid:
            continue
        owners = _owners(events)
        return qid if not owners or session in owners else ""
    return qid


def _owners(events: list[dict]) -> set[str]:
    """이 기장에 이벤트를 적은 세션들. 비어 있으면 모르는 것이고, 모르는 것은 남의 것이 아니다.

    `-` 는 세션 이름이 아니라 `asgard_hooklib.session.host_session_id()` 가 호스트에서 이름을 못
    받았을 때 적는 자리표시자다. 그것을 신원으로 세면 서로 모르는 두 기장이 같은 세션의 것으로
    묶이고, 반대로 이름이 `-` 로 들어온 턴은 자기 기장까지 남의 것으로 밀어낸다.
    """
    return {name for e in events if (name := str(e.get("session_id") or "")) and name != _ANON}


def _active(root: str) -> str:
    """지금 열려 있는 퀘스트 id. 포인터가 없거나 못 읽으면 빈 문자열 — 그러면 아래 순위가 고른다."""
    try:
        with open(os.path.join(root, _QUEST_REL, "ACTIVE"), encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _quest_files(root: str) -> list[str]:
    """최근 순 퀘스트 파일. 상한을 두는 이유는 값이다 — 되짚기는 턴마다 도는 층이다."""
    base = os.path.join(root, _QUEST_REL)
    try:
        rows = [os.path.join(base, name) for name in os.listdir(base) if name.endswith(".jsonl")]
    except OSError:
        return []
    rows.sort(key=lambda p: _mtime(p), reverse=True)
    return rows[:_SCAN_CAP]


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _read(path: str) -> list[dict]:
    """JSONL 한 묶음. 절단된 줄은 건너뛴다 — 크래시 흔적 하나가 기장 전체를 못 읽게 하지 않는다."""
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as handle:
            rows = list(handle)
    except OSError:
        return []
    for line in rows:
        body = line.strip()
        if not body:
            continue
        try:
            row = json.loads(body)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _touched(events: list[dict]) -> set[str]:
    return {
        str(rel).replace(os.sep, "/")
        for event in events
        for rel in (event.get("changed_files") or [])
        if str(rel).strip()
    }


def _normalise(paths: object) -> set[str]:
    if not isinstance(paths, (list, tuple, set, frozenset)):
        return set()
    return {rel for raw in paths if (rel := str(raw).strip().replace(os.sep, "/"))}


def _shape(events: list[dict]) -> Rationale:
    opened = next((e for e in events if e.get("event") == "plan"), {})
    criteria = [str(c).strip() for c in (opened.get("criteria") or []) if str(c).strip()]
    goals = [_goal(c) for c in criteria if not c.startswith(_ASSUME)]
    assumptions = [_after(c) for c in criteria if c.startswith(_ASSUME)]
    verdicts = [e for e in events if e.get("event") == "verify" and e.get("verdict") in ("PASS", "FAIL")]
    last = verdicts[-1] if verdicts else {}
    return Rationale(
        quest_id=str(opened.get("quest_id") or (events[0].get("quest_id") if events else "") or ""),
        request=" ".join(str(opened.get("request") or "").split()),
        goals=tuple(goals[:_GOAL_CAP]),
        assumptions=tuple(assumptions),
        evidence=_evidence(last),
        verdict=str(last.get("verdict") or ""),
        goals_total=len(goals),
    )


def _goal(criterion: str) -> str:
    """기준 한 줄에서 사람이 읽을 부분. `| verify:`·`| artifacts:` 꼬리는 계약이지 설명이 아니다."""
    return criterion.split("|", 1)[0].strip()


def _after(criterion: str) -> str:
    for mark in _ASSUME:
        if criterion.startswith(mark):
            return criterion[len(mark) :].strip()
    return criterion


def _evidence(event: dict) -> tuple[tuple[str, int], ...]:
    """판정이 **직접 돌린** 명령과 그 종료 코드. 하네스가 다시 돌린 기준 검사를 먼저 넣는다.

    `criteria_checks` 를 앞에 두는 이유는 증명력이다 — 그쪽은 퀘스트를 열 때 선언한 계약을
    하네스가 스스로 재실행한 결과이고, `commands` 는 판정자가 자기가 골라 돌린 것이다.
    """
    rows: list[tuple[str, int]] = []
    for key in ("criteria_checks", "commands"):
        for item in event.get(key) or []:
            if not isinstance(item, dict):
                continue
            cmd = " ".join(str(item.get("cmd") or "").split())
            code = item.get("exit_code")
            if cmd and isinstance(code, int) and not any(cmd == seen for seen, _ in rows):
                rows.append((cmd, code))
    return tuple(rows[:_EVIDENCE_CAP])


def as_dict(row: Rationale) -> dict:
    """훅이 읽을 칸. 훅은 stdlib 전용이라 이 모듈을 못 부르고 `asgard tutor --json` 만 본다."""
    return {
        "quest_id": row.quest_id,
        "request": row.request,
        "goals": list(row.goals),
        "assumptions": list(row.assumptions),
        "evidence": [[cmd, code] for cmd, code in row.evidence],
        "verdict": row.verdict,
        "goals_total": row.goals_total,
    }


def lines(row: object, limit: int = _GOAL_CAP) -> list[str]:
    """카드에 실릴 줄. **엔진과 훅이 같은 화면을 내는 유일한 자리**라 규칙은 여기 하나뿐이다.

    `row` 는 `Rationale` 이거나 `as_dict` 가 낸 사전이다 — 훅은 사전만 갖고 있고, 두 렌더러가
    갈리면 같은 판정이 클라이언트마다 다르게 보인다(`tutor_teach.card` 와 같은 계약).
    """
    data = row if isinstance(row, dict) else as_dict(row) if isinstance(row, Rationale) else {}
    goals = [str(g) for g in _listed(data.get("goals")) if str(g).strip()][: max(0, limit)]
    assumptions = [str(a) for a in _listed(data.get("assumptions")) if str(a).strip()]
    evidence = [
        (str(e[0]), e[1]) for e in _listed(data.get("evidence")) if isinstance(e, (list, tuple)) and len(e) >= 2
    ]
    request = " ".join(str(data.get("request") or "").split())
    if not (goals or assumptions or evidence or request):
        return []
    qid = str(data.get("quest_id") or "")
    out = ["⠶ 왜 이렇게 했는가" + (f" — 퀘스트 `{qid}`" if qid else "")]
    if request:
        out.append(f"  받은 요청 — {_clip(request, 160)}")
    for index, goal in enumerate(goals):
        out.append(("  맞추려던 것 — " if index == 0 else "                ") + _clip(goal, 160))
    counted = data.get("goals_total")
    total = counted if isinstance(counted, int) else len(goals)
    if total > len(goals):
        out.append(f"                …외 {total - len(goals)}건은 퀘스트 로그에 있어요")
    for index, assume in enumerate(assumptions):
        out.append(("  가정 — " if index == 0 else "         ") + _clip(assume, 160))
    for index, (cmd, code) in enumerate(evidence):
        out.append(("  확인 — " if index == 0 else "         ") + f"{_clip(cmd, 120)} (exit {code})")
    return out


def _listed(value: object) -> list:
    """사전에서 꺼낸 값 중 목록인 것만. 훅이 넘기는 사전은 JSON 에서 와서 타입 보장이 없다."""
    return value if isinstance(value, list) else []


def _clip(text: str, cap: int) -> str:
    body = " ".join(str(text).split())
    return body if len(body) <= cap else body[: cap - 1] + "…"
