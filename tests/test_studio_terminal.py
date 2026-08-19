"""창 안의 터미널 — 진짜 셸을 띄워 끝에서 끝까지 확인한다.

여기서 못박는 것 넷:

  1. **정말 도는가** — 열고, 글자를 넣고, 그 결과가 스트림으로 돌아오는가. 셸이 되받아 찍는
     글자(터미널 에코)와 셸이 실행해서 낸 글자는 다르므로, 표식은 셸만 만들 수 있는 값
     (`$((6*7))` → `42`)으로 둔다.
  2. **토큰** — id 만 아는 쪽은 못 붙는다. 이게 없으면 이 창을 여는 아무 페이지나 남의 셸에 붙는다.
  3. **경계** — 뿌리 밖 `cwd` 는 거절한다.
  4. **뒷정리** — 닫은 뒤 자식이 거둬져 있는가. 안 거두면 여닫을 때마다 좀비가 쌓인다.
     이 프로세스가 곧 부모라, 안 거뒀으면 `waitpid` 가 그 좀비를 돌려준다.

PTY 는 POSIX 전용이라 그 갈래는 통째로 건너뛴다(`skipUnless` — 건너뛴 사실이 보고에 남는다).
Windows 갈래는 셸 없이 확인한다: `os.name` 을 바꿔 창구 전부가 501 을 내는지.

실행: uv run pytest tests/test_studio_terminal.py
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

from asgard.commands.studio import server, terminal

_POSIX = os.name != "nt"
_SKIP = "PTY 는 POSIX 전용이에요 — 이 플랫폼에서는 터미널 백엔드를 안 돌려요"


def _api(port: int, path: str, payload: dict | None = None) -> tuple[int, dict]:
    """창구 하나를 두드리고 `(상태, 본문)` 을 돌려준다."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as refused:
        raw = refused.read()
        try:
            return refused.code, json.loads(raw or b"{}")
        except ValueError:
            return refused.code, {"raw": raw.decode("utf-8", "replace")}


class TerminalSurfaceTest(unittest.TestCase):
    """POSIX 가 아닌 곳에서도 임포트는 살아 있어야 한다 — 그 갈래만 여기 둔다."""

    def test_the_posix_only_modules_are_not_imported_at_module_level(self):
        """최상위에서 `import pty` 를 하면 Windows 는 창 전체가 임포트에서 죽는다."""
        for name in ("pty", "fcntl", "termios"):
            self.assertNotIn(name, vars(terminal), f"{name} 이 모듈 전역에 올라와 있어요")

    def test_every_entrance_answers_501_on_windows(self):
        # `os.name` 은 이 프로세스 전체가 공유하는 값이라, 서버를 안 띄우는 이 시험에서만 바꾼다.
        with mock.patch.object(terminal.os, "name", "nt"):
            answers = [terminal.dispatch("GET", "/api/terminal/sessions", {}, os.getcwd())]
            for path in ("open", "input", "resize", "close"):
                answers.append(terminal.dispatch_post(f"/api/terminal/{path}", {}, os.getcwd()))
            for status, _, body in answers:
                payload = json.loads(body)["error"]
                self.assertEqual(status, 501)
                self.assertEqual(payload["code"], "terminal_unsupported")
                self.assertTrue(payload["remedy"], "무엇을 하면 되는지가 없어요")

    def test_the_stream_refuses_on_windows_without_opening_one(self):
        class Recorder:
            sent: tuple = ()
            opened = False

            def send_guarded(self, status, ctype, body, head_only=False):
                self.sent = (status, ctype, body)

            def open_stream(self, ctype):
                self.opened = True

        recorder = Recorder()
        with mock.patch.object(terminal.os, "name", "nt"):
            terminal.stream(recorder, {})
        self.assertEqual(recorder.sent[0], 501)
        self.assertFalse(recorder.opened, "열지 못할 스트림을 열었어요")


@unittest.skipUnless(_POSIX, _SKIP)
class ServedTerminalTest(unittest.TestCase):
    """실제 서버 + 실제 셸."""

    def setUp(self):
        # 이 시험은 **사람의 진짜 로그인 셸**을 띄운다 — 그게 제품 동작이라 바꾸지 않는다.
        # 대신 셸 설정이 시험을 좌우하지 않게 막는다. 실측(26-08-18): oh-my-zsh 가
        # "Would you like to update? [Y/n]" 를 띄운 날, 그 프롬프트가 시험이 보낸 첫 글자를
        # 먹어서 `echo …` 가 `cho …` 로 도착했고 `command not found: cho` 로 셋이 넘어갔다.
        # 개발자의 플러그인 갱신 주기에 따라 빨개지는 시험은 회귀를 말해 주지 못한다.
        self._env = mock.patch.dict(
            os.environ,
            {"DISABLE_AUTO_UPDATE": "true", "DISABLE_UPDATE_PROMPT": "true", "ZSH_DISABLE_COMPFIX": "true"},
        )
        self._env.start()
        self.addCleanup(self._env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.httpd = server._bind("127.0.0.1", 0, self.root)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        for session in list(terminal._SESSIONS.values()):
            terminal.close_session(session)
        terminal._SESSIONS.clear()
        self.httpd.shutdown()
        self._tmp.cleanup()

    # ── 도구 ──────────────────────────────────────────────────────────────────

    def _open(self, **payload) -> dict:
        status, body = _api(self.port, "/api/terminal/open", payload)
        self.assertEqual(status, 200, body)
        return body

    def _await(self, session: dict, needle: str, timeout: float = 12.0) -> str:
        """표식이 나올 때까지 스트림을 읽는다.

        입력을 먼저 넣고 나중에 붙어도 되는 이유는 세션이 자기 출력을 들고 있기 때문이다 —
        창이 붙기 전에 뜬 프롬프트를 잃지 않으려고 둔 버퍼가 여기서도 값을 한다."""
        query = urllib.parse.urlencode(_key(session))
        seen: list[str] = []
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/terminal/stream?{query}", timeout=timeout
            ) as response:
                _drain(response, needle, timeout, seen)
        except (TimeoutError, OSError) as exc:  # 표식이 안 오면 아래 assert 가 무엇이 왔는지 보여 준다
            seen.append(f"\n<끊김: {exc}>")
        return "".join(seen)

    # ── 시험 ──────────────────────────────────────────────────────────────────

    def test_a_shell_opens_and_its_output_comes_back_on_the_stream(self):
        session = self._open(cols=80, rows=24)
        self.assertTrue(session["token"])
        self.assertEqual(session["cwd"], self.root)
        status, _ = _api(self.port, "/api/terminal/input", {**_key(session), "data": "echo OK_$((6*7))\n"})
        self.assertEqual(status, 200)
        seen = self._await(session, "OK_42")
        # 셸이 되받아 찍은 글자에는 `$((6*7))` 가 그대로 있다 — `42` 는 셸만 만들 수 있다.
        self.assertIn("OK_42", seen, seen)

    def test_resize_reaches_the_shell(self):
        session = self._open(cols=80, rows=24)
        status, body = _api(self.port, "/api/terminal/resize", {**_key(session), "cols": 120, "rows": 40})
        self.assertEqual((status, body["cols"], body["rows"]), (200, 120, 40))
        _api(self.port, "/api/terminal/input", {**_key(session), "data": "stty size\n"})
        seen = self._await(session, "40 120")
        self.assertIn("40 120", seen, seen)

    def test_the_stream_refuses_a_missing_or_wrong_token(self):
        session = self._open()
        for query in (
            {"id": session["id"]},
            {"id": session["id"], "token": ""},
            {"id": session["id"], "token": "not-the-token"},
            {"id": session["id"], "token": "토큰"},
        ):
            url = f"http://127.0.0.1:{self.port}/api/terminal/stream?{urllib.parse.urlencode(query)}"
            with self.assertRaises(urllib.error.HTTPError, msg=str(query)) as refused:
                urllib.request.urlopen(url, timeout=10)
            self.assertEqual(refused.exception.code, 403, str(query))

    def test_input_refuses_a_wrong_token(self):
        session = self._open()
        status, body = _api(
            self.port, "/api/terminal/input", {"id": session["id"], "token": "not-the-token", "data": "whoami\n"}
        )
        self.assertEqual((status, body["error"]["code"]), (403, "terminal_denied"))

    def test_an_unknown_session_is_not_found(self):
        status, body = _api(self.port, "/api/terminal/input", {"id": "nope", "token": "nope", "data": "x"})
        self.assertEqual((status, body["error"]["code"]), (404, "terminal_unknown_session"))

    def test_a_cwd_outside_the_root_is_refused(self):
        os.makedirs(os.path.join(self.root, "inside"), exist_ok=True)
        for cwd in ("/etc", "..", "../..", os.path.expanduser("~")):
            status, body = _api(self.port, "/api/terminal/open", {"cwd": cwd})
            self.assertEqual(status, 400, f"{cwd}: {body}")
            self.assertEqual(body["error"]["code"], "terminal_cwd_outside_root", cwd)
        inside = self._open(cwd="inside")
        self.assertEqual(inside["cwd"], os.path.join(self.root, "inside"))

    def test_closing_leaves_no_zombie(self):
        session = self._open()
        pid = session["pid"]
        status, _ = _api(self.port, "/api/terminal/close", _key(session))
        self.assertEqual(status, 200)
        # 이 프로세스가 그 셸의 부모다. 안 거뒀으면 좀비가 남아 waitpid 가 그것을 돌려준다.
        with self.assertRaises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
        status, body = _api(self.port, "/api/terminal/sessions")
        self.assertNotIn(session["id"], [row["id"] for row in body["sessions"]])

    def test_a_shell_that_exits_on_its_own_ends_the_stream_and_is_reaped(self):
        """닫기 창구를 안 거치는 갈래 — 사용자가 `exit` 을 친다. 여기도 거둬야 좀비가 안 쌓인다."""
        session = self._open()
        _api(self.port, "/api/terminal/input", {**_key(session), "data": "exit\n"})
        query = urllib.parse.urlencode(_key(session))
        lines = []
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/api/terminal/stream?{query}", timeout=12
        ) as response:
            deadline = time.time() + 12
            while time.time() < deadline:
                line = response.readline()
                if not line:
                    break
                lines.append(line)
        self.assertIn(b"event: exit\n", lines, lines)
        # 끝 프레임은 거둔 **뒤에** 나간다 — 그러니 이 시점엔 이미 거둬져 있어야 한다.
        with self.assertRaises(ChildProcessError):
            os.waitpid(session["pid"], os.WNOHANG)

    def test_the_session_list_never_carries_the_token(self):
        session = self._open()
        status, body = _api(self.port, "/api/terminal/sessions")
        self.assertEqual(status, 200)
        row = next(row for row in body["sessions"] if row["id"] == session["id"])
        self.assertNotIn("token", row)
        self.assertNotIn(session["token"], json.dumps(body))
        self.assertTrue(row["alive"])
        self.assertEqual(row["pid"], session["pid"])

    def test_a_bad_size_is_refused(self):
        for payload in ({"cols": 0, "rows": 24}, {"cols": 80, "rows": 9999}, {"cols": "wide", "rows": 24}):
            status, body = _api(self.port, "/api/terminal/open", payload)
            self.assertEqual((status, body["error"]["code"]), (400, "terminal_bad_size"), payload)


def _key(session: dict) -> dict:
    return {"id": session["id"], "token": session["token"]}


def _drain(response, needle: str, timeout: float, seen: list[str]) -> None:
    """표식이 나올 때까지 프레임을 모은다 — 읽은 것은 `seen` 에 그대로 남는다."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = response.readline()
        if not line:
            return
        if not line.startswith(b"data: "):
            continue
        seen.append(json.loads(line[6:].decode("utf-8")).get("data", ""))
        if needle in "".join(seen):
            return


if __name__ == "__main__":
    unittest.main()
