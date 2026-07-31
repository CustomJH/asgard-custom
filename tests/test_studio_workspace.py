"""워크스페이스 층 — 팀·프로젝트·마일스톤·이니셔티브·사이클·트리아지·반입.

여태 티켓은 폴더마다 파일 하나였다. 폴더를 옮기면 보드가 갈렸고, "지금 뭘 해야 하지"에
답하려면 **먼저 어느 폴더를 열지 알아야** 했다. 일감은 그렇게 살지 않는다.

이 계층이 지켜야 하는 것:
  ① 번호의 주인은 팀이다 — 폴더는 팀으로 들어오고, 폴더가 없어도 팀은 선다
  ② 프로젝트는 팀을 가로지르지만 티켓은 프로젝트 하나에만 속한다(진척의 단위)
  ③ 사이클을 닫으면 안 끝난 일이 다음으로 넘어간다 — 닫힌 주기가 일을 삼키지 않는다
  ④ 밖에서 들어온 일감은 인박스에 선다 — 사람의 백로그에 곧장 섞이지 않는다
  ⑤ 옛 보드는 무손실로 들어온다 — 번호도, 관계도, 원본도 잃지 않는다
"""

import os
import sqlite3
import tempfile
import time
import unittest

from asgard.studio import db as studio_db
from asgard.studio import legacy as L
from asgard.studio import projects as P
from asgard.studio import teams as TM
from asgard.studio import tickets as T


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="asgard-ws-")
        self.addCleanup(self._tmp.cleanup)
        self.root = self.repo("nordic")

    def repo(self, name: str) -> str:
        """저장소 하나를 만들고 **손으로** 그 이름의 팀에 결속한다.

        폴더는 더 이상 스스로 팀이 되지 않는다(그게 프로젝트 종속의 마지막 가닥이었다).
        아래 판정들은 팀의 셈법을 보는 것이지 팀이 어떻게 생겼는지를 보는 게 아니라서,
        옛 자동 결속이 하던 일을 여기서 한 줄로 대신한다."""
        path = os.path.join(self._tmp.name, name)
        os.makedirs(path, exist_ok=True)
        TM.bind_root(TM.create_team(name)["id"], path)
        return path


class TestTeams(WorkspaceCase):
    def test_a_bound_folder_keeps_its_numbers_after_a_rename(self):
        """한 번 결속하면 폴더를 옮겨도 번호가 안 흔들린다.

        결속을 저장소 **안**(`.asgard/studio/team.json`)에도 적기 때문이다 — 워크스페이스의
        표만 두면 경로가 바뀌는 순간 그 팀의 출신을 잃는다."""
        first = T.create_ticket(self.root, "첫 일감")
        self.assertEqual(first["key"], "NOR-1")

        moved = os.path.join(self._tmp.name, "renamed-later")
        os.rename(self.root, moved)
        self.assertEqual(T.create_ticket(moved, "두 번째")["key"], "NOR-2")

    def test_reading_is_workspace_wide_and_the_folder_is_only_a_filter(self):
        """**읽기의 기본은 전체다.** 폴더는 거르는 값이지 경계가 아니다.

        여태는 반대였다 — 아무것도 안 주면 이 폴더의 팀만 봤다. 그래서 같은 명령이 선 자리에
        따라 다른 답을 냈고, 저장소 밖에서 켠 창은 자기 일감을 못 찾았다."""
        other = self.repo("helios")
        T.create_ticket(self.root, "여기 일")
        T.create_ticket(other, "저기 일")

        self.assertEqual(sorted(t["key"] for t in T.list_tickets(self.root)), ["HEL-1", "NOR-1"])
        self.assertEqual(sorted(t["key"] for t in T.list_tickets(other)), ["HEL-1", "NOR-1"])
        self.assertEqual(sorted(t["key"] for t in T.list_tickets(None)), ["HEL-1", "NOR-1"])
        # 좁히고 싶으면 고른다 — `.`은 이 폴더에 결속된 팀
        self.assertEqual([t["key"] for t in T.list_tickets(self.root, team=".")], ["NOR-1"])
        self.assertEqual([t["key"] for t in T.list_tickets(other, team=".")], ["HEL-1"])
        self.assertEqual([t["key"] for t in T.list_tickets(self.root, team="HEL")], ["HEL-1"])
        self.assertEqual(sorted(t["key"] for t in TM.list_teams()), sorted(["HEL", "NOR"]))

    def test_a_clashing_prefix_is_refused_instead_of_sharing_numbers(self):
        """키가 같으면 번호가 겹친다 — 겹치면 `NOR-1`이 둘이 되고 대화가 깨진다.

        팀은 이제 사람이 짓는다. 그래서 조용히 `NOR2`로 비켜 주는 대신 **거절**하고 이름을
        묻는다 — 폴더가 자동으로 팀이 되던 시절엔 물을 사람이 없어서 비켜 줬던 것이다."""
        with self.assertRaisesRegex(TM.TeamError, "already in use"):
            TM.create_team("nordic-two")  # 같은 세 글자 NOR
        self.assertEqual([t["key"] for t in TM.list_teams()], ["NOR"])

    def test_a_team_can_stand_without_a_folder(self):
        """기획은 코드가 생기기 전에 시작한다 — 폴더 없는 팀도 서야 한다."""
        team = TM.create_team("디자인", "DES")
        self.assertEqual(team["roots"], [])
        ticket = T.create_ticket("", "폴더 없이 적는 일감", team="DES")
        self.assertEqual(ticket["key"], "DES-1")

    def test_custom_workflow_states_map_to_the_five_categories(self):
        T.create_ticket(self.root, "seed")
        team = TM.list_teams()[0]["id"]
        TM.create_state(team, "배포 대기", "started", slug="staged")

        self.assertIn("staged", [s["slug"] for s in TM.list_states(team)])
        moved = T.update_ticket(self.root, "NOR-1", {"status": "staged"})
        self.assertEqual(moved["status_label"], "배포 대기")
        self.assertEqual(moved["status_type"], "started")
        # 범주가 started 이므로 '진행'으로 세어진다 — 이름은 팀이 짓고 셈은 범주가 한다
        self.assertEqual(T.summary(self.root)["started"], 1)
        self.assertIn("배포 대기", [c["label"] for c in T.board(self.root)["columns"]])

    def test_a_state_in_use_cannot_be_deleted(self):
        """조용히 지우면 그 티켓들은 이름 없는 칸에 남는다 — 보드에도 안 뜨는데 열린 채로."""
        T.create_ticket(self.root, "seed", status="in_progress")
        team = TM.list_teams()[0]["id"]
        with self.assertRaises(TM.TeamError):
            TM.delete_state(team, "in_progress")
        # 그 칸을 비우면 지울 수 있다 — 막는 것은 상태가 아니라 **거기 서 있는 티켓**이다
        T.update_ticket(self.root, "NOR-1", {"status": "todo"})
        self.assertTrue(TM.delete_state(team, "in_progress"))


class TestProjects(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self.web = self.repo("webapp")
        T.create_ticket(self.root, "seed")
        T.create_ticket(self.web, "seed")

    def test_a_project_spans_teams_and_rolls_progress_into_one_number(self):
        project = P.create_project("결제 개편", lead="윤", teams=["NOR", "WEB"])
        self.assertEqual(sorted(t["key"] for t in project["teams"]), ["NOR", "WEB"])

        a = T.create_ticket(self.root, "서버 API", project=project["id"])
        b = T.create_ticket(self.web, "앱 화면", project=project["id"])
        # 번호는 각자 팀에서 나온다 — 프로젝트는 번호를 주지 않는다
        self.assertEqual((a["key"][:3], b["key"][:3]), ("NOR", "WEB"))

        T.update_ticket(self.root, a["key"], {"status": "done"})
        rolled = P.get_project(project["id"])
        self.assertEqual((rolled["done"], rolled["total"], rolled["progress"]), (1, 2, 0.5))

    def test_a_milestone_needs_its_project(self):
        """마일스톤만 주면 진척이 어느 쪽으로 굴러가는지 모른다."""
        with self.assertRaises(T.TicketError):
            T.create_ticket(self.root, "떠도는 일감", milestone="베타")

    def test_milestones_count_only_their_own_tickets(self):
        project = P.create_project("결제 개편", teams=["NOR"])
        P.add_milestone(project["id"], "설계 확정")
        P.add_milestone(project["id"], "베타")
        one = T.create_ticket(self.root, "설계", project=project["id"], milestone="설계 확정")
        T.create_ticket(self.root, "구현", project=project["id"], milestone="베타")
        T.update_ticket(self.root, one["key"], {"status": "done"})

        stones = {m["name"]: (m["done"], m["total"]) for m in P.list_milestones(project["id"])}
        self.assertEqual(stones, {"설계 확정": (1, 1), "베타": (0, 1)})

    def test_deleting_a_project_frees_its_tickets_instead_of_taking_them(self):
        """프로젝트 하나를 잘못 지운 손이 몇 달치 일감을 같이 가져가면 안 된다."""
        project = P.create_project("잘못 만든 것", teams=["NOR"])
        ticket = T.create_ticket(self.root, "살아남아야 하는 일", project=project["id"])
        self.assertTrue(P.delete_project(project["id"]))
        survivor = T.get_ticket(self.root, ticket["key"])
        self.assertIsNone(survivor["project"])
        self.assertEqual(survivor["title"], "살아남아야 하는 일")

    def test_a_status_change_moves_the_moment_it_implies(self):
        project = P.create_project("끝낼 것")
        done = P.update_project(project["id"], {"status": "completed"})
        self.assertIsNotNone(done["completed_at"])
        # 되돌리면 지운다 — 완료 시각이 남은 '진행 중' 프로젝트는 리드타임을 거짓말한다
        back = P.update_project(project["id"], {"status": "started"})
        self.assertIsNone(back["completed_at"])

    def test_an_update_carries_health_onto_the_project(self):
        """보고와 계기판이 다른 말을 하면 둘 다 안 믿게 된다."""
        project = P.create_project("결제 개편")
        P.add_update(project["id"], "설계 끝", health="at_risk", author="윤")
        self.assertEqual(P.get_project(project["id"])["health"], "at_risk")

    def test_an_initiative_rolls_up_its_projects(self):
        initiative = P.create_initiative("26년 상반기", owner="윤")
        project = P.create_project("결제 개편", teams=["NOR"], initiative=initiative["name"])
        one = T.create_ticket(self.root, "하나", project=project["id"])
        T.create_ticket(self.root, "둘", project=project["id"])
        T.update_ticket(self.root, one["key"], {"status": "done"})

        rolled = P.get_initiative(initiative["id"])
        self.assertEqual((rolled["done"], rolled["total"]), (1, 2))
        self.assertEqual([p["name"] for p in rolled["projects"]], ["결제 개편"])


class TestCycles(WorkspaceCase):
    def test_closing_a_cycle_rolls_unfinished_work_forward(self):
        """안 끝난 일을 닫힌 사이클에 남겨 두면 그 일은 어느 보드에도 안 뜨면서 열린 채로 남는다."""
        T.create_ticket(self.root, "seed")
        team = TM.list_teams()[0]["id"]
        first = TM.create_cycle(team, name="1주차")
        finished = T.create_ticket(self.root, "끝낼 것", cycle=first["number"])
        leftover = T.create_ticket(self.root, "남을 것", cycle=first["number"])
        T.update_ticket(self.root, finished["key"], {"status": "done"})
        second = TM.create_cycle(team, name="2주차")

        closed = TM.close_cycle(team, first["number"], roll=True)
        self.assertEqual(closed["rolled"], 1)
        self.assertEqual(T.get_ticket(self.root, leftover["key"])["cycle"]["id"], second["id"])
        # 끝난 것은 닫힌 사이클에 남는다 — 이력이라 옮기면 그 주기의 성과가 사라진다
        self.assertEqual(T.get_ticket(self.root, finished["key"])["cycle"]["id"], first["id"])

    def test_a_cycle_closes_from_the_folder_that_owns_it(self):
        """사이클은 팀의 것이라 하나를 골라야 닫힌다 — 읽기의 기본(전체)을 그대로 쓰면
        결속된 폴더에서조차 늘 '팀이 없다'가 된다(CLI `asgard ticket cycle --close`의 길)."""
        T.create_ticket(self.root, "seed")
        cycle = TM.create_cycle(TM.get_team("NOR")["id"], name="1주차")
        closed = T.close_cycle(self.root, cycle["number"])
        self.assertEqual((closed["id"], closed["closed_at"] is not None), (cycle["id"], True))

        # 다른 팀 것은 그 팀을 지목해서 닫는다 — 번호는 팀 안에서만 유일하기 때문이다
        self.repo("helios")
        theirs = TM.create_cycle(TM.get_team("HEL")["id"], name="가")
        self.assertEqual(T.close_cycle(self.root, theirs["number"], team="HEL")["id"], theirs["id"])
        with self.assertRaisesRegex(T.TicketError, "team not found"):
            T.close_cycle(self.root, theirs["number"], team="NOPE")

    def test_cycle_numbers_are_per_team(self):
        other = self.repo("helios")
        T.create_ticket(self.root, "seed")
        T.create_ticket(other, "seed")
        keys = {t["key"]: t["id"] for t in TM.list_teams()}
        self.assertEqual(TM.create_cycle(keys["NOR"], name="가")["number"], 1)
        self.assertEqual(TM.create_cycle(keys["HEL"], name="나")["number"], 1)


class TestTriage(WorkspaceCase):
    def setUp(self):
        super().setUp()
        T.create_ticket(self.root, "seed")
        self.team = TM.list_teams()[0]["id"]
        TM.update_team(self.team, {"triage": True})

    def test_agent_tickets_land_in_the_inbox_not_the_board(self):
        """기계가 만든 일감이 사람의 백로그에 곧장 섞이면 백로그는 곧 아무도 안 보는 목록이 된다."""
        filed = T.create_ticket(self.root, "지나가다 본 결함", source="agent")
        self.assertTrue(filed["triage"])
        self.assertEqual([t["key"] for t in T.triage_queue(self.root)], [filed["key"]])
        self.assertNotIn(filed["key"], [t["key"] for t in T.list_tickets(self.root)])
        # 사람이 적은 것은 그대로 보드로 간다
        self.assertFalse(T.create_ticket(self.root, "내가 적은 것")["triage"])

    def test_accepting_moves_it_to_the_teams_default_status(self):
        filed = T.create_ticket(self.root, "받을 것", source="agent")
        taken = T.triage_accept(self.root, filed["key"], actor="윤", note="맞는 지적")
        self.assertFalse(taken["triage"])
        self.assertEqual(taken["status"], "backlog")  # 팀 기본값
        self.assertEqual(T.triage_queue(self.root), [])
        self.assertEqual(len(taken["comments_list"]), 1)

    def test_declining_closes_it_as_canceled_without_deleting_the_reason(self):
        filed = T.create_ticket(self.root, "거절할 것", source="agent")
        out = T.triage_decline(self.root, filed["key"], actor="윤", note="이미 있는 동작")
        self.assertEqual(out["status"], "canceled")
        self.assertFalse(out["triage"])
        self.assertIn("이미 있는 동작", [c["body"] for c in out["comments_list"]])

    def test_snoozing_hides_it_until_its_time(self):
        filed = T.create_ticket(self.root, "나중에 볼 것", source="agent")
        T.triage_snooze(self.root, filed["key"], time.time() + 3600, actor="윤")
        self.assertEqual(T.triage_queue(self.root), [])
        T.triage_snooze(self.root, filed["key"], time.time() - 1, actor="윤")
        self.assertEqual([t["key"] for t in T.triage_queue(self.root)], [filed["key"]])


class TestLegacyImport(WorkspaceCase):
    """폴더마다 보드가 하나이던 시절의 저장소를 잃지 않는다."""

    def _make_legacy(self, root: str, prefix: str = "OLD") -> str:
        directory = os.path.join(root, ".asgard", "studio")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "studio.db")
        old = sqlite3.connect(path)
        old.executescript(
            """
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE cycles(id TEXT PRIMARY KEY, number INTEGER, name TEXT, starts_at REAL,
                ends_at REAL, closed_at REAL, created_at REAL);
            CREATE TABLE labels(id TEXT PRIMARY KEY, name TEXT, color TEXT, created_at REAL);
            CREATE TABLE tickets(id TEXT PRIMARY KEY, key TEXT, seq INTEGER, title TEXT, body TEXT,
                status TEXT, priority INTEGER, estimate INTEGER, assignee TEXT, reporter TEXT,
                source TEXT, parent_id TEXT, cycle_id TEXT, plan_id TEXT, plan_record TEXT,
                task_id TEXT, position REAL, created_at REAL, updated_at REAL, started_at REAL,
                completed_at REAL, canceled_at REAL, due_at REAL);
            CREATE TABLE ticket_labels(ticket_id TEXT, label_id TEXT);
            CREATE TABLE ticket_links(source_id TEXT, target_id TEXT, kind TEXT, created_at REAL);
            CREATE TABLE comments(id TEXT PRIMARY KEY, ticket_id TEXT, author TEXT, body TEXT, created_at REAL);
            CREATE TABLE activity(id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT, actor TEXT,
                field TEXT, before TEXT, after TEXT, created_at REAL);
            """
        )
        old.executemany("INSERT INTO meta VALUES(?,?)", [("prefix", prefix), ("schema", "1"), ("seq", "2")])
        old.execute("INSERT INTO labels VALUES('l1','버그','rose',1.0)")
        old.execute(
            "INSERT INTO tickets VALUES('t1',?,1,'옛 일감','본문','in_progress',2,3,'윤','윤','user',"
            "NULL,NULL,'','','',1.0,1.0,2.0,1.5,NULL,NULL,NULL)",
            (f"{prefix}-1",),
        )
        old.execute(
            "INSERT INTO tickets VALUES('t2',?,2,'옛 하위','','todo',0,NULL,'','','user','t1',NULL,"
            "'','','',2.0,1.0,2.0,NULL,NULL,NULL,NULL)",
            (f"{prefix}-2",),
        )
        old.execute("INSERT INTO ticket_labels VALUES('t1','l1')")
        old.execute("INSERT INTO comments VALUES('c1','t1','윤','옛 댓글',3.0)")
        old.execute(
            "INSERT INTO activity(ticket_id,actor,field,before,after,created_at) "
            "VALUES('t1','윤','status','할 일','진행 중',2.0)"
        )
        old.commit()
        old.close()
        return path

    def test_an_old_board_arrives_whole_and_keeps_its_numbers(self):
        source = self._make_legacy(self.root)
        self.assertEqual(L.pending_roots([self.root]), [os.path.abspath(self.root)])

        out = L.import_root(self.root)
        self.assertTrue(out["imported"])
        self.assertEqual((out["team"], out["tickets"], out["comments"]), ("OLD", 2, 1))

        one = T.get_ticket(self.root, "OLD-1")
        self.assertEqual((one["status"], one["priority"], one["estimate"]), ("in_progress", 2, 3))
        self.assertEqual([label["name"] for label in one["labels"]], ["버그"])
        self.assertEqual([kid["key"] for kid in one["children_list"]], ["OLD-2"])
        self.assertEqual(len(one["comments_list"]), 1)
        self.assertTrue(one["activity"])
        # 번호는 이어서 나온다 — 반입이 카운터를 되돌리면 발급된 번호가 두 번 나온다
        self.assertEqual(T.create_ticket(self.root, "반입 뒤")["key"], "OLD-3")
        # 원본은 그대로 — 반입이 잘못됐을 때 돌아갈 곳이 있어야 한다
        self.assertTrue(os.path.isfile(source))

    def test_importing_twice_does_not_import_twice(self):
        self._make_legacy(self.root)
        L.import_root(self.root)
        again = L.import_root(self.root)
        self.assertFalse(again["imported"])
        self.assertEqual(len(T.list_tickets(self.root)), 2)
        self.assertEqual(L.pending_roots([self.root]), [])

    def test_a_clashing_prefix_is_reported_not_silently_renumbered(self):
        """조용히 번호를 바꾸면 어제 적어 둔 메모가 오늘 다른 티켓을 가리킨다."""
        TM.create_team("이미 있는 팀", "OLD")
        self._make_legacy(self.root)
        out = L.import_root(self.root)
        self.assertTrue(out["imported"])
        self.assertTrue(out["renamed"])
        self.assertEqual(out["was"], "OLD")
        self.assertNotEqual(out["team"], "OLD")


class TestWorkspaceStore(WorkspaceCase):
    def test_the_store_lives_in_the_agent_home_not_the_repo(self):
        T.create_ticket(self.root, "첫 건")
        self.assertEqual(studio_db.db_path(), studio_db.workspace_path())
        self.assertTrue(os.path.isfile(studio_db.workspace_path()))
        # 리포 안에 남는 것은 결속 한 줄뿐이다 — 보드가 아니다
        self.assertFalse(os.path.exists(studio_db.legacy_db_path(self.root)))
        self.assertEqual(studio_db.read_bind(self.root)["key"], "NOR")


class TestUntouchedWorkspace(unittest.TestCase):
    """아무것도 안 한 기계 — 이 판정은 팀 하나 없는 자리에서만 뜻이 있다."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="asgard-untouched-")
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "plain")  # 결속도 티켓도 없는 폴더
        os.makedirs(self.root)

    def test_reading_never_creates_the_workspace(self):
        """창을 열어 본 것만으로 저장소가 생기면, 안 쓴 기능이 자리를 차지한다."""
        self.assertEqual(T.list_tickets(self.root), [])
        self.assertEqual(T.board(self.root)["total"], 0)
        self.assertEqual(T.triage_queue(self.root), [])
        self.assertEqual(P.list_projects(), [])
        self.assertEqual(TM.list_teams(), [])
        self.assertFalse(os.path.exists(studio_db.workspace_path()))
        self.assertFalse(os.path.exists(studio_db.store_dir(self.root)))

    def test_a_ticket_filed_from_an_unbound_folder_lands_in_the_workspace_team(self):
        """폴더는 **스스로 팀이 되지 않는다.**

        여태는 결속 없는 폴더에서 적으면 그 폴더 이름으로 팀이 하나 섰다. 저장소 다섯 곳을
        오가며 일한 사람은 고른 적 없는 팀 다섯과 번호 다섯 갈래를 갖게 됐다 — 폴더가
        프로젝트라는 전제가 거기 남아 있었다."""
        ticket = T.create_ticket(self.root, "결속 없는 폴더에서 적는 일감")
        self.assertEqual(ticket["key"], "WRK-1")
        self.assertEqual([team["key"] for team in TM.list_teams()], ["WRK"])
        # 저장소 안에는 아무것도 안 남는다 — 결속은 사람이 걸 때만 적힌다
        self.assertFalse(os.path.exists(studio_db.store_dir(self.root)))

        elsewhere = os.path.join(self._tmp.name, "another")
        os.makedirs(elsewhere)
        self.assertEqual(T.create_ticket(elsewhere, "다른 폴더")["key"], "WRK-2")
        self.assertEqual([team["key"] for team in TM.list_teams()], ["WRK"])


if __name__ == "__main__":
    unittest.main()


class TestWorkspaceApi(WorkspaceCase):
    """창이 쓰는 문 — 팀·프로젝트·트리아지가 한 왕복에 실려야 한다."""

    def call(self, method, path, params=None, payload=None):
        import json

        from asgard.commands import ticket_api

        status, _, body = ticket_api.dispatch(method, path, params or {}, payload or {}, self.root)
        return status, json.loads(body)

    def test_the_snapshot_carries_every_axis_in_one_round_trip(self):
        self.call("POST", "/api/tickets", payload={"title": "첫 일감", "priority": 2})
        status, snap = self.call("GET", "/api/tickets")
        self.assertEqual(status, 200)
        for key in ("board", "summary", "teams", "projects", "initiatives", "triage", "cycles", "legacy"):
            self.assertIn(key, snap, key)
        self.assertEqual([t["key"] for t in snap["teams"]], ["NOR"])
        # 어휘도 서버가 싣는다 — 화면이 같은 enum을 한 벌 더 들면 언젠가 한 곳만 고친다
        self.assertTrue(snap["project_statuses"] and snap["healths"] and snap["status_types"])

    def test_a_project_can_be_built_and_read_over_http(self):
        self.call("POST", "/api/tickets", payload={"title": "seed"})
        status, project = self.call(
            "POST", "/api/projects", payload={"name": "결제 개편", "teams": ["NOR"], "lead": "윤"}
        )
        self.assertEqual(status, 201)
        self.call("POST", "/api/projects/milestone", payload={"ref": project["id"], "name": "베타"})
        self.call("POST", "/api/tickets", payload={"title": "서버 API", "project": project["id"], "milestone": "베타"})
        status, detail = self.call("GET", "/api/project", {"ref": [project["id"]]})
        self.assertEqual(status, 200)
        self.assertEqual([m["name"] for m in detail["milestones"]], ["베타"])
        self.assertEqual([t["title"] for t in detail["tickets"]], ["서버 API"])

    def test_triage_can_be_worked_from_the_window(self):
        self.call("POST", "/api/tickets", payload={"title": "seed"})
        status, teams = self.call("GET", "/api/teams")
        team = teams["teams"][0]["id"]
        self.call("PUT", "/api/teams", payload={"ref": team, "changes": {"triage": True}})
        _, filed = self.call("POST", "/api/tickets", payload={"title": "에이전트 결함", "source": "agent"})
        self.assertTrue(filed["triage"])

        status, queue = self.call("GET", "/api/triage")
        self.assertEqual([t["key"] for t in queue["tickets"]], [filed["key"]])
        status, taken = self.call("POST", "/api/triage/accept", payload={"ref": filed["key"], "actor": "odin"})
        self.assertEqual(status, 200)
        self.assertFalse(taken["triage"])

    def test_an_unknown_team_is_a_client_error_not_a_crash(self):
        self.call("POST", "/api/tickets", payload={"title": "seed"})
        status, out = self.call("GET", "/api/tickets", {"team": ["NOPE"]})
        self.assertEqual(status, 400)
        self.assertIn("team not found", out["error"]["message"])


class TestAgentWorkflow(WorkspaceCase):
    """에이전트가 **일하면서** 티켓을 움직인다 — 끝난 뒤에 적는 것이 아니라.

    보드가 소원 목록이 아니라 '무슨 일이 실제로 있었는지의 기록'이 되려면 이 흐름이
    툴 한 벌로 끝나야 한다: 열고 → 시작하고 → 검토로 넘긴다."""

    def run_tool(self, args, role="worker", readonly=False):
        from asgard.agent.tool_kernel import ToolContext, build_session_registry, execute_tool

        registry = build_session_registry()
        return execute_tool(registry, "ticket", args, ToolContext(root=self.root, role=role, readonly=readonly))

    def test_open_start_finish_is_one_ticket_moving_not_three(self):
        filed = self.run_tool({"action": "create", "title": "결제 재시도에 지수 백오프 적용", "priority": 2})
        self.assertEqual(filed.status, "ok")
        self.assertIn("NOR-1", filed.content)

        started = self.run_tool({"action": "start", "ref": "NOR-1", "text": "백오프 상수부터 본다"})
        self.assertEqual(started.status, "ok")
        row = T.get_ticket(self.root, "NOR-1")
        self.assertEqual(row["status"], "in_progress")
        self.assertEqual(row["assignee"], "agent")  # 시작하면 주인이 생긴다
        self.assertIsNotNone(row["started_at"])

        done = self.run_tool({"action": "finish", "ref": "NOR-1", "text": "테스트까지 통과"})
        self.assertEqual(done.status, "ok")
        row = T.get_ticket(self.root, "NOR-1")
        # 완료가 아니라 **검토 중** — 프로세스가 끝난 것과 사람이 받아들인 것은 다른 일이다
        self.assertEqual(row["status"], "in_review")
        self.assertIsNone(row["completed_at"])
        self.assertEqual(len(T.list_tickets(self.root)), 1)  # 줄은 여전히 하나다

    def test_the_agent_can_only_attach_projects_that_exist(self):
        """프로젝트 이름을 지어내면 진척이 어디에도 안 잡히는 유령 묶음이 생긴다."""
        self.run_tool({"action": "create", "title": "seed"})
        bad = self.run_tool({"action": "create", "title": "떠도는 일", "project": "없는 프로젝트"})
        self.assertEqual(bad.status, "error")
        self.assertIn("project not found", bad.content)

        P.create_project("결제 개편", teams=["NOR"])
        listed = self.run_tool({"action": "projects"})
        self.assertIn("결제 개편", listed.content)
        ok = self.run_tool({"action": "create", "title": "서버 API", "project": "결제 개편"})
        self.assertEqual(ok.status, "ok")
        self.assertIn("결제 개편", ok.content)

    def test_a_triaged_team_tells_the_agent_the_ticket_is_waiting(self):
        """'만들었으니 됐다'로 끝내지 않게, 인박스에 섰다는 사실이 툴의 답에 실려야 한다."""
        self.run_tool({"action": "create", "title": "seed"})
        TM.update_team(TM.list_teams()[0]["id"], {"triage": True})
        filed = self.run_tool({"action": "create", "title": "지나가다 본 결함"})
        self.assertIn("트리아지", filed.content)
        self.assertIn("사람이 받아야", filed.content)

    def test_a_read_only_role_can_still_open_start_and_report(self):
        """결함을 찾은 자리가 그것을 적을 자리다 — 읽기 전용이라고 막으면 발견이 증발한다."""
        for action, args in (
            ("create", {"title": "검증 중 발견"}),
            ("start", {"ref": "NOR-1"}),
            ("finish", {"ref": "NOR-1"}),
            ("projects", {}),
        ):
            with self.subTest(action=action):
                self.assertEqual(self.run_tool({"action": action, **args}, "verifier").status, "ok")


class TestProjectSurface(WorkspaceCase):
    """프로젝트 화면이 드는 것 — 자료·라벨·멤버·진척 분해.

    Linear의 프로젝트 페이지가 오른쪽 판에 이 넷을 세우는 이유는 같다: "무엇으로 정해졌고,
    무엇에 기대고 있고, 누가 남은 몫을 들고 있나"가 프로젝트를 볼 때의 세 물음이다."""

    def setUp(self):
        super().setUp()
        T.create_ticket(self.root, "seed")
        self.project = P.create_project("결제 개편", teams=["NOR"], lead="윤")

    def test_resources_only_take_addresses_that_can_be_opened(self):
        """`javascript:`를 목록에 담아 두면 그 목록이 언젠가 클릭되는 실행 경로가 된다."""
        P.add_resource(self.project["id"], "설계 문서", "https://example.com/doc")
        self.assertEqual([r["title"] for r in P.list_resources(self.project["id"])], ["설계 문서"])
        for bad in ("javascript:alert(1)", "data:text/html,<script>", "vbscript:x"):
            with self.subTest(url=bad), self.assertRaises(P.ProjectError):
                P.add_resource(self.project["id"], "나쁜 것", bad)

    def test_a_resource_can_be_dropped_without_touching_the_project(self):
        one = P.add_resource(self.project["id"], "대시보드", "https://example.com/d")
        self.assertTrue(P.delete_resource(self.project["id"], one["id"]))
        self.assertEqual(P.list_resources(self.project["id"]), [])
        self.assertEqual(P.get_project(self.project["id"])["name"], "결제 개편")

    def test_project_labels_share_the_ticket_vocabulary(self):
        """라벨은 표가 하나여야 한다 — 두 벌이면 같은 이름이 다른 색으로 두 번 산다."""
        P.set_labels(self.project["id"], ["플랫폼", "결제"])
        self.assertEqual(
            sorted(label["name"] for label in P.get_project(self.project["id"])["labels"]), ["결제", "플랫폼"]
        )
        T.create_ticket(self.root, "라벨 쓰는 티켓", labels=["플랫폼"])
        names = [row["name"] for row in T.list_labels()]
        self.assertEqual(names.count("플랫폼"), 1)

    def test_progress_breaks_down_by_assignee_label_and_cycle(self):
        """총계만 보면 '80% 왔다'까지는 알아도 **누가 남은 20%를 들고 있는지**를 모른다."""
        mine = T.create_ticket(self.root, "내 것", project=self.project["id"], assignee="윤", labels=["backend"])
        T.create_ticket(self.root, "주인 없는 것", project=self.project["id"], labels=["frontend"])
        T.update_ticket(self.root, mine["key"], {"status": "done"})

        breakdown = P.get_project(self.project["id"])["breakdown"]
        by_name = {row["name"]: (row["done"], row["total"]) for row in breakdown["assignees"]}
        self.assertEqual(by_name["윤"], (1, 1))
        self.assertEqual(by_name[""], (0, 1))  # 주인 없는 몫은 지우지 않고 그대로 센다
        self.assertEqual({row["name"] for row in breakdown["labels"]}, {"backend", "frontend"})
        self.assertIn("cycles", breakdown)

    def test_the_project_endpoint_carries_everything_the_page_draws(self):
        import json

        from asgard.commands import ticket_api

        P.add_milestone(self.project["id"], "베타")
        P.add_resource(self.project["id"], "문서", "https://example.com")
        P.add_update(self.project["id"], "순항 중", health="on_track", author="윤")
        T.create_ticket(self.root, "이 프로젝트의 일", project=self.project["id"])

        status, _, body = ticket_api.dispatch("GET", "/api/project", {"ref": [self.project["id"]]}, {}, self.root)
        page = json.loads(body)
        self.assertEqual(status, 200)
        for key in ("milestones", "updates", "resources", "breakdown", "labels", "members", "teams", "tickets"):
            self.assertIn(key, page, key)
        self.assertEqual([t["title"] for t in page["tickets"]], ["이 프로젝트의 일"])

    def test_list_rows_carry_their_parent_so_a_sub_issue_is_not_an_orphan(self):
        """목록의 한 줄도 '이게 무엇의 조각인가'를 말해야 한다 — 상세에만 실으면
        하위 티켓이 목록에서 고아처럼 보이고, 사람은 그것만 보고 우선순위를 매긴다."""
        parent = T.create_ticket(self.root, "큰 일", project=self.project["id"])
        T.create_ticket(self.root, "조각", parent=parent["key"], project=self.project["id"])
        rows = {row["key"]: row for row in T.list_tickets(self.root)}
        self.assertEqual(rows[parent["key"]]["parent"], None)
        child = next(row for row in rows.values() if row["title"] == "조각")
        self.assertEqual(child["parent"]["key"], parent["key"])
        self.assertEqual(child["parent"]["title"], "큰 일")
