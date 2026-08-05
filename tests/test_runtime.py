"""Transport-neutral agent runtime contracts."""

from __future__ import annotations

import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import TYPE_CHECKING, cast
from unittest import mock

if TYPE_CHECKING:
    from asgard.providers import ResolvedProvider


class TestExecutionSession(unittest.TestCase):
    def test_submit_normalizes_streamed_response_and_emits_typed_lifecycle(self):
        from asgard.agent.runtime import (
            ExecutionSession,
            TurnFinished,
            TurnStarted,
            TurnStatusChanged,
            TurnText,
        )

        class FakeRP:
            class profile:
                name = "anthropic"

            model = "claude-x"

        calls: list[tuple[str, str]] = []

        class FakeHeimdall:
            def __init__(self, rp, root, on_text, on_status=None):
                self.total_tokens = 21
                self.cache_read_tokens = 8
                self.cache_prompt_tokens = 13
                self.last_response_text = "direct answer"
                self._last_quest_id = None
                self.cancel_event = threading.Event()
                self.cancel_event.set()
                self.on_text = on_text
                self.on_status = on_status or (lambda _label: None)

            def handle(self, prompt):
                calls.append(("handle", prompt))
                self.on_status("생각 중")
                self.on_text("direct answer")
                return ""

        events = []
        clock = iter((10.0, 12.34))
        with mock.patch("asgard.agent.heimdall.Heimdall", FakeHeimdall):
            session = ExecutionSession(
                cast("ResolvedProvider", FakeRP()),
                "/workspace",
                session_id="session-1",
                on_event=events.append,
                clock=lambda: next(clock),
            )
            result = session.submit("읽어줘")

        self.assertEqual(calls, [("handle", "읽어줘")])
        self.assertEqual(result.text, "direct answer")
        self.assertEqual(result.outcome, "completed")
        self.assertTrue(result.response_streamed)
        self.assertTrue(result.ok)
        self.assertEqual(result.wall_s, 2.3)
        self.assertEqual(result.tokens, 21)
        self.assertEqual(result.cache_read_tokens, 8)
        self.assertEqual(result.cache_prompt_tokens, 13)
        self.assertEqual(result.session_id, "session-1")

        self.assertEqual(
            [type(event) for event in events],
            [TurnStarted, TurnStatusChanged, TurnText, TurnFinished],
        )
        self.assertEqual(events[0].prompt, "읽어줘")
        self.assertFalse(events[0].resume)
        self.assertEqual(events[-1].wall_s, 2.3)
        self.assertTrue(events[-1].ok)

    def test_resume_reuses_the_session_and_dual_mode(self):
        from asgard.agent.runtime import ExecutionSession

        class FakeRP:
            class profile:
                name = "anthropic"

            model = "claude-x"

        instances = []

        class FakeHeimdall:
            def __init__(self, rp, root, on_text, on_status=None):
                self.total_tokens = 0
                self.cache_read_tokens = 0
                self.cache_prompt_tokens = 0
                self.last_response_text = ""
                self.cancel_event = threading.Event()
                self.calls = []
                instances.append(self)

            def handle(self, prompt):
                self.calls.append(("handle", prompt))
                return "first"

            def resume(self, quest_id=None):
                self.calls.append(("resume", quest_id))
                return "resumed"

        clock = iter((1.0, 2.0, 3.0, 4.0))
        with mock.patch("asgard.agent.heimdall.Heimdall", FakeHeimdall):
            session = ExecutionSession(
                cast("ResolvedProvider", FakeRP()),
                "/workspace",
                dual=True,
                clock=lambda: next(clock),
            )
            session.submit("start")
            result = session.resume("quest-1")

        self.assertEqual(len(instances), 1)
        self.assertTrue(instances[0].dual_mode)
        self.assertEqual(instances[0].calls, [("handle", "start"), ("resume", "quest-1")])
        self.assertEqual(result.text, "resumed")

    def test_cancel_from_turn_started_reaches_the_lazily_created_heimdall(self):
        from asgard.agent.runtime import ExecutionSession, TurnStarted, TurnText

        class FakeRP:
            class profile:
                name = "anthropic"

            model = "claude-x"

        instances = []

        class FakeHeimdall:
            def __init__(self, rp, root, on_text, on_status=None):
                self.total_tokens = 0
                self.cache_read_tokens = 0
                self.cache_prompt_tokens = 0
                self.last_response_text = ""
                self.cancel_event = threading.Event()
                self.cancelled = False
                instances.append(self)
                on_text("init-warning")

            def handle(self, prompt):
                return "cancelled" if self.cancel_event.is_set() else "ran"

            def cancel(self):
                self.cancelled = True
                self.cancel_event.set()

        events = []
        session = None

        def on_event(event):
            events.append(event)
            if isinstance(event, TurnStarted):
                assert session is not None
                session.cancel()

        clock = iter((1.0, 2.0))
        with mock.patch("asgard.agent.heimdall.Heimdall", FakeHeimdall):
            session = ExecutionSession(
                cast("ResolvedProvider", FakeRP()),
                "/workspace",
                on_event=on_event,
                clock=lambda: next(clock),
            )
            result = session.submit("start")

        self.assertEqual(result.text, "cancelled")
        self.assertTrue(instances[0].cancelled)
        self.assertEqual([type(event) for event in events[:2]], [TurnStarted, TurnText])

    def test_failed_resume_does_not_reuse_the_previous_quest_id(self):
        from asgard.agent.runtime import ExecutionSession

        class FakeRP:
            class profile:
                name = "anthropic"

            model = "claude-x"

        class FakeHeimdall:
            def __init__(self, rp, root, on_text, on_status=None):
                self.total_tokens = 0
                self.cache_read_tokens = 0
                self.cache_prompt_tokens = 0
                self.last_response_text = ""
                self.cancel_event = threading.Event()
                self._last_quest_id = None

            def handle(self, prompt):
                self._last_quest_id = "quest-old"
                return "first"

            def resume(self, quest_id=None):
                return "⚠ 이어서 할 ACTIVE Quest가 없어요."

        clock = iter((1.0, 2.0, 3.0, 4.0))
        with mock.patch("asgard.agent.heimdall.Heimdall", FakeHeimdall):
            session = ExecutionSession(
                cast("ResolvedProvider", FakeRP()),
                "/workspace",
                clock=lambda: next(clock),
            )
            self.assertEqual(session.submit("start").quest_id, "quest-old")
            result = session.resume("missing")

        self.assertEqual(result.outcome, "attention")
        self.assertIsNone(result.quest_id)


class TestRunPromptAdapter(unittest.TestCase):
    def assert_activity_events(self, emit):
        self.assertEqual(
            emit.call_args_list,
            [
                mock.call(
                    "run.start",
                    prompt="작업해줘",
                    provider="anthropic",
                    model="claude-x",
                    resume=False,
                ),
                mock.call("status", label="생각 중"),
                mock.call("run.end", ok=True, wall_s=0.4, tokens=3),
            ],
        )

    def test_run_prompt_uses_execution_session(self):
        from asgard import activity
        from asgard.agent.runtime import TurnFinished, TurnResult, TurnStarted, TurnStatusChanged, TurnText
        from asgard.commands import start

        class FakeRP:
            class profile:
                name = "anthropic"

            model = "claude-x"

        calls = []

        class FakeSession:
            def __init__(self, provider, root, *, dual=False, on_event=None):
                calls.append(("init", provider, root, dual, on_event))
                assert on_event is not None
                self.on_event = on_event

            def submit(self, prompt):
                calls.append(("submit", prompt))
                self.on_event(TurnStarted("session-1", prompt, "anthropic", "claude-x", False))
                self.on_event(TurnStatusChanged("session-1", "생각 중"))
                self.on_event(TurnText("session-1", "progress\n"))
                self.on_event(TurnFinished("session-1", True, 0.4, 3))
                return TurnResult(
                    session_id="session-1",
                    text="via runtime",
                    outcome="completed",
                    response_streamed=False,
                    quest_id="quest-1",
                    tokens=3,
                    cache_read_tokens=1,
                    cache_prompt_tokens=2,
                    wall_s=0.4,
                    provider="anthropic",
                    model="claude-x",
                )

        def forbidden_heimdall(*args, **kwargs):
            raise AssertionError("run_prompt bypassed ExecutionSession")

        output = StringIO()
        error = StringIO()
        emit = mock.Mock()
        with (
            redirect_stdout(output),
            redirect_stderr(error),
            mock.patch.object(start, "preflight", return_value=([{"ok": True}], FakeRP())),
            mock.patch.object(activity, "emit", emit),
            mock.patch("asgard.agent.runtime.ExecutionSession", FakeSession),
            mock.patch("asgard.agent.heimdall.Heimdall", forbidden_heimdall),
        ):
            return_code = start.run_prompt("작업해줘", json_out=True)

        self.assertEqual(return_code, 0)
        self.assertEqual(calls[0][0], "init")
        self.assertEqual(calls[1], ("submit", "작업해줘"))
        self.assertIn('"result": "via runtime"', output.getvalue())
        self.assertEqual(error.getvalue(), "progress\n")
        self.assert_activity_events(emit)


if __name__ == "__main__":
    unittest.main()
