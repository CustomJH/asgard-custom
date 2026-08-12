"""memory 테스트 공용 토대 — temp HOME + ASGARD_MEMORY_DIR 격리로 실사용 ~/.asgard 를 건드리지 않는다."""

import os
import shutil
import tempfile
import unittest

from asgard import memory


def memory_semantic_env() -> str:
    """시맨틱 모드 env 이름 — conftest가 전 테스트를 off로 밀폐하므로 되돌릴 때 쓴다."""
    from asgard import memory_semantic as sem

    return sem._ENV


class MemoryBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-mem-")
        self._home, self._mem = os.environ.get("HOME"), os.environ.get(memory.MEMORY_ENV)
        os.environ["HOME"] = self.tmp  # config.toml(예산) 오염 차단
        self.d = os.path.join(self.tmp, "memory")
        os.environ[memory.MEMORY_ENV] = self.d

    def tearDown(self):
        for k, v in (("HOME", self._home), (memory.MEMORY_ENV, self._mem)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _page(self, slug: str) -> tuple[dict, str]:
        """방금 쓴 페이지를 되읽는다 — 없으면 그 자체가 결함이라 여기서 끊는다."""
        page = memory._read(self.d, slug)
        assert page is not None, f"page not found: {slug}"
        return page
