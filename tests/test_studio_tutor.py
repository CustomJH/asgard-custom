"""스튜디오 되짚기 패널 — 재료의 왕복과 사슬 준수.

여기서 지키는 것은 세 가지다.
  · 패널 재료는 네 갈래(물음·성장·부채·recap)가 한 왕복으로 오고, 못 잰 갈래는 못 쟀다고 적힌다.
  · 답과 오탐이 실제로 돌아온다 — 물음만 보여주는 창은 이 층에 아무것도 못 가르친다.
  · 재료 모듈은 사슬(STUDIO_CHAIN)에서 routes 아래에 산다 — 위를 부르면 순환이다.
"""

import ast
import json
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import asgard
from asgard import tutor as tutor_engine
from asgard import tutor_growth
from asgard.commands import studio
from asgard.commands.studio import tutor as studio_tutor

_MODULE_PATH = os.path.join(os.path.dirname(studio_tutor.__file__), "tutor.py")
_HTML_PATH = os.path.join(os.path.dirname(os.path.dirname(studio_tutor.__file__)), "..", "assets", "studio.html")


class PanelCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="asgard-tutor-panel-")
        self.now = time.time()

    def _ask(self, kind="todo-left", path="app.py", key="TODO: later", ask="이건 언제 갚는가?"):
        """물음 하나를 성장 기록에 심고 그 표식을 돌려준다 — 판정기를 돌리지 않고 기록만 만든다."""
        tutor_growth.note_asked(self.root, [{"kind": kind, "path": path, "unit": "", "key": key, "ask": ask}], self.now)
        return tutor_growth.cid(kind, path, key)


class TestPanelState(PanelCase):
    def test_the_panel_carries_all_four_branches(self):
        """한 왕복에 네 갈래 — 갈래마다 GET 을 따로 돌면 창이 네 번 깜빡인다."""
        status, _, body = studio.dispatch("GET", "/api/tutor", {}, self.root)

        self.assertEqual(status, 200)
        data = json.loads(body)
        for key in ("open", "growth", "debt", "recap", "missing", "labels"):
            self.assertIn(key, data)
        # 종류의 사람 이름은 엔진의 것 그대로다 — 표면이 다시 쓰면 화면마다 다르게 불린다
        self.assertEqual(data["labels"], tutor_engine.KIND_LABEL)

    def test_open_questions_come_heaviest_first(self):
        """확인 순위는 엔진의 무게표를 따른다 — 사람의 눈은 유한하다."""
        light = self._ask(kind="todo-left", key="TODO: a")
        heavy = self._ask(kind="silent-failure", path="core.py", key="OSError@load", ask="누가 알아차리는가?")

        data = studio_tutor.panel_state(self.root, now=self.now)

        self.assertEqual([row["cid"] for row in data["open"]], [heavy, light])
        first = data["open"][0]
        for key in ("cid", "kind", "where", "ask", "asks", "days"):
            self.assertIn(key, first)

    def test_a_missing_gauge_is_reported_not_hidden(self):
        """부채·recap 엔진이 없으면 None + missing — "없음"과 "못 봤음"은 다른 화면이다."""
        with mock.patch.object(asgard, "tutor_debt", None, create=True):
            data = studio_tutor.panel_state(self.root, now=self.now)

        self.assertIsNone(data["debt"])
        self.assertIn("debt", data["missing"])
        # recap 이 엔진에 아직 없다면 같은 규약으로 적힌다 — 있으면 missing 에서 빠진다
        if not hasattr(tutor_engine, "recap"):
            self.assertIsNone(data["recap"])
            self.assertIn("recap", data["missing"])

    def test_a_present_debt_engine_fills_the_gauge(self):
        """Worker A 의 계약 시그니처(ledger(root, sid, now) → Ledger)가 그대로 재료가 된다."""
        signal = SimpleNamespace(name="skip-streak", level=2, fact="4회 연속 건너뜀", why="근거", source="growth.json")
        ledger = SimpleNamespace(
            level=2, open_debt=3, oldest_days=5, turns=7, added=120, worst=signal, signals=(signal,)
        )
        stub = SimpleNamespace(ledger=lambda root, sid="", now=None: ledger)

        with mock.patch.object(asgard, "tutor_debt", stub, create=True):
            data = studio_tutor.panel_state(self.root, now=self.now)

        self.assertNotIn("debt", data["missing"])
        self.assertEqual(data["debt"]["open_debt"], 3)
        self.assertEqual(data["debt"]["worst"], "skip-streak")
        self.assertEqual(data["debt"]["signals"][0]["fact"], "4회 연속 건너뜀")

    def test_a_broken_gauge_fails_open(self):
        """계기 하나가 죽어도 나머지 세 갈래는 나간다 — 이 갈래는 관문이 아니라 계기다."""

        def boom(root, sid="", now=None):
            raise RuntimeError("죽은 엔진")

        with mock.patch.object(asgard, "tutor_debt", SimpleNamespace(ledger=boom), create=True):
            data = studio_tutor.panel_state(self.root, now=self.now)

        self.assertIsNone(data["debt"])
        self.assertIn("debt", data["missing"])
        self.assertIn("open", data)

    def test_recap_is_passed_through_when_the_engine_learns_it(self):
        """Worker B 의 recap(root, sid, span, now) → str 이 그대로 실린다."""
        with mock.patch.object(tutor_engine, "recap", create=True, new=lambda root, span="day", now=None: "서사 한 판"):
            data = studio_tutor.panel_state(self.root, now=self.now)

        self.assertEqual(data["recap"], "서사 한 판")
        self.assertNotIn("recap", data["missing"])


class TestAnswerRoundTrip(PanelCase):
    def test_an_answer_closes_the_question_and_returns_fresh_state(self):
        """답하기 → 물음이 닫히고, 응답에 실려 온 재료에는 그 물음이 더 없다."""
        cid = self._ask()

        status, _, body = studio.dispatch_post(
            "/api/tutor/answer", {"cid": cid, "text": "표식은 다음 릴리스 전 정리 대상으로 티켓에 옮겼다"}, self.root
        )

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["closed"], cid)
        self.assertNotIn(cid, [row["cid"] for row in payload["state"]["open"]])
        self.assertEqual(payload["state"]["growth"]["answered"], 1)

    def test_a_dismissal_is_counted_as_a_dismissal(self):
        """오탐은 답이 아니다 — 답으로 세면 조절(fading)이 거꾸로 간다."""
        cid = self._ask()

        status, _, body = studio.dispatch_post("/api/tutor/dismiss", {"cid": cid}, self.root)

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["state"]["growth"]["dismissed"], 1)
        self.assertEqual(payload["state"]["growth"]["answered"], 0)

    def test_bad_payloads_are_refused(self):
        cid = self._ask()
        self.assertEqual(studio.dispatch_post("/api/tutor/answer", {"cid": cid}, self.root)[0], 400)
        self.assertEqual(studio.dispatch_post("/api/tutor/answer", {"text": "답만 있음"}, self.root)[0], 400)
        self.assertEqual(studio.dispatch_post("/api/tutor/dismiss", {}, self.root)[0], 400)

    def test_an_unknown_cid_is_a_404_not_a_silent_success(self):
        """없는 물음을 닫았다고 말하면 기록이 거짓이 된다."""
        status, _, body = studio.dispatch_post(
            "/api/tutor/answer", {"cid": "ffffffff", "text": "충분히 긴 답 본문"}, self.root
        )
        self.assertEqual(status, 404)
        self.assertIn("error", json.loads(body))


class TestChainAndWiring(unittest.TestCase):
    def test_the_material_module_never_looks_up_the_chain(self):
        """tutor 는 config 와 routes 사이다 — routes·server·파사드를 부르면 사슬이 순환한다."""
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
        """재료만 있고 문이 없으면 이 층은 도달하지 않는다 — 사이드바·뷰·왕복 주소가 다 있어야 한다."""
        with open(os.path.normpath(_HTML_PATH), encoding="utf-8") as handle:
            html = handle.read()
        for needle in ('data-view="tutor"', 'id="tutor-view"', "/api/tutor/answer", "/api/tutor/dismiss", "'tutor'"):
            self.assertIn(needle, html)


if __name__ == "__main__":
    unittest.main()
