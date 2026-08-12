#!/usr/bin/env python3
"""thor-lead 물리 fan-out — split 병합과 tournament 패치 회수."""

import json
import os
import unittest

from asgard.agent.session import SessionResult
from heimdall.harness import (
    Base,
    FakeHeimdall,
    FakeSession,
    seed_learned_skill,
    worker,
)


class TestNativeThorSquad(Base):
    """thor-lead 물리 fan-out — split(비중첩 병합)·tournament(패치 회수) 두 계약."""

    def _capture_heimdall(self, sessions):
        calls = []

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
                calls.append(
                    {
                        "role": role,
                        "label": label,
                        "system": system,
                        "tools": extra_tools or [],
                        "handlers": handlers or {},
                    }
                )
                return super()._session(
                    system, extra_tools, handlers, quiet, role, model, readonly, rp_override, cwd, label
                )

        return Capture(self.root, sessions), calls

    def test_lead_gets_bounded_squad_tool_and_children_do_not(self):
        lead = worker(root=self.root, text="lead ready")
        child_a = worker(root=self.root, text="a")
        child_b = worker(root=self.root, text="b")
        h, calls = self._capture_heimdall([lead, child_a, child_b])
        writes = []
        h._dispatch_handler("s1", writes)({"agent": "thor-lead", "task": "대형 백엔드 과업", "why": "다표면 분할"})

        self.assertEqual(calls[0]["role"], "thor-lead")
        self.assertIn("Backend specialist", calls[0]["system"])  # 선언이 아니라 Thor 코어 본문 물리 상속
        self.assertIn("Pre-diagnosis gate", calls[0]["system"])
        self.assertIn("asgard-thor-einherjar", calls[0]["system"])
        self.assertEqual([t["name"] for t in calls[0]["tools"]], ["load_skill", "dispatch_thor_squad"])
        self.assertIn(
            "Einherjar Squad (Team Backend Work)",
            calls[0]["handlers"]["load_skill"]({"name": "asgard-thor-einherjar"}),
        )
        squad = calls[0]["handlers"]["dispatch_thor_squad"]
        result = json.loads(
            squad(
                {
                    "mode": "split",
                    "tasks": [
                        {"id": "api", "task": "핸들러 계층 정리", "scope": ["src/api"], "why": "표면 분리"},
                        {"id": "db", "task": "저장 계층 정리", "scope": ["src/db"], "why": "표면 분리"},
                    ],
                }
            )
        )
        self.assertEqual(result["mode"], "split")
        self.assertEqual({r["id"] for r in result["results"]}, {"api", "db"})
        self.assertEqual(result["failures"], [])
        self.assertEqual([c["role"] for c in calls[1:]], ["thor", "thor"])
        self.assertTrue(all([t["name"] for t in c["tools"]] == ["load_skill"] for c in calls[1:]))
        for c in calls[1:]:
            self.assertNotIn("Einherjar Squad (Team Backend Work)", c["system"])  # 서브에 편대 프로토콜 본문 무주입

    def test_split_rejects_overlapping_scopes_at_declaration(self):
        h = FakeHeimdall(self.root, [])
        with self.assertRaises(ValueError):
            h._thor_squad_handler("s1", [], self.root)(
                {
                    "mode": "split",
                    "tasks": [
                        {"id": "a", "task": "t", "scope": ["src/api"], "why": "w"},
                        {"id": "b", "task": "t", "scope": ["src/api/handlers"], "why": "w"},  # 프리픽스 교차
                    ],
                }
            )

    def test_split_children_cannot_write_outside_scope(self):
        def escaping_child(name: str):
            session = FakeSession(SessionResult(text=name, stop_reason="end_turn", writes=["unauthorized.txt"]))

            def effect():
                open(os.path.join(session.cwd, "unauthorized.txt"), "w").write(name)

            session.effect = effect
            return session

        h = FakeHeimdall(self.root, [escaping_child("a"), escaping_child("b")])
        result = json.loads(
            h._thor_squad_handler("s1", [], self.root)(
                {
                    "mode": "split",
                    "tasks": [
                        {"id": "api", "task": "t", "scope": ["src/api"], "why": "w"},
                        {"id": "db", "task": "t", "scope": ["src/db"], "why": "w"},
                    ],
                }
            )
        )
        self.assertEqual(result["results"], [])
        self.assertEqual({failure["id"] for failure in result["failures"]}, {"api", "db"})
        self.assertTrue(all("scope violation" in failure["error"] for failure in result["failures"]))
        self.assertFalse(os.path.exists(os.path.join(self.root, "unauthorized.txt")))

    def test_split_merges_scoped_writes(self):
        def scoped_child():
            session = FakeSession(SessionResult(text="scoped", stop_reason="end_turn"))

            def effect():
                unit = "api" if "Squad unit api" in session.prompt else "db"
                rel = f"src/{unit}/service.py"
                session.result.writes = [rel]
                path = os.path.join(session.cwd, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w").write(f"# {unit}\n")

            session.effect = effect
            return session

        h = FakeHeimdall(self.root, [scoped_child(), scoped_child()])
        writes = []
        result = json.loads(
            h._thor_squad_handler("s1", writes, self.root)(
                {
                    "mode": "split",
                    "tasks": [
                        {"id": "api", "task": "t", "scope": ["src/api"], "why": "w"},
                        {"id": "db", "task": "t", "scope": ["src/db"], "why": "w"},
                    ],
                }
            )
        )
        self.assertEqual(result["failures"], [])
        self.assertEqual(set(writes), {"src/api/service.py", "src/db/service.py"})
        for unit in ("api", "db"):
            self.assertIn(unit, open(os.path.join(self.root, f"src/{unit}/service.py")).read())

    def test_squad_children_discover_learned_skills_and_load_on_demand(self):
        seed_learned_skill(self.root, "migration-lesson", triggers="마이그레이션", agent="thor")
        children = [
            FakeSession(SessionResult(text="a", stop_reason="end_turn")),
            FakeSession(SessionResult(text="b", stop_reason="end_turn")),
        ]
        h = FakeHeimdall(self.root, children)
        result = json.loads(
            h._thor_squad_handler("s1", [], self.root)(
                {
                    "mode": "split",
                    "tasks": [
                        {"id": "api", "task": "api 마이그레이션", "scope": ["src/api"], "why": "w"},
                        {"id": "db", "task": "db 마이그레이션", "scope": ["src/db"], "why": "w"},
                    ],
                }
            )
        )

        self.assertEqual(result["failures"], [])
        for child in h.consumed:
            self.assertIn("migration-lesson", child.system)
            self.assertNotIn("migration-lesson 본문", child.system)
            self.assertIn(
                "migration-lesson 본문",
                child.injected_handlers["load_skill"]({"name": "migration-lesson"}),
            )

    def test_tournament_collects_patches_without_applying(self):
        def variant_child(marker: str):
            session = FakeSession(SessionResult(text=marker, stop_reason="end_turn"))

            def effect():
                rel = "src/core/fix.py"
                session.result.writes = [rel]
                path = os.path.join(session.cwd, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w").write(f"# variant {marker}\n")

            session.effect = effect
            return session

        h = FakeHeimdall(self.root, [variant_child("v1"), variant_child("v2")])
        writes = []
        result = json.loads(
            h._thor_squad_handler("s1", writes, self.root)(
                {
                    "mode": "tournament",
                    "tasks": [
                        # 토너먼트는 같은 난제 — scope 중첩이 허용된다
                        {"id": "v1", "task": "t", "scope": ["src/core"], "why": "접근 A"},
                        {"id": "v2", "task": "t", "scope": ["src/core"], "why": "접근 B"},
                    ],
                }
            )
        )
        self.assertEqual(result["mode"], "tournament")
        self.assertEqual(result["failures"], [])
        self.assertIn("NOT applied to the mainline", result["note"])
        # 본류에는 미적용 — 패치 파일만 회수된다 (승자 적용·검증은 대장 몫)
        self.assertFalse(os.path.exists(os.path.join(self.root, "src/core/fix.py")))
        for vid in ("v1", "v2"):
            rel = f"deliverables/thor-tournament/{vid}.patch"
            self.assertIn(rel, writes)
            body = open(os.path.join(self.root, rel), "rb").read().decode("utf-8", "replace")
            self.assertIn("src/core/fix.py", body)


if __name__ == "__main__":
    unittest.main(verbosity=1)
