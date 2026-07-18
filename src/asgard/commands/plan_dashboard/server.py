"""Asgard Plan 로컬 대시보드 HTTP 계층 — 루프백 전용, 의존성 0."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files as _files
from urllib.parse import urlsplit

from ... import ui

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def host_allowed(host_header: str | None) -> bool:
    """DNS 리바인딩 방어 — Plan 목업과 향후 로컬 기획 데이터는 루프백에서만 노출한다."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    return host in _LOOPBACK_HOSTS


def dispatch(method: str, path: str) -> tuple[int, str, bytes]:
    if method not in ("GET", "HEAD"):
        return 405, "text/plain; charset=utf-8", b"method not allowed"
    if path in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", render_html().encode("utf-8")
    if path == "/asset/logo":
        body = (_files("asgard") / "assets" / "gold-brand-logo.png").read_bytes()
        return 200, "image/png", body
    if path == "/health":
        return 200, "application/json; charset=utf-8", b'{"ok":true,"surface":"plan"}'
    return 404, "text/plain; charset=utf-8", b"not found"


class _Handler(BaseHTTPRequestHandler):
    server_version = "AsgardPlanDashboard"

    def _route(self, head_only: bool = False) -> None:
        if not host_allowed(self.headers.get("Host")):
            self._send(403, "text/plain; charset=utf-8", b"forbidden host", head_only)
            return
        path = urlsplit(self.path).path
        try:
            status, ctype, body = dispatch(self.command, path)
        except Exception as exc:
            status, ctype, body = 500, "text/plain; charset=utf-8", f"error: {type(exc).__name__}".encode()
        self._send(status, ctype, body, head_only)

    def _send(self, status: int, ctype: str, body: bytes, head_only: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; connect-src 'self'",
        )
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def do_GET(self) -> None:
        self._route()

    def do_HEAD(self) -> None:
        self._route(head_only=True)

    def do_POST(self) -> None:
        self._route()

    def log_message(self, format: str, *args: object) -> None:
        return


def _bind(host: str, port: int) -> ThreadingHTTPServer:
    try:
        return ThreadingHTTPServer((host, port), _Handler)
    except OSError:
        return ThreadingHTTPServer((host, 0), _Handler)


def run_dashboard(port: int = 8767, host: str = "127.0.0.1", open_browser: bool = True) -> int:
    """Plan 목업을 루프백에서 실행한다. 종료는 Ctrl-C."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        ui.warn(f"host {host!r} is not loopback — forcing 127.0.0.1 (Plan은 로컬 전용)")
        host = "127.0.0.1"
    httpd = _bind(host, port)
    actual = httpd.server_address[1]
    url = f"http://{host}:{actual}/"
    ui.ok(f"Asgard Plan · planning workspace → {url}")
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


def render_html() -> str:
    return _PAGE


_PAGE = (_files("asgard") / "assets" / "plan_dashboard.html").read_text(encoding="utf-8")
