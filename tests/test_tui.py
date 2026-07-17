#!/usr/bin/env python3
"""TUI 뼈대 스모크 — textual pilot. 실 API 없이 App 기동·입력·슬래시·종료.

실행: uv run pytest tests/test_tui.py
"""

import asyncio
import threading
import unittest
from typing import Any, cast

from asgard.agent.tui import AsgardTUI
from asgard.providers import resolve


class Stub:
    """Heimdall 스텁 — API 없이 handle."""

    def handle(self, req):
        return f"[echo] {req}"


class BlockingStub:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def handle(self, req):
        self.calls.append(req)
        self.started.set()
        self.release.wait(timeout=5)
        return f"[echo] {req}"


class TestTUI(unittest.TestCase):
    def _app(self):
        rp = resolve("/tmp", provider="anthropic")
        rp.missing = []  # 키 있는 것으로 (온보딩 회피)
        app = AsgardTUI("/tmp", rp)
        app.heimdall = Stub()
        return app

    def test_mount_and_widgets(self):
        async def go():
            app = self._app()
            async with app.run_test() as pilot:
                from textual.widgets import Input, RichLog, Static

                assert app.query_one("#log", RichLog) is not None
                assert app.query_one("#input", Input) is not None
                assert app.query_one("#logo", Static) is not None
                await pilot.pause()

        asyncio.run(go())

    def test_slash_help(self):
        async def go():
            app = self._app()
            async with app.run_test() as pilot:
                inp = app.query_one("#input")
                inp.value = "/help"
                await pilot.press("enter")
                await pilot.pause()
                # RichLog 에 help 항목이 쓰였는지 (line 수 > 초기)
                from textual.widgets import RichLog

                log = app.query_one("#log", RichLog)
                assert len(log.lines) > 1

        asyncio.run(go())

    def test_bang_bash(self):
        async def go():
            app = self._app()
            async with app.run_test() as pilot:
                inp = app.query_one("#input")
                inp.value = "!echo tui-smoke"
                await pilot.press("enter")
                await asyncio.sleep(0.5)  # worker thread 완료 대기
                await pilot.pause()

        asyncio.run(go())

    def test_slash_suggester(self):
        async def go():
            app = self._app()
            async with app.run_test():
                from textual.widgets import Input

                inp = app.query_one("#input", Input)
                assert inp.suggester is not None
                s = await inp.suggester.get_suggestion("/he")
                assert s == "/help", s
                s2 = await inp.suggester.get_suggestion("/pro")
                assert s2 and s2.startswith("/provider"), s2

        asyncio.run(go())

    def test_status_busy_toggle(self):
        async def go():
            app = self._app()
            async with app.run_test() as pilot:
                from textual.widgets import Static

                st = app.query_one("#status", Static)
                from asgard.i18n import t

                app._set_status(True)
                await pilot.pause()
                assert t("busy") in str(st.render())
                app._set_status(False)
                await pilot.pause()
                assert t("busy") not in str(st.render())

        asyncio.run(go())

    def test_second_turn_and_interrupt_do_not_overlap_live_thread(self):
        async def go():
            app = self._app()
            stub = BlockingStub()
            app.heimdall = cast(Any, stub)
            async with app.run_test() as pilot:
                from textual.widgets import Input

                inp = app.query_one("#input", Input)
                inp.value = "first"
                await pilot.press("enter")
                for _ in range(50):
                    if stub.started.is_set():
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(stub.started.is_set())

                inp.value = "second"
                await pilot.press("enter")
                original = app.heimdall
                inp.value = "/new"
                await pilot.press("enter")
                self.assertIs(app.heimdall, original)
                app.action_interrupt()
                await pilot.pause()
                self.assertEqual(stub.calls, ["first"])
                self.assertTrue(app._turn_running)

                stub.release.set()
                for _ in range(50):
                    if not app._turn_running:
                        break
                    await asyncio.sleep(0.01)
                self.assertFalse(app._turn_running)

        asyncio.run(go())

    def test_quit_binding(self):
        async def go():
            app = self._app()
            async with app.run_test() as pilot:
                await pilot.press("ctrl+q")
                await pilot.pause()
            assert app.return_code == 0 or app.return_code is None

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main(verbosity=1)
