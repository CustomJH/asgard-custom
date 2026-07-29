"""Desktop 작업 공간의 기억과 경계 — 영속화 · 프로젝트 전환 · 산출물 열기.

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

from asgard.commands import desktop, desktop_store


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        with desktop._TASK_LOCK:
            desktop._TASKS.clear()
        home = tempfile.mkdtemp(prefix="asgard-desktop-home-")
        patcher = mock.patch.dict(os.environ, {desktop_store.DESKTOP_HOME_ENV: home})
        patcher.start()
        self.addCleanup(patcher.stop)
        desktop._LOADED_ROOTS.clear()
        desktop._CURRENT_ROOT = None
        desktop._SERVER = None
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
        desktop_store.save_task(self.root, self._task("keep", result="끝났습니다"))
        with desktop._TASK_LOCK:
            desktop._TASKS.clear()  # 프로세스가 죽은 상황
        desktop._LOADED_ROOTS.clear()

        desktop.load_project_tasks(self.root)

        rows = desktop._task_snapshot(self.root)
        self.assertEqual([r["id"] for r in rows], ["keep"])
        self.assertEqual(rows[0]["result"], "끝났습니다")

    def test_live_statuses_are_normalized_on_reload(self):
        """프로세스와 함께 죽은 작업을 '실행 중'이라고 말하는 창은 계기가 아니다."""
        for status in ("running", "queued", "paused"):
            desktop_store.save_task(self.root, self._task(f"t-{status}", status=status))

        rows = desktop_store.load_tasks(self.root)

        self.assertEqual({row["status"] for row in rows}, {"interrupted"})
        self.assertTrue(all(row.get("interrupted_at") for row in rows))

    def test_record_holds_no_process_handle_or_command(self):
        """핸들은 재시작 뒤 의미가 없고, 명령줄은 디스크에 남길 이유가 없다."""
        task = self._task("t-clean")
        task["process"] = object()
        task["command"] = ["python", "-m", "asgard", "run", "x"]

        desktop_store.save_task(self.root, task)

        raw = open(desktop_store.tasks_path(self.root), encoding="utf-8").read()
        self.assertNotIn("command", raw)
        self.assertNotIn("process", raw)

    def test_upsert_replaces_the_same_id(self):
        desktop_store.save_task(self.root, self._task("same", status="queued"))
        desktop_store.save_task(self.root, self._task("same", status="ready"))

        rows = desktop_store.load_tasks(self.root)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ready")

    def test_a_torn_line_does_not_eat_the_history(self):
        desktop_store.save_task(self.root, self._task("good"))
        with open(desktop_store.tasks_path(self.root), "a", encoding="utf-8") as handle:
            handle.write('{"id": "torn", "sta\n')

        rows = desktop_store.load_tasks(self.root)

        self.assertEqual([row["id"] for row in rows], ["good"])

    def test_tasks_stay_inside_their_project(self):
        """다른 프로젝트의 작업이 이 창에 섞이면 경계가 UI 에서 무너진다."""
        other = tempfile.mkdtemp(prefix="asgard-other-")
        desktop_store.save_task(self.root, self._task("mine"))
        desktop_store.save_task(other, {**self._task("theirs"), "root": other})
        desktop.load_project_tasks(self.root)
        desktop.load_project_tasks(other)

        self.assertEqual([r["id"] for r in desktop._task_snapshot(self.root)], ["mine"])
        self.assertEqual([r["id"] for r in desktop._task_snapshot(other)], ["theirs"])

    def test_created_task_is_written_through(self):
        status, _, body = desktop.create_task({"prompt": "적어 두기", "permission": "important"}, self.root)
        self.assertEqual(status, 202)
        task_id = json.loads(body)["id"]

        rows = desktop_store.load_tasks(self.root)

        self.assertEqual([row["id"] for row in rows], [task_id])
        self.assertEqual(rows[0]["status"], "needs_input")

    def test_denied_task_is_written_through(self):
        _, _, body = desktop.create_task({"prompt": "거부될 작업", "permission": "important"}, self.root)
        task_id = json.loads(body)["id"]

        desktop.approve_task({"id": task_id, "decision": "deny"}, self.root)

        rows = desktop_store.load_tasks(self.root)
        self.assertEqual(rows[0]["status"], "blocked")

    def test_a_task_without_a_boundary_is_written_nowhere(self):
        """경계를 모르는 작업을 cwd 에 떨어뜨리면 남의 프로젝트에 남의 이력이 쌓인다."""
        with desktop._TASK_LOCK:
            desktop._TASKS["ghost"] = {
                "id": "ghost",
                "status": "running",
                "created": 1,
                "updated": 1,
                "process": mock.Mock(),
            }
        with mock.patch("asgard.agent.tools._kill_group"):
            desktop.stop_task({"id": "ghost"})

        # cwd 에 이미 이력이 있을 수 있으니 파일 유무가 아니라 **이 작업이 거기 없음**을 본다
        self.assertNotIn("ghost", [row["id"] for row in desktop_store.load_tasks(os.getcwd())])
        self.assertNotIn("ghost", [row["id"] for row in desktop_store.load_tasks(self.root)])


class TestProjectRegistry(WorkspaceCase):
    def test_add_list_and_forget(self):
        desktop_store.add_project(self.root)

        rows = desktop_store.list_projects(self.root)
        self.assertEqual([row["root"] for row in rows], [self.root])
        self.assertTrue(rows[0]["current"])
        self.assertTrue(rows[0]["exists"])

        self.assertTrue(desktop_store.remove_project(self.root))
        self.assertFalse(desktop_store.remove_project(self.root))

    def test_a_path_that_is_not_a_directory_is_refused(self):
        with self.assertRaises(ValueError):
            desktop_store.add_project(os.path.join(self.root, "nope"))

    def test_current_project_is_listed_even_when_unregistered(self):
        rows = desktop_store.list_projects(self.root)
        self.assertEqual([row["root"] for row in rows], [self.root])

    def test_switching_moves_the_window_and_loads_that_history(self):
        other = tempfile.mkdtemp(prefix="asgard-other-")
        desktop_store.save_task(other, {**self._task("elsewhere"), "root": other})

        status, _, body = desktop.use_project({"root": other})

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["root"], other)
        self.assertEqual([t["id"] for t in payload["snapshot"]["tasks"]], ["elsewhere"])
        self.assertEqual(desktop.current_root(), other)

    def test_switching_to_a_missing_path_is_refused(self):
        status, _, _ = desktop.use_project({"root": os.path.join(self.root, "missing")})
        self.assertEqual(status, 400)

    def test_the_open_project_cannot_be_removed_from_the_list(self):
        desktop.use_project({"root": self.root})
        status, _, _ = desktop.forget_project({"root": self.root})
        self.assertEqual(status, 409)


class TestArtifactBoundary(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self.file = os.path.join(self.root, "note.txt")
        with open(self.file, "w", encoding="utf-8") as handle:
            handle.write("한 줄")

    def test_a_file_inside_the_project_reads(self):
        status, _, body = desktop.read_artifact(self.root, {"path": ["note.txt"]})
        payload = json.loads(body)

        self.assertEqual(status, 200)
        self.assertEqual(payload["text"], "한 줄")
        self.assertFalse(payload["binary"])

    def test_traversal_and_absolute_paths_are_refused(self):
        for candidate in ("../../etc/passwd", "/etc/passwd", "", "note.txt\x00.png"):
            status, _, _ = desktop.read_artifact(self.root, {"path": [candidate]})
            self.assertEqual(status, 404, candidate)

    def test_a_symlink_pointing_outside_is_refused(self):
        """문자열 검사로는 안 잡힌다 — 경계는 realpath 로 판정해야 한다."""
        outside = tempfile.mkdtemp(prefix="asgard-outside-")
        secret = os.path.join(outside, "secret.txt")
        with open(secret, "w", encoding="utf-8") as handle:
            handle.write("보이면 안 되는 것")
        link = os.path.join(self.root, "link.txt")
        os.symlink(secret, link)

        status, _, _ = desktop.read_artifact(self.root, {"path": ["link.txt"]})

        self.assertEqual(status, 404)

    def test_binary_files_report_themselves_instead_of_spilling(self):
        blob = os.path.join(self.root, "blob.bin")
        with open(blob, "wb") as handle:
            handle.write(bytes(range(32)) * 8)

        _, _, body = desktop.read_artifact(self.root, {"path": ["blob.bin"]})

        payload = json.loads(body)
        self.assertTrue(payload["binary"])
        self.assertEqual(payload["text"], "")

    def test_oversized_files_are_marked_truncated(self):
        big = os.path.join(self.root, "big.txt")
        with open(big, "w", encoding="utf-8") as handle:
            handle.write("x" * (desktop._ARTIFACT_CAP + 10))

        _, _, body = desktop.read_artifact(self.root, {"path": ["big.txt"]})

        payload = json.loads(body)
        self.assertTrue(payload["truncated"])
        self.assertEqual(len(payload["text"]), desktop._ARTIFACT_CAP)

    def test_diff_outside_the_boundary_is_refused(self):
        status, _, _ = desktop.read_diff(self.root, {"path": ["../escape"]})
        self.assertEqual(status, 404)

    def test_untracked_file_is_not_reported_as_unchanged(self):
        """`git diff` 는 추적 밖 파일에 조용하다 — '변경 없음'이라 말하면 새 파일이 없는 파일이 된다."""
        with mock.patch("subprocess.run") as run:
            run.side_effect = [
                mock.Mock(stdout="", stderr=""),
                mock.Mock(stdout="?? note.txt\n", stderr=""),
            ]
            _, _, body = desktop.read_diff(self.root, {"path": ["note.txt"]})

        self.assertIn("새 파일", json.loads(body)["note"])

    def test_reveal_stays_inside_the_boundary(self):
        with mock.patch("subprocess.Popen") as popen:
            status, _, _ = desktop.reveal_path(self.root, {"path": "../.."})
        self.assertEqual(status, 404)
        popen.assert_not_called()

        with mock.patch("subprocess.Popen") as popen:
            status, _, _ = desktop.reveal_path(self.root, {"path": "note.txt"})
        self.assertEqual(status, 200)
        popen.assert_called_once()


class TestRoutes(WorkspaceCase):
    def test_projects_artifact_and_diff_are_routed(self):
        with open(os.path.join(self.root, "a.txt"), "w", encoding="utf-8") as handle:
            handle.write("x")

        status, _, body = desktop.dispatch("GET", "/api/projects", {}, self.root)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["current"], self.root)

        status, _, _ = desktop.dispatch("GET", "/api/artifact", {"path": ["a.txt"]}, self.root)
        self.assertEqual(status, 200)

        status, _, _ = desktop.dispatch("GET", "/api/diff", {"path": ["a.txt"]}, self.root)
        self.assertEqual(status, 200)

    def test_project_posts_are_routed(self):
        other = tempfile.mkdtemp(prefix="asgard-other-")
        status, _, _ = desktop.dispatch_post("/api/projects/add", {"root": other}, self.root)
        self.assertEqual(status, 200)

        status, _, _ = desktop.dispatch_post("/api/projects/use", {"root": other}, self.root)
        self.assertEqual(status, 200)

    def test_an_explicit_boundary_beats_the_module_default(self):
        """핸들러는 늘 서버의 root 를 넘긴다 — 전역이 그걸 덮으면 전환이 거짓말이 된다."""
        desktop._CURRENT_ROOT = "/tmp/somewhere-else"
        self.assertEqual(desktop.current_root(self.root), self.root)


if __name__ == "__main__":
    unittest.main()
