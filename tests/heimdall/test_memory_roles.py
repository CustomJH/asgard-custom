#!/usr/bin/env python3
"""기억 표면 — 저장 턴·역할별 주입 매트릭스·스냅샷 동결·턴 recap 집계."""

import json
import os
import tempfile
import threading
import unittest

from asgard.agent.session import SessionResult
from heimdall.harness import (
    CLS_DIRECT,
    CLS_WRITE,
    Base,
    FakeHeimdall,
    FakeSession,
    seed_map_canary,
    thinker,
    verifier,
    worker,
)


class TestMemoryWriteTurn(Base):
    """기억 지시 턴 — memory_save 계약 + 실행 증거 봉합.

    26-07-21 실측 봉인: 모델이 ingest 없이 "기억했다" 허위 확답(2회 재현) → 도구 호출 성공이
    유일한 증거이고, 미호출은 원문 결정론 폴백으로 디스크에 반드시 남는다."""

    def _cls_read(self):
        return dict(CLS_WRITE, write_expected=False, criteria=[])

    def _pages(self):
        d = os.path.join(self.root, ".asgard", "memory", "pages")  # HOME=root 격리 — memory_dir 등가
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def test_memory_intent_opens_save_tool_and_records_evidence(self):
        direct = FakeSession(
            SessionResult(text="기억했다.", stop_reason="end_turn"),
            label="direct",
            tool_script=[("memory_save", {"text": "사용자 이름은 썬더오브갓", "kind": "user"})],
        )
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        h.handle("내 이름은 썬더오브갓이야. 기억해줘.")
        self.assertIn("memory_save contract", direct.system)  # 계약 주입
        self.assertTrue(any("썬더오브갓" in f for f in self._pages()))  # 디스크 진실
        self.assertIn("위그드라실에 새겼어요", h.last_response_text)
        self.assertNotIn("원문 폴백", h.last_response_text)

    def test_fabricated_claim_without_tool_falls_back_to_verbatim_ingest(self):
        direct = FakeSession(
            SessionResult(text="세션 메모리에 기록되었습니다.", stop_reason="end_turn"), label="direct"
        )
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        h.handle("내 별명은 번개주먹이야. 기억해줘.")
        self.assertTrue(any("번개주먹" in f for f in self._pages()))
        self.assertIn("원문 폴백", h.last_response_text)
        log = open(os.path.join(self.root, ".asgard", "state", "classify.jsonl")).read()
        self.assertIn("memory_write", log)
        self.assertIn("fallback", log)

    def test_plain_direct_turn_gets_no_memory_tool(self):
        direct = FakeSession(SessionResult(text="답변", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        h.handle("이 함수 뭐하는거야")
        self.assertNotIn("memory_save", direct.injected_handlers)
        self.assertNotIn("memory_save contract", direct.system)
        self.assertEqual(self._pages(), [])


class TestDeliveryMemoryIsolation(Base):
    """개인 메모리 스냅샷은 코디네이터(DIRECT) 전용 (memory v3 P1 — heimdall 주석 계약).
    26-07-15 리뷰: identity에 memory_note가 합쳐지며 딜리버리 자식(freyja/thor/loki)까지
    누출 — 특히 loki는 Verifier 반례 탐색자라 게이트 무결성 훼손."""

    def setUp(self):
        super().setUp()
        from asgard import memory

        os.environ[memory.MEMORY_ENV] = os.path.join(self.root, "mem")
        memory.add("게이트 불신 원칙", title="gate-rule", kind="insight")

    def tearDown(self):
        from asgard import memory

        os.environ.pop(memory.MEMORY_ENV, None)
        super().tearDown()

    def test_identity_split(self):
        h = FakeHeimdall(self.root, [])
        self.assertIn("<memory-context", h.identity)  # 코디네이터 표면엔 주입
        self.assertNotIn("<memory-context", h.delivery_identity)  # 딜리버리 표면은 무주입
        self.assertEqual(h.identity, h.delivery_identity + h.memory_note)

    def test_dispatch_child_system_is_memory_free(self):
        captured = {}

        class Capture(FakeHeimdall):
            def _session(
                self,
                system,
                extra_tools=None,
                handlers=None,
                quiet=False,
                role=None,
                model=None,
                readonly=False,
                rp_override=None,
                cwd=None,
                label="",
            ):
                captured["system"] = system
                return super()._session(system, extra_tools, handlers, quiet, role, model, readonly)

        seed_map_canary(self.root)
        h = Capture(self.root, [worker(root=self.root)])
        h._prepare_map("버튼 라벨 수정")
        h._dispatch_handler("s1", [])({"agent": "freyja", "task": "버튼 라벨 수정", "why": "w"})
        self.assertNotIn("<memory-context", captured["system"])
        self.assertIn("asgard-freyja", captured["system"])  # role 본문은 그대로
        self.assertIn("MAP_CANARY", captured["system"])


class TestFrozenSnapshotIntegration(Base):
    """감사 공백 ①: 생성 후 메모리를 변경해도 기존 Heimdall 인스턴스의 system 바이트는 불변.

    frozen snapshot 계약(캐시 정합성)의 통합 회귀 — 구성요소 테스트가 아니라 실제 인스턴스의
    identity/system 바이트를 직접 대조한다. recall(프롬프트 측)은 라이브가 계약이므로 미대상."""

    def test_memory_mutation_after_construction_keeps_system_bytes_frozen(self):
        from asgard import memory

        old_env = os.environ.get(memory.MEMORY_ENV)
        os.environ[memory.MEMORY_ENV] = os.path.join(self.root, "mem")
        self.addCleanup(
            lambda: (
                os.environ.pop(memory.MEMORY_ENV, None)
                if old_env is None
                else os.environ.__setitem__(memory.MEMORY_ENV, old_env)
            )
        )
        memory.add("동결 전 사실 알파", title="alpha-fact", kind="note")
        turns = [
            FakeSession(SessionResult(text="답1", stop_reason="end_turn"), label="direct"),
            FakeSession(SessionResult(text="답2", stop_reason="end_turn"), label="direct"),
        ]
        h = FakeHeimdall(self.root, turns, cls=CLS_DIRECT)
        identity_before = h.identity
        self.assertIn("alpha-fact", identity_before)  # 스냅샷이 실제로 실렸는지 전제 확인
        h.handle("알파 사실이 뭐였지")
        memory.add("세션 중 추가된 사실 베타", title="beta-fact", kind="note")  # 생성 후 변이
        h.handle("알파 사실이 뭐였지")  # 동일 요청 — request 파생 주입분까지 동일 조건
        self.assertEqual(turns[0].system, turns[1].system)  # system 바이트 불변
        self.assertNotIn("beta-fact", turns[1].system)
        self.assertEqual(h.identity, identity_before)  # 동결 원본 자체도 불변


class TestMemoryRoleMatrix(Base):
    """감사 매트릭스: DIRECT·호출된 Thinker = 스냅샷+회수, standard Worker = 요청 관련 회수만,
    deep Worker/Verifier = 직접 무주입. provider allowlist가 모든 전송 표면을 게이트."""

    def setUp(self):
        super().setUp()
        from asgard import memory

        os.environ[memory.MEMORY_ENV] = os.path.join(self.root, "mem")
        memory.add("Odin 은 pytest -q 스타일 검증을 선호한다", title="pytest-pref", kind="user")
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a", encoding="utf-8") as f:
            f.write("\n/mem/\n")

    def tearDown(self):
        from asgard import memory

        os.environ.pop(memory.MEMORY_ENV, None)
        super().tearDown()

    def test_replan_thinker_injected_worker_verifier_not(self):
        systems = []

        class Cap(FakeHeimdall):
            def _session(
                self,
                system,
                extra_tools=None,
                handlers=None,
                quiet=False,
                role=None,
                model=None,
                readonly=False,
                rp_override=None,
                cwd=None,
                label="",
            ):
                systems.append(system)
                return super()._session(
                    system, extra_tools, handlers, quiet, role, model, readonly, rp_override, cwd, label
                )

        cls = {**CLS_WRITE, "task_class": "deep", "shared": True}
        h = Cap(
            self.root,
            [
                worker({"w1.txt": "bad\n"}, self.root),
                verifier("FAIL", structural=True, sig="bad-plan"),
                thinker("재설계"),
                worker({"w1.txt": "x\n"}, self.root),
                verifier("PASS"),
            ],
            cls=cls,
        )
        h.handle("w1.txt 만들어 — pytest 검증 선호 반영")
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier", "thinker", "worker", "verifier"])
        role_systems = list(zip((s.role for s in h.consumed), systems, strict=True))
        thinker_session = next(s for s in h.consumed if s.label == "thinker")
        self.assertIn("<memory-context", next(system for role, system in role_systems if role == "thinker"))
        self.assertIn("<memory-recall", thinker_session.prompt)
        for role, system in role_systems:
            if role in ("worker", "verifier"):
                self.assertNotIn("<memory-context", system)
        for session in h.consumed:
            if session.role in ("worker", "verifier"):
                self.assertNotIn("<memory-recall", session.prompt)

    def test_direct_prompt_gets_recall(self):
        cls = {**CLS_WRITE, "write_expected": False, "criteria": []}
        s = FakeSession(SessionResult(text="답변", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [s], cls=cls)
        h.handle("pytest 검증 선호가 뭐였지?")
        self.assertIn("<memory-recall", s.prompt)
        self.assertIn("pytest-pref", s.prompt)
        # 답변 소스 배지 원천 — 주입된 회상량이 턴 recap에 집계된다
        self.assertGreater(h.turn_recap.get("recall_chars", 0), 0)

    def test_provider_allowlist_blocks_identity(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write('[memory]\nproviders = ["ollama"]\n')
        h = FakeHeimdall(self.root, [])  # 기본 provider = anthropic — allowlist 밖
        self.assertEqual(h.memory_note, "")
        self.assertNotIn("<memory-context", h.identity)
        self.assertTrue(h._memory_snap)  # 스냅샷 자체는 존재 — 게이트가 막았을 뿐

    def test_thinker_fallback_rebuilds_prompt_for_disallowed_provider(self):
        from asgard.agent.claude_native import UsageCapError

        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[memory]\nproviders = ["ollama"]\n\n[trinity.thinker]\nprovider = "ollama"\nmodel = "placed-t"\n'
        )

        def capped():
            raise UsageCapError("cap")

        failed = FakeSession(SessionResult(text="", stop_reason="error"), effect=capped, label="thinker")
        fallback = thinker("fallback plan")
        cls = {**CLS_WRITE, "task_class": "deep"}
        h = FakeHeimdall(
            self.root,
            [
                worker({"w1.txt": "bad\n"}, self.root),
                verifier("FAIL", structural=True, sig="bad-plan"),
                failed,
                fallback,
                worker({"w1.txt": "x\n"}, self.root),
                verifier("PASS"),
            ],
            cls=cls,
        )

        h.handle("w1.txt 만들어 — pytest 검증 선호 반영")

        self.assertIn("<memory-recall", failed.prompt)
        self.assertNotIn("<memory-recall", fallback.prompt)
        self.assertNotIn("pytest-pref", fallback.prompt)

    def test_thinker_fallback_adds_recall_only_for_allowed_default_provider(self):
        from asgard.agent.claude_native import UsageCapError

        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[memory]\nproviders = ["anthropic"]\n\n[trinity.thinker]\nprovider = "ollama"\nmodel = "placed-t"\n'
        )

        def capped():
            raise UsageCapError("cap")

        failed = FakeSession(SessionResult(text="", stop_reason="error"), effect=capped, label="thinker")
        fallback = thinker("fallback plan")
        cls = {**CLS_WRITE, "task_class": "deep"}
        h = FakeHeimdall(
            self.root,
            [
                worker({"w1.txt": "bad\n"}, self.root),
                verifier("FAIL", structural=True, sig="bad-plan"),
                failed,
                fallback,
                worker({"w1.txt": "x\n"}, self.root),
                verifier("PASS"),
            ],
            cls=cls,
        )

        h.handle("w1.txt 만들어 — pytest 검증 선호 반영")

        self.assertNotIn("<memory-recall", failed.prompt)
        self.assertIn("<memory-recall", fallback.prompt)
        self.assertIn("pytest-pref", fallback.prompt)

    def test_standard_worker_gets_bounded_task_relevant_recall(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "trinity-policy.json"), "w").write(
            json.dumps({"baseline_checks": ["true"]})
        )
        work = worker({"w1.txt": "x\n"}, self.root)
        h = FakeHeimdall(self.root, [work], cls={**CLS_WRITE, "task_class": "standard"})

        h.handle("w1.txt 만들어 — pytest 검증 선호 반영")

        self.assertIn("<memory-recall", work.prompt)
        self.assertIn("pytest-pref", work.prompt)
        self.assertNotIn("<memory-context", work.system)


class TestTurnRecapCollector(unittest.TestCase):
    """턴 recap 집계(_record_tool) — 툴 카운트·수정 파일(view 제외·root 상대화)·커맨드 첫 단어."""

    def test_record_tool_aggregates_tools_files_and_commands(self):
        from types import SimpleNamespace
        from typing import cast

        from asgard.agent.heimdall import core

        # _state_lock/turn_recap/root만 쓰는 최소 대역 — ty invalid-argument-type 내로잉 (45297ac 처방)
        hd = cast(
            core.Heimdall, SimpleNamespace(_state_lock=threading.Lock(), turn_recap=core._new_recap(), root="/repo")
        )
        core.Heimdall._record_tool(hd, "bash", {"command": "pytest -q tests"})
        core.Heimdall._record_tool(hd, "bash", {"command": "pytest -x"})
        core.Heimdall._record_tool(
            hd, "str_replace_based_edit_tool", {"command": "str_replace", "path": "/repo/src/a.py"}
        )
        core.Heimdall._record_tool(hd, "str_replace_based_edit_tool", {"command": "view", "path": "/repo/src/b.py"})
        core.Heimdall._record_tool(hd, "str_replace_based_edit_tool", {"command": "create", "path": "src/c.py"})

        self.assertEqual(hd.turn_recap["tools"]["bash"], 2)
        self.assertEqual(hd.turn_recap["tools"]["str_replace_based_edit_tool"], 3)
        # view 제외·절대경로 상대화·파일별 작업 종류와 횟수
        self.assertEqual(
            hd.turn_recap["files"], {"src/a.py": {"op": "edit", "n": 1}, "src/c.py": {"op": "create", "n": 1}}
        )
        self.assertEqual(hd.turn_recap["cmds"], {"pytest": 2})

    def test_record_recall_accumulates_injected_chars(self):
        from types import SimpleNamespace
        from typing import cast

        from asgard.agent.heimdall import core

        hd = cast(core.Heimdall, SimpleNamespace(_state_lock=threading.Lock(), turn_recap=core._new_recap()))
        core.Heimdall._record_recall(hd, "<memory-recall>alpha</memory-recall>")
        core.Heimdall._record_recall(hd, "")  # 빈 회상 = 미발동 — 무기록
        core.Heimdall._record_recall(hd, "  \n")  # 공백뿐인 회상도 무기록
        core.Heimdall._record_recall(hd, "beta")

        self.assertEqual(hd.turn_recap["recall_chars"], len("<memory-recall>alpha</memory-recall>") + len("beta"))

    def test_memory_write_outcome_records_recap_event(self):
        from types import SimpleNamespace
        from typing import cast

        from asgard.agent.heimdall import core

        with tempfile.TemporaryDirectory() as root:
            # _state_lock/turn_recap/root만 쓰는 최소 대역 — cast는 소비 직전 1회 (ty 내로잉, 45297ac 처방)
            ns = SimpleNamespace(_state_lock=threading.Lock(), turn_recap=core._new_recap(), root=root)
            ns._recap_event = lambda text: core.Heimdall._recap_event(cast(core.Heimdall, ns), text)
            hd = cast(core.Heimdall, ns)

            notice = core.Heimdall._memory_write_outcome(hd, "pytest 선호 기억해", [("created", "pytest-pref")])

        self.assertIn("pytest-pref", notice)
        self.assertEqual(hd.turn_recap["events"], ["carved into Yggdrasil: pytest-pref"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
