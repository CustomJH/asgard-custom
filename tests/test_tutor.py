"""되짚기 판정 앵커 — 탐침마다 **물을 자리 하나와 안 물 자리 하나**를 짝으로 못박는다.

실행: uv run pytest tests/test_tutor.py

이 층은 아무것도 막지 않는다. 그래서 실패 방식이 게이트와 다르다: 게이트가 오탐을 내면 사람이
게이트를 끄지만, 튜터가 오탐을 내면 사람은 **끄지 않고 그냥 안 읽는다**. 끈 것은 눈에 보이고 안
읽는 것은 안 보이므로, 이쪽이 더 조용히 죽는다. 그래서 음성 대조군이 여기서는 더 중요하다.

같이 고정하는 계약 둘: ① 래칫 — base 에 이미 있던 물음은 다시 묻지 않는다. ② 종료 코드는
언제나 0 — 되짚기가 통과/실패를 만들기 시작하면 그 순간 관문이 된다.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
import unittest

from asgard import tutor, tutor_probes

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


class SwallowProbeTest(unittest.TestCase):
    """설명 없는 삼킴만 묻는다 — 이 저장소는 fail-open 을 의도적으로 쓴다."""

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
        """`pandas.testing` 처럼 진짜 패키지 이름이 있다 — 남의 표면을 테스트로 세면 물음이 사라진다."""
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
        """판정이 사라진 것과 기능이 사라진 것은 diff 에서 똑같이 보인다 — 물음이 달라야 한다."""
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
        """추적 안 되는 새 파일은 numstat 에 없다 — 0 으로 두면 가장 큰 변경이 가장 작아 보인다."""
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

    def test_a_turn_that_wrote_nothing_is_silent(self):
        with contextlib.ExitStack() as stack:
            root = self._repo_with_writes(stack)
            self.assertEqual(tutor.turn_note(root, "no-such-quest"), "")
            self.assertEqual(tutor.turn_note(root, None), "")


class NeverBlocksTest(unittest.TestCase):
    """튜터는 규율이지 관문이 아니다 — 통과/실패를 만들기 시작하면 사람이 먼저 끈다."""

    def test_the_command_exits_zero_even_with_checkpoints(self):
        from asgard.commands.tutor import run_tutor

        self.assertEqual(run_tutor(json_out=True), 0)


if __name__ == "__main__":
    unittest.main()
