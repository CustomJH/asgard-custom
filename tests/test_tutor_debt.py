"""튜터 인지적 항복 계측 앵커.

실행: python3 -m pytest tests/test_tutor_debt.py
"""

from __future__ import annotations

import inspect
import json
import os
import tempfile
import unittest
from dataclasses import fields
from unittest import mock

from asgard import tutor_debt, tutor_growth

DAY = tutor_growth.DAY
NOW = 1_000_000.0


def _point(kind: str = "silent-failure", path: str = "app.py", unit: str = "go") -> dict:
    return {"kind": kind, "path": path, "unit": unit, "ask": "왜?"}


def _signal(root: str, name: str, sid: str = "s", now: float = 1000.0) -> tutor_debt.Signal:
    found = [signal for signal in tutor_debt.ledger(root, sid, now=now).signals if signal.name == name]
    assert found
    return found[0]


def _write_json(root: str, relative: str, data: object) -> None:
    path = os.path.join(root, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def _write_stores(root: str, session: dict | None = None, backlog: int = 0, skipped: int = 0) -> None:
    row = {
        "sid": "s",
        "started": NOW,
        "turns": 0,
        "files": 0,
        "added": 0,
        "removed": 0,
        "asked": 0,
        "answered": 0,
        "answered_seen": 0,
        "pending": [],
        "latencies": [],
    }
    row.update(session or {})
    open_rows = {
        f"q{index}": {
            "kind": "silent-failure",
            "path": f"app_{index}.py",
            "unit": "go",
            "ask": "무엇을 확인했나요?",
            "asks": 1,
            "opened": NOW - DAY,
        }
        for index in range(backlog)
    }
    topics = {"silent-failure": {"asked": skipped + 1, "answered": 0, "deep": 0, "skipped": skipped}}
    _write_json(root, tutor_debt.DEBT_REL, {"version": 1, "sessions": {"s": row}, "expects": {}})
    _write_json(root, tutor_growth.GROWTH_REL, {"version": 1, "topics": topics, "open": open_rows, "closed": []})


class InterfaceTest(unittest.TestCase):
    def test_public_contract_names_are_fixed(self):
        self.assertEqual(
            tutor_debt.SIGNALS,
            ("acceptance-latency", "unanswered-backlog", "review-ratio", "skip-streak", "session-load"),
        )

    def test_public_dataclasses_and_signatures_match_the_shared_contract(self):
        self.assertEqual(
            [(field.name, str(field.type)) for field in fields(tutor_debt.Signal)],
            [("name", "str"), ("level", "int"), ("fact", "str"), ("why", "str"), ("source", "str")],
        )
        self.assertEqual(
            [(field.name, str(field.type)) for field in fields(tutor_debt.Ledger)],
            [
                ("signals", "tuple[Signal, ...]"),
                ("open_debt", "int"),
                ("oldest_days", "int"),
                ("turns", "int"),
                ("added", "int"),
            ],
        )
        expected = {
            "ledger": "(root: 'str', sid: 'str' = '', now: 'float | None' = None) -> 'Ledger'",
            "note_turn": "(root: 'str', sid: 'str', files: 'int', added: 'int', removed: 'int', asked: 'int' = 0, now: 'float | None' = None) -> 'None'",
            "expect": "(root: 'str', sid: 'str', text: 'str', now: 'float | None' = None) -> 'str'",
            "expectations": "(root: 'str', sid: 'str' = '', open_only: 'bool' = True) -> 'list[dict]'",
            "settle": "(root: 'str', key: 'str', verdict: 'str', now: 'float | None' = None) -> 'tuple[bool, str]'",
        }
        self.assertEqual(
            {name: str(inspect.signature(getattr(tutor_debt, name))) for name in expected},
            expected,
        )

    def test_ledger_level_and_worst_are_derived_from_signals(self):
        low = tutor_debt.Signal("session-load", 1, "1", "왜", "src")
        high = tutor_debt.Signal("review-ratio", 2, "2", "왜", "src")
        led = tutor_debt.Ledger((low, high), 0, 0, 0, 0)
        self.assertEqual(led.level, 2)
        self.assertEqual(led.worst, high)


class TurnTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_note_turn_counts_session_turns_and_added_lines(self):
        tutor_debt.note_turn(self.root, "s", files=2, added=30, removed=4, now=1000.0)
        tutor_debt.note_turn(self.root, "s", files=1, added=12, removed=1, now=1010.0)
        led = tutor_debt.ledger(self.root, "s", now=1020.0)
        self.assertEqual((led.turns, led.added), (2, 42))

    def test_note_turn_is_fail_open_when_the_store_cannot_be_written(self):
        os.makedirs(os.path.join(self.root, tutor_debt.DEBT_REL), exist_ok=True)
        tutor_debt.note_turn(self.root, "s", files=1, added=1, removed=0, asked=1, now=1000.0)
        led = tutor_debt.ledger(self.root, "s", now=1000.0)
        self.assertEqual((led.turns, led.added), (0, 0))


class SignalTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_all_five_persisted_signals_reach_levels_zero_one_and_two(self):
        cases = (
            ("acceptance-latency", {"latencies": [90.0]}, 0, 0, 0),
            ("acceptance-latency", {"latencies": [89.0]}, 0, 0, 1),
            ("acceptance-latency", {"latencies": [44.0]}, 0, 0, 2),
            ("unanswered-backlog", {}, tutor_debt.BACKLOG_WARN - 1, 0, 0),
            ("unanswered-backlog", {}, tutor_debt.BACKLOG_WARN, 0, 1),
            ("unanswered-backlog", {}, tutor_debt.BACKLOG_ALARM, 0, 2),
            ("review-ratio", {"answered": 1, "added": tutor_debt.REVIEW_LINES - 1}, 0, 0, 0),
            ("review-ratio", {"answered": 1, "added": tutor_debt.REVIEW_LINES}, 0, 0, 1),
            ("review-ratio", {"answered": 1, "added": tutor_debt.REVIEW_LINES * 2}, 0, 0, 2),
            ("skip-streak", {}, 0, tutor_debt.STREAK_WARN - 1, 0),
            ("skip-streak", {}, 0, tutor_debt.STREAK_WARN, 1),
            ("skip-streak", {}, 0, tutor_debt.STREAK_WARN * 2, 2),
            ("session-load", {"turns": tutor_debt.LOAD_TURNS - 1}, 0, 0, 0),
            ("session-load", {"turns": tutor_debt.LOAD_TURNS}, 0, 0, 1),
            ("session-load", {"turns": tutor_debt.LOAD_TURNS * 2}, 0, 0, 2),
        )
        for name, session, backlog, skipped, expected in cases:
            with self.subTest(signal=name, expected=expected), tempfile.TemporaryDirectory() as root:
                _write_stores(root, session, backlog, skipped)
                signal = _signal(root, name, now=NOW)
                self.assertEqual(signal.level, expected)
                self.assertRegex(signal.fact, r"\d")
                self.assertTrue(signal.fact.endswith("요"))
                self.assertTrue(signal.why.endswith("요"))

    def test_schema_damage_fails_open_but_programming_errors_surface(self):
        _write_json(self.root, tutor_debt.DEBT_REL, {"version": 1, "sessions": [], "expects": []})
        _write_json(
            self.root,
            tutor_growth.GROWTH_REL,
            {"version": "broken", "topics": {}, "open": {}, "closed": []},
        )
        self.assertEqual(tuple(signal.name for signal in tutor_debt.ledger(self.root).signals), tutor_debt.SIGNALS)
        with mock.patch.object(tutor_debt, "_latency_signal", side_effect=RuntimeError("programming error")):
            with self.assertRaisesRegex(RuntimeError, "programming error"):
                tutor_debt.ledger(self.root)

    def test_acceptance_latency_warns_when_an_answer_closes_too_fast(self):
        tutor_debt.note_turn(self.root, "s", files=1, added=5, removed=0, asked=1, now=1000.0)
        tutor_growth.note_asked(self.root, [_point()], now=1000.0)
        key = tutor_growth.cid("silent-failure", "app.py", "go")
        tutor_growth.answer(self.root, key, "상류가 죽어도 화면은 캐시로 버텨야 해서 삼킨다", now=1040.0)
        signal = _signal(self.root, "acceptance-latency", now=1041.0)
        self.assertEqual(signal.level, 2)
        self.assertIn("40초", signal.fact)

    def test_unanswered_backlog_uses_growth_open_points_and_oldest_age(self):
        rows = [_point(path=f"app_{index}.py", unit="go") for index in range(tutor_debt.BACKLOG_ALARM)]
        tutor_growth.note_asked(self.root, rows, now=1000.0)
        led = tutor_debt.ledger(self.root, "s", now=1000.0 + 3 * DAY)
        signal = [signal for signal in led.signals if signal.name == "unanswered-backlog"][0]
        self.assertEqual((led.open_debt, led.oldest_days, signal.level), (tutor_debt.BACKLOG_ALARM, 3, 2))

    def test_review_ratio_counts_added_lines_per_answered_question(self):
        tutor_debt.note_turn(self.root, "s", files=1, added=tutor_debt.REVIEW_LINES * 2, removed=0, asked=1, now=1000.0)
        tutor_growth.note_asked(self.root, [_point()], now=1000.0)
        key = tutor_growth.cid("silent-failure", "app.py", "go")
        tutor_growth.answer(self.root, key, "상류가 죽어도 화면은 캐시로 버텨야 해서 삼킨다", now=1200.0)
        signal = _signal(self.root, "review-ratio", now=1201.0)
        self.assertEqual(signal.level, 2)
        self.assertIn("800.0줄", signal.fact)

    def test_review_ratio_flags_large_changes_with_no_answers(self):
        tutor_debt.note_turn(self.root, "s", files=1, added=tutor_debt.REVIEW_LINES, removed=0, now=1000.0)
        signal = _signal(self.root, "review-ratio", now=1001.0)
        self.assertEqual(signal.level, 2)
        self.assertIn("답한 물음 0건", signal.fact)

    def test_skip_streak_reads_growth_topics_that_never_got_deep_answers(self):
        data = tutor_growth.load(self.root)
        data["topics"]["todo-left"] = {"asked": 5, "answered": 0, "deep": 0, "skipped": tutor_debt.STREAK_WARN}
        tutor_growth.save(self.root, data)
        signal = _signal(self.root, "skip-streak")
        self.assertEqual(signal.level, 1)
        self.assertIn("4번", signal.fact)

    def test_session_load_counts_cumulative_turns(self):
        for index in range(tutor_debt.LOAD_TURNS):
            tutor_debt.note_turn(self.root, "s", files=0, added=0, removed=0, now=1000.0 + index)
        signal = _signal(self.root, "session-load", now=2000.0)
        self.assertEqual(signal.level, 1)
        self.assertIn("12턴", signal.fact)


class ExpectationTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_expect_stores_an_open_expectation_and_returns_an_eight_character_key(self):
        key = tutor_debt.expect(self.root, "s", "이 변경은 캐시 경로만 만질 것 같아요", now=1000.0)
        rows = tutor_debt.expectations(self.root, "s")
        self.assertEqual(len(key), 8)
        self.assertEqual(rows[0]["key"], key)
        self.assertEqual(rows[0]["text"], "이 변경은 캐시 경로만 만질 것 같아요")

    def test_expectations_can_filter_by_session_and_closed_state(self):
        open_key = tutor_debt.expect(self.root, "s", "열린 예상", now=1000.0)
        other_key = tutor_debt.expect(self.root, "other", "다른 세션", now=1001.0)
        tutor_debt.settle(self.root, open_key, "맞았어요", now=1002.0)
        self.assertEqual([row["key"] for row in tutor_debt.expectations(self.root, "s")], [])
        self.assertEqual([row["key"] for row in tutor_debt.expectations(self.root, "s", open_only=False)], [open_key])
        self.assertEqual([row["key"] for row in tutor_debt.expectations(self.root, "other")], [other_key])

    def test_settle_accepts_a_unique_prefix_and_records_the_verdict(self):
        key = tutor_debt.expect(self.root, "s", "예상", now=1000.0)
        ok, message = tutor_debt.settle(self.root, key[:4], "생각보다 테스트를 더 만졌어요", now=1100.0)
        rows = tutor_debt.expectations(self.root, "s", open_only=False)
        self.assertTrue(ok)
        self.assertEqual(message, "예상을 닫았어요")
        self.assertEqual(rows[0]["verdict"], "생각보다 테스트를 더 만졌어요")
        self.assertEqual(rows[0]["settled_at"], 1100.0)

    def test_settle_does_not_pretend_an_unknown_key_was_closed(self):
        ok, message = tutor_debt.settle(self.root, "ffffffff", "없어요", now=1000.0)
        self.assertFalse(ok)
        self.assertIn("ffffffff", message)


if __name__ == "__main__":
    unittest.main()
