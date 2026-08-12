"""턴마다 붙는 회수 블록 — 종류를 섞어 k 개만 싣고, 실린 것만 노출로 센다."""

from __future__ import annotations

from ..policy import inject_enabled, memory_dir
from .rows import _hit_row
from .search import _track, query

RECALL_BUDGET = 900  # chars — 회수 블록 상한 (턴마다 붙으므로 카탈로그보다 훨씬 작게)


def _diversify(hits: list[dict], k: int) -> list[dict]:
    """한 종류가 회수 블록을 독식하지 못하게 자른다 — 순위는 건드리지 않는다.

    같은 공간에 섞여 있는 서로 다른 성격의 기억은 서로를 대체할 수 있는 근거처럼 회수된다
    (MemGuard, arXiv 2605.28009 — "heterogeneous memory contamination"). asgard는 kind로
    성격을 이미 구분해 두었는데 회수는 그걸 안 봤다: reference 세 장이 상위를 차지하면
    바로 아래의 feedback("이렇게 하지 말라던 그것")이 블록에 못 들어온다. 값이 다른 게 아니라
    종류가 다른 것이라 순위로만 자르면 안 되는 자리다.

    한 종류 상한은 과반(k=3 이면 2). 다른 종류에 후보가 없으면 상한을 안 걸고 그대로 채운다 —
    다양성을 위해 빈 줄을 남기지는 않는다."""
    cap = max(1, (k + 1) // 2)
    if len({h.get("kind") for h in hits}) < 2:
        return hits[:k]
    picked: list[dict] = []
    seen: dict[str, int] = {}
    for hit in hits:  # 1차 — 상한을 지키며 순위대로
        kind = str(hit.get("kind") or "")
        if seen.get(kind, 0) >= cap:
            continue
        picked.append(hit)
        seen[kind] = seen.get(kind, 0) + 1
        if len(picked) == k:
            return picked
    for hit in hits:  # 2차 — 자리가 남으면 상한을 풀고 순위대로 채운다
        if hit not in picked:
            picked.append(hit)
            if len(picked) == k:
                break
    return picked


RECALL_PREFIX = '\n\n<memory-recall scope="personal">\n요청 관련 개인 메모리 (힌트 — 완료 증거 아님):\n'
RECALL_SUFFIX = "\n</memory-recall>"


def recall_rows(text: str, k: int = 3, d: str | None = None) -> list[str]:
    """회수 본문 목록 — **렌더도 예산도 여기서 안 한다**.

    레인을 후보 생산자로 갈라 둔 이유는 조립기(`memory.assemble`)가 여섯 레인을 하나의
    예산 위에서 겨루게 하고 레인 간 중복을 제거해야 하기 때문이다. 각 레인이 자기 예산을
    자기가 자르던 시절에는 같은 사실이 다섯 레인으로 다섯 번 들어갈 수 있었다."""
    if not inject_enabled():
        return []
    # 넉넉히 뽑아 종류를 섞은 뒤 k 개로 줄인다 — 왜인지는 _diversify 참조.
    # track=False 로 부른다: 이 레인은 사람이 친 검색이 아니라 매 턴 도는 자동 주입이다.
    hits = query(text, k=max(k, k * 2), d=d, track=False)
    if not hits:
        return []
    picked = _diversify(hits, k)
    # 노출은 **실제로 실린 것**만 센다 — 자르기 전에 세면 프롬프트에 못 들어간 후보까지
    # "보여 준 것"이 되고, 그 수를 근거로 삼는 다음 판정이 같이 틀린다.
    _track(d or memory_dir(), picked, exposure=True)
    return [_hit_row(h) for h in picked]


def recall_note(text: str, k: int = 3, d: str | None = None) -> str:
    """요청 기반 zero-LLM 회수 블록 — DIRECT/Thinker 턴 시작 시 결정론 주입 (감사 권고:
    "모델이 자발적으로 CLI를 부르는" 순응 의존을 없앤다). query가 오염 페이지를 이미
    제외하므로 여기선 경계 무력화 + 예산만. 무적중·킬스위치 off = 빈 문자열 (무변화).

    이 레인 **혼자** 쓰는 표면(`asgard memory recall`·개인 메모리만 보는 호출)용이다. 여섯
    레인을 같이 넣는 자리는 `memory_context.recall_note`가 조립기로 간다."""
    try:
        rows = recall_rows(text, k=k, d=d)
        if not rows:
            return ""
        from ..assemble import Candidate, Lane, assemble

        lane = Lane("personal", RECALL_PREFIX, RECALL_SUFFIX, RECALL_BUDGET)
        return assemble(
            [Candidate("personal", body, rank=index) for index, body in enumerate(rows)],
            (lane,),
            budget=RECALL_BUDGET,
        )
    except Exception:
        return ""  # fail-open
