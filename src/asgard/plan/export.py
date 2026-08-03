"""PRD 한 장을 문서 밖으로 내보내는 자리 — 형식은 마크다운 하나다.

여태 창 밖으로 나가는 길은 textarea 를 손으로 복사하는 것뿐이었다. 그러면 받는 쪽에 남는 것이
본문 다섯 덩이뿐이라 칸 이름도, 뒤 문서가 소비하는 속성도, 초안이 근거 없이 채운 자리도
사라진다. 검토자가 "무엇을 근거로 썼는가"를 물을 수 없는 문서가 된다.

여기서는 저장하지 않는다. 문자열 하나를 짓고 끝난다.
"""

from __future__ import annotations

from typing import Any

from . import store
from .review import GRADE_LABEL, review

_EMPTY = "(아직 비어 있어요)"


def to_markdown(plan: dict[str, Any]) -> str:
    """PRD 한 장의 마크다운 본문 — 제목·다섯 칸·속성·가정 목록·심사 요약 순서.

    빈 칸도 제목을 남기고 비었다고 적는다: 빠뜨린 칸과 아직 안 쓴 칸은 받는 쪽에서 구별이 안 된다.
    끝은 줄바꿈 하나로 닫는다."""
    prd = plan.get("prd") or {}
    sections = prd.get("sections") or {}
    attributes = prd.get("attributes") or {}
    card = review(plan)

    out = [f"# {str(plan.get('title') or '').strip() or '제목 없는 기획'}", ""]
    for sid, label, _ in store.PRD_SECTIONS:
        body = str((sections.get(sid) or {}).get("body") or "").strip()
        out += [f"## {label}", "", body or _EMPTY, ""]
    out += _attributes_block(attributes)
    out += _assumptions_block(card["assumptions"])
    out += _review_block(card)
    return "\n".join(out).rstrip("\n") + "\n"


def _attributes_block(attributes: dict[str, Any]) -> list[str]:
    """뒤 문서가 그대로 읽는 값 셋 — 본문 안에 녹여 두면 꺼낼 때마다 다시 추측해야 한다."""
    roles = ", ".join(str(row) for row in attributes.get("roles") or [])
    environments = ", ".join(str(row) for row in attributes.get("environments") or [])
    return [
        "## 속성",
        "",
        f"- 제품 갈래: {str(attributes.get('category') or '').strip() or _EMPTY}",
        f"- 사용자 역할: {roles or _EMPTY}",
        f"- 서비스 환경: {environments or _EMPTY}",
        "",
    ]


def _assumptions_block(assumptions: list[dict[str, Any]]) -> list[str]:
    out = ["## 가정", ""]
    if not assumptions:
        return out + ["- 초안이 근거 없이 채운 자리는 없어요.", ""]
    for row in assumptions:
        mark = "확인함" if row["confirmed"] else "미확인"
        out.append(f"- ({mark}) {row['text']}")
    return out + [""]


def _review_block(card: dict[str, Any]) -> list[str]:
    grade = card["grade"]
    out = [
        "## 심사",
        "",
        f"- 점수 {card['score']}/100 — {GRADE_LABEL.get(grade, grade)}",
        f"- 막는 지적 {card['blocking']}건 · 지적 전체 {len(card['findings'])}건",
        "",
    ]
    if not card["findings"]:
        return out + ["- 걸린 지적이 없어요.", ""]
    labels = {sid: label for sid, label, _ in store.PRD_SECTIONS}
    for row in card["findings"]:
        where = labels.get(row["section"], "문서 전체")
        out.append(f"- [{row['severity']}] {where} · {row['label']} — {row['detail']} {row['fix']}")
    return out + [""]
