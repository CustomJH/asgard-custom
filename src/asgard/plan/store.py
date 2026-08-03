"""기획의 정본 데이터 — 대화 하나와 문서 셋(PRD → 기능 명세서 → 유저 플로우).

앞선 형상은 단계 열 개와 기록 갈래 스물둘을 사용자에게 그대로 물었다. 문을 열면 "산출물을
고르세요 · 방법을 고르세요"가 먼저 서 있었고, 한 항목을 적으려면 갈래와 상태를 고른 뒤
다른 항목과 손으로 이어야 했다. 구조는 맞았지만 그 구조를 **사람이 조립**하고 있었다.

그래서 여기서는 사람이 드는 것을 하나로 줄인다 — **말**. 한 줄을 적으면 대화가 시작되고,
그 대화가 PRD를 채우고, 채워진 PRD가 기능 명세서의 입력이 되고, 명세서가 유저 플로우의
입력이 된다. 순서를 건너뛸 수 없는 이유는 규칙이라서가 아니라 **뒤 문서의 재료가 앞 문서**이기
때문이다: `readiness()`가 막는 것은 권한이 아니라 빈 입력이다.

두 가지를 일부러 나눠 둔다:
  · `phase`는 **커서**다 — 지금 사람이 어느 문서를 보고 있는가. 진척이 아니다.
  · 진척은 늘 내용에서 **파생**한다(`readiness`) — 저장하면 "다 됐다고 적힌 빈 문서"가 생긴다.

PRD 다섯 칸 중 앞 넷은 산문이고 마지막 '속성'만 구조를 가진다. 역할·환경은 아래 두 문서가
기계적으로 소비하는 값이라, 문장 안에 녹아 있으면 꺼낼 때마다 다시 추측해야 한다.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from typing import Any
from uuid import uuid4

from .. import errors
from ..io_files import read_json, write_json
from . import intake

# 온보딩 표의 정본은 `intake` 다. 계약이 `store.INTAKE_AXES` 로 부르므로 여기서 다시 낸다.
INTAKE_AXES = intake.INTAKE_AXES
INTAKE_STAGES = intake.INTAKE_STAGES

# 순수 가산이라 버전을 안 올린다. 3으로 올리면 아래 `_archive_legacy`가 사용자의 `plans.json`을
# 통째로 비켜 놓는데, 옛 문서는 `intake.checked`가 기본값을 채워 그대로 통과하므로 그 비용을
# 치를 이유가 없다.
SCHEMA_VERSION = 2

# 커서가 설 수 있는 자리. 'done'은 문서 셋이 다 찬 뒤 사람이 닫은 상태다.
PHASES = ("intake", "prd", "spec", "flow", "done")

PRD_SECTIONS = (
    ("overview", "개요", "한 줄 정의와 제품 목표, 그리고 왜 지금 이걸 만드는지."),
    ("value", "핵심 가치", "사용자가 겪는 문제와 우리의 해결 방식, 다른 것과 무엇이 다른지."),
    ("target", "타겟 및 시나리오", "핵심 사용자 그룹과 그들이 실제로 이걸 쓰는 이야기."),
    ("success", "성공 지표", "무엇으로 성공을 재는지, 무엇이 위험한지, 아직 안 정한 것은 무엇인지."),
    ("attributes", "속성 설정", "제품 갈래·사용자 역할·서비스 환경. 뒤 문서가 이 값을 그대로 써요."),
)
PRD_SECTION_IDS = tuple(section for section, _, _ in PRD_SECTIONS)
_PRD_LABEL = {section: label for section, label, _ in PRD_SECTIONS}

# 기능 명세서 세 층. PRD가 '무엇을 왜'라면 이 문서는 '어떻게 작동하는가'다.
SPEC_LEVELS = ((1, "요구사항"), (2, "기능"), (3, "상세 기능"))
SPEC_LEVEL_LABEL = dict(SPEC_LEVELS)
PRIORITIES = ("low", "medium", "high")
ITEM_STATUSES = ("todo", "doing", "done", "hold")

# 유저 플로우 노드 넷. 'section'은 그 구획의 최상위 페이지이자 구획 자신의 대표다.
NODE_TYPES = ("start", "section", "page", "action")

CHAT_ROLES = ("user", "asgard")

# 뒤 문서를 막는 이유. 코드는 계약이고, 사람 말은 화면이 고른다.
BLOCKED_TEXT = {
    "prd.overview": "PRD의 개요를 먼저 채워 주세요",
    "spec.feature": "기능 명세서에 기능을 하나 이상 적어 주세요",
    "intake.idea": "무엇을 만들지 한 줄로 적어 주세요",
}

_ID = intake.ROW_ID
_MAX_TEXT = intake.MAX_TEXT
_MAX_TITLE = intake.MAX_TITLE
_MAX_PLAN_BYTES = 512_000
_MAX_PLANS = 100
_MAX_CHAT = 400
_MAX_ITEMS = 300
_MAX_NODES = 200
_MAX_EDGES = 400
_MAX_SECTIONS = 40
_LOCK = threading.Lock()


class RevisionConflict(errors.Conflict, ValueError):
    """읽은 뒤에 남이 고쳤다 — 덮어쓰지 않고 되돌려 준다."""

    code = "plan_conflict"


class PlanNotReady(errors.Conflict, ValueError):
    """앞 문서가 비어 있어 뒤 문서를 만들 재료가 없다."""

    code = "not_ready"


def store_path() -> str:
    """기획의 정본 자리 — **워크스페이스 하나**, 폴더당 하나가 아니다.

    기획은 코드가 아직 없는 데서 시작한다. 그런데 여태 이 파일은
    `<프로젝트>/.asgard/plan/`에 살았다 — 그래서 문서를 열려면 먼저 어느 폴더에서 열었는지가 맞아야 했고, 저장소가
    없는 아이디어는 적을 자리가 없었으며, 폴더를 옮기면 기획이 통째로 사라졌다. 일감이
    워크스페이스로 간 것과 같은 이유로([[studio.db]]) 여기도 같이 간다."""
    return os.path.join(_home(), "plans.json")


def legacy_path() -> str:
    """옛 형상(단계·기록)의 자리. 스키마가 갈리면 지우지 않고 여기로 비켜 둔다."""
    return os.path.join(_home(), "plans.v1.json")


def project_store_path(root: str) -> str:
    """폴더마다 기획이 하나이던 시절의 자리. 반입의 **원본**이라 읽기로만 연다."""
    return os.path.join(os.path.abspath(root), ".asgard", "plan", "plans.json")


def _home() -> str:
    from ..settings import workspace_home

    return workspace_home()


def new_plan(idea: str, title: str = "", root: str = "", mode: str = "", engine: Any = None) -> dict[str, Any]:
    """한 줄에서 시작한다 — 고를 것은 갈래와 엔진뿐이고 둘 다 비워도 된다.

    제목은 안 주면 그 한 줄에서 깎는다. `root`는 이 기획이 **가리키는** 폴더지 있는 자리가
    아니다 — 코드가 아직 없는 기획이 그렇고, 그게 기본이다. `mode`가 비면 화면이 나중에
    고르고, `engine`이 비면 그 자리의 기본 엔진으로 돈다."""
    idea = " ".join(str(idea or "").split())
    if not idea or len(idea) > _MAX_TEXT:
        raise ValueError(f"idea must be 1..{_MAX_TEXT} characters")
    name = " ".join(str(title or "").split()) or idea
    now = _now()
    onboarding = intake.new(idea)
    onboarding["mode"] = intake.checked_mode(mode)
    onboarding["stage"] = _entry_stage(onboarding["mode"])
    return {
        "schema": SCHEMA_VERSION,
        "id": uuid4().hex,
        "title": name[:_MAX_TITLE],
        "root": _checked_root(root),
        "created_at": now,
        "updated_at": now,
        "revision": 1,
        "phase": "intake",
        "engine": _checked_engine(engine),
        "intake": onboarding,
        "chat": [{"id": intake.new_row_id("t"), "role": "user", "text": idea, "ts": now}],
        "prd": {
            "sections": {section: {"body": ""} for section in PRD_SECTION_IDS},
            "attributes": {"category": "", "roles": [], "environments": []},
        },
        "spec": {"items": []},
        "flow": {"sections": [], "nodes": [], "edges": []},
    }


def validate_plan(value: Any) -> dict[str, Any]:
    """저장 전 전량 검사. 통과하면 정규화된 사본을 돌려준다 — 원본은 건드리지 않는다."""
    if not isinstance(value, dict):
        raise ValueError("plan must be an object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("plan must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > _MAX_PLAN_BYTES:
        raise ValueError("plan is too large")
    if value.get("schema") != SCHEMA_VERSION:
        raise ValueError(f"schema must be {SCHEMA_VERSION}")
    if not isinstance(value.get("id"), str) or not _ID.fullmatch(value["id"]):
        raise ValueError("invalid plan id")
    title = value.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > _MAX_TITLE:
        raise ValueError(f"title must be 1..{_MAX_TITLE} characters")
    if not all(isinstance(value.get(key), str) and value[key] for key in ("created_at", "updated_at")):
        raise ValueError("created_at and updated_at are required")
    if type(value.get("revision")) is not int or value["revision"] < 1:
        raise ValueError("revision must be a positive integer")
    if value.get("phase") not in PHASES:
        raise ValueError(f"phase must be one of: {', '.join(PHASES)}")

    plan = copy.deepcopy(value)
    # 폴더는 선택이다 — 없는 것이 정상이라 없다고 거부하지 않는다(폴더 종속을 끊은 자리).
    plan["root"] = _checked_root(plan.get("root"))
    plan["engine"] = _checked_engine(plan.get("engine"))
    plan["intake"] = intake.checked(plan.get("intake"))
    plan["chat"] = _checked_chat(plan.get("chat"))
    plan["prd"] = _checked_prd(plan.get("prd"))
    plan["spec"] = {"items": _checked_items(plan.get("spec"))}
    plan["flow"] = _checked_flow(plan.get("flow"))
    return plan


def _checked_root(value: Any) -> str:
    """기획이 가리키는 폴더. 빈 값이 기본이고, 절대경로로만 굳힌다."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("root must be a path string")
    text = value.strip()
    if not text:
        return ""
    if len(text) > _MAX_TITLE * 4:
        raise ValueError("root path is too long")
    return os.path.abspath(os.path.expanduser(text))


def _checked_engine(value: Any) -> dict[str, str]:
    """이 기획이 쓰는 엔진. 둘 다 빈 값이면 그 자리의 기본 엔진으로 돈다 — 비어 있는 것이 기본이다."""
    row = value if isinstance(value, dict) else {}
    out = {}
    for key in ("provider", "model"):
        text = row.get(key, "")
        if not isinstance(text, str) or len(text) > _MAX_TITLE:
            raise ValueError(f"engine.{key} must be a short string")
        out[key] = text.strip()
    return out


def _entry_stage(mode: str) -> str:
    """갈래를 고른 직후 서는 단계. `auto`는 문답을 안 돌므로 확인 단계로 바로 간다."""
    if not mode:
        return "entry"
    return "confirm" if mode == "auto" else "frame"


def _checked_chat(chat: Any) -> list[dict[str, Any]]:
    if not isinstance(chat, list) or len(chat) > _MAX_CHAT:
        raise ValueError(f"chat must be a list with at most {_MAX_CHAT} turns")
    out = []
    seen: set[str] = set()
    for turn in chat:
        if not isinstance(turn, dict):
            raise ValueError("each chat turn must be an object")
        tid, role, text, ts = turn.get("id"), turn.get("role"), turn.get("text"), turn.get("ts")
        if not isinstance(tid, str) or not _ID.fullmatch(tid) or tid in seen:
            raise ValueError("each chat turn needs a unique valid id")
        if role not in CHAT_ROLES:
            raise ValueError(f"chat role must be one of: {', '.join(CHAT_ROLES)}")
        if not isinstance(text, str) or not text.strip() or len(text) > _MAX_TEXT:
            raise ValueError("each chat turn needs text")
        if not isinstance(ts, str) or not ts:
            raise ValueError("each chat turn needs a timestamp")
        seen.add(tid)
        out.append({"id": tid, "role": role, "text": text, "ts": ts})
    return out


def _checked_prd(prd: Any) -> dict[str, Any]:
    if not isinstance(prd, dict):
        raise ValueError("prd must be an object")
    sections = prd.get("sections")
    if not isinstance(sections, dict):
        raise ValueError("prd.sections must be an object")
    # 칸은 정본 다섯 개 고정 — 없으면 채우고 모르는 것은 버린다. 문구를 다듬는 순간
    # 사용자의 `plans.json`이 "정본이 아니다"로 거부되면 안 된다.
    checked = {}
    for section in PRD_SECTION_IDS:
        row = sections.get(section) or {}
        if not isinstance(row, dict):
            raise ValueError(f"prd.sections.{section} must be an object")
        body = row.get("body", "")
        if not isinstance(body, str) or len(body) > _MAX_TEXT:
            raise ValueError(f"prd.sections.{section}.body must be text under {_MAX_TEXT} characters")
        checked[section] = {"body": body}
    attrs = prd.get("attributes") or {}
    if not isinstance(attrs, dict):
        raise ValueError("prd.attributes must be an object")
    category = attrs.get("category", "")
    if not isinstance(category, str) or len(category) > _MAX_TITLE:
        raise ValueError("prd.attributes.category must be a short string")
    return {
        "sections": checked,
        "attributes": {
            "category": category.strip(),
            "roles": _checked_labels(attrs.get("roles"), "prd.attributes.roles"),
            "environments": _checked_labels(attrs.get("environments"), "prd.attributes.environments"),
        },
    }


def _checked_labels(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError(f"{where} must be a list with at most 20 items")
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > _MAX_TITLE:
            raise ValueError(f"{where} entries must be short non-empty strings")
        label = " ".join(item.split())
        if label not in out:
            out.append(label)
    return out


def _checked_items(spec: Any) -> list[dict[str, Any]]:
    if not isinstance(spec, dict):
        raise ValueError("spec must be an object")
    items = spec.get("items")
    if not isinstance(items, list) or len(items) > _MAX_ITEMS:
        raise ValueError(f"spec.items must be a list with at most {_MAX_ITEMS} entries")
    ids = [row.get("id") if isinstance(row, dict) else None for row in items]
    if len(set(ids)) != len(ids):
        raise ValueError("spec item ids must be unique")
    known = set(ids)
    out = []
    for row in items:
        if not isinstance(row, dict):
            raise ValueError("each spec item must be an object")
        item_id, level, title = row.get("id"), row.get("level"), row.get("title")
        if not isinstance(item_id, str) or not _ID.fullmatch(item_id):
            raise ValueError("each spec item needs a valid id")
        if level not in dict(SPEC_LEVELS):
            raise ValueError("spec item level must be 1, 2, or 3")
        if not isinstance(title, str) or not title.strip() or len(title) > _MAX_TITLE * 2:
            raise ValueError("each spec item needs a title")
        parent = row.get("parent") or ""
        if parent and (parent not in known or parent == item_id):
            raise ValueError(f"spec item {item_id} has an unknown parent")
        if (level == 1) != (not parent):
            raise ValueError("only level 1 items may be parentless")
        desc = row.get("desc", "")
        if not isinstance(desc, str) or len(desc) > _MAX_TEXT:
            raise ValueError("spec item desc must be text")
        criteria = row.get("criteria") or []
        if not isinstance(criteria, list) or len(criteria) > 30:
            raise ValueError("spec item criteria must be a list with at most 30 entries")
        if not all(isinstance(c, str) and c.strip() and len(c) <= _MAX_TITLE * 3 for c in criteria):
            raise ValueError("spec item criteria entries must be short non-empty strings")
        role = row.get("role", "")
        if not isinstance(role, str) or len(role) > _MAX_TITLE:
            raise ValueError("spec item role must be a short string")
        priority = row.get("priority", "medium")
        status = row.get("status", "todo")
        if priority not in PRIORITIES or status not in ITEM_STATUSES:
            raise ValueError("spec item priority/status is unknown")
        source = row.get("source", "")
        if not isinstance(source, str) or (source and source not in PRD_SECTION_IDS):
            raise ValueError("spec item source must name a PRD section")
        out.append(
            {
                "id": item_id,
                "level": level,
                "parent": parent,
                "title": title.strip(),
                "desc": desc,
                "criteria": [" ".join(c.split()) for c in criteria],
                "role": role.strip(),
                "priority": priority,
                "status": status,
                "source": source,
            }
        )
    _reject_cycles(out)
    return out


def _reject_cycles(items: list[dict[str, Any]]) -> None:
    """부모 체인은 반드시 위로 끝나야 한다 — 고리가 있으면 트리를 그리는 쪽이 영원히 돈다."""
    parent = {row["id"]: row["parent"] for row in items}
    for start in parent:
        seen, cursor = {start}, parent[start]
        while cursor:
            if cursor in seen:
                raise ValueError("spec items must not form a parent cycle")
            seen.add(cursor)
            cursor = parent.get(cursor, "")


def _checked_flow(flow: Any) -> dict[str, Any]:
    if not isinstance(flow, dict):
        raise ValueError("flow must be an object")
    raw_sections = flow.get("sections") or []
    if not isinstance(raw_sections, list) or len(raw_sections) > _MAX_SECTIONS:
        raise ValueError(f"flow.sections must be a list with at most {_MAX_SECTIONS} entries")
    sections, seen_sections = [], set()
    for row in raw_sections:
        if not isinstance(row, dict):
            raise ValueError("each flow section must be an object")
        sid, title = row.get("id"), row.get("title")
        if not isinstance(sid, str) or not _ID.fullmatch(sid) or sid in seen_sections:
            raise ValueError("each flow section needs a unique valid id")
        if not isinstance(title, str) or not title.strip() or len(title) > _MAX_TITLE:
            raise ValueError("each flow section needs a title")
        seen_sections.add(sid)
        sections.append({"id": sid, "title": title.strip()})

    raw_nodes = flow.get("nodes") or []
    if not isinstance(raw_nodes, list) or len(raw_nodes) > _MAX_NODES:
        raise ValueError(f"flow.nodes must be a list with at most {_MAX_NODES} entries")
    nodes, seen_nodes = [], set()
    starts = 0
    for row in raw_nodes:
        if not isinstance(row, dict):
            raise ValueError("each flow node must be an object")
        nid, ntype, title = row.get("id"), row.get("type"), row.get("title")
        if not isinstance(nid, str) or not _ID.fullmatch(nid) or nid in seen_nodes:
            raise ValueError("each flow node needs a unique valid id")
        if ntype not in NODE_TYPES:
            raise ValueError(f"flow node type must be one of: {', '.join(NODE_TYPES)}")
        if not isinstance(title, str) or not title.strip() or len(title) > _MAX_TITLE:
            raise ValueError("each flow node needs a title")
        section = row.get("section", "")
        if not isinstance(section, str) or (section and section not in seen_sections):
            raise ValueError(f"flow node {nid} names an unknown section")
        source = row.get("source", "")
        if not isinstance(source, str) or len(source) > 64:
            raise ValueError("flow node source must be a short id")
        starts += ntype == "start"
        seen_nodes.add(nid)
        nodes.append({"id": nid, "type": ntype, "title": title.strip(), "section": section, "source": source})
    if starts > 1:
        raise ValueError("a flow may have at most one start node")

    raw_edges = flow.get("edges") or []
    if not isinstance(raw_edges, list) or len(raw_edges) > _MAX_EDGES:
        raise ValueError(f"flow.edges must be a list with at most {_MAX_EDGES} entries")
    edges, seen_edges = [], set()
    for row in raw_edges:
        if not isinstance(row, dict):
            raise ValueError("each flow edge must be an object")
        eid, head, tail = row.get("id"), row.get("from"), row.get("to")
        if not isinstance(eid, str) or not _ID.fullmatch(eid) or eid in seen_edges:
            raise ValueError("each flow edge needs a unique valid id")
        if head not in seen_nodes or tail not in seen_nodes:
            raise ValueError(f"flow edge {eid} references a missing node")
        if head == tail:
            raise ValueError(f"flow edge {eid} must connect two different nodes")
        pair = (head, tail)
        if pair in {(e["from"], e["to"]) for e in edges}:
            raise ValueError("flow edges must not duplicate a connection")
        label = row.get("label", "")
        if not isinstance(label, str) or len(label) > _MAX_TITLE:
            raise ValueError("flow edge label must be a short string")
        seen_edges.add(eid)
        edges.append({"id": eid, "from": head, "to": tail, "label": label.strip()})
    return {"sections": sections, "nodes": nodes, "edges": edges}


def readiness(value: Any) -> dict[str, Any]:
    """뒤 문서를 만들 재료가 있는가 — 전부 내용에서 파생한다(저장하지 않는다).

    막는 이유는 권한이 아니라 **빈 입력**이다: 개요가 비면 기능 명세서가 읽을 것이 없고,
    기능이 하나도 없으면 유저 플로우가 이을 것이 없다.

    `prd`의 `score`·`grade`·`blocking`은 심사(`review`) 결과를 같이 실은 값이다. **판정에는
    안 쓰인다** — `ready`는 여전히 개요 한 칸이 찼는가만 본다."""
    # `review`가 이 모듈의 PRD 표를 읽는다 — 최상단에서 import 하면 순환이다.
    from .review import review as review_prd

    plan = validate_plan(value)
    card = review_prd(plan)
    sections = plan["prd"]["sections"]
    # 채운 칸의 판정은 심사 쪽 하나다. 여기서 본문만 세면 속성 설정은 값 셋이 다 차도 늘 빈 칸으로
    # 잡혀, 완성된 기획이 영원히 `4/5`로 보인다 — 속성의 뜻은 본문이 아니라 값 세 칸이 진다.
    filled = [s for s in PRD_SECTION_IDS if card["sections"][s]["filled"]]
    # 기능 명세서를 여는 판정만은 본문을 본다. 뒤 문서가 읽는 것이 개요 본문이라서다.
    overview = bool(sections["overview"]["body"].strip())
    features = [i for i in plan["spec"]["items"] if i["level"] == 2]
    spec_blocked = [] if overview else ["prd.overview"]
    flow_blocked = list(spec_blocked) + ([] if features else ["spec.feature"])
    return {
        "phase": plan["phase"],
        "intake": intake.readiness_view(plan["intake"]),
        "prd": {
            "ready": overview,
            "filled": len(filled),
            "total": len(PRD_SECTION_IDS),
            "sections": filled,
            "blocked": [],
            "score": card["score"],
            "grade": card["grade"],
            "blocking": card["blocking"],
        },
        "spec": {
            "ready": not spec_blocked,
            "items": len(plan["spec"]["items"]),
            "features": len(features),
            "blocked": spec_blocked,
        },
        "flow": {
            "ready": not flow_blocked,
            "nodes": len(plan["flow"]["nodes"]),
            "edges": len(plan["flow"]["edges"]),
            "blocked": flow_blocked,
        },
    }


def require_ready(plan: dict[str, Any], document: str) -> None:
    """뒤 문서를 만들기 전에 앞 문서를 확인한다 — 비면 만들지 않고 이유를 말한다."""
    blocked = readiness(plan).get(document, {}).get("blocked") or []
    if blocked:
        raise PlanNotReady("; ".join(BLOCKED_TEXT.get(code, code) for code in blocked))


# --- 저장소 ------------------------------------------------------------------


def load_state() -> dict[str, Any]:
    with _LOCK:
        return _load_state()


def list_plans(root: str = "") -> dict[str, Any]:
    """워크스페이스의 기획 전부. `root`는 **거르는 값이지 경계가 아니다** — 주면 그 폴더를
    가리키는 기획만 골라 주고, 안 주면 전부다(창의 기본이 이쪽이다)."""
    state = load_state()
    plans = state["plans"]
    if root:
        target = os.path.abspath(os.path.expanduser(root))
        plans = [plan for plan in plans if plan.get("root") == target]
    return {
        "schema": SCHEMA_VERSION,
        "active_plan_id": state["active_plan_id"],
        "plans": [_head(plan) for plan in plans],
        # 축·단계 표는 여기로 나간다 — 화면이 HTML에 베껴 적으면 표가 두 벌이 된다.
        "axes": intake.axes_table(),
        "stages": intake.stages_table(),
    }


def _head(plan: dict[str, Any]) -> dict[str, Any]:
    ready = readiness(plan)
    return {
        "id": plan["id"],
        "title": plan["title"],
        "root": plan.get("root", ""),
        "phase": plan["phase"],
        "updated_at": plan["updated_at"],
        "revision": plan["revision"],
        "prd_filled": ready["prd"]["filled"],
        "prd_total": ready["prd"]["total"],
        "features": ready["spec"]["features"],
        "nodes": ready["flow"]["nodes"],
        "engine": dict(plan.get("engine") or {"provider": "", "model": ""}),
        "mode": ready["intake"]["mode"],
        "intake_answered": ready["intake"]["answered"],
        "intake_asked": ready["intake"]["asked"],
    }


def load_plan(plan_id: str) -> dict[str, Any]:
    for plan in load_state()["plans"]:
        if plan["id"] == plan_id:
            return plan
    raise KeyError(plan_id)


def create_plan(idea: str, title: str = "", root: str = "", mode: str = "", engine: Any = None) -> dict[str, Any]:
    plan = new_plan(idea, title, root, mode, engine)
    with _LOCK:
        state = _load_state()
        if len(state["plans"]) >= _MAX_PLANS:
            raise ValueError(f"the workspace may hold at most {_MAX_PLANS} plans")
        state["plans"].append(plan)
        state["active_plan_id"] = plan["id"]
        _write_state(state)
    return plan


def save_plan(value: Any) -> dict[str, Any]:
    """개정 번호가 맞을 때만 덮어쓴다 — 다르면 남이 먼저 고친 것이다."""
    plan = validate_plan(value)
    with _LOCK:
        state = _load_state()
        for index, existing in enumerate(state["plans"]):
            if existing["id"] != plan["id"]:
                continue
            if plan["revision"] != existing["revision"]:
                raise RevisionConflict("plan changed after it was loaded")
            plan["revision"] += 1
            plan["updated_at"] = _now()
            state["plans"][index] = plan
            state["active_plan_id"] = plan["id"]
            _write_state(state)
            return plan
    raise KeyError(plan["id"])


def delete_plan(plan_id: str) -> None:
    with _LOCK:
        state = _load_state()
        remaining = [plan for plan in state["plans"] if plan["id"] != plan_id]
        if len(remaining) == len(state["plans"]):
            raise KeyError(plan_id)
        state["plans"] = remaining
        if state["active_plan_id"] == plan_id:
            state["active_plan_id"] = remaining[-1]["id"] if remaining else None
        _write_state(state)


def mutate(plan_id: str, change) -> dict[str, Any]:
    """읽고 · 고치고 · 쓰기를 한 잠금 안에서. 화면이 왕복하는 사이의 경합을 없앤다."""
    with _LOCK:
        state = _load_state()
        for index, existing in enumerate(state["plans"]):
            if existing["id"] != plan_id:
                continue
            draft = copy.deepcopy(existing)
            change(draft)
            plan = validate_plan(draft)
            plan["revision"] = existing["revision"] + 1
            plan["updated_at"] = _now()
            state["plans"][index] = plan
            state["active_plan_id"] = plan_id
            _write_state(state)
            return plan
    raise KeyError(plan_id)


def append_chat(plan: dict[str, Any], role: str, text: str) -> dict[str, Any]:
    """대화 한 줄. 오래된 줄은 앞에서 떨어진다 — 첫 줄(아이디어)만 붙잡아 둔다."""
    if role not in CHAT_ROLES:
        raise ValueError(f"chat role must be one of: {', '.join(CHAT_ROLES)}")
    body = str(text or "").strip()
    if not body:
        raise ValueError("chat text is required")
    turn = {"id": intake.new_row_id("t"), "role": role, "text": body[:_MAX_TEXT], "ts": _now()}
    chat = plan.setdefault("chat", [])
    chat.append(turn)
    if len(chat) > _MAX_CHAT:
        plan["chat"] = chat[:1] + chat[len(chat) - _MAX_CHAT + 1 :]
    return turn


def set_phase(plan: dict[str, Any], phase: str) -> None:
    """커서만 옮긴다 — 재료가 없는 자리로는 못 간다."""
    if phase not in PHASES:
        raise ValueError(f"phase must be one of: {', '.join(PHASES)}")
    if phase in {"spec", "flow"}:
        require_ready(plan, phase)
    plan["phase"] = phase


def set_mode(plan_id: str, mode: str) -> dict[str, Any]:
    """온보딩 갈래를 고른다 — 기획 하나에 한 번뿐이다.

    같은 갈래를 다시 주는 것은 통과시킨다(화면이 재시도할 수 있다). 이미 다른 갈래로
    시작했으면 `ValueError` — 두 갈래는 뒤 절차가 달라서 도중에 못 바꾼다."""
    chosen = intake.checked_mode(mode)
    if not chosen:
        raise ValueError("mode must be auto or guided")

    def change(draft: dict[str, Any]) -> None:
        current = draft["intake"]["mode"]
        if current and current != chosen:
            raise ValueError("이 기획은 이미 다른 갈래로 시작했어요")
        draft["intake"]["mode"] = chosen
        if draft["intake"]["stage"] in ("", "entry"):
            draft["intake"]["stage"] = _entry_stage(chosen)

    return mutate(plan_id, change)


def set_engine(plan_id: str, provider: str = "", model: str = "") -> dict[str, Any]:
    """이 기획이 쓸 엔진을 바꾼다. 둘 다 빈 값이면 그 자리의 기본 엔진으로 되돌린다."""
    engine = _checked_engine({"provider": provider, "model": model})
    return mutate(plan_id, lambda draft: draft.__setitem__("engine", engine))


def spec_tree(value: Any) -> list[dict[str, Any]]:
    """트리 뷰가 그대로 그리는 형상 — 부모 순서를 지키고 고아는 뿌리로 올린다."""
    items = validate_plan(value)["spec"]["items"]
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_parent.setdefault(item["parent"], []).append(item)

    def build(parent: str) -> list[dict[str, Any]]:
        return [{**row, "children": build(row["id"])} for row in by_parent.get(parent, [])]

    return build("")


def next_step(value: Any) -> dict[str, str]:
    """지금 이어서 할 일 한 가지. 화면의 큰 버튼 하나가 이 값을 쓴다."""
    plan = validate_plan(value)
    ready = readiness(plan)
    onboarding = ready["intake"]
    if not plan["prd"]["sections"]["overview"]["body"].strip():
        return _intake_step(onboarding)
    # PRD를 쓴 뒤에도 확인 단계의 질문은 남는다. 자동초안이 추측으로 채운 줄이 걸린 축을
    # 되묻는 자리라, 이걸 지나치면 근거 없는 PRD가 그대로 기능 명세서의 입력이 된다.
    open_question = onboarding["open_question"]
    if open_question and open_question["stage"] == "confirm":
        return {"action": "answer", "label": "이 질문에 답해 주세요"}
    if ready["prd"]["filled"] < ready["prd"]["total"]:
        return {"action": "fill_prd", "label": "PRD의 남은 칸 채우기"}
    if not ready["spec"]["items"]:
        return {"action": "draft_spec", "label": "PRD를 기반으로 기능 명세서 만들기"}
    if not ready["flow"]["nodes"]:
        return {"action": "draft_flow", "label": "기능 명세서를 기반으로 유저 플로우 만들기"}
    return {"action": "review", "label": "문서 셋을 함께 점검하기"}


def _intake_step(onboarding: dict[str, Any]) -> dict[str, str]:
    """PRD를 쓰기 전의 다음 한 걸음 — 갈래 고르기 · 답하기 · 더 묻기 · 초안 쓰기 순서다."""
    if not onboarding["mode"]:
        return {"action": "choose_mode", "label": "어떻게 시작할까요"}
    if onboarding["open_question"]:
        return {"action": "answer", "label": "이 질문에 답해 주세요"}
    if onboarding["can_ask"]:
        return {"action": "ask", "label": "먼저 몇 가지 여쭤볼게요"}
    return {"action": "draft_prd", "label": "여기까지로 PRD 초안 만들기"}


def new_id(prefix: str) -> str:
    return intake.new_row_id(prefix)


def _load_state() -> dict[str, Any]:
    path = store_path()
    raw = read_json(path)
    if raw is None:
        if os.path.exists(path):
            raise ValueError("plan store is unreadable; the original file was left untouched")
        return _empty()
    if not isinstance(raw, dict):
        raise ValueError("invalid plan store")
    if raw.get("schema") != SCHEMA_VERSION:
        # 옛 형상은 옮길 것이 없다 — 단계와 기록은 이 문서 셋에 대응하는 자리가 없다.
        # 그렇다고 지우지도 않는다: 비켜 두고 빈 저장소에서 시작한다.
        _archive_legacy(raw)
        return _empty()
    return checked_state(raw)


def checked_state(raw: dict[str, Any]) -> dict[str, Any]:
    plans = raw.get("plans")
    if not isinstance(plans, list) or len(plans) > _MAX_PLANS:
        raise ValueError("invalid plan list")
    checked = [validate_plan(plan) for plan in plans]
    ids = [plan["id"] for plan in checked]
    if len(set(ids)) != len(ids) or raw.get("active_plan_id") not in (None, *ids):
        raise ValueError("invalid active plan")
    return {"schema": SCHEMA_VERSION, "active_plan_id": raw.get("active_plan_id"), "plans": checked}


def _empty() -> dict[str, Any]:
    return {"schema": SCHEMA_VERSION, "active_plan_id": None, "plans": []}


def _archive_legacy(raw: Any) -> None:
    target = legacy_path()
    if not os.path.exists(target):
        write_json(target, raw)
    try:
        os.unlink(store_path())
    except OSError:
        pass


def _write_state(state: dict[str, Any]) -> None:
    write_json(store_path(), state)


def adopt(plans: list[dict[str, Any]], root: str = "") -> int:
    """다른 자리에서 온 기획을 워크스페이스에 더한다 — 더한 개수를 돌려준다.

    이미 있는 id 는 건너뛴다(두 번 불러도 두 벌이 안 생긴다). `root` 를 주면 폴더 링크가 빈
    기획에만 그 값을 건다 — 링크일 뿐 기획을 저장하는 자리는 아니다."""
    with _LOCK:
        state = _load_state()
        known = {plan["id"] for plan in state["plans"]}
        added = 0
        for plan in plans:
            if plan["id"] in known or len(state["plans"]) >= _MAX_PLANS:
                continue
            plan["root"] = plan.get("root") or root
            state["plans"].append(plan)
            known.add(plan["id"])
            added += 1
        if added:
            _write_state(state)
    return added


def _now() -> str:
    return intake.stamp()
