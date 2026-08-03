"""사용자 정책의 형상 우선순위와 닿는 엔진 배치 계약."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import dataclass
from unittest import mock

from asgard.orchestration.policy import DEFAULT, POLICIES, current, decide, set_policy


@dataclass(frozen=True)
class _Engine:
    name: str
    reachable: bool = True
    models: tuple[str, ...] = ()


def _engine(name: str, *, reachable: bool = True) -> _Engine:
    return _Engine(name, reachable, (f"{name}-model",))


class TestPolicySettings(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.root = os.path.join(self.tmp.name, "project")
        os.makedirs(self.root)
        self.environment = mock.patch.dict(os.environ, {"HOME": self.home})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop("ASGARD_HOME", None)
        os.environ.pop("ASGARD_PROFILE", None)

    def test_default_global_project_precedence_and_round_trip(self) -> None:
        self.assertEqual(POLICIES, ("auto", "solo", "graph", "squad", "off"))
        self.assertEqual(current(self.root), (DEFAULT, "built-in default"))

        global_path = set_policy(self.root, "SOLO", "global")
        self.assertEqual(current(self.root), ("solo", "global"))
        project_path = set_policy(self.root, "graph")
        self.assertEqual(current(self.root), ("graph", "project"))
        for path, expected in ((global_path, "solo"), (project_path, "graph")):
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["orchestration"]["policy"], expected)

    def test_invalid_policy_and_scope_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "policy"):
            set_policy(self.root, "native")
        with self.assertRaisesRegex(ValueError, "scope"):
            set_policy(self.root, "auto", "machine")


class TestPolicyDecision(unittest.TestCase):
    def test_auto_keeps_strategy_shape_and_plan_disagreement(self) -> None:
        graph = decide(".", engines=[_engine("a")], policy="auto", planned=True, unit_count=2)
        self.assertEqual(graph.shape, "graph")
        direct = decide(".", engines=[_engine("a")], policy="auto", write_expected=False)
        self.assertEqual((direct.shape, direct.placements), ("direct", ()))

        fallen = decide(
            ".",
            engines=[_engine("a")],
            policy="auto",
            planned=True,
            unit_count=1,
            parallel_requested=True,
        )
        self.assertEqual(fallen.shape, "single")
        self.assertIn("배정 단위", fallen.degraded)

    def test_graph_preference_does_not_invent_planned_units(self) -> None:
        preferred = decide(".", engines=[_engine("a")], policy="graph")
        self.assertEqual(preferred.shape, "graph")

        fallen = decide(".", engines=[_engine("a")], policy="graph", planned=True, unit_count=1)
        self.assertEqual(fallen.shape, "single")
        self.assertIn("1개", fallen.degraded)

    def test_squad_needs_specialists_and_yields_to_plan_units(self) -> None:
        squad = decide(".", engines=[_engine("a")], policy="squad", specialists=["ui", "motion"])
        self.assertEqual((squad.shape, squad.degraded), ("squad", ""))
        unavailable = decide(".", engines=[_engine("a")], policy="squad", specialists=["ui"])
        self.assertEqual(unavailable.shape, "single")
        self.assertIn("2개 미만", unavailable.degraded)
        graph = decide(
            ".",
            engines=[_engine("a")],
            policy="squad",
            planned=True,
            unit_count=2,
            specialists=["ui", "motion"],
        )
        self.assertEqual(graph.shape, "graph")
        self.assertIn("squad 대신 graph", graph.degraded)

    def test_solo_collapses_shape_and_off_has_no_placements(self) -> None:
        engines = [_engine("a"), _engine("b")]
        solo = decide(".", engines=engines, policy="solo", planned=True, unit_count=3)
        self.assertEqual(solo.shape, "single")
        self.assertEqual({placement.engine for placement in solo.placements}, {"a"})
        off = decide(".", engines=engines, policy="off", planned=True, unit_count=3)
        self.assertEqual((off.shape, off.placements, off.degraded), ("direct", (), ""))

    def test_auto_uses_only_reachable_distinct_engines_and_separates_review(self) -> None:
        none = decide(".", engines=[_engine("down", reachable=False)], policy="auto")
        self.assertEqual(none.placements, ())
        self.assertIn("닿는 엔진", none.degraded)

        one = decide(".", engines=[_engine("a")], policy="auto")
        self.assertEqual([placement.engine for placement in one.placements], ["a", "a", "a"])

        two = decide(
            ".",
            engines=[_engine("a"), _engine("down", reachable=False), _engine("a"), _engine("b")],
            policy="auto",
        )
        by_role = {placement.role: placement for placement in two.placements}
        self.assertEqual((by_role["worker"].engine, by_role["verifier"].engine), ("a", "b"))
        self.assertIn("다른 엔진", by_role["verifier"].why)

        three = decide(".", engines=[_engine("a"), _engine("b"), _engine("c")], policy="auto")
        by_role = {placement.role: placement for placement in three.placements}
        self.assertEqual(
            (by_role["thinker"].engine, by_role["worker"].engine, by_role["verifier"].engine),
            ("c", "a", "b"),
        )
        self.assertEqual(by_role["thinker"].model, "c-model")


if __name__ == "__main__":
    unittest.main()
