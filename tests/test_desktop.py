"""Asgard Desktop API, security boundary, and real configuration wiring."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from asgard.commands import desktop


class DesktopCase(unittest.TestCase):
    def setUp(self):
        with desktop._TASK_LOCK:
            desktop._TASKS.clear()


class TestDispatch(DesktopCase):
    def test_root_is_self_contained_desktop(self):
        status, ctype, body = desktop.dispatch("GET", "/")
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn("Asgard Desktop", page)
        self.assertIn("플러그인과 스킬", page)
        self.assertIn("승인 필요", page)
        self.assertIn(".inspector[hidden]{display:none}", page)
        self.assertNotIn("Studio", page)
        self.assertNotIn('src="http', page)

    def test_logo_health_and_unknown_routes(self):
        status, ctype, body = desktop.dispatch("GET", "/asset/logo")
        self.assertEqual((status, ctype), (200, "image/png"))
        self.assertTrue(body.startswith(b"\x89PNG"))
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


class TestTaskLifecycle(DesktopCase):
    def test_important_task_waits_for_one_time_approval(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(desktop, "_start") as start:
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
        with tempfile.TemporaryDirectory() as root, mock.patch.object(desktop, "_start") as start:
            _, _, body = desktop.create_task({"prompt": "파일을 수정해줘", "permission": "manual"}, root)
            task = json.loads(body)
            status, _, body = desktop.approve_task({"id": task["id"], "decision": "deny"}, root)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["status"], "blocked")
            start.assert_not_called()

    def test_auto_task_uses_existing_asgard_run_command(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(desktop, "_start") as start:
            status, _, body = desktop.create_task(
                {"prompt": "테스트를 실행해줘", "permission": "auto", "provider": "openai"}, root
            )
            task = json.loads(body)
            self.assertEqual(status, 202)
            self.assertEqual(task["status"], "queued")
            with desktop._TASK_LOCK:
                command = desktop._TASKS[task["id"]]["command"]
            self.assertEqual(command[1:4], ["-m", "asgard", "run"])
            self.assertIn("--json", command)
            self.assertEqual(command[-2:], ["--provider", "openai"])
            start.assert_called_once()

    def test_prompt_and_permission_are_validated(self):
        self.assertEqual(desktop.create_task({"prompt": ""}, ".")[0], 400)
        self.assertEqual(desktop.create_task({"prompt": "x", "permission": "forever"}, ".")[0], 400)

    @unittest.skipUnless(hasattr(desktop.signal, "SIGSTOP"), "process pause is POSIX-only")
    def test_running_task_can_pause_resume_and_stop(self):
        process = mock.Mock()
        task = {"id": "live", "status": "running", "created": 1, "updated": 1, "process": process}
        with desktop._TASK_LOCK:
            desktop._TASKS["live"] = task
        self.assertEqual(desktop.pause_task({"id": "live"})[0], 200)
        self.assertEqual(task["status"], "paused")
        process.send_signal.assert_called_with(desktop.signal.SIGSTOP)
        self.assertEqual(desktop.resume_task({"id": "live"})[0], 200)
        self.assertEqual(task["status"], "running")
        process.send_signal.assert_called_with(desktop.signal.SIGCONT)
        self.assertEqual(desktop.stop_task({"id": "live"})[0], 200)
        self.assertEqual(task["status"], "blocked")
        process.terminate.assert_called_once()


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

    def test_global_scope_and_unknown_keys_are_guarded(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"HOME": home}):
                status, _, body = desktop.save_settings(
                    {"scope": "global", "section": "lagom", "values": {"mode": "lite"}}, root
                )
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["saved"].startswith(home))
            self.assertEqual(
                desktop.save_settings(
                    {"scope": "project", "section": "provider", "values": {"secret": "no"}}, root
                )[0],
                400,
            )
            self.assertEqual(
                desktop.save_settings({"scope": "team", "section": "ui", "values": {}}, root)[0], 400
            )


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
            httpd = desktop._bind("127.0.0.1", 0, root)
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
            finally:
                httpd.shutdown()
                httpd.server_close()


class TestNativeShell(unittest.TestCase):
    def test_configured_native_app_is_discovered_first(self):
        with tempfile.TemporaryDirectory() as root:
            app = os.path.join(root, "asgard-desktop")
            open(app, "w").close()
            with mock.patch.dict(os.environ, {"ASGARD_DESKTOP_APP": app}), mock.patch.object(
                desktop.shutil, "which", return_value=None
            ):
                self.assertEqual(desktop._native_candidates()[0], app)

    def test_native_app_receives_only_managed_loopback_context(self):
        with mock.patch.object(desktop, "_native_candidates", return_value=["/app/asgard-desktop"]), mock.patch.object(
            desktop.subprocess, "run"
        ) as run:
            self.assertTrue(desktop._open_native("http://127.0.0.1:8766/", "/project"))
            env = run.call_args.kwargs["env"]
            self.assertEqual(env["ASGARD_DESKTOP_URL"], "http://127.0.0.1:8766/")
            self.assertEqual(env["ASGARD_DESKTOP_ROOT"], "/project")


if __name__ == "__main__":
    unittest.main()
