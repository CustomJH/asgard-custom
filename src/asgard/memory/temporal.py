"""사건 시각 확정 — 사실 안의 상대 시간 표현을 절대 날짜로 푼다.

"어제 정한 규칙"은 적힐 때는 참이지만 한 달 뒤에 읽으면 거짓이다. 개인 메모리는 오래 남는
게 목적이라 이 미끄러짐이 그대로 부채가 된다. 그래서 저장 시점에 한 번 절대 날짜로 확정한다.

**본문은 안 고친다.** 오딘이 쓴 문장은 그대로 두고 `event:` 메타에 절대 날짜만 적는다 —
사람의 말을 기계가 고쳐 쓰기 시작하면 정본이 정본이 아니게 된다. 랭킹·표시는 메타를 보고,
사람은 원문을 본다.

기록 시각(`created`/`updated`)과 사건 시각(`event`)은 다르다. "작년에 정한 규칙"을 오늘
적으면 기록은 오늘이고 사건은 작년이다. 최신성 보정이 봐야 하는 건 뒤쪽이다.
"""

from __future__ import annotations

import datetime as _dt
import re

# 상대 표현 → 오늘로부터의 일수. 한국어를 앞에 둔다 (정본 어휘).
_OFFSETS: tuple[tuple[str, int], ...] = (
    (r"그저께|그제|엊그제", -2),
    (r"어제|어저께|yesterday", -1),
    (r"오늘|금일|today", 0),
    (r"내일|명일|tomorrow", 1),
    (r"모레|내일모레", 2),
)
# 단위 표현 — (정규식, 하루 단위 환산). 숫자는 캡처 그룹 1에서 읽는다.
_UNITS: tuple[tuple[str, int], ...] = (
    (r"(\d+)\s*일\s*(?:전|앞)", 1),
    (r"(\d+)\s*주\s*(?:일\s*)?전", 7),
    (r"(\d+)\s*(?:개월|달)\s*전", 30),
    (r"(\d+)\s*년\s*전", 365),
    (r"(\d+)\s*days?\s*ago", 1),
    (r"(\d+)\s*weeks?\s*ago", 7),
    (r"(\d+)\s*months?\s*ago", 30),
    (r"(\d+)\s*years?\s*ago", 365),
)
# 숫자 없는 관용 표현 — 정밀도가 낮아 '구간의 시작'으로 보수적으로 잡는다.
_LOOSE: tuple[tuple[str, int], ...] = (
    (r"지난\s*주|저번\s*주|last\s+week", -7),
    (r"지난\s*달|저번\s*달|last\s+month", -30),
    (r"작년|지난\s*해|last\s+year", -365),
)
# 이미 절대 날짜가 적혀 있으면 그게 정답이다 — 추론보다 명시가 세다.
_ABSOLUTE = re.compile(r"\b(\d{4})[-./](\d{1,2})[-./](\d{1,2})\b")

MAX_AGE_DAYS = 365 * 20  # 확정 결과 온전성 상한 — 오탐(전화번호·버전 문자열)을 날짜로 삼지 않는다


def ground_event_date(text: str, today: _dt.date | None = None) -> str | None:
    """사실 안의 시간 표현 → ISO 날짜. 못 찾으면 None (그 사실엔 사건 시각이 없다).

    명시 날짜 > 상대 표현 > 단위 표현 순으로 본다. 여러 개면 **가장 이른 것**을 고른다:
    사건은 보통 문장의 앞쪽에서 언급되고, 여러 시점이 섞였다면 그 사실이 걸쳐 있는 구간의
    시작이 검색에 더 쓸모 있다."""
    if not text or not text.strip():
        return None
    base = today or _dt.date.today()
    found: list[_dt.date] = []

    for match in _ABSOLUTE.finditer(text):
        year, month, day = (int(g) for g in match.groups())
        try:
            found.append(_dt.date(year, month, day))
        except ValueError:
            continue  # 2026-13-45 같은 건 날짜가 아니다

    for pattern, days in (*_OFFSETS, *_LOOSE):
        if re.search(pattern, text, re.IGNORECASE):
            found.append(base + _dt.timedelta(days=days))

    for pattern, scale in _UNITS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            try:
                amount = int(match.group(1))
            except ValueError, IndexError:
                continue
            if 0 < amount * scale <= MAX_AGE_DAYS:
                found.append(base - _dt.timedelta(days=amount * scale))

    if not found:
        return None
    earliest = min(found)
    if abs((base - earliest).days) > MAX_AGE_DAYS:
        return None  # 확정 결과가 상식 밖이면 확정 안 한 것으로 친다
    return earliest.isoformat()


def event_date(meta: dict) -> str:
    """랭킹·표시가 쓰는 사건 시각 — `event` 우선, 없으면 기록 시각으로 폴백."""
    for key in ("event", "updated", "created"):
        value = str(meta.get(key) or "").strip()
        if value:
            return value
    return ""
