#!/usr/bin/env python3
"""TUI 뼈대 스모크 — textual pilot. 실 API 없이 App 기동·입력·슬래시·종료.

실행: uv run pytest tests/test_tui.py
"""

import asyncio
import threading
import unittest
from typing import Any, cast
from unittest import mock

from asgard.agent import repl
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
                masthead = app.query_one("#masthead", Static)
                assert repl._LOGO_SLIM in str(masthead.render())
                assert app.query_one("#prompt-label", Static) is not None
                await pilot.pause()

        asyncio.run(go())

    def test_full_brand_logo_on_wide_terminal(self):
        async def go():
            app = self._app()
            async with app.run_test(size=(120, 36)) as pilot:
                from textual.widgets import Static

                masthead = app.query_one("#masthead", Static)
                assert repl._LOGO.splitlines()[0].strip() in str(masthead.render())
                await pilot.resize_terminal(80, 24)
                await pilot.pause()
                assert repl._LOGO_SLIM in str(masthead.render())

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

    def test_interactive_slash_commands_stay_inside_tui(self):
        async def go():
            app = self._app()
            async with app.run_test() as pilot:
                inp = app.query_one("#input")
                with (
                    mock.patch.object(app, "suspend", side_effect=AssertionError("TUI suspended")) as suspend,
                    mock.patch.object(app, "_open_provider_picker") as provider,
                    mock.patch.object(app, "_open_model_picker") as model,
                    mock.patch.object(app, "_open_role_picker") as trinity,
                    mock.patch.object(app, "_start_update") as update,
                ):
                    for command in ("/provider set", "/model", "/trinity set", "/update"):
                        inp.value = command
                        await pilot.press("enter")
                        await pilot.pause()

                    suspend.assert_not_called()
                    provider.assert_called_once()
                    model.assert_called_once()
                    trinity.assert_called_once()
                    update.assert_called_once_with([])
                    self.assertTrue(app.is_running)

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
                assert not inp.disabled

        asyncio.run(go())

    def test_slash_suggester(self):
        async def go():
            app = self._app()
            async with app.run_test() as pilot:
                from textual.widgets import Input

                inp = app.query_one("#input", Input)
                assert inp.suggester is not None
                s = await inp.suggester.get_suggestion("/he")
                assert s == "/help", s
                s2 = await inp.suggester.get_suggestion("/pro")
                assert s2 and s2.startswith("/provider"), s2
                inp.value = "/he"
                inp.cursor_position = len(inp.value)
                await pilot.pause()
                await pilot.press("tab")
                assert inp.value == "/help"

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
                assert app.query_one("#input").disabled
                app._set_status(False)
                await pilot.pause()
                assert t("busy") not in str(st.render())
                assert not app.query_one("#input").disabled

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

    def test_interrupt_signals_heimdall_cancel(self):
        async def go():
            app = self._app()

            class CancelStub(BlockingStub):
                def __init__(self):
                    super().__init__()
                    self.cancelled = threading.Event()

                def cancel(self):
                    self.cancelled.set()
                    self.release.set()  # 취소 = 턴 조기 종료 시뮬레이션

            stub = CancelStub()
            app.heimdall = cast(Any, stub)
            async with app.run_test() as pilot:
                from textual.widgets import Input

                inp = app.query_one("#input", Input)
                inp.value = "long turn"
                await pilot.press("enter")
                for _ in range(50):
                    if stub.started.is_set():
                        break
                    await asyncio.sleep(0.01)
                app.action_interrupt()
                await pilot.pause()
                self.assertTrue(stub.cancelled.is_set())
                self.assertTrue(app._bang_cancel.is_set())  # ! bash 경로도 같은 신호로 중단
                for _ in range(50):
                    if not app._turn_running:
                        break
                    await asyncio.sleep(0.01)
                self.assertFalse(app._turn_running)

        asyncio.run(go())

    def test_stream_coalescing_flushes_on_newline(self):
        async def go():
            app = self._app()
            async with app.run_test() as pilot:
                from textual.widgets import RichLog

                log = app.query_one("#log", RichLog)
                before = len(log.lines)
                # _emit 은 워커 스레드 계약 (call_from_thread) — to_thread 로 실사용 경로 재현
                await asyncio.to_thread(app._emit, "조각1 ")  # 개행 없음 — 아직 미출력
                await pilot.pause()
                self.assertEqual(len(log.lines), before)
                await asyncio.to_thread(app._emit, "조각2\n잔여")  # 개행 — 완결 줄만 출력
                await pilot.pause()
                self.assertGreater(len(log.lines), before)
                self.assertEqual(app._stream_buf, "잔여")
                app._flush_stream()
                await pilot.pause()
                self.assertEqual(app._stream_buf, "")

        asyncio.run(go())

    def test_busy_keeps_telemetry_and_shows_activity(self):
        async def go():
            app = self._app()
            async with app.run_test() as pilot:
                from textual.widgets import Static

                st = app.query_one("#status", Static)
                app._set_status(True)
                app._set_activity("$ pytest -q")
                await pilot.pause()
                rendered = str(st.render())
                self.assertIn("pytest", rendered)  # 활동 서픽스
                self.assertIn("ASGARD", rendered)  # 브랜드칩 유지
                app._set_status(False)
                await pilot.pause()
                self.assertNotIn("pytest", str(st.render()))

        asyncio.run(go())

    def test_init_survives_immediate_heimdall_emission(self):
        """Heimdall 생성자는 즉시 on_text/on_status 를 방출할 수 있다 (미완 퀘스트·placement 경고).
        콜백 상태(_stream_lock 등)가 준비되기 전 생성하면 AttributeError — 순서 회귀 방지."""
        rp = resolve("/tmp", provider="anthropic")
        rp.missing = []

        def factory(root, rp_, emit, status=None):
            emit("⚠ 초기 경고\n")
            if status is not None:
                status("thinking")
                status(None)
            return Stub()

        with mock.patch.object(repl, "_new_heimdall", side_effect=factory):
            app = AsgardTUI("/tmp", rp)
        self.assertIsInstance(app.heimdall, Stub)

    def test_quit_binding(self):
        async def go():
            app = self._app()
            async with app.run_test() as pilot:
                await pilot.press("ctrl+q")
                await pilot.pause()
            assert app.return_code == 0 or app.return_code is None

        asyncio.run(go())

    def test_start_uses_tui_by_default_and_plain_only_when_requested(self):
        from asgard.commands.start import run_start

        rp = object()
        with (
            mock.patch("asgard.providers.resolve", return_value=rp),
            mock.patch("asgard.agent.tui.run", return_value=7) as tui_run,
            mock.patch("asgard.agent.repl.run", return_value=8) as plain_run,
        ):
            self.assertEqual(run_start(), 7)
            tui_run.assert_called_once_with(mock.ANY, rp, cont=False)
            plain_run.assert_not_called()

            self.assertEqual(run_start(plain=True), 8)
            plain_run.assert_called_once_with(mock.ANY, rp, cont=False)


if __name__ == "__main__":
    unittest.main(verbosity=1)
