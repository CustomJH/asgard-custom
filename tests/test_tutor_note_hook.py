"""tutor-note 훅 — 22개 훅 중 유일하게 행위 테스트가 0이던 자리.

실행: uv run pytest tests/test_tutor_note_hook.py

`tests/test_tutor.py` 는 엔진(`asgard.tutor`)만 잰다. 훅은 그 엔진의 판정을 **클라이언트
프로토콜로 옮기는 층**이고, 거기서 고장 나면 Stop 시점마다 조용히 실패한다 — 막지 않는 훅이라
화면에 아무것도 안 남는다. 되짚기가 빠진 턴과 되짚을 것이 없던 턴은 똑같이 생겼다.

그래서 여기서 보는 것은 두 가지뿐이다: 정상 payload 가 카드를 내는가, 깨진 payload 가 턴을
막지 않는가. 판정 규칙 자체는 엔진 몫이라 여기서 다시 재지 않는다 (훅은 규칙을 안 갖는다).

구동은 `tests/test_mode_parity.py` 의 `_hook_payload` 를 그대로 쓴다 — 스캐폴드를 깔지 않고
훅 소스를 in-process 로 돌리는 같은 자.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import asdict, replace
from typing import Any
from unittest import mock

from test_mode_parity import _hook_payload  # rootdir 삽입 경로 — test_orchestration_trinity 와 같은 관례

from asgard import tutor_teach
from asgard.hooks import tutor_note

_LESSON = {
    "files": ["app.py"],
    "added": 12,
    "removed": 3,
    "checkpoints": [
        {
            "kind": "silent-failure",
            "path": "app.py",
            "line": 42,
            "unit": "load_config",
            "ask": "이 except 가 삼키는 실패는 누가 알게 되나요?",
            "cid": "c1f2",
        }
    ],
    "revisits": [],
}
# 훅이 받는 JSON 그대로라 칸마다 타입이 다르다 — 좁혀 적으면 칸 하나를 고칠 때마다 판정기가
# 이 표 전체를 다시 유추한다.
_EXPLAIN: dict[str, Any] = {
    "base": "HEAD",
    "depth": "first",
    "mission": "설정 읽기를 실패해도 죽지 않게 바꿨어요",
    "steps": [
        {
            "order": 1,
            "path": "app.py",
            "line": 42,
            "unit": "load_config",
            "what": "예외를 잡아요",
            "why_here": "여기가 입구예요",
        }
    ],
    "terms": [{"name": "sentinel", "where": "app.py:3", "gloss": "없음을 뜻하는 표식이에요", "source": "signature"}],
    "checks": ["python -m pytest tests/test_app.py"],
    "recall": ["이 설정이 비면 무엇이 기본값이 되나요?"],
    "gaps": [["web.js", "구문을 못 읽었어요"]],
}


class TutorNoteHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        # 훅은 CLAUDE_PROJECT_DIR 를 cwd 보다 먼저 본다 — 이 스위트를 돌리는 세션이 그 변수를
        # 세워 두면 판정 대상이 사용자의 실제 저장소가 된다. 여기서 명시적으로 끊는다.
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def _sentinel(self, sid: str, paths: list[str]) -> None:
        state = os.path.join(self.root, ".asgard", "state")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "writes-" + sid + ".json"), "w", encoding="utf-8") as fh:
            json.dump(paths, fh)

    def test_a_written_session_gets_the_review_card(self) -> None:
        """정상 payload — 이 턴이 쓴 파일이 있고 엔진이 물음을 냈으면 카드가 stdout 으로 나간다."""
        self._sentinel("s1", ["app.py"])
        with (
            mock.patch.object(tutor_note, "_lesson", return_value=_LESSON),
            mock.patch.object(tutor_note.shutil, "which", return_value="/usr/bin/asgard"),
        ):
            code, out = _hook_payload("tutor_note", {"session_id": "s1", "cwd": self.root}, [])
        self.assertEqual(code, 0, "되짚기는 규율이지 관문이 아니다 — 어떤 경우에도 0으로 끝난다")
        card = json.loads(out)["systemMessage"]
        self.assertIn("app.py:42 load_config", card, out)
        self.assertIn("이 except 가 삼키는 실패는 누가 알게 되나요?", card)
        self.assertIn("조용히 삼킨 실패", card, "kind 가 사람 말로 번역돼야 한다")

    def _run(self, lesson: dict, sid: str = "s1") -> str:
        self._sentinel(sid, ["app.py"])
        with (
            mock.patch.object(tutor_note, "_lesson", return_value=lesson),
            mock.patch.object(tutor_note.shutil, "which", return_value="/usr/bin/asgard"),
        ):
            code, out = _hook_payload("tutor_note", {"session_id": sid, "cwd": self.root}, [])
        self.assertEqual(code, 0, "되짚기는 규율이지 관문이 아니다 — 어떤 경우에도 0으로 끝난다")
        return json.loads(out)["systemMessage"] if out else ""

    def test_the_explanation_comes_before_the_questions(self) -> None:
        """지식이 먼저, 인출이 나중 — 전달된 적 없는 것을 인출부터 시키면 물음은 침묵을 받는다."""
        card = self._run(dict(_LESSON, explain=_EXPLAIN))
        self.assertIn("임무 — 설정 읽기를 실패해도 죽지 않게 바꿨어요", card)
        self.assertIn("1. app.py:42 load_config — 예외를 잡아요 · 여기가 입구예요", card)
        self.assertIn("`sentinel` — app.py:3 — 없음을 뜻하는 표식이에요", card)
        self.assertIn("확인 — python -m pytest tests/test_app.py", card)
        self.assertIn("이 설정이 비면 무엇이 기본값이 되나요?", card)
        self.assertIn("못 본 것 — web.js: 구문을 못 읽었어요", card, "못 본 것은 못 봤다고 적는다")
        self.assertLess(
            card.index("⠶ 설명 —"),
            card.index("이 except 가 삼키는 실패는 누가 알게 되나요?"),
            "설명 절이 물음 아래로 내려가면 인출 순서가 뒤집힌다",
        )

    def test_the_two_screens_are_one_screen(self) -> None:
        """훅과 네이티브가 같은 줄을 낸다 — 갈리면 사용자는 어느 쪽이 진짜인지부터 물어야 한다.

        훅은 stdlib 전용이라 엔진을 못 부르고 JSON 칸만 보고 다시 그린다. 그 두 산출을 여기서
        문자열로 맞대 본다 — 엔진의 `card`가 줄을 바꾸면 이 자가 빨개진다.
        """
        exp = tutor_teach.Explanation(
            base="HEAD",
            depth="first",
            mission="설정 읽기를 실패해도 죽지 않게 바꿨어요",
            steps=tuple(tutor_teach.Step(**step) for step in _EXPLAIN["steps"]),
            terms=tuple(tutor_teach.Term(**term) for term in _EXPLAIN["terms"]),
            checks=tuple(_EXPLAIN["checks"]),
            recall=tuple(_EXPLAIN["recall"]),
            gaps=tuple(tuple(gap) for gap in _EXPLAIN["gaps"]),
        )
        for depth in ("first", "familiar", "owned"):
            row = replace(exp, depth=depth)
            engine = tutor_teach.card(row, 3)
            hook = "\n".join(tutor_note._explain(json.loads(json.dumps(asdict(row)))))
            self.assertEqual(hook, engine, depth)

    def test_an_owned_reader_gets_one_line(self) -> None:
        """이미 갖고 계신 자리는 한 줄로 줄인다 — 자르는 규칙은 엔진 몫이라 여기서 다시 안 자른다."""
        card = self._run(dict(_LESSON, explain=dict(_EXPLAIN, depth="owned")))
        self.assertIn("⠶ 설명 — app.py:42 load_config", card)
        self.assertNotIn("여기가 입구예요", card)
        self.assertNotIn("sentinel", card)

    def test_a_missing_explain_field_still_asks(self) -> None:
        """칸이 없거나 null 이면 지금까지처럼 물음만 낸다 (fail-open)."""
        empty = dict(_EXPLAIN, steps=[], terms=[], checks=[], gaps=[])
        for lesson in (_LESSON, dict(_LESSON, explain=None), dict(_LESSON, explain="x"), dict(_LESSON, explain=empty)):
            card = self._run(lesson, sid="s-%d" % id(lesson))
            self.assertIn("이 except 가 삼키는 실패는 누가 알게 되나요?", card)
            self.assertNotIn("⠶ 설명", card)

    def test_a_gaps_only_payload_draws_no_explanation(self) -> None:
        """못 본 것만 남은 회차는 훅도 침묵한다 — 엔진 `tutor_teach.card`와 같은 규칙이다.

        조건이 갈리면 같은 payload 가 네이티브에서는 안 나가고 훅에서는 두 줄로 나간다. 그 두 줄은
        `읽을 자리 0곳` + 못 본 것 하나뿐이라, 턴마다 나가면 다음 카드까지 안 읽히게 만든다.
        """
        gaps_only = dict(_EXPLAIN, steps=[], terms=[], checks=[], recall=[])
        card = self._run(dict(_LESSON, explain=gaps_only))
        self.assertNotIn("⠶ 설명", card)
        self.assertEqual(
            tutor_teach.card(
                tutor_teach.Explanation(
                    base="HEAD",
                    depth=str(gaps_only["depth"]),
                    mission="",
                    steps=(),
                    terms=(),
                    checks=(),
                    recall=(),
                    gaps=tuple(tuple(gap) for gap in gaps_only["gaps"]),
                )
            ),
            "",
        )

    def test_an_explanation_alone_still_reaches_the_user(self) -> None:
        """물음이 없어도 설명이 있으면 카드는 나간다 — 설명 자체가 이 층이 내야 할 것이다."""
        card = self._run({"files": ["app.py"], "added": 1, "removed": 0, "explain": _EXPLAIN})
        self.assertIn("⠶ 설명 — 이번 변경에서 읽을 자리 1곳이에요.", card)

    def test_the_report_path_comes_from_the_judgement(self) -> None:
        """카드 마지막 줄은 판정이 실제로 쓴 자리를 적는다 — 상수는 자리가 옮겨지면 빈 자리를 연다."""
        card = self._run(dict(_LESSON, report=".asgard/tutor/other.md"))
        self.assertIn(".asgard/tutor/other.md", card)
        self.assertIn(tutor_note.REPORT_REL, self._run(_LESSON, sid="s-fallback"))

    def test_a_broken_payload_does_not_take_the_turn_down(self) -> None:
        """깨진 payload — 칸 타입이 어긋나도 훅은 조용히 0으로 끝나고 아무것도 안 낸다.

        여기서 예외가 새면 Stop 훅이 매 턴 끝을 오염시킨다. 카드를 못 내는 것보다 나쁘다.
        """
        code, out = _hook_payload("tutor_note", {"session_id": {"not": "a string"}, "cwd": 12}, [])
        self.assertEqual(code, 0)
        self.assertEqual(out, "", "판정 못 한 턴에 빈 카드를 놓으면 다음 카드의 신뢰가 깎인다")


if __name__ == "__main__":
    unittest.main()
