"""데이터 계층 — 전부 읽기 전용, asgard.memory 실함수에서 조립한다."""

from __future__ import annotations

import base64
import datetime as _dt
import os
import re

from ... import memory

# ── 로고 (골드 브랜드 로고를 base64 인라인 — 자기완결) ─────────────────────────────


def _packaged_logo() -> bytes | None:
    try:
        from importlib.resources import files

        return (files("asgard") / "assets" / "gold-brand-logo.png").read_bytes()
    except Exception:
        return None


def _repo_logo() -> bytes | None:
    # 개발 트리 폴백 — 설치본이 아니면 저장소 원본 골드 로고를 찾는다.
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        cand = os.path.join(here, "assets", "individual", "13-gold-brand-logo.png")
        if os.path.isfile(cand):
            return open(cand, "rb").read()
        here = os.path.dirname(here)
    return None


def _logo_data_uri() -> str:
    for loader in (_packaged_logo, _repo_logo):
        data = loader()
        if data:
            return "data:image/png;base64," + base64.b64encode(data).decode()
    return ""  # 없으면 HTML 이 인라인 SVG 마크로 우아하게 저하


_LOGO_URI = _logo_data_uri()


# ── 데이터 조립 (전부 읽기 전용, asgard.memory 실함수) ──────────────────────────────


def _desc_of(meta: dict, body: str) -> str:
    return memory._desc(meta, body)


def catalog_data(d: str) -> list[dict]:
    """pages/ frontmatter 카탈로그. 오염 페이지는 본문·설명을 비우고 poisoned 로 표시만 한다."""
    usage = {u["slug"]: u for u in memory.usage_stats(d)}
    rows: list[dict] = []
    for slug in memory._pages(d):
        pg = memory._read(d, slug)
        if not pg:
            rows.append({"slug": slug, "title": slug, "kind": "note", "poisoned": True, "unreadable": True})
            continue
        meta, body = pg
        poisoned = bool(memory.poisoned(meta, body))
        u = usage.get(slug, {})
        rows.append(
            {
                "slug": slug,
                "title": meta.get("title", slug),
                "kind": memory._kind(meta),
                "created": meta.get("created", ""),
                "updated": meta.get("updated", ""),
                "links": [s.strip() for s in meta.get("links", "").split(",") if s.strip()],
                "desc": "" if poisoned else _desc_of(meta, body),
                "size": len(body),
                "uses": int(u.get("uses", 0)),
                "last_used": u.get("last_used") or "",
                "poisoned": poisoned,
            }
        )
    return rows


def health_data(d: str) -> dict:
    findings = memory.lint(d)
    counts = {"error": 0, "warn": 0, "info": 0}
    for f in findings:
        counts[f["level"]] = counts.get(f["level"], 0) + 1
    size = len(memory.build_index(d))
    budget = memory.index_budget()
    pct = round(100 * size / budget) if budget else 0
    state = "crit" if size > budget else "warn" if pct >= 85 else "ok"
    return {
        "findings": findings,
        "counts": counts,
        "budget": {"size": size, "budget": budget, "pct": pct, "state": state},
    }


def graph_data(d: str) -> dict:
    """본문 [[slug]] + frontmatter links 로 링크 그래프. 고아·죽은 링크 탐지."""
    slugs = set(memory._pages(d))
    usage = {u["slug"]: u for u in memory.usage_stats(d)}
    nodes: list[dict] = []
    edges: list[dict] = []
    degree: dict[str, int] = dict.fromkeys(slugs, 0)
    dead = 0
    kinds: dict[str, str] = {}
    for slug in sorted(slugs):
        pg = memory._read(d, slug)
        if not pg:
            continue
        meta, body = pg
        kinds[slug] = memory._kind(meta)
        # 본문 [[링크]] + frontmatter links — 같은 대상 중복 참조는 1엣지로 dedupe
        # (중복이 엣지 2개·차수 2배로 새던 결함, 프레이야 리뷰 지적)
        refs = list(
            dict.fromkeys(
                re.findall(r"\[\[([^\]]+)\]\]", body)
                + [s.strip() for s in meta.get("links", "").split(",") if s.strip()]
            )
        )
        seen_targets: set[str] = set()
        for ref in refs:
            target = memory.slugify(ref) if memory.slugify(ref) in slugs else (ref if ref in slugs else None)
            if target and target != slug:
                if target in seen_targets:  # slugify 경유 별칭 중복 ("Thor Squad"/"thor-squad")
                    continue
                seen_targets.add(target)
                edges.append({"from": slug, "to": target, "dead": False})
                degree[slug] += 1
                degree[target] += 1
            else:
                edges.append({"from": slug, "to": ref, "dead": True})
                dead += 1
    sem_edges = _semantic_edges(d, slugs)
    for e in sem_edges:  # 의미 엣지도 고아 판정에 기여 — 링크 없어도 의미로 이어져 있으면 고아가 아니다
        degree[e["from"]] = degree.get(e["from"], 0) + 1
        degree[e["to"]] = degree.get(e["to"], 0) + 1
    orphans = sorted(s for s in slugs if degree.get(s, 0) == 0)
    for slug in sorted(slugs):
        if slug not in kinds:
            continue
        pg = memory._read(d, slug)
        title = pg[0].get("title", slug) if pg else slug
        nodes.append(
            {
                "slug": slug,
                "kind": kinds[slug],
                "title": title,
                "uses": int(usage.get(slug, {}).get("uses", 0)),
                "degree": degree.get(slug, 0),
                "orphan": slug in orphans,
            }
        )
    return {"nodes": nodes, "edges": edges + sem_edges, "orphans": orphans, "dead": dead}


SEM_EDGE_FLOOR = 0.35  # 의미 엣지 문턱 — 검색 floor(0.20)보다 높게: 그래프는 확신 연결만
SEM_EDGE_TOP = 3  # 노드당 의미 엣지 상한 — 완전그래프化 방지


def _semantic_edges(d: str, slugs: set[str]) -> list[dict]:
    """저장된 벡터로 페이지 간 의미 유사 엣지 생성 (type=semantic). 벡터 없으면 빈 리스트.

    [[링크]] 없이도 '같은 주제' 페이지가 그래프에서 이어진다 — agentmemory 지식그래프의
    핵심 가치를 우리 파생물(vec 테이블)로 재현. LLM 0, 읽기 전용, fail-open."""
    try:
        from ... import memory_semantic as sem

        conn = memory._db(d)
        rows = conn.execute("SELECT slug, data FROM vec").fetchall()
        conn.close()
        vecs = {s: sem.unpack(b) for s, b in rows if s in slugs}
        if len(vecs) < 2:
            return []
        best: dict[str, list[tuple[float, str]]] = {s: [] for s in vecs}
        items = sorted(vecs.items())
        for i, (s1, v1) in enumerate(items):
            for s2, v2 in items[i + 1 :]:
                cos = sem.cosine(v1, v2)
                if cos >= SEM_EDGE_FLOOR:
                    best[s1].append((cos, s2))
                    best[s2].append((cos, s1))
        edges: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for s, cands in best.items():
            for cos, t in sorted(cands, reverse=True)[:SEM_EDGE_TOP]:
                key = (min(s, t), max(s, t))
                if key in seen:
                    continue
                seen.add(key)
                edges.append({"from": key[0], "to": key[1], "dead": False, "type": "semantic", "w": round(cos, 3)})
        return edges
    except Exception:
        return []  # fail-open — 그래프는 링크 엣지만으로 계속


_LOG_LINE = re.compile(r"^-\s+(\S+)\s+\[([^\]]+)\]\s+(\S+)(?:\s+—\s+(.*))?$")


def log_data(d: str, n: int = 40) -> list[dict]:
    path = os.path.join(d, memory.LOG)
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except Exception:
        return []
    out: list[dict] = []
    for line in reversed(lines):
        m = _LOG_LINE.match(line.strip())
        if not m:
            continue
        out.append({"ts": m.group(1), "op": m.group(2), "slug": m.group(3), "detail": m.group(4) or ""})
        if len(out) >= n:
            break
    return out


def _local_day(ts: str) -> str:
    """UTC 로그 ts(`%Y-%m-%dT%H:%MZ`) → 로컬 날짜 YYYY-MM-DD. 로컬 자정 부근 항목이
    히트맵에서 하루 어긋나던 결함(프레이야 감사 지적) 교정. 파싱 불능은 접두 폴백."""
    try:
        dt = _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%MZ").replace(tzinfo=_dt.UTC)
        return dt.astimezone().date().isoformat()
    except Exception:
        return ts[:10]


def log_query(d: str, offset: int = 0, limit: int = 60, op: str | None = None, day: str | None = None) -> dict:
    """연대기 페이지네이션 + 필터 — 최신순. op 는 접두 매칭(add ← add:decision),
    day 는 **로컬 날짜** 접두 매칭(활동 히트맵 셀 → 해당 일자 딥링크 — 히트맵 집계와 동일 기준)."""
    path = os.path.join(d, memory.LOG)
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except Exception:
        return {"entries": [], "total": 0, "offset": 0, "limit": limit}
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 500))
    rows: list[dict] = []
    for line in reversed(lines):
        m = _LOG_LINE.match(line.strip())
        if not m:
            continue
        entry = {"ts": m.group(1), "op": m.group(2), "slug": m.group(3), "detail": m.group(4) or ""}
        if op and not entry["op"].startswith(op):
            continue
        if day and not _local_day(entry["ts"]).startswith(day):
            continue
        rows.append(entry)
    return {"entries": rows[offset : offset + limit], "total": len(rows), "offset": offset, "limit": limit}


def activity_data(d: str) -> dict:
    """전체 운영 로그 집계 — Activity 탭(연간 히트맵·op 분포)용. log.md 전량을 일 단위로 센다.
    타임라인(log_data)은 최근 N건, 여기는 집계만 — payload 가 페이지 수와 무관하게 작다."""
    path = os.path.join(d, memory.LOG)
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except Exception:
        return {"days": {}, "ops": {}, "total": 0, "first": "", "last": ""}
    days: dict[str, int] = {}
    ops: dict[str, int] = {}
    total = 0
    for line in lines:
        m = _LOG_LINE.match(line.strip())
        if not m:
            continue
        day = _local_day(m.group(1))  # UTC ts → 로컬 날짜 (히트맵·딥링크 기준 통일)
        op = m.group(2).split(":")[0]  # add:decision → add
        days[day] = days.get(day, 0) + 1
        ops[op] = ops.get(op, 0) + 1
        total += 1
    # first/last 는 파일 순서가 아니라 날짜 값으로 — 외부 편집으로 순서가 어긋난 로그에 강건
    return {
        "days": days,
        "ops": ops,
        "total": total,
        "first": min(days) if days else "",
        "last": max(days) if days else "",
    }


def norn_data(d: str) -> dict:
    """노른 손질 이력 — 리포트 목록 + insight 계보 (연대기 탭 편입, 읽기 전용).

    리포트는 reports/norn-*.md 파생물(원문 그대로 요약), insight 계보는 kind=insight
    페이지의 sources 링크·confidence 를 카탈로그에서 재구성한다."""
    reports: list[dict] = []
    rdir = os.path.join(d, "reports")
    try:
        names = sorted((n for n in os.listdir(rdir) if n.startswith("norn-") and n.endswith(".md")), reverse=True)
    except OSError:
        names = []
    for name in names[:12]:
        path = os.path.join(rdir, name)
        try:
            lines = open(path, encoding="utf-8").read().splitlines()
        except OSError:
            continue
        ops = [ln[2:].strip() for ln in lines if ln.startswith("- ")]
        counts = {
            "merge": sum(1 for op in ops if op.startswith("merge")),
            "archive": sum(1 for op in ops if op.startswith("archive")),
            "insight": sum(1 for op in ops if op.startswith("insight")),
            "contradiction": sum(1 for op in ops if op.startswith("⚠")),
            "proposed": sum(1 for op in ops if op.startswith("(제안)")),
            "dropped": sum(1 for op in ops if op.startswith("(기각)")),
        }
        reports.append({"name": name, "ops": ops[:20], "counts": counts})
    insights: list[dict] = []
    for row in catalog_data(d):
        if row.get("kind") != "insight" or row.get("poisoned"):
            continue
        pg = memory._read(d, row["slug"])
        confidence = ""
        if pg:
            m = re.search(r"confidence:\s*(low|medium|high)", pg[1])
            confidence = m.group(1) if m else ""
        insights.append(
            {
                "slug": row["slug"],
                "title": row["title"],
                "sources": row.get("links") or [],
                "confidence": confidence,
                "created": row.get("created", ""),
                "uses": row.get("uses", 0),
            }
        )
    insights.sort(key=lambda r: r["created"], reverse=True)
    return {"reports": reports, "insights": insights[:20], "auto_mode": _norn_auto_mode()}


def _norn_auto_mode() -> str:
    try:
        from ...memory.norn import auto_mode

        return auto_mode()
    except Exception:
        return "safe"


def _semantic_status() -> dict:
    try:
        from ... import memory_semantic as sem

        return {"active": bool(sem.active()), "mode": str(sem.mode())}
    except Exception:
        return {"active": False, "mode": "off"}


def snapshot_data(d: str | None = None) -> dict:
    d = memory.ensure_home(d)
    health = health_data(d)
    catalog = catalog_data(d)
    sem = _semantic_status()
    return {
        "meta": {
            "dir": d,
            "pages": len(catalog),
            "semantic": sem["active"],
            "semantic_mode": sem["mode"],
            "budget": health["budget"],
            "generated": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
        "health": health,
        "catalog": catalog,
        "usage": memory.usage_stats(d),
        "graph": graph_data(d),
        "log": log_data(d, n=120),  # 연대기 탭 분량 — 집계는 activity 가 담당
        "activity": activity_data(d),
        "norn": norn_data(d),  # 노른 손질 이력 + insight 계보 (연대기 탭)
    }


def page_data(slug: str, d: str | None = None) -> dict:
    """페이지 상세 (그래프/목록 클릭 스루) — 읽기 전용. 오염 페이지는 본문 미노출(격리 카드),
    수리는 CLI `asgard memory show --unsafe` 로만 (run_show 와 동일 규율)."""
    d = d or memory.memory_dir()
    if not memory.valid_slug(slug):
        return {"error": "invalid slug"}
    pg = memory._read(d, slug)
    if not pg:
        return {"error": "not found", "slug": slug}
    meta, body = pg
    threat = memory.poisoned(meta, body)
    usage = {u["slug"]: u for u in memory.usage_stats(d)}
    u = usage.get(slug, {})
    out = {
        "slug": slug,
        "title": meta.get("title", slug),
        "kind": memory._kind(meta),
        "created": meta.get("created", ""),
        "updated": meta.get("updated", ""),
        "links": [s.strip() for s in meta.get("links", "").split(",") if s.strip()],
        "uses": int(u.get("uses", 0)),
        "last_used": u.get("last_used") or "",
        "poisoned": bool(threat),
    }
    if threat:
        out["quarantine"] = f"오염 격리됨 — 수리: asgard memory show {slug} --unsafe"
    else:
        out["body"] = body
        out["refs"] = re.findall(r"\[\[([^\]]+)\]\]", body)
    return out


def search_data(q: str, k: int, d: str | None = None) -> dict:
    d = d or memory.memory_dir()
    q = (q or "").strip()[:200]
    k = max(1, min(int(k or 5), 25))
    sem = _semantic_status()
    if not q:
        return {"q": q, "k": k, "semantic_active": sem["active"], "hits": []}
    # 관측 무해 — track=False: 대시보드 열람이 usage/decay 통계를 왜곡하지 않는다.
    hits = memory.query(q, k=k, d=d, track=False, explain=True)
    return {"q": q, "k": k, "semantic_active": sem["active"], "hits": hits}
