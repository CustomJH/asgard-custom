"""페이지 CRUD·운영 — add/ingest(승인 plan)·remove/merge·선호 갱신·lint 건강 점검."""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import os
import re

from .index import _db, _fts_upsert, build_index, vec_coverage, write_index
from .policy import memory_dir, scan_secrets, scan_threats
from .recall import _containment, _jaccard, query, section_usage
from .store import (
    DB,
    DEFAULT_KIND,
    INDEX,
    KINDS,
    _atomic_write,
    _fm_value,
    _identity_slot,
    _kind,
    _lock,
    _page_path,
    _pages,
    _read,
    _today,
    ensure_home,
    log_op,
    poisoned,
    render_page,
    slugify,
    valid_slug,
)
from .temporal import ground_event_date

STALE_DAYS = 90  # lint 부패 후보 기준 — 90일 무갱신 + 사용 0회
# ingest 병합 문턱 — containment(포함 계수)로 판정: Jaccard 는 길이 차에 취약해 "같은 사실의
# 패러프레이즈+추가 상세"를 놓친다 (실측 26-07-15: 병합쌍 cont 0.56/0.61 vs 생성쌍 0.00/0.02).
MERGE_CONTAINMENT = 0.45
DUP_JACCARD = 0.60  # lint 중복 의심 문턱 — 대칭 비교라 Jaccard 가 맞다

# ── 쓰기 (add / ingest) — 승인은 CLI 계층, 여기는 기계 검증 + 락 ───────────────────


def _fresh_slug(d: str, base: str, seed: str) -> str:
    """충돌 없는 slug — 이미 있으면 seed 로 접미사를 붙이며 빈 자리까지 반복 (P2, 3번째 충돌 방지)."""
    slug, i = base, 0
    while os.path.exists(_page_path(d, slug)):
        i += 1
        slug = f"{base}-{hashlib.sha1(f'{seed}{i}'.encode()).hexdigest()[:6]}"
    return slug


def add(
    text: str,
    title: str | None = None,
    kind: str = DEFAULT_KIND,
    links: str = "",
    d: str | None = None,
) -> tuple[str, str]:
    """페이지 생성. 반환 = (slug, path). 스캔 위반·잘못된 kind 는 ValueError.

    예산은 저장을 막지 않는다 — 주입면 상한은 "프롬프트에 몇 자 실을지"의 문제고, 지식은
    pages/ 에 남는다. 카탈로그가 꽉 찬 건 lint 가 칸별로 일러준다."""
    d = ensure_home(d)
    if not text.strip():
        raise ValueError("empty memory text")
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind!r} — one of {', '.join(KINDS)}")
    title = _fm_value(title or next((ln.strip().lstrip("# ") for ln in text.splitlines() if ln.strip()), "untitled"))[
        :80
    ]
    links = _fm_value(links)
    threat = scan_threats(text, title, links)  # 본문 + 주입 메타 전부 (P0)
    if threat:
        raise ValueError(f"injection scan: {threat}")
    if secret := scan_secrets(text, title, links):
        raise ValueError(f"secret scan: {secret}")
    with _lock(d):
        slug, path = _add_unlocked(d, text, title, kind, links)
    return slug, path


def _add_unlocked(d: str, text: str, title: str, kind: str, links: str) -> tuple[str, str]:
    """호출자가 _lock(d)을 보유한 add 본체 — ingest create의 락 공백 방지."""
    slug = _fresh_slug(d, slugify(title), text)
    meta = {"title": title, "kind": kind, "created": _today(), "updated": _today()}
    # 사건 시각 — 기록 시각과 다르다. "작년에 정한 규칙"을 오늘 적으면 기록은 오늘, 사건은 작년.
    # 본문은 안 고치고 메타에만 적는다 (temporal.ground_event_date 참조).
    if event := ground_event_date(text):
        meta["event"] = event
    if links:
        meta["links"] = links
    path = _page_path(d, slug)
    _atomic_write(path, render_page(meta, text))
    write_index(d)
    with contextlib.suppress(Exception):
        conn = _db(d)
        with conn:
            _fts_upsert(conn, d, slug)
        conn.close()
    log_op(d, f"add:{kind}", slug)
    return slug, path


def plan_ingest(text: str, d: str | None = None) -> dict:
    """ingest 계획 — 실행 없이 판정만 (CLI 승인 게이트가 이 계획을 사람에게 보여준다).

    ① 같은 정체성 슬롯(이름·호칭·생일…)을 쓰는 user 페이지가 있으면 유사도와 무관하게 그
    페이지로 merge — 단일값 사실은 누적 대상이 아니다. ② 아니면 후보 top-3 중 최대
    containment ≥ MERGE_CONTAINMENT 면 merge, ③ 그 외 create."""
    d = d or memory_dir()
    if slot_plan := _plan_identity_slot(text, d):
        return slot_plan
    best, best_sim = None, 0.0
    for hit in query(text, k=3, d=d, track=False):
        pg = _read(d, hit["slug"])
        if not pg:
            continue
        sim = _containment(text, pg[0].get("title", "") + " " + pg[1])
        if sim > best_sim:
            best, best_sim = hit, sim
    if best and best_sim >= MERGE_CONTAINMENT:
        return {
            "action": "merge",
            "slug": best["slug"],
            "title": best["title"],
            "sim": round(best_sim, 2),
            "rev": _rev(d, best["slug"]),  # 승인 시점 페이지 리비전 — 실행 시 대조 (2차 리뷰 ⑤)
        }
    return {"action": "create", "slug": None, "title": None, "sim": round(best_sim, 2)}


def _plan_identity_slot(text: str, d: str) -> dict | None:
    """같은 슬롯을 이미 가진 user 페이지로의 merge 계획 — 없으면 None.

    슬롯 보유 페이지가 여럿이면(과거 create 누수로 이미 쌓인 모순) 가장 오래된 쪽을 정본으로
    삼고 나머지는 absorb 목록에 실어 같은 승인으로 접는다. 정본 선택은 created→slug 정렬이라
    결정론이다 — 계획을 두 번 세워도 같은 대상이 나온다."""
    slot = _identity_slot(text)
    if not slot:
        return None
    holders = []
    for slug in _pages(d):
        pg = _read(d, slug)
        if not pg or _kind(pg[0]) != "user":
            continue
        if any(_identity_slot(p) == slot for p in re.split(r"\n\s*\n", pg[1].strip())):
            holders.append((str(pg[0].get("created", "")), slug, pg[0].get("title", "")))
    if not holders:
        return None
    holders.sort()
    _, slug, title = holders[0]
    return {
        "action": "merge",
        "slug": slug,
        "title": title,
        "sim": 1.0,
        "rev": _rev(d, slug),
        "slot": slot,
        # 흡수 대상도 승인 시점 리비전을 함께 봉인한다 — 승인과 실행 사이에 바뀐 페이지를 지우지 않는다
        "absorb": [[s, _rev(d, s)] for _, s, _ in holders[1:]],
    }


def _rev(d: str, slug: str) -> str:
    """페이지 리비전 = 원문 sha1 — plan 승인과 실행 사이의 변경 감지용."""
    try:
        with open(_page_path(d, slug), "rb") as handle:
            return hashlib.sha1(handle.read()).hexdigest()[:12]
    except Exception:
        return ""


def _fact_present(body: str, text: str) -> bool:
    """동일 ingest 재실행 탐지. 과거 날짜-prefix 병합분도 같은 사실로 본다."""
    fact = text.strip()
    if not fact:
        return False
    for paragraph in re.split(r"\n\s*\n", body.strip()):
        existing = re.sub(r"^\d{4}-\d{2}-\d{2}:\s*", "", paragraph.strip())
        if existing == fact:
            return True
    return False


_PREFERENCE_PATTERNS = (
    re.compile(r"^(?P<subject>.+?)\s+(?P<key>.+?)(?:로|으로)\s+(?P<value>.+?)(?:을|를)\s+선호"),
    re.compile(r"^(?P<subject>.+?)\s+(?P<value>.+?)(?:을|를)\s+(?P<key>.+?)(?:로|으로)\s+선호"),
)


def _preference_parts(text: str) -> tuple[str, frozenset[str]] | None:
    statement = re.sub(r"^\d{4}-\d{2}-\d{2}:\s*", "", text.strip())
    for pattern in _PREFERENCE_PATTERNS:
        match = pattern.search(statement)
        if not match:
            continue
        key = re.sub(r"\s+", " ", f"{match.group('subject')} {match.group('key')}").strip().casefold()
        values = frozenset(
            value.strip().casefold()
            for value in re.split(r"\s*(?:과|와|및|,)\s*", match.group("value"))
            if value.strip()
        )
        if key and values:
            return key, values
    return None


def _update_user_preference(body: str, text: str) -> tuple[str, str]:
    """동일 슬롯/preference key만 갱신한다. 복합값 축소·다른 key는 보존한다."""
    if slot := _identity_slot(text):
        return _supersede_slot(body, text, slot)
    incoming = _preference_parts(text)
    if incoming is None:
        return body.rstrip() + f"\n\n{_today()}: {text.strip()}", "merged"
    paragraphs = re.split(r"\n\s*\n", body.strip())
    matches = [
        (i, parts[1])
        for i, paragraph in enumerate(paragraphs)
        if (parts := _preference_parts(paragraph)) and parts[0] == incoming[0]
    ]
    if not matches:
        return body.rstrip() + f"\n\n{_today()}: {text.strip()}", "merged"
    old_values = frozenset().union(*(values for _, values in matches))
    new_values = incoming[1]
    if new_values <= old_values:
        return body, "unchanged"
    if old_values.isdisjoint(new_values) or old_values <= new_values:
        first = matches[0][0]
        remove = {i for i, _ in matches[1:]}
        paragraphs[first] = text.strip()
        return "\n\n".join(p for i, p in enumerate(paragraphs) if i not in remove), "updated"
    return body.rstrip() + f"\n\n{_today()}: {text.strip()}", "merged"


def _supersede_slot(body: str, text: str, slot: str) -> tuple[str, str]:
    """같은 슬롯 문단을 새 사실로 교체한다 (append 아님). 슬롯이 없던 페이지면 추가한다."""
    fact = text.strip()
    paragraphs = re.split(r"\n\s*\n", body.strip())
    matches = [i for i, paragraph in enumerate(paragraphs) if _identity_slot(paragraph) == slot]
    if not matches:
        return body.rstrip() + f"\n\n{fact}", "merged"
    first, drop = matches[0], set(matches[1:])
    paragraphs[first] = fact
    updated = "\n\n".join(p for i, p in enumerate(paragraphs) if i not in drop)
    return (body, "unchanged") if updated.strip() == body.strip() else (updated, "updated")


def _absorb_slot_dups(d: str, plan: dict) -> list[str]:
    """계획이 지목한 같은-슬롯 중복 페이지를 접는다 (호출자가 _lock 보유). 반환 = 접힌 slug.

    승인 시점 리비전이 어긋난 페이지는 지우지 않고 남긴다 — 승인 범위 밖의 변경을 삭제로
    덮는 것보다 모순 하나를 lint 로 넘기는 편이 낫다."""
    absorbed: list[str] = []
    for entry in plan.get("absorb") or []:
        slug, rev = (list(entry) + [""])[:2] if isinstance(entry, (list, tuple)) else (entry, "")
        if not (isinstance(slug, str) and valid_slug(slug) and os.path.exists(_page_path(d, slug))):
            continue
        if rev and rev != _rev(d, slug):
            log_op(d, "ingest:absorb-skipped", str(slug), "changed since approval")
            continue
        os.remove(_page_path(d, slug))
        with contextlib.suppress(Exception):
            conn = _db(d)
            with conn:
                for table in ("fts", "usage", "vec"):
                    conn.execute(f"DELETE FROM {table} WHERE slug = ?", (slug,))  # noqa: S608 — 테이블명은 리터럴
            conn.close()
        log_op(d, "ingest:absorbed", str(slug), f"slot={plan.get('slot')}")
        absorbed.append(str(slug))
    return absorbed


def ingest(text: str, kind: str = DEFAULT_KIND, d: str | None = None, plan: dict | None = None) -> tuple[str, str]:
    """자가 학습 쓰기 — plan 대로 생성·병합·선호 갱신·동일 사실 no-op. 반환 = (action, slug).

    plan 을 넘기면(CLI 승인 게이트가 이미 계산·표시한 계획) 재계산하지 않는다 (TOCTOU 차단, P1):
    "승인한 merge 대상"과 "실제 merge 대상"이 갈라지지 않는다."""
    d = ensure_home(d)
    if not text.strip():
        raise ValueError("empty memory text")
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind!r} — one of {', '.join(KINDS)}")
    threat = scan_threats(text)
    if threat:
        raise ValueError(f"injection scan: {threat}")
    if secret := scan_secrets(text):
        raise ValueError(f"secret scan: {secret}")
    with _lock(d):
        approved = plan is not None
        plan = plan or plan_ingest(text, d)
        if approved and plan.get("action") not in ("create", "merge"):
            raise ValueError("invalid approved plan: action must be create or merge")
        if approved and plan.get("action") == "merge":
            if not plan.get("rev"):
                raise ValueError("invalid approved plan: missing revision for merge")
            target = plan.get("slug")
            if not target or not os.path.exists(_page_path(d, target)):
                raise ValueError("stale plan: merge target disappeared — re-run ingest")
        if plan["action"] == "merge" and plan.get("slug") and os.path.exists(_page_path(d, plan["slug"])):
            slug = plan["slug"]
            meta, body = _read(d, slug) or ({}, "")
            # crash가 정본 쓰기 후 approval finish 전에 발생했다면 stale rev보다 idempotence가 우선이다.
            known = _fact_present(body, text)
            # 승인된 plan 은 리비전까지 대조 (2차 리뷰 ⑤) — 승인과 실행 사이 대상이 바뀌었으면 중단
            if not known and approved and plan.get("rev") and plan["rev"] != _rev(d, slug):
                raise ValueError(f"stale plan: page '{slug}' changed since approval — re-run ingest")
            # 같은 슬롯 중복 접기는 정본 본문과 독립이다: 사실이 이미 있어도 모순 페이지는 남아 있다
            absorbed = _absorb_slot_dups(d, plan)
            if known:
                if not absorbed:
                    log_op(d, "ingest:unchanged", slug)
                    return "unchanged", slug
                write_index(d)
                log_op(d, "ingest:updated", slug, f"absorbed={len(absorbed)}")
                return "updated", slug
            meta["updated"] = _today()
            if kind == "user" and _kind(meta) == "user":
                merged, action = _update_user_preference(body, text)
                if action == "unchanged":
                    if absorbed:
                        write_index(d)
                        log_op(d, "ingest:updated", slug, f"absorbed={len(absorbed)}")
                        return "updated", slug
                    log_op(d, "ingest:unchanged", slug)
                    return action, slug
                if action == "updated":
                    meta["title"] = _fm_value(next(ln.strip().lstrip("# ") for ln in text.splitlines() if ln.strip()))[
                        :80
                    ]
            else:
                merged = body.rstrip() + f"\n\n{_today()}: {text.strip()}"
                action = "merged"
            _atomic_write(_page_path(d, slug), render_page(meta, merged))
            write_index(d)
            with contextlib.suppress(Exception):
                conn = _db(d)
                with conn:
                    _fts_upsert(conn, d, slug)
                conn.close()
            log_op(d, f"ingest:{action}", slug, f"sim={plan.get('sim')}")
            return action, slug
        existing = next((slug for slug in _pages(d) if (pg := _read(d, slug)) and _fact_present(pg[1], text)), None)
        if existing:
            log_op(d, "ingest:unchanged", existing)
            return "unchanged", existing
        title = _fm_value(next(ln.strip().lstrip("# ") for ln in text.splitlines() if ln.strip()))[:80]
        slug, _ = _add_unlocked(d, text, title, kind, "")
        log_op(d, "ingest:created", slug)
        return "created", slug


def remove(slug: str, d: str | None = None) -> bool:
    """페이지 삭제 + 파생 재생성 (P2). 반환 = 삭제 성공 여부."""
    d = d or memory_dir()
    if not valid_slug(slug):
        raise ValueError(f"invalid slug: {slug!r}")
    with _lock(d):
        path = _page_path(d, slug)
        if not os.path.exists(path):
            return False
        os.remove(path)
        with contextlib.suppress(Exception):
            conn = _db(d)
            with conn:
                conn.execute("DELETE FROM fts WHERE slug = ?", (slug,))
                conn.execute("DELETE FROM usage WHERE slug = ?", (slug,))
                conn.execute("DELETE FROM vec WHERE slug = ?", (slug,))
            conn.close()
        write_index(d)
        log_op(d, "remove", slug)
    return True


def merge(src: str, dst: str, d: str | None = None) -> str:
    """src 를 dst 에 흡수하고 src 삭제 (P2, 예산 초과 수동 통합). 반환 = dst slug."""
    d = d or memory_dir()
    if not (valid_slug(src) and valid_slug(dst)):
        raise ValueError("invalid slug")
    if src == dst:  # 자기 병합 = 원본 삭제 사고 (2차 리뷰 ③)
        raise ValueError("src and dst are the same page")
    with _lock(d):
        ps, pd = _read(d, src), _read(d, dst)
        if ps is None or pd is None:
            raise ValueError("src or dst not found")
        dmeta, dbody = pd
        dmeta["updated"] = _today()
        merged = dbody.rstrip() + f"\n\n{_today()} (merged from {src}): {ps[1].strip()}"
        _atomic_write(_page_path(d, dst), render_page(dmeta, merged))
        os.remove(_page_path(d, src))
        with contextlib.suppress(Exception):
            conn = _db(d)
            with conn:
                conn.execute("DELETE FROM fts WHERE slug = ?", (src,))
                conn.execute("DELETE FROM usage WHERE slug = ?", (src,))
                conn.execute("DELETE FROM vec WHERE slug = ?", (src,))
                _fts_upsert(conn, d, dst)
            conn.close()
        write_index(d)
        log_op(d, "merge", dst, f"← {src}")
    return dst


# ── lint — 위키 건강 점검 (Karpathy lint = 부패 방지의 기계화) ───────────────────────

# user 메모리 명령문 탐지 — 명확한 지시 어휘 결합에만 앵커 (false positive 회피).
_IMPERATIVE_PATTERNS = (
    re.compile(r"(항상|반드시|무조건|절대)\s+\S[^\n]*?(하라|해라|할 것|하세요|하지 ?마|해야 한다|금지)"),
    re.compile(r"^\s*(always|never|must|do not|don't)\b", re.IGNORECASE | re.MULTILINE),
)


def _imperative_phrase(body: str) -> str:
    """user 페이지의 명령문 탐지 — 매치 구절(절단)을 반환, 없으면 빈 문자열."""
    for pattern in _IMPERATIVE_PATTERNS:
        m = pattern.search(body)
        if m:
            return m.group(0)[:40]
    return ""


def lint(d: str | None = None) -> list[dict]:
    """기계 판정만 — 모순 탐지 같은 의미 판단은 LLM 몫(후속). 반환 = findings."""
    d = d or memory_dir()
    findings: list[dict] = []
    slugs = set(_pages(d))
    if not slugs:
        index_path = os.path.join(d, INDEX)
        if os.path.exists(index_path):
            try:
                with open(index_path, encoding="utf-8") as handle:
                    stale_index = handle.read() != build_index(d)
                if stale_index:
                    findings.append(
                        {"level": "info", "code": "index-stale", "slug": INDEX, "msg": "run: asgard memory reindex"}
                    )
            except Exception:
                findings.append(
                    {"level": "info", "code": "index-stale", "slug": INDEX, "msg": "run: asgard memory reindex"}
                )
        return findings
    usage: dict[str, tuple[int, str]] = {}
    try:
        conn = _db(d)
        usage = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT slug, uses, last_used FROM usage")}
        conn.close()
    except Exception:
        pass
    today = _dt.date.today()
    docs: dict[str, str] = {}
    for slug in sorted(slugs):
        pg = _read(d, slug)
        if not pg:
            findings.append({"level": "error", "code": "unreadable", "slug": slug, "msg": "parse failed"})
            continue
        meta, body = pg
        docs[slug] = meta.get("title", "") + " " + body
        for ref in re.findall(r"\[\[([^\]]+)\]\]", body) + [
            s.strip() for s in meta.get("links", "").split(",") if s.strip()
        ]:
            if slugify(ref) not in slugs and ref not in slugs:
                findings.append({"level": "warn", "code": "dead-link", "slug": slug, "msg": f"[[{ref}]]"})
        # 외부 편집으로 스캔을 우회한 오염 소급 탐지 — 본문 + 주입 메타 전부, kind 포함 (P0)
        threat = poisoned(meta, body)
        if threat:
            findings.append({"level": "error", "code": "threat", "slug": slug, "msg": threat})
        # user 메모리는 선언문이어야 한다 — 명령문은 미래 세션에서 지시로 재해석되어
        # 사용자의 현재 요청을 덮어쓸 수 있다 ("사용자는 X를 선호한다" ✓ / "항상 X하라" ✗)
        if _kind(meta) == "user":
            imperative = _imperative_phrase(body)
            if imperative:
                findings.append(
                    {
                        "level": "warn",
                        "code": "imperative-user-memory",
                        "slug": slug,
                        "msg": f"명령문 감지({imperative}) — 선언문으로 바꾸세요 ('사용자는 …를 선호한다')",
                    }
                )
        try:
            updated = _dt.date.fromisoformat(meta.get("updated", meta.get("created", "")))
            uses = usage.get(slug, (0, None))[0]
            if (today - updated).days >= STALE_DAYS and uses == 0:
                findings.append(
                    {
                        "level": "info",
                        "code": "decay-candidate",
                        "slug": slug,
                        "msg": f"{(today - updated).days}d untouched, never recalled",
                    }
                )
        except Exception:
            findings.append({"level": "warn", "code": "no-date", "slug": slug, "msg": "missing/invalid updated:"})
    items = sorted(docs.items())
    for i, (s1, t1) in enumerate(items):
        for s2, t2 in items[i + 1 :]:
            if _jaccard(t1, t2) >= DUP_JACCARD:
                findings.append({"level": "warn", "code": "near-duplicate", "slug": s1, "msg": f"≈ {s2}"})
    # 칸별 초과 — 넘친 칸만 지목한다. "인덱스가 크다"는 어디를 통합할지 안 알려준다.
    # 재는 대상은 실제 주입 행이다: index.md 행은 pages/<slug>.md 링크를 달고 있는데
    # 그 링크는 프롬프트에 한 글자도 안 실린다 — 안 실리는 문자로 경고하면 계기가 거짓말한다.
    for kind, used, budget in section_usage(d):
        if used > budget:
            findings.append(
                {
                    "level": "warn",
                    "code": "index-over-budget",
                    "slug": f"{INDEX}#{kind}",
                    "msg": f"{used}/{budget} chars",
                }
            )
    try:
        with open(os.path.join(d, INDEX), encoding="utf-8") as handle:
            stale = handle.read() != build_index(d)
        if stale:
            findings.append(
                {"level": "info", "code": "index-stale", "slug": INDEX, "msg": "run: asgard memory reindex"}
            )
    except Exception:
        findings.append({"level": "info", "code": "index-stale", "slug": INDEX, "msg": "run: asgard memory reindex"})
    # 시맨틱 파생 인덱스가 정본을 덮는가. index.md 의 낡음은 이미 보는데 벡터의 낡음은 안 봤다 —
    # 그런데 이쪽이 더 조용하다: index.md 가 낡으면 목차가 틀리지만, 벡터가 없으면 검색 경로
    # 하나가 통째로 사라지면서 상태 표면은 계속 "on" 이라고 말한다 (실측 26-07-29).
    # 임베더를 로드하지 않는 판정이라 lint 가 무거워지지 않는다.
    with contextlib.suppress(Exception):
        from .. import memory_semantic as sem

        if sem.mode() != "off":
            coverage = vec_coverage(d)
            if not coverage["ok"] and coverage["pages"]:
                findings.append(
                    {
                        "level": "warn",
                        "code": "vec-stale",
                        "slug": DB,
                        "msg": (
                            f"시맨틱 색인 {coverage['fresh']}/{coverage['pages']} 페이지"
                            + (f" · 낡음 {coverage['stale']}" if coverage["stale"] else "")
                            + (f" · 고아 {coverage['orphan']}" if coverage["orphan"] else "")
                            + " — run: asgard memory reindex"
                        ),
                    }
                )
    return findings
