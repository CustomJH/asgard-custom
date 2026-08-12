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
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import orchestration as orc  # noqa: E402
from asgard.orchestration import model, store, strategy  # noqa: E402
from asgard.orchestration.store import connect  # noqa: E402


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
        # 정리는 LIFO 라 스레드 회수가 임시 디렉터리 삭제보다 **먼저** 돈다 — 순서가 뒤집히면
        # 남은 스레드가 이미 지워진 DB 를 열어 그 자체로 새 실패를 만든다.
        self._threads_before = set(threading.enumerate())
        self.addCleanup(self._join_stray_threads)
        # `self.run` 으로 두면 unittest.TestCase.run 메서드를 인스턴스 속성으로 덮는다.
        # 런타임에는 run() 이 이미 진입한 뒤라 통과하지만 타입 검사는 87건을 낸다.
        self.run_row = orc.run_create(self.root, "test objective", quest_id="q-1")

    def _join_stray_threads(self) -> None:
        """이 테스트가 띄운 스레드를 다음 테스트로 넘기지 않는다.

        여기 있는 테스트 몇은 daemon 스레드를 띄운다(`test_wait_wakes_on_arrival` 등). daemon
        은 프로세스를 붙잡지 않으므로 회수하지 않으면 다음 테스트가 도는 동안 그대로 산다 —
        `store._WRITE_LOCK` 은 프로세스 로컬이라 그 스레드는 같은 락을 두고 다음 테스트와
        경쟁한다. 26-08-02 감사가 관측한 간헐 실패 1건(`test_worker_done_cannot_be_sent_twice`
        의 첫 정산이 이미 settled 였다)의 성격은 끝내 규명되지 않았고(같은 프로세스 3,600회
        반복에서 재현 0), 그 상태에서 걸 수 있는 방어가 이것이다: **원인을 모르면 최소한
        테스트 사이의 상태 누수 경로를 닫는다.**

        살아남은 스레드는 통과시키지 않고 실패로 올린다. 조용히 넘기면 다음 실패가 엉뚱한
        테스트 이름을 달고 나타난다 — 이 방어가 막으려던 바로 그 형상이다.
        """
        for thread in threading.enumerate():
            if thread in self._threads_before or thread is threading.current_thread():
                continue
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive(), f"테스트가 스레드를 남겼다: {thread.name}")


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

    def test_unknown_outcomes_do_not_spend_the_failure_budget(self):
        """프로세스 재시작 횟수는 실패 횟수가 아니다 — 시도 이력은 남기되 회로에는 넣지 않는다."""
        task = orc.task_create(self.root, self.run_row["id"], "never failed")
        for _ in range(model.MAX_ATTEMPTS):
            dispatch = orc.open_dispatch(self.root, task["id"])
            orc.dispatch_mark(self.root, dispatch["id"], "outcome_unknown")

        retry = orc.open_dispatch(self.root, task["id"])
        self.assertEqual(retry["attempt"], model.MAX_ATTEMPTS + 1)
        settled = orc.dispatch_settle(self.root, retry["id"], "failed")
        self.assertEqual(settled["task"]["status"], "ready", "첫 실패를 네 번째 시도라는 이유로 접었다")

    def test_success_resets_the_consecutive_failure_count(self):
        """늦게 확인된 성공 뒤의 실패만 센다 — 결과 순서와 시도 총수는 같은 수가 아니다."""
        task = orc.task_create(self.root, self.run_row["id"], "eventually succeeded")
        first = orc.open_dispatch(self.root, task["id"])
        orc.dispatch_mark(self.root, first["id"], "outcome_unknown")
        second = orc.open_dispatch(self.root, task["id"])
        orc.dispatch_settle(self.root, second["id"], "failed")
        orc.dispatch_settle(self.root, first["id"], "succeeded")

        third = orc.open_dispatch(self.root, task["id"])
        settled = orc.dispatch_settle(self.root, third["id"], "failed")
        self.assertEqual(settled["task"]["status"], "ready")


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

    def test_heartbeat_keeps_a_live_dispatch_out_of_the_age_window(self):
        """살아 있다는 신호가 회수를 비껴가게 하는가.

        신호가 우편함에만 남던 동안 이 시험은 실패했다. `reclaim` 은 `dispatches.updated_at`
        만 보므로, 30초마다 신호를 보내는 워커도 `older_than=60` 에 회수되고 그 Task 에
        두 번째 워커가 열렸다 — 한 Task 에 살아 있는 시도는 하나라는 계약이 신호를 보낸
        쪽에서 깨진다.
        """
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        with connect(self.root, write=True) as conn:  # 신호 없이 창 밖으로 늙힌다
            conn.execute("UPDATE dispatches SET updated_at=? WHERE id=?", (time.time() - 600, dispatch["id"]))

        orc.heartbeat(self.root, self.run_row["id"], task["id"], dispatch["id"], phase="아직 붙들고 있어요")

        self.assertEqual(orc.reclaim(self.root, self.run_row["id"], older_than=60), [])
        self.assertEqual(found(orc.dispatch_show(self.root, dispatch_id=dispatch["id"]))["state"], "ready")
        self.assertEqual(
            [m["type"] for m in orc.inbox(self.root, self.run_row["id"]) if m["type"] == "heartbeat"],
            ["heartbeat"],
            "신호가 우편함에는 안 남았다 — 코디네이터가 진행 상황을 못 읽는다",
        )

    def test_a_settled_dispatch_cannot_claim_to_be_alive(self):
        """끝난 시도의 `updated_at` 을 뒤로 미루면 그 시도가 언제 끝났는지가 밀린다."""
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        orc.dispatch_settle(self.root, dispatch["id"], "succeeded")
        with self.assertRaises(orc.OrchestrationError):
            orc.heartbeat(self.root, self.run_row["id"], task["id"], dispatch["id"])


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


class TestFailedWriteDoesNotCreateGhost(unittest.TestCase):
    """쓰기가 실패해 아무것도 못 바꾸면 유령 장부가 남으면 안 된다 (감사 갭 2-A).

    `connect()` 의 문서 약속은 조회에만 적혀 있었지만 쓰기에서도 거짓이었다 — 파일이 없던
    자리에서 `sqlite3.connect(path)` 를 부르는 순간 이미 0바이트 파일이 생기고, 그 뒤
    `_ensure_schema` 의 DDL 이 autocommit 되어 나중에 일어나는 `rollback()` 으로도 지울 수
    없었다. `없는 메시지에 답하기`(`reply`)와 `없는 Run 에 Task 만들기`(`task_create`) 둘 다
    실제로는 아무 INSERT 도 하기 전에 검사에서 걸려 실패하는 경로다 — 그런데도 파일은 남았다.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_replying_to_a_missing_message_leaves_no_ledger(self):
        with self.assertRaises(orc.OrchestrationError):
            orc.reply(self.root, "msg_nope", "x")
        self.assertFalse(orc.exists(self.root))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard")), "실패한 쓰기가 .asgard를 남겼다")

    def test_creating_a_task_under_an_unknown_run_leaves_no_ledger(self):
        with self.assertRaises(orc.OrchestrationError):
            orc.task_create(self.root, "run_ghost", "고아 일감")
        self.assertFalse(orc.exists(self.root))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard")))

    def test_a_genuine_first_write_still_creates_the_ledger(self):
        """유령 청소가 진짜 첫 쓰기까지 지우면 안 된다 — 성공한 쓰기의 결과는 남아야 한다."""
        run = orc.run_create(self.root, "첫 Run")
        self.assertTrue(orc.exists(self.root))
        self.assertEqual(found(orc.run_show(self.root, run["id"]))["id"], run["id"])


class TestSchemaMigration(OrchestrationBase):
    def test_version_one_database_gains_the_live_dispatch_constraint(self):
        """이미 쓰던 장부도 판 올림 때 제약을 얻는다 — 새 파일만 안전하면 재시작 경계는 그대로 샌다."""
        with sqlite3.connect(orc.db_path(self.root)) as conn:
            conn.execute("DROP INDEX IF EXISTS dispatches_one_ready_per_task")
            conn.execute("PRAGMA user_version=1")

        orc.run_show(self.root, self.run_row["id"])

        with sqlite3.connect(orc.db_path(self.root)) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            index = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name='dispatches_one_ready_per_task'"
            ).fetchone()
        self.assertEqual(version, store.SCHEMA_VERSION)
        self.assertIsNotNone(index)

    def test_version_one_database_with_duplicates_still_opens(self):
        """옛 중복은 장부 전체를 막지 않는다 — 파생 DB의 기존 fail-open 계약을 지킨다."""
        task = orc.task_create(self.root, self.run_row["id"], "already duplicated")
        dispatch = orc.open_dispatch(self.root, task["id"])
        with sqlite3.connect(orc.db_path(self.root)) as conn:
            conn.execute("DROP INDEX IF EXISTS dispatches_one_ready_per_task")
            conn.execute(
                "INSERT INTO dispatches SELECT ?, run_id, task_id, worker, role, agent, model, attempt + 1,"
                " retry_of, state, outcome, summary, files_modified, created_at, updated_at, settled_at"
                " FROM dispatches WHERE id=?",
                ("disp_duplicate", dispatch["id"]),
            )
            conn.execute("PRAGMA user_version=1")

        self.assertEqual(len(orc.dispatch_history(self.root, task["id"])), 2)
        with sqlite3.connect(orc.db_path(self.root)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], store.SCHEMA_VERSION)

    def test_a_table_that_already_exists_still_gains_the_new_columns(self):
        """`CREATE TABLE IF NOT EXISTS` 는 표가 있으면 통째로 건너뛴다 — 열은 ALTER 로만 온다.

        이 시험이 없으면 새로 만든 장부에서만 통과하고, 쓰던 장부에서는 `plan` 이 없는 열에
        적으려다 죽는다. 재는 것은 판 번호가 아니라 열의 존재다.
        """
        with sqlite3.connect(orc.db_path(self.root)) as conn:
            conn.execute("ALTER TABLE tasks DROP COLUMN agent")
            conn.execute("ALTER TABLE tasks DROP COLUMN kind")
            conn.execute("PRAGMA user_version=2")

        task = orc.task_create(self.root, self.run_row["id"], "옛 장부 위의 일감", agent="asgard-thor", kind="work")

        self.assertEqual(task["agent"], "asgard-thor")
        self.assertEqual(task["kind"], "work")


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

    def test_two_processes_cannot_open_the_same_task(self):
        """프로세스 로컬 락 밖에서도 패자는 같은 계약 오류를 받고 활성 시도는 하나만 남는다."""
        child_code = """
import os, sys
sys.path.insert(0, os.environ["ASGARD_TEST_SRC"])
from asgard import orchestration as orc
sys.stdin.read(1)
try:
    orc.open_dispatch(os.environ["ASGARD_TEST_ROOT"], os.environ["ASGARD_TEST_TASK"])
except Exception as exc:
    print(type(exc).__name__)
else:
    print("ok")
"""
        source = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        for attempt in range(12):
            task = orc.task_create(self.root, self.run_row["id"], f"race {attempt}")
            env = {
                **os.environ,
                "ASGARD_TEST_SRC": source,
                "ASGARD_TEST_ROOT": self.root,
                "ASGARD_TEST_TASK": task["id"],
            }
            children = [
                subprocess.Popen(
                    [sys.executable, "-c", child_code],
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(2)
            ]
            for child in children:
                assert child.stdin is not None
                child.stdin.write("x")
                child.stdin.close()
            outcomes = []
            for child in children:
                child.wait(timeout=10)
                assert child.stdout is not None and child.stderr is not None
                self.assertEqual(child.returncode, 0, child.stderr.read())
                outcomes.append(child.stdout.read().strip())
            self.assertEqual(sorted(outcomes), ["OrchestrationError", "ok"])
            self.assertEqual(
                len([row for row in orc.dispatch_history(self.root, task["id"]) if row["state"] == "ready"]),
                1,
            )

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
        """heartbeat 만 있으면 안 깨고, escalation 이 붙으면 heartbeat 까지 함께 나온다."""
        orc.send(self.root, self.run_row["id"], "heartbeat", subject="alive")
        quiet = orc.check(self.root, self.run_row["id"], types=("escalation",))
        self.assertEqual(quiet["count"], 0)

        orc.escalate(self.root, self.run_row["id"], "막혔다")
        woken = orc.check(self.root, self.run_row["id"], types=("escalation",))
        self.assertEqual([m["type"] for m in woken["messages"]], ["heartbeat", "escalation"])

    def test_type_filter_wakes_past_the_delivery_cap(self):
        """상한(50)을 넘긴 자리의 escalation 도 대기를 깨우는가 (감사 높음-4).

        워커가 5분마다 heartbeat 를 보내는 것이 정상 계약이라 긴 wave 에서는 50건이 쉽게 쌓인다.
        묶음을 먼저 자르고 그 안에서 종류를 찾으면 51번째 보고가 영영 안 보이고, 묶지 않으니
        ack 도 안 되어 우편함이 스스로 풀리지 않는다.
        """
        for i in range(model.DELIVERY_CAP):
            orc.send(self.root, self.run_row["id"], "heartbeat", subject=f"alive{i}")
        quiet = orc.check(self.root, self.run_row["id"], types=("escalation",))
        self.assertEqual(quiet["count"], 0, "heartbeat 만 있는데 깨어났다")

        orc.escalate(self.root, self.run_row["id"], "상한 뒤의 보고")
        woken = orc.check(self.root, self.run_row["id"], types=("escalation",), wait=True, timeout_ms=300)
        self.assertEqual(woken["count"], model.DELIVERY_CAP, "51번째 보고가 대기를 못 깨웠다")
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
            orc.escalate(self.root, self.run_row["id"], "late")

        threading.Thread(target=deliver, daemon=True).start()
        batch = orc.check(self.root, self.run_row["id"], types=("escalation",), wait=True, timeout_ms=5000)
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


class TestScopedReset(OrchestrationBase):
    """부분 초기화 — 각 범위는 자기가 주장하는 것만 지우고 나머지는 그대로 둔다 (감사 갭 2-B).

    Orca 의 `reset --tasks|--messages|--all` 과 같은 자리다. `--all`(=`reset`)은 이미 있었고
    나머지 둘이 없어서, 코디네이터는 메일함만 비우거나 Task DAG 만 지우고 싶어도 장부 전체를
    날리는 수밖에 없었다.
    """

    def test_reset_tasks_clears_the_dag_but_keeps_the_run_and_mail(self):
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        orc.dispatch_settle(self.root, dispatch["id"], "succeeded")
        orc.send(self.root, self.run_row["id"], "status", subject="살아있다")

        removed = orc.reset_tasks(self.root)

        self.assertEqual(removed, 1, "지운 Task 행 수가 실제와 다르다")
        self.assertEqual(orc.task_list(self.root, self.run_row["id"]), [])
        self.assertEqual(orc.dispatch_history(self.root, task["id"]), [], "Task를 지웠는데 Dispatch가 남았다")
        self.assertIsNotNone(orc.run_show(self.root, self.run_row["id"]), "Task 범위가 Run까지 지웠다")
        self.assertEqual(len(orc.inbox(self.root, self.run_row["id"])), 1, "Task 범위가 메일함까지 비웠다")

    def test_reset_messages_clears_the_mailbox_but_keeps_the_dag(self):
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        orc.send(self.root, self.run_row["id"], "status", subject="살아있다")
        orc.send(self.root, self.run_row["id"], "status", subject="또 하나")

        removed = orc.reset_messages(self.root)

        self.assertEqual(removed, 2, "지운 메시지 행 수가 실제와 다르다")
        self.assertEqual(orc.inbox(self.root, self.run_row["id"]), [])
        self.assertEqual(
            found(orc.task_show(self.root, task["id"]))["id"], task["id"], "메일 범위가 Task DAG까지 지웠다"
        )
        self.assertIsNotNone(orc.run_show(self.root, self.run_row["id"]), "메일 범위가 Run까지 지웠다")

    def test_whole_reset_still_removes_everything(self):
        """범위 인자를 안 주는 기본 동작은 오늘까지와 같다 — 파일 전체가 사라진다."""
        orc.task_create(self.root, self.run_row["id"], "unit")
        self.assertTrue(orc.reset(self.root))
        self.assertFalse(orc.exists(self.root))


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

    def test_conflicting_ids_do_not_share_a_wave(self):
        """두 배정 단위가 access 없이 같은 파일을 만질 때 planning 이 넘기는 형상 그대로다."""
        self.assertEqual(model.topo_waves(["a", "b"], {}, {"a": {"b"}, "b": {"a"}}), [["a"], ["b"]])

    def test_conflicts_do_not_reorder_dependencies(self):
        """충돌은 같은 묶음만 막고 순서는 못 정한다 — c 는 충돌해도 a·b 뒤에 남는다."""
        waves = model.topo_waves(["a", "b", "c"], {"c": ["a", "b"]}, {"a": {"c"}, "c": {"a"}})
        self.assertEqual(waves, [["a", "b"], ["c"]])

    def test_a_fully_self_conflicting_ready_set_terminates_one_at_a_time(self):
        ids = ["a", "b", "c"]
        conflicts = {tid: {other for other in ids if other != tid} for tid in ids}
        self.assertEqual(model.topo_waves(ids, {}, conflicts), [["a"], ["b"], ["c"]])

    def test_absent_conflicts_reproduce_the_dependency_only_schedule(self):
        """conflicts 없는 호출은 인자가 생기기 전과 같은 묶음을 낸다 — bifrost 의 등록 순서."""
        ids, deps = ["a", "b", "c", "d"], {"c": ["a"], "d": ["b"]}
        self.assertEqual(model.topo_waves(ids, deps), [["a", "b"], ["c", "d"]])
        self.assertEqual(model.topo_waves(ids, deps, None), [["a", "b"], ["c", "d"]])
        self.assertEqual(model.topo_waves(ids, deps, {}), [["a", "b"], ["c", "d"]])
        self.assertEqual(model.topo_waves(ids, deps, {"a": set()}), [["a", "b"], ["c", "d"]])

    def test_conflicts_still_raise_on_cycles(self):
        with self.assertRaises(model.OrchestrationError):
            model.topo_waves(["a", "b"], {"a": ["b"], "b": ["a"]}, {"a": {"b"}, "b": {"a"}})

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


class TestDeliveryContract(OrchestrationBase):
    """배달 계약을 Orca 오케스트레이션 규격과 대조한다 — 재생 신원과 종류 필터의 경계."""

    def test_replay_returns_only_the_oldest_open_bundle(self):
        """열린 묶음이 둘이면 오래된 쪽만 나온다 — 돌려준 delivery_id 가 설명하는 그 묶음.

        이 DB 는 파생 상태라 다른 판이 쓴 장부를 이어 받을 수 있고, 그 파일에는 묶였지만 확인
        안 된 묶음이 둘 있을 수 있다. 둘을 한 번에 돌려주면 그 id 로 ack 했을 때 절반만 확인
        처리되고, 나머지는 묶인 채 남아 다음 조회마다 따라 나온다.
        """
        orc.send(self.root, self.run_row["id"], "status", subject="첫 묶음")
        first = orc.check(self.root, self.run_row["id"])
        later = orc.send(self.root, self.run_row["id"], "status", subject="다른 묶음")
        with sqlite3.connect(orc.db_path(self.root)) as conn:
            conn.execute("UPDATE messages SET delivery_id='dlv_other' WHERE id=?", (later["id"],))

        replayed = orc.check(self.root, self.run_row["id"])
        self.assertEqual(replayed["delivery_id"], first["delivery_id"])
        self.assertEqual([m["subject"] for m in replayed["messages"]], ["첫 묶음"])

    def test_actionable_filter_returns_and_acks_the_whole_batch(self):
        """actionable 만 기다려도 묶음에는 status 까지 들어오고, ack 는 둘 다 확인 처리한다.

        필터로 묶음을 거르면 걸러진 status 가 영영 ack 되지 않아 우편함 앞자리에 남고, 그 뒤의
        모든 배달이 그것을 계속 끌고 다닌다.
        """
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        orc.send(self.root, self.run_row["id"], "status", subject="절반쯤 했다")
        orc.worker_done(self.root, self.run_row["id"], task["id"], dispatch["id"], "succeeded", subject="끝")

        batch = orc.check(self.root, self.run_row["id"], types=orc.ACTIONABLE_TYPES, wait=True, timeout_ms=1000)
        self.assertEqual({m["type"] for m in batch["messages"]}, {"status", "worker_done"})

        emptied = orc.check(self.root, self.run_row["id"], ack=batch["delivery_id"])
        self.assertEqual(emptied["count"], 0, "필터 밖 메일이 ack 되지 않고 남았다")
        self.assertTrue(all(m["acked_at"] is not None for m in orc.inbox(self.root, self.run_row["id"])))

    def test_ack_cannot_consume_another_runs_delivery(self):
        """배달 id 를 알아도 다른 Run 권한으로 소비할 수 없다 — 원래 묶음은 계속 재생되어야 한다."""
        other = orc.run_create(self.root, "다른 Run", quest_id="q-other")
        orc.send(self.root, self.run_row["id"], "status", subject="이 Run 것")
        claimed = orc.check(self.root, self.run_row["id"])

        with self.assertRaisesRegex(orc.OrchestrationError, "다른 Run"):
            orc.check(self.root, other["id"], ack=claimed["delivery_id"])

        replayed = orc.check(self.root, self.run_row["id"])
        self.assertEqual(replayed["delivery_id"], claimed["delivery_id"])
        self.assertEqual(replayed["count"], 1)


class TestCompletionAuthority(OrchestrationBase):
    """완료 보고는 정산과 함께 온다 — 메일만 남는 완료가 없어야 한다."""

    def test_plain_send_cannot_report_completion(self):
        """`send` 로 넣은 완료는 정산을 안 한다 — 그래서 그 문을 막는다."""
        with self.assertRaises(orc.OrchestrationError):
            orc.send(self.root, self.run_row["id"], "worker_done", subject="끝", body="실패했다")
        self.assertEqual(orc.inbox(self.root, self.run_row["id"]), [])

    def test_failed_outcome_closes_both_dispatch_and_task(self):
        """실패도 종결 보고다 — Dispatch 와 Task 가 함께 실패로 접히고 outcome 칸에 남는다."""
        orc.set_meta(self.root, orc.META_MAX_ATTEMPTS, "1")
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        reported = orc.worker_done(self.root, self.run_row["id"], task["id"], dispatch["id"], "failed", body="못 했다")
        self.assertEqual(reported["dispatch"]["state"], "failed")
        self.assertEqual(reported["task"]["status"], "failed")
        self.assertEqual(reported["message"]["outcome"], "failed")


class TestRecoveryStates(OrchestrationBase):
    """`outcome_unknown` 은 실패가 아니다 — 그 시도의 자원은 아직 살아 있을 수 있다."""

    def test_mark_refuses_to_write_failure(self):
        """복구가 실패를 적으면 outcome 도 settled_at 도 없이 state 만 failed 가 된다."""
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        with self.assertRaises(orc.OrchestrationError):
            orc.dispatch_mark(self.root, dispatch["id"], "failed")
        self.assertEqual(found(orc.dispatch_show(self.root, dispatch_id=dispatch["id"]))["state"], "ready")

    def test_mark_refuses_a_finished_dispatch(self):
        """끝난 시도를 다시 표시하면 기록된 outcome 과 state 가 어긋난다."""
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        dispatch = orc.open_dispatch(self.root, task["id"])
        orc.dispatch_settle(self.root, dispatch["id"], "succeeded")
        with self.assertRaises(orc.OrchestrationError):
            orc.dispatch_mark(self.root, dispatch["id"], "outcome_unknown")
        shown = found(orc.dispatch_show(self.root, dispatch_id=dispatch["id"]))
        self.assertEqual((shown["state"], shown["outcome"]), ("settled", "succeeded"))


class TestAskIdentity(OrchestrationBase):
    """질문은 원래 message id 로 이어 받는다 — 시간이 다 되어도 질문 자체는 남는다."""

    def test_timeout_resumes_by_the_original_id(self):
        question = orc.ask(self.root, self.run_row["id"], "포트를 바꿔도 되나?", timeout_ms=120)
        self.assertIsNone(question["answered_at"], "시간이 다 됐는데 답이 달렸다")
        orc.reply(self.root, question["id"], "yes")
        resumed = orc.wait_answer(self.root, question["id"], timeout_ms=200)
        self.assertEqual(resumed["id"], question["id"])
        self.assertEqual(resumed["answer"], "yes")

    def test_asking_again_creates_a_second_question(self):
        """같은 물음을 다시 만들면 질문이 둘 생긴다 — 이어 받으려면 `wait_answer` 를 쓴다."""
        first = orc.ask(self.root, self.run_row["id"], "같은 물음")
        second = orc.ask(self.root, self.run_row["id"], "같은 물음")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(orc.pending_questions(self.root, self.run_row["id"])), 2)


class TestGateAndQuestionAreDistinct(OrchestrationBase):
    """게이트와 질문은 다른 표면이다 — 어느 쪽도 다른 쪽을 끝내지 않는다."""

    def test_resolving_a_gate_does_not_answer_the_question(self):
        question = orc.ask(self.root, self.run_row["id"], "워커가 막혔다")
        gate = orc.gate_create(self.root, self.run_row["id"], "다음 갈래는?", options=["a", "b"])
        orc.gate_resolve(self.root, gate["id"], "a")
        self.assertEqual([q["id"] for q in orc.pending_questions(self.root, self.run_row["id"])], [question["id"]])

    def test_answering_a_question_does_not_resolve_the_gate(self):
        question = orc.ask(self.root, self.run_row["id"], "워커가 막혔다")
        gate = orc.gate_create(self.root, self.run_row["id"], "다음 갈래는?")
        orc.reply(self.root, question["id"], "yes")
        still_open = orc.gate_list(self.root, run_id=self.run_row["id"], status="open")
        self.assertEqual([g["id"] for g in still_open], [gate["id"]])

    def test_reply_refuses_a_message_that_is_not_a_question(self):
        note = orc.send(self.root, self.run_row["id"], "status", subject="진행 중")
        with self.assertRaises(orc.OrchestrationError):
            orc.reply(self.root, note["id"], "답")

    def test_gate_needs_an_open_run(self):
        """없는 Run 은 외래키가 raw IntegrityError 를 내고, 닫힌 Run 의 게이트는 고를 사람이 없다."""
        with self.assertRaises(orc.OrchestrationError):
            orc.gate_create(self.root, "run_ghost", "없는 Run 의 게이트")
        orc.run_close(self.root, self.run_row["id"])
        with self.assertRaises(orc.OrchestrationError):
            orc.gate_create(self.root, self.run_row["id"], "닫힌 Run 의 게이트")


class TestAddressedDelivery(OrchestrationBase):
    """주소를 적은 메일은 그 이름을 댄 쪽만 가져간다 — 참가자 여럿이 한 우편함을 쓰는 조건."""

    def send_to(self, who: str, subject: str) -> dict:
        return orc.send(self.root, self.run_row["id"], "status", subject=subject, sender="coord", recipient=who)

    def test_a_named_caller_takes_only_its_own_mail(self):
        self.send_to("session-a", "for-a")
        self.send_to("session-b", "for-b")
        batch = orc.check(self.root, self.run_row["id"], recipient="session-a")
        self.assertEqual([m["subject"] for m in batch["messages"]], ["for-a"])

    def test_unaddressed_mail_stays_for_the_coordinator(self):
        """이름을 댄 쪽은 주인 없는 메일을 안 집는다 — 그 메일의 수신자는 코디네이터다."""
        orc.send(self.root, self.run_row["id"], "status", subject="누구에게랄 것 없이")
        self.assertEqual(orc.check(self.root, self.run_row["id"], recipient="session-a")["count"], 0)
        self.assertEqual(orc.check(self.root, self.run_row["id"])["count"], 1)

    def test_an_unnamed_caller_still_sees_everything(self):
        """뒤호환 — 이름을 안 대면 오늘처럼 우편함 전체다. 네이티브 코디네이터가 이 자리다."""
        self.send_to("session-a", "for-a")
        orc.send(self.root, self.run_row["id"], "status", subject="주인 없음")
        self.assertEqual(orc.check(self.root, self.run_row["id"])["count"], 2)

    def test_replay_is_scoped_to_the_name_that_claimed_it(self):
        """A 가 처리하다 만 묶음을 B 가 받으면, B 의 ack 가 A 의 메일을 A 없이 접는다."""
        self.send_to("session-a", "for-a")
        first = orc.check(self.root, self.run_row["id"], recipient="session-a")
        self.assertEqual(first["count"], 1)
        self.assertEqual(orc.check(self.root, self.run_row["id"], recipient="session-b")["count"], 0)
        again = orc.check(self.root, self.run_row["id"], recipient="session-a")
        self.assertEqual(again["delivery_id"], first["delivery_id"])

    def test_the_wake_filter_uses_the_same_name(self):
        """남 앞으로 온 메일이 대기를 깨우면, 깨어난 쪽은 빈 묶음만 받고 다시 잔다."""
        self.send_to("session-b", "for-b")
        started = time.monotonic()
        batch = orc.check(
            self.root, self.run_row["id"], recipient="session-a", types=("status",), wait=True, timeout_ms=300
        )
        self.assertEqual(batch["count"], 0)
        self.assertGreaterEqual(time.monotonic() - started, 0.25)

    def test_ask_can_address_one_participant(self):
        """`ask --recipient` + `serve` 가 한 모델과의 왕복이다 — 코디네이터는 그 질문을 안 잡는다."""
        question = orc.ask(self.root, self.run_row["id"], "어느 모델이 답하나", recipient="codex-1")
        self.assertEqual(orc.check(self.root, self.run_row["id"], recipient="codex-1")["count"], 1)
        orc.reply(self.root, question["id"], "gpt")
        self.assertEqual(orc.wait_answer(self.root, question["id"], timeout_ms=0)["answer"], "gpt")

    def test_one_name_acking_a_shared_batch_does_not_fold_another_name_s_mail(self):
        """묶음은 이름보다 먼저 생긴다 — 무명 코디네이터가 둘 앞의 메일을 한 묶음으로 잡을 수 있다.

        그 상태에서 alice 가 자기 이름으로 재생해 ack 할 때 조건이 배달 id 하나뿐이면 bob 의
        메일이 읽히지도 않고 접힌다 (판정자가 재현한 자리).
        """
        self.send_to("alice", "for-alice")
        self.send_to("bob", "for-bob")
        shared = orc.check(self.root, self.run_row["id"])  # 코디네이터가 둘을 한 묶음으로 잡는다
        self.assertEqual(shared["count"], 2)
        replayed = orc.check(self.root, self.run_row["id"], recipient="alice")
        self.assertEqual(replayed["delivery_id"], shared["delivery_id"])
        orc.check(self.root, self.run_row["id"], ack=replayed["delivery_id"], recipient="alice")
        self.assertEqual(
            [m["subject"] for m in orc.check(self.root, self.run_row["id"], recipient="bob")["messages"]], ["for-bob"]
        )

    def test_peek_is_scoped_too(self):
        self.send_to("session-a", "for-a")
        self.send_to("session-b", "for-b")
        peeked = orc.check(self.root, self.run_row["id"], recipient="session-b", peek=True)
        self.assertEqual([m["subject"] for m in peeked["messages"]], ["for-b"])


if __name__ == "__main__":
    unittest.main()
