"""HTTP 계층 — 루프백 전용 서버·라우팅. 프론트엔드 HTML 은 assets/memory_dashboard.html 에셋."""

from __future__ import annotations

import json as _json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files as _files
from urllib.parse import parse_qs, urlsplit

from ... import memory, ui
from .data import _LOGO_URI, log_query, page_data, search_data, snapshot_data

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
    ui.ok(f"위그드라실 · memory dashboard → {url}")
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


# 자기완결 단일 HTML 에셋 — 로고 png(_packaged_logo)와 같은 importlib.resources 패턴, import 시 1회 로드
_PAGE = (_files("asgard") / "assets" / "memory_dashboard.html").read_text(encoding="utf-8")
