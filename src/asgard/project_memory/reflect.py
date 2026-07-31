"""프로젝트 메모리 회고 — backend LLM이 있으면 그쪽, 없으면 여기서 합성한다.

Hindsight의 reflect는 **서버의 LLM**이 뱅크 전체를 근거로 답을 만든다. 그런데 서버는
환경마다 다르다 — 사내 게이트웨이가 안 붙은 인스턴스, LLM 없이 색인만 도는 배포, 키가
만료된 서버. 그때 reflect는 실패하고, 2차 메모리는 "저장은 되는데 물어볼 수는 없는" 상태가
된다. 저장된 지식이 그대로 있는데 답만 못 하는 건 서버 사정이지 지식의 사정이 아니다.

그래서 판정을 이렇게 나눈다.
  backend — 서버 LLM이 답한다 (기본. 뱅크 전체를 보는 건 서버가 더 잘한다)
  local   — 이쪽 provider가 답한다. 근거는 **Git 정본 record**와 backend의 검색 히트다
  auto    — backend를 먼저 시도하고, 못 하면 local로 내려간다 (기본값)

local 경로가 근거로 삼는 것은 Git 정본이다. backend는 재생 가능한 검색 인덱스일 뿐이고
정본은 `.asgard/memory/records/`에 있다 — 서버가 아무것도 못 해도 근거는 여기 남아 있다.
어느 경로로 답했는지는 언제나 산출에 실어 보낸다. 자문의 출처를 숨기면 자문이 아니다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

BUDGET_K = {"low": 5, "mid": 10, "high": 20}
MODES = ("auto", "backend", "local")
MAX_EVIDENCE_CHARS = 1200
MAX_PROMPT_CHARS = 24000

_REFLECT_SYS = """You answer a question about one software project using only the evidence below.

The evidence is Git-canonical project records and search hits from this project's memory bank.
Rules:
- Answer in the language of the question. Be short and concrete.
- Cite the record ids you used, in brackets, next to the claim they support.
- If the evidence does not answer the question, say exactly that and name which file or record
  would settle it. Never fill a gap with a plausible guess — this output is advice, not evidence."""


class ReflectUnavailable(RuntimeError):
    """backend도 local도 답할 수 없다 — 호출측이 사용자에게 처방을 보여줄 신호."""


def reflect_mode(cfg: Mapping[str, object] | None) -> str:
    """[project_memory].reflect — auto|backend|local. 미설정/오설정은 auto."""
    raw = str((cfg or {}).get("reflect") or "auto").strip().lower()
    return raw if raw in MODES else "auto"


def _words(text: str) -> set[str]:
    return {word.lower() for word in re.split(r"[^\w가-힣]+", text) if len(word) >= 2}


def _score(question_words: set[str], text: str) -> int:
    return len(question_words & _words(text))


def canonical_evidence(root: str, question: str, k: int) -> list[dict]:
    """Git 정본 record 중 질문과 겹치는 것들 — 결정론 렉시컬 랭킹 (LLM 없음)."""
    from .canonical import load_canonical_records

    try:
        loaded = load_canonical_records(root)
    except Exception:
        return []  # 손상 record 하나가 회고 전체를 막지 않는다 (lint가 따로 보고한다)
    question_words = _words(question)
    ranked: list[tuple[int, dict]] = []
    for record, path, _digest in loaded:
        if record.status != "active":
            continue
        haystack = f"{record.title}\n{record.content}\n{record.source}"
        score = _score(question_words, haystack)
        if not score:
            continue
        ranked.append(
            (
                score,
                {
                    "id": record.record_id,
                    "title": record.title,
                    "kind": record.kind,
                    "source": record.source,
                    "path": path,
                    "text": record.content[:MAX_EVIDENCE_CHARS],
                    "origin": "canonical",
                },
            )
        )
    ranked.sort(key=lambda row: (-row[0], row[1]["id"]))
    return [row[1] for row in ranked[:k]]


def backend_evidence(backend, question: str, k: int) -> list[dict]:
    """backend 검색 히트 — LLM 없이도 도는 렉시컬·벡터 경로. 실패는 빈 리스트."""
    try:
        hits = backend.recall(question, max_results=k)
    except Exception:
        return []
    return [
        {
            "id": hit.document_id or f"hit:{index}",
            "title": str((hit.metadata or {}).get("title") or ""),
            "kind": str((hit.metadata or {}).get("kind") or ""),
            "source": str((hit.metadata or {}).get("source") or ""),
            "path": "",
            "text": hit.text[:MAX_EVIDENCE_CHARS],
            "origin": "backend-search",
        }
        for index, hit in enumerate(hits)
    ]


def gather_evidence(root: str, backend, question: str, budget: str = "low") -> list[dict]:
    """local 합성용 근거 — Git 정본 우선, backend 검색 히트로 보강. record_id로 중복 제거."""
    k = BUDGET_K.get(budget, BUDGET_K["low"])
    rows = canonical_evidence(root, question, k)
    seen = {row["id"] for row in rows}
    for row in backend_evidence(backend, question, k):
        if row["id"] not in seen:
            seen.add(row["id"])
            rows.append(row)
    return rows[: k * 2]


def _complete(root: str, system: str, user: str, max_tokens: int) -> str:
    """LLM 단발 호출 간접점 — 테스트가 이 지점만 대체한다. 메인 provider를 쓴다."""
    from ..agent.oneshot import complete_once

    return complete_once(root, system, user, max_tokens=max_tokens)


def local_reflect(root: str, backend, question: str, budget: str = "low", max_tokens: int = 2048) -> dict:
    """이쪽 provider로 합성한다. 근거가 없으면 합성하지 않고 그렇게 보고한다."""
    import json

    evidence = gather_evidence(root, backend, question, budget)
    if not evidence:
        return {
            "text": "",
            "based_on": {"memories": []},
            "source": "local",
            "detail": "no canonical record or backend hit matched the question",
        }
    payload = json.dumps({"question": question, "evidence": evidence}, ensure_ascii=False)[:MAX_PROMPT_CHARS]
    try:
        text = _complete(root, _REFLECT_SYS, payload, max_tokens).strip()
    except Exception as exc:
        raise ReflectUnavailable(
            f"the backend has no reflect LLM and the local provider is unusable: {type(exc).__name__}: {exc}"
        ) from exc
    return {
        "text": text,
        "based_on": {
            "memories": [{"id": row["id"], "title": row["title"], "origin": row["origin"]} for row in evidence]
        },
        "source": "local",
        "detail": f"{len(evidence)} evidence item(s)",
    }


def reflect(root: str, backend, question: str, budget: str = "low", cfg: Mapping[str, object] | None = None) -> dict:
    """설정된 모드로 회고한다. 반환에는 언제나 어느 경로가 답했는지(source)가 실린다."""
    if budget not in BUDGET_K:
        raise ValueError("reflect budget must be low|mid|high")
    mode = reflect_mode(cfg)
    if mode == "local":
        return local_reflect(root, backend, question, budget)
    backend_reflect = getattr(backend, "reflect", None)
    if not callable(backend_reflect):
        if mode == "backend":
            raise ReflectUnavailable(f"backend '{backend.engine}' does not support reflect")
        return local_reflect(root, backend, question, budget)
    try:
        output = dict(backend_reflect(question, budget=budget))
        if str(output.get("text") or "").strip():
            return {**output, "source": "backend"}
        reason = "backend reflect returned an empty answer"
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
    if mode == "backend":
        raise ReflectUnavailable(f"backend reflect failed: {reason}")
    # auto — 서버가 못 하면 이쪽이 한다. 왜 내려왔는지를 산출에 남긴다.
    fallback = local_reflect(root, backend, question, budget)
    fallback["detail"] = f"{fallback['detail']} · backend fallback: {reason}"
    return fallback
