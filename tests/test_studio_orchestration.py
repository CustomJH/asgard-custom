"""스튜디오 오케스트레이션 패널 — 재료의 왕복과 사슬 준수.

여기서 지키는 것은 네 가지다.
  · 패널 재료는 두 갈래(정책·엔진 준비 상태)가 한 왕복으로 오고, 못 읽은 갈래는 못 읽었다고 적힌다.
  · 화면 최초 렌더는 캐시만 읽는다 — GET 이 probe 를 돌면 설정 화면이 엔진 수만큼 느려진다.
  · 정책 저장과 강제 재점검이 실제로 돌아온다 — 판정은 엔진의 것 그대로다(400·503 도 판정이다).
  · 재료 모듈은 사슬(STUDIO_CHAIN)에서 routes 아래에 산다 — 위를 부르면 순환이다.
"""

import ast
import importlib.util
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import asgard
from asgard import orchestration as orch_pkg
from asgard.commands import studio
from asgard.commands.studio import orchestration as studio_orch

_MODULE_PATH = os.path.join(os.path.dirname(studio_orch.__file__), "orchestration.py")
_HTML_PATH = os.path.join(os.path.dirname(os.path.dirname(studio_orch.__file__)), "..", "assets", "studio.html")

_ENGINE = SimpleNamespace(
    name="anthropic",
    display="Anthropic",
    configured=True,
    reachable=True,
    detail="카탈로그 응답",
    models=("claude-fable-5",),
    checked=1000.0,
)


def _engines_stub(calls):
    """호출을 세는 엔진 판정기 — cached 와 probe 가 각각 언제 도는지가 이 층의 계약이다."""

    def cached(root):
        calls["cached"] += 1
        return [_ENGINE]

    def probe(root, names=(), timeout=6.0, force=False, now=None):
        calls["probe"] += 1
        calls["force"] = force
        return [_ENGINE]

    return SimpleNamespace(cached=cached, probe=probe)


def _policy_stub(store):
    """공용 계약(ORCH_SPEC)의 시그니처 그대로 — current/set_policy/POLICIES/DEFAULT."""

    def current(root):
        return store.get("policy", "auto"), store.get("source", "built-in default")

    def set_policy(root, value, scope="project"):
        if value not in ("auto", "solo", "graph", "squad", "off"):
            raise ValueError(f"모르는 정책: {value}")
        store["policy"] = value
        store["source"] = "global" if scope == "global" else "project"
        return os.path.join(root, f"asgard-setting-{scope}.json")

    return SimpleNamespace(
        POLICIES=("auto", "solo", "graph", "squad", "off"), DEFAULT="auto", current=current, set_policy=set_policy
    )


class PanelCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="asgard-orch-panel-")


class TestPanelState(PanelCase):
    def test_the_panel_carries_both_branches_in_one_trip(self):
        """한 왕복에 두 갈래 — 갈래마다 GET 을 따로 돌면 창이 두 번 깜빡인다."""
        status, _, body = studio.dispatch("GET", "/api/orchestration", {}, self.root)

        self.assertEqual(status, 200)
        data = json.loads(body)
        for key in ("policy", "engines", "missing", "labels"):
            self.assertIn(key, data)
        # 정책의 사람 뜻은 재료 모듈의 것 그대로다 — 표면이 다시 쓰면 창마다 다르게 설명된다
        self.assertEqual(data["labels"], studio_orch.POLICY_LABEL)

    def test_every_policy_choice_has_a_meaning(self):
        """이름만 있는 목록은 고르는 자리가 아니다 — 계약의 다섯 정책 전부에 뜻이 있어야 한다."""
        self.assertEqual(set(studio_orch.POLICY_LABEL), {"auto", "solo", "graph", "squad", "off"})

    def test_missing_engines_are_reported_not_hidden(self):
        """엔진(engines·policy)이 없으면 None + missing — "없음"과 "못 읽었음"은 다른 화면이다."""
        with mock.patch.object(asgard, "engines", None, create=True), mock.patch.object(
            orch_pkg, "policy", None, create=True
        ):
            data = studio_orch.panel_state(self.root)

        self.assertIsNone(data["policy"])
        self.assertIsNone(data["engines"])
        self.assertEqual(sorted(data["missing"]), ["engines", "policy"])

    def test_present_engines_fill_the_panel_from_cache(self):
        """판정기가 있으면 그 판정이 그대로 재료가 된다 — 최초 렌더는 cached 만 읽는다."""
        calls = {"cached": 0, "probe": 0}
        store = {}
        with mock.patch.object(asgard, "engines", _engines_stub(calls), create=True), mock.patch.object(
            orch_pkg, "policy", _policy_stub(store), create=True
        ):
            data = studio_orch.panel_state(self.root)

        self.assertEqual(calls, {"cached": 1, "probe": 0})
        self.assertEqual(data["missing"], [])
        self.assertEqual(data["policy"]["current"], "auto")
        self.assertEqual(data["policy"]["source"], "built-in default")
        self.assertEqual(data["policy"]["choices"], ["auto", "solo", "graph", "squad", "off"])
        row = data["engines"][0]
        self.assertEqual(
            (row["name"], row["reachable"], row["detail"], row["models"]),
            ("anthropic", True, "카탈로그 응답", ["claude-fable-5"]),
        )

    def test_a_broken_gauge_fails_open(self):
        """판정기 하나가 죽어도 나머지 갈래는 나간다 — 이 칸은 관문이 아니라 계기다."""

        def boom(root):
            raise RuntimeError("죽은 판정기")

        store = {}
        with mock.patch.object(asgard, "engines", SimpleNamespace(cached=boom), create=True), mock.patch.object(
            orch_pkg, "policy", _policy_stub(store), create=True
        ):
            data = studio_orch.panel_state(self.root)

        self.assertIsNone(data["engines"])
        self.assertIn("engines", data["missing"])
        self.assertIsNotNone(data["policy"])


class TestPolicyRoundTrip(PanelCase):
    def test_a_save_persists_and_returns_fresh_state(self):
        """저장 → 응답에 실려 온 재료가 이미 그 값이다 — 창이 GET 을 한 번 더 돌지 않는다."""
        store = {}
        with mock.patch.object(orch_pkg, "policy", _policy_stub(store), create=True):
            status, _, body = studio.dispatch_post(
                "/api/orchestration/policy", {"policy": "solo", "scope": "project"}, self.root
            )

            self.assertEqual(status, 200)
            payload = json.loads(body)
            self.assertTrue(payload["saved"].endswith("asgard-setting-project.json"))
            self.assertEqual(payload["state"]["policy"]["current"], "solo")
            self.assertEqual(payload["state"]["policy"]["source"], "project")
        self.assertEqual(store["policy"], "solo")

    def test_bad_payloads_are_refused(self):
        """판정은 엔진의 것 그대로다 — 모르는 정책은 400, 빈 이름·틀린 scope 는 문 앞에서 400."""
        store = {}
        with mock.patch.object(orch_pkg, "policy", _policy_stub(store), create=True):
            self.assertEqual(studio.dispatch_post("/api/orchestration/policy", {"policy": "warp"}, self.root)[0], 400)
        self.assertEqual(studio.dispatch_post("/api/orchestration/policy", {}, self.root)[0], 400)
        self.assertEqual(
            studio.dispatch_post("/api/orchestration/policy", {"policy": "solo", "scope": "galaxy"}, self.root)[0], 400
        )

    def test_saving_without_the_engine_is_a_503_not_a_silent_success(self):
        """엔진이 없는데 저장했다고 말하면 설정이 거짓이 된다 — 못 적은 것은 못 적었다고 답한다."""
        with mock.patch.object(orch_pkg, "policy", None, create=True):
            status, _, body = studio.dispatch_post("/api/orchestration/policy", {"policy": "solo"}, self.root)
        self.assertEqual(status, 503)
        self.assertIn("error", json.loads(body))

    @unittest.skipUnless(importlib.util.find_spec("asgard.orchestration.policy"), "policy 엔진이 아직 없다")
    def test_the_real_engine_round_trips_through_the_window(self):
        """실제 엔진이 붙으면 스텁 없이도 같은 왕복이 선다 — 저장한 값이 다시 열었을 때 남아 있다."""
        status, _, _ = studio.dispatch_post("/api/orchestration/policy", {"policy": "solo"}, self.root)
        self.assertEqual(status, 200)

        status, _, body = studio.dispatch("GET", "/api/orchestration", {}, self.root)
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["policy"]["current"], "solo")
        self.assertEqual(data["policy"]["source"], "project")


class TestRecheck(PanelCase):
    def test_a_recheck_forces_a_probe(self):
        """'다시 확인'만 네트워크를 탄다 — force 없는 재점검은 캐시를 또 읽는 것과 같다."""
        calls = {"cached": 0, "probe": 0}
        store = {}
        with mock.patch.object(asgard, "engines", _engines_stub(calls), create=True), mock.patch.object(
            orch_pkg, "policy", _policy_stub(store), create=True
        ):
            status, _, body = studio.dispatch_post("/api/orchestration/recheck", {}, self.root)

        self.assertEqual(status, 200)
        self.assertEqual(calls["probe"], 1)
        self.assertIs(calls["force"], True)
        payload = json.loads(body)
        self.assertEqual(payload["state"]["engines"][0]["name"], "anthropic")

    def test_a_recheck_without_the_gauge_is_a_503(self):
        with mock.patch.object(asgard, "engines", None, create=True):
            status, _, body = studio.dispatch_post("/api/orchestration/recheck", {}, self.root)
        self.assertEqual(status, 503)
        self.assertIn("error", json.loads(body))


class TestChainAndWiring(unittest.TestCase):
    def test_the_material_module_never_looks_up_the_chain(self):
        """orchestration 은 tutor 와 routes 사이다 — routes·server·파사드를 부르면 사슬이 순환한다."""
        with open(_MODULE_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        banned = {"routes", "server", "__init__"}
        offending = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                siblings = {node.module.split(".")[0]} if node.module else {alias.name for alias in node.names}
                offending.extend(sorted(siblings & banned))
        self.assertFalse(offending, f"사슬을 거슬러 오르는 임포트: {offending}")

    def test_the_window_actually_mounts_the_panel(self):
        """재료만 있고 문이 없으면 이 층은 도달하지 않는다 — 탭·패널·왕복 주소가 다 있어야 한다."""
        with open(os.path.normpath(_HTML_PATH), encoding="utf-8") as handle:
            html = handle.read()
        needles = (
            'data-panel="orchestration"',
            'id="orchestration-panel"',
            "/api/orchestration/policy",
            "/api/orchestration/recheck",
            'id="orch-recheck"',
        )
        for needle in needles:
            self.assertIn(needle, html)


if __name__ == "__main__":
    unittest.main()
