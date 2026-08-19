"""로컬 창들의 공통 접근 검사 — 루프백 경계와 응답 헤더를 **한 곳에만** 둔다.

이 저장소는 로컬 HTTP 표면을 셋 배송한다(Studio · 기획 · 메모리). 셋 다 같은 것을 막아야
한다: 루프백이 아닌 Host, 남의 출처, 스니핑, 리퍼러 누수. 그런데 여태 셋이 각자 적고
있었고, 그래서 **갈라졌다** — 실측:

  · `Referrer-Policy`는 Studio·기획에만 있었다 (메모리 창은 경로를 밖으로 흘릴 수 있었다)
  · `frame-src`·`base-uri`·`form-action`은 Studio 에만 있었다
  · 같은 `host_allowed`가 세 벌, 같은 `_LOOPBACK_HOSTS`가 세 벌

보안 경계가 세 벌이면 고칠 때도 세 번 고쳐야 하고, 언젠가 두 번만 고친다. 그때 어느 창이
뚫렸는지는 아무도 모른다 — 세 벌이 다르다는 사실 자체가 이미 아무도 안 보고 있었다는 증거다.

여기 있는 것은 계약뿐이다. 무엇을 낼지는 각 표면이 정하고(`dispatch`), 어떻게 낼지만
이 모듈이 진다.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

# 창이 실제로 쓰는 것만 연다. 나머지는 전부 닫는다 — 특히 `frame-src`(클릭재킹)·
# `base-uri`(상대경로 탈취)·`form-action`(폼 유출)은 셋 다 걸어야 한다.
#
# `'self'` 가 script-src·style-src 에 있는 이유: 창이 더는 자립형 단일 파일이 아니다. 세 화면이
# 토큰과 기본 컴포넌트를 한 곳에만 두려면 그것이 파일이어야 하고, 터미널의 xterm.js 는 283KB 라
# 페이지마다 인라인으로 실을 것이 아니다. 둘 다 같은 출처(`/asset/...`)에서만 온다.
# `'unsafe-inline'` 은 아직 남는다 — studio.html 의 인라인 블록이 모듈로 다 빠지기 전까지는
# 지우면 화면이 죽는다. 그것이 빠지는 날 이 두 낱말도 같이 지운다.
CSP = (
    "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self'; "
    "frame-ancestors 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'"
)
SECURITY_HEADERS = (
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy", CSP),
)

JSON_TYPE = "application/json; charset=utf-8"
TEXT_TYPE = "text/plain; charset=utf-8"
HTML_TYPE = "text/html; charset=utf-8"


def host_allowed(host_header: str | None) -> bool:
    """DNS 리바인딩 방어 — Host의 호스트명이 루프백이어야 한다.

    읽기 전용 표면이라도 막는다: 목록·스니펫·경로에 사적인 것이 들어간다. 외부 도메인이
    사용자의 브라우저를 통해 127.0.0.1을 읽는 길을 여기서 끊는다."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):  # IPv6 리터럴 [::1]:port
        host = host.split("]")[0] + "]"
    elif ":" in host:  # host:port
        host = host.rsplit(":", 1)[0]
    return host in LOOPBACK_HOSTS


def origin_allowed(origin: str | None) -> bool:
    """Origin이 있으면 그것도 루프백 **평문**이어야 한다 — 없으면(동일 출처 요청) 통과.

    `https`를 막는 이유: 이 창들은 전부 평문 `ThreadingHTTPServer` 다. 그러니 https 출처는
    **우리 페이지일 수가 없다**. 합치기 전 두 표면이 갈려 있었고(Studio는 http만, 기획은
    https도 받았다), 그럴 때 고를 것은 느슨한 쪽이 아니라 참인 쪽이다."""
    if not origin:
        return True
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    return parts.scheme == "http" and host_allowed(parts.netloc)


def json_body(status: int, payload: object) -> tuple[int, str, bytes]:
    """세 표면이 같은 모양으로 낸다 — `(status, content-type, bytes)`."""
    return status, JSON_TYPE, json.dumps(payload, ensure_ascii=False).encode("utf-8")


def api_error(
    status: int, code: str, message: str, remedy: str = "", detail: dict | None = None
) -> tuple[int, str, bytes]:
    """오류에도 **코드**를 넣어 준다 — 화면이 문구가 아니라 코드로 분기할 수 있어야 한다.

    `remedy`는 뒤에 붙은 칸이다: 코드는 화면이 분기하는 데 쓰지만, 사용자에게 보여 줄
    "그래서 뭘 하면 되는가"는 여태 어디에도 없었다. 빈 값이면 넣지 않는다."""
    payload: dict = {"code": code, "message": message}
    if remedy:
        payload["remedy"] = remedy
    if detail:
        payload["detail"] = detail
    return json_body(status, {"error": payload})


def error_result(exc: BaseException, *, surface: str = "", root: str = "", where: str = "") -> tuple[int, str, bytes]:
    """예외 하나 → HTTP 응답 하나. **경계마다 매핑을 다시 적지 않는다.**

    여태 도메인 오류를 상태 코드로 옮기는 표가 표면마다 한 묶음씩 있었다(`except TicketError →
    400`, `except StoreError → 503` …). 표가 여러 벌이면 새 오류가 생겼을 때 어느 표를 빠뜨렸는지
    아무도 모르고, 빠뜨린 표면은 그 오류를 500으로 낸다 — 사용자가 고칠 수 있는 잘못이 서버
    잘못으로 둔갑한다. 이제 상태 코드는 **예외 자신이** 안다(`AsgardError.http_status`).

    모르는 예외는 500으로 내되 **흔적을 남긴다**. 여기가 여태 사고가 사라지던 자리다:
    `error: KeyError` 한 줄만 나가고 트레이스백은 버려져서, 어느 줄이었는지 알 길이 없었다."""
    from .. import errors

    err = errors.coerce(exc)
    if err.http_status >= 500 and root:
        errors.record(root, err, surface=surface or "http", where=where)
    return api_error(err.http_status, err.code, err.message, err.remedy, err.detail or None)


def not_found() -> tuple[int, str, bytes]:
    return 404, TEXT_TYPE, b"not found"


def method_not_allowed() -> tuple[int, str, bytes]:
    return 405, TEXT_TYPE, b"method not allowed"


class LoopbackHandler(BaseHTTPRequestHandler):
    """세 창이 공유하는 응답 형태. 라우팅은 각자 `dispatch`로 붙인다.

    상속으로 묶는 이유는 코드를 아끼려는 게 아니다 — **헤더를 빠뜨릴 자리를 없애려는** 것이다.
    새 표면을 하나 더 만들 사람이 이 클래스를 상속하면, 무엇을 걸어야 하는지 몰라도 걸린다."""

    def send_guarded(self, status: int, ctype: str, body: bytes, head_only: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def open_stream(self, ctype: str) -> None:
        """길이를 모르는 응답을 연다 — 헤더만 보내고 몸통은 `write_chunk` 가 이어 붙인다.

        `send_guarded` 는 `Content-Length` 를 박고 한 번에 쓴다. 터미널 출력은 길이를 미리 알 수
        없으므로 그 계약으로는 못 낸다. 청크 전송으로 바꾸되 보안 헤더는 그대로 건다 — 스트리밍
        응답만 헤더가 빠지면 그 자리가 곧 구멍이다.

        HTTP/1.1 이어야 청크가 성립한다. `BaseHTTPRequestHandler` 의 기본은 1.0 이라
        이 클래스가 올려 둔다(아래 `protocol_version`)."""
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Transfer-Encoding", "chunked")
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        self.end_headers()

    def write_chunk(self, body: bytes) -> bool:
        """청크 하나. 창이 닫혀 끊기면 False — 부르는 쪽의 정상 종료 신호다."""
        try:
            self.wfile.write(b"%x\r\n" % len(body) + body + b"\r\n")
            self.wfile.flush()
        except BrokenPipeError, ConnectionResetError, TimeoutError:
            return False
        return True

    def close_stream(self) -> None:
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except BrokenPipeError, ConnectionResetError, TimeoutError:
            return

    def guard_host(self, head_only: bool = False) -> bool:
        """루프백이 아니면 여기서 끝낸다. 통과하면 True."""
        if host_allowed(self.headers.get("Host")):
            return True
        self.send_guarded(403, TEXT_TYPE, b"forbidden host", head_only)
        return False

    def log_message(self, format: str, *args: object) -> None:
        return  # 요청 로그 억제 — 창은 서버 로그를 보여 주는 자리가 아니다


class LoopbackServer(ThreadingHTTPServer):
    """세 창이 같이 쓰는 소켓 — 끊긴 연결을 사고로 찍지 않는다.

    Ctrl-C로 창을 닫으면 브라우저가 붙잡고 있던 요청이 그 자리에서 끊긴다. 기본
    `handle_error`는 그것을 트레이스백으로 찍어서, 정상 종료가 화면에서 고장으로 보였다
    (Windows 실측 — `Exception occurred during processing of request from ('127.0.0.1', …)`가
    `stopped` 바로 뒤에 붙어 나왔다). 끊긴 연결만 삼킨다 — 나머지 예외는 그대로 올린다.
    """

    def handle_error(self, request: object, client_address: object) -> None:
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)  # ty: ignore[invalid-argument-type]  (기반 별칭은 비공개다)
