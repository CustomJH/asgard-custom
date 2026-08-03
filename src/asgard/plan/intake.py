"""온보딩의 표와 판정 — 커버리지 축·단계·상한, 그리고 온보딩 형상 검사.

`store`가 이 모듈을 부른다. 그래서 여기서는 저장소도 모델도 모르고, 표와 순수 함수만 둔다.

**축(axis)** 은 PRD 한 칸의 근거가 되는 질문 갈래다. 열두 개인 이유는 실무 PRD 템플릿
(Atlassian PRD·Amazon PR/FAQ·Lean Canvas)이 공통으로 요구하는 항목이 그만큼이기 때문이고,
축이 어느 칸의 근거인지는 `INTAKE_AXES`의 세 번째 값이 적는다. 어떤 칸에 대응하는 필수 축이
하나도 `covered`가 아니면 그 칸은 근거가 없다(`grounded_sections`). 표 밖의 축은 만들지
않는다 — 어떤 PRD 칸의 근거도 되지 못하는 질문은 하지 않는다는 뜻이다.

**단계(stage)** 는 축을 묶는 단위다. 묶는 기준은 앞 축의 답이 뒤 축의 질문을 바꾸는가다:
문제를 모르는 채로 성공 판정을 물으면 답이 안 나온다. 단계는 커서지 진척이 아니다 —
진척은 `coverage`에서 파생한다(`readiness_view`).

**상한 넷** (총 12질문 · 5라운드 · 단계당 3질문 · 축당 되묻기 1회)은 설계 결정이다. 이 조합
자체를 잰 연구는 없다. 근거가 정하는 것은 정지 규칙의 형태까지다 — "직전 라운드에서 새로
덮인 축이 없으면 멈춘다".
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

# 기획 문서의 모든 행 id 형상. store도 이 표를 쓴다 — 두 곳에 적으면 언젠가 한 곳만 고친다.
ROW_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_TEXT = 8_000
MAX_TITLE = 200

# 온보딩 갈래. ""는 아직 안 골랐다는 뜻이고, 한 번 고르면 안 바꾼다.
MODES = ("", "auto", "guided")

# (축 id, 사람이 읽는 이름, 근거가 되는 PRD 칸)
INTAKE_AXES = (
    ("problem", "지금 무엇이 안 되는가", "value"),
    ("current_alternative", "지금은 어떻게 하고 있는가", "value"),
    ("user", "누가 쓰는가", "target"),
    ("usage_moment", "언제 여는가", "target"),
    ("success_signal", "무엇을 성공이라 부르는가", "success"),
    ("non_goal", "안 할 것", "overview"),
    ("environment", "어디서 도는가", "attributes"),
    ("role", "사용자 역할", "attributes"),
    ("constraint", "제약", "success"),
    ("why_now", "지금인 이유", "overview"),
    ("risk_unknown", "위험·미정", "success"),
    ("product_category", "제품 갈래", "attributes"),
)

# (단계 id, 이름, 설명, 이 단계의 필수 축, 이 단계의 선택 축)
# `entry`는 갈래를 고르는 자리라 묻는 축이 없고, `confirm`은 새 축을 열지 않고 확인만 한다.
INTAKE_STAGES = (
    ("entry", "진입 갈래", "질문 없이 초안을 쓸지, 문답으로 다듬을지 골라요.", (), ()),
    (
        "frame",
        "맥락",
        "무엇이 문제이고 누가 겪고 지금은 어떻게 하고 있는지 봐요.",
        ("problem", "user", "current_alternative"),
        ("why_now",),
    ),
    (
        "scope",
        "경계",
        "무엇을 성공이라 부르고 무엇을 안 할지 정해요.",
        ("success_signal", "non_goal", "usage_moment"),
        ("risk_unknown",),
    ),
    (
        "ground",
        "조건",
        "어디서 누가 어떤 제약 아래 쓰는지 봐요.",
        ("environment", "role", "constraint"),
        ("product_category",),
    ),
    ("confirm", "확인", "모은 것을 되읽고, 못 채운 칸을 가정으로 적어 둬요.", (), ()),
)

# 축 상태. `thin`은 답이 축을 건드렸지만 일반론·가정법에 머문 것이라 되묻기 대상이 된다.
AXIS_STATES = ("missing", "thin", "covered", "skipped", "assumed")
# 더 물을 것이 없는 상태 — 진척은 이 셋을 센다.
SETTLED_STATES = frozenset({"covered", "skipped", "assumed"})
# 질문 상태. `skipped`는 답이 빈 것과 다르다 — 안 하기로 한 것이라 다시 안 묻는다.
QUESTION_STATES = ("open", "answered", "skipped")
# 질문 종류. `check`는 confirm 단계의 예·아니오 확인 질문이다.
QUESTION_KINDS = ("open", "follow_up", "check")

MAX_QUESTIONS = 12
MAX_ROUNDS = 5
MAX_STAGE_QUESTIONS = 3
MAX_ASSUMPTIONS = 20

AXIS_IDS = tuple(axis for axis, _, _ in INTAKE_AXES)
AXIS_LABEL = {axis: label for axis, label, _ in INTAKE_AXES}
AXIS_SECTION = {axis: section for axis, _, section in INTAKE_AXES}
AXIS_SECTIONS = tuple(dict.fromkeys(section for _, _, section in INTAKE_AXES))

STAGE_IDS = tuple(stage for stage, _, _, _, _ in INTAKE_STAGES)
STAGE_LABEL = {stage: label for stage, label, _, _, _ in INTAKE_STAGES}
_STAGE_AXES = {stage: (required, optional) for stage, _, _, required, optional in INTAKE_STAGES}

REQUIRED_AXES = tuple(axis for _, _, _, required, _ in INTAKE_STAGES for axis in required)

# 상태를 되돌리지 않기 위한 순서. 모델은 매 라운드 전 축을 다시 판정하므로, 이미 정리된 축이
# 다시 missing으로 내려갈 수 있으면 되묻기가 끝나지 않는다.
_STATE_ORDER = {"missing": 0, "thin": 1, "assumed": 2, "skipped": 3, "covered": 4}


def stamp() -> str:
    """UTC 초 단위 시각 문자열 — 기획 문서의 모든 시각 칸이 이 형식이다."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_row_id(prefix: str) -> str:
    """기획 문서 안의 행 하나에 붙일 id."""
    return f"{prefix}-{uuid4().hex[:10]}"


def new(idea: str) -> dict[str, Any]:
    """새 기획의 온보딩 — 갈래도 단계도 아직 안 정해진 상태."""
    return {
        "idea": " ".join(str(idea or "").split()),
        "mode": "",
        "stage": "entry",
        "rounds": 0,
        "questions": [],
        "coverage": {},
        "assumptions": [],
    }


# --- 형상 검사 ----------------------------------------------------------------


def checked(value: Any) -> dict[str, Any]:
    """저장 전 온보딩 검사 — 정규화된 사본을 돌려준다.

    가산 필드가 없는 옛 문서(`{idea, questions: [{id, q, a}]}`)도 그대로 통과한다: 없는 칸은
    기본값으로 채우고 모르는 키는 버린다. 여기서 새 필드를 통과시키지 않으면 저장할 때마다
    조용히 사라진다."""
    if not isinstance(value, dict):
        raise ValueError("intake must be an object")
    idea = value.get("idea")
    if not isinstance(idea, str) or not idea.strip() or len(idea) > MAX_TEXT:
        raise ValueError("intake.idea is required")
    rows = value.get("questions")
    if not isinstance(rows, list) or len(rows) > MAX_QUESTIONS:
        raise ValueError(f"intake.questions must be a list with at most {MAX_QUESTIONS} items")
    return {
        "idea": " ".join(idea.split()),
        "mode": checked_mode(value.get("mode")),
        "stage": checked_stage(value.get("stage")),
        "rounds": _checked_rounds(value.get("rounds")),
        "questions": _checked_questions(rows),
        "coverage": _checked_coverage(value.get("coverage")),
        "assumptions": _checked_assumptions(value.get("assumptions")),
    }


def checked_mode(value: Any) -> str:
    text = str(value or "").strip()
    if text not in MODES:
        raise ValueError("intake.mode must be auto or guided")
    return text


def checked_stage(value: Any) -> str:
    """모르는 단계는 진입 갈래로 되돌린다 — 없는 단계에 서 있으면 물을 축을 못 고른다."""
    text = str(value or "").strip()
    return text if text in STAGE_IDS else "entry"


def _checked_rounds(value: Any) -> int:
    if value is None:
        return 0
    if type(value) is not int or value < 0:
        raise ValueError("intake.rounds must be a non-negative integer")
    return min(value, MAX_ROUNDS)


def _checked_questions(rows: list[Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each intake question must be an object")
        qid, text, answer = row.get("id"), row.get("q"), row.get("a", "")
        if not isinstance(qid, str) or not ROW_ID.fullmatch(qid) or qid in seen:
            raise ValueError("each intake question needs a unique valid id")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TITLE * 3:
            raise ValueError("each intake question needs text")
        if not isinstance(answer, str) or len(answer) > MAX_TEXT:
            raise ValueError("each intake answer must be text")
        parent = row.get("parent")
        out.append(
            {
                "id": qid,
                "q": text.strip(),
                "a": answer,
                "axis": _one_of(row.get("axis"), AXIS_IDS, ""),
                "kind": _one_of(row.get("kind"), QUESTION_KINDS, "open"),
                # 되묻기의 원 질문은 반드시 앞줄이다. 뒷줄을 가리키면 화면이 끝없이 되짚는다.
                "parent": parent if isinstance(parent, str) and parent in seen else "",
                "stage": _one_of(row.get("stage"), STAGE_IDS, ""),
                "state": _question_state(row.get("state"), answer),
            }
        )
        seen.add(qid)
    return out


def _question_state(value: Any, answer: str) -> str:
    if value not in QUESTION_STATES:
        return "answered" if answer.strip() else "open"
    return "answered" if value == "open" and answer.strip() else str(value)


def _checked_coverage(value: Any) -> dict[str, dict[str, str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("intake.coverage must be an object")
    found: dict[str, dict[str, str]] = {}
    for axis, row in value.items():
        if axis not in AXIS_IDS:
            continue  # 축은 코드가 정한다 — 표 밖의 이름은 버린다
        if not isinstance(row, dict) or row.get("state") not in AXIS_STATES:
            raise ValueError(f"intake.coverage.{axis} needs a known state")
        source, at = row.get("source", ""), row.get("at", "")
        if not isinstance(source, str) or len(source) > 64 or not isinstance(at, str) or len(at) > 64:
            raise ValueError(f"intake.coverage.{axis} source and at must be short strings")
        found[axis] = {"state": row["state"], "source": source, "at": at}
    return {axis: found[axis] for axis in AXIS_IDS if axis in found}


def _checked_assumptions(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_ASSUMPTIONS:
        raise ValueError(f"intake.assumptions must be a list with at most {MAX_ASSUMPTIONS} items")
    seen: set[str] = set()
    out = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("each assumption must be an object")
        aid, text = row.get("id"), " ".join(str(row.get("text") or "").split())
        if not isinstance(aid, str) or not ROW_ID.fullmatch(aid) or aid in seen:
            raise ValueError("each assumption needs a unique valid id")
        if not text:
            raise ValueError("each assumption needs text")
        seen.add(aid)
        out.append(
            {
                "id": aid,
                "axis": _one_of(row.get("axis"), AXIS_IDS, ""),
                "text": text[: MAX_TITLE * 3],
                "confirmed": bool(row.get("confirmed")),
            }
        )
    return out


def _one_of(value: Any, allowed: tuple[str, ...], fallback: str) -> str:
    return str(value) if isinstance(value, str) and value in allowed else fallback


# --- 커버리지 -----------------------------------------------------------------


def state_of(coverage: dict[str, Any], axis: str) -> str:
    """축 하나의 상태. 아직 판정한 적이 없으면 `missing`이다."""
    row = coverage.get(axis)
    return row["state"] if isinstance(row, dict) and row.get("state") in AXIS_STATES else "missing"


def mark(coverage: dict[str, Any], axis: str, state: str, source: str = "") -> None:
    """축 상태를 적는다 — 이미 더 정리된 상태면 안 내린다.

    표 밖의 축이나 모르는 상태는 조용히 무시한다: 판정은 모델이 하고 이 함수는 상태만 센다."""
    if axis not in AXIS_IDS or state not in AXIS_STATES:
        return
    prior = coverage.get(axis)
    if isinstance(prior, dict) and _STATE_ORDER.get(prior.get("state"), 0) > _STATE_ORDER[state]:
        return
    coverage[axis] = {"state": state, "source": source, "at": stamp()}


def freeze(coverage: dict[str, Any], axis: str, state: str, source: str = "") -> None:
    """축을 끝난 상태로 굳힌다 — `mark`와 달리 이미 적힌 상태를 덮는다.

    되묻고도 여전히 모호한 축에 쓴다. 답이 들어온 축은 `mark`가 `covered`로 올려 두므로, 여기서
    안 덮으면 모델의 재판정이 아무 효과가 없다."""
    if axis not in AXIS_IDS or state not in AXIS_STATES:
        return
    coverage[axis] = {"state": state, "source": source, "at": stamp()}


def note_assumption(row: dict[str, Any], axis: str, text: str = "") -> dict[str, Any] | None:
    """근거 없이 남은 축 하나를 가정 목록에 적는다 — 같은 축은 한 번만.

    이미 적혀 있거나 상한(`MAX_ASSUMPTIONS`)에 닿았으면 `None`을 돌려준다. 본문 줄 안에 섞어
    두면 세지도 확인하지도 못하기 때문에 목록을 따로 둔다."""
    assumptions = row.setdefault("assumptions", [])
    if axis not in AXIS_IDS or any(item["axis"] == axis for item in assumptions):
        return None
    if len(assumptions) >= MAX_ASSUMPTIONS:
        return None
    body = " ".join(str(text or "").split()) or f"{AXIS_LABEL[axis]} — 답을 못 들어서 초안이 채웠어요"
    item = {"id": new_row_id("a"), "axis": axis, "text": body[: MAX_TITLE * 3], "confirmed": False}
    assumptions.append(item)
    return item


def stage_axes(stage: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """그 단계의 (필수 축, 선택 축). 모르는 단계는 빈 쌍이다."""
    return _STAGE_AXES.get(stage, ((), ()))


def next_stage(stage: str) -> str:
    """다음 단계 id. 마지막 단계면 빈 문자열이다."""
    if stage not in STAGE_IDS:
        return STAGE_IDS[0]
    at = STAGE_IDS.index(stage)
    return STAGE_IDS[at + 1] if at + 1 < len(STAGE_IDS) else ""


def stage_settled(coverage: dict[str, Any], stage: str) -> bool:
    """그 단계의 필수 축이 전부 정리됐는가."""
    required, _ = stage_axes(stage)
    return all(state_of(coverage, axis) in SETTLED_STATES for axis in required)


def settled(coverage: dict[str, Any]) -> bool:
    """온보딩 전체의 필수 축이 전부 정리됐는가."""
    return all(state_of(coverage, axis) in SETTLED_STATES for axis in REQUIRED_AXES)


def grounded_sections(coverage: dict[str, Any]) -> list[str]:
    """근거가 있는 PRD 칸 — 그 칸에 대응하는 필수 축 중 하나라도 `covered`인 칸이다.

    전부 `skipped`이거나 `assumed`인 칸은 사람이 말한 것이 아니라 초안이 채운 것이라 여기서
    빠진다."""
    out = []
    for section in AXIS_SECTIONS:
        axes = [axis for axis in REQUIRED_AXES if AXIS_SECTION[axis] == section]
        if axes and any(state_of(coverage, axis) == "covered" for axis in axes):
            out.append(section)
    return out


def budget(row: dict[str, Any], stage: str = "") -> dict[str, int]:
    """남은 질문 예산. `stage`를 주면 그 단계 기준으로 센다."""
    questions = row.get("questions") or []
    where = stage or row.get("stage") or "entry"
    in_stage = sum(1 for item in questions if item.get("stage") == where)
    rounds = int(row.get("rounds") or 0)
    return {
        "asked": len(questions),
        "remaining": max(0, MAX_QUESTIONS - len(questions)),
        "stage_remaining": max(0, MAX_STAGE_QUESTIONS - in_stage),
        "rounds": rounds,
        "rounds_remaining": max(0, MAX_ROUNDS - rounds),
    }


def open_question(row: dict[str, Any]) -> dict[str, str] | None:
    """지금 물을 것 한 개 — 답도 건너뛰기도 안 한 질문 중 가장 먼저 온 것. 없으면 `None`."""
    for item in row.get("questions") or []:
        if item.get("state") == "open":
            return {
                "id": item["id"],
                "q": item["q"],
                "axis": item["axis"],
                "kind": item["kind"],
                "parent": item["parent"],
                "stage": item["stage"],
            }
    return None


def pending_checks(row: dict[str, Any]) -> list[dict[str, Any]]:
    """예·아니오로 아직 한 번도 안 되짚은 가정들 — 확인 단계가 물을 것.

    이미 확인 질문이 나간 축은 빠진다. 건너뛴 축을 되짚는 것은 전 과정에 한 번뿐이고, 그
    한 번을 셀 자리가 여기다."""
    asked = {item["axis"] for item in row.get("questions") or [] if item.get("kind") == "check"}
    return [item for item in row.get("assumptions") or [] if not item["confirmed"] and item["axis"] not in asked]


def ask_stage(row: dict[str, Any]) -> str:
    """다음 라운드가 설 단계 — 이미 정리됐거나 질문 예산을 다 쓴 단계는 건너뛴다.

    `entry`는 갈래를 고르는 자리라 첫 질문 단계로 옮긴다. `auto`는 문답을 안 돌아 확인 단계로
    바로 간다. 단계당 3질문을 다 쓰고도 축이 안 덮인 단계를 건너뛰는 이유는 상한의 뜻이 그것이기
    때문이다 — 한 단계를 묶는 값이지 문답 전체를 끝내는 값이 아니다."""
    coverage = row.get("coverage") or {}
    stage = row.get("stage") or "entry"
    if stage == "entry":
        stage = "confirm" if row.get("mode") == "auto" else next_stage("entry")
    while stage and stage != "confirm":
        if not stage_settled(coverage, stage) and budget(row, stage)["stage_remaining"]:
            return stage
        stage = next_stage(stage)
    return stage or "confirm"


def can_ask(row: dict[str, Any]) -> bool:
    """지금 모델을 한 번 더 불러 질문을 만들 수 있는가.

    `build.ask` 가 실제로 무엇을 하는지와 같은 판정이다 — 갈리면 화면이 "더 묻기"를 내밀고
    그 버튼이 아무것도 안 하는 자리가 생긴다.

    확인 단계에 선 기획은 축이 안 덮여 있어도 더 안 묻는다 — 자동초안 갈래가 그 자리이고,
    거기서 물을 것은 초안이 낸 가정을 되짚는 예·아니오뿐이다. 반대로 문답을 다 돈 기획은
    축이 전부 정리돼도 아직 안 되짚은 가정이 있으면 확인 한 라운드가 남는다."""
    if open_question(row):
        return False
    stage = ask_stage(row)
    left = budget(row, stage)
    if not left["remaining"] or not left["rounds_remaining"] or not left["stage_remaining"]:
        return False
    if stage == "confirm":
        return bool(pending_checks(row))
    return not stage_settled(row.get("coverage") or {}, stage)


# --- 표면이 받는 모양 ----------------------------------------------------------


def axes_table() -> list[dict[str, Any]]:
    """축 표 — 화면이 HTML에 베껴 적지 않게 API로 내보내는 값."""
    return [
        {"id": axis, "label": label, "prd_section": section, "required": axis in REQUIRED_AXES}
        for axis, label, section in INTAKE_AXES
    ]


def stages_table() -> list[dict[str, Any]]:
    """단계 표 — 축 표와 같은 이유로 API로 내보내는 값."""
    return [
        {"id": stage, "label": label, "desc": desc, "required": list(required), "optional": list(optional)}
        for stage, label, desc, required, optional in INTAKE_STAGES
    ]


def coverage_view(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    """축 열두 개의 지금 상태 — 표 순서 그대로. 안 뜬 축도 `missing`으로 낸다."""
    return [
        {
            "axis": axis,
            "label": label,
            "prd_section": section,
            "required": axis in REQUIRED_AXES,
            "state": state_of(coverage, axis),
        }
        for axis, label, section in INTAKE_AXES
    ]


def readiness_view(row: dict[str, Any]) -> dict[str, Any]:
    """`readiness()['intake']` 가 내는 값 — 전부 내용에서 파생한다(저장하지 않는다).

    `covered`/`axes`는 필수 축 기준이고, 여기서 "덮었다"는 더 물을 것이 없다는 뜻이다
    (`covered`·`skipped`·`assumed`). `blocked`는 늘 비어 있다 — 온보딩은 뒤 문서를 막지 않는다."""
    coverage = row.get("coverage") or {}
    questions = row.get("questions") or []
    done = [axis for axis in REQUIRED_AXES if state_of(coverage, axis) in SETTLED_STATES]
    return {
        "ready": len(done) == len(REQUIRED_AXES),
        "asked": len(questions),
        "answered": len([item for item in questions if item["a"].strip()]),
        "blocked": [],
        "mode": row.get("mode", ""),
        "stage": row.get("stage") or "entry",
        "rounds": int(row.get("rounds") or 0),
        "coverage": coverage_view(coverage),
        "covered": len(done),
        "axes": len(REQUIRED_AXES),
        "grounded_sections": grounded_sections(coverage),
        "assumptions": len(row.get("assumptions") or []),
        "can_ask": can_ask(row),
        "open_question": open_question(row),
    }
