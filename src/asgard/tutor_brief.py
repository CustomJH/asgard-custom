"""앞서 말하는 층 — 같은 자리를 다시 건드리기 **전에** 남은 물음을 꺼낸다.

되짚기는 오래 사후였다: 다 쓰고 나서 물었다. 그런데 지난번 물음이 값을 갖는 유일한 때는 같은
자리를 다시 여는 순간이다 — 그때는 "언젠가 볼 것"이었지만 지금은 **지금 여는 파일**이다. 사후
카드(`tutor.review`)가 부채를 적는 층이면 여기는 부채를 만나는 층이다.

`tutor` 에서 갈라 나온 이유는 축이 다르기 때문이다. 그쪽은 **이번 변경의 사실**을 만들고, 여기는
이미 쌓인 기록(`tutor_growth`)을 요청 문장에 맞춰 **고르기만** 한다 — 새 판정을 하지 않는다.
여기서 파일을 다시 읽기 시작하면 턴 시작이 느려지고, 느린 안내는 꺼지는 안내다.

계약 두 줄:

  ① 가리키는 자리에만 말한다. 경로 조각이 **통째로** 맞을 때만 센다 (`heimdall` ○, `dall` ✕) —
     느슨하게 맞추면 아무 요청에나 남의 물음이 붙고, 그러면 이 줄은 배경 소음이 된다.
  ② 같은 물음을 두 번 쓰지 않는다. (종류, 파일)로 접어 한 번만 묻고, 마지막 줄에 이게 무엇이고
     통째로 치우려면 무엇을 치면 되는지 적는다 — 열두 건을 하나씩 답할 사람은 없다.
"""

from __future__ import annotations

import os
import re
import time

from . import tutor_growth
from .tutor_model import KIND_LABEL, WEIGHT

_TOKEN = re.compile(r"[A-Za-z0-9_./\\-]{3,}")
# 자기 힘으로는 자리를 못 가리키는 조각. `src` 한 글자에 나무 전체가 걸리면 이 줄은 배경 소음이
# 되고, 배경 소음이 된 안내는 켜져 있어도 꺼진 것과 같다. 확장자·구조 디렉터리가 여기 온다.
_WEAK = frozenset("src lib test tests spec py js ts tsx jsx go rs java kt md json toml yaml yml".split())
_GROUP_UNITS = 3  # 한 줄에 이름 셋까지 — 넘치면 수로만 적는다
# 표식 여덟 자를 외우게 하지 않는다 — 파일 하나, 또는 전부. 셋 다 `--dismiss` 한 입구로 들어간다.
_EXIT_LINE = (
    '  답하면 `asgard tutor --answer <표식> "..."` · 아니다 싶으면 `asgard tutor --dismiss <표식>`.\n'
    "  파일째 치우려면 `asgard tutor --dismiss <경로>`, 전부 치우려면 `asgard tutor --dismiss all`."
)


def brief(root: str, text: str = "", paths: object = (), cap: int = 3) -> str:
    """**들어가기 전에** 이 자리에 남아 있는 답 없는 물음. 없으면 빈 문자열.

    26-08-11 오딘 지적이 지금 모양을 정했다: 같은 종류가 같은 파일에서 셋이면 물음 문장도 셋이
    똑같이 나갔고, 뒤의 둘은 앞의 하나에 아무것도 안 더했다. 표식 여덟 자는 아무도 안 외웠다.
    """
    named = _normalise(paths)
    here = named or _here(root, _keys(text or ""))
    if not here:
        return ""
    hit = [r for r in tutor_growth.open_points(root) if r.path in here]
    back = tutor_growth.recall(root, here)
    if not hit and not back:
        return ""
    hit.sort(key=lambda r: (-WEIGHT.get(r.kind, 0), r.opened))
    lines = []
    if hit:
        groups = _group(hit)
        lines.append(f"⠶ 들어가기 전 — 지난 턴에 열어 둔 물음이 이 자리에 {len(hit)}건 있어요 (막지 않아요).")
        for row, units, extra in groups[:cap]:
            where = row.path + (f" {units}" if units else "")
            lines.append(f"  {KIND_LABEL.get(row.kind, row.kind)} — {where}  [{row.cid}]")
            lines.append(f"    ▸ {row.ask}")
            if extra:
                lines.append(f"    같은 물음이 이 파일에 {extra}건 더 있어요 — 한 번에 닫으려면 아래를 보세요.")
        if len(groups) > cap:
            lines.append(f"  …다른 자리 {len(groups) - cap}곳은 접었어요")
        lines.append(_EXIT_LINE)
    lines += _recall_lines(back, bool(hit))
    return "\n".join(lines)


def _normalise(paths: object) -> set[str]:
    """지목된 경로들. `tutor._normalise` 와 같은 규칙이지만 부르지 않는다 — 그쪽은 적용 등급이라
    여기서 부르면 계층이 거꾸로 선다 (`tests/test_architecture.py` 가 잡는다)."""
    if not isinstance(paths, (list, tuple, set, frozenset)):
        return set()
    return {rel for raw in paths if (rel := str(raw).strip().replace(os.sep, "/"))}


def _group(rows: list[tutor_growth.Revisit]) -> list[tuple[tutor_growth.Revisit, str, int]]:
    """(종류, 파일)로 접는다 — 대표 하나, 같이 접힌 단위 이름, 이름조차 못 실은 나머지 수.

    접는 축이 (종류, 파일)인 이유는 물음 문장이 그 둘로 정해지기 때문이다. `KIND_LABEL` 이 같고
    파일이 같으면 `ask` 도 글자 그대로 같고, 같은 문장을 세 번 읽는 사람은 세 번째부터 안 읽는다.
    """
    seen: dict[tuple[str, str], list[tutor_growth.Revisit]] = {}
    for row in rows:
        seen.setdefault((row.kind, row.path), []).append(row)
    out = []
    for group in seen.values():
        names = [row.unit for row in group[:_GROUP_UNITS] if row.unit]
        out.append((group[0], " · ".join(names), max(0, len(group) - max(1, len(names)))))
    return out


def _here(root: str, keys: set[str]) -> set[str]:
    """요청 문장이 가리키는 자리 — 열린 물음이 안 남은 자리도 포함한다(회상은 거기서 나온다)."""
    if not keys:
        return set()
    return {path for path, units in tutor_growth.places(root).items() if _touches(path, units, keys)}


def _recall_lines(back: list[tutor_growth.Said], after_questions: bool) -> list[str]:
    """그때 당신이 한 답을 그대로 되돌려 준다 — 기계의 판정으로 다시 쓰지 않는다.

    날짜를 반드시 붙인다. 그 사이 코드가 바뀌었을 수 있고, 바뀌었는지는 여기서 못 정한다 —
    "당신이 그때 이렇게 말했다"는 사실만 참이고, 지금도 맞는지는 사람이 본다.
    """
    if not back:
        return []
    now = time.time()
    head = "  " if after_questions else "⠶ 들어가기 전 — "
    lines = [f"{head}이 자리를 두고 **예전에 하신 답**이 있어요."]
    for row in back:
        days = row.days(now)
        when = f"{days}일 전" if days else "오늘"
        tag = "오탐으로 닫음" if row.dismissed else "답"
        lines.append(f"  ↺ {row.where} — {when} {tag}")
        lines.append(f'    "{row.said}"')
    return lines


def _keys(text: str) -> set[str]:
    """요청 문장에서 자리를 가리킬 수 있는 조각만. `app.py`는 통째로도, 쪼개서도 센다."""
    out: set[str] = set()
    for raw in _TOKEN.findall(text):
        for piece in [raw, *re.split(r"[/\\.]", raw)]:
            key = piece.lower().strip("-_")
            if len(key) >= 3 and key not in _WEAK:
                out.add(key)
    return out


def _touches(path: str, units: set[str], keys: set[str]) -> bool:
    """요청 문장이 이 자리를 가리키는가 — 경로 조각과 단위 이름만 본다(0-LLM).

    느슨하게 맞추면 아무 요청에나 남의 물음이 붙고, 그러면 이 줄은 배경 소음이 된다. 그래서
    경로의 **조각 하나가 통째로** 일치할 때만 센다 (`heimdall` ○, `dall` ✕).
    """
    parts = {p.lower() for p in re.split(r"[/\\.]", path) if p}
    parts.add(path.lower())
    parts.add(os.path.basename(path).lower())
    parts |= {u.rsplit(".", 1)[-1].lower() for u in units if u}
    return bool(parts & keys)
