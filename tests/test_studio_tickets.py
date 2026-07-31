"""스튜디오 업무 보드 — 저장소 계약, 라우팅, 에이전트 툴, 작업과의 되먹임.

이 계층이 지켜야 하는 것은 넷이다:
  ① 번호는 한 번만 나온다 — 지운 뒤에도 재사용하지 않는다(대화에 남은 이름이 다른 일감을
     가리키면 안 된다)
  ② 상태를 되돌리면 그 상태가 함의한 시각도 되돌아간다(완료 시각이 남은 '진행 중' 금지)
  ③ 정본이라 못 열면 못 열었다고 말한다 — 빈 보드로 가장하지 않는다
  ④ 읽기 전용 역할도 티켓은 끊을 수 있다 — 결함을 찾은 자리가 그것을 적을 자리다
"""

import json
import os
import sqlite3
import tempfile
import unittest

from asgard.agent.tool_kernel import ToolContext, build_session_registry, execute_tool
from asgard.commands import ticket_api
from asgard.studio import db as studio_db
from asgard.studio import teams as TM
from asgard.studio import tickets as T


class TicketCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="asgard-studio-")
        self.root = os.path.join(self._tmp.name, "nordic")
        os.makedirs(self.root)
        self.addCleanup(self._tmp.cleanup)
        # 폴더는 스스로 팀이 되지 않는다 — 결속은 사람이 건다. 아래 판정은 번호와 상태의
        # 셈법을 보는 것이라, 접두어가 임시 디렉터리 이름에 안 흔들리게 여기서 고정한다.
        TM.bind_root(TM.create_team("nordic")["id"], self.root)


class TestUntouched(unittest.TestCase):
    """팀도 티켓도 없는 기계 — 읽기만으로 자리가 생기는지를 보는 유일한 자리."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="asgard-studio-fresh-")
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def test_reading_an_untouched_project_leaves_no_file_behind(self):
        """읽기는 자리를 만들지 않는다 — 창을 열어 본 것만으로 파일이 생기면 안 된다.

        두 자리를 지킨다: 남의 리포 안(`.asgard/studio/`)과 기계의 워크스페이스. 그래도
        접두어는 진짜여야 한다: 화면이 '첫 티켓은 WRK-1 이 됩니다'를 말할 수 있어야 한다."""
        self.assertEqual(T.summary(self.root)["prefix"], "WRK")
        self.assertEqual(T.summary(self.root)["open"], 0)
        self.assertEqual(T.list_tickets(self.root), [])
        self.assertEqual(T.board(self.root)["total"], 0)
        self.assertEqual((T.list_labels(self.root), T.list_cycles(self.root)), ([], []))
        self.assertIsNone(T.find_ticket(self.root, "WRK-1"))
        self.assertFalse(os.path.exists(studio_db.workspace_path()))
        self.assertFalse(os.path.exists(studio_db.store_dir(self.root)))
        # 첫 쓰기가 자리를 만든다 — 그리고 폴더가 아니라 워크스페이스에 만든다
        self.assertEqual(T.create_ticket(self.root, "첫 건")["key"], "WRK-1")
        self.assertTrue(os.path.exists(studio_db.workspace_path()))
        self.assertFalse(os.path.exists(studio_db.store_dir(self.root)))


class TestStore(TicketCase):
    def test_the_workspace_holds_the_board_and_the_repo_holds_only_the_binding(self):
        """경계는 폴더가 아니라 워크스페이스다 — 폴더는 **팀으로** 들어온다.

        저장소는 기계에 하나뿐이고, 리포 안에는 '어느 팀에 매였나'만 적힌다."""
        ticket = T.create_ticket(self.root, "첫 일감")
        self.assertEqual(ticket["key"], "NOR-1")
        self.assertEqual(ticket["team"]["key"], "NOR")
        self.assertTrue(studio_db.exists())
        self.assertEqual(studio_db.db_path(), studio_db.workspace_path())
        # 리포 안에 남는 것은 결속 한 줄뿐 — 보드가 아니다
        self.assertFalse(os.path.exists(studio_db.legacy_db_path(self.root)))
        self.assertEqual(studio_db.read_bind(self.root)["key"], "NOR")

    def test_the_prefix_survives_a_renamed_folder(self):
        """번호는 결속에서 나오고, 한 번 굳으면 폴더 이름을 바꿔도 안 흔들린다."""
        T.create_ticket(self.root, "첫 일감")
        moved = os.path.join(self._tmp.name, "renamed-later")
        os.rename(self.root, moved)
        self.assertEqual(T.create_ticket(moved, "두 번째")["key"], "NOR-2")

    def test_a_number_is_never_reissued(self):
        first = T.create_ticket(self.root, "지울 것")
        T.create_ticket(self.root, "남을 것")
        self.assertTrue(T.delete_ticket(self.root, first["key"]))
        self.assertEqual(T.create_ticket(self.root, "그 다음")["key"], "NOR-3")

    def test_a_ticket_answers_to_its_number_bare_digits_or_id(self):
        ticket = T.create_ticket(self.root, "여러 이름으로 불린다")
        for ref in (ticket["key"], ticket["key"].lower(), "1", ticket["id"]):
            self.assertEqual(T.get_ticket(self.root, ref)["id"], ticket["id"])
        with self.assertRaises(T.TicketError):
            T.get_ticket(self.root, "NOR-999")

    def test_reopening_clears_the_timestamps_the_old_status_implied(self):
        ticket = T.create_ticket(self.root, "되돌릴 일감")
        started = T.update_ticket(self.root, ticket["key"], {"status": "in_progress"})
        self.assertIsNotNone(started["started_at"])
        done = T.update_ticket(self.root, ticket["key"], {"status": "done"})
        self.assertIsNotNone(done["completed_at"])
        # 재개는 새 시작이 아니다 — 처음 시작한 때를 지킨다
        again = T.update_ticket(self.root, ticket["key"], {"status": "in_progress"})
        self.assertIsNone(again["completed_at"])
        self.assertEqual(again["started_at"], started["started_at"])
        # 아직 손대지 않은 자리로 되돌리면 시작 시각도 없어진다
        shelved = T.update_ticket(self.root, ticket["key"], {"status": "backlog"})
        self.assertIsNone(shelved["started_at"])
        self.assertIsNone(shelved["completed_at"])

    def test_sub_tickets_stop_at_one_level(self):
        parent = T.create_ticket(self.root, "상위")
        child = T.create_ticket(self.root, "하위", parent=parent["key"])
        with self.assertRaises(T.TicketError):
            T.create_ticket(self.root, "손자", parent=child["key"])
        with self.assertRaises(T.TicketError):
            T.update_ticket(self.root, parent["key"], {"parent": child["key"]})

    def test_blocking_cannot_form_a_cycle(self):
        a = T.create_ticket(self.root, "A")
        b = T.create_ticket(self.root, "B")
        c = T.create_ticket(self.root, "C")
        T.link_tickets(self.root, a["key"], "blocks", b["key"])
        T.link_tickets(self.root, b["key"], "blocks", c["key"])
        with self.assertRaises(T.TicketError):  # 여러 다리 건너서도 순환은 순환이다
            T.link_tickets(self.root, c["key"], "blocks", a["key"])
        self.assertEqual(T.get_ticket(self.root, b["key"])["blocked_by"], [a["key"]])

    def test_a_closed_blocker_no_longer_blocks(self):
        blocker = T.create_ticket(self.root, "먼저 할 일")
        blocked = T.create_ticket(self.root, "그 다음")
        T.link_tickets(self.root, blocker["key"], "blocks", blocked["key"])
        self.assertEqual(T.get_ticket(self.root, blocked["key"])["blocked_by"], [blocker["key"]])
        T.update_ticket(self.root, blocker["key"], {"status": "done"})
        self.assertEqual(T.get_ticket(self.root, blocked["key"])["blocked_by"], [])

    def test_moving_places_the_ticket_at_the_asked_seat(self):
        keys = [T.create_ticket(self.root, f"일감 {i}")["key"] for i in range(3)]
        T.move_ticket(self.root, keys[2], "todo", 0)
        order = [row["key"] for row in T.list_tickets(self.root, status="todo")]
        self.assertEqual(order, [keys[2], keys[0], keys[1]])

    def test_labels_are_replaced_wholesale_and_created_on_first_use(self):
        ticket = T.create_ticket(self.root, "라벨", labels=["버그", "결제"])
        self.assertEqual({x["name"] for x in ticket["labels"]}, {"버그", "결제"})
        swapped = T.update_ticket(self.root, ticket["key"], {"labels": ["문서"]})
        self.assertEqual([x["name"] for x in swapped["labels"]], ["문서"])
        self.assertEqual({row["name"] for row in T.list_labels(self.root)}, {"버그", "결제", "문서"})

    def test_activity_records_names_not_ids(self):
        """활동 줄은 나중에 읽는 사람을 위한 것이다 — id 는 아무에게도 아무 말이 아니다."""
        ticket = T.create_ticket(self.root, "주기에 넣을 일감")
        cycle = T.create_cycle(self.root, "7월 5주")
        T.update_ticket(self.root, ticket["key"], {"cycle": str(cycle["number"])}, actor="odin")
        rows = T.get_ticket(self.root, ticket["key"])["activity"]
        moved = next(row for row in rows if row["field"] == "cycle_id")
        self.assertEqual(moved["after"], "7월 5주")
        self.assertNotIn(cycle["id"], json.dumps(rows, ensure_ascii=False))

    def test_partial_update_leaves_untouched_fields_alone(self):
        ticket = T.create_ticket(self.root, "제목", body="본문", assignee="odin", priority=2)
        after = T.update_ticket(self.root, ticket["key"], {"priority": 1})
        self.assertEqual((after["title"], after["body"], after["assignee"]), ("제목", "본문", "odin"))
        with self.assertRaises(T.TicketError):
            T.update_ticket(self.root, ticket["key"], {"colour": "red"})

    def test_filters_and_search_narrow_the_same_way_the_tiles_do(self):
        urgent = T.create_ticket(self.root, "결제 실패 재현", priority=1, labels=["버그"])
        T.create_ticket(self.root, "문서 정리", assignee="odin", status="done")
        overdue = T.create_ticket(self.root, "지난 기한", due_at=1.0)
        blocker = T.create_ticket(self.root, "선행", status="in_progress")
        T.link_tickets(self.root, blocker["key"], "blocks", urgent["key"])
        keys = lambda **kw: [row["key"] for row in T.list_tickets(self.root, **kw)]  # noqa: E731
        self.assertEqual(keys(query="결제"), [urgent["key"]])
        self.assertEqual(keys(priority=1), [urgent["key"]])
        self.assertEqual(keys(label="버그"), [urgent["key"]])
        self.assertEqual(keys(assignee="odin"), ["NOR-2"])
        self.assertEqual(keys(blocked=True), [urgent["key"]])
        self.assertEqual(keys(overdue=True), [overdue["key"]])
        self.assertNotIn("NOR-2", keys(open_only=True))
        self.assertIn(urgent["key"], keys(unassigned=True))

    def test_summary_counts_what_the_menu_shows(self):
        T.create_ticket(self.root, "열린 것", priority=1)
        T.create_ticket(self.root, "도는 것", status="in_progress", assignee="odin")
        T.create_ticket(self.root, "끝난 것", status="done")
        summary = T.summary(self.root)
        self.assertEqual((summary["prefix"], summary["total"], summary["open"]), ("NOR", 3, 2))
        self.assertEqual((summary["started"], summary["done"], summary["unassigned"]), (1, 1, 1))
        self.assertEqual(summary["priority"]["1"], 1)

    def test_a_corrupt_store_is_reported_not_silently_recreated(self):
        """파생 인덱스와 계약이 다르다 — 사람이 적은 원문은 재생성할 곳이 없다."""
        T.create_ticket(self.root, "잃으면 안 되는 것")
        path = studio_db.db_path(self.root)
        with open(path, "wb") as handle:
            handle.write(b"this is not a database, not even close" * 40)
        with self.assertRaises(studio_db.StoreError):
            T.list_tickets(self.root)
        self.assertTrue(os.path.exists(path))  # 지우지 않았다

    def test_a_newer_schema_is_refused_rather_than_downgraded(self):
        T.create_ticket(self.root, "미래에서 온 저장소")
        with sqlite3.connect(studio_db.db_path(self.root)) as conn:
            conn.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(studio_db.SCHEMA_VERSION + 1),))
        with self.assertRaises(studio_db.StoreError):
            T.list_tickets(self.root)


class TestApi(TicketCase):
    def call(self, method, path, params=None, payload=None):
        status, _, body = ticket_api.dispatch(method, path, params, payload, self.root)
        return status, json.loads(body)

    def test_create_read_update_and_move_over_http(self):
        status, ticket = self.call("POST", "/api/tickets", payload={"title": "API로 발급", "priority": 2})
        self.assertEqual((status, ticket["key"]), (201, "NOR-1"))
        status, snapshot = self.call("GET", "/api/tickets")
        self.assertEqual(status, 200)
        self.assertEqual([column["status"] for column in snapshot["board"]["columns"]], list(T.STATUSES))
        # 어휘는 서버가 싣는다 — 화면이 같은 enum 을 한 벌 더 들지 않게
        self.assertEqual([row["id"] for row in snapshot["statuses"]], list(T.STATUSES))
        self.assertEqual([row["value"] for row in snapshot["priorities"]], [1, 2, 3, 4, 0])
        status, moved = self.call("POST", "/api/tickets/move", payload={"ref": "NOR-1", "status": "in_review"})
        self.assertEqual((status, moved["status"]), (200, "in_review"))
        status, edited = self.call("PUT", "/api/tickets", payload={"ref": "NOR-1", "changes": {"assignee": "odin"}})
        self.assertEqual((status, edited["assignee"]), (200, "odin"))

    def test_bad_input_answers_400_and_a_missing_ticket_404(self):
        status, body = self.call("POST", "/api/tickets", payload={"title": ""})
        self.assertEqual((status, body["error"]["code"]), (400, "invalid_ticket"))
        status, body = self.call("GET", "/api/ticket", params={"key": ["NOR-9"]})
        self.assertEqual((status, body["error"]["code"]), (404, "ticket_not_found"))
        status, body = self.call("POST", "/api/tickets/move", payload={"ref": "NOR-1", "status": "shipped"})
        self.assertEqual(status, 400)

    def test_an_unopenable_store_answers_503_not_an_empty_board(self):
        T.create_ticket(self.root, "있던 것")
        with open(studio_db.db_path(self.root), "wb") as handle:
            handle.write(b"corrupt" * 500)
        status, body = self.call("GET", "/api/tickets")
        self.assertEqual((status, body["error"]["code"]), (503, "store_unavailable"))

    def test_unknown_method_on_a_known_path_is_405(self):
        self.assertEqual(self.call("DELETE", "/api/tickets")[0], 405)
        self.assertFalse(ticket_api.owns("/api/tickets/run"))  # 실행은 작업 계층이 소유한다


class TestDesktopBridge(TicketCase):
    def test_the_studio_snapshot_carries_the_ticket_tally(self):
        from asgard.commands import desktop

        T.create_ticket(self.root, "메뉴에 셀 것", priority=1)
        tally = desktop.snapshot_data(self.root)["tickets"]
        self.assertTrue(tally["available"])
        self.assertEqual(tally["open"], 1)

    def test_a_broken_store_does_not_take_the_window_down_with_it(self):
        """기록이 실행을 막으면 기록이 아니라 관문이다 — 창은 뜨되 모른다고 말한다."""
        from asgard.commands import desktop

        T.create_ticket(self.root, "있던 것")
        with open(studio_db.db_path(self.root), "wb") as handle:
            handle.write(b"corrupt" * 500)
        tally = desktop.snapshot_data(self.root)["tickets"]
        self.assertFalse(tally["available"])
        self.assertEqual(tally["open"], 0)

    def test_running_a_ticket_links_the_task_and_starts_the_ticket(self):
        from asgard.commands import desktop

        ticket = T.create_ticket(self.root, "실행할 일감")
        status, _, body = desktop.run_ticket({"ref": ticket["key"], "permission": "manual"}, self.root)
        payload = json.loads(body)
        self.assertEqual(status, 202)
        self.assertEqual(payload["ticket"]["status"], "in_progress")
        self.assertEqual(payload["ticket"]["task_id"], payload["task"]["id"])
        self.assertIn(ticket["key"], payload["task"]["label"])

    def test_a_ticket_runs_where_it_was_filed_not_where_the_window_stands(self):
        """보드는 폴더에 안 매이지만 **실행은 매인다.**

        창은 이제 개인 작업 공간에서 열린다. 그 자리에서 티켓을 돌리면 저장소 얘기인 일감이
        코드 없는 데서 돈다 — 티켓이 적어 둔 자리가 아직 있으면 거기서 돌아야 한다."""
        from asgard.commands import desktop

        elsewhere = os.path.join(self._tmp.name, "somewhere-else")
        os.makedirs(elsewhere)
        ticket = T.create_ticket(self.root, "이 저장소의 일")
        status, _, body = desktop.run_ticket({"ref": ticket["key"], "permission": "manual"}, elsewhere)
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(body)["task"]["root"], os.path.abspath(self.root))

    def test_a_ticket_with_no_folder_behind_it_runs_where_the_window_stands(self):
        """폴더 없이 적힌 일감(기획에서 나온 것이 그렇다)은 갈 자리가 없다 — 창의 자리가 답이다."""
        from asgard.commands import desktop

        here = os.path.join(self._tmp.name, "window-here")
        os.makedirs(here)
        ticket = T.create_ticket("", "폴더 없이 적은 일감", team="NOR")
        status, _, body = desktop.run_ticket({"ref": ticket["key"], "permission": "manual"}, here)
        self.assertEqual(status, 202)
        # 팀에 결속된 폴더가 있으면 그쪽이 이긴다 — 이 팀은 self.root 에 매여 있다
        self.assertEqual(json.loads(body)["task"]["root"], os.path.abspath(self.root))

    def test_a_blocked_ticket_refuses_to_run_and_stays_where_it_was(self):
        from asgard.commands import desktop

        blocker = T.create_ticket(self.root, "선행")
        blocked = T.create_ticket(self.root, "막힌 것")
        T.link_tickets(self.root, blocker["key"], "blocks", blocked["key"])
        status, _, _ = desktop.run_ticket({"ref": blocked["key"]}, self.root)
        self.assertEqual(status, 409)
        self.assertEqual(T.get_ticket(self.root, blocked["key"])["status"], "todo")

    def test_a_finished_task_hands_its_result_back_to_the_ticket(self):
        """성공은 완료가 아니라 검토 중이다 — 종료 코드 0 은 사람이 받아들였다는 뜻이 아니다."""
        from asgard.commands import desktop

        ticket = T.create_ticket(self.root, "되먹임 받을 일감", status="in_progress")
        T.update_ticket(self.root, ticket["key"], {"task_id": "task-abc"})
        desktop.tasks._settle_ticket(self.root, {"id": "task-abc", "status": "ready", "result": "테스트를 고쳤습니다"})
        after = T.get_ticket(self.root, ticket["key"])
        self.assertEqual(after["status"], "in_review")
        self.assertEqual(after["comments_list"][-1]["body"], "테스트를 고쳤습니다")

    def test_a_blocked_task_comments_but_does_not_move_the_ticket(self):
        from asgard.commands import desktop

        ticket = T.create_ticket(self.root, "막힌 실행", status="in_progress")
        T.update_ticket(self.root, ticket["key"], {"task_id": "task-xyz"})
        desktop.tasks._settle_ticket(self.root, {"id": "task-xyz", "status": "blocked", "result": "엔진 설정 없음"})
        after = T.get_ticket(self.root, ticket["key"])
        self.assertEqual(after["status"], "in_progress")
        self.assertIn("엔진 설정 없음", after["comments_list"][-1]["body"])


class TestAgentTool(TicketCase):
    def run_tool(self, args, role="worker", readonly=False):
        registry = build_session_registry()
        return execute_tool(registry, "ticket", args, ToolContext(root=self.root, role=role, readonly=readonly))

    def test_the_agent_files_a_ticket_and_gets_the_number_back(self):
        """번호가 안 돌아오면 그 티켓은 만든 순간 잃어버린 것이다 — 다음 턴이 못 부른다."""
        result = self.run_tool({"action": "create", "title": "스스로 끊은 일감", "priority": 1})
        self.assertEqual(result.status, "ok")
        self.assertIn("NOR-1", result.content)
        self.assertEqual(T.get_ticket(self.root, "NOR-1")["source"], "agent")

    def test_read_only_roles_may_still_file_what_they_found(self):
        """결함을 찾은 자리가 그것을 적을 자리다 — 여기서 막으면 Verifier 의 발견이 증발한다."""
        for role in ("verifier", "thinker", "readonly"):
            with self.subTest(role=role):
                self.assertEqual(self.run_tool({"action": "create", "title": f"{role}가 본 것"}, role).status, "ok")
        self.assertEqual(self.run_tool({"action": "list"}, "verifier").status, "ok")

    def test_list_puts_urgent_first_and_none_last(self):
        for title, priority in (("없음", 0), ("긴급", 1), ("낮음", 4)):
            self.run_tool({"action": "create", "title": title, "priority": priority})
        lines = self.run_tool({"action": "list"}).content.splitlines()
        self.assertEqual([line.split("·")[1].strip() for line in lines], ["긴급", "낮음", "없음"])

    def test_the_tool_reports_a_fixable_mistake_as_a_message(self):
        result = self.run_tool({"action": "create", "title": "   "})
        self.assertEqual(result.status, "error")
        self.assertIn("title", result.content)

    def test_an_unknown_action_is_refused_by_the_schema(self):
        self.assertEqual(self.run_tool({"action": "archive"}).status, "invalid_input")


if __name__ == "__main__":
    unittest.main()
