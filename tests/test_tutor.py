"""되짚기 판정 앵커 — 탐침마다 **물을 자리 하나와 안 물 자리 하나**를 짝으로 못박는다.

실행: uv run pytest tests/test_tutor.py

이 층은 아무것도 막지 않는다. 그래서 실패 방식이 게이트와 다르다: 게이트가 오탐을 내면 사람이
게이트를 끄지만, 튜터가 오탐을 내면 사람은 **끄지 않고 그냥 안 읽는다**. 끈 것은 눈에 보이고 안
읽는 것은 안 보이므로, 이쪽이 더 조용히 죽는다. 그래서 음성 대조군이 여기서는 더 중요하다.

같이 고정하는 계약 둘: ① 래칫 — base에 이미 있던 물음은 다시 묻지 않는다. ② 종료 코드는
언제나 0 — 되짚기가 통과/실패를 만들기 시작하면 그 순간 관문이 된다.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from asgard import tutor, tutor_growth, tutor_probes, tutor_teach

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _signal(name: str, level: int = 2, fact: str = "13턴", why: str = "검토가 밀린다", source: str = "test"):
    return types.SimpleNamespace(name=name, level=level, fact=fact, why=why, source=source)


def _ledger(signals=(), open_debt: int = 0, oldest_days: int = 0, turns: int = 0, added: int = 0):
    return types.SimpleNamespace(
        signals=tuple(signals), open_debt=open_debt, oldest_days=oldest_days, turns=turns, added=added
    )


@dataclasses.dataclass(frozen=True)
class _Term:
    name: str
    where: str
    gloss: str
    source: str


@dataclasses.dataclass(frozen=True)
class _Step:
    order: int
    path: str
    line: int
    unit: str
    what: str
    why_here: str


@dataclasses.dataclass(frozen=True)
class _Explanation:
    base: str
    depth: str
    mission: str
    steps: tuple[_Step, ...]
    terms: tuple[_Term, ...]
    checks: tuple[str, ...]
    recall: tuple[str, ...]
    gaps: tuple[tuple[str, str], ...]


def _explanation(depth: str = "first"):
    """`tutor_teach.explain()`이 돌려주기로 한 모양 — 표면은 이 모양만 알면 된다(공유 SPEC)."""
    return _Explanation(
        base="HEAD",
        depth=depth,
        mission="캐시 계층을 걷어낸다",
        steps=(_Step(1, "src/asgard/tutor.py", 42, "review", "diff를 물음으로 바꾼다", "여기부터 값이 생긴다"),),
        terms=(_Term("래칫", "src/asgard/tutor.py:88", "이미 있던 물음은 다시 안 묻는 규칙", "docstring"),),
        checks=("python -m pytest tests/test_tutor.py -q",),
        recall=("이 변경이 없으면 무엇이 깨지나요?",),
        gaps=(("src/asgard/ui.py", "설명 대상이 아니다"),),
    )


def _teach_module(explanation=None, error: Exception | None = None):
    module = types.ModuleType("asgard.tutor_teach")
    store: dict[str, str] = {}

    def explain(root: str, base: str = "HEAD", paths=(), depth: str = ""):
        if error is not None:
            raise error
        return explanation

    setattr(module, "explain", explain)
    setattr(module, "mission", lambda root: store.get(root, ""))
    setattr(module, "set_mission", lambda root, text: store.setdefault(root, text))
    return mock.patch.dict(sys.modules, {"asgard.tutor_teach": module})


def _debt_module(ledger=None, error: Exception | None = None):
    module = types.ModuleType("asgard.tutor_debt")

    def run(root: str, sid: str = "", now: float | None = None):
        if error is not None:
            raise error
        return ledger

    setattr(module, "ledger", run)  # ModuleType 에 동적으로 다는 자리라 대입 대신 setattr
    return mock.patch.dict(sys.modules, {"asgard.tutor_debt": module})


class SwallowProbeTest(unittest.TestCase):
    """설명 없는 삼킴만 묻는다 — 이 저장소는 fail-open을 의도적으로 쓴다."""

    def test_an_unexplained_swallow_is_asked_about(self):
        src = "def f():\n    try:\n        g()\n    except OSError:\n        pass\n"
        self.assertEqual(len(tutor_probes.swallows(src)), 1)

    def test_a_swallow_with_a_written_reason_is_not_asked_about(self):
        """저자가 이유를 적어 둔 자리는 이미 답한 자리다 — 다시 물으면 그게 오탐이다."""
        src = "def f():\n    try:\n        g()\n    except OSError:\n        pass  # 관측용 — 실행을 막지 않는다\n"
        self.assertEqual(tutor_probes.swallows(src), {})

    def test_a_handler_that_does_something_is_not_a_swallow(self):
        src = "def f():\n    try:\n        g()\n    except OSError:\n        return None\n"
        self.assertEqual(tutor_probes.swallows(src), {})

    def test_a_reason_on_the_line_above_also_counts_as_answered(self):
        src = "def f():\n    try:\n        g()\n    # 없는 파일은 정상 — 첫 실행\n    except OSError:\n        pass\n"
        self.assertEqual(tutor_probes.swallows(src), {})


class ImportProbeTest(unittest.TestCase):
    def test_a_third_party_import_is_asked_about(self):
        self.assertIn("requests", tutor_probes.imports("import requests\n"))

    def test_the_standard_library_is_not_a_new_dependency(self):
        """표준 라이브러리를 의존 결정이라 부르면 매 파일이 물음 하나를 달고 온다."""
        self.assertEqual(tutor_probes.imports("import os, json, subprocess\nfrom pathlib import Path\n"), {})

    def test_a_relative_import_is_not_external(self):
        self.assertEqual(tutor_probes.imports("from . import craft\nfrom .health import _read\n"), {})


class MarkProbeTest(unittest.TestCase):
    def test_a_new_todo_is_carried_to_the_reader(self):
        found = tutor_probes.marks("x = 1  # " + "TODO" + ": wire the retry\n", "m.py")
        self.assertEqual(list(found), ["TODO:wire the retry"])

    def test_a_mark_inside_a_string_literal_is_not_a_mark(self):
        """실측 오탐 1번 — 정규식으로 훑으면 이 테스트 파일 자체가 표식 더미가 된다."""
        src = 'label = "' + "TODO" + ': later"\nprint("' + "FIXME" + ' me")\n'
        self.assertEqual(tutor_probes.marks(src, "m.py"), {})

    def test_a_non_python_file_still_gets_a_best_effort_read(self):
        """파서 없는 언어를 침묵으로 두면 표식이 언어별로 있다 없다 한다 — 한계는 적되 포기는 안 한다."""
        self.assertEqual(list(tutor_probes.marks("int x; // " + "FIXME" + ": overflow\n", "m.c")), ["FIXME:overflow"])


class TestPathProbeTest(unittest.TestCase):
    def test_a_test_tree_path_is_recognised(self):
        self.assertTrue(tutor_probes.is_test_path("tests/test_tutor.py"))
        self.assertTrue(tutor_probes.is_test_path("src/pkg/__tests__/thing.js"))

    def test_a_source_path_that_merely_mentions_testing_is_not_a_test(self):
        """`pandas.testing`처럼 진짜 패키지 이름이 있다 — 남의 표면을 테스트로 세면 물음이 사라진다."""
        self.assertFalse(tutor_probes.is_test_path("src/asgard/testing_utils.py"))
        self.assertFalse(tutor_probes.is_test_path("src/latest/thing.py"))


class ReviewTest(unittest.TestCase):
    """실제 git 저장소 위에서 래칫과 인벤토리를 확인한다 — 래칫은 본문이 아니라 이력에 걸린다."""

    def _repo(self, stack) -> str:
        root = stack.enter_context(tempfile.TemporaryDirectory())
        for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=root, check=True, env=_ENV, capture_output=True)
        return root

    def _commit(self, root: str) -> None:
        subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=_ENV, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True, env=_ENV, capture_output=True)

    def _write(self, root: str, rel: str, text: str) -> None:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def _kinds(self, lesson: tutor.Lesson) -> set[str]:
        return {point.kind for point in lesson.checkpoints}

    def test_an_inherited_swallow_is_not_asked_again(self):
        """물음도 부채다 — 매 턴 같은 것을 물으면 세 번째부터 아무도 안 읽는다."""
        old = "def f():\n    try:\n        g()\n    except OSError:\n        pass\n"
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            self._write(root, "m.py", old)
            self._commit(root)
            self.assertNotIn("silent-failure", self._kinds(tutor.review(root, "HEAD", ["m.py"])))

            self._write(root, "m.py", old + "\ndef h():\n    try:\n        g()\n    except ValueError:\n        pass\n")
            self.assertIn("silent-failure", self._kinds(tutor.review(root, "HEAD", ["m.py"])))

    def test_a_removed_function_is_asked_about(self):
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            self._write(root, "m.py", "def keep():\n    return 1\n\n\ndef drop():\n    return 2\n")
            self._commit(root)
            self._write(root, "m.py", "def keep():\n    return 1\n")
            lesson = tutor.review(root, "HEAD", ["m.py"])
            self.assertIn("behavior-removed", self._kinds(lesson))
            self.assertEqual(lesson.files[0].units_removed, ("drop",))

    def test_a_removed_test_asks_a_different_question_than_removed_code(self):
        """판정이 사라진 것과 기능이 사라진 것은 diff에서 똑같이 보인다 — 물음이 달라야 한다."""
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            self._write(root, "tests/test_m.py", "def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 2\n")
            self._commit(root)
            self._write(root, "tests/test_m.py", "def test_a():\n    assert 1\n")
            self.assertIn("test-removed", self._kinds(tutor.review(root, "HEAD", ["tests/test_m.py"])))

    def test_the_repos_own_package_is_not_a_new_dependency(self):
        """자기 나무를 남이라 부르는 물음은 한 번이면 신뢰를 잃는다 (실측 오탐)."""
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            self._write(root, "src/mypkg/__init__.py", "")
            self._write(root, "tests/test_m.py", "x = 1\n")
            self._commit(root)
            self._write(root, "tests/test_m.py", "from mypkg import thing\n")
            self.assertNotIn("new-dependency", self._kinds(tutor.review(root, "HEAD", ["tests/test_m.py"])))

    def test_a_document_is_inventoried_but_not_called_unjudged(self):
        """문서·설정이 미판정 목록을 채우면 진짜 못 읽은 코드가 그 속에 묻힌다."""
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            self._write(root, "README.md", "# hi\n")
            self._commit(root)
            self._write(root, "README.md", "# hi\n\nmore\n")
            lesson = tutor.review(root, "HEAD", ["README.md"])
            self.assertEqual(lesson.undetermined, ())
            self.assertFalse(lesson.files[0].code)

    def test_a_brand_new_file_reports_its_real_size(self):
        """추적 안 되는 새 파일은 numstat에 없다 — 0으로 두면 가장 큰 변경이 가장 작아 보인다."""
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            self._write(root, "seed.py", "x = 1\n")
            self._commit(root)
            self._write(root, "fresh.py", "def a():\n    return 1\n")
            lesson = tutor.review(root, "HEAD", ["fresh.py"])
            self.assertTrue(lesson.files[0].new_file)
            self.assertEqual(lesson.files[0].added, 2)

    def test_moving_a_function_down_is_not_a_change(self):
        """위에서 함수가 늘면 아래 전부가 밀린다 — 줄로 대조하면 안 건드린 자리가 전부 새것이 된다."""
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            self._write(root, "m.py", "def a():\n    return 1\n")
            self._commit(root)
            self._write(root, "m.py", "def z():\n    return 0\n\n\ndef a():\n    return 1\n")
            lesson = tutor.review(root, "HEAD", ["m.py"])
            self.assertEqual(lesson.files[0].units_changed, ())
            self.assertEqual(lesson.files[0].units_added, ("z",))


class ScopeTest(unittest.TestCase):
    """경로를 지목받으면 그 밖은 안 묻는다 — 훅은 "이 세션이 쓴 것"만 넘긴다."""

    def test_a_named_scope_does_not_ask_about_other_files(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
                subprocess.run(["git", *args], cwd=root, check=True, env=_ENV, capture_output=True)
            for rel in ("mine.py", "theirs.py"):
                with open(os.path.join(root, rel), "w", encoding="utf-8") as handle:
                    handle.write("def public_thing(a):\n    return a\n")
            subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=_ENV, capture_output=True)
            subprocess.run(["git", "commit", "-qm", "b"], cwd=root, check=True, env=_ENV, capture_output=True)
            for rel in ("mine.py", "theirs.py"):  # 양쪽 다 계약을 깬다
                with open(os.path.join(root, rel), "w", encoding="utf-8") as handle:
                    handle.write("def public_thing(a, b):\n    return a\n")

            scoped = tutor.review(root, "HEAD", ["mine.py"])
            self.assertEqual(
                {p.path for p in scoped.checkpoints}, {"mine.py"}, "남의 빚을 이 턴의 물음으로 돌려주면 안 된다"
            )
            self.assertIn("theirs.py", {p.path for p in tutor.review(root, "HEAD").checkpoints})


class SurfaceTest(unittest.TestCase):
    def test_a_checkpoint_ranks_a_broken_contract_above_a_todo(self):
        """사람의 눈은 유한하다 — 순위가 없으면 스무 개는 영 개와 같다."""
        self.assertGreater(tutor.WEIGHT["contract-break"], tutor.WEIGHT["todo-left"])

    def test_every_kind_carries_a_weight(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
                subprocess.run(["git", *args], cwd=root, check=True, env=_ENV, capture_output=True)
            with open(os.path.join(root, "m.py"), "w", encoding="utf-8") as handle:
                handle.write("import requests  # TODO: drop this\n")
            for point in tutor.review(root, "HEAD", ["m.py"]).checkpoints:
                self.assertGreater(point.weight, 0, f"{point.kind} 에 순위가 없다 — 순위 없는 판정은 맨 뒤로 밀린다")


class TurnNoteTest(unittest.TestCase):
    """네이티브 루프 도달 경로 — 훅이 없는 단일 프로세스에서도 물음이 사용자에게 닿아야 한다."""

    def _repo_with_writes(self, stack) -> str:
        root = stack.enter_context(tempfile.TemporaryDirectory())
        for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=root, check=True, env=_ENV, capture_output=True)
        with open(os.path.join(root, "m.py"), "w", encoding="utf-8") as handle:
            handle.write("def f():\n    try:\n        g()\n    except OSError:\n        pass\n")
        state = os.path.join(root, ".asgard", "state")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "writes-q1.json"), "w", encoding="utf-8") as handle:
            handle.write('["m.py"]')
        return root

    def test_a_turn_that_wrote_code_gets_a_card(self):
        with contextlib.ExitStack() as stack:
            root = self._repo_with_writes(stack)
            self.assertIn("되짚기", tutor.turn_note(root, "q1"))

    def test_the_same_questions_are_not_repeated_next_turn(self):
        """카드가 매 턴 나오면 셋째 턴부터 안 읽힌다 — 안 읽히는 것은 꺼진 것보다 조용히 죽는다."""
        with contextlib.ExitStack() as stack:
            root = self._repo_with_writes(stack)
            self.assertTrue(tutor.turn_note(root, "q1"))
            self.assertEqual(tutor.turn_note(root, "q1"), "")

    def test_the_native_card_banks_the_words_it_showed(self):
        """네이티브 루프만 도는 세션은 `asgard tutor`를 안 거친다 — 여기서 안 적으면 용어집이
        영영 안 쌓이고 설명은 회차마다 같은 길이로 나온다(`tutor_teach` 계약 ③).
        """
        with contextlib.ExitStack() as stack:
            root = self._repo_with_writes(stack)
            for args in (["add", "-A"], ["commit", "-qm", "base"]):
                subprocess.run(["git", *args], cwd=root, check=True, env=_ENV, capture_output=True)
            with open(os.path.join(root, "m.py"), "a", encoding="utf-8") as handle:
                handle.write('\n\ndef steam(cup):\n    """우유를 데워요."""\n    return cup\n')
            subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=_ENV, capture_output=True)
            self.assertIn("`steam`", tutor.turn_note(root, "q1"))
            self.assertEqual(tutor_teach.glossary_known(root), {"steam"})

    def test_a_turn_that_wrote_nothing_is_silent(self):
        with contextlib.ExitStack() as stack:
            root = self._repo_with_writes(stack)
            self.assertEqual(tutor.turn_note(root, "no-such-quest"), "")
            self.assertEqual(tutor.turn_note(root, None), "")


class MidTurnTipsTest(unittest.TestCase):
    """작업 도중 팁은 빚 신호가 있을 때만, 같은 세션에는 한 번만 나온다."""

    def test_a_fresh_session_is_silent(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(tutor.tips(root, "fresh", now=1000.0), [])

    def test_a_debt_signal_emits_one_question_and_latches(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            debt = _ledger([_signal("session-load", fact="13턴이 쌓였다")])
            with _debt_module(debt):
                first = tutor.tips(root, "s1", now=1000.0)
                self.assertEqual(len(first), 1)
                self.assertIn("⠶ 도중 점검 — 세션 부하: 13턴이 쌓였다", first[0])
                self.assertIn("    ▸ 다음 변경 전에", first[0])
                self.assertEqual(tutor.tips(root, "s1", now=1001.0), [])
                self.assertEqual(len(tutor.tips(root, "s2", now=1001.0)), 1)

    def test_a_corrupt_latch_fails_open_then_latches(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            path = os.path.join(root, tutor.TIPS_REL)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{broken")
            with _debt_module(_ledger([_signal("session-load")])):
                self.assertEqual(len(tutor.tips(root, "s1", now=1000.0)), 1)
                self.assertEqual(tutor.tips(root, "s1", now=1001.0), [])

    def test_safe_or_missing_debt_is_silent(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            with _debt_module(_ledger([_signal("session-load", level=0)])):
                self.assertEqual(tutor.tips(root, "s1", now=1000.0), [])
            with _debt_module(error=RuntimeError("not ready")):
                self.assertEqual(tutor.tips(root, "s1", now=1000.0), [])

    def test_a_tip_asks_for_posture_without_explaining_the_answer(self):
        with tempfile.TemporaryDirectory() as root:
            signal = _signal("review-ratio", why="이 해설은 카드에 나오면 안 돼요", source="secret-source")
            with _debt_module(_ledger([signal])):
                card = tutor.tips(root, "s1", now=1000.0)[0]
        self.assertTrue(card.splitlines()[-1].endswith("?"))
        self.assertNotIn(signal.why, card)
        self.assertNotIn(signal.source, card)

    def test_cap_keeps_the_worst_signal_only(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            debt = _ledger(
                [
                    _signal("unanswered-backlog", level=1, fact="9건"),
                    _signal("review-ratio", level=2, fact="답 1건당 430행"),
                ]
            )
            with _debt_module(debt):
                cards = tutor.tips(root, "s1", cap=1, now=1000.0)
        self.assertEqual(len(cards), 1)
        self.assertIn("검토 비율", cards[0])
        self.assertNotIn("답 없는 물음", cards[0])


class RecapTest(unittest.TestCase):
    """recap은 숫자판이 아니라 남은 물음과 부채 위치를 드러내는 서사다."""

    def _open_question(self, root: str, now: float = 1000.0) -> None:
        tutor.record(
            root,
            [
                {
                    "kind": "silent-failure",
                    "path": "app.py",
                    "unit": "load",
                    "key": "OSError@load",
                    "ask": "이 실패는 사용자 화면에 어떻게 보이나요?",
                }
            ],
            now=now,
        )

    def test_recap_has_work_unanswered_and_debt_paragraphs(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            self._open_question(root, now=1000.0)
            debt = _ledger(
                [_signal("review-ratio", fact="답 1건당 430행", why="검토보다 생성이 빨라요", source="debt.json")],
                open_debt=1,
                oldest_days=2,
                turns=3,
                added=120,
            )
            with _debt_module(debt):
                text = tutor.recap(root, "s1", now=1000.0 + 2 * tutor_growth.DAY)
        self.assertEqual(len(text.split("\n\n")), 3)
        self.assertIn("⠶ 되짚기 — 이번 세션에는 튜터가 3턴을 보았고", text)
        self.assertIn("⠶ 답 없이 남은 것 — 열린 물음 1건", text)
        self.assertIn("app.py load", text)
        self.assertIn("이 실패는 사용자 화면에 어떻게 보이나요?", text)
        self.assertIn("⠶ 부채 위치 — 지금 가장 큰 신호는 검토 비율 쪽이에요: 답 1건당 430행.", text)
        self.assertIn("근거는 검토보다 생성이 빨라요.", text)
        self.assertNotIn("요예요", text)

    def test_recap_marks_debt_unavailable_when_debt_is_missing(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            self._open_question(root)
            with _debt_module(error=RuntimeError("not ready")):
                text = tutor.recap(root, "s1", now=1000.0)
        self.assertEqual(len(text.split("\n\n")), 3)
        self.assertIn("⠶ 부채 위치 — 부채 계측을 읽지 못했어요", text)

    def test_session_day_and_week_use_different_work_windows(self):
        now = 10 * tutor_growth.DAY
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            for index, closed_at in enumerate((now - 3 * tutor_growth.DAY, now - tutor_growth.DAY / 2)):
                self._open_question(root, now=closed_at - 10 - index)
                key = next(iter(tutor_growth.load(root)["open"]))
                tutor_growth.answer(root, key, "왜 닫아도 되는지 직접 설명한 충분히 긴 답이에요", now=closed_at)
            with _debt_module(_ledger(turns=3, added=120)):
                texts = {span: tutor.recap(root, "s1", span=span, now=now) for span in ("session", "day", "week")}
        self.assertEqual(len(set(texts.values())), 3)
        self.assertIn("이번 세션에는 튜터가 3턴을 보았고", texts["session"])
        self.assertIn("오늘에는 물음 1건이 닫혔어요", texts["day"])
        self.assertIn("이번 주에는 물음 2건이 닫혔어요", texts["week"])

    def test_missing_tutor_debt_module_is_fail_open(self):
        with tempfile.TemporaryDirectory() as root:
            self._open_question(root)
            with mock.patch.object(tutor.importlib, "import_module", side_effect=ModuleNotFoundError("missing")):
                self.assertEqual(tutor.tips(root, "s1", now=1000.0), [])
                text = tutor.recap(root, "s1", now=1000.0)
        self.assertEqual(len(text.split("\n\n")), 3)
        self.assertIn("부채 계측을 읽지 못했어요", text)

    def test_empty_or_unknown_span_is_silent(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            with _debt_module(_ledger()):
                self.assertEqual(tutor.recap(root, "s1", now=1000.0), "")
                self.assertEqual(tutor.recap(root, "s1", span="month", now=1000.0), "")


class ReportLaneTest(unittest.TestCase):
    """`--json`과 `--report`를 같이 준 호출. 훅이 언제나 그렇게 부르므로 여기가 실사용 경로다."""

    def _repo(self, stack) -> str:
        root = stack.enter_context(tempfile.TemporaryDirectory())
        for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=root, check=True, env=_ENV, capture_output=True)
        with open(os.path.join(root, "m.py"), "w", encoding="utf-8") as handle:
            handle.write("import requests\n\n\ndef f(a, b):\n    return a\n")
        stack.enter_context(contextlib.chdir(root))
        return root

    def _run(self, **kwargs) -> str:
        from asgard.commands.tutor import run_tutor

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(run_tutor(**kwargs), 0)
        return out.getvalue()

    def test_json_and_report_together_still_write_the_file(self):
        """실측 결함: `--json`이 먼저 돌아서서 보고서가 8일간 안 갱신됐다. 훅 카드가 가리키는 자리다."""
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            body = self._run(json_out=True, report=True, paths=("m.py",))
            written = os.path.join(root, ".asgard", "tutor", "last-review.md")
            self.assertTrue(os.path.exists(written), "--json --report로 불렀는데 보고서가 안 생겼다")
            self.assertEqual(json.loads(body)["report"], os.path.join(".asgard", "tutor", "last-review.md"))

    def test_the_json_keys_the_hook_reads_stay(self):
        with contextlib.ExitStack() as stack:
            self._repo(stack)
            data = json.loads(self._run(json_out=True, paths=("m.py",)))
            for key in ("base", "files", "added", "removed", "checkpoints", "revisits", "undetermined", "mandate"):
                self.assertIn(key, data)
            self.assertIn("explain", data)

    def test_the_explain_slot_is_null_when_the_engine_is_missing(self):
        """표면이 엔진보다 먼저 배송될 수 있다 — 그때 훅이 받는 값은 예외가 아니라 null이다."""
        with contextlib.ExitStack() as stack:
            self._repo(stack)
            stack.enter_context(mock.patch.dict(sys.modules, {"asgard.tutor_teach": None}))
            self.assertIsNone(json.loads(self._run(json_out=True, paths=("m.py",)))["explain"])

    def test_nothing_to_review_writes_no_report(self):
        """되짚을 게 없을 때까지 쓰면 빈 보고서가 직전에 쓴 진짜 보고서를 덮는다."""
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            for args in (["add", "-A"], ["commit", "-qm", "base"]):
                subprocess.run(["git", *args], cwd=root, check=True, env=_ENV, capture_output=True)
            body = self._run(json_out=True, report=True)
            self.assertEqual(json.loads(body)["report"], "")
            self.assertFalse(os.path.exists(os.path.join(root, ".asgard", "tutor", "last-review.md")))


class ExplainLaneTest(unittest.TestCase):
    """설명 레인. 엔진이 아직 없어도 죽지 않고, 있으면 물음의 답을 대신 적지 않는다."""

    def _run(self, **kwargs) -> str:
        from asgard.commands.tutor import run_tutor

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(run_tutor(**kwargs), 0)
        return out.getvalue()

    def test_the_lane_is_silent_when_the_engine_is_missing(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            stack.enter_context(contextlib.chdir(root))
            stack.enter_context(mock.patch.dict(sys.modules, {"asgard.tutor_teach": None}))
            self.assertEqual(self._run(explain=True, json_out=True).strip(), "null")

    def test_the_explanation_is_carried_into_the_json(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            stack.enter_context(contextlib.chdir(root))
            stack.enter_context(_teach_module(_explanation()))
            data = json.loads(self._run(explain=True, json_out=True))
            self.assertEqual(data["steps"][0]["path"], "src/asgard/tutor.py")
            self.assertEqual(data["terms"][0]["name"], "래칫")

    def test_the_report_puts_the_explanation_before_the_unanswered_section(self):
        """설명 절이 2절 뒤로 가면 저자가 2절을 이미 채워진 것으로 읽고 넘긴다."""
        from asgard.commands import tutor as surface

        text = surface._report(tutor.Lesson("HEAD", (), (), ()), _explanation())
        self.assertLess(text.index("## 1-1."), text.index("## 2. 왜 이렇게 했는가"))
        self.assertIn(surface._WHY_SLOT, text, "2절 빈칸 문구는 그대로여야 한다")

    def test_a_mission_written_once_comes_back(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            stack.enter_context(contextlib.chdir(root))
            stack.enter_context(_teach_module(_explanation()))
            self._run(mission=True, text="캐시 계층을 걷어낸다")
            self.assertEqual(json.loads(self._run(mission=True, json_out=True))["mission"], "캐시 계층을 걷어낸다")


class NeverBlocksTest(unittest.TestCase):
    """튜터는 규율이지 관문이 아니다 — 통과/실패를 만들기 시작하면 사람이 먼저 끈다."""

    def test_the_command_exits_zero_even_with_checkpoints(self):
        from asgard.commands.tutor import run_tutor

        self.assertEqual(run_tutor(json_out=True), 0)

    def test_an_engine_that_throws_does_not_take_the_surface_down(self):
        from asgard.commands.tutor import run_tutor

        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            stack.enter_context(contextlib.chdir(root))
            stack.enter_context(_teach_module(_explanation(), error=RuntimeError("boom")))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_tutor(explain=True), 0)
                self.assertEqual(run_tutor(explain=True, json_out=True), 0)


if __name__ == "__main__":
    unittest.main()
