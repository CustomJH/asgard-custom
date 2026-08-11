"""설명 엔진 앵커 — 항목마다 **설명이 나와야 하는 자리 하나와 안 나와야 하는 자리 하나**를 짝으로 못박는다.

실행: uv run pytest tests/test_tutor_teach.py

이 층은 `tutor`와 반대쪽 절반이다. `tutor`가 물음을 놓는다면 여기는 읽는 순서를 놓는다. 그래서
실패 방식도 반대다: 물음이 오탐이면 사람이 안 읽고 끝나지만, **설명이 틀리면 사람은 그 틀린
설명을 믿는다.** 그러므로 여기서 가장 중요한 판정은 "안 나와야 할 것이 안 나오는가"다 —
자리가 밀렸을 뿐인 함수, base 에 이미 있던 심볼, 용어집에 이미 적힌 말, 그리고 **의도 서술**.

계약 ② 를 판정으로 못박는 자리가 `PurposeTest` 다. `what`·`why_here` 에 목적 서술이 들어가는
순간 이 층은 `tutor` 가 막으려던 일을 대신 하게 되고, 그건 기능 추가가 아니라 계약 파기다.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import subprocess
import tempfile
import unittest
from dataclasses import replace

from asgard import tutor_growth, tutor_teach

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


class _Repo(unittest.TestCase):
    """실제 `git init` 위에서만 판정한다 — 래칫은 본문이 아니라 이력에 걸린다."""

    def _repo(self, stack) -> str:
        root = stack.enter_context(tempfile.TemporaryDirectory())
        for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=root, check=True, env=_ENV, capture_output=True)
        return root

    def _write(self, root: str, rel: str, text: str) -> None:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def _stage(self, root: str) -> None:
        """새 파일을 인덱스에 올린다 — `surface.diff` 는 추적되는 변경만 본다."""
        subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=_ENV, capture_output=True)

    def _commit(self, root: str) -> None:
        self._stage(root)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True, env=_ENV, capture_output=True)

    def _base(self, stack, files: dict[str, str]) -> str:
        root = self._repo(stack)
        for rel, text in files.items():
            self._write(root, rel, text)
        self._commit(root)
        return root

    def _units(self, exp) -> list[str]:
        return [step.unit for step in exp.steps]


class ReadingOrderTest(_Repo):
    """읽는 순서는 실행 흐름 순서다 — 부르는 쪽이 먼저다."""

    def test_the_caller_is_read_before_what_it_calls(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "x = 1\n\n\ndef zeta():\n    return 1\n\n\ndef alpha():\n    return zeta()\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD")
            self.assertEqual(self._units(exp), ["alpha", "zeta"])
            self.assertEqual([step.order for step in exp.steps], [1, 2])

    def test_a_function_that_only_moved_is_not_a_step(self):
        """위에서 함수가 하나 생기면 아래가 전부 밀린다 — 밀린 것을 변경이라 부르면 순서가 소음이 된다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "def kept():\n    return 1\n"})
            self._write(root, "m.py", "def added():\n    return 2\n\n\ndef kept():\n    return 1\n")
            self._stage(root)
            self.assertEqual(self._units(tutor_teach.explain(root, "HEAD")), ["added"])

    def test_a_cycle_falls_back_to_coordinate_order(self):
        """서로 부르면 먼저 읽을 쪽이 없다 — 그때는 좌표 순서로 놓되 자리를 빠뜨리지 않는다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "def ping():\n    return pong()\n\n\ndef pong():\n    return ping()\n")
            self._stage(root)
            self.assertEqual(self._units(tutor_teach.explain(root, "HEAD")), ["ping", "pong"])

    def test_a_unit_that_both_calls_and_is_called_keeps_the_two_facts_apart(self):
        """`·` 는 같은 종류의 항목을 잇는 글리프다 — 두 사실을 그것으로 이으면 한 목록으로 읽힌다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(
                root,
                "m.py",
                "def leaf():\n    return 1\n\n\ndef middle():\n    return leaf()\n\n\n"
                "def top():\n    return middle()\n",
            )
            self._stage(root)
            middle = {step.unit: step for step in tutor_teach.explain(root, "HEAD").steps}["middle"]
            head, sep, tail = middle.why_here.partition(". ")
            self.assertEqual(sep, ". ", "두 사실은 문장으로 갈린다")
            self.assertIn("이 자리가 부르는 곳 — `leaf`", head)
            self.assertEqual(tail, "이 자리를 부르는 곳 — `top`")
            self.assertNotIn("·", middle.why_here, "`·` 는 같은 종류의 항목만 잇는다")

    def test_a_unit_that_only_calls_stays_one_sentence(self):
        """사실이 하나면 문장도 하나다 — 안 나눌 자리를 나누면 그것도 소음이다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "def leaf():\n    return 1\n\n\ndef top():\n    return leaf()\n")
            self._stage(root)
            top = {step.unit: step for step in tutor_teach.explain(root, "HEAD").steps}["top"]
            self.assertEqual(top.why_here, "이 변경 안에서 이 자리가 부르는 곳 — `leaf`")
            self.assertNotIn(". ", top.why_here)

    def test_a_method_call_is_not_counted_as_a_call_but_the_name_call_still_is(self):
        """`dev.run(3)`의 `run` 단위는 남의 것일 수 있다 — 수신자를 모르는 호출로 간선을 놓으면
        화면에 없는 관계가 사실로 나가고, 오탐 하나가 읽는 순서 전체의 값을 깎는다. 못 센 갈래는
        조용히 버리지 않고 못 본 것에 적는다(계약 ⑤).
        """
        body = "def run(cmd):\n    return cmd\n\n\ndef main(dev):\n    return %s\n"
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", body % "dev.run(3)")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD")
            said = {step.unit: step.why_here for step in exp.steps}
            self.assertNotIn("`run`", said["main"], "속성 호출은 간선이 아니다")
            self.assertEqual(said["main"], "이 변경 안에서는 호출 관계가 안 보여요")
            self.assertIn("속성 호출 1곳은 수신자를 몰라서 호출 관계에서 뺐어요", [why for _, why in exp.gaps])

            self._write(root, "m.py", body % "run(3)")
            self._stage(root)
            after = tutor_teach.explain(root, "HEAD")
            self.assertEqual(self._units(after), ["main", "run"], "이름 호출은 여전히 간선이다")
            self.assertNotIn("속성 호출", " ".join(why for _, why in after.gaps))

    def test_a_name_defined_once_still_crosses_files(self):
        """파일로 자르면 이 간선이 죽는다 — 이름이 한 자리뿐이면 어느 파일에서 부르든 그 자리다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"a.py": "x = 1\n", "b.py": "x = 1\n"})
            self._write(root, "a.py", "x = 1\n\n\ndef helper():\n    return 1\n")
            self._write(root, "b.py", "from a import helper\n\n\ndef top():\n    return helper()\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD")
            self.assertEqual(self._units(exp), ["top", "helper"], "부르는 쪽이 먼저다")
            said = {step.unit: step.why_here for step in exp.steps}
            self.assertIn("`helper`", said["top"])
            self.assertNotIn("이름이 같은 단위", " ".join(why for _, why in exp.gaps))

    def test_disconnected_changes_start_with_one_complete_flow(self):
        """카드 첫 세 자리가 서로 다른 파일의 시작점이면 읽는 순서가 다시 목록이 된다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"a.py": "x = 1\n", "z.py": "x = 1\n"})
            self._write(root, "a.py", "def alone():\n    return 1\n")
            self._write(
                root,
                "z.py",
                "def leaf():\n    return 1\n\n\ndef middle():\n    return leaf()\n\n\ndef top():\n    return middle()\n",
            )
            self._stage(root)

            exp = tutor_teach.explain(root, "HEAD")

            self.assertEqual(self._units(exp)[:3], ["top", "middle", "leaf"])
            self.assertEqual((exp.total_units, exp.flow_count, exp.primary_units), (4, 2, 3))
            self.assertIn("4곳", exp.overview)

    def test_the_same_name_in_two_files_makes_no_edge_at_all(self):
        """실측으로 잡은 자리 — `tutor.py`의 `turn_note`가 `hooks/tutor_note.py`의 `_card` 를
        부르는 것으로 나왔다. 이름이 겹치면 어느 쪽인지 기계가 못 정하고, 못 정한 것을 단언하면
        ①과 같은 거짓 간선이 된다. 접은 사실은 못 본 것에 남긴다(계약 ⑤).
        """
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"a.py": "x = 1\n", "b.py": "x = 1\n"})
            self._write(root, "a.py", "def _card():\n    return 1\n\n\ndef top():\n    return _card()\n")
            self._write(root, "b.py", "def _card():\n    return 2\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD")
            said = {step.unit: step.why_here for step in exp.steps}
            self.assertEqual(said["top"], "이 변경 안에서는 호출 관계가 안 보여요")
            self.assertEqual(said["_card"], "이 변경 안에서는 호출 관계가 안 보여요")
            self.assertIn(
                (
                    "a.py · b.py _card",
                    "이름이 같은 단위가 여러 파일에 있어서 어느 쪽을 부르는지 못 정하고 호출 관계에서 뺐어요",
                ),
                exp.gaps,
            )

    def test_a_step_carries_a_coordinate(self):
        """좌표 없는 주장은 안 만든다(계약 ①) — `path:line` 이 없으면 사람이 열어 볼 자리가 없다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "x = 1\n\n\ndef solo():\n    return 2\n")
            self._stage(root)
            step = tutor_teach.explain(root, "HEAD").steps[0]
            self.assertEqual((step.path, step.line), ("m.py", 4))
            self.assertEqual(step.where, "m.py:4")


class NonPythonTest(_Repo):
    def test_a_non_python_unit_is_ordered_but_its_limit_is_written_down(self):
        """파서가 없어 간선을 못 놓는다 — 침묵하지 않고 못 본 사실을 적는다(계약 ⑤)."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"a.js": "// base\n"})
            self._write(root, "a.js", "export function greet(name) {\n  return name;\n}\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD")
            self.assertEqual(self._units(exp), ["greet"])
            self.assertIn("호출 관계를 못 읽는 언어", exp.steps[0].why_here)

    def test_a_document_is_not_reported_as_unread(self):
        """문서에는 읽을 단위가 없다 — 그것까지 못 본 목록에 올리면 그 목록을 아무도 안 본다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"README.md": "hi\n"})
            self._write(root, "README.md", "hi there\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD")
            self.assertEqual(exp.steps, ())
            self.assertEqual([where for where, _ in exp.gaps if where == "README.md"], [])

    def test_a_gitignore_is_not_reported_as_unreadable_code(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {".gitignore": ".venv/\n"})
            self._write(root, ".gitignore", ".venv/\nbuild/\n")
            self._stage(root)

            exp = tutor_teach.explain(root, "HEAD")

            self.assertNotIn(".gitignore", [where for where, _ in exp.gaps])

    def test_a_deleted_file_is_not_reported_as_unread(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"gone.py": "def gone():\n    return 1\n"})
            os.remove(os.path.join(root, "gone.py"))
            self._stage(root)

            exp = tutor_teach.explain(root, "HEAD")

            self.assertNotIn("gone.py", [where for where, _ in exp.gaps])


class PurposeTest(_Repo):
    """계약 ② — 설계 의도를 추측해 적으면 이 층이 막으려던 일을 이 층이 하게 된다."""

    def test_no_step_states_a_purpose(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "x = 1\n\n\ndef zeta():\n    return 1\n\n\ndef alpha():\n    return zeta()\n")
            self._stage(root)
            for step in tutor_teach.explain(root, "HEAD").steps:
                for banned in ("위해", "하려고", "때문에", "목적"):
                    self.assertNotIn(banned, step.what)
                    self.assertNotIn(banned, step.why_here)

    # `Step.does` 도 같은 계약 아래 있다 — 인용이면 되고 지어내면 안 된다. 그 판정은 카드 표면과
    # 함께 `tests/test_tutor_explain.py` 가 진다.

    def test_a_gloss_is_quoted_from_the_source_not_written_by_the_machine(self):
        """`gloss`에는 "위해"가 들어와도 된다 — 그게 원문이면. 그래서 낱말을 막는 대신 **인용인지**를
        판정한다. 낱말 목록으로 막으면 원문을 자르게 되고, 잘린 인용은 계약 ② 를 지키는 대신 계약 ①
        (좌표가 가리키는 자리와 화면이 같다)을 깬다.

        갈래마다 인용의 모양이 다르다. docstring 은 본문의 부분 문자열이고, signature 는 이름과
        타입만 골라 다시 적은 것이라 낱말이 전부 본문에 있으며, dependency 는 뜻을 안 만든다.
        """
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            body = (
                "import requests\n\n\ndef steam(cup: str) -> str:\n    return cup\n\n\n"
                'def brew(bean):\n    """설정을 읽기 위해 물을 부어요."""\n    return bean\n'
            )
            self._write(root, "m.py", body)
            self._stage(root)
            terms = {t.name: t for t in tutor_teach.explain(root, "HEAD").terms}
            self.assertEqual(terms["brew"].source, "docstring")
            self.assertIn(terms["brew"].gloss, body, "docstring 갈래는 본문 그대로여야 한다")
            self.assertIn("위해", terms["brew"].gloss, "원문에 있던 말을 지우지 않는다")
            self.assertEqual(terms["steam"].source, "signature")
            for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", terms["steam"].gloss):
                self.assertIn(word, body, "signature 갈래의 낱말은 전부 본문에서 온다")
            self.assertEqual(terms["requests"].gloss, "", "dependency 갈래는 뜻을 안 만든다")


class TermTest(_Repo):
    def test_a_new_public_symbol_becomes_a_term_with_its_docstring(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": 'def brew():\n    """커피를 내려요."""\n    return 1\n'})
            self._write(
                root,
                "m.py",
                'def brew():\n    """커피를 내려요."""\n    return 1\n\n\ndef steam(cup):\n'
                '    """우유를 데워요."""\n    return cup\n',
            )
            self._stage(root)
            terms = {t.name: t for t in tutor_teach.explain(root, "HEAD").terms}
            self.assertEqual(terms["steam"].gloss, "우유를 데워요.")
            self.assertEqual(terms["steam"].source, "docstring")
            self.assertEqual(terms["steam"].where, "m.py:6")

    def test_a_symbol_that_already_existed_is_not_a_new_word(self):
        """base 에 있던 말은 이번에 들여온 말이 아니다 — 매 회차 같은 말을 설명하면 아무도 안 읽는다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": 'def brew():\n    """커피를 내려요."""\n    return 1\n'})
            self._write(
                root,
                "m.py",
                'def brew():\n    """커피를 내려요."""\n    return 2\n\n\ndef steam(cup):\n    return cup\n',
            )
            self._stage(root)
            names = {t.name for t in tutor_teach.explain(root, "HEAD").terms}
            self.assertIn("steam", names)
            self.assertNotIn("brew", names)

    def test_a_symbol_without_a_docstring_falls_back_to_its_signature(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "x = 1\n\n\ndef steam(cup: str) -> str:\n    return cup\n")
            self._stage(root)
            term = {t.name: t for t in tutor_teach.explain(root, "HEAD").terms}["steam"]
            self.assertEqual(term.source, "signature")
            self.assertEqual(term.gloss, "steam(cup) -> str")

    def test_a_new_dependency_is_a_new_word_but_the_standard_library_is_not(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "import os\nimport requests\n\nx = requests\n")
            self._stage(root)
            terms = {t.name: t for t in tutor_teach.explain(root, "HEAD").terms}
            self.assertEqual(terms["requests"].source, "dependency")
            self.assertEqual(terms["requests"].where, "m.py:2")
            self.assertNotIn("os", terms)

    def test_a_word_already_in_the_glossary_is_not_explained_again(self):
        """계약 ③ — 회차마다 설명이 줄어드는 근거가 용어집이다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "x = 1\n\n\ndef steam(cup):\n    return cup\n")
            self._stage(root)
            self.assertIn("steam", {t.name for t in tutor_teach.explain(root, "HEAD").terms})
            tutor_teach.glossary_merge(root, [tutor_teach.Term("steam", "m.py:4", "", "signature")])
            self.assertNotIn("steam", {t.name for t in tutor_teach.explain(root, "HEAD").terms})


class CheckTest(_Repo):
    def test_a_test_file_that_names_the_symbol_becomes_the_check_command(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "x = 1\n\n\ndef steam(cup):\n    return cup\n")
            self._write(
                root, "tests/test_m.py", "from m import steam\n\n\ndef test_steam():\n    assert steam(1) == 1\n"
            )
            self._stage(root)
            self.assertEqual(tutor_teach.explain(root, "HEAD").checks, ("python -m pytest tests/test_m.py",))

    def test_no_test_file_leaves_checks_empty_and_records_the_gap(self):
        """못 찾은 것을 찾은 척하지 않는다 — 없는 명령 한 줄이면 이 카드 전체가 신뢰를 잃는다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "x = 1\n\n\ndef steam(cup):\n    return cup\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD")
            self.assertEqual(exp.checks, ())
            self.assertIn("이 변경을 직접 확인하는 판정을 못 찾았어요", [why for _, why in exp.gaps])

    def test_a_changed_test_file_is_itself_the_check_command(self):
        """바뀐 단위가 전부 비공개면 이름으로 찾을 심볼이 없다 — 그래도 같이 고친 판정은 사실이다."""
        with contextlib.ExitStack() as stack:
            root = self._base(
                stack,
                {"m.py": "def _helper():\n    return 1\n", "tests/test_m.py": "def test_a():\n    assert 1\n"},
            )
            self._write(root, "m.py", "def _helper():\n    return 2\n")
            self._write(root, "tests/test_m.py", "def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 2\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD")
            self.assertEqual(exp.checks, ("python -m pytest tests/test_m.py",))
            self.assertNotIn("이 변경을 직접 확인하는 판정을 못 찾았어요", [why for _, why in exp.gaps])

    def test_pytest_support_files_are_not_put_in_the_check_command(self):
        base = {
            "tests/conftest.py": "VALUE = 1\n",
            "tests/hookscaffold.py": "VALUE = 1\n",
            "tests/test_m.py": "def test_a():\n    assert 1\n",
        }
        with contextlib.ExitStack() as stack:
            root = self._base(stack, base)
            for rel, text in base.items():
                self._write(root, rel, text + "\nCHANGED = 1\n")
            self._stage(root)

            check = tutor_teach.explain(root, "HEAD").checks[0]

            self.assertIn("tests/test_m.py", check)
            self.assertNotIn("conftest.py", check)
            self.assertNotIn("hookscaffold.py", check)

    def test_gitignored_reference_tests_are_not_put_in_the_check_command(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n", ".gitignore": "workspace/\n"})
            self._write(root, "m.py", "def steam(cup):\n    return cup\n")
            self._write(
                root,
                "workspace/copy/tests/test_m.py",
                "from m import steam\n\n\ndef test_steam():\n    assert steam(1) == 1\n",
            )
            self._stage(root)

            exp = tutor_teach.explain(root, "HEAD")

            self.assertEqual(exp.checks, ())
            self.assertIn("이 변경을 직접 확인하는 판정을 못 찾았어요", [why for _, why in exp.gaps])

    def test_a_change_with_no_new_symbol_and_no_test_says_it_found_no_check(self):
        """본문만 고친 변경에는 찾을 심볼도 판정도 없다 — 그때는 명령 줄을 조용히 비우지 않는다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "def steam(cup):\n    return cup\n"})
            self._write(root, "m.py", "def steam(cup):\n    return cup\n\n\ndef _helper():\n    return 1\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD")
            self.assertEqual(exp.checks, ())
            self.assertIn("이 변경을 직접 확인하는 판정을 못 찾았어요", [why for _, why in exp.gaps])

    def test_a_named_scope_does_not_hide_the_test_file_this_change_touched(self):
        """실측으로 잡은 자리 — 소스 경로만 지목해 부르면 같이 고친 판정이 화면에서 사라졌다."""
        with contextlib.ExitStack() as stack:
            root = self._base(
                stack,
                {"m.py": "def _helper():\n    return 1\n", "tests/test_m.py": "def test_a():\n    assert 1\n"},
            )
            self._write(root, "m.py", "def _helper():\n    cup = 1\n    return cup\n")
            self._write(root, "tests/test_m.py", "def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 2\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD", ["m.py"])
            self.assertEqual(self._units(exp), ["_helper"], "지목은 읽을 자리를 좁힌다")
            self.assertEqual(exp.checks, ("python -m pytest tests/test_m.py",))

    def test_the_related_test_file_survives_the_cap(self):
        """상한을 자를 때 순서가 값을 정한다 — 이름순으로만 자르면 무관한 판정이 앞자리를 먹는다."""
        with contextlib.ExitStack() as stack:
            base = {"m.py": "def _helper():\n    return 1\n"}
            base.update({f"tests/test_a{i}.py": "def test_x():\n    assert 1\n" for i in range(8)})
            base["tests/test_m.py"] = "def test_a():\n    assert 1\n"
            root = self._base(stack, base)
            self._write(root, "m.py", "def _helper():\n    cup = 1\n    return cup\n")
            for rel in [*(f"tests/test_a{i}.py" for i in range(8)), "tests/test_m.py"]:
                self._write(root, rel, "def test_x():\n    assert 1\n\n\ndef test_y():\n    assert 2\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD", ["m.py"])
            self.assertIn("tests/test_m.py", exp.checks[0])
            self.assertIn("확인 명령에는 테스트 파일 6개까지만 넣었어요", [why for _, why in exp.gaps])

    def test_a_change_with_nothing_to_read_still_says_it_found_no_check(self):
        """읽을 자리가 없는 변경에서도 이 줄은 남는다 — 확인 명령을 못 찾은 것은 읽는 순서와
        무관한 사실이고, 자리가 없다고 지우면 "0건"과 "안 봤다"가 같은 화면이 된다(계약 ⑤).
        """
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"README.md": "hi\n"})
            self._write(root, "README.md", "hi there\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD")
            self.assertEqual(exp.steps, ())
            self.assertIn("이 변경을 직접 확인하는 판정을 못 찾았어요", [why for _, why in exp.gaps])
            self.assertEqual(tutor_teach.card(exp), "", "카드에는 안 싣는다 — 빈 카드는 다음 카드의 신뢰를 깎는다")

    def test_the_two_lanes_do_not_list_the_same_file_twice(self):
        """바뀐 테스트 파일이자 새 심볼의 이름이 보이는 파일 — 한 번만 들어가야 명령이 안 길어진다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "x = 1\n\n\ndef steam(cup):\n    return cup\n")
            self._write(
                root, "tests/test_m.py", "from m import steam\n\n\ndef test_steam():\n    assert steam(1) == 1\n"
            )
            self._stage(root)
            self.assertEqual(tutor_teach.explain(root, "HEAD").checks, ("python -m pytest tests/test_m.py",))


class UnstagedTest(_Repo):
    """실측으로 잡은 자리 — 새 파일을 인덱스에 안 올리면 표면 대조가 통째로 못 본다."""

    def test_a_new_file_outside_the_index_is_named_not_silently_dropped(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "fresh.py", "def steam(cup):\n    return cup\n")
            exp = tutor_teach.explain(root, "HEAD")
            self.assertEqual(self._units(exp), ["steam"])
            self.assertEqual(exp.terms, ())
            self.assertIn("fresh.py", [where for where, _ in exp.gaps])

    def test_the_same_file_inside_the_index_needs_no_such_note(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "fresh.py", "def steam(cup):\n    return cup\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD")
            self.assertEqual({t.name for t in exp.terms}, {"steam"})
            self.assertNotIn("fresh.py", [where for where, _ in exp.gaps])


class DepthTest(_Repo):
    """깊이는 이 자리에서 **답한** 물음 수로만 정해진다 — 오탐으로 닫은 것은 이해가 아니다."""

    def _answer(self, root: str, path: str, unit: str) -> None:
        tutor_growth.note_asked(root, [{"kind": "silent-failure", "path": path, "unit": unit, "ask": "왜인가요?"}])
        ok, _ = tutor_growth.answer(
            root, tutor_growth.cid("silent-failure", path, unit), f"{unit} 자리는 이렇게 읽어요"
        )
        self.assertTrue(ok)

    def test_a_place_with_no_answers_is_first(self):
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            self.assertEqual(tutor_teach.depth_for(root, ["m.py"]), "first")

    def test_one_answer_makes_it_familiar_and_three_make_it_owned(self):
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            self._answer(root, "m.py", "a")
            self.assertEqual(tutor_teach.depth_for(root, ["m.py"]), "familiar")
            self._answer(root, "m.py", "b")
            self._answer(root, "m.py", "c")
            self.assertEqual(tutor_teach.depth_for(root, ["m.py"]), "owned")

    def test_another_files_answers_do_not_count(self):
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            for unit in ("a", "b", "c"):
                self._answer(root, "other.py", unit)
            self.assertEqual(tutor_teach.depth_for(root, ["m.py"]), "first")

    def test_an_explicit_depth_wins_over_the_record(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "x = 1\n\n\ndef steam(cup):\n    return cup\n")
            self._stage(root)
            self.assertEqual(tutor_teach.explain(root, "HEAD", depth="owned").depth, "owned")


class RecallTest(_Repo):
    def _two_steps(self, root: str):
        self._write(root, "m.py", "x = 1\n\n\ndef zeta():\n    return 1\n\n\ndef alpha():\n    return zeta()\n")
        self._stage(root)

    def test_a_first_visit_with_a_flow_asks_once(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._two_steps(root)
            recall = tutor_teach.explain(root, "HEAD", depth="first").recall
            self.assertEqual(len(recall), 1)
            self.assertIn("`zeta` 단위를", recall[0])

    def test_a_familiar_place_is_not_quizzed_here(self):
        """이미 아는 자리의 인출은 `tutor` 의 재방문 사다리가 맡는다 — 두 층이 같은 일을 하면 두 번 묻는다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._two_steps(root)
            self.assertEqual(tutor_teach.explain(root, "HEAD", depth="familiar").recall, ())

    def test_a_single_step_has_no_flow_to_recall(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "x = 1\n\n\ndef solo():\n    return 2\n")
            self._stage(root)
            self.assertEqual(tutor_teach.explain(root, "HEAD", depth="first").recall, ())


class MissionTest(_Repo):
    def test_a_mission_survives_a_round_trip(self):
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            self.assertEqual(tutor_teach.mission(root), "")
            self.assertEqual(
                tutor_teach.set_mission(root, " 회수 경로를 혼자 재구성하기 "), "회수 경로를 혼자 재구성하기"
            )
            self.assertEqual(tutor_teach.mission(root), "회수 경로를 혼자 재구성하기")

    def test_the_mission_file_stays_out_of_the_repository(self):
        """이건 팀 문서가 아니라 이 사람의 기록이다 — 좌표가 `.asgard/tutor` 밖으로 나가면 안 된다."""
        self.assertEqual(tutor_teach.MISSION_REL, os.path.join(".asgard", "tutor", "mission.md"))
        self.assertEqual(tutor_teach.GLOSSARY_REL, os.path.join(".asgard", "tutor", "glossary.md"))


class GlossaryTest(_Repo):
    def test_merge_counts_only_words_it_had_not_seen(self):
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            rows = [tutor_teach.Term("steam", "m.py:4", "우유를 데워요.", "docstring")]
            self.assertEqual(tutor_teach.glossary_merge(root, rows), 1)
            self.assertEqual(tutor_teach.glossary_merge(root, rows), 0)
            self.assertEqual(tutor_teach.glossary_known(root), {"steam"})

    def test_a_dict_row_is_accepted_too(self):
        """훅은 JSON 을, 네이티브는 객체를 넘긴다 — 두 경로가 같은 용어집을 쓴다."""
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            self.assertEqual(tutor_teach.glossary_merge(root, [{"name": "brew", "where": "m.py:1"}]), 1)
            self.assertEqual(tutor_teach.glossary_known(root), {"brew"})


class ShownTermsTest(_Repo):
    """적립은 **카드가 그린 말**까지다 — 안 그린 말을 적으면 그 말은 영영 설명 안 된다."""

    def _five(self, stack) -> str:
        root = self._base(stack, {"m.py": "x = 1\n"})
        body = "x = 1\n" + "".join(f"\n\ndef word{i}(cup):\n    return cup\n" for i in range(5))
        self._write(root, "m.py", body)
        self._stage(root)
        return root

    def test_an_owned_reader_banks_nothing(self):
        """`owned` 카드는 좌표뿐이라 실린 말이 0건이다. 사다리가 익으면 여기가 정상 종착지다."""
        with contextlib.ExitStack() as stack:
            root = self._five(stack)
            exp = tutor_teach.explain(root, "HEAD", depth="owned")
            self.assertEqual(len(exp.terms), 5)
            self.assertEqual(tutor_teach.shown_terms(exp, 3), ())
            self.assertEqual(tutor_teach.glossary_merge(root, tutor_teach.shown_terms(exp, 3)), 0)
            self.assertEqual(tutor_teach.glossary_known(root), set())

    def test_a_first_visit_banks_exactly_the_three_the_card_drew(self):
        with contextlib.ExitStack() as stack:
            root = self._five(stack)
            exp = tutor_teach.explain(root, "HEAD", depth="first")
            shown = tutor_teach.shown_terms(exp, 3)
            card = tutor_teach.card(exp, 3)
            self.assertEqual(len(shown), 3)
            for term in shown:
                self.assertIn(f"`{term.name}`", card)
            for term in exp.terms[3:]:
                self.assertNotIn(f"`{term.name}`", card)
            self.assertIn("나머지 말은 보고서에 접어 뒀어요", card)
            self.assertEqual(tutor_teach.glossary_merge(root, shown), 3)

    def test_a_word_the_card_cut_is_still_explained_next_time(self):
        """상한 아래로 잘린 말까지 적립하면 사람이 못 본 말이 "이미 설명한 말"이 된다."""
        with contextlib.ExitStack() as stack:
            root = self._five(stack)
            exp = tutor_teach.explain(root, "HEAD", depth="first")
            cut = {term.name for term in exp.terms[3:]}
            tutor_teach.glossary_merge(root, tutor_teach.shown_terms(exp, 3))
            after = tutor_teach.explain(root, "HEAD", depth="first")
            self.assertEqual({term.name for term in after.terms}, cut)


class GlossaryWiringTest(_Repo):
    """계약 ③ 은 병합하는 자리가 있어야 걸린다 — 읽는 쪽만 물려 있으면 용어집이 영영 안 생기고
    설명은 회차마다 같은 길이로 나온다. 병합 시점의 규칙은 `tutor.hand_back`과 같다: 사람 앞에
    나간 회차만 센다.
    """

    def _named(self, stack) -> str:
        root = self._base(stack, {"m.py": "x = 1\n"})
        self._write(root, "m.py", 'x = 1\n\n\ndef steam(cup):\n    """우유를 데워요."""\n    return cup\n')
        self._stage(root)
        stack.enter_context(contextlib.chdir(root))
        return root

    def _run(self, **kwargs) -> None:
        from asgard.commands.tutor import run_tutor

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_tutor(**kwargs), 0)

    def test_a_word_the_screen_carried_is_not_explained_again(self):
        with contextlib.ExitStack() as stack:
            root = self._named(stack)
            self._run(explain=True)
            self.assertEqual(tutor_teach.glossary_known(root), {"steam"})
            self.assertEqual(tutor_teach.explain(root, "HEAD").terms, (), "두 번째 회차에는 빠진다")

    def test_the_hook_lane_merges_what_its_card_carried(self):
        """훅은 `--json --record --report`로 부른다 — 그 산출은 사용자 화면에 그대로 들어간다."""
        with contextlib.ExitStack() as stack:
            root = self._named(stack)
            self._run(json_out=True, record=True, report=True)
            self.assertEqual(tutor_teach.glossary_known(root), {"steam"})

    def test_a_machine_only_look_leaves_no_glossary_behind(self):
        """사람이 안 본 호출까지 병합하면 본 적 없는 말이 "이미 설명한 말"이 된다."""
        with contextlib.ExitStack() as stack:
            root = self._named(stack)
            self._run(json_out=True, report=True)
            self.assertFalse(os.path.exists(os.path.join(root, tutor_teach.GLOSSARY_REL)))


class CardTest(unittest.TestCase):
    """계약 ④ — 깊이가 올라갈수록 화면이 줄어든다."""

    def _exp(self, depth: str) -> tutor_teach.Explanation:
        return tutor_teach.Explanation(
            base="HEAD",
            depth=depth,
            mission="회수 경로를 혼자 재구성하기",
            steps=(
                tutor_teach.Step(
                    1, "m.py", 8, "alpha", "새로 생긴 단위예요 (2행)", "이 변경 안에서 다음 자리를 불러요 — zeta"
                ),
                tutor_teach.Step(
                    2, "m.py", 4, "zeta", "새로 생긴 단위예요 (2행)", "이 변경 안에서 여기를 부르는 자리 — alpha"
                ),
            ),
            terms=(tutor_teach.Term("steam", "m.py:4", "우유를 데워요.", "docstring"),),
            checks=("python -m pytest tests/test_m.py",),
            recall=("방금 본 흐름에서 `zeta` 단위를 부르는 자리는 어디였나요?",),
            gaps=(("a.js", "호출 관계를 못 읽는 언어예요"),),
        )

    def test_a_first_visit_shows_words_checks_and_the_recall_question(self):
        card = tutor_teach.card(self._exp("first"))
        self.assertIn("m.py:8 alpha", card)
        self.assertIn("`steam`", card)
        self.assertIn("python -m pytest tests/test_m.py", card)
        self.assertIn("▸", card)
        self.assertIn("회수 경로를 혼자 재구성하기", card)

    def test_a_step_with_a_docstring_leads_with_it_and_keeps_the_change_below(self):
        exp = replace(
            self._exp("first"),
            steps=(
                tutor_teach.Step(
                    1, "m.py", 8, "alpha", "새로 생긴 단위예요 (2행)", "여기가 먼저예요", "우유를 데워요."
                ),
                tutor_teach.Step(2, "m.py", 4, "zeta", "새로 생긴 단위예요 (2행)", "그 다음이에요"),
            ),
            primary_units=2,
        )
        lines = tutor_teach.card(exp).splitlines()

        head = next(line for line in lines if "m.py:8 alpha" in line)
        self.assertTrue(head.endswith("— 우유를 데워요."), head)
        self.assertIn("     새로 생긴 단위예요 (2행) · 여기가 먼저예요", lines)
        self.assertIn("  2. m.py:4 zeta — 새로 생긴 단위예요 (2행) · 그 다음이에요", lines, "없으면 한 줄 그대로다")

    def test_a_stop_card_can_leave_the_recall_quiz_to_the_ranked_checkpoint(self):
        card = tutor_teach.card(self._exp("first"), quiz=False)
        self.assertNotIn("방금 본 흐름", card)
        self.assertIn("python -m pytest", card)

    def test_a_card_folds_other_flows_without_an_overflow_counter(self):
        exp = replace(self._exp("first"), total_units=40, flow_count=12, primary_units=2)
        card = tutor_teach.card(exp, limit=1)
        self.assertIn("나머지 흐름은 보고서에 접어 뒀어요", card)
        self.assertNotIn("…외 39건", card)

    def test_a_familiar_place_gets_the_order_and_nothing_else(self):
        card = tutor_teach.card(self._exp("familiar"))
        self.assertIn("m.py:8 alpha", card)
        for gone in ("`steam`", "pytest", "▸", "못 본 것"):
            self.assertNotIn(gone, card)

    def test_an_owned_place_gets_coordinates_only(self):
        card = tutor_teach.card(self._exp("owned"))
        self.assertEqual(card, "⠶ 설명 — m.py:8 alpha · m.py:4 zeta")

    def test_an_empty_explanation_is_silent(self):
        """빈 카드는 다음 카드의 신뢰를 깎는다 — 실을 것이 없으면 아무것도 안 넣는다."""
        empty = tutor_teach.Explanation("HEAD", "first", "", (), (), (), (), ())
        self.assertEqual(tutor_teach.card(empty), "")

    def test_no_emoji_reaches_the_screen(self):
        card = tutor_teach.card(self._exp("first"))
        self.assertTrue(all(ord(ch) < 0x1F000 for ch in card))


class FailOpenTest(_Repo):
    """튜터는 관문이 아니다 — 못 읽어도 예외를 올리지 않는다."""

    def test_a_directory_that_is_not_a_repository_explains_nothing(self):
        with contextlib.ExitStack() as stack:
            root = stack.enter_context(tempfile.TemporaryDirectory())
            exp = tutor_teach.explain(root, "HEAD")
            self.assertEqual(exp.steps, ())
            self.assertEqual(exp.depth, "first")

    def test_a_named_path_that_does_not_exist_is_recorded_not_swallowed(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            exp = tutor_teach.explain(root, "HEAD", ["gone.py"])
            self.assertEqual(exp.steps, ())
            self.assertIn("gone.py", [where for where, _ in exp.gaps])


class ParticleTest(_Repo):
    """조사는 식별자에 안 붙인다 — 라틴 이름의 받침은 소리로 갈리고, 그 소리를 기계는 모른다.

    `top`은 톱(받침 있음), `card`는 카드(없음)다. 철자로도 어미로도 못 가르므로 이름 뒤에는 늘
    한국어 낱말을 하나 두고 조사를 거기 붙인다.
    """

    def test_no_particle_follows_an_identifier(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack, {"m.py": "x = 1\n"})
            self._write(root, "m.py", "def top():\n    return 1\n\n\ndef run():\n    return top()\n")
            self._stage(root)
            exp = tutor_teach.explain(root, "HEAD", depth="first")
            said = [step.why_here for step in exp.steps] + list(exp.recall)
            for line in said:
                for particle in ("`을", "`를", "`이 ", "`가 ", "`은", "`는"):
                    self.assertNotIn(particle, line)
            self.assertIn("`top` 단위를", exp.recall[0])


if __name__ == "__main__":
    unittest.main()
