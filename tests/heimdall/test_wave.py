#!/usr/bin/env python3
"""Worker wave 병렬 — 단위 파싱·토폴로지·격리 병합·티켓 수명주기."""

import contextlib
import json
import os
import subprocess
import threading
import unittest
from unittest import mock

from asgard.agent.heimdall.todo import files_note
from asgard.agent.session import SessionResult
from asgard.i18n import t
from heimdall.harness import (
    CLS_WRITE,
    DONE,
    PLAN_WITH_UNITS,
    Base,
    FakeHeimdall,
    FakeSession,
    seed_map_canary,
    thinker,
    verifier,
    worker,
)


class TestWaveParallel(Base):
    """Worker wave 병렬 + access list 격리 (Fugu Conductor analog)."""

    @staticmethod
    def isolated_worker(rel: str, body: str):
        session = FakeSession(SessionResult(text="isolated", stop_reason="end_turn", writes=[]), label="worker")

        def effect():
            path = os.path.join(session.cwd, rel)
            os.makedirs(os.path.dirname(path) or session.cwd, exist_ok=True)
            open(path, "w").write(body)

        session.effect = effect
        return session

    def test_wave_isolation_merges_physical_deltas_not_self_reported_writes(self):
        units = [
            {"id": 1, "subtask": "a", "files": ["a.txt", "b.txt"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["a.txt", "b.txt"], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(self.root, [self.isolated_worker("a.txt", "a"), self.isolated_worker("b.txt", "b")])
        h.policy["ticket_runtime"] = {"isolation": True, "max_attempts": 1}
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-isolated", session="wave-isolated")
        h._run_worker_waves("wave-isolated", "task", units, "")
        self.assertEqual(open(os.path.join(self.root, "a.txt")).read(), "a")
        self.assertEqual(open(os.path.join(self.root, "b.txt")).read(), "b")
        events = [json.loads(line) for line in self.quest_log_text().splitlines()]
        changed = {
            event["unit"]: event["changed_files"]
            for event in events
            if event.get("event") == "work" and event.get("unit") in (1, 2)
        }
        self.assertEqual(changed, {1: ["a.txt"], 2: ["b.txt"]})

    def test_isolated_unit_accepts_declared_root_dot_path(self):
        rel = ".github/workflows/ci.yml"
        unit = {"id": 1, "subtask": "workflow", "files": [rel], "criteria": [], "access": []}
        h = FakeHeimdall(self.root, [self.isolated_worker(rel, "name: ci\n")])
        h.policy["ticket_runtime"] = {"isolation": True, "max_attempts": 1}
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-dot-path", session="wave-dot-path")
        h._run_worker_waves("wave-dot-path", "task", [unit], "")
        self.assertEqual(open(os.path.join(self.root, rel)).read(), "name: ci\n")

    def test_disjoint_isolated_units_execute_in_parallel_then_merge(self):
        import threading

        units = [
            {"id": 1, "subtask": "a", "files": ["a.txt"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["b.txt"], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(
            self.root,
            [
                FakeSession(SessionResult(text="a", stop_reason="end_turn")),
                FakeSession(SessionResult(text="b", stop_reason="end_turn")),
            ],
        )
        h.policy["ticket_runtime"] = {"isolation": True, "max_attempts": 1}
        barrier = threading.Barrier(2)
        root_was_clean = []

        def turn(make, prompt, fallback=None, fallback_prompt=None):
            session = make()
            rel = "a.txt" if "Assigned unit 1" in prompt else "b.txt"
            root_was_clean.append(not os.path.exists(os.path.join(self.root, rel)))
            barrier.wait(timeout=5)
            open(os.path.join(session.cwd, rel), "w").write(rel)
            return SessionResult(text=rel, stop_reason="end_turn", writes=[])

        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-real-parallel", session="wave-real-parallel")
        with mock.patch.object(h, "_run_turn", side_effect=turn):
            h._run_worker_waves("wave-real-parallel", "task", units, "")
        self.assertEqual(root_was_clean, [True, True])
        self.assertEqual(open(os.path.join(self.root, "a.txt")).read(), "a.txt")
        self.assertEqual(open(os.path.join(self.root, "b.txt")).read(), "b.txt")

    def test_wave_isolation_rejects_undeclared_actual_writes_without_touching_root(self):
        open(os.path.join(self.root, "shared.txt"), "w").write("user\n")
        units = [
            {"id": 1, "subtask": "a", "files": ["a.txt"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["b.txt"], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(
            self.root,
            [self.isolated_worker("shared.txt", "one\n"), self.isolated_worker("shared.txt", "two\n")],
        )
        h.policy["ticket_runtime"] = {"isolation": True, "max_attempts": 1}
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-overlap", session="wave-overlap")
        with self.assertRaisesRegex(RuntimeError, "scope violation"):
            h._run_worker_waves("wave-overlap", "task", units, "")
        self.assertEqual(open(os.path.join(self.root, "shared.txt")).read(), "user\n")

    def test_parse_units_valid_and_fallbacks(self):
        from asgard.agent.heimdall.planning import _parse_units

        units = _parse_units(PLAN_WITH_UNITS) or []
        self.assertEqual([u["id"] for u in units], [1, 2, 3])
        self.assertIsNone(_parse_units('```json\n{"units":[{"id":1,"subtask":"a"},{"id":"1","subtask":"b"}]}\n```'))
        self.assertIsNone(_parse_units("계획만 있고 블록 없음"))
        self.assertIsNone(_parse_units('```json\n{"units": [{"id": 1, "subtask": "하나뿐"}]}\n```'))  # 단일 = 기존 경로
        self.assertIsNone(_parse_units("```json\n{깨진 json}\n```"))
        self.assertIsNone(
            _parse_units(
                '```json\n{"units":[{"id":1,"subtask":"a","access":[99]},{"id":2,"subtask":"b","access":[]}]}\n```'
            )
        )
        self.assertIsNone(
            _parse_units(
                '```json\n{"units":[{"id":1,"subtask":"a","access":[2]},{"id":2,"subtask":"b","access":[1]}]}\n```'
            )
        )

    def test_plan_waves_topology_and_file_overlap(self):
        from asgard.agent.heimdall.planning import _plan_waves

        units = [
            {"id": 1, "files": ["a.py"], "access": []},
            {"id": 2, "files": ["b.py"], "access": []},
            {"id": 3, "files": ["c.py"], "access": [1, 2]},
        ]
        waves = _plan_waves(units)
        self.assertEqual([[u["id"] for u in w] for w in waves], [[1, 2], [3]])
        overlap = [{"id": 1, "files": ["a.py"], "access": []}, {"id": 2, "files": ["a.py"], "access": []}]
        self.assertEqual([[u["id"] for u in w] for w in _plan_waves(overlap)], [[1], [2]])  # 겹침 직렬화
        aliases = [
            {"id": 1, "files": ["src"], "access": []},
            {"id": 2, "files": ["./src/A.py"], "access": []},
            {"id": 3, "files": ["src/a.py"], "access": []},
        ]
        self.assertEqual([[u["id"] for u in w] for w in _plan_waves(aliases, self.root)], [[1], [2], [3]])
        with self.assertRaisesRegex(ValueError, "dependency graph"):
            _plan_waves([{"id": 1, "files": [], "access": [2]}, {"id": 2, "files": [], "access": [1]}])

    @staticmethod
    def wave_ids(waves: list[list[dict]]) -> list[list[int]]:
        return [[unit["id"] for unit in wave] for wave in waves]

    def test_file_overlap_without_access_splits_both_schedulers(self):
        """access 없이 파일이 겹치는 두 단위 — 여기서 두 일정이 갈라져 있었다.

        배차 장부는 topo_waves 로 한 묶음이라 적고 실행은 _plan_waves 로 두 wave 를 돌렸다.
        겹침을 conflicts 로 넘기면 같은 함수가 같은 답을 낸다.
        """
        from asgard.agent.heimdall.planning import _plan_waves
        from asgard.orchestration import topo_waves

        units = [
            {"id": 1, "subtask": "a", "files": ["shared.py"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["shared.py"], "criteria": [], "access": []},
        ]
        self.assertEqual(self.wave_ids(_plan_waves(units, self.root)), [[1], [2]])
        self.assertEqual(topo_waves(["1", "2"], {}), [["1", "2"]])  # 겹침을 모르면 한 묶음이다
        self.assertEqual(topo_waves(["1", "2"], {}, {"1": {"2"}, "2": {"1"}}), [["1"], ["2"]])

    def test_dependencies_dominate_file_overlap(self):
        """access 가 있으면 겹침 판정보다 순서가 먼저다 — 3 은 1·2 뒤에 한 번만 온다."""
        from asgard.agent.heimdall.planning import _plan_waves

        units = [
            {"id": 1, "files": ["a.py"], "access": []},
            {"id": 2, "files": ["a.py"], "access": []},
            {"id": 3, "files": ["a.py"], "access": [1, 2]},
        ]
        self.assertEqual(self.wave_ids(_plan_waves(units, self.root)), [[1], [2], [3]])

    def test_a_fully_overlapping_ready_set_yields_single_unit_waves(self):
        """준비된 것이 전부 서로 겹쳐도 wave 하나에 하나씩 나오고 끝난다."""
        from asgard.agent.heimdall.planning import _plan_waves

        units = [{"id": uid, "files": ["same.py"], "access": []} for uid in (1, 2, 3)]
        self.assertEqual(self.wave_ids(_plan_waves(units, self.root)), [[1], [2], [3]])

    def test_path_prefix_overlaps_only_at_a_directory_boundary(self):
        from asgard.agent.heimdall.planning import _plan_waves

        nested = [{"id": 1, "files": ["a/b"], "access": []}, {"id": 2, "files": ["a/b/c"], "access": []}]
        self.assertEqual(self.wave_ids(_plan_waves(nested, self.root)), [[1], [2]])
        sibling = [{"id": 1, "files": ["a/b"], "access": []}, {"id": 2, "files": ["a/bc"], "access": []}]
        self.assertEqual(self.wave_ids(_plan_waves(sibling, self.root)), [[1, 2]])

    def test_symlinked_paths_resolve_to_one_key(self):
        from asgard.agent.heimdall.planning import _plan_waves

        with open(os.path.join(self.root, "real.py"), "w") as handle:
            handle.write("x\n")
        os.symlink(os.path.join(self.root, "real.py"), os.path.join(self.root, "link.py"))
        units = [{"id": 1, "files": ["real.py"], "access": []}, {"id": 2, "files": ["link.py"], "access": []}]
        self.assertEqual(self.wave_ids(_plan_waves(units, self.root)), [[1], [2]])

    def test_access_outside_the_unit_list_is_rejected(self):
        """목록에 없는 단위를 가리키는 access — topo_waves 는 무시하지만 여기서는 실행 순서 유실이다."""
        from asgard.agent.heimdall.planning import _plan_waves

        with self.assertRaisesRegex(ValueError, "dependency graph"):
            _plan_waves([{"id": 1, "files": [], "access": [9]}, {"id": 2, "files": [], "access": []}])

    @staticmethod
    def random_graph(rng, count: int) -> list[dict]:
        """앞 번호만 access 로 두어 순환 없는 작은 그래프를 만든다. 목록 순서는 섞는다."""
        paths = ["a.py", "b.py", "pkg", "pkg/m.py", "pkg/n.py", "pkg2/m.py"]
        units = []
        for uid in range(1, count + 1):
            prior = list(range(1, uid))
            units.append(
                {
                    "id": uid,
                    "files": rng.sample(paths, rng.randint(0, 2)),
                    "access": rng.sample(prior, rng.randint(0, len(prior))),
                }
            )
        rng.shuffle(units)
        return units

    def test_random_graphs_yield_dependency_respecting_conflict_free_waves(self):
        """무작위 그래프 200개 — 어느 wave 도 의존을 앞지르지 않고 같은 wave 안에서 파일이 겹치지 않는다."""
        import random

        from asgard.agent.heimdall.planning import _plan_waves

        def clashes(left: list[str], right: list[str]) -> bool:
            return any(a == b or a.startswith(b + "/") or b.startswith(a + "/") for a in left for b in right)

        rng = random.Random(20260802)
        for _ in range(200):
            units = self.random_graph(rng, rng.randint(2, 5))
            waves = _plan_waves(units, self.root)
            self.assertEqual(sorted(u["id"] for wave in waves for u in wave), sorted(u["id"] for u in units))
            done: set = set()
            for wave in waves:
                for index, unit in enumerate(wave):
                    self.assertLessEqual(set(unit["access"]), done)
                    self.assertFalse(any(clashes(unit["files"], other["files"]) for other in wave[index + 1 :]))
                done |= {unit["id"] for unit in wave}

    def test_resume_snapshot_reuses_done_units_and_returns_only_retryable_work(self):
        from asgard.agent.heimdall import ql
        from asgard.agent.heimdall.planning import _resume_snapshot

        ql(
            self.root,
            "open",
            "resume-q",
            "--criteria",
            "resume criteria",
            "--request",
            "original resumable task",
            session="resume-q",
        )
        units = [
            {"id": 1, "subtask": "done", "files": ["a.txt"], "criteria": ["a"], "access": []},
            {"id": 2, "subtask": "pending", "files": ["b.txt"], "criteria": ["b"], "access": [1]},
        ]
        for unit in units:
            ql(
                self.root,
                "append",
                session="resume-q",
                stdin=json.dumps(
                    {
                        "role": "thinker",
                        "event": "ticket",
                        "ticket_status": "todo",
                        "unit": unit["id"],
                        "subtask": unit["subtask"],
                        "changed_files": unit["files"],
                        "criteria": unit["criteria"],
                        "access": unit["access"],
                    }
                ),
            )
        claim = json.loads(ql(self.root, "ticket-claim", "--unit", "1", "--worker", "old", session="resume-q").stdout)
        ql(
            self.root,
            "ticket-finish",
            "--unit",
            "1",
            "--claim-token",
            claim["claim_token"],
            "--status",
            "done",
            session="resume-q",
        )
        snapshot = _resume_snapshot(self.root, "resume-q")
        self.assertEqual(snapshot["completed"], [1])
        self.assertEqual([unit["id"] for unit in snapshot["units"]], [2])
        self.assertEqual(snapshot["units"][0]["access"], [])
        self.assertEqual(snapshot["criteria"], ["resume criteria"])
        self.assertEqual(snapshot["request"], "original resumable task")
        h = FakeHeimdall(self.root, [])
        with mock.patch.object(h, "_trinity", return_value="resumed") as resumed:
            self.assertEqual(h.resume("resume-q"), "resumed")
        call = resumed.call_args
        self.assertEqual(call.args[0], "original resumable task")
        self.assertEqual([unit["id"] for unit in call.kwargs["resume_units"]], [2])
        self.assertEqual(call.kwargs["resume_qid"], "resume-q")
        resumed_cls = call.args[1]
        self.assertFalse(resumed_cls["ambiguous"])
        self.assertFalse(resumed_cls["external_research"])
        self.assertFalse(resumed_cls["shared"])

    def test_wave_execution_isolation_and_unit_events(self):
        seed_map_canary(self.root)
        cls = dict(CLS_WRITE, ambiguous=True, parallel_requested=True)
        seq = [
            FakeSession(SessionResult(text=PLAN_WITH_UNITS, stop_reason="end_turn"), label="thinker"),
            worker({"u1.txt": "1\n"}, self.root, text="unit-result-A"),
            worker({"u2.txt": "2\n"}, self.root, text="unit-result-B"),
            worker({"sum.txt": "s\n"}, self.root, text="unit-result-C"),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=cls)
        out = h.handle("u1, u2 만들고 요약")
        self.assertIn(DONE, out)
        thinker_session = next(session for session in h.consumed if session.label == "thinker")
        verifier_session = next(session for session in h.consumed if session.label == "verifier")
        self.assertIn("MAP_CANARY", thinker_session.system)
        self.assertNotIn("MAP_CANARY", verifier_session.system)
        workers = [s for s in h.consumed if s.label == "worker"]
        self.assertEqual(len(workers), 3)
        self.assertTrue(all("MAP_CANARY" in session.system for session in workers))
        prompts = [w.prompt for w in workers]
        # 단위 1·2 (wave 1) — 격리: 선행 컨텍스트 없음, 서로의 결과 미노출
        wave1 = [p for p in prompts if "Assigned unit 3" not in p]
        self.assertEqual(len(wave1), 2)
        for p in wave1:
            self.assertNotIn("prior unit", p)
            self.assertNotIn("unit-result", p)
        # 단위 3 (wave 2) — access [1]의 결과만 주입
        p3 = next(p for p in prompts if "Assigned unit 3" in p)
        self.assertIn("[prior unit 1 result]", p3)
        self.assertNotIn("[prior unit 2 result]", p3)
        # work 이벤트 단위별 기록 (unit 필드)
        events = [json.loads(ln) for ln in self.quest_log_text().splitlines() if ln.strip()]
        units_logged = [e.get("unit") for e in events if e.get("event") == "work"]
        self.assertEqual(sorted(u for u in units_logged if u is not None), [1, 2, 3])
        ticket_statuses = {
            unit: [e.get("ticket_status") for e in events if e.get("event") == "ticket" and e.get("unit") == unit]
            for unit in (1, 2, 3)
        }
        # 하트비트가 `in_progress`를 한 줄 더 남기므로 정확한 목록을 단언하면 부하에서 깨진다
        # (실측: 다른 pytest와 CPU를 나눠 쓰는 동안 `todo, in_progress, in_progress, done`).
        # 고정할 것은 개수가 아니라 **수명주기의 모양**이다 — 열고, 진행하고, 닫는다.
        for unit in (1, 2, 3):
            with self.subTest(unit=unit):
                seen = ticket_statuses[unit]
                self.assertEqual("todo", seen[0])
                self.assertEqual("done", seen[-1])
                self.assertEqual({"in_progress"}, set(seen[1:-1]))
        from asgard.hooks.quest_log import load_events, load_policy, summarize

        quest_file = next(
            name for name in os.listdir(os.path.join(self.root, ".asgard", "quest")) if name.endswith(".jsonl")
        )
        quest_id = quest_file.removesuffix(".jsonl")
        state = summarize(self.root, quest_id, load_events(self.root, quest_id), load_policy(self.root))
        self.assertEqual(state["ticket_counts"], {"done": 3})
        self.assertEqual([ticket["id"] for ticket in state["tickets"]], [1, 2, 3])
        self.assertTrue(all(ticket["attempt"] == 1 for ticket in state["tickets"]))
        self.assertTrue(all(ticket["claim_token_hash"] for ticket in state["tickets"]))

    def test_fast_sibling_keeps_lease_while_waiting_for_slow_fan_in(self):
        import time

        plan = (
            '```json\n{"units":['
            '{"id":1,"subtask":"fast","files":["u1.txt"],"criteria":["u1"],"access":[]},'
            '{"id":2,"subtask":"slow","files":["u2.txt"],"criteria":["u2"],"access":[]}'
            "]}\n```"
        )
        fast = worker({"u1.txt": "1\n"}, self.root)
        slow = worker({"u2.txt": "2\n"}, self.root)
        slow_effect = slow.effect
        assert slow_effect is not None

        def delayed():
            time.sleep(3.2)
            slow_effect()

        slow.effect = delayed
        h = FakeHeimdall(
            self.root,
            [thinker(plan), fast, slow, verifier("PASS")],
            cls=dict(CLS_WRITE, ambiguous=True, parallel_requested=True),
        )
        h.policy.setdefault("ticket_runtime", {})["lease_seconds"] = 2
        self.assertIn(DONE, h.handle("u1과 u2를 병렬 구현해줘"))

    def test_wave_worker_supplies_default_provider_fallback(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.worker]\nprovider = "ollama"\nmodel = "placed-w"\n'
        )
        fallback_session = worker(text="fallback")
        h = FakeHeimdall(self.root, [fallback_session])
        captured = {}
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-fallback", session="wave-fallback")

        def capture(_make, _prompt, fallback=None, fallback_prompt=None):
            captured["fallback"] = fallback
            return SessionResult(text="primary", stop_reason="end_turn")

        unit = {"id": 1, "subtask": "u1", "files": [], "criteria": [], "access": []}
        with mock.patch.object(h, "_run_turn", side_effect=capture):
            h._run_worker_waves("wave-fallback", "task", [unit], "")

        self.assertTrue(callable(captured["fallback"]))
        session = captured["fallback"]()
        self.assertIs(session.rp_override, h.rp)
        self.assertEqual(session.role, "worker")

    def test_wave_partial_failure_records_success_units_before_raise(self):
        """CUS-247 — 한 단위 fatal 이어도 성공 단위의 완료 처리·writes 기록을 확정한 뒤 전파.
        기존 ex.map은 lazy 예외 재발생으로 성공 단위의 ql append·record_writes까지 끊었다."""
        units = [
            {"id": 1, "subtask": "a", "files": ["ok.txt"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["bad.txt"], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(self.root, [])
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-partial", session="wave-partial")

        def turn(_make, prompt, fallback=None, fallback_prompt=None):
            if "Assigned unit 2" in prompt:
                raise RuntimeError("fatal-unit-2")
            return SessionResult(text="ok", stop_reason="end_turn", writes=["ok.txt"])

        with mock.patch.object(h, "_run_turn", side_effect=turn):
            with self.assertRaises(RuntimeError) as cm:
                h._run_worker_waves("wave-partial", "task", units, "")
        self.assertIn("fatal-unit-2", str(cm.exception))  # fatal = Trinity 중단 의미론 유지
        recorded = json.load(open(os.path.join(self.root, ".asgard", "state", "writes-wave-partial.json")))
        self.assertIn("ok.txt", recorded)  # 성공 단위 쓰기가 게이트 증거로 남는다
        joined = "".join(h.texts)
        # 진행 보드가 단위별로 닫힌다 — 완료 한 줄, 재배정 한 줄, 예산 소진 한 줄 (i18n 앵커)
        self.assertIn(f"✓ 1  a · {files_note(1)}", joined)
        self.assertIn(f"✗ 2  b · {t('todo_unit_retry', e='RuntimeError')}", joined)
        self.assertIn(f"⚠ 2  b · {t('todo_unit_exhausted')}", joined)
        events = [json.loads(ln) for ln in self.quest_log_text().splitlines() if ln.strip()]
        statuses = {
            unit: [e.get("ticket_status") for e in events if e.get("event") == "ticket" and e.get("unit") == unit]
            for unit in (1, 2)
        }
        self.assertEqual(statuses[1], ["todo", "in_progress", "done"])
        self.assertEqual(
            statuses[2],
            ["todo", "in_progress", "failed", "in_progress", "failed", "in_progress", "blocked"],
        )

    def test_capture_failure_joins_all_wave_heartbeats(self):
        units = [
            {"id": 1, "subtask": "a", "files": ["a.txt"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["b.txt"], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(self.root, [])
        h.policy["ticket_runtime"] = {"isolation": True, "max_attempts": 1}
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-capture-error", session="wave-capture-error")
        result = SessionResult(text="ok", stop_reason="end_turn")
        with (
            mock.patch.object(h, "_run_turn", return_value=result),
            mock.patch("asgard.agent.unit_workspace.UnitWorkspace.capture", side_effect=RuntimeError("capture failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "capture failed"):
                h._run_worker_waves("wave-capture-error", "task", units, "")
        self.assertFalse(any(thread.name.startswith("asgard-ticket-") for thread in threading.enumerate()))
        from asgard.hooks.quest_log import fold_tickets, load_events

        tickets = fold_tickets(load_events(self.root, "wave-capture-error"))
        self.assertTrue(all(ticket["status"] not in {"active", "in_progress"} for ticket in tickets.values()))

    def test_completion_error_still_joins_failed_sibling_heartbeat(self):
        units = [
            {"id": 1, "subtask": "success", "files": [], "criteria": [], "access": []},
            {"id": 2, "subtask": "failure", "files": [], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(self.root, [])
        from asgard.agent.heimdall import ql as real_ql

        real_ql(self.root, "open", "wave-completion-error", session="wave-completion-error")

        def turn(_make, prompt, fallback=None, fallback_prompt=None):
            if "Assigned unit 2" in prompt:
                raise RuntimeError("worker failed")
            return SessionResult(text="ok", stop_reason="end_turn")

        def fail_work_append(root, *args, stdin="", session="native"):
            if args and args[0] == "append" and json.loads(stdin or "{}").get("event") == "work":
                return subprocess.CompletedProcess(args, 1, "", "forced work append failure")
            return real_ql(root, *args, stdin=stdin, session=session)

        with (
            mock.patch.object(h, "_run_turn", side_effect=turn),
            mock.patch("asgard.agent.heimdall.waves.ql", side_effect=fail_work_append),
            mock.patch("asgard.agent.heimdall.ticket_lease.ql", side_effect=fail_work_append),
        ):
            with self.assertRaisesRegex(RuntimeError, "forced work append failure"):
                h._run_worker_waves("wave-completion-error", "task", units, "")
        self.assertFalse(any(thread.name.startswith("asgard-ticket-") for thread in threading.enumerate()))
        from asgard.hooks.quest_log import fold_tickets, load_events

        tickets = fold_tickets(load_events(self.root, "wave-completion-error"))
        self.assertTrue(all(ticket["status"] not in {"active", "in_progress"} for ticket in tickets.values()))

    def test_raised_postprocess_errors_settle_every_claim(self):
        scenarios = ("record-writes", "work-append")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                qid = f"wave-raised-{scenario}"
                units = [{"id": 1, "subtask": "success", "files": [], "criteria": [], "access": []}]
                h = FakeHeimdall(self.root, [])
                from asgard.agent.heimdall import ql as real_ql
                from asgard.hooks.quest_log import fold_tickets, load_events

                real_ql(self.root, "open", qid, session=qid)

                def raised_ql(root, *args, stdin="", session="native"):
                    if (
                        scenario == "work-append"
                        and args
                        and args[0] == "append"
                        and json.loads(stdin or "{}").get("event") == "work"
                    ):
                        raise OSError("raised work append")
                    return real_ql(root, *args, stdin=stdin, session=session)

                patches = [
                    mock.patch.object(h, "_run_turn", return_value=SessionResult(text="ok", stop_reason="end_turn")),
                    mock.patch("asgard.agent.heimdall.waves.ql", side_effect=raised_ql),
                    mock.patch("asgard.agent.heimdall.ticket_lease.ql", side_effect=raised_ql),
                ]
                if scenario == "record-writes":
                    patches.append(
                        mock.patch("asgard.agent.heimdall.waves.record_writes", side_effect=OSError("writes failed"))
                    )
                # 인덱스로 조립하면 패치를 하나 더할 때마다 산술이 깨진다 — 전부 적용한다
                with contextlib.ExitStack() as stack:
                    for patch in patches:
                        stack.enter_context(patch)
                    with self.assertRaises(OSError):
                        h._run_worker_waves(qid, "task", units, "")
                self.assertFalse(any(thread.name.startswith("asgard-ticket-") for thread in threading.enumerate()))
                tickets = fold_tickets(load_events(self.root, qid))
                self.assertTrue(all(ticket["status"] not in {"active", "in_progress"} for ticket in tickets.values()))

    def test_workspace_close_error_settles_claims_and_joins_heartbeats(self):
        units = [
            {"id": 1, "subtask": "a", "files": ["a.txt"], "criteria": [], "access": []},
            {"id": 2, "subtask": "b", "files": ["b.txt"], "criteria": [], "access": []},
        ]
        h = FakeHeimdall(self.root, [])
        h.policy["ticket_runtime"] = {"isolation": True, "max_attempts": 1}
        from asgard.agent.heimdall import ql
        from asgard.hooks.quest_log import fold_tickets, load_events

        ql(self.root, "open", "wave-close-error", session="wave-close-error")
        with (
            mock.patch.object(h, "_run_turn", return_value=SessionResult(text="ok", stop_reason="end_turn")),
            mock.patch("asgard.agent.heimdall.waves.ExitStack.close", side_effect=OSError("close failed")),
        ):
            with self.assertRaisesRegex(OSError, "close failed"):
                h._run_worker_waves("wave-close-error", "task", units, "")
        self.assertFalse(any(thread.name.startswith("asgard-ticket-") for thread in threading.enumerate()))
        tickets = fold_tickets(load_events(self.root, "wave-close-error"))
        self.assertTrue(all(ticket["status"] not in {"active", "in_progress"} for ticket in tickets.values()))

    def test_finish_failure_shortens_unsettled_claim_lease(self):
        unit = {"id": 1, "subtask": "a", "files": [], "criteria": [], "access": []}
        h = FakeHeimdall(self.root, [])
        from asgard.agent.heimdall import ql as real_ql

        real_ql(self.root, "open", "wave-finish-error", session="wave-finish-error")
        shortened = []

        def fail_finish(root, *args, stdin="", session="native"):
            if args and args[0] == "ticket-finish":
                return subprocess.CompletedProcess(args, 1, "", "finish unavailable")
            if args and args[0] == "ticket-heartbeat" and args[args.index("--lease-seconds") + 1] == "1":
                shortened.append(args)
            return real_ql(root, *args, stdin=stdin, session=session)

        with (
            mock.patch.object(h, "_run_turn", return_value=SessionResult(text="ok", stop_reason="end_turn")),
            mock.patch("asgard.agent.heimdall.waves.ql", side_effect=fail_finish),
            mock.patch("asgard.agent.heimdall.ticket_lease.ql", side_effect=fail_finish),
        ):
            with self.assertRaisesRegex(RuntimeError, "finish unavailable"):
                h._run_worker_waves("wave-finish-error", "task", [unit], "")
        self.assertTrue(shortened)
        self.assertFalse(any(thread.name.startswith("asgard-ticket-") for thread in threading.enumerate()))

    def test_finish_and_lease_shortening_failures_are_both_surfaced(self):
        unit = {"id": 1, "subtask": "a", "files": [], "criteria": [], "access": []}
        h = FakeHeimdall(self.root, [])
        from asgard.agent.heimdall import ql as real_ql

        real_ql(self.root, "open", "wave-control-error", session="wave-control-error")

        def fail_control(root, *args, stdin="", session="native"):
            if args and args[0] == "ticket-finish":
                return subprocess.CompletedProcess(args, 1, "", "finish unavailable")
            if args and args[0] == "ticket-heartbeat" and args[args.index("--lease-seconds") + 1] == "1":
                return subprocess.CompletedProcess(args, 1, "", "lease shortening rejected")
            return real_ql(root, *args, stdin=stdin, session=session)

        with (
            mock.patch.object(h, "_run_turn", return_value=SessionResult(text="ok", stop_reason="end_turn")),
            mock.patch("asgard.agent.heimdall.waves.ql", side_effect=fail_control),
            mock.patch("asgard.agent.heimdall.ticket_lease.ql", side_effect=fail_control),
        ):
            with self.assertRaises(RuntimeError) as raised:
                h._run_worker_waves("wave-control-error", "task", [unit], "")
        self.assertIn("finish unavailable", str(raised.exception))
        self.assertIn("lease shortening rejected", str(raised.exception))
        self.assertFalse(any(thread.name.startswith("asgard-ticket-") for thread in threading.enumerate()))

    def test_wave_retries_only_failed_ticket_with_new_claim(self):
        unit = {"id": 1, "subtask": "flaky", "files": ["flaky.txt"], "criteria": [], "access": []}
        h = FakeHeimdall(self.root, [])
        from asgard.agent.heimdall import ql

        ql(self.root, "open", "wave-retry", session="wave-retry")
        attempts = 0

        def turn(_make, _prompt, fallback=None, fallback_prompt=None):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient")
            return SessionResult(text="ok", stop_reason="end_turn", writes=["flaky.txt"])

        with mock.patch.object(h, "_run_turn", side_effect=turn):
            h._run_worker_waves("wave-retry", "task", [unit], "")
        self.assertEqual(attempts, 2)
        events = [json.loads(ln) for ln in self.quest_log_text().splitlines() if ln.strip()]
        statuses = [e.get("ticket_status") for e in events if e.get("event") == "ticket" and e.get("unit") == 1]
        self.assertEqual(statuses, ["todo", "in_progress", "failed", "in_progress", "done"])
        from asgard.hooks.quest_log import fold_tickets

        ticket = fold_tickets(events)["1"]
        self.assertEqual(ticket["attempt"], 2)
        self.assertEqual(ticket["status"], "done")

    def test_retry_after_wave_replans_and_preserves_unit_scope(self):
        cls = dict(CLS_WRITE, ambiguous=True, parallel_requested=True)
        seq = [
            FakeSession(SessionResult(text=PLAN_WITH_UNITS, stop_reason="end_turn"), label="thinker"),
            worker({"u1.txt": "1\n"}, self.root),
            worker({"u2.txt": "2\n"}, self.root),
            worker({"sum.txt": "s\n"}, self.root),
            verifier("FAIL", sig="broken"),
            FakeSession(SessionResult(text=PLAN_WITH_UNITS, stop_reason="end_turn"), label="thinker-replan"),
            worker({"u1.txt": "fix1\n"}, self.root),
            worker({"u2.txt": "fix2\n"}, self.root),
            worker({"sum.txt": "fixed\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=cls)
        out = h.handle("u1, u2 만들고 요약")
        self.assertIn(DONE, out)
        replan = h.consumed[5]
        self.assertEqual(replan.label, "thinker-replan")
        self.assertIn("broken", replan.prompt)

    def test_structural_replan_executes_new_units_as_a_wave(self):
        cls = dict(CLS_WRITE, ambiguous=True, parallel_requested=True)
        seq = [
            FakeSession(SessionResult(text=PLAN_WITH_UNITS, stop_reason="end_turn"), label="thinker"),
            worker({"u1.txt": "1\n"}, self.root),
            worker({"u2.txt": "2\n"}, self.root),
            worker({"sum.txt": "bad\n"}, self.root),
            verifier("FAIL", structural=True, sig="bad-plan"),
            FakeSession(SessionResult(text=PLAN_WITH_UNITS, stop_reason="end_turn"), label="thinker-replan"),
            worker({"u1.txt": "1\n"}, self.root),
            worker({"u2.txt": "2\n"}, self.root),
            worker({"sum.txt": "fixed\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=cls)

        out = h.handle("u1, u2 만들고 요약")

        self.assertIn(DONE, out)
        workers = [session for session in h.consumed if session.label == "worker"]
        self.assertEqual(len(workers), 6)
        self.assertEqual(sum("Assigned unit 3" in session.prompt for session in workers), 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
