#!/usr/bin/env python3
"""원탁 — 좌석 여럿을 한 안건에 앉히고 회차를 돌리는 자리.

여기서 지키는 계약 여섯 (틀리면 토론이 토론이 아니게 된다):
  · 교차 회차의 좌석은 **자기 앞 회차**와 **남의 최신 입장** 둘을 다 읽는다.
  · 좌석 하나가 죽어도 나머지는 계속 말한다 — 한 좌석의 실패는 원탁의 실패가 아니다.
  · 입장은 `STANCE:` 줄에서만 읽는다. 줄이 없으면 없다고 적지, 서술에서 추론하지 않는다.
  · 좌석 이름이 겹치면 거절한다 — 이름이 실(thread)의 열쇠라 기억이 섞인다.
  · 답한 좌석이 하나뿐이면 교차 회차를 열지 않는다 (상대가 없는 토론).
  · `siege serve` 는 같은 실의 앞 회차를 다시 넣고 답한다 — 그것이 안 꺼지는 좌석이다.

실행: uv run pytest tests/test_roundtable.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import orchestration as orc  # noqa: E402
from asgard import roundtable as rt  # noqa: E402
from asgard.commands import siege_serve  # noqa: E402


class Scripted:
    """좌석 자리에 정해진 답을 세운다 — 부른 프롬프트를 전부 남겨 시험이 읽는다."""

    def __init__(
        self,
        answers: dict[str, list[str]] | None = None,
        boom: set[str] | None = None,
        delay: float = 0.0,
    ) -> None:
        self.answers = answers or {}
        self.boom = boom or set()
        self.delay = delay  # 한 발언이 무는 초 — 소요를 재는 시험만 쓴다
        self.calls: list[tuple[str, str]] = []  # (좌석 이름, 사용자 프롬프트)

    def __call__(self, seat, system, user):
        if self.delay:
            time.sleep(self.delay)
        self.calls.append((seat.name, user))
        if seat.name in self.boom:
            raise RuntimeError("provider down")
        queued = self.answers.get(seat.name)
        if queued:
            return queued.pop(0)
        return f"{seat.name} 의 {len(self.calls)}번째 발언\nSTANCE: MAINTAIN"

    def prompts(self, seat_name: str) -> list[str]:
        return [user for name, user in self.calls if name == seat_name]


class TestSeatSpec(unittest.TestCase):
    def test_bare_name_is_its_own_role(self):
        (seat,) = rt.parse_seats(["critic"])
        self.assertEqual((seat.name, seat.role, seat.provider, seat.model), ("critic", "critic", "", ""))

    def test_provider_and_model_split_off(self):
        (seat,) = rt.parse_seats(["researcher:openai:gpt-5.6"])
        self.assertEqual((seat.provider, seat.model), ("openai", "gpt-5.6"))

    def test_name_can_differ_from_role(self):
        (seat,) = rt.parse_seats(["tyr=critic:ollama"])
        self.assertEqual((seat.name, seat.role, seat.provider), ("tyr", "critic", "ollama"))

    def test_duplicate_name_is_refused(self):
        with self.assertRaises(ValueError):
            rt.parse_seats(["critic", "critic:ollama"])

    def test_empty_name_is_refused(self):
        with self.assertRaises(ValueError):
            rt.parse_seats([":openai"])


class TestAutoSeating(unittest.TestCase):
    """좌석을 안 지정했을 때 — 이 기계에 있는 것으로 채우고, 벤더를 흩는다."""

    def test_three_clis_fill_three_seats_with_three_vendors(self):
        seats = rt.auto_seats(available=["cc", "codex", "cursor"])
        self.assertEqual([s.provider for s in seats], ["cc", "codex", "cursor"])

    def test_one_cli_leaves_the_rest_on_the_default_model(self):
        seats = rt.auto_seats(available=["codex"])
        self.assertEqual([s.provider for s in seats], ["codex", "", "codex"])

    def test_no_cli_means_everyone_on_the_default_model(self):
        self.assertEqual([s.provider for s in rt.auto_seats(available=[])], ["", "", ""])

    def test_roles_keep_their_names(self):
        self.assertEqual([s.role for s in rt.auto_seats(available=[])], list(rt.DEFAULT_SEATS))


class TestSeatingIsOfferedNotAssumed(unittest.TestCase):
    """설치되어 있다는 사실이 보낸다는 결정을 대신하지 않는다 — 26-08-14 원탁의 판정."""

    def notes(self, seats, *, offer):
        from asgard.commands.roundtable import _seating_notes

        return _seating_notes(seats, offer=offer)

    def test_one_backend_across_every_seat_is_said_out_loud(self):
        found = self.notes(rt.auto_seats(available=[]), offer=False)
        self.assertTrue(any("같은 뒷단" in line for line in found))

    def test_a_mixed_table_needs_no_such_warning(self):
        found = self.notes(rt.auto_seats(available=["codex", "cursor"]), offer=False)
        self.assertFalse(any("같은 뒷단" in line for line in found))

    def test_a_found_cli_is_named_with_the_flag_that_seats_it(self):
        from unittest import mock

        with mock.patch("asgard.agent.runtime.peers_present", return_value=("codex",)):
            found = self.notes(rt.auto_seats(available=[]), offer=True)
        self.assertTrue(any("--auto-cli" in line and "codex" in line for line in found))

    def test_nothing_is_offered_when_the_seats_were_named(self):
        from unittest import mock

        with mock.patch("asgard.agent.runtime.peers_present", return_value=("codex",)):
            found = self.notes(rt.parse_seats(["a:openai", "b:ollama"]), offer=False)
        self.assertEqual(found, [])


class TestTheTableStatesItsCost(unittest.TestCase):
    """값과 값어치를 같은 화면에 — 26-08-14 실측이 좌석의 값을 안 갚는 경우를 보였다."""

    def notes(self, stances, turns=6, secs=12.5):
        from asgard.commands.roundtable import _cost_notes

        result = {
            "turns": [{"ok": True, "round": 1, "seat": "a"}] * turns,
            "seats": [{"name": n} for n in stances],
            "stances": stances,
        }
        if secs is not None:
            result["secs"] = secs
        return _cost_notes(result)

    def test_the_call_count_is_always_printed(self):
        (first, *_rest) = self.notes({"a": "MODIFY", "b": "MAINTAIN"})
        self.assertIn("호출 6회", first)
        self.assertIn("2석", first)

    def test_the_elapsed_time_is_on_the_same_line(self):
        """좌석 수를 정하는 쪽이 값을 보려면 호출 수만으로는 모자란다 — 소요가 같은 줄에 있다."""
        (first, *_rest) = self.notes({"a": "MODIFY", "b": "MAINTAIN"})
        self.assertIn("12.5초", first)

    def test_a_table_with_no_measured_time_still_prints_its_calls(self):
        """`convene` 을 안 거친 dict 에도 값 한 줄은 나온다 — 시간만 빠진다."""
        (first, *_rest) = self.notes({"a": "MODIFY"}, secs=None)
        self.assertIn("호출 6회", first)
        self.assertNotIn("초", first)

    def test_a_table_that_moved_nobody_says_so(self):
        found = self.notes({"a": "MAINTAIN", "b": "MAINTAIN", "c": "MAINTAIN"})
        self.assertTrue(any("아무도 입장을 안 바꿨" in line for line in found))

    def test_a_table_that_moved_someone_does_not(self):
        found = self.notes({"a": "MAINTAIN", "b": "MODIFY"})
        self.assertFalse(any("아무도 입장을 안 바꿨" in line for line in found))

    def test_one_speaking_seat_is_not_called_unanimous(self):
        """좌석 하나가 MAINTAIN 인 것은 합의가 아니라 상대가 없던 것이다."""
        found = self.notes({"a": "MAINTAIN"})
        self.assertFalse(any("아무도 입장을 안 바꿨" in line for line in found))


class TestCliSeat(unittest.TestCase):
    """CLI 좌석 — 자기 세션을 이어받으므로 자기 앞 회차를 다시 안 받는다."""

    def test_a_peer_name_makes_it_a_cli_seat(self):
        self.assertTrue(rt.Seat(name="a", role="critic", provider="codex").is_cli)
        self.assertFalse(rt.Seat(name="a", role="critic", provider="openai").is_cli)

    def test_a_seat_without_a_session_still_gets_its_own_turns(self):
        seat = rt.Seat(name="a", role="critic", provider="codex")
        seat.turns.append({"round": 1, "text": "내 1회차 주장"})
        self.assertIn("내 1회차 주장", rt._cross_prompt("안건", seat, [("b", "b 의 말")], 2))

    def test_a_resumed_session_is_not_told_what_it_already_said(self):
        seat = rt.Seat(name="a", role="critic", provider="codex", session_id="thread-7")
        seat.turns.append({"round": 1, "text": "내 1회차 주장"})
        prompt = rt._cross_prompt("안건", seat, [("b", "b 의 말")], 2)
        self.assertNotIn("내 1회차 주장", prompt)
        self.assertIn("b 의 말", prompt)  # 남이 한 말은 세션에 없으므로 늘 넣는다


class TestStance(unittest.TestCase):
    def test_reads_the_declared_line(self):
        self.assertEqual(rt.read_stance("긴 논증\n\nSTANCE: MODIFY"), "MODIFY")

    def test_reads_it_through_markdown_emphasis(self):
        self.assertEqual(rt.read_stance("**STANCE: WITHDRAW**"), "WITHDRAW")

    def test_absent_line_is_absent_not_guessed(self):
        self.assertEqual(rt.read_stance("나는 이 제안에 전적으로 동의한다"), "")

    def test_last_line_wins_when_the_seat_repeats_itself(self):
        self.assertEqual(rt.read_stance("STANCE: MAINTAIN\n다시 생각했다\nSTANCE: WITHDRAW"), "WITHDRAW")


class RoundTableBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)


class TestConvene(RoundTableBase):
    def test_every_seat_speaks_every_round(self):
        model = Scripted()
        result = rt.convene(self.root, "캐시를 어디에 둘까", rt.parse_seats(["a", "b", "c"]), rounds=2, complete=model)
        self.assertEqual(len(result["turns"]), 6)
        self.assertTrue(all(turn["ok"] for turn in result["turns"]))

    def test_cross_round_carries_both_memories(self):
        """자기 앞 회차와 남의 최신 입장 — 둘 중 하나라도 빠지면 토론이 아니라 재출제다."""
        model = Scripted(answers={"a": ["a 의 최초 입장", "a 의 재반론\nSTANCE: MODIFY"], "b": ["b 의 최초 입장"]})
        rt.convene(self.root, "안건", rt.parse_seats(["a", "b"]), rounds=2, complete=model)
        second = model.prompts("a")[1]
        self.assertIn("a 의 최초 입장", second)  # 자기가 한 말
        self.assertIn("b 의 최초 입장", second)  # 상대가 한 말
        self.assertIn("STANCE", second)  # 입장 줄을 요구했다

    def test_first_round_carries_no_other_seat(self):
        """1회차는 독립 분석이다 — 남의 입장이 새면 첫 발언이 서로를 베낀다."""
        model = Scripted(answers={"a": ["a 의 최초 입장"], "b": ["b 의 최초 입장"]})
        rt.convene(self.root, "안건", rt.parse_seats(["a", "b"]), rounds=1, complete=model)
        self.assertNotIn("b 의 최초 입장", model.prompts("a")[0])

    def test_a_dead_seat_does_not_close_the_table(self):
        model = Scripted(boom={"b"})
        result = rt.convene(self.root, "안건", rt.parse_seats(["a", "b", "c"]), rounds=2, complete=model)
        self.assertEqual([row["seat"] for row in result["failed"]], ["b"])
        self.assertEqual({turn["seat"] for turn in result["turns"] if turn["ok"] and turn["round"] == 2}, {"a", "c"})

    def test_a_single_survivor_gets_no_cross_round(self):
        model = Scripted(boom={"b", "c"})
        result = rt.convene(self.root, "안건", rt.parse_seats(["a", "b", "c"]), rounds=3, complete=model)
        self.assertEqual({turn["round"] for turn in result["turns"]}, {1})

    def test_the_table_reports_how_long_it_took(self):
        """값 줄의 소요는 여기서 온다 — 이 키를 빼면 화면에서 시간만 조용히 사라진다.

        표시 쪽 시험은 자기가 지은 dict 를 쓰므로 생산 쪽에서 `secs` 를 빼도 안 떨어진다.
        26-08-14 에 그 구멍으로 기준 하나가 미충족인 채 시험 전부가 통과했다.
        """
        model = Scripted(delay=0.05)
        result = rt.convene(self.root, "안건", rt.parse_seats(["a", "b"]), rounds=2, complete=model)
        self.assertIsInstance(result["secs"], float)
        self.assertGreaterEqual(result["secs"], 0.1)  # 회차 둘 × 좌석당 0.05초, 좌석은 나란히 돈다

    def test_stances_come_only_from_cross_rounds(self):
        model = Scripted(answers={"a": ["1회차\nSTANCE: WITHDRAW", "2회차\nSTANCE: MODIFY"]})
        result = rt.convene(self.root, "안건", rt.parse_seats(["a", "b"]), rounds=2, complete=model)
        self.assertEqual(result["stances"]["a"], "MODIFY")

    def test_transcript_lands_on_the_ledger_under_one_thread_per_seat(self):
        run_id = orc.run_create(self.root, "원탁")["id"]
        rt.convene(self.root, "안건", rt.parse_seats(["a", "b"]), rounds=2, run_id=run_id, complete=Scripted())
        mail = orc.inbox(self.root, run_id)
        self.assertEqual(len({row["thread_id"] for row in mail}), 2)
        self.assertEqual(len([row for row in mail if row["sender"] == "a"]), 2)

    def test_seatless_table_is_refused(self):
        with self.assertRaises(ValueError):
            rt.convene(self.root, "안건", [], complete=Scripted())


class TestCliSeatInAConvening(RoundTableBase):
    """CLI 좌석이 실제 판에서 도는가 — 세션이 붙고, 2회차가 그것을 이어받는가."""

    def convene_with_fake_cli(self):
        from unittest import mock

        turns: list[tuple[str, str]] = []  # (넘긴 세션 id, 프롬프트)

        class FakePeer:
            def __init__(self, root, timeout_s=0.0):
                self.root = root

            def turn(self, spec, prompt, session_id=""):
                turns.append((session_id, prompt))
                from asgard.agent.runtime import PeerTurnResult

                return PeerTurnResult(f"{spec.runtime} 의 말\nSTANCE: MAINTAIN", "sess-1", (), 0)

        seats = rt.parse_seats(["a:codex", "b:cursor"])
        with mock.patch("asgard.agent.runtime.CliPeerRuntime", FakePeer):
            result = rt.convene(self.root, "안건", seats, rounds=2)
        return seats, turns, result

    def test_the_session_lands_on_the_seat_and_the_next_round_resumes_it(self):
        seats, turns, _result = self.convene_with_fake_cli()
        self.assertEqual([seat.session_id for seat in seats], ["sess-1", "sess-1"])
        self.assertEqual([session for session, _prompt in turns[:2]], ["", ""])  # 1회차는 새 세션
        self.assertEqual([session for session, _prompt in turns[2:]], ["sess-1", "sess-1"])

    def test_the_resumed_round_carries_the_others_but_not_itself(self):
        _seats, turns, _result = self.convene_with_fake_cli()
        second = [prompt for session, prompt in turns if session][0]
        self.assertIn("said]", second)  # 남이 한 말은 들어간다
        self.assertNotIn("[you said", second)  # 자기 말은 세션에 이미 있다

    def test_the_table_still_reads_the_stance(self):
        _seats, _turns, result = self.convene_with_fake_cli()
        self.assertEqual(set(result["stances"].values()), {"MAINTAIN"})


class TestServeRemembersItsThread(RoundTableBase):
    """`siege serve` 좌석의 기억 — 회차를 거듭해도 자기가 무엇을 주장했는지 안다."""

    def setUp(self) -> None:
        super().setUp()
        self.run_id = orc.run_create(self.root, "토론")["id"]

    def test_thread_history_is_replayed_with_the_speaker(self):
        first = orc.ask(self.root, self.run_id, "1회차 물음", recipient="critic", thread_id="t1")
        orc.reply(self.root, first["id"], "1회차 내 답")
        second = orc.ask(self.root, self.run_id, "2회차 물음", recipient="critic", thread_id="t1")
        history = siege_serve._history(self.root, self.run_id, "critic", dict(second, thread_id="t1"))
        self.assertIn("1회차 물음", history)
        self.assertIn("[you] 1회차 내 답", history)
        self.assertNotIn("2회차 물음", history)  # 지금 답할 물음은 프롬프트에 이미 들어간다

    def test_no_thread_means_no_history(self):
        message = orc.ask(self.root, self.run_id, "실 없는 물음", recipient="critic")
        self.assertEqual(siege_serve._history(self.root, self.run_id, "critic", message), "")

    def test_threadless_mail_does_not_pool_into_one_conversation(self):
        orc.ask(self.root, self.run_id, "남의 물음 하나", recipient="critic")
        orc.ask(self.root, self.run_id, "남의 물음 둘", recipient="critic")
        self.assertEqual(orc.thread(self.root, self.run_id, ""), [])


class TestSkillReach(unittest.TestCase):
    """어느 과업에 붙는가 — 양방향으로 잡는다. 한쪽만 재면 오탐과 구멍이 번갈아 난다."""

    def picked(self, task: str) -> set[str]:
        from asgard.templates.siege import resolve_siege_skills

        return {name for name, _body in resolve_siege_skills(task)}

    def test_a_debate_request_reaches_the_table(self):
        for task in ("원탁회의 열어서 정해줘", "이 설계 토론해보자", "let's debate the migration order"):
            self.assertIn("asgard-roundtable", self.picked(task), task)

    def test_plain_fan_out_does_not_drag_the_table_along(self):
        picked = self.picked("dispatch these units in parallel")
        self.assertIn("asgard-siege", picked)
        self.assertNotIn("asgard-roundtable", picked)

    def test_a_debate_alone_does_not_drag_the_ledger_along(self):
        self.assertEqual(self.picked("이 방안에 반대 의견을 듣고 싶다"), {"asgard-roundtable"})

    def test_ordinary_code_words_reach_neither(self):
        for task in ("fix the argument parser", "rename the dispatcher module"):
            self.assertEqual(self.picked(task), set(), task)


class TestSkillIsCarried(unittest.TestCase):
    def test_the_registry_serves_the_round_table_skill(self):
        from asgard.skill_registry.catalog import show_skill, skills

        self.assertIn("asgard-roundtable", {row["name"] for row in skills(os.getcwd())})
        self.assertIn("siege roundtable", show_skill(os.getcwd(), "asgard-roundtable") or "")

    def test_the_siege_skill_documents_the_verb(self):
        from asgard.templates.siege import SIEGE_SKILL_MD

        self.assertIn("asgard siege roundtable", SIEGE_SKILL_MD)


if __name__ == "__main__":
    unittest.main()
