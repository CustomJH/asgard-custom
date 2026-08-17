#!/usr/bin/env python3
"""네이티브 에이전트 루프 시험 공용 픽스처 — git 초기화된 임시 워킹트리 하나.

시험 본문은 주제별 `test_*.py` 에 있다. 실행: uv run pytest tests/agent
"""

import os
import subprocess
import tempfile
import unittest


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

        def run(*a):
            return subprocess.run(a, cwd=self.root, capture_output=True, check=True)

        run("git", "init", "-q")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        open(os.path.join(self.root, "f.txt"), "w").write("base\n")
        run("git", "add", "-A")
        run("git", "commit", "-qm", "init")

    def tearDown(self):
        self._tmp.cleanup()
