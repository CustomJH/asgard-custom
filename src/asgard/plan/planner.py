"""기획 대화의 지능 — 한 줄에서 질문을, 답에서 PRD를, PRD에서 명세서를, 명세서에서 플로우를.

여기 있는 모든 호출은 **앞 문서를 입력으로 받는다**. 그것이 이 계층의 유일한 규칙이다:
기능 명세서는 PRD를 읽고 만들고, 유저 플로우는 PRD의 개요와 명세서의 기능을 읽고 만든다.
근거 없이 지어내는 것을 막는 장치도 여기 있다 — 프롬프트가 "모르면 열린 질문으로 남겨라"라고
말하고, 만들어진 항목은 어느 칸/어느 기능에서 왔는지(`source`)를 달고 나온다.

프롬프트는 영어다(모델이 더 빨리 읽는다). **내용**은 사용자의 언어로 쓰게 한다 — 화면에
그대로 들어가는 글이라 여기서 언어가 갈리면 사람이 읽는 문서가 갈린다.

실패는 그대로 올린다. 무엇을 할지는 부르는 쪽 정책이다 — 화면은 초안을 못 받으면 손으로
쓰면 되고, 그것이 이 계층이 없어도 기획이 굴러가는 이유다.
"""

from __future__ import annotations

import json
from typing import Any

from . import intake, store

_LANGUAGE = (
    "Write every user-facing string in the same language the user wrote their idea and answers in "
    "(Korean input means Korean output). Keep it plain and concrete; no marketing tone, no emoji.\n"
    # 언어만 정하고 문체를 안 정하면 모델은 합쇼체로 떨어진다 — 이 저장소의 사용자 표면은
    # 해요체가 정본이라, 되묻기 질문만 "무엇이 문제입니까"로 서면 화면 안에서 문체가 갈린다.
    "When writing Korean, use the 해요체 register (…해요 / …예요 / …까요). "
    "Never use 합쇼체 (…습니다 / …입니까) or 해라체 (…한다 / …인가)."
)
_HONESTY = (
    "Never invent facts, numbers, company names, or research findings. "
    "If something is genuinely unknown, say so in an open question instead of filling it in."
)
_JSON_ONLY = "Reply with STRICT JSON only. No prose, no markdown, no code fences."

_SECTION_LABEL = {section: label for section, label, _ in store.PRD_SECTIONS}

_ASK_SYS = (
    "You are a product planning partner running ONE stage of an intake interview. The user gave "
    "one line about what they want to build; earlier stages may have added answers.\n"
    "You are given: the current stage, the coverage axes that belong to it, every question asked "
    "so far with its answer, and the remaining question budget.\n"
    "Do two things.\n"
    "1. ASSESS every axis of this stage against the answers already given:\n"
    "   - covered: an answer states it concretely — a real situation, a named thing, a time.\n"
    "   - thin: an answer touches it but stays generic, hypothetical, or opinion ('usually', "
    "'I would', 'people want').\n"
    "   - missing: nothing said so far addresses it.\n"
    "   - skipped: the user was already asked and declined or left it empty.\n"
    "2. ASK questions only for axes assessed thin or missing.\n"
    "Rules:\n"
    "- At most 3 questions, at most 1 per axis, never more than the remaining budget. "
    "Ask nothing if every axis is covered or skipped.\n"
    "- One question per item, answerable in a sentence or two. No compound questions.\n"
    "- For a missing axis, ask an open question.\n"
    "- For a thin axis, ask a follow_up that requests one concrete instance from the past "
    "('the last time this happened', 'how do you do it today') — never a hypothetical, never an "
    "opinion about the future. Put the id of the answer you are following up on in `target`.\n"
    "- Never re-ask an axis the user skipped. Never ask what the idea or an existing answer "
    "already states. Never repeat a question already asked.\n"
    "- Ask nothing outside the axes you were given. If an answer opened a fact that belongs to a "
    "different axis, name that axis in `opened_axes` — do not ask about it here.\n"
    "- Every question names the axis it serves; a question that serves no axis is not asked.\n"
    "- Set stage_done true when every axis of this stage is covered or skipped.\n"
    f"{_LANGUAGE}\n{_HONESTY}\n"
    f'{_JSON_ONLY} Shape: {{"assessment": [{{"axis": "problem", '
    '"state": "covered|thin|missing|skipped"}], '
    '"questions": [{"axis": "problem", "kind": "open|follow_up", "target": "", "q": "..."}], '
    '"opened_axes": ["..."], "stage_done": false}'
)

# 확인 단계는 축 목록이 비어 있고 가정 목록이 대신 들어온다. 열린 질문을 던지면 이미 있는
# 초안을 사용자가 처음부터 다시 읽어야 하므로 예·아니오 형태만 받는다.
_CONFIRM_RULE = (
    "\nIn the confirm stage, ask only yes/no validation questions about the listed assumptions, "
    'at most 3, and never open a new axis. Use kind "check" for those questions.'
)

_PRD_BASE = (
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
)
_PRD_SHAPE = (
    '"sections": {"overview": "...", "value": "...", "target": "...", '
    '"success": "...", "attributes": "..."}, "attributes": {"category": "...", '
    '"roles": ["..."], "environments": ["..."]}'
)

_PRD_SYS = (
    _PRD_BASE + "Mark anything you had to guess by ending that line with ' (확인 필요)'.\n"
    f"{_LANGUAGE}\n{_HONESTY}\n"
    f"{_JSON_ONLY} Shape: {{{_PRD_SHAPE}}}"
)

# 자동초안 갈래의 프롬프트. 표기를 1인칭으로 바꾸는 근거는 Kim 등(FAccT 2024, n=404)이다 —
# 모델이 1인칭으로 불확실성을 말했을 때 과의존이 줄고 정답률이 올랐고, 비인칭 표현은 같은
# 방향이지만 유의하지 않았다. 역할·환경을 비워 두는 이유는 기능 명세서와 유저 플로우가 그
# 값을 그대로 소비하기 때문이다: 추측 하나가 뒤 문서 둘로 번진다.
_PRD_AUTO_SYS = (
    _PRD_BASE + "The user chose to skip the interview, so most of this draft is your inference.\n"
    "- End every line you had to guess with ' (확인 필요 — 답을 못 들어서 제가 채웠어요)'. "
    "Do not put that marker on lines the idea actually states.\n"
    "- Leave roles and environments as empty lists unless the idea itself names them.\n"
    "- Put every inference in `assumptions` as its own row, one line each, naming the axis it "
    "belongs to. Do not bury an assumption inside a section body — it cannot be checked there.\n"
    "- Write at most 3 `checks`: yes/no validation questions, each about one axis you had to "
    "guess. They must be answerable with 예 or 아니오 without rereading the draft.\n"
    f"{_LANGUAGE}\n{_HONESTY}\n"
    f"{_JSON_ONLY} Shape: {{{_PRD_SHAPE}, "
    '"assumptions": [{"axis": "user", "text": "..."}], '
    '"checks": [{"axis": "user", "q": "..."}]}'
)

_REFINE_SYS = (
    "You are editing ONE section of an existing PRD. Return the full replacement body for that "
    "section only — not a diff, not the whole document.\n"
    "Keep the existing structure and every decision the user already made unless the request "
    "explicitly changes it. Plain text, '- ' bullets, 2 to 8 short lines.\n"
    f"{_LANGUAGE}\n{_HONESTY}\n"
    f'{_JSON_ONLY} Shape: {{"body": "...", "note": "one short line on what you changed"}}'
)

# 칸 하나가 아니라 다섯 칸을 한 번에 읽는 갈래. 칸별 다듬기로는 못 잡는 것 — 한 칸이 주장하고
# 다른 칸이 뒤집는 자리, 같은 말이 칸마다 다른 뜻으로 쓰인 자리 — 이 여기서 걸린다.
# 안 고친 칸을 빼게 하는 근거는 화면이다: 본문이 그대로인 카드가 같이 뜨면 무엇을 봐야 하는지
# 사람이 못 가린다.
_DOCUMENT_SYS = (
    "You are editing an existing PRD as one document. You are given all five sections at once.\n"
    "Read them together and fix what only shows across sections: a claim one section makes and "
    "another contradicts, a term used with two meanings, a section written in a different register, "
    "a stated fact that no other section supports.\n"
    "Rules:\n"
    "- Return a replacement body only for a section you actually change. Omit every section you "
    "leave alone; never return an empty body and never return a body identical to the one given.\n"
    "- Keep every decision the user already made — numbers, names, roles, scope, and anything the "
    "interview answers state. You may reword a decision; you may not drop it.\n"
    "- Keep the existing shape: plain text, '- ' bullets, 2 to 8 short lines per section.\n"
    "- Keep the ' (확인 필요' markers already in the text unless the request resolves them.\n"
    "- `note` is one short line on what changed in that section; `summary` is one line on the "
    "document as a whole.\n"
    f"{_LANGUAGE}\n{_HONESTY}\n"
    f'{_JSON_ONLY} Shape: {{"sections": {{"overview": {{"body": "...", "note": "..."}}}}, '
    '"summary": "..."}'
)

# 앞뒤 문맥은 프롬프트에 넣되 돌려받지 않는다. 문맥이 없으면 대체 글이 앞뒤와 안 이어지고,
# 문맥까지 돌려받으면 사람이 안 고른 자리가 같이 갈린다. 3배 상한은 "구간 수정"이 사실상 칸
# 다시 쓰기로 번지는 것을 막는 자리다.
_SELECTION_SYS = (
    "You are editing ONE selected passage inside one PRD section. Return the replacement for that "
    "passage only — not the section, not the document.\n"
    "You are given the text before the passage and the text after it. That is context: it tells you "
    "what the replacement has to sit between. Never repeat it in your answer.\n"
    "Rules:\n"
    "- The caller splices your text back in at exactly that spot, so it must read continuously with "
    "the text before and after it.\n"
    "- Stay under `max_chars`, which is three times the length of the passage. A one-line passage "
    "comes back as one or two lines, never as a rewritten section.\n"
    "- Keep the passage's shape: a '- ' bullet comes back as a '- ' bullet; a fragment inside a "
    "line comes back as a fragment, with no bullet and no added line break.\n"
    "- Keep every decision the passage already states unless the request changes it.\n"
    f"{_LANGUAGE}\n{_HONESTY}\n"
    f'{_JSON_ONLY} Shape: {{"replacement": "...", "note": "one short line on what you changed"}}'
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


def ask_questions(root: str, plan: dict[str, Any], stage: str) -> dict[str, Any]:
    """한 단계의 판정과 질문을 받아 온다 — 축은 코드가 주고 모델은 그중에서만 고른다.

    돌려주는 값: `assessment`(축, 상태 쌍), `questions`(axis·kind·parent·q), `opened_axes`,
    `stage_done`. 상한을 세는 것은 부르는 쪽(`build`)이다 — 여기서는 표 밖의 값만 버린다."""
    row = plan["intake"]
    required, optional = intake.stage_axes(stage)
    payload = {
        "stage": stage,
        "stage_label": intake.STAGE_LABEL.get(stage, stage),
        "axes": [
            {
                "id": axis,
                "label": intake.AXIS_LABEL[axis],
                "prd_section": intake.AXIS_SECTION[axis],
                "required": axis in required,
                "state": intake.state_of(row["coverage"], axis),
            }
            for axis in (*required, *optional)
        ],
        "idea": row["idea"],
        "answers": [
            {"id": q["id"], "axis": q["axis"], "q": q["q"], "a": q["a"], "state": q["state"]} for q in row["questions"]
        ],
        "assumptions": [
            {"axis": item["axis"], "text": item["text"]} for item in row["assumptions"] if not item["confirmed"]
        ],
        "budget": intake.budget(row, stage),
        "conversation": _recent_chat(plan),
    }
    system = _ASK_SYS + (_CONFIRM_RULE if stage == "confirm" else "")
    data = _json_call(root, system, json.dumps(payload, ensure_ascii=False), 1500, plan.get("engine"))
    return _read_round(data, row, stage)


def _read_round(payload: dict[str, Any], row: dict[str, Any], stage: str) -> dict[str, Any]:
    """모델이 낸 한 라운드를 표 안의 값으로만 추린다 — 모르는 축·종류·원 질문은 버린다."""
    required, optional = intake.stage_axes(stage)
    here = set(required) | set(optional)
    known = {item["id"] for item in row["questions"]}
    assessment = []
    for item in payload.get("assessment") or []:
        if isinstance(item, dict) and item.get("axis") in here and item.get("state") in intake.AXIS_STATES:
            assessment.append((item["axis"], item["state"]))
    questions = []
    for item in payload.get("questions") or []:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("q") or "").split())[:600]
        axis = item.get("axis") if item.get("axis") in intake.AXIS_IDS else ""
        kind = item.get("kind") if item.get("kind") in intake.QUESTION_KINDS else "open"
        target = str(item.get("target") or "")
        if not text:
            continue
        questions.append({"axis": axis, "kind": kind, "parent": target if target in known else "", "q": text})
    opened = [axis for axis in payload.get("opened_axes") or [] if axis in intake.AXIS_IDS and axis not in here]
    return {
        "assessment": assessment,
        "questions": questions,
        "opened_axes": opened,
        "stage_done": bool(payload.get("stage_done")),
    }


def draft_prd(root: str, plan: dict[str, Any]) -> dict[str, Any]:
    """온보딩의 답을 PRD 다섯 칸으로. 답이 비어도 만든다 — 대신 추측한 줄에 표를 단다.

    자동초안 갈래(`intake.mode == "auto"`)는 프롬프트가 갈린다: 표기를 1인칭으로 쓰고, 가정을
    본문 밖 목록으로 꺼내고, 사후 확인 질문을 세 개까지 같이 낸다."""
    row = plan["intake"]
    auto = row["mode"] == "auto"
    user = json.dumps(
        {
            "idea": row["idea"],
            "interview": [
                {"q": item["q"], "a": item["a"], "axis": item["axis"]} for item in row["questions"] if item["a"].strip()
            ],
            "coverage": [
                {"axis": axis, "label": intake.AXIS_LABEL[axis], "state": intake.state_of(row["coverage"], axis)}
                for axis in intake.AXIS_IDS
            ],
            "assumptions": [{"axis": item["axis"], "text": item["text"]} for item in row["assumptions"]],
            "conversation": _recent_chat(plan),
            "existing_sections": {sid: plan["prd"]["sections"][sid]["body"] for sid in store.PRD_SECTION_IDS},
        },
        ensure_ascii=False,
    )
    payload = _json_call(root, _PRD_AUTO_SYS if auto else _PRD_SYS, user, 3000, plan.get("engine"))
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
        "assumptions": _axis_rows(payload.get("assumptions"), "text"),
        "checks": _axis_rows(payload.get("checks"), "q")[:3],
    }


def _axis_rows(value: Any, field: str) -> list[dict[str, str]]:
    """`{axis, <field>}` 줄만 추린다 — 축이 표 밖이거나 글이 비면 버린다."""
    out = []
    for item in value or []:
        if not isinstance(item, dict) or item.get("axis") not in intake.AXIS_IDS:
            continue
        text = " ".join(str(item.get(field) or "").split())[:600]
        if text:
            out.append({"axis": item["axis"], field: text})
    return out


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
    payload = _json_call(root, _REFINE_SYS, user, 2000, plan.get("engine"))
    body = _text(payload.get("body"))
    if not body:
        raise ValueError("planner returned an empty section")
    return {"body": body, "note": " ".join(str(payload.get("note") or "").split())[:300]}


def refine_document(root: str, plan: dict[str, Any], request: str) -> dict[str, Any]:
    """다섯 칸을 한 번에 다듬는다 — 고친 칸만 대체 본문과 한 줄 설명으로 돌려준다.

    돌려주는 값: `{"sections": {sid: {"body", "note"}}, "summary"}`. 안 고친 칸은 `sections`에
    없다 — 빈 본문이나 원문과 같은 본문으로 온 칸은 여기서 떨어뜨린다. 그래서 `sections`가 비면
    실패가 아니라 **고칠 것이 없었다**는 뜻이다. 확정한 답과 확인된 가정을 프롬프트에 함께
    넣는 이유는 문서 전체를 다시 쓰는 갈래라 사람이 정한 것이 조용히 지워질 수 있기 때문이다."""
    row = plan["intake"]
    user = json.dumps(
        {
            "title": plan["title"],
            "request": request,
            "sections": [
                {"id": sid, "label": label, "guide": guide, "body": plan["prd"]["sections"][sid]["body"]}
                for sid, label, guide in store.PRD_SECTIONS
            ],
            "attributes": plan["prd"]["attributes"],
            "decided": [{"q": item["q"], "a": item["a"]} for item in row["questions"] if item["a"].strip()][:40],
            "confirmed_assumptions": [item["text"] for item in row["assumptions"] if item["confirmed"]],
        },
        ensure_ascii=False,
    )
    payload = _json_call(root, _DOCUMENT_SYS, user, 4000, plan.get("engine"))
    rows = payload.get("sections")
    if not isinstance(rows, dict):
        raise ValueError("planner returned no document sections")
    out: dict[str, dict[str, str]] = {}
    for sid in store.PRD_SECTION_IDS:
        item = rows.get(sid)
        if not isinstance(item, dict):
            continue
        body = _text(item.get("body"))
        if not body or body == _text(plan["prd"]["sections"][sid]["body"]):
            continue
        out[sid] = {"body": body, "note": " ".join(str(item.get("note") or "").split())[:300]}
    return {"sections": out, "summary": " ".join(str(payload.get("summary") or "").split())[:300]}


def refine_selection(root: str, plan: dict[str, Any], section: str, request: str, selection: str) -> dict[str, str]:
    """고른 구간만 고쳐 돌려준다 — 그 구간의 대체 글뿐이고 칸 전체는 내지 않는다.

    앞뒤 글은 프롬프트에 문맥으로 넣되 돌려받지 않는다. 길이는 프롬프트로 원문 구간의 3배까지
    묶는다 — 구간 수정이 칸 다시 쓰기로 번지면 사람이 안 고른 자리가 같이 갈린다.
    고른 글이 그 칸 본문에 없으면 `ValueError`."""
    if section not in store.PRD_SECTION_IDS:
        raise ValueError(f"unknown PRD section: {section}")
    body = plan["prd"]["sections"][section]["body"]
    start = body.find(selection) if selection else -1
    if start < 0:
        raise ValueError("selection is not in the section body")
    end = start + len(selection)
    user = json.dumps(
        {
            "section": section,
            "section_label": _SECTION_LABEL[section],
            "text_before": body[:start][-1200:],
            "selection": selection[:2000],
            "text_after": body[end:][:1200],
            "max_chars": len(selection) * 3,
            "request": request,
            "attributes": plan["prd"]["attributes"],
        },
        ensure_ascii=False,
    )
    payload = _json_call(root, _SELECTION_SYS, user, 1500, plan.get("engine"))
    replacement = _text(payload.get("replacement"))
    if not replacement:
        raise ValueError("planner returned an empty replacement")
    return {"replacement": replacement, "note": " ".join(str(payload.get("note") or "").split())[:300]}


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
    payload = _json_call(root, _SPEC_SYS, user, 6000, plan.get("engine"))
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
    payload = _json_call(root, _FLOW_SYS, user, 6000, plan.get("engine"))
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
    text = _complete(root, _REPLY_SYS, user, 1200, plan.get("engine")).strip()
    if not text:
        raise ValueError("planner returned an empty reply")
    return text[:4000]


# --- 옮겨 담기 ---------------------------------------------------------------


def _materialize_items(rows: list[Any], roles: list[str]) -> list[dict[str, Any]]:
    """모델의 임시 key를 저장소 id로 바꾸고, 부모를 못 찾은 항목은 버린다.

    두 번 도는 이유는 부모가 뒤에 올 수 있기 때문이다 — 먼저 id를 전부 발급하고,
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
    """구획·노드·연결선을 저장소 id로 옮긴다. 없는 노드를 가리키는 선은 버린다."""
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


def _json_call(root: str, system: str, user: str, max_tokens: int, engine: Any = None) -> dict[str, Any]:
    return _parse(_complete(root, system, user, max_tokens, engine))


def _complete(root: str, system: str, user: str, max_tokens: int, engine: Any) -> str:
    """`plan["engine"]`이 정본이다 — 둘 다 비면 그 자리의 기본 엔진으로 돈다.

    엔진이 안 닿으면 어느 엔진으로 부르려 했는지를 메시지에 남긴다. 기획마다 다른 엔진을 걸 수
    있게 된 순간, "왜 실패했나"에 엔진 이름이 없으면 사용자가 손댈 곳을 못 찾는다."""
    from ..agent.oneshot import complete_with
    from ..providers import resolve

    row = engine if isinstance(engine, dict) else {}
    provider, model = str(row.get("provider") or ""), str(row.get("model") or "")
    resolved = resolve(root, provider or None, model or None)
    if resolved.missing:
        raise RuntimeError(f"{_engine_label(provider, model)} 엔진 미충족: " + "; ".join(resolved.missing))
    return complete_with(resolved, root, system, user, max_tokens=max_tokens)


def _engine_label(provider: str, model: str) -> str:
    return " · ".join(part for part in (provider, model) if part) or "기본"


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
