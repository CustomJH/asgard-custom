"""Asgard Studio API, security boundary, and real configuration wiring."""

import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from asgard.commands import studio, studio_store


class StudioCase(unittest.TestCase):
    def setUp(self):
        with studio.state._TASK_LOCK:
            studio.state._TASKS.clear()
        # 기억이 생긴 뒤로 테스트는 자기 자리를 갖고 놀아야 한다 — 실측: 첫 판에서 테스트의
        # 임시 디렉터리들이 사용자의 실제 프로젝트 등록부에 그대로 쌓였다.
        home = tempfile.mkdtemp(prefix="asgard-studio-home-")
        patcher = mock.patch.dict(os.environ, {studio_store.STUDIO_STATE_ENV: home})
        patcher.start()
        self.addCleanup(patcher.stop)
        # 시작 경계 사다리가 이 변수를 두 번째로 본다 — 부모 환경에 남아 있으면 테스트가
        # 자기 자리 대신 남이 정해 준 자리를 재게 된다.
        os.environ.pop("ASGARD_STUDIO_ROOT", None)
        self.studio_state = home
        studio.state._LOADED_ROOTS.clear()
        studio.state._CURRENT_ROOT = None
        studio.state._SERVER = None


class TestDispatch(StudioCase):
    def test_root_is_self_contained_studio(self):
        status, ctype, body = studio.dispatch("GET", "/")
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        # 이름은 한 벌이어야 한다 — 제목·워드마크·첫 화면이 같은 것을 부른다. 여는 화면에만
        # 남아 있던 옛 이름이 이 검사를 통과시키던 적이 있다. 그래서 새 이름이 **있는지**와
        # 옛 이름이 **없는지**를 같이 짚는다: 하나만 짚으면 둘이 나란히 살아도 통과한다.
        self.assertIn("Asgard Studio", page)
        self.assertNotIn("Asgard Desktop", page)
        self.assertNotIn("asgard desktop", page)
        self.assertIn("플러그인과 스킬", page)
        self.assertIn("승인 필요", page)
        # 목적지 줄은 이제 그림 + 이름 + 수 세 조각이다(접힌 레일에서 그림이 이름을 대신 선다).
        # 그래서 속성 바로 뒤의 글자로 짚지 않는다 — 지킬 것은 배치가 아니라 **그 문이 있고
        # 이름이 붙어 있다**는 것이다.
        self.assertIn('data-view="plan"', page)
        self.assertIn('<span class="lb">기획</span>', page)
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

    def test_the_ledger_rail_folds(self):
        """원장은 접힌다 — 그리고 접힌 채로도 어디로 갈지 말한다.

        지킬 것이 넷이다.

        1. 목적지마다 **그림**이 있다. 접히면 이름이 사라지므로, 그림이 없는 줄은 접힌 순간
           빈 칸이 된다 — 여섯 개 중 하나만 빠져도 그 자리는 못 짚는 자리가 된다.
        2. 접힘은 **폭 값 하나**(`--rail`)가 쥔다. 줄마다 감추는 규칙으로 접으면 레일은 좁아진
           척만 하고 무대는 한 뼘도 안 넓어진다.
        3. 접힌 상태는 **이 기계에 남는다**(localStorage). 프로젝트 설정으로 새면 남이 이
           저장소를 받았을 때 그 사람 창이 접혀서 열린다.
        4. 좁은 폭에서는 원장이 레일이 아니라 덮개라 접힘이 **되돌려진다**. 손잡이도 감춘다 —
           그때 `.dest button` 이 `.rail-toggle` 의 display 를 이기므로 클래스를 하나 더 짚어야
           한다(실측: 안 짚으면 100% 폭짜리 손잡이가 '설정'을 26px 로 눌렀다).
        """
        page = studio.dispatch("GET", "/")[1:][1].decode()
        rail = page.split('<aside class="ledger"', 1)[1].split("</aside>", 1)[0]
        for view in ("home", "tickets", "plan", "projects", "artifacts", "plugins", "settings"):
            door = rail.split(f'data-view="{view}"', 1)
            self.assertEqual(len(door), 2, view)
            self.assertIn('<svg class="ico"', door[1].split("</button>", 1)[0], view)
        # 설정은 목적지 무리가 아니라 발치의 도구다
        self.assertIn('<nav class="dest foot"', rail)
        self.assertLess(rail.index('id="recent-list"'), rail.index('data-view="settings"'))
        # 접힘 = 폭 값 하나 · 기억은 이 기계에
        self.assertIn(':root[data-rail="mini"]{--rail:', page)
        self.assertIn("asgard.studio.rail", page)
        self.assertNotIn("studio_rail", page)  # 서버 설정으로 새면 여기서 걸린다
        # 좁은 폭에서는 되돌린다
        sheet = page.split("@media(max-width:960px){", 1)[1]
        self.assertIn('[data-rail="mini"] .ledger-body{display:flex}', sheet)
        self.assertIn(".dest .rail-toggle{display:none}", sheet)

    def test_the_dock_is_the_only_place_that_takes_input(self):
        """적는 자리는 대화 아래 독 하나다 — 새 작업이든 이어가기든, 권한까지 거기서 정한다.

        여태는 머리에도 입력이 있어서 같은 칸이 상황에 따라 조용히 모드를 바꿨다(돌고 있는
        동안 적으면 새 작업). 그래서 이 검사가 지킬 것은 둘이다: 독이 온전히 있다 ·
        **머리에는 입력도 권한도 없다**(되살아나면 그 혼동이 같이 돌아온다)."""
        page = studio.dispatch("GET", "/")[1:][1].decode()
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
        page = studio.dispatch("GET", "/")[1:][1].decode()
        script = page.split("<script>", 1)[1]
        self.assertIn("function renderDockHint()", script)
        for reason in ("보낼 내용이 비어 있어요", "상한이에요", "이 턴이 끝나면 보내요", "보내는 중"):
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
        status, ctype, body = studio.dispatch("GET", "/asset/logo")
        self.assertEqual((status, ctype), (200, "image/png"))
        self.assertTrue(body.startswith(b"\x89PNG"))
        # 앱 아이콘 — 네이티브 창과 브라우저 폴백이 같은 얼굴을 든다
        for path in ("/asset/app-icon", "/favicon.ico"):
            status, ctype, body = studio.dispatch("GET", path)
            self.assertEqual((status, ctype), (200, "image/png"), path)
            self.assertTrue(body.startswith(b"\x89PNG"), path)
        status, _, body = studio.dispatch("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True, "surface": "studio"})
        self.assertEqual(studio.dispatch("GET", "/missing", {})[0], 404)
        self.assertEqual(studio.dispatch("POST", "/", {})[0], 405)

    def test_snapshot_and_catalog_use_real_sources(self):
        with tempfile.TemporaryDirectory() as root:
            status, _, body = studio.dispatch("GET", "/api/snapshot", {}, root)
            snapshot = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual(snapshot["project"]["root"], root)
            self.assertIn("provider", snapshot)
            self.assertGreater(snapshot["catalog"]["skills"], 0)
            status, _, body = studio.dispatch("GET", "/api/catalog", {}, root)
            self.assertTrue(json.loads(body)["skills"])

    def test_plan_api_reuses_the_project_local_plan_store(self):
        with tempfile.TemporaryDirectory() as root:
            status, _, body = studio.dispatch_post("/api/plans", {"idea": "협업 기획"}, root)
            self.assertEqual(status, 201)
            created = json.loads(body)["plan"]

            status, _, body = studio.dispatch("GET", f"/api/plans/{created['id']}", {}, root)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["plan"]["title"], "협업 기획")

            status, _, body = studio.dispatch_post(
                f"/api/plans/{created['id']}/edit",
                {"op": "section", "section": "overview", "body": "- 사용자가 검토할 Asgard 제안"},
                root,
            )
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["readiness"]["spec"]["ready"])

    def test_a_new_plan_needs_only_one_line(self):
        """Studio의 기획은 "어떤 기획을 할까요?" 한 칸에서 시작한다 — 적는 것은 한 줄뿐이다.

        한 줄 뒤에 오는 것은 고르기 하나다: 질문 없이 초안을 쓸지, 문답으로 다듬을지."""
        with tempfile.TemporaryDirectory() as root:
            status, _, body = studio.dispatch_post("/api/plans", {"idea": "검색 명세를 정리하고 싶다"}, root)
            self.assertEqual(status, 201)
            view = json.loads(body)
            self.assertEqual(view["plan"]["phase"], "intake")
            self.assertEqual(view["next"]["action"], "choose_mode")

            status, _, body = studio.dispatch_post("/api/plans", {"idea": "   "}, root)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["error"]["code"], "invalid_plan")


class TestTaskLifecycle(StudioCase):
    def test_important_task_waits_for_one_time_approval(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(studio.tasks, "_start") as start:
            status, _, body = studio.create_task({"prompt": "README를 검토해줘", "permission": "important"}, root)
            task = json.loads(body)
            self.assertEqual(status, 202)
            self.assertEqual(task["status"], "needs_input")
            self.assertEqual(task["approval"]["scope"], root)
            start.assert_not_called()

            status, _, body = studio.approve_task({"id": task["id"], "decision": "allow_once"}, root)
            self.assertEqual(status, 202)
            self.assertEqual(json.loads(body)["status"], "queued")
            start.assert_called_once_with(task["id"], root)

    def test_deny_blocks_without_execution(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(studio.tasks, "_start") as start:
            _, _, body = studio.create_task({"prompt": "파일을 수정해줘", "permission": "manual"}, root)
            task = json.loads(body)
            status, _, body = studio.approve_task({"id": task["id"], "decision": "deny"}, root)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["status"], "blocked")
            start.assert_not_called()

    def test_auto_task_uses_existing_asgard_run_command(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(studio.tasks, "_start") as start:
            status, _, body = studio.create_task(
                {"prompt": "테스트를 실행해줘", "permission": "auto", "provider": "openai"}, root
            )
            task = json.loads(body)
            self.assertEqual(status, 202)
            self.assertEqual(task["status"], "queued")
            with studio.state._TASK_LOCK:
                command = studio.state._TASKS[task["id"]]["command"]
            self.assertEqual(command[1:4], ["-m", "asgard", "run"])
            self.assertIn("--json", command)
            self.assertEqual(command[-2:], ["--provider", "openai"])
            start.assert_called_once()

    def test_prompt_and_permission_are_validated(self):
        self.assertEqual(studio.create_task({"prompt": ""}, ".")[0], 400)
        self.assertEqual(studio.create_task({"prompt": "x", "permission": "forever"}, ".")[0], 400)
        self.assertEqual(studio.create_task({"prompt": "x", "label": "x" * 201}, ".")[0], 400)

    def test_task_label_is_display_metadata_not_the_executed_prompt(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(studio.tasks, "_start"):
            _, _, body = studio.create_task(
                {"prompt": "full planner context", "label": "Asgard 기획 제안", "permission": "auto"}, root
            )
            task = json.loads(body)
            self.assertEqual(task["label"], "Asgard 기획 제안")
            with studio.state._TASK_LOCK:
                self.assertEqual(studio.state._TASKS[task["id"]]["command"][4], "full planner context")

    def test_follow_keeps_one_quest_and_carries_the_earlier_turns(self):
        """이어가기는 새 줄이 아니라 같은 작업의 다음 턴이다 — 원장의 줄은 하나로 남는다."""
        with tempfile.TemporaryDirectory() as root, mock.patch.object(studio.tasks, "_start"):
            _, _, body = studio.create_task({"prompt": "README를 살펴봐", "permission": "auto"}, root)
            task_id = json.loads(body)["id"]
            with studio.state._TASK_LOCK:
                studio.state._TASKS[task_id].update({"status": "ready", "result": "살펴봤습니다"})
                studio.state._TASKS[task_id]["turns"].append({"role": "agent", "text": "살펴봤습니다", "ts": 2})

            status, _, body = studio.follow_task({"id": task_id, "prompt": "이제 고쳐줘"}, root)
            followed = json.loads(body)
            self.assertEqual(status, 202)
            self.assertEqual(followed["status"], "queued")
            self.assertEqual([turn["role"] for turn in followed["turns"]], ["user", "agent", "user"])
            self.assertEqual(len(studio.tasks._task_snapshot(root)), 1)  # 줄이 늘지 않는다
            with studio.state._TASK_LOCK:
                composed = studio.state._TASKS[task_id]["command"][4]
            for carried in ("README를 살펴봐", "살펴봤습니다", "이제 고쳐줘"):
                self.assertIn(carried, composed)

    def test_follow_can_change_how_far_this_turn_runs_by_itself(self):
        """권한 칸이 독으로 내려왔으니 이어가는 턴도 그 값으로 돈다 — 아니면 그 칸은 장식이다."""
        with tempfile.TemporaryDirectory() as root, mock.patch.object(studio.tasks, "_start") as start:
            _, _, body = studio.create_task({"prompt": "살펴봐", "permission": "important"}, root)
            task_id = json.loads(body)["id"]
            with studio.state._TASK_LOCK:
                studio.state._TASKS[task_id]["status"] = "ready"

            _, _, body = studio.follow_task({"id": task_id, "prompt": "이어서", "permission": "auto"}, root)
            followed = json.loads(body)
            self.assertEqual(followed["status"], "queued")  # 자동이면 승인을 안 묻는다
            self.assertEqual(followed["permission"], "auto")  # 기록에도 남는다
            start.assert_called_once_with(task_id, root)

            # 안 주면 그 작업이 여태 쓰던 값을 지킨다
            with studio.state._TASK_LOCK:
                studio.state._TASKS[task_id]["status"] = "ready"
            _, _, body = studio.follow_task({"id": task_id, "prompt": "또 이어서"}, root)
            self.assertEqual(json.loads(body)["permission"], "auto")
            self.assertEqual(studio.follow_task({"id": task_id, "prompt": "x", "permission": "always"}, root)[0], 400)

    def test_follow_refuses_a_turn_that_has_not_finished(self):
        """돌고 있는 작업에는 붙이지 않는다 — 화면이 다음 턴을 예약해 두는 근거다."""
        with studio.state._TASK_LOCK:
            studio.state._TASKS["live"] = {"id": "live", "status": "running", "created": 1, "updated": 1, "turns": []}
        self.assertEqual(studio.follow_task({"id": "live", "prompt": "이어서"}, ".")[0], 409)
        self.assertEqual(studio.follow_task({"id": "gone", "prompt": "이어서"}, ".")[0], 404)
        self.assertEqual(studio.follow_task({"id": "live", "prompt": " "}, ".")[0], 400)

    @unittest.skipUnless(hasattr(studio.signal, "SIGSTOP"), "process pause is POSIX-only")
    def test_running_task_can_pause_resume_and_stop(self):
        """멈춤은 **무리 전체**에 걸려야 한다.

        맨 앞의 프로세스 하나에만 SIGSTOP을 걸면 멈추는 것은 껍데기다: 모델을 실제로 부르는
        것은 그 아래의 CLI라, 창은 '일시정지'라고 적는데 토큰은 계속 나갔다. `_run_task`가
        `start_new_session`으로 띄우니 무리는 그 작업만의 것이고, 무리째 거는 것이 옳다."""
        process = mock.Mock(pid=4321)
        task = {"id": "live", "status": "running", "created": 1, "updated": 1, "process": process}
        with studio.state._TASK_LOCK:
            studio.state._TASKS["live"] = task
        with (
            mock.patch.object(studio.tasks.os, "getpgid", return_value=4321),
            mock.patch.object(studio.tasks.os, "killpg") as killpg,
        ):
            self.assertEqual(studio.pause_task({"id": "live"})[0], 200)
            self.assertEqual(task["status"], "paused")
            killpg.assert_called_with(4321, studio.signal.SIGSTOP)
            self.assertEqual(studio.resume_task({"id": "live"})[0], 200)
            self.assertEqual(task["status"], "running")
            killpg.assert_called_with(4321, studio.signal.SIGCONT)
        process.send_signal.assert_not_called()  # 하나만 겨눈 신호는 이제 없다
        with mock.patch("asgard.agent.tools._kill_group") as kill_group:
            self.assertEqual(studio.stop_task({"id": "live"})[0], 200)
        kill_group.assert_called_once_with(process)
        self.assertEqual(task["status"], "blocked")

    def test_stop_is_heard_before_the_process_exists(self):
        """중지는 의사 표시가 먼저다.

        창은 `queued`도 '실행 중'으로 그리고 중지 단추를 함께 내놓는다. 승인을 누르고 곧바로
        중지를 누르면 그 사이에는 아직 프로세스가 없는데, 여태 그 자리는 409로 튕겨 단추가
        죽은 것처럼 보였다. 이제 뜻을 먼저 적고, `_run_task`가 그 표시를 보고 물러난다."""
        with studio.state._TASK_LOCK:
            studio.state._TASKS["soon"] = {"id": "soon", "status": "queued", "created": 1, "updated": 1}
        status, _, body = studio.stop_task({"id": "soon"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "blocked")
        with studio.state._TASK_LOCK:
            self.assertTrue(studio.state._TASKS["soon"]["stopped"])
        # 표시를 본 실행기는 프로세스를 아예 띄우지 않는다
        with mock.patch.object(studio.tasks.subprocess, "Popen") as popen:
            studio.tasks._run_task("soon", ".")
        popen.assert_not_called()
        with studio.state._TASK_LOCK:
            self.assertEqual(studio.state._TASKS["soon"]["status"], "blocked")
        # 이미 끝난 작업에는 중지가 뜻이 없다 — 그건 409가 맞다
        self.assertEqual(studio.stop_task({"id": "soon"})[0], 409)
        self.assertEqual(studio.stop_task({"id": "gone"})[0], 404)


class TestSettings(StudioCase):
    def test_project_settings_persist_through_canonical_store(self):
        with tempfile.TemporaryDirectory() as root:
            status, _, body = studio.save_settings(
                {
                    "scope": "project",
                    "section": "ui",
                    "values": {"theme": "dark", "density": "compact", "studio_permission": "manual"},
                },
                root,
            )
            result = json.loads(body)
            self.assertEqual(status, 200)
            self.assertTrue(os.path.isfile(result["saved"]))
            self.assertEqual(result["settings"]["effective"]["ui"]["studio_permission"], "manual")

    def test_engine_change_answers_with_the_re_resolved_engine(self):
        """엔진을 바꾸면 그 응답만으로 창이 지금 상태를 말할 수 있어야 한다 —
        settings만 돌려주면 상태 표시줄·연결 상자는 옛 엔진에 머문다."""
        with tempfile.TemporaryDirectory() as root:
            status, _, body = studio.save_settings(
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
            studio.save_settings(
                {"scope": "project", "section": "provider", "values": {"name": "openai_compat", "model": "m2"}}, root
            )
            kept = settings.load_project(root)["provider"]
            self.assertEqual(kept["model"], "m2")
            self.assertEqual(kept["base_url"], "http://gpu.local:8000/v1")
            self.assertEqual(kept["rpm"], 40)

            studio.save_settings(
                {"scope": "project", "section": "provider", "values": {"name": "ollama", "model": ""}}, root
            )
            self.assertEqual(settings.load_project(root)["provider"], {"name": "ollama"})

    def test_global_scope_and_unknown_keys_are_guarded(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"HOME": home}):
                status, _, body = studio.save_settings(
                    {"scope": "global", "section": "lagom", "values": {"mode": "lite"}}, root
                )
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["saved"].startswith(home))
            self.assertEqual(
                studio.save_settings({"scope": "project", "section": "provider", "values": {"secret": "no"}}, root)[0],
                400,
            )
            self.assertEqual(studio.save_settings({"scope": "team", "section": "ui", "values": {}}, root)[0], 400)


class TestTheRenameKeepsWhatWasThere(StudioCase):
    """`desktop` → `studio` 개명이 사용자의 것을 안 잃는다.

    개명은 우리 사정이지 사용자의 사정이 아니다. 그런데 이 창의 이름은 **디스크 경로**와
    **설정 키**에 박혀 있었다: `.asgard/desktop/`, `ui.desktop_permission`. 아무 장치 없이
    이름만 바꾸면 사용자는 개명한 날 작업 이력·개인 작업 공간·권한 설정을 한꺼번에 잃는다 —
    지워지진 않지만 아무도 안 읽는 자리에 남으니 잃은 것과 같다.
    """

    def test_the_old_folder_is_moved_in_not_left_behind(self):
        """옛 자리는 **옮겨 온다**. 폴백으로 읽기만 하면 두 자리가 영영 같이 산다."""
        with tempfile.TemporaryDirectory() as root:
            legacy = os.path.join(root, ".asgard", "desktop")
            os.makedirs(legacy)
            with open(os.path.join(legacy, "tasks.jsonl"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"id": "old", "prompt": "옛 자리의 작업", "status": "ready"}) + "\n")

            rows = studio_store.load_tasks(root)

            self.assertEqual([row["id"] for row in rows], ["old"])
            self.assertTrue(os.path.exists(os.path.join(root, ".asgard", "studio", "tasks.jsonl")))
            self.assertFalse(os.path.exists(legacy), "옮긴 뒤 옛 자리는 남지 않는다")

    def test_the_new_place_wins_when_both_exist(self):
        """새 자리에 이미 있으면 그쪽이 정본이다 — 이관이 덮어쓰면 되돌릴 수 없다."""
        with tempfile.TemporaryDirectory() as root:
            legacy = os.path.join(root, ".asgard", "desktop")
            current = os.path.join(root, ".asgard", "studio")
            os.makedirs(legacy)
            os.makedirs(current)
            for place, task_id in ((legacy, "old"), (current, "new")):
                with open(os.path.join(place, "tasks.jsonl"), "w", encoding="utf-8") as handle:
                    handle.write(json.dumps({"id": task_id, "prompt": "p", "status": "ready"}) + "\n")

            self.assertEqual([row["id"] for row in studio_store.load_tasks(root)], ["new"])
            # 안 옮긴 옛것은 조용히 지우지 않는다 — 사용자가 볼 수 있는 자리에 남긴다
            self.assertTrue(os.path.exists(os.path.join(legacy, "tasks.jsonl")))

    def test_the_moved_workspace_is_still_the_workspace(self):
        """개인 작업 공간은 옮긴 폴더 **안에** 산다 — 기록에 적힌 절대경로도 같이 고쳐야 한다.

        파일만 옮기고 주소를 그대로 두면, 여태 하던 일이 사이드바에 "남의 프로젝트 ·
        폴더를 찾을 수 없습니다"로 뜬다. 이사는 짐을 옮기는 것과 주소를 고치는 것 둘 다다."""
        with tempfile.TemporaryDirectory() as home:
            legacy = os.path.join(home, ".asgard", "desktop")
            os.makedirs(os.path.join(legacy, "workspace"))
            stale = os.path.join(legacy, "workspace")
            with open(os.path.join(legacy, "index.jsonl"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"id": "t", "root": stale, "prompt": "p", "status": "ready"}) + "\n")
            with open(os.path.join(legacy, "projects.json"), "w", encoding="utf-8") as handle:
                json.dump([{"root": stale, "opened": 1}], handle)

            # 이관은 **기본 자리**에서만 돈다(`ASGARD_STUDIO_STATE`를 준 사람은 자리를 스스로
            # 정한 것이다). 그래서 환경변수를 걷고 홈을 임시 폴더로 바꿔 놓고 잰다 — 판정도
            # 같은 홈 안에서 해야 한다: 밖에서 부르면 `scratch_root()`가 진짜 홈을 가리킨다.
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(studio_store.STUDIO_STATE_ENV, None)
                with mock.patch("os.path.expanduser", lambda p: p.replace("~", home, 1)):
                    rows = studio_store.feed(10)
                    scratch = studio_store.scratch_root()
                    self.assertEqual([row["root"] for row in rows], [scratch])
                    self.assertTrue(studio_store.is_scratch(rows[0]["root"]), "옮긴 뒤에도 개인 작업 공간이다")
                    self.assertEqual(
                        [row["root"] for row in studio_store.list_projects() if not row["scratch"]],
                        [],
                    )
            self.assertFalse(os.path.exists(legacy), "옮긴 뒤 옛 자리는 남지 않는다")

    def test_the_old_permission_key_still_arms_the_window(self):
        """`ui.desktop_permission`으로 맞춰 둔 창이 개명 뒤 조용히 좁아지지 않는다."""
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".asgard"), exist_ok=True)
            with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
                json.dump({"ui": {"desktop_permission": "auto"}}, handle)

            effective = studio.snapshot.settings_state(root)["effective"]["ui"]

            self.assertEqual(effective.get("studio_permission"), "auto")


class TestProjectRegistry(StudioCase):
    def _registered(self) -> list[dict]:
        """등록부에서 온 줄만 — 개인 작업 공간은 등록의 결과가 아니라 앱의 성질이라 늘 붙는다."""
        rows = studio_store.list_projects()
        self.assertTrue(rows[-1]["scratch"], "개인 작업 공간은 목록 끝에 언제나 있다")
        return [row for row in rows if not row["scratch"]]

    def test_prune_drops_only_the_roots_that_are_gone(self):
        """자리에 없는 등록만 걷어낸다 — 살아 있는 것과 현재 경계는 남는다."""
        with tempfile.TemporaryDirectory() as alive, tempfile.TemporaryDirectory() as current:
            studio_store.add_project(alive)
            studio_store.add_project(current)
            with tempfile.TemporaryDirectory() as doomed:
                studio_store.add_project(doomed)
            self.assertEqual(len(self._registered()), 3)

            removed = studio_store.prune_projects(current)
            self.assertEqual(removed, 1)
            roots = {os.path.abspath(row["root"]) for row in self._registered()}
            self.assertEqual(roots, {os.path.abspath(alive), os.path.abspath(current)})

    def test_prune_keeps_the_open_project_even_when_its_folder_vanished(self):
        with tempfile.TemporaryDirectory() as home:
            missing = os.path.join(home, "unmounted")
            os.makedirs(missing)
            studio_store.add_project(missing)
            os.rmdir(missing)
            self.assertEqual(studio_store.prune_projects(missing), 0)
            self.assertEqual(len(self._registered()), 1)

    def test_the_personal_workspace_cannot_be_added_or_forgotten(self):
        """개인 작업 공간은 앱의 일부다 — 등록부에 적히지도, 목록에서 빠지지도 않는다.

        (등록부에 적히면 '사라진 폴더 정리'가 언젠가 그것을 지우고, 그 순간 프로젝트를 하나도
        안 연 사람에게 설 자리가 없어진다.)"""
        scratch = studio_store.ensure_scratch()
        studio_store.add_project(scratch)
        self.assertEqual(self._registered(), [])
        self.assertFalse(studio_store.remove_project(scratch))
        self.assertTrue(studio_store.list_projects()[-1]["scratch"])


class TestTaskEvidence(StudioCase):
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
            with mock.patch.object(studio.tasks, "_workspace_files", return_value=after):
                changed = studio.tasks._changed_by_task(root, before)
            self.assertEqual([row["path"] for row in changed], ["touched.py", "made.py"])

    def test_a_file_that_changed_state_during_the_task_still_counts(self):
        with tempfile.TemporaryDirectory() as root:
            before = [{"status": "??", "path": "draft.py"}]
            after = [{"status": "M", "path": "draft.py"}]
            with mock.patch.object(studio.tasks, "_workspace_files", return_value=after):
                self.assertEqual(studio.tasks._changed_by_task(root, before), after)


class TestHostAndOriginGuard(unittest.TestCase):
    def test_loopback_hosts_and_origins(self):
        for host in ("127.0.0.1", "127.0.0.1:8766", "localhost:8766", "[::1]:8766"):
            self.assertTrue(studio.host_allowed(host), host)
        for host in (None, "", "evil.example", "10.0.0.5:80"):
            self.assertFalse(studio.host_allowed(host), repr(host))
        self.assertTrue(studio.origin_allowed(None))
        self.assertTrue(studio.origin_allowed("http://127.0.0.1:8766"))
        self.assertFalse(studio.origin_allowed("https://127.0.0.1:8766"))
        self.assertFalse(studio.origin_allowed("http://evil.example"))

    def test_live_roundtrip_has_security_headers(self):
        with tempfile.TemporaryDirectory() as root:
            httpd = studio.server._bind("127.0.0.1", 0, root)
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
                        "X-Asgard-Studio": "1",
                    },
                )
                with urllib.request.urlopen(preview_request, timeout=5) as response:
                    self.assertEqual(response.status, 201)
                    self.assertEqual(json.loads(response.read())["plan"]["title"], "preview plan")
            finally:
                httpd.shutdown()
                httpd.server_close()


class TestAppFirstLaunch(StudioCase):
    """창은 폴더가 아니라 기계의 것이다 — 여는 데 프로젝트가 필요하지 않다."""

    def test_a_plain_folder_does_not_become_a_project(self):
        """표식 없는 자리에서 띄우면 개인 작업 공간에 선다 — 그리고 등록부는 그대로다.

        여태는 cwd가 곧 프로젝트였다. 독에서 아이콘을 누르면 홈이 프로젝트가 되고, 사용자의
        집에 `.asgard/studio/`이 생기고, 열어 본 적 없는 자리가 목록에 쌓였다."""
        with tempfile.TemporaryDirectory() as plain:
            with mock.patch.object(studio.boundary.os, "getcwd", return_value=plain):
                start = studio.resolve_start_root()
            self.assertTrue(studio_store.is_scratch(start))
            self.assertEqual([row for row in studio_store.list_projects() if not row["scratch"]], [])
            self.assertFalse(os.path.isdir(os.path.join(plain, ".asgard")))

    def test_home_is_never_a_project_even_with_marks_in_it(self):
        """집에 `.git`이 있어도 집은 프로젝트가 아니다 — 경계가 사용자의 삶 전체가 된다."""
        self.assertFalse(studio_store.looks_like_project(os.path.expanduser("~")))
        self.assertFalse(studio_store.looks_like_project(os.sep))

    def test_even_a_marked_folder_does_not_pull_the_window_into_itself(self):
        """저장소 안에서 켜도 창은 **메인 루트**에서 선다 — 프로젝트는 창 안에서 고른다.

        여태는 표식 있는 cwd가 창의 자리를 정했다. 그래서 같은 앱이 어디서 켜느냐에 따라
        다른 곳에서 열렸다: 터미널에서 켜면 그 저장소, 독에서 누르면 다른 데. 창이 사람의
        것이라면 그럴 수 없다."""
        with tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, ".git"))
            self.assertTrue(studio_store.looks_like_project(repo))
            with mock.patch.object(studio.boundary.os, "getcwd", return_value=repo):
                self.assertTrue(studio_store.is_scratch(studio.resolve_start_root()))

    def test_the_last_project_does_not_reopen_itself(self):
        """지난번 자리로 **끌려가지** 않는다 — 등록부는 목록이지 창의 정체가 아니다."""
        with tempfile.TemporaryDirectory() as recent, tempfile.TemporaryDirectory() as plain:
            studio_store.add_project(recent)
            with mock.patch.object(studio.boundary.os, "getcwd", return_value=plain):
                self.assertTrue(studio_store.is_scratch(studio.resolve_start_root()))
            # 목록에는 그대로 있다 — 창 안에서 고르면 그 자리로 간다
            self.assertIn(os.path.abspath(recent), [row["root"] for row in studio_store.list_projects()])

    def test_an_explicit_root_beats_everything(self):
        with tempfile.TemporaryDirectory() as picked, tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, ".git"))
            with mock.patch.object(studio.boundary.os, "getcwd", return_value=repo):
                self.assertEqual(studio.resolve_start_root(picked), os.path.abspath(picked))
                with mock.patch.dict(os.environ, {"ASGARD_STUDIO_ROOT": picked}):
                    self.assertEqual(studio.resolve_start_root(), os.path.abspath(picked))


class TestWorkspacePerTask(StudioCase):
    """작업 공간은 창의 상태가 아니라 **그 작업의 값**이다."""

    def test_a_task_runs_where_it_was_asked_for_not_where_the_window_is(self):
        with tempfile.TemporaryDirectory() as here, tempfile.TemporaryDirectory() as there:
            status, _, body = studio.create_task({"prompt": "저기서 해라", "permission": "manual", "root": there}, here)
            task = json.loads(body)
            self.assertEqual(status, 202)
            self.assertEqual(task["root"], os.path.abspath(there))
            # 승인문도 실제로 돌 자리를 부른다 — "현재 프로젝트"라고 뭉뜽그리면 범위가 안 보인다
            self.assertIn(os.path.basename(there), task["approval"]["reason"])

    def test_an_unknown_workspace_is_refused(self):
        with tempfile.TemporaryDirectory() as here:
            status, _, body = studio.create_task({"prompt": "어디?", "root": "/nope/nowhere"}, here)
            self.assertEqual(status, 400)
            self.assertIn("작업 공간", json.loads(body)["error"])

    def test_following_a_task_stays_in_its_own_workspace(self):
        """창이 다른 자리로 옮겨 갔어도, 이어가는 턴은 그 대화가 시작된 자리에서 돈다.

        여태는 이어가기·승인이 전부 '지금 창이 보는 곳'에서 돌았다 — 프로젝트를 옮긴 뒤
        옛 작업을 승인하면 **남의 저장소에서** 실행됐다."""
        with tempfile.TemporaryDirectory() as origin, tempfile.TemporaryDirectory() as moved:
            task = json.loads(studio.create_task({"prompt": "시작", "permission": "manual"}, origin)[1:][1])
            started: list[str] = []
            with mock.patch.object(studio.tasks, "_start", side_effect=lambda _id, root: started.append(root)):
                # 창은 이제 moved를 본다. 그래도 승인은 origin을 연다.
                status, _, _ = studio.approve_task({"id": task["id"], "decision": "allow_once"}, moved)
                self.assertEqual(status, 202)
                self.assertEqual(started, [os.path.abspath(origin)])

    def test_the_personal_workspace_is_a_real_place_to_run_in(self):
        with tempfile.TemporaryDirectory() as here:
            scratch = studio_store.scratch_root()
            task = json.loads(
                studio.create_task({"prompt": "프로젝트 없이", "permission": "manual", "root": scratch}, here)[1:][1]
            )
            self.assertTrue(studio_store.is_scratch(task["root"]))
            self.assertTrue(os.path.isdir(task["root"]), "고른 순간 자리가 만들어져 있어야 한다")
            self.assertIn(studio_store.SCRATCH_NAME, task["approval"]["target"])


class TestCrossProjectFeed(StudioCase):
    """프로젝트를 옮겼다고 여태 하던 일이 목록에서 사라지면 안 된다."""

    def test_the_feed_spans_projects_while_the_scoped_list_does_not(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            studio.create_task({"prompt": "가에서", "permission": "manual"}, a)
            studio.create_task({"prompt": "나에서", "permission": "manual", "root": b}, a)

            feed = json.loads(studio.dispatch("GET", "/api/tasks", {"scope": ["all"]}, a)[1:][1])
            self.assertEqual({row["prompt"] for row in feed}, {"가에서", "나에서"})
            # 줄마다 어느 자리의 일인지 달고 온다 — 배지가 없으면 모르는 채로 눌러야 한다
            self.assertEqual({row["project"] for row in feed}, {os.path.basename(a), os.path.basename(b)})
            self.assertEqual({row["here"] for row in feed}, {True, False})

            scoped = json.loads(studio.dispatch("GET", "/api/tasks", {}, a)[1:][1])
            self.assertEqual([row["prompt"] for row in scoped], ["가에서"])

    def test_the_feed_survives_the_process_that_made_it(self):
        """창을 닫았다 열어도 남의 프로젝트 이력이 보인다 — 색인은 디스크에 있다."""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            studio.create_task({"prompt": "가에서", "permission": "manual"}, a)
            studio.create_task({"prompt": "나에서", "permission": "manual", "root": b}, a)
            with studio.state._TASK_LOCK:  # 프로세스가 죽은 셈 친다
                studio.state._TASKS.clear()

            feed = studio_store.feed()
            self.assertEqual({row["prompt"] for row in feed}, {"가에서", "나에서"})
            # 살아 있던 상태는 되살아나지 않는다 — 죽은 작업을 '실행 중'이라 말하면 계기가 아니다
            self.assertNotIn("running", {row["status"] for row in feed})

    def test_the_index_is_convenience_not_canon(self):
        """색인을 지워도 프로젝트의 기록에서 다시 세운다."""
        with tempfile.TemporaryDirectory() as a:
            studio.create_task({"prompt": "가에서", "permission": "manual"}, a)
            os.unlink(studio_store.index_path())
            self.assertEqual(studio_store.feed(), [])
            self.assertEqual(studio_store.reindex([a]), 1)
            self.assertEqual([row["prompt"] for row in studio_store.feed()], ["가에서"])

    def test_an_artifact_is_read_from_the_workspace_that_made_it(self):
        """남의 작업 공간의 작업을 열어 둔 채로 변경 파일을 눌러도 그 자리의 파일을 읽는다.

        자리를 안 실어 보내면 창이 선 저장소에서 같은 상대 경로를 찾는다 — 없으면 404 지만,
        하필 같은 이름이 있으면 **엉뚱한 파일의 내용**을 그 작업의 산출물이라고 보여 준다."""
        with tempfile.TemporaryDirectory() as here, tempfile.TemporaryDirectory() as there:
            for root, text in ((here, "이 저장소의 것"), (there, "저 저장소의 것")):
                with open(os.path.join(root, "note.txt"), "w", encoding="utf-8") as handle:
                    handle.write(text)
            studio_store.add_project(there)

            body = studio.dispatch("GET", "/api/artifact", {"path": ["note.txt"], "root": [there]}, here)[1:][1]
            self.assertEqual(json.loads(body)["text"], "저 저장소의 것")
            body = studio.dispatch("GET", "/api/artifact", {"path": ["note.txt"]}, here)[1:][1]
            self.assertEqual(json.loads(body)["text"], "이 저장소의 것")

    def test_reading_is_confined_to_workspaces_the_window_knows(self):
        """임의 경로를 받아 읽는 창은 파일 탐색기가 된다 — 그건 이 표면의 일이 아니다."""
        with tempfile.TemporaryDirectory() as here, tempfile.TemporaryDirectory() as stranger:
            with open(os.path.join(stranger, "note.txt"), "w", encoding="utf-8") as handle:
                handle.write("남의 것")
            for route in ("/api/artifact", "/api/diff"):
                status, _, body = studio.dispatch("GET", route, {"path": ["note.txt"], "root": [stranger]}, here)
                self.assertEqual(status, 403, route)
                self.assertIn("목록에 없는", json.loads(body)["error"])

    def test_the_snapshot_carries_the_feed_and_says_where_it_stands(self):
        with tempfile.TemporaryDirectory() as a:
            snapshot = json.loads(studio.dispatch("GET", "/api/snapshot", {}, a)[1:][1])
            self.assertIn("feed", snapshot)
            self.assertFalse(snapshot["project"]["scratch"])
            self.assertFalse(snapshot["project"]["is_project"])
            scratch = json.loads(studio.dispatch("GET", "/api/snapshot", {}, studio_store.ensure_scratch())[1:][1])
            self.assertTrue(scratch["project"]["scratch"])
            self.assertEqual(scratch["project"]["name"], studio_store.SCRATCH_NAME)

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

            status, _, body = studio.dispatch_post("/api/projects/browse", {"path": root}, root)
            self.assertEqual(status, 200)
            listing = json.loads(body)
            names = [row["name"] for row in listing["entries"]]
            self.assertEqual(names, ["alpha", "beta"])  # 파일도 숨김 폴더도 없다
            self.assertTrue(next(r for r in listing["entries"] if r["name"] == "alpha")["project"])
            self.assertFalse(next(r for r in listing["entries"] if r["name"] == "beta")["project"])
            # 마지막 조각은 지금 서 있는 자리다 — 눌러서 되돌아갈 수 있어야 하므로 같은 경로여야 한다
            self.assertEqual(listing["crumbs"][-1]["path"], listing["path"])

            hidden = json.loads(
                studio.dispatch_post("/api/projects/browse", {"path": root, "hidden": True}, root)[1:][1]
            )
            self.assertIn(".hidden", [row["name"] for row in hidden["entries"]])

    def test_browsing_a_non_folder_says_which_path_failed(self):
        with tempfile.TemporaryDirectory() as root:
            status, _, body = studio.dispatch_post("/api/projects/browse", {"path": os.path.join(root, "nope")}, root)
            self.assertEqual(status, 400)
            self.assertIn("nope", json.loads(body)["error"])

    def test_browsing_starts_beside_the_current_workspace_not_inside_it(self):
        """형제 폴더를 더하는 일이 훨씬 흔하다 — 지금 자리를 열면 '여기 아래에서 고르라'가 된다."""
        with tempfile.TemporaryDirectory() as root:
            here = os.path.join(root, "repo")
            os.makedirs(os.path.join(here, "src"))
            os.makedirs(os.path.join(root, "sibling"))
            listing = json.loads(studio.dispatch_post("/api/projects/browse", {}, here)[1:][1])
            self.assertEqual(os.path.realpath(listing["path"]), os.path.realpath(root))
            self.assertIn("sibling", [row["name"] for row in listing["entries"]])

    def test_the_window_only_offers_the_system_dialog_where_one_exists(self):
        """없는 단추를 눌러 놓고 실패를 보게 두지 않는다."""
        page = studio.dispatch("GET", "/")[1:][1].decode()
        self.assertIn('id="project-dialog"', page)
        self.assertIn("$('#project-dialog').hidden=!s.capabilities?.folder_dialog", page)
        self.assertIsInstance(studio.folder_dialog_available(), bool)
        with mock.patch.object(studio.workspaces, "_folder_dialog_command", return_value=None):
            status, _, body = studio.dispatch_post("/api/projects/pick", {}, os.getcwd())
            self.assertEqual(status, 501)
            self.assertIn("대화상자", json.loads(body)["error"])

    def test_cancelling_the_system_dialog_is_not_a_failure(self):
        """취소는 아무것도 안 고른 것이다 — 오류로 띄우면 취소할 때마다 빨간 말을 본다."""
        cancelled = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="User canceled")
        with mock.patch.object(studio.workspaces, "_folder_dialog_command", return_value=["true"]):
            with mock.patch.object(subprocess, "run", return_value=cancelled):
                status, _, body = studio.dispatch_post("/api/projects/pick", {}, os.getcwd())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["path"], "")

    def test_auto_permission_speaks_in_more_than_one_channel(self):
        """'자동 실행'은 스스로 손대는 모드다 — 켜 놓은 줄 모르면 안 된다.

        여태 이 값은 금(`--gold`)으로 표시됐는데, 이 독에서 금은 이미 넷(스레드·예약·승인·
        보내기)이 '지금 여기'라는 뜻으로 쓰고 있었다. 다섯 번째 금은 배경이다. 그래서 호박으로
        옮기고 아이콘(방패→번개)·굵기·글자까지 넷이 같이 말하게 했다."""
        page = studio.dispatch("GET", "/")[1:][1].decode()
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
            snapshot = json.loads(studio.dispatch("GET", "/api/snapshot", {}, plain)[1:][1])
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
            snapshot = json.loads(studio.dispatch("GET", "/api/snapshot", {}, repo)[1:][1])
            self.assertEqual(snapshot["project"]["branch"], "trunk")


class TestNativeShell(unittest.TestCase):
    def test_configured_native_app_is_discovered_first(self):
        with tempfile.TemporaryDirectory() as root:
            app = os.path.join(root, "asgard-studio")
            open(app, "w").close()
            with (
                mock.patch.dict(os.environ, {"ASGARD_STUDIO_APP": app}),
                mock.patch.object(studio.server.shutil, "which", return_value=None),
            ):
                self.assertEqual(studio.server._native_candidates()[0], app)

    def test_macos_prefers_the_bundle_so_the_dock_gets_a_face(self):
        """맨 실행 파일에는 번들이 없다 — 독에 이름도 아이콘도 안 붙는다. `.app` 안쪽을 먼저 본다."""
        app = "/Applications/Asgard Studio.app/Contents/MacOS/asgard-studio"
        with (
            mock.patch.object(studio.server.os, "name", "posix"),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(studio.server.shutil, "which", return_value="/usr/local/bin/asgard-studio"),
            mock.patch.object(studio.server.os.path, "isfile", return_value=True),
        ):
            candidates = studio.server._native_candidates()
        self.assertTrue(candidates[0].endswith(".app/Contents/MacOS/asgard-studio"))
        self.assertIn(app, candidates)
        self.assertLess(candidates.index(app), candidates.index("/usr/local/bin/asgard-studio"))

    def test_the_repo_local_build_is_reachable_from_the_repo(self):
        """리포가 방금 구운 번들을 그 리포에서 실행할 때 찾을 수 있어야 한다.

        후보 경로는 이 파일에서 `..`를 세어 리포 뿌리를 잡는다. 한 파일이던 `desktop.py`가
        패키지로 갈리면서 깊이가 하나 늘었는데 그 줄만 그대로여서, 뿌리가 `<리포>/src`에
        멈춰 있었다 — 빌드는 성공하는데 창은 말없이 브라우저로 떨어졌다(실측). 자릿수를
        직접 재지 않고 **뿌리에 있는 표식**으로 짚는다: 세는 수가 틀리면 여기서 걸린다."""
        server = studio.server.__file__
        repo = os.path.abspath(os.path.join(os.path.dirname(server), "..", "..", "..", ".."))
        self.assertTrue(os.path.exists(os.path.join(repo, "pyproject.toml")), f"뿌리가 아니다: {repo}")
        expected = os.path.join(repo, "studio-shell", "src-tauri", "target", "release", "asgard-studio")
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(studio.server.shutil, "which", return_value=None),
            mock.patch.object(studio.server.os.path, "isfile", return_value=True),
        ):
            self.assertIn(expected, studio.server._native_candidates())

    def test_windows_native_install_is_discovered(self):
        expected = os.path.join("C:\\Users\\yun\\AppData\\Local", "Asgard Studio", "asgard-studio.exe")
        with (
            mock.patch.object(studio.server.os, "name", "nt"),
            mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:\\Users\\yun\\AppData\\Local"}, clear=True),
            mock.patch.object(studio.server.shutil, "which", return_value=None),
            mock.patch.object(studio.server.os.path, "isfile", side_effect=lambda path: path == expected),
        ):
            self.assertIn(expected, studio.server._native_candidates())

    def test_native_app_receives_only_managed_loopback_context(self):
        with (
            mock.patch.object(studio.server, "_native_candidates", return_value=["/app/asgard-studio"]),
            mock.patch.object(studio.server.subprocess, "run") as run,
        ):
            self.assertTrue(studio.server._open_native("http://127.0.0.1:8766/", "/project"))
            env = run.call_args.kwargs["env"]
            self.assertEqual(env["ASGARD_STUDIO_URL"], "http://127.0.0.1:8766/")
            self.assertEqual(env["ASGARD_STUDIO_ROOT"], "/project")


class TestFailureReachesTheWindowIntact(StudioCase):
    """실패한 작업이 창에 **읽을 수 있는 모양**으로 도착하는가.

    여기가 사용자가 본 난잡함의 자리다: 창은 `asgard run --json`을 자식 프로세스로 띄우는데,
    프리플라이트가 막히면 JSON 대신 색칠된 체크리스트가 stdout으로 나왔고, 파싱에 실패한 창은
    그 원문을 결과 칸에 통째로 부었다. 이제 사유는 구조로 오고, 원문은 접힌 자리로 내려간다.
    """

    def test_a_structured_failure_survives_the_process_boundary(self):
        envelope = {
            "error": {
                "code": "preflight_failed",
                "message": "세션을 열 수 없습니다 — 점검 1건이 막혔습니다 (claude CLI)",
                "remedy": "https://claude.com/claude-code 설치 후 claude /login",
                "detail": {"checks": [{"name": "claude CLI", "ok": False, "detail": "not found", "fix": "설치"}]},
            }
        }
        failure = studio.tasks._failure_of(envelope, 2, json.dumps(envelope), "")
        assert failure is not None
        self.assertEqual(failure["code"], "preflight_failed")
        self.assertIn("claude CLI", failure["message"])
        self.assertIn("claude.com/claude-code", failure["remedy"])
        self.assertEqual(failure["detail"]["checks"][0]["name"], "claude CLI")

    def test_a_silent_failure_still_becomes_one_readable_line(self):
        """자식이 JSON을 안 냈어도 결과 칸에 원문을 붓지 않는다 — 표제 한 줄과 접힌 원문이다."""
        noisy = "  ✔ provider   Claude Code\n  ✘ claude CLI  not found\n! headless 실행 불가"
        failure = studio.tasks._failure_of({}, 2, noisy, "")
        assert failure is not None
        self.assertEqual(failure["code"], "task_failed")
        self.assertEqual(failure["message"], "! headless 실행 불가")
        self.assertEqual(failure["detail"]["exit_code"], 2)
        self.assertIn("claude CLI", failure["detail"]["output"])

    def test_a_clean_exit_is_not_a_failure(self):
        self.assertIsNone(studio.tasks._failure_of({"result": "다 했습니다"}, 0, "", ""))

    def test_a_finished_task_carries_the_error_beside_the_result(self):
        """사유는 결과 문자열과 **따로** 든다 — 창이 문구를 되파싱하면 문구를 바꿀 때 깨진다."""
        envelope = {"error": {"code": "preflight_failed", "message": "막혔습니다", "remedy": "고치세요"}}

        class _Proc:
            returncode = 2

            def communicate(self):
                return json.dumps(envelope), ""

        with tempfile.TemporaryDirectory() as root, mock.patch.object(studio.tasks, "_start"):
            _, _, body = studio.create_task({"prompt": "돌려줘", "permission": "auto"}, root)
            task_id = json.loads(body)["id"]
            with mock.patch.object(studio.tasks.subprocess, "Popen", return_value=_Proc()):
                studio.tasks._run_task(task_id, root)
            _, _, body = studio.dispatch("GET", "/api/task", {"id": [task_id]}, root)
            task = json.loads(body)
        self.assertEqual(task["status"], "blocked")
        self.assertEqual(task["error"]["code"], "preflight_failed")
        self.assertEqual(task["error"]["remedy"], "고치세요")
        self.assertEqual(task["result"], "막혔습니다")  # 원문 덤프가 아니라 사유 한 줄

    def test_a_process_that_will_not_start_arrives_the_same_shape(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(studio.tasks, "_start"):
            _, _, body = studio.create_task({"prompt": "돌려줘", "permission": "auto"}, root)
            task_id = json.loads(body)["id"]
            with mock.patch.object(studio.tasks.subprocess, "Popen", side_effect=OSError("no such binary")):
                studio.tasks._run_task(task_id, root)
            _, _, body = studio.dispatch("GET", "/api/task", {"id": [task_id]}, root)
            task = json.loads(body)
        self.assertEqual(task["status"], "blocked")
        self.assertEqual(task["error"]["code"], "task_spawn_failed")
        self.assertIn("OSError", task["error"]["message"])


class TestTheWindowBoundarySpeaksJson(StudioCase):
    def test_an_unexpected_failure_is_json_not_a_bare_type_name(self):
        """여태 `error: KeyError` 한 줄이 나갔다 — JSON이 아니라 창의 api()가 못 읽었다."""
        from asgard.commands import loopback

        status, ctype, body = loopback.error_result(KeyError("boom"), surface="studio", where="/api/tasks")
        self.assertEqual(status, 500)
        self.assertIn("json", ctype)
        self.assertEqual(json.loads(body)["error"]["code"], "internal_error")

    def test_the_window_renders_a_structured_error_not_a_raw_dump(self):
        """화면 쪽 계약 — 카드 렌더러와 그것을 부르는 자리가 둘 다 살아 있어야 한다."""
        page = studio.dispatch("GET", "/")[2].decode()
        self.assertIn("function errorCard(", page)
        self.assertIn("t.error?errorCard(t.error)", page)
        self.assertIn("err-fix", page)  # 처방은 사유와 다른 칸에 선다


class TestTheWindowFindsTheEngineItWasLaunchedWithout(unittest.TestCase):
    """독에서 누른 창은 셸을 안 거친다 — PATH가 넉 줄로 줄고 `claude`도 `codex`도 사라진다.

    실측(26-08-01): 그 상태에서 창이 띄운 모든 작업이 `claude CLI not found`로 막혔다.
    터미널에서는 같은 명령이 멀쩡히 돌았기 때문에 "창만 고장"으로 보였다."""

    def test_the_user_bin_dirs_come_back_when_the_shell_did_not_set_them(self):
        from asgard import platform as P

        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            added = P.ensure_user_path()
            now = os.environ["PATH"].split(os.pathsep)
            self.assertEqual(now[:2], ["/usr/bin", "/bin"])  # 사용자가 정한 앞머리는 안 건드린다
            for entry in added:
                self.assertIn(entry, now)
                self.assertTrue(os.path.isdir(entry))  # 없는 자리는 안 붙인다

    def test_repairing_twice_does_not_stack_the_same_dir(self):
        from asgard import platform as P

        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            P.ensure_user_path()
            once = os.environ["PATH"]
            self.assertEqual(P.ensure_user_path(), [])
            self.assertEqual(os.environ["PATH"], once)

    def test_every_command_passes_the_repair_not_just_main(self):
        """설치본에 따라 콘솔 스크립트가 `app()`을 직접 부른다 — `main()`에만 두면 새는 문이다."""
        import inspect

        from asgard import cli

        self.assertIn("ensure_user_path", inspect.getsource(cli._main))


class TestTheEngineChipTellsTheTruthBeforeSending(StudioCase):
    """엔진은 **작업이 도는 자리**가 정한다. 창이 선 자리와 독에서 고른 자리가 갈리면,
    상태 바가 말하는 엔진과 실제로 도는 엔진이 다르다 — 그 갈림이 화면에 없었다."""

    def test_the_provider_answer_follows_the_workspace_it_was_asked_about(self):
        from asgard import providers

        with tempfile.TemporaryDirectory() as root:
            status, _, body = studio.dispatch("GET", "/api/provider", {}, root)
            self.assertEqual(status, 200)
            answer = json.loads(body)
            expected = providers.resolve(root)
            self.assertEqual(answer["name"], expected.profile.name)
            self.assertEqual(answer["ready"], not expected.missing)
            self.assertEqual(answer["missing"], list(expected.missing))

    def test_an_unknown_folder_is_not_a_place_this_window_will_answer_for(self):
        status, _, body = studio.dispatch("GET", "/api/provider", {"root": ["/etc"]}, os.getcwd())
        self.assertEqual(status, 403)
        self.assertIn("작업 공간", json.loads(body)["error"])

    def test_the_engine_can_be_made_the_floor_for_folders_that_never_chose_one(self):
        """창만 쓰는 사람에게도 전역 기본을 정할 문이 있어야 한다 — 없으면 새 폴더마다
        말없이 기본값(anthropic)으로 떨어져 "키가 없다"며 막힌다."""
        page = studio.dispatch("GET", "/")[2].decode()
        self.assertIn('data-save-global="provider"', page)
        self.assertIn("모든 프로젝트 기본으로", page)

        # 전역 설정은 사용자의 실제 파일이다 — 테스트가 자기 집을 갖고 놀아야 한다
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home}):
                status, _, body = studio.dispatch_post(
                    "/api/settings",
                    {"scope": "global", "section": "provider", "values": {"name": "ollama", "model": "gemma4:12b-mlx"}},
                    root,
                )
                self.assertEqual(status, 200)
                saved = json.loads(body)
                self.assertTrue(saved["saved"].startswith(home))
                self.assertEqual(saved["settings"]["global"]["provider"]["name"], "ollama")
                # 정하지 않은 폴더가 이 값을 바닥으로 받는다 — 이 문이 있는 이유가 그것이다
                self.assertEqual(saved["settings"]["effective"]["provider"]["name"], "ollama")

    def test_the_dock_carries_the_chip_and_reddens_when_it_is_not_connected(self):
        page = studio.dispatch("GET", "/")[2].decode()
        self.assertIn('id="dock-engine"', page)
        self.assertIn("function renderDockEngine(", page)
        self.assertIn("'/api/provider?root='", page)
        self.assertIn("연결 안 됨", page)
        self.assertIn("forgetEngineCache()", page)  # 엔진을 바꾸면 들고 있던 답은 옛말이다


class TestAMissingEngineBinaryIsAMissingConnection(unittest.TestCase):
    """`claude_cli`는 키가 아니라 **실행 파일**이 있어야 도는 엔진이다 — SDK가 그것을 스폰한다.

    이 검사가 없던 동안 창은 초록으로 "지금 이 엔진을 쓰고 있습니다"라고 적어 놓고,
    보내는 작업마다 자식 프로세스가 죽어서 돌아왔다."""

    def test_no_claude_binary_means_the_provider_is_not_ready(self):
        from asgard import providers

        with mock.patch("asgard.providers.shutil.which", return_value=None):
            resolved = providers.resolve(tempfile.gettempdir(), provider="claude-native")
        self.assertTrue(resolved.missing)
        self.assertTrue(any("claude CLI" in m for m in resolved.missing))

    def test_a_token_in_the_environment_does_not_excuse_the_missing_binary(self):
        """토큰을 export 한 사람도 CLI 없이는 한 줄도 못 돈다 — 키 갈래 안에 두면 안 되는 이유."""
        from asgard import providers

        with (
            mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "x" * 8}),
            mock.patch("asgard.providers.shutil.which", return_value=None),
        ):
            resolved = providers.resolve(tempfile.gettempdir(), provider="claude-native")
        self.assertTrue(any("claude CLI" in m for m in resolved.missing))


if __name__ == "__main__":
    unittest.main()
