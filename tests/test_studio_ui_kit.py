"""공용 자산 전달 계약 — 창이 파일로 된 토큰·컴포넌트를 읽을 수 있는가, 그리고 그것뿐인가.

세 화면이 디자인 토큰을 한 곳에서만 읽으려면 그것이 파일이어야 하고, 파일이면 서버가 내줘야
한다. 그 문을 여는 순간 생기는 위험이 이 파일이 지키는 것이다: `src/asgard/assets/` 는 패키지
**안에** 있으므로, 이름을 그대로 이어 붙이는 구현은 `../commands/loopback.py` 를 그대로 내준다.

실행: uv run pytest tests/test_studio_ui_kit.py
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from asgard.commands import loopback
from asgard.commands.studio import assets, server


class CspTest(unittest.TestCase):
    """CSP 는 넓히되, 넓힌 만큼만 넓혔는가."""

    def test_same_origin_scripts_and_styles_are_allowed(self):
        """`'self'` 가 없으면 `<script src="/asset/…">` 가 브라우저에서 차단된다."""
        self.assertIn("script-src 'self'", loopback.CSP)
        self.assertIn("style-src 'self'", loopback.CSP)

    def test_the_closed_defaults_stay_closed(self):
        for directive in (
            "default-src 'none'",
            "frame-ancestors 'none'",
            "frame-src 'none'",
            "base-uri 'none'",
            "form-action 'none'",
        ):
            self.assertIn(directive, loopback.CSP)

    def test_no_remote_origin_is_named(self):
        """벤더링한 라이브러리는 우리 출처에서만 온다 — CDN 을 여는 순간 자립 배송이 끝난다."""
        for scheme in ("http://", "https://", "*"):
            self.assertNotIn(scheme, loopback.CSP)


class AssetGuardTest(unittest.TestCase):
    """경로 검사 — 자산 밖으로 나가는 길이 있는가."""

    def _serve(self, rel: str):
        return assets.serve(rel)

    def test_escapes_are_refused(self):
        for rel in (
            "ui/../../commands/loopback.py",
            "ui/../../../etc/hosts",
            "../commands/loopback.py",
            "/etc/hosts",
            "ui/..%2f..%2fcommands/loopback.py",
            "ui\\..\\..\\commands\\loopback.py",
            "ui/./../../pyproject.toml",
        ):
            status, _, _ = self._serve(rel)
            self.assertEqual(status, 404, f"escaped through: {rel!r}")

    def test_only_declared_prefixes_open(self):
        for rel in ("studio.html", "app-icon.png", "k6_kit/lib/asgard.js", "elsewhere/thing.js"):
            status, _, _ = self._serve(rel)
            self.assertEqual(status, 404, f"served outside the declared prefixes: {rel!r}")

    def test_only_declared_extensions_open(self):
        for rel in ("ui/x.py", "ui/x.json", "ui/x.md", "ui/x.html", "ui/x"):
            status, _, _ = self._serve(rel)
            self.assertEqual(status, 404, f"served a type we do not deliver: {rel!r}")

    def test_the_delivered_types_are_exactly_what_a_page_needs(self):
        """확장자 목록은 넓히기 쉽고, 넓히면 아무도 안 본다 — 소스가 나가는 것이 그 끝이다.

        경로 검사와 달리 이 목록은 변이에 안 걸린다(`ui/`·`js/`·`vendor/` 아래에 `.py` 가 없어서
        `.py` 를 더해도 시험이 전부 초록이다). 그래서 목록 자체를 못박는다."""
        self.assertEqual(set(assets._TYPES), {".css", ".js", ".map", ".svg", ".png", ".woff2"})

    def test_hidden_files_are_refused(self):
        for rel in ("ui/.hidden.css", "vendor/.git/config.js"):
            self.assertEqual(self._serve(rel)[0], 404)

    def test_refusal_and_absence_look_identical(self):
        """이유를 나누면 그 차이가 자산 밖 파일의 존재를 알려 주는 신호가 된다."""
        refused = self._serve("ui/../../commands/loopback.py")
        absent = self._serve("ui/there-is-no-such-file.css")
        self.assertEqual(refused, absent)


class AssetDeliveryTest(unittest.TestCase):
    """규칙 안의 파일은 실제로 나가는가 — 뿌리를 임시 디렉터리로 바꿔 검사한다.

    패키지 안에 시험용 파일을 쓰지 않는 이유는, 그 파일을 소유한 단위가 따로 있어서다."""

    def _with_root(self, tmp: str):
        return mock.patch.object(assets, "_root", lambda: os.path.realpath(tmp))

    def test_declared_types_are_delivered_with_their_content_type(self):
        cases = (
            ("ui/tokens.css", b":root{--ink:#0D0D0D}", "text/css; charset=utf-8"),
            ("js/map.js", b"function draw(){}", "text/javascript; charset=utf-8"),
            ("vendor/xterm/xterm.js", b"!function(){}();", "text/javascript; charset=utf-8"),
        )
        with tempfile.TemporaryDirectory() as tmp, self._with_root(tmp):
            for rel, body, ctype in cases:
                path = os.path.join(tmp, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(body)
                self.assertEqual(assets.serve(rel), (200, ctype, body))

    def test_a_symlink_out_of_the_tree_is_refused(self):
        """글자 검사만으로는 못 잡는 자리 — 이름은 규칙 안인데 실제 파일이 밖이다."""
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            target = os.path.join(outside, "outside.css")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("taken")
            os.makedirs(os.path.join(tmp, "ui"), exist_ok=True)
            try:
                os.symlink(target, os.path.join(tmp, "ui", "linked.css"))
            except OSError, NotImplementedError:
                self.skipTest("이 플랫폼에서 심볼릭 링크를 만들 수 없어요")
            with self._with_root(tmp):
                self.assertEqual(assets.serve("ui/linked.css")[0], 404)


class ServedSurfaceTest(unittest.TestCase):
    """실제 서버를 띄워 — 헤더가 붙는가, 옛 그림 경로가 살아 있는가."""

    def _serve_forever(self, root: str):
        httpd = server._bind("127.0.0.1", 0, root)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd, httpd.server_address[1]

    def test_named_image_routes_still_answer(self):
        """자산 경로를 일반화하면서 이름이 정해진 셋을 덮지 않았는가."""
        with tempfile.TemporaryDirectory() as root:
            httpd, port = self._serve_forever(root)
            try:
                for path in ("/asset/logo", "/asset/mark", "/asset/app-icon", "/favicon.ico"):
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                        self.assertEqual(response.status, 200, path)
                        self.assertEqual(response.headers["Content-Type"], "image/png", path)
            finally:
                httpd.shutdown()

    def test_traversal_over_http_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            httpd, port = self._serve_forever(root)
            try:
                for path in ("/asset/ui/../../commands/loopback.py", "/asset/../pyproject.toml"):
                    with self.assertRaises(urllib.error.HTTPError, msg=path) as refused:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5)
                    self.assertEqual(refused.exception.code, 404, path)
            finally:
                httpd.shutdown()

    def test_security_headers_ride_on_asset_responses(self):
        with tempfile.TemporaryDirectory() as root:
            httpd, port = self._serve_forever(root)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/asset/logo", timeout=5) as response:
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                    self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
            finally:
                httpd.shutdown()


class KeepAliveTest(unittest.TestCase):
    """연결을 이어 쓰기 시작하면서 생긴 위험 — 한 요청이 남긴 바이트가 다음 요청이 되는가.

    HTTP/1.0 일 때는 응답 뒤 소켓이 닫혀서 안 읽은 몸통이 그냥 버려졌다. 터미널 출력을 흘리려고
    1.1 로 올린 순간 그 바이트는 **다음 요청의 첫 줄**로 파싱된다 — 거절당한 요청의 몸통이
    다음 명령이 된다. 그래서 몸통은 읽거나 끊거나 해야 한다.

    소켓을 직접 쓰는 이유는 `urllib` 이 연결을 이어 쓰지 않아 이 사고를 재현하지 못해서다."""

    def _read_all(self, sock) -> bytes:
        """소켓이 조용해질 때까지 읽는다. 서버가 연결을 이어 두면 끝은 침묵으로만 온다."""
        sock.settimeout(3)
        seen = b""
        try:
            while len(seen) < 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    return seen
                seen += chunk
        except TimeoutError, OSError:
            return seen
        return seen

    def _talk(self, root: str, raw: bytes) -> bytes:
        import socket

        httpd = server._bind("127.0.0.1", 0, root)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
                sock.sendall(raw)
                return self._read_all(sock)
        finally:
            httpd.shutdown()

    def test_a_refused_body_does_not_become_the_next_request(self):
        """403 이 난 POST 의 몸통이 소켓에 남으면 그 다음 줄이 요청으로 읽힌다."""
        with tempfile.TemporaryDirectory() as root:
            # 몸통 자체를 '다음 요청'처럼 생긴 글자로 채운다 — 안 제거하면 이것이 실행된다.
            smuggled = b"GET /asset/logo HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
            raw = (
                b"POST /api/tasks HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Origin: http://evil.example\r\nContent-Type: application/json\r\n"
                b"Content-Length: " + str(len(smuggled)).encode() + b"\r\n\r\n" + smuggled
            )
            seen = self._talk(root, raw)
            self.assertIn(b"403", seen.split(b"\r\n")[0])
            # 응답이 하나여야 한다. 둘이면 밀항한 줄이 두 번째 요청으로 실행된 것이다.
            self.assertEqual(seen.count(b"HTTP/1.1 "), 1, seen[:400])
            self.assertNotIn(b"image/png", seen)

    def test_an_oversized_body_is_refused_instead_of_truncated(self):
        """잘라 읽으면 나머지가 소켓에 남는다 — 자르지 말고 끊어야 한다."""
        with tempfile.TemporaryDirectory() as root:
            body = b'{"x":"' + b"a" * 300_000 + b'"}'
            raw = (
                b"POST /api/tasks HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"X-Asgard-Studio: 1\r\nContent-Type: application/json\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
            )
            seen = self._talk(root, raw)
            self.assertIn(b"413", seen.split(b"\r\n")[0], seen[:200])
            self.assertEqual(seen.count(b"HTTP/1.1 "), 1, seen[:400])

    def test_a_chunked_body_cannot_ride_into_the_next_request(self):
        """`Content-Length` 갈래만 막으면 헤더 하나 바꿔서 같은 구멍으로 들어온다.

        청크로 오는 몸통은 길이가 헤더에 없어 소켓에서 제거할 수가 없다. 그래서 연결을 끊는다.

        몸통에 **청크 틀을 쓰지 않는** 것이 요점이다. 크기 줄(`2c\\r\\n`)을 앞에 붙이면 그 줄이
        먼저 요청 줄 자리에 와서 어차피 깨지고, 그러면 이 시험은 고친 코드와 안 고친 코드를
        구분하지 못한다(실제로 처음엔 그렇게 썼다가 변이 시험에서 걸렸다). 서버는 청크를 읽지
        않으므로 공격자는 틀을 지킬 이유가 없다 — 요청 줄을 그대로 넣는다."""
        with tempfile.TemporaryDirectory() as root:
            raw = (
                b"POST /api/tasks HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"X-Asgard-Studio: 1\r\nContent-Type: application/json\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n"
                b"GET /asset/logo HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
            )
            seen = self._talk(root, raw)
            self.assertEqual(seen.count(b"HTTP/1.1 "), 1, seen[:400])
            self.assertNotIn(b"image/png", seen)

    def test_every_way_of_muddling_the_body_length_closes_the_connection(self):
        """나쁜 모양을 하나씩 세어 막다가 넷을 놓쳤다 — 그래서 그 넷을 전부 여기 못박는다.

        판정자가 뚫은 자리들이다. 각각 다른 이유로 통과했었다: 중복 선언은 `.get()` 이 첫 값만
        읽어서, 음수는 `max(0, …)` 가 0 으로 만들어서, 콜론 앞 공백은 `email` 파서가 그 줄에서
        머리 읽기를 멈춰 헤더 이름 자체가 사라져서, 몸통 달린 `GET` 은 읽기 경로가 길이를
        아예 안 봐서. 뒤엣것 둘은 이름을 맞춰 보는 검사로는 영영 안 잡힌다."""
        smuggle = b"GET /asset/logo HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
        cases = {
            "중복 Content-Length": (b"POST /api/tasks", b"Content-Length: 0\r\nContent-Length: 45\r\n"),
            "음수 Content-Length": (b"POST /api/tasks", b"Content-Length: -10\r\n"),
            "16진수 Content-Length": (b"POST /api/tasks", b"Content-Length: 0x2d\r\n"),
            "콜론 앞 공백 TE": (b"POST /api/tasks", b"Transfer-Encoding : chunked\r\n"),
            "소문자 TE": (b"POST /api/tasks", b"transfer-encoding: chunked\r\n"),
            "몸통 달린 GET": (b"GET /health", b"Content-Length: 45\r\n"),
            # `isdigit()` 은 참을 내는데 `int()` 는 거절하는 글자다. 검사를 `isdecimal()` 로
            # 안 바꾸면 여기서 `ValueError` 가 새어 나가 응답 없이 연결이 죽는다.
            "위첨자 Content-Length": (b"POST /api/tasks", "Content-Length: ²\r\n".encode("latin-1")),
        }
        with tempfile.TemporaryDirectory() as root:
            for name, (line, extra) in cases.items():
                raw = (
                    line + b" HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Asgard-Studio: 1\r\n"
                    b"Content-Type: application/json\r\n" + extra + b"\r\n" + smuggle
                )
                seen = self._talk(root, raw)
                self.assertNotIn(b"image/png", seen, f"{name} — 밀항한 요청이 실행됐어요")
                self.assertEqual(seen.count(b"HTTP/1.1 "), 1, f"{name} — 응답이 둘이에요")

    def test_an_ordinary_pair_still_rides_one_connection(self):
        """고친 것이 이어 쓰기 자체를 죽이지는 않았는가 — 두 요청, 두 응답."""
        with tempfile.TemporaryDirectory() as root:
            raw = (
                b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
                b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
            )
            seen = self._talk(root, raw)
            self.assertEqual(seen.count(b"HTTP/1.1 200"), 2, seen[:400])


class StreamPrimitiveTest(unittest.TestCase):
    """길이를 모르는 응답 — 헤더 계약만 검사한다(터미널 자체는 자기 시험이 있다)."""

    def test_the_handler_offers_a_streaming_path(self):
        for name in ("open_stream", "write_chunk", "close_stream"):
            self.assertTrue(hasattr(loopback.LoopbackHandler, name), name)

    def test_chunked_transfer_needs_http_1_1(self):
        """1.0 으로는 청크가 성립하지 않는다 — 이 한 줄이 빠지면 터미널이 조용히 안 흐른다."""
        self.assertEqual(server._Handler.protocol_version, "HTTP/1.1")

    def test_a_broken_pipe_is_reported_not_raised(self):
        """창을 닫으면 쓰기가 끊긴다. 그것은 사고가 아니라 정상 종료 신호다."""

        class Dead:
            def write(self, _):
                raise BrokenPipeError

            def flush(self):
                raise BrokenPipeError

        handler = loopback.LoopbackHandler.__new__(loopback.LoopbackHandler)
        handler.wfile = Dead()
        self.assertFalse(handler.write_chunk(b"x"))
        handler.close_stream()  # 던지지 않는다


if __name__ == "__main__":
    unittest.main()
