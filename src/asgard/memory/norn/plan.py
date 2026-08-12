"""계획 — 증거 카드 수집 → LLM 델타 제안 → 결정적 검증. 쓰기 없음.

`_complete` 하나가 LLM 왕복의 간접점이라 시험은 이 지점만 대체한다.
"""

from __future__ import annotations

import json

from ..contradiction import ACKNOWLEDGED, open_contradictions
from ..pages import lint
from ..policy import memory_dir
from ..store import _pages, _read, ensure_home, poisoned
from ..usage import merged as usage_merged
from .validate import validate_ops

# LLM행 기본 프롬프트는 영어 정본 — 사람 표면은 한국어 유지.
_NORN_SYS = (
    "You are the Norn tender of Yggdrasil, a personal memory wiki. Review the page catalog "
    "and propose a SMALL set of consolidation deltas. You never rewrite the library wholesale: "
    "you emit deltas only, and deterministic code validates and applies them.\n\n"
    "Allowed operations (JSON array `ops`):\n"
    '- {"op":"merge","src":"<slug>","dst":"<slug>","why":"..."} — src is absorbed into dst, then '
    "src is removed. Only when both pages state the same fact or one strictly contains the other.\n"
    '- {"op":"archive","slug":"<slug>","why":"..."} — retire a stale page (kept restorable). Only '
    "slugs listed under `decay_candidates` are eligible; anything else will be dropped.\n"
    '- {"op":"insight","title":"...","text":"...","sources":["<slug>","<slug>"],"why":"..."} — a NEW '
    "higher-order pattern that is only visible across 2+ existing pages (inductive reasoning: "
    "preferences, tendencies, recurring behaviors). The text must be self-contained, declarative, "
    "grounded ONLY in the listed source pages, and must not merely restate a single page. "
    "Deterministic code checks that grounding: the insight must reuse the concrete vocabulary of "
    "its sources, and EVERY listed source must contribute to it. Do not pad the source list — a "
    "page that the insight does not actually draw on will be rejected as decoration. Code also "
    "checks polarity: an insight that reuses source vocabulary while flipping what the sources "
    "assert (dropping or adding a negation) is rejected. If sources genuinely disagree with each "
    "other, that is a `contradiction` for a human to resolve, not an insight to synthesize.\n"
    '- {"op":"contradiction","a":"<slug>","b":"<slug>","why":"..."} — two pages make incompatible '
    "claims. Report only; a human resolves it. Pairs listed under `acknowledged_contradictions` "
    "have already been reviewed by the human — do not report them again.\n"
    '- {"op":"link","a":"<slug>","b":"<slug>","why":"..."} — two EXISTING pages are related but '
    "distinct: one gives context the other needs, they belong to the same decision, or knowing one "
    "makes the other findable. Do NOT use this for pages that state the same fact — that is a merge.\n\n"
    "Rules:\n"
    '- Output STRICT JSON: {"ops":[...]} and nothing else. No prose, no code fences.\n'
    "- Be conservative. An empty ops list is a valid, common outcome — do not invent work.\n"
    "- Never put environment-dependent failures, negative claims about tools, or credentials in "
    "insight text.\n"
    '- Never merge a page of kind "user" into a page of another kind.\n'
    "- Write insight text in the dominant language of the source pages."
)


# ── 신호 수집 (결정론) ─────────────────────────────────────────────────────────


def signals(d: str | None = None) -> dict:
    """LLM에게 보여줄 증거 카드 — 페이지 카탈로그·usage·lint 판정. 쓰기 없음."""
    d = d or memory_dir()
    # 사람이 실제로 찾은 횟수 — 자동 주입은 여기 안 섞인다 (`memory.usage`). 파일과 DB 중
    # 큰 쪽을 보므로 파생이 방금 날아간 기계에서도 증거 카드가 0을 말하지 않는다.
    uses = {slug: row["uses"] for slug, row in usage_merged(d).items()}
    pages: list[dict] = []
    for slug in _pages(d):
        pg = _read(d, slug)
        if not pg or poisoned(*pg):
            continue  # 오염 페이지는 노른 대상도 아니다 — lint가 threat로 보고한다
        meta, body = pg
        first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        pages.append(
            {
                "slug": slug,
                "title": meta.get("title", slug),
                "kind": meta.get("kind", "note"),
                "updated": meta.get("updated", meta.get("created", "")),
                "uses": int(uses.get(slug, 0)),
                "excerpt": first[:160],
            }
        )
    findings = lint(d)
    return {
        "pages": pages,
        "decay_candidates": sorted({f["slug"] for f in findings if f["code"] == "decay-candidate"}),
        "near_duplicates": [
            f["msg"].replace("≈ ", f"{f['slug']} ≈ ") for f in findings if f["code"] == "near-duplicate"
        ],
        # 사람이 이미 보고 넘긴 어긋남 — 다시 제안해 봐야 장부에서 같은 줄로 접힌다.
        # 증거 카드에 같이 넣으면 LLM 이 애초에 그 쌍을 안 고른다 (`memory.contradiction`).
        "acknowledged_contradictions": [
            {"a": row["a"], "b": row["b"], "note": row["note"]}
            for row in open_contradictions(d, include_acknowledged=True)
            if row["status"] == ACKNOWLEDGED
        ],
    }


# ── 계획 (LLM 제안 → 결정적 검증) ──────────────────────────────────────────────


def _parse_ops(raw: str) -> list[dict]:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("norn: LLM output is not JSON")
    payload = json.loads(raw[start : end + 1])
    ops = payload.get("ops") if isinstance(payload, dict) else None
    if not isinstance(ops, list):
        raise ValueError("norn: LLM output has no ops list")
    return [op for op in ops if isinstance(op, dict)]


def _complete(root: str, system: str, user: str) -> str:
    """LLM 단발 호출 간접점 — 테스트가 이 지점만 대체한다.

    개인 메모리를 손질하는 provider는 memory.manager가 정한다 (기본 = 메인 provider)."""
    from ..manager import complete

    return complete(root, system, user, max_tokens=3000)


def plan_norn(root: str, d: str | None = None) -> dict:
    """신호 수집 → LLM 제안 → 결정적 검증. 반환 = {"ops", "dropped", "signals"}. 쓰기 없음."""
    d = ensure_home(d)
    sig = signals(d)
    if len(sig["pages"]) < 2:
        return {"ops": [], "dropped": [], "signals": sig}
    user = json.dumps(
        {
            "pages": sig["pages"],
            "decay_candidates": sig["decay_candidates"],
            "near_duplicates": sig["near_duplicates"],
            "acknowledged_contradictions": sig["acknowledged_contradictions"],
        },
        ensure_ascii=False,
    )
    raw = _complete(root, _NORN_SYS, user)
    ops = _parse_ops(raw)
    accepted, dropped = validate_ops(ops, d)
    return {"ops": accepted, "dropped": dropped, "signals": sig}
