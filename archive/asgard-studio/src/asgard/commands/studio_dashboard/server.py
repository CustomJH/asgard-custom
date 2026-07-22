"""HTTP 계층 — 루프백 전용 서버·라우팅. 프론트엔드 HTML 은 assets/studio_dashboard.html 에셋.

memory dashboard 와 코드·표면 분리(CUS-263: 별도 명령·별도 모듈) — Host 가드 같은 보안
기법은 관례로 동일하게 적용하되 구현은 스튜디오 소유다.
"""

from __future__ import annotations

import json as _json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files as _files
from urllib.parse import parse_qs, urlsplit

from ... import ui
from .data import (
    ENGINES,
    PROJECTS,
    artifact_path,
    engine,
    ensure_home,
    project_data,
    read_run_log,
    read_state,
    slug_ok,
    snapshot_data,
    studio_dir,
    template_file,
    templates_data,
)

# ── 라우팅 (소켓 없이 단위 테스트 가능한 순수 디스패치) ──────────────────────────────


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
_SPAWN_LOCK = threading.Lock()


def host_allowed(host_header: str | None) -> bool:
    """DNS 리바인딩 방어 — Host 헤더의 호스트명이 루프백이어야 한다. 스튜디오 아티팩트는
    로컬 작업물이므로, 외부 도메인이 사용자의 브라우저를 통해 127.0.0.1 을 읽는 표면을
    봉쇄한다 (memory dashboard 와 같은 관례, 구현은 스튜디오 소유)."""
    if not host_header:
        return False
    h = host_header.strip().lower()
    if h.startswith("["):  # IPv6 리터럴 [::1]:port
        h = h.split("]")[0] + "]"
    elif ":" in h:  # host:port
        h = h.rsplit(":", 1)[0]
    return h in _LOOPBACK_HOSTS


def origin_allowed(origin: str | None) -> bool:
    """POST CSRF 방어 — Origin 이 없거나(curl 류) 루프백 출처여야 한다. Host 가드는 위조
    Host 를 막지만, 외부 페이지가 127.0.0.1 로 보내는 cross-origin POST 의 Host 는 정상이라
    Origin 검사로만 걸러진다."""
    if not origin:
        return True
    try:
        from urllib.parse import urlsplit as _split

        return (_split(origin).hostname or "") in ("127.0.0.1", "localhost", "::1")
    except Exception:
        return False


def dispatch(method: str, path: str, params: dict[str, list[str]], d: str | None = None) -> tuple[int, str, bytes]:
    if method not in ("GET", "HEAD"):
        return 405, "text/plain; charset=utf-8", b"method not allowed"
    if path in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", render_html().encode("utf-8")
    if path == "/api/snapshot":
        snap = snapshot_data(d)
        snap["engine"] = {"provider": engine(d), "label": ENGINES.get(engine(d), engine(d)), "choices": ENGINES}
        body = _json.dumps(snap, ensure_ascii=False).encode("utf-8")
        return 200, "application/json; charset=utf-8", body
    if path == "/api/templates":
        body = _json.dumps(templates_data(), ensure_ascii=False).encode("utf-8")
        return 200, "application/json; charset=utf-8", body
    if path == "/template":
        name = (params.get("name") or [""])[0]
        rel = (params.get("file") or [None])[0]
        got = template_file(name, rel)
        if got is None:
            return 404, "text/plain; charset=utf-8", b"not found"
        ctype = mimetypes.guess_type(got[0])[0] or "application/octet-stream"
        return 200, ctype, got[1]
    if path == "/api/project":
        slug = (params.get("slug") or [""])[0]
        data = project_data(slug, d)
        status = 404 if data.get("error") else 200
        return status, "application/json; charset=utf-8", _json.dumps(data, ensure_ascii=False).encode("utf-8")
    if path == "/api/runlog":
        slug = (params.get("slug") or [""])[0]
        if not slug_ok(slug):
            return 404, "text/plain; charset=utf-8", b"not found"
        import os as _os

        text = read_run_log(_os.path.join(d or studio_dir(), PROJECTS, slug))
        return 200, "text/plain; charset=utf-8", text.encode("utf-8")
    if path == "/artifact":
        slug = (params.get("slug") or [""])[0]
        rel = (params.get("path") or [""])[0]
        target = artifact_path(slug, rel, d)
        if target is None:
            return 404, "text/plain; charset=utf-8", b"not found"
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        with open(target, "rb") as f:
            return 200, ctype, f.read()
    return 404, "text/plain; charset=utf-8", b"not found"


def dispatch_post(path: str, payload: dict, d: str | None = None) -> tuple[int, str, bytes]:
    """쓰기 표면은 생성 트리거 하나 — 서버는 워커를 스폰만 하고 결과는 GET 폴링으로 관찰한다.
    (내보내기 등 추가 쓰기는 CUS-263 본체 몫.)"""

    def _json_body(status: int, obj: dict) -> tuple[int, str, bytes]:
        return status, "application/json; charset=utf-8", _json.dumps(obj, ensure_ascii=False).encode("utf-8")

    from .. import studio as _studio

    if path == "/api/engine":  # Claude Code ↔ Codex CLI 전환
        provider = _studio.set_engine(str(payload.get("engine") or ""), d)
        if provider is None:
            return _json_body(400, {"error": "unknown engine", "choices": ENGINES})
        return _json_body(200, {"engine": provider, "label": ENGINES[provider]})
    if path == "/api/template-use":  # 템플릿 → 즉시 프로젝트 (무 LLM)
        p = _studio.use_template(
            str(payload.get("name") or ""), brief=str(payload.get("brief") or "").strip() or None, d=d
        )
        if p is None:
            return _json_body(404, {"error": "unknown template"})
        return _json_body(201, {"slug": p["slug"], "template": p["template"], "status": "ok"})
    if path != "/api/generate":
        return 404, "text/plain; charset=utf-8", b"not found"

    with _SPAWN_LOCK:  # ThreadingHTTPServer의 중복 POST가 상태 확인과 spawn 사이로 끼어들지 못하게 한다.
        slug = str(payload.get("slug") or "").strip()
        brief = str(payload.get("brief") or "").strip()
        if slug:  # 기존 프로젝트 재생성 (+선택적 추가 지시 병합 — refine-lite)
            if not slug_ok(slug):
                return _json_body(400, {"error": "bad slug"})
            import os as _os

            pdir = _os.path.join(d or studio_dir(), PROJECTS, slug)
            if not _os.path.isdir(pdir):
                return _json_body(404, {"error": "not found", "slug": slug})
            if read_state(pdir).get("status") == "running":
                return _json_body(409, {"error": "generation already running", "slug": slug})
            if brief:
                _studio.append_instruction(slug, brief, d)
        else:  # 새 프로젝트 — 브리프 필수
            if not brief:
                return _json_body(400, {"error": "brief required"})
            name = str(payload.get("name") or "").strip() or None
            slug = _studio.create_project(brief, name=name, d=d)["slug"]
        pid = _spawn(slug, d)
        return _json_body(202, {"slug": slug, "pid": pid, "status": "running"})


def _spawn(slug: str, d: str | None) -> int:
    """워커 스폰 간접층 — 테스트가 monkeypatch 하는 단일 지점."""
    from .. import studio as _studio

    return _studio.spawn_generation(slug, d)


class _Handler(BaseHTTPRequestHandler):
    server_version = "AsgardStudioDashboard"

    def _send(self, status: int, ctype: str, body: bytes, head_only: bool = False, artifact: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if artifact:
            # 아티팩트는 생성물(신뢰 경계 밖) — 프리뷰는 격리 샌드박스에서만 실행된다.
            self.send_header("Content-Security-Policy", "sandbox allow-scripts")
        else:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "connect-src 'self'; frame-src 'self'",
            )
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _route(self, head_only: bool = False) -> None:
        if not host_allowed(self.headers.get("Host")):
            self._send(403, "text/plain; charset=utf-8", b"forbidden host", head_only=head_only)
            return
        parts = urlsplit(self.path)
        try:
            status, ctype, body = dispatch(self.command, parts.path, parse_qs(parts.query))
        except Exception as exc:  # 어떤 실패도 서버를 죽이지 않는다 (fail-open)
            status, ctype, body = 500, "text/plain; charset=utf-8", f"error: {type(exc).__name__}".encode()
        self._send(status, ctype, body, head_only=head_only, artifact=parts.path in ("/artifact", "/template"))

    def do_GET(self) -> None:
        self._route()

    def do_HEAD(self) -> None:
        self._route(head_only=True)

    def do_POST(self) -> None:
        if not host_allowed(self.headers.get("Host")) or not origin_allowed(self.headers.get("Origin")):
            self._send(403, "text/plain; charset=utf-8", b"forbidden")
            return
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 1_000_000)  # 브리프 상한 1MB
            payload = _json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        parts = urlsplit(self.path)
        try:
            status, ctype, body = dispatch_post(parts.path, payload)
        except Exception as exc:  # fail-open — 서버는 죽지 않는다
            status, ctype, body = 500, "text/plain; charset=utf-8", f"error: {type(exc).__name__}".encode()
        self._send(status, ctype, body)

    def log_message(self, format: str, *args: object) -> None:  # 조용히 (요청 로그 억제)
        return


def _bind(host: str, port: int) -> ThreadingHTTPServer:
    """요청 포트를 먼저 시도하고, 점유돼 있으면 임시 포트(0)로 폴백한다."""
    try:
        return ThreadingHTTPServer((host, port), _Handler)
    except OSError:
        return ThreadingHTTPServer((host, 0), _Handler)


def run_dashboard(
    port: int = 8766, host: str = "127.0.0.1", open_browser: bool = True, focus: str | None = None
) -> int:
    """127.0.0.1 바인드 · 표준 라이브러리 전용 · Ctrl-C 종료 일회성 프로세스.
    focus = 프로젝트 슬러그 딥링크 (해시 라우팅 #p/<slug>)."""
    ensure_home()
    if host not in ("127.0.0.1", "localhost", "::1"):
        ui.warn(f"host {host!r} is not loopback — forcing 127.0.0.1 (스튜디오는 로컬 전용)")
        host = "127.0.0.1"
    httpd = _bind(host, port)
    actual = httpd.server_address[1]
    url = f"http://{host}:{actual}/"
    if focus and slug_ok(focus):
        url += f"#p/{focus}"
    ui.ok(f"세스룸니르 · studio dashboard → {url}")
    ui.step("종료: Ctrl-C")
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
    return _PAGE


# 자기완결 단일 HTML 에셋 — memory dashboard 와 같은 importlib.resources 패턴, import 시 1회 로드
_PAGE = (_files("asgard") / "assets" / "studio_dashboard.html").read_text(encoding="utf-8")
