from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from asgard import runs


class RunsTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        patcher = mock.patch.dict(os.environ, {runs.RUNS_ENV: self.state.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def register(self) -> dict:
        return runs.register("demo", "studio", "127.0.0.1", 8766, "http://127.0.0.1:8766")

    def read(self) -> list[dict]:
        with open(runs.runs_path(), encoding="utf-8") as handle:
            return json.load(handle)

    def write(self, rows: list[dict]) -> None:
        with open(runs.runs_path(), "w", encoding="utf-8") as handle:
            json.dump(rows, handle)

    def test_register_listing_heartbeat_and_unregister(self):
        record = self.register()
        self.assertEqual(runs.listing()[0]["state"], "live")
        self.assertTrue(runs.heartbeat(record["id"]))
        self.assertTrue(runs.unregister(record["id"]))
        self.assertEqual(runs.listing(), [])

    def test_dead_pid_is_stale_and_pruned(self):
        self.register()
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        process.wait()
        rows = self.read()
        rows[0]["pid"] = process.pid
        self.write(rows)

        self.assertEqual(runs.listing(prune=False)[0]["state"], "stale")
        self.assertEqual(runs.listing(), [])
        self.assertEqual(self.read(), [])

    def test_reused_pid_with_different_identity_is_not_live(self):
        self.register()
        original = self.read()
        for field in ("proc_start", "proc_cmd"):
            with self.subTest(field):
                rows = [dict(original[0])]
                rows[0][field] += "-different"
                self.write(rows)
                self.assertEqual(runs.listing(prune=False)[0]["state"], "stale")

    def test_indeterminate_record_is_never_pruned(self):
        record = self.register()
        with mock.patch.object(runs, "_proc_identity", return_value=(record["proc_start"], "")):
            self.assertEqual(runs.listing()[0]["state"], "indeterminate")
        self.assertEqual(self.read()[0]["id"], record["id"])

    def test_wrong_token_cannot_unregister(self):
        record = self.register()
        self.assertFalse(runs.unregister(record["id"], "wrong"))
        self.assertEqual(runs.listing()[0]["id"], record["id"])
        self.assertTrue(runs.unregister(record["id"], record["token"]))

    def test_concurrent_register_keeps_valid_json(self):
        errors = []

        def add(index: int) -> None:
            try:
                runs.register(f"agent-{index}", "studio", "127.0.0.1", 9000 + index, f"http://127.0.0.1:{9000 + index}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=add, args=(index,)) for index in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(self.read()), 16)
        self.assertEqual(len(runs.listing()), 16)

    def test_missing_or_corrupt_file_is_fail_open(self):
        self.assertEqual(runs.listing(), [])
        os.makedirs(os.path.dirname(runs.runs_path()), exist_ok=True)
        with open(runs.runs_path(), "w", encoding="utf-8") as handle:
            handle.write("{")
        self.assertEqual(runs.listing(), [])


if __name__ == "__main__":
    unittest.main()
