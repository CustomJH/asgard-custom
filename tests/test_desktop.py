"""Asgard Desktop API, security boundary, and real configuration wiring."""

import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from asgard.commands import desktop, desktop_store


class DesktopCase(unittest.TestCase):
    def setUp(self):
        with desktop.state._TASK_LOCK:
            desktop.state._TASKS.clear()
        # 기억이 생긴 뒤로 테스트는 자기 자리를 갖고 놀아야 한다 — 실측: 첫 판에서 테스트의
        # 임시 디렉터리들이 사용자의 실제 프로젝트 등록부에 그대로 쌓였다.
        home = tempfile.mkdtemp(prefix="asgard-desktop-home-")
        patcher = mock.patch.dict(os.environ, {desktop_store.DESKTOP_HOME_ENV: home})
        patcher.start()
        self.addCleanup(patcher.stop)
        # 시작 경계 사다리가 이 변수를 두 번째로 본다 — 부모 환경에 남아 있으면 테스트가
        # 자기 자리 대신 남이 정해 준 자리를 재게 된다.
        os.environ.pop("ASGARD_DESKTOP_ROOT", None)
        self.desktop_home = home
        desktop.state._LOADED_ROOTS.clear()
        desktop.state._CURRENT_ROOT = None
        desktop.state._SERVER = None


class TestDispatch(DesktopCase):
    def test_root_is_self_contained_desktop(self):
        status, ctype, body = desktop.dispatch("GET", "/")
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        # 이름은 한 벌이어야 한다 — 제목·워드마크·첫 화면이 같은 것을 부른다. 여는 화면에만
        # 남아 있던 옛 이름("Asgard Desktop")이 이 검사를 통과시키고 있었다.
        self.assertIn("Asgard Studio", page)
        self.assertNotIn("Asgard Desktop", page)
        self.assertIn("플러그인과 스킬", page)
        self.assertIn("승인 필요", page)
        self.assertIn('data-view="plan">기획', page)
        # 기획 화면의 문은 하나다 — 묻는 문장 한 줄. 고르기 판이 되살아나면 여기서 걸린다.
        self.assertIn("어떤 기획을 할까요?", page)
        self.assertNotIn("plan-picks", page)
        # 증거 판은 기본으로 닫혀 있다 — 재설계로 클래스는 .evidence가 됐고 계약은 그대로다
        self.assertIn(".evidence[hidden]{display:none}", page)
        # 이 표면의 이름은 이제 Asgard Studio 다(사용자 결정). 그러니 이 검사가 지킬 것은
        # 이름이 아니라 **폐기된 세스룸니르 표면이 되살아나지 않는 것**이다.
        self.assertNotIn("세스룸니르", page)
        self.assertNotIn("studio_dashboard", page)
        self.assertNotIn('src="http', page)

    def test_the_dock_is_the_only_place_that_takes_input(self):
        """적는 자리는 대화 아래 독 하나다 — 새 작업이든 이어가기든, 권한까지 거기서 정한다.

        여태는 머리에도 입력이 있어서 같은 칸이 상황에 따라 조용히 모드를 바꿨다(돌고 있는
        동안 적으면 새 작업). 그래서 이 검사가 지킬 것은 둘이다: 독이 온전히 있다 ·
        **머리에는 입력도 권한도 없다**(되살아나면 그 혼동이 같이 돌아온다)."""
        page = desktop.dispatch("GET", "/")[1:][1].decode()
        for anchor in ('id="dock"', 'id="dock-input"', 'id="dock-send"', 'id="dock-mode"', 'id="jump-latest"'):
            self.assertIn(anchor, page, anchor)
        self.assertIn("/api/tasks/follow", page)
        # 권한 칸은 독의 계기 줄에 있다 — 입력과 같은 자리다
        dock = page.split('<form class="dock"', 1)[1]
        self.assertIn('id="permission"', dock)

    def test_the_dock_says_why_it_cannot_send(self):
        """이유 없는 disabled는 금지다 — 힌트 한 칸이 그 이유를 진다.

        여태 그 자리엔 "Enter 보내기 · Shift+Enter 줄바꿈"이 상시로 앉아 있었다. 배울 수 있는
        사실이라 몇 세션이면 가구가 되고, 그동안 **왜 못 보내는지**는 아무 데서도 안 말했다.
        (이 검사의 옛 앵커는 그 문구였는데, 문구가 주석으로만 남아도 통과했다 — 주석은
        화면이 아니다. 그래서 이제 렌더 함수가 내는 실제 문장을 잡는다.)"""
        page = desktop.dispatch("GET", "/")[1:][1].decode()
        script = page.split("<script>", 1)[1]
        self.assertIn("function renderDockHint()", script)
        for reason in ("보낼 내용을 적으세요", "상한입니다", "이 턴이 끝나면 보냅니다", "보내는 중"):
            self.assertIn(reason, script, reason)
        # 키 안내는 손이 상자 안에 있을 때만 — 상시 노출로 되돌아가면 여기서 걸린다
        self.assertIn("$('#dock-input').onfocus=renderDockHint", script)
        self.assertNotIn('id="dock-hint-keys">Enter', page)
        # 머리에 남은 것은 브랜드와 경계뿐이다
        header = page.split('<header class="command">', 1)[1].split("</header>", 1)[0]
        for gone in ("<textarea", "<select", 'id="send"', "로컬에서 실행"):
            self.assertNotIn(gone, header, gone)
        self.assertNotIn("cmdform", page)

    def test_logo_health_and_unknown_routes(self):
        status, ctype, body = desktop.dispatch("GET", "/asset/logo")
        self.assertEqual((status, ctype), (200, "image/png"))
        self.assertTrue(body.startswith(b"\x89PNG"))
        # 앱 아이콘 — 네이티브 창과 브라우저 폴백이 같은 얼굴을 든다
        for path in ("/asset/app-icon", "/favicon.ico"):
            status, ctype, body = desktop.dispatch("GET", path)
            self.assertEqual((status, ctype), (200, "image/png"), path)
            self.assertTrue(body.startswith(b"\x89PNG"), path)
        status, _, body = desktop.dispatch("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True, "surface": "desktop"})
        self.assertEqual(desktop.dispatch("GET", "/missing", {})[0], 404)
        self.assertEqual(desktop.dispatch("POST", "/", {})[0], 405)

    def test_snapshot_and_catalog_use_real_sources(self):
        with tempfile.TemporaryDirectory() as root:
            status, _, body = desktop.dispatch("GET", "/api/snapshot", {}, root)
            snapshot = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual(snapshot["project"]["root"], root)
            self.assertIn("provider", snapshot)
            self.assertGreater(snapshot["catalog"]["skills"], 0)
            status, _, body = desktop.dispatch("GET", "/api/catalog", {}, root)
            self.assertTrue(json.loads(body)["skills"])

    def test_plan_api_reuses_the_project_local_plan_store(self):
        with tempfile.TemporaryDirectory() as root:
            status, _, body = desktop.dispatch_post("/api/plans", {"idea": "협업 기획"}, root)
            self.assertEqual(status, 201)
            created = json.loads(body)["plan"]

            status, _, body = desktop.dispatch("GET", f"/api/plans/{created['id']}", {}, root)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["plan"]["title"], "협업 기획")

            status, _, body = desktop.dispatch_post(
                f"/api/plans/{created['id']}/edit",
                {"op": "section", "section": "overview", "body": "- 사용자가 검토할 Asgard 제안"},
                root,
            )
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["readiness"]["spec"]["ready"])

    def test_a_new_plan_needs_only_one_line(self):
        """Studio의 기획은 "어떤 기획을 할까요?" 한 칸에서 시작한다 — 고를 것이 없다."""
        with tempfile.TemporaryDirectory() as root:
            status, _, body = desktop.dispatch_post("/api/plans", {"idea": "검색 명세를 정리하고 싶다"}, root)
            self.assertEqual(status, 201)
            view = json.loads(body)
            self.assertEqual(view["plan"]["phase"], "intake")
            self.assertEqual(view["next"]["action"], "ask")

            status, _, body = desktop.dispatch_post("/api/plans", {"idea": "   "}, root)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["error"]["code"], "invalid_plan")


class TestTaskLifecycle(DesktopCase):
    def test_important_task_waits_for_one_time_approval(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(desktop.tasks, "_start") as start:
            status, _, body = desktop.create_task({"prompt": "README를 검토해줘", "permission": "important"}, root)
            task = json.loads(body)
            self.assertEqual(status, 202)
            self.assertEqual(task["status"], "needs_input")
            self.assertEqual(task["approval"]["scope"], root)
            start.assert_not_called()

            status, _, body = desktop.approve_task({"id": task["id"], "decision": "allow_once"}, root)
            self.assertEqual(status, 202)
            self.assertEqual(json.loads(body)["status"], "queued")
            start.assert_called_once_with(task["id"], root)

    def test_deny_blocks_without_execution(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(desktop.tasks, "_start") as start:
            _, _, body = desktop.create_task({"prompt": "파일을 수정해줘", "permission": "manual"}, root)
            task = json.loads(body)
            status, _, body = desktop.approve_task({"id": task["id"], "decision": "deny"}, root)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["status"], "blocked")
            start.assert_not_called()

    def test_auto_task_uses_existing_asgard_run_command(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(desktop.tasks, "_start") as start:
            status, _, body = desktop.create_task(
                {"prompt": "테스트를 실행해줘", "permission": "auto", "provider": "openai"}, root
            )
            task = json.loads(body)
            self.assertEqual(status, 202)
            self.assertEqual(task["status"], "queued")
            with desktop.state._TASK_LOCK:
                command = desktop.state._TASKS[task["id"]]["command"]
            self.assertEqual(command[1:4], ["-m", "asgard", "run"])
            self.assertIn("--json", command)
            self.assertEqual(command[-2:], ["--provider", "openai"])
            start.assert_called_once()

    def test_prompt_and_permission_are_validated(self):
        self.assertEqual(desktop.create_task({"prompt": ""}, ".")[0], 400)
        self.assertEqual(desktop.create_task({"prompt": "x", "permission": "forever"}, ".")[0], 400)
        self.assertEqual(desktop.create_task({"prompt": "x", "label": "x" * 201}, ".")[0], 400)

    def test_task_label_is_display_metadata_not_the_executed_prompt(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(desktop.tasks, "_start"):
            _, _, body = desktop.create_task(
                {"prompt": "full planner context", "label": "Asgard 기획 제안", "permission": "auto"}, root
            )
            task = json.loads(body)
            self.assertEqual(task["label"], "Asgard 기획 제안")
            with desktop.state._TASK_LOCK:
                self.assertEqual(desktop.state._TASKS[task["id"]]["command"][4], "full planner context")

    def test_follow_keeps_one_quest_and_carries_the_earlier_turns(self):
        """이어가기는 새 줄이 아니라 같은 작업의 다음 턴이다 — 원장의 줄은 하나로 남는다."""
        with tempfile.TemporaryDirectory() as root, mock.patch.object(desktop.tasks, "_start"):
            _, _, body = desktop.create_task({"prompt": "README를 살펴봐", "permission": "auto"}, root)
            task_id = json.loads(body)["id"]
            with desktop.state._TASK_LOCK:
                desktop.state._TASKS[task_id].update({"status": "ready", "result": "살펴봤습니다"})
                desktop.state._TASKS[task_id]["turns"].append({"role": "agent", "text": "살펴봤습니다", "ts": 2})

            status, _, body = desktop.follow_task({"id": task_id, "prompt": "이제 고쳐줘"}, root)
            followed = json.loads(body)
            self.assertEqual(status, 202)
            self.assertEqual(followed["status"], "queued")
            self.assertEqual([turn["role"] for turn in followed["turns"]], ["user", "agent", "user"])
            self.assertEqual(len(desktop.tasks._task_snapshot(root)), 1)  # 줄이 늘지 않는다
            with desktop.state._TASK_LOCK:
                composed = desktop.state._TASKS[task_id]["command"][4]
            for carried in ("README를 살펴봐", "살펴봤습니다", "이제 고쳐줘"):
                self.assertIn(carried, composed)

    def test_follow_can_change_how_far_this_turn_runs_by_itself(self):
        """권한 칸이 독으로 내려왔으니 이어가는 턴도 그 값으로 돈다 — 아니면 그 칸은 장식이다."""
        with tempfile.TemporaryDirectory() as root, mock.patch.object(desktop.tasks, "_start") as start:
            _, _, body = desktop.create_task({"prompt": "살펴봐", "permission": "important"}, root)
            task_id = json.loads(body)["id"]
            with desktop.state._TASK_LOCK:
                desktop.state._TASKS[task_id]["status"] = "ready"

            _, _, body = desktop.follow_task({"id": task_id, "prompt": "이어서", "permission": "auto"}, root)
            followed = json.loads(body)
            self.assertEqual(followed["status"], "queued")  # 자동이면 승인을 안 묻는다
            self.assertEqual(followed["permission"], "auto")  # 기록에도 남는다
            start.assert_called_once_with(task_id, root)

            # 안 주면 그 작업이 여태 쓰던 값을 지킨다
            with desktop.state._TASK_LOCK:
                desktop.state._TASKS[task_id]["status"] = "ready"
            _, _, body = desktop.follow_task({"id": task_id, "prompt": "또 이어서"}, root)
            self.assertEqual(json.loads(body)["permission"], "auto")
            self.assertEqual(desktop.follow_task({"id": task_id, "prompt": "x", "permission": "always"}, root)[0], 400)

    def test_follow_refuses_a_turn_that_has_not_finished(self):
        """돌고 있는 작업에는 붙이지 않는다 — 화면이 다음 턴을 예약해 두는 근거다."""
        with desktop.state._TASK_LOCK:
            desktop.state._TASKS["live"] = {"id": "live", "status": "running", "created": 1, "updated": 1, "turns": []}
        self.assertEqual(desktop.follow_task({"id": "live", "prompt": "이어서"}, ".")[0], 409)
        self.assertEqual(desktop.follow_task({"id": "gone", "prompt": "이어서"}, ".")[0], 404)
        self.assertEqual(desktop.follow_task({"id": "live", "prompt": " "}, ".")[0], 400)

    @unittest.skipUnless(hasattr(desktop.signal, "SIGSTOP"), "process pause is POSIX-only")
    def test_running_task_can_pause_resume_and_stop(self):
        process = mock.Mock()
        task = {"id": "live", "status": "running", "created": 1, "updated": 1, "process": process}
        with desktop.state._TASK_LOCK:
            desktop.state._TASKS["live"] = task
        self.assertEqual(desktop.pause_task({"id": "live"})[0], 200)
        self.assertEqual(task["status"], "paused")
        process.send_signal.assert_called_with(desktop.signal.SIGSTOP)
        self.assertEqual(desktop.resume_task({"id": "live"})[0], 200)
        self.assertEqual(task["status"], "running")
        process.send_signal.assert_called_with(desktop.signal.SIGCONT)
        with mock.patch("asgard.agent.tools._kill_group") as kill_group:
            self.assertEqual(desktop.stop_task({"id": "live"})[0], 200)
        kill_group.assert_called_once_with(process)
        self.assertEqual(task["status"], "blocked")


class TestSettings(DesktopCase):
    def test_project_settings_persist_through_canonical_store(self):
        with tempfile.TemporaryDirectory() as root:
            status, _, body = desktop.save_settings(
                {
                    "scope": "project",
                    "section": "ui",
                    "values": {"theme": "dark", "density": "compact", "desktop_permission": "manual"},
                },
                root,
            )
            result = json.loads(body)
            self.assertEqual(status, 200)
            self.assertTrue(os.path.isfile(result["saved"]))
            self.assertEqual(result["settings"]["effective"]["ui"]["desktop_permission"], "manual")

    def test_engine_change_answers_with_the_re_resolved_engine(self):
        """엔진을 바꾸면 그 응답만으로 창이 지금 상태를 말할 수 있어야 한다 —
        settings만 돌려주면 상태 표시줄·연결 상자는 옛 엔진에 머문다."""
        with tempfile.TemporaryDirectory() as root:
            status, _, body = desktop.save_settings(
                {"scope": "project", "section": "provider", "values": {"name": "ollama", "model": ""}}, root
            )
            result = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual(result["settings"]["effective"]["provider"]["name"], "ollama")
            self.assertEqual(result["provider"]["name"], "ollama")
            self.assertTrue(result["provider"]["model"])  # 빈 칸은 그 엔진의 기본 모델로 풀린다
            self.assertIn("ready", result["provider"])
            self.assertTrue(result["provider"]["choices"])

    def test_model_change_keeps_provider_keys_the_window_never_shows(self):
        """창은 엔진 이름과 모델만 보여 준다 — 모델 하나 바꾸는 동작이 손으로 적어 둔
        base_url·rpm을 지우면 안 된다. 다만 엔진이 바뀌면 그 키들은 옛 엔진의 것이다."""
        from asgard import settings

        with tempfile.TemporaryDirectory() as root:
            settings.save_project(
                root,
                "provider",
                {"name": "openai_compat", "model": "m1", "base_url": "http://gpu.local:8000/v1", "rpm": 40},
            )
            desktop.save_settings(
                {"scope": "project", "section": "provider", "values": {"name": "openai_compat", "model": "m2"}}, root
            )
            kept = settings.load_project(root)["provider"]
            self.assertEqual(kept["model"], "m2")
            self.assertEqual(kept["base_url"], "http://gpu.local:8000/v1")
            self.assertEqual(kept["rpm"], 40)

            desktop.save_settings(
                {"scope": "project", "section": "provider", "values": {"name": "ollama", "model": ""}}, root
            )
            self.assertEqual(settings.load_project(root)["provider"], {"name": "ollama"})

    def test_global_scope_and_unknown_keys_are_guarded(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"HOME": home}):
                status, _, body = desktop.save_settings(
                    {"scope": "global", "section": "lagom", "values": {"mode": "lite"}}, root
                )
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["saved"].startswith(home))
            self.assertEqual(
                desktop.save_settings({"scope": "project", "section": "provider", "values": {"secret": "no"}}, root)[0],
                400,
            )
            self.assertEqual(desktop.save_settings({"scope": "team", "section": "ui", "values": {}}, root)[0], 400)


class TestProjectRegistry(DesktopCase):
    def _registered(self) -> list[dict]:
        """등록부에서 온 줄만 — 개인 작업 공간은 등록의 결과가 아니라 앱의 성질이라 늘 붙는다."""
        rows = desktop_store.list_projects()
        self.assertTrue(rows[-1]["scratch"], "개인 작업 공간은 목록 끝에 언제나 있다")
        return [row for row in rows if not row["scratch"]]

    def test_prune_drops_only_the_roots_that_are_gone(self):
        """자리에 없는 등록만 걷어낸다 — 살아 있는 것과 현재 경계는 남는다."""
        with tempfile.TemporaryDirectory() as alive, tempfile.TemporaryDirectory() as current:
            desktop_store.add_project(alive)
            desktop_store.add_project(current)
            with tempfile.TemporaryDirectory() as doomed:
                desktop_store.add_project(doomed)
            self.assertEqual(len(self._registered()), 3)

            removed = desktop_store.prune_projects(current)
            self.assertEqual(removed, 1)
            roots = {os.path.abspath(row["root"]) for row in self._registered()}
            self.assertEqual(roots, {os.path.abspath(alive), os.path.abspath(current)})

    def test_prune_keeps_the_open_project_even_when_its_folder_vanished(self):
        with tempfile.TemporaryDirectory() as home:
            missing = os.path.join(home, "unmounted")
            os.makedirs(missing)
            desktop_store.add_project(missing)
            os.rmdir(missing)
            self.assertEqual(desktop_store.prune_projects(missing), 0)
            self.assertEqual(len(self._registered()), 1)

    def test_the_personal_workspace_cannot_be_added_or_forgotten(self):
        """개인 작업 공간은 앱의 일부다 — 등록부에 적히지도, 목록에서 빠지지도 않는다.

        (등록부에 적히면 '사라진 폴더 정리'가 언젠가 그것을 지우고, 그 순간 프로젝트를 하나도
        안 연 사람에게 설 자리가 없어진다.)"""
        scratch = desktop_store.ensure_scratch()
        desktop_store.add_project(scratch)
        self.assertEqual(self._registered(), [])
        self.assertFalse(desktop_store.remove_project(scratch))
        self.assertTrue(desktop_store.list_projects()[-1]["scratch"])


class TestTaskEvidence(DesktopCase):
    def test_changed_files_are_the_task_delta_not_the_whole_dirty_tree(self):
        """작업이 손대지 않은 더러운 트리는 그 작업의 산출물이 아니다.

        실측: README 한 줄만 읽고 끝난 작업이 '변경 파일 14개'를 달고 산출물에 올라왔다."""
        with tempfile.TemporaryDirectory() as root:
            before = [{"status": "M", "path": "already-dirty.py"}]
            after = [
                {"status": "M", "path": "already-dirty.py"},  # 작업 전부터 있던 것 — 제외
                {"status": "M", "path": "touched.py"},  # 작업이 새로 바꾼 것
                {"status": "??", "path": "made.py"},  # 작업이 새로 만든 것
            ]
            with mock.patch.object(desktop.tasks, "_workspace_files", return_value=after):
                changed = desktop.tasks._changed_by_task(root, before)
            self.assertEqual([row["path"] for row in changed], ["touched.py", "made.py"])

    def test_a_file_that_changed_state_during_the_task_still_counts(self):
        with tempfile.TemporaryDirectory() as root:
            before = [{"status": "??", "path": "draft.py"}]
            after = [{"status": "M", "path": "draft.py"}]
            with mock.patch.object(desktop.tasks, "_workspace_files", return_value=after):
                self.assertEqual(desktop.tasks._changed_by_task(root, before), after)


class TestHostAndOriginGuard(unittest.TestCase):
    def test_loopback_hosts_and_origins(self):
        for host in ("127.0.0.1", "127.0.0.1:8766", "localhost:8766", "[::1]:8766"):
            self.assertTrue(desktop.host_allowed(host), host)
        for host in (None, "", "evil.example", "10.0.0.5:80"):
            self.assertFalse(desktop.host_allowed(host), repr(host))
        self.assertTrue(desktop.origin_allowed(None))
        self.assertTrue(desktop.origin_allowed("http://127.0.0.1:8766"))
        self.assertFalse(desktop.origin_allowed("https://127.0.0.1:8766"))
        self.assertFalse(desktop.origin_allowed("http://evil.example"))

    def test_live_roundtrip_has_security_headers(self):
        with tempfile.TemporaryDirectory() as root:
            httpd = desktop.server._bind("127.0.0.1", 0, root)
            port = httpd.server_address[1]
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("default-src 'none'", response.headers["Content-Security-Policy"])
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/tasks",
                    data=b'{"prompt":"x"}',
                    headers={"Content-Type": "application/json", "Origin": "http://evil.example"},
                )
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(rejected.exception.code, 403)

                preview_request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/plans",
                    data=b'{"idea":"preview plan"}',
                    headers={
                        "Content-Type": "application/json",
                        "Origin": "https://local-preview.invalid",
                        "X-Asgard-Desktop": "1",
                    },
                )
                with urllib.request.urlopen(preview_request, timeout=5) as response:
                    self.assertEqual(response.status, 201)
                    self.assertEqual(json.loads(response.read())["plan"]["title"], "preview plan")
            finally:
                httpd.shutdown()
                httpd.server_close()


class TestAppFirstLaunch(DesktopCase):
    """창은 폴더가 아니라 기계의 것이다 — 여는 데 프로젝트가 필요하지 않다."""

    def test_a_plain_folder_does_not_become_a_project(self):
        """표식 없는 자리에서 띄우면 개인 작업 공간에 선다 — 그리고 등록부는 그대로다.

        여태는 cwd가 곧 프로젝트였다. 독에서 아이콘을 누르면 홈이 프로젝트가 되고, 사용자의
        집에 `.asgard/desktop/`이 생기고, 열어 본 적 없는 자리가 목록에 쌓였다."""
        with tempfile.TemporaryDirectory() as plain:
            with mock.patch.object(desktop.boundary.os, "getcwd", return_value=plain):
                start = desktop.resolve_start_root()
            self.assertTrue(desktop_store.is_scratch(start))
            self.assertEqual([row for row in desktop_store.list_projects() if not row["scratch"]], [])
            self.assertFalse(os.path.isdir(os.path.join(plain, ".asgard")))

    def test_home_is_never_a_project_even_with_marks_in_it(self):
        """집에 `.git`이 있어도 집은 프로젝트가 아니다 — 경계가 사용자의 삶 전체가 된다."""
        self.assertFalse(desktop_store.looks_like_project(os.path.expanduser("~")))
        self.assertFalse(desktop_store.looks_like_project(os.sep))

    def test_even_a_marked_folder_does_not_pull_the_window_into_itself(self):
        """저장소 안에서 켜도 창은 **메인 루트**에서 선다 — 프로젝트는 창 안에서 고른다.

        여태는 표식 있는 cwd가 창의 자리를 정했다. 그래서 같은 앱이 어디서 켜느냐에 따라
        다른 곳에서 열렸다: 터미널에서 켜면 그 저장소, 독에서 누르면 다른 데. 창이 사람의
        것이라면 그럴 수 없다."""
        with tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, ".git"))
            self.assertTrue(desktop_store.looks_like_project(repo))
            with mock.patch.object(desktop.boundary.os, "getcwd", return_value=repo):
                self.assertTrue(desktop_store.is_scratch(desktop.resolve_start_root()))

    def test_the_last_project_does_not_reopen_itself(self):
        """지난번 자리로 **끌려가지** 않는다 — 등록부는 목록이지 창의 정체가 아니다."""
        with tempfile.TemporaryDirectory() as recent, tempfile.TemporaryDirectory() as plain:
            desktop_store.add_project(recent)
            with mock.patch.object(desktop.boundary.os, "getcwd", return_value=plain):
                self.assertTrue(desktop_store.is_scratch(desktop.resolve_start_root()))
            # 목록에는 그대로 있다 — 창 안에서 고르면 그 자리로 간다
            self.assertIn(os.path.abspath(recent), [row["root"] for row in desktop_store.list_projects()])

    def test_an_explicit_root_beats_everything(self):
        with tempfile.TemporaryDirectory() as picked, tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, ".git"))
            with mock.patch.object(desktop.boundary.os, "getcwd", return_value=repo):
                self.assertEqual(desktop.resolve_start_root(picked), os.path.abspath(picked))
                with mock.patch.dict(os.environ, {"ASGARD_DESKTOP_ROOT": picked}):
                    self.assertEqual(desktop.resolve_start_root(), os.path.abspath(picked))


class TestWorkspacePerTask(DesktopCase):
    """작업 공간은 창의 상태가 아니라 **그 작업의 값**이다."""

    def test_a_task_runs_where_it_was_asked_for_not_where_the_window_is(self):
        with tempfile.TemporaryDirectory() as here, tempfile.TemporaryDirectory() as there:
            status, _, body = desktop.create_task(
                {"prompt": "저기서 해라", "permission": "manual", "root": there}, here
            )
            task = json.loads(body)
            self.assertEqual(status, 202)
            self.assertEqual(task["root"], os.path.abspath(there))
            # 승인문도 실제로 돌 자리를 부른다 — "현재 프로젝트"라고 뭉뜽그리면 범위가 안 보인다
            self.assertIn(os.path.basename(there), task["approval"]["reason"])

    def test_an_unknown_workspace_is_refused(self):
        with tempfile.TemporaryDirectory() as here:
            status, _, body = desktop.create_task({"prompt": "어디?", "root": "/nope/nowhere"}, here)
            self.assertEqual(status, 400)
            self.assertIn("작업 공간", json.loads(body)["error"])

    def test_following_a_task_stays_in_its_own_workspace(self):
        """창이 다른 자리로 옮겨 갔어도, 이어가는 턴은 그 대화가 시작된 자리에서 돈다.

        여태는 이어가기·승인이 전부 '지금 창이 보는 곳'에서 돌았다 — 프로젝트를 옮긴 뒤
        옛 작업을 승인하면 **남의 저장소에서** 실행됐다."""
        with tempfile.TemporaryDirectory() as origin, tempfile.TemporaryDirectory() as moved:
            task = json.loads(desktop.create_task({"prompt": "시작", "permission": "manual"}, origin)[1:][1])
            started: list[str] = []
            with mock.patch.object(desktop.tasks, "_start", side_effect=lambda _id, root: started.append(root)):
                # 창은 이제 moved를 본다. 그래도 승인은 origin을 연다.
                status, _, _ = desktop.approve_task({"id": task["id"], "decision": "allow_once"}, moved)
                self.assertEqual(status, 202)
                self.assertEqual(started, [os.path.abspath(origin)])

    def test_the_personal_workspace_is_a_real_place_to_run_in(self):
        with tempfile.TemporaryDirectory() as here:
            scratch = desktop_store.scratch_root()
            task = json.loads(
                desktop.create_task({"prompt": "프로젝트 없이", "permission": "manual", "root": scratch}, here)[1:][1]
            )
            self.assertTrue(desktop_store.is_scratch(task["root"]))
            self.assertTrue(os.path.isdir(task["root"]), "고른 순간 자리가 만들어져 있어야 한다")
            self.assertIn(desktop_store.SCRATCH_NAME, task["approval"]["target"])


class TestCrossProjectFeed(DesktopCase):
    """프로젝트를 옮겼다고 여태 하던 일이 목록에서 사라지면 안 된다."""

    def test_the_feed_spans_projects_while_the_scoped_list_does_not(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            desktop.create_task({"prompt": "가에서", "permission": "manual"}, a)
            desktop.create_task({"prompt": "나에서", "permission": "manual", "root": b}, a)

            feed = json.loads(desktop.dispatch("GET", "/api/tasks", {"scope": ["all"]}, a)[1:][1])
            self.assertEqual({row["prompt"] for row in feed}, {"가에서", "나에서"})
            # 줄마다 어느 자리의 일인지 달고 온다 — 배지가 없으면 모르는 채로 눌러야 한다
            self.assertEqual({row["project"] for row in feed}, {os.path.basename(a), os.path.basename(b)})
            self.assertEqual({row["here"] for row in feed}, {True, False})

            scoped = json.loads(desktop.dispatch("GET", "/api/tasks", {}, a)[1:][1])
            self.assertEqual([row["prompt"] for row in scoped], ["가에서"])

    def test_the_feed_survives_the_process_that_made_it(self):
        """창을 닫았다 열어도 남의 프로젝트 이력이 보인다 — 색인은 디스크에 있다."""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            desktop.create_task({"prompt": "가에서", "permission": "manual"}, a)
            desktop.create_task({"prompt": "나에서", "permission": "manual", "root": b}, a)
            with desktop.state._TASK_LOCK:  # 프로세스가 죽은 셈 친다
                desktop.state._TASKS.clear()

            feed = desktop_store.feed()
            self.assertEqual({row["prompt"] for row in feed}, {"가에서", "나에서"})
            # 살아 있던 상태는 되살아나지 않는다 — 죽은 작업을 '실행 중'이라 말하면 계기가 아니다
            self.assertNotIn("running", {row["status"] for row in feed})

    def test_the_index_is_convenience_not_canon(self):
        """색인을 지워도 프로젝트의 기록에서 다시 세운다."""
        with tempfile.TemporaryDirectory() as a:
            desktop.create_task({"prompt": "가에서", "permission": "manual"}, a)
            os.unlink(desktop_store.index_path())
            self.assertEqual(desktop_store.feed(), [])
            self.assertEqual(desktop_store.reindex([a]), 1)
            self.assertEqual([row["prompt"] for row in desktop_store.feed()], ["가에서"])

    def test_an_artifact_is_read_from_the_workspace_that_made_it(self):
        """남의 작업 공간의 작업을 열어 둔 채로 변경 파일을 눌러도 그 자리의 파일을 읽는다.

        자리를 안 실어 보내면 창이 선 저장소에서 같은 상대 경로를 찾는다 — 없으면 404 지만,
        하필 같은 이름이 있으면 **엉뚱한 파일의 내용**을 그 작업의 산출물이라고 보여 준다."""
        with tempfile.TemporaryDirectory() as here, tempfile.TemporaryDirectory() as there:
            for root, text in ((here, "이 저장소의 것"), (there, "저 저장소의 것")):
                with open(os.path.join(root, "note.txt"), "w", encoding="utf-8") as handle:
                    handle.write(text)
            desktop_store.add_project(there)

            body = desktop.dispatch("GET", "/api/artifact", {"path": ["note.txt"], "root": [there]}, here)[1:][1]
            self.assertEqual(json.loads(body)["text"], "저 저장소의 것")
            body = desktop.dispatch("GET", "/api/artifact", {"path": ["note.txt"]}, here)[1:][1]
            self.assertEqual(json.loads(body)["text"], "이 저장소의 것")

    def test_reading_is_confined_to_workspaces_the_window_knows(self):
        """임의 경로를 받아 읽는 창은 파일 탐색기가 된다 — 그건 이 표면의 일이 아니다."""
        with tempfile.TemporaryDirectory() as here, tempfile.TemporaryDirectory() as stranger:
            with open(os.path.join(stranger, "note.txt"), "w", encoding="utf-8") as handle:
                handle.write("남의 것")
            for route in ("/api/artifact", "/api/diff"):
                status, _, body = desktop.dispatch("GET", route, {"path": ["note.txt"], "root": [stranger]}, here)
                self.assertEqual(status, 403, route)
                self.assertIn("목록에 없는", json.loads(body)["error"])

    def test_the_snapshot_carries_the_feed_and_says_where_it_stands(self):
        with tempfile.TemporaryDirectory() as a:
            snapshot = json.loads(desktop.dispatch("GET", "/api/snapshot", {}, a)[1:][1])
            self.assertIn("feed", snapshot)
            self.assertFalse(snapshot["project"]["scratch"])
            self.assertFalse(snapshot["project"]["is_project"])
            scratch = json.loads(desktop.dispatch("GET", "/api/snapshot", {}, desktop_store.ensure_scratch())[1:][1])
            self.assertTrue(scratch["project"]["scratch"])
            self.assertEqual(scratch["project"]["name"], desktop_store.SCRATCH_NAME)

    def test_browsing_lists_folders_only_and_marks_the_ones_with_a_marker(self):
        """작업 공간을 더하려면 경로를 외워야 했다 — 경로는 외우는 게 아니라 찾아가는 것이다.

        파일은 내지 않는다: 여기서 필요한 건 자리를 고르는 일이지 안을 들여다보는 일이 아니고,
        이름만 내는 쪽이 낼 수 있는 게 적어서 안전하다."""
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "alpha", ".asgard"))
            os.makedirs(os.path.join(root, "beta"))
            os.makedirs(os.path.join(root, ".hidden"))
            with open(os.path.join(root, "note.txt"), "w", encoding="utf-8") as handle:
                handle.write("x")

            status, _, body = desktop.dispatch_post("/api/projects/browse", {"path": root}, root)
            self.assertEqual(status, 200)
            listing = json.loads(body)
            names = [row["name"] for row in listing["entries"]]
            self.assertEqual(names, ["alpha", "beta"])  # 파일도 숨김 폴더도 없다
            self.assertTrue(next(r for r in listing["entries"] if r["name"] == "alpha")["project"])
            self.assertFalse(next(r for r in listing["entries"] if r["name"] == "beta")["project"])
            # 마지막 조각은 지금 서 있는 자리다 — 눌러서 되돌아갈 수 있어야 하므로 같은 경로여야 한다
            self.assertEqual(listing["crumbs"][-1]["path"], listing["path"])

            hidden = json.loads(
                desktop.dispatch_post("/api/projects/browse", {"path": root, "hidden": True}, root)[1:][1]
            )
            self.assertIn(".hidden", [row["name"] for row in hidden["entries"]])

    def test_browsing_a_non_folder_says_which_path_failed(self):
        with tempfile.TemporaryDirectory() as root:
            status, _, body = desktop.dispatch_post("/api/projects/browse", {"path": os.path.join(root, "nope")}, root)
            self.assertEqual(status, 400)
            self.assertIn("nope", json.loads(body)["error"])

    def test_browsing_starts_beside_the_current_workspace_not_inside_it(self):
        """형제 폴더를 더하는 일이 훨씬 흔하다 — 지금 자리를 열면 '여기 아래에서 고르라'가 된다."""
        with tempfile.TemporaryDirectory() as root:
            here = os.path.join(root, "repo")
            os.makedirs(os.path.join(here, "src"))
            os.makedirs(os.path.join(root, "sibling"))
            listing = json.loads(desktop.dispatch_post("/api/projects/browse", {}, here)[1:][1])
            self.assertEqual(os.path.realpath(listing["path"]), os.path.realpath(root))
            self.assertIn("sibling", [row["name"] for row in listing["entries"]])

    def test_the_window_only_offers_the_system_dialog_where_one_exists(self):
        """없는 단추를 눌러 놓고 실패를 보게 두지 않는다."""
        page = desktop.dispatch("GET", "/")[1:][1].decode()
        self.assertIn('id="project-dialog"', page)
        self.assertIn("$('#project-dialog').hidden=!s.capabilities?.folder_dialog", page)
        self.assertIsInstance(desktop.folder_dialog_available(), bool)
        with mock.patch.object(desktop.workspaces, "_folder_dialog_command", return_value=None):
            status, _, body = desktop.dispatch_post("/api/projects/pick", {}, os.getcwd())
            self.assertEqual(status, 501)
            self.assertIn("대화상자", json.loads(body)["error"])

    def test_cancelling_the_system_dialog_is_not_a_failure(self):
        """취소는 아무것도 안 고른 것이다 — 오류로 띄우면 취소할 때마다 빨간 말을 본다."""
        cancelled = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="User canceled")
        with mock.patch.object(desktop.workspaces, "_folder_dialog_command", return_value=["true"]):
            with mock.patch.object(subprocess, "run", return_value=cancelled):
                status, _, body = desktop.dispatch_post("/api/projects/pick", {}, os.getcwd())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["path"], "")

    def test_auto_permission_speaks_in_more_than_one_channel(self):
        """'자동 실행'은 스스로 손대는 모드다 — 켜 놓은 줄 모르면 안 된다.

        여태 이 값은 금(`--gold`)으로 표시됐는데, 이 독에서 금은 이미 넷(스레드·예약·승인·
        보내기)이 '지금 여기'라는 뜻으로 쓰고 있었다. 다섯 번째 금은 배경이다. 그래서 호박으로
        옮기고 아이콘(방패→번개)·굵기·글자까지 넷이 같이 말하게 했다."""
        page = desktop.dispatch("GET", "/")[1:][1].decode()
        style = page.split("<style>", 1)[1].split("</style>", 1)[0]
        # 선언 블록을 통째로 본다 — 줄 단위로 세면 규칙이 두 줄로 접히는 순간 검사가 눈을 감는다
        head, _, rest = style.partition('.dock-perm[data-mode="auto"]{')
        self.assertTrue(rest, "자동 실행에 제 표시가 없다")
        body = rest.split("}", 1)[0]
        self.assertIn("--warn", body)
        self.assertNotIn("--gold", body)
        # 색 말고도 말하는 채널이 있어야 한다 — 굵기와 아이콘 교체
        self.assertIn("font-weight", body)
        self.assertIn('.dock-perm[data-mode="auto"] ~ .dock-perm-ico.bolt', style)
        self.assertIn("PERM_HINT", page)

    def test_the_snapshot_names_the_branch_only_when_there_is_one(self):
        """독은 보내기 직전에 **어느 가지에 손대는지**를 말한다 — 없으면 지어내지 않는다."""
        with tempfile.TemporaryDirectory() as plain:
            snapshot = json.loads(desktop.dispatch("GET", "/api/snapshot", {}, plain)[1:][1])
            self.assertEqual(snapshot["project"]["branch"], "")

            repo = os.path.join(plain, "repo")
            os.makedirs(repo)
            for command in (
                ["git", "init", "-b", "trunk"],
                ["git", "config", "user.email", "t@t"],
                ["git", "config", "user.name", "t"],
                ["git", "commit", "--allow-empty", "-m", "x"],
            ):
                subprocess.run(command, cwd=repo, capture_output=True, check=True)
            snapshot = json.loads(desktop.dispatch("GET", "/api/snapshot", {}, repo)[1:][1])
            self.assertEqual(snapshot["project"]["branch"], "trunk")


class TestNativeShell(unittest.TestCase):
    def test_configured_native_app_is_discovered_first(self):
        with tempfile.TemporaryDirectory() as root:
            app = os.path.join(root, "asgard-desktop")
            open(app, "w").close()
            with (
                mock.patch.dict(os.environ, {"ASGARD_DESKTOP_APP": app}),
                mock.patch.object(desktop.server.shutil, "which", return_value=None),
            ):
                self.assertEqual(desktop.server._native_candidates()[0], app)

    def test_macos_prefers_the_bundle_so_the_dock_gets_a_face(self):
        """맨 실행 파일에는 번들이 없다 — 독에 이름도 아이콘도 안 붙는다. `.app` 안쪽을 먼저 본다."""
        app = "/Applications/Asgard Desktop.app/Contents/MacOS/asgard-desktop"
        with (
            mock.patch.object(desktop.server.os, "name", "posix"),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(desktop.server.shutil, "which", return_value="/usr/local/bin/asgard-desktop"),
            mock.patch.object(desktop.server.os.path, "isfile", return_value=True),
        ):
            candidates = desktop.server._native_candidates()
        self.assertTrue(candidates[0].endswith(".app/Contents/MacOS/asgard-desktop"))
        self.assertIn(app, candidates)
        self.assertLess(candidates.index(app), candidates.index("/usr/local/bin/asgard-desktop"))

    def test_windows_native_install_is_discovered(self):
        expected = os.path.join("C:\\Users\\yun\\AppData\\Local", "Asgard Desktop", "asgard-desktop.exe")
        with (
            mock.patch.object(desktop.server.os, "name", "nt"),
            mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:\\Users\\yun\\AppData\\Local"}, clear=True),
            mock.patch.object(desktop.server.shutil, "which", return_value=None),
            mock.patch.object(desktop.server.os.path, "isfile", side_effect=lambda path: path == expected),
        ):
            self.assertIn(expected, desktop.server._native_candidates())

    def test_native_app_receives_only_managed_loopback_context(self):
        with (
            mock.patch.object(desktop.server, "_native_candidates", return_value=["/app/asgard-desktop"]),
            mock.patch.object(desktop.server.subprocess, "run") as run,
        ):
            self.assertTrue(desktop.server._open_native("http://127.0.0.1:8766/", "/project"))
            env = run.call_args.kwargs["env"]
            self.assertEqual(env["ASGARD_DESKTOP_URL"], "http://127.0.0.1:8766/")
            self.assertEqual(env["ASGARD_DESKTOP_ROOT"], "/project")


if __name__ == "__main__":
    unittest.main()
