"""문서 계층과 `@` 부름 — 티켓 옆에 사는 글, 그리고 댓글에서 일이 갈리는 자리.

이 둘이 지켜야 하는 것:
  ① 문서는 백로그의 셈에 안 든다 — 닫히지 않는 글이 '열린 건수'를 흐리면 목록을 못 믿는다
  ② 목록은 본문을 안 준다 — 발췌만. 본문은 열 때 온다
  ③ 모르는 칸은 거절한다 — 조용히 무시하면 오타 한 글자가 유실로 나타난다
  ④ 부르기와 배차는 갈려 있다 — 댓글을 저장하는 것만으로 프로세스가 뜨면 안 된다
  ⑤ 없는 이름은 없다고 말한다 — 조용히 빼면 사람은 자기가 부른 줄 안다
"""

import json
import os
import tempfile
import unittest

from asgard.commands import ticket_api
from asgard.studio import documents as D
from asgard.studio import mentions
from asgard.studio import projects as P
from asgard.studio import teams as TM
from asgard.studio import tickets as T


class DocumentCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="asgard-docs-")
        self.root = os.path.join(self._tmp.name, "nordic")
        os.makedirs(self.root)
        self.addCleanup(self._tmp.cleanup)
        TM.bind_root(TM.create_team("nordic")["id"], self.root)

    def call(self, method, path, params=None, payload=None):
        status, _, body = ticket_api.dispatch(method, path, params, payload, self.root)
        return status, json.loads(body)


class TestDocuments(DocumentCase):
    def test_a_document_starts_with_only_a_title(self):
        """자리를 반드시 고르게 하면 그 글은 안 적히거나 엉뚱한 프로젝트에 걸린다."""
        doc = D.create_document("설계 노트")
        self.assertEqual((doc["title"], doc["body"]), ("설계 노트", ""))
        self.assertIsNone(doc["project"])
        self.assertIsNone(doc["team"])
        self.assertEqual([row["title"] for row in D.list_documents()], ["설계 노트"])

    def test_documents_do_not_show_up_in_the_ticket_tally(self):
        """닫히지 않는 글이 '열린 건수'에 섞이면 그 수는 곧 거짓말이 된다."""
        T.create_ticket(self.root, "열린 일감")
        D.create_document("사양", "닫히지 않는 글")
        summary = T.summary(self.root)
        self.assertEqual((summary["total"], summary["open"]), (1, 1))
        self.assertEqual(T.board(self.root)["total"], 1)

    def test_the_list_carries_an_excerpt_and_not_the_body(self):
        D.create_document("긴 글", "# 큰 제목\n\n> 인용\n\n실제 첫 문단입니다.\n" + ("가" * 5000))
        row = D.list_documents()[0]
        self.assertNotIn("body", row)  # 목록에 본문을 넣으면 서랍 하나가 화면 지연이 된다
        self.assertEqual(row["excerpt"], "큰 제목")  # 마크다운 장식은 지운다
        self.assertIn("body", D.get_document(row["id"]))

    def test_an_empty_first_line_is_skipped_when_building_the_excerpt(self):
        doc = D.create_document("빈 줄로 시작", "\n\n   \n첫 글자는 여기부터")
        self.assertEqual(D.list_documents()[0]["excerpt"], "첫 글자는 여기부터")
        self.assertEqual(D.get_document(doc["id"])["body"].lstrip("\n").strip(), "첫 글자는 여기부터")

    def test_unknown_fields_are_refused_rather_than_ignored(self):
        doc = D.create_document("오타 방지")
        with self.assertRaises(D.DocumentError):
            D.update_document(doc["id"], {"titel": "오타"})
        self.assertEqual(D.get_document(doc["id"])["title"], "오타 방지")

    def test_editing_moves_the_document_to_the_top_of_the_list(self):
        first = D.create_document("먼저 쓴 글")
        D.create_document("나중에 쓴 글")
        self.assertEqual(D.list_documents()[0]["title"], "나중에 쓴 글")
        D.update_document(first["id"], {"body": "고쳐 씀"})
        self.assertEqual(D.list_documents()[0]["title"], "먼저 쓴 글")

    def test_hanging_a_document_under_a_project_and_letting_go(self):
        project = P.create_project("결제 개편")
        doc = D.create_document("결제 사양", project=project["id"])
        self.assertEqual(D.list_documents(project=project["id"])[0]["id"], doc["id"])
        D.update_document(doc["id"], {"project": ""})
        self.assertEqual(D.list_documents(project=project["id"]), [])
        self.assertEqual(len(D.list_documents()), 1)  # 자리에서 풀었다고 글을 잃지는 않는다

    def test_deleting_the_project_keeps_the_document(self):
        """프로젝트에서 푸는 것과 글을 잃는 것은 다른 일이다."""
        project = P.create_project("사라질 프로젝트")
        doc = D.create_document("남아야 할 글", "본문", project=project["id"])
        P.delete_project(project["id"])
        self.assertIsNone(D.get_document(doc["id"])["project"])
        self.assertEqual(D.get_document(doc["id"])["body"], "본문")

    def test_search_reaches_into_the_body(self):
        D.create_document("제목에는 없음", "본문 안에 비프로스트")
        D.create_document("다른 글", "관계 없는 내용")
        self.assertEqual([row["title"] for row in D.list_documents(query="비프로스트")], ["제목에는 없음"])

    def test_archiving_hides_it_without_losing_it(self):
        doc = D.create_document("치워 둘 글")
        D.archive_document(doc["id"])
        self.assertEqual(D.list_documents(), [])
        self.assertEqual(len(D.list_documents(include_archived=True)), 1)
        D.archive_document(doc["id"], False)
        self.assertEqual(len(D.list_documents()), 1)

    def test_reading_an_untouched_machine_makes_no_file(self):
        """읽기는 자리를 만들지 않는다 — 문서 화면을 열어 본 것만으로 워크스페이스가 생기면 안 된다."""
        from asgard.studio import db as studio_db

        os.remove(studio_db.workspace_path())
        self.assertEqual(D.list_documents(), [])
        self.assertFalse(os.path.exists(studio_db.workspace_path()))


class TestDocumentApi(DocumentCase):
    def test_the_window_can_open_write_and_read_a_document(self):
        status, doc = self.call("POST", "/api/docs", payload={"title": "회고", "actor": "odin"})
        self.assertEqual((status, doc["title"]), (201, "회고"))
        status, saved = self.call(
            "PUT", "/api/docs", payload={"ref": doc["id"], "changes": {"body": "# 무엇이 됐나"}, "actor": "odin"}
        )
        self.assertEqual((status, saved["body"]), (200, "# 무엇이 됐나"))
        status, read = self.call("GET", "/api/doc", params={"ref": [doc["id"]]})
        self.assertEqual((status, read["body"]), (200, "# 무엇이 됐나"))

    def test_the_board_snapshot_carries_documents_as_excerpts(self):
        D.create_document("보드에 실릴 글", "첫 줄이 발췌가 된다")
        status, snapshot = self.call("GET", "/api/tickets")
        self.assertEqual(status, 200)
        self.assertEqual(snapshot["documents"][0]["excerpt"], "첫 줄이 발췌가 된다")
        self.assertNotIn("body", snapshot["documents"][0])

    def test_a_missing_document_is_404_and_a_blank_title_is_400(self):
        """처방이 다르다 — 빈 제목은 고쳐 보내면 되고, 없는 문서는 고쳐 보내도 없다."""
        status, body = self.call("GET", "/api/doc", params={"ref": ["없는글"]})
        self.assertEqual((status, body["error"]["code"]), (404, "document_not_found"))
        status, body = self.call("POST", "/api/docs", payload={"title": "  "})
        self.assertEqual((status, body["error"]["code"]), (400, "invalid_document"))

    def test_deleting_over_http(self):
        doc = D.create_document("지울 글")
        status, body = self.call("POST", "/api/docs/delete", payload={"ref": doc["id"]})
        self.assertEqual((status, body["deleted"]), (200, True))
        self.assertEqual(D.list_documents(), [])


class TestMentions(unittest.TestCase):
    """`@이름` 읽기 — 저장소를 안 본다(프로필 명부만)."""

    def test_an_email_address_is_not_a_mention(self):
        self.assertEqual(mentions.handles("odin@asgard.io 로 보내 주세요"), [])
        self.assertEqual(mentions.handles("파일 a.b@c 도"), [])

    def test_names_come_back_in_order_without_repeats_and_case_folded(self):
        found = mentions.handles("@Freyja 여기 · @eitri 저기 · @freyja 다시")
        self.assertEqual(found, ["freyja", "eitri"])

    def test_an_unknown_name_is_reported_rather_than_dropped(self):
        """빼면 화면은 '아무도 안 불렸다'를 그리고, 사람은 자기가 부른 줄 안다."""
        rows = mentions.resolve("@아무도 @zzznotanagent 부름")
        self.assertEqual([row["handle"] for row in rows], ["zzznotanagent"])
        self.assertFalse(rows[0]["known"])
        self.assertEqual(mentions.agents("@zzznotanagent"), [])

    def test_the_roster_is_the_machines_own_agents(self):
        handles = {row["handle"] for row in mentions.roster()}
        self.assertIn("default", handles)  # 늘 서 있는 하나


class TestMentionDispatch(DocumentCase):
    """부르기(기록)와 맡기기(실행)가 갈려 있는지."""

    def test_posting_a_comment_reports_who_was_called_but_starts_nothing(self):
        from asgard.commands.studio import tasks

        ticket = T.create_ticket(self.root, "화면 손보기")
        before = len(tasks._TASKS)
        status, posted = self.call(
            "POST",
            "/api/tickets/comment",
            payload={"ref": ticket["key"], "body": "@default 여기 부탁", "actor": "odin"},
        )
        self.assertEqual(status, 201)
        self.assertEqual([row["handle"] for row in posted["mentions"]], ["default"])
        self.assertTrue(posted["mentions"][0]["known"])
        # 저장 하나에 프로세스가 딸려 뜨면 안 된다 — 부르기만 하고 안 맡기는 것도 정상이다
        self.assertEqual(len(tasks._TASKS), before)

    def test_the_roster_rides_along_with_the_board_so_the_window_never_holds_its_own(self):
        status, snapshot = self.call("GET", "/api/tickets")
        self.assertEqual(status, 200)
        self.assertIn("default", {row["handle"] for row in snapshot["mention_roster"]})

    def test_assignment_belongs_to_the_task_layer_not_the_record_layer(self):
        """실행은 기록의 것이 아니다 — `run`이 그렇듯 부름도 작업 계층이 소유한다."""
        self.assertFalse(ticket_api.owns("/api/tickets/assign"))

    def test_assigning_starts_a_task_as_that_agent_and_moves_the_ticket(self):
        from asgard.commands.studio import routes, tasks

        ticket = T.create_ticket(self.root, "여백 손보기")
        status, _, body = routes.dispatch_post(
            "/api/tickets/assign",
            {"ref": ticket["key"], "agent": "default", "note": "여백만요", "permission": "manual"},
            self.root,
        )
        out = json.loads(body)
        self.assertEqual(status, 202)
        self.assertEqual(out["ticket"]["status"], "in_progress")
        self.assertEqual(out["ticket"]["assignee"], "default")
        self.assertEqual(out["ticket"]["task_id"], out["task"]["id"])
        # 부른 자리의 말이 지시에 들어간다 — 빼면 "이 부분만"이라고 적은 뜻이 사라진다
        self.assertIn("여백만요", tasks._TASKS[out["task"]["id"]]["prompt"])

    def test_an_agent_that_does_not_exist_is_refused_before_anything_moves(self):
        from asgard.commands.studio import routes

        ticket = T.create_ticket(self.root, "안 맡겨질 일")
        status, _, body = routes.dispatch_post(
            "/api/tickets/assign", {"ref": ticket["key"], "agent": "zzznotanagent"}, self.root
        )
        self.assertEqual(status, 400)
        self.assertIn("zzznotanagent", json.loads(body)["error"])
        self.assertEqual(T.get_ticket(self.root, ticket["key"])["status"], ticket["status"])
        self.assertEqual(T.get_ticket(self.root, ticket["key"])["task_id"], "")

    def test_a_closed_ticket_cannot_be_handed_to_anyone(self):
        from asgard.commands.studio import routes

        ticket = T.create_ticket(self.root, "이미 끝난 일", status="done")
        status, _, _ = routes.dispatch_post(
            "/api/tickets/assign", {"ref": ticket["key"], "agent": "default"}, self.root
        )
        self.assertEqual(status, 409)

    def test_calling_someone_does_not_take_the_ticket_from_its_owner(self):
        """부름은 요청이지 인수인계가 아니다."""
        from asgard.commands.studio import routes

        ticket = T.create_ticket(self.root, "이미 주인이 있는 일", assignee="odin")
        status, _, body = routes.dispatch_post(
            "/api/tickets/assign", {"ref": ticket["key"], "agent": "default", "permission": "manual"}, self.root
        )
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(body)["ticket"]["assignee"], "odin")


if __name__ == "__main__":
    unittest.main()
