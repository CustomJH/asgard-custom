"""지능이 만든 것을 문서에 앉히는 자리 — `planner`(짓기)와 `store`(담기) 사이.

여기서 갈리는 것이 하나 있다: **초안은 앉히고, 수정은 제안한다.**

빈 문서에 첫 초안을 넣는 것은 아무것도 지우지 않으므로 바로 쓴다. 반대로 이미 사람이
손댄 칸을 모델이 다시 쓰는 것은 되돌릴 수 없는 일이라, 그때는 글만 돌려주고 반영은
사람이 누른다. "AI가 내 문장을 조용히 갈아치웠다"가 이 기획 화면에서 가장 비싼 실패다.

제안은 범위가 셋이고 셋 다 저장하지 않는다: 칸 하나(`propose_section`), 다섯 칸을 한 번에
(`propose_document`), 사람이 고른 구간만(`propose_selection`). 범위가 좁을수록 사람이 안 고른
자리가 갈릴 확률이 낮으므로, 화면은 고른 구간이 있으면 가장 좁은 것을 고른다.

대화 한 턴도 여기 있다. 사용자의 말과 답을 **같은 왕복 안에서** 기록에 남기기 때문이다 —
따로 쓰면 답이 오는 사이에 창을 닫은 사람의 질문이 사라진다.
"""

from __future__ import annotations

import os
from typing import Any

from . import intake, planner, store


def _model_root(plan: dict[str, Any], root: str = "") -> str:
    """모델을 부를 때 **설정을 읽을** 자리. 기획이 있는 자리가 아니다.

    기획 자체는 폴더에 매이지 않는다(워크스페이스 하나). 다만 provider·모델 설정은 여전히
    자리에서 읽으므로, 이 기획이 가리키는 폴더가 있으면 그 폴더의 설정을 존중하고 없으면
    부른 쪽이 준 자리를, 그것도 없으면 지금 서 있는 자리를 쓴다."""
    return plan.get("root") or root or os.getcwd()


def ask(plan_id: str, root: str = "") -> dict[str, Any]:
    """온보딩 한 라운드 — 지금 단계의 안 덮인 축만 묻는다.

    한 번 부르면 모델 호출은 한 번이다. 그 단계에서 물을 것이 없으면 질문을 안 얹고 단계만
    다음으로 옮긴다 — 다음 단계는 화면이 다시 부를 때 돈다. 상한(질문 12·라운드 5)에 닿았거나
    필수 축이 전부 정리됐으면 아무것도 안 하고 그대로 돌려준다."""
    plan = store.load_plan(plan_id)
    stage = intake.ask_stage(plan["intake"])
    if not intake.can_ask(plan["intake"]):
        if stage == plan["intake"]["stage"]:
            return plan
        # 물을 것은 없지만 커서는 움직였다 — 안 적으면 화면이 끝난 단계를 계속 보여 준다.
        return store.mutate(plan_id, lambda draft: draft["intake"].__setitem__("stage", stage))
    result = planner.ask_questions(_model_root(plan, root), plan, stage)
    return store.mutate(plan_id, lambda draft: _land_round(draft, stage, result))


def _land_round(draft: dict[str, Any], stage: str, result: dict[str, Any]) -> None:
    """한 라운드의 판정과 질문을 문서에 기록한다."""
    row = draft["intake"]
    row["rounds"] += 1
    row["stage"] = stage
    followed = {item["axis"] for item in row["questions"] if item["kind"] == "follow_up"}
    for axis, state in result["assessment"]:
        if state == "thin" and axis in followed:
            # 되묻고도 여전히 모호하면 가정으로 굳힌다 — 같은 축을 두 번 되물으면 문답이 안 끝난다.
            intake.freeze(row["coverage"], axis, "assumed")
            intake.note_assumption(row, axis)
            continue
        intake.mark(row["coverage"], axis, state)
        if state == "skipped":
            intake.note_assumption(row, axis)
    # `opened_axes`는 저장하지 않는다. 축 열두 개는 고정이고 안 뜬 축의 기본 상태가 이미
    # `missing`이라 적을 것이 없다 — 이 칸이 하는 일은 프롬프트 쪽이다: 답이 다른 축의 사실을
    # 열었을 때 모델이 이 단계에서 그걸 묻는 대신 이름만 대게 한다.
    added = _land_questions(row, stage, result["questions"])
    if added:
        store.append_chat(draft, "asgard", _ask_note(stage, len(added)))
        return
    row["stage"] = intake.next_stage(stage) or stage


def _land_questions(row: dict[str, Any], stage: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """이 라운드의 질문을 표에 얹는다 — 상한과 중복은 여기서 거른다.

    거르는 것 넷: 단계·전체 질문 예산, 같은 문장 중복, 축당 열린 질문 1개, 축당 되묻기 1회.
    판정은 모델이 하고 상한은 코드가 센다."""
    left = intake.budget(row, stage)
    room = min(left["remaining"], left["stage_remaining"])
    asked = {item["q"] for item in row["questions"]}
    used = {(item["axis"], item["kind"]) for item in row["questions"] if item["axis"]}
    added = []
    for item in rows:
        if len(added) >= room:
            break
        axis, kind = item["axis"], item["kind"]
        if item["q"] in asked or (axis and (axis, kind) in used):
            continue
        # 건너뛴 축은 다시 안 묻는다. 예외는 확인 질문 하나뿐이다 — 건너뛴 자리를 가정으로
        # 굳히기 전에 예·아니오로 한 번만 되짚는다(`intake.pending_checks`가 그 한 번을 센다).
        if axis and kind != "check" and intake.state_of(row["coverage"], axis) == "skipped":
            continue
        asked.add(item["q"])
        if axis:
            used.add((axis, kind))
        added.append(
            {
                "id": store.new_id("q"),
                "q": item["q"],
                "a": "",
                "axis": axis,
                "kind": kind,
                "parent": item["parent"],
                "stage": stage,
                "state": "open",
            }
        )
    row["questions"].extend(added)
    return added


def _ask_note(stage: str, count: int) -> str:
    label = intake.STAGE_LABEL.get(stage, stage)
    if stage == "confirm":
        return f"초안에서 제가 채운 자리를 {count}가지만 확인할게요. 예·아니오로 답해 주시면 돼요."
    return f"{label} 단계예요. {count}가지만 여쭤볼게요 — 아는 것만 답하고 나머지는 건너뛰셔도 돼요."


def draft_prd(plan_id: str, root: str = "") -> dict[str, Any]:
    """문답에서 PRD 초안으로. 사람이 이미 쓴 칸은 덮지 않는다.

    자동초안 갈래는 여기서 방어 셋이 붙는다: 추측한 역할·환경을 안 적고, 못 채운 축을 가정
    목록으로 꺼내고, 사후 확인 질문을 세 개까지 문답표에 얹는다."""
    plan = store.load_plan(plan_id)
    drafted = planner.draft_prd(_model_root(plan, root), plan)

    def change(draft: dict[str, Any]) -> None:
        auto = draft["intake"]["mode"] == "auto"
        written = _land_sections(draft, drafted, auto)
        _land_assumptions(draft, drafted)
        checks = _land_checks(draft, drafted) if auto else []
        draft["intake"]["stage"] = "confirm"
        draft["phase"] = "prd"
        store.append_chat(draft, "asgard", _prd_note(written, len(checks), auto))

    return store.mutate(plan_id, change)


def _land_sections(draft: dict[str, Any], drafted: dict[str, Any], auto: bool) -> list[str]:
    """빈 칸만 채운다. 자동초안은 역할·환경을 추측으로 안 채운다 — 기능 명세서와 유저 플로우가
    그 값을 그대로 소비하므로 추측 하나가 뒤 문서 둘로 번진다."""
    written = []
    for section in store.PRD_SECTION_IDS:
        if draft["prd"]["sections"][section]["body"].strip():
            continue  # 손댄 칸은 사람의 것이다
        body = drafted["sections"].get(section, "")
        if body:
            draft["prd"]["sections"][section]["body"] = body
            written.append(section)
    attrs = draft["prd"]["attributes"]
    coverage = draft["intake"]["coverage"]
    for key in ("category", "roles", "environments"):
        if attrs[key] or not drafted["attributes"][key]:
            continue
        axis = _ATTRIBUTE_AXIS.get(key, "")
        if auto and axis and intake.state_of(coverage, axis) != "covered":
            intake.note_assumption(draft["intake"], axis)
            continue
        attrs[key] = drafted["attributes"][key]
    return written


# 뒤 문서가 그대로 읽는 두 칸과 그 근거 축(`planner._SPEC_SYS`·`draft_flow`). category 는
# 아무 문서도 기계적으로 읽지 않으므로 여기 없다.
_ATTRIBUTE_AXIS = {"roles": "role", "environments": "environment"}


def _land_assumptions(draft: dict[str, Any], drafted: dict[str, Any]) -> None:
    """근거 없이 채운 자리를 가정 목록으로 꺼낸다 — 본문 줄에 섞으면 세지도 확인하지도 못한다."""
    row = draft["intake"]
    for item in drafted["assumptions"]:
        intake.note_assumption(row, item["axis"], item["text"])
    for axis in intake.REQUIRED_AXES:
        if intake.state_of(row["coverage"], axis) in ("missing", "thin"):
            intake.mark(row["coverage"], axis, "assumed")
            intake.note_assumption(row, axis)


def _land_checks(draft: dict[str, Any], drafted: dict[str, Any]) -> list[dict[str, Any]]:
    """자동초안의 사후 확인 질문. 예·아니오 형태이고 최대 세 개다."""
    row = draft["intake"]
    left = intake.budget(row, "confirm")
    room = min(left["remaining"], left["stage_remaining"], 3)
    asked = {item["q"] for item in row["questions"]}
    added = []
    for item in drafted["checks"]:
        if len(added) >= room or item["q"] in asked:
            continue
        asked.add(item["q"])
        added.append(
            {
                "id": store.new_id("q"),
                "q": item["q"],
                "a": "",
                "axis": item["axis"],
                "kind": "check",
                "parent": "",
                "stage": "confirm",
                "state": "open",
            }
        )
    row["questions"].extend(added)
    return added


def _prd_note(written: list[str], checks: int, auto: bool) -> str:
    labels = {sid: label for sid, label, _ in store.PRD_SECTIONS}
    filled = ", ".join(labels[section] for section in written) or "없음"
    if not auto:
        return (
            f"PRD 초안을 만들었어요 — 채운 칸: {filled}.\n"
            "확신이 없는 줄에는 (확인 필요)를 달아 뒀어요. 한 칸씩 보면서 고쳐 주세요."
        )
    tail = f"\n제가 채운 자리를 {checks}가지만 확인할게요." if checks else ""
    return (
        f"질문 없이 PRD 초안을 먼저 썼어요 — 채운 칸: {filled}.\n"
        "답을 못 들어서 제가 채운 줄에는 표시를 달았고, 근거가 없는 자리는 가정 목록으로 꺼내 뒀어요."
        f"{tail}"
    )


def propose_section(plan_id: str, section: str, request: str, selection: str = "", root: str = "") -> dict[str, str]:
    """고칠 글을 돌려주기만 한다 — 반영은 사람이 누른다. 저장소는 건드리지 않는다."""
    plan = store.load_plan(plan_id)
    proposal = planner.refine_section(_model_root(plan, root), plan, section, request, selection)
    return {"section": section, "before": plan["prd"]["sections"][section]["body"], **proposal}


# 방향을 안 적고 누르는 사람이 기본이라 빈 요청을 그대로 모델에 보내지 않는다. 문서 전체
# 다듬기가 잡으라고 있는 두 가지를 여기 적는다 — 칸끼리 어긋난 말투와 근거 없는 단정.
_DOCUMENT_REQUEST = "칸끼리 말투와 논리 일관성을 맞추고, 근거 없이 단정한 곳은 열린 질문으로 바꿔 주세요"


def propose_document(plan_id: str, request: str = "", root: str = "") -> dict[str, Any]:
    """문서 전체 제안 — 칸마다 갈 글을 돌려주기만 한다. 저장소는 건드리지 않는다.

    돌려주는 값: `{"summary", "sections": [{"section", "label", "before", "body", "note"}]}`.
    `sections`에는 **고칠 것이 있는 칸만** 들어가고 순서는 문서 순서다(모델이 낸 순서가 아니다).
    비어 있으면 다듬을 것이 없었다는 뜻이다. `request`가 비면 기본 방향으로 돈다."""
    plan = store.load_plan(plan_id)
    proposal = planner.refine_document(_model_root(plan, root), plan, str(request or "").strip() or _DOCUMENT_REQUEST)
    labels = {sid: label for sid, label, _ in store.PRD_SECTIONS}
    rows = []
    for section in store.PRD_SECTION_IDS:
        item = proposal["sections"].get(section)
        if not item:
            continue
        rows.append(
            {
                "section": section,
                "label": labels[section],
                "before": plan["prd"]["sections"][section]["body"],
                "body": item["body"],
                "note": item["note"],
            }
        )
    return {"summary": proposal["summary"], "sections": rows}


def propose_selection(plan_id: str, section: str, request: str, selection: str, root: str = "") -> dict[str, Any]:
    """선택 구간 제안 — 그 구간의 대체 글만 돌려준다. 저장소는 건드리지 않는다.

    `start`/`end`는 `before` 안에서 고른 글을 찾은 자리다. 같은 글이 여러 번 나오면 **첫 자리**를
    쓴다 — 화면이 어느 자리를 갈지 알아야 반영이 엉뚱한 곳에 앉지 않는다. 고른 글이 `before`
    안에 없으면 `ValueError`이고, 그 판정은 모델을 부르기 전에 한다."""
    plan = store.load_plan(plan_id)
    if section not in store.PRD_SECTION_IDS:
        raise ValueError(f"unknown PRD section: {section}")
    before = plan["prd"]["sections"][section]["body"]
    start = before.find(selection) if selection else -1
    if start < 0:
        raise ValueError("selection is not in the section body")
    proposal = planner.refine_selection(_model_root(plan, root), plan, section, request, selection)
    return {
        "section": section,
        "selection": selection,
        **proposal,
        "before": before,
        "start": start,
        "end": start + len(selection),
    }


def draft_spec(plan_id: str, note: str = "", replace: bool = False, root: str = "") -> dict[str, Any]:
    """PRD → 기능 명세서. `replace`가 아니면 기존 항목 뒤에 이어 붙인다."""
    plan = store.load_plan(plan_id)
    items = planner.draft_spec(_model_root(plan, root), plan, note)

    def change(draft: dict[str, Any]) -> None:
        draft["spec"]["items"] = items if replace else [*draft["spec"]["items"], *items]
        if replace:
            # 항목이 통째로 갈렸으니, 옛 항목을 가리키던 노드의 출처는 더 이상 참이 아니다.
            live = {row["id"] for row in items}
            for node in draft["flow"]["nodes"]:
                if node["source"] not in live:
                    node["source"] = ""
        draft["phase"] = "spec"
        levels = {level: sum(1 for row in items if row["level"] == level) for level, _ in store.SPEC_LEVELS}
        store.append_chat(
            draft,
            "asgard",
            f"PRD에서 기능 명세서를 만들었어요 — "
            f"요구사항 {levels[1]}개 · 기능 {levels[2]}개 · 상세 기능 {levels[3]}개.\n"
            "항목마다 어느 PRD 칸에서 나왔는지 적어 뒀어요.",
        )

    return store.mutate(plan_id, change)


def draft_flow(plan_id: str, note: str = "", replace: bool = True, root: str = "") -> dict[str, Any]:
    """기능 명세서 → 유저 플로우. 그래프는 통째로 다시 그리는 것이 기본이다 —
    노드 반쪽만 새것이면 이어진 선이 무엇을 뜻하는지 아무도 모른다."""
    plan = store.load_plan(plan_id)
    flow = planner.draft_flow(_model_root(plan, root), plan, note)

    def change(draft: dict[str, Any]) -> None:
        if replace:
            draft["flow"] = flow
        else:
            draft["flow"]["sections"].extend(flow["sections"])
            draft["flow"]["nodes"].extend(flow["nodes"])
            draft["flow"]["edges"].extend(flow["edges"])
        draft["phase"] = "flow"
        store.append_chat(
            draft,
            "asgard",
            f"기능 명세서에서 유저 플로우를 그렸어요 — "
            f"구획 {len(flow['sections'])}개 · 노드 {len(flow['nodes'])}개 · 연결 {len(flow['edges'])}개.\n"
            "노드를 눌러 이름과 종류를 바꾸고, 두 노드를 골라 흐름을 이어 보세요.",
        )

    return store.mutate(plan_id, change)


def converse(plan_id: str, text: str, root: str = "") -> dict[str, Any]:
    """대화 한 턴 — 사람의 말을 먼저 남기고, 답을 받아 이어 붙인다.

    답이 실패해도 사람의 말은 남는다. 실패는 그대로 올리되 이미 쓴 것은 되돌리지 않는다:
    되돌리면 사용자는 자기가 방금 친 문장이 사라지는 것을 본다."""
    message = str(text or "").strip()
    if not message:
        raise ValueError("message is required")
    store.mutate(plan_id, lambda draft: store.append_chat(draft, "user", message))
    plan = store.load_plan(plan_id)
    answer = planner.reply(_model_root(plan, root), plan, message)
    return store.mutate(plan_id, lambda draft: store.append_chat(draft, "asgard", answer))
