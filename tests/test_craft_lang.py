"""다국어 미시 형상 앵커 — 어휘 분석기와 C 계열 규칙.

실행: uv run pytest tests/test_craft_lang.py

파서 없이 재기 때문에 여기서 고정할 것은 "잰 값"이 아니라 **잘못 읽지 않는가**다. 실코퍼스
2,100파일 검증에서 나온 결함이 전부 같은 종류였다 — 문자열·주석·정규식·애너테이션을 코드로
읽어서 함수 경계가 통째로 어긋나는 것. 그래서 그 다섯을 하나씩 못박는다.

C 규칙은 규칙마다 진양성 하나와 음성 대조군 하나를 짝으로 둔다. 회수해 주는 런타임이 없는
언어에서 오탐은 그냥 소음이 아니라 잘못된 수리를 부른다.
"""

from __future__ import annotations

import unittest

from asgard import craft_c, craft_lex


def _units(source: str, lang: str) -> dict:
    found = craft_lex.units(source, lang)
    assert found is not None, "중괄호 균형이 깨져 미판정으로 떨어졌다"
    return found


def _rules(source: str, lang: str = "c") -> list[str]:
    units = _units(source, lang)
    return [f.rule for f in craft_c.pattern_findings(source, "p.c", list(units.values()), lang)]


class ScrubTest(unittest.TestCase):
    """세척이 틀리면 그 뒤의 모든 판정이 틀린다 — 여기가 다국어 판정의 바닥이다."""

    def test_braces_inside_strings_and_comments_do_not_count(self):
        src = 'void f(void) {\n    const char *s = "}{";  /* } */  // }\n}\n'
        self.assertEqual(list(_units(src, "c")), ["f"])

    def test_line_numbers_survive_scrubbing(self):
        src = "/* one\n   two */\nvoid f(void) {\n}\n"
        self.assertEqual(_units(src, "c")["f"].line, 3)

    def test_a_multiline_template_literal_does_not_break_the_file(self):
        """백틱 상태를 줄 사이에 안 들고 다니면 HTML 조각의 중괄호가 함수 경계를 무너뜨린다."""
        src = "export function f(): string {\n  return `\n    <div>{ not code }\n  `;\n}\n"
        self.assertEqual(list(_units(src, "ts")), ["f"])

    def test_a_regex_literal_is_not_a_string(self):
        """`/[\",]/` 안의 따옴표를 문자열 시작으로 읽으면 뒤의 중괄호를 통째로 삼킨다."""
        src = 'export function f(v: string): boolean {\n  if (/[",\\n]/.test(v)) {\n    return true;\n  }\n  return false;\n}\n'
        self.assertEqual(list(_units(src, "ts")), ["f"])

    def test_division_is_not_a_regex(self):
        src = "export function f(a: number, b: number): number {\n  return a / b / 2;\n}\n"
        self.assertEqual(list(_units(src, "ts")), ["f"])

    def test_unbalanced_braces_are_undetermined_not_empty(self):
        self.assertIsNone(craft_lex.units("void f(void) {\n", "c"))


class ExtractTest(unittest.TestCase):
    def test_a_control_block_is_not_a_function(self):
        src = "void f(int a) {\n    if (a) {\n        a++;\n    }\n    while (a) { a--; }\n}\n"
        self.assertEqual(list(_units(src, "c")), ["f"])

    def test_a_type_body_is_not_a_function(self):
        src = "struct P { int a; };\n\nvoid f(void) {\n}\n"
        self.assertEqual(list(_units(src, "c")), ["f"])

    def test_a_java_annotation_is_not_a_function(self):
        """`@SuppressWarnings("x")`를 서명으로 읽으면 클래스 본문 전체가 함수 하나가 된다."""
        src = '@SuppressWarnings("unchecked")\npublic class A {\n    void run() {\n        int x = 1;\n    }\n}\n'
        self.assertEqual(list(_units(src, "java")), ["run"])

    def test_a_method_inside_a_class_is_found(self):
        src = "export class S {\n  run(rows: string[]): number {\n    return rows.length;\n  }\n}\n"
        self.assertEqual(list(_units(src, "ts")), ["run"])

    def test_an_annotated_method_is_still_a_function(self):
        src = "public class A {\n    @Override\n    public void run() {\n        int x = 1;\n    }\n}\n"
        self.assertEqual(list(_units(src, "java")), ["run"])


class DepthTest(unittest.TestCase):
    def test_a_parenthesised_for_header_counts_as_one_level(self):
        """`for (i = 0; i < n; i++)`의 헤더 세미콜론이 절을 끝내면 for가 중첩에서 빠진다."""
        src = "void f(int n) {\n    for (int i = 0; i < n; i++) {\n        if (i) {\n            n--;\n        }\n    }\n}\n"
        self.assertEqual(_units(src, "c")["f"].depth, 2)

    def test_an_unparenthesised_for_header_counts_too(self):
        """Go의 3절 for는 괄호가 없어 세미콜론 규칙을 그대로 쓰면 반대로 작동한다."""
        src = "func F(n int) {\n\tfor i := 0; i < n; i++ {\n\t\tif i > 0 {\n\t\t\tn--\n\t\t}\n\t}\n}\n"
        self.assertEqual(_units(src, "go")["F"].depth, 2)

    def test_an_initialiser_list_is_not_nesting(self):
        src = "void f(void) {\n    int xs[3] = { 1, 2, 3 };\n    struct P p = { .a = 1 };\n}\n"
        self.assertEqual(_units(src, "c")["f"].depth, 0)


class CMemoryTest(unittest.TestCase):
    def test_an_allocation_without_an_owner_is_caught(self):
        src = "void f(int n) {\n    char *b = malloc(n);\n    if (!b) return;\n    b[0] = 1;\n}\n"
        self.assertIn("c-alloc-unfreed", _rules(src))

    def test_freeing_returning_or_handing_off_clears_it(self):
        freed = "void f(int n) {\n    char *b = malloc(n);\n    if (!b) return;\n    free(b);\n}\n"
        returned = "char *f(int n) {\n    char *b = malloc(n);\n    if (!b) return NULL;\n    return b;\n}\n"
        given = "void f(int n) {\n    char *b = malloc(n);\n    if (!b) return;\n    take(b);\n}\n"
        out_param = "void f(char **out, int n) {\n    *out = malloc(n);\n}\n"
        for src in (freed, returned, given, out_param):
            self.assertNotIn("c-alloc-unfreed", _rules(src), src)

    def test_using_a_resource_inside_a_return_is_not_handing_it_off(self):
        """`return fgetc(f)`는 자원을 **읽은 결과**를 돌려줄 뿐이고 자원은 이 함수에 남는다.

        "반환문 안에 이름이 보인다"로 읽으면 C에서 가장 흔한 형상에서 규칙이 조용히 꺼진다 —
        같은 누수가 `int c = fgetc(f); return c;`로 쓰면 잡히고 한 줄로 합치면 안 잡혔다.
        """
        used = 'int f(const char *p) {\n    FILE *h = fopen(p, "r");\n    if (!h) return -1;\n    return fgetc(h);\n}\n'
        indexed = "int f(int n) {\n    char *b = malloc(n);\n    if (!b) return -1;\n    return b[0];\n}\n"
        self.assertIn("c-handle-unclosed", _rules(used))
        self.assertIn("c-alloc-unfreed", _rules(indexed))

    def test_returning_the_resource_itself_still_hands_it_off(self):
        """좁히는 쪽이 넓히는 쪽을 잡아먹으면 안 된다 — 진짜 인계 네 형태는 그대로 통과해야 한다."""
        plain = "char *f(int n) {\n    char *b = malloc(n);\n    if (!b) return NULL;\n    return b;\n}\n"
        cast = "char *f(int n) {\n    char *b = malloc(n);\n    if (!b) return NULL;\n    return (char *)b;\n}\n"
        parens = "char *f(int n) {\n    char *b = malloc(n);\n    if (!b) return NULL;\n    return (b);\n}\n"
        ternary = (
            "char *f(int n, int c) {\n    char *b = malloc(n);\n    if (!b) return NULL;\n    return c ? b : NULL;\n}\n"
        )
        for src in (plain, cast, parens, ternary):
            self.assertNotIn("c-alloc-unfreed", _rules(src), src)

    def test_an_unchecked_allocation_is_caught_and_a_checked_one_is_not(self):
        unchecked = "void f(int n) {\n    char *b = malloc(n);\n    b[0] = 1;\n    free(b);\n}\n"
        checked = "void f(int n) {\n    char *b = malloc(n);\n    if (b == NULL) return;\n    free(b);\n}\n"
        self.assertIn("c-alloc-unchecked", _rules(unchecked))
        self.assertNotIn("c-alloc-unchecked", _rules(checked))

    def test_realloc_into_itself_is_caught(self):
        src = "void f(char *p, int n) {\n    p = realloc(p, n);\n    free(p);\n}\n"
        self.assertIn("c-realloc-self-assign", _rules(src))

    def test_realloc_through_a_temporary_is_not_caught(self):
        """실패해도 원본이 살아 있는 정석 형태 — 이걸 걸면 올바른 코드가 막힌다."""
        src = (
            "void f(int n) {\n"
            "    char *p = malloc(n);\n"
            "    if (!p) return;\n"
            "    char *tmp = realloc(p, n * 2);\n"
            "    if (tmp) p = tmp;\n"
            "    free(p);\n"
            "}\n"
        )
        self.assertEqual(_rules(src), [])

    def test_an_unclosed_handle_is_caught_and_using_it_is_not_handing_it_off(self):
        leaked = 'void f(const char *p) {\n    FILE *h = fopen(p, "r");\n    if (!h) return;\n    fgetc(h);\n}\n'
        closed = 'void f(const char *p) {\n    FILE *h = fopen(p, "r");\n    if (!h) return;\n    fclose(h);\n}\n'
        self.assertIn("c-handle-unclosed", _rules(leaked))
        self.assertNotIn("c-handle-unclosed", _rules(closed))


class CBoundsAndCostTest(unittest.TestCase):
    def test_a_copy_that_cannot_know_the_destination_size_is_caught(self):
        src = "void f(char *d, const char *s) {\n    strcpy(d, s);\n}\n"
        self.assertIn("c-unbounded-copy", _rules(src))

    def test_a_sized_copy_is_not_caught(self):
        src = 'void f(char *d, const char *s, size_t n) {\n    snprintf(d, n, "%s", s);\n}\n'
        self.assertEqual(_rules(src), [])

    def test_recounting_length_every_iteration_is_caught(self):
        src = "void f(const char *s) {\n    for (size_t i = 0; i < strlen(s); i++) { (void)s[i]; }\n}\n"
        self.assertIn("c-quadratic-scan", _rules(src))

    def test_hoisting_the_length_is_not_caught(self):
        src = "void f(const char *s) {\n    size_t n = strlen(s);\n    for (size_t i = 0; i < n; i++) { (void)s[i]; }\n}\n"
        self.assertEqual(_rules(src), [])


class SilentLanguageTest(unittest.TestCase):
    def test_a_language_without_rules_is_measured_for_shape_but_makes_no_claims(self):
        """규칙이 없는 언어에 없는 판정을 지어내지 않는다 — 형상만 재고 침묵한다."""
        src = "func F(n int) int {\n\treturn n\n}\n"
        units = _units(src, "go")
        self.assertEqual(list(units), ["F"])
        self.assertEqual(craft_c.pattern_findings(src, "p.go", list(units.values()), "go"), [])


if __name__ == "__main__":
    unittest.main()
