"""단계 표면 판정 앵커 — `asgard tutor` 로 **단계·기준·다음 물음·승급을 읽고 쓰는가**.

실행: uv run pytest tests/test_tutor_level.py

**파일 이름이 모듈 이름과 다른 이유.** 판정 대상 엔진은 `asgard.tutor_track` 이다. 퀘스트
`tutor-alter-1on1-260820` 이 이 시험의 경로를 `tests/test_tutor_level.py` 로 기준에 적었고
기준은 개봉 뒤 고정인데, 그 뒤 모듈 이름이 `tutor_level` 에서 `tutor_track` 으로 바뀌었다 —
`tutor_growth.level(data, kind)`(`src/asgard/tutor_growth.py:344`)가 **물음 종류** 축에서 이미
`level` 을 쓰고 있어서, 사람 축을 재는 모듈이 같은 이름을 가지면 두 축이 한 이름에 얹히기
때문이다. 그 충돌은 파이썬 심볼 축의 것이고 시험 파일 이름은 그 축에 안 들어간다. 그래서 이름은
기준이 부르는 대로 두고, 무엇을 재는지는 이 문단이 진다.

**여기가 지는 것은 배치가 아니라 배선이다.** 단계를 정하는 규칙(`place`·`grade`·`pick_exam`)은
`tests/test_tutor_track.py` 가 엔진 층에서 문다. 이 파일은 그 결론이 **화면과 JSON 까지 그대로
오는가**만 본다. 둘을 한 파일에 두면 화면 시험이 엔진을 다시 판정하게 되고, 그러면 엔진을 고칠
때마다 화면 시험이 같이 빨개져 어느 쪽이 깨졌는지 못 가린다.

같이 고정하는 계약 둘: ① 어휘는 엔진이 갖는다 — 화면이 단계 이름이나 기준 문장을 스스로 지으면
같은 판정이 두 이름으로 불린다. ② 종료 코드는 언제나 0 — 기록이 비어도, 트랙이 0개여도, 엔진이
없거나 던져도. 되짚기가 통과/실패를 만들기 시작하면 그 순간 관문이 된다.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from unittest import mock

from asgard import tutor_growth, tutor_track


def _track_module(placed=None, exam=("", ""), verdict=(False, 0, 0, ()), error: Exception | None = None):
    """`asgard.tutor_track` 대역 — 상수까지 진짜 모듈에서 떠 온다.

    화면이 통과선과 상한을 엔진 상수로 읽으므로, 대역이 그 값을 손으로 다시 적으면 이 시험은
    화면이 아니라 사본을 재게 된다.
    """
    module = types.ModuleType("asgard.tutor_track")

    def place(root: str, now=None):
        if error is not None:
            raise error
        return placed

    setattr(module, "place", place)  # ModuleType 에 동적으로 다는 자리라 대입 대신 setattr
    setattr(module, "pick_exam", lambda root, track: exam)
    setattr(module, "grade", lambda root, track, answer: verdict)
    for name in ("EXAM_MIN", "EXAM_CAP", "PASS_NUM", "PASS_DEN"):
        setattr(module, name, getattr(tutor_track, name))
    return mock.patch.dict(sys.modules, {"asgard.tutor_track": module})


def _placed(rung: str = "first", track: str = "src/asgard", **extra):
    """`place()` 산출 하나 — 화면에 뜨는 문장은 진짜 엔진에서 떠 온다."""
    count = tutor_track.Count(asked=3, deep=1)
    row = {
        "track": track,
        "rung": rung,
        "bar": tutor_track.bar(rung),
        "asked": count.asked,
        "deep": count.deep,
        "open": 1,
        "kinds": [],
        "next_bar": tutor_track.BARS[tutor_track.RUNGS[tutor_track.RUNGS.index(rung) + 1]],
        "remaining": tutor_track.remaining(count, rung, False),
        "exam_passed": False,
    }
    return {"tracks": [row], "mission": "", "active": [track], "notes": [], **extra}


class TrackLaneTest(unittest.TestCase):
    """`--track` — 지금 어느 영역까지 갔나. 화면이 지는 것은 배치가 아니라 **배선**이다."""

    def _run(self, **kwargs) -> str:
        from asgard.commands.tutor import run_tutor

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(run_tutor(**kwargs), 0)
        return out.getvalue()

    def test_the_lane_runs_without_a_state_file_and_invents_no_track(self):
        """기록이 하나도 없는 저장소에서 부르는 것이 첫 호출의 모양이다 — 여기서 죽으면 아무도 안 켠다."""
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            stack.enter_context(contextlib.chdir(root))
            text = self._run(track=True)
            data = json.loads(self._run(track=True, json_out=True))
        self.assertIn("아직 트랙이 없어요", text)
        self.assertEqual(data["tracks"], [])
        self.assertTrue(data["notes"], "못 본 것을 안 적으면 0건과 안 봤다가 화면에서 같아진다")

    def test_the_screen_carries_the_next_rungs_bar_and_what_is_missing(self):
        """오딘이 요청한 기준 제시가 이 화면의 몫이다 — 지금 단계만 그리면 점수판이지 사다리가 아니다."""
        placed = _placed()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.chdir(stack.enter_context(tempfile.TemporaryDirectory())))
            stack.enter_context(_track_module(placed))
            text = self._run(track=True)
        row = placed["tracks"][0]
        for piece in (row["track"], row["rung"], row["bar"], row["next_bar"], row["remaining"]):
            self.assertIn(piece, text)

    def test_the_vocabulary_comes_from_the_engine_not_from_the_surface(self):
        """단계 이름과 기준 문장을 표면이 다시 만들면 두 화면이 같은 트랙을 다르게 부른다."""
        placed = _placed()
        placed["tracks"][0]["bar"] = "엔진이 정한 문장"
        placed["tracks"][0]["next_bar"] = "엔진이 정한 다음 문장"
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.chdir(stack.enter_context(tempfile.TemporaryDirectory())))
            stack.enter_context(_track_module(placed))
            text = self._run(track=True)
        self.assertIn("엔진이 정한 문장", text)
        self.assertIn("엔진이 정한 다음 문장", text)
        self.assertNotIn(tutor_track.BARS["familiar"], text)

    def test_the_notes_and_the_mission_reach_the_screen(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.chdir(stack.enter_context(tempfile.TemporaryDirectory())))
            stack.enter_context(_track_module(_placed(mission="캐시 계층을 걷어낸다", notes=["경로가 없는 물음 2건"])))
            text = self._run(track=True)
        self.assertIn("캐시 계층을 걷어낸다", text)
        self.assertIn("경로가 없는 물음 2건", text)

    def test_the_json_is_the_placement_verbatim(self):
        """훅과 화면이 같은 산출을 읽는다 — 표면이 칸을 골라 담으면 훅 카드가 조용히 빈다."""
        placed = _placed()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.chdir(stack.enter_context(tempfile.TemporaryDirectory())))
            stack.enter_context(_track_module(placed))
            self.assertEqual(json.loads(self._run(track=True, json_out=True)), placed)

    def test_a_missing_or_dead_engine_leaves_the_lane_at_zero(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.chdir(stack.enter_context(tempfile.TemporaryDirectory())))
            with _track_module(error=RuntimeError("boom")):
                self.assertIn("이번엔 배치를 못 했어요", self._run(track=True))
                self.assertEqual(self._run(track=True, json_out=True).strip(), "null")
            with mock.patch.dict(sys.modules, {"asgard.tutor_track": None}):
                self.assertIn("기능이 아직 없어요", self._run(track=True))


class ExamLaneTest(unittest.TestCase):
    """`--exam` — 오딘이 직접 치는 승급 시험. 채점하는 유일한 표면이고, 카드 물음과는 다른 자리다."""

    def _run(self, **kwargs) -> str:
        from asgard.commands.tutor import run_tutor

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(run_tutor(**kwargs), 0)
        return out.getvalue()

    def test_the_bare_call_puts_the_question_on_screen(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.chdir(stack.enter_context(tempfile.TemporaryDirectory())))
            stack.enter_context(_track_module(exam=("`review`를 부르는 자리를 적어 볼까요?", "tutor.review")))
            text = self._run(exam="src/asgard")
        self.assertIn("`review`를 부르는 자리를 적어 볼까요?", text)

    def test_a_track_with_no_exam_says_so_instead_of_inventing_one(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.chdir(stack.enter_context(tempfile.TemporaryDirectory())))
            stack.enter_context(_track_module())
            self.assertIn("아직 낼 시험이 없어요", self._run(exam="없는트랙"))

    def test_the_grade_screen_carries_both_limits(self):
        """한계를 안 적으면 채점이 전지해 보인다 — 이름으로 찾은 후보라 동적 호출은 못 본다."""
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.chdir(stack.enter_context(tempfile.TemporaryDirectory())))
            stack.enter_context(_track_module(verdict=(False, 2, 5, ["src/asgard/cli/root.py"])))
            text = self._run(exam="src/asgard", answer="src/asgard/tutor.py")
        from asgard.commands.tutor.labels import _EXAM_BLIND

        self.assertIn("물은 5곳 중 2곳", text)
        self.assertIn("src/asgard/cli/root.py", text)
        self.assertIn(str(tutor_track.EXAM_CAP), text)
        self.assertIn(_EXAM_BLIND, text)

    def test_a_pass_is_said_as_a_pass(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.chdir(stack.enter_context(tempfile.TemporaryDirectory())))
            stack.enter_context(_track_module(verdict=(True, 4, 5, [])))
            self.assertIn("통과예요", self._run(exam="src/asgard", answer="a.py b.py"))

    def test_an_exam_answer_does_not_close_a_checkpoint(self):
        """같은 `--answer`가 뜻이 둘이라 갈래 순서가 계약이다 — 아래로 내리면 시험 답이 물음 닫기로 샌다."""
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.chdir(stack.enter_context(tempfile.TemporaryDirectory())))
            stack.enter_context(_track_module(verdict=(False, 1, 5, [])))
            close = stack.enter_context(mock.patch.object(tutor_growth, "answer", return_value=(True, "닫았어요")))
            text = self._run(exam="src/asgard", answer="src/asgard/tutor.py")
        close.assert_not_called()
        self.assertIn("승급 시험 채점", text)

    def test_a_bare_answer_still_closes_a_checkpoint(self):
        """음성 대조군 — `--exam` 없이 준 `--answer`는 종전 그대로 물음을 닫는 통로다."""
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.chdir(stack.enter_context(tempfile.TemporaryDirectory())))
            close = stack.enter_context(mock.patch.object(tutor_growth, "answer", return_value=(True, "닫았어요")))
            text = self._run(answer="ab12cd", note="이래서 이렇게 뒀어요")
        close.assert_called_once()
        self.assertIn("물음 닫기", text)


if __name__ == "__main__":
    unittest.main()
