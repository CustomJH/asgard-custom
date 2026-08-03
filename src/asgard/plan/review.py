"""PRD 심사 — 코드가 기계적으로 잴 수 있는 것만 재고, 모델은 안 부른다.

같은 문서는 늘 같은 점수를 낸다. 왕복마다 값이 흔들리면 사람이 그 값을 안 믿고, 안 믿는
숫자는 화면에 없는 것과 같다. 그래서 여기 들어오는 검사는 전부 문서 내용만 읽는 순수 함수다 —
논리 일관성이나 톤처럼 모델이 읽어야 아는 것은 `planner` 쪽 일이다.

심사는 뒤 문서를 막지 않는다. 기능 명세서를 여는 판정은 그대로 `store.readiness()['prd']['ready']`
(개요 한 칸이 찼는가)이고, 여기서 내는 `score`·`grade`·`blocking`은 그 판정을 안 바꾼다.

검사 표는 PRD 리뷰 실무가 잡아내는 실패 유형에서 왔다: 잴 수 없는 성공 지표(기준선·목표·기한이
없다), 확인 안 된 채 남은 도메인 가정, 근거 없이 초안이 채운 칸. 축과 PRD 칸의 대응은
`intake.AXIS_SECTION`·`intake.grounded_sections`가 정본이라 여기서 다시 적지 않는다.
"""

from __future__ import annotations

import re
from typing import Any

from . import intake, store

GRADES = ("draft", "workable", "solid")

# 등급의 사람 이름 — 화면과 마크다운이 같은 말을 쓰게 한다.
GRADE_LABEL = {"draft": "초안이에요", "workable": "쓸 만해요", "solid": "탄탄해요"}

SEVERITIES = ("block", "warn", "note")

# (검사 id, 사람이 읽는 이름, 이 검사가 낼 수 있는 가장 높은 severity)
# 지적마다 붙는 severity 가 정본이다 — `section.empty`는 개요에서만 block 이고 나머지 칸에서는 warn 이다.
REVIEW_CHECKS = (
    ("section.empty", "칸이 비었어요", "block"),
    ("section.thin", "본문이 한 줄뿐이에요", "warn"),
    ("success.unmeasurable", "성공 지표에 숫자가 없어요", "warn"),
    ("success.no_timeframe", "성공 지표에 기간이 없어요", "note"),
    ("attributes.roles_missing", "사용자 역할이 비었어요", "warn"),
    ("attributes.environments_missing", "서비스 환경이 비었어요", "note"),
    ("marker.unresolved", "확인 필요 표시가 남았어요", "warn"),
    ("assumption.unconfirmed", "확인 안 된 가정이 남았어요", "warn"),
    ("section.ungrounded", "초안이 채운 칸이에요", "note"),
)

CHECK_IDS = tuple(check for check, _, _ in REVIEW_CHECKS)
_CHECK_LABEL = {check: label for check, label, _ in REVIEW_CHECKS}
_PRD_LABEL = {section: label for section, label, _ in store.PRD_SECTIONS}

# 감점 폭. 100점에서 지적마다 뺀다 — 검사 아홉 개가 한 번씩 걸린 문서가 0점 근처에 닿는 크기다.
_PENALTY = {"block": 25, "warn": 8, "note": 3}

# 초안이 확신 없는 줄에 다는 표시. 문구의 정본은 `planner._PRD_*` 프롬프트다.
_MARKER = "(확인 필요"

_NUMBER = re.compile(r"\d")

# 기간·시점 표현. `note` 한 건짜리 검사라 넉넉히 잡는다 — 못 잡아서 조용한 쪽이 잘못 지적하는
# 쪽보다 싸다.
_TIMEFRAME = re.compile(
    r"\d+\s*(일|주|주일|개월|달|분기|년|시간|차)"
    r"|이내|안에|까지|기한|마감|출시\s*후|매일|매주|매월|매분기|분기|반기|연간|월간|주간|하루|한\s*달|첫\s*주"
    r"|\bQ[1-4]\b|\bD\+\d+"
    r"|\b(day|week|month|quarter|year|daily|weekly|monthly|quarterly|deadline)s?\b"
)


def review(plan: dict[str, Any]) -> dict[str, Any]:
    """PRD 한 장의 심사 — 점수·등급·지적·칸별 상태·가정 목록을 한 dict 으로 돌려준다.

    모델을 안 부르고 `plan` 내용만 읽는다. 같은 문서는 늘 같은 값이 나온다.

      score       0..100. 100 에서 지적마다 `_PENALTY` 만큼 뺀 값(음수는 0)
      grade       `block`이 있으면 draft · `block`도 `warn`도 없으면 solid · 그 사이는 workable
      blocking    severity 가 `block`인 지적 수
      findings    지적 목록. `section`이 빈 문자열이면 칸이 아니라 문서 전체를 가리킨다
      sections    PRD 칸 다섯 개의 상태. 지적이 하나도 없는 칸도 반드시 들어간다
      assumptions 온보딩이 적어 둔 가정 — `section`은 그 축이 근거가 되는 PRD 칸이다
    """
    prd = plan.get("prd") or {}
    sections = prd.get("sections") or {}
    attributes = prd.get("attributes") or {}
    onboarding = plan.get("intake") or {}
    grounded = set(intake.grounded_sections(onboarding.get("coverage") or {}))

    findings: list[dict[str, Any]] = []
    view: dict[str, dict[str, Any]] = {}
    for sid in store.PRD_SECTION_IDS:
        body = str((sections.get(sid) or {}).get("body") or "")
        found = _section_findings(sid, body, grounded)
        if sid == "attributes":
            found.extend(_attribute_findings(attributes))
        findings.extend(found)
        view[sid] = {
            "filled": _filled(sid, body, attributes),
            "grounded": sid in grounded,
            "lines": _lines(body),
            "findings": len(found),
            "markers": body.count(_MARKER),
        }
    findings.extend(_assumption_findings(onboarding.get("assumptions") or []))

    blocking = sum(1 for row in findings if row["severity"] == "block")
    warning = sum(1 for row in findings if row["severity"] == "warn")
    return {
        "score": max(0, 100 - sum(_PENALTY[row["severity"]] for row in findings)),
        "grade": "draft" if blocking else ("workable" if warning else "solid"),
        "blocking": blocking,
        "findings": findings,
        "sections": view,
        "assumptions": _assumptions_view(onboarding.get("assumptions") or []),
    }


def _filled(sid: str, body: str, attributes: dict[str, Any]) -> bool:
    """이 칸이 채워졌는가. 속성 설정만 본문이 아니라 값 세 칸으로 판정한다.

    `planner._PRD_BASE`가 속성 본문을 짧게 두라고 지시하고 `store.PRD_SECTIONS`의 안내도
    값 세 칸을 가리키므로, 본문이 비어 있고 값이 다 찬 것이 이 칸의 정상이다."""
    if sid != "attributes":
        return bool(body.strip())
    return bool(body.strip() or attributes.get("category") or attributes.get("roles") or attributes.get("environments"))


def _section_findings(sid: str, body: str, grounded: set[str]) -> list[dict[str, Any]]:
    """칸 하나의 지적. 빈 칸에는 내용 검사를 안 건다 — 같은 자리를 세 줄로 지적하게 된다."""
    label = _PRD_LABEL.get(sid, sid)
    # 속성 설정의 빈 본문은 지적하지 않는다 — 뜻을 지는 것은 값 세 칸이고, 그 셋은
    # `_attribute_findings`가 따로 본다. 여기서 걸면 정상 상태의 문서마다 지적이 하나 뜬다.
    if not body.strip() and sid != "attributes":
        severity = "block" if sid == "overview" else "warn"
        return [_found("section.empty", sid, severity, f"{label} 칸에 본문이 없어요.", f"{label} 칸을 채워 주세요.")]
    if not body.strip():
        return []

    found = []
    lines = _lines(body)
    # 속성 설정은 산문이 아니라 값이 든 칸이라 줄 수로 재지 않는다 — 역할·환경은 아래 두 검사가 본다.
    if sid != "attributes" and lines <= 1:
        found.append(
            _found(
                "section.thin", sid, "warn", f"{label} 칸이 {lines}줄이에요.", f"{label} 칸에 두어 줄을 더 적어 주세요."
            )
        )
    if sid == "success":
        found.extend(_success_findings(body))
    markers = body.count(_MARKER)
    if markers:
        found.append(
            _found(
                "marker.unresolved",
                sid,
                "warn",
                f"확인 필요 표시가 {markers}군데 남았어요.",
                "표시된 줄을 확인하고 표시를 지워 주세요.",
            )
        )
    if sid not in grounded:
        found.append(
            _found(
                "section.ungrounded",
                sid,
                "note",
                f"{label} 칸의 근거가 되는 축이 아직 답으로 안 덮였어요.",
                f"{label} 칸에 대응하는 온보딩 질문에 답해 주세요.",
            )
        )
    return found


def _success_findings(body: str) -> list[dict[str, Any]]:
    """성공 지표 칸만 받는 두 검사 — 기준선·목표는 숫자로, 기한은 기간 표현으로 적힌다."""
    found = []
    if not _NUMBER.search(body):
        found.append(
            _found(
                "success.unmeasurable",
                "success",
                "warn",
                "숫자가 하나도 없어요.",
                "기준선과 목표를 숫자로 적어 주세요.",
            )
        )
    if not _TIMEFRAME.search(body):
        found.append(
            _found(
                "success.no_timeframe",
                "success",
                "note",
                "언제까지 재는지가 안 적혀 있어요.",
                "지표를 재는 기간이나 시점을 적어 주세요.",
            )
        )
    return found


def _attribute_findings(attributes: dict[str, Any]) -> list[dict[str, Any]]:
    """역할·환경은 기능 명세서와 유저 플로우가 그대로 소비하는 값이라 본문과 별개로 본다."""
    found = []
    if not (attributes.get("roles") or []):
        found.append(
            _found(
                "attributes.roles_missing",
                "attributes",
                "warn",
                "사용자 역할이 0개예요.",
                "속성 설정에 역할을 하나 이상 적어 주세요.",
            )
        )
    if not (attributes.get("environments") or []):
        found.append(
            _found(
                "attributes.environments_missing",
                "attributes",
                "note",
                "서비스 환경이 0개예요.",
                "속성 설정에 환경을 하나 이상 적어 주세요.",
            )
        )
    return found


def _assumption_findings(assumptions: list[Any]) -> list[dict[str, Any]]:
    """확인 안 된 가정은 문서 전체의 지적이다 — 한 칸에 매달면 여러 칸의 가정이 한 칸에 몰린다."""
    left = [row for row in assumptions if isinstance(row, dict) and not row.get("confirmed")]
    if not left:
        return []
    return [
        _found(
            "assumption.unconfirmed",
            "",
            "warn",
            f"확인 안 된 가정이 {len(left)}건이에요.",
            "가정 목록에서 맞는지 아닌지 판정해 주세요.",
        )
    ]


def _assumptions_view(assumptions: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(row.get("id") or ""),
            "axis": str(row.get("axis") or ""),
            "section": intake.AXIS_SECTION.get(str(row.get("axis") or ""), ""),
            "text": str(row.get("text") or ""),
            "confirmed": bool(row.get("confirmed")),
        }
        for row in assumptions
        if isinstance(row, dict)
    ]


def _found(check: str, section: str, severity: str, detail: str, fix: str) -> dict[str, Any]:
    return {
        "id": check,
        "section": section,
        "severity": severity,
        "label": _CHECK_LABEL[check],
        "detail": detail,
        "fix": fix,
    }


def _lines(body: str) -> int:
    """본문의 줄 수 — 빈 줄은 안 센다. 문단 사이 빈 줄까지 세면 한 문장도 여러 줄이 된다."""
    return len([line for line in body.splitlines() if line.strip()])


def checks_table() -> list[dict[str, str]]:
    """검사 표 — 화면이 HTML 에 베껴 적지 않게 API 로 내보내는 값."""
    return [{"id": check, "label": label, "severity": severity} for check, label, severity in REVIEW_CHECKS]
