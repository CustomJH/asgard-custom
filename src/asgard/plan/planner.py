"""기획 대화의 지능 — 한 줄에서 질문을, 답에서 PRD를, PRD에서 명세서를, 명세서에서 플로우를.

여기 있는 모든 호출은 **앞 문서를 입력으로 받는다**. 그것이 이 계층의 유일한 규칙이다:
기능 명세서는 PRD 를 읽고 만들고, 유저 플로우는 PRD 의 개요와 명세서의 기능을 읽고 만든다.
근거 없이 지어내는 것을 막는 장치도 여기 있다 — 프롬프트가 "모르면 열린 질문으로 남겨라"라고
말하고, 만들어진 항목은 어느 칸/어느 기능에서 왔는지(`source`)를 달고 나온다.

프롬프트는 영어다(모델이 더 빨리 읽는다). **내용**은 사용자의 언어로 쓰게 한다 — 화면에
그대로 실리는 글이라 여기서 언어가 갈리면 사람이 읽는 문서가 갈린다.

실패는 그대로 올린다. 무엇을 할지는 부르는 쪽 정책이다 — 화면은 초안을 못 받으면 손으로
쓰면 되고, 그것이 이 계층이 없어도 기획이 굴러가는 이유다.
"""

from __future__ import annotations

import json
from typing import Any

from . import store

_LANGUAGE = (
    "Write every user-facing string in the same language the user wrote their idea and answers in "
    "(Korean input means Korean output). Keep it plain and concrete; no marketing tone, no emoji."
)
_HONESTY = (
    "Never invent facts, numbers, company names, or research findings. "
    "If something is genuinely unknown, say so in an open question instead of filling it in."
)
_JSON_ONLY = "Reply with STRICT JSON only. No prose, no markdown, no code fences."

_ASK_SYS = (
    "You are a product planning partner running an intake interview. The user gave you one line "
    "about what they want to build. Ask the fewest questions that would change the shape of the "
    "product if answered differently.\n"
    "Rules:\n"
    "- 3 to 5 questions, ordered by how much they unblock.\n"
    "- One question per item, answerable in a sentence or two. No compound questions.\n"
    "- Cover, at most once each: who it is for, the problem it replaces, what success looks like, "
    "scope boundary, environment/platform.\n"
    "- Never ask something the idea already answers.\n"
    f"{_LANGUAGE}\n{_HONESTY}\n"
    f'{_JSON_ONLY} Shape: {{"questions": ["...", "..."]}}'
)

_PRD_SYS = (
    "You are a product planning partner writing the first PRD draft from an intake interview.\n"
    "Fill five sections. Each body is plain text, 2 to 6 short lines, one idea per line, "
    "written as '- ' bullets. Ground every line in what the user actually said.\n"
    "Sections:\n"
    "- overview: one-line definition, product goals, why now.\n"
    "- value: the user's problem, how this solves it, what makes it different.\n"
    "- target: the core user groups and a concrete usage scenario.\n"
    "- success: how success is measured, the main risks, and what is still undecided.\n"
    "- attributes: leave the body short; the structured fields carry the meaning.\n"
    "Also fill attributes: category (a few words), roles (the user roles this product has), "
    "environments (web, iOS, Android, desktop, CLI, ...). Roles are consumed verbatim by the "
    "feature spec, so name them the way the team would say them.\n"
    "Mark anything you had to guess by ending that line with ' (확인 필요)'.\n"
    f"{_LANGUAGE}\n{_HONESTY}\n"
    f'{_JSON_ONLY} Shape: {{"sections": {{"overview": "...", "value": "...", "target": "...", '
    '"success": "...", "attributes": "..."}, "attributes": {"category": "...", '
    '"roles": ["..."], "environments": ["..."]}}'
)

_REFINE_SYS = (
    "You are editing ONE section of an existing PRD. Return the full replacement body for that "
    "section only — not a diff, not the whole document.\n"
    "Keep the existing structure and every decision the user already made unless the request "
    "explicitly changes it. Plain text, '- ' bullets, 2 to 8 short lines.\n"
    f"{_LANGUAGE}\n{_HONESTY}\n"
    f'{_JSON_ONLY} Shape: {{"body": "...", "note": "one short line on what you changed"}}'
)

_SPEC_SYS = (
    "You are turning an approved PRD into a feature specification. The PRD says what and why; "
    "this document says how it behaves.\n"
    "Build three levels:\n"
    "- level 1 요구사항: a user need taken from the PRD. 3 to 6 of them.\n"
    "- level 2 기능: a concrete capability that satisfies its parent requirement. 1 to 4 per parent.\n"
    "- level 3 상세 기능: the actual operations of its parent feature. 0 to 5 per feature.\n"
    "Every item carries: title, desc (one or two lines), criteria (what must be true for it to be "
    "done — phrase each as a checkable statement), role (pick from the PRD roles, or empty), "
    "priority (low|medium|high), source (which PRD section it came from: overview|value|target|"
    "success|attributes).\n"
    "Do not invent features the PRD does not imply. If the PRD is thin somewhere, produce fewer "
    "items rather than filler.\n"
    f"{_LANGUAGE}\n{_HONESTY}\n"
    f'{_JSON_ONLY} Shape: {{"items": [{{"key": "r1", "level": 1, "parent": "", "title": "...", '
    '"desc": "...", "criteria": ["..."], "role": "", "priority": "medium", "source": "overview"}]}. '
    "Use your own short keys and reference parents by key."
)

_FLOW_SYS = (
    "You are turning a feature specification into a user flow graph: the paths a user takes "
    "through the product.\n"
    "Produce sections (one per top-level area of the product), nodes, and edges.\n"
    "Node types: start (exactly one, where a first-time user enters), section (the top page that "
    "represents a section), page (a screen), action (something the user does — a click, an input, "
    "a submit).\n"
    "Every page and action node should name the feature key it realizes in `source`. Cover the "
    "normal path first, then the branches the features imply (empty, error, permission, return).\n"
    "Keep it readable: 8 to 24 nodes. Every node except start must be reachable by some edge.\n"
    f"{_LANGUAGE}\n{_HONESTY}\n"
    f'{_JSON_ONLY} Shape: {{"sections": [{{"key": "s1", "title": "..."}}], '
    '"nodes": [{"key": "n1", "type": "start", "title": "...", "section": "s1", "source": ""}], '
    '"edges": [{"from": "n1", "to": "n2", "label": ""}]}'
)

_REPLY_SYS = (
    "You are a product planning partner in an ongoing conversation about one product. You are "
    "helping the user think, not writing code and not editing files.\n"
    "Answer the user's message directly in at most 6 short lines. If they are drifting past what "
    "the current document decides, say which document the point belongs to and offer to take it "
    "there. If a decision is missing, ask for exactly one thing.\n"
    f"{_LANGUAGE}\n{_HONESTY}\n"
    "Reply with plain text only — no JSON, no markdown headings, no code fences."
)


def ask_questions(root: str, plan: dict[str, Any]) -> list[str]:
    """온보딩 — 한 줄에서 되물을 것을 뽑는다. 이미 물은 것은 다시 묻지 않는다."""
    asked = [row["q"] for row in plan["intake"]["questions"]]
    user = json.dumps(
        {"idea": plan["intake"]["idea"], "already_asked": asked, "conversation": _recent_chat(plan)},
        ensure_ascii=False,
    )
    payload = _json_call(root, _ASK_SYS, user, max_tokens=1200)
    questions = payload.get("questions")
    if not isinstance(questions, list):
        raise ValueError("planner returned no questions")
    out = []
    for text in questions:
        line = " ".join(str(text or "").split())
        if line and line not in asked and line not in out:
            out.append(line[:600])
    return out[:5]


def draft_prd(root: str, plan: dict[str, Any]) -> dict[str, Any]:
    """온보딩의 답을 PRD 다섯 칸으로. 답이 비어도 만든다 — 대신 추측한 줄에 표를 단다."""
    user = json.dumps(
        {
            "idea": plan["intake"]["idea"],
            "interview": [{"q": row["q"], "a": row["a"]} for row in plan["intake"]["questions"] if row["a"].strip()],
            "conversation": _recent_chat(plan),
            "existing_sections": {sid: plan["prd"]["sections"][sid]["body"] for sid in store.PRD_SECTION_IDS},
        },
        ensure_ascii=False,
    )
    payload = _json_call(root, _PRD_SYS, user, max_tokens=3000)
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        raise ValueError("planner returned no PRD sections")
    bodies = {sid: _text(sections.get(sid)) for sid in store.PRD_SECTION_IDS}
    if not bodies["overview"]:
        raise ValueError("planner returned an empty overview")
    raw_attrs = payload.get("attributes")
    attrs: dict[str, Any] = raw_attrs if isinstance(raw_attrs, dict) else {}
    return {
        "sections": bodies,
        "attributes": {
            "category": " ".join(str(attrs.get("category") or "").split())[:200],
            "roles": _labels(attrs.get("roles")),
            "environments": _labels(attrs.get("environments")),
        },
    }


def refine_section(root: str, plan: dict[str, Any], section: str, request: str, selection: str = "") -> dict[str, str]:
    """한 칸만 고쳐 돌려준다 — 문서 전체를 다시 쓰면 확정한 결정이 조용히 지워진다."""
    if section not in store.PRD_SECTION_IDS:
        raise ValueError(f"unknown PRD section: {section}")
    user = json.dumps(
        {
            "section": section,
            "section_label": dict((s, label) for s, label, _ in store.PRD_SECTIONS)[section],
            "current_body": plan["prd"]["sections"][section]["body"],
            "selected_text": selection[:2000],
            "request": request,
            "other_sections": {
                sid: plan["prd"]["sections"][sid]["body"] for sid in store.PRD_SECTION_IDS if sid != section
            },
            "attributes": plan["prd"]["attributes"],
        },
        ensure_ascii=False,
    )
    payload = _json_call(root, _REFINE_SYS, user, max_tokens=2000)
    body = _text(payload.get("body"))
    if not body:
        raise ValueError("planner returned an empty section")
    return {"body": body, "note": " ".join(str(payload.get("note") or "").split())[:300]}


def draft_spec(root: str, plan: dict[str, Any], note: str = "") -> list[dict[str, Any]]:
    """PRD → 기능 명세서. 저장소가 그대로 받을 수 있는 평평한 항목 목록으로 돌려준다."""
    store.require_ready(plan, "spec")
    user = json.dumps(
        {
            "prd": {sid: plan["prd"]["sections"][sid]["body"] for sid in store.PRD_SECTION_IDS},
            "attributes": plan["prd"]["attributes"],
            "emphasis": note,
            "existing_items": [{"title": row["title"], "level": row["level"]} for row in plan["spec"]["items"][:60]],
        },
        ensure_ascii=False,
    )
    payload = _json_call(root, _SPEC_SYS, user, max_tokens=6000)
    rows = payload.get("items")
    if not isinstance(rows, list) or not rows:
        raise ValueError("planner returned no spec items")
    return _materialize_items(rows, plan["prd"]["attributes"]["roles"])


def draft_flow(root: str, plan: dict[str, Any], note: str = "") -> dict[str, Any]:
    """기능 명세서 → 유저 플로우. 노드는 자기가 실현하는 기능을 들고 나온다."""
    store.require_ready(plan, "flow")
    features = [row for row in plan["spec"]["items"] if row["level"] in (2, 3)]
    user = json.dumps(
        {
            "overview": plan["prd"]["sections"]["overview"]["body"],
            "target": plan["prd"]["sections"]["target"]["body"],
            "roles": plan["prd"]["attributes"]["roles"],
            "environments": plan["prd"]["attributes"]["environments"],
            "emphasis": note,
            "features": [
                {"key": row["id"], "level": row["level"], "title": row["title"], "desc": row["desc"]}
                for row in features[:80]
            ],
        },
        ensure_ascii=False,
    )
    payload = _json_call(root, _FLOW_SYS, user, max_tokens=6000)
    return _materialize_flow(payload, {row["id"] for row in features})


def reply(root: str, plan: dict[str, Any], message: str) -> str:
    """자유 대화 한 턴 — 문서를 고치지 않는다. 고칠 것이 있으면 어느 문서인지를 말한다."""
    ready = store.readiness(plan)
    user = json.dumps(
        {
            "phase": plan["phase"],
            "title": plan["title"],
            "idea": plan["intake"]["idea"],
            "progress": {
                "prd_filled": ready["prd"]["filled"],
                "features": ready["spec"]["features"],
                "flow_nodes": ready["flow"]["nodes"],
            },
            "prd": {sid: plan["prd"]["sections"][sid]["body"] for sid in store.PRD_SECTION_IDS},
            "features": [row["title"] for row in plan["spec"]["items"] if row["level"] == 2][:30],
            "conversation": _recent_chat(plan),
            "message": message,
        },
        ensure_ascii=False,
    )
    from ..agent.oneshot import complete_once

    text = complete_once(root, _REPLY_SYS, user, max_tokens=1200).strip()
    if not text:
        raise ValueError("planner returned an empty reply")
    return text[:4000]


# --- 옮겨 담기 ---------------------------------------------------------------


def _materialize_items(rows: list[Any], roles: list[str]) -> list[dict[str, Any]]:
    """모델의 임시 key 를 저장소 id 로 바꾸고, 부모를 못 찾은 항목은 버린다.

    두 번 도는 이유는 부모가 뒤에 올 수 있기 때문이다 — 먼저 id 를 전부 발급하고,
    그다음에 잇는다. 층과 부모가 어긋나면(3층인데 부모가 없거나 1층인데 부모가 있으면)
    저장소가 어차피 막으므로 여기서 조용히 떨어뜨린다."""
    known_roles = {role.casefold(): role for role in roles}
    ids: dict[str, str] = {}
    staged = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        level = row.get("level")
        title = " ".join(str(row.get("title") or "").split())
        key = str(row.get("key") or "")
        if level not in (1, 2, 3) or not title or not key or key in ids:
            continue
        ids[key] = store.new_id("i")
        staged.append((key, row, level, title))

    out = []
    for key, row, level, title in staged:
        parent_key = str(row.get("parent") or "")
        parent = ids.get(parent_key, "")
        if (level == 1) != (not parent):
            continue
        role = " ".join(str(row.get("role") or "").split())
        priority = row.get("priority") if row.get("priority") in store.PRIORITIES else "medium"
        source = row.get("source") if row.get("source") in store.PRD_SECTION_IDS else ""
        out.append(
            {
                "id": ids[key],
                "level": level,
                "parent": parent,
                "title": title[:400],
                "desc": _text(row.get("desc"))[:8000],
                "criteria": [" ".join(str(c).split())[:600] for c in (row.get("criteria") or []) if str(c).strip()][
                    :30
                ],
                "role": known_roles.get(role.casefold(), role)[:200],
                "priority": priority,
                "status": "todo",
                "source": source,
            }
        )
    if not out:
        raise ValueError("planner returned no usable spec items")
    return out[:300]


def _materialize_flow(payload: dict[str, Any], feature_ids: set[str]) -> dict[str, Any]:
    """구획·노드·연결선을 저장소 id 로 옮긴다. 없는 노드를 가리키는 선은 버린다."""
    section_ids: dict[str, str] = {}
    sections = []
    for row in payload.get("sections") or []:
        if not isinstance(row, dict):
            continue
        key, title = str(row.get("key") or ""), " ".join(str(row.get("title") or "").split())
        if not key or not title or key in section_ids:
            continue
        section_ids[key] = store.new_id("s")
        sections.append({"id": section_ids[key], "title": title[:200]})

    node_ids: dict[str, str] = {}
    nodes = []
    seen_start = False
    for row in payload.get("nodes") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "")
        ntype = row.get("type") if row.get("type") in store.NODE_TYPES else "page"
        title = " ".join(str(row.get("title") or "").split())
        if not key or not title or key in node_ids:
            continue
        if ntype == "start":
            if seen_start:
                ntype = "page"
            seen_start = True
        source = str(row.get("source") or "")
        node_ids[key] = store.new_id("n")
        nodes.append(
            {
                "id": node_ids[key],
                "type": ntype,
                "title": title[:200],
                "section": section_ids.get(str(row.get("section") or ""), ""),
                "source": source if source in feature_ids else "",
            }
        )
    if not nodes:
        raise ValueError("planner returned no flow nodes")

    edges, pairs = [], set()
    for row in payload.get("edges") or []:
        if not isinstance(row, dict):
            continue
        head, tail = node_ids.get(str(row.get("from") or "")), node_ids.get(str(row.get("to") or ""))
        if not head or not tail or head == tail or (head, tail) in pairs:
            continue
        pairs.add((head, tail))
        edges.append(
            {
                "id": store.new_id("e"),
                "from": head,
                "to": tail,
                "label": " ".join(str(row.get("label") or "").split())[:200],
            }
        )
    return {"sections": sections, "nodes": nodes[:200], "edges": edges[:400]}


# --- 호출 --------------------------------------------------------------------


def _json_call(root: str, system: str, user: str, max_tokens: int) -> dict[str, Any]:
    from ..agent.oneshot import complete_once

    raw = complete_once(root, system, user, max_tokens=max_tokens)
    return _parse(raw)


def _parse(raw: str) -> dict[str, Any]:
    """울타리를 쳐서 돌려주는 모델이 있다 — 가장 바깥 중괄호 쌍만 본다."""
    text = str(raw or "")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("planner output is not JSON")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("planner output is not a JSON object")
    return payload


def _recent_chat(plan: dict[str, Any], limit: int = 20) -> list[dict[str, str]]:
    return [{"role": turn["role"], "text": turn["text"][:1200]} for turn in plan.get("chat", [])[-limit:]]


def _text(value: Any) -> str:
    if isinstance(value, list):
        value = "\n".join(str(item) for item in value)
    lines = [line.rstrip() for line in str(value or "").replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()[:8000]


def _labels(value: Any) -> list[str]:
    out: list[str] = []
    for item in value or []:
        label = " ".join(str(item or "").split())[:200]
        if label and label not in out:
            out.append(label)
    return out[:20]
