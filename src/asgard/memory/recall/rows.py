"""주입면에 나가는 한 줄 — 경계 무력화와 제목·발췌 중복 제거. 카탈로그 행과 회수 행이 같은 규율을 쓴다."""

from __future__ import annotations

from ..policy import _INVISIBLE

# 발췌 상한 — 렌더(`_hit_row`)가 자르는 길이와 **같은 값**이어야 한다. 두 값이 갈리면 여기서
# 통째로 넣어 보낸 본문을 저쪽이 다시 자르거나, 여기서 자른 것을 저쪽이 온전한 줄로 취급한다.
SNIPPET_MAX = 160


def _neutralize(s: str) -> str:
    """주입면 경계 무력화 (P0) — 각괄호를 유사문자로 치환해 태그/펜스 탈출 차단.

    비가시 문자는 여기서도 벗긴다. poisoned()가 이미 막지만 그건 '페이지째 제외'라
    저장 이전에 심어진 것·판정을 비껴간 것이 남는다. 주입면에서 한 번 더 벗기는 값이
    제외보다 크다 — 마지막 관문은 조용히 무해하게 만드는 쪽이 낫다."""
    stripped = "".join(c for c in s if c not in _INVISIBLE and not 0xE0000 <= ord(c) <= 0xE007F)
    return stripped.replace("<", "‹").replace(">", "›")


def _row(title: str, desc: str) -> str:
    """카탈로그 행 — 제목과 설명이 같은 말이면 한 번만 적는다.

    한 문장짜리 페이지에서는 title이 곧 본문 첫 줄이고 _desc도 본문 첫 줄이라, 그대로 두면
    주입면의 절반이 같은 문장의 반복이 된다. 자르는 길이가 달라(제목 80·설명 90) 한쪽이 다른
    쪽의 접두사가 되므로 긴 쪽을 남긴다 — 잘림이 덜한 쪽이다."""
    if desc.startswith(title) or title.startswith(desc):
        return f"- {max(title, desc, key=len)}"
    return f"- {title} — {desc}"


def _hit_row(hit: dict) -> str:
    """회수 한 줄 — 제목과 발췌가 같은 말이면 한 번만 적는다.

    스냅샷 쪽은 이미 이 규율을 갖고 있었는데(`_row`) 회수 쪽에는 없었다. 한 문장짜리 페이지는
    title이 곧 본문이고 snippet도 그 본문에서 잘라 오므로, 그대로 두면 **같은 문장이 한 줄에
    두 번** 들어간다 (실측 26-07-29: 182자 중 절반이 반복). 레인 간 중복을 제거하면서 한 줄
    안의 중복을 남겨 두는 것은 앞뒤가 안 맞는다."""
    title = _neutralize(str(hit["title"]))[:120]
    snippet = _neutralize(str(hit["snippet"]))[:SNIPPET_MAX]
    head = f"{title} `{hit['kind']}`"
    if not snippet:
        return head
    # 한쪽이 다른 쪽을 품으면 긴 쪽만 남긴다 — 자르는 길이가 달라(120/160) 접두사 관계가 흔하다.
    if snippet in title or title in snippet:
        return f"{max(title, snippet, key=len)} `{hit['kind']}`"
    return f"{head} — {snippet}"
