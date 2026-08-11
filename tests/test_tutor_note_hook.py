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


if __name__ == "__main__":
    unittest.main()
