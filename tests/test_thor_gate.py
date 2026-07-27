"""토르 게이트 — 규칙별 진양성과 오탐 가드를 **짝으로** 둔다.

한쪽만 있으면 시험이 규칙을 지켜주지 못한다. 진양성만 있으면 규칙을 넓히는 변경이 통과하고
(오탐이 늘어도 초록), 오탐 가드만 있으면 규칙을 꺼도 통과한다. 그래서 규칙 하나에 두 앵커다.

실행: uv run pytest tests/test_thor_gate.py
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from asgard import thor_gate, thor_lex, thor_rules
from asgard.commands.thor import VERBS, run_thor


def _py(source: str) -> list:
    found = thor_rules.findings(source, "t.py", [])
    assert found is not None, "파싱 실패는 이 시험의 관심사가 아니다"
    return found


def _lex(source: str, lang: str) -> list:
    found = thor_lex.findings(source, "t." + lang, [], lang)
    assert found is not None
    return found


def _rules(found, *, blocking: bool | None = None) -> set[str]:
    return {f.rule for f in found if blocking is None or f.blocking is blocking}


class SqlInterpolation(unittest.TestCase):
    """값 자리(비교 연산자 뒤)만 막는다 — 그 자리는 바인딩으로 전부 대체되므로 반례가 없다."""

    def test_value_slot_blocks(self):
        for source in (
            'q = f"SELECT * FROM users WHERE id = {uid}"',
            'q = "SELECT name FROM t WHERE id = " + uid',
            'q = "SELECT a FROM b WHERE c = %s" % val',
            'q = "UPDATE t SET a = {} WHERE id = 1".format(v)',
        ):
            with self.subTest(source=source):
                self.assertIn("sql-interpolated", _rules(_py(source), blocking=True))

    def test_identifier_slot_only_notes(self):
        """식별자는 바인딩 자체가 불가능하다 — 막으면 고칠 방법이 없는 판정이 된다."""
        found = _py('q = f"SELECT * FROM {table} WHERE id = %s"')
        self.assertIn("sql-interpolated", _rules(found, blocking=False))
        self.assertEqual(set(), _rules(found, blocking=True))

    def test_placeholder_assembly_is_not_a_value(self):
        """`VALUES (` 는 물음표 목록을 조립하는 자리이기도 하다 — 실측 오탐 3건의 형상."""
        java = 'String sql = "INSERT INTO " + s.t() + " (" + cols + ") VALUES (" + placeholders + ")";'
        self.assertEqual(set(), _rules(_lex(java, "java"), blocking=True))

    def test_binding_is_not_interpolation(self):
        for source in (
            'cur.execute("SELECT a FROM b WHERE c = %s", (val,))',
            'q = f"SELECT * FROM users WHERE id = {1}"',
            'msg = f"select an option {name}"',
        ):
            with self.subTest(source=source):
                self.assertEqual(set(), _rules(_py(source)))

    def test_brace_languages_fire(self):
        for lang, source in (
            ("java", 'String q = "SELECT * FROM users WHERE id = " + userId;'),
            ("kotlin", 'val q = "SELECT * FROM users WHERE id = $userId"'),
            ("ts", "const q = `SELECT * FROM users WHERE id = ${id}`;"),
            ("csharp", 'var q = $"SELECT * FROM t WHERE id = {0}";'),
        ):
            with self.subTest(lang=lang):
                self.assertIn("sql-interpolated", _rules(_lex(source, lang), blocking=True))

    def test_comment_is_not_code(self):
        self.assertEqual(set(), _rules(_lex('// SELECT * FROM users WHERE id = " + x', "java")))


class SwallowedException(unittest.TestCase):
    def test_broad_silent_blocks(self):
        self.assertIn("swallowed-exception", _rules(_py("try:\n    x()\nexcept Exception:\n    pass"), blocking=True))

    def test_narrow_type_only_notes(self):
        found = _py("try:\n    x()\nexcept KeyError:\n    pass")
        self.assertIn("swallowed-exception", _rules(found, blocking=False))
        self.assertEqual(set(), _rules(found, blocking=True))

    def test_rationale_in_code_downgrades(self):
        """탄그리스니르 캐논: 근거가 코드에 남은 폴백은 정당한 폴백이다 (실측 오탐 4건의 형상)."""
        found = _py("try:\n    x()\nexcept Exception:\n    pass  # 못 읽으면 다음 턴에 다시 온다")
        self.assertEqual(set(), _rules(found, blocking=True))
        self.assertIn("swallowed-exception", _rules(found, blocking=False))

    def test_handled_is_not_swallowed(self):
        self.assertEqual(set(), _rules(_py("try:\n    x()\nexcept Exception as e:\n    log(e)")))

    def test_untyped_catch_is_broad(self):
        """TS 의 catch 는 타입을 못 붙인다 — 좁다고 읽으면 이 언어에서 규칙이 통째로 죽는다."""
        self.assertIn("swallowed-exception", _rules(_lex("try { f(); } catch (e) { }", "ts"), blocking=True))

    def test_brace_comment_downgrades(self):
        found = _lex("try { f(); } catch (Exception e) { // intentional\n }", "java")
        self.assertEqual(set(), _rules(found, blocking=True))


class ExternalCall(unittest.TestCase):
    def test_missing_timeout_blocks(self):
        self.assertIn("call-no-timeout", _rules(_py("requests.get(url)"), blocking=True))

    def test_timeout_present_is_silent(self):
        self.assertEqual(set(), _rules(_py("requests.get(url, timeout=3)")))

    def test_kwargs_cannot_be_proven_absent(self):
        """`**opts` 안에 timeout 이 있을 수 있다 — 증명 못 하는 것은 미검출로 남긴다."""
        self.assertEqual(set(), _rules(_py("requests.get(url, **opts)")))


class Secret(unittest.TestCase):
    def test_high_entropy_literal_blocks(self):
        self.assertIn("secret-literal", _rules(_py('API_KEY = "sk9f2ba71c4de88a01x"'), blocking=True))

    def test_camel_case_names_are_seen(self):
        """JVM·TS 관용구가 camelCase 다 — 못 보면 그쪽에서 규칙이 사실상 발화하지 않는다."""
        self.assertIn(
            "secret-literal", _rules(_lex('val clientSecret = "sk9f2ba71c4de88a01x"', "kotlin"), blocking=True)
        )

    def test_placeholders_and_short_values_are_not_secrets(self):
        for source in ('API_KEY = "changeme"', 'API_KEY = "abc123"', 'HEADER = "sk9f2ba71c4de88a01x"'):
            with self.subTest(source=source):
                self.assertEqual(set(), _rules(_py(source)))

    def test_env_lookup_is_not_a_literal(self):
        self.assertEqual(set(), _rules(_py('API_KEY = os.environ["API_KEY"]')))


class TransactionAndMoney(unittest.TestCase):
    def test_external_io_in_transaction_blocks(self):
        source = "with db.atomic():\n    save()\n    requests.post(u, timeout=1)"
        self.assertIn("tx-external-io", _rules(_py(source), blocking=True))

    def test_transaction_without_io_is_silent(self):
        self.assertEqual(set(), _rules(_py("with db.atomic():\n    save()")))

    def test_money_float_blocks(self):
        for source in ("amount: float = 0.0", "x = float(total_price)"):
            with self.subTest(source=source):
                self.assertIn("money-float", _rules(_py(source), blocking=True))

    def test_non_money_float_is_silent(self):
        """`ratio`·`total`·`cost` 는 비율·개수·알고리즘 비용이 훨씬 많다 — 넣으면 오탐이 이긴다."""
        for source in ("ratio: float = 0.0", "cost: float = 0.0", "total: float = 0.0"):
            with self.subTest(source=source):
                self.assertEqual(set(), _rules(_py(source)))

    def test_naive_now_notes_but_does_not_block(self):
        found = _py("t = datetime.now()")
        self.assertIn("naive-now", _rules(found, blocking=False))
        self.assertEqual(set(), _rules(found, blocking=True))


class Ratchet(unittest.TestCase):
    """이미 있던 것은 막지 않는다 — 나무 전체를 판정하면 아무 작업도 못 한다."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.dir], check=False))
        for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=self.dir, check=True, capture_output=True)

    def _write(self, text: str) -> None:
        with open(os.path.join(self.dir, "a.py"), "w", encoding="utf-8") as handle:
            handle.write(text)

    def _commit(self) -> None:
        subprocess.run(["git", "add", "-A"], cwd=self.dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "x"], cwd=self.dir, check=True, capture_output=True)

    def test_inherited_debt_does_not_block(self):
        self._write("try:\n    x()\nexcept Exception:\n    pass\n")
        self._commit()
        self._write("try:\n    x()\nexcept Exception:\n    pass\n\n\ndef added():\n    return 1\n")
        report = thor_gate.judge(self.dir, ["a.py"])
        self.assertEqual((), report.blocking)
        self.assertEqual(1, report.inherited)

    def test_new_debt_blocks(self):
        self._write("def f():\n    return 1\n")
        self._commit()
        self._write("def f():\n    try:\n        x()\n    except Exception:\n        pass\n")
        report = thor_gate.judge(self.dir, ["a.py"])
        self.assertEqual({"swallowed-exception"}, {f.rule for f in report.blocking})


class Honesty(unittest.TestCase):
    """ "0건"이 "안 봤다"를 뜻할 수 있으면 게이트가 아니라 알리바이다."""

    def test_unknown_language_is_undetermined_not_clean(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "a.rb"), "w", encoding="utf-8") as handle:
                handle.write("puts 1\n")
            report = thor_gate.judge(root, ["a.rb"])
            self.assertEqual((), report.judged)
            self.assertEqual(1, len(report.undetermined))

    def test_brace_languages_report_unmeasured_rules(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "a.java"), "w", encoding="utf-8") as handle:
                handle.write("class A {}\n")
            report = thor_gate.judge(root, ["a.java"])
            self.assertEqual(("a.java",), report.judged)
            missing = dict(report.unmeasured)["a.java"]
            self.assertIn("call-no-timeout", missing)
            self.assertIn("tx-external-io", missing)
            self.assertIn("money-float", missing)

    def test_python_measures_every_rule(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "a.py"), "w", encoding="utf-8") as handle:
                handle.write("x = 1\n")
            self.assertEqual((), thor_gate.judge(root, ["a.py"]).unmeasured)


class VerbSurface(unittest.TestCase):
    def test_every_verb_has_a_playbook(self):
        for verb in VERBS:
            with self.subTest(verb=verb):
                self.assertEqual(0, run_thor(verb, quiet=True))

    def test_unknown_verb_is_rejected(self):
        self.assertEqual(2, run_thor("nonsense", quiet=True))

    def test_gate_verb_runs_the_judge(self):
        self.assertIn(run_thor("gate", paths=("src/asgard/thor_gate.py",), quiet=True), (0, 1))

    def test_menu_needs_no_argument(self):
        self.assertEqual(0, run_thor(quiet=True))


if __name__ == "__main__":
    unittest.main()
