"""HTTP 계층과 창 띄우기 — 소켓·핸들러·네이티브 셸.

라우팅은 `routes`가, 접근 검사와 헤더는 `commands.loopback`이 진다. 여기 남은 것은
"어디에 묶고, 무엇으로 여는가" 뿐이다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from ... import ui
from .. import loopback
from . import state
from .boundary import resolve_start_root
from .routes import dispatch, dispatch_post, dispatch_put, render_html  # noqa: F401  (계약 재수출)
from .state import _ROOT_LOCK  # noqa: F401  (계약 재수출)
from .tasks import load_project_tasks

# 접근 검사는 `commands.loopback` 한 곳 — 세 창이 같은 것을 막는다
host_allowed = loopback.host_allowed
origin_allowed = loopback.origin_allowed


class _Handler(loopback.LoopbackHandler):
    server_version = "AsgardStudio"

    _send = loopback.LoopbackHandler.send_guarded

    def _route(self, head_only: bool = False) -> None:
        if not host_allowed(self.headers.get("Host")):
            self._send(403, "text/plain; charset=utf-8", b"forbidden host", head_only)
            return
        parts = urlsplit(self.path)
        root = getattr(self.server, "root", os.getcwd())
        try:
            status, ctype, body = dispatch(self.command, parts.path, parse_qs(parts.query), root)
        except Exception as exc:
            # 여태 여기서 나가던 것은 `error: KeyError` 한 줄이었다 — JSON도 아니라 창의
            # `api()`가 읽지 못했고, 트레이스백은 버려져 어느 줄이었는지 알 길이 없었다.
            status, ctype, body = loopback.error_result(exc, surface="studio", root=root, where=parts.path)
        self._send(status, ctype, body, head_only)

    def do_GET(self) -> None:
        self._route()

    def do_HEAD(self) -> None:
        self._route(head_only=True)

    def _mutate(self, method: str) -> None:
        trusted_json = self.headers.get("X-Asgard-Studio") == "1" and self.headers.get(
            "Content-Type", ""
        ).lower().startswith("application/json")
        if not host_allowed(self.headers.get("Host")) or (
            not origin_allowed(self.headers.get("Origin")) and not trusted_json
        ):
            self._send(403, "text/plain; charset=utf-8", b"forbidden")
            return
        try:
            size = min(int(self.headers.get("Content-Length") or 0), 256_000)
            payload = json.loads(self.rfile.read(size).decode() or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        parts = urlsplit(self.path)
        root = getattr(self.server, "root", os.getcwd())
        try:
            route = dispatch_post if method == "POST" else dispatch_put
            status, ctype, body = route(parts.path, payload, root)
        except Exception as exc:
            status, ctype, body = loopback.error_result(exc, surface="studio", root=root, where=parts.path)
        self._send(status, ctype, body)

    def do_POST(self) -> None:
        self._mutate("POST")

    def do_PUT(self) -> None:
        self._mutate("PUT")


class _RootServer(ThreadingHTTPServer):
    root: str


def _bind(host: str, port: int, root: str | None = None) -> _RootServer:
    from .. import studio_store

    try:
        httpd = _RootServer((host, port), _Handler)
    except OSError:
        httpd = _RootServer((host, 0), _Handler)
    httpd.root = resolve_start_root(root)
    # 자리와 서버 핸들은 `state`가 소유한다 — 여기서 `global`로 잡으면 이 모듈의 전역이
    # 하나 더 생길 뿐이고, 되돌아 읽는 쪽은 영영 None을 본다.
    state._SERVER = httpd
    with state._ROOT_LOCK:
        state._CURRENT_ROOT = httpd.root
    # 등록부에는 **사용자가 프로젝트로 여는 자리**만 들어간다. cwd를 말없이 등록하면
    # 독에서 앱을 누른 것만으로 홈이 목록에 오른다 — 그건 기록이 아니라 오염이다.
    if studio_store.looks_like_project(httpd.root):
        studio_store.touch_project(httpd.root)
    load_project_tasks(httpd.root)  # 지난번에 하던 일이 창을 열면 그대로 있어야 한다
    return httpd


def _native_candidates() -> list[str]:
    """네이티브 셸을 어디서 찾을지 — 순서가 곧 정체성이다.

    macOS에서 맨 실행 파일을 그냥 띄우면 그 프로세스는 번들이 없는 것이 되어, 독에 이름도
    아이콘도 못 붙인다(회색 기본 아이콘이 뜨던 이유). `.app/Contents/MacOS/…`를 직접 실행하면
    시스템이 위로 올라가 그 번들의 Info.plist·아이콘을 읽는다 — 그래서 번들부터 본다.

    `..`가 넷인 이유: 이 파일은 `<리포>/src/asgard/commands/studio/server.py`다. 셋이면
    `<리포>/src`에서 멈춰 리포가 방금 빌드한 번들을 영영 못 찾는다 — 창은 조용히 브라우저로
    떨어지고, 사용자는 "네이티브 앱이 왜 안 뜨지"만 남는다. 한 파일이던 `desktop.py`가
    패키지로 갈리면서 깊이가 하나 늘었는데 이 줄만 그대로였다."""
    here = os.path.dirname(os.path.abspath(__file__))  # …/src/asgard/commands/studio
    repo = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    configured = os.environ.get("ASGARD_STUDIO_APP")
    found = shutil.which("asgard-studio")
    binary = "asgard-studio.exe" if os.name == "nt" else "asgard-studio"
    bare = [
        os.path.join(repo, "studio-shell", "src-tauri", "target", "release", binary),
        os.path.join(repo, "studio-shell", "src-tauri", "target", "debug", binary),
    ]
    if os.name == "nt":
        candidates = [
            configured,
            found,
            *bare,
            *(
                os.path.join(base, "Asgard Studio", binary)
                for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"))
                if base
            ),
        ]
    else:
        bundles = [
            os.path.join(
                repo,
                "studio-shell",
                "src-tauri",
                "target",
                "release",
                "bundle",
                "macos",
                "Asgard Studio.app",
                "Contents",
                "MacOS",
                binary,
            ),
            f"/Applications/Asgard Studio.app/Contents/MacOS/{binary}",
            os.path.expanduser(f"~/Applications/Asgard Studio.app/Contents/MacOS/{binary}"),
        ]
        candidates = [configured, *bundles, found, *bare]
    return list(dict.fromkeys(path for path in candidates if path and os.path.isfile(path)))


def _open_native(url: str, root: str) -> bool:
    env = {**os.environ, "ASGARD_STUDIO_URL": url, "ASGARD_STUDIO_ROOT": root}
    for path in _native_candidates():
        try:
            subprocess.run([path], env=env, check=False)
            return True
        except OSError:
            continue
    return False


def run_studio(
    port: int = 8766,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    prefer_native: bool = True,
    view: str = "",
    label: str = "Asgard Studio",
    root: str | None = None,
) -> int:
    from .. import studio_store

    if host not in ("127.0.0.1", "localhost", "::1"):
        ui.warn(f"host {host!r} is not loopback — forcing 127.0.0.1")
        host = "127.0.0.1"
    httpd = _bind(host, port, root)
    actual = httpd.server_address[1]
    # 모드 딥링크 — `--view plan`은 같은 창의 기획 화면으로 바로 들어온다(기획은 스튜디오 안에서만 쓴다)
    suffix = f"?view={quote(view)}" if view else ""
    url = f"http://{host}:{actual}/{suffix}"
    ui.ok(f"{label} → {url}")
    where = studio_store.SCRATCH_NAME if studio_store.is_scratch(httpd.root) else httpd.root
    ui.step(f"작업 공간: {where} (창에서 언제든 바꿉니다)")
    ui.step("종료: Ctrl-C")
    if open_browser:

        def launch() -> None:
            if prefer_native and _open_native(url, httpd.root):
                httpd.shutdown()
                return
            if prefer_native:
                ui.warn("Tauri app not built yet — opening the browser fallback")
            _open(url)

        threading.Timer(0.4, launch).start()
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
