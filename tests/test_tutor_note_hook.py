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

import glob
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

_LESSON: dict[str, Any] = {
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
            # 그 단위가 스스로 적어 둔 한 문장 (docstring 인용). 없는 자리는 아래 zeta 가 맡는다.
            "does": "설정 파일을 읽어 사전으로 돌려줘요.",
        },
        {
            "order": 2,
            "path": "app.py",
            "line": 61,
            "unit": "zeta",
            "what": "새로 생긴 단위예요 (3행)",
            "why_here": "이 변경 안에서 이 자리를 부르는 곳 — `load_config`",
        },
    ],
    "terms": [{"name": "sentinel", "where": "app.py:3", "gloss": "없음을 뜻하는 표식이에요", "source": "signature"}],
    "checks": ["python -m pytest tests/test_app.py"],
    "recall": ["이 설정이 비면 무엇이 기본값이 되나요?"],
    "gaps": [["web.js", "구문을 못 읽었어요"]],
}


class _HookCase(unittest.TestCase):
    """훅 하나를 진짜 저장소가 아닌 임시 나무 위에서 돌리기 위한 자리 — 테스트는 없다."""

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
        for rel in paths:
            path = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("")


class TutorNoteHookTest(_HookCase):
    def test_a_scratch_file_created_and_removed_in_the_turn_is_not_reviewed(self) -> None:
        self._sentinel("scratch", ["app.py", "_scratch.py"])
        os.remove(os.path.join(self.root, "_scratch.py"))

        self.assertEqual(tutor_note._writes(self.root, "scratch"), ["app.py"])

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
        self.assertIn("1. app.py:42 load_config — 설정 파일을 읽어 사전으로 돌려줘요.", card)
        self.assertIn("     예외를 잡아요 · 여기가 입구예요", card, "변경 사실은 그 아래 줄에 남는다")
        self.assertIn("2. app.py:61 zeta — 새로 생긴 단위예요 (3행)", card, "docstring 이 없으면 한 줄 그대로다")
        self.assertIn("`sentinel` — app.py:3 — 없음을 뜻하는 표식이에요", card)
        self.assertIn("확인 — python -m pytest tests/test_app.py", card)
        self.assertNotIn("이 설정이 비면 무엇이 기본값이 되나요?", card, "한 카드에는 회상 질문도 하나만 둔다")
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
            hook = "\n".join(tutor_note._explain(json.loads(json.dumps(asdict(row))), 3))
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
        self.assertIn("⠶ 설명 — 변경 단위 2곳을 호출 관계 기준 1개 흐름으로 나눴어요.", card)
        self.assertIn("이 설정이 비면 무엇이 기본값이 되나요?", card, "판정 질문이 없을 때는 회상 질문을 쓴다")

    def test_the_hook_prefers_the_one_checkpoint_the_engine_marked_as_shown(self) -> None:
        hidden = dict(
            _LESSON["checkpoints"][0], path="hidden.py", unit="hidden", ask="숨은 질문인가요?", cid="deadbeef"
        )
        lesson = dict(
            _LESSON,
            checkpoints=[_LESSON["checkpoints"][0], hidden],
            shown_checkpoints=[_LESSON["checkpoints"][0]],
            explain=_EXPLAIN,
        )

        card = self._run(lesson)

        self.assertIn("load_config", card)
        self.assertNotIn("숨은 질문", card)
        self.assertNotIn("…외", card)

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


class TutorNoteWireFormatTest(_HookCase):
    """호스트마다, 이벤트마다, 그 자리가 실제로 읽는 필드 하나.

    이 층은 조용히 고장 난다 — 안 읽는 이름으로 적은 카드는 화면에서 "되짚을 게 없던 턴"과
    똑같이 생겼다. codex 는 실제로 그렇게 두 레인을 잃고 있었다: Stop 만 `systemMessage` 를
    쓰고 brief·tip 은 평문 stdout 을 썼는데, codex 의 훅 출력 스키마는
    `additionalProperties: false` 라 JSON 이 아닌 출력을 통째로 버린다.

    표는 세 호스트가 각자 문서로 정한 것이다 — Claude Code·Codex 는 세 이벤트 모두
    `systemMessage`, Cursor 만 `beforeSubmitPrompt` 는 `user_message`, `stop` 은
    `followup_message` 로 갈린다.
    """

    _EXPECTED = {
        ("claude", "note"): "systemMessage",
        ("codex", "note"): "systemMessage",
        ("cursor", "note"): "followup_message",
        ("claude", "brief"): "systemMessage",
        ("codex", "brief"): "systemMessage",
        ("cursor", "brief"): "user_message",
        ("claude", "tip"): "systemMessage",
        ("codex", "tip"): "systemMessage",
        ("cursor", "tip"): "user_message",
    }

    def _emit(self, protocol: str, mode: str, sid: str) -> dict:
        """한 레인을 한 번 돌린 stdout — 판정과 셸 호출은 막고 프로토콜 층만 남긴다."""
        argv = [protocol] if mode == "note" else [protocol, mode]
        payload: dict[str, Any] = {"session_id": sid, "cwd": self.root}
        # Cursor payload 에는 세션 좌표가 없어서 훅이 상수 `"cursor"` 로 접는다 (write-sentinel 과
        # 같은 규약) — write sentinel 파일도 그 이름으로 놓아야 훅이 찾는다.
        sid = "cursor" if protocol == "cursor" else sid
        if mode == "brief":
            payload["prompt"] = "app.py 를 봐 주세요"
        if mode == "tip":
            payload |= {"tool_name": "Edit", "tool_input": {"file_path": "app.py"}}
        self._sentinel(sid, ["app.py"])
        with (
            mock.patch.object(tutor_note, "_lesson", return_value=_LESSON),
            mock.patch.object(tutor_note, "_brief", return_value="⠶ 들어가기 전 — 한 건"),
            mock.patch.object(tutor_note, "_every", return_value=True),
            mock.patch.object(tutor_note.shutil, "which", return_value="/usr/bin/asgard"),
            mock.patch.object(
                tutor_note.subprocess, "run", return_value=mock.Mock(stdout="⠶ 도중 점검 — 한 건", returncode=0)
            ),
        ):
            code, out = _hook_payload("tutor_note", payload, argv)
        self.assertEqual(code, 0, "되짚기는 규율이지 관문이 아니다 — 어떤 경우에도 0으로 끝난다")
        self.assertTrue(out.strip(), f"{protocol}/{mode} 레인이 아무것도 안 냈다")
        return json.loads(out)

    def test_every_lane_speaks_the_field_its_host_reads(self) -> None:
        for (protocol, mode), field in self._EXPECTED.items():
            with self.subTest(protocol=protocol, mode=mode):
                sent = self._emit(protocol, mode, f"{protocol}-{mode}")
                self.assertEqual(list(sent), [field], f"{protocol}/{mode} 는 {field} 하나만 낸다")
                self.assertTrue(str(sent[field]).strip())

    def test_no_lane_writes_bare_text(self) -> None:
        """평문 stdout 은 어느 호스트에서도 사람에게 안 닿는다 — codex 는 그것을 오류로 버린다."""
        for protocol, mode in self._EXPECTED:
            with self.subTest(protocol=protocol, mode=mode):
                self._emit(protocol, mode, f"raw-{protocol}-{mode}")  # json.loads 가 곧 판정이다

    def test_a_delete_counts_as_a_write_for_the_tip(self) -> None:
        """Cursor 의 postToolUse 매처가 `Delete` 를 여기로 보낸다 — 계수에서 빼면 팁이 가장
        필요한 구간(삭제)을 못 본다. 삭제는 물음 종류 절반이 태어나는 자리다."""
        for name in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Delete", "apply_patch"):
            with self.subTest(tool=name):
                self.assertTrue(tutor_note._wrote_a_file({"tool_name": name, "tool_input": {"file_path": "a.py"}}))
        self.assertFalse(tutor_note._wrote_a_file({"tool_name": "Read", "tool_input": {"file_path": "a.py"}}))
        self.assertFalse(
            tutor_note._wrote_a_file({"tool_name": "Delete", "tool_input": {"file_path": ".asgard/state/x.json"}}),
            "자기 상태 파일을 세면 팁이 자기를 부른다",
        )


class TutorNoteRungTest(_HookCase):
    """카드 머리의 단계 줄 — 지금 어느 칸에 서 있고 다음 칸의 기준이 무엇인가.

    이 칸(`track`)은 엔진(`asgard.tutor_track.place`)이 만들고 훅은 옮겨 적기만 한다. 그래서
    여기서 재는 것은 둘이다: 칸이 들어오면 줄로 나오는가, **칸이 없을 때 카드가 안 죽는가**.
    뒤쪽이 이 층의 실패 방식이다 — 없는 칸을 오류로 다루면 되짚기 카드가 통째로 사라지고,
    막지 않는 훅이라 화면에는 아무것도 안 남는다.
    """

    _ROW = {
        "track": "hooks",
        "rung": "familiar",
        "bar": "답해 봤어요",
        "asked": 7,
        "deep": 2,
        "open": 3,
        "next_bar": "당신 것이에요",
        "remaining": "깊은 답 3건이 더 필요해요",
    }

    def _card(self, lesson: dict, sid: str) -> str:
        self._sentinel(sid, ["app.py"])
        with (
            mock.patch.object(tutor_note, "_lesson", return_value=lesson),
            mock.patch.object(tutor_note.shutil, "which", return_value="/usr/bin/asgard"),
        ):
            code, out = _hook_payload("tutor_note", {"session_id": sid, "cwd": self.root}, [])
        self.assertEqual(code, 0, "되짚기는 규율이지 관문이 아니다 — 어떤 경우에도 0으로 끝난다")
        return json.loads(out)["systemMessage"] if out.strip() else ""

    def test_the_card_opens_with_where_you_stand(self) -> None:
        """단계 줄이 물음 위에 온다 — 오를 칸이 화면에 없으면 물음은 쌓이기만 한다."""
        card = self._card(dict(_LESSON, track=self._ROW), "rung")

        self.assertIn("`hooks` 트랙 familiar (답해 봤어요)", card)
        self.assertIn("다음 칸 — 당신 것이에요: 깊은 답 3건이 더 필요해요", card)
        self.assertTrue(card.startswith("⠶ 지금 자리 —"), card.splitlines()[:2])
        self.assertLess(card.index("⠶ 지금 자리 —"), card.index("⠶ 되짚기 —"))

    def test_a_payload_without_a_track_draws_the_card_it_drew_before(self) -> None:
        """칸이 아직 안 오는 동안에도 오늘의 카드가 그대로 나간다 — 없는 칸은 오류가 아니다."""
        card = self._card(_LESSON, "no-track")

        self.assertTrue(card.startswith("⠶ 되짚기 — 이번 턴 1개 파일 · +12/-3행이에요."), card)
        self.assertNotIn("지금 자리", card)
        self.assertIn("이 except 가 삼키는 실패는 누가 알게 되나요?", card)

    def test_a_track_the_hook_cannot_read_costs_one_line_not_the_card(self) -> None:
        """모양이 어긋난 칸은 줄 하나를 잃을 뿐이고, 물음은 그대로 나간다."""
        broken: list[Any] = [None, "familiar", [], {}, {"tracks": []}, {"rung": ""}, {"tracks": "hooks"}]
        for index, value in enumerate(broken):
            with self.subTest(track=value):
                card = self._card(dict(_LESSON, track=value), "broken-%d" % index)
                self.assertNotIn("지금 자리", card)
                self.assertIn("이 except 가 삼키는 실패는 누가 알게 되나요?", card)

    def test_the_hook_reads_the_fields_the_engine_actually_sends(self) -> None:
        """엔진이 실제로 낸 `place()` 산출을 그대로 통과시킨다 — 모양을 손으로 베끼면 갈린다.

        기대값은 엔진 산출에서 꺼낸다. 훅이 찾는 칸 이름과 엔진이 적는 칸 이름 중 한쪽이
        움직이면 이 자가 빨개진다 — 어휘를 네 번째로 베껴 적다 종류 하나를 잃은 적이 있다.
        """
        from asgard import tutor_growth, tutor_track

        self.assertEqual(tutor_note._rung(tutor_track.place(self.root)), [], "물음이 없으면 세울 트랙도 없다")
        tutor_growth.note_asked(
            self.root,
            [{"kind": "silent-failure", "path": "src/app.py", "unit": "load_config", "ask": "누가 알게 되나요?"}],
        )

        placed = tutor_track.place(self.root)
        row = placed["tracks"][0]
        line = "\n".join(tutor_note._rung(placed))

        self.assertTrue(line.startswith("⠶ 지금 자리 —"), placed)
        for field in ("track", "rung", "bar", "next_bar", "remaining"):
            self.assertIn(str(row[field]), line, field)


class TutorNoteModelChannelTest(_HookCase):
    """모델 통로 — 열린 물음이 **있다는 사실**과 오딘의 답을 어디에 적는지만 간다.

    오딘과 한 방에 있는 것은 에이전트뿐이라, 오딘이 말한 답을 기록으로 옮기는 일은 에이전트가
    진다. 아무도 안 옮기면 `--answer` 는 도는데 아무도 안 치는 상태가 되고, 그게 물음 36건에
    답 0건이던 형상이다.

    물음 문장은 이 통로로 한 글자도 안 간다. 물음을 읽은 모델은 그 물음에 대신 답하고, 그러면
    되짚기가 막으려던 바로 그 일이 일어난다. 아래 첫 시험이 그 불변식이다.
    """

    # 이 문장이 모델 통로에 조각으로라도 나타나면 시험이 빨개진다 — 카드 안에서만 살아야 한다.
    _ASK = "제우스가 삼킨 예외는 누가 알게 되나요?"
    _MARK = "7c968810"
    _CARD = (
        "⠶ 들어가기 전 — 지난 턴에 열어 둔 물음이 이 자리에 1건 있어요 (막지 않아요).\n"
        "  조용히 삼킨 실패 — app.py load_config  [%s]\n    ▸ %s" % (_MARK, _ASK)
    )
    _HUMAN = {"claude": "systemMessage", "codex": "systemMessage", "cursor": "user_message"}

    def _brief(self, protocol: str, sid: str, card: str = "") -> dict:
        """브리핑 레인을 한 번 돌린 stdout — 판정은 막고 통로 층만 남긴다."""
        payload = {"session_id": sid, "cwd": self.root, "prompt": "app.py 를 봐 주세요"}
        with (
            mock.patch.object(tutor_note, "_brief", return_value=card or self._CARD),
            mock.patch.object(tutor_note.shutil, "which", return_value="/usr/bin/asgard"),
        ):
            code, out = _hook_payload("tutor_note", payload, [protocol, "brief"])
        self.assertEqual(code, 0, "되짚기는 규율이지 관문이 아니다 — 어떤 경우에도 0으로 끝난다")
        self.assertEqual(
            out.strip().count("\n"), 0, "stdout 에 JSON 객체가 둘이면 호스트가 파싱에 실패해 통째로 버린다"
        )
        return json.loads(out) if out.strip() else {}

    def _told(self, sent: dict) -> str:
        """이 payload 에서 모델에게 가는 글자 전부 — 통로 이름은 호스트가 정한다."""
        if "additional_context" in sent:
            return str(sent["additional_context"])
        return str((sent.get("hookSpecificOutput") or {}).get("additionalContext") or "")

    def test_the_question_never_reaches_the_model(self) -> None:
        """물음 문장은 사람 통로에만 있다. 모델이 읽으면 대신 답하고, 그러면 이 층이 하는 일이 없다."""
        for protocol in ("claude", "codex", "cursor"):
            with self.subTest(protocol=protocol):
                sent = self._brief(protocol, "leak-" + protocol)
                told = self._told(sent)

                self.assertTrue(told, "모델 통로가 비면 이 시험은 아무것도 안 재는 것과 같다")
                self.assertNotIn(self._ASK, told)
                for piece in ("제우스", "삼킨 예외", "누가 알게"):
                    self.assertNotIn(piece, told, "물음의 조각도 안 간다")
                self.assertIn(self._ASK, str(sent[self._HUMAN[protocol]]), "물음은 사람 화면에 그대로 남는다")

    def test_the_model_gets_the_mark_and_the_way_to_write_the_answer_down(self) -> None:
        told = self._told(self._brief("claude", "scribe"))

        self.assertIn(self._MARK, told)
        self.assertIn('asgard tutor --answer %s --note "' % self._MARK, told)
        self.assertIn("당신이 답하지 마세요", told)

    def test_each_host_hears_the_model_channel_at_its_own_name(self) -> None:
        """이름이 틀린 주입은 호스트가 조용히 버린다 — 안 보내는 것과 화면에서 똑같이 생겼다."""
        for protocol in ("claude", "codex"):
            with self.subTest(protocol=protocol):
                sent = self._brief(protocol, "wire-" + protocol)
                self.assertEqual(sent["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
                self.assertIn(self._MARK, sent["hookSpecificOutput"]["additionalContext"])
        self.assertIn(self._MARK, self._brief("cursor", "wire-cursor")["additional_context"])

    def test_a_brief_with_no_open_question_says_nothing_to_the_model(self) -> None:
        """되돌려 주는 옛 답만 남은 회차에는 받아 적을 물음이 없다 — 통로를 열지 않는다."""
        recall = (
            "⠶ 들어가기 전 — 이 자리를 두고 **예전에 하신 답**이 있어요.\n"
            '  ↺ app.py — 3일 전 답\n    "그때 이렇게 했어요"'
        )
        sent = self._brief("claude", "recall", card=recall)

        self.assertEqual(list(sent), ["systemMessage"])
        self.assertEqual(self._told(sent), "")

    def test_the_scribe_protocol_comes_back_after_the_card_is_latched(self) -> None:
        """카드는 한 번만, 받아 적는 방법은 매 턴. 오딘이 답하는 턴은 물음을 본 턴 다음이다."""
        first = self._brief("claude", "latch")
        again = self._brief("claude", "latch")

        self.assertIn(self._ASK, str(first["systemMessage"]))
        self.assertEqual(list(again), ["hookSpecificOutput"], "같은 카드를 두 번 놓으면 세 번째부터 안 읽는다")
        self.assertIn(self._MARK, self._told(again))
        self.assertNotIn(self._ASK, self._told(again))


class TutorNoteClosingGuideTest(_HookCase):
    """대화를 닫는 자리 — 새 카드가 없는 Stop 에 세션당 한 번 놓는 모아 준 안내.

    이 층의 실측이 이 갈래를 만든 자리다: 이 저장소에서 튜터는 36번 묻고 답을 0번 받았다.
    사람이 한 번 쳐야 값이 생기는 절은 0으로 수렴하고, 화면에서는 정상 동작과 구분이 안 된다.
    안내는 반대 조건 위에 선다 — 아무것도 안 쳐도 읽을 것이 남아야 하고, 그래서 여기서 재는
    것은 "물었는가"가 아니라 "무엇이 실렸는가"다.
    """

    _RECAP = (
        "⠶ 되짚기 — 이번 세션에는 튜터가 4턴을 보았고, 변경은 +120행까지 쌓였어요.\n\n"
        "⠶ 답 없이 남은 것 — 열린 물음 2건이 그대로 남아 있어요."
    )
    _QUIET: dict[str, Any] = {"files": ["app.py"], "added": 3, "removed": 0}
    _BACK: dict[str, Any] = {"path": "old.py", "unit": "boot", "ask": "이 기본값은 왜 이 값인가요?", "cid": "ab12cd34"}
    _HUMAN = {"claude": "systemMessage", "codex": "systemMessage", "cursor": "followup_message"}

    def _stop(self, lesson: dict, sid: str, recap: str = "", protocol: str = "claude") -> str:
        """Stop 레인을 한 번 돌린 stdout 그대로 — 객체가 둘인지까지 봐야 해서 문자열로 돌려준다."""
        # Cursor payload 에는 세션 좌표가 없어 훅이 상수 `"cursor"` 로 접는다 — sentinel 도 그 이름이다.
        self._sentinel("cursor" if protocol == "cursor" else sid, ["app.py"])
        with (
            mock.patch.object(tutor_note, "_lesson", return_value=lesson),
            mock.patch.object(tutor_note, "_recap", return_value=recap),
            mock.patch.object(tutor_note.shutil, "which", return_value="/usr/bin/asgard"),
        ):
            code, out = _hook_payload("tutor_note", {"session_id": sid, "cwd": self.root}, [protocol])
        self.assertEqual(code, 0, "튜터는 규율이지 관문이 아니다 — 어떤 경우에도 0으로 끝난다")
        return out

    def test_a_stop_with_nothing_new_closes_the_session_with_a_guide(self) -> None:
        """물음도 설명도 없던 자리의 침묵이 안내 한 장이 된다 — 그 침묵이 곧 대화가 끝난 자리다."""
        card = json.loads(self._stop(self._QUIET, "quiet", recap=self._RECAP))["systemMessage"]

        self.assertIn("⠶ 마무리 안내 — 이번 세션에 파일 1개를 고쳤어요.", card)
        self.assertIn("  app.py", card)
        self.assertIn(
            "⠶ 답 없이 남은 것 — 열린 물음 2건이 그대로 남아 있어요.", card, "서사는 recap 레인이 만든 것 그대로다"
        )

    def test_the_guide_goes_out_once_a_session(self) -> None:
        """매 턴 끝에 다시 나가는 요약은 그 다음 것부터 안 읽힌다 — 래치 지문이 세션 표식이다."""
        first = self._stop(self._QUIET, "once", recap=self._RECAP)
        again = self._stop(self._QUIET, "once", recap=self._RECAP)

        self.assertIn("⠶ 마무리 안내", first)
        self.assertEqual(again, "", "두 번째 Stop 은 지금까지처럼 조용하다")

    def test_a_session_with_nothing_to_carry_keeps_its_one_shot(self) -> None:
        """실을 것이 없던 턴은 래치를 안 태운다 — 태우면 정작 마무리하는 턴이 침묵으로 닫힌다."""
        self.assertEqual(self._stop({}, "keep"), "", "경로 목록만 남은 회차는 빈 카드다")

        self.assertIn("⠶ 마무리 안내", self._stop(self._QUIET, "keep", recap=self._RECAP))

    def test_the_turn_that_repeats_a_card_gets_the_guide_instead(self) -> None:
        """두 번째 조기 종료 — 같은 카드를 다시 놓는 대신 그 물음들을 안내로 모아 준다."""
        lesson = dict(_LESSON, revisits=[self._BACK])

        card = json.loads(self._stop(lesson, "latch", recap=self._RECAP))["systemMessage"]
        self.assertIn("이 except 가 삼키는 실패는 누가 알게 되나요?", card, "첫 턴은 지금까지처럼 카드다")

        guide = json.loads(self._stop(lesson, "latch", recap=self._RECAP))["systemMessage"]
        self.assertIn("⠶ 마무리 안내", guide)
        self.assertIn("[ab12cd34]", guide)
        self.assertIn("이 기본값은 왜 이 값인가요?", guide)

    def test_the_question_never_reaches_the_model(self) -> None:
        """안내가 물음을 다시 실어도 모델 통로는 안 열린다 — 읽은 모델은 오딘 대신 답해 버린다.

        Stop 에서 모델에게 말하는 길은 `decision=block` 뿐이고 그것은 턴을 막는 자다. 튜터는
        관문이 아니라 이 레인에는 모델 통로가 아예 없어야 한다.
        """
        lesson = dict(_LESSON, revisits=[self._BACK])
        for protocol, field in self._HUMAN.items():
            with self.subTest(protocol=protocol):
                sid = "model-" + protocol
                self._stop(lesson, sid, recap=self._RECAP, protocol=protocol)  # 첫 턴은 카드
                out = self._stop(lesson, sid, recap=self._RECAP, protocol=protocol)

                self.assertEqual(
                    out.strip().count("\n"), 0, "stdout 에 JSON 객체가 둘이면 호스트가 파싱에 실패해 통째로 버린다"
                )
                sent = json.loads(out)
                self.assertEqual(list(sent), [field], "안내는 사람 통로 하나로만 나간다")
                self.assertIn(self._BACK["ask"], str(sent[field]), "물음은 사람 화면에 그대로 남는다")
                for piece in ("additionalContext", "additional_context", "hookSpecificOutput"):
                    self.assertNotIn(piece, out, "모델이 읽는 칸은 이 레인에 없다")

    def test_the_guide_reuses_the_recap_lane(self) -> None:
        """서사는 `asgard tutor --recap` 이 만든다 — 훅 안에 두 번째 요약기를 두면 화면이 갈린다."""
        run = mock.Mock(
            return_value=mock.Mock(stdout=json.dumps({"span": "session", "recap": self._RECAP}), returncode=0)
        )
        with mock.patch.object(tutor_note.subprocess, "run", run):
            body = tutor_note._recap("/usr/bin/asgard", self.root, "s9")

        self.assertEqual(body, self._RECAP)
        self.assertEqual(
            list(run.call_args.args[0]),
            ["/usr/bin/asgard", "tutor", "--recap", "--span", "session", "--sid", "s9", "--json"],
        )

    def test_a_recap_the_hook_cannot_read_costs_one_section_not_the_guide(self) -> None:
        """`asgard` 를 못 부르면 서사 절만 빠진다 — 나머지 두 절은 그대로 나간다 (fail-open)."""
        with mock.patch.object(tutor_note.subprocess, "run", side_effect=OSError("no asgard")):
            self.assertEqual(tutor_note._recap("/usr/bin/asgard", self.root, "s9"), "")

        card = tutor_note._guide(self._QUIET, ["app.py"], [self._BACK], "")
        self.assertIn("⠶ 마무리 안내", card)
        self.assertNotIn("⠶ 되짚기", card)

    def test_the_guide_names_eight_paths_and_counts_the_rest(self) -> None:
        """세션 하나가 마흔 곳을 건드려도 마흔 줄은 안내가 아니라 목록이다."""
        card = tutor_note._guide({}, ["f%d.py" % n for n in range(11)], [], self._RECAP)

        self.assertIn("파일 11개를 고쳤어요", card)
        self.assertIn("  f7.py", card)
        self.assertNotIn("  f8.py", card)
        self.assertIn("…외 3개", card)

    def test_the_guide_carries_the_reason_the_change_was_made(self) -> None:
        """왜 그렇게 했는지는 `_why` 가 이미 그린다 — 안내는 같은 줄을 그대로 넣는다."""
        rationale = {
            "quest_id": "q1",
            "request": "튜터 마무리 안내",
            "goals": ["침묵을 안내 한 장으로"],
            "evidence": [["uv run python -m pytest", 0]],
        }
        card = json.loads(self._stop(dict(self._QUIET, rationale=rationale), "why"))["systemMessage"]

        self.assertIn("⠶ 왜 이렇게 했는가 — 퀘스트 `q1`", card)
        self.assertIn("uv run python -m pytest (exit 0)", card)


class TutorNoteDeployedCopyTest(unittest.TestCase):
    """훅은 세 자리에 있다 — 패키지 정본과 클라이언트별 배포본. 갈리면 조용히 갈린다.

    이 저장소는 그렇게 물린 적이 있다: 사본 49개 중 9개가 이미 갈라져 있었는데 시험이 패키지
    배치만 태워서 아무도 못 봤다. 그래서 여기서는 파일을 **문자열로** 맞대 본다.
    """

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _SOURCE = os.path.join("src", "asgard", "hooks", "tutor_note.py")
    _DEPLOYED = os.path.join("hooks", "tutor-note.py")
    # 이 훅을 실제로 부르는 호스트들. 자리를 세는 대신 이름을 적는다 — 사본 하나가 사라지면 그
    # 호스트에서 되짚기가 통째로 꺼지는데, 개수만 보면 "원래 하나였다"와 구분이 안 된다.
    # 다만 이름이 곧 요구는 아니다: 이 저장소는 루트 .gitignore 가 `.claude` 를 통째로 가려서
    # 신규 체크아웃에 그 스캐폴드가 없다. 있는 것만 요구하지 않으면 사람 기계에서만 초록인
    # 시험이 된다 (26-08-20 CI 실측: 로컬 6147건 통과, 같은 커밋이 CI 에서 이 자로 빨갰다).
    _WIRED = (".claude", ".cursor", ".codex")

    def _read(self, rel: str) -> str:
        with open(os.path.join(self._ROOT, rel), encoding="utf-8") as handle:
            return handle.read()

    def test_every_deployed_copy_is_the_package_source(self) -> None:
        source = self._read(self._SOURCE)
        found = sorted(glob.glob(os.path.join(self._ROOT, ".*", self._DEPLOYED)))
        if not found:
            # 26-08-22 부터 이 저장소는 `.claude`·`.cursor`·`.codex` 를 전부 gitignore 한다 —
            # Claude Code 로만 개발하므로 교차도구 배선을 커밋하지 않는다. 그래서 깨끗한
            # 체크아웃에는 견줄 배포본이 한 벌도 없고, 그 상태는 "자리 규약이 바뀌었다" 와
            # 구분되지 않는다. 배포 계약 자체는 `tests/test_mode_parity.py` 의
            # `test_the_deployed_hook_copies_match_the_source` 가 `hook_files` 를 기준으로 잰다.
            self.skipTest("배포본이 gitignore 라 깨끗한 체크아웃에는 견줄 사본이 없어요")

        for host in self._WIRED:
            if not os.path.isdir(os.path.join(self._ROOT, host, "hooks")):
                continue  # 이 체크아웃이 안 들고 있는 스캐폴드 — 전체 실종은 위 assertTrue 가 잡는다
            self.assertIn(os.path.join(self._ROOT, host, self._DEPLOYED), found, "%s 배포본이 사라졌다" % host)
        for path in found:
            rel = os.path.relpath(path, self._ROOT)
            with self.subTest(copy=rel):
                self.assertEqual(self._read(rel), source, "%s 가 패키지 정본과 갈라졌다" % rel)


if __name__ == "__main__":
    unittest.main()
