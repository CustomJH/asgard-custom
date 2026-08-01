"""Bifrost 오케스트레이션 계층 — DAG 준비도·회로 차단·배달 재생·왕복.

실행: uv run pytest tests/test_orchestration.py

여기서 지키는 계약 여섯 (틀리면 코디네이터가 조용히 잘못된 판단을 한다):
  · 준비도는 의존에서만 도출된다 — 호출자가 ready 를 적어 넣을 수 없다.
  · 연속 실패 3회면 회로가 끊기고, 그 뒤의 배차는 거부된다.
  · 배달 묶음은 ack 전까지 같은 내용으로 재생된다.
  · 종류 필터는 대기를 깨울지만 정하고, 묶음의 내용은 거르지 않는다.
  · 정산 없이 사라진 시도는 회수되어 그 Task 가 다시 배차된다.
  · 돌 수 없는 Task(blocked)와 닫힌 Run 에는 배차가 열리지 않는다.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import orchestration as orc  # noqa: E402
from asgard.orchestration import model, strategy  # noqa: E402


def found(row: dict | None) -> dict:
    """조회가 값을 냈는지 확인하고 그대로 넘긴다.

    `task_show`·`run_show`·`dispatch_show` 는 없는 id 에 None 을 낸다. 그 결과를 바로
    첨자하면 TypeError 만 나고 무엇을 못 찾았는지가 안 남는다.
    """
    assert row is not None, "조회 결과가 없다"
    return row


class OrchestrationBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        # `self.run` 으로 두면 unittest.TestCase.run 메서드를 인스턴스 속성으로 덮는다.
        # 런타임에는 run() 이 이미 진입한 뒤라 통과하지만 타입 검사는 87건을 낸다.
        self.run_row = orc.run_create(self.root, "test objective", quest_id="q-1")


class TestTaskDag(OrchestrationBase):
    def test_task_without_deps_is_ready(self):
        task = orc.task_create(self.root, self.run_row["id"], "standalone")
        self.assertEqual(task["status"], "ready")

    def test_dependent_task_waits_then_becomes_ready(self):
        first = orc.task_create(self.root, self.run_row["id"], "first")
        second = orc.task_create(self.root, self.run_row["id"], "second", deps=[first["id"]])
        self.assertEqual(second["status"], "pending")

        dispatch = orc.open_dispatch(self.root, first["id"])
        orc.dispatch_settle(self.root, dispatch["id"], "succeeded")
        self.assertEqual(found(orc.task_show(self.root, second["id"]))["status"], "ready")

    def test_failed_dependency_blocks_downstream(self):
        first = orc.task_create(self.root, self.run_row["id"], "first")
        second = orc.task_create(self.root, self.run_row["id"], "second", deps=[first["id"]])
        for _ in range(model.MAX_ATTEMPTS):
            dispatch = orc.open_dispatch(self.root, first["id"])
            orc.dispatch_settle(self.root, dispatch["id"], "failed")
        self.assertEqual(found(orc.task_show(self.root, first["id"]))["status"], "failed")
        self.assertEqual(found(orc.task_show(self.root, second["id"]))["status"], "blocked")

    def test_chain_propagates_in_one_refresh(self):
        """A→B→C 로 의존이 이어질 때 A 완료 한 번에 B 까지 열린다 — 재도출이 한 번만 돌면 C 가 늦는다."""
        a = orc.task_create(self.root, self.run_row["id"], "a")
        b = orc.task_create(self.root, self.run_row["id"], "b", deps=[a["id"]])
        c = orc.task_create(self.root, self.run_row["id"], "c", deps=[b["id"]])
        dispatch = orc.open_dispatch(self.root, a["id"])
        orc.dispatch_settle(self.root, dispatch["id"], "succeeded")
        self.assertEqual(found(orc.task_show(self.root, b["id"]))["status"], "ready")
        self.assertEqual(found(orc.task_show(self.root, c["id"]))["status"], "pending")

    def test_unknown_dependency_is_rejected(self):
        with self.assertRaises(orc.OrchestrationError):
            orc.task_create(self.root, self.run_row["id"], "orphan", deps=["task_nope"])

    def test_ready_filter_is_the_coordinator_worklist(self):
        first = orc.task_create(self.root, self.run_row["id"], "first")
        orc.task_create(self.root, self.run_row["id"], "second", deps=[first["id"]])
        ready = orc.task_list(self.root, self.run_row["id"], ready=True)
        self.assertEqual([t["id"] for t in ready], [first["id"]])


class TestCircuitBreaker(OrchestrationBase):
    def test_three_failures_close_the_task(self):
        task = orc.task_create(self.root, self.run_row["id"], "flaky")
        for attempt in range(1, model.MAX_ATTEMPTS + 1):
            dispatch = orc.open_dispatch(self.root, task["id"])
            self.assertEqual(dispatch["attempt"], attempt)
            settled = orc.dispatch_settle(self.root, dispatch["id"], "failed")
        self.assertEqual(settled["task"]["status"], "failed")
        with self.assertRaises(orc.OrchestrationError):
            orc.open_dispatch(self.root, task["id"])

    def test_history_keeps_every_attempt(self):
        task = orc.task_create(self.root, self.run_row["id"], "flaky")
        for _ in range(2):
            dispatch = orc.open_dispatch(self.root, task["id"])
            orc.dispatch_settle(self.root, dispatch["id"], "failed")
        history = orc.dispatch_history(self.root, task["id"])
        self.assertEqual([h["attempt"] for h in history], [1, 2])
        self.assertTrue(all(h["state"] == "failed" for h in history))

    def test_success_after_failure_completes(self):
        task = orc.task_create(self.root, self.run_row["id"], "retried")
        first = orc.open_dispatch(self.root, task["id"])
        orc.dispatch_settle(self.root, first["id"], "failed")
        second = orc.open_dispatch(self.root, task["id"])
        settled = orc.dispatch_settle(self.root, second["id"], "succeeded")
        self.assertEqual(settled["task"]["status"], "completed")

    def test_stopped_dispatch_does_not_close_the_task(self):
        task = orc.task_create(self.root, self.run_row["id"], "stopped")
        dispatch = orc.open_dispatch(self.root, task["id"])
        orc.dispatch_mark(self.root, dispatch["id"], "outcome_unknown")
        self.assertEqual(found(orc.task_show(self.root, task["id"]))["status"], "dispatched")


class TestReclaim(OrchestrationBase):
    """정산 없이 사라진 시도를 회수하는가 (감사 높음-3).

    이것 없이는 크래시 한 번이 그 Task 를 영구히 막는다: Dispatch 는 `ready`, Task 는
    `dispatched` 로 남고 `open_dispatch` 는 활성 시도가 있다며 재배차를 거부한다.
    """

    def test_abandoned_dispatch_is_reclaimed_and_the_task_dispatches_again(self):
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        abandoned = orc.open_dispatch(self.root, task["id"])
        with self.assertRaises(orc.OrchestrationError):
            orc.open_dispatch(self.root, task["id"])  # 죽은 워커가 자리를 막고 있다

        reclaimed = orc.reclaim(self.root, self.run_row["id"])
        self.assertEqual(reclaimed, [abandoned["id"]])
        self.assertEqual(found(orc.dispatch_show(self.root, dispatch_id=abandoned["id"]))["state"], "outcome_unknown")
        self.assertEqual(found(orc.task_show(self.root, task["id"]))["status"], "ready")

        retry = orc.open_dispatch(self.root, task["id"])
        self.assertEqual(retry["attempt"], 2, "회수가 시도 횟수를 지웠다 — 회로 차단이 무력해진다")

    def test_reclaim_leaves_settled_dispatches_alone(self):
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        orc.dispatch_settle(self.root, dispatch["id"], "succeeded")
        self.assertEqual(orc.reclaim(self.root, self.run_row["id"]), [])
        self.assertEqual(found(orc.task_show(self.root, task["id"]))["status"], "completed")

    def test_closing_a_run_reclaims_its_open_dispatches(self):
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        orc.run_close(self.root, self.run_row["id"])
        self.assertEqual(found(orc.dispatch_show(self.root, dispatch_id=dispatch["id"]))["state"], "outcome_unknown")

    def test_reclaim_respects_the_age_window(self):
        """방금 연 시도는 살아 있을 수 있다 — 시간 창을 주면 그것은 회수하지 않는다."""
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        orc.open_dispatch(self.root, task["id"])
        self.assertEqual(orc.reclaim(self.root, self.run_row["id"], older_than=3600), [])
        self.assertEqual(found(orc.task_show(self.root, task["id"]))["status"], "dispatched")


class TestUndispatchable(OrchestrationBase):
    """배차가 열리면 안 되는 자리 (감사 높음-2 · 보통-7)."""

    def test_blocked_task_refuses_dispatch(self):
        """선행이 실패해 blocked 인 Task 에 배차하면 '의존이 실패했다' 는 사실이 장부에서 사라진다."""
        first = orc.task_create(self.root, self.run_row["id"], "first")
        second = orc.task_create(self.root, self.run_row["id"], "second", deps=[first["id"]])
        for _ in range(model.MAX_ATTEMPTS):
            dispatch = orc.open_dispatch(self.root, first["id"])
            orc.dispatch_settle(self.root, dispatch["id"], "failed")
        self.assertEqual(found(orc.task_show(self.root, second["id"]))["status"], "blocked")

        with self.assertRaises(orc.OrchestrationError):
            orc.open_dispatch(self.root, second["id"])
        self.assertEqual(found(orc.task_show(self.root, second["id"]))["status"], "blocked")

    def test_closed_run_refuses_new_work(self):
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        orc.run_close(self.root, self.run_row["id"])
        with self.assertRaises(orc.OrchestrationError):
            orc.task_create(self.root, self.run_row["id"], "늦게 온 일감")
        with self.assertRaises(orc.OrchestrationError):
            orc.open_dispatch(self.root, task["id"])

    def test_resolved_task_cannot_be_revived(self):
        """끝난 것은 되살아나지 않는다 — 되살리면 끝난 일이 다시 배차된다."""
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        orc.dispatch_settle(self.root, dispatch["id"], "succeeded")
        with self.assertRaises(orc.OrchestrationError):
            orc.task_update(self.root, task["id"], status="pending")


class TestRetryBudget(OrchestrationBase):
    """재시도 상한은 설정값 하나를 본다 (감사 보통-4).

    배차와 정산이 다른 수를 보면 실제로 다섯 번 돌았는데 장부에는 세 번만 남는다.
    """

    def test_configured_max_attempts_governs_both_dispatch_and_settlement(self):
        orc.set_meta(self.root, orc.META_MAX_ATTEMPTS, "5")
        task = orc.task_create(self.root, self.run_row["id"], "flaky")
        for attempt in range(1, 6):
            dispatch = orc.open_dispatch(self.root, task["id"])
            self.assertEqual(dispatch["attempt"], attempt)
            settled = orc.dispatch_settle(self.root, dispatch["id"], "failed")
        self.assertEqual(settled["task"]["status"], "failed")
        with self.assertRaises(orc.OrchestrationError):
            orc.open_dispatch(self.root, task["id"])


class TestReadDoesNotCreate(unittest.TestCase):
    """조회가 유령 장부를 만들지 않는가 (감사 보통-1).

    읽기 전용이라고 문서에 적힌 명령이 파일을 만들면, 잘못된 디렉터리에서 친 조회가 그 자리에
    빈 DB 를 남기고 다음 조회를 계속 속인다.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_listing_an_empty_project_creates_no_file(self):
        self.assertEqual(orc.run_list(self.root), [])
        self.assertFalse(orc.exists(self.root))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard")))

    def test_writing_creates_the_ledger(self):
        orc.run_create(self.root, "첫 Run")
        self.assertTrue(orc.exists(self.root))


class TestStaleReports(OrchestrationBase):
    """죽은 시도의 뒤늦은 보고가 살아 있는 Task 를 흔들지 않는가 (감사 발견 3건).

    셋 다 같은 사고를 낸다: 이미 끝난 일이 다시 배차되거나, 남의 일이 끝난 것으로 표시된다.
    """

    def _abandoned_then_retried(self) -> tuple[dict, dict, dict]:
        """버려진 시도 하나와 그 뒤의 재시도 — 죽은 시도가 살아 돌아오는 유일한 실제 경로.

        `outcome_unknown` 은 terminal 이 아니라서(자원이 살아 있을 수 있다) 나중에 보고할 수
        있다. 그 늦은 보고가 이 묶음의 시험 대상이다.
        """
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        abandoned = orc.open_dispatch(self.root, task["id"])
        orc.dispatch_mark(self.root, abandoned["id"], "outcome_unknown")
        retry = orc.open_dispatch(self.root, task["id"], retry_of=abandoned["id"])
        return task, abandoned, retry

    def test_two_active_dispatches_on_one_task_are_refused(self):
        """살아 있는 시도가 있는데 또 열면 두 워커가 같은 파일을 동시에 고친다."""
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        orc.open_dispatch(self.root, task["id"])
        with self.assertRaises(orc.OrchestrationError):
            orc.open_dispatch(self.root, task["id"])

    def test_settling_a_finished_dispatch_twice_is_refused(self):
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        orc.dispatch_settle(self.root, dispatch["id"], "succeeded")
        with self.assertRaises(orc.OrchestrationError):
            orc.dispatch_settle(self.root, dispatch["id"], "failed")

    def test_late_failure_from_an_abandoned_attempt_does_not_reopen_the_task(self):
        task, abandoned, retry = self._abandoned_then_retried()
        orc.dispatch_settle(self.root, retry["id"], "succeeded")
        self.assertEqual(found(orc.task_show(self.root, task["id"]))["status"], "completed")

        stale = orc.dispatch_settle(self.root, abandoned["id"], "failed")
        self.assertEqual(stale["task"]["status"], "completed", "죽은 시도가 끝난 Task 를 되살렸다")
        self.assertEqual(stale["dispatch"]["outcome"], "failed", "자기 Dispatch 기록은 남아야 한다")

    def test_late_success_from_an_abandoned_attempt_does_not_complete_the_task(self):
        task, abandoned, _retry = self._abandoned_then_retried()
        orc.dispatch_settle(self.root, abandoned["id"], "succeeded")
        self.assertNotEqual(
            found(orc.task_show(self.root, task["id"]))["status"],
            "completed",
            "최신 시도가 아직 도는데 버려진 시도가 Task 를 끝냈다",
        )

    def test_worker_done_rejects_a_mismatched_task(self):
        mine = orc.task_create(self.root, self.run_row["id"], "mine")
        yours = orc.task_create(self.root, self.run_row["id"], "yours")
        dispatch = orc.open_dispatch(self.root, mine["id"])
        with self.assertRaises(orc.OrchestrationError):
            orc.worker_done(self.root, self.run_row["id"], yours["id"], dispatch["id"], "succeeded")
        self.assertEqual(found(orc.task_show(self.root, yours["id"]))["status"], "ready")
        self.assertEqual(found(orc.task_show(self.root, mine["id"]))["status"], "dispatched")

    def test_worker_done_rejects_a_mismatched_run(self):
        other = orc.run_create(self.root, "다른 Run", quest_id="q-other")
        task = orc.task_create(self.root, self.run_row["id"], "mine")
        dispatch = orc.open_dispatch(self.root, task["id"])
        with self.assertRaises(orc.OrchestrationError):
            orc.worker_done(self.root, other["id"], task["id"], dispatch["id"], "succeeded")
        self.assertEqual(found(orc.task_show(self.root, task["id"]))["status"], "dispatched")

    def test_a_rejected_worker_done_leaves_no_mail_and_no_settlement(self):
        """신원이 안 맞으면 정산도 메일도 없어야 한다 — 둘이 한 트랜잭션인 이유."""
        task = orc.task_create(self.root, self.run_row["id"], "mine")
        dispatch = orc.open_dispatch(self.root, task["id"])
        before = len(orc.inbox(self.root, self.run_row["id"], limit=50))
        with self.assertRaises(orc.OrchestrationError):
            orc.worker_done(self.root, self.run_row["id"], "task_ghost", dispatch["id"], "succeeded")
        self.assertEqual(len(orc.inbox(self.root, self.run_row["id"], limit=50)), before)
        self.assertEqual(found(orc.dispatch_show(self.root, dispatch_id=dispatch["id"]))["state"], "ready")

    def test_worker_done_cannot_be_sent_twice(self):
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        orc.worker_done(self.root, self.run_row["id"], task["id"], dispatch["id"], "succeeded")
        with self.assertRaises(orc.OrchestrationError):
            orc.worker_done(self.root, self.run_row["id"], task["id"], dispatch["id"], "succeeded")
        reports = [m for m in orc.inbox(self.root, self.run_row["id"], limit=50) if m["type"] == "worker_done"]
        self.assertEqual(len(reports), 1)


class TestRunBindingRace(OrchestrationBase):
    def test_concurrent_bind_yields_one_run(self):
        """같은 퀘스트에 동시에 bind 해도 Run 은 하나다 (감사가 24스레드로 재현한 경쟁)."""
        barrier = threading.Barrier(16)
        seen: list[str] = []
        lock = threading.Lock()

        def bind():
            barrier.wait()
            run = orc.run_bind(self.root, "race-q", "동시 bind")
            with lock:
                seen.append(run["id"])

        threads = [threading.Thread(target=bind) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(set(seen)), 1, f"Run 이 갈렸다: {set(seen)}")
        opened = [r for r in orc.run_list(self.root, status="open") if r["quest_id"] == "race-q"]
        self.assertEqual(len(opened), 1)


class TestDelivery(OrchestrationBase):
    def test_delivery_replays_until_acked(self):
        orc.send(self.root, self.run_row["id"], "status", subject="one")
        first = orc.check(self.root, self.run_row["id"])
        second = orc.check(self.root, self.run_row["id"])
        self.assertEqual(first["delivery_id"], second["delivery_id"])
        self.assertEqual(second["count"], 1)

        emptied = orc.check(self.root, self.run_row["id"], ack=first["delivery_id"])
        self.assertEqual(emptied["count"], 0)

    def test_delivery_is_capped(self):
        for i in range(model.DELIVERY_CAP + 5):
            orc.send(self.root, self.run_row["id"], "status", subject=f"m{i}")
        batch = orc.check(self.root, self.run_row["id"])
        self.assertEqual(batch["count"], model.DELIVERY_CAP)

    def test_type_filter_gates_the_wake_not_the_batch(self):
        """heartbeat 만 있으면 안 깨고, worker_done 이 붙으면 heartbeat 까지 함께 나온다."""
        orc.send(self.root, self.run_row["id"], "heartbeat", subject="alive")
        quiet = orc.check(self.root, self.run_row["id"], types=("worker_done",))
        self.assertEqual(quiet["count"], 0)

        orc.send(self.root, self.run_row["id"], "worker_done", subject="done")
        woken = orc.check(self.root, self.run_row["id"], types=("worker_done",))
        self.assertEqual([m["type"] for m in woken["messages"]], ["heartbeat", "worker_done"])

    def test_type_filter_wakes_past_the_delivery_cap(self):
        """상한(50)을 넘긴 자리의 worker_done 도 대기를 깨우는가 (감사 높음-4).

        워커가 5분마다 heartbeat 를 보내는 것이 정상 계약이라 긴 wave 에서는 50건이 쉽게 쌓인다.
        묶음을 먼저 자르고 그 안에서 종류를 찾으면 51번째 완료 보고가 영영 안 보이고, 묶지
        않으니 ack 도 안 되어 우편함이 스스로 풀리지 않는다.
        """
        for i in range(model.DELIVERY_CAP):
            orc.send(self.root, self.run_row["id"], "heartbeat", subject=f"alive{i}")
        quiet = orc.check(self.root, self.run_row["id"], types=("worker_done",))
        self.assertEqual(quiet["count"], 0, "heartbeat 만 있는데 깨어났다")

        orc.send(self.root, self.run_row["id"], "worker_done", subject="상한 뒤의 완료")
        woken = orc.check(self.root, self.run_row["id"], types=("worker_done",), wait=True, timeout_ms=300)
        self.assertEqual(woken["count"], model.DELIVERY_CAP, "51번째 완료 보고가 대기를 못 깨웠다")
        self.assertIsNotNone(woken["delivery_id"], "묶지 않으면 ack 도 안 되어 우편함이 안 풀린다")

    def test_peek_does_not_claim(self):
        orc.send(self.root, self.run_row["id"], "status", subject="one")
        peeked = orc.check(self.root, self.run_row["id"], peek=True)
        self.assertEqual(peeked["count"], 1)
        self.assertIsNone(peeked["delivery_id"])
        claimed = orc.check(self.root, self.run_row["id"])
        self.assertIsNotNone(claimed["delivery_id"])

    def test_wait_returns_empty_on_timeout(self):
        started = time.monotonic()
        batch = orc.check(self.root, self.run_row["id"], wait=True, timeout_ms=200)
        self.assertEqual(batch["count"], 0)
        self.assertGreaterEqual(time.monotonic() - started, 0.15)

    def test_wait_wakes_on_arrival(self):
        def deliver():
            time.sleep(0.1)
            orc.send(self.root, self.run_row["id"], "worker_done", subject="late")

        threading.Thread(target=deliver, daemon=True).start()
        batch = orc.check(self.root, self.run_row["id"], types=("worker_done",), wait=True, timeout_ms=5000)
        self.assertEqual(batch["count"], 1)


class TestRoundTrip(OrchestrationBase):
    def test_ask_then_reply(self):
        question = orc.ask(self.root, self.run_row["id"], "포트를 바꿔도 되나?", options=["yes", "no"])
        self.assertIsNone(question["answered_at"])
        self.assertEqual(orc.pending_questions(self.root, self.run_row["id"])[0]["id"], question["id"])

        orc.reply(self.root, question["id"], "yes")
        answered = orc.wait_answer(self.root, question["id"], timeout_ms=100)
        self.assertEqual(answered["answer"], "yes")
        self.assertEqual(orc.pending_questions(self.root, self.run_row["id"]), [])

    def test_second_reply_is_rejected(self):
        question = orc.ask(self.root, self.run_row["id"], "질문")
        orc.reply(self.root, question["id"], "first")
        with self.assertRaises(orc.OrchestrationError):
            orc.reply(self.root, question["id"], "second")

    def test_ask_timeout_leaves_the_question_pending(self):
        question = orc.ask(self.root, self.run_row["id"], "느린 질문", timeout_ms=150)
        self.assertIsNone(question["answered_at"])
        self.assertEqual(len(orc.pending_questions(self.root, self.run_row["id"])), 1)


class TestWorkerDone(OrchestrationBase):
    def test_worker_done_settles_dispatch_and_task(self):
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"], worker="u1")
        reported = orc.worker_done(
            self.root,
            self.run_row["id"],
            task["id"],
            dispatch["id"],
            "succeeded",
            body="고쳤다",
            files_modified=["a.py", "b.py"],
        )
        self.assertEqual(reported["task"]["status"], "completed")
        self.assertEqual(reported["dispatch"]["state"], "settled")
        self.assertEqual(reported["dispatch"]["files_modified"], ["a.py", "b.py"])
        self.assertEqual(reported["message"]["type"], "worker_done")

    def test_failed_outcome_is_recorded_as_failure(self):
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        reported = orc.worker_done(self.root, self.run_row["id"], task["id"], dispatch["id"], "failed", body="안 됨")
        self.assertEqual(reported["dispatch"]["outcome"], "failed")
        self.assertEqual(reported["message"]["outcome"], "failed")

    def test_bad_outcome_is_rejected(self):
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        with self.assertRaises(orc.OrchestrationError):
            orc.worker_done(self.root, self.run_row["id"], task["id"], dispatch["id"], "maybe")


class TestGates(OrchestrationBase):
    def test_gate_open_then_resolve(self):
        gate = orc.gate_create(self.root, self.run_row["id"], "둘 중 무엇?", options=["a", "b"])
        self.assertEqual(gate["status"], "open")
        self.assertEqual(orc.gate_list(self.root, run_id=self.run_row["id"], status="open")[0]["id"], gate["id"])

        resolved = orc.gate_resolve(self.root, gate["id"], "a")
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["resolution"], "a")
        self.assertEqual(orc.gate_list(self.root, run_id=self.run_row["id"], status="open"), [])

    def test_resolving_twice_is_rejected(self):
        gate = orc.gate_create(self.root, self.run_row["id"], "질문")
        orc.gate_resolve(self.root, gate["id"], "a")
        with self.assertRaises(orc.OrchestrationError):
            orc.gate_resolve(self.root, gate["id"], "b")


class TestRunBinding(OrchestrationBase):
    def test_bind_reuses_the_open_run_for_a_quest(self):
        again = orc.run_bind(self.root, "q-1", "다시")
        self.assertEqual(again["id"], self.run_row["id"])

    def test_bind_creates_when_absent(self):
        fresh = orc.run_bind(self.root, "q-2", "새 퀘스트")
        self.assertNotEqual(fresh["id"], self.run_row["id"])
        self.assertEqual(fresh["quest_id"], "q-2")

    def test_closed_run_is_not_reused(self):
        orc.run_close(self.root, self.run_row["id"])
        fresh = orc.run_bind(self.root, "q-1", "다시 연다")
        self.assertNotEqual(fresh["id"], self.run_row["id"])


class TestPureJudgement(unittest.TestCase):
    """저장소 없이 도는 절반 — DB 를 세우지 않고 판정만 확인한다."""

    def test_topo_waves_groups_independent_work(self):
        waves = model.topo_waves(["a", "b", "c"], {"c": ["a", "b"]})
        self.assertEqual(waves, [["a", "b"], ["c"]])

    def test_topo_waves_rejects_cycles(self):
        with self.assertRaises(model.OrchestrationError):
            model.topo_waves(["a", "b"], {"a": ["b"], "b": ["a"]})

    def test_topo_waves_ignores_unknown_deps(self):
        self.assertEqual(model.topo_waves(["a"], {"a": ["ghost"]}), [["a"]])

    def test_resolved_tasks_do_not_move(self):
        self.assertEqual(model.task_status_for("completed", ["failed"]), "completed")
        self.assertEqual(model.task_status_for("failed", ["completed"]), "failed")

    def test_dispatched_task_is_not_reopened_by_dep_change(self):
        self.assertEqual(model.task_status_for("dispatched", ["failed"]), "dispatched")

    def test_circuit_breaks_at_the_limit(self):
        self.assertFalse(model.circuit_broken(model.MAX_ATTEMPTS - 1))
        self.assertTrue(model.circuit_broken(model.MAX_ATTEMPTS))


class TestShapeRouting(unittest.TestCase):
    """형상 선택 — 어떤 신호가 어떤 모양을 부르는가. 순수 함수라 저장소가 필요 없다."""

    def test_no_write_means_no_orchestration(self):
        self.assertEqual(strategy.choose(write_expected=False)["shape"], "direct")

    def test_units_make_a_graph(self):
        self.assertEqual(strategy.choose(unit_count=3)["shape"], "graph")

    def test_two_specialists_make_a_squad(self):
        self.assertEqual(strategy.choose(specialists=["freyja", "thor"])["shape"], "squad")

    def test_one_specialist_stays_single(self):
        """전문가 하나면 Worker 가 자기 dispatch 툴로 부르는 편이 싸다 — 편대를 안 세운다."""
        self.assertEqual(strategy.choose(specialists=["thor"], task_class="standard")["shape"], "single")

    def test_units_outrank_specialists(self):
        """일감이 여럿이면 손이 여럿인 것보다 그래프가 먼저다 — 파일 경계가 실제 제약이다."""
        self.assertEqual(strategy.choose(unit_count=2, specialists=["freyja", "thor"])["shape"], "graph")

    def test_explicit_parallel_on_deep_work_plans_a_graph(self):
        self.assertEqual(strategy.choose(parallel_requested=True, task_class="deep")["shape"], "graph")

    def test_every_shape_is_declared(self):
        # 인자 종류가 케이스마다 달라서 리터럴 그대로 두면 값 타입이 union 으로 좁혀진다.
        cases: list[dict[str, Any]] = [
            {"write_expected": False},
            {"unit_count": 2},
            {"specialists": ["a", "b"]},
            {},
        ]
        for case in cases:
            self.assertIn(strategy.choose(**case)["shape"], strategy.SHAPES)

    def test_decision_carries_a_reason(self):
        self.assertTrue(strategy.choose(unit_count=2)["why"])


class TestShapeRecording(OrchestrationBase):
    def test_shape_is_written_to_the_run(self):
        orc.run_shape(self.root, self.run_row["id"], "graph", "배정 단위 3개")
        shown = found(orc.run_show(self.root, self.run_row["id"]))
        self.assertEqual(shown["shape"], "graph")
        self.assertEqual(shown["shape_why"], "배정 단위 3개")

    def test_shape_can_change_when_the_plan_arrives(self):
        orc.run_shape(self.root, self.run_row["id"], "single", "처음 판정")
        orc.run_shape(self.root, self.run_row["id"], "graph", "계획이 단위를 냈다")
        self.assertEqual(found(orc.run_show(self.root, self.run_row["id"]))["shape"], "graph")


if __name__ == "__main__":
    unittest.main()
