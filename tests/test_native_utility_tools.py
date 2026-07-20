from __future__ import annotations

import shlex
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from asgard.agent import tools
from asgard.agent.tool_kernel import ToolContext, build_session_registry, execute_tool


class NativeUtilityToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_worker_gets_new_tools_but_readonly_role_cannot_patch(self):
        registry = build_session_registry()
        try:
            worker = ToolContext(root=self.root, role="worker")
            thinker = ToolContext(root=self.root, role="thinker", readonly=True)
            self.assertTrue({"apply_patch", "process", "web_fetch"} <= {spec.name for spec in registry.available_specs(worker)})
            self.assertNotIn("apply_patch", {spec.name for spec in registry.available_specs(thinker)})
            self.assertIn("process", {spec.name for spec in registry.available_specs(thinker)})
        finally:
            registry.close()

    def test_apply_patch_validates_then_changes_multiple_files(self):
        Path(self.root, "keep.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        Path(self.root, "remove.txt").write_text("old\n", encoding="utf-8")
        registry = build_session_registry()
        context = ToolContext(root=self.root, role="worker")
        patch = """*** Begin Patch
*** Update File: keep.txt
@@
 alpha
-beta
+gamma
*** Add File: added.txt
+new
*** Delete File: remove.txt
*** End Patch"""
        try:
            result = execute_tool(registry, "apply_patch", {"patch_text": patch}, context)
        finally:
            registry.close()
        self.assertFalse(result.is_error, result.content)
        self.assertEqual(Path(self.root, "keep.txt").read_text(encoding="utf-8"), "alpha\ngamma\n")
        self.assertEqual(Path(self.root, "added.txt").read_text(encoding="utf-8"), "new\n")
        self.assertFalse(Path(self.root, "remove.txt").exists())
        self.assertEqual(context.writes, ["keep.txt", "added.txt", "remove.txt"])

    def test_apply_patch_failure_leaves_every_file_unchanged(self):
        original = Path(self.root, "existing.txt")
        original.write_text("actual\n", encoding="utf-8")
        registry = build_session_registry()
        patch = """*** Begin Patch
*** Add File: should-not-exist.txt
+new
*** Update File: existing.txt
@@
-missing
+changed
*** End Patch"""
        try:
            result = execute_tool(
                registry,
                "apply_patch",
                {"patch_text": patch},
                ToolContext(root=self.root, role="worker"),
            )
        finally:
            registry.close()
        self.assertTrue(result.is_error)
        self.assertEqual(original.read_text(encoding="utf-8"), "actual\n")
        self.assertFalse(Path(self.root, "should-not-exist.txt").exists())

    def test_background_process_can_be_polled_and_is_closed_with_registry(self):
        registry = build_session_registry()
        context = ToolContext(root=self.root, role="worker")
        command = "python -c " + shlex.quote('import time; print("ready", flush=True); time.sleep(30)')
        started = execute_tool(registry, "process", {"action": "start", "command": command}, context)
        self.assertFalse(started.is_error, started.content)
        process_id = started.content.split(" · ", 1)[0]
        polled = execute_tool(
            registry,
            "process",
            {"action": "poll", "process_id": process_id, "wait_seconds": 1},
            context,
        )
        self.assertIn("ready", polled.content)
        registry.close()
        time.sleep(0.05)
        stopped = execute_tool(registry, "process", {"action": "poll", "process_id": process_id}, context)
        self.assertIn("exited(", stopped.content)

    def test_web_fetch_blocks_local_and_private_networks(self):
        for url in ("http://localhost/", "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/"):
            with self.subTest(url=url), self.assertRaises(tools.ToolError):
                tools.run_web_fetch(self.root, {"url": url})

    def test_web_fetch_revalidates_redirect_targets(self):
        class Redirect:
            status_code = 302
            headers = {"location": "http://127.0.0.1/private"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        class Client:
            calls = 0

            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def stream(self, *_args):
                self.calls += 1
                return Redirect()

        public_dns = [(2, 1, 6, "", ("93.184.216.34", 80))]
        with (
            patch("socket.getaddrinfo", return_value=public_dns),
            patch("httpx.Client", Client),
            self.assertRaises(tools.ToolError),
        ):
            tools.run_web_fetch(self.root, {"url": "http://example.test/redirect"})


if __name__ == "__main__":
    unittest.main()
