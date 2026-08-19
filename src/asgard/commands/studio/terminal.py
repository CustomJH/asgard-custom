"""터미널 백엔드 — 셸 하나를 열고, 그 출력만 흘려보내고, 입력은 평범한 POST 로 받는다.

두 개의 축이 있다.

**세션 등록부** — `pty.fork()` 로 띄운 셸 하나가 세션 하나다. 세션은 자기 읽기 스레드를 갖고,
그 스레드만 마스터 fd 를 읽는다. 읽는 손이 하나뿐이어야 프레임 번호(`seq`)가 끊기지 않고,
fd 를 닫는 자리도 하나로 모인다 — 스트림이 fd 를 닫고 다른 스레드가 같은 번호를 다시 받는
경합이 여기서 사라진다.

**토큰** — 세션 id 만으로 붙을 수 있으면, 이 창을 여는 아무 페이지나 남의 셸에 붙는다.
루프백이라는 것은 "브라우저가 여기까지 올 수 있다"는 뜻이지 "여기 있는 것이 그 페이지 것"이라는
뜻이 아니다. 그래서 `open` 이 낸 토큰을 이후 모든 창구가 요구하고, 비교는
`secrets.compare_digest` 로 한다.

출력만 길이를 모르는 응답이라 갈래가 다르다: `stream` 은 `server._Handler._route` 가 `dispatch`
**앞에서** 가로채 핸들러를 통째로 넘겨준다(청크 전송 원시 도구는 `loopback.LoopbackHandler`).
나머지 넷은 평범한 JSON 왕복이다.

`pty`·`fcntl`·`termios` 는 POSIX 전용이라 최상위에서 임포트하지 않는다 — Windows 에서 이 모듈이
임포트되는 것만으로 창 전체가 죽으면 안 된다. 그 플랫폼에서는 모든 창구가 501 로 답한다.
"""

from __future__ import annotations

import codecs
import json
import os
import secrets
import selectors
import shutil
import signal
import threading
import time
from collections import deque

from .. import loopback

# 읽기 한 번의 상한. 이보다 큰 출력은 다음 프레임으로 넘어간다.
_READ_SIZE = 65536
# 읽기 스레드가 닫힘 요청을 확인하는 주기. 블로킹 읽기 대신 이 주기로 깨는 이유는,
# 슬레이브를 붙잡은 손자 프로세스가 남으면 블로킹 읽기가 영영 안 돌아오기 때문이다.
_TICK = 0.5
# 스트림이 아무 출력 없이 보내는 주석 프레임 간격 — 창이 닫힌 것을 이걸로 알아챈다.
_HEARTBEAT = 15.0
# 그래도 아무것도 안 오면 스트림을 놓는다. 서버 스레드를 영원히 잡을 수는 없다.
# 창은 `?after=<seq>` 로 이어 붙는다.
_IDLE_LIMIT = 900.0
# 창이 붙기 전에 나온 출력을 들고 있는 폭. 이걸 넘으면 앞에서부터 버린다.
_BUFFER_CHARS = 256_000
_MAX_SESSIONS = 8
_MAX_COLS, _MAX_ROWS = 500, 300
# SIGTERM 뒤 자식이 스스로 나가기를 기다리는 시간, 그다음 SIGKILL 뒤 거두기를 기다리는 시간.
_TERM_GRACE = 1.0
_KILL_GRACE = 2.0
# 끝난 세션을 등록부에 남겨 두는 시간 — 창이 늦게 붙어도 "왜 죽었는지"를 볼 수 있어야 한다.
_DEAD_GRACE = 60.0

_SESSIONS: dict[str, _Session] = {}
_REGISTRY_LOCK = threading.Lock()

_SSE_TYPE = "text/event-stream; charset=utf-8"


# ── 세션 ──────────────────────────────────────────────────────────────────────


class _Session:
    """셸 하나 — 프로세스, 마스터 fd, 그리고 아직 아무도 안 읽은 출력."""

    def __init__(self, sid: str, token: str, pid: int, fd: int, cwd: str, shell: str, cols: int, rows: int) -> None:
        self.id = sid
        self.token = token
        self.pid = pid
        self.fd = fd
        self.cwd = cwd
        self.shell = shell
        self.cols = cols
        self.rows = rows
        self.started = time.time()
        self.seq = 0
        self.alive = True
        self.closing = False
        self.reaped = False
        self.status: int | None = None
        self.ended = 0.0
        self.thread: threading.Thread | None = None
        # 창이 붙기 전에 나온 출력. 무한정 쌓지 않는다 — 넘치면 앞에서부터 버린다.
        self._frames: deque[tuple[int, str]] = deque()
        self._chars = 0
        # PTY 는 바이트로 오고 한 글자가 두 읽기에 걸쳐 올 수 있다. 조각난 UTF-8 을
        # 프레임마다 새로 디코드하면 한글이 물음표가 된다.
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.cond = threading.Condition()
        self.lock = threading.Lock()

    def push(self, chunk: bytes) -> None:
        text = self._decoder.decode(chunk)
        if not text:
            return
        with self.cond:
            self.seq += 1
            self._frames.append((self.seq, text))
            self._chars += len(text)
            while self._chars > _BUFFER_CHARS and len(self._frames) > 1:
                self._chars -= len(self._frames.popleft()[1])
            self.cond.notify_all()

    def pending(self, after: int) -> list[tuple[int, str]]:
        return [frame for frame in self._frames if frame[0] > after]

    def finish(self) -> None:
        """셸이 끝났다 — 기다리는 스트림을 전부 깨운다."""
        with self.cond:
            if self.alive:
                self.alive = False
                self.ended = time.time()
            self.cond.notify_all()

    def row(self) -> dict:
        """진단용 한 줄. **토큰은 넣지 않는다** — 목록이 곧 열쇠가 되면 토큰을 둔 뜻이 없다."""
        return {
            "id": self.id,
            "pid": self.pid,
            "cwd": self.cwd,
            "shell": self.shell,
            "cols": self.cols,
            "rows": self.rows,
            "alive": self.alive,
            "started": self.started,
            "seq": self.seq,
            "status": self.status,
        }


def _spawn(cwd: str, shell: str, cols: int, rows: int) -> tuple[int, int]:
    """셸을 띄우고 `(pid, 마스터 fd)` 를 돌려준다.

    `pty.fork()` 를 쓰는 이유는 그것만이 자식을 세션 리더로 만들고 슬레이브를 **제어 터미널**로
    붙여 주기 때문이다. `openpty()` + `subprocess(start_new_session=True)` 로 바꾸면 제어
    터미널이 없어 셸이 잡 제어를 끄고, Ctrl-C 가 앞단 프로세스에 안 간다 — 터미널이 아니게 된다.
    대신 제약이 하나 붙는다: 스레드가 도는 프로세스에서 fork 하면 자식은 exec 까지
    async-signal-safe 한 것만 해야 한다(파이썬 3.12 부터 `DeprecationWarning` 으로 알린다). 그래서 자식이
    하는 일을 둘로 줄였다 — 나머지는 전부 부모에서 미리 만든다: 셸의 절대 경로(PATH 탐색 없음),
    환경 사전, 그리고 크기.
    """
    import pty

    env = {**os.environ, "TERM": "xterm-256color"}
    pid, fd = pty.fork()
    if pid == 0:  # 자식
        try:
            os.chdir(cwd)
            os.execve(shell, [shell], env)
        except BaseException as exc:
            # 자식에서는 예외를 올릴 수 없다 — 올리면 부모의 요청 처리 스택이 자식에서 한 번 더
            # 돈다(응답을 두 벌 쓰고, 소켓을 두 벌 닫는다). 대신 이유를 슬레이브에 적는다:
            # 여기 적은 줄은 마스터로 그대로 나가서 사용자의 터미널 첫 줄이 된다.
            os.write(2, f"asgard: {shell} 을 띄우지 못했어요 — {exc}\r\n".encode(errors="replace"))
        os._exit(127)
    try:
        _resize(fd, cols, rows)
    except OSError:
        pass  # 크기는 창이 붙은 뒤 resize 로 다시 온다 — 여기서 못 정했다고 셸을 버릴 이유는 없다
    return pid, fd


def _resize(fd: int, cols: int, rows: int) -> None:
    import fcntl
    import struct
    import termios

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _pump(session: _Session) -> None:
    """세션의 유일한 독자. 마스터 fd 를 읽는 것도, 닫는 것도 이 스레드뿐이다."""
    selector = selectors.DefaultSelector()
    try:
        selector.register(session.fd, selectors.EVENT_READ)
        while not session.closing:
            if not selector.select(timeout=_TICK):
                continue
            try:
                chunk = os.read(session.fd, _READ_SIZE)
            except OSError:
                break  # 슬레이브가 닫혔다 — 셸이 끝났다는 뜻이다
            if not chunk:
                break
            session.push(chunk)
    finally:
        selector.close()
        _reap(session)
        try:
            os.close(session.fd)
        except OSError:
            pass  # 이미 닫혔다 — 닫는 손은 이 스레드뿐이라 그 밖의 실패는 없다
        session.finish()


def _reap(session: _Session) -> bool:
    """이미 죽은 자식만 거둔다 — 아직 살아 있으면 False.

    안 거두면 세션을 여닫을 때마다 좀비가 쌓인다. 거두는 자리를 하나로 모아 두는 이유는,
    둘이 같은 pid 에 `waitpid` 를 걸면 한쪽이 `ChildProcessError` 를 받고 그 실패가
    "못 거뒀다"로 읽히기 때문이다."""
    with session.lock:
        if session.reaped:
            return True
        try:
            pid, raw = os.waitpid(session.pid, os.WNOHANG)
        except ChildProcessError:
            session.reaped = True  # 이미 누가 거뒀다
            return True
        except OSError:
            return False
        if pid == 0:
            return False
        session.reaped = True
        session.status = os.waitstatus_to_exitcode(raw)
        return True


def _signal(session: _Session, sig: int) -> None:
    """프로세스 **그룹**에 보낸다 — 셸이 띄운 자식들까지 같이 나가야 한다.

    거둔 뒤에는 절대 보내지 않는다. 거두기 전의 pid 는 좀비라 재사용되지 않지만,
    거둔 뒤의 같은 수는 남의 프로세스일 수 있다."""
    with session.lock:
        if session.reaped:
            return
        try:
            os.killpg(os.getpgid(session.pid), sig)
        except OSError:
            pass  # 그새 그룹이 통째로 나갔다 — 보내려던 것이 이미 이뤄진 상태다


def _await_exit(session: _Session, limit: float) -> bool:
    deadline = time.monotonic() + limit
    while True:
        if _reap(session):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def close_session(session: _Session) -> None:
    """SIGTERM 으로 부탁하고, 안 나가면 SIGKILL 로 끝낸다. 돌아올 때 자식은 거둬져 있다."""
    session.closing = True
    _signal(session, signal.SIGTERM)
    if not _await_exit(session, _TERM_GRACE):
        _signal(session, signal.SIGKILL)
        _await_exit(session, _KILL_GRACE)
    thread = session.thread
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=_TICK * 3)
    session.finish()


def _prune() -> None:
    """끝난 지 오래된 세션을 등록부에서 뺀다 — 창이 안 닫아도 목록이 자라지 않는다."""
    now = time.time()
    with _REGISTRY_LOCK:
        for sid in [s.id for s in _SESSIONS.values() if not s.alive and now - s.ended > _DEAD_GRACE]:
            _SESSIONS.pop(sid, None)


# ── 접근 검사 ─────────────────────────────────────────────────────────────────


def _supported() -> tuple[int, str, bytes] | None:
    """POSIX 가 아니면 그 이유를 낸다. 통과하면 None."""
    if os.name == "nt":
        return loopback.api_error(
            501,
            "terminal_unsupported",
            "이 운영체제에서는 창 안의 터미널을 못 열어요 — PTY 가 POSIX 전용이에요",
            "Windows Terminal 이나 PowerShell 을 따로 열어서 같은 명령을 쓰세요",
        )
    return None


def _resolve(sid: str, token: str) -> tuple[_Session | None, tuple[int, str, bytes] | None]:
    """id 와 토큰이 함께 맞아야 세션을 돌려준다."""
    with _REGISTRY_LOCK:
        session = _SESSIONS.get(sid)
    if session is None:
        return None, loopback.api_error(
            404, "terminal_unknown_session", "그 터미널은 없어요", "창에서 터미널을 새로 열어 주세요"
        )
    # `compare_digest` 는 비ASCII 문자열을 받지 않는다 — 토큰은 우리가 낸 urlsafe 값뿐이라
    # 그 밖의 것은 그 자리에서 틀린 값이다.
    if not token or not token.isascii() or not secrets.compare_digest(session.token, token):
        return None, loopback.api_error(
            403, "terminal_denied", "터미널 토큰이 맞지 않아요", "이 터미널을 연 창에서만 붙을 수 있어요"
        )
    return session, None


def _confined_cwd(raw: object, root: str) -> tuple[str, str]:
    """뿌리 안의 실재하는 디렉터리만 돌려준다 — `(경로, 오류)`.

    `realpath` 로 비교하는 이유는 `_confine` 과 같다: `..` 도, 밖을 가리키는 심링크도 글자
    검사로는 안 잡힌다. 창은 루프백이지만 아무 디렉터리나 여는 문이 되면 안 된다."""
    base = os.path.realpath(root)
    text = str(raw or "").strip()
    if not text:
        return base, ""
    if "\x00" in text:
        return "", "경로에 쓸 수 없는 글자가 있어요"
    target = os.path.realpath(os.path.join(base, os.path.expanduser(text)))
    if target != base and not target.startswith(base + os.sep):
        return "", "작업 공간 밖은 열 수 없어요"
    if not os.path.isdir(target):
        return "", "그 자리에 디렉터리가 없어요"
    return target, ""


def _dims(payload: dict, fallback: tuple[int, int]) -> tuple[int, int] | None:
    """`(칸, 줄)` 또는 None. **없는 값과 0 은 다르다** — `or` 로 기본값을 대면 0칸짜리
    요청이 조용히 80칸이 되고, 창은 자기가 보낸 크기로 그린다."""
    raw = (payload.get("cols"), payload.get("rows"))
    try:
        cols = fallback[0] if raw[0] is None else int(raw[0])
        rows = fallback[1] if raw[1] is None else int(raw[1])
    except TypeError, ValueError:
        return None
    if not (1 <= cols <= _MAX_COLS and 1 <= rows <= _MAX_ROWS):
        return None
    return cols, rows


def _shell() -> str:
    """자식이 exec 할 **절대 경로**. `execve` 는 PATH 를 안 뒤지고, 뒤지는 일은 fork 뒤의
    자식이 할 일이 아니다(위 `_spawn` 주석)."""
    candidate = os.environ.get("SHELL") or ""
    return (candidate and shutil.which(candidate)) or shutil.which("sh") or "/bin/sh"


# ── 창구 ──────────────────────────────────────────────────────────────────────


def dispatch(method: str, path: str, params: dict[str, list[str]], root: str) -> tuple[int, str, bytes]:
    """읽기 갈래. 흘려보내는 `stream` 은 여기까지 오지 않는다(핸들러가 앞에서 가른다)."""
    if method != "GET":
        return loopback.method_not_allowed()
    unsupported = _supported()
    if unsupported:
        return unsupported
    _prune()
    if path == "/api/terminal/sessions":
        with _REGISTRY_LOCK:
            rows = [session.row() for session in _SESSIONS.values()]
        return loopback.json_body(200, {"sessions": rows, "limit": _MAX_SESSIONS})
    return loopback.not_found()


def dispatch_post(path: str, payload: dict, root: str) -> tuple[int, str, bytes]:
    """열고, 넣고, 크기를 바꾸고, 닫는다."""
    unsupported = _supported()
    if unsupported:
        return unsupported
    _prune()
    if path == "/api/terminal/open":
        return _open(payload, root)
    session, refused = _resolve(str(payload.get("id") or ""), str(payload.get("token") or ""))
    if refused:
        return refused
    assert session is not None
    if path == "/api/terminal/input":
        return _input(session, payload)
    if path == "/api/terminal/resize":
        return _resize_session(session, payload)
    if path == "/api/terminal/close":
        close_session(session)
        with _REGISTRY_LOCK:
            _SESSIONS.pop(session.id, None)
        return loopback.json_body(200, {"ok": True, "status": session.status})
    return loopback.not_found()


def _open(payload: dict, root: str) -> tuple[int, str, bytes]:
    dims = _dims(payload, (80, 24))
    if dims is None:
        return loopback.api_error(
            400,
            "terminal_bad_size",
            f"크기는 1~{_MAX_COLS}칸 · 1~{_MAX_ROWS}줄 안이어야 해요",
            "창 크기를 다시 재서 보내 주세요",
        )
    cwd, error = _confined_cwd(payload.get("cwd"), root)
    if error:
        return loopback.api_error(400, "terminal_cwd_outside_root", error, "지금 작업 공간 안의 자리를 골라 주세요")
    with _REGISTRY_LOCK:
        if len([s for s in _SESSIONS.values() if s.alive]) >= _MAX_SESSIONS:
            return loopback.api_error(
                429,
                "terminal_limit",
                f"터미널은 한 번에 {_MAX_SESSIONS}개까지 열려요",
                "쓰지 않는 터미널을 닫고 다시 열어 주세요",
            )
    cols, rows = dims
    shell = _shell()
    try:
        pid, fd = _spawn(cwd, shell, cols, rows)
    except OSError as exc:
        return loopback.api_error(500, "terminal_spawn_failed", f"셸을 띄우지 못했어요: {exc}", "다시 시도해 주세요")
    session = _Session(secrets.token_urlsafe(12), secrets.token_urlsafe(24), pid, fd, cwd, shell, cols, rows)
    session.thread = threading.Thread(target=_pump, args=(session,), name=f"asgard-pty-{session.id}", daemon=True)
    with _REGISTRY_LOCK:
        _SESSIONS[session.id] = session
    session.thread.start()
    return loopback.json_body(200, {"id": session.id, "token": session.token, **session.row()})


def _input(session: _Session, payload: dict) -> tuple[int, str, bytes]:
    if not session.alive:
        return loopback.api_error(409, "terminal_closed", "그 터미널은 이미 끝났어요", "새 터미널을 열어 주세요")
    data = str(payload.get("data") or "")
    if not data:
        return loopback.json_body(200, {"ok": True})
    view = memoryview(data.encode("utf-8"))
    try:
        # 마스터 fd 는 블로킹이라 한 번에 다 안 나갈 수 있다(파이프 버퍼가 찬 경우).
        # 남은 만큼 이어 쓴다 — 잘린 입력은 셸에서 엉뚱한 명령이 된다.
        while view:
            view = view[os.write(session.fd, view) :]
    except OSError as exc:
        return loopback.api_error(409, "terminal_closed", f"터미널에 쓰지 못했어요: {exc}", "새 터미널을 열어 주세요")
    return loopback.json_body(200, {"ok": True})


def _resize_session(session: _Session, payload: dict) -> tuple[int, str, bytes]:
    dims = _dims(payload, (session.cols, session.rows))
    if dims is None:
        return loopback.api_error(
            400,
            "terminal_bad_size",
            f"크기는 1~{_MAX_COLS}칸 · 1~{_MAX_ROWS}줄 안이어야 해요",
            "창 크기를 다시 재서 보내 주세요",
        )
    cols, rows = dims
    try:
        _resize(session.fd, cols, rows)
    except OSError as exc:
        return loopback.api_error(409, "terminal_closed", f"크기를 못 바꿨어요: {exc}", "새 터미널을 열어 주세요")
    session.cols, session.rows = cols, rows
    return loopback.json_body(200, {"ok": True, "cols": cols, "rows": rows})


# ── 흘려보내기 ────────────────────────────────────────────────────────────────


def _frame(seq: int, text: str) -> bytes:
    return b"data: " + json.dumps({"seq": seq, "data": text}, ensure_ascii=False).encode("utf-8") + b"\n\n"


def stream(handler, params: dict[str, list[str]]) -> None:
    """SSE 로 출력을 흘려보낸다. 핸들러를 통째로 받으므로 바이트를 돌려주지 않는다.

    `?after=<seq>` 로 이어 붙을 수 있다 — 창이 끊겼다 다시 붙을 때 이미 그린 것을 두 번
    그리지 않는 자리다. 없으면 버퍼에 남은 것부터 전부 보낸다(창이 붙기 전에 뜬 프롬프트)."""
    unsupported = _supported()
    if unsupported:
        handler.send_guarded(*unsupported)
        return
    sid = (params.get("id") or [""])[0]
    session, refused = _resolve(sid, (params.get("token") or [""])[0])
    if refused:
        handler.send_guarded(*refused)
        return
    assert session is not None
    try:
        cursor = int((params.get("after") or ["0"])[0])
    except ValueError:
        cursor = 0

    handler.open_stream(_SSE_TYPE)
    deadline = time.monotonic() + _IDLE_LIMIT
    while True:
        with session.cond:
            pending = session.pending(cursor)
            if not pending and session.alive:
                session.cond.wait(_HEARTBEAT)
                pending = session.pending(cursor)
            ended = not session.alive and not pending
        if pending:
            deadline = time.monotonic() + _IDLE_LIMIT
            for seq, text in pending:
                if not handler.write_chunk(_frame(seq, text)):
                    return  # 창이 닫혔다 — 사고가 아니다
                cursor = seq
            continue
        if ended:
            handler.write_chunk(b"event: exit\ndata: " + json.dumps({"status": session.status}).encode() + b"\n\n")
            break
        # 아무것도 없을 때 보내는 주석 — 창이 살아 있는지 이걸로 안다.
        if not handler.write_chunk(b": ping\n\n"):
            return
        if time.monotonic() > deadline:
            break
    handler.close_stream()
