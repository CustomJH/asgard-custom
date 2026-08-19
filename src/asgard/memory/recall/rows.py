"""주입면에 나가는 한 줄 — 경계 무력화와 제목·발췌 중복 제거. 카탈로그 행과 회수 행이 같은 규율을 쓴다."""

from __future__ import annotations

from ..policy import _INVISIBLE

# 발췌 상한 — 렌더(`_hit_row`)가 자르는 길이와 **같은 값**이어야 한다. 두 값이 갈리면 여기서
# 통째로 넣어 보낸 본문을 저쪽이 다시 자르거나, 여기서 자른 것을 저쪽이 온전한 줄로 취급한다.
SNIPPET_MAX = 160
# 이어 붙일 겹침 하한 — 이보다 짧으면 두 조각이 우연히 같은 어절로 끝나고 시작한 것일 수 있다.
OVERLAP_MIN = 12


def _neutralize(s: str) -> str:
    """주입면 경계 무력화 (P0) — 각괄호를 유사문자로 치환해 태그/펜스 탈출 차단.

    비가시 문자는 여기서도 벗긴다. poisoned()가 이미 막지만 그건 '페이지째 제외'라
    저장 이전에 심어진 것·판정을 비껴간 것이 남는다. 주입면에서 한 번 더 벗기는 값이
    제외보다 크다 — 마지막 관문은 조용히 무해하게 만드는 쪽이 낫다."""
    stripped = "".join(c for c in s if c not in _INVISIBLE and not 0xE0000 <= ord(c) <= 0xE007F)
    return stripped.replace("<", "‹").replace(">", "›")


def _fuse(head: str, tail: str) -> str | None:
    """같은 본문에서 온 두 조각을 하나로 이어 붙인 값 — 겹치는 데가 없으면 None.

    제목은 본문 앞부분에서 오고 발췌는 적중 위치 둘레에서 온다. 잘라 온 자리가 달라 한쪽이
    다른 쪽의 접두사가 아니라 **앞 조각의 꼬리와 뒤 조각의 머리가 겹치는** 모양이 되는데,
    포함 검사만으로는 이 겹침이 안 보인다 (실측 26-08-19: 회수 25행 중 19행이 같은 문장을
    두 번 실었다). 겹친 만큼만 빼고 이어 붙이면 한 문장이 온전해지고 어느 쪽도 안 버린다."""
    a, b = _bare(head), _bare(tail)
    if not a or not b:
        return None
    if b in a:
        return head
    if a in b:
        return tail
    # 뒤 조각이 잘려 있었다면 이은 결과도 잘린 것이다 — 표시를 여기서 떨구면 `_snippet` 이
    # 그 표시를 붙인 이유가 사라지고, 읽는 쪽이 마지막 낱말을 온전한 값으로 읽는다.
    mark = "…" if tail.rstrip().endswith("…") else ""
    for n in range(min(len(a), len(b)), OVERLAP_MIN - 1, -1):
        if a[-n:] == b[:n]:
            return a + b[n:] + mark
    return None


def _bare(s: str) -> str:
    """잘림 표시를 뺀 비교용 값 — 표시가 붙은 자리는 겹침 판정의 대상이 아니다."""
    return s.strip().strip("…").strip()


def _row(title: str, desc: str) -> str:
    """카탈로그 행 — 제목과 설명이 같은 말이면 한 번만 적는다.

    한 문장짜리 페이지에서는 title 이 곧 본문 첫 줄이고 _desc 도 본문 첫 줄이라, 그대로 두면
    주입면의 절반이 같은 문장의 반복이 된다. 자르는 길이가 달라(제목 80·설명 90) 겹치는
    지점도 다르므로 `_fuse` 가 겹치는 만큼만 빼고 잇는다."""
    if fused := _fuse(title, desc):
        return f"- {fused}"
    return f"- {title} — {desc}"


def _hit_row(hit: dict) -> str:
    """회수 한 줄 — 제목과 발췌가 같은 말이면 한 번만 적는다.

    스냅샷 쪽은 이미 이 규율을 갖고 있었는데(`_row`) 회수 쪽에는 없었다. 한 문장짜리 페이지는
    title 이 곧 본문이고 snippet 도 그 본문에서 잘라 오므로, 그대로 두면 **같은 문장이 한 줄에
    두 번** 들어간다 (실측 26-07-29: 182자 중 절반이 반복)."""
    title = _neutralize(str(hit["title"]))[:120]
    snippet = _neutralize(str(hit["snippet"]))[:SNIPPET_MAX]
    head = f"{title} `{hit['kind']}`"
    if not snippet:
        return head
    if fused := _fuse(title, snippet):
        return f"{fused} `{hit['kind']}`"
    return f"{head} — {snippet}"
