"""siege — 배차 장부를 사람이 읽는 표면.

실행: uv run pytest tests/test_siege.py

여기서 지키는 계약 둘:
  · 조회는 프로젝트 루트의 장부를 본다 — 하위 디렉터리에서 쳐도 "비어 있다" 는 거짓 보고를
    내지 않는다.
  · 조회는 아무것도 만들지 않는다 — 장부가 없는 곳에서 읽어도 파일이 안 생긴다.

둘은 한 쌍이다. 루트를 못 찾으면 거짓 보고를 하고, 그 자리에 빈 DB 를 남겨 다음 조회까지
계속 속인다. 한쪽만 고치면 나머지 절반이 그대로 남는다.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import orchestration as orc  # noqa: E402
from asgard.commands import siege  # noqa: E402
from asgard.orchestration import store  # noqa: E402


class SiegeBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # `_project_root` 는 `.git` 을 찾아 올라간다 — 그 표식이 있어야 하위 디렉터리 갈래가
        # 실제 사용과 같은 모양이 된다.
        subprocess.run(["git", "init", "-q", self.root], check=True, capture_output=True)
        self.deep = os.path.join(self.root, "src", "asgard")
        os.makedirs(self.deep, exist_ok=True)
        self._cwd = os.getcwd()
        self.addCleanup(lambda: os.chdir(self._cwd))
        # 장부 자리 덮어쓰기(`ASGARD_ORCHESTRATION_DB`)를 끈 채 돈다. 경로 판정 자체가 이
        # 시험의 대상이라 덮어쓰면 잴 것이 없어진다.
        override = os.environ.pop(store.STATE_ENV, None)
        if override is not None:
            self.addCleanup(os.environ.__setitem__, store.STATE_ENV, override)

    def capture(self, call) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            call()
        return buffer.getvalue()


class TestRootResolution(SiegeBase):
    def test_a_subdirectory_reads_the_project_ledger(self):
        run = orc.run_create(self.root, "루트의 Run", quest_id="q-root")
        os.chdir(self.deep)
        payload = json.loads(self.capture(lambda: siege.run_runs(json_out=True)))
        self.assertEqual([row["id"] for row in payload], [run["id"]], "하위 디렉터리에서 장부를 못 찾았다")

    def test_a_subdirectory_does_not_leave_a_ledger_behind(self):
        orc.run_create(self.root, "루트의 Run", quest_id="q-root")
        os.chdir(self.deep)
        siege.run_runs(json_out=True)
        self.assertFalse(os.path.exists(os.path.join(self.deep, ".asgard")), "조회가 하위 디렉터리에 장부를 만들었다")


class TestReadOnly(SiegeBase):
    def test_an_empty_project_reports_empty_without_creating_a_file(self):
        os.chdir(self.root)
        payload = json.loads(self.capture(lambda: siege.run_runs(json_out=True)))
        self.assertEqual(payload, [])
        self.assertFalse(orc.exists(self.root), "읽기 전용 조회가 장부를 만들었다")

    def test_run_show_reports_a_missing_run(self):
        os.chdir(self.root)
        self.assertEqual(siege.run_show("run_nope", json_out=True), 2)
        self.assertFalse(orc.exists(self.root))

    def test_run_show_prints_the_dag(self):
        run = orc.run_create(self.root, "DAG", quest_id="q-dag")
        first = orc.task_create(self.root, run["id"], "선행")
        orc.task_create(self.root, run["id"], "후행", deps=[first["id"]], unit_id="2")
        os.chdir(self.root)
        payload = json.loads(self.capture(lambda: siege.run_show(run["id"], json_out=True)))
        self.assertEqual(payload["run"]["id"], run["id"])
        self.assertEqual({task["status"] for task in payload["tasks"]}, {"ready", "pending"})


if __name__ == "__main__":
    unittest.main()
