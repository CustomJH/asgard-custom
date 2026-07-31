"""토르 절차의 자취 — 어떤 동사가 언제 불렸나. 절차가 지켜지는지 **재기 위한** 최소 기록.

왜 필요한가: 절차 엔진이 열한 개 동사와 그 호(弧)를 정의하는데, 그 호가 실제로 지켜지는지 아무도
몰랐다. 플레이북은 stdout으로 나가고 그걸로 끝이었다. 지켜지는지 모르는 절차는 절차가 아니라
권고문이고, 권고문은 턴이 쌓이면 흐려진다 — 이 저장소가 규칙을 프롬프트에서 기계로 옮긴 것과
같은 이유로, 이행률도 사람의 인상이 아니라 기록에서 나와야 한다.

**이 모듈은 판단하지 않는다.** 적는 것은 넷뿐이다: 언제, 어떤 동사, 그때 변경분이 몇 개였나,
그리고 `gate` 라면 몇 건이 막혔나. 넷 다 기계가 그 자리에서 재는 사실이다. "절차를 잘 따랐다"
같은 것은 여기서 나오지 않는다 — 그 판정은 사실을 본 사람의 몫이고, 기계가 대신 내리면 그때부터
자취가 아니라 성적표가 되어 아무도 정직하게 남기지 않는다.

`gate` 판정을 같은 줄에 싣는 이유는 하나 더 있다. "게이트를 통과하고 나서 무엇이 새어 나갔나"를
물으려면 게이트 판정과 그 뒤의 결과가 같은 축에 있어야 한다. 두 벌로 나누면 조인 키가 없어서,
그 질문은 영원히 못 묻는다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

REL = os.path.join(".asgard", "thor", "trail.jsonl")
# 절차의 호. `commands.thor.VERBS`의 순서가 정본이고 여기는 그 순서를 **읽기만** 한다 —
# 두 벌로 적으면 동사를 하나 더할 때 한쪽만 고쳐지고, 그 순간 이행률이 조용히 틀려진다.
TERMINAL = ("sweep", "evidence")
KEEP = 500  # 자취도 자라기만 하면 자원이다 (craft의 unbounded-accumulator와 같은 자를 자신에게)


@dataclass(frozen=True)
class Step:
    at: str
    verb: str
    changed: int  # 그때 판정 가능한 변경분 수 — 동사가 작업의 어디쯤에서 불렸는지
    blocking: int | None = None  # gate만. None = 게이트가 아니거나 판정을 못 냈다


def _order() -> tuple[str, ...]:
    from .commands.thor import VERBS

    return tuple(VERBS)


def record(root: str, verb: str, changed: int, blocking: int | None = None) -> None:
    """한 줄 덧붙인다. 실패는 삼킨다 — 계측이 작업을 막으면 그것은 계측이 아니라 관문이다."""
    line = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verb": verb,
        "changed": changed,
    }
    if blocking is not None:
        line["blocking"] = blocking
    path = os.path.join(root, REL)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        return  # 자취를 못 남기는 것이 동사를 못 부를 이유는 아니다
    _prune(path)


def _prune(path: str) -> None:
    """마지막 KEEP 줄만 남긴다. temp+rename이라 중간에 죽어도 반쪽 자취가 남지 않는다."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
        if len(lines) <= KEEP:
            return
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.writelines(lines[-KEEP:])
        os.replace(tmp, path)
    except OSError:
        return


def load(root: str) -> list[Step]:
    """읽을 수 있는 줄만. 깨진 줄은 건너뛴다 — 한 줄이 깨졌다고 자취 전체를 버릴 이유가 없다."""
    out: list[Step] = []
    try:
        with open(os.path.join(root, REL), encoding="utf-8") as handle:
            rows = handle.readlines()
    except OSError:
        return out
    for row in rows:
        try:
            raw = json.loads(row)
        except ValueError:
            continue
        if not isinstance(raw, dict) or not raw.get("verb"):
            continue
        blocking = raw.get("blocking")
        out.append(
            Step(
                str(raw.get("at") or ""),
                str(raw["verb"]),
                int(raw.get("changed") or 0),
                int(blocking) if isinstance(blocking, int) else None,
            )
        )
    return out


@dataclass(frozen=True)
class Adherence:
    """자취에서 **계산되는** 것만. 각 칸이 무엇을 뜻하는지는 화면이 같이 실어야 한다."""

    steps: tuple[Step, ...]
    called: tuple[str, ...]  # 부른 동사 (처음 부른 순서)
    skipped: tuple[str, ...]  # 한 번도 안 부른 동사
    reached_terminal: bool  # sweep이나 evidence로 갔는가 — 캐논이 명시한 유일한 순서 계약
    gates: tuple[Step, ...]  # gate 판정들
    blocked_runs: int  # 막는 판정이 있었던 gate 실행 수


# 여기 **없는** 것: "호를 거슬렀는가". 한 번 넣었다가 걷어냈다.
#
# `VERBS`의 순서를 선형 호로 읽고 역행을 세면, `diagnose → shape → implement → sweep`이
# 역행 2회로 찍힌다. 그 순서는 버그 수리에서 완벽히 옳다 — 고칠 자격을 먼저 얻고(diagnose),
# 그 다음에 형상을 정한다(shape). 신규 기능이면 반대가 옳다. 즉 선형 호는 애초에 없고,
# `VERBS`의 순서는 메뉴 순서지 강제 순서가 아니다.
#
# 없는 계약을 지표로 만들면 그것은 사실이 아니라 **판단이 사실인 척하는 것**이고, 이 모듈이
# 하지 않기로 한 바로 그 일이다. 지표를 손보는 대신 지웠다.
@dataclass(frozen=True)
class Escape:
    """게이트 판정 하나와, **그 뒤에 온** 검증 판정 하나."""

    quest: str
    verify_at: str
    verdict: str
    gate_at: str
    gate_blocking: int

    @property
    def escaped(self) -> bool:
        """게이트가 통과시킨 뒤에 검증이 잡았는가 — 이 축의 유일한 질문."""
        return self.gate_blocking == 0 and self.verdict != "PASS"


def escapes(root: str) -> list[Escape]:
    """게이트 판정과 검증 판정을 시각으로 잇는다. **새 기록을 안 만들고** 있는 둘을 조인한다.

    조인 규칙은 하나: 각 `verify` 이벤트에 **그보다 앞선 마지막 게이트 실행**을 붙인다. 앞선
    게이트가 없는 검증은 아예 담지 않는다 — 게이트를 안 돌린 검증은 이 질문의 표본이 아니다.

    **이 수치를 읽는 법.** 여기 잡히는 것은 "게이트가 버그를 놓쳤다"가 아니다. 두 판정기가 재는
    것이 다르다 — 게이트는 형상과 정적으로 증명되는 오류를 재고, Verifier는 요구한 일이
    되었는지를 잰다. 그러므로 이 비율이 뜻하는 것은 정확히 **"게이트 통과가 검증 통과를
    함의하지 않는다"** 이고, 그 이상으로 읽으면 두 층의 역할이 섞인다. 비율이 0 이어도 게이트가
    완전하다는 뜻이 아니고, 높아도 게이트가 틀렸다는 뜻이 아니다.
    """
    gates = sorted((s for s in load(root) if s.verb == "gate" and s.at), key=lambda s: s.at)
    if not gates:
        return []
    out: list[Escape] = []
    for quest, event in _verify_events(root):
        at = str(event.get("at") or event.get("ts") or "")
        if not at:
            continue
        prior = [g for g in gates if g.at <= at]
        if not prior:
            continue  # 게이트를 안 돌린 검증은 이 질문의 표본이 아니다
        last = prior[-1]
        out.append(Escape(quest, at, str(event.get("verdict") or "NA"), last.at, last.blocking or 0))
    return out


def _verify_events(root: str):
    """(퀘스트 id, verify 이벤트). 퀘스트 로그가 정본이고 이 모듈은 읽기만 한다."""
    import os as _os

    qdir = _os.path.join(root, ".asgard", "quest")
    try:
        names = sorted(n for n in _os.listdir(qdir) if n.endswith(".jsonl"))
    except OSError:
        return
    for name in names:
        try:
            with open(_os.path.join(qdir, name), encoding="utf-8") as handle:
                rows = list(handle)
        except OSError:
            continue
        for row in rows:
            try:
                event = json.loads(row)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("event") == "verify":
                yield (name[: -len(".jsonl")], event)


def adherence(steps: list[Step]) -> Adherence:
    order = frozenset(_order())
    called: list[str] = []
    seen: set[str] = set()  # `called`를 매번 훑으면 자취가 길어질수록 제곱이 된다 (자기 게이트가 잡았다)
    for step in steps:
        if step.verb in order and step.verb not in seen:
            seen.add(step.verb)
            called.append(step.verb)
    gates = tuple(s for s in steps if s.verb == "gate")
    return Adherence(
        steps=tuple(steps),
        called=tuple(called),
        skipped=tuple(v for v in _order() if v not in seen),
        reached_terminal=any(s.verb in TERMINAL for s in steps),
        gates=gates,
        blocked_runs=sum(1 for s in gates if s.blocking),
    )
