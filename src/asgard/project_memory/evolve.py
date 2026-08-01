"""프로젝트 메모리 진화 패스 — 2차 메모리도 스스로 낡은 곳을 찾아 고쳐 나간다.

개인 위키에는 노른이 있다: 신호를 모으고, LLM이 델타를 제안하고, 코드가 판정해서 커밋한다.
프로젝트 메모리에는 그게 없었다 — 등록은 되는데 낡지 않는 기억은 없으므로, 시간이 지나면
지워진 파일을 가리키는 record와 서로 어긋나는 record가 조용히 쌓인다.

같은 규율을 여기로 옮기되, **승인 게이트를 우회하지 않는다**. 프로젝트 메모리는 팀 공유
스코프라 쓰기가 언제나 사람 승인을 지난다 (stage_retain → project-approve). 그래서 이
패스의 산출은 커밋이 아니라 **승인 대기 제안**이다. 자율성은 "무엇을 볼지"에 있지
"무엇을 쓸지"에 있지 않다.

신호가 코드 몫과 LLM 몫으로 갈린다.
  결정론 — 사라진 source 파일, 근사 중복 쌍, revision 드리프트. 파일시스템이 답한다.
  제안   — 무엇이 낡았고 무엇이 새 통찰인지. 판정은 다시 코드가 한다 (사라짐은 재확인,
           통찰의 근거 record는 실존 확인, 스캔은 등록 기준 그대로).
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import os
import re

from .canonical import load_canonical_records
from .records import RELATIONS, ProjectRecord, record_item, render_record, validate_record
from .scan import source_revision

MERGE_FLOOR = 0.55  # 근사 중복 판정 — LLM 주장과 무관하게 코드가 본다 (노른 MERGE_FLOOR와 같은 취지)
MAX_RETIRE, MAX_INSIGHTS, MAX_CONTRADICTIONS = 5, 2, 3
# 관계는 레코드를 안 지우고 안 고쳐 쓴다 — 덧붙이기만 하므로 캡이 넉넉하다.
# 그래도 상한은 둔다: 전부를 전부에 잇는 그래프는 아무것도 안 잇는 것과 회수 성능이 같다.
MAX_RELATIONS = 6
INSIGHT_MIN_SOURCES, INSIGHT_MAX_SOURCES = 2, 6
INSIGHT_MAX_CHARS = 1500
MAX_RECORDS_IN_PROMPT = 80

# source가 파일 경로일 때만 "사라졌다"를 판정할 수 있다. quest:·url:·commit: 계열은
# 저장소 파일이 아니므로 존재 판정 대상이 아니다 — 못 보는 것을 봤다고 하지 않는다.
_PATH_SOURCE = re.compile(r"^(?!(?:quest|url|https?|commit|test|adr):)[\w./-]+$")

_EVOLVE_SYS = """You review one project's memory records and propose maintenance deltas.

You may propose three kinds of operation, and nothing else:
- retire — a record that no longer describes this repository. Give the record_id.
- insight — a durable cross-record conclusion worth registering as its own record. Cite the
  record_ids it comes from (at least two).
- contradiction — two records that cannot both be true. Give both record_ids. Report only.

Rules:
- Everything you claim is re-checked against the repository. A retire whose file still exists,
  or an insight whose sources do not exist, is dropped. Proposing more does not get you more.
- Records describe the project, never a person and never a session. Keep it that way.
- Insights must be about this codebase's design, contracts, or decisions — not about tooling
  that happened to fail once.
- Say nothing you cannot tie to the records you were given.

Return JSON only:
{"ops": [{"op": "retire", "record_id": "...", "why": "..."},
         {"op": "insight", "title": "...", "text": "...", "sources": ["id1","id2"], "why": "..."},
         {"op": "contradiction", "a": "id1", "b": "id2", "why": "..."},
         {"op": "relate", "a": "id1", "b": "id2", "relation": "dependsOn", "why": "..."}]}

`relate` states a typed relation that already holds between two existing records but was never
written down. Use only these relation types: supersedes, supportedBy, appliesTo, causedBy,
resolvedBy, dependsOn, implements, documents. Pick the one that is literally true from the record
text; do not reach for a relation because it sounds important.
"""


def _grams(text: str, n: int = 4) -> set[str]:
    normalized = re.sub(r"\s+", " ", text.lower())
    return {normalized[index : index + n] for index in range(max(len(normalized) - n + 1, 1))}


def _containment(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / (min(len(ga), len(gb)) or 1)


def _is_path_source(source: str) -> bool:
    return bool(_PATH_SOURCE.fullmatch(source.strip()))


def _missing_source(root: str, source: str) -> bool:
    """source가 저장소 파일 경로인데 지금 없으면 True. 경로가 아니면 판정하지 않는다.

    봉쇄는 글자 접두사가 아니라 **경로 성분**으로 센다 (scan._canonical_repo_path와 같은 규율).
    `startswith`는 `/repo`가 `/repo-notes`를 자기 안이라고 말한다 — `../repo-notes/x.md`가
    저장소를 벗어나 놓고 존재 판정을 받고, 없으면 그 record는 폐기 후보로 올라간다. 저장소
    밖은 우리가 볼 수 있는 자리가 아니므로 "없다"가 아니라 "판정하지 않는다"가 맞다."""
    if not _is_path_source(source):
        return False
    base = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(base, source.strip()))
    try:
        if os.path.commonpath((base, candidate)) != base:
            return False  # 경로 탈출 표기 — 존재 판정 대상 아님
    except ValueError:
        return False  # 드라이브가 다르다 — 비교 자체가 성립하지 않는다
    return not os.path.exists(candidate)


# ── 신호 수집 (결정론) ─────────────────────────────────────────────────────────


def signals(root: str) -> dict:
    """LLM에게 보여줄 증거 카드 — record 카탈로그와 코드가 이미 확인한 판정. 쓰기 없음."""
    try:
        loaded = load_canonical_records(root)
    except Exception as exc:
        return {"records": [], "missing_sources": [], "near_duplicates": [], "error": f"{type(exc).__name__}: {exc}"}
    rows: list[dict] = []
    for record, path, _digest in loaded:
        rows.append(
            {
                "record_id": record.record_id,
                "kind": record.kind,
                "title": record.title,
                "source": record.source,
                "status": record.status,
                "excerpt": record.content[:200],
                "path": path,
                "content": record.content,
                # 관계는 검증(중복 relate 차단)이 봐야 하므로 카탈로그에 넣는다
                "relations": [dict(rel) for rel in record.relations],
            }
        )
    active = [row for row in rows if row["status"] == "active"]
    missing = sorted(row["record_id"] for row in active if _missing_source(root, row["source"]))
    duplicates: list[dict] = []
    for index, left in enumerate(active):
        for right in active[index + 1 :]:
            overlap = _containment(left["content"], right["content"])
            if overlap >= MERGE_FLOOR:
                duplicates.append({"a": left["record_id"], "b": right["record_id"], "overlap": round(overlap, 3)})
    return {
        "records": [{k: v for k, v in row.items() if k != "content"} for row in rows[:MAX_RECORDS_IN_PROMPT]],
        "missing_sources": missing,
        "near_duplicates": duplicates[:20],
        "total": len(rows),
        "active": len(active),
    }


# ── 계획 (LLM 제안 → 결정적 검증) ──────────────────────────────────────────────


def _parse_ops(raw: str) -> list[dict]:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("project evolve: LLM output is not JSON")
    payload = json.loads(raw[start : end + 1])
    ops = payload.get("ops") if isinstance(payload, dict) else None
    if not isinstance(ops, list):
        raise ValueError("project evolve: LLM output has no ops list")
    return [op for op in ops if isinstance(op, dict)]


def validate_ops(ops: list[dict], root: str, sig: dict) -> tuple[list[dict], list[dict]]:
    """결정적 검증 — 통과한 op와 (op, 기각 사유). LLM 주장은 검증 입력일 뿐이다."""
    known = {row["record_id"]: row for row in sig.get("records") or []}
    active = {rid for rid, row in known.items() if row["status"] == "active"}
    accepted: list[dict] = []
    dropped: list[dict] = []
    counts = {"retire": 0, "insight": 0, "contradiction": 0, "relate": 0}
    caps = {
        "retire": MAX_RETIRE,
        "insight": MAX_INSIGHTS,
        "contradiction": MAX_CONTRADICTIONS,
        "relate": MAX_RELATIONS,
    }
    seen_retire: set[str] = set()

    def _drop(op: dict, reason: str) -> None:
        dropped.append({"op": op, "reason": reason})

    for op in ops:
        kind = str(op.get("op") or "").strip().lower()
        if kind not in caps:
            _drop(op, f"unknown op: {kind!r}")
            continue
        if counts[kind] >= caps[kind]:
            _drop(op, f"{kind} cap reached ({caps[kind]})")
            continue
        if kind == "retire":
            record_id = str(op.get("record_id") or "").strip()
            if record_id not in active:
                _drop(op, "record_id is not an active canonical record")
                continue
            if record_id in seen_retire:
                _drop(op, "duplicate retire in this pass")
                continue
            # 코드가 다시 본다. LLM이 "낡았다"고 말해도, 파일이 살아 있으면 낡지 않았다.
            if not _missing_source(root, known[record_id]["source"]):
                _drop(op, f"source still exists in the repository: {known[record_id]['source']}")
                continue
            seen_retire.add(record_id)
            accepted.append(
                {
                    "op": "retire",
                    "record_id": record_id,
                    "source": known[record_id]["source"],
                    "title": known[record_id]["title"],
                    "why": str(op.get("why", ""))[:200],
                }
            )
        elif kind == "insight":
            title = str(op.get("title") or "").strip()
            text = str(op.get("text") or "").strip()
            sources = [str(value).strip() for value in (op.get("sources") or []) if str(value).strip()]
            sources = list(dict.fromkeys(sources))
            if not INSIGHT_MIN_SOURCES <= len(sources) <= INSIGHT_MAX_SOURCES:
                _drop(op, f"insight needs {INSIGHT_MIN_SOURCES}–{INSIGHT_MAX_SOURCES} source records")
                continue
            unknown = [value for value in sources if value not in known]
            if unknown:
                _drop(op, f"insight cites records that do not exist: {unknown[:3]}")
                continue
            if len(text) > INSIGHT_MAX_CHARS:
                _drop(op, f"insight exceeds {INSIGHT_MAX_CHARS} chars")
                continue
            record = _insight_record(root, title, text, sources)
            validation = validate_record(record, root)
            if not validation.accepted:
                _drop(op, "; ".join(validation.reasons))
                continue
            accepted.append(
                {
                    "op": "insight",
                    "record_id": record.record_id,
                    "title": title,
                    "text": text,
                    "sources": sources,
                    "why": str(op.get("why", ""))[:200],
                }
            )
        elif kind == "relate":
            # 관계 어휘는 이미 정본에 있다 (records.RELATIONS). 코드가 그 목록으로 다시 본다 —
            # LLM이 그럴듯한 새 관계명을 지어내면(과거 실측: `derived_from`) 조용히 통과해선 안 된다.
            a, b = str(op.get("a") or "").strip(), str(op.get("b") or "").strip()
            relation = str(op.get("relation") or "").strip()
            if a not in active or b not in active or a == b:
                _drop(op, "relate: records missing, retired, or identical")
                continue
            if relation not in RELATIONS:
                _drop(op, f"relate: unknown relation {relation!r} — one of {', '.join(sorted(RELATIONS))}")
                continue
            if any(
                rel.get("type") == relation and rel.get("target") == b
                for rel in (known[a].get("relations") or ())
                if isinstance(rel, dict)
            ):
                _drop(op, "relate: already recorded")
                continue
            accepted.append({"op": "relate", "a": a, "b": b, "relation": relation, "why": str(op.get("why", ""))[:200]})
        else:  # contradiction — 보고 전용, record 실존만 확인
            a, b = str(op.get("a") or "").strip(), str(op.get("b") or "").strip()
            if a not in known or b not in known or a == b:
                _drop(op, "contradiction records missing or identical")
                continue
            accepted.append({"op": "contradiction", "a": a, "b": b, "why": str(op.get("why", ""))[:200]})
        counts[kind] += 1
    return accepted, dropped


def _insight_record(root: str, title: str, text: str, sources: list[str]) -> ProjectRecord:
    digest = hashlib.sha256("\0".join([title, *sorted(sources)]).encode()).hexdigest()[:20]
    return ProjectRecord(
        record_id=f"insight.{digest}",
        kind="decision",
        title=title[:120],
        content=f"{text}\n\n근거 record: {', '.join(sources)}",
        source=f"evolve:{','.join(sources[:3])}",
        source_revision=source_revision(root),
        importance="normal",
        # 합성물은 관측이지 검증이 아니다 — confidence를 사람이 올려주기 전까지 observed 다
        confidence="observed",
        relations=tuple({"type": "supportedBy", "target": value} for value in sources),
    )


def _retire_record(root: str, existing: dict) -> ProjectRecord:
    """같은 record_id를 superseded 상태로 다시 쓴다 — 삭제가 아니라 상태 전이다."""
    return ProjectRecord(
        record_id=existing["record_id"],
        kind=existing["kind"],
        title=existing["title"],
        content=(
            f"{existing['excerpt']}\n\n"
            f"이 record의 출처 `{existing['source']}`는 저장소에서 사라졌다 — "
            f"진화 패스가 superseded로 전이시켰다 (내용은 이력으로 남는다)."
        ),
        source=existing["source"],
        source_revision=source_revision(root),
        importance="normal",
        confidence="observed",
        status="superseded",
    )


def _relate_record(root: str, record_id: str, relation: str, target: str) -> ProjectRecord:
    """정본 레코드에 관계 하나를 덧붙인다 — 본문·상태는 한 글자도 안 고친다.

    카탈로그 행(excerpt 200자)이 아니라 정본을 다시 읽는 이유: 관계를 적으려고 레코드를
    다시 쓰는데 발췌를 본문 자리에 넣으면 그 레코드는 그 순간 잘린다. 덧붙이는 연산이
    지우는 연산이 되면 안 된다."""
    for record, _path, _digest in load_canonical_records(root):
        if record.record_id == record_id:
            return dataclasses.replace(
                record,
                source_revision=source_revision(root),
                relations=(*record.relations, {"type": relation, "target": target}),
            )
    raise KeyError(f"relate: canonical record not found: {record_id}")


def _complete(root: str, system: str, user: str) -> str:
    """LLM 단발 호출 간접점 — 테스트가 이 지점만 대체한다. 메인 provider를 쓴다."""
    from ..agent.oneshot import complete_once

    return complete_once(root, system, user, max_tokens=3000)


def plan_evolve(root: str) -> dict:
    """신호 수집 → LLM 제안 → 결정적 검증. 반환 = {"ops", "dropped", "signals"}. 쓰기 없음."""
    sig = signals(root)
    if len(sig.get("records") or []) < 2:
        return {"ops": [], "dropped": [], "signals": sig, "reason": "fewer than two canonical records"}
    user = json.dumps(
        {
            "records": sig["records"],
            "sources_missing_from_repo": sig["missing_sources"],
            "near_duplicates": sig["near_duplicates"],
        },
        ensure_ascii=False,
    )
    ops = _parse_ops(_complete(root, _EVOLVE_SYS, user))
    accepted, dropped = validate_ops(ops, root, sig)
    return {"ops": accepted, "dropped": dropped, "signals": sig}


# ── 적용 (승인 대기 제안 — 커밋 아님) ──────────────────────────────────────────


def apply_evolve(root: str, cfg: dict, plan: dict) -> dict:
    """검증 통과 op를 승인 대기로 올린다. 팀 공유 스코프라 여기서 커밋하지 않는다."""
    from ..memory_bridge import backend_target, stage_retain

    target = backend_target(cfg)
    known = {row["record_id"]: row for row in plan.get("signals", {}).get("records") or []}
    staged: list[dict] = []
    failed: list[dict] = []
    reported: list[dict] = []
    for op in plan.get("ops") or []:
        if op["op"] == "contradiction":
            reported.append(op)
            continue
        try:
            if op["op"] == "insight":
                record = _insight_record(root, op["title"], op["text"], op["sources"])
            elif op["op"] == "relate":
                record = _relate_record(root, op["a"], op["relation"], op["b"])
            else:
                record = _retire_record(root, known[op["record_id"]])
            validation = validate_record(record, root)
            if not validation.accepted:
                failed.append({**op, "error": "; ".join(validation.reasons)})
                continue
            item = record_item(
                record,
                str(target["project_id"]),
                project_uid=str(target.get("project_uid") or ""),
                binding_id=str(target.get("binding_id") or ""),
            )
            approval_id = stage_retain(root, item, target=target)
            staged.append(
                {
                    **op,
                    "record_id": record.record_id,
                    "approval_id": approval_id,
                    "preview": render_record(record),
                }
            )
        except Exception as exc:
            failed.append({**op, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "staged": staged,
        "failed": failed,
        "reported": reported,
        "dropped": list(plan.get("dropped") or []),
    }


def evolve_note(root: str) -> str:
    """진화 신호 한 줄 요약 — 넛지·doctor 표면용. 신호가 없으면 빈 문자열."""
    with contextlib.suppress(Exception):
        sig = signals(root)
        missing, duplicates = len(sig.get("missing_sources") or []), len(sig.get("near_duplicates") or [])
        if missing or duplicates:
            return (
                f"프로젝트 메모리 진화 신호 — 사라진 출처 {missing}건, 근사 중복 {duplicates}건. "
                "asgard memory project-evolve로 검토"
            )
    return ""


__all__ = [
    "MERGE_FLOOR",
    "apply_evolve",
    "evolve_note",
    "plan_evolve",
    "signals",
    "validate_ops",
]
