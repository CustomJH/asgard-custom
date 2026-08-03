"""댓글의 `@이름` — 누구를 부른 것인가.

**왜 담당 칸으로 안 되는가.** `assignee`는 지금 누구 것인지 하나를 적는 자리다. 부르는 것은
다르다: 한 댓글이 둘을 부를 수 있고("@freyja 화면은 이쪽, @eitri 빌드는 그쪽"), 부른 기록은
남되 담당은 안 바뀔 수도 있다. 대화에서 일이 갈리는 자리가 댓글이라 여기에 문을 낸다.

**이름은 사용자가 세운 에이전트다**(`profiles.listing()`). 내장 명부에 있으나 아직 안 세운
이름은 **모르는 이름으로 낸다** — 조용히 만들어 붙이면, 오타 하나가 없는 에이전트에게 일을
맡긴 것처럼 보이고 아무도 안 온다. 모른다고 말하는 편이 낫다.

**여기서는 부르지 않는다.** 이 모듈은 글에서 이름을 읽어 명부에 맞춰 볼 뿐이고, 실제로
작업을 띄우는 것은 실행을 소유한 계층이다(`commands.studio.tasks`). 파싱과 배차를 한자리에
두면, 댓글을 저장하는 것만으로 프로세스가 뜬다.
"""

from __future__ import annotations

import re

__all__ = ["agents", "handles", "resolve", "roster"]

# `@이름` — 앞 글자가 단어 문자면 안 잡는다. 그래야 메일 주소(`odin@asgard.io`)가 멘션으로
# 읽히지 않는다. 이름은 영문자로 시작하고 profiles 의 이름 규약(영숫자·`-`·`_`)을 따른다.
_HANDLE = re.compile(r"(?<![\w@.-])@([A-Za-z][A-Za-z0-9_-]{0,39})")


def roster() -> list[dict]:
    """`@`로 부를 수 있는 이름들 — 이 기계에 실제로 선 에이전트.

    설명까지 싣는 이유는 창의 자동완성 때문이다: 이름만 있으면 사람은 `@ullr`과 `@loki`
    중 무엇을 부를지 매번 다른 화면에 가서 확인해야 한다."""
    from ..profiles import listing

    return [
        {
            "handle": str(row["id"]),
            "name": str(row.get("name") or row["id"]),
            "description": str(row.get("description") or ""),
            "active": bool(row.get("active")),
        }
        for row in listing()
    ]


def handles(text: str) -> list[str]:
    """글에 나온 이름들 — 원문 순서, 중복 없이. 대소문자는 안 가린다(프로필 이름이 소문자다)."""
    if not isinstance(text, str) or "@" not in text:
        return []
    found: list[str] = []
    seen: set[str] = set()  # 순서는 목록이 지키고 중복 판정은 집합이 진다
    for match in _HANDLE.finditer(text):
        name = match.group(1).lower()
        if name not in seen:
            seen.add(name)
            found.append(name)
    return found


def resolve(text: str) -> list[dict]:
    """부른 이름 하나하나를 명부에 맞춰 본다 — 없는 이름도 **뺴지 않고** 모른다고 적는다.

    빼면 화면은 "아무도 안 불렸다"를 그리고, 사람은 자기가 부른 줄 안다."""
    known = {row["handle"].lower(): row for row in roster()}
    out = []
    for name in handles(text):
        row = known.get(name)
        out.append(
            {
                "handle": name,
                "known": row is not None,
                "name": str(row["name"]) if row else name,
                "description": str(row["description"]) if row else "",
            }
        )
    return out


def agents(text: str) -> list[str]:
    """실제로 일을 맡길 수 있는 이름만."""
    return [row["handle"] for row in resolve(text) if row["known"]]
