"""턴 끝에 나가는 한 줄 — 채굴·자동 설치를 돌리고 무엇이 늘었는지 또는 무엇이 기다리는지 말한다."""

from __future__ import annotations

import hashlib
import os

from .autonomy import autoapprove, autonomy_mode, autoscan
from .corrections import _corrections
from .inbox import pending_list
from .quests import _quest_signal, _read_quest
from .store import _latched, _load_seen, _mineable


def nudge_line(root: str) -> str | None:
    """채굴하고, **승인 대기 초안**을 한 줄로 — 대기 집합이 변했을 때만 (latch).

    네 모드가 전부 이 한 지점을 지난다: 외부 클라이언트는 Stop 훅(memory-activate)이
    `asgard evolve nudge`로, 네이티브 루프는 quest close에서 직접 부른다.

    종전에는 "미채굴 신호가 있다"고 알리고 채굴은 사람이 치게 했다 — 그래서 놓친 넛지 하나가
    교훈 하나의 영구 소실이었다. 이제 채굴까지는 하니스가 하고(가역·비활성), 사람에게는
    **승인할 것이 있다**고 말한다. 채굴을 끈 사람에게는 종전 문장 그대로다.

    한 줄이 말해야 하는 것 셋: 기다리는 것이 무엇인가(스킬 초안), 어디서 나왔는가(어느 퀘스트의
    어떤 실패), 승인하면 무엇이 되는가(다음 워커 배차부터 자동으로 쓰인다). 셋 중 하나라도 빠지면
    읽는 사람은 "학습 후보"가 무엇을 가리키는 말인지부터 되물어야 한다 (26-08-11 오딘 지적).

    자율 등급이 켜져 있으면(`autonomy_mode`) 자격분은 여기서 바로 설치되고, 그 턴의 한 줄은
    대기 안내가 아니라 **무엇이 늘었는지**를 말한다."""
    mined = autoscan(root)
    installed = autoapprove(root, mined)
    items = pending_list(root)
    if installed:
        return _installed_line(installed, len(items))
    if items:
        ids = sorted(str(item.get("id") or "") for item in items)
        digest = hashlib.sha1("\0".join(ids).encode()).hexdigest()
        if _latched(root, digest, len(items)):
            return None
        return f"진화 인박스 — 스킬 초안 {len(items)}건이 승인을 기다린다{_fresh(mined)}. {_INBOX_TAIL}"
    qdir = os.path.join(root, ".asgard", "quest")
    seen = _load_seen(root)
    signals = sorted(
        sig["signal"]
        for fname in (os.listdir(qdir) if os.path.isdir(qdir) else [])
        if fname.endswith(".jsonl")
        for sig in [_quest_signal(_read_quest(os.path.join(qdir, fname)))]
        if sig and _mineable(seen, sig["signal"])
    )
    signals += sorted(
        str(row["signal"]) for row in _corrections(root) if row.get("signal") and _mineable(seen, str(row["signal"]))
    )
    if not signals:
        return None
    digest = hashlib.sha1("\0".join(signals).encode()).hexdigest()
    if _latched(root, digest, len(signals)):
        return None
    return (
        f"진화 인박스 — 실패를 딛고 통과한 퀘스트 {len(signals)}건이 아직 초안이 안 됐다. "
        "`asgard evolve scan` 이 초안을 뜨고, 그 뒤는 승인해야 실린다."
    )


# 승인이 무엇을 하는지 한 번은 적는다 — 이 줄을 읽는 사람 대부분은 인박스를 처음 본다.
_INBOX_TAIL = "승인하면 그 뒤 워커 배차부터 자동으로 쓰이고, 안 하면 아무 데도 안 쓰인다 — `asgard evolve list`"


def _installed_line(installed: list[dict], waiting: int) -> str:
    """스스로 설치한 스킬을 알리는 한 줄. latch 를 안 건다 — 설치는 능력이 늘어난 사건이라
    사람이 못 보고 지나가면 안 되고, 같은 스킬이 두 번 설치되는 경로도 없다."""
    names = ", ".join(str(m.get("name") or "?") for m in installed[:2])
    more = f" 외 {len(installed) - 2}건" if len(installed) > 2 else ""
    tail = f" 초안 {waiting}건은 그대로 승인을 기다린다 — `asgard evolve list`." if waiting else ""
    return (
        f"진화 — 학습 스킬 {len(installed)}건을 스스로 설치했다 ({names}{more}). 다음 워커 배차부터 쓰이고, "
        f"물리려면 `asgard evolve archive <이름>` (등급 {autonomy_mode()} — 설정 `evolution.autonomy`).{tail}"
    )


def _fresh(mined: list[dict]) -> str:
    """방금 뜬 초안이 어느 퀘스트의 무엇에서 나왔는지. 없으면 빈 문자열."""
    if not mined:
        return ""
    row = mined[0]
    where = str(row.get("quest_id") or "") or str(row.get("origin") or "")
    fails = row.get("fail_count")
    detail = f"{where} — 실패 {fails}회 뒤 통과" if where and isinstance(fails, int) else where
    head = f" (방금 {len(mined)}건: `{row.get('name')}`"
    return head + (f" ← {detail})" if detail else ")")
