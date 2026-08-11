"""되짚기의 "왜 이렇게 했는가" — 퀘스트 기록이 사실로 실리는가.

실행: uv run pytest tests/test_tutor_rationale.py

이 절은 지어내면 안 되는 절이다. 그래서 여기서 보는 것은 세 가지다: 기록이 있을 때 그 원문이
실리는가, 기록이 없을 때 **아무 줄도 안 내는가**, 그리고 엔진과 훅 두 렌더러가 같은 줄을 내는가.

모드도 같이 잰다. 기본이 `explain` 이라는 것은 오딘의 결정이고(26-08-07), 결정이 코드 어딘가의
기본 인자로만 살아 있으면 다음 리팩터가 조용히 뒤집는다.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from asgard import tutor, tutor_rationale
from asgard.hooks import tutor_note

_PLAN = {
    "quest_id": "q-demo",
    "event": "plan",
    "role": "thinker",
    "request": "튜터가 퀴즈 대신 설명하게",
    "criteria": [
        "카드가 답을 요구하지 않는다 | verify: pytest tests/test_x.py | artifacts: src/x.py",
        "기록이 없으면 그 절은 안 그린다",
        "가정: 모드는 explain|quiz 둘",
    ],
    "changed_files": [],
}
_VERIFY = {
    "quest_id": "q-demo",
    "event": "verify",
    "role": "verifier",
    "verdict": "PASS",
    "changed_files": ["src/x.py"],
    "criteria_checks": [{"cmd": "pytest tests/test_x.py", "exit_code": 0}],
    "commands": [{"cmd": "ruff check src", "exit_code": 0}, {"cmd": "git diff --stat", "exit_code": 0}],
}


class _QuestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.root, ".asgard", "quest"), exist_ok=True)

    def _quest(self, qid: str, events: list[dict], active: bool = False) -> None:
        path = os.path.join(self.root, ".asgard", "quest", qid + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for event in events:
                fh.write(json.dumps({**event, "quest_id": qid}, ensure_ascii=False) + "\n")
        if active:
            with open(os.path.join(self.root, ".asgard", "quest", "ACTIVE"), "w", encoding="utf-8") as fh:
                fh.write(qid)


class RationaleTest(_QuestCase):
    def test_the_record_is_read_verbatim(self) -> None:
        self._quest("q-demo", [_PLAN, _VERIFY])

        row = tutor_rationale.rationale(self.root, ["src/x.py"])

        self.assertEqual(row.quest_id, "q-demo")
        self.assertEqual(row.request, "튜터가 퀴즈 대신 설명하게")
        self.assertEqual(row.verdict, "PASS")
        self.assertEqual(row.goals[0], "카드가 답을 요구하지 않는다", "`| verify:` 꼬리는 계약이지 설명이 아니다")
        self.assertEqual(row.assumptions, ("모드는 explain|quiz 둘",), "`가정:` 접두는 목표가 아니라 가정이다")
        self.assertEqual(row.evidence[0], ("pytest tests/test_x.py", 0), "하네스가 다시 돌린 기준 검사가 먼저다")
        self.assertIn(("ruff check src", 0), row.evidence)

    def test_no_record_draws_nothing(self) -> None:
        """기록이 없으면 빈칸은 빈칸이다 — 없는 이유를 지어내면 이 절은 통째로 못 믿을 것이 된다."""
        self.assertFalse(tutor_rationale.rationale(self.root, ["src/x.py"]))
        self.assertEqual(tutor_rationale.lines(tutor_rationale.rationale(self.root)), [])

    def test_the_active_pointer_beats_an_overlapping_closed_quest(self) -> None:
        """닫힌 릴리스 기장은 저장소를 넓게 건드려 어느 경로든 겹친다 — 겹침만으로 고르면 그쪽이
        이번 변경의 이유로 들어간다 (26-08-07 실측: `release-0-10-8` 이 그렇게 이겼다)."""
        self._quest(
            "release-old",
            [
                {**_PLAN, "criteria": ["판 번호를 올린다"], "request": "릴리스"},
                {**_VERIFY, "changed_files": ["src/x.py", "src/y.py"]},
                {"event": "quest_closed", "role": "odin"},
            ],
        )
        self._quest("q-demo", [_PLAN], active=True)

        self.assertEqual(tutor_rationale.rationale(self.root, ["src/x.py"]).quest_id, "q-demo")

    def test_an_unrelated_open_quest_is_not_this_change_s_reason(self) -> None:
        """포인터도 겹침도 없으면 빈칸이다.

        26-08-11 실측: 닫는 것을 잊은 옛 기장 하나가 "열려 있다"는 이유만으로 계속 이겼다.
        워킹트리는 workroots·tutor 를 건드리고 있었는데 카드에는 `ql-inproc-fastpath` 의 기준이
        이 변경의 이유로 실렸다 — 경로가 한 곳도 안 겹치는데도 그랬다.
        """
        self._quest(  # 안 닫힌 옛 기장 — 이 변경과 경로가 한 곳도 안 겹친다
            "stale-open",
            [
                {**_PLAN, "criteria": ["다른 일을 한다"], "request": "옛 퀘스트"},
                {**_VERIFY, "changed_files": ["src/somewhere-else.py"]},
            ],
        )

        self.assertFalse(tutor_rationale.rationale(self.root, ["src/x.py"]), "겹침이 0이면 이유가 아니다")

    def test_an_open_quest_still_wins_while_the_pointer_names_it(self) -> None:
        """막 연 퀘스트는 아직 changed_files 가 없다 — 겹침 문턱이 그 자리를 죽이면 안 된다."""
        self._quest("q-demo", [_PLAN], active=True)

        self.assertEqual(tutor_rationale.rationale(self.root, ["src/x.py"]).quest_id, "q-demo")

    def test_a_neighbour_session_s_quest_is_not_this_change_s_reason(self) -> None:
        """포인터는 저장소마다 하나인데 세션은 여럿일 수 있다 (26-08-11 실측).

        경로로 가르려던 첫 판은 안 섰다: 하네스가 `changed_files` 를 워킹트리 전체에서 떠서 같은
        트리의 두 퀘스트는 서로의 파일을 다 적는다(그 실측에서 옆 기장이 39개를 적었고 이쪽
        파일도 그 안에 있었다). 그래서 가르는 축은 이벤트마다 적히는 `session_id` 다.
        """
        self._quest(  # 옆 세션이 열어 둔 것 — 포인터를 쥐고 있고 이쪽 파일까지 적고 있다
            "neighbour",
            [
                {**_PLAN, "request": "옆 세션", "session_id": "other-session"},
                {**_VERIFY, "changed_files": ["src/x.py", "src/elsewhere.py"], "session_id": "other-session"},
            ],
            active=True,
        )
        self._quest(
            "q-demo",
            [
                {**_PLAN, "session_id": "my-session"},
                {**_VERIFY, "session_id": "my-session"},
                {"event": "quest_closed", "role": "odin"},
            ],
        )

        picked = tutor_rationale.rationale(self.root, ["src/x.py"], "my-session")

        self.assertEqual(picked.quest_id, "q-demo")

    def test_a_session_name_the_log_never_wrote_does_not_filter_anything(self) -> None:
        """훅이 넘기는 이름과 기장이 적는 이름은 다른 통에서 나온다.

        훅은 호스트 payload 의 `session_id` 를, 없으면 `default` 를, Cursor 에서는 리터럴
        `cursor` 를 넘긴다. 기장은 환경 변수에서 읽은 값을 적는다. 두 통이 어긋나면 세션 축이
        **모든** 후보를 남의 것으로 밀어내고 이 칸이 통째로 빈다 — Cursor 에서는 늘 그랬다.
        """
        self._quest("q-demo", [{**_PLAN, "session_id": "real-host-id"}, {**_VERIFY, "session_id": "real-host-id"}])

        for stranger in ("cursor", "default", "-"):
            self.assertEqual(tutor_rationale.rationale(self.root, ["src/x.py"], stranger).quest_id, "q-demo", stranger)

    def test_the_unknown_marker_is_not_a_session_identity(self) -> None:
        """`-` 는 이름이 아니라 "못 받았다" 는 표시다 — 신원으로 세면 남남인 두 기장이 한 세션이 된다."""
        self._quest("q-demo", [{**_PLAN, "session_id": "-"}, {**_VERIFY, "session_id": "-"}])

        self.assertEqual(tutor_rationale.rationale(self.root, ["src/x.py"], "my-session").quest_id, "q-demo")

    def test_without_a_session_the_pointer_is_still_trusted(self) -> None:
        """사람이 직접 친 `asgard tutor` 는 세션을 모른다 — 근거 없이 포인터를 버리면 정상
        단일 세션의 카드까지 빈칸이 된다."""
        self._quest("q-demo", [{**_PLAN, "session_id": "my-session"}], active=True)

        self.assertEqual(tutor_rationale.rationale(self.root, ["src/x.py"]).quest_id, "q-demo")

    def test_a_truncated_line_does_not_lose_the_rest(self) -> None:
        path = os.path.join(self.root, ".asgard", "quest", "q-demo.jsonl")
        self._quest("q-demo", [_PLAN], active=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"event": "verify", "ver\n')

        self.assertEqual(tutor_rationale.rationale(self.root).goals[0], "카드가 답을 요구하지 않는다")


class TwoRenderersTest(_QuestCase):
    def test_the_engine_and_the_hook_draw_the_same_lines(self) -> None:
        """훅은 stdlib 전용이라 엔진을 못 부르고 JSON 칸만 보고 다시 그린다 — 두 산출을 맞대 본다.

        갈리면 같은 판정이 클라이언트마다 다르게 보이고, 사용자는 어느 쪽이 진짜인지부터 묻는다.
        """
        self._quest("q-demo", [_PLAN, _VERIFY], active=True)
        row = tutor_rationale.rationale(self.root, ["src/x.py"])

        engine = tutor_rationale.lines(row)
        hook = tutor_note._why(json.loads(json.dumps(tutor_rationale.as_dict(row))))

        self.assertEqual(hook, engine)
        self.assertTrue(engine[0].startswith("⠶ 왜 이렇게 했는가 — 퀘스트 `q-demo`"))

    def test_an_empty_record_draws_nothing_on_both_sides(self) -> None:
        for payload in (None, {}, "x", {"goals": [], "evidence": []}):
            self.assertEqual(tutor_note._why(payload), [], payload)
        self.assertEqual(tutor_rationale.lines(None), [])


class ModeTest(unittest.TestCase):
    def test_explain_is_the_default(self) -> None:
        """오딘의 결정 (26-08-07) — 기본 인자에만 살아 있으면 다음 리팩터가 조용히 뒤집는다."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASGARD_TUTOR_MODE", None)
            with (
                mock.patch("asgard.settings.load_project", return_value={}),
                mock.patch("asgard.settings.load_global", return_value={}),
            ):
                self.assertEqual(tutor.mode("/nowhere"), "explain")

    def test_the_flag_beats_the_setting_and_the_setting_beats_the_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASGARD_TUTOR_MODE", None)
            with (
                mock.patch("asgard.settings.load_project", return_value={"tutor": {"mode": "quiz"}}),
                mock.patch("asgard.settings.load_global", return_value={}),
            ):
                self.assertEqual(tutor.mode("/nowhere"), "quiz")
                self.assertEqual(tutor.mode("/nowhere", "explain"), "explain", "플래그가 설정을 이긴다")
            with (
                mock.patch("asgard.settings.load_project", return_value={"tutor": {"mode": "nonsense"}}),
                mock.patch("asgard.settings.load_global", return_value={}),
            ):
                self.assertEqual(tutor.mode("/nowhere"), "explain", "모르는 값은 값이 아니다")

    def test_the_env_var_is_read(self) -> None:
        with mock.patch.dict(os.environ, {"ASGARD_TUTOR_MODE": "quiz"}):
            self.assertEqual(tutor.mode("/nowhere"), "quiz")


class CardShapeTest(unittest.TestCase):
    """카드가 실제로 답을 요구하지 않는가 — 모드의 값은 이 화면 하나로 판정된다."""

    _LESSON = {
        "files": [{"path": "src/x.py", "units_moved": []}],
        "added": 10,
        "removed": 2,
        "report": ".asgard/tutor/last-review.md",
    }
    _POINT = {
        "kind": "behavior-removed",
        "path": "src/x.py",
        "line": 4,
        "unit": "alpha",
        "what": "이 단위가 사라졌어요",
        "ask": "이걸 부르던 곳은 어디였나요?",
        "cid": "c1f2",
    }

    def test_explain_mode_states_the_fact_and_asks_nothing(self) -> None:
        card = tutor_note._card(
            dict(self._LESSON, mode="explain"), [self._POINT], [], (), ("⠶ 왜 이렇게 했는가 — 퀘스트 `q`",)
        )

        self.assertIn("이 단위가 사라졌어요", card)
        self.assertIn("⠶ 왜 이렇게 했는가", card)
        self.assertNotIn("▸", card, "물음표는 답을 기다린다 — explain 모드에는 기다리는 것이 없다")
        self.assertNotIn("--answer", card)
        self.assertNotIn("기계가 못 답하는", card, "머리글도 퀴즈 틀이다")
        self.assertIn("--quiz", card, "되돌릴 길은 화면에 남는다")

    def test_quiz_mode_keeps_the_round_trip(self) -> None:
        card = tutor_note._card(dict(self._LESSON, mode="quiz"), [self._POINT], [], (), ())

        self.assertIn("▸ 이걸 부르던 곳은 어디였나요?", card)
        self.assertIn('--answer <표식> "..."', card)
        self.assertIn("[c1f2]", card, "표식이 없으면 답할 수가 없다")

    def test_a_payload_with_no_mode_stays_a_quiz(self) -> None:
        """구 판본 payload — 칸이 없으면 종전 동작이다. 훅과 엔진의 배송 시점이 어긋날 수 있다."""
        self.assertIn("▸", tutor_note._card(self._LESSON, [self._POINT], [], (), ()))


if __name__ == "__main__":
    unittest.main()
