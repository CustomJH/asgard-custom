"""siege — 배차 장부를 사람이 읽는 표면.

실행: uv run pytest tests/test_siege.py

여기서 지키는 계약 둘:
  · 조회는 프로젝트 루트의 장부를 본다 — 하위 디렉터리에서 쳐도 "비어 있다" 는 거짓 보고를
    내지 않는다.
  · 조회는 아무것도 만들지 않는다 — 장부가 없는 곳에서 읽어도 파일이 안 생긴다.

둘은 한 쌍이다. 루트를 못 찾으면 거짓 보고를 하고, 그 자리에 빈 DB 를 남겨 다음 조회까지
계속 속인다. 한쪽만 고치면 나머지 절반이 그대로 남는다.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import orchestration as orc  # noqa: E402
from asgard.commands import siege  # noqa: E402
from asgard.orchestration import store  # noqa: E402


class SiegeBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # `_project_root` 는 `.git` 을 찾아 올라간다 — 그 표식이 있어야 하위 디렉터리 갈래가
        # 실제 사용과 같은 모양이 된다.
        subprocess.run(["git", "init", "-q", self.root], check=True, capture_output=True)
        self.deep = os.path.join(self.root, "src", "asgard")
        os.makedirs(self.deep, exist_ok=True)
        self._cwd = os.getcwd()
        self.addCleanup(lambda: os.chdir(self._cwd))
        # 장부 자리 덮어쓰기(`ASGARD_ORCHESTRATION_DB`)를 끈 채 돈다. 경로 판정 자체가 이
        # 시험의 대상이라 덮어쓰면 잴 것이 없어진다.
        override = os.environ.pop(store.STATE_ENV, None)
        if override is not None:
            self.addCleanup(os.environ.__setitem__, store.STATE_ENV, override)

    def capture(self, call) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            call()
        return buffer.getvalue()


class TestRootResolution(SiegeBase):
    def test_a_subdirectory_reads_the_project_ledger(self):
        run = orc.run_create(self.root, "루트의 Run", quest_id="q-root")
        os.chdir(self.deep)
        payload = json.loads(self.capture(lambda: siege.run_runs(json_out=True)))
        self.assertEqual([row["id"] for row in payload], [run["id"]], "하위 디렉터리에서 장부를 못 찾았다")

    def test_a_subdirectory_does_not_leave_a_ledger_behind(self):
        orc.run_create(self.root, "루트의 Run", quest_id="q-root")
        os.chdir(self.deep)
        siege.run_runs(json_out=True)
        self.assertFalse(os.path.exists(os.path.join(self.deep, ".asgard")), "조회가 하위 디렉터리에 장부를 만들었다")


class TestListingHidesNothingSilently(SiegeBase):
    """26-08-21 실측: 장부에 run 이 110개인데 목록이 20개에서 잘렸고, 잘렸다는 표시도 더 보는
    손잡이도 없었다. 같은 저장소의 `siege blocked` 는 전수를 훑기 때문에, 목록에 없는 run 의
    미답 질문이 나오는 자리가 생겼다."""

    def _many(self, count: int) -> int:
        os.chdir(self.root)
        for i in range(count):
            orc.run_create(self.root, f"Run {i}", quest_id=f"q-{i}")
        return count

    def test_json_lists_every_run(self):
        made = self._many(25)
        payload = json.loads(self.capture(lambda: siege.run_runs(json_out=True)))
        self.assertEqual(len(payload), made, "`--json` 이 조용히 잘랐다 — 스킬 문서의 계약은 every run 이다")

    def test_json_stays_an_array(self):
        """봉투를 씌우면 이미 이 표면을 읽고 있는 쪽이 깨진다."""
        self._many(3)
        payload = json.loads(self.capture(lambda: siege.run_runs(json_out=True)))
        self.assertIsInstance(payload, list)

    def test_a_truncated_plain_list_says_how_many_it_hid(self):
        self._many(25)
        text = self.capture(lambda: siege.run_runs(json_out=False, limit=20))
        self.assertIn("5개를 더 안 보여 줬어요", text)
        self.assertIn("--limit 0", text)

    def test_a_complete_plain_list_says_nothing_extra(self):
        self._many(3)
        text = self.capture(lambda: siege.run_runs(json_out=False, limit=20))
        self.assertNotIn("더 안 보여 줬어요", text)

    def test_limit_zero_means_every_one(self):
        made = self._many(25)
        payload = json.loads(self.capture(lambda: siege.run_runs(json_out=True, limit=0)))
        self.assertEqual(len(payload), made)


class TestReadOnly(SiegeBase):
    def test_an_empty_project_reports_empty_without_creating_a_file(self):
        os.chdir(self.root)
        payload = json.loads(self.capture(lambda: siege.run_runs(json_out=True)))
        self.assertEqual(payload, [])
        self.assertFalse(orc.exists(self.root), "읽기 전용 조회가 장부를 만들었다")

    def test_run_show_reports_a_missing_run(self):
        os.chdir(self.root)
        self.assertEqual(siege.run_show("run_nope", json_out=True), 2)
        self.assertFalse(orc.exists(self.root))

    def test_run_show_prints_the_dag(self):
        run = orc.run_create(self.root, "DAG", quest_id="q-dag")
        first = orc.task_create(self.root, run["id"], "선행")
        orc.task_create(self.root, run["id"], "후행", deps=[first["id"]], unit_id="2")
        os.chdir(self.root)
        payload = json.loads(self.capture(lambda: siege.run_show(run["id"], json_out=True)))
        self.assertEqual(payload["run"]["id"], run["id"])
        self.assertEqual({task["status"] for task in payload["tasks"]}, {"ready", "pending"})

    def test_a_failing_answer_leaves_no_ledger_behind(self):
        """없는 메시지에 답하려는 쓰기가 실패해도 장부가 생기면 안 된다 (감사 갭 2-A)."""
        os.chdir(self.root)
        self.assertEqual(siege.run_answer("msg_nope", "x", json_out=True), 2)
        self.assertFalse(orc.exists(self.root))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard")), "실패한 답변이 .asgard를 남겼다")


class TestScopedReset(SiegeBase):
    """`siege reset` 의 부분 초기화 표면 — 각 범위가 주장한 것만 지우는가 (감사 갭 2-B)."""

    def setUp(self) -> None:
        super().setUp()
        self.run_row = orc.run_create(self.root, "장부", quest_id="q-reset")
        os.chdir(self.root)

    def test_tasks_scope_keeps_the_run_and_mail(self):
        orc.task_create(self.root, self.run_row["id"], "unit")
        orc.send(self.root, self.run_row["id"], "status", subject="살아있다")

        result = siege.run_reset(json_out=True, tasks=True)

        self.assertEqual(result, 0)
        self.assertEqual(orc.task_list(self.root, self.run_row["id"]), [])
        self.assertIsNotNone(orc.run_show(self.root, self.run_row["id"]))
        self.assertEqual(len(orc.inbox(self.root, self.run_row["id"])), 1)

    def test_messages_scope_keeps_the_task_dag(self):
        task = orc.task_create(self.root, self.run_row["id"], "unit")
        orc.send(self.root, self.run_row["id"], "status", subject="살아있다")

        result = siege.run_reset(json_out=True, messages=True)

        self.assertEqual(result, 0)
        self.assertEqual(orc.inbox(self.root, self.run_row["id"]), [])
        self.assertEqual(orc.task_list(self.root, self.run_row["id"]), [task])

    def test_no_scope_wipes_the_whole_ledger(self):
        orc.task_create(self.root, self.run_row["id"], "unit")
        result = siege.run_reset(json_out=True)
        self.assertEqual(result, 0)
        self.assertFalse(orc.exists(self.root))

    def test_combining_scopes_is_rejected_and_changes_nothing(self):
        orc.task_create(self.root, self.run_row["id"], "unit")
        orc.send(self.root, self.run_row["id"], "status", subject="살아있다")

        result = siege.run_reset(json_out=True, tasks=True, messages=True)

        self.assertEqual(result, 2)
        self.assertEqual(len(orc.task_list(self.root, self.run_row["id"])), 1, "거부됐는데 Task가 지워졌다")
        self.assertEqual(len(orc.inbox(self.root, self.run_row["id"])), 1, "거부됐는데 메일이 지워졌다")

    def test_the_confirmation_line_does_not_claim_the_whole_ledger_was_wiped(self):
        """부분 초기화의 확인문은 '장부를 지웠어요' 라고 말하면 안 된다 — 실제로는 일부만 지웠다."""
        orc.task_create(self.root, self.run_row["id"], "unit")
        output = self.capture(lambda: siege.run_reset(tasks=True))
        self.assertNotIn("배차 장부를 지웠어요", output)


class TestGates(SiegeBase):
    """결정 게이트의 닫는 쪽.

    여는 쪽(`gate_create`)과 세는 쪽(`show` 의 "열린 결정 게이트 N건")은 이미 있었고 닫는 쪽만
    없었다 — 게이트를 열 수는 있어도 표면으로는 못 닫는 상태였다. 여기서 재는 것은 그 반쪽이다:
    목록에 id 가 나오고, 그 id 로 닫히고, 두 번은 안 닫힌다.
    """

    def setUp(self) -> None:
        super().setUp()
        self.run_row = orc.run_create(self.root, "갈래", quest_id="q-gate")
        os.chdir(self.root)

    def test_open_gates_are_listed(self):
        gate = orc.gate_create(self.root, self.run_row["id"], "A 로 갈까요 B 로 갈까요?", options=["A", "B"])
        payload = json.loads(self.capture(lambda: siege.run_gates(json_out=True)))
        self.assertEqual([row["id"] for row in payload], [gate["id"]])
        self.assertEqual(payload[0]["options"], ["A", "B"])
        self.assertEqual(payload[0]["status"], "open")

    def test_one_run_can_be_asked_for_alone(self):
        mine = orc.gate_create(self.root, self.run_row["id"], "이 Run 의 갈래")
        other = orc.run_create(self.root, "옆 Run", quest_id="q-other")
        orc.gate_create(self.root, other["id"], "옆 Run 의 갈래")
        payload = json.loads(self.capture(lambda: siege.run_gates(self.run_row["id"], json_out=True)))
        self.assertEqual([row["id"] for row in payload], [mine["id"]], "Run 을 줬는데 옆 Run 것까지 끌어왔다")
        everywhere = json.loads(self.capture(lambda: siege.run_gates(json_out=True)))
        self.assertEqual(len(everywhere), 2, "Run 을 안 주면 장부 전체를 훑어야 한다")

    def test_a_missing_run_is_reported(self):
        self.assertEqual(siege.run_gates("run_nope", json_out=True), 2)

    def test_the_list_prints_the_id_the_decide_verb_needs(self):
        gate = orc.gate_create(self.root, self.run_row["id"], "A 로 갈까요 B 로 갈까요?", options=["A", "B"])
        output = self.capture(lambda: siege.run_gates())
        self.assertIn(gate["id"], output, "목록에 id 가 없으면 보고도 못 닫는다")

    def test_deciding_closes_the_gate(self):
        gate = orc.gate_create(self.root, self.run_row["id"], "A 로 갈까요 B 로 갈까요?", options=["A", "B"])
        self.assertEqual(siege.run_decide(gate["id"], "A", json_out=True), 0)
        self.assertEqual(orc.gate_list(self.root, status="open"), [], "닫았는데 열린 채로 남았다")
        closed = orc.gate_list(self.root)[0]
        self.assertEqual((closed["status"], closed["resolution"]), ("resolved", "A"))

    def test_deciding_reports_the_closed_gate_as_json(self):
        gate = orc.gate_create(self.root, self.run_row["id"], "A 로 갈까요 B 로 갈까요?", options=["A", "B"])
        payload = json.loads(self.capture(lambda: siege.run_decide(gate["id"], "A", json_out=True)))
        self.assertEqual(payload["id"], gate["id"])
        self.assertEqual(payload["run_id"], self.run_row["id"])
        self.assertEqual(payload["status"], "resolved")
        self.assertEqual(payload["resolution"], "A")
        self.assertEqual(payload["options"], ["A", "B"], "--json 은 options 를 목록으로 준다")

    def test_deciding_twice_fails(self):
        gate = orc.gate_create(self.root, self.run_row["id"], "A 로 갈까요 B 로 갈까요?")
        siege.run_decide(gate["id"], "A", json_out=True)
        self.assertEqual(siege.run_decide(gate["id"], "B", json_out=True), 2, "이미 닫힌 게이트를 또 닫았다")
        closed = orc.gate_list(self.root)[0]
        self.assertEqual(closed["resolution"], "A", "두 번째 선택이 첫 선택을 덮어썼다")

    def test_an_unknown_gate_fails(self):
        self.assertEqual(siege.run_decide("gate_nope", "A", json_out=True), 2)

    def test_a_resolved_gate_shows_only_when_asked(self):
        gate = orc.gate_create(self.root, self.run_row["id"], "A 로 갈까요 B 로 갈까요?")
        siege.run_decide(gate["id"], "A", json_out=True)
        self.assertEqual(json.loads(self.capture(lambda: siege.run_gates(json_out=True))), [])
        every = json.loads(self.capture(lambda: siege.run_gates(json_out=True, all_gates=True)))
        self.assertEqual([row["id"] for row in every], [gate["id"]])


class TestWatch(SiegeBase):
    """지켜보기 — `show` 와 같은 것을 그리되, 팬아웃이 끝나기 전에 그린다.

    한 번 찍은 화면은 전부 돌아온 뒤에야 읽히는데, 병렬 배차에서 알고 싶은 것은 지금 무엇이
    답을 못 돌려주고 있는가다. 여기서 재는 것은 멈추는 조건이다 — 안 멈추면 백그라운드로 띄운
    화면을 죽이는 일이 사람 몫이 된다.
    """

    def setUp(self) -> None:
        super().setUp()
        os.chdir(self.root)
        self.run_id = orc.run_create(self.root, "지켜볼 Run", quest_id="q-watch")["id"]

    def test_an_unknown_run_is_refused(self):
        self.assertEqual(siege.run_watch("run_nope"), 2)

    def test_a_settled_run_draws_once_and_stops(self):
        task = orc.task_create(self.root, self.run_id, "끝난 일감")
        dispatch = orc.open_dispatch(self.root, task["id"], worker="w-1")
        orc.dispatch_settle(self.root, dispatch["id"], "succeeded")
        screen = self.capture(lambda: self.assertEqual(siege.run_watch(self.run_id, interval=0.01), 0))
        self.assertIn("끝났어요", screen)
        self.assertEqual(screen.count("끝난 일감"), 1, "멈춰야 할 자리에서 다시 그렸다")

    def test_a_live_attempt_holds_the_screen_open(self):
        """Task 만 보면 안 된다 — 단위 티켓이 쥔 수명은 ticket-finish 가 올 때까지 `ready` 다."""
        task = orc.task_create(self.root, self.run_id, "도는 일감")
        orc.open_dispatch(self.root, task["id"], worker="w-1")
        self.assertFalse(siege._run_settled(self.root, self.run_id))
        screen = self.capture(lambda: self.assertEqual(siege.run_watch(self.run_id, interval=0.01, limit_seconds=0), 0))
        self.assertIn("지켜보기 상한", screen)

    def test_an_empty_run_is_not_read_as_finished(self):
        """일감이 아직 안 선 Run 을 끝난 것으로 읽으면 그래프를 다 적기 전에 화면이 닫힌다."""
        self.assertFalse(siege._run_settled(self.root, self.run_id))


if __name__ == "__main__":
    unittest.main()
