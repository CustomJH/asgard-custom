"""로컬 창들의 공통 문지기 — 루프백 경계와 응답 헤더를 **한 벌만** 둔다.

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
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

# 창이 실제로 쓰는 것만 연다. 인라인 style/script는 이 저장소의 배송 형태(자립형 단일 파일)
# 라 필요하고, 나머지는 전부 닫는다 — 특히 `frame-src`(클릭재킹)·`base-uri`(상대경로 탈취)·
# `form-action`(폼 유출)은 셋 다 걸어야 한다. 여태 Studio 에만 걸려 있었다.
CSP = (
    "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
    "script-src 'unsafe-inline'; connect-src 'self'; "
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

    읽기 전용 표면이라도 막는다: 목록·스니펫·경로에 사적인 것이 실린다. 외부 도메인이
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


def api_error(status: int, code: str, message: str) -> tuple[int, str, bytes]:
    """오류에도 **코드**를 실어 준다 — 화면이 문구가 아니라 코드로 분기할 수 있어야 한다."""
    return json_body(status, {"error": {"code": code, "message": message}})


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

    def guard_host(self, head_only: bool = False) -> bool:
        """루프백이 아니면 여기서 끝낸다. 통과하면 True."""
        if host_allowed(self.headers.get("Host")):
            return True
        self.send_guarded(403, TEXT_TYPE, b"forbidden host", head_only)
        return False

    def log_message(self, format: str, *args: object) -> None:
        return  # 요청 로그 억제 — 창은 서버 로그를 보여 주는 자리가 아니다
