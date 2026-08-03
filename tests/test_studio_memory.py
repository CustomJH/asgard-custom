"""Studio 작업 공간의 기억과 경계 — 영속화 · 프로젝트 전환 · 산출물 열기.

여기서 지키는 것은 세 가지다.
  · 작업은 창을 닫아도 남고, 죽은 작업을 "실행 중"이라 말하지 않는다.
  · 작업은 프로젝트에 속한다 — 경계를 옮기면 남의 이력이 따라오지 않는다.
  · 산출물 열기는 프로젝트 경계 밖으로 한 걸음도 못 나간다.
"""

import json
import os
import tempfile
import time
import unittest
from unittest import mock

from asgard.commands import studio, studio_store


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        with studio.state._TASK_LOCK:
            studio.state._TASKS.clear()
        home = tempfile.mkdtemp(prefix="asgard-studio-home-")
        patcher = mock.patch.dict(os.environ, {studio_store.STUDIO_STATE_ENV: home})
        patcher.start()
        self.addCleanup(patcher.stop)
        studio.state._LOADED_ROOTS.clear()
        studio.state._CURRENT_ROOT = None
        studio.state._SERVER = None
        self.root = tempfile.mkdtemp(prefix="asgard-project-")

    def _task(self, task_id="t1", status="ready", **extra):
        now = time.time()
        return {
            "id": task_id,
            "prompt": "테스트 작업",
            "status": status,
            "created": now,
            "updated": now,
            "root": self.root,
            "files": [],
            "usage": {},
            **extra,
        }


class TestTaskMemory(WorkspaceCase):
    def test_task_survives_a_restart(self):
        """창을 닫았다 열어도 작업이 남는다 — 이 계층이 생긴 이유 그 자체."""
        studio_store.save_task(self.root, self._task("keep", result="끝났습니다"))
        with studio.state._TASK_LOCK:
            studio.state._TASKS.clear()  # 프로세스가 죽은 상황
        studio.state._LOADED_ROOTS.clear()

        studio.load_project_tasks(self.root)

        rows = studio.tasks._task_snapshot(self.root)
        self.assertEqual([r["id"] for r in rows], ["keep"])
        self.assertEqual(rows[0]["result"], "끝났습니다")

    def test_live_statuses_are_normalized_on_reload(self):
        """프로세스와 함께 죽은 작업을 '실행 중'이라고 말하는 창은 계기가 아니다."""
        for status in ("running", "queued", "paused"):
            studio_store.save_task(self.root, self._task(f"t-{status}", status=status))

        rows = studio_store.load_tasks(self.root)

        self.assertEqual({row["status"] for row in rows}, {"interrupted"})
        self.assertTrue(all(row.get("interrupted_at") for row in rows))

    def test_record_holds_no_process_handle_or_command(self):
        """핸들은 재시작 뒤 의미가 없고, 명령줄은 디스크에 남길 이유가 없다."""
        task = self._task("t-clean")
        task["process"] = object()
        task["command"] = ["python", "-m", "asgard", "run", "x"]

        studio_store.save_task(self.root, task)

        raw = open(studio_store.tasks_path(self.root), encoding="utf-8").read()
        self.assertNotIn("command", raw)
        self.assertNotIn("process", raw)

    def test_upsert_replaces_the_same_id(self):
        studio_store.save_task(self.root, self._task("same", status="queued"))
        studio_store.save_task(self.root, self._task("same", status="ready"))

        rows = studio_store.load_tasks(self.root)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ready")

    def test_a_torn_line_does_not_eat_the_history(self):
        studio_store.save_task(self.root, self._task("good"))
        with open(studio_store.tasks_path(self.root), "a", encoding="utf-8") as handle:
            handle.write('{"id": "torn", "sta\n')

        rows = studio_store.load_tasks(self.root)

        self.assertEqual([row["id"] for row in rows], ["good"])

    def test_tasks_stay_inside_their_project(self):
        """다른 프로젝트의 작업이 이 창에 섞이면 경계가 UI에서 무너진다."""
        other = tempfile.mkdtemp(prefix="asgard-other-")
        studio_store.save_task(self.root, self._task("mine"))
        studio_store.save_task(other, {**self._task("theirs"), "root": other})
        studio.load_project_tasks(self.root)
        studio.load_project_tasks(other)

        self.assertEqual([r["id"] for r in studio.tasks._task_snapshot(self.root)], ["mine"])
        self.assertEqual([r["id"] for r in studio.tasks._task_snapshot(other)], ["theirs"])

    def test_created_task_is_written_through(self):
        status, _, body = studio.create_task({"prompt": "적어 두기", "permission": "important"}, self.root)
        self.assertEqual(status, 202)
        task_id = json.loads(body)["id"]

        rows = studio_store.load_tasks(self.root)

        self.assertEqual([row["id"] for row in rows], [task_id])
        self.assertEqual(rows[0]["status"], "needs_input")

    def test_denied_task_is_written_through(self):
        _, _, body = studio.create_task({"prompt": "거부될 작업", "permission": "important"}, self.root)
        task_id = json.loads(body)["id"]

        studio.approve_task({"id": task_id, "decision": "deny"}, self.root)

        rows = studio_store.load_tasks(self.root)
        self.assertEqual(rows[0]["status"], "blocked")

    def test_a_task_without_a_boundary_is_written_nowhere(self):
        """경계를 모르는 작업을 cwd에 떨어뜨리면 남의 프로젝트에 남의 이력이 쌓인다."""
        with studio.state._TASK_LOCK:
            studio.state._TASKS["ghost"] = {
                "id": "ghost",
                "status": "running",
                "created": 1,
                "updated": 1,
                "process": mock.Mock(),
            }
        with mock.patch("asgard.agent.tools._kill_group"):
            studio.stop_task({"id": "ghost"})

        # cwd에 이미 이력이 있을 수 있으니 파일 유무가 아니라 **이 작업이 거기 없음**을 본다
        self.assertNotIn("ghost", [row["id"] for row in studio_store.load_tasks(os.getcwd())])
        self.assertNotIn("ghost", [row["id"] for row in studio_store.load_tasks(self.root)])


class TestProjectRegistry(WorkspaceCase):
    def registered(self, current=None):
        """등록부에서 온 줄만. 개인 작업 공간은 등록의 결과가 아니라 앱의 성질이라 늘 끝에 붙는다
        — 프로젝트를 하나도 안 연 사람에게도 설 자리가 있어야 창이 열리기 때문이다."""
        rows = studio_store.list_projects(current)
        self.assertTrue(rows[-1]["scratch"])
        return [row for row in rows if not row["scratch"]]

    def test_add_list_and_forget(self):
        studio_store.add_project(self.root)

        rows = self.registered(self.root)
        self.assertEqual([row["root"] for row in rows], [self.root])
        self.assertTrue(rows[0]["current"])
        self.assertTrue(rows[0]["exists"])

        self.assertTrue(studio_store.remove_project(self.root))
        self.assertFalse(studio_store.remove_project(self.root))

    def test_a_path_that_is_not_a_directory_is_refused(self):
        with self.assertRaises(ValueError):
            studio_store.add_project(os.path.join(self.root, "nope"))

    def test_current_project_is_listed_even_when_unregistered(self):
        self.assertEqual([row["root"] for row in self.registered(self.root)], [self.root])

    def test_switching_moves_the_window_and_loads_that_history(self):
        other = tempfile.mkdtemp(prefix="asgard-other-")
        studio_store.save_task(other, {**self._task("elsewhere"), "root": other})

        status, _, body = studio.use_project({"root": other})

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["root"], other)
        self.assertEqual([t["id"] for t in payload["snapshot"]["tasks"]], ["elsewhere"])
        self.assertEqual(studio.current_root(), other)

    def test_switching_to_a_missing_path_is_refused(self):
        status, _, _ = studio.use_project({"root": os.path.join(self.root, "missing")})
        self.assertEqual(status, 400)

    def test_the_open_project_cannot_be_removed_from_the_list(self):
        studio.use_project({"root": self.root})
        status, _, _ = studio.forget_project({"root": self.root})
        self.assertEqual(status, 409)


class TestArtifactBoundary(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self.file = os.path.join(self.root, "note.txt")
        with open(self.file, "w", encoding="utf-8") as handle:
            handle.write("한 줄")

    def test_a_file_inside_the_project_reads(self):
        status, _, body = studio.read_artifact(self.root, {"path": ["note.txt"]})
        payload = json.loads(body)

        self.assertEqual(status, 200)
        self.assertEqual(payload["text"], "한 줄")
        self.assertFalse(payload["binary"])

    def test_traversal_and_absolute_paths_are_refused(self):
        for candidate in ("../../etc/passwd", "/etc/passwd", "", "note.txt\x00.png"):
            status, _, _ = studio.read_artifact(self.root, {"path": [candidate]})
            self.assertEqual(status, 404, candidate)

    def test_a_symlink_pointing_outside_is_refused(self):
        """문자열 검사로는 안 잡힌다 — 경계는 realpath로 판정해야 한다."""
        outside = tempfile.mkdtemp(prefix="asgard-outside-")
        secret = os.path.join(outside, "secret.txt")
        with open(secret, "w", encoding="utf-8") as handle:
            handle.write("보이면 안 되는 것")
        link = os.path.join(self.root, "link.txt")
        os.symlink(secret, link)

        status, _, _ = studio.read_artifact(self.root, {"path": ["link.txt"]})

        self.assertEqual(status, 404)

    def test_binary_files_report_themselves_instead_of_spilling(self):
        blob = os.path.join(self.root, "blob.bin")
        with open(blob, "wb") as handle:
            handle.write(bytes(range(32)) * 8)

        _, _, body = studio.read_artifact(self.root, {"path": ["blob.bin"]})

        payload = json.loads(body)
        self.assertTrue(payload["binary"])
        self.assertEqual(payload["text"], "")

    def test_oversized_files_are_marked_truncated(self):
        big = os.path.join(self.root, "big.txt")
        with open(big, "w", encoding="utf-8") as handle:
            handle.write("x" * (studio.state._ARTIFACT_CAP + 10))

        _, _, body = studio.read_artifact(self.root, {"path": ["big.txt"]})

        payload = json.loads(body)
        self.assertTrue(payload["truncated"])
        self.assertEqual(len(payload["text"]), studio.state._ARTIFACT_CAP)

    def test_diff_outside_the_boundary_is_refused(self):
        status, _, _ = studio.read_diff(self.root, {"path": ["../escape"]})
        self.assertEqual(status, 404)

    def test_untracked_file_is_not_reported_as_unchanged(self):
        """`git diff`는 추적 밖 파일에 조용하다 — '변경 없음'이라 말하면 새 파일이 없는 파일이 된다."""
        with mock.patch("subprocess.run") as run:
            run.side_effect = [
                mock.Mock(stdout="", stderr="", returncode=0),
                mock.Mock(stdout="?? note.txt\n", stderr="", returncode=0),
            ]
            _, _, body = studio.read_diff(self.root, {"path": ["note.txt"]})

        self.assertIn("새 파일", json.loads(body)["note"])

    def test_a_workspace_without_git_says_so_instead_of_claiming_no_changes(self):
        """개인 작업 공간은 저장소가 아니다 — 비교할 것이 없는 것을 '비교했더니 같더라'로
        말하면, 사용자는 자기 파일이 이미 커밋된 줄 안다."""
        with mock.patch("subprocess.run") as run:
            run.side_effect = [
                mock.Mock(stdout="", stderr="", returncode=128),
                mock.Mock(stdout="", stderr="not a git repository", returncode=128),
            ]
            _, _, body = studio.read_diff(self.root, {"path": ["note.txt"]})

        self.assertIn("Git 저장소가 아니에요", json.loads(body)["note"])

    def test_reveal_stays_inside_the_boundary(self):
        with mock.patch("subprocess.Popen") as popen:
            status, _, _ = studio.reveal_path(self.root, {"path": "../.."})
        self.assertEqual(status, 404)
        popen.assert_not_called()

        with mock.patch("subprocess.Popen") as popen:
            status, _, _ = studio.reveal_path(self.root, {"path": "note.txt"})
        self.assertEqual(status, 200)
        popen.assert_called_once()

    def test_reveal_opens_the_card_that_was_clicked_not_the_open_one(self):
        """목록의 '폴더 열기'는 그 카드의 자리를 연다 — 창이 보던 곳이 아니라.

        작업 공간이 여럿이 되면서 실제 물음이 됐다. 다만 열 수 있는 자리는 아는 자리로 묶는다:
        임의 경로를 받아 여는 창은 파일 탐색기가 되고, 그건 이 표면의 일이 아니다."""
        other = tempfile.mkdtemp(prefix="asgard-other-")
        studio_store.add_project(other)

        with mock.patch("subprocess.Popen") as popen:
            status, _, _ = studio.reveal_path(self.root, {"root": other})
        self.assertEqual(status, 200)
        self.assertIn(os.path.realpath(other), " ".join(popen.call_args.args[0]))

        with mock.patch("subprocess.Popen") as popen:
            status, _, _ = studio.reveal_path(self.root, {"root": tempfile.mkdtemp(prefix="asgard-stranger-")})
        self.assertEqual(status, 403)
        popen.assert_not_called()


class TestRoutes(WorkspaceCase):
    def test_projects_artifact_and_diff_are_routed(self):
        with open(os.path.join(self.root, "a.txt"), "w", encoding="utf-8") as handle:
            handle.write("x")

        status, _, body = studio.dispatch("GET", "/api/projects", {}, self.root)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["current"], self.root)

        status, _, _ = studio.dispatch("GET", "/api/artifact", {"path": ["a.txt"]}, self.root)
        self.assertEqual(status, 200)

        status, _, _ = studio.dispatch("GET", "/api/diff", {"path": ["a.txt"]}, self.root)
        self.assertEqual(status, 200)

    def test_project_posts_are_routed(self):
        other = tempfile.mkdtemp(prefix="asgard-other-")
        status, _, _ = studio.dispatch_post("/api/projects/add", {"root": other}, self.root)
        self.assertEqual(status, 200)

        status, _, _ = studio.dispatch_post("/api/projects/use", {"root": other}, self.root)
        self.assertEqual(status, 200)

    def test_an_explicit_boundary_beats_the_module_default(self):
        """핸들러는 늘 서버의 root를 넘긴다 — 전역이 그걸 덮으면 전환이 거짓말이 된다."""
        studio.state._CURRENT_ROOT = "/tmp/somewhere-else"
        self.assertEqual(studio.current_root(self.root), self.root)


if __name__ == "__main__":
    unittest.main()
