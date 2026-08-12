"""메모리 계층의 견딤 — 동시 쓰기·죽은 backend·파생 소실.

여기 모인 테스트는 전부 "정상 경로가 아니라 겹친 경로"를 잰다. 축 넷:

  ① 노른의 link op — 분리된 프로세스에서 도는 손질이 사람의 쓰기와 겹칠 때 페이지가
     안 깨지는가, 그리고 그 뒤 파생 목차가 정본과 어긋나 있지 않은가.
  ② 죽은 backend — 접속이 안 되는 2차 회수가 턴마다 같은 값을 다시 무는가.
  ③ JSON 장부(제안·모순) — 겹친 읽고-고쳐-쓰기에서 레코드가 사라지는가.
  ④ 파생 — 지웠다 다시 만들면 같은 것이 나오는가.

겹침을 재는 테스트는 **락이 없으면 실제로 깨지는 순서**를 강제한다. 스레드 둘을 띄우고
사건으로 만나게 하는 이유가 그것이다: 그냥 두 스레드를 돌리면 락이 없어도 대개 통과하고,
통과하는 테스트는 아무것도 안 지킨다. 시간을 단언하지는 않는다 — 재는 것은 호출 수다.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from asgard import memory, memory_bridge, memory_semantic
from asgard.memory import assemble, backup, contradiction, norn, propose
from asgard.memory.store import _lock
from asgard.project_memory_backends import (
    BackendCapabilities,
    BackendReadiness,
    BackendWriteResult,
    ProjectMemoryBinding,
    ProjectMemoryHit,
    register_backend,
)

# 겹침 테스트에서 "상대가 아직 안 끝났다"를 기다리는 폭. 락이 있으면 상대는 이 시간 내내
# 못 들어오므로 여기서 값을 다 쓰고, 락이 없으면 상대가 그 사이에 끼어들어 결함이 드러난다.
INTERLEAVE_WAIT = 0.4


def _read_text(*parts: str) -> str:
    """파일 내용 — 없으면 빈 문자열. 파생 목차 대조가 존재 여부와 내용을 같이 묻는다."""
    path = os.path.join(*parts)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class MemoryTempHome(unittest.TestCase):
    """HOME과 메모리 홈을 임시 디렉터리로 격리한다 (다른 메모리 스위트와 같은 규율)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-resilience-")
        self._home = os.environ.get("HOME")
        self._mem = os.environ.get(memory.MEMORY_ENV)
        os.environ["HOME"] = self.tmp
        self.d = os.path.join(self.tmp, "memory")
        os.environ[memory.MEMORY_ENV] = self.d
        memory.ensure_home(self.d)

    def tearDown(self):
        for key, value in (("HOME", self._home), (memory.MEMORY_ENV, self._mem)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add(self, text: str, title: str, kind: str = "note") -> str:
        slug, _ = memory.add(text, title=title, kind=kind, d=self.d)
        return slug

    def _body(self, slug: str) -> str:
        page = memory._read(self.d, slug)
        assert page is not None, f"page vanished: {slug}"
        return page[1]

    def _meta(self, slug: str) -> dict:
        page = memory._read(self.d, slug)
        assert page is not None, f"page vanished: {slug}"
        return page[0]

    def _run_interleaved(self, first, second, gate: threading.Event) -> None:
        """`first` 를 돌리다 `gate` 가 열리면 `second` 를 끼워 넣는다 — 둘 다 끝나면 반환.

        `second` 는 gate 가 열린 **뒤에** 시작하므로, 락이 없으면 `first` 의 읽기와 쓰기
        사이에 들어간다. 락이 있으면 `first` 가 끝날 때까지 flock 에 걸려 서 있는다."""
        errors: list[BaseException] = []

        def _guarded(fn):
            def _wrapped():
                try:
                    fn()
                except BaseException as error:  # noqa: BLE001 — 스레드의 실패를 본 스레드로 옮긴다
                    errors.append(error)

            return _wrapped

        rival = threading.Thread(target=_guarded(second))

        def _start_rival_when_the_gate_opens():
            gate.wait(5)
            rival.start()

        starter = threading.Thread(target=_guarded(_start_rival_when_the_gate_opens))
        starter.start()
        _guarded(first)()
        starter.join(10)
        if rival.ident is not None:
            rival.join(10)
        if errors:
            raise errors[0]


class TestNornLinkConcurrency(MemoryTempHome):
    """M6 — link op이 락 없이 페이지를 고치던 자리."""

    def test_link_does_not_overwrite_a_concurrent_page_write(self):
        """link 가 읽은 뒤 남이 쓴 본문을 옛 본문으로 덮지 않는가.

        link 는 frontmatter 만 고치지만 쓰기는 페이지 **전체**다. 락이 없으면 읽은 순간의
        본문을 그대로 다시 써서, 그 사이에 들어온 병합이 통째로 사라진다."""
        left = self._add("릴리스 태그 규칙은 v 접두어를 붙인다", title="릴리스 태그")
        right = self._add("배포 전 확인 목록과 롤백 경로", title="배포 확인")
        donor = self._add("태그를 잘못 달면 되돌리는 절차가 따로 있다", title="태그 되돌리기")

        read_started = threading.Event()
        real_read = norn._read

        def _slow_read(d, slug):
            page = real_read(d, slug)
            if slug == left and not read_started.is_set():
                read_started.set()
                # 상대에게 자리를 내준다. 락이 있으면 상대는 여기 내내 못 들어온다.
                threading.Event().wait(INTERLEAVE_WAIT)
            return page

        with mock.patch.object(norn.apply, "_read", _slow_read):
            self._run_interleaved(
                lambda: norn._add_link(self.d, left, right),
                lambda: memory.merge(donor, left, self.d),
                read_started,
            )

        body = self._body(left)
        self.assertIn("되돌리는 절차", body, "link 가 그 사이에 들어온 병합을 덮어썼다")
        self.assertIn(right, self._meta(left).get("links", ""))

    def test_derived_maps_are_not_stale_after_a_link_run(self):
        """link op 이 있는 런 뒤에 파생 목차가 정본과 어긋나 있지 않은가.

        측정해 보면 `index.md` 는 link 로 안 낡는다 — 카탈로그 한 줄은 제목·kind·요약뿐이라
        links·updated 가 안 들어간다. 실제로 낡는 것은 `maps/` 다 (`vault._rows` 가 links 를
        그대로 적는다). 그래서 둘 다 본다: lint 가 조용한지와, 지도가 지금 정본과 같은지."""
        left = self._add("릴리스 태그 규칙은 v 접두어를 붙인다", title="릴리스 태그")
        right = self._add("배포 전 확인 목록과 롤백 경로", title="배포 확인")

        from asgard.memory.vault import build_maps

        result = norn.apply_norn(self.d, {"ops": [{"op": "link", "a": left, "b": right, "why": "같이 본다"}]})
        self.assertEqual([op["op"] for op in result["applied"]], ["link"])

        self.assertEqual([f["code"] for f in memory.lint(self.d) if f["code"] == "index-stale"], [])
        maps_dir = os.path.join(self.d, "maps")
        stale = [name for name, text in build_maps(self.d).items() if _read_text(maps_dir, name) != text]
        self.assertEqual(stale, [], "link op 뒤 파생 지도가 정본과 어긋난다")


class _CountingBackend:
    """왕복을 세는 최소 backend — 나머지 표면은 프로토콜을 만족시키기 위한 자리채움이다."""

    engine = "resilience-counting"
    api_version = 2
    calls: list[str] = []

    def __init__(self, settings):
        self.project_id = settings.project_id

    def capabilities(self):
        return BackendCapabilities(
            semantic_search=True,
            metadata_roundtrip=True,
            namespace_isolation=True,
            stable_replace=True,
            ownership_binding=True,
        )

    def readiness(self):
        return BackendReadiness("ready", self.engine, self.project_id)

    def retain(self, items):
        return BackendWriteResult(True, accepted_ids=tuple(item.record_id for item in items))

    def write_binding(self, binding):
        return BackendWriteResult(True, accepted_ids=("asgard:project-binding:v1",))

    def namespace_document_count(self):
        return 0

    def close(self):
        return None


class _FlakyBackend(_CountingBackend):
    """접속이 안 되는 backend — read_binding 이 매번 OSError."""

    engine = "resilience-dead"
    calls: list[str] = []

    def read_binding(self):
        type(self).calls.append("read_binding")
        raise OSError("backend is unreachable")

    def recall(self, query, max_results=8):
        type(self).calls.append("recall")
        return []


class _DriftingBackend(_CountingBackend):
    """처음 두 번은 제 신원을, 그 뒤로는 남의 신원을 말하는 backend."""

    engine = "resilience-drift"
    calls: list[str] = []
    reads = 0
    own = ProjectMemoryBinding(
        project_uid="11111111-1111-4111-8111-111111111111",
        binding_id="22222222-2222-4222-8222-222222222222",
        project_id="demo",
    )
    foreign = ProjectMemoryBinding(
        project_uid="33333333-3333-4333-8333-333333333333",
        binding_id="44444444-4444-4444-8444-444444444444",
        project_id="demo",
    )

    def read_binding(self):
        type(self).calls.append("read_binding")
        type(self).reads += 1
        return type(self).own if type(self).reads <= 2 else type(self).foreign

    def recall(self, query, max_results=8):
        type(self).calls.append("recall")
        return [ProjectMemoryHit(text="프로젝트 사실", metadata={}, document_id="doc-1")]


class ProjectRecallBase(unittest.TestCase):
    """2차 회수의 원격 왕복을 재는 자리 — target 마다 건강 상태를 비우고 시작한다."""

    engine = ""

    def setUp(self):
        self.cfg = {
            "engine": self.engine,
            "project_id": "demo",
            "project_uid": "11111111-1111-4111-8111-111111111111",
            "binding_id": "22222222-2222-4222-8222-222222222222",
        }
        memory_bridge.reset_recall_health()

    def tearDown(self):
        memory_bridge.reset_recall_health()


class TestDeadBackendCost(ProjectRecallBase):
    """M4 — 죽은 backend 가 턴마다 같은 값을 다시 물던 자리."""

    engine = _FlakyBackend.engine

    def setUp(self):
        register_backend(_FlakyBackend.engine, _FlakyBackend, replace=True)
        _FlakyBackend.calls = []
        super().setUp()

    def test_consecutive_recalls_stop_paying_the_full_round_trip(self):
        """연속 실패가 이 레인을 잠시 끄는가 — 잰 것은 시간이 아니라 원격 호출 수다."""
        failures = 0
        with mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True):
            for _ in range(5):
                with self.assertRaises(OSError):
                    memory_bridge.server_recall(self.cfg, "질의")
                failures += 1

        self.assertEqual(failures, 5)
        self.assertEqual(
            len(_FlakyBackend.calls),
            memory_bridge.RECALL_BREAKER_FAILURES,
            "차단기가 열린 뒤에도 원격을 계속 두드린다",
        )

    def test_breaker_reports_the_skip_instead_of_pretending_to_have_looked(self):
        """건너뛴 턴은 빈 결과가 아니라 예외다 — 호출측이 fail-open 을 결정하게 둔다."""
        with mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True):
            for _ in range(memory_bridge.RECALL_BREAKER_FAILURES):
                with self.assertRaises(OSError):
                    memory_bridge.server_recall(self.cfg, "질의")
            with self.assertRaises(TimeoutError):
                memory_bridge.server_recall(self.cfg, "질의")


class TestLiveBackendRoundTrips(ProjectRecallBase):
    """M4 — 살아 있는 backend 의 왕복 수와, 그래도 안 깎이는 드리프트 방어."""

    engine = _DriftingBackend.engine

    def setUp(self):
        register_backend(_DriftingBackend.engine, _DriftingBackend, replace=True)
        _DriftingBackend.calls = []
        _DriftingBackend.reads = 0
        super().setUp()

    def test_second_recall_skips_only_the_leading_verification(self):
        """두 번째 회수의 왕복이 셋이 아니라 둘인가 (앞 검증만 캐시가 덮는다)."""
        with mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True):
            memory_bridge.server_recall(self.cfg, "질의")
            first = list(_DriftingBackend.calls)
            with self.assertRaisesRegex(PermissionError, "foreign or drifted"):
                memory_bridge.server_recall(self.cfg, "질의")
            second = _DriftingBackend.calls[len(first) :]

        self.assertEqual(first, ["read_binding", "recall", "read_binding"])
        # 두 번째: 앞 검증이 캐시로 덮이고 뒤 검증만 남는다 — 그리고 그 뒤 검증이 드리프트를 잡는다.
        self.assertEqual(second, ["recall", "read_binding"])

    def test_a_drifted_binding_still_blocks_results_when_the_cache_is_warm(self):
        """캐시가 아무리 신선해도 결과가 검증 없이 모델 경계를 넘지 않는가."""
        with mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True):
            hits = memory_bridge.server_recall(self.cfg, "질의")
            self.assertEqual([hit["document_id"] for hit in hits], ["doc-1"])
            with self.assertRaisesRegex(PermissionError, "foreign or drifted"):
                memory_bridge.server_recall(self.cfg, "질의")
            # 실패는 캐시를 버린다 — 다음 호출은 앞 검증부터 다시 한다.
            before = len(_DriftingBackend.calls)
            with self.assertRaisesRegex(PermissionError, "foreign or drifted"):
                memory_bridge.server_recall(self.cfg, "질의")
            self.assertEqual(_DriftingBackend.calls[before], "read_binding")


class TestLedgerConcurrency(MemoryTempHome):
    """L2 — 디렉터리 락 없이 읽고-고쳐-쓰던 JSON 장부 둘."""

    def test_two_proposals_staged_at_once_both_survive(self):
        save_started = threading.Event()
        real_save = propose._save

        def _slow_save(d, rows):
            if not save_started.is_set():
                save_started.set()
                threading.Event().wait(INTERLEAVE_WAIT)
            real_save(d, rows)

        with mock.patch.object(propose, "_save", _slow_save):
            self._run_interleaved(
                lambda: propose.stage("첫 번째 제안 사실", d=self.d),
                lambda: propose.stage("두 번째 제안 사실", d=self.d),
                save_started,
            )

        texts = sorted(row["text"] for row in propose.pending(self.d))
        self.assertEqual(texts, ["두 번째 제안 사실", "첫 번째 제안 사실"])

    def test_two_contradictions_recorded_at_once_both_survive(self):
        pages = [
            self._add("금요일에는 배포하지 않는다", title="배포 금지 요일"),
            self._add("금요일에도 배포한다", title="배포 허용 요일"),
            self._add("로그는 30일 보관한다", title="로그 보관 30"),
            self._add("로그는 90일 보관한다", title="로그 보관 90"),
        ]
        save_started = threading.Event()
        real_save = contradiction._save

        def _slow_save(d, items):
            if not save_started.is_set():
                save_started.set()
                threading.Event().wait(INTERLEAVE_WAIT)
            real_save(d, items)

        with mock.patch.object(contradiction, "_save", _slow_save):
            self._run_interleaved(
                lambda: contradiction.record([{"a": pages[0], "b": pages[1], "why": "요일이 어긋난다"}], self.d),
                lambda: contradiction.record([{"a": pages[2], "b": pages[3], "why": "보관 기간이 어긋난다"}], self.d),
                save_started,
            )

        keys = sorted(row["key"] for row in contradiction.open_contradictions(self.d))
        self.assertEqual(
            keys,
            sorted(
                [
                    contradiction.contradiction_key(pages[0], pages[1]),
                    contradiction.contradiction_key(pages[2], pages[3]),
                ]
            ),
        )

    def test_the_proposal_queue_file_stays_readable_json(self):
        """겹친 쓰기가 반쯤 쓰인 파일을 남기지 않는가 (원자 쓰기 계약)."""
        propose.stage("장부 형식 확인용 사실", d=self.d)
        with open(os.path.join(self.d, propose.QUEUE_FILE), encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["schema"], propose.SCHEMA)


class TestRestoreSafetyBackup(MemoryTempHome):
    """L4 — 복원의 안전 백업이 복원과 다른 락 구간에 있던 자리."""

    def test_the_safety_backup_is_taken_inside_the_restore_lock(self):
        """안전 백업과 복원 사이에 락이 풀리지 않는가.

        풀리면 그 틈에 들어온 쓰기가 **어느 쪽에도 없다** — 안전 백업은 그 쓰기 전에 떴고,
        복원은 그 쓰기를 덮는다. 되돌릴 자리가 없는 소실이라 계측이 아니라 구조로 막는다."""
        self._add("복원 전에 있던 사실", title="복원 전 사실")
        archive = backup.create(self.d)["name"]
        self._add("복원으로 사라질 사실", title="복원 후 사실")

        held: list[bool] = []
        real_create = backup._create_unlocked

        def _probing_create(d, *, label, keep):
            held.append(self._lock_is_held(d))
            return real_create(d, label=label, keep=keep)

        with mock.patch.object(backup, "_create_unlocked", _probing_create):
            result = backup.restore(archive, self.d)

        self.assertEqual(held, [True], "안전 백업이 복원 락 밖에서 떴다")
        self.assertTrue(result["safety_backup"].endswith(".tar.gz"))
        self.assertEqual(memory._pages(self.d), ["복원-전-사실"])

    @staticmethod
    def _lock_is_held(d: str) -> bool:
        """다른 fd 로 비차단 배타 락을 시도한다 — 실패하면 누군가 쥐고 있다는 뜻.

        같은 프로세스라도 open 이 다르면 flock 은 독립된 것으로 본다 (flock(2)). 그래서
        이 판정은 스레드를 띄우지 않고도 성립한다."""
        try:
            import fcntl
        except ImportError:  # pragma: no cover — posix 전용 판정
            return True
        with open(os.path.join(d, ".lock"), "a+", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
            return False


class TestDerivedRebuild(MemoryTempHome):
    """파생은 지워도 복원된다 — 직전 커밋이 세운 규율(본문 sha 키)이 이 경로에도 서는가."""

    def test_deleting_every_derived_artifact_reproduces_the_same_result(self):
        left = self._add("릴리스 태그 규칙은 v 접두어를 붙인다", title="릴리스 태그")
        right = self._add("배포 전 확인 목록과 롤백 경로", title="배포 확인")
        norn.apply_norn(self.d, {"ops": [{"op": "link", "a": left, "b": right, "why": "같이 본다"}]})

        index_path = os.path.join(self.d, "index.md")
        before_index = _read_text(index_path)
        before_hits = [hit["slug"] for hit in memory.query("릴리스 태그", d=self.d, track=False)]

        os.remove(index_path)
        os.remove(os.path.join(self.d, "state.db"))
        shutil.rmtree(os.path.join(self.d, "maps"), ignore_errors=True)
        memory.reindex(self.d)

        self.assertEqual(_read_text(index_path), before_index)
        self.assertEqual([hit["slug"] for hit in memory.query("릴리스 태그", d=self.d, track=False)], before_hits)
        self.assertEqual([f["code"] for f in memory.lint(self.d) if f["code"] == "index-stale"], [])


class TestAssembleAccounting(unittest.TestCase):
    """L1·L5 — 밀린 후보의 갈래와, 같은 파일 안에서 갈라져 있던 두 판정 방식."""

    lanes = (
        assemble.Lane("personal", "<p>\n", "\n</p>", 200),
        assemble.Lane("project", "<q>\n", "\n</q>", 200),
    )

    def test_stats_separates_redundancy_from_budget_pressure(self):
        fact = "금요일 배포는 릴리스 담당자의 승인을 받아야 한다"
        candidates = [
            assemble.Candidate("personal", fact, rank=0),
            assemble.Candidate("project", fact + " (프로젝트 기록)", rank=0),
            assemble.Candidate("project", "로그는 90일 보관한다", rank=1),
        ]
        redundant: list[assemble.Candidate] = []
        chosen = assemble.select(candidates, self.lanes, budget=4000, redundant=redundant)
        stats = assemble.stats(candidates, chosen, redundant)

        self.assertEqual([c.lane for c in redundant], ["project"])
        self.assertEqual(stats["dropped_redundant"], ["project"])
        self.assertEqual(stats["dropped"], ["project"])

    def test_stats_says_it_does_not_know_when_nobody_counted(self):
        candidates = [assemble.Candidate("personal", "사실 하나", rank=0)]
        chosen = assemble.select(candidates, self.lanes, budget=4000)
        self.assertIsNone(assemble.stats(candidates, chosen)["dropped_redundant"])

    def test_an_exact_duplicate_within_one_lane_is_still_carried_once(self):
        """레인 안의 완전 중복은 `_redundant` 가 안 잡는다 — 고른 것 판정이 값으로 서 있어야 한다."""
        row = assemble.Candidate("personal", "같은 줄", rank=0)
        chosen = assemble.select([row, row], self.lanes, budget=4000)
        self.assertEqual(len(chosen), 1)


class TestEmbedderDownloadLatch(unittest.TestCase):
    """M8 — 캐시 없고 네트워크 막힌 기계가 프로세스마다 같은 내려받기를 다시 시도하던 자리."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-latch-")
        self._home = os.environ.get("HOME")
        self._semantic = os.environ.get("ASGARD_MEMORY_SEMANTIC")
        os.environ["HOME"] = self.tmp
        os.environ["ASGARD_MEMORY_SEMANTIC"] = "local"
        memory_semantic.reset()

    def tearDown(self):
        memory_semantic.reset()
        for key, value in (("HOME", self._home), ("ASGARD_MEMORY_SEMANTIC", self._semantic)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _next_process() -> None:
        """새 프로세스를 흉내낸다 — 프로세스 수명 캐시만 비우고 디스크 래치는 그대로 둔다."""
        memory_semantic._CACHE.update({"loaded": False, "fn": None, "dim": 0, "model": ""})

    def test_a_failed_first_download_is_not_retried_by_the_next_process(self):
        loads: list[str] = []

        def _failing_load(name):
            loads.append(name)
            return None

        with (
            mock.patch.object(memory_semantic, "_load_local", _failing_load),
            mock.patch.object(memory_semantic, "model_cached", return_value=False),
        ):
            self.assertIsNone(memory_semantic.embedder())
            self._next_process()
            self.assertIsNone(memory_semantic.embedder())
            self._next_process()
            self.assertIsNone(memory_semantic.embedder())

        self.assertEqual(len(loads), 1, "래치가 없어 프로세스마다 다시 내려받으려 한다")

    def test_a_failure_with_the_model_already_on_disk_is_retried(self):
        """구별할 수 있는 실패만 기억한다 — 깨진 캐시는 다음 실행에서 다시 시도할 값이 있다."""
        loads: list[str] = []

        def _failing_load(name):
            loads.append(name)
            return None

        with (
            mock.patch.object(memory_semantic, "_load_local", _failing_load),
            mock.patch.object(memory_semantic, "model_cached", return_value=True),
        ):
            self.assertIsNone(memory_semantic.embedder())
            self._next_process()
            self.assertIsNone(memory_semantic.embedder())

        self.assertEqual(len(loads), 2)

    def test_reset_is_the_recovery_handle(self):
        """사람이 네트워크를 고친 뒤 부르는 명령(`warmup`)이 래치를 무르는가."""
        with (
            mock.patch.object(memory_semantic, "_load_local", lambda name: None),
            mock.patch.object(memory_semantic, "model_cached", return_value=False),
        ):
            memory_semantic.embedder()
            self.assertTrue(memory_semantic._download_latched())

        memory_semantic.reset()  # warmup() 이 이것으로 시작한다
        self.assertFalse(memory_semantic._download_latched())

    def test_a_successful_load_clears_the_latch(self):
        with (
            mock.patch.object(memory_semantic, "_load_local", lambda name: None),
            mock.patch.object(memory_semantic, "model_cached", return_value=False),
        ):
            memory_semantic.embedder()
            self.assertTrue(memory_semantic._download_latched())

        self._next_process()
        with (
            mock.patch.object(memory_semantic, "_load_local", lambda name: (lambda text: [1.0], 1, name)),
            mock.patch.object(memory_semantic, "model_cached", return_value=True),
        ):
            self.assertIsNotNone(memory_semantic.embedder())
        self.assertFalse(memory_semantic._download_latched())


class TestLockReentrancyGuard(MemoryTempHome):
    """락을 새로 잡은 경로가 이미 락을 쥔 경로에서 안 불리는가 (flock 은 재진입이 아니다)."""

    def test_the_paths_that_now_take_the_lock_are_reachable_without_deadlock(self):
        left = self._add("첫 사실", title="첫 사실")
        right = self._add("둘째 사실", title="둘째 사실")

        propose.stage("제안 하나", d=self.d)
        self.assertEqual(len(propose.pending(self.d)), 1)
        proposal = propose.pending(self.d)[0]
        self.assertTrue(propose.discard(proposal["id"], self.d))

        contradiction.record([{"a": left, "b": right, "why": "어긋난다"}], self.d)
        key = contradiction.contradiction_key(left, right)
        self.assertIsNotNone(contradiction.acknowledge_contradiction(key, d=self.d))

        norn._add_link(self.d, left, right)
        summary = backup.create(self.d)
        self.assertGreaterEqual(summary["pages"], 2)
        with _lock(self.d):  # 락이 정말로 풀려 있는가 — 위 경로 중 하나라도 안 놓았으면 여기서 멈춘다
            pass


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
