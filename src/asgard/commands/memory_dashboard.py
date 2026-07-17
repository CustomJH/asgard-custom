"""memory dashboard — 개인 1차 메모리(Tier0 로컬 위키)의 읽기 전용 관측 창.

`asgard memory dashboard` 가 127.0.0.1 에 표준 라이브러리 http.server 만으로 일회성
프로세스를 띄운다(신규 의존성 0, Ctrl-C 종료). 상주 데몬·다포트가 아니다.

계약:
  · 읽기 전용 — 쓰기 엔드포인트 없음. 검색만 파라미터를 받는 GET. 쓰기는 기존 CLI 승인
    게이트가 담당한다 (대시보드는 창이지 손이 아니다).
  · 실데이터 — 모든 패널은 asgard.memory 의 실제 함수(query·lint·_pages·usage_stats 등)에서
    읽는다. 목업 없음.
  · 관측 무해 — 대시보드 검색은 track=False 로 usage 를 변조하지 않는다. 대시보드가 표시하는
    바로 그 decay/회수 통계를 자기 관측으로 왜곡하지 않기 위함이다.

디자인(관문 콘솔 · Gate Console): 나이트+골드 다크 단일 테마. 앱 구성은 agentmemory 뷰어의
셸을 이식 — 상단 탭 바(개요·성좌·서고·연대기·활동) + URL 해시 라우팅(#성좌 딥링크·뒤로가기)
+ 탭별 lazy-load + 전역 data-action 위임 + IME-safe 검색·포커스 보존. 오프닝 = 로고 스플래시
점등 씬(세션 1회, 상단 고정 로고 없음). 성좌 = 물리 시뮬 Canvas 그래프(링크 실선·의미 점선·
죽은 링크 절단선 삼중 엣지 언어), 서고 = 카탈로그+질의 스트림 프리즘(FTS/스캔/시맨틱 레인),
연대기 = 좌우 교차 타임라인(/api/log 서버 페이지네이션·op/day 필터), 활동 = 52주 열지도
(셀 클릭 → 연대기 해당 일자 딥링크). 자동 새로고침 30s — 활성 탭만, document.hidden 정지,
성좌는 데이터 서명 불변이면 재시드하지 않는다(드래그 배치 보존). 자기완결 단일 HTML(외부 CDN 0).
"""

from __future__ import annotations

import base64
import datetime as _dt
import json as _json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .. import memory, ui

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
        from .. import memory_semantic as sem

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


def _semantic_status() -> dict:
    try:
        from .. import memory_semantic as sem

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


# ── 라우팅 (소켓 없이 단위 테스트 가능한 순수 디스패치) ──────────────────────────────


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def host_allowed(host_header: str | None) -> bool:
    """DNS 리바인딩 방어 — Host 헤더의 호스트명이 루프백이어야 한다. 개인 메모리는 로컬
    전용이므로, 외부 도메인이 사용자의 브라우저를 통해 127.0.0.1 을 읽는 표면을 봉쇄한다
    (읽기 전용이어도 카탈로그·스니펫에 사적 내용이 실릴 수 있다 — memory.py P0 정합)."""
    if not host_header:
        return False
    h = host_header.strip().lower()
    if h.startswith("["):  # IPv6 리터럴 [::1]:port
        h = h.split("]")[0] + "]"
    elif ":" in h:  # host:port
        h = h.rsplit(":", 1)[0]
    return h in _LOOPBACK_HOSTS


def dispatch(method: str, path: str, params: dict[str, list[str]], d: str | None = None) -> tuple[int, str, bytes]:
    if method not in ("GET", "HEAD"):
        return 405, "text/plain; charset=utf-8", b"method not allowed"
    if path in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", render_html().encode("utf-8")
    if path == "/api/snapshot":
        body = _json.dumps(snapshot_data(d), ensure_ascii=False).encode("utf-8")
        return 200, "application/json; charset=utf-8", body
    if path == "/api/search":
        q = (params.get("q") or [""])[0]
        try:
            k = int((params.get("k") or ["5"])[0])
        except ValueError:
            k = 5
        body = _json.dumps(search_data(q, k, d), ensure_ascii=False).encode("utf-8")
        return 200, "application/json; charset=utf-8", body
    if path == "/api/page":
        slug = (params.get("slug") or [""])[0]
        data = page_data(slug, d)
        status = 404 if data.get("error") else 200
        return status, "application/json; charset=utf-8", _json.dumps(data, ensure_ascii=False).encode("utf-8")
    if path == "/api/log":

        def _int(name: str, default: int) -> int:
            try:
                return int((params.get(name) or [str(default)])[0])
            except ValueError:
                return default

        op = (params.get("op") or [""])[0].strip() or None
        day = (params.get("day") or [""])[0].strip() or None
        if day and not re.fullmatch(r"\d{4}(-\d{2}){0,2}", day):
            day = None  # 형식 밖 필터는 무시 (fail-open)
        data = log_query(d or memory.memory_dir(), _int("offset", 0), _int("limit", 60), op, day)
        return 200, "application/json; charset=utf-8", _json.dumps(data, ensure_ascii=False).encode("utf-8")
    return 404, "text/plain; charset=utf-8", b"not found"


class _Handler(BaseHTTPRequestHandler):
    server_version = "AsgardMemoryDashboard"

    def _send(self, status: int, ctype: str, body: bytes, head_only: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'",
        )
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _route(self, head_only: bool = False) -> None:
        if not host_allowed(self.headers.get("Host")):
            # DNS 리바인딩·비루프백 Host — 개인 메모리를 외부 출처에 노출하지 않는다.
            self._send(403, "text/plain; charset=utf-8", b"forbidden host", head_only=head_only)
            return
        parts = urlsplit(self.path)
        try:
            status, ctype, body = dispatch(self.command, parts.path, parse_qs(parts.query))
        except Exception as exc:  # 어떤 실패도 서버를 죽이지 않는다 (fail-open)
            status, ctype, body = 500, "text/plain; charset=utf-8", f"error: {type(exc).__name__}".encode()
        self._send(status, ctype, body, head_only=head_only)

    def do_GET(self) -> None:
        self._route()

    def do_HEAD(self) -> None:
        self._route(head_only=True)

    def log_message(self, format: str, *args: object) -> None:  # 조용히 (요청 로그 억제)
        return


def _bind(host: str, port: int) -> ThreadingHTTPServer:
    """요청 포트를 먼저 시도하고, 점유돼 있으면 임시 포트(0)로 폴백한다."""
    try:
        return ThreadingHTTPServer((host, port), _Handler)
    except OSError:
        return ThreadingHTTPServer((host, 0), _Handler)


def run_dashboard(port: int = 8765, host: str = "127.0.0.1", open_browser: bool = True) -> int:
    """127.0.0.1 바인드 · 표준 라이브러리 전용 · Ctrl-C 종료 일회성 프로세스."""
    memory.ensure_home()
    if host not in ("127.0.0.1", "localhost", "::1"):
        ui.warn(f"host {host!r} is not loopback — forcing 127.0.0.1 (개인 메모리는 로컬 전용)")
        host = "127.0.0.1"
    httpd = _bind(host, port)
    actual = httpd.server_address[1]
    url = f"http://{host}:{actual}/"
    ui.ok(f"memory dashboard → {url}")
    ui.step("읽기 전용 관측 창 · 종료: Ctrl-C")
    if open_browser:
        threading.Timer(0.4, lambda: _open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        ui.step("stopped")
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


def _open(url: str) -> None:
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        pass


# ── 프론트엔드 (자기완결 단일 HTML — 외부 CDN·의존성 0) ─────────────────────────────


def render_html() -> str:
    return _PAGE.replace("__LOGO__", _LOGO_URI)


_PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Asgard 개인 1차 메모리(Tier0 로컬 위키) 관측 대시보드 — 개요·기억 성좌 그래프·서고 카탈로그·운영 연대기·활동 열지도. 읽기 전용, 나이트+골드 다크 단일 테마.">
<title>메모리 관문 · Asgard Memory Gate</title>
<style>
  :root{
    --vault:#0C0A07; --surface-1:#14110C; --surface-2:#1B160E; --surface-3:#241C11;
    --line:rgba(230,208,150,.09); --line-strong:rgba(230,208,150,.17);
    --rune-gold:#C6A45E; --gold-lit:#E8C87E; --gem:#5E8A6E;
    --ink:#E9E0CA; --ink-dim:#9C9179; --ink-ghost:rgba(233,224,202,.55);
    --heal:#86A860; --warn:#D2933F; --crit:#C25B46; --info:#6E8BA8;
    --serif:"Iowan Old Style","Palatino Linotype","Palatino","AppleMyungjo","Nanum Myeongjo","Times New Roman",serif;
    --sans:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Segoe UI",Roboto,sans-serif;
    --mono:"SF Mono",ui-monospace,"JetBrains Mono",Menlo,"Cascadia Code",monospace;
  }
  *{box-sizing:border-box}
  html{color-scheme:dark;-webkit-text-size-adjust:100%}
  body{margin:0;background:var(--vault);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.6;
    background-image:radial-gradient(120% 70% at 50% -10%, rgba(198,164,94,.06), transparent 60%);
    background-attachment:fixed;min-height:100vh}
  .skip{position:absolute;left:-999px;top:0;background:var(--surface-3);color:var(--gold-lit);padding:10px 16px;border-radius:6px;z-index:120}
  .skip:focus{left:16px;top:16px}
  .vh{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
  .wrap{max-width:1180px;margin:0 auto;padding:0 20px}
  a{color:var(--gold-lit)}
  code,.mono{font-family:var(--mono)}
  .num{font-family:var(--mono);font-variant-numeric:tabular-nums}
  .dimnote{color:var(--ink-dim);font-size:12px;font-weight:400}
  mark{background:rgba(198,164,94,.28);color:var(--gold-lit);border-radius:2px;padding:0 1px}

  /* ── 스플래시 — 로고 점등 씬 (세션 1회, 콘텐츠 페인트 비차단 오버레이) ── */
  #splash{position:fixed;inset:0;z-index:100;background:#080604;display:flex;flex-direction:column;
    align-items:center;justify-content:center;gap:26px;transition:opacity .55s ease}
  #splash.out{opacity:0;pointer-events:none}
  #splash img{width:min(52vw,320px);height:auto;animation:splash-ignite 1.15s cubic-bezier(.25,.6,.25,1) both}
  /* 폴백 마크는 CSS 로 숨긴다 — SVG 요소에는 hidden 속성이 적용되지 않는다 (실측 결함 수정) */
  #splash .mark{display:none;width:min(30vw,150px);height:auto;color:var(--rune-gold);animation:splash-ignite 1.15s cubic-bezier(.25,.6,.25,1) both}
  #splash.no-img .mark{display:block}
  .splash-word{font-family:var(--mono);font-size:11px;letter-spacing:.42em;text-transform:uppercase;
    color:var(--rune-gold);margin:0;padding-left:.42em;animation:splash-word .8s ease .4s both}
  @keyframes splash-ignite{from{opacity:0;transform:scale(.965);filter:brightness(.3) saturate(.6)}
    to{opacity:1;transform:scale(1);filter:brightness(1) saturate(1)}}
  @keyframes splash-word{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

  /* ── 헤더 — 탭 바와 통합한 최소 헤더 (고정 로고 없음) ── */
  header.top{display:flex;justify-content:space-between;align-items:flex-end;gap:8px 24px;flex-wrap:wrap;
    padding-top:26px;padding-bottom:10px}
  .kicker{font-family:var(--mono);font-size:10.5px;letter-spacing:.3em;text-transform:uppercase;color:var(--rune-gold);margin:0 0 4px}
  h1{font-family:var(--serif);font-weight:500;font-size:clamp(21px,3.2vw,26px);letter-spacing:-.01em;margin:0;color:var(--gold-lit)}
  .meta-line{font-family:var(--mono);font-size:11px;letter-spacing:.05em;color:var(--ink-dim);display:flex;gap:6px 16px;flex-wrap:wrap;justify-content:flex-end}
  .meta-line b{color:var(--ink)}
  .meta-line .on{color:var(--heal)} .meta-line .off{color:var(--ink-ghost)}
  .hright{display:flex;flex-direction:column;align-items:flex-end;gap:7px}
  .livebar{display:flex;align-items:center;gap:8px}
  .live-badge{display:inline-flex;align-items:center;gap:7px;font-family:var(--mono);font-size:10.5px;letter-spacing:.05em;
    color:var(--ink-dim);border:1px solid var(--line);border-radius:999px;padding:5px 12px}
  .live-dot{width:6px;height:6px;border-radius:50%;background:var(--heal);flex:none;animation:live-pulse 2.4s ease-in-out infinite}
  .live-badge.err{color:var(--crit);border-color:color-mix(in oklab,var(--crit) 45%,transparent)}
  .live-badge.err .live-dot{background:var(--crit);animation:none}
  .live-badge.idle .live-dot{background:var(--ink-ghost);animation:none}
  @keyframes live-pulse{0%,100%{opacity:1}50%{opacity:.35}}
  .live-btn{width:44px;height:44px;display:flex;align-items:center;justify-content:center;cursor:pointer;
    background:var(--surface-2);border:1px solid var(--line-strong);border-radius:8px;color:var(--gold-lit)}
  .live-btn:hover{border-color:var(--rune-gold)}
  .live-btn:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px}
  .live-btn:active{transform:scale(.96)}
  .live-btn[disabled]{opacity:.45;cursor:default;transform:none}
  .live-btn[disabled] svg{animation:live-spin .8s linear infinite}
  @keyframes live-spin{to{transform:rotate(360deg)}}

  /* ── 탭 바 (agentmemory 셸 — APG tablist: roving tabindex + aria-selected) ── */
  .tabbar{display:flex;gap:2px;border-bottom:1px solid var(--line-strong);overflow-x:auto}
  .tabbar [role=tab]{appearance:none;background:none;border:none;border-bottom:2px solid transparent;color:var(--ink-dim);
    font-family:var(--sans);font-size:13.5px;letter-spacing:.02em;padding:12px 16px;min-height:44px;cursor:pointer;
    display:inline-flex;align-items:center;gap:8px;white-space:nowrap;margin-bottom:-1px}
  .tabbar [role=tab] svg{color:currentColor;opacity:.8;flex:none}
  .tabbar [role=tab]:hover{color:var(--ink)}
  .tabbar [role=tab].on{color:var(--gold-lit);border-bottom-color:var(--rune-gold)}
  .tabbar [role=tab]:focus-visible{outline:2px solid var(--rune-gold);outline-offset:-2px}

  .view{display:none}
  .view.active{display:block;animation:view-in .22s ease-out}
  @keyframes view-in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
  main{padding-top:22px;padding-bottom:90px}

  h2{font-family:var(--serif);font-weight:500;font-size:17px;color:var(--gold-lit);margin:0 0 14px;letter-spacing:.01em;display:flex;align-items:center;gap:9px}
  h2 svg{color:var(--rune-gold);flex:none}
  .panel{background:var(--surface-1);border:1px solid var(--line);border-radius:12px;padding:20px}
  .grid{display:grid;gap:18px}
  @media(min-width:860px){.two{grid-template-columns:1fr 1fr}.side{grid-template-columns:auto 1fr}}

  /* ── 개요 — 통계 카드 그리드 → 게이지+건강 → 시맨틱 → 2단 (agentmemory Dashboard 구성) ── */
  .stats5{grid-template-columns:repeat(auto-fit,minmax(160px,1fr));margin-bottom:18px}
  .stat{background:var(--surface-2);border:1px solid var(--line);border-radius:10px;padding:13px 15px}
  .stat .v{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:26px;line-height:1.1;color:var(--gold-lit)}
  .stat .l{font-size:12px;color:var(--ink);margin-top:5px}
  .stat .s{font-size:11px;color:var(--ink-ghost);margin-top:2px}
  .stat.crit .v{color:var(--crit)} .stat.warn .v{color:var(--warn)}
  .gauge-card{display:flex;align-items:center;gap:18px;margin:0}
  .gauge-card figcaption{font-size:12.5px;color:var(--ink-dim);line-height:1.5}
  .gauge-card .lab,.semstrip .lab{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--rune-gold)}
  .semstrip{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;padding:13px 20px;margin:0 0 18px;font-size:13px;color:var(--ink-dim)}

  .flist{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:8px;max-height:300px;overflow:auto}
  .flist li{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:baseline;font-size:13px;padding-bottom:8px;border-bottom:1px solid var(--line)}
  .flist li:last-child{border-bottom:none}
  .flist .sl{font-family:var(--mono);font-size:12px;color:var(--gold-lit)}
  .flist .ms{color:var(--ink-dim);font-size:12.5px}

  .uselist{list-style:none;padding:0;margin:0}
  .uselist li{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;padding:7px 0;border-bottom:1px solid var(--line);font-size:13px}
  .uselist li:last-child{border-bottom:none}
  .uselist .u{font-family:var(--mono);color:var(--gold-lit);font-variant-numeric:tabular-nums}
  .uselist .du{font-family:var(--mono);font-size:11px;color:var(--ink-dim)}

  .log{list-style:none;padding:0;margin:0;max-height:320px;overflow:auto}
  .log li{display:grid;grid-template-columns:auto auto 1fr;gap:12px;align-items:baseline;padding:6px 0;border-bottom:1px solid var(--line);font-size:12.5px}
  .log li:last-child{border-bottom:none}
  .log .ts{font-family:var(--mono);font-size:10.5px;color:var(--ink-ghost);white-space:nowrap}
  .log .op{font-family:var(--mono);font-size:10.5px;letter-spacing:.04em;color:var(--rune-gold);white-space:nowrap}
  .log .sl{font-family:var(--mono);color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

  /* ── 기억 성좌 (일급 그래프 뷰 — 기존 물리 시뮬 그대로 이관) ── */
  .gbody{display:grid;gap:14px;grid-template-columns:minmax(0,1fr)}
  @media(min-width:980px){.gbody{grid-template-columns:minmax(0,1fr) 296px}}
  .gwrap{position:relative;border:1px solid var(--line);border-radius:10px;overflow:hidden;height:400px;
    background:radial-gradient(90% 80% at 50% 28%, rgba(198,164,94,.05), transparent 70%), var(--surface-2)}
  @media(min-width:980px){.gwrap{height:560px}}
  #gcanvas{position:absolute;inset:0;width:100%;height:100%;display:block;cursor:grab;touch-action:none}
  #gcanvas:focus-visible{outline:2px solid var(--rune-gold);outline-offset:-2px}
  .gctrl{position:absolute;top:10px;right:10px;display:flex;flex-direction:column;gap:6px}
  .gctrl button{width:44px;height:44px;display:flex;align-items:center;justify-content:center;cursor:pointer;
    background:rgba(20,17,12,.88);border:1px solid var(--line-strong);border-radius:8px;color:var(--gold-lit)}
  .gctrl button:hover{border-color:var(--rune-gold)}
  .gctrl button:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px}
  .ghint{position:absolute;left:12px;bottom:6px;margin:0;font-family:var(--mono);font-size:10px;letter-spacing:.04em;
    color:var(--ink-ghost);pointer-events:none;max-width:78%}
  .gtip{position:absolute;pointer-events:none;z-index:5;background:rgba(12,10,7,.95);border:1px solid var(--line-strong);
    border-radius:8px;padding:8px 11px;font-size:12px;line-height:1.5;opacity:0;transition:opacity .15s ease;max-width:250px}
  .gtip.on{opacity:1}
  .gtip .tt-t{color:var(--ink);font-weight:600}
  .gtip .tt-k{font-family:var(--mono);font-size:10.5px;letter-spacing:.06em}
  .gtip .tt-m{color:var(--ink-dim);font-size:11px;font-family:var(--mono)}
  .gside{display:flex;flex-direction:column;gap:14px;max-height:560px;overflow-y:auto;padding-right:2px}
  .gside input[type=search]{width:100%;background:var(--surface-2);border:1px solid var(--line-strong);border-radius:8px;
    color:var(--ink);font-family:var(--sans);font-size:14px;padding:10px 12px}
  .gside input[type=search]::placeholder{color:var(--ink-dim)}
  .gside input[type=search]:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px;border-color:var(--rune-gold)}
  .gstats{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .gstats .cell{background:var(--surface-2);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
  .gstats .cell .v{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:19px;color:var(--gold-lit);line-height:1.2}
  .gstats .cell .l{font-size:10.5px;color:var(--ink-dim)}
  .gstats .cell.bad .v{color:var(--crit)} .gstats .cell.warn .v{color:var(--warn)}
  .gfilters{display:flex;flex-direction:column;gap:2px}
  .fitem{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink);padding:7px 6px;border-radius:6px;cursor:pointer}
  .fitem:hover{background:var(--surface-2)}
  .fitem input{accent-color:var(--rune-gold);width:15px;height:15px;margin:0}
  .fitem input:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px}
  .fitem .cnt{margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--ink-dim)}
  .glegend{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--ink-dim)}
  .glegend li{display:flex;align-items:center;gap:9px}
  .glegend svg{flex:none}
  .sectitle{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--rune-gold);margin:0 0 8px}
  .gdet{background:var(--surface-2);border:1px solid var(--line-strong);border-radius:10px;padding:14px}
  .gdet-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px}
  .gclose{background:none;border:1px solid var(--line-strong);border-radius:6px;color:var(--ink-dim);
    font-family:var(--mono);font-size:11px;padding:5px 14px;cursor:pointer;min-height:44px;min-width:44px}
  .gclose:hover{color:var(--gold-lit);border-color:var(--rune-gold)}
  .gclose:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px}
  .gdet-title{font-family:var(--serif);font-weight:500;font-size:15.5px;color:var(--gold-lit);margin:0 0 2px}
  .gdet-slug{font-size:11px;color:var(--ink-dim);margin:0 0 10px}
  .gdet-meta{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:0 0 10px;font-size:12px}
  .gdet-meta dt{color:var(--ink-dim)} .gdet-meta dd{margin:0;font-family:var(--mono);font-size:11.5px;color:var(--ink)}
  .gdet-body{font-family:var(--mono);font-size:11.5px;line-height:1.65;color:var(--ink);white-space:pre-wrap;word-break:break-word;
    background:var(--surface-1);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:0 0 10px;max-height:220px;overflow:auto}
  .gdet-poison{color:var(--crit);font-size:12.5px;border:1px solid color-mix(in oklab,var(--crit) 45%,transparent);
    background:color-mix(in oklab,var(--crit) 10%,var(--surface-1));border-radius:8px;padding:9px 12px;margin:0 0 10px}
  .gdet-links{display:flex;flex-wrap:wrap;gap:6px}
  .lchip{background:var(--surface-1);border:1px solid var(--line-strong);border-radius:999px;color:var(--gold-lit);
    font-family:var(--mono);font-size:11px;padding:5px 13px;cursor:pointer;min-height:44px}
  .lchip:hover{border-color:var(--rune-gold)}
  .lchip:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px}
  .glist{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:4px}
  .glist li{font-family:var(--mono);font-size:12px;color:var(--ink-dim);display:flex;align-items:center;gap:8px}
  .glist .dot{width:7px;height:7px;border-radius:50%;background:var(--warn);flex:none}
  .linklike{background:none;border:none;padding:6px 2px;margin:-6px 0;color:var(--gold-lit);font-family:inherit;font-size:inherit;
    cursor:pointer;text-align:left;border-radius:4px}
  .linklike:hover{text-decoration:underline}
  .linklike:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px}

  /* ── 서고 — 검색(질의 스트림 프리즘 통합) + 종류 칩 + 카탈로그 표 ── */
  .search{display:flex;gap:10px;margin-bottom:12px}
  .search input{flex:1;background:var(--surface-2);border:1px solid var(--line-strong);border-radius:8px;color:var(--ink);
    font-family:var(--sans);font-size:15px;padding:11px 14px;min-width:0}
  .search input::placeholder{color:var(--ink-dim)}
  .search input:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px;border-color:var(--rune-gold)}
  .search button{background:var(--surface-3);border:1px solid var(--line-strong);border-radius:8px;color:var(--gold-lit);
    font-family:var(--mono);font-size:13px;letter-spacing:.06em;padding:0 18px;cursor:pointer;min-height:44px}
  .search button:hover{border-color:var(--rune-gold)}
  .search button:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px}
  .legend{display:flex;gap:14px;font-family:var(--mono);font-size:10.5px;letter-spacing:.05em;color:var(--ink-dim);margin-bottom:12px;flex-wrap:wrap}
  .legend i{display:inline-block;width:16px;height:4px;border-radius:2px;vertical-align:middle;margin-right:5px}
  .chips{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}
  .chip{display:inline-flex;align-items:center;gap:7px;background:var(--surface-2);border:1px solid var(--line-strong);
    border-radius:999px;color:var(--ink-dim);font-family:var(--mono);font-size:11.5px;padding:0 15px;min-height:44px;cursor:pointer}
  .chip:hover{border-color:var(--rune-gold);color:var(--ink)}
  .chip:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px}
  .chip.on{color:var(--gold-lit);border-color:var(--rune-gold);background:color-mix(in oklab,var(--rune-gold) 12%,var(--surface-1))}
  .chip .cnt{color:var(--ink-ghost);font-size:10px}
  .qrow{display:grid;grid-template-columns:1fr auto;gap:14px;align-items:center;background:var(--surface-2);
    border:1px solid var(--line);border-radius:9px;padding:11px 14px;margin-bottom:8px;cursor:pointer;
    transition:border-color .2s ease,transform .2s ease}
  .qrow:hover,.qrow:focus-within{border-color:var(--line-strong);transform:translateY(-1px)}
  .qrow:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px}
  .qrow .t{font-size:14.5px;color:var(--ink)}
  .qrow .t .sub{display:block;font-family:var(--mono);font-size:11px;color:var(--ink-dim);margin-top:3px}
  .qrow .t .snip{display:block;font-size:12.5px;color:var(--ink-dim);margin-top:4px;max-width:62ch}
  .lanes{display:flex;flex-direction:column;gap:3px;width:104px}
  .lane{display:flex;align-items:center;gap:7px;font-family:var(--mono);font-size:9px;letter-spacing:.06em;color:var(--ink-dim)}
  .lane .bar{height:4px;border-radius:2px;flex:1;background:var(--line-strong)}
  .lane.on.fts .bar{background:var(--rune-gold)} .lane.on.sem .bar{background:var(--gem)} .lane.on.scan .bar{background:var(--info)}
  .lane.off{opacity:.3}
  .dbox{margin:-2px 0 8px}
  tr.dtr>td{padding:2px 10px 12px}
  .dwrap .gdet{margin-top:6px}
  .ubar{display:inline-block;width:56px;height:5px;border-radius:3px;background:var(--surface-3);margin-right:8px;vertical-align:2px;overflow:hidden}
  .ubar i{display:block;height:100%;background:var(--rune-gold)}

  /* ── 칩·글리프 ── */
  .kchip{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:11px;letter-spacing:.03em;color:var(--ink);
    background:var(--surface-2);border:1px solid var(--line);border-radius:999px;padding:2px 10px 2px 7px;white-space:nowrap}
  .kchip svg{flex:none;color:var(--rune-gold)}
  .fchip{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;font-family:var(--mono);border-radius:6px;padding:2px 8px;border:1px solid}
  .f-crit{color:var(--crit);border-color:color-mix(in oklab,var(--crit) 45%,transparent);background:color-mix(in oklab,var(--crit) 12%,var(--surface-1))}
  .f-warn{color:var(--warn);border-color:color-mix(in oklab,var(--warn) 42%,transparent);background:color-mix(in oklab,var(--warn) 12%,var(--surface-1))}
  .f-info{color:var(--info);border-color:color-mix(in oklab,var(--info) 40%,transparent);background:color-mix(in oklab,var(--info) 12%,var(--surface-1))}

  /* ── 카탈로그 표 ── */
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  caption{text-align:left;color:var(--ink-dim);font-size:12px;margin-bottom:8px}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
  thead th{color:var(--rune-gold);font-family:var(--mono);font-size:10px;letter-spacing:.11em;text-transform:uppercase;font-weight:500;border-bottom:1px solid var(--line-strong)}
  tbody tr:last-child td{border-bottom:none}
  tbody tr:hover{background:var(--surface-2)}
  td.ti{color:var(--ink)} td.di{color:var(--ink-dim)} .rt{text-align:right;font-variant-numeric:tabular-nums;font-family:var(--mono)}
  .poison{color:var(--crit);font-family:var(--mono);font-size:10.5px;border:1px solid color-mix(in oklab,var(--crit) 45%,transparent);border-radius:5px;padding:1px 6px;margin-right:6px}

  /* ── 연대기 — 좌우 교차 수직 타임라인 (agentmemory Timeline 구성) ── */
  .chrono{position:relative;padding:6px 0}
  .chrono::before{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--line-strong)}
  .cdate{position:relative;text-align:center;margin:18px 0 16px;z-index:1}
  .cdate span{background:var(--surface-3);border:1px solid var(--line-strong);border-radius:999px;color:var(--rune-gold);
    font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;padding:4px 14px}
  .citem{position:relative;width:50%;padding:0 26px 14px}
  .citem.right{margin-left:50%}
  .cdot{position:absolute;top:14px;width:9px;height:9px;border-radius:50%;border:2px solid var(--vault)}
  .citem.left .cdot{right:-5.5px}
  .citem.right .cdot{left:-5.5px}
  .ccard{background:var(--surface-2);border:1px solid var(--line);border-radius:9px;padding:10px 13px}
  .chead{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
  .ctime{font-family:var(--mono);font-size:10px;color:var(--ink-ghost);margin-left:auto}
  .cdet{color:var(--ink-dim);font-size:12px;margin-top:5px;word-break:break-word}
  .obadge{display:inline-flex;align-items:center;gap:5px;font-family:var(--mono);font-size:10.5px;border:1px solid;border-radius:5px;padding:2px 7px}
  @media(max-width:760px){
    .chrono::before{left:10px}
    .citem{width:100%;padding:0 0 12px 28px}
    .citem.right{margin-left:0}
    .citem.left .cdot,.citem.right .cdot{left:6px;right:auto}
  }

  /* ── 활동 — 52주 열지도 + 작업 분포 + 피드 (agentmemory Activity 구성) ── */
  .heat{display:flex;gap:6px;align-items:flex-start}
  .heat-days{display:grid;grid-template-rows:repeat(7,11px);gap:3px;font-family:var(--mono);font-size:9px;color:var(--ink-ghost);flex:none}
  .heat-scroll{overflow-x:auto;padding-bottom:4px}
  .heat-grid{display:grid;grid-template-rows:repeat(7,11px);grid-auto-flow:column;grid-auto-columns:11px;gap:3px}
  .heat-cell{width:11px;height:11px;border-radius:2.5px;background:var(--surface-2);border:1px solid var(--line);padding:0}
  button.heat-cell{cursor:pointer;appearance:none}
  button.heat-cell:hover{border-color:var(--rune-gold)}
  button.heat-cell:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px}
  .heat-cell.lv1{background:rgba(198,164,94,.22)}
  .heat-cell.lv2{background:rgba(198,164,94,.45);border-color:rgba(198,164,94,.3)}
  .heat-cell.lv3{background:rgba(214,182,110,.72);border-color:rgba(198,164,94,.45)}
  .heat-cell.lv4{background:#E8C87E;border-color:#E8C87E}
  .heat-legend{display:flex;align-items:center;gap:4px;justify-content:flex-end;margin-top:8px;font-family:var(--mono);font-size:10px;color:var(--ink-ghost)}
  .bars{display:flex;flex-direction:column;gap:9px}
  .bar-row{display:grid;grid-template-columns:88px 1fr auto;gap:10px;align-items:center;font-size:12.5px}
  .bar-label{font-family:var(--mono);font-size:11px;color:var(--ink-dim);overflow:hidden;text-overflow:ellipsis}
  .bar-track{height:7px;background:var(--surface-3);border-radius:4px;overflow:hidden}
  .bar-fill{height:100%;border-radius:4px}
  .bar-val{font-family:var(--mono);font-size:11px;color:var(--ink)}

  .empty{color:var(--ink-dim);font-size:13px;padding:8px 0}

  /* ── 빈 서고 온보딩 — 빈 표 대신 행동 유도 ── */
  .onboard{display:flex;flex-direction:column;align-items:flex-start;gap:10px;padding:20px 4px;color:var(--ink-dim);font-size:13px;line-height:1.6}
  .onboard svg{color:var(--rune-gold)}
  .onboard p{margin:0}
  .onboard b{color:var(--ink);font-weight:600}
  .onboard code{display:inline-block;background:var(--surface-2);border:1px solid var(--line-strong);border-radius:6px;
    padding:9px 13px;color:var(--gold-lit);font-size:12px;user-select:all}

  /* ── 연대기 페이지네이션 + 날짜 딥링크 필터 ── */
  .pgn{display:flex;align-items:center;justify-content:center;gap:12px;margin-top:16px;
    font-family:var(--mono);font-size:11.5px;color:var(--ink-dim);flex-wrap:wrap}
  .pgn button{background:var(--surface-2);border:1px solid var(--line-strong);border-radius:8px;color:var(--gold-lit);
    font-family:var(--mono);font-size:12px;padding:0 16px;min-height:44px;cursor:pointer}
  .pgn button:hover{border-color:var(--rune-gold)}
  .pgn button:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px}
  .pgn button[disabled]{opacity:.35;cursor:default;border-color:var(--line)}
  .dayflt{display:inline-flex;align-items:center;gap:9px;background:color-mix(in oklab,var(--rune-gold) 10%,var(--surface-1));
    border:1px solid var(--rune-gold);border-radius:999px;color:var(--gold-lit);font-family:var(--mono);font-size:11.5px;
    padding:5px 8px 5px 15px;margin:0 0 14px}
  .dayflt button{background:none;border:none;color:var(--gold-lit);cursor:pointer;font-family:var(--mono);font-size:11px;
    min-width:34px;min-height:34px;border-radius:999px;display:inline-flex;align-items:center;justify-content:center}
  .dayflt button:hover{background:rgba(198,164,94,.18)}
  .dayflt button:focus-visible{outline:2px solid var(--rune-gold);outline-offset:1px}

  /* ── 성좌 시맨틱 opt-in 안내 ── */
  .semhint{display:flex;gap:9px;align-items:flex-start;border:1px dashed color-mix(in oklab,var(--gem) 55%,transparent);
    border-radius:8px;padding:10px 12px;font-size:12px;color:var(--ink-dim);line-height:1.55;margin:0}
  .semhint svg{flex:none;color:var(--gem);margin-top:2px}
  .semhint code{color:var(--gold-lit);font-size:11px}
  footer{margin-top:50px;padding-top:20px;border-top:1px solid var(--line);color:var(--ink-ghost);font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;text-align:center}

  @media(prefers-reduced-motion:reduce){
    #splash{display:none}
    .qrow{transition:none}
    .view.active{animation:none}
    .live-dot,.live-btn[disabled] svg{animation:none}
    .live-btn:active{transform:none}
    html{scroll-behavior:auto}
  }
</style>
</head>
<body>
<!-- 스플래시 — 검은 화면에 골드 로고 점등, 데이터 로드 후 디졸브. 본문은 아래에 이미 페인트된다. -->
<div id="splash" aria-hidden="true">
  <img id="splashImg" src="__LOGO__" alt="">
  <svg id="splashMark" class="mark" viewBox="0 0 120 96" aria-hidden="true">
    <path d="M18 90V52a42 42 0 0 1 84 0v38" fill="none" stroke="currentColor" stroke-width="2.5"/>
    <path d="M33 90V55a27 27 0 0 1 54 0v35" fill="none" stroke="currentColor" stroke-width="2"/>
    <path d="M48 90V58a12 12 0 0 1 24 0v32" fill="none" stroke="currentColor" stroke-width="1.5"/>
    <path d="M10 90h100" stroke="currentColor" stroke-width="2.5"/>
  </svg>
  <p class="splash-word">Asgard · Memory Gate</p>
</div>
<script>
"use strict";
// 스플래시 게이트 — 세션 재방문·reduced-motion 이면 페인트 전에 제거한다.
(function(){
  var reduced = false, seen = false;
  try{ reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches; }catch(e){}
  try{ seen = !!sessionStorage.getItem("asgard-splash-lit"); }catch(e){}
  var sp = document.getElementById("splash");
  if(!sp) return;
  var img = document.getElementById("splashImg");
  if(img && !img.getAttribute("src")){ // 로고 에셋 부재 — 관문 삼중 아치 마크로 우아하게 저하
    img.remove();
    sp.classList.add("no-img");
  }
  if(seen || reduced){ sp.remove(); }
  else{
    try{ sessionStorage.setItem("asgard-splash-lit", "1"); }catch(e){}
    window.__splashT0 = performance.now();
  }
})();
</script>
<a class="skip" href="#main">본문으로 건너뛰기</a>

<header class="wrap top">
  <div>
    <p class="kicker">Asgard · Tier0 Memory Gate</p>
    <h1>메모리 관문</h1>
  </div>
  <div class="hright">
    <div class="livebar">
      <span class="live-badge idle" id="liveBadge"><span class="live-dot" aria-hidden="true"></span><span id="liveText">갱신 30s · <span id="liveTime" class="num">—</span></span></span>
      <button type="button" class="live-btn" id="refreshBtn" data-action="refresh-now" aria-label="지금 새로고침"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true"><path d="M12.3 8.2a5 5 0 1 1-1.2-4.4" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M12.6 1.2v3h-3" fill="none" stroke="currentColor" stroke-width="1.4"/></svg></button>
    </div>
    <div class="meta-line" id="metaLine">불러오는 중…</div>
  </div>
</header>

<!-- 탭 바 — agentmemory 뷰어 셸 이식: 해시 딥링크 + 탭별 lazy-load. 데이터가 실존하는 5탭만. -->
<nav class="wrap" aria-label="관측 창 내비게이션">
  <div class="tabbar" id="tabBar" role="tablist" aria-label="관측 창 보기">
    <button type="button" role="tab" id="tab-개요" data-tab="개요" class="on" aria-selected="true" aria-controls="view-개요" tabindex="0"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M2 10a5.5 5.5 0 0 1 10 0" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M7 10L9.6 6.6" stroke="currentColor" stroke-width="1.3"/><circle cx="7" cy="10" r="1.1" fill="currentColor"/></svg>개요</button>
    <button type="button" role="tab" id="tab-성좌" data-tab="성좌" aria-selected="false" aria-controls="view-성좌" tabindex="-1"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="3" cy="3.5" r="1.3" fill="currentColor"/><circle cx="11" cy="2.8" r="1" fill="currentColor"/><circle cx="7" cy="8" r="1.6" fill="currentColor"/><circle cx="11.5" cy="11" r="1.2" fill="currentColor"/><path d="M3 3.5L7 8l4-5.2M7 8l4.5 3" stroke="currentColor" stroke-width=".8" fill="none" opacity=".6"/></svg>성좌</button>
    <button type="button" role="tab" id="tab-서고" data-tab="서고" aria-selected="false" aria-controls="view-서고" tabindex="-1"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><rect x="1.8" y="1.8" width="10.4" height="10.4" rx="1" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M1.8 5.5h10.4M5.5 5.5V12.2" stroke="currentColor" stroke-width="1.2"/></svg>서고</button>
    <button type="button" role="tab" id="tab-연대기" data-tab="연대기" aria-selected="false" aria-controls="view-연대기" tabindex="-1"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="5.2" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M7 4v3.2l2.4 1.6" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>연대기</button>
    <button type="button" role="tab" id="tab-활동" data-tab="활동" aria-selected="false" aria-controls="view-활동" tabindex="-1"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><rect x="1.5" y="1.5" width="5" height="5" rx="1" fill="currentColor" opacity=".35"/><rect x="7.7" y="1.5" width="5" height="5" rx="1" fill="currentColor" opacity=".6"/><rect x="1.5" y="7.7" width="5" height="5" rx="1" fill="currentColor" opacity=".85"/><rect x="7.7" y="7.7" width="5" height="5" rx="1" fill="currentColor"/></svg>활동</button>
  </div>
</nav>

<main id="main" class="wrap">

  <!-- ══ 개요 (agentmemory Dashboard 구성: 통계 카드 → 게이지 → 2단) ══ -->
  <section class="view active" id="view-개요" role="tabpanel" aria-labelledby="tab-개요">
    <div class="grid stats5" id="ovStats" aria-label="서고 통계"></div>
    <div id="ovOnboard"></div>
    <div class="grid side" style="margin-bottom:18px">
      <figure class="panel gauge-card">
        <div id="gauge" aria-hidden="true"></div>
        <figcaption>
          <div class="lab">룬-링 인덱스 예산</div>
          <div id="budgetText" style="margin-top:6px">—</div>
        </figcaption>
      </figure>
      <section class="panel" aria-label="건강 진단">
        <h2><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5l5.5 2.4v3.6c0 3.4-2.3 5.5-5.5 6.5-3.2-1-5.5-3.1-5.5-6.5V3.9z" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M5.6 8l1.7 1.7 3.1-3.4" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>건강 진단</h2>
        <ul class="flist" id="findList"></ul>
      </section>
    </div>
    <p class="panel semstrip" id="semState"></p>
    <div class="grid two">
      <section class="panel" aria-label="최근 연대기 발췌">
        <h2><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5h8M4 5.5h8M4 8.5h5M4 11.5h6" stroke="currentColor" stroke-width="1.2"/></svg>연대기 발췌</h2>
        <ul class="log" id="ovLog"></ul>
        <p style="margin:12px 0 0"><button type="button" class="linklike" data-action="open-tab" data-tab="연대기">연대기 전체 보기 →</button></p>
      </section>
      <section class="panel" aria-label="회수 상위">
        <h2><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v5l3 2" fill="none" stroke="currentColor" stroke-width="1.2"/><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>자주 회수됨</h2>
        <ul class="uselist" id="topUse"></ul>
      </section>
    </div>
  </section>

  <!-- ══ 성좌 — 일급 그래프 뷰 (기존 Canvas 물리 시뮬 그대로 이관) ══ -->
  <section class="view" id="view-성좌" role="tabpanel" aria-labelledby="tab-성좌">
    <section class="panel" id="constellation" aria-label="기억 성좌 그래프">
      <h2><svg width="17" height="17" viewBox="0 0 17 17" aria-hidden="true"><circle cx="3.5" cy="4" r="1.7" fill="currentColor"/><circle cx="13" cy="3" r="1.3" fill="currentColor"/><circle cx="8.5" cy="9.5" r="2" fill="currentColor"/><circle cx="14" cy="13.5" r="1.5" fill="currentColor"/><circle cx="3" cy="13" r="1.2" fill="currentColor"/><path d="M3.5 4L8.5 9.5 13 3M8.5 9.5l5.5 4M8.5 9.5L3 13" stroke="currentColor" stroke-width=".9" fill="none" opacity=".55"/></svg>기억 성좌 <span id="gCount" class="num dimnote"></span></h2>
      <div class="gbody">
        <div class="gwrap">
          <canvas id="gcanvas" tabindex="0" role="application" aria-describedby="gHelp"
            aria-label="기억 성좌 캔버스 — 페이지가 별, 링크·의미 유사가 별자리 선. 화살표 키로 이동, 대괄호 키로 노드 순회."></canvas>
          <div class="gctrl" role="group" aria-label="성좌 보기 조절">
            <button type="button" data-action="g-zoom-in" aria-label="확대"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true"><path d="M7.5 2.5v10M2.5 7.5h10" stroke="currentColor" stroke-width="1.6"/></svg></button>
            <button type="button" data-action="g-zoom-out" aria-label="축소"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true"><path d="M2.5 7.5h10" stroke="currentColor" stroke-width="1.6"/></svg></button>
            <button type="button" data-action="g-recenter" aria-label="처음 위치로"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true"><circle cx="7.5" cy="7.5" r="4.2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M7.5 .8v3M7.5 11.2v3M.8 7.5h3M11.2 7.5h3" stroke="currentColor" stroke-width="1.3"/></svg></button>
          </div>
          <div class="gtip" id="gTip" aria-hidden="true"></div>
          <p class="ghint" id="gHelp">드래그 이동 · 휠 줌 · 키보드: 화살표 팬 / + − 줌 / ] [ 노드 순회 / Enter 상세로 / Esc 해제 / 0 초기화</p>
        </div>
        <aside class="gside" aria-label="성좌 조작반">
          <div>
            <label class="vh" for="gq">성좌에서 노드 검색</label>
            <input id="gq" type="search" placeholder="노드 검색 — 제목·슬러그" autocomplete="off">
          </div>
          <div id="gDetail"></div>
          <div class="gstats" id="gStats" aria-label="성좌 통계"></div>
          <div>
            <p class="sectitle">종류 필터 — 색+형태 이중 인코딩</p>
            <div id="gFilters" class="gfilters"></div>
          </div>
          <div>
            <p class="sectitle">엣지 언어</p>
            <ul class="glegend">
              <li><svg width="28" height="10" aria-hidden="true"><path d="M2 5h24" stroke="#C6A45E" stroke-width="2"/></svg>명시 링크 — 실선 골드</li>
              <li><svg width="28" height="10" aria-hidden="true"><path d="M2 5h24" stroke="#5E8A6E" stroke-width="2" stroke-dasharray="4 3"/></svg>의미 유사 — 점선 비취 (코사인 가중)</li>
              <li><svg width="28" height="10" aria-hidden="true"><path d="M2 5h16" stroke="#C25B46" stroke-width="1.6" stroke-dasharray="3 3"/><path d="M20 2l6 6M26 2l-6 6" stroke="#C25B46" stroke-width="1.4"/></svg>죽은 링크 — 붉은 절단선</li>
            </ul>
          </div>
          <div id="gSemHint"></div>
          <div>
            <p class="sectitle">고아 성단 <span id="orphanCount" class="num"></span></p>
            <ul class="glist" id="orphanList"></ul>
          </div>
        </aside>
      </div>
      <div id="gAnnounce" class="vh" role="status" aria-live="polite"></div>
    </section>
  </section>

  <!-- ══ 서고 — 카탈로그 + 질의 스트림 프리즘 통합 (agentmemory Memories 구성) ══ -->
  <section class="view" id="view-서고" role="tabpanel" aria-labelledby="tab-서고">
    <section class="panel" aria-label="서고 카탈로그">
      <h2><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><rect x="2.5" y="2.5" width="11" height="11" rx="1" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M2.5 6.5h11M6.5 6.5v7" stroke="currentColor" stroke-width="1.2"/></svg>서고 <span id="catCount" class="num dimnote"></span></h2>
      <form class="search" id="searchForm" role="search">
        <label for="q" class="vh">서고 검색어</label>
        <input id="q" name="q" type="search" placeholder="이 서고에서 무엇을 찾나 — RRF 하이브리드 검색 (읽기 전용)" autocomplete="off">
        <button type="submit">검색</button>
      </form>
      <div class="legend" id="legend">
        <span class="sectitle" style="margin:0">질의 스트림 프리즘</span>
        <span><i style="background:var(--rune-gold)"></i>FTS BM25</span>
        <span><i style="background:var(--info)"></i>정본 스캔</span>
        <span><i style="background:var(--gem)"></i>시맨틱</span>
        <span id="semNote"></span>
      </div>
      <div id="kindChips" class="chips" role="group" aria-label="종류 필터"></div>
      <div id="sortChips" class="chips" role="group" aria-label="정렬 기준"></div>
      <div id="libBody" aria-live="polite"><p class="empty">불러오는 중…</p></div>
    </section>
  </section>

  <!-- ══ 연대기 — 좌우 교차 타임라인 (agentmemory Timeline 구성) ══ -->
  <section class="view" id="view-연대기" role="tabpanel" aria-labelledby="tab-연대기">
    <section class="panel" aria-label="운영 연대기">
      <h2><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M8 4.5V8l2.8 1.8" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>운영 연대기 <span id="chronCount" class="num dimnote"></span></h2>
      <div id="opChips" class="chips" role="group" aria-label="작업 종류 필터"></div>
      <div id="dayFilter"></div>
      <div class="chrono" id="chronBody" aria-live="polite"><p class="empty">불러오는 중…</p></div>
      <div id="chronPgn"></div>
    </section>
  </section>

  <!-- ══ 활동 — 52주 열지도 + 작업 분포 + 피드 (agentmemory Activity 구성) ══ -->
  <section class="view" id="view-활동" role="tabpanel" aria-labelledby="tab-활동">
    <section class="panel" aria-label="활동 열지도">
      <h2><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><rect x="1.8" y="1.8" width="5.5" height="5.5" rx="1" fill="currentColor" opacity=".35"/><rect x="8.7" y="1.8" width="5.5" height="5.5" rx="1" fill="currentColor" opacity=".6"/><rect x="1.8" y="8.7" width="5.5" height="5.5" rx="1" fill="currentColor" opacity=".85"/><rect x="8.7" y="8.7" width="5.5" height="5.5" rx="1" fill="currentColor"/></svg>활동 <span id="actMeta" class="num dimnote"></span></h2>
      <div id="heatWrap"></div>
    </section>
    <div class="grid two" style="margin-top:18px">
      <section class="panel" aria-label="작업 분포">
        <h2><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 13.5v-5M6.2 13.5v-9M9.9 13.5V6M13.6 13.5V2.5" stroke="currentColor" stroke-width="1.6"/></svg>작업 분포</h2>
        <div id="opBars" class="bars"></div>
      </section>
      <section class="panel" aria-label="최근 피드">
        <h2><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5h8M4 5.5h8M4 8.5h5M4 11.5h6" stroke="currentColor" stroke-width="1.2"/></svg>최근 피드</h2>
        <ul class="log" id="actFeed"></ul>
      </section>
    </div>
  </section>

  <footer>Asgard 개인 메모리 · 읽기 전용 관측 창 · 127.0.0.1 · 쓰기는 CLI 승인 게이트</footer>
</main>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
const truncate = (s, n) => { s = String(s == null ? "" : s); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
let REDUCED = false;
try{ REDUCED = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches; }catch(e){}

function debounce(fn, ms){
  let t = null;
  return function(){ const a = arguments; clearTimeout(t); t = setTimeout(() => fn.apply(null, a), ms); };
}
// IME-safe 검색 — 한글 조합(compositionstart/end) 중에는 트리거하지 않는다 (agentmemory IME_SAFE_SEARCH_V2 이식)
function bindImeSafeSearch(input, ms, onSearch){
  let composing = false, justCommitted = false;
  const run = debounce((v) => onSearch(v), ms);
  input.addEventListener("compositionstart", () => { composing = true; });
  input.addEventListener("compositionend", () => {
    composing = false; justCommitted = true;
    onSearch(input.value);
    setTimeout(() => { justCommitted = false; }, 0);
  });
  input.addEventListener("input", (e) => {
    if(composing || e.isComposing || justCommitted) return;
    run(input.value);
  });
}
// 재렌더 시 검색 포커스·커서 복원 (agentmemory captureSearchFocus/restoreSearchFocus 이식)
function captureSearchFocus(ids){
  const a = document.activeElement;
  if(!a || ids.indexOf(a.id) < 0) return null;
  return { id: a.id, start: a.selectionStart, end: a.selectionEnd };
}
function restoreSearchFocus(focus){
  if(!focus) return;
  const el = $(focus.id);
  if(!el) return;
  el.focus();
  if(typeof el.setSelectionRange === "function"){
    try{ el.setSelectionRange(focus.start, focus.end); }catch(e){}
  }
}

// kind 룬 글리프 (인라인 SVG, 이모지 금지)
const RUNE = {
  note:'<path d="M3 2h6l2 2v8H3z" fill="none" stroke="currentColor" stroke-width="1.1"/><path d="M9 2v2h2M5 7h4M5 9.5h4" stroke="currentColor" stroke-width="1.1"/>',
  user:'<circle cx="7" cy="5" r="2.4" fill="none" stroke="currentColor" stroke-width="1.1"/><path d="M2.5 12c0-2.5 2-4 4.5-4s4.5 1.5 4.5 4" fill="none" stroke="currentColor" stroke-width="1.1"/>',
  decision:'<path d="M7 1l5 3v6l-5 3-5-3V4z" fill="none" stroke="currentColor" stroke-width="1.1"/><path d="M7 5v4" stroke="currentColor" stroke-width="1.1"/>',
  insight:'<path d="M7 1.5v2M7 10.5v2M1.5 7h2M10.5 7h2M3 3l1.5 1.5M9.5 9.5L11 11M11 3L9.5 4.5M4.5 9.5L3 11" stroke="currentColor" stroke-width="1.1"/><circle cx="7" cy="7" r="2" fill="none" stroke="currentColor" stroke-width="1.1"/>',
  reference:'<path d="M4 2h5a2 2 0 0 1 2 2v8H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" fill="none" stroke="currentColor" stroke-width="1.1"/><path d="M3 10.5h8" stroke="currentColor" stroke-width="1.1"/>',
  feedback:'<path d="M2 3h10v6H7l-3 3V9H2z" fill="none" stroke="currentColor" stroke-width="1.1"/><path d="M5 6h4" stroke="currentColor" stroke-width="1.1"/>',
};
const kglyph = (k) => '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">' + (RUNE[k] || RUNE.note) + '</svg>';
const kchip = (k) => '<span class="kchip">' + kglyph(k) + esc(k) + '</span>';

const FGLYPH = {
  error:'<svg width="11" height="11" viewBox="0 0 11 11" aria-hidden="true"><path d="M5.5 1L10 9H1z" fill="none" stroke="currentColor" stroke-width="1.1"/><path d="M5.5 4v2.2M5.5 7.4v.4" stroke="currentColor" stroke-width="1.1"/></svg>',
  warn:'<svg width="11" height="11" viewBox="0 0 11 11" aria-hidden="true"><path d="M3 8L8 3M3.5 3H2.5v1M7.5 8h1V7" stroke="currentColor" stroke-width="1.1" fill="none"/></svg>',
  info:'<svg width="11" height="11" viewBox="0 0 11 11" aria-hidden="true"><circle cx="5.5" cy="5.5" r="4" fill="none" stroke="currentColor" stroke-width="1.1"/><path d="M5.5 4.6v3M5.5 3.3v.5" stroke="currentColor" stroke-width="1.1"/></svg>',
};
const flevel = (lv) => lv === "error" ? "crit" : lv === "warn" ? "warn" : "info";
const fchip = (lv) => '<span class="fchip f-' + flevel(lv) + '">' + (FGLYPH[lv] || FGLYPH.info) + esc(lv) + '</span>';

// 운영 로그 op 패밀리 — 색+글리프 이중 인코딩
const OPS = {
  add: { c: "#86A860", g: '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M5 1.5v7M1.5 5h7" stroke="currentColor" stroke-width="1.4"/></svg>' },
  ingest: { c: "#6E8BA8", g: '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M5 1v5M2.6 3.9L5 6.3l2.4-2.4M1.5 8.5h7" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>' },
  merge: { c: "#C6A45E", g: '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M1.5 1.5L5 5l3.5-3.5M5 5v3.5" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>' },
  remove: { c: "#C25B46", g: '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 2l6 6M8 2L2 8" stroke="currentColor" stroke-width="1.3"/></svg>' },
  other: { c: "#9C9179", g: '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><circle cx="5" cy="5" r="2" fill="currentColor"/></svg>' },
};
const opFamName = (op) => String(op || "").split(":")[0];
const opStyle = (op) => OPS[opFamName(op)] || OPS.other;

function daysAgo(iso){
  if(!iso) return "";
  const d = new Date(iso + (iso.length <= 10 ? "T00:00:00" : ""));
  if(isNaN(d)) return esc(iso);
  const n = Math.floor((Date.now() - d.getTime()) / 86400000);
  return n <= 0 ? "오늘" : n + "일 전";
}

function gauge(b){
  const pct = Math.max(0, Math.min(100, b.pct));
  const R = 44, C = 2 * Math.PI * R, off = C * (1 - pct / 100);
  const col = b.state === "crit" ? "var(--crit)" : b.state === "warn" ? "var(--warn)" : "var(--rune-gold)";
  return '<svg width="108" height="108" viewBox="0 0 112 112" role="img" aria-label="인덱스 예산 사용량 '
    + b.size + ' / ' + b.budget + '자, ' + pct + '퍼센트">'
    + '<circle cx="56" cy="56" r="44" fill="none" stroke="var(--surface-3)" stroke-width="7"/>'
    + '<circle cx="56" cy="56" r="44" fill="none" stroke="' + col + '" stroke-width="7" stroke-linecap="round" stroke-dasharray="' + C.toFixed(1) + '" stroke-dashoffset="' + off.toFixed(1) + '" transform="rotate(-90 56 56)"/>'
    + '<g stroke="' + col + '" stroke-width="1" opacity=".5"><path d="M56 5v6M56 101v6M5 56h6M101 56h6"/></g>'
    + '<text x="56" y="52" text-anchor="middle" fill="var(--gold-lit)" font-family="monospace" font-size="18" font-weight="600">' + pct + '%</text>'
    + '<text x="56" y="68" text-anchor="middle" fill="var(--ink-dim)" font-family="monospace" font-size="9">' + b.size + '/' + b.budget + '</text></svg>';
}

/* ══ 기억 성좌 — Canvas 물리 시뮬 그래프 ════════════════════════════════════════
   물리 파라미터는 agentmemory viewer(#563 속도캡, #753 대형 그래프)에서 실전 검증된
   값을 그대로 이식: 반발력 노드수 적응형, 스프링 목표 100px, 감쇠 틱-냉각, RMS 파킹. */

const KIND = {
  note:      { c:"#C9A45C", shape:"circle",  ko:"노트" },
  user:      { c:"#9B8EC4", shape:"tri",     ko:"사용자" },
  decision:  { c:"#C4766B", shape:"diamond", ko:"결정" },
  insight:   { c:"#6FA8A0", shape:"hexagon", ko:"통찰" },
  reference: { c:"#7E97B8", shape:"rect",    ko:"참조" },
  feedback:  { c:"#C48EA5", shape:"tridown", ko:"피드백" },
};
const KIND_FALLBACK = KIND.note;

const G = {
  nodes: [], liveEdges: [], deadEdges: [], adj: {},
  canvas: null, ctx: null, raf: null, running: false, bound: false,
  panX: 0, panY: 0, zoom: 1, drag: null, mx: -1e4, my: -1e4,
  tick: 0, quiet: 0, filters: {}, term: "", sel: null, hoverId: null,
};

function angleOf(str){
  let h = 0;
  for(let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
  return (h % 360) * Math.PI / 180;
}
function liftColor(hex){
  const r = Math.min(255, parseInt(hex.slice(1,3),16) + 60);
  const g = Math.min(255, parseInt(hex.slice(3,5),16) + 60);
  const b = Math.min(255, parseInt(hex.slice(5,7),16) + 60);
  return "rgba(" + r + "," + g + "," + b + ",0.95)";
}
function rgbaOf(hex, a){
  return "rgba(" + parseInt(hex.slice(1,3),16) + "," + parseInt(hex.slice(3,5),16) + "," + parseInt(hex.slice(5,7),16) + "," + a + ")";
}
function shapePath(ctx, x, y, r, shape){
  ctx.beginPath();
  if(shape === "rect"){ ctx.rect(x - r, y - r * 0.75, r * 2, r * 1.5); }
  else if(shape === "diamond"){ ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath(); }
  else if(shape === "hexagon"){
    for(let i = 0; i < 6; i++){
      const a = (Math.PI / 3) * i - Math.PI / 2;
      const hx = x + r * Math.cos(a), hy = y + r * Math.sin(a);
      if(i === 0) ctx.moveTo(hx, hy); else ctx.lineTo(hx, hy);
    }
    ctx.closePath();
  }
  else if(shape === "tri"){ ctx.moveTo(x, y - r); ctx.lineTo(x + r * 0.9, y + r * 0.75); ctx.lineTo(x - r * 0.9, y + r * 0.75); ctx.closePath(); }
  else if(shape === "tridown"){ ctx.moveTo(x, y + r); ctx.lineTo(x + r * 0.9, y - r * 0.75); ctx.lineTo(x - r * 0.9, y - r * 0.75); ctx.closePath(); }
  else { ctx.arc(x, y, r, 0, Math.PI * 2); }
}
function shapeSwatch(kind){
  const st = KIND[kind] || KIND_FALLBACK;
  const c = st.c;
  const inner = {
    circle: '<circle cx="7" cy="7" r="5" fill="' + c + '"/>',
    rect: '<rect x="2" y="3.5" width="10" height="7" fill="' + c + '"/>',
    diamond: '<path d="M7 1.5L12.5 7 7 12.5 1.5 7z" fill="' + c + '"/>',
    hexagon: '<path d="M7 1.5l4.8 2.75v5.5L7 12.5 2.2 9.75v-5.5z" fill="' + c + '"/>',
    tri: '<path d="M7 2l5.5 10h-11z" fill="' + c + '"/>',
    tridown: '<path d="M1.5 2h11L7 12z" fill="' + c + '"/>',
  }[st.shape] || '<circle cx="7" cy="7" r="5" fill="' + c + '"/>';
  return '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">' + inner + '</svg>';
}

function visNodes(){ return G.nodes.filter((n) => G.filters[n.kind]); }
function nodeMatches(n){ return (n.title + " " + n.slug).toLowerCase().includes(G.term); }
const FONT_SANS = '-apple-system, "Apple SD Gothic Neo", "Segoe UI", sans-serif';
const FONT_MONO = '"SF Mono", ui-monospace, Menlo, monospace';

function tickPhysics(){
  const nodes = G.nodes;
  const nodeCount = nodes.length;
  G.tick++;
  // 틱-냉각 감쇠 + 노드수 적응 파라미터 + 속도캡 — agentmemory 실측값 그대로
  const coolBoost = Math.min(0.4, G.tick / 1500);
  const damping = 0.9 - coolBoost;
  const repulsion = nodeCount > 1000 ? 3000 : nodeCount > 100 ? 2000 : nodeCount > 50 ? 1200 : 800;
  const attraction = nodeCount > 100 ? 0.002 : 0.005;
  const centerGravity = nodeCount > 1000 ? 0.012 : nodeCount > 100 ? 0.005 : 0.01;
  const velocityCap = nodeCount > 1000 ? 6 : nodeCount > 200 ? 12 : 24;

  const map = {};
  nodes.forEach((n) => { map[n.slug] = n; });

  for(let i = 0; i < nodes.length; i++){
    const n = nodes[i];
    if(G.drag === n) continue;
    let fx = 0, fy = 0;
    for(let j = 0; j < nodes.length; j++){
      if(i === j) continue;
      const dx = n.x - nodes[j].x, dy = n.y - nodes[j].y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = repulsion / (dist * dist);
      fx += (dx / dist) * force;
      fy += (dy / dist) * force;
    }
    fx -= n.x * centerGravity;
    fy -= n.y * centerGravity;
    let nvx = (n.vx + fx) * damping;
    let nvy = (n.vy + fy) * damping;
    if(nvx > velocityCap) nvx = velocityCap; else if(nvx < -velocityCap) nvx = -velocityCap;
    if(nvy > velocityCap) nvy = velocityCap; else if(nvy < -velocityCap) nvy = -velocityCap;
    n.vx = nvx; n.vy = nvy;
  }

  G.liveEdges.forEach((e) => {
    const s = map[e.from], t = map[e.to];
    if(!s || !t) return;
    const dx = t.x - s.x, dy = t.y - s.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const f = (dist - 100) * attraction; // 스프링 목표 길이 100px
    const fx = (dx / dist) * f, fy = (dy / dist) * f;
    if(G.drag !== s){ s.vx += fx; s.vy += fy; }
    if(G.drag !== t){ t.vx -= fx; t.vy -= fy; }
  });

  let ke = 0;
  nodes.forEach((n) => {
    if(G.drag === n) return;
    n.x += n.vx; n.y += n.vy;
    ke += n.vx * n.vx + n.vy * n.vy;
  });
  const rms = nodes.length > 0 ? Math.sqrt(ke / nodes.length) : 0;
  if(rms < 0.05 && G.tick > 60 && !G.drag) G.quiet++; else G.quiet = 0;
}

function simLoop(){
  if(!G.running) return;
  tickPhysics();
  renderGraph();
  if(G.quiet > 30){ G.raf = null; return; } // RMS 정착 → rAF 파킹 (CPU 절약)
  G.raf = requestAnimationFrame(simLoop);
}
function wakeSim(){
  G.quiet = 0;
  if(G.running && !G.raf) G.raf = requestAnimationFrame(simLoop);
}

function canvasSize(){
  const dpr = window.devicePixelRatio || 1;
  return { w: G.canvas.width / dpr, h: G.canvas.height / dpr };
}
function resizeCanvas(){
  if(!G.canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const r = G.canvas.parentElement.getBoundingClientRect();
  G.canvas.width = r.width * dpr;
  G.canvas.height = r.height * dpr;
  G.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function renderGraph(){
  const ctx = G.ctx, canvas = G.canvas;
  if(!ctx || !canvas) return;
  const { w, h } = canvasSize();
  ctx.clearRect(0, 0, w, h);

  // 미세 그리드 — 관측 계기판 바닥
  ctx.save();
  ctx.strokeStyle = "rgba(230,208,150,0.03)";
  ctx.lineWidth = 0.5;
  for(let gx = 0; gx < w; gx += 24){ ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, h); ctx.stroke(); }
  for(let gy = 0; gy < h; gy += 24){ ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(w, gy); ctx.stroke(); }
  ctx.restore();

  if(!G.nodes.length){
    ctx.fillStyle = "#9C9179";
    ctx.font = '14px ' + FONT_SANS;
    ctx.textAlign = "center";
    ctx.fillText("성좌가 비어 있다 — asgard memory add 로 첫 별을 새기세요", w / 2, h / 2);
    return;
  }

  ctx.save();
  ctx.translate(G.panX, G.panY);
  ctx.scale(G.zoom, G.zoom);

  const map = {};
  G.nodes.forEach((n) => { map[n.slug] = n; });
  const searchActive = G.term.length > 0;
  const visible = visNodes();
  const isDense = visible.length > 40;
  const labelZoom = isDense ? 1.5 : 0.5;
  const edgeLabelZoom = isDense ? 2.5 : 1.2;
  const selId = G.sel ? G.sel.slug : null;

  // 호버 탐지 (히트테스트 역순 선형)
  let hoverId = null;
  if(!G.drag){
    const rect = canvas.getBoundingClientRect();
    const hx = (G.mx - rect.left - G.panX) / G.zoom;
    const hy = (G.my - rect.top - G.panY) / G.zoom;
    for(let i = G.nodes.length - 1; i >= 0; i--){
      const n = G.nodes[i];
      if(!G.filters[n.kind]) continue;
      const dx = n.x - hx, dy = n.y - hy;
      if(dx * dx + dy * dy < n.r * n.r + 25){ hoverId = n.slug; break; }
    }
  }
  G.hoverId = hoverId;
  const focusId = selId || hoverId;

  // ── 엣지: 링크(실선 골드) vs 의미(점선 비취) — 시각 구별 ──
  G.liveEdges.forEach((e) => {
    const s = map[e.from], t = map[e.to];
    if(!s || !t) return;
    if(!G.filters[s.kind] || !G.filters[t.kind]) return;
    const dim = searchActive && !(nodeMatches(s) || nodeMatches(t));
    const conn = focusId && (e.from === focusId || e.to === focusId);
    const weight = e.sem ? e.w : 0.5;
    const lw = conn ? 2 + weight * 2 : 1 + weight * 1.5;
    const dx = t.x - s.x, dy = t.y - s.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const off = isDense ? 12 : 18;
    const cpx = (s.x + t.x) / 2 + (-dy / len * off);
    const cpy = (s.y + t.y) / 2 + (dx / len * off);
    let alpha = dim ? 0.06 : (focusId ? (conn ? 0.65 : 0.06) : (isDense ? 0.15 : 0.25));
    if(e.sem && !dim && !(focusId && !conn)) alpha = Math.min(0.75, alpha + 0.08);

    ctx.beginPath();
    ctx.moveTo(s.x, s.y);
    ctx.quadraticCurveTo(cpx, cpy, t.x, t.y);
    if(e.sem){ ctx.setLineDash([5, 5]); ctx.strokeStyle = "rgba(94,138,110," + alpha + ")"; }
    else { ctx.setLineDash([]); ctx.strokeStyle = "rgba(198,164,94," + alpha + ")"; }
    ctx.lineWidth = lw;
    ctx.stroke();
    ctx.setLineDash([]);

    if(!e.sem && (!isDense || conn)){ // 링크는 방향이 있다 — 화살촉
      const ang = Math.atan2(t.y - cpy, t.x - cpx);
      const al = 5 + lw;
      ctx.beginPath();
      ctx.moveTo(t.x - t.r * Math.cos(ang), t.y - t.r * Math.sin(ang));
      ctx.lineTo(t.x - (t.r + al) * Math.cos(ang - 0.3), t.y - (t.r + al) * Math.sin(ang - 0.3));
      ctx.lineTo(t.x - (t.r + al) * Math.cos(ang + 0.3), t.y - (t.r + al) * Math.sin(ang + 0.3));
      ctx.closePath();
      ctx.fillStyle = "rgba(198,164,94," + (dim ? 0.06 : conn ? 0.6 : 0.2) + ")";
      ctx.fill();
    }
    const showW = e.sem && !dim && (conn ? G.zoom > 0.6 : G.zoom > edgeLabelZoom);
    if(showW){
      const zi = 1 / G.zoom;
      ctx.save();
      ctx.fillStyle = "rgba(148,190,162," + (conn ? 0.95 : 0.7) + ")";
      ctx.font = "500 " + (10 * zi).toFixed(1) + "px " + FONT_MONO;
      ctx.textAlign = "center";
      ctx.fillText("cos " + e.w.toFixed(2), cpx, cpy - 4 * zi);
      ctx.restore();
    }
  });

  // ── 죽은 링크 — 붉은 절단선 스텁 + 십자 표식 ──
  G.deadEdges.forEach((de) => {
    const s = map[de.from];
    if(!s || !G.filters[s.kind]) return;
    const dim = searchActive && !nodeMatches(s);
    const conn = focusId === de.from;
    const alpha = dim ? 0.08 : (focusId ? (conn ? 0.8 : 0.08) : 0.45);
    const a = de.a;
    const x1 = s.x + Math.cos(a) * (s.r + 4), y1 = s.y + Math.sin(a) * (s.r + 4);
    const x2 = s.x + Math.cos(a) * (s.r + 34), y2 = s.y + Math.sin(a) * (s.r + 34);
    ctx.save();
    ctx.strokeStyle = "rgba(194,91,70," + alpha + ")";
    ctx.lineWidth = 1.2;
    ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(x2 - 3.5, y2 - 3.5); ctx.lineTo(x2 + 3.5, y2 + 3.5);
    ctx.moveTo(x2 + 3.5, y2 - 3.5); ctx.lineTo(x2 - 3.5, y2 + 3.5);
    ctx.stroke();
    if(conn || G.zoom > 1.4){
      const zi = 1 / G.zoom;
      ctx.fillStyle = "rgba(194,91,70," + Math.min(1, alpha + 0.2) + ")";
      ctx.font = (10 * zi).toFixed(1) + "px " + FONT_MONO;
      ctx.textAlign = "left";
      ctx.fillText(truncate(de.ref, 20), x2 + 6 * zi, y2 + 3 * zi);
    }
    ctx.restore();
  });

  // ── 노드: kind 별 색+형태, 반경=차수, 방사형 그라데이션+글로우 ──
  G.nodes.forEach((n) => {
    if(!G.filters[n.kind]) return;
    const st = KIND[n.kind] || KIND_FALLBACK;
    const color = st.c;
    const isSel = selId === n.slug;
    const isHov = hoverId === n.slug;
    const m = !searchActive || nodeMatches(n);
    const faded = focusId && n.slug !== focusId && !(G.adj[focusId] && G.adj[focusId].has(n.slug));
    const alpha = !m ? 0.12 : (faded ? 0.2 : 1);

    ctx.save();
    ctx.globalAlpha = alpha;
    if(m && !faded && (isSel || isHov || !searchActive)){
      ctx.shadowColor = color;
      ctx.shadowBlur = isSel ? 20 : isHov ? 16 : (isDense ? 4 : 8);
    }
    shapePath(ctx, n.x, n.y, n.r, st.shape);
    const grad = ctx.createRadialGradient(n.x - n.r * 0.3, n.y - n.r * 0.3, 0, n.x, n.y, n.r * 1.2);
    grad.addColorStop(0, liftColor(color));
    grad.addColorStop(1, color);
    ctx.fillStyle = grad;
    ctx.fill();
    ctx.restore();

    if(isSel){
      ctx.save();
      shapePath(ctx, n.x, n.y, n.r + 3, st.shape);
      ctx.strokeStyle = color; ctx.lineWidth = 3;
      ctx.shadowColor = color; ctx.shadowBlur = 12;
      ctx.stroke();
      ctx.restore();
    } else if(isHov){
      shapePath(ctx, n.x, n.y, n.r + 2, st.shape);
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
    } else if(searchActive && m){
      shapePath(ctx, n.x, n.y, n.r + 2, st.shape);
      ctx.strokeStyle = "#E8C87E"; ctx.lineWidth = 2; ctx.stroke();
    }
    if(n.orphan){ // 고아 — 점선 궤도 링 (색+형태 이중 인코딩)
      ctx.save();
      ctx.globalAlpha = Math.max(alpha, 0.4);
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 6, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(210,147,63,0.8)"; ctx.lineWidth = 1.2; ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }
    if(n.poisoned){ // 오염 — 붉은 링 + 사선 표식
      ctx.save();
      ctx.globalAlpha = Math.max(alpha, 0.6);
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 4, 0, Math.PI * 2);
      ctx.strokeStyle = "#C25B46"; ctx.lineWidth = 1.6; ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(n.x - n.r - 4, n.y + n.r + 4); ctx.lineTo(n.x + n.r + 4, n.y - n.r - 4);
      ctx.stroke();
      ctx.restore();
    }

    const showLabel = m && !faded && (
      isSel || isHov || (searchActive && m) ||
      (!isDense && G.zoom > labelZoom) ||
      (isDense && G.zoom > labelZoom && n.r > 10)
    );
    if(showLabel){ // 줌 적응 pill 라벨
      const zi = 1 / G.zoom;
      ctx.save();
      ctx.font = (isSel || isHov ? "600 " : "500 ") + (13 * zi).toFixed(1) + "px " + FONT_SANS;
      ctx.textAlign = "center";
      const label = truncate(n.title, 18);
      const textW = ctx.measureText(label).width;
      const labelW = textW + 16 * zi;
      const labelH = 20 * zi;
      const labelY = n.y + n.r + 8 * zi;
      ctx.fillStyle = "rgba(18,15,10,0.92)";
      ctx.beginPath();
      if(ctx.roundRect) ctx.roundRect(n.x - labelW / 2, labelY, labelW, labelH, 4 * zi);
      else ctx.rect(n.x - labelW / 2, labelY, labelW, labelH);
      ctx.fill();
      ctx.strokeStyle = "rgba(230,208,150,0.12)";
      ctx.lineWidth = 1 * zi;
      ctx.stroke();
      ctx.fillStyle = isSel || isHov ? "#E9E0CA" : "#9C9179";
      ctx.fillText(label, n.x, labelY + 14 * zi);
      ctx.restore();
    }
  });

  ctx.restore();
}

function canvasCoords(e){
  const rect = G.canvas.getBoundingClientRect();
  return {
    x: (e.clientX - rect.left - G.panX) / G.zoom,
    y: (e.clientY - rect.top - G.panY) / G.zoom,
  };
}
function findNode(cx, cy){
  for(let i = G.nodes.length - 1; i >= 0; i--){
    const n = G.nodes[i];
    if(!G.filters[n.kind]) continue;
    const dx = n.x - cx, dy = n.y - cy;
    if(dx * dx + dy * dy < n.r * n.r + 25) return n;
  }
  return null;
}
function zoomBy(factor){
  G.zoom = Math.max(0.1, Math.min(5, G.zoom * factor));
  wakeSim();
}
function recenterGraph(){
  G.zoom = 1;
  const { w, h } = canvasSize();
  G.panX = w / 2; G.panY = h / 2;
  wakeSim();
}
function centerOn(n){
  const { w, h } = canvasSize();
  G.panX = w / 2 - n.x * G.zoom;
  G.panY = h / 2 - n.y * G.zoom;
}

function announce(msg){ const el = $("gAnnounce"); if(el) el.textContent = msg; }

function selectNode(n, center){
  G.sel = n;
  if(center) centerOn(n);
  loadDetail(n.slug);
  const st = KIND[n.kind] || KIND_FALLBACK;
  announce(n.title + " 선택 — " + (st.ko || n.kind) + ", 연결 " + n.degree + "개" + (n.orphan ? ", 고아" : "") + (n.poisoned ? ", 오염 격리" : ""));
  wakeSim();
}
function clearSelection(){
  G.sel = null;
  $("gDetail").innerHTML = "";
  announce("선택 해제");
  wakeSim();
}
function cycleNode(dir){
  const vs = visNodes().slice().sort((a, b) => (b.degree - a.degree) || (a.slug < b.slug ? -1 : 1));
  if(!vs.length) return;
  const i = G.sel ? vs.findIndex((n) => n.slug === G.sel.slug) : -1;
  const n = vs[((i + dir) % vs.length + vs.length) % vs.length];
  selectNode(n, true);
}
// 어느 탭에서든 별을 지목하면 성좌 탭으로 건너가 그 별을 비춘다 (해시 라우팅 경유 — 뒤로가기 보존)
async function gotoSlug(slug){
  await switchTab("성좌");
  const n = G.nodes.find((x) => x.slug === slug);
  if(n){
    if(!G.filters[n.kind]){ // 꺼진 종류의 별을 지목하면 필터를 되켠다 (숨은 채 선택되는 모순 방지)
      G.filters[n.kind] = true;
      const cb = document.querySelector('#gFilters input[data-kind="' + n.kind + '"]');
      if(cb) cb.checked = true;
    }
    selectNode(n, true);
    const c = $("gcanvas");
    if(c) c.focus();
  } else {
    loadDetail(slug); // 성좌 밖 참조 — 상세 API 가 not found 를 알려준다
  }
}

async function fetchPage(slug){
  const res = await fetch("/api/page?slug=" + encodeURIComponent(slug), { cache: "no-store" });
  return await res.json();
}

// 페이지 상세 카드 빌더 — 성좌 사이드 패널과 서고 인플레이스 상세가 공유한다
function detailHtml(p, opts){
  opts = opts || {};
  const closeAct = opts.close || "close-detail";
  if(p.error){
    return '<div class="gdet"><div class="gdet-head"><span class="mono" style="font-size:11px;color:var(--crit)">' + esc(p.slug || opts.slug || "")
      + '</span><button type="button" class="gclose" data-action="' + closeAct + '">닫기</button></div>'
      + '<p class="empty" style="padding:0">페이지를 찾을 수 없다 — 죽은 링크의 목적지다.</p></div>';
  }
  const drow = (k, v) => v ? "<dt>" + k + "</dt><dd>" + esc(v) + "</dd>" : "";
  let html = '<div class="gdet">';
  html += '<div class="gdet-head">' + kchip(p.kind) + '<button type="button" class="gclose" data-action="' + closeAct + '" aria-label="상세 닫기">닫기</button></div>';
  html += '<h3 class="gdet-title">' + esc(p.title) + '</h3>';
  html += '<p class="gdet-slug mono">' + esc(p.slug) + '</p>';
  html += '<dl class="gdet-meta">' + drow("생성", p.created) + drow("갱신", p.updated)
    + drow("회수", p.uses + "회") + drow("최근 회수", p.last_used) + '</dl>';
  if(p.poisoned){
    html += '<p class="gdet-poison">' + esc(p.quarantine || "오염 격리됨") + '</p>';
  } else {
    if(p.body) html += '<pre class="gdet-body">' + esc(truncate(p.body, 1200)) + '</pre>';
    const outs = [];
    (p.refs || []).concat(p.links || []).forEach((s) => { if(outs.indexOf(s) < 0) outs.push(s); });
    if(outs.length){
      html += '<p class="sectitle">잇는 별</p><div class="gdet-links">'
        + outs.map((s) => '<button type="button" class="lchip" data-slug="' + esc(s) + '">' + esc(s) + '</button>').join("")
        + '</div>';
    }
  }
  if(opts.star){
    html += '<p style="margin:10px 0 0"><button type="button" class="lchip" data-action="goto-star" data-slug="' + esc(p.slug) + '">성좌에서 보기</button></p>';
  }
  html += '</div>';
  return html;
}

async function loadDetail(slug){ // 성좌 사이드 패널 상세
  const box = $("gDetail");
  box.innerHTML = '<div class="gdet"><p class="empty" style="padding:0">불러오는 중…</p></div>';
  try{
    box.innerHTML = detailHtml(await fetchPage(slug), { close: "close-detail", slug: slug });
  }catch(e){
    box.innerHTML = '<div class="gdet"><p class="empty" style="padding:0">상세 로드 실패</p></div>';
  }
  // 사이드바가 아래로 스크롤된 상태에서 별을 지목해도 상세가 시야에 들어온다 (실측 결함 수정)
  box.scrollIntoView({ block: "nearest", behavior: REDUCED ? "auto" : "smooth" });
}

function bindGraphInteraction(){
  const canvas = G.canvas;
  let isPanning = false, lastMX = 0, lastMY = 0;

  canvas.addEventListener("mousedown", (e) => {
    const c = canvasCoords(e);
    const node = findNode(c.x, c.y);
    if(node) G.drag = node; else isPanning = true;
    lastMX = e.clientX; lastMY = e.clientY;
    wakeSim();
  });
  canvas.addEventListener("mousemove", (e) => {
    const dx = e.clientX - lastMX, dy = e.clientY - lastMY;
    if(G.drag){
      G.drag.x += dx / G.zoom; G.drag.y += dy / G.zoom;
      G.drag.vx = 0; G.drag.vy = 0;
      wakeSim();
    } else if(isPanning){
      G.panX += dx; G.panY += dy;
      wakeSim();
    }
    lastMX = e.clientX; lastMY = e.clientY;
    G.mx = e.clientX; G.my = e.clientY;

    const c = canvasCoords(e);
    const hoverNode = findNode(c.x, c.y);
    const tip = $("gTip");
    if(tip){
      if(hoverNode && !G.drag && !isPanning){
        const st = KIND[hoverNode.kind] || KIND_FALLBACK;
        tip.innerHTML = '<div class="tt-t">' + esc(hoverNode.title) + '</div>'
          + '<div class="tt-k" style="color:' + st.c + '">' + esc(st.ko || hoverNode.kind) + ' · ' + esc(hoverNode.kind) + '</div>'
          + '<div class="tt-m">연결 ' + hoverNode.degree + ' · 회수 ' + hoverNode.uses + '회'
          + (hoverNode.orphan ? ' · 고아' : '') + (hoverNode.poisoned ? ' · 오염 격리' : '') + '</div>';
        const rect = canvas.getBoundingClientRect();
        tip.style.left = Math.min(e.clientX - rect.left + 12, rect.width - 200) + "px";
        tip.style.top = (e.clientY - rect.top + 12) + "px";
        tip.classList.add("on");
        canvas.style.cursor = "pointer";
      } else {
        tip.classList.remove("on");
        canvas.style.cursor = G.drag || isPanning ? "grabbing" : "grab";
      }
    }
    if(!G.raf) renderGraph(); // 파킹 중에도 호버 포커스는 응답한다
  });
  canvas.addEventListener("mouseleave", () => {
    G.mx = -1e4; G.my = -1e4;
    const tip = $("gTip");
    if(tip) tip.classList.remove("on");
    if(!G.raf) renderGraph();
  });
  canvas.addEventListener("mouseup", () => {
    if(G.drag && !isPanning) selectNode(G.drag, false);
    G.drag = null; isPanning = false;
  });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    zoomBy(e.deltaY > 0 ? 0.9 : 1.1); // 휠 줌 0.1~5x
  }, { passive: false });
  canvas.addEventListener("dblclick", (e) => {
    const c = canvasCoords(e);
    const node = findNode(c.x, c.y);
    if(node){
      G.zoom = Math.max(G.zoom, 1.6);
      selectNode(node, true);
    }
  });

  // 키보드 완주 — 캔버스는 role=application: 팬·줌·노드 순회·상세 진입 전부 키로
  canvas.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 120 : 40;
    let used = true;
    if(e.key === "ArrowLeft") G.panX += step;
    else if(e.key === "ArrowRight") G.panX -= step;
    else if(e.key === "ArrowUp") G.panY += step;
    else if(e.key === "ArrowDown") G.panY -= step;
    else if(e.key === "+" || e.key === "=") zoomBy(1.25);
    else if(e.key === "-" || e.key === "_") zoomBy(0.8);
    else if(e.key === "0") recenterGraph();
    else if(e.key === "]") cycleNode(1);
    else if(e.key === "[") cycleNode(-1);
    else if(e.key === "Enter"){
      const btn = $("gDetail").querySelector("button");
      if(btn) btn.focus();
    }
    else if(e.key === "Escape") clearSelection();
    else used = false;
    if(used){ e.preventDefault(); wakeSim(); }
  });

  window.addEventListener("resize", () => { resizeCanvas(); wakeSim(); });
}

function buildFilters(){
  const counts = {};
  G.nodes.forEach((n) => { counts[n.kind] = (counts[n.kind] || 0) + 1; });
  const kinds = Object.keys(counts).sort();
  $("gFilters").innerHTML = kinds.map((k) => {
    const st = KIND[k] || KIND_FALLBACK;
    return '<label class="fitem">'
      + '<input type="checkbox" checked data-kind="' + esc(k) + '">'
      + shapeSwatch(k) + esc(st.ko || k) + ' <span class="mono" style="font-size:10px;color:var(--ink-dim)">' + esc(k) + '</span>'
      + '<span class="cnt">' + counts[k] + '</span></label>';
  }).join("");
  document.querySelectorAll("#gFilters input").forEach((cb) => {
    cb.addEventListener("change", function(){
      G.filters[this.dataset.kind] = this.checked;
      wakeSim();
    });
  });
}

function renderGraphStats(g){
  const semCount = g.edges.filter((e) => e.type === "semantic").length;
  const linkCount = g.edges.filter((e) => !e.dead && e.type !== "semantic").length;
  $("gStats").innerHTML =
      '<div class="cell"><div class="v">' + g.nodes.length + '</div><div class="l">별 (페이지)</div></div>'
    + '<div class="cell"><div class="v">' + linkCount + '</div><div class="l">명시 링크</div></div>'
    + '<div class="cell"><div class="v">' + semCount + '</div><div class="l">의미 엣지</div></div>'
    + '<div class="cell' + (g.dead ? " bad" : "") + '"><div class="v">' + g.dead + '</div><div class="l">죽은 링크</div></div>';
  $("gCount").textContent = "· 별 " + g.nodes.length + " · 선 " + g.edges.length;
}

function initGraph(g, poisonMap){
  const canvas = $("gcanvas");
  if(!canvas) return;
  G.canvas = canvas;
  G.ctx = canvas.getContext("2d");
  resizeCanvas();
  const { w, h } = canvasSize();
  G.panX = w / 2; G.panY = h / 2;
  // 초기 줌 — 소형 성좌는 당겨 본다 (스프링 목표 100px 기준, 물리 파라미터와 무관한 카메라 값)
  G.zoom = g.nodes.length <= 15 ? 1.5 : g.nodes.length <= 40 ? 1.2 : 1;
  G.tick = 0; G.quiet = 0; G.sel = null;

  G.nodes = g.nodes.map((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(g.nodes.length, 1);
    const radius = Math.min(w, h) * 0.3;
    return {
      slug: n.slug, kind: n.kind, title: n.title, uses: n.uses,
      degree: n.degree, orphan: n.orphan, poisoned: !!poisonMap[n.slug],
      x: Math.cos(angle) * radius + (Math.random() - 0.5) * 50,
      y: Math.sin(angle) * radius + (Math.random() - 0.5) * 50,
      vx: 0, vy: 0,
      r: Math.max(8, Math.min(22, 8 + n.degree * 2.5)), // 반경 = 차수 인코딩
    };
  });
  G.liveEdges = [];
  G.deadEdges = [];
  g.edges.forEach((e) => {
    if(e.dead) G.deadEdges.push({ from: e.from, ref: e.to, a: angleOf(e.from + ">" + e.to) });
    else G.liveEdges.push({ from: e.from, to: e.to, sem: e.type === "semantic", w: typeof e.w === "number" ? e.w : 0.5 });
  });
  G.adj = {};
  G.liveEdges.forEach((e) => {
    (G.adj[e.from] = G.adj[e.from] || new Set()).add(e.to);
    (G.adj[e.to] = G.adj[e.to] || new Set()).add(e.from);
  });
  G.filters = {};
  G.nodes.forEach((n) => { G.filters[n.kind] = true; });

  buildFilters();
  renderGraphStats(g);
  if(!G.bound){ bindGraphInteraction(); G.bound = true; }
  G.running = true;
  if(REDUCED){
    // reduced-motion: 정착 애니메이션 없이 즉시 안정 레이아웃 — 이후 조작은 사용자 주도만
    for(let i = 0; i < 600 && G.quiet <= 30; i++) tickPhysics();
    renderGraph();
  } else {
    wakeSim();
  }
}

// ── 그래프 검색 (IME-safe — 한글 조합 안전) ──
bindImeSafeSearch($("gq"), 200, (v) => {
  G.term = v.trim().toLowerCase();
  wakeSim();
  if(!G.raf) renderGraph();
});

/* ══ 앱 셸 — 탭 바 + URL 해시 라우팅 + 탭별 lazy-load (agentmemory 뷰어 구성 이식) ══ */

const TAB_IDS = ["개요", "성좌", "서고", "연대기", "활동"];
const APP = { active: "개요", loaded: {}, snap: null, snapPromise: null, graphReady: false, graphSig: "",
  kind: "", op: "", q: "", sort: "updated", day: "", chronOffset: 0, inline: null };

function normalizeTab(t){ return TAB_IDS.indexOf(t) >= 0 ? t : ""; }
function tabFromRoute(){
  try{ return normalizeTab(decodeURIComponent(location.hash.slice(1))); }catch(e){ return ""; }
}
function currentHash(){
  try{ return decodeURIComponent(location.hash); }catch(e){ return location.hash; }
}
function updateTabRoute(tab, replace){
  const target = "#" + tab;
  if(currentHash() === target) return;
  if(replace) history.replaceState(null, "", target);
  else history.pushState(null, "", target);
}
function switchTab(tab, opts){
  opts = opts || {};
  tab = normalizeTab(tab) || APP.active;
  if(!opts.skipRoute) updateTabRoute(tab, !!opts.replaceRoute);
  APP.active = tab;
  document.querySelectorAll('#tabBar [role="tab"]').forEach((b) => {
    const on = b.dataset.tab === tab;
    b.setAttribute("aria-selected", on ? "true" : "false");
    b.tabIndex = on ? 0 : -1; // APG roving tabindex
    b.classList.toggle("on", on);
  });
  document.querySelectorAll(".view").forEach((v) => {
    v.classList.toggle("active", v.id === "view-" + tab);
  });
  return loadTab(tab);
}
// 탭별 lazy-load — 첫 진입에만 렌더, 재진입은 캐시 (agentmemory loadTab 패턴)
async function loadTab(tab){
  const view = $("view-" + tab);
  try{
    const s = await fetchSnap();
    switch(tab){
      case "개요": if(!APP.loaded["개요"]){ renderOverview(s); APP.loaded["개요"] = true; } break;
      case "성좌": refreshGraph(s); break;
      case "서고": if(!APP.loaded["서고"]){ renderKindChips(s); renderLibrary(); APP.loaded["서고"] = true; } break;
      case "연대기": if(!APP.loaded["연대기"]){ renderChronicle(s); APP.loaded["연대기"] = true; } break;
      case "활동": if(!APP.loaded["활동"]){ renderActivity(s); APP.loaded["활동"] = true; } break;
    }
  }catch(e){
    if(view && !view.querySelector(".loaderr")){
      view.insertAdjacentHTML("afterbegin",
        '<p class="empty loaderr">데이터 로드 실패 — 서버가 살아있는지 확인하세요. (' + esc(String(e)) + ')</p>');
    }
  }
}
function fetchSnap(){
  if(APP.snap) return Promise.resolve(APP.snap);
  if(!APP.snapPromise){
    APP.snapPromise = fetch("/api/snapshot", { cache: "no-store" })
      .then((r) => r.json())
      .then((s) => { APP.snap = s; renderMeta(s); setLiveBadge(true); return s; })
      .catch((e) => { $("metaLine").textContent = "스냅샷 로드 실패: " + e; setLiveBadge(false); APP.snapPromise = null; throw e; })
      .finally(() => dismissSplash()); // 성공이든 실패든 스플래시는 걷는다
  }
  return APP.snapPromise;
}

/* ── 자동 새로고침 — 30s 폴링, 현재 활성 탭만 갱신 (agentmemory startPolling 이식) ── */
const POLL_MS = 30000;
let pollTimer = null, refreshing = false;
function setLiveBadge(ok){
  const b = $("liveBadge");
  if(!b) return;
  b.classList.remove("idle");
  b.classList.toggle("err", !ok);
  $("liveText").innerHTML = ok
    ? '갱신 30s · <span class="num">' + new Date().toTimeString().slice(0, 8) + '</span>'
    : '갱신 실패 — 재시도 대기';
}
function renderActiveTab(s){
  switch(APP.active){
    case "개요": renderOverview(s); APP.loaded["개요"] = true; break;
    case "성좌": refreshGraph(s); break; // 데이터 불변이면 시뮬 유지 — 드래그 배치를 부수지 않는다
    case "서고": renderKindChips(s); renderLibrary(); APP.loaded["서고"] = true; break;
    case "연대기": renderChronicle(s); APP.loaded["연대기"] = true; break;
    case "활동": renderActivity(s); APP.loaded["활동"] = true; break;
  }
}
async function refreshNow(){
  if(refreshing) return;
  refreshing = true;
  const btn = $("refreshBtn");
  if(btn) btn.disabled = true;
  try{
    const res = await fetch("/api/snapshot", { cache: "no-store" });
    const s = await res.json();
    APP.snap = s;
    APP.snapPromise = Promise.resolve(s);
    renderMeta(s);
    APP.loaded = {}; // 비활성 탭은 다음 진입 때 새 데이터로 lazy 재렌더
    renderActiveTab(s);
    setLiveBadge(true);
  }catch(e){
    setLiveBadge(false);
  }finally{
    refreshing = false;
    if(btn) btn.disabled = false;
  }
}
function startPolling(){
  if(pollTimer) return;
  pollTimer = setInterval(() => { if(!document.hidden) refreshNow(); }, POLL_MS);
}
function stopPolling(){
  if(pollTimer){ clearInterval(pollTimer); pollTimer = null; }
}
document.addEventListener("visibilitychange", () => {
  if(document.hidden){ stopPolling(); } // 숨은 탭은 폴링 정지 — 헛일 금지
  else { startPolling(); refreshNow(); } // 복귀 즉시 따라잡기
});
function renderMeta(s){
  const m = s.meta;
  $("metaLine").innerHTML =
    '<span>서고 <b>' + esc(m.dir) + '</b></span>'
    + '<span>페이지 <b class="num">' + m.pages + '</b></span>'
    + '<span>시맨틱 <b class="' + (m.semantic ? "on" : "off") + '">' + (m.semantic ? "on · " + esc(m.semantic_mode) : "off") + '</b></span>'
    + '<span>' + esc(m.generated) + '</span>';
}
// 성좌 데이터 서명 — 폴링 갱신 때 이 값이 같으면 재시드하지 않는다 (드래그 배치 보존)
function graphSig(g){
  return JSON.stringify({
    n: g.nodes.map((n) => [n.slug, n.kind, n.degree, n.orphan]),
    e: g.edges.map((e) => [e.from, e.to, !!e.dead, e.type || "", e.w || 0]),
  });
}
function renderOrphans(s){
  $("orphanCount").textContent = "· " + s.graph.orphans.length;
  $("orphanList").innerHTML = s.graph.orphans.slice(0, 12).map((o) =>
    '<li><span class="dot"></span><button type="button" class="linklike mono" style="font-size:12px" data-slug="' + esc(o) + '">' + esc(o) + '</button></li>').join("")
    || (s.graph.nodes.length
      ? '<li class="empty" style="color:var(--heal)">고아 없음 — 모두 연결됨</li>'
      : '<li class="empty">별이 없으면 고아도 없다 — 첫 별부터.</li>');
}
function renderSemHint(s){
  $("gSemHint").innerHTML = s.meta.semantic ? "" :
    '<p class="semhint"><svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true">'
    + '<circle cx="3" cy="6.5" r="1.6" fill="currentColor"/><circle cx="10" cy="3" r="1.4" fill="currentColor"/>'
    + '<circle cx="10" cy="10" r="1.4" fill="currentColor"/>'
    + '<path d="M4.5 5.7L8.7 3.5M4.5 7.3l4.2 2.2" stroke="currentColor" stroke-width="1" stroke-dasharray="2 1.6" fill="none"/></svg>'
    + '<span>의미 유사 엣지를 보려면 <code>[memory] semantic=local</code> 로 켠다 — 지금은 명시 링크만 잇는다.</span></p>';
}
function seedGraph(s){
  const pm = {};
  s.catalog.forEach((p) => { if(p.poisoned) pm[p.slug] = true; });
  initGraph(s.graph, pm); // 뷰가 보일 때만 초기화 — display:none 캔버스는 치수가 0 이다
  APP.graphReady = true;
  APP.graphSig = graphSig(s.graph);
  renderOrphans(s);
  renderSemHint(s);
}
// 성좌 진입·폴링 공용 경로 — 데이터가 변했을 때만 재시드, 불변이면 시뮬(드래그 배치) 유지
function refreshGraph(s){
  if(!APP.graphReady){ seedGraph(s); return; }
  resizeCanvas();
  if(graphSig(s.graph) === APP.graphSig){
    const um = {};
    s.graph.nodes.forEach((n) => { um[n.slug] = n.uses; });
    G.nodes.forEach((n) => { n.uses = um[n.slug] || 0; }); // 회수수만 제자리 갱신
    renderOrphans(s);
    renderSemHint(s);
    wakeSim();
    if(REDUCED) renderGraph();
    return;
  }
  APP.graphReady = false;
  seedGraph(s);
}

/* ══ 개요 — 통계 카드 → 게이지+건강 → 시맨틱 → 2단 (agentmemory Dashboard 순서) ══ */

function ovCard(v, label, sub, cls){
  return '<div class="stat ' + cls + '"><div class="v num">' + v + '</div><div class="l">' + esc(label) + '</div><div class="s">' + esc(sub) + '</div></div>';
}
// 빈 서고 온보딩 — 빈 표 대신 첫 행동을 안내한다 (UX 라이팅: 빈 화면은 행동 유도)
function onboardHtml(msg){
  return '<div class="onboard">'
    + '<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">'
    + '<path d="M4 24V12a9 9 0 0 1 18 0v12" fill="none" stroke="currentColor" stroke-width="1.6"/>'
    + '<path d="M9 24v-9a4 4 0 0 1 8 0v9" fill="none" stroke="currentColor" stroke-width="1.2"/>'
    + '<path d="M2 24h22" stroke="currentColor" stroke-width="1.6"/></svg>'
    + '<p>' + msg + '</p>'
    + '<code>asgard memory add "오늘 결정한 것 — 근거 한 줄"</code></div>';
}
function renderOverview(s){
  const g = s.graph, cat = s.catalog, b = s.meta.budget;
  $("ovOnboard").innerHTML = cat.length ? "" :
    '<div class="panel" style="margin-bottom:18px">' + onboardHtml("서고가 비어 있다 — 첫 페이지를 새기면 개요·성좌·연대기가 함께 깨어난다.") + '</div>';
  const kinds = {};
  cat.forEach((p) => { kinds[p.kind] = (kinds[p.kind] || 0) + 1; });
  const kn = Object.keys(kinds).sort((a, x) => kinds[x] - kinds[a]);
  const usesSum = s.usage.reduce((acc, u) => acc + (u.uses || 0), 0);
  $("ovStats").innerHTML =
      ovCard(cat.length, "페이지", "서고의 별", "")
    + ovCard(kn.length, "종류", kn.slice(0, 3).map((k) => k + " " + kinds[k]).join(" · ") || "비어 있음", "")
    + ovCard(usesSum, "회수 총합", "쿼리가 실제로 꺼내 쓴 횟수", "")
    + ovCard(g.dead, "죽은 링크", g.dead ? "성좌의 절단선 — 정리 대상" : "끊긴 참조 없음", g.dead ? "crit" : "")
    + ovCard(g.orphans.length, "고아 페이지", g.orphans.length ? "링크도 의미도 닿지 않음" : "모두 연결됨", g.orphans.length ? "warn" : "");

  $("gauge").innerHTML = gauge(b);
  $("budgetText").innerHTML = '<b class="num" style="color:var(--gold-lit)">' + b.size + '</b> / ' + b.budget + '자'
    + '<br><span style="color:' + (b.state === "crit" ? "var(--crit)" : b.state === "warn" ? "var(--warn)" : "var(--ink-dim)") + '">'
    + (b.state === "crit" ? "예산 초과 — add 거부, 통합 필요" : b.state === "warn" ? "예산 임박" : "여유") + '</span>';

  const fl = $("findList");
  if(!s.health.findings.length){ fl.innerHTML = '<li style="grid-template-columns:1fr;color:var(--heal)">건강함 — findings 없음</li>'; }
  else fl.innerHTML = s.health.findings.slice(0, 40).map((f) =>
    '<li>' + fchip(f.level) + '<span><span class="sl">' + esc(f.slug) + '</span> <span class="ms">' + esc(f.code) + ' — ' + esc(f.msg) + '</span></span></li>').join("");

  $("semState").innerHTML = '<span class="lab">시맨틱 회수</span> '
    + (s.meta.semantic
      ? '<span><b style="color:var(--heal)">on</b> · ' + esc(s.meta.semantic_mode) + ' — 성좌의 점선 비취 엣지와 SEM 레인이 살아 있다</span>'
      : '<span><b style="color:var(--ink-ghost)">off</b> — opt-in 전까지 FTS·정본 스캔만으로 회수한다</span>');

  $("ovLog").innerHTML = s.log.slice(0, 8).map(logRow).join("") || '<li class="empty">로그 없음</li>';

  const top = s.usage.filter((u) => u.uses > 0).slice(0, 8);
  $("topUse").innerHTML = top.length ? top.map((u) =>
    '<li><span class="ti"><button type="button" class="linklike mono" style="font-size:12.5px" data-slug="' + esc(u.slug) + '">' + esc(u.slug) + '</button></span><span class="u">' + u.uses + '×</span><span class="du">' + daysAgo(u.last_used) + '</span></li>').join("")
    : '<li class="empty">아직 회수 기록 없음</li>';
}
function logRow(l){
  const oc = opStyle(l.op);
  return '<li><span class="ts">' + esc(l.ts) + '</span><span class="op" style="color:' + oc.c + '">' + oc.g + ' ' + esc(l.op) + '</span>'
    + '<span class="sl"><button type="button" class="linklike mono" style="font-size:12px" data-slug="' + esc(l.slug) + '">' + esc(l.slug) + '</button>'
    + (l.detail ? ' <span style="color:var(--ink-ghost)">' + esc(l.detail) + '</span>' : "") + '</span></li>';
}

/* ══ 서고 — 카탈로그 표 + 질의 스트림 프리즘 통합 (agentmemory Memories 구성) ══ */

function renderKindChips(s){
  const counts = {};
  s.catalog.forEach((p) => { counts[p.kind] = (counts[p.kind] || 0) + 1; });
  if(APP.kind && !counts[APP.kind]) APP.kind = ""; // 갱신 후 사라진 종류 필터는 해제
  if(!s.catalog.length){ // 빈 서고 — "전체 0" 칩·정렬 토글은 소음이다: 온보딩만 남긴다
    $("kindChips").innerHTML = "";
    $("sortChips").innerHTML = "";
    $("catCount").textContent = "";
    $("semNote").innerHTML = "";
    return;
  }
  const kinds = Object.keys(counts).sort();
  const chip = (k, label) => {
    const on = (k || "") === APP.kind;
    return '<button type="button" class="chip' + (on ? " on" : "") + '" data-action="kind-filter" data-kind="' + esc(k)
      + '" aria-pressed="' + (on ? "true" : "false") + '">' + label + '</button>';
  };
  $("kindChips").innerHTML =
    chip("", '전체 <span class="cnt">' + s.catalog.length + '</span>')
    + kinds.map((k) => chip(k, shapeSwatch(k) + esc((KIND[k] || {}).ko || k) + ' <span class="cnt">' + counts[k] + '</span>')).join("");
  renderSortChips();
  $("catCount").textContent = s.catalog.length ? "· " + s.catalog.length : "";
  $("semNote").innerHTML = s.meta.semantic ? "" : '<span style="color:var(--ink-ghost)">(시맨틱 비활성 — opt-in)</span>';
}
// 정렬 토글 — updated(기본)/회수/제목, aria-pressed 칩
const SORTS = [["updated", "갱신순"], ["uses", "회수순"], ["title", "제목순"]];
function renderSortChips(){
  $("sortChips").innerHTML = '<span class="sectitle" style="margin:0;align-self:center">정렬</span>'
    + SORTS.map(([key, ko]) => {
      const on = APP.sort === key;
      return '<button type="button" class="chip' + (on ? " on" : "") + '" data-action="lib-sort" data-sort="' + key
        + '" aria-pressed="' + (on ? "true" : "false") + '">' + ko + '</button>';
    }).join("");
}
function setLibSort(btn){
  APP.sort = btn.dataset.sort || "updated";
  renderSortChips();
  renderLibrary();
}
function sortCatalog(rows){
  const upd = (a, b) => String(b.updated || "").localeCompare(String(a.updated || ""));
  if(APP.sort === "uses") return rows.sort((a, b) => ((b.uses || 0) - (a.uses || 0)) || upd(a, b));
  if(APP.sort === "title") return rows.sort((a, b) => String(a.title || "").localeCompare(String(b.title || ""), "ko"));
  return rows.sort(upd);
}
function setKindFilter(btn){
  APP.kind = btn.dataset.kind || "";
  document.querySelectorAll("#kindChips .chip").forEach((c) => {
    const on = (c.dataset.kind || "") === APP.kind;
    c.classList.toggle("on", on);
    c.setAttribute("aria-pressed", on ? "true" : "false");
  });
  renderLibrary();
}
function onLibraryQuery(v){
  APP.q = (v || "").trim();
  renderLibrary();
}
function renderLibrary(){
  const s = APP.snap;
  if(!s) return;
  if(APP.q){ $("sortChips").style.display = "none"; doSearch(APP.q); return; } // 검색 중 정렬 칩은 무의미 — RRF 점수가 순위다
  $("sortChips").style.display = "";
  APP.inline = null;
  const focus = captureSearchFocus(["q"]);
  const rows = sortCatalog(s.catalog.filter((p) => !APP.kind || p.kind === APP.kind).slice());
  const maxU = Math.max(1, s.catalog.reduce((m, p) => Math.max(m, p.uses || 0), 0));
  $("libBody").innerHTML = rows.length
    ? '<div style="overflow-x:auto"><table><caption>pages/ frontmatter — 제목을 고르면 상세가 펼쳐진다</caption>'
      + '<thead><tr><th scope="col">페이지</th><th scope="col">종류</th><th scope="col" class="rt">회수</th><th scope="col">갱신</th></tr></thead><tbody>'
      + rows.map((p) => {
          const pct = Math.round(100 * (p.uses || 0) / maxU);
          return '<tr><td class="ti">' + (p.poisoned ? '<span class="poison">오염</span>' : "")
            + '<button type="button" class="linklike" data-action="page-detail" data-slug="' + esc(p.slug) + '" aria-expanded="false">' + esc(p.title) + '</button>'
            + '<div class="di" style="font-size:11px;font-family:var(--mono)">' + esc(p.slug) + '</div>'
            + (p.desc ? '<div class="di" style="font-size:12px">' + esc(truncate(p.desc, 90)) + '</div>' : "")
            + '</td><td>' + kchip(p.kind) + '</td>'
            + '<td class="rt"><span class="ubar" aria-hidden="true"><i style="width:' + pct + '%"></i></span>' + (p.uses || 0) + '</td>'
            + '<td class="di">' + daysAgo(p.updated) + '</td></tr>';
        }).join("")
      + '</tbody></table></div>'
    : (APP.kind ? '<p class="empty">이 종류의 페이지 없음</p>'
       : onboardHtml("서고가 비어 있다 — 아래 한 줄이면 첫 페이지가 만들어진다."));
  restoreSearchFocus(focus);
}
// 검색어 하이라이트 — 이미 이스케이프된 텍스트에 <mark> 를 입힌다 (agentmemory Memories 이식)
function markHl(safe, q){
  if(!q || q.length < 2) return safe;
  try{
    const re = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi");
    return safe.replace(re, "<mark>$1</mark>");
  }catch(e){ return safe; }
}
async function doSearch(q){
  try{
    const res = await fetch("/api/search?q=" + encodeURIComponent(q) + "&k=12", { cache: "no-store" });
    renderHits(await res.json());
  }catch(e){
    $("libBody").innerHTML = '<p class="empty">검색 실패: ' + esc(String(e)) + '</p>';
  }
}
function renderHits(data){
  if(APP.q !== data.q) return; // 늦게 도착한 응답 무시 (연타 안전)
  APP.inline = null;
  const focus = captureSearchFocus(["q"]);
  const hits = data.hits.filter((h) => !APP.kind || h.kind === APP.kind);
  $("libBody").innerHTML = hits.length ? hits.map((h) => {
    const st = h.streams || {};
    return '<div class="qrow" tabindex="0" role="button" data-action="page-detail" data-slug="' + esc(h.slug) + '" aria-expanded="false" aria-label="' + esc(h.title) + ' — 상세 펼치기">'
      + '<div class="t">' + kchip(h.kind) + ' ' + markHl(esc(h.title), data.q)
      + '<span class="sub">' + esc(h.slug) + ' · score ' + esc(h.score) + '</span>'
      + (h.snippet ? '<span class="snip">' + markHl(esc(h.snippet), data.q) + '</span>' : "")
      + '</div><div class="lanes" aria-hidden="true">'
      + lane("FTS", st.fts, "fts") + lane("SCAN", st.scan, "scan") + lane("SEM", st.semantic, "sem")
      + '</div></div>';
  }).join("") : '<p class="empty">“' + esc(data.q) + '” 적중 없음' + (APP.kind ? " (종류 필터 적용 중)" : "") + '</p>';
  restoreSearchFocus(focus);
}
function lane(name, on, cls){
  return '<div class="lane ' + (on ? "on " : "off ") + cls + '"><span>' + name + '</span><span class="bar"></span></div>';
}

// 인플레이스 상세 — 행 바로 아래에 펼친다. 닫으면 연 요소로 포커스 복귀 (오버레이 캐논)
async function toggleInlineDetail(slug, opener){
  if(APP.inline && APP.inline.slug === slug){ closeInlineDetail(true); return; }
  closeInlineDetail(false);
  const tr = opener.closest("tr");
  let mount = null;
  if(tr){
    mount = document.createElement("tr");
    mount.className = "dtr";
    mount.innerHTML = '<td colspan="4"><div class="dwrap"><p class="empty">불러오는 중…</p></div></td>';
    tr.after(mount);
  } else {
    const row = opener.closest(".qrow");
    if(!row) return;
    mount = document.createElement("div");
    mount.className = "dbox";
    mount.innerHTML = '<div class="dwrap"><p class="empty">불러오는 중…</p></div>';
    row.after(mount);
  }
  opener.setAttribute("aria-expanded", "true");
  APP.inline = { slug: slug, opener: opener, mount: mount };
  try{
    const p = await fetchPage(slug);
    if(APP.inline && APP.inline.mount === mount){
      mount.querySelector(".dwrap").innerHTML = detailHtml(p, { close: "close-inline", star: true, slug: slug });
    }
  }catch(e){
    if(mount.isConnected) mount.querySelector(".dwrap").innerHTML = '<p class="empty">상세 로드 실패</p>';
  }
}
function closeInlineDetail(refocus){
  if(!APP.inline) return;
  const it = APP.inline;
  APP.inline = null;
  if(it.mount && it.mount.isConnected) it.mount.remove();
  if(it.opener && it.opener.isConnected){
    it.opener.setAttribute("aria-expanded", "false");
    if(refocus) it.opener.focus();
  }
}

/* ══ 연대기 — 좌우 교차 타임라인 + op 칩 필터 (agentmemory Timeline 구성) ══ */

const CHRON_LIMIT = 60; // 60건 페이지 — /api/log 서버 페이지네이션 소비
function renderChronicle(s){
  const a = (s && s.activity) || { ops: {}, total: 0 };
  const fams = Object.keys(a.ops).sort((x, y) => a.ops[y] - a.ops[x]);
  const chip = (f, label) => {
    const on = (f || "") === APP.op;
    return '<button type="button" class="chip' + (on ? " on" : "") + '" data-action="op-filter" data-op="' + esc(f)
      + '" aria-pressed="' + (on ? "true" : "false") + '">' + label + '</button>';
  };
  $("opChips").innerHTML =
    chip("", '전체 <span class="cnt">' + a.total + '</span>')
    + fams.map((f) => {
      const oc = OPS[f] || OPS.other;
      return chip(f, '<span style="color:' + oc.c + ';display:inline-flex">' + oc.g + '</span>' + esc(f)
        + ' <span class="cnt">' + a.ops[f] + '</span>');
    }).join("");
  renderDayFilter();
  loadChron();
}
function renderDayFilter(){
  $("dayFilter").innerHTML = APP.day
    ? '<span class="dayflt"><span>' + esc(APP.day) + ' 하루만</span>'
      + '<button type="button" data-action="day-clear" aria-label="날짜 필터 해제">해제 ✕</button></span>'
    : "";
}
function setOpFilter(btn){
  APP.op = btn.dataset.op || "";
  APP.chronOffset = 0;
  document.querySelectorAll("#opChips .chip").forEach((c) => {
    const on = (c.dataset.op || "") === APP.op;
    c.classList.toggle("on", on);
    c.setAttribute("aria-pressed", on ? "true" : "false");
  });
  loadChron();
}
// 활동 히트맵 셀 → 연대기 딥링크 (해시는 #연대기 — 쿼리는 메모리 상태로 충분)
async function gotoDay(day){
  APP.day = day || "";
  APP.chronOffset = 0;
  APP.loaded["연대기"] = false;
  await switchTab("연대기");
}
function clearDayFilter(){
  APP.day = "";
  APP.chronOffset = 0;
  renderDayFilter();
  loadChron();
}
async function loadChron(){
  const p = new URLSearchParams({ offset: String(APP.chronOffset), limit: String(CHRON_LIMIT) });
  if(APP.op) p.set("op", APP.op);
  if(APP.day) p.set("day", APP.day);
  try{
    const res = await fetch("/api/log?" + p.toString(), { cache: "no-store" });
    renderChronList(await res.json());
  }catch(e){
    $("chronBody").innerHTML = '<p class="empty">연대기 로드 실패 — 서버가 살아있는지 확인하세요.</p>';
    $("chronPgn").innerHTML = "";
  }
}
function renderChronList(data){
  const filtered = !!(APP.op || APP.day);
  $("chronCount").textContent = "· 총 " + data.total + "건" + (filtered ? " (필터 적용)" : "");
  let html = "", lastDay = "";
  data.entries.forEach((l, i) => {
    const day = String(l.ts).slice(0, 10);
    if(day && day !== lastDay){ // 날짜 마커 — 타임라인 축 위 봉인 필
      html += '<div class="cdate"><span>' + esc(day) + '</span></div>';
      lastDay = day;
    }
    const oc = opStyle(l.op);
    html += '<article class="citem ' + ((data.offset + i) % 2 ? "right" : "left") + '">'
      + '<span class="cdot" style="background:' + oc.c + '" aria-hidden="true"></span>'
      + '<div class="ccard">'
      + '<div class="chead"><span class="obadge" style="color:' + oc.c + ';border-color:color-mix(in oklab,' + oc.c + ' 45%,transparent)">' + oc.g + esc(l.op) + '</span>'
      + '<button type="button" class="linklike mono" style="font-size:12px" data-slug="' + esc(l.slug) + '">' + esc(l.slug) + '</button>'
      + '<span class="ctime">' + esc(String(l.ts).slice(11, 16)) + '</span></div>'
      + (l.detail ? '<div class="cdet">' + esc(l.detail) + '</div>' : "")
      + '</div></article>';
  });
  $("chronBody").innerHTML = html
    || (filtered ? '<p class="empty">조건에 맞는 기록 없음 — 칩·날짜 필터를 풀어 보세요.</p>'
        : onboardHtml("아직 연대기가 비어 있다 — 첫 기록이 곧 첫 봉인이다."));
  // 페이지 넘김 — agentmemory Timeline Prev/Next 형 (총 건수 표시)
  const pages = Math.max(1, Math.ceil(data.total / CHRON_LIMIT));
  const cur = Math.floor(data.offset / CHRON_LIMIT);
  $("chronPgn").innerHTML = pages > 1
    ? '<nav class="pgn" aria-label="연대기 페이지 넘김">'
      + '<button type="button" data-action="chron-page" data-page="' + (cur - 1) + '"' + (cur <= 0 ? " disabled" : "") + '>← 최근</button>'
      + '<span>' + (cur + 1) + ' / ' + pages + ' 페이지 · 총 ' + data.total + '건</span>'
      + '<button type="button" data-action="chron-page" data-page="' + (cur + 1) + '"' + (cur >= pages - 1 ? " disabled" : "") + '>과거 →</button>'
      + '</nav>'
    : "";
}
function chronPage(p){
  const page = Math.max(0, parseInt(p, 10) || 0);
  APP.chronOffset = page * CHRON_LIMIT;
  loadChron();
  const panel = $("view-연대기");
  if(panel) panel.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
}

/* ══ 활동 — 52주 열지도(순수 div) + 작업 분포 + 피드 (agentmemory Activity 구성) ══ */

function renderActivity(s){
  const a = s.activity || { days: {}, ops: {}, total: 0, first: "", last: "" };
  $("actMeta").textContent = "· 총 " + a.total + "건" + (a.first ? " · " + a.first + " ~ " + a.last : "");

  if(!a.total){
    $("heatWrap").innerHTML = onboardHtml("52주 열지도가 아직 비어 있다 — 첫 운영 기록이 첫 칸을 밝힌다.");
    $("opBars").innerHTML = '<p class="empty">기록 없음</p>';
    $("actFeed").innerHTML = '<li class="empty">기록 없음</li>';
    return;
  }
  let max = 0;
  Object.keys(a.days).forEach((k) => { if(a.days[k] > max) max = a.days[k]; });
  let cells = "";
  const today = new Date();
  for(let w = 51; w >= 0; w--){ // 52주 × 7일 — 왼쪽이 옛날, GitHub식 순수 div 반복문
    for(let d = 0; d < 7; d++){
      const cd = new Date(today);
      cd.setDate(cd.getDate() - (w * 7 + (6 - d)));
      const key = cd.toISOString().slice(0, 10);
      const c = a.days[key] || 0;
      const lv = !c ? 0 : c <= max * 0.25 ? 1 : c <= max * 0.5 ? 2 : c <= max * 0.75 ? 3 : 4;
      // 기록 있는 날만 버튼 — 셀 클릭 = 연대기 해당 일자 딥링크
      cells += c
        ? '<button type="button" class="heat-cell lv' + lv + '" data-action="heat-day" data-day="' + key
          + '" title="' + key + ' · ' + c + '건" aria-label="' + key + ' ' + c + '건 — 연대기에서 보기"></button>'
        : '<div class="heat-cell" title="' + key + ' · 0건" aria-hidden="true"></div>';
    }
  }
  $("heatWrap").innerHTML =
    '<p class="vh">지난 52주 일별 운영 기록 열지도 — 총 ' + a.total + '건. 기록 있는 날짜 셀을 고르면 연대기의 그 하루로 이동한다.</p>'
    + '<div class="heat">'
    + '<div class="heat-days" aria-hidden="true"><span>월</span><span></span><span>수</span><span></span><span>금</span><span></span><span></span></div>'
    + '<div class="heat-scroll"><div class="heat-grid">' + cells + '</div></div>'
    + '</div>'
    + '<div class="heat-legend" aria-hidden="true">적음 <span class="heat-cell"></span><span class="heat-cell lv1"></span><span class="heat-cell lv2"></span><span class="heat-cell lv3"></span><span class="heat-cell lv4"></span> 많음</div>';

  const ops = Object.keys(a.ops).sort((x, y) => a.ops[y] - a.ops[x]);
  const tot = Math.max(1, a.total);
  $("opBars").innerHTML = ops.length ? ops.map((o) => {
    const oc = OPS[o] || OPS.other;
    const pct = Math.max(2, Math.round(100 * a.ops[o] / tot));
    return '<div class="bar-row"><span class="bar-label">' + esc(o) + '</span>'
      + '<div class="bar-track"><div class="bar-fill" style="width:' + pct + '%;background:' + oc.c + '"></div></div>'
      + '<span class="bar-val">' + a.ops[o] + '</span></div>';
  }).join("") : '<p class="empty">기록 없음</p>';

  $("actFeed").innerHTML = s.log.slice(0, 14).map(logRow).join("") || '<li class="empty">기록 없음</li>';
}

/* ══ 전역 위임 + 탭 바 배선 + 부트 ══════════════════════════════════════════════ */

// 서고 검색 배선 — IME-safe + 제출 즉시
$("searchForm").addEventListener("submit", (ev) => {
  ev.preventDefault();
  onLibraryQuery($("q").value);
});
bindImeSafeSearch($("q"), 200, onLibraryQuery);

// data-action / data-slug 전역 위임 — 모든 탭의 행동이 한 리스너로 통한다 (agentmemory 위임 패턴)
document.addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-action],[data-slug]");
  if(!t) return;
  const act = t.getAttribute("data-action");
  if(act === "g-zoom-in") zoomBy(1.25);
  else if(act === "g-zoom-out") zoomBy(0.8);
  else if(act === "g-recenter") recenterGraph();
  else if(act === "close-detail"){
    clearSelection();
    const c = $("gcanvas");
    if(c) c.focus(); // 오버레이 닫힘 → 연 표면으로 포커스 복귀
  }
  else if(act === "page-detail") toggleInlineDetail(t.getAttribute("data-slug"), t);
  else if(act === "close-inline") closeInlineDetail(true);
  else if(act === "goto-star") gotoSlug(t.getAttribute("data-slug"));
  else if(act === "kind-filter") setKindFilter(t);
  else if(act === "op-filter") setOpFilter(t);
  else if(act === "lib-sort") setLibSort(t);
  else if(act === "chron-page") chronPage(t.getAttribute("data-page"));
  else if(act === "heat-day") gotoDay(t.getAttribute("data-day"));
  else if(act === "day-clear") clearDayFilter();
  else if(act === "refresh-now") refreshNow();
  else if(act === "open-tab") switchTab(t.getAttribute("data-tab"));
  else if(t.hasAttribute("data-slug")) gotoSlug(t.getAttribute("data-slug"));
});
document.addEventListener("keydown", (ev) => {
  if((ev.key === "Enter" || ev.key === " ") && ev.target instanceof HTMLElement && ev.target.tagName !== "BUTTON"
      && (ev.target.hasAttribute("data-slug") || ev.target.hasAttribute("data-action"))){
    ev.preventDefault();
    ev.target.click(); // role=button 표면(qrow)의 키보드 완주 — 클릭 위임과 같은 경로
  }
});

// 탭 바 — 클릭 + APG 키보드(화살표·Home·End 순회, 자동 활성)
const _tabBar = $("tabBar");
_tabBar.addEventListener("click", (e) => {
  const b = e.target instanceof Element ? e.target.closest("[data-tab]") : null;
  if(b) switchTab(b.dataset.tab);
});
_tabBar.addEventListener("keydown", (e) => {
  const tabs = Array.from(_tabBar.querySelectorAll('[role="tab"]'));
  const i = tabs.indexOf(document.activeElement);
  if(i < 0) return;
  let j = -1;
  if(e.key === "ArrowRight") j = (i + 1) % tabs.length;
  else if(e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
  else if(e.key === "Home") j = 0;
  else if(e.key === "End") j = tabs.length - 1;
  if(j >= 0){
    e.preventDefault();
    tabs[j].focus();
    switchTab(tabs[j].dataset.tab);
  }
});

// 해시 라우팅 — #성좌 딥링크 + 뒤로가기 (agentmemory syncTabFromRoute 이식).
// 미지의 해시(#main 스킵 링크 등)는 무시한다 — 스킵 링크가 탭을 리셋하면 안 된다.
function syncTabFromRoute(){
  const t = tabFromRoute();
  if(t) switchTab(t, { skipRoute: true });
}
window.addEventListener("hashchange", syncTabFromRoute);
window.addEventListener("popstate", syncTabFromRoute);

// ── 스플래시 디졸브 — 최소 점등 시간 보장 후 걷고, 요소는 제거 ──
function dismissSplash(){
  const sp = $("splash");
  if(!sp) return;
  const t0 = window.__splashT0 || 0;
  const wait = t0 ? Math.max(0, 1200 - (performance.now() - t0)) : 0;
  setTimeout(() => {
    sp.classList.add("out");
    setTimeout(() => { sp.remove(); }, 650);
  }, wait);
}
setTimeout(dismissSplash, 5000); // 어떤 실패에도 스플래시가 화면을 잡아두지 않는다

switchTab(tabFromRoute() || "개요", { replaceRoute: true });
startPolling();
</script>
</body>
</html>
"""
