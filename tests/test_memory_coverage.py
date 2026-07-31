"""시맨틱 파생 인덱스 커버리지 — "켜져 있다"와 "회수에 기여한다"를 가른다.

왜 이 파일이 있는가 (26-07-29 실측). 이 기계의 개인 메모리는 페이지 2장에 vec 0행이었고,
그런데도 `semantic status` · `doctor` 는 "동작 중"이라고 말했다. 두 문장이 다 참이다 —
임베더는 로드되고, 벡터는 없다. `active()` 는 **임베더가 서는가**만 묻기 때문이다. 그 간극에서
사용자는 매 질의마다 모델 로드 비용을 내고 기여는 0을 받는다.

`memory_semantic` 독스트링이 이 층의 존재 이유를 이렇게 적어 뒀다: *"agentmemory 는 로컬
임베딩 기본이라 광고하고 실제론 OFF 였다. 우리는 active() 로 그대로 노출한다."* 정직함이
한 층 얕은 데서 멈춰 있었고, 이 검사가 그 한 층이다.

드리프트는 세 가지다. 셋 다 따로 잰다:
  ① 벡터가 아예 없다 (색인 전에 쓰인 페이지 · 시맨틱을 나중에 켠 설치)
  ② 본문이 바뀌었다 (벡터는 낡은 문장의 것)
  ③ **임베더가 바뀌었다** — 본문 sha 는 그대로다. 차원이 우연히 같으면 코사인이 조용히
     엉뚱한 값을 내므로 sha 만으로는 못 본다.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from asgard import memory
from asgard import memory_semantic as sem


class CoverageCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = os.path.join(self.tmp.name, "mem")
        self._prev = os.environ.get("ASGARD_MEMORY_DIR")
        os.environ["ASGARD_MEMORY_DIR"] = self.d
        memory.ensure_home(self.d)
        self.addCleanup(self._restore)
        self.addCleanup(sem.set_embedder, None)

    def _restore(self) -> None:
        if self._prev is None:
            os.environ.pop("ASGARD_MEMORY_DIR", None)
        else:
            os.environ["ASGARD_MEMORY_DIR"] = self._prev

    def embedder(self, marker: float = 1.0):
        sem.set_embedder(lambda text, m=marker: [m, float(len(text) % 7), 0.5])


class TestCoverageReportsReality(CoverageCase):
    def test_an_empty_wiki_is_covered_by_definition(self):
        self.assertTrue(memory.vec_coverage(self.d)["ok"])

    def test_pages_written_before_the_embedder_existed_are_reported_uncovered(self):
        """가장 조용한 고장 — 시맨틱을 나중에 켠 설치가 정확히 이 상태다."""
        sem.set_embedder(None)
        memory.add("오딘은 uv 로 테스트를 돌린다", kind="feedback", d=self.d)
        self.embedder()
        report = memory.vec_coverage(self.d)
        self.assertEqual((report["pages"], report["fresh"]), (1, 0))
        self.assertEqual(report["coverage"], 0.0)
        self.assertFalse(report["ok"])

    def test_reindex_repairs_it(self):
        sem.set_embedder(None)
        memory.add("오딘은 uv 로 테스트를 돌린다", kind="feedback", d=self.d)
        self.embedder()
        memory.reindex(self.d)
        report = memory.vec_coverage(self.d)
        self.assertEqual(report["fresh"], report["pages"])
        self.assertTrue(report["ok"])

    def test_an_edited_page_makes_its_vector_stale(self):
        self.embedder()
        memory.add("오딘은 uv 로 테스트를 돌린다", kind="feedback", d=self.d)
        slug = memory._pages(self.d)[0]
        page = memory._read(self.d, slug)
        assert page is not None
        meta, _body = page
        memory._atomic_write(memory._page_path(self.d, slug), memory.render_page(meta, "완전히 다른 본문이다 이것은"))
        report = memory.vec_coverage(self.d)
        self.assertEqual(report["stale"], 1)
        self.assertFalse(report["ok"])

    def test_a_swapped_embedder_invalidates_every_vector(self):
        """본문 sha 는 그대로다 — 이 축은 sha 로 못 본다.

        모델을 실제로 갈아끼우는 대신 파생 인덱스에 적힌 모델명을 바꾼다: 그것이 모델을 바꾼
        설치의 **온디스크 상태** 그대로이고, 이 판정이 읽는 것도 바로 그 상태다."""
        self.embedder(1.0)
        memory.add("오딘은 uv 로 테스트를 돌린다", kind="feedback", d=self.d)
        self.assertTrue(memory.vec_coverage(self.d)["ok"])

        conn = memory._db(self.d)
        with conn:
            conn.execute("UPDATE meta SET value = 'old/model-A' WHERE key = 'vec_model'")
        conn.close()

        report = memory.vec_coverage(self.d)
        self.assertTrue(report["model_mismatch"])
        self.assertEqual(report["fresh"], 0)
        self.assertFalse(report["ok"])
        memory.reindex(self.d)
        self.assertTrue(memory.vec_coverage(self.d)["ok"])

    def test_orphan_vectors_are_counted(self):
        self.embedder()
        memory.add("오딘은 uv 로 테스트를 돌린다", kind="feedback", d=self.d)
        slug = memory._pages(self.d)[0]
        os.remove(memory._page_path(self.d, slug))
        report = memory.vec_coverage(self.d)
        self.assertEqual(report["orphan"], 1)
        self.assertFalse(report["ok"])

    def test_coverage_never_loads_the_embedder(self):
        """상태를 재느라 35초짜리 첫 내려받기를 열면 그건 상태 계기가 아니다."""
        sem.set_embedder(None)
        sem.reset()
        memory.add("오딘은 uv 로 테스트를 돌린다", kind="feedback", d=self.d)
        calls: list[str] = []
        original = sem._load_local
        sem._load_local = lambda name: calls.append(name) or None  # ty: ignore[invalid-assignment]
        try:
            memory.vec_coverage(self.d)
        finally:
            sem._load_local = original  # type: ignore[assignment]
        self.assertEqual(calls, [])


class TestFastPathNeverLies(CoverageCase):
    """정상 상태 메모 — 빠른 길은 판정을 바꾸면 안 된다. 바꾸면 그건 최적화가 아니라 결함이다."""

    def _exact(self) -> dict:
        """메모를 지우고 정확한 경로로만 잰 결과."""
        conn = memory._db(self.d)
        with conn:
            conn.execute("DELETE FROM meta WHERE key = 'coverage_ok'")
        conn.close()
        return memory.vec_coverage(self.d)

    def test_the_memo_agrees_with_the_exact_computation(self):
        self.embedder()
        for index in range(5):
            memory.add(f"오딘에 대한 서로 다른 사실 번호 {index} 이고 자립 문장이다", kind="note", d=self.d)
        warm = memory.vec_coverage(self.d)  # 메모를 심는다
        cached = memory.vec_coverage(self.d)  # 빠른 길
        self.assertEqual(cached, warm)
        self.assertEqual(cached, self._exact())

    def test_editing_a_page_invalidates_the_memo(self):
        """지문은 stat 이다 — 본문이 바뀌면 크기나 mtime 이 바뀌어 빠른 길이 닫힌다."""
        self.embedder()
        memory.add("오딘은 uv 로 테스트를 돌린다", kind="feedback", d=self.d)
        self.assertTrue(memory.vec_coverage(self.d)["ok"])
        slug = memory._pages(self.d)[0]
        page = memory._read(self.d, slug)
        assert page is not None
        meta, _body = page
        memory._atomic_write(
            memory._page_path(self.d, slug),
            memory.render_page(meta, "완전히 다른 본문이다 이것은 그리고 훨씬 더 길다 " * 4),
        )
        report = memory.vec_coverage(self.d)
        self.assertFalse(report["ok"])
        self.assertEqual(report["stale"], 1)

    def test_a_failing_state_is_never_memoized(self):
        """고장을 캐시하면 고친 뒤에도 고장이라 말한다 — 이 함수가 고치려던 그 병이다."""
        sem.set_embedder(None)
        memory.add("오딘은 uv 로 테스트를 돌린다", kind="feedback", d=self.d)
        self.embedder()
        self.assertFalse(memory.vec_coverage(self.d)["ok"])
        conn = memory._db(self.d)
        memo = conn.execute("SELECT value FROM meta WHERE key = 'coverage_ok'").fetchone()
        conn.close()
        self.assertIsNone(memo)

    def test_the_memo_does_not_hide_a_swapped_embedder(self):
        """모델 대조는 형상이 아니라 **이 프로세스가 무엇을 로드했는가**라 빠른 길도 다시 본다."""
        self.embedder()
        memory.add("오딘은 uv 로 테스트를 돌린다", kind="feedback", d=self.d)
        self.assertTrue(memory.vec_coverage(self.d)["ok"])  # 메모 심김
        conn = memory._db(self.d)
        with conn:
            conn.execute("UPDATE meta SET value = 'other/model-B' WHERE key = 'vec_model'")
        conn.close()
        report = memory.vec_coverage(self.d)
        self.assertTrue(report["model_mismatch"])
        self.assertFalse(report["ok"])

    def test_the_fast_path_reads_no_page(self):
        """빠른 길의 존재 이유 — 페이지를 한 장도 안 읽는다."""
        self.embedder()
        for index in range(5):
            memory.add(f"오딘에 대한 서로 다른 사실 번호 {index} 이고 자립 문장이다", kind="note", d=self.d)
        memory.vec_coverage(self.d)  # 메모를 심는다
        reads: list[str] = []
        original = memory.index._read
        memory.index._read = lambda directory, slug: reads.append(slug) or original(directory, slug)  # ty: ignore[invalid-assignment]
        try:
            self.assertTrue(memory.vec_coverage(self.d)["ok"])
        finally:
            memory.index._read = original  # type: ignore[assignment]
        self.assertEqual(reads, [])


class TestSurfacesTellTheTruth(CoverageCase):
    def test_lint_reports_the_drift(self):
        sem.set_embedder(None)
        memory.add("오딘은 uv 로 테스트를 돌린다", kind="feedback", d=self.d)
        self.embedder()
        # conftest 가 스위트를 시맨틱 off 로 밀폐한다 (1GB 내려받기 방지). lint 는 꺼진 설치를
        # 고장이라 하지 않으므로, 이 판정을 재려면 이 검사만 켠 상태로 물어야 한다.
        previous = os.environ.get("ASGARD_MEMORY_SEMANTIC")
        os.environ["ASGARD_MEMORY_SEMANTIC"] = "local"
        try:
            codes = {finding["code"] for finding in memory.lint(self.d)}
        finally:
            if previous is None:
                os.environ.pop("ASGARD_MEMORY_SEMANTIC", None)
            else:
                os.environ["ASGARD_MEMORY_SEMANTIC"] = previous
        self.assertIn("vec-stale", codes)

    def test_lint_is_silent_when_semantic_is_off(self):
        """끈 것은 고장이 아니다 — 끄면 어휘 2경로로 도는 것이 정상 동작이다."""
        sem.set_embedder(None)
        previous = os.environ.get("ASGARD_MEMORY_SEMANTIC")
        os.environ["ASGARD_MEMORY_SEMANTIC"] = "off"
        try:
            memory.add("오딘은 uv 로 테스트를 돌린다", kind="feedback", d=self.d)
            codes = {finding["code"] for finding in memory.lint(self.d)}
        finally:
            if previous is None:
                os.environ.pop("ASGARD_MEMORY_SEMANTIC", None)
            else:
                os.environ["ASGARD_MEMORY_SEMANTIC"] = previous
        self.assertNotIn("vec-stale", codes)

    def test_the_semantic_stream_is_dead_exactly_when_coverage_says_so(self):
        """계기와 실사가 같은지 — 이 검사가 F1 의 전부다."""
        sem.set_embedder(None)
        memory.add("오딘은 uv 로 테스트를 돌린다", kind="feedback", d=self.d)
        self.embedder()
        self.assertFalse(memory.vec_coverage(self.d)["ok"])
        hits = memory.query("uv 테스트", k=3, d=self.d, track=False, explain=True)
        self.assertTrue(hits)
        self.assertFalse(any(hit["streams"]["semantic"] for hit in hits))

        memory.reindex(self.d)
        self.assertTrue(memory.vec_coverage(self.d)["ok"])
        hits = memory.query("uv 테스트", k=3, d=self.d, track=False, explain=True)
        self.assertTrue(any(hit["streams"]["semantic"] for hit in hits))


if __name__ == "__main__":
    unittest.main()
