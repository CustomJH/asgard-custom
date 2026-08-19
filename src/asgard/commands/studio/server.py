"""HTTP 계층과 창 띄우기 — 소켓·핸들러·네이티브 셸.

라우팅은 `routes`가, 접근 검사와 헤더는 `commands.loopback`이 진다. 여기 남은 것은
"어디에 묶고, 무엇으로 여는가" 뿐이다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from importlib import import_module
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

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
    # 청크 전송은 HTTP/1.1 부터다. 기본값 1.0 으로는 터미널 출력을 흘려보낼 수 없다.
    # 1.1 은 연결을 이어 쓴다는 뜻이기도 하다 — 그래서 아래 `timeout` 과 `_mutate` 의 몸통 처리가
    # 같이 따라온다. 이어 쓰는 연결에서는 안 읽은 몸통과 놀고 있는 소켓이 둘 다 사고가 된다.
    protocol_version = "HTTP/1.1"
    # 다음 요청을 기다리는 시간의 상한. 없으면 놀고 있는 연결 하나가 스레드 하나를 영원히 붙든다
    # (`ThreadingHTTPServer` 는 연결마다 스레드다). 흘려보내는 응답은 읽지 않고 쓰기만 하므로
    # 이 값에 걸리지 않는다 — 상한은 `readline` 이 다음 요청 줄을 기다릴 때만 센다.
    timeout = 30

    _send = loopback.LoopbackHandler.send_guarded

    # 길이를 미리 모르는 응답. `dispatch` 는 `(status, ctype, bytes)` 를 돌려주는 계약이라
    # 이 갈래는 그 앞에서 갈라져야 한다 — 40개가 넘는 나머지 경로의 모양을 하나 때문에
    # 바꾸지 않기 위해서다.
    _STREAMS = ("/api/terminal/stream",)

    def _route(self, head_only: bool = False) -> None:
        # 읽기에도 몸통이 올 수 있다. `GET` 은 몸통을 쓰지 않으므로 여태 아무도 안 읽었고,
        # 연결을 이어 쓰기 시작한 뒤로는 그 바이트가 다음 요청의 첫 줄이 됐다. 쓰기 쪽과
        # 같은 처리를 건다 — 길이가 확정되면 제거하고, 아니면 끊는다.
        self._drain(self._declared_length())
        if not host_allowed(self.headers.get("Host")):
            self._send(403, "text/plain; charset=utf-8", b"forbidden host", head_only)
            return
        parts = urlsplit(self.path)
        root = getattr(self.server, "root", os.getcwd())
        if parts.path in self._STREAMS and not head_only:
            from . import terminal

            terminal.stream(self, parse_qs(parts.query))
            return
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

    # 한 요청이 남긴 바이트가 다음 요청의 첫 줄로 읽히지 않도록, 몸통은 **읽거나 끊거나** 한다.
    # HTTP/1.0 일 때는 응답 뒤 소켓이 닫혀서 남은 바이트가 그냥 버려졌다. 연결을 이어 쓰기
    # 시작하면 그 바이트가 다음 요청으로 파싱된다 — 거절한 요청의 몸통이 다음 명령이 된다.
    _BODY_LIMIT = 256_000

    def _drain(self, size: int) -> None:
        """읽지 않을 몸통을 소켓에서 제거한다. 너무 크면 제거하는 대신 연결을 끊는다."""
        if size <= 0:
            return
        if size > self._BODY_LIMIT:
            self.close_connection = True
            return
        try:
            self.rfile.read(size)
        except OSError:
            self.close_connection = True

    def _declared_length(self) -> int:
        """몸통 길이가 **하나로 확정될 때만** 그 값을, 아니면 0 과 함께 연결을 끊는다.

        나쁜 모양을 하나씩 세어 막으려다 네 갈래를 놓쳤다(중복 `Content-Length`, 음수,
        콜론 앞 공백이 붙은 `Transfer-Encoding`, 몸통 달린 `GET`). 그래서 방향을 뒤집었다:
        길이를 의심 없이 셀 수 있는 요청만 통과시키고 나머지는 전부 끊는다. 새 우회 모양이
        생겨도 그것은 "확정되지 않음"으로 떨어지지 통과하지 않는다.

        끊는 이유는 하나다 — 안 읽은 몸통이 이어 쓰는 연결에서 다음 요청의 첫 줄이 된다.
        헤더 이름은 공백을 떼고 소문자로 맞춰 본다. `email` 파서는 `Transfer-Encoding :`
        처럼 콜론 앞에 공백이 있으면 이름에 그 공백을 남기므로, `.get()` 한 번으로는 못 잡는다."""
        if getattr(self.headers, "defects", None):
            # 헤더 한 줄이 망가지면 `email` 파서는 거기서 **머리 읽기를 멈춘다** — 뒤따르는
            # 헤더가 통째로 사라지고 그 바이트는 몸통 자리에 남는다. 실측: `Transfer-Encoding :`
            # (콜론 앞 공백) 하나로 `Content-Type` 이하가 전부 없어지고 `MissingHeaderBody
            # SeparatorDefect` 만 남았다. 이름을 맞춰 보는 검사로는 못 잡는다 — 그 이름 자체가
            # 파싱되지 않았기 때문이다. 머리를 믿을 수 없으면 길이도 믿을 수 없다.
            self.close_connection = True
            return 0
        names = {str(k).strip().lower() for k in self.headers.keys()}
        if "transfer-encoding" in names:
            # 길이가 몸통 안 청크에 적혀 있다. 이 표면은 청크를 안 읽으므로 셀 수가 없다.
            self.close_connection = True
            return 0
        declared = [v for k, v in self.headers.items() if str(k).strip().lower() == "content-length"]
        if not declared:
            return 0
        if len({v.strip() for v in declared}) != 1:
            # 값이 갈리면 어느 쪽이 몸통인지 우리가 정할 일이 아니다.
            self.close_connection = True
            return 0
        raw = declared[0].strip()
        # `isdecimal()` 이어야 한다. `isdigit()` 은 위첨자 `²`·`³`·`¹` 에 참을 내는데 `int()` 는
        # 그것을 거절하므로, 검사를 통과한 값이 아래에서 `ValueError` 로 터져 나간다 — 요청은
        # 거절되는 대신 응답 없이 죽는다. 그 셋이 여기까지 닿는 이유는 latin-1 에 있어서다:
        # `http.client` 가 머리를 iso-8859-1 로 읽으므로 회선을 타고 올 수 있는 글자는 그 범위뿐이고,
        # 그래서 실제로 통과할 수 있는 값은 ASCII 숫자열 하나뿐이다.
        if not raw.isdecimal():  # 음수·16진수·공백·빈 값도 여기서 걸린다
            self.close_connection = True
            return 0
        return int(raw)

    def _mutate(self, method: str) -> None:
        trusted_json = self.headers.get("X-Asgard-Studio") == "1" and self.headers.get(
            "Content-Type", ""
        ).lower().startswith("application/json")
        declared = self._declared_length()
        if not host_allowed(self.headers.get("Host")) or (
            not origin_allowed(self.headers.get("Origin")) and not trusted_json
        ):
            # 거절해도 몸통은 제거한다 — 안 걷으면 그것이 다음 요청 줄이 된다.
            self._drain(declared)
            self._send(403, "text/plain; charset=utf-8", b"forbidden")
            return
        if declared > self._BODY_LIMIT:
            # 상한을 넘은 몸통은 잘라 읽지 않는다. 잘라 읽으면 나머지가 소켓에 남는다.
            self.close_connection = True
            self._send(413, "text/plain; charset=utf-8", b"payload too large")
            return
        try:
            payload = json.loads(self.rfile.read(declared).decode() or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        parts = urlsplit(self.path)
        root = getattr(self.server, "root", os.getcwd())
        try:
            # 쿼리도 같이 넘긴다 — `?agent=…`는 **읽기만의 것이 아니다**. 여태 쓰기 쪽은
            # 이 값을 통째로 버려서, 명시로 고른 에이전트에 저장한 설정이 조용히 기본
            # 에이전트의 파일로 갔다(`request_scope`가 빈 explicit을 받아 sticky로 떨어진다).
            route = dispatch_post if method == "POST" else dispatch_put
            status, ctype, body = route(parts.path, payload, root, parse_qs(parts.query))
        except Exception as exc:
            status, ctype, body = loopback.error_result(exc, surface="studio", root=root, where=parts.path)
        self._send(status, ctype, body)

    def do_POST(self) -> None:
        self._mutate("POST")

    def do_PUT(self) -> None:
        self._mutate("PUT")


class _RootServer(loopback.LoopbackServer):
    root: str
    agent: str
    agent_explicit: str  # 사용자가 이름을 대고 연 경우에만 찬다 — 해석값(agent)과 다른 축이다
    agent_source: str
    run_id: str
    run_token: str

    def server_close(self) -> None:
        try:
            run_id = getattr(self, "run_id", "")
            if run_id:
                from ... import runs

                runs.unregister(run_id, getattr(self, "run_token", ""))
                self.run_id = ""
        finally:
            super().server_close()


def _studio_url(host: str, port: int, agent: str = "", view: str = "") -> str:
    query = urlencode({key: value for key, value in (("agent", agent), ("view", view)) if value})
    return f"http://{host}:{port}/" + (f"?{query}" if query else "")


def _resolve_agent(root: str, explicit: str | None = None) -> str:
    from ... import errors, profiles, sessions

    if explicit:
        try:
            explicit = profiles.validate(explicit)
        except ValueError as exc:
            raise errors.InvalidInput(str(exc), remedy="`asgard agent list`로 쓸 수 있는 이름을 확인하세요") from exc
        if not profiles.exists(explicit):
            raise errors.NotFound(
                f"에이전트 {explicit!r}를 못 찾았어요",
                remedy=f"`asgard agent create {explicit}`로 먼저 세우세요",
                detail={"agent": explicit},
            )
    agent = sessions.resolve_agent(root, explicit=explicit)
    if not profiles.exists(agent):
        raise errors.NotFound(
            f"에이전트 {agent!r}를 못 찾았어요",
            remedy=f"`asgard agent create {agent}`로 먼저 세우세요",
            detail={"agent": agent},
        )
    return agent


def _agent_source(root: str, explicit: str = "") -> str:
    """이 서버가 왜 그 에이전트로 섰는가 — explicit·binding·sticky 중 하나.

    창의 배지가 이 값을 그대로 말한다. 해석 결과만 들고 있으면 "고정으로 골랐다"와 "프로젝트가
    배치했다"와 "기계 기본이다"가 화면에서 구분되지 않는다."""
    from ... import sessions

    try:
        return str(sessions.describe(root, explicit=explicit or None).get("source") or "sticky")
    except Exception:  # 출처를 못 읽는 것이 서버 시동을 막으면 안 된다
        return "explicit" if explicit else "sticky"


def _bind(
    host: str,
    port: int,
    root: str | None = None,
    *,
    agent: str | None = None,
    label: str = "Asgard Studio",
    isolated: bool = False,
) -> _RootServer:
    from ... import profiles
    from .. import studio_store

    resolved_root = resolve_start_root(root)
    resolved_agent = _resolve_agent(resolved_root, agent)
    try:
        httpd = _RootServer((host, port), _Handler)
    except OSError:
        httpd = _RootServer((host, 0), _Handler)
    httpd.root = resolved_root
    httpd.agent = resolved_agent
    # 명시로 고른 이름과 해석된 이름을 가른다. 등록부는 해석값을 적어야 하고(지금 누가 도는가),
    # 시동 URL은 명시값만 실어야 한다(왜 그 에이전트인가). 여태 URL이 해석값을 실어서, 배치나
    # 끈끈한 활성으로 연 창도 `?agent=`를 달고 열려 창이 그것을 explicit으로 읽었다 — 배지가
    # "고정"이라고 말하는데 실제 출처는 sticky인 상태였다.
    httpd.agent_explicit = profiles.normalize(agent) if agent else ""
    httpd.agent_source = _agent_source(resolved_root, httpd.agent_explicit)
    httpd.run_id = ""
    httpd.run_token = ""
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
    from ... import runs

    actual = int(httpd.server_address[1])
    record = runs.register(
        httpd.agent,
        "studio",
        host,
        actual,
        _studio_url(host, actual, httpd.agent_explicit),
        root=httpd.root,
        label=f"{label} (isolated)" if isolated else label,
    )
    httpd.run_id = str(record["id"])
    httpd.run_token = str(record["token"])
    return httpd


def _windows_install_dirs() -> list[str]:
    """설치본이 **적어 둔** 자리. 추측 경로는 사람이 폴더를 바꿔 깔면 통째로 빗나간다.

    설치본은 제거 항목에 `InstallLocation`을 남긴다 — 사용자 설치는 HKCU, 기계 전체 설치는
    HKLM이고 키 이름은 번들 식별자다. 옛 설치본은 같은 자리를 제품 이름으로 적었다."""
    try:  # POSIX에 없는 모듈 — Any로 든다 (winterm의 msvcrt 선례)
        winreg: Any = import_module("winreg")
    except ImportError:
        return []
    found: list[str] = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for name in ("dev.asgard.studio", "Asgard Studio"):
            try:
                with winreg.OpenKey(hive, rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{name}") as handle:
                    where = str(winreg.QueryValueEx(handle, "InstallLocation")[0] or "")
            except OSError:
                continue
            if where:
                found.append(where)
    return found


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
        bases = [base for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles")) if base]
        homes = [
            *_windows_install_dirs(),
            *(os.path.join(base, "Asgard Studio") for base in bases),
            *(os.path.join(base, "Programs", "Asgard Studio") for base in bases),
        ]
        candidates = [configured, found, *bare, *(os.path.join(home, binary) for home in homes)]
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


def _open_native(url: str, root: str, agent: str = "") -> bool:
    env = {
        **os.environ,
        "ASGARD_STUDIO_URL": url,
        "ASGARD_STUDIO_ROOT": root,
        "ASGARD_STUDIO_AGENT": agent,
    }
    for path in _native_candidates():
        try:
            subprocess.run([path], env=env, check=False)
            return True
        except OSError:
            continue
    return False


def install_shell() -> int:
    """네이티브 창을 이 기계에 깐다 — 릴리스에 붙어 있는 Windows 설치본을 받아 실행한다.

    여태 Windows에는 창을 가져올 길이 없었다. 설치본(`Asgard.Studio_<판>_x64-setup.exe`)은
    릴리스마다 붙어 나갔는데 `install.ps1`도 `asgard update`도 그것을 안 가져왔고, 화면에
    나가던 말은 "아직 안 구웠다"였다 — 휠로 받은 사람에게 구울 것은 애초에 없다."""
    from ... import __version__
    from ..update import _REPO, _download

    if os.name != "nt":
        ui.fail("설치본은 Windows 것만 릴리스에 붙어요")
        ui.step(ui.dim("다른 플랫폼은 studio-shell/README.md 를 따라 직접 구우세요"))
        return 1
    if _native_candidates():
        ui.ok("네이티브 창이 이미 깔려 있어요")
        return 0
    name = f"Asgard.Studio_{__version__}_x64-setup.exe"
    url = f"https://github.com/{_REPO}/releases/download/v{__version__}/{name}"
    tmpd = tempfile.mkdtemp(prefix="asgard-studio-")
    setup = os.path.join(tmpd, name)
    ui.head("install the native window", 2)
    ui.phase("download")
    try:
        _download(url, setup, label=name)
    except Exception as exc:
        shutil.rmtree(tmpd, ignore_errors=True)
        ui.fail(f"내려받지 못했어요: {exc}")
        ui.step(ui.dim(url))
        return 1
    ui.phase("install")
    # `/S` — 무인 설치. 창을 여는 도중에 마법사를 띄우면 눌러 줄 사람이 그 자리에 없다.
    # 사용자 설치(현재 사용자)라 권한 상승도 없다.
    with ui.spin("installing the native window…"):
        code = subprocess.run([setup, "/S"]).returncode
    shutil.rmtree(tmpd, ignore_errors=True)  # 설치본이 아직 돌면 Windows가 못 지운다 — 무해하다
    if _native_candidates():
        ui.done("네이티브 창을 깔았어요")
        return 0
    ui.fail(f"설치본이 끝났는데도 창을 못 찾았어요 (종료 코드 {code})")
    ui.step(ui.dim("직접 깔아 보세요: " + url))
    return code or 1


def _launch_window(url: str, root: str, agent: str, prefer_native: bool, json_out: bool) -> bool:
    """창을 띄운다. 네이티브로 열었으면 True — 그 창이 닫힌 것이니 서버도 접어야 한다.

    Windows에서는 **처음 여는 자리가 곧 까는 자리다**. 설치본은 릴리스마다 붙어 나가는데
    가져오는 길이 없어서, 첫 실행이 늘 브라우저로 떨어지고 사람에게는 "앱이 안 켜진다"로
    보였다. 사람이 보고 있을 때만(TTY) 깐다 — 무인 실행에서 말없이 프로그램을 내려받아
    까는 것은 부른 적 없는 일이다. 그 자리에서는 예전처럼 브라우저로 연다."""
    if prefer_native and _open_native(url, root, agent):
        return True
    installable = prefer_native and not json_out and os.name == "nt" and sys.stdout.isatty()
    if installable and install_shell() == 0 and _open_native(url, root, agent):
        return True
    if prefer_native and not json_out:
        ui.warn("네이티브 창이 아직 없어요 — 브라우저로 열게요")
        ui.step(ui.dim("설치: asgard open studio --install" if os.name == "nt" else "빌드: studio-shell/README.md"))
    _open(url)
    return False


def run_studio(
    port: int = 8766,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    prefer_native: bool = True,
    view: str = "",
    label: str = "Asgard Studio",
    root: str | None = None,
    agent: str | None = None,
    isolated: bool = False,
    json_out: bool = False,
) -> int:
    from .. import studio_store

    if host not in ("127.0.0.1", "localhost", "::1"):
        ui.warn(f"host {host!r} is not loopback — forcing 127.0.0.1")
        host = "127.0.0.1"
    httpd = _bind(host, port, root, agent=agent, label=label, isolated=isolated)
    actual = httpd.server_address[1]
    url = _studio_url(host, actual, httpd.agent_explicit, view)
    if json_out:
        print(
            json.dumps(
                {
                    "window": {
                        "id": httpd.run_id,
                        "agent": httpd.agent,
                        "url": url,
                        "pid": os.getpid(),
                        "port": actual,
                    },
                    "reused": False,
                },
                ensure_ascii=False,
            )
        )
    else:
        ui.ok(f"{label} → {url}")
        ui.step(f"에이전트: {httpd.agent}")
        where = studio_store.SCRATCH_NAME if studio_store.is_scratch(httpd.root) else httpd.root
        ui.step(f"작업 공간: {where} (창에서 언제든 바꿀 수 있어요)")
        ui.step("종료: Ctrl-C")
    if open_browser:

        def launch() -> None:
            if _launch_window(url, httpd.root, httpd.agent, prefer_native, json_out):
                httpd.shutdown()

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
