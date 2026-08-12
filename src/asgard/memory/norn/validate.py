"""결정적 검증 — LLM이 낸 op 목록에서 기계가 확인한 것만 남긴다.

캡·유사도 플로어·링크 대역·통찰 검사가 여기 모여 있다. LLM의 주장은 검증 입력일 뿐이고,
통과 못 한 op는 사유와 함께 기각 목록으로 나간다.
"""

from __future__ import annotations

import contextlib

from ..pages import lint
from ..policy import _memory_settings, scan_secrets, scan_threats
from ..recall import _containment, _jaccard
from ..store import _read, poisoned, valid_slug
from .insight import (
    _FORBIDDEN_INSIGHT,
    INSIGHT_GROUNDING_FLOOR,
    INSIGHT_MAX_CHARS,
    INSIGHT_MAX_SOURCES,
    INSIGHT_MIN_SOURCES,
    _confidence,
    _insight_grounding,
    _polarity_conflict,
)

MERGE_FLOOR = 0.25  # merge 결정적 유사도 플로어 — LLM 주장과 무관하게 코드가 본다
MAX_MERGES, MAX_ARCHIVES, MAX_INSIGHTS, MAX_CONTRADICTIONS = 3, 3, 2, 3
# 링크는 파괴적이지 않아(페이지가 안 지워진다) 캡이 넉넉하다. 그래도 상한은 둔다 —
# 전부를 전부에 잇는 그래프는 아무것도 안 잇는 그래프와 회수 성능이 같다.
MAX_LINKS = 6
# 링크 근거 대역 — 아래는 남남, 위는 링크가 아니라 병합이다
# (LLM이 link로 merge를 피해가는 길을 막는 상한).
#
# 대역이 척도마다 다른 게 핵심이다. 어휘 유사도와 코사인은 같은 기준으로 잴 수 없다:
# MERGE_FLOOR 0.25는 어휘 척도에서 뽑은 값인데, 같은 0.25를 코사인에 대면 의미가 통하는
# 거의 모든 쌍이 병합 대상으로 잘못 분류된다 — 이 저장소 실측이 이미 말해 준다
# (recall.SEM_FLOOR 주석: 교차언어 정답조차 절대 코사인 0.18–0.29). 한 상수를 두 척도에
# 돌려쓰면 대역이 사라진다.
LINK_BAND_LEXICAL = (0.12, MERGE_FLOOR)
LINK_BAND_SEMANTIC = (0.25, 0.80)


def _merge_floor() -> float:
    try:
        v = _memory_settings().get("norn_merge_floor")
        return float(v) if v is not None else MERGE_FLOOR
    except Exception:
        return MERGE_FLOOR


def _existing_links(meta: dict) -> set[str]:
    return {s.strip() for s in str(meta.get("links") or "").split(",") if s.strip()}


def _relatedness(d: str, a: str, b: str, pa: tuple[dict, str], pb: tuple[dict, str]) -> tuple[float, str]:
    """두 페이지의 근접도와 **어느 자로 쟀는지** — ("semantic"|"lexical"). 척도를 같이 돌려주는
    이유는 대역이 척도마다 다르기 때문이다 (LINK_BAND_* 참조).

    링크는 **말이 다른데 관련된** 것을 잇는 연산이라 어휘만으로 재면 잴 수가 없다("릴리스
    태그 규칙"과 "배포 전 확인 목록"은 겹치는 낱말이 거의 없다). 그래서 벡터가 있으면 그걸
    본다. 벡터가 없을 때만 어휘로 내려오고, 그 경우 링크는 보수적으로 덜 생긴다 — 근거 없이
    잇느니 안 잇는 쪽이다."""
    with contextlib.suppress(Exception):
        from ... import memory_semantic as sem
        from ..index import _db

        if sem.active():
            conn = _db(d)
            rows = {
                row[0]: sem.unpack(row[1])
                for row in conn.execute("SELECT slug, data FROM vec WHERE slug IN (?,?)", (a, b)).fetchall()
            }
            conn.close()
            if a in rows and b in rows:
                return max(0.0, sem.cosine(rows[a], rows[b])), "semantic"
    ta = pa[0].get("title", "") + " " + pa[1]
    tb = pb[0].get("title", "") + " " + pb[1]
    return max(_containment(ta, tb), _jaccard(ta, tb)), "lexical"


def validate_ops(ops: list[dict], d: str) -> tuple[list[dict], list[dict]]:
    """결정적 검증 — 통과한 op와 (op, 기각 사유). LLM 주장은 검증 입력일 뿐이다."""
    floor = _merge_floor()
    lint_findings = lint(d)
    decay_ok = {f["slug"] for f in lint_findings if f["code"] == "decay-candidate"}
    accepted: list[dict] = []
    dropped: list[dict] = []
    counts = {"merge": 0, "archive": 0, "insight": 0, "contradiction": 0, "link": 0}
    caps = {
        "merge": MAX_MERGES,
        "archive": MAX_ARCHIVES,
        "insight": MAX_INSIGHTS,
        "contradiction": MAX_CONTRADICTIONS,
        "link": MAX_LINKS,
    }

    def _drop(op: dict, reason: str) -> None:
        dropped.append({"op": op, "reason": reason})

    def _clean(slug: object) -> tuple[dict, str] | None:
        if not isinstance(slug, str) or not valid_slug(slug):
            return None
        pg = _read(d, slug)
        return pg if pg and not poisoned(*pg) else None

    for op in ops:
        kind = str(op.get("op") or "")
        if kind not in counts:
            _drop(op, f"unknown op: {kind!r}")
            continue
        if counts[kind] >= caps[kind]:
            _drop(op, f"cap reached: {kind} ≤ {caps[kind]}")
            continue
        if kind == "merge":
            src, dst = op.get("src"), op.get("dst")
            ps, pd = _clean(src), _clean(dst)
            if not ps or not pd or src == dst:
                _drop(op, "merge: src/dst missing, poisoned, or identical")
                continue
            if ps[0].get("kind") == "user" and pd[0].get("kind") != "user":
                _drop(op, "merge: user page must not merge into non-user page")
                continue
            a = ps[0].get("title", "") + " " + ps[1]
            b = pd[0].get("title", "") + " " + pd[1]
            sim = max(_containment(a, b), _jaccard(a, b))
            if sim < floor:
                _drop(op, f"merge: similarity {sim:.2f} < floor {floor:.2f} (deterministic backstop)")
                continue
            accepted.append(
                {"op": "merge", "src": src, "dst": dst, "sim": round(sim, 2), "why": str(op.get("why", ""))[:200]}
            )
        elif kind == "link":
            a, b = op.get("a"), op.get("b")
            pa, pb = _clean(a), _clean(b)
            if not pa or not pb or a == b:
                _drop(op, "link: a/b missing, poisoned, or identical")
                continue
            if b in _existing_links(pa[0]) and a in _existing_links(pb[0]):
                _drop(op, "link: already linked")
                continue
            sim, scale = _relatedness(d, str(a), str(b), pa, pb)
            low, high = LINK_BAND_SEMANTIC if scale == "semantic" else (LINK_BAND_LEXICAL[0], floor)
            if sim < low:
                _drop(op, f"link: {scale} relatedness {sim:.2f} < floor {low:.2f} (deterministic backstop)")
                continue
            if sim >= high:
                _drop(op, f"link: {scale} relatedness {sim:.2f} ≥ {high:.2f} — propose merge, not link")
                continue
            accepted.append(
                {
                    "op": "link",
                    "a": a,
                    "b": b,
                    "sim": round(sim, 2),
                    "scale": scale,
                    "why": str(op.get("why", ""))[:200],
                }
            )
        elif kind == "archive":
            slug = op.get("slug")
            if not isinstance(slug, str) or slug not in decay_ok:
                _drop(op, "archive: only lint decay-candidates are eligible")
                continue
            accepted.append({"op": "archive", "slug": slug, "why": str(op.get("why", ""))[:200]})
        elif kind == "insight":
            title = str(op.get("title") or "").strip()[:80]
            text = str(op.get("text") or "").strip()
            sources = [s for s in (op.get("sources") or []) if isinstance(s, str)]
            sources = list(dict.fromkeys(sources))
            if not title or not text or len(text) > INSIGHT_MAX_CHARS:
                _drop(op, "insight: missing/oversized title or text")
                continue
            if not (INSIGHT_MIN_SOURCES <= len(sources) <= INSIGHT_MAX_SOURCES):
                _drop(op, f"insight: needs {INSIGHT_MIN_SOURCES}–{INSIGHT_MAX_SOURCES} distinct sources")
                continue
            pages = [_clean(s) for s in sources]
            if any(pg is None for pg in pages):
                _drop(op, "insight: source page missing or poisoned")
                continue
            if _FORBIDDEN_INSIGHT.search(title + " " + text):
                _drop(op, "insight: forbidden capture (env-dependent/tool-negativity/credential)")
                continue
            threat = scan_threats(text, title) or scan_secrets(text, title)
            if threat:
                _drop(op, f"insight: {threat}")
                continue
            # 소스가 실존한다는 것과 통찰이 그 소스에서 나왔다는 것은 다른 말이다.
            score, per_source = _insight_grounding(title, text, [pg for pg in pages if pg])
            if score < INSIGHT_GROUNDING_FLOOR:
                _drop(op, f"insight: not grounded in its sources ({score:.2f} < {INSIGHT_GROUNDING_FLOOR})")
                continue
            if (weakest := min(per_source, default=0.0)) <= 0:
                idle = sources[per_source.index(weakest)]
                _drop(op, f"insight: source [[{idle}]] contributes nothing — not a cross-page pattern")
                continue
            row = {
                "op": "insight",
                "title": title,
                "text": text,
                "sources": sources,
                "grounding": round(score, 3),
                "confidence": _confidence(len(sources)),
                "why": str(op.get("why", ""))[:200],
            }
            # 근거 점수가 높다는 것은 출처의 어휘를 썼다는 뜻이지 출처에 동의한다는 뜻이 아니다.
            # 표식이지 기각이 아닌 이유는 _polarity_conflict 독스트링에 있다 — 이 신호는
            # 자동 승격을 막을 만큼은 강하지만 후보 지식을 없앨 만큼 정밀하지는 않다.
            if conflict := _polarity_conflict(title, text, [pg for pg in pages if pg]):
                word, side = conflict
                row["polarity_conflict"] = f"{word}: {side}"
            accepted.append(row)
        else:  # contradiction — 보고 전용, 페이지 실존만 확인
            a, b = op.get("a"), op.get("b")
            if not _clean(a) or not _clean(b) or a == b:
                _drop(op, "contradiction: pages missing, poisoned, or identical")
                continue
            accepted.append({"op": "contradiction", "a": a, "b": b, "why": str(op.get("why", ""))[:200]})
        counts[kind] += 1
    return accepted, dropped
