"""문서 인제스트 — 사람이 던진 문서를 프로젝트 메모리가 받을 수 있는 모양으로 만든다.

사람들은 명령어를 치지 않는다. "이 문서 분석해서 프로젝트에 넣어줘" 하고 파일을 던진다.
그 한 문장이 도달해야 하는 판단이 넷이고, 셋은 코드가 결정론으로 답할 수 있다:

  ① 무슨 파일인가        — 확장자별 추출기 (pdf·docx·hwp·hwpx·md·txt)
  ② 어떤 종류의 문서인가  — 형상으로 판정 (요구사항 ID 밀도·절 번호·표·결정 어휘)
  ③ 무엇이 엔티티인가     — 요구사항 ID·표제 (정규식. LLM 추측이 아니다)
  ④ 승인할 것인가        — 사람 몫. 팀 공유 스코프의 쓰기는 언제나 사람을 지난다

②가 전략을 정한다. 요구사항·설계처럼 **정적이고 큰** 문서는 `document` 전략(hindsight
chunks 모드 — LLM 추출 없이 원문 청크 저장)으로, 결정·사건처럼 **관계가 중요한** 짧은 것은
`record` 전략(LLM 추출 + 관찰 통합)으로 보낸다. 한 프로젝트 = 한 뱅크이고, 갈리는 것은
뱅크가 아니라 아이템이다 (hindsight `MemoryItem.strategy`).

판정이 틀릴 수 있으므로 언제나 사람이 덮어쓸 수 있다 — 자동은 기본값이지 구속이 아니다.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re

from .records import MAX_ARTIFACT_BYTES

# hindsight 뱅크 설정에 심는 전략 표. 이름은 우리가 정하고, 값은 서버의 hierarchical 필드다.
STRATEGIES = {
    # 정적 대용량 — LLM 추출을 건너뛰고 원문 청크를 그대로 둔다. 우리 신뢰 게이트가
    # 어차피 원문만 받으므로 추출된 사실은 쓰이지 않는다 (돈 주고 버리는 셈이었다).
    "document": {"retain_extraction_mode": "chunks", "retain_chunk_size": 3000},
    # 관계가 중요한 짧은 것 — 추출과 관찰 통합이 실제로 값을 한다.
    "record": {"retain_extraction_mode": "concise"},
}
DEFAULT_STRATEGY = "document"

MAX_DOCUMENT_BYTES = 64 * 1024 * 1024  # 추출 입력 상한 (agent.tools 와 같은 자리)
MAX_ENTITIES = 40
SUPPORTED = (".pdf", ".docx", ".hwp", ".hwpx", ".md", ".markdown", ".txt", ".rst")

# 요구사항 ID — 실제 문서에서 쓰이는 모양. "METER-001", "REQ-12", "SRS-3.2.1"
_REQ_ID = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,4}(?:\.\d{1,3})*)\b")
# 같은 모양이지만 요구사항이 아닌 것들 — 규격·표준 이름. 26-07-28 실측: DLMS 문서에서
# RS-485·CRC-16 이 REQUIREMENT 로 잡혔다. 형상이 같으니 형상으로는 못 가른다 — 근거를 더 본다.
_REQ_ID_LABEL = re.compile(
    # 실제 문서는 "**요구사항 ID**: METER-001" 처럼 굵게 표시가 라벨과 콜론 사이에 낀다.
    # 콜론 앞뒤 양쪽에서 마크다운 강조를 흘려보낸다.
    r"(?:요구사항\s*ID|요구\s*번호|Requirement\s*ID|REQ\s*ID)\s*\**\s*[:：]?\s*\**\s*"
    r"([A-Z][A-Z0-9]{1,9}-\d{1,4}(?:\.\d{1,3})*)",
    re.IGNORECASE,
)
_REQ_ID_MIN_OCCURRENCES = 3  # 표제 + 상호참조 — 진짜 요구사항 ID 는 문서 안에서 반복된다
# 절 번호 — "## 3.2 제목" / "3.2.1 제목"
_SECTION = re.compile(r"^#{0,6}\s*(\d+(?:\.\d+){0,3})\s+\S", re.MULTILINE)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
# 결정문의 어휘 — 이게 짙으면 record 다
_DECISION = re.compile(
    r"결정(했|한다|사항)|채택(했|한다)|기각(했|한다)|합의(했|한다)|decided|adopted|rejected|"
    r"장애|사고|원인|재발\s*방지|postmortem|incident|root\s*cause",
    re.IGNORECASE,
)
# 요구사항·설계문의 어휘
_SPEC = re.compile(
    r"요구사항|수용\s*기준|제약|규격|사양|인터페이스|프로토콜|아키텍처|설계|기획|"
    r"requirement|acceptance\s*criteria|specification|architecture|protocol|shall\b|must\b",
    re.IGNORECASE,
)


class IngestError(ValueError):
    """인제스트 계약 위반 — 미지원 형식·빈 문서·과대 파일."""


@dataclasses.dataclass(frozen=True)
class IngestedDocument:
    """추출·판정이 끝난 문서. 등록은 아직 하지 않았다 (승인 전 상태)."""

    path: str
    name: str
    text: str
    suffix: str
    bytes_in: int
    strategy: str
    kind: str
    entities: tuple[tuple[str, str], ...]
    signals: dict
    content_hash: str

    @property
    def document_id(self) -> str:
        """같은 파일을 다시 던지면 같은 id — update_mode=replace 가 갈아끼운다."""
        return f"asgard:doc:{hashlib.sha256(self.name.encode()).hexdigest()[:24]}"


# ── ① 추출 ────────────────────────────────────────────────────────────────────


def extract_text(path: str) -> str:
    """문서 → 평문. 형식별 추출기는 agent.tools 의 것을 재사용한다 (단일 출처).

    던져지는 문서는 저장소 밖에 있을 수 있으므로 경로를 프로젝트 안으로 가두지 않는다 —
    대신 크기 상한과 아카이브 안전 검사는 그대로 통과시킨다."""
    suffix = os.path.splitext(path)[1].lower()
    if suffix not in SUPPORTED:
        raise IngestError(f"지원하지 않는 형식: {suffix or '(확장자 없음)'} — {', '.join(SUPPORTED)}")
    if not os.path.isfile(path):
        raise IngestError(f"파일이 없다: {path}")
    if os.path.getsize(path) > MAX_DOCUMENT_BYTES:
        raise IngestError(f"문서가 {MAX_DOCUMENT_BYTES // (1024 * 1024)}MiB 상한을 넘는다")
    if suffix in (".md", ".markdown", ".txt", ".rst"):
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    from ..agent.tools import _extract_docx, _extract_hwp, _extract_hwpx, _extract_pdf

    extractors = {".pdf": _extract_pdf, ".docx": _extract_docx, ".hwpx": _extract_hwpx, ".hwp": _extract_hwp}
    try:
        return extractors[suffix](path)
    except Exception as exc:  # ToolError 포함 — 호출측은 IngestError 하나만 알면 된다
        raise IngestError(f"{suffix[1:].upper()} 추출 실패: {exc}") from exc


# ── ② 종류 판정 (결정론) ──────────────────────────────────────────────────────


def classify(text: str, name: str = "") -> tuple[str, str, dict]:
    """(strategy, kind, signals) — 형상만 본다. LLM 없음.

    가르는 축은 "크고 정적인가" 대 "짧고 관계적인가"다. 요구사항 ID 가 여럿이거나 절 번호·표가
    빽빽하면 앞쪽, 결정·사고 어휘가 짙고 짧으면 뒤쪽. 애매하면 document 로 둔다 — 잘못 넣어
    LLM 추출비를 무는 것보다, 원문을 그대로 두고 사람이 나중에 승격하는 편이 되돌리기 쉽다."""
    body = text or ""
    req_ids = set(_REQ_ID.findall(body))
    sections = len(_SECTION.findall(body))
    tables = len(_TABLE_ROW.findall(body))
    decision = len(_DECISION.findall(body))
    spec = len(_SPEC.findall(body))
    length = len(body)
    signals = {
        "chars": length,
        "requirement_ids": len(req_ids),
        "sections": sections,
        "table_rows": tables,
        "decision_terms": decision,
        "spec_terms": spec,
    }
    lowered = name.lower()
    if any(word in lowered for word in ("결정", "decision", "adr", "postmortem", "장애", "incident")):
        return "record", "decision", signals
    if any(word in lowered for word in ("요구", "requirement", "spec", "설계", "design", "기획", "규격", "프로토콜")):
        return "document", "specification", signals
    # 짧고 결정 어휘가 스펙 어휘보다 짙으면 record
    if length < 4000 and decision > spec:
        return "record", "decision", signals
    if req_ids or sections >= 5 or tables >= 5 or length >= 8000:
        return "document", "specification", signals
    return DEFAULT_STRATEGY, "artifact", signals


# ── ③ 엔티티 (결정론) ─────────────────────────────────────────────────────────


def extract_entities(text: str) -> tuple[tuple[str, str], ...]:
    """문서에서 확정 엔티티를 뽑는다 — 요구사항 ID 만. 추측하지 않는다.

    hindsight 의 chunks 모드에서는 서버가 엔티티를 추출하지 않으므로 여기서 준 것이 **유일한**
    엔티티 출처다 (fact_extraction._extract_facts_chunks 독스트링). 그래서 정규식으로 확실한
    것만 올린다 — 문서 제목이나 사람 이름처럼 형상으로 못 가르는 것은 넣지 않는다."""
    body = text or ""
    # ① 명시 라벨이 붙은 것은 확실하다
    labelled = {match.upper() for match in _REQ_ID_LABEL.findall(body)}
    # ② 라벨이 없으면 반복 횟수로 가른다. 규격 이름(RS-485)은 한두 번 스치고 지나가지만
    #    요구사항 ID 는 자기 절 표제와 다른 절의 상호참조에 거듭 나온다.
    counts: dict[str, int] = {}
    for match in _REQ_ID.findall(body):
        counts[match] = counts.get(match, 0) + 1
    repeated = {name for name, count in counts.items() if count >= _REQ_ID_MIN_OCCURRENCES}
    seen: list[tuple[str, str]] = []
    for name in _REQ_ID.findall(body):  # 문서 등장 순서를 유지한다
        if name not in labelled and name not in repeated:
            continue
        pair = (name, "REQUIREMENT")
        if pair not in seen:
            seen.append(pair)
        if len(seen) >= MAX_ENTITIES:
            break
    return tuple(seen)


# ── 조립 ──────────────────────────────────────────────────────────────────────


def prepare(path: str, *, strategy: str | None = None) -> IngestedDocument:
    """문서 하나를 등록 직전 상태까지 만든다. 쓰기 없음.

    strategy 를 명시하면 자동 판정을 덮는다 — 자동은 기본값이지 구속이 아니다."""
    text = extract_text(path)
    if not text.strip():
        raise IngestError("추출된 텍스트가 없다 (스캔 PDF 라면 OCR 이 필요하다)")
    name = os.path.basename(path)
    auto_strategy, kind, signals = classify(text, name)
    chosen = (strategy or auto_strategy).strip().lower()
    if chosen not in STRATEGIES:
        raise IngestError(f"알 수 없는 전략: {chosen} — {', '.join(STRATEGIES)}")
    return IngestedDocument(
        path=os.path.abspath(path),
        name=name,
        text=text,
        suffix=os.path.splitext(path)[1].lower(),
        bytes_in=os.path.getsize(path),
        strategy=chosen,
        kind=kind,
        entities=extract_entities(text),
        signals={**signals, "auto_strategy": auto_strategy, "overridden": bool(strategy)},
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def plan(paths: list[str], *, strategy: str | None = None) -> tuple[list[IngestedDocument], list[dict]]:
    """여러 문서를 한 번에 준비한다. 반환 = (준비된 것, 못 읽은 것). 쓰기 없음."""
    ready: list[IngestedDocument] = []
    failed: list[dict] = []
    for path in paths:
        try:
            ready.append(prepare(path, strategy=strategy))
        except IngestError as exc:
            failed.append({"path": path, "error": str(exc)})
    return ready, failed


def document_item(document: IngestedDocument, project_id: str, *, project_uid: str = "", binding_id: str = "") -> dict:
    """hindsight 가 받는 아이템 한 벌. 전략과 확정 엔티티를 실어 보낸다.

    본문은 **원문 그대로**다 — 요약하지 않는다. 요약은 되돌릴 수 없고, 무엇이 빠졌는지
    나중에 알 방법이 없다. 크기 상한은 서버 청킹이 감당한다."""
    header = (
        f"[ProjectDocument:{document.kind}]\n"
        f"Name: {document.name}\n"
        f"Format: {document.suffix[1:] or 'text'}\n"
        f"Content-SHA256: {document.content_hash}\n"
        f"Strategy: {document.strategy}\n\n"
    )
    return {
        "content": header + document.text,
        "context": f"asgard project document {document.kind}",
        "document_id": document.document_id,
        "update_mode": "replace",  # 같은 문서를 다시 던지면 갈아끼운다 (교정 경로)
        "strategy": document.strategy,
        "timestamp": "unset",  # 규격·요구사항에는 발생 시각이 없다
        "tags": [f"project:{project_id}", "document", f"kind:{document.kind}"],
        "entities": [{"text": name, "type": kind} for name, kind in document.entities],
        "metadata": {
            "source": f"document:{document.name}",
            "source_revision": document.content_hash[:16],
            "content_hash": document.content_hash,
            "ontology_type": "project-document",
            "origin": "ingest",
            "kind": document.kind,
            "strategy": document.strategy,
            "scope": "project",
            "status": "active",
            "confidence": "verified",
            "project_uid": project_uid,
            "binding_id": binding_id,
        },
    }


def oversized(document: IngestedDocument) -> bool:
    """Git 정본으로 두기엔 큰가 — 사본 보관 여부 판단에 쓴다."""
    return len(document.text.encode()) > MAX_ARTIFACT_BYTES


__all__ = [
    "DEFAULT_STRATEGY",
    "STRATEGIES",
    "SUPPORTED",
    "IngestError",
    "IngestedDocument",
    "classify",
    "document_item",
    "extract_entities",
    "extract_text",
    "oversized",
    "plan",
    "prepare",
]


# ── 등록 (승인 게이트 경유) ────────────────────────────────────────────────────


def ensure_strategies(cfg: dict) -> dict:
    """뱅크 설정에 전략 표를 심는다. 이미 같으면 건드리지 않는다.

    전략은 뱅크 설정에 이름으로 살고 아이템은 이름만 참조한다 — 그래서 한 프로젝트(=한 뱅크)
    안에서 문서마다 다른 처리가 가능하다. 뱅크를 나눌 일이 아니다."""
    from ..project_memory_backends import get_backend

    backend = get_backend(cfg)
    try:
        current = backend.bank_config().get("retain_strategies") or {}
        if all(current.get(name) == body for name, body in STRATEGIES.items()):
            return {"changed": False, "strategies": current}
        merged = {**current, **STRATEGIES}
        backend.update_bank_config({"retain_strategies": merged, "retain_default_strategy": DEFAULT_STRATEGY})
        return {"changed": True, "strategies": merged}
    finally:
        backend.close()


def stage_documents(root: str, cfg: dict, documents: list[IngestedDocument]) -> list[dict]:
    """준비된 문서를 승인 대기로 올린다. 여기서 등록하지 않는다 — 팀 공유 스코프다."""
    from ..memory_bridge import backend_target, stage_retain

    target = backend_target(cfg)
    staged: list[dict] = []
    for document in documents:
        item = document_item(
            document,
            str(target["project_id"]),
            project_uid=str(target.get("project_uid") or ""),
            binding_id=str(target.get("binding_id") or ""),
        )
        staged.append(
            {
                "name": document.name,
                "kind": document.kind,
                "strategy": document.strategy,
                "entities": len(document.entities),
                "chars": len(document.text),
                "document_id": document.document_id,
                "approval_id": stage_retain(root, item, target=target),
            }
        )
    return staged
