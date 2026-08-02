#!/usr/bin/env python3
"""SQLite 접속 계약 — 여는 방법은 공용, 손상 정책은 자리마다.

실행: uv run pytest tests/test_sqlite_contract.py

왜 이 파일이 있나 (실측 26-08-03). `sqlite3.connect` 를 부르는 자리가 여섯인데 그중 넷이
파이썬 기본값으로 열고 있었다. 그 기본값은 `journal_mode=delete` · `busy_timeout=5000` 이다.
delete 모드에서는 쓰는 연결이 읽는 연결까지 막으므로, 형제 워커가 6초짜리 쓰기 트랜잭션을
쥐고 있으면 읽으러 온 쪽은 5.16초를 기다린 뒤 `database is locked` 로 죽었다. 넷 다 접속할
때마다 스키마 문장을 돌리기 때문에 죽는 자리는 조회가 아니라 연결을 여는 함수 자신이었고,
넷의 호출자가 전부 fail-open 이라 그 죽음은 예외가 아니라 **빈 결과**로 보였다.

그래서 이 파일이 재는 것은 속도가 아니라 생존이다. 옛 계약을 나란히 놓고 같은 상황에서
그쪽이 실제로 죽는 것을 같이 보인다 — 안 그러면 이 시험은 통과해도 아무것도 안 문다.

병렬 접근은 추측이 아니라 호출자를 따라가서 판정했다:
  state.db      회수(`recall_rows`)가 매 턴 돌고 노출 계수를 쓴다. Dual Thinker 는 그 턴을
                스레드 둘로 돌린다 (`heimdall/trinity.py` 의 `_dual_thinker_turn`).
  episodes.db   조회 넷이 전부 `sync` 부터 부른다 — 읽으러 온 것이 곧 쓰는 것이다. 들어오는
                자리는 state.db 와 같다.
  evicted.db    압축 보관(`huginn._archive`)이 세션마다 돈다. 웨이브(최대 3)와 편대는 세션을
                스레드로 여럿 띄우고 root 가 같다.
  documents.db  `search` 가 `sync` 부터 부르고 그 재구축은 조각 전량 DELETE + INSERT 다.
"""

import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import io_sqlite  # noqa: E402
from asgard.agent import episodes, evicted  # noqa: E402
from asgard.memory import index as memory_index  # noqa: E402
from asgard.orchestration import store as orchestration_store  # noqa: E402
from asgard.project_memory import documents  # noqa: E402
from asgard.studio import db as studio_db  # noqa: E402

_GARBAGE = b"this is not a database, it is 16 bytes of nothing" * 8


class _Homes(unittest.TestCase):
    """네 파생 저장소와 두 참고 저장소를 임시 홈에 격리한다."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="asgard-sqlite-")
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "project")
        os.makedirs(self.root)
        self.memory_home = os.path.join(self._tmp.name, "memory")
        os.makedirs(self.memory_home)
        for key, value in (
            ("HOME", self._tmp.name),
            ("ASGARD_HOME", os.path.join(self._tmp.name, "agent")),
            ("ASGARD_STUDIO_HOME", os.path.join(self._tmp.name, "studio")),
            ("ASGARD_ORCHESTRATION_DB", os.path.join(self._tmp.name, "orchestration.db")),
        ):
            patch = mock.patch.dict(os.environ, {key: value})
            patch.start()
            self.addCleanup(patch.stop)

    # -- 자리별 연결 --------------------------------------------------------

    def memory_conn(self):
        return memory_index._db(self.memory_home)

    def episodes_conn(self):
        return episodes._db(self.root)

    def evicted_conn(self):
        return evicted._db(self.root)

    def documents_conn(self):
        os.makedirs(os.path.dirname(documents._index_path(self.root)), exist_ok=True)
        return documents._db(self.root)

    def derived_openers(self):
        """손상되면 지우고 다시 만드는 자리 넷 — (이름, 연결 함수, 파일 경로)."""
        return (
            ("memory/index.py", self.memory_conn, os.path.join(self.memory_home, "state.db")),
            ("agent/episodes.py", self.episodes_conn, episodes._db_path(self.root)),
            ("agent/evicted.py", self.evicted_conn, evicted.db_path(self.root)),
            ("project_memory/documents.py", self.documents_conn, documents._index_path(self.root)),
        )


class TestConnectionContract(_Homes):
    """여는 방법은 여섯 자리가 같은 답을 내야 한다 — 값이 갈리면 그것은 계약이 아니다."""

    def test_every_derived_store_opens_in_wal_with_the_repo_busy_timeout(self):
        for name, opener, _ in self.derived_openers():
            with self.subTest(name):
                conn = opener()
                try:
                    self.assertEqual(str(conn.execute("PRAGMA journal_mode").fetchone()[0]), "wal")
                    self.assertEqual(int(conn.execute("PRAGMA busy_timeout").fetchone()[0]), io_sqlite.BUSY_TIMEOUT_MS)
                finally:
                    conn.close()

    def test_the_two_reference_stores_still_answer_the_same(self):
        """참고 기준이 움직이면 정본이 셋이 된다 — 그 둘도 같이 잰다."""
        conn = studio_db.connect()
        try:
            self.assertEqual(str(conn.execute("PRAGMA journal_mode").fetchone()[0]), "wal")
            self.assertEqual(int(conn.execute("PRAGMA busy_timeout").fetchone()[0]), io_sqlite.BUSY_TIMEOUT_MS)
        finally:
            conn.close()
        with orchestration_store.connect(self.root, write=True) as orc:
            self.assertEqual(str(orc.execute("PRAGMA journal_mode").fetchone()[0]), "wal")
            self.assertEqual(int(orc.execute("PRAGMA busy_timeout").fetchone()[0]), io_sqlite.BUSY_TIMEOUT_MS)


class _HeldWrite:
    """다른 연결이 쓰기 트랜잭션을 쥔 상태. 나갈 때까지 놓지 않는다.

    쥐는 쪽을 별도 스레드에 두는 이유는 sqlite3 연결이 만든 스레드에서만 쓰이기 때문이다."""

    def __init__(self, opener, path: str):
        self._opener, self._path = opener, path
        self._held, self._release = threading.Event(), threading.Event()
        self._thread = threading.Thread(target=self._hold, daemon=True)

    def _hold(self):
        conn = self._opener(self._path)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS held(x INTEGER)")
            conn.commit()
            conn.execute("BEGIN EXCLUSIVE")
            conn.execute("INSERT INTO held VALUES (1)")
            self._held.set()
            self._release.wait(30)
            conn.rollback()
        finally:
            conn.close()

    def __enter__(self):
        self._thread.start()
        self._held.wait(10)
        return self

    def __exit__(self, *exc):
        self._release.set()
        self._thread.join(30)
        return False


def _bare_connect(path: str) -> sqlite3.Connection:
    """수리 전의 접속 계약 — 파이썬 기본값 그대로. 대기만 짧게 줄여 시험이 5초를 안 쓰게 한다."""
    return sqlite3.connect(path, timeout=0.2)


class TestReadDoesNotDieUnderAWriter(_Homes):
    """다른 연결이 쓰기 트랜잭션을 쥐고 있을 때 읽기가 어떻게 되는가."""

    def test_the_old_contract_dies_where_the_new_one_reads_through(self):
        """같은 상황을 두 계약으로 나란히 친다 — 옛 쪽이 죽어야 이 시험이 무는 것이다."""
        old = os.path.join(self._tmp.name, "old.db")
        with _HeldWrite(_bare_connect, old):
            reader = _bare_connect(old)
            try:
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    reader.execute("SELECT count(*) FROM held").fetchone()
                self.assertIn("locked", str(caught.exception))
            finally:
                reader.close()

        new = os.path.join(self._tmp.name, "new.db")
        with _HeldWrite(io_sqlite.connect, new):
            reader = io_sqlite.connect(new)
            try:
                started = time.perf_counter()
                self.assertEqual(int(reader.execute("SELECT count(*) FROM held").fetchone()[0]), 0)
                # 기다린 것이 아니라 안 막힌 것이다 — WAL 에서 읽기는 쓰기의 뒤에 서지 않는다.
                self.assertLess(time.perf_counter() - started, 0.2)
            finally:
                reader.close()

    def test_journal_mode_is_the_cause_not_the_longer_wait(self):
        """대기를 옛 계약과 같은 0.2초로 줄여도 새 계약은 산다."""
        path = os.path.join(self._tmp.name, "same-wait.db")
        with mock.patch.object(io_sqlite, "BUSY_TIMEOUT_MS", 200):
            with _HeldWrite(io_sqlite.connect, path):
                reader = io_sqlite.connect(path)
                try:
                    self.assertEqual(int(reader.execute("PRAGMA busy_timeout").fetchone()[0]), 200)
                    self.assertEqual(int(reader.execute("SELECT count(*) FROM held").fetchone()[0]), 0)
                finally:
                    reader.close()

    def test_opening_a_derived_store_survives_a_held_writer(self):
        """죽던 자리는 조회가 아니라 연결을 여는 함수였다 — 자리마다 그것을 친다."""
        for name, opener, path in self.derived_openers():
            with self.subTest(name):
                opener().close()  # 스키마를 만들고 WAL 모드를 파일에 기록한다
                with _HeldWrite(io_sqlite.connect, path):
                    conn = opener()
                    conn.close()


class TestConcurrentWritersKeepEveryRecord(_Homes):
    """쓰기끼리는 WAL 에서도 한 번에 하나다 — 그 경합을 대기로 받는가, 유실로 받는가."""

    THREADS, PER_THREAD = 4, 25

    def _race(self, opener, path: str) -> tuple[int, list[str]]:
        setup = opener(path)
        setup.execute("CREATE TABLE IF NOT EXISTS race(tid INTEGER, i INTEGER)")
        setup.commit()
        setup.close()
        errors: list[str] = []

        def writer(tid: int):
            conn = opener(path)
            try:
                for i in range(self.PER_THREAD):
                    try:
                        with conn:
                            conn.execute("INSERT INTO race(tid, i) VALUES (?,?)", (tid, i))
                    except sqlite3.Error as exc:
                        errors.append(f"{type(exc).__name__}: {exc}")
            finally:
                conn.close()

        pool = [threading.Thread(target=writer, args=(tid,)) for tid in range(self.THREADS)]
        for thread in pool:
            thread.start()
        for thread in pool:
            thread.join(60)
        check = opener(path)
        try:
            return int(check.execute("SELECT count(*) FROM race").fetchone()[0]), errors
        finally:
            check.close()

    def test_no_record_is_lost_when_four_threads_write_at_once(self):
        written, errors = self._race(io_sqlite.connect, os.path.join(self._tmp.name, "race.db"))
        self.assertEqual(errors, [])
        self.assertEqual(written, self.THREADS * self.PER_THREAD)

    def test_the_archive_lane_keeps_every_span_under_parallel_sessions(self):
        """실제 표면으로 같은 것을 친다 — `archive` 는 fail-open 이라 죽음이 유실로만 보인다."""

        def archive(tid: int):
            evicted.archive(
                self.root, [("user", f"span {tid}-{i}") for i in range(self.PER_THREAD)], session_id=str(tid)
            )

        pool = [threading.Thread(target=archive, args=(tid,)) for tid in range(self.THREADS)]
        for thread in pool:
            thread.start()
        for thread in pool:
            thread.join(60)
        self.assertEqual(evicted.stats(self.root)["rows"], self.THREADS * self.PER_THREAD)


class TestCorruptionPolicyStaysPerSite(_Homes):
    """접속을 한 곳으로 모아도 손상 정책은 자리마다 그대로여야 한다."""

    def test_derived_stores_discard_and_rebuild(self):
        for name, opener, path in self.derived_openers():
            with self.subTest(name):
                opener().close()
                with open(path, "wb") as handle:
                    handle.write(_GARBAGE)
                conn = opener()  # 예외 없이 열린다 = 지우고 다시 만들었다
                try:
                    self.assertEqual(str(conn.execute("PRAGMA journal_mode").fetchone()[0]), "wal")
                finally:
                    conn.close()

    def test_a_locked_derived_store_is_not_mistaken_for_a_corrupt_one(self):
        """경합은 손상이 아니다 — 기다리다 죽더라도 파일은 그 자리에 있어야 한다."""
        conn = self.memory_conn()
        conn.close()
        path = os.path.join(self.memory_home, "state.db")
        inode = os.stat(path).st_ino
        with _HeldWrite(io_sqlite.connect, path), mock.patch.object(io_sqlite, "BUSY_TIMEOUT_MS", 10):
            with self.assertRaises(sqlite3.OperationalError):
                memory_index.reindex(self.memory_home)
        self.assertEqual(os.stat(path).st_ino, inode)

    def test_the_studio_store_raises_instead_of_rebuilding(self):
        """사람이 적은 원문이라 재생성할 곳이 없다 — 잃은 것을 잃었다고 말한다."""
        studio_db.connect().close()
        with open(studio_db.workspace_path(), "wb") as handle:
            handle.write(_GARBAGE)
        with self.assertRaises(studio_db.StoreError):
            studio_db.connect()

    def test_the_orchestration_store_neither_rebuilds_nor_wraps(self):
        """파생이지만 재생성은 접속 자리가 안 한다 — fail-open 은 호출자에 있다."""
        with orchestration_store.connect(self.root, write=True):
            pass
        with open(orchestration_store.db_path(self.root), "wb") as handle:
            handle.write(_GARBAGE)
        with self.assertRaises(sqlite3.DatabaseError):
            with orchestration_store.connect(self.root, write=True):
                pass


class TestSidecarsGoWithTheFile(_Homes):
    """WAL 을 켜면 저장소가 파일 하나가 아니다."""

    def test_remove_takes_the_wal_and_shm_too(self):
        path = os.path.join(self._tmp.name, "sidecar.db")
        conn = io_sqlite.connect(path)
        conn.execute("CREATE TABLE t(x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
        self.assertTrue(os.path.exists(path + "-wal"))
        conn.close()
        # 닫으면 체크포인트가 곁 파일을 정리하므로, 다시 열어 쥔 채로 지운다 — 지우는 쪽이
        # 곁 파일을 남기는 경우가 바로 이 상태다.
        holder = io_sqlite.connect(path)
        holder.execute("INSERT INTO t VALUES (2)")
        holder.commit()
        self.assertTrue(os.path.exists(path + "-wal"))
        io_sqlite.remove(path)
        holder.close()
        for suffix in ("", "-wal", "-shm"):
            self.assertFalse(os.path.exists(path + suffix), suffix)

    def test_remove_is_silent_about_what_is_not_there(self):
        io_sqlite.remove(os.path.join(self._tmp.name, "never-existed.db"))

    def test_clearing_the_evicted_store_leaves_nothing_behind(self):
        evicted.archive(self.root, [("user", "지워질 구간")])
        path = evicted.db_path(self.root)
        self.assertTrue(os.path.exists(path))
        evicted.clear(self.root)
        for suffix in ("", "-wal", "-shm"):
            self.assertFalse(os.path.exists(path + suffix), suffix)


if __name__ == "__main__":
    unittest.main()
