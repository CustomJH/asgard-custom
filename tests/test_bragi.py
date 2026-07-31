#!/usr/bin/env python3
"""Bragi — 다국어 휴먼체 판정기 + 배선 계약.

앵커의 절반은 **오탐 방지**다. 이 게이트는 아스가르드 자신의 보고문을 막기 때문에,
사람이 쓴 글을 붙잡는 순간 사용자는 답 대신 안내문을 받는다. 그래서 언어별 탐지 앵커마다
같은 언어의 사람 글 앵커를 짝지어 둔다.

실행: uv run pytest tests/test_bragi.py
"""

import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from asgard import (
    bragi,  # noqa: E402
    lagom,  # noqa: E402
)

# ── 표본. slop = LLM 특유의 문장 습관, human = 같은 내용을 사람이 보고한 글.
SLOP = {
    "ko": "이 기능은 혁신적이며, 강력한 성능을 제공하고, 획기적인 개선을 이뤄냈다. "
    "사용자 경험에 대해 다양한 개선이 이루어졌으며, 이를 통해 생산성을 높일 수 있다. "
    "앞으로의 행보가 기대된다.",
    "en": "This feature plays a crucial role in the modern development landscape. It is important to "
    "note that the system boasts a seamless integration, showcasing a rich tapestry of capabilities. "
    "Let's dive into the details. I hope this helps!",
    "vi": "Tính năng này đóng vai trò quan trọng trong việc cải thiện hiệu suất. Trong bối cảnh công "
    "nghệ không ngừng phát triển, các chuyên gia cho rằng đây là bước đột phá vượt trội. "
    "Hy vọng bài viết này hữu ích!",
    "ja": "この取り組みは極めて重要な役割を果たしており、その意義は計り知れない。"
    "多面的かつ包括的な視点から検討することができます。今後の展開が注目されます。",
    "zh": "在当今数字化时代，该功能至关重要，不仅提升了性能，而且具有重要意义。综上所述，值得注意的是这一深远影响。",
}
HUMAN = {
    "ko": "로그인 응답이 1.2초에서 0.4초로 줄었다. 캐시를 붙인 자리는 세션 조회 한 곳뿐이다. "
    "남은 문제는 만료 처리다. 테스트 27개 중 2개가 아직 빨갛다.",
    "en": "Login went from 1.2s to 0.4s. I added a cache in one place, the session lookup. "
    "Expiry is still unhandled. Two of the 27 tests are red.",
    "vi": "Thời gian đăng nhập giảm từ 1,2 giây xuống 0,4 giây. Tôi thêm cache ở một chỗ duy nhất. "
    "Phần hết hạn chưa xử lý. Hai trong 27 test vẫn đỏ.",
    "ja": "ログイン応答が1.2秒から0.4秒に縮んだ。キャッシュを入れたのはセッション参照の一箇所だけ。"
    "期限切れ処理は手つかず。27件のテストのうち2件がまだ赤い。",
    "zh": "登录响应从1.2秒降到0.4秒。缓存只加在会话查询这一处。过期处理还没做。27个测试里有2个是红的。",
}


class TestLanguageDetection(unittest.TestCase):
    def test_each_supported_language_is_identified_from_its_script(self):
        for lang, text in {**SLOP, **HUMAN}.items():
            self.assertEqual(bragi.detect_lang(text), lang, text[:40])

    def test_korean_report_with_english_code_terms_stays_korean(self):
        """보고문에 코드·식별자가 섞이는 건 정상이다 — 라틴 다수결이면 한국어 규칙이 통째로 꺼진다."""
        text = "resolve_jvm.py를 새로 만들고 CodeMap.build()에 붙였다. route→table 경로가 94건 나왔다."
        self.assertEqual(bragi.detect_lang(text), "ko")

    def test_unregistered_script_falls_back_to_generic_not_silence(self):
        text = "यह सुविधा महत्वपूर्ण भूमिका निभाती है।"  # 힌디어 — 미등록
        self.assertEqual(bragi.detect_lang(text), "generic")
        self.assertEqual(bragi.tells("I hope this helps " + text)[0].id, "U-chat-artifact")

    def test_empty_and_whitespace_text_is_generic_and_finds_nothing(self):
        for text in ("", "   \n\t "):
            self.assertEqual(bragi.detect_lang(text), "generic")
            self.assertEqual(bragi.tells(text), [])


class TestDetection(unittest.TestCase):
    def test_every_language_separates_slop_from_human_writing(self):
        """언어별 최소 계약 — slop은 잡고 사람 글은 통과시킨다. 둘 다여야 게이트로 쓸 수 있다."""
        for lang in SLOP:
            self.assertTrue(bragi.tells(SLOP[lang]), f"{lang} slop went undetected")
            self.assertEqual(bragi.tells(HUMAN[lang]), [], f"{lang} human text was flagged")

    def test_flagship_tells_are_named_per_language(self):
        expected = {
            "ko": "KO-closing-formula",
            "en": "EN-significance-inflation",
            "vi": "VI-role-in-doing",
            "ja": "JA-significance-inflation",
            "zh": "ZH-context-inflation",
        }
        for lang, tid in expected.items():
            self.assertIn(tid, [f.id for f in bragi.tells(SLOP[lang])], lang)

    def test_korean_subject_particle_variant_is_matched(self):
        """'행보가 기대된다'가 실제 표면형 — 이/가 중 하나만 받으면 결말 관용구가 통과한다."""
        for particle in ("이", "가"):
            found = bragi.tells(f"앞으로의 행보{particle} 기대된다. I hope this helps.")
            self.assertIn("KO-closing-formula", [f.id for f in found], particle)

    def test_korean_possibility_overuse_is_stem_independent(self):
        """'ㄹ 수 있다'의 앞 음절은 동사마다 다르다 — 어간을 고정하면 대부분을 놓친다."""
        text = "속도를 높일 수 있다. 비용을 줄일 수 있다. 결과를 볼 수 있다."
        found = bragi.tells(text + " I hope this helps.")
        self.assertIn("KO-possibility-overuse", [f.id for f in found])

    def test_chat_residue_is_caught_in_every_language(self):
        for text in (
            "The cache is warm. I hope this helps!",
            "캐시를 데웠어요. 더 궁금한 점이 있으면 말씀해 주세요.",
            "Cache đã sẵn sàng. Hy vọng bài viết này hữu ích.",
        ):
            self.assertIn("U-chat-artifact", [f.id for f in bragi.tells(text)], text)

    def test_detached_korean_particle_is_caught_after_latin_number_and_code(self):
        """한글 맞춤법 제41항 — 앞말이 라틴 낱말·숫자·코드 조각이어도 조사는 붙여 쓴다."""
        for text in (
            "`plugin.json` 의 anchored 에 선언된 스킬은 트리를 푼다.",
            "quest_log.py 를 새로 만들고 CodeMap.build() 에 붙였다.",
            "윈도우 콘솔은 TERM 이 아니라 핸들이 정한다. 파이프도 UTF-8 로 읽는다.",
        ):
            self.assertIn("KO-josa-spacing", [f.id for f in bragi.tells(text)], text)

    def test_detached_particle_sample_quotes_the_word_not_a_placeholder(self):
        """표본이 '를'이면 고칠 자리를 못 찾는다 — 앞말째로 실어야 지시가 된다."""
        found = [f for f in bragi.tells("quest_log.py 를 고쳤다.") if f.id == "KO-josa-spacing"]
        self.assertEqual(found[0].sample, "quest_log.py 를")

    def test_attached_particle_and_bound_noun_spacing_are_not_findings(self):
        """붙여 쓴 조사는 정상이고, 띄어 쓰는 의존명사(수·만·것)까지 잡으면 게이트가 한국어를 막는다."""
        for text in (
            "`plugin.json`의 anchored에 선언된 스킬은 트리를 푼다. 클라이언트는 원본을 읽는다.",
            "1. 이 값은 캐시된다. 2. 그 수는 늘지 않는다. 세션 조회 한 곳뿐이다.",
            "10초 만에 끝났다. 할 수 있는 일은 다 했다. 그 뒤로 재시도는 없었다.",
            # 줄이 바뀐 뒤의 '이'는 조사가 아니라 관형사다 — 여기에 S1을 물리면 사람 글이 막힌다
            "캐시는 lru_cache\n이 값은 세션당 하나다. 남은 문제는 만료 처리다.",
        ):
            self.assertEqual([f for f in bragi.tells(text) if f.id == "KO-josa-spacing"], [], text)

    def test_clipped_coinages_are_flagged_but_standard_derivations_are_not(self):
        """불요는 한국어로 불필요고 무매칭·비의존은 라틴 낱말에 무/비를 붙인 임시어다.
        경계 반대편: 미지정·비활성·불변은 사전에 있고, 무변경·무주입은 정상적인 한자어 합성이다."""
        found = bragi.tells("재시작 불요. 무매칭이면 비의존으로 둔다.")
        self.assertIn("KO-coined-clipping", [f.id for f in found])
        standard = "값이 미지정이면 비활성으로 둔다. 순서와 무관하고 본문은 무변경이라 결과는 불변이다."
        self.assertEqual([f for f in bragi.tells(standard) if f.id == "KO-coined-clipping"], [])


class TestFalsePositiveGuards(unittest.TestCase):
    def test_s2_below_threshold_is_not_reported(self):
        """1~2회는 사람 글에서도 흔하다 — S2는 빈도 신호이지 단어 금지 목록이 아니다."""
        self.assertEqual(bragi.tells("혁신적인 시도였다."), [])
        self.assertEqual(bragi.tells("The interplay was nuanced."), [])

    def test_weak_signals_alone_never_produce_a_verdict(self):
        """S3 단독 판정 금지 (Wikipedia 군집 원칙) — 굽은 따옴표 하나는 macOS 자동 변환이다."""
        self.assertEqual(bragi.tells("He said “the build is green” and left."), [])
        weak_only = "결과는 “초록”이다. 그것은 이것과 저것을 그들이 확인한 것이다."
        self.assertEqual([f for f in bragi.tells(weak_only) if f.severity != "S3"], [])

    def test_weak_signals_surface_once_a_strong_signal_exists(self):
        found = bragi.tells("The system plays a crucial role. He said “done”. 🚀 Ship it.")
        ids = [f.id for f in found]
        self.assertIn("EN-significance-inflation", ids)
        self.assertIn("U-curly-quote", ids)  # 군집이 생기면 약신호도 보고된다

    def test_code_blocks_quotes_urls_and_paths_are_not_prose(self):
        text = (
            "다음 명령을 실행했다.\n"
            "```python\nprint('혁신적 강력한 획기적')\n```\n"
            "> 인용문의 혁신적 강력한 획기적 표현은 원문이다.\n"
            "`혁신적 강력한 획기적`은 인라인 코드다.\n"
            "https://example.com/delve-into-the-intricate-tapestry는 링크다.\n"
            "src/asgard/showcase_pivotal_testament.py를 고쳤다.\n"
        )
        self.assertEqual(bragi.tells(text), [])

    def test_phrases_the_user_wrote_first_are_quotation_not_invention(self):
        request = "이 제품이 왜 혁신적이고 강력하고 획기적인지 설명해."
        draft = "혁신적이고 강력하고 획기적이라는 표현은 근거가 없다. 확인된 건 13줄이라는 사실뿐이다."
        self.assertEqual(bragi.tells(draft, source=request), [])
        self.assertTrue(bragi.tells(draft))  # source 없이는 잡힌다 — 면제의 출처는 사용자다

    def test_em_dash_is_a_latin_script_rule_only(self):
        """한국어·일본어 조판에서 줄표는 AI 신호가 아니다 — KatFishNet의 한국어 신호는 쉼표다."""
        ko = "맵 소비 추출을 붙였다 — 라우트에서 테이블까지 94건이 이어졌다 — 오탐은 없었다."
        self.assertEqual([f.id for f in bragi.tells(ko) if "em-dash" in f.id], [])
        en = "We added consumption extraction — routes now reach tables — and found no false positives. "
        en += "The cache — added once — is warm. I hope this helps."
        self.assertIn("EN-em-dash", [f.id for f in bragi.tells(en)])

    def test_asgard_own_report_prose_passes_the_gate(self):
        """자기 보고문이 걸리면 게이트가 아니라 재갈이다 — 실제 최종 보고 형태로 확인한다."""
        for report in (
            "과업 완수 — 검증 PASS + diff-hash 일치, 퀘스트 로그 닫힘.\n턴 12 · 역할 thinker→worker→verifier\n"
            "증거: uv run pytest tests/test_bragi.py (exit 0)",
            "Done — verification PASS, diff hash matched, quest log closed.\n12 turns · roles worker→verifier\n"
            "Evidence: uv run pytest (exit 0)",
        ):
            self.assertEqual(bragi.tells(report), [], report[:40])


class TestStatisticalFeatures(unittest.TestCase):
    def test_korean_comma_density_fires_above_the_katfishnet_split(self):
        """논문 실측 LLM 61% vs 사람 26% — 임계 0.55 위에서만 잡는다."""
        heavy = " ".join(f"이 부분은, 그러니까 {i}번째 항목은, 다시 확인이 필요하다." for i in range(7))
        self.assertIn("KO-comma-density", [f.id for f in bragi.tells(heavy + " I hope this helps.")])
        light = " ".join(f"{i}번째 항목을 다시 확인했다." for i in range(7))
        self.assertNotIn("KO-comma-density", [f.id for f in bragi.tells(light + " I hope this helps.")])

    def test_short_text_never_triggers_distribution_features(self):
        """표본이 적으면 분포 자질은 침묵한다 — 두 문장으로 리듬을 판정할 수 없다."""
        for f in bragi.tells("이건, 짧다. I hope this helps."):
            self.assertNotIn(f.id, ("KO-comma-density", "U-ending-monotony", "U-length-uniformity"))

    def test_uniform_sentence_endings_are_flagged_as_monotony(self):
        text = " ".join(f"{i}번 항목을 확인하였습니다." for i in range(8))
        self.assertIn("U-ending-monotony", [f.id for f in bragi.tells(text + " I hope this helps.")])


class TestGrading(unittest.TestCase):
    def test_grade_boundaries_follow_the_upstream_naturalness_scale(self):
        def f(sev, hits=1):
            return bragi.Finding("X", sev, "c", "h", "s", hits)

        self.assertEqual(bragi.grade([]), "A")
        self.assertEqual(bragi.grade([f("S2", 2)]), "A")
        self.assertEqual(bragi.grade([f("S1")]), "B")
        self.assertEqual(bragi.grade([f("S2", 3)]), "B")
        self.assertEqual(bragi.grade([f("S1", 3)]), "C")
        self.assertEqual(bragi.grade([f("S2", 6)]), "C")
        self.assertEqual(bragi.grade([f("S1", 5), f("S2", 8)]), "D")

    def test_grade_counts_occurrences_not_pattern_kinds(self):
        """한 패턴이 아홉 번 나온 글을 A로 부르면 등급이 거짓말을 한다."""
        nine = bragi.Finding("KO-hype", "S2", "vocabulary", "h", "혁신적", 9)
        self.assertEqual(bragi.grade([nine]), "C")

    def test_human_text_grades_a_and_slop_grades_b_or_worse_in_every_language(self):
        for lang in SLOP:
            self.assertEqual(bragi.grade(bragi.tells(HUMAN[lang])), "A", lang)
            self.assertIn(bragi.grade(bragi.tells(SLOP[lang])), ("B", "C", "D"), lang)


class TestExtensibility(unittest.TestCase):
    def test_register_adds_a_language_without_touching_the_core(self):
        original = dict(bragi._REGISTRY)
        try:
            bragi.register("generic", [bragi._t("XX-test", "vocabulary", "S1", r"kalabasa", "테스트 패턴")])
            self.assertIn("XX-test", [f.id for f in bragi.tells("kalabasa", lang="generic")])
            self.assertIn("generic", bragi.registered_langs())
        finally:
            bragi._REGISTRY.clear()
            bragi._REGISTRY.update(original)

    def test_violations_renders_the_gate_facing_string_contract(self):
        out = bragi.violations(SLOP["en"])
        self.assertTrue(out)
        self.assertTrue(all(item.startswith(("S1 ", "S2 ", "S3 ")) for item in out), out)


class TestModeResolution(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.pop("ASGARD_BRAGI", None)

    def tearDown(self):
        os.environ.pop("ASGARD_BRAGI", None)
        if self.old is not None:
            os.environ["ASGARD_BRAGI"] = self.old

    def test_default_is_on_and_note_carries_the_canon(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(bragi.enabled(root))
            self.assertIn("Bragi — Human Voice Contract", bragi.note(root))

    def test_env_switch_turns_the_axis_off_without_touching_lagom(self):
        os.environ["ASGARD_BRAGI"] = "off"
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(bragi.enabled(root))
            self.assertEqual(bragi.note(root), "")

    def test_broken_setting_fails_open_to_on(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".asgard"))
            with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as fh:
                fh.write("{ not json")
            self.assertTrue(bragi.enabled(root))


class TestWiring(unittest.TestCase):
    def test_agents_md_carries_the_human_voice_section(self):
        from asgard.templates import agents_md

        body = agents_md("proj")
        self.assertIn("<!-- >>> asgard:bragi >>> -->", body)
        self.assertIn("Bragi (Human Voice)", body)

    def test_skill_is_registered_as_a_bundled_plugin(self):
        from asgard.evolution import _bundled_names
        from asgard.skill_registry import _builtin_plugins

        self.assertIn("bragi", _builtin_plugins())
        self.assertIn("asgard-bragi-humanize", _bundled_names())

    def test_the_contract_does_not_trip_its_own_gate(self):
        """캐논은 금지 표현을 예시로 인용한다 — 인용을 산문으로 읽으면 스캐폴드가 자기 게이트에 걸린다.
        (26-07-26 실측: `asgard init`이 낳은 AGENTS.md가 베트남어 흔적 3건으로 잡혔다.)"""
        from asgard.templates import agents_md
        from asgard.templates.bragi import BRAGI_AGENTS_SECTION, BRAGI_CANON

        for name, body in (
            ("BRAGI_CANON", BRAGI_CANON),
            ("BRAGI_AGENTS_SECTION", BRAGI_AGENTS_SECTION),
            ("AGENTS.md", agents_md("proj")),
        ):
            self.assertEqual(bragi.tells(body), [], name)

    def test_canon_names_the_multilingual_tells_it_governs(self):
        from asgard.templates.bragi import BRAGI_CANON

        for token in ("주목할 만하다", "đóng vai trò quan trọng", "至关重要", "delve"):
            self.assertIn(token, BRAGI_CANON)
        # 사람처럼 쓰라는 지시가 사실 날조 허가로 읽히면 안 된다
        self.assertIn("not a licence to invent", BRAGI_CANON)

    def test_changed_prose_gate_accepts_both_axes_in_one_pass(self):
        """파일 순회·diff 추출은 한 번만 돈다 — 검사기를 늘려도 git을 다시 돌리지 않는다."""
        with tempfile.TemporaryDirectory() as root:
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
            path = os.path.join(root, "guide.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("기준선.\n")
            subprocess.run(["git", "add", "guide.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("앞으로의 행보가 기대된다.\n")
            checks: list[Callable[[str, str], list[str]]] = [lagom.style_violations, bragi.violations]
            found = lagom.changed_prose_violations(root, ["guide.md"], "", checks)
            self.assertTrue(any("KO-closing-formula" in item for item in found), found)
            self.assertTrue(all(item.startswith("guide.md: ") for item in found), found)
            # 근거 검사만 걸면 문체 흔적은 통과한다 — 두 축이 독립임을 확인
            self.assertEqual(lagom.changed_prose_violations(root, ["guide.md"], ""), [])


if __name__ == "__main__":
    unittest.main()
