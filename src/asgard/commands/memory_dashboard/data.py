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
            with open(cand, "rb") as handle:
                return handle.read()
        here = os.path.dirname(here)
    return None


def _logo_data_uri() -> str:
    for loader in (_packaged_logo, _repo_logo):
        data = loader()
        if data:
            return "data:image/png;base64," + base64.b64encode(data).decode()
    return ""  # 없으면 HTML이 인라인 SVG 마크로 우아하게 저하


_LOGO_URI = _logo_data_uri()


def _packaged_mark() -> bytes | None:
    """헤더 브랜드 마크 — 위그드라실 엠블럼. `asgard map`이 읽는 바로 그 파일이다
    (map_graph/view.py `_logo_data_uri`). 같은 파일을 쓰는 것이 두 창을 한 제품으로
    묶는 실제 배선이다 — 각자 다른 로고를 인라인하면 '공통 앵커'는 말뿐이 된다."""
    try:
        from importlib.resources import files

        return (files("asgard") / "assets" / "yggdrasil-mark.png").read_bytes()
    except Exception:
        return None


def _mark_data_uri() -> str:
    data = _packaged_mark()
    return "data:image/png;base64," + base64.b64encode(data).decode() if data else ""


_MARK_URI = _mark_data_uri()


# ── 데이터 조립 (전부 읽기 전용, asgard.memory 실함수) ──────────────────────────────


def _desc_of(meta: dict, body: str) -> str:
    return memory._desc(meta, body)


def catalog_data(d: str) -> list[dict]:
    """pages/ frontmatter 카탈로그. 오염 페이지는 본문·설명을 비우고 poisoned로 표시만 한다."""
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
    sections = []
    for kind, used, budget in memory.section_usage(d):
        pct = round(100 * used / budget) if budget else 0
        sections.append(
            {
                "kind": kind,
                "size": used,
                "budget": budget,
                "pct": pct,
                "state": "crit" if used > budget else "warn" if pct >= 85 else "ok",
            }
        )
    size = sum(s["size"] for s in sections)
    total = sum(s["budget"] for s in sections)
    pct = round(100 * size / total) if total else 0
    return {
        "findings": findings,
        "counts": counts,
        # 총량은 요약일 뿐이다 — 통합할 자리는 칸이 정한다. 한 칸이라도 넘치면 전체가 crit.
        "budget": {
            "size": size,
            "budget": total,
            "pct": pct,
            "state": "crit"
            if any(s["state"] == "crit" for s in sections)
            else "warn"
            if any(s["state"] == "warn" for s in sections)
            else "ok",
            "sections": sections,
        },
    }


def graph_data(d: str) -> dict:
    """본문 [[slug]] + frontmatter links로 링크 그래프. 고아·죽은 링크 탐지."""
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
    orphans = {s for s in slugs if degree.get(s, 0) == 0}  # 집합인 이유 — 아래 루프가 서고 전체를 돈다
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
    # 의미 연결선을 접었으면 그렇다고 말한다 — 조용히 비면 "이어진 게 없다"로 읽힌다.
    vec_count = 0
    try:
        conn = memory._db(d)
        vec_count = int(conn.execute("SELECT count(*) FROM vec").fetchone()[0])
        conn.close()
    except Exception:
        pass
    return {
        "nodes": nodes,
        "edges": edges + sem_edges,
        "orphans": sorted(orphans),
        "dead": dead,
        "sem_capped": vec_count > SEM_EDGE_MAX_NODES,
        "sem_cap": SEM_EDGE_MAX_NODES,
    }


SEM_EDGE_FLOOR = 0.35  # 의미 엣지 문턱 — 검색 floor(0.20)보다 높게: 그래프는 확신 연결만
SEM_EDGE_TOP = 3  # 노드당 의미 엣지 상한 — 완전그래프化 방지
# 쌍 비교 상한 — 이 계산은 O(n²)이고 30초 폴링마다 스냅샷 안에서 돈다. 실측(26-07-29, M-series):
#   150p 88ms · 400p 582ms · 800p 2,195ms.  800페이지에서 창이 2초씩 멈추면 관측 창이 아니다.
# 넘으면 의미 연결선을 접고 그 사실을 그래프에 함께 보낸다 — 조용히 비면 "연결이 없다"로 읽힌다.
SEM_EDGE_MAX_NODES: int = 500  # 상한이지 상수가 아니다 — 검사가 낮춰 끼우고 접힘을 확인한다
_SEM_EDGE_CACHE: dict[str, tuple[str, list[dict]]] = {}  # dir → (벡터 지문, 엣지)


def _vec_signature(rows: list[tuple[str, bytes]]) -> str:
    """벡터 집합 지문 — 이 값이 같으면 엣지도 같다. 행 읽기는 O(n)이라 값싸고,
    아낄 대상은 그 뒤의 O(n²) 코사인이다."""
    import hashlib

    h = hashlib.blake2b(digest_size=16)
    for slug, data in sorted(rows):
        h.update(slug.encode("utf-8"))
        h.update(data)
    return h.hexdigest()


def _semantic_edges(d: str, slugs: set[str]) -> list[dict]:
    """저장된 벡터로 페이지 간 의미 유사 엣지 생성 (type=semantic). 벡터 없으면 빈 리스트.

    [[링크]] 없이도 '같은 주제' 페이지가 그래프에서 이어진다 — agentmemory 지식그래프의
    핵심 가치를 우리 파생물(vec 테이블)로 재현. LLM 0, 읽기 전용, fail-open.

    30초 폴링은 대개 **같은 데이터**를 다시 본다. 그런데도 매번 전 쌍을 다시 재고 있었다 —
    벡터 지문이 같으면 답도 같으므로 그때는 계산 자체를 건너뛴다."""
    try:
        from ... import memory_semantic as sem

        conn = memory._db(d)
        rows = conn.execute("SELECT slug, data FROM vec").fetchall()
        conn.close()
        rows = [(s, b) for s, b in rows if s in slugs]
        if len(rows) < 2:
            return []
        sig = _vec_signature(rows)
        cached = _SEM_EDGE_CACHE.get(d)
        if cached and cached[0] == sig:
            return cached[1]
        if len(rows) > SEM_EDGE_MAX_NODES:
            _SEM_EDGE_CACHE[d] = (sig, [])
            return []
        vecs = {s: sem.unpack(b) for s, b in rows}
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
        _SEM_EDGE_CACHE[d] = (sig, edges)
        return edges
    except Exception:
        return []  # fail-open — 그래프는 링크 엣지만으로 계속


_LOG_LINE = re.compile(r"^-\s+(\S+)\s+\[([^\]]+)\]\s+(\S+)(?:\s+—\s+(.*))?$")


def log_data(d: str, n: int = 40) -> list[dict]:
    path = os.path.join(d, memory.LOG)
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
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
    """연대기 페이지네이션 + 필터 — 최신순. op는 접두 매칭(add ← add:decision),
    day는 **로컬 날짜** 접두 매칭(활동 히트맵 셀 → 해당 일자 딥링크 — 히트맵 집계와 동일 기준)."""
    path = os.path.join(d, memory.LOG)
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
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
    타임라인(log_data)은 최근 N건, 여기는 집계만 — payload가 페이지 수와 무관하게 작다."""
    path = os.path.join(d, memory.LOG)
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
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
    # first/last는 파일 순서가 아니라 날짜 값으로 — 외부 편집으로 순서가 어긋난 로그에 강건
    return {
        "days": days,
        "ops": ops,
        "total": total,
        "first": min(days) if days else "",
        "last": max(days) if days else "",
    }


def norn_data(d: str) -> dict:
    """노른 손질 이력 — 리포트 목록 + insight 계보 + 모순·보관·백업 (손질 탭, 읽기 전용).

    리포트는 reports/norn-*.md 파생물(원문 그대로 요약), insight 계보는 kind=insight
    페이지의 sources 링크·confidence를 카탈로그에서 재구성한다. 모순은 사람이 풀 일이라
    리포트 안에 묻어두지 않고 따로 세워 올린다(노른은 보고만 하고 고치지 않는다)."""
    contradictions = _contradictions(d)
    reports: list[dict] = []
    rdir = os.path.join(d, "reports")
    try:
        names = sorted((n for n in os.listdir(rdir) if n.startswith("norn-") and n.endswith(".md")), reverse=True)
    except OSError:
        names = []
    for name in names[:12]:
        path = os.path.join(rdir, name)
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
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
    return {
        "reports": reports,
        "insights": insights[:20],
        "auto_mode": _norn_auto_mode(),
        "insight_auto": _norn_insight_auto(),
        "contradictions": contradictions,
        "archive": archive_data(d),
        "backups": backup_data(d),
        "patterns": pattern_reports(d),
    }


def _contradictions(d: str) -> list[dict]:
    """미해결 모순 — 노른이 고치지 않고 사람에게 넘긴 것들. 출처는 장부다 (`memory.contradiction`).

    예전에는 이 목록을 reports/norn-*.md 본문에서 정규식으로 긁었다. 리포트는 런마다 새로
    생기는 파일이라 거기서는 알 수 있는 것이 "이 런에서 이런 줄이 보였다"뿐이었다: 같은
    어긋남을 몇 번째 보는지도, 사람이 이미 보고 넘긴 것인지도 리포트에는 안 적혀 있다.
    그래서 창은 열 번 감지된 모순도 매번 처음 보는 것처럼 그렸고, 사람이 "둘 다 맞다"고
    판단한 것도 다음 런에서 똑같은 얼굴로 다시 떴다.

    장부는 그 셋을 다 안다. 여기서는 그대로 옮기기만 한다 — 판정도 쓰기도 없다
    (`open_contradictions`는 읽기 전용이다). 기본 목록에서 확인된 것을 빼는 것도 장부의
    기본값 그대로다: **창과 CLI(`asgard memory contradictions`)가 같은 수를 말해야 한다.**
    한쪽만 감추면 사람이 두 표면에서 다른 건수를 보고 어느 쪽을 믿을지 정해야 한다.

    `report` 키는 더 안 준다 — 창이 링크할 리포트 하나를 고를 수 없다. 같은 모순은 여러
    리포트에 걸쳐 있고, 장부가 세는 것은 파일이 아니라 어긋남 하나다."""
    rows = memory.open_contradictions(d)
    return [
        {
            "key": row["key"],
            "a": row["a"],
            "b": row["b"],
            "a_title": row["a_title"],
            "b_title": row["b_title"],
            "why": row["why"],
            "detected": row["detected"],
            "last_seen": row["last_seen"],
            "count": row["count"],
            "status": row["status"],
            # 장부가 본 판본 이후로 두 페이지 중 하나가 바뀌었다 — 사유가 낡았을 수 있다는 뜻.
            "changed_since": row["changed_since"],
        }
        for row in rows[:20]
    ]


_ARCHIVE_SNAP = re.compile(r"^(?P<slug>.+)-(?P<ts>\d{14})\.md$")


def archive_data(d: str) -> list[dict]:
    """보관함 — norn archive가 옮겨 둔 페이지. 삭제가 아니라 이동이라 되살릴 수 있다.

    같은 slug의 스냅샷이 여럿이면 최신만 세운다 (restore가 최신을 복귀시키므로 표시도 최신)."""
    adir = os.path.join(d, "archive")
    latest: dict[str, str] = {}
    try:
        names = os.listdir(adir)
    except OSError:
        return []
    for name in names:
        m = _ARCHIVE_SNAP.match(name)
        if not m:
            continue
        slug, ts = m.group("slug"), m.group("ts")
        if ts > latest.get(slug, ""):
            latest[slug] = ts
    rows = [
        {"slug": slug, "ts": f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}", "restore": f"asgard memory norn-restore {slug}"}
        for slug, ts in latest.items()
    ]
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows[:40]


def backup_data(d: str) -> list[dict]:
    """노른 백업 — merge/archive 직전 pages/ 전량 스냅샷 (최근 5개 유지)."""
    bdir = os.path.join(d, "norn-backups")
    rows: list[dict] = []
    try:
        names = sorted(os.listdir(bdir), reverse=True)
    except OSError:
        return []
    for name in names[:8]:
        path = os.path.join(bdir, name)
        try:
            pages = len([n for n in os.listdir(path) if n.endswith(".md")])
        except OSError:
            continue
        rows.append({"name": name, "pages": pages})
    return rows


def pattern_reports(d: str) -> list[dict]:
    """패턴 학습 리포트 — 관측이 페이지로 승격되기까지의 검증 기록 (reports/pattern-*.md)."""
    rdir = os.path.join(d, "reports")
    out: list[dict] = []
    try:
        names = sorted((n for n in os.listdir(rdir) if n.startswith("pattern-") and n.endswith(".md")), reverse=True)
    except OSError:
        return []
    for name in names[:8]:
        try:
            with open(os.path.join(rdir, name), encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except OSError:
            continue
        ops = [ln[2:].strip() for ln in lines if ln.startswith("- ")]
        out.append(
            {
                "name": name,
                "ops": ops[:12],
                "applied": sum(1 for op in ops if not op.startswith(("✗", "(기각)"))),
                "dropped": sum(1 for op in ops if op.startswith(("✗", "(기각)"))),
            }
        )
    return out


def peer_card_data(d: str) -> dict:
    """오딘 피어 카드 — kind=user 관측이 모인 요약 한 장. 재료(근거 페이지)와 카드 실존을 같이 준다.

    카드는 파생물이라 없을 수 있다 — 그때는 '재료는 n개 있는데 카드가 아직 없다'가 정직한 표시다."""
    try:
        from ...memory.pattern import PEER_CARD_SLUG, peer_card_rows

        rows = [{"slug": slug, "text": text} for slug, text in peer_card_rows(d)]
        return {"slug": PEER_CARD_SLUG, "exists": memory._read(d, PEER_CARD_SLUG) is not None, "rows": rows[:20]}
    except Exception:
        return {"slug": "", "exists": False, "rows": []}


def _norn_auto_mode() -> str:
    try:
        from ...memory.norn import auto_mode

        return auto_mode()
    except Exception:
        return "safe"


def _norn_insight_auto() -> bool:
    """통찰 자동 승격이 켜져 있는가 — 기본은 꺼짐(옵트인). 꺼져 있으면 통찰은 제안까지만 간다."""
    try:
        from ...memory.norn import insight_auto

        return bool(insight_auto())
    except Exception:
        return False


def semantic_data(d: str) -> dict:
    """의미 검색 상태 + **벡터 커버리지** + 못 도는 이유.

    켜져 있다는 말과 이 서고에 실제로 벡터가 있다는 말은 다르다 — 모델을 나중에 켰다면
    옛 페이지에는 벡터가 없고, 의미 검색·의미 엣지는 그 페이지들을 못 본다. 커버리지가
    그 차이를 드러내는 유일한 계기라서 상태 옆에 같이 세운다.

    더 나쁜 혼동이 하나 더 있었다: 기본값은 켜짐(mode=local)인데 라이브러리가 없으면
    동작만 실패한다. 그때 화면이 그냥 "off"라고 적으면 사용자가 **자기가 끈 것**과
    **켜져 있는데 못 도는 것**을 구별할 수 없다 — 원인을 못 찾으니 고칠 수도 없다.
    그래서 설정(mode)과 실동작을 따로 싣고, 어긋나면 왜인지까지 말한다.

    **모델을 올려서 확인하지 않는다.** 예전에는 상태 한 줄을 적으려고 sem.status()를 불렀고,
    그게 임베더를 로드해 관측 창 하나가 1.45GB를 물었다 (실측 25MB → 1,471MB). 창은 보는
    곳이지 돌리는 곳이 아니다.

    대신 더 강한 증거를 쓴다: **이 서고의 페이지에 벡터가 있으면 임베딩은 이미 돌았다.**
    모델을 새로 올려 "될 것 같다"를 확인하는 것보다, 남아 있는 벡터가 "됐었다"를 증명한다.
    벡터가 없을 때만 준비 상태(라이브러리·모델 캐시)로 예측하고, 예측임을 밝힌다."""
    out: dict = {
        "active": False,  # 이 프로세스에 임베더가 실제로 올라와 있는가 (관측)
        "mode": "off",  # 설정값
        "model": "",
        "dim": 0,
        "vectors": 0,
        "pages": 0,
        "pct": 0,
        "state": "off",  # off | ready | blocked
        "evidence": "none",  # loaded(로드됨) | vectors(벡터가 증명) | none(예측)
        "blocked": "",  # 켜짐인데 못 도는 사유
        "fix": "",
        "dims": [],  # 저장된 벡터의 차원들 — 둘 이상이면 모델이 바뀐 것이다
        "dim_mixed": False,
    }
    try:
        conn = memory._db(d)
        out["vectors"] = int(conn.execute("SELECT count(*) FROM vec").fetchone()[0])
        # 모델을 바꾸면 옛 벡터는 차원이 달라지고, cosine은 길이가 다르면 0을 돌려준다
        # (차원 오염 방지). 그래서 검색이 **조용히** 아무것도 못 찾는다 — 벡터 수는 그대로라
        # 커버리지만 보면 멀쩡해 보인다. 섞인 차원이 그 사실을 드러내는 유일한 값이다.
        dims = [int(r[0]) for r in conn.execute("SELECT DISTINCT dim FROM vec").fetchall() if r[0]]
        conn.close()
        out["dims"] = sorted(dims)
        out["dim_mixed"] = len(dims) > 1
    except Exception:
        pass
    out["pages"] = len(memory._pages(d))
    out["pct"] = round(100 * out["vectors"] / out["pages"]) if out["pages"] else 0
    try:
        from ... import memory_semantic as sem

        out["mode"] = str(sem.mode())
        if out["mode"] == "off":
            return out
        # 이미 올라와 있으면 그 사실을 그대로 쓴다 (새로 로드하지는 않는다)
        cache = getattr(sem, "_CACHE", {})
        if cache.get("loaded") and cache.get("fn") is not None:
            out.update({"active": True, "state": "ready", "evidence": "loaded"})
            out["model"], out["dim"] = str(cache.get("model", "")), int(cache.get("dim", 0))
            return out
        has_lib = _embedder_installed()
        if not has_lib:
            # model2vec는 기본 의존성이다(26-07-27 승격) — 없으면 설치가 그 이전 것이다
            out.update({"state": "blocked", "blocked": "library", "fix": "asgard memory semantic status"})
        elif out["vectors"]:
            # 벡터가 남아 있다 = 임베딩이 실제로 돌았다. 모델을 다시 올려 물을 필요가 없다.
            out.update({"state": "ready", "evidence": "vectors"})
        elif not sem.model_cached():
            out.update({"state": "blocked", "blocked": "model", "fix": "asgard memory semantic warmup"})
        else:
            # 부품도 모델도 있는데 아직 벡터가 없다 — 될 것으로 보이지만 확인된 건 아니다
            out.update({"state": "ready", "evidence": "none"})
    except Exception:
        pass
    return out


def _embedder_installed() -> bool:
    """임베더 라이브러리가 설치돼 있는가 — **import 하지 않고** 판정한다.
    import 하는 순간 무거운 의존성이 딸려 올라오므로, 존재 확인은 spec 조회로 끝낸다."""
    from importlib.util import find_spec

    for name in ("model2vec", "sentence_transformers"):
        try:
            if find_spec(name) is not None:
                return True
        except Exception:
            continue
    return False


def derived_data(d: str) -> dict:
    """정본과 파생물의 경계 — 무엇을 잃으면 지식이 죽고, 무엇은 다시 만들어지는가.

    index.md·state.db·maps/ 는 pages/ 에서 재생성되고, reports/·archive/·norn-backups/ 는
    손질이 남긴 기록이다. 이 표가 없으면 사용자는 백업할 것과 지워도 되는 것을 구분할 방법이
    없다 — 대시보드가 답할 수 있는데 안 답하던 물음이었다.

    정본은 pages/ 만이 아니다. **사람의 손이 남긴 것** 둘이 같은 쪽에 있다: 무엇을 실제로
    찾았는가(`usage.json`)와 어떤 어긋남을 보고 넘겼는가(`contradictions.json`). 둘 다
    pages/ 에서 다시 만들 원본이 없어서 파생이 아니고, 그래서 백업 대상이다
    (`backup.CANONICAL_FILES` · `memory.usage` · `memory.contradiction`).

    이 표가 그동안 두 번 틀렸던 자리가 사용기록이다. 처음엔 "손상 시 자동 복구"라고 적혀
    있었는데 사실이 아니었고, 고쳐 적은 "손상되면 영영 사라진다"도 지금은 사실이 아니다 —
    회수 기록이 정본으로 나온 뒤로는 state.db 를 잃어도 `reindex` 가 되살린다. 표는 코드가
    실제로 하는 것만 말한다."""

    def _stat(rel: str, kind: str, canon: bool, note: str) -> dict:
        path = os.path.join(d, rel)
        row = {"name": rel, "kind": kind, "canon": canon, "note": note, "exists": os.path.exists(path), "n": 0}
        if not row["exists"]:
            return row
        if os.path.isdir(path):
            try:
                row["n"] = len([n for n in os.listdir(path) if not n.startswith(".")])
            except OSError:
                row["n"] = 0
        else:
            try:
                row["n"] = os.path.getsize(path)
            except OSError:
                row["n"] = 0
        return row

    return {
        "dir": d,
        "rows": [
            _stat(memory.PAGES, "dir", True, "원본 — 사람이 읽고 고치는 md 파일"),
            _stat(memory.LOG, "file", True, "원본 — 덧붙이기만 하는 작업 기록"),
            _stat(memory.SCHEMA, "file", True, "원본 — 저장 규칙"),
            # 회수 기록과 모순 장부는 pages/ 에서 나오지 않는다 — 사람이 무엇을 찾았고 무엇을
            # 보고 넘겼는지는 페이지에 안 적혀 있다. 그래서 파생이 아니라 정본 쪽에 선다.
            _stat(memory.USAGE, "file", True, "원본 — 사람이 무엇을 실제로 찾았는가 (부패 판정의 근거)"),
            _stat(memory.CONTRADICTIONS, "file", True, "원본 — 어떤 어긋남을 사람이 보고 넘겼는가"),
            _stat(memory.INDEX, "file", False, "자동생성 — asgard memory reindex로 다시 만듦"),
            # 이 줄은 두 번 틀렸다. 처음엔 "손상 시 자동 복구"라고 적혀 있었는데 손상 분기
            # (`index.reindex`)는 파일을 **지우고** pages/ 에서 다시 만들 뿐이라 사실이 아니었고,
            # 고쳐 적은 "사용기록은 영영 사라진다"도 지금은 사실이 아니다.
            #
            # 코드가 실제로 하는 것 (`index.reindex` · `memory.usage`): 재생성 뒤에 정본
            # `usage.json` 을 DB 로 되살리고(`usage.hydrate`) 다시 접는다(`usage.flush`). 사람이
            # 부른 검색은 셀 때마다 곧바로 정본에 접히므로(`usage.bump` — exposure=False) DB 를
            # 통째로 잃어도 uses·last_used 는 돌아온다. 부패 판정이 읽는 값이 그것이라
            # (`pages.lint`의 decay-candidate = 오래됨 + **사용** 0) 판정도 초기화되지 않는다.
            #
            # 안 돌아오는 것은 하나다: 마지막으로 접힌 뒤에 쌓인 **노출** 계수. 노출은 매 턴
            # 일어나 파일 쓰기를 달 수 없어 DB 에만 적고 큰 계기(검색·reindex·백업)에 접힌다.
            # 판정에도 랭킹에도 안 쓰이는 값이라 잃어도 판단이 흔들리지 않는다. 벡터는 시맨틱이
            # 켜져 있을 때만 다시 임베딩된다.
            _stat(
                memory.DB,
                "file",
                False,
                "자동생성 — 검색 색인·벡터는 pages/ 에서, 회수 기록은 usage.json 에서 되살린다 · "
                "마지막으로 접힌 뒤의 노출 계수만 잃는다 (부패 판정은 사용만 보므로 안 흔들린다)",
            ),
            _stat("maps", "dir", False, "자동생성 — Obsidian 목차"),
            _stat("reports", "dir", False, "기록 — 정리·패턴 보고서"),
            _stat("archive", "dir", False, "보관 — 되살릴 수 있음"),
            _stat("norn-backups", "dir", False, "백업 — 정리 직전 원본 사본"),
            _stat(".obsidian", "dir", False, "설정 — Obsidian으로 열기 위한 최소 설정"),
        ],
    }


def _row_title(row: str) -> str:
    """주입 행 `- 제목 — 설명`에서 제목만. 형식이 어긋나면 행 전체를 돌려준다 (fail-open)."""
    text = row[2:] if row.startswith("- ") else row
    return text.split(" — ", 1)[0].strip()


def injection_data(d: str | None = None) -> dict:
    """주입면 — 이 기억이 세션 프롬프트에 **실제로** 어떻게 들어가는가 (읽기 전용).

    다른 패널은 "무엇이 저장돼 있나"를 말한다. 여기는 "무엇이 모델에게 가나"를 말한다 —
    킬스위치·오염 제외·칸 예산·총량 상한 때문에 둘은 같지 않고, 지금까지 대시보드는
    그 차이를 게이지 하나로만 암시했다. 보여 주는 문자열은 재구성이 아니라
    snapshot_note()가 돌려주는 바로 그 블록이다 — 재구성하면 그 순간부터 화면과 프롬프트가 갈린다.

    잘림 판정도 실함수(_section)를 그대로 부른다: 유지되는 행은 언제나 앞에서부터의
    연속분이므로, 남은 행 수를 세면 밀려난 행이 정확히 나온다."""
    d = memory.ensure_home(d)
    from ...memory.recall import _SECTIONS, _SNAPSHOT_WARN, _section, _snapshot_rows

    enabled = bool(memory.inject_enabled())
    text = memory.snapshot_note(d)
    rows = _snapshot_rows(d)
    budgets = memory.kind_budgets()
    sections: list[dict] = []
    for kind, label in _SECTIONS:
        kind_rows = [r for k, r in rows if k == kind]
        budget = int(budgets.get(kind, 0))
        block = _section(kind, label, kind_rows, budget)
        kept = [ln for ln in block.split("\n")[1:] if ln and ln != _SNAPSHOT_WARN] if block else []
        full = sum(len(r) + 1 for r in kind_rows)
        sections.append(
            {
                "kind": kind,
                "label": label,
                "budget": budget,
                "full": full,
                "used": sum(len(r) + 1 for r in kept),
                "pct": round(100 * full / budget) if budget else 0,
                "rows": len(kind_rows),
                "kept": len(kept),
                "muted": budget <= 0 and bool(kind_rows),  # 예산 0 — 저장은 되지만 주입은 안 된다
                "dropped": [_row_title(r) for r in kind_rows[len(kept) :]][:12],
            }
        )
    poisoned = [{"slug": row["slug"], "title": row["title"]} for row in catalog_data(d) if row.get("poisoned")]
    return {
        "enabled": enabled,
        "text": text,
        "chars": len(text),
        "total_budget": memory.index_budget(),
        "recall_budget": memory.RECALL_BUDGET,
        "truncated": _SNAPSHOT_WARN in text,
        "sections": sections,
        "excluded": poisoned[:20],
        "excluded_total": len(poisoned),
    }


def snapshot_data(d: str | None = None) -> dict:
    d = memory.ensure_home(d)
    health = health_data(d)
    catalog = catalog_data(d)
    sem = semantic_data(d)
    return {
        "meta": {
            "dir": d,
            "pages": len(catalog),
            "semantic": sem["state"] == "ready",
            "semantic_mode": sem["mode"],
            "semantic_state": sem["state"],
            "inject": bool(memory.inject_enabled()),  # 킬스위치 — 꺼져 있으면 어떤 provider 로도 안 나간다
            "budget": health["budget"],
            # UTC(aware)로 잡아 표시 경계에서 현지로 돌린다 — 찍히는 글자는 같고, 값이 시간대를 안다.
            "generated": _dt.datetime.now(_dt.UTC).astimezone().strftime("%Y-%m-%d %H:%M"),
        },
        "health": health,
        "catalog": catalog,
        "usage": memory.usage_stats(d),
        "graph": graph_data(d),
        "log": log_data(d, n=120),  # 연대기 탭 분량 — 집계는 activity가 담당
        "activity": activity_data(d),
        "norn": norn_data(d),  # 노른 손질 이력 + insight 계보 + 모순·보관 (손질 탭)
        "semantic": sem,  # 벡터 커버리지 — "켜짐"과 "이 서고에 벡터가 있음"은 다른 말이다
        "derived": derived_data(d),  # 정본/파생 경계
        "peer": peer_card_data(d),  # 오딘 피어 카드 (패턴 학습 산출)
    }


def page_data(slug: str, d: str | None = None) -> dict:
    """페이지 상세 (그래프/목록 클릭 스루) — 읽기 전용. 오염 페이지는 본문 미노출(격리 카드),
    수리는 CLI `asgard memory show --unsafe` 로만 (run_show와 동일 규율)."""
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
        # 문장은 클라이언트가 번역하고, 서버는 명령만 준다 — 슬러그가 낀 통문장은 사전에 못 올린다
        out["quarantine_cmd"] = f"asgard memory show {slug} --unsafe"
    else:
        out["body"] = body
        out["refs"] = re.findall(r"\[\[([^\]]+)\]\]", body)
    return out


def search_data(q: str, k: int, d: str | None = None) -> dict:
    d = d or memory.memory_dir()
    q = (q or "").strip()[:200]
    k = max(1, min(int(k or 5), 25))
    if not q:
        # 빈 질의에 임베더를 올리지 않는다 — 검색을 안 하는데 모델을 물 이유가 없다.
        return {"q": q, "k": k, "semantic_active": semantic_data(d)["state"] == "ready", "hits": []}
    # 관측 무해 — track=False: 대시보드 열람이 usage/decay 통계를 왜곡하지 않는다.
    # 질의는 시맨틱 스트림을 실제로 쓰므로 임베더가 여기서 올라온다 — 쓰는 자리에서 낸다.
    hits = memory.query(q, k=k, d=d, track=False, explain=True)
    # 스트림별 실제 적중은 hit["streams"]가 hit 단위로 말한다 — 여기 플래그는 가용 여부다.
    return {"q": q, "k": k, "semantic_active": semantic_data(d)["state"] == "ready", "hits": hits}
