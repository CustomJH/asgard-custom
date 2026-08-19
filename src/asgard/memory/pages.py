"""페이지 CRUD·운영 — add/ingest(승인 plan)·remove/merge·선호 갱신·lint 건강 점검."""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import math
import os
import re
import shutil

from .index import _db, _fts_upsert, build_index, vec_coverage, write_index
from .policy import memory_dir, scan_secrets, scan_threats
from .recall import _containment, _Grams, page_verdicts, query, section_usage
from .store import (
    DB,
    DEFAULT_KIND,
    INDEX,
    KINDS,
    TITLE_MAX,
    _atomic_write,
    _fm_value,
    _identity_slot,
    _kind,
    _lock,
    _page_path,
    _pages,
    _read,
    _read_all_cached,
    _today,
    derive_title,
    ensure_home,
    log_op,
    poisoned,
    render_page,
    slugify,
    valid_slug,
)
from .temporal import ground_event_date
from .usage import forget as _usage_forget
from .usage import merged as _usage_counters

STALE_DAYS = 90  # lint 부패 후보 기준 — 90일 무갱신 + 사용 0회
# ingest 병합 문턱 — containment(포함 계수)로 판정: Jaccard는 길이 차에 취약해 "같은 사실의
# 패러프레이즈+추가 상세"를 놓친다 (실측 26-07-15: 병합쌍 cont 0.56/0.61 vs 생성쌍 0.00/0.02).
MERGE_CONTAINMENT = 0.45
DUP_JACCARD = 0.60  # lint 중복 의심 문턱 — 대칭 비교라 Jaccard가 맞다

# ── 쓰기 (add / ingest) — 승인은 CLI 계층, 여기는 기계 검증 + 락 ───────────────────


def _fresh_slug(d: str, base: str, seed: str) -> str:
    """충돌 없는 slug — 이미 있으면 seed로 접미사를 붙이며 빈 자리까지 반복 (P2, 3번째 충돌 방지)."""
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
    """페이지 생성. 반환 = (slug, path). 스캔 위반·잘못된 kind는 ValueError.

    예산은 저장을 막지 않는다 — 주입면 상한은 "프롬프트에 몇 자 실을지"의 문제고, 지식은
    pages/ 에 남는다. 카탈로그가 꽉 찬 건 lint가 칸별로 일러준다."""
    d = ensure_home(d)
    if not text.strip():
        raise ValueError("empty memory text")
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind!r} — one of {', '.join(KINDS)}")
    title = _fm_value(title)[:TITLE_MAX] if title else derive_title(text)
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
    삼고 나머지는 absorb 목록에 넣어 같은 승인으로 접는다. 정본 선택은 created→slug 정렬이라
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


def _archive_unlocked(d: str, slug: str) -> None:
    """페이지 하나를 pages/ 밖 archive/ 로 옮긴다 (호출자가 _lock 보유).

    `norn.archive_page` 와 같은 디렉터리·같은 이름 규칙(`<slug>-<UTC 14자리>.md`)을 쓴다.
    복원 손잡이는 `norn.restore_page` 하나여야 하고, 이름이 갈리면 이 경로로 접힌 페이지만
    복원이 안 듣는다. `archive_page` 를 그대로 부르지 못하는 이유는 그쪽이 `_lock` 을 다시
    잡는데 flock 은 재진입이 안 되기 때문이다 — 같은 스레드가 자기 락에 걸린다."""
    from .norn import ARCHIVE_DIR

    adir = os.path.join(d, ARCHIVE_DIR)
    os.makedirs(adir, exist_ok=True)
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d%H%M%S")
    shutil.move(_page_path(d, slug), os.path.join(adir, f"{slug}-{stamp}.md"))


def _absorb_slot_dups(d: str, plan: dict) -> list[str]:
    """계획이 지목한 같은-슬롯 중복 페이지를 접는다 (호출자가 _lock 보유). 반환 = 접힌 slug.

    접기는 삭제가 아니라 아카이브다. 무엇을 접을지는 계획이 정하고 계획은 틀릴 수 있는데,
    틀린 자리에서 사라지는 것이 사용자가 직접 적은 사실이다 — `norn.restore_page` 로 되돌릴
    수 있어야 한다. 승인 시점 리비전이 어긋난 페이지는 아예 건드리지 않는다: 승인 범위 밖의
    변경을 접기로 덮는 것보다 모순 하나를 lint로 넘기는 편이 낫다."""
    absorbed: list[str] = []
    for entry in plan.get("absorb") or []:
        slug, rev = (list(entry) + [""])[:2] if isinstance(entry, (list, tuple)) else (entry, "")
        if not (isinstance(slug, str) and valid_slug(slug) and os.path.exists(_page_path(d, slug))):
            continue
        if rev and rev != _rev(d, slug):
            log_op(d, "ingest:absorb-skipped", str(slug), "changed since approval")
            continue
        _archive_unlocked(d, str(slug))
        with contextlib.suppress(Exception):
            conn = _db(d)
            with conn:
                for table in ("fts", "vec"):
                    conn.execute(f"DELETE FROM {table} WHERE slug = ?", (slug,))  # noqa: S608 — 테이블명은 리터럴
            conn.close()
        # 회수 통계는 pages/ 를 떠난 페이지를 안 가리킨다. 복원하면 0부터 다시 쌓인다.
        _usage_forget(d, str(slug))
        log_op(d, "ingest:absorbed", str(slug), f"slot={plan.get('slot')}")
        absorbed.append(str(slug))
    return absorbed


def ingest(
    text: str,
    kind: str = DEFAULT_KIND,
    d: str | None = None,
    plan: dict | None = None,
    title: str | None = None,
) -> tuple[str, str]:
    """자가 학습 쓰기 — plan 대로 생성·병합·선호 갱신·동일 사실 no-op. 반환 = (action, slug).

    plan을 넘기면(CLI 승인 게이트가 이미 계산·표시한 계획) 재계산하지 않는다 (TOCTOU 차단, P1):
    "승인한 merge 대상"과 "실제 merge 대상"이 갈라지지 않는다."""
    d = ensure_home(d)
    if not text.strip():
        raise ValueError("empty memory text")
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind!r} — one of {', '.join(KINDS)}")
    title = _fm_value(title)[:TITLE_MAX] if title else ""
    # 제목도 주입면에 나가는 값이다 — 본문만 태우면 제목 칸이 스캔을 비껴가는 통로가 된다.
    threat = scan_threats(text, title)
    if threat:
        raise ValueError(f"injection scan: {threat}")
    if secret := scan_secrets(text, title):
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
            # 승인된 plan은 리비전까지 대조 (2차 리뷰 ⑤) — 승인과 실행 사이 대상이 바뀌었으면 중단
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
                    meta["title"] = title or derive_title(text)
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
        slug, _ = _add_unlocked(d, text, title or derive_title(text), kind, "")
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
                conn.execute("DELETE FROM vec WHERE slug = ?", (slug,))
            conn.close()
        _usage_forget(d, slug)
        write_index(d)
        log_op(d, "remove", slug)
    return True


def merge(src: str, dst: str, d: str | None = None) -> str:
    """src를 dst에 흡수하고 src 삭제 (P2, 예산 초과 수동 통합). 반환 = dst slug."""
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
                conn.execute("DELETE FROM vec WHERE slug = ?", (src,))
                _fts_upsert(conn, d, dst)
            conn.close()
        _usage_forget(d, src)
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


def _duplicate_pairs(texts: list[str], grams: _Grams, threshold: float) -> list[tuple[int, int]]:
    """Jaccard ≥ threshold 인 쌍 — 앞 색인 오름차순. 전쌍 비교와 답이 같고, 세는 쌍만 적다.

    전쌍 비교는 O(N²)다. 1,000페이지면 50만 쌍이고 쌍마다 그램 집합 교집합이라, `lint` 시간의
    대부분이 여기서 나왔다 (실측 26-08-02: lint 5.9초). 그런데 쌍의 대부분은 **볼 필요조차
    없다** — 두 가지 자로 미리 떨어뜨릴 수 있고, 둘 다 답을 바꾸지 않는 정확한 경계다.

    ① 크기 경계. |A| ≤ |B| 이면 Jaccard = |A∩B|/|A∪B| ≤ |A|/|B| 이므로, |A| < t·|B| 인 쌍은
       계산해 볼 것도 없이 문턱 미만이다.

    ② 접두 필터 (집합 유사도 조인의 표준 기법). 전역 빈도 오름차순으로 정렬한 그램 중 앞
       |X| − ⌈t·|X|⌉ + 1 개만 색인한다. Jaccard ≥ t 인 두 집합은 반드시 그 접두를 하나 이상
       공유한다: 공통 원소 수는 ⌈t·max(|A|,|B|)⌉ 이상인데, 가장 앞선 공통 원소가 어느 한쪽의
       접두 **밖**에 있다면 그 집합에서 그 원소 이후 자리가 ⌈t·|X|⌉ − 1 개뿐이라 공통 원소를
       다 담을 수 없기 때문이다. 그래서 접두를 안 공유하는 쌍은 문턱 미만이 확정이다.

    희귀한 그램부터 색인하는 것이 요점이다 — 흔한 그램(조사·어미)으로 색인하면 목록이 길어져
    걸러지는 것이 없다. 코퍼스가 실제로 서로 닮았으면 살아남는 쌍이 많다: 그건 필터가 약한
    것이 아니라 그만큼이 진짜 후보라는 뜻이고, 그때는 아래 정확 판정이 그만큼 돈다."""
    sets = [grams.of(text) for text in texts]
    sizes = [len(gramset) for gramset in sets]
    frequency: dict[str, int] = {}
    for gramset in sets:
        for gram in gramset:
            frequency[gram] = frequency.get(gram, 0) + 1
    posting: dict[str, list[int]] = {}
    pairs: set[tuple[int, int]] = set()
    for i in sorted(range(len(texts)), key=lambda idx: sizes[idx]):  # 작은 집합부터 색인한다
        gramset = sets[i]
        if not gramset:
            continue
        cut = len(gramset) - math.ceil(threshold * len(gramset)) + 1
        prefix = sorted(gramset, key=lambda gram: (frequency[gram], gram))[:cut]
        floor = threshold * sizes[i]  # 크기 경계 — 작은 쪽이 이 밑이면 문턱을 못 넘는다
        seen: set[int] = set()
        for gram in prefix:
            for j in posting.get(gram, ()):
                if j in seen:
                    continue
                seen.add(j)
                if sizes[j] >= floor and grams.jaccard_of(gramset, sets[j]) >= threshold:
                    pairs.add((min(i, j), max(i, j)))
        for gram in prefix:
            posting.setdefault(gram, []).append(i)
    return sorted(pairs)


def _stale_title(meta: dict, body: str) -> str:
    """다시 뽑으면 나아지는 제목이면 그 새 제목, 아니면 빈 문자열.

    본문 앞부분을 그대로 베낀 제목만 대상이다 — 부르는 쪽이 지어 준 제목은 본문 첫 줄의
    접두사가 아니라서 걸리지 않는다. 글자 수로만 자르던 시절의 제목이 여기 걸린다.

    비교 전에 잘림 표시를 뗀다. 안 떼면 **가장 나아질 여지가 큰 제목이 통째로 빠진다** —
    말줄임표가 붙은 제목은 본문의 접두사가 아니게 되어 이 판정을 못 지나고, 오딘의 기억에서
    다섯 장이 `오딘은…` 으로 시작한 채 남아 있었다 (실측 26-08-19)."""
    title = str(meta.get("title") or "")
    if not title:
        return ""
    first = next((ln.strip().lstrip("# ") for ln in body.splitlines() if ln.strip()), "")
    if not first.startswith(title.rstrip("…")):
        return ""
    fresh = derive_title(body)
    return fresh if fresh != title else ""


def retitle(d: str | None = None) -> list[tuple[str, str, str]]:
    """본문에서 베껴 온 제목을 다시 뽑는다. 반환 = (slug, 옛 제목, 새 제목) 목록.

    본문도 slug 도 안 건드린다 — slug 을 따라 바꾸면 페이지 경로가 바뀌어 `[[링크]]` 가 끊기고,
    끊긴 링크는 lint 가 죽은 링크로 다시 보고한다. 제목 칸 하나만 고쳐도 주입면과 목차는 바뀐다."""
    d = ensure_home(d)
    changed: list[tuple[str, str, str]] = []
    with _lock(d):
        for slug in sorted(_pages(d)):
            pg = _read(d, slug)
            if not pg:
                continue
            meta, body = pg
            fresh = _stale_title(meta, body)
            if not fresh:
                continue
            changed.append((slug, str(meta.get("title") or ""), fresh))
            meta["title"] = fresh
            _atomic_write(_page_path(d, slug), render_page(meta, body))
        if changed:
            write_index(d)
            with contextlib.suppress(Exception):
                conn = _db(d)
                with conn:
                    for slug, _old, _new in changed:
                        _fts_upsert(conn, d, slug)
                conn.close()
    for slug, _old, _new in changed:
        log_op(d, "retitle", slug)
    return changed


def _page_findings(
    slug: str,
    meta: dict,
    body: str,
    slugs: set[str],
    threat: str | None,
    counts: dict,
    today: _dt.date,
) -> list[dict]:
    """페이지 한 장의 점검 결과 — 죽은 링크·오염·명령문·부패 후보. 순서가 곧 보고 순서다.

    오염 판정(`threat`)은 호출자가 넘긴다: 같은 판정을 회수와 나눠 쓰기 위해서다
    (`recall.page_verdicts`). 여기서 다시 재면 같은 위협 스캔이 한 점검 안에서 두 번 돈다."""
    findings: list[dict] = []
    for ref in re.findall(r"\[\[([^\]]+)\]\]", body) + [
        s.strip() for s in meta.get("links", "").split(",") if s.strip()
    ]:
        if slugify(ref) not in slugs and ref not in slugs:
            findings.append({"level": "warn", "code": "dead-link", "slug": slug, "msg": f"[[{ref}]]"})
    if fresh := _stale_title(meta, body):
        findings.append(
            {"level": "info", "code": "title-truncated", "slug": slug, "msg": f"제목을 다시 뽑으면: {fresh}"}
        )
    # 외부 편집으로 스캔을 우회한 오염 소급 탐지 — 본문 + 주입 메타 전부, kind 포함 (P0)
    if threat:
        findings.append({"level": "error", "code": "threat", "slug": slug, "msg": threat})
    # user 메모리는 선언문이어야 한다 — 명령문은 미래 세션에서 지시로 재해석되어
    # 사용자의 현재 요청을 덮어쓸 수 있다 ("사용자는 X를 선호한다" ✓ / "항상 X하라" ✗)
    if _kind(meta) == "user" and (imperative := _imperative_phrase(body)):
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
    except Exception:
        findings.append({"level": "warn", "code": "no-date", "slug": slug, "msg": "missing/invalid updated:"})
        return findings
    if (today - updated).days >= STALE_DAYS and not counts.get("uses"):
        # 노출만 쌓인 페이지는 사유에 그 수를 적는다: "매 턴 실리는데 아무도 안 찾는다"는
        # 지우라는 말이 아니라 사람이 봐야 할 사실이다 (자동 주입은 회수기의 선택이다).
        exposures = int(counts.get("exposures") or 0)
        findings.append(
            {
                "level": "info",
                "code": "decay-candidate",
                "slug": slug,
                "msg": f"{(today - updated).days}d untouched, never searched"
                + (f" ({exposures} auto-exposure(s))" if exposures else ""),
            }
        )
    return findings


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
    # 판정이 읽는 것은 **사용**(사람이 부른 검색)이다. 자동 주입 횟수(exposures)는 같이 읽되
    # 자격을 흔들지 않고 사유에만 붙는다 — 왜 갈랐는지는 `memory.usage` 참조.
    usage = _usage_counters(d)
    today = _dt.date.today()
    docs: dict[str, str] = {}
    # 페이지는 여기서 한 번만 읽는다. 아래 `section_usage`·`build_index`·`vec_coverage`가 같은 파일을
    # 다시 열던 자리라, 1,000페이지 점검 한 번이 전량 읽기 서너 벌이었다 (실측 26-08-02).
    # 못 읽는 페이지는 이 목록에서 빠지므로 아래에서 slug 차집합으로 잡아 그대로 보고한다.
    loaded = {slug: (meta, body) for slug, meta, body in _read_all_cached(d)}
    # 오염 판정도 회수와 나눠 쓴다 — 본문 sha 가 그대로면 접어 둔 판정 그대로다
    # (`recall.page_verdicts`). 여기서 다시 재면 같은 위협 스캔이 한 점검 안에서 두 벌이 된다.
    verdicts = page_verdicts(d)
    for slug in sorted(slugs):
        pg = loaded.get(slug)
        if not pg:
            findings.append({"level": "error", "code": "unreadable", "slug": slug, "msg": "parse failed"})
            continue
        meta, body = pg
        docs[slug] = meta.get("title", "") + " " + body
        threat = verdicts[slug] if slug in verdicts else poisoned(meta, body)
        findings.extend(_page_findings(slug, meta, body, slugs, threat, usage.get(slug) or {}, today))
    items = sorted(docs.items())
    # 그램 생성은 본문마다 한 번이면 된다 — 캐시를 이 호출의 수명으로 들고 돈다 (`recall._Grams`).
    # 쌍 비교는 그 위에서 사전 필터로 좁힌다: 실제 Jaccard 는 살아남은 쌍에만 매기고, 그 값과
    # 문턱 판정은 전쌍 비교 시절과 글자 그대로 같다 (`_duplicate_pairs`).
    grams = _Grams()
    # 보고 순서는 전쌍 비교 시절과 같다 — 앞 페이지 기준 오름차순 (`_duplicate_pairs` 가 정렬해 준다).
    for i, j in _duplicate_pairs([text for _slug, text in items], grams, DUP_JACCARD):
        findings.append({"level": "warn", "code": "near-duplicate", "slug": items[i][0], "msg": f"≈ {items[j][0]}"})
    # 칸별 초과 — 넘친 칸만 지목한다. "인덱스가 크다"는 어디를 통합할지 안 알려준다.
    # 재는 대상은 실제 주입 행이다: index.md 행은 pages/<slug>.md 링크를 달고 있는데
    # 그 링크는 프롬프트에 한 글자도 안 들어간다 — 안 들어가는 문자로 경고하면 계기가 거짓말한다.
    # 예산 0은 "이 칸은 주입하지 않는다"는 사용자의 선언이다 (`policy.kind_budgets` · `recall._section`이
    # 그 칸을 통째로 뺀다). 그걸 초과로 읽으면 lint 는 사용자가 끈 칸을 두고 영영 켜진 경고를 내고,
    # 통합할 것이 없는 경고는 나머지 경고까지 같이 안 읽히게 만든다.
    for kind, used, budget in section_usage(d):
        if budget > 0 and used > budget:
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
    # 시맨틱 파생 인덱스가 정본을 덮는가. index.md의 낡음은 이미 보는데 벡터의 낡음은 안 봤다 —
    # 그런데 이쪽이 더 조용하다: index.md가 낡으면 목차가 틀리지만, 벡터가 없으면 검색 경로
    # 하나가 통째로 사라지면서 상태 표면은 계속 "on"이라고 말한다 (실측 26-07-29).
    # 임베더를 로드하지 않는 판정이라 lint가 무거워지지 않는다.
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
