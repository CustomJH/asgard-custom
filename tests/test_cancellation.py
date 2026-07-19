#!/usr/bin/env python3
"""협조적 취소 계약 — cancel_event 가 청크/툴/iteration 경계에서 턴을 멈추고,
bash 는 프로세스 그룹째(손자 포함) 종료되며, 히스토리는 항상 API-유효 상태로 닫힌다.

실행: uv run pytest tests/test_cancellation.py
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.agent import tools as T  # noqa: E402


@unittest.skipUnless(os.name == "posix", "프로세스 그룹 킬·sleep 은 POSIX 계약 — Windows 는 taskkill 분기")
class TestBashCancel(unittest.TestCase):
    def test_cancel_kills_promptly(self):
        cancel = threading.Event()
        with tempfile.TemporaryDirectory() as root:
            timer = threading.Timer(0.5, cancel.set)
            timer.start()
            t0 = time.monotonic()
            with self.assertRaises(T.ToolError) as cm:
                T.run_bash(root, {"command": "sleep 30"}, cancel=cancel)
            timer.cancel()
            self.assertLess(time.monotonic() - t0, 10)
            self.assertIn("취소", str(cm.exception))

    def test_cancel_kills_grandchild_process(self):
        cancel = threading.Event()
        with tempfile.TemporaryDirectory() as root:
            cmd = (
                "python3 -c \"import subprocess; p=subprocess.Popen(['sleep','30']); "
                "open('pid.txt','w').write(str(p.pid)); p.wait()\""
            )
            timer = threading.Timer(0.8, cancel.set)
            timer.start()
            with self.assertRaises(T.ToolError):
                T.run_bash(root, {"command": cmd}, cancel=cancel)
            timer.cancel()
            pid = int(open(os.path.join(root, "pid.txt")).read())
            deadline = time.monotonic() + 3
            alive = True
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    alive = False
                    break
                time.sleep(0.1)
            self.assertFalse(alive, "손자 프로세스가 살아 있음 — 프로세스 그룹 킬 실패")

    def test_timeout_unaffected_without_cancel(self):
        with tempfile.TemporaryDirectory() as root:
            out, code = T.run_bash(root, {"command": "echo ok"})
            self.assertEqual((out, code), ("ok", 0))


class _FakeStream:
    def __init__(self, resp, chunks):
        self.resp = resp
        self.text_stream = chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.resp


class _FakeClient:
    """messages.stream 대역 — 준비된 (chunks, resp) 를 순서대로 서빙. 소진 후 호출은 실패."""

    def __init__(self, scripted):
        self.calls = 0
        outer = self

        class _Messages:
            def stream(self, **kw):
                if outer.calls >= len(scripted):
                    raise AssertionError("취소 후 추가 API 호출 발생 — 취소 계약 위반")
                chunks, resp = scripted[outer.calls]
                outer.calls += 1
                return _FakeStream(resp, iter(chunks))

        self.messages = _Messages()


def _usage():
    return SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)


def _text_resp(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn", usage=_usage())


def _tool_resp(*names):
    blocks = [SimpleNamespace(type="tool_use", id=f"t{i}", name=name, input={}) for i, name in enumerate(names)]
    return SimpleNamespace(content=blocks, stop_reason="tool_use", usage=_usage())


class _TmpHome(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = self.root

    def tearDown(self):
        if self._home is not None:
            os.environ["HOME"] = self._home
        self._tmp.cleanup()

    def _session(self, scripted, handlers=None, extra_tools=None):
        from asgard.agent.session import AgentSession
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        client = _FakeClient(scripted)
        return AgentSession(client, rp, self.root, "s", extra_tools=extra_tools, tool_handlers=handlers), client


class TestSessionCancel(_TmpHome):
    def test_precancelled_turn_makes_no_api_call(self):
        s, client = self._session([([], _text_resp("x"))])
        s.cancel()
        r = s.run("질문")
        self.assertEqual(r.stop_reason, "cancelled")
        self.assertEqual(client.calls, 0)

    def test_midstream_cancel_seals_partial_assistant(self):
        holder = {}

        def chunks():
            yield "부분"
            holder["s"].cancel()
            yield "이후"

        s, client = self._session([(None, _text_resp("무시"))])
        holder["s"] = s
        # 스크립트 스트림을 취소 유발 제너레이터로 교체
        client.messages.stream = lambda **kw: _FakeStream(_text_resp("무시"), chunks())
        r = s.run("질문")
        self.assertEqual(r.stop_reason, "cancelled")
        self.assertEqual(r.text, "부분")
        self.assertEqual(s.messages[-1]["role"], "assistant")
        self.assertEqual(s.messages[-1]["content"], "부분")

    def test_cancel_during_tool_batch_closes_pairs_without_executing_rest(self):
        executed = []
        holder = {}

        def tool_a(args):
            executed.append("a")
            holder["s"].cancel()
            return "A done"

        def tool_b(args):
            executed.append("b")
            return "B done"

        schema = {"type": "object", "properties": {}}
        extra = [
            {"name": "tool_a", "description": "a", "input_schema": schema},
            {"name": "tool_b", "description": "b", "input_schema": schema},
        ]
        s, client = self._session(
            [([], _tool_resp("tool_a", "tool_b"))],
            handlers={"tool_a": tool_a, "tool_b": tool_b},
            extra_tools=extra,
        )
        holder["s"] = s
        r = s.run("질문")
        self.assertEqual(r.stop_reason, "cancelled")
        self.assertEqual(executed, ["a"])  # b 는 실행되지 않음
        trs = s.messages[-1]["content"]  # 마지막 user 메시지 = tool_result 쌍
        self.assertEqual({tr["tool_use_id"] for tr in trs}, {"t0", "t1"})
        cancelled_tr = next(tr for tr in trs if tr["tool_use_id"] == "t1")
        self.assertIn("취소", cancelled_tr["content"])


if __name__ == "__main__":
    unittest.main()
