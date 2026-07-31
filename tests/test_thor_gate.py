"""토르 게이트 — 규칙별 진양성과 오탐 가드를 **짝으로** 둔다.

한쪽만 있으면 시험이 규칙을 지켜주지 못한다. 진양성만 있으면 규칙을 넓히는 변경이 통과하고
(오탐이 늘어도 초록), 오탐 가드만 있으면 규칙을 꺼도 통과한다. 그래서 규칙 하나에 두 앵커다.

실행: uv run pytest tests/test_thor_gate.py
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest

from asgard import thor_gate, thor_lex, thor_rules, thor_survey, thor_trail
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
        """`VALUES (`는 물음표 목록을 조립하는 자리이기도 하다 — 실측 오탐 3건의 형상."""
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

    def test_a_cli_usage_string_is_not_a_query(self):
        """도움말 문자열이 막는 판정을 받았다 — 실측 오탐 2건이 전부 이 형상이었다.

        우연 셋이 겹친다: `--merge`가 동사로, `--from`이 절로, 자리표시자 `<`가 값 자리
        연산자로 읽혔다. SQL에서 `--`는 주석의 시작이므로 어느 쪽으로 읽어도 지우는 것이 맞다.
        """
        usage = "const s = `Usage: cli --from <file> --merge --locale <${LOCALES.join('|')}>`;"
        self.assertEqual(set(), _rules(_lex(usage, "ts")))

    def test_an_interpolated_expression_is_not_query_text(self):
        """백틱 문자열은 `${...}` 안의 식까지 통째로 잡힌다 — 그 안의 `join`이 절로 읽혔다.

        파이썬 판정기는 애초에 구멍 안을 보지 않는다. 구멍을 지우고 재는 것은 중괄호 계열을
        파이썬과 같은 자로 맞추는 일이다.
        """
        self.assertEqual(set(), _rules(_lex("const s = `updated ${rows.join(', ')} rows`;", "ts")))

    def test_a_real_query_still_blocks_beside_them(self):
        """좁힌 뒤에도 진짜 보간은 그대로 막혀야 한다 — 오탐을 지우려다 규칙을 끄면 안 된다."""
        source = "const q = `SELECT id FROM users WHERE id = ${uid}`;"
        self.assertIn("sql-interpolated", _rules(_lex(source, "ts"), blocking=True))


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
        """TS의 catch는 타입을 못 붙인다 — 좁다고 읽으면 이 언어에서 규칙이 통째로 죽는다."""
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
        """`**opts` 안에 timeout이 있을 수 있다 — 증명 못 하는 것은 미검출로 남긴다."""
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
        """`ratio`·`total`·`cost`는 비율·개수·알고리즘 비용이 훨씬 많다 — 넣으면 오탐이 이긴다."""
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
        """JVM 밖 중괄호 계열은 공통 셋 셋만 잰다 — 나머지는 못 쟀다고 실어야 한다."""
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "a.ts"), "w", encoding="utf-8") as handle:
                handle.write("const x = 1;\n")
            report = thor_gate.judge(root, ["a.ts"])
            self.assertEqual(("a.ts",), report.judged)
            missing = dict(report.unmeasured)["a.ts"]
            for rule in ("call-no-timeout", "tx-external-io", "money-float"):
                self.assertIn(rule, missing)

    def test_timeout_is_unmeasured_even_on_jvm(self):
        """타임아웃 설정은 호출부가 아니라 빈 정의·설정 파일에 있다 — 한 문장으로 부재를 증명 못 한다."""
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "a.java"), "w", encoding="utf-8") as handle:
                handle.write("class A {}\n")
            missing = dict(thor_gate.judge(root, ["a.java"]).unmeasured)["a.java"]
            self.assertIn("call-no-timeout", missing)
            self.assertNotIn("money-float", missing)

    def test_python_measures_every_rule(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "a.py"), "w", encoding="utf-8") as handle:
                handle.write("x = 1\n")
            self.assertEqual((), thor_gate.judge(root, ["a.py"]).unmeasured)


class VerbSurface(unittest.TestCase):
    """동사 표면. **개발자의 저장소에 자취를 남기지 않는다** — 시험이 계측을 오염시키면 계측이 거짓말한다.

    `run_thor`는 부른 동사를 `.asgard/thor/trail.jsonl`에 적는다. 시험이 이 저장소 안에서 돌면
    아무도 부른 적 없는 `migrate`·`scale`·`squad`가 자취에 쌓이고, 그 자취로 이행률을 재면
    측정 대상이 측정 도구를 오염시킨 값이 나온다 (실측: 한 세션에서 243회가 그렇게 쌓였다).
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.root], check=False))
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)

    def test_every_verb_has_a_playbook(self):
        for verb in VERBS:
            with self.subTest(verb=verb):
                self.assertEqual(0, run_thor(verb, quiet=True))

    def test_unknown_verb_is_rejected(self):
        self.assertEqual(2, run_thor("nonsense", quiet=True))

    def test_gate_verb_runs_the_judge(self):
        with open(os.path.join(self.root, "a.py"), "w", encoding="utf-8") as handle:
            handle.write("q = f'SELECT id FROM t WHERE id = {uid}'\n")
        self.assertEqual(1, run_thor("gate", paths=("a.py",), quiet=True))  # 막는 판정 → 1

    def test_menu_needs_no_argument(self):
        self.assertEqual(0, run_thor(quiet=True))

    def test_calling_a_verb_leaves_a_trail_entry(self):
        """자취가 안 남으면 이행률을 잴 수 없다 — 표면과 계측이 한 자리에서 이어져 있는지 못박는다."""
        run_thor("shape", quiet=True)
        self.assertEqual(["shape"], [s.verb for s in thor_trail.load(self.root)])


class JvmRules(unittest.TestCase):
    """JVM 에서만 발화하는 둘 — 금액과 트랜잭션. 언어가 더 많이 말해 주는 만큼 더 잰다."""

    def _java(self, source: str, lang: str = "java") -> list:
        from asgard.craft_lex import units

        spans = list((units(source, lang) or {}).values())
        found = thor_lex.findings(source, "t." + lang, spans, lang)
        assert found is not None
        return found

    def test_typed_money_declaration_blocks(self):
        """정적 타입 언어에선 선언에 타입이 붙어 있어 파이썬보다 오히려 잘 보인다."""
        for lang, source in (
            ("java", "class A { void f() { double amount = 0.0; } }"),
            ("java", "class A { void f() { double totalPrice = 0.0; } }"),
            ("kotlin", "class A { fun f() { val amount: Double = 0.0 } }"),
        ):
            with self.subTest(source=source):
                self.assertIn("money-float", _rules(self._java(source, lang), blocking=True))

    def test_bigdecimal_is_the_right_answer_not_a_defect(self):
        self.assertEqual(set(), _rules(self._java("class A { void f() { BigDecimal amount = X; } }")))

    def test_rate_is_not_an_amount(self):
        """환율·이자율은 본래 분수라 부동소수가 옳다 — 실측 오탐 1건이 `USD_TO_VND_RATE` 였다."""
        for name in ("USD_TO_VND_RATE", "exchangeRate", "discountRatio"):
            with self.subTest(name=name):
                source = "class A { void f() { double %s = 1.0; } }" % name
                self.assertEqual(set(), _rules(self._java(source)))

    def test_external_call_inside_transactional_blocks(self):
        source = (
            "class A {\n  @Transactional\n  public void pay() {\n"
            "    repo.save(o);\n    restTemplate.postForObject(url, b, String.class);\n  }\n}"
        )
        self.assertIn("tx-external-io", _rules(self._java(source), blocking=True))

    def test_transactional_without_external_call_is_silent(self):
        source = "class A {\n  @Transactional\n  public void pay() {\n    repo.save(o);\n  }\n}"
        self.assertEqual(set(), _rules(self._java(source)))

    def test_external_call_outside_a_transaction_is_silent(self):
        """애너테이션이 없는 메서드의 외부 호출은 이 규칙의 관심사가 아니다."""
        source = "class A {\n  public void pay() {\n    restTemplate.postForObject(u, b, String.class);\n  }\n}"
        self.assertEqual(set(), _rules(self._java(source)))

    def test_method_name_colliding_with_a_type_keyword_is_still_judged(self):
        """`record`는 자바 record 타입 키워드라 craft_lex가 단위로 못 잡는다. 단위를 못 잡았다는
        이유로 정확성 규칙이 조용히 꺼지면 안 된다 — 실전 검증이 잡은 결함이고, `record`는 결제·
        감사 코드에서 아주 흔한 메서드 이름이다."""
        source = (
            "class A {\n  @Transactional\n  public void record(Long id, double amt) {\n"
            "    jdbc.update(q, id);\n    restTemplate.postForObject(u, amt, String.class);\n  }\n}"
        )
        self.assertIn("tx-external-io", _rules(self._java(source), blocking=True))

    def test_class_level_transactional_covers_its_methods(self):
        """클래스 애너테이션은 실제로 모든 public 메서드를 트랜잭션에 넣는다 — 그대로 읽는다."""
        source = (
            "@Transactional\nclass A {\n  public void pay() {\n"
            "    restTemplate.postForObject(u, b, String.class);\n  }\n}"
        )
        self.assertIn("tx-external-io", _rules(self._java(source), blocking=True))

    def test_bodyless_declaration_is_not_a_transaction_body(self):
        """인터페이스·추상 메서드는 본문이 없다 — 다음 중괄호를 본문으로 오인하면 안 된다."""
        source = (
            "interface A {\n  @Transactional\n  void pay();\n}\n"
            "class B {\n  void other() { restTemplate.postForObject(u, b, String.class); }\n}"
        )
        self.assertEqual(set(), _rules(self._java(source)))

    def test_annotation_does_not_leak_across_methods(self):
        """파일 어딘가의 @Transactional을 끌어오면 안 된다 — 시그니처 바로 위만 본다."""
        source = (
            "class A {\n  @Transactional\n  public void a() { repo.save(o); }\n\n\n\n\n\n"
            "  public void b() {\n    restTemplate.postForObject(u, b, String.class);\n  }\n}"
        )
        self.assertEqual(set(), _rules(self._java(source)))


class LanguageCoverage(unittest.TestCase):
    def test_jvm_measures_more_than_other_brace_languages(self):
        self.assertEqual(set(thor_gate.JVM_RULES) - set(thor_gate.LEX_RULES), {"money-float", "tx-external-io"})

    def test_unmeasured_reflects_the_language(self):
        with tempfile.TemporaryDirectory() as root:
            for name, body in (("a.java", "class A {}\n"), ("b.ts", "const x = 1;\n")):
                with open(os.path.join(root, name), "w", encoding="utf-8") as handle:
                    handle.write(body)
            missing = dict(thor_gate.judge(root, ["a.java", "b.ts"]).unmeasured)
            self.assertNotIn("money-float", missing["a.java"])  # JVM은 잰다
            self.assertIn("money-float", missing["b.ts"])  # TS는 못 잰다
            self.assertIn("call-no-timeout", missing["a.java"])  # 타임아웃은 어디서도 못 잰다


class SurveySidecar(unittest.TestCase):
    """정찰 기록은 세션을 넘어 살아야 하고, 기계가 사람의 답을 지우면 안 된다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.root], check=False))
        self._manifest('[project]\nname="x"\n')
        os.makedirs(os.path.join(self.root, "src"), exist_ok=True)
        with open(os.path.join(self.root, "src", "a.py"), "w", encoding="utf-8") as handle:
            handle.write("x = 1\n")

    def _manifest(self, body: str) -> None:
        with open(os.path.join(self.root, "pyproject.toml"), "w", encoding="utf-8") as handle:
            handle.write(body)

    def test_detection_comes_from_files_not_guesses(self):
        survey = thor_survey.detect(self.root)
        self.assertEqual(["Python"], survey.ecosystems)
        self.assertIn("pytest", survey.verifiers)
        self.assertEqual(["python"], survey.languages)

    def test_judgement_starts_blank_and_is_never_invented(self):
        survey = thor_survey.detect(self.root)
        self.assertEqual(list(thor_survey.JUDGEMENT_KEYS), survey.blanks)
        self.assertEqual({}, survey.judgement)

    def test_record_survives_a_reload(self):
        thor_survey.save(self.root, thor_survey.refresh(self.root, {"layering": "flat"}))
        again = thor_survey.load(self.root)
        assert again is not None
        self.assertEqual("flat", again.text_of("layering"))

    def test_redetection_preserves_human_answers(self):
        """기계가 다시 훑어도 사람이 적어 둔 판단은 남는다 — 안 그러면 아무도 안 적는다."""
        thor_survey.save(self.root, thor_survey.refresh(self.root, {"layering": "flat"}))
        self._manifest('[project]\nname="x"\ndependencies=["requests"]\n')
        merged = thor_survey.refresh(self.root, {})
        self.assertEqual("flat", merged.text_of("layering"))

    def test_manifest_change_marks_the_record_stale(self):
        thor_survey.save(self.root, thor_survey.detect(self.root))
        fresh = thor_survey.load(self.root)
        assert fresh is not None
        self.assertFalse(thor_survey.stale(self.root, fresh))
        self._manifest('[project]\nname="x"\ndependencies=["requests"]\n')
        self.assertTrue(thor_survey.stale(self.root, fresh))

    def _judged_file(self, rel: str) -> None:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("y = 2\n")

    def test_a_written_judgement_carries_when_it_was_written(self):
        """출처 없는 판단은 낡았는지 물어볼 수조차 없다 — 다음 세션이 그대로 믿는다."""
        thor_survey.save(self.root, thor_survey.refresh(self.root, {"layering": "flat"}))
        again = thor_survey.load(self.root)
        assert again is not None
        note = again.judgement["layering"]
        self.assertTrue(note.sourced)
        self.assertTrue(note.at.startswith("20"))
        self.assertEqual([], again.unsourced)

    def test_an_old_record_reads_as_unsourced_not_as_fresh(self):
        """구 형식에는 시각이 없다. 그 칸을 '지금'으로 채우면 사이드카가 거짓말을 시작한다."""
        os.makedirs(os.path.dirname(os.path.join(self.root, thor_survey.REL)), exist_ok=True)
        with open(os.path.join(self.root, thor_survey.REL), "w", encoding="utf-8") as handle:
            json.dump({"judgement": {"layering": "flat"}, "manifests": ["pyproject.toml"]}, handle)
        loaded = thor_survey.load(self.root)
        assert loaded is not None
        self.assertEqual("flat", loaded.text_of("layering"))  # 기록은 버리지 않는다
        self.assertEqual(["layering"], loaded.unsourced)
        self.assertEqual({}, thor_survey.drifted(self.root, loaded))  # 모르는 것을 움직였다고 하지 않는다

    def test_a_new_package_drifts_a_judgement_that_predates_it(self):
        """판단 넷은 전부 코드를 읽어야 아는 것이다 — 매니페스트만 보면 그 넷의 낡음을 못 잰다."""
        thor_survey.save(self.root, thor_survey.refresh(self.root, {"layering": "flat"}))
        recorded = thor_survey.load(self.root)
        assert recorded is not None
        self.assertEqual({}, thor_survey.drifted(self.root, recorded))
        self.assertFalse(thor_survey.stale(self.root, recorded))  # 매니페스트는 그대로다
        self._judged_file("src/adapters/http.py")
        self.assertEqual({"layering": ("구조",)}, thor_survey.drifted(self.root, recorded))

    def test_another_file_in_an_existing_package_is_not_a_layering_change(self):
        """실측에서 이 형상이 매일 나왔다 — 여기서 흔들면 경고가 배경 소음이 되어 아무도 안 본다."""
        thor_survey.save(self.root, thor_survey.refresh(self.root, {"layering": "flat"}))
        recorded = thor_survey.load(self.root)
        assert recorded is not None
        self._judged_file("src/b.py")
        self.assertEqual({}, thor_survey.drifted(self.root, recorded))

    def test_editing_a_file_is_not_a_structure_change(self):
        """내용까지 재면 커밋마다 전부 낡음이 된다 — 언제나 켜진 경고는 꺼진 경고와 같다."""
        thor_survey.save(self.root, thor_survey.refresh(self.root, {"layering": "flat"}))
        recorded = thor_survey.load(self.root)
        assert recorded is not None
        with open(os.path.join(self.root, "src", "a.py"), "w", encoding="utf-8") as handle:
            handle.write("x = 1\n" * 50)
        self.assertEqual({}, thor_survey.drifted(self.root, recorded))

    def test_rewriting_one_judgement_does_not_refresh_the_others(self):
        """옛 판단에 새 지문을 찍으면 그 순간 낡음이 지워진다 — 신선도가 통째로 거짓이 된다."""
        thor_survey.save(self.root, thor_survey.refresh(self.root, {"layering": "flat", "errors": "codes"}))
        self._judged_file("src/adapters/http.py")
        thor_survey.save(self.root, thor_survey.refresh(self.root, {"errors": "exceptions"}))
        recorded = thor_survey.load(self.root)
        assert recorded is not None
        self.assertEqual({"layering": ("구조",)}, thor_survey.drifted(self.root, recorded))
        self.assertEqual("exceptions", recorded.text_of("errors"))

    def test_a_changed_fingerprint_ruler_is_not_reported_as_movement(self):
        """자가 바뀌면 옛 지문과 새 지문은 비교가 안 된다.

        그때 '구조가 움직였다'고 말하면 움직인 것은 저장소가 아니라 판정기인데 사람은 저장소를
        본다 — 실측에서 자를 한 번 바꾸자 판단 넷이 전부 영구 낡음으로 떴다.
        """
        thor_survey.save(self.root, thor_survey.refresh(self.root, {"layering": "flat"}))
        recorded = thor_survey.load(self.root)
        assert recorded is not None
        aged = thor_survey.Note("flat", recorded.judgement["layering"].at, "", "olderruler:deadbeefdeadbeef")
        recorded.judgement["layering"] = aged
        self.assertEqual({}, thor_survey.drifted(self.root, recorded))  # 움직였다고 하지 않는다
        self.assertEqual(["layering"], thor_survey.unmeasured(recorded))  # 못 쟀다고 말한다

    def test_a_current_ruler_is_measured_not_excused(self):
        """못 잰다는 출구가 넓어지면 신선도가 통째로 침묵한다 — 지금 자로 적은 것은 계속 재야 한다."""
        thor_survey.save(self.root, thor_survey.refresh(self.root, {"layering": "flat"}))
        recorded = thor_survey.load(self.root)
        assert recorded is not None
        self.assertEqual([], thor_survey.unmeasured(recorded))
        self._judged_file("src/adapters/http.py")
        self.assertEqual({"layering": ("구조",)}, thor_survey.drifted(self.root, recorded))

    def test_unknown_note_key_is_rejected(self):
        """어휘를 고정하지 않으면 기록이 곧 자유 서술이 되고, 자유 서술은 다음 세션이 못 읽는다."""
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        self.assertEqual(2, run_thor("survey", notes=("nonsense=x",), quiet=True))
        self.assertEqual(2, run_thor("survey", notes=("layering=",), quiet=True))

    def test_corrupt_sidecar_reads_as_absent(self):
        """깨진 기록을 반쯤 믿느니 없는 것으로 친다 — 정찰을 다시 하면 그만이다."""
        os.makedirs(os.path.dirname(os.path.join(self.root, thor_survey.REL)), exist_ok=True)
        with open(os.path.join(self.root, thor_survey.REL), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertIsNone(thor_survey.load(self.root))


class VerbTrail(unittest.TestCase):
    """절차가 지켜지는지 재려면 먼저 적혀야 한다. 이 자취는 **사실만** 적고 판정하지 않는다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.root], check=False))

    def _steps(self, *pairs: tuple[str, int]) -> list[thor_trail.Step]:
        for verb, changed in pairs:
            thor_trail.record(self.root, verb, changed)
        return thor_trail.load(self.root)

    def test_a_verb_call_is_recorded_with_what_the_machine_could_measure(self):
        thor_trail.record(self.root, "shape", 3)
        steps = thor_trail.load(self.root)
        self.assertEqual(1, len(steps))
        self.assertEqual("shape", steps[0].verb)
        self.assertEqual(3, steps[0].changed)
        self.assertTrue(steps[0].at.startswith("20"))
        self.assertIsNone(steps[0].blocking)

    def test_a_gate_run_carries_its_verdict_on_the_same_axis(self):
        """게이트 판정과 그 뒤의 결과가 같은 축에 없으면 '통과 후 무엇이 샜나'를 못 묻는다."""
        thor_trail.record(self.root, "gate", 2, 5)
        seen = thor_trail.adherence(thor_trail.load(self.root))
        self.assertEqual(1, len(seen.gates))
        self.assertEqual(5, seen.gates[0].blocking)
        self.assertEqual(1, seen.blocked_runs)

    def test_a_clean_gate_run_is_not_counted_as_blocked(self):
        thor_trail.record(self.root, "gate", 2, 0)
        self.assertEqual(0, thor_trail.adherence(thor_trail.load(self.root)).blocked_runs)

    def test_adherence_reports_order_skips_and_backtracks_as_facts(self):
        steps = self._steps(("diagnose", 1), ("shape", 1), ("implement", 2), ("shape", 2), ("sweep", 2))
        seen = thor_trail.adherence(steps)
        self.assertEqual(("diagnose", "shape", "implement", "sweep"), seen.called)  # 처음 부른 순서
        self.assertTrue(seen.reached_terminal)
        self.assertIn("survey", seen.skipped)

    def test_never_reaching_the_terminal_verb_is_visible(self):
        """모든 길은 sweep → evidence로 끝난다는 계약이 지켜졌는지가 한 칸으로 보여야 한다."""
        seen = thor_trail.adherence(self._steps(("shape", 1), ("implement", 1)))
        self.assertFalse(seen.reached_terminal)

    def test_the_gate_is_not_a_procedure_verb(self):
        """`gate`는 절차 동사가 아니라 판정이다 — 부른 동사 목록에 섞이면 안 부른 동사가 거짓이 된다."""
        seen = thor_trail.adherence(self._steps(("implement", 1), ("gate", 1), ("sweep", 1)))
        self.assertNotIn("gate", seen.called)
        self.assertNotIn("gate", seen.skipped)

    def test_no_verb_order_is_enforced_because_no_single_arc_exists(self):
        """`diagnose → shape`는 버그 수리에서 옳고 `shape → diagnose`는 신규 기능에서 옳다.

        선형 호를 가정하고 역행을 세면 전자가 결함으로 찍힌다 — 없는 계약을 지표로 만드는 것은
        사실이 아니라 판단이 사실인 척하는 것이라, 그 지표는 넣었다가 걷어냈다.
        """
        self.assertFalse(hasattr(thor_trail.Adherence, "backwards"))
        for sequence in (("diagnose", "shape"), ("shape", "diagnose")):
            with self.subTest(sequence=sequence):
                seen = thor_trail.adherence([thor_trail.Step("", v, 0) for v in sequence])
                self.assertEqual(set(sequence), set(seen.called))

    def test_the_arc_order_comes_from_the_single_source(self):
        """동사를 하나 더할 때 한쪽만 고쳐지면 이행률이 조용히 틀려진다."""
        self.assertEqual(tuple(VERBS), thor_trail._order())

    def test_a_corrupt_line_does_not_discard_the_trail(self):
        thor_trail.record(self.root, "shape", 1)
        with open(os.path.join(self.root, thor_trail.REL), "a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        thor_trail.record(self.root, "sweep", 1)
        self.assertEqual(["shape", "sweep"], [s.verb for s in thor_trail.load(self.root)])

    def test_the_trail_is_bounded(self):
        """자취도 자라기만 하면 자원이다 — 자기 게이트의 unbounded-accumulator와 같은 자를 자신에게."""
        for _ in range(thor_trail.KEEP + 20):
            thor_trail.record(self.root, "shape", 0)
        self.assertEqual(thor_trail.KEEP, len(thor_trail.load(self.root)))

    def _quest(self, qid: str, *events: dict) -> None:
        qdir = os.path.join(self.root, ".asgard", "quest")
        os.makedirs(qdir, exist_ok=True)
        with open(os.path.join(qdir, qid + ".jsonl"), "w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")

    def test_a_clean_gate_followed_by_a_failed_verify_is_an_escape(self):
        """claim ④ 의 축 — 새 기록을 만들지 않고 있는 두 기록을 시각으로 잇는다."""
        thor_trail.record(self.root, "gate", 2, 0)
        at = thor_trail.load(self.root)[0].at
        self._quest("q1", {"event": "verify", "verdict": "FAIL", "at": "2099-01-01T00:00:00+00:00"})
        found = thor_trail.escapes(self.root)
        self.assertEqual(1, len(found))
        self.assertTrue(found[0].escaped)
        self.assertEqual(at, found[0].gate_at)

    def test_a_blocking_gate_followed_by_a_failure_is_not_an_escape(self):
        """게이트가 이미 막고 있었으면 검증이 잡은 것은 새어 나간 것이 아니다."""
        thor_trail.record(self.root, "gate", 2, 3)
        self._quest("q1", {"event": "verify", "verdict": "FAIL", "at": "2099-01-01T00:00:00+00:00"})
        self.assertFalse(thor_trail.escapes(self.root)[0].escaped)

    def test_a_clean_gate_followed_by_a_pass_is_not_an_escape(self):
        thor_trail.record(self.root, "gate", 2, 0)
        self._quest("q1", {"event": "verify", "verdict": "PASS", "at": "2099-01-01T00:00:00+00:00"})
        self.assertFalse(thor_trail.escapes(self.root)[0].escaped)

    def test_a_verify_with_no_prior_gate_is_not_a_sample(self):
        """게이트를 안 돌린 검증을 표본에 넣으면 분모가 부풀어 비율이 통째로 거짓이 된다."""
        thor_trail.record(self.root, "gate", 2, 0)
        self._quest("q1", {"event": "verify", "verdict": "FAIL", "at": "2000-01-01T00:00:00+00:00"})
        self.assertEqual([], thor_trail.escapes(self.root))

    def test_non_verify_events_are_not_counted(self):
        thor_trail.record(self.root, "gate", 2, 0)
        self._quest("q1", {"event": "work", "at": "2099-01-01T00:00:00+00:00"})
        self.assertEqual([], thor_trail.escapes(self.root))

    def test_no_gate_run_means_no_join_at_all(self):
        self._quest("q1", {"event": "verify", "verdict": "FAIL", "at": "2099-01-01T00:00:00+00:00"})
        self.assertEqual([], thor_trail.escapes(self.root))

    def test_recording_never_blocks_the_verb(self):
        """계측이 작업을 막으면 그것은 계측이 아니라 관문이다."""
        blocked = os.path.join(self.root, "ro")
        os.makedirs(blocked)
        os.chmod(blocked, 0o500)
        self.addCleanup(os.chmod, blocked, 0o700)
        thor_trail.record(blocked, "shape", 0)  # 예외가 새어 나오면 실패
        self.assertEqual([], thor_trail.load(blocked))


if __name__ == "__main__":
    unittest.main()
