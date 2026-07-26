"""공개 표면 대조 앵커 — "호출부가 그대로면 깨지는가"의 분류를 고정한다.

실행: uv run pytest tests/test_surface.py

이 모듈의 산출물은 판정자의 호출부 전수 대조에 **하한**으로 실린다. 분류가 틀리면 판정이
깨진 호출부를 안전하다고 읽으므로, breaking 여부는 종류별로 하나씩 못박는다.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from asgard import surface


class ExtractTest(unittest.TestCase):
    def test_private_symbols_are_not_surface(self):
        got = surface.extract("def _hidden():\n    pass\n\ndef shown():\n    pass\n")
        assert got is not None
        self.assertEqual(set(got), {"shown"})

    def test_dunder_is_surface(self):
        got = surface.extract("class A:\n    def __init__(self, x):\n        pass\n")
        assert got is not None
        self.assertIn("A.__init__", got)

    def test_self_and_cls_are_not_parameters(self):
        got = surface.extract("class A:\n    def m(self, x):\n        pass\n")
        assert got is not None
        self.assertEqual(got["A.m"].params, ("x",))

    def test_required_vs_defaulted_parameters(self):
        got = surface.extract("def f(a, b=1, *, c, d=2):\n    pass\n")
        assert got is not None
        sig = got["f"]
        self.assertEqual(sig.params, ("a", "b"))
        self.assertEqual(sig.required, ("a",))
        self.assertEqual(sig.kwonly, ("c", "d"))
        self.assertEqual(sig.kwonly_required, ("c",))

    def test_varargs_and_return_annotation(self):
        got = surface.extract("def f(*args, **kw) -> int:\n    pass\n")
        assert got is not None
        self.assertTrue(got["f"].vararg)
        self.assertTrue(got["f"].kwarg)
        self.assertEqual(got["f"].returns, "int")

    def test_unparsable_is_none_not_empty(self):
        """파싱 실패와 "공개 심볼 0개"는 다른 사실이다 — 뭉개면 미측정이 PASS 로 읽힌다."""
        self.assertIsNone(surface.extract("def f(:\n"))
        self.assertEqual(surface.extract("x = 1\n"), {})


class CompareTest(unittest.TestCase):
    def _diff(self, before: str, after: str):
        b, a = surface.extract(before), surface.extract(after)
        assert b is not None and a is not None
        return {c.kind: c for c in surface._compare("m.py", b, a)}

    def test_removed_symbol_is_breaking(self):
        got = self._diff("def f():\n    pass\n", "")
        self.assertTrue(got["removed"].breaking)

    def test_added_symbol_is_not_breaking(self):
        got = self._diff("", "def f():\n    pass\n")
        self.assertFalse(got["added"].breaking)

    def test_dropped_parameter_is_breaking(self):
        got = self._diff("def f(a, b):\n    pass\n", "def f(a):\n    pass\n")
        self.assertTrue(got["param_removed"].breaking)

    def test_new_required_parameter_is_breaking(self):
        got = self._diff("def f(a):\n    pass\n", "def f(a, b):\n    pass\n")
        self.assertTrue(got["required_param_added"].breaking)

    def test_new_optional_parameter_is_not_breaking(self):
        got = self._diff("def f(a):\n    pass\n", "def f(a, b=1):\n    pass\n")
        self.assertFalse(got["optional_param_added"].breaking)

    def test_removing_a_default_is_breaking(self):
        got = self._diff("def f(a, b=1):\n    pass\n", "def f(a, b):\n    pass\n")
        self.assertTrue(got["default_removed"].breaking)

    def test_renamed_parameter_is_breaking_for_keyword_callers(self):
        got = self._diff("def f(a, old):\n    pass\n", "def f(a, new):\n    pass\n")
        self.assertIn("param_renamed", got)
        self.assertTrue(got["param_renamed"].breaking)

    def test_new_required_keyword_is_breaking(self):
        got = self._diff("def f(a):\n    pass\n", "def f(a, *, k):\n    pass\n")
        self.assertTrue(got["required_kwonly_added"].breaking)

    def test_new_optional_keyword_is_reported_but_not_breaking(self):
        """시그니처의 절반(kwonly)을 조용히 빠뜨리지 않는다."""
        got = self._diff("def f(a):\n    pass\n", "def f(a, *, k=1):\n    pass\n")
        self.assertIn("optional_kwonly_added", got)
        self.assertFalse(got["optional_kwonly_added"].breaking)

    def test_dropped_keyword_is_breaking(self):
        got = self._diff("def f(a, *, k=1):\n    pass\n", "def f(a):\n    pass\n")
        self.assertTrue(got["kwonly_removed"].breaking)

    def test_return_change_is_reported_as_non_breaking(self):
        """호출은 그대로 성공하지만 값의 소비처가 깨질 수 있다 — 보고하되 breaking 은 아니다."""
        got = self._diff("def f() -> int:\n    pass\n", "def f() -> str:\n    pass\n")
        self.assertIn("return_changed", got)
        self.assertFalse(got["return_changed"].breaking)

    def test_function_to_class_is_breaking(self):
        got = self._diff("def f():\n    pass\n", "class f:\n    pass\n")
        self.assertTrue(got["kind_changed"].breaking)

    def test_identical_surface_yields_nothing(self):
        body = "def f(a, b=1) -> int:\n    return 1\n"
        self.assertEqual(self._diff(body, body), {})

    def test_body_only_change_is_not_a_surface_change(self):
        """본문은 표면이 아니다 — 구현만 바뀌면 호출부 의무가 생기지 않는다."""
        self.assertEqual(self._diff("def f(a):\n    return 1\n", "def f(a):\n    return 2\n"), {})


class GitDiffTest(unittest.TestCase):
    """git 기준 대조 — 변경된 파일만 훑는지, 신규 파일과 삭제를 어떻게 읽는지."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self._git("init", "-q")
        self._git("config", "user.email", "t@t")
        self._git("config", "user.name", "t")

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def _write(self, rel: str, body: str) -> None:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)

    def _commit(self) -> None:
        self._git("add", "-A")
        self._git("commit", "-qm", "x")

    def test_breaking_change_lists_call_site_candidates(self):
        self._write("lib.py", "def fetch_record(a, b):\n    return a\n")
        self._write("app.py", "from lib import fetch_record\n\nfetch_record(1, 2)\n")
        self._commit()
        self._write("lib.py", "def fetch_record(a):\n    return a\n")
        result = surface.diff(self.root, "HEAD")
        self.assertEqual([c.kind for c in result.breaking], ["param_removed"])
        self.assertIn("app.py", result.obligations["fetch_record"])
        self.assertNotIn("lib.py", result.obligations["fetch_record"], "정의 파일은 후보가 아니다")

    def test_unchanged_tree_has_no_changes(self):
        self._write("lib.py", "def f(a):\n    return a\n")
        self._commit()
        result = surface.diff(self.root, "HEAD")
        self.assertEqual(result.changes, ())
        self.assertEqual(result.files_compared, 0, "변경된 파일만 대조한다")

    def test_new_file_symbols_are_additions(self):
        self._write("lib.py", "def f():\n    pass\n")
        self._commit()
        self._write("new.py", "def brand_new():\n    pass\n")
        self._git("add", "-A")  # untracked 는 git diff 에 안 나오므로 스테이징한다
        result = surface.diff(self.root, "HEAD")
        self.assertEqual([c.kind for c in result.changes], ["added"])
        self.assertFalse(result.breaking)

    def test_deleted_file_symbols_are_breaking(self):
        self._write("lib.py", "def gone_soon():\n    pass\n")
        self._commit()
        os.remove(os.path.join(self.root, "lib.py"))
        result = surface.diff(self.root, "HEAD")
        self.assertEqual([c.kind for c in result.breaking], ["removed"])

    def test_unparsable_file_is_recorded_not_silently_passed(self):
        self._write("lib.py", "def f():\n    pass\n")
        self._commit()
        self._write("lib.py", "def f(:\n")
        result = surface.diff(self.root, "HEAD")
        self.assertEqual(result.unparsed, ("lib.py",))
        self.assertEqual(result.changes, ())

    def test_deleted_test_method_is_not_a_surface_break(self):
        self._write("tests/test_thing.py", "class T:\n    def test_one(self):\n        pass\n")
        self._write("benchmarks/harness.py", "def measure():\n    pass\n")
        self._commit()
        self._write("tests/test_thing.py", "class T:\n    pass\n")
        os.remove(os.path.join(self.root, "benchmarks", "harness.py"))
        result = surface.diff(self.root, "HEAD")
        self.assertEqual(result.changes, (), "테스트·벤치는 공개 표면이 아니다")
        self.assertEqual(result.files_compared, 0)

    def test_test_callers_still_appear_as_edit_obligations(self):
        self._write("lib.py", "def fetch_record(a, b):\n    return a\n")
        self._write("tests/test_lib.py", "from lib import fetch_record\n\nfetch_record(1, 2)\n")
        self._commit()
        self._write("lib.py", "def fetch_record(a):\n    return a\n")
        result = surface.diff(self.root, "HEAD")
        self.assertIn("tests/test_lib.py", result.obligations["fetch_record"], "테스트 호출부는 진짜 의무다")

    def test_note_is_empty_when_surface_is_stable(self):
        self._write("lib.py", "def f(a):\n    return a\n")
        self._commit()
        self._write("lib.py", "def f(a):\n    return a + 1\n")  # 본문만
        self.assertEqual(surface.note(self.root, "HEAD"), "")

    def test_note_states_obligations_and_its_own_limits(self):
        self._write("lib.py", "def fetch_record(a, b):\n    return a\n")
        self._write("app.py", "from lib import fetch_record\n\nfetch_record(1, 2)\n")
        self._commit()
        self._write("lib.py", "def fetch_record(a):\n    return a\n")
        note = surface.note(self.root, "HEAD")
        self.assertIn("edit obligation", note)
        self.assertIn("app.py", note)
        self.assertIn("name-based", note, "한계를 같이 실어야 전수 증명으로 오독되지 않는다")
        self.assertIn("not a substitute", note)

    def test_bad_base_ref_fails_open(self):
        self._write("lib.py", "def f():\n    pass\n")
        self._commit()
        self.assertEqual(surface.diff(self.root, "no-such-ref").changes, ())
        self.assertEqual(surface.note(self.root, "no-such-ref"), "")

    def test_non_git_directory_fails_open(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(surface.diff(plain, "HEAD").changes, ())


class CandidatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def _write(self, rel: str, body: str) -> None:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)

    def test_method_qualname_searches_the_leaf_identifier(self):
        self._write("caller.py", "obj.render_row(1)\n")
        got = surface.candidates(self.root, ["Table.render_row"])
        self.assertEqual(got["render_row"], ("caller.py",))

    def test_word_boundary_prevents_substring_matches(self):
        self._write("caller.py", "prefix_render_row_suffix = 1\n")
        self.assertEqual(surface.candidates(self.root, ["render_row"]), {})

    def test_empty_input_is_empty_output(self):
        self.assertEqual(surface.candidates(self.root, []), {})
        self.assertEqual(surface.candidates(self.root, None), {})

    def test_excluded_paths_are_skipped(self):
        self._write("a.py", "target()\n")
        self._write("b.py", "target()\n")
        got = surface.candidates(self.root, ["target"], exclude={"a.py"})
        self.assertEqual(got["target"], ("b.py",))


if __name__ == "__main__":
    unittest.main()
