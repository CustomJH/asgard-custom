"""손으로 고치는 자리 — 표면이 부를 수 있는 편집 연산의 전량.

화면마다 다른 경로를 내주면 계약이 화면 수만큼 생긴다. 그래서 문은 하나(`apply`)이고,
할 수 있는 일은 여기 적힌 표가 전부다. 표에 없는 연산은 존재하지 않는다 — 새 연산은
이름을 얻고 검사를 통과해야 들어온다.

모든 연산은 **초안을 제자리에서 고치는 함수**다. 검사·개정 번호·기록은 `store.mutate`가
한 잠금 안에서 진다. 그래서 여기서는 규칙만 쓴다: 무엇이 무엇의 자식인지, 무엇을 지우면
무엇이 같이 사라지는지.
"""

from __future__ import annotations

from typing import Any

from .. import errors
from . import intake, store


class UnknownOp(errors.InvalidInput, ValueError):
    """모르는 편집 연산 — 화면과 서버가 아는 연산 목록이 갈렸다는 뜻이다."""

    code = "unknown_edit"


# 건너뛴 질문이 대화에 남기는 답. 빈 답과 다르다 — 안 하기로 한 것이라 다시 안 묻는다.
SKIPPED_NOTE = "건너뛰었어요"


def apply(plan_id: str, op: str, payload: dict[str, Any]) -> dict[str, Any]:
    handler = _OPS.get(op)
    if handler is None:
        raise UnknownOp(f"unknown edit: {op}")
    return store.mutate(plan_id, lambda plan: handler(plan, payload))


def _title(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    title = " ".join(str(payload.get("title") or "").split())
    if not title:
        raise ValueError("title is required")
    plan["title"] = title[:200]


def _root(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    """이 기획이 가리키는 폴더를 걸거나 푼다 — 빈 값이면 푼다.

    **거는 것이지 옮기는 것이 아니다.** 기획은 워크스페이스에 그대로 있고, 이 값은 "이건
    저 저장소 얘기다"를 적어 둘 뿐이다. 그래서 폴더가 사라져도 기획은 안 사라진다."""
    plan["root"] = str(payload.get("root") or "")


def _phase(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    store.set_phase(plan, str(payload.get("phase") or ""))


def _section(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    section = str(payload.get("section") or "")
    if section not in store.PRD_SECTION_IDS:
        raise ValueError(f"unknown PRD section: {section}")
    plan["prd"]["sections"][section]["body"] = str(payload.get("body") or "")


def _sections(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    """PRD 여러 칸을 **한 개정에** 쓴다 — 문서 전체 다듬기의 제안을 받는 자리.

    칸마다 `section`을 따로 보내면 개정이 칸 수만큼 늘고, 중간에 하나가 막히면 절반만 반영된
    문서가 남는다. 모르는 sid 가 하나라도 있으면 한 칸도 안 쓴다."""
    incoming = payload.get("sections")
    if not isinstance(incoming, dict) or not incoming:
        raise ValueError("sections is required")
    unknown = sorted(sid for sid in incoming if sid not in store.PRD_SECTION_IDS)
    if unknown:
        raise ValueError(f"unknown PRD section: {', '.join(unknown)}")
    for sid, body in incoming.items():
        plan["prd"]["sections"][sid]["body"] = str(body or "")


def _attributes(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    attrs = plan["prd"]["attributes"]
    for key in ("category", "roles", "environments"):
        if key in payload:
            attrs[key] = payload[key]


def _answer(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    """온보딩 답 하나. 답이 들어오면 그 질문의 축을 `covered`로 옮긴다.

    답은 대화에도 남는다 — 문답이 대화 밖에 있으면 모델이 읽는 것과 사람이 보는 것이 갈린다.
    빈 답은 아무 상태도 안 바꾼다: 아직 안 한 것과 안 하기로 한 것은 다르고, 후자는
    `intake.skip`이 든다.

    확인 질문(`kind == "check"`)의 답은 축을 `covered`로 올리지 않는다. 예·아니오로 추측을
    맞다고 한 것은 근거가 아니라 확인된 가정이고, 올려 버리면 `grounded_sections`가 그 PRD
    칸을 근거 있는 칸으로 셈한다."""
    row = _question(plan, str(payload.get("question") or ""))
    text = str(payload.get("text") or "").strip()
    row["a"] = text
    if not text:
        return
    row["state"] = "answered"
    if row["kind"] == "check":
        _confirm_assumption(plan["intake"], row)
    else:
        intake.mark(plan["intake"]["coverage"], row["axis"], "covered", source=row["id"])
    _log_exchange(plan, row, text)


def _skip(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    """질문 하나를 건너뛴 것으로 표시한다 — 다시 안 묻는다.

    그 축은 `skipped`로 잠기고, 그 축에 대응하는 PRD 칸은 근거 없이 채운 자리라 가정 목록에
    오른다(`readiness().intake.grounded_sections`가 그 칸을 뺀다).

    건너뛴 것도 대화에 남는다. 답만 남기면 화면이 건너뛴 기록을 대화 밖에 따로 들고 있어야
    하고, 그 목록이 지금 물을 것 위에 계속 따라 붙는다."""
    row = _question(plan, str(payload.get("id") or payload.get("question") or ""))
    row["state"] = "skipped"
    if row["axis"]:
        intake.mark(plan["intake"]["coverage"], row["axis"], "skipped", source=row["id"])
        intake.note_assumption(plan["intake"], row["axis"])
    _log_exchange(plan, row, SKIPPED_NOTE)


def _log_exchange(plan: dict[str, Any], question: dict[str, Any], answer: str) -> None:
    """문답 한 쌍을 대화에 적는다 — 물은 쪽과 답한 쪽을 따로.

    여태는 `질문\\n→ 답` 한 줄로 묶어 적었다. 묶인 줄은 누가 말한 것으로도 못 세워서 화면이
    대화를 못 쓰고 문답 표를 따로 그렸고, 같은 답이 두 자리에 섰다. 나눠 적으면 대화 하나가
    정본이 된다 — 모델이 읽는 것과 사람이 보는 것이 같은 줄이다."""
    store.append_chat(plan, "asgard", question["q"])
    store.append_chat(plan, "user", answer)


def _question(plan: dict[str, Any], question_id: str) -> dict[str, Any]:
    for row in plan["intake"]["questions"]:
        if row["id"] == question_id:
            return row
    raise KeyError(question_id)


def _confirm_assumption(row: dict[str, Any], question: dict[str, Any]) -> None:
    """확인 질문에 답이 오면 그 축의 가정을 확인된 것으로 표시한다.

    `confirmed`는 사용자가 동의했다는 뜻이 아니라 **판정을 받았다**는 뜻이다. 아니라고 답한
    가정도 다시 묻지 않는다 — 그 뒤는 PRD 칸을 고치는 일이지 문답이 아니다."""
    for item in row["assumptions"]:
        if item["axis"] == question["axis"]:
            item["confirmed"] = True


def _questions(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    """되물을 것을 더한다 — 이미 답한 질문은 건드리지 않는다."""
    asked = {row["q"] for row in plan["intake"]["questions"]}
    for text in payload.get("questions") or []:
        line = " ".join(str(text or "").split())
        if line and line not in asked:
            asked.add(line)
            plan["intake"]["questions"].append({"id": store.new_id("q"), "q": line, "a": ""})


def _item_save(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    """기능 명세서 항목 하나 — 있으면 고치고 없으면 더한다."""
    incoming = payload.get("item")
    if not isinstance(incoming, dict):
        raise ValueError("item is required")
    items = plan["spec"]["items"]
    item_id = str(incoming.get("id") or "")
    for row in items:
        if row["id"] == item_id:
            row.update({k: v for k, v in incoming.items() if k in _ITEM_FIELDS})
            return
    level = incoming.get("level", 2)
    parent = str(incoming.get("parent") or "")
    row = {
        "id": store.new_id("i"),
        "level": level,
        "parent": parent,
        "title": incoming.get("title", ""),
        "desc": incoming.get("desc", ""),
        "criteria": incoming.get("criteria") or [],
        "role": incoming.get("role", ""),
        "priority": incoming.get("priority", "medium"),
        "status": incoming.get("status", "todo"),
        "source": incoming.get("source", ""),
    }
    # 부모 바로 뒤에 꽂는다 — 끝에 붙이면 트리 뷰에서 형제와 떨어져 나타난다.
    at = next((i + 1 for i, existing in enumerate(items) if existing["id"] == parent), len(items))
    items.insert(at, row)


_ITEM_FIELDS = frozenset({"level", "parent", "title", "desc", "criteria", "role", "priority", "status", "source"})


def _item_delete(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    """자식도 같이 사라진다 — 부모 없는 상세 기능은 저장소가 어차피 받지 않는다."""
    target = str(payload.get("id") or "")
    items = plan["spec"]["items"]
    doomed = {target}
    changed = True
    while changed:
        changed = False
        for row in items:
            if row["parent"] in doomed and row["id"] not in doomed:
                doomed.add(row["id"])
                changed = True
    plan["spec"]["items"] = [row for row in items if row["id"] not in doomed]
    # 그 기능을 실현하던 노드는 남되, 끊어진 출처는 지운다(가리키는 곳이 없는 링크는 거짓말이다).
    for node in plan["flow"]["nodes"]:
        if node.get("source") in doomed:
            node["source"] = ""


def _flow_section_save(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    incoming = payload.get("section")
    if not isinstance(incoming, dict):
        raise ValueError("section is required")
    sections = plan["flow"]["sections"]
    for row in sections:
        if row["id"] == str(incoming.get("id") or ""):
            row["title"] = incoming.get("title", row["title"])
            return
    sections.append({"id": store.new_id("s"), "title": incoming.get("title", "")})


def _flow_section_delete(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    """구획을 지워도 노드는 남는다 — 화면을 지우는 것이 아니라 묶음을 푸는 것이다."""
    target = str(payload.get("id") or "")
    plan["flow"]["sections"] = [row for row in plan["flow"]["sections"] if row["id"] != target]
    for node in plan["flow"]["nodes"]:
        if node["section"] == target:
            node["section"] = ""


def _node_save(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    incoming = payload.get("node")
    if not isinstance(incoming, dict):
        raise ValueError("node is required")
    nodes = plan["flow"]["nodes"]
    for row in nodes:
        if row["id"] == str(incoming.get("id") or ""):
            row.update({k: v for k, v in incoming.items() if k in _NODE_FIELDS})
            return
    nodes.append(
        {
            "id": store.new_id("n"),
            "type": incoming.get("type", "page"),
            "title": incoming.get("title", ""),
            "section": incoming.get("section", ""),
            "source": incoming.get("source", ""),
        }
    )


_NODE_FIELDS = frozenset({"type", "title", "section", "source"})


def _node_delete(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    """노드를 지우면 그 노드에 걸린 선도 함께 — 남기면 저장소가 '없는 노드'로 막는다."""
    target = str(payload.get("id") or "")
    plan["flow"]["nodes"] = [row for row in plan["flow"]["nodes"] if row["id"] != target]
    plan["flow"]["edges"] = [e for e in plan["flow"]["edges"] if target not in (e["from"], e["to"])]


def _edge_save(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    incoming = payload.get("edge")
    if not isinstance(incoming, dict):
        raise ValueError("edge is required")
    edges = plan["flow"]["edges"]
    for row in edges:
        if row["id"] == str(incoming.get("id") or ""):
            row["label"] = incoming.get("label", row["label"])
            return
    edges.append(
        {
            "id": store.new_id("e"),
            "from": incoming.get("from", ""),
            "to": incoming.get("to", ""),
            "label": incoming.get("label", ""),
        }
    )


def _edge_delete(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    target = str(payload.get("id") or "")
    plan["flow"]["edges"] = [row for row in plan["flow"]["edges"] if row["id"] != target]


def _chat(plan: dict[str, Any], payload: dict[str, Any]) -> None:
    store.append_chat(plan, str(payload.get("role") or "user"), str(payload.get("text") or ""))


_OPS = {
    "title": _title,
    "root": _root,
    "phase": _phase,
    "section": _section,
    "sections": _sections,
    "attributes": _attributes,
    "answer": _answer,
    # 계약이 부르는 이름과 여기 있던 이름이 갈린다 — 둘 다 같은 함수로 받는다. 화면이 어느
    # 쪽을 부르든 통해야 하고, 이름 하나 때문에 온보딩이 통째로 멈추는 것이 더 비싸다.
    "intake.answer": _answer,
    "intake.skip": _skip,
    "questions": _questions,
    "item.save": _item_save,
    "item.delete": _item_delete,
    "flow.section.save": _flow_section_save,
    "flow.section.delete": _flow_section_delete,
    "node.save": _node_save,
    "node.delete": _node_delete,
    "edge.save": _edge_save,
    "edge.delete": _edge_delete,
    "chat": _chat,
}

OPS = tuple(sorted(_OPS))
