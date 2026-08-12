#!/usr/bin/env python3
"""`asgard siege serve` — 우편함 한 칸을 모델에게 잇는 자리.

여기서 지키는 계약 넷:
  · 자기 이름 앞으로 온 메일만 모델에게 간다 (남의 메일도, 주인 없는 메일도 안 건드린다).
  · `question` 은 그 메시지에 답이 달려야 한다 — 묻는 쪽의 `wait_answer` 가 그것으로 깨어난다.
  · 나머지는 발신자 앞으로 새 메일이 간다 — 답을 달 자리가 없기 때문이다.
  · 모델 호출이 실패하면 답을 지어내지 않고 escalation 을 남긴 뒤 그 묶음을 접는다.

실행: uv run pytest tests/test_siege_serve.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import orchestration as orc  # noqa: E402
from asgard.commands import siege_serve  # noqa: E402
from asgard.providers import PROVIDERS, ResolvedProvider  # noqa: E402

WHO = "codex-1"


def stub_provider() -> ResolvedProvider:
    """해석까지는 실물 자료구조로 — 시험이 검사하는 것은 호출 경로이지 자격 증명이 아니다."""
    return ResolvedProvider(profile=PROVIDERS["anthropic"], model="claude-test", source="test")


class ServeBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self._cwd = os.getcwd()
        os.makedirs(os.path.join(self.root, ".git"), exist_ok=True)  # _project_root 가 여기서 멈춘다
        os.chdir(self.root)
        self.addCleanup(os.chdir, self._cwd)
        self.run_id = orc.run_create(self.root, "bridge run", quest_id="q-serve")["id"]

    def serve(self, answer="답이다", **kwargs) -> int:
        """모델 자리에 정해진 문자열을 세우고 한 묶음만 처리한다."""
        with (
            mock.patch("asgard.providers.resolve", return_value=stub_provider()),
            mock.patch("asgard.agent.oneshot.complete_with", return_value=answer) as called,
        ):
            self.called = called
            return siege_serve.run_serve(self.run_id, who=WHO, once=True, **kwargs)

    def mailbox(self, recipient=""):
        return orc.check(self.root, self.run_id, recipient=recipient, peek=True)["messages"]


class TestRoundTrip(ServeBase):
    def test_a_question_comes_back_as_an_answer_on_that_message(self):
        question = orc.ask(self.root, self.run_id, "이 저장소는 무엇을 하나", sender="cc-1", recipient=WHO)
        self.assertEqual(self.serve("우편함을 모델에 잇는다"), 0)
        answered = orc.wait_answer(self.root, question["id"], timeout_ms=0)
        self.assertEqual(answered["answer"], "우편함을 모델에 잇는다")

    def test_the_model_reads_the_sender_and_the_body(self):
        orc.ask(self.root, self.run_id, "본문이 닿는가", sender="cc-1", recipient=WHO, options=["예", "아니오"])
        self.serve()
        user_prompt = self.called.call_args[0][3]
        self.assertIn("from: cc-1", user_prompt)
        self.assertIn("본문이 닿는가", user_prompt)
        self.assertIn("예 | 아니오", user_prompt)

    def test_other_mail_comes_back_to_its_sender(self):
        """질문이 아닌 메일에는 답을 달 자리가 없다 — 발신자 앞으로 새로 보낸다."""
        orc.send(self.root, self.run_id, "status", subject="상태 좀", sender="cc-1", recipient=WHO)
        self.serve("잘 돌고 있다")
        replies = [m for m in self.mailbox("cc-1") if m["sender"] == WHO]
        self.assertEqual([m["body"] for m in replies], ["잘 돌고 있다"])
        self.assertEqual(replies[0]["subject"], "re: 상태 좀")

    def test_the_batch_is_acked_so_it_does_not_replay(self):
        orc.ask(self.root, self.run_id, "한 번만 답해라", sender="cc-1", recipient=WHO)
        self.serve()
        self.assertEqual(orc.check(self.root, self.run_id, recipient=WHO)["count"], 0)


class TestWhatItLeavesAlone(ServeBase):
    def test_mail_for_someone_else_is_untouched(self):
        orc.ask(self.root, self.run_id, "남의 질문", sender="cc-1", recipient="other")
        self.serve()
        self.called.assert_not_called()
        self.assertEqual(orc.check(self.root, self.run_id, recipient="other")["count"], 1)

    def test_unaddressed_mail_is_left_for_the_coordinator(self):
        orc.ask(self.root, self.run_id, "주인 없는 질문", sender="cc-1")
        self.serve()
        self.called.assert_not_called()
        self.assertEqual(orc.check(self.root, self.run_id)["count"], 1)

    def test_a_question_a_person_already_answered_is_not_answered_twice(self):
        question = orc.ask(self.root, self.run_id, "이미 답이 있다", sender="cc-1", recipient=WHO)
        orc.reply(self.root, question["id"], "사람의 답")
        self.serve("모델의 답")
        self.called.assert_not_called()
        self.assertEqual(orc.wait_answer(self.root, question["id"], timeout_ms=0)["answer"], "사람의 답")

    def test_a_heartbeat_does_not_call_the_model(self):
        orc.send(self.root, self.run_id, "heartbeat", subject="살아 있다", sender="cc-1", recipient=WHO)
        self.serve()
        self.called.assert_not_called()


class TestWaiting(ServeBase):
    def test_once_with_a_wait_stands_until_the_mail_arrives(self):
        """답할 쪽을 먼저 세우고 뒤에 묻는 형태 — `--once` 만 보고 내려오면 그 순서가 안 선다."""
        import threading

        def post():
            time.sleep(0.4)
            orc.ask(self.root, self.run_id, "늦게 온 질문", sender="cc-1", recipient=WHO)

        writer = threading.Thread(target=post)
        writer.start()
        self.addCleanup(writer.join)
        self.serve("기다렸다 답했다", idle_timeout=10)
        self.called.assert_called_once()

    def test_once_without_a_wait_comes_straight_back(self):
        started = time.monotonic()
        self.assertEqual(self.serve(), 0)
        self.assertLess(time.monotonic() - started, 8)
        self.called.assert_not_called()


class TestRefusals(ServeBase):
    def test_an_empty_name_is_refused(self):
        """이름 없이 서면 `check` 가 우편함 전체를 잡아 코디네이터 앞 메일까지 모델에게 넘어간다."""
        self.assertEqual(siege_serve.run_serve(self.run_id, who="  "), 2)

    def test_an_unknown_run_is_refused(self):
        self.assertEqual(siege_serve.run_serve("run_ghost", who=WHO), 2)

    def test_a_provider_that_cannot_be_called_is_refused_before_standing(self):
        broken = ResolvedProvider(profile=PROVIDERS["anthropic"], model="", source="test", missing=["키가 없어요"])
        with mock.patch("asgard.providers.resolve", return_value=broken):
            self.assertEqual(siege_serve.run_serve(self.run_id, who=WHO, once=True), 2)


class TestModelFailure(ServeBase):
    def setUp(self) -> None:
        super().setUp()
        orc.ask(self.root, self.run_id, "답할 수 없는 것", sender="cc-1", recipient=WHO)
        with (
            mock.patch("asgard.providers.resolve", return_value=stub_provider()),
            mock.patch("asgard.agent.oneshot.complete_with", side_effect=RuntimeError("모델이 거절했다")),
        ):
            self.code = siege_serve.run_serve(self.run_id, who=WHO, once=True)

    def test_it_does_not_invent_an_answer(self):
        pending = orc.pending_questions(self.root, self.run_id)
        self.assertEqual([q["subject"] for q in pending], ["답할 수 없는 것"])

    def test_it_leaves_the_reason_in_the_mailbox(self):
        escalations = [m for m in self.mailbox() if m["type"] == "escalation"]
        self.assertEqual(len(escalations), 1)
        self.assertIn("모델이 거절했다", escalations[0]["subject"])

    def test_it_does_not_loop_on_the_same_message(self):
        """확인 처리를 안 하면 같은 메일이 재생되어 그 자리에서 영영 맴돈다."""
        self.assertEqual(self.code, 0)
        self.assertEqual(orc.check(self.root, self.run_id, recipient=WHO)["count"], 0)


if __name__ == "__main__":
    unittest.main()
