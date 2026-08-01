"""지능이 만든 것을 문서에 앉히는 자리 — `planner`(짓기)와 `store`(담기) 사이.

여기서 갈리는 것이 하나 있다: **초안은 앉히고, 수정은 제안한다.**

빈 문서에 첫 초안을 넣는 것은 아무것도 지우지 않으므로 바로 쓴다. 반대로 이미 사람이
손댄 칸을 모델이 다시 쓰는 것은 되돌릴 수 없는 일이라, 그때는 글만 돌려주고 반영은
사람이 누른다(`propose_section`). "AI가 내 문장을 조용히 갈아치웠다"가 이 기획 화면에서
가장 비싼 실패다.

대화 한 턴도 여기 있다. 사용자의 말과 답을 **같은 왕복 안에서** 기록에 남기기 때문이다 —
따로 쓰면 답이 오는 사이에 창을 닫은 사람의 질문이 사라진다.
"""

from __future__ import annotations

import os
from typing import Any

from . import planner, store


def _model_root(plan: dict[str, Any], root: str = "") -> str:
    """모델을 부를 때 **설정을 읽을** 자리. 기획이 있는 자리가 아니다.

    기획 자체는 폴더에 매이지 않는다(워크스페이스 하나). 다만 provider·모델 설정은 여전히
    자리에서 읽으므로, 이 기획이 가리키는 폴더가 있으면 그 폴더의 설정을 존중하고 없으면
    부른 쪽이 준 자리를, 그것도 없으면 지금 서 있는 자리를 쓴다."""
    return plan.get("root") or root or os.getcwd()


def ask(plan_id: str, root: str = "") -> dict[str, Any]:
    """온보딩 — 되물을 것을 뽑아 문답표에 얹는다."""
    plan = store.load_plan(plan_id)
    questions = planner.ask_questions(_model_root(plan, root), plan)
    if not questions:
        return plan

    def change(draft: dict[str, Any]) -> None:
        asked = {row["q"] for row in draft["intake"]["questions"]}
        for text in questions:
            if text not in asked:
                asked.add(text)
                draft["intake"]["questions"].append({"id": store.new_id("q"), "q": text, "a": ""})
        store.append_chat(draft, "asgard", "먼저 몇 가지만 여쭤볼게요. 아는 것만 답해 주셔도 됩니다.")

    return store.mutate(plan_id, change)


def draft_prd(plan_id: str, root: str = "") -> dict[str, Any]:
    """문답에서 PRD 초안으로. 사람이 이미 쓴 칸은 덮지 않는다."""
    plan = store.load_plan(plan_id)
    drafted = planner.draft_prd(_model_root(plan, root), plan)

    def change(draft: dict[str, Any]) -> None:
        written = []
        for section in store.PRD_SECTION_IDS:
            if draft["prd"]["sections"][section]["body"].strip():
                continue  # 손댄 칸은 사람의 것이다
            body = drafted["sections"].get(section, "")
            if body:
                draft["prd"]["sections"][section]["body"] = body
                written.append(section)
        attrs = draft["prd"]["attributes"]
        for key in ("category", "roles", "environments"):
            if not attrs[key] and drafted["attributes"][key]:
                attrs[key] = drafted["attributes"][key]
        draft["phase"] = "prd"
        labels = {sid: label for sid, label, _ in store.PRD_SECTIONS}
        filled = ", ".join(labels[s] for s in written) or "없음"
        store.append_chat(
            draft,
            "asgard",
            f"PRD 초안을 올렸습니다 — 채운 칸: {filled}.\n"
            "확신이 없는 줄에는 (확인 필요)를 달아 두었습니다. 한 칸씩 보면서 고쳐 주세요.",
        )

    return store.mutate(plan_id, change)


def propose_section(plan_id: str, section: str, request: str, selection: str = "", root: str = "") -> dict[str, str]:
    """고칠 글을 돌려주기만 한다 — 반영은 사람이 누른다. 저장소는 건드리지 않는다."""
    plan = store.load_plan(plan_id)
    proposal = planner.refine_section(_model_root(plan, root), plan, section, request, selection)
    return {"section": section, "before": plan["prd"]["sections"][section]["body"], **proposal}


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
            f"PRD를 기반으로 기능 명세서를 만들었습니다 — "
            f"요구사항 {levels[1]} · 기능 {levels[2]} · 상세 기능 {levels[3]}.\n"
            "각 항목은 어느 PRD 칸에서 나왔는지를 달고 있습니다.",
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
            f"기능 명세서를 기반으로 유저 플로우를 그렸습니다 — "
            f"구획 {len(flow['sections'])} · 노드 {len(flow['nodes'])} · 연결 {len(flow['edges'])}.\n"
            "노드를 눌러 이름과 종류를 바꾸고, 두 노드를 골라 흐름을 이을 수 있습니다.",
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
