"""실패 카탈로그 정형화 — 코드가 정본, 문장은 렌더링 (failures.py).

계약: 게이트 실패는 `[gate:<code>]` 태그로 태어나고 소비자는 문장 파싱 없이 코드를 직독한다.
훅은 자기완결 단일 파일이라 failures 모듈을 임포트하지 못한다 — 패리티 테스트가 두 표를 봉인한다.
"""

from __future__ import annotations

import string
import unittest

from asgard import failures


class TestCatalogParity(unittest.TestCase):
    def test_hook_catalog_matches_canon(self):
        # 훅 사본 표가 정본과 어긋나면 코드는 남고 문장만 갈라진다 — dict 동일성으로 봉인
        from asgard.hooks import verifier_gate

        self.assertEqual(verifier_gate.GATE_MESSAGES, failures.GATE_MESSAGES)

    def test_gate_codes_are_kebab_case(self):
        for code in failures.KNOWN_CODES:
            self.assertEqual(code, failures.normalize_sig(code), f"카탈로그 코드가 슬러그 정본이 아님: {code}")


class TestTagRoundTrip(unittest.TestCase):
    def _params(self, template: str) -> dict:
        return {name: "x" for _, name, _, _ in string.Formatter().parse(template) if name}

    def test_every_gate_code_round_trips_through_classify(self):
        # 발화(gate_message) → 소비(_gate_sig)가 코드 무손실 — 문장 역추출 다리의 대체 증명
        from asgard.agent.heimdall.classify import _gate_sig

        for code, template in failures.GATE_MESSAGES.items():
            rendered = "Asgard verifier-gate (Canon 10 — 완료 증명): " + failures.gate_message(
                code, **self._params(template)
            )
            self.assertEqual(_gate_sig(rendered), code)

    def test_legacy_prose_fallback_still_maps(self):
        # 구버전 훅 사본(태그 없는 문장)의 사유도 니들 폴백으로 시그니처가 잡힌다
        from asgard.agent.heimdall.classify import _gate_sig

        self.assertEqual(_gate_sig("stale PASS — 물리 대조 불일치"), "stale-pass")
        self.assertEqual(_gate_sig("write 과업인데 Verifier 판정(PASS/ESCALATE) 레코드가 없습니다."), "no-verdict")
        self.assertEqual(_gate_sig("듣도 보도 못한 사유"), "other")

    def test_parse_gate_code_ignores_plain_text(self):
        self.assertIsNone(failures.parse_gate_code("게이트 아님"))
        self.assertEqual(failures.parse_gate_code("전치사 [gate:no-verdict] 후치사"), "no-verdict")


class TestRepairMapping(unittest.TestCase):
    def test_repair_transitions(self):
        self.assertEqual(failures.repair_for("no-criteria")[0], "THINKER_REPLAN")
        self.assertEqual(failures.repair_for("baseline-red")[0], "WORKER_RETRY")
        self.assertEqual(failures.repair_for("tickets-incomplete")[0], "WORKER_RETRY")
        self.assertEqual(failures.repair_for("escalate-nudge")[0], "THINKER_REPLAN")
        self.assertEqual(failures.repair_for("stale-pass")[0], "VERIFIER")
        self.assertEqual(failures.repair_for("other")[0], "VERIFIER")

    def test_classify_delegates_to_catalog(self):
        from asgard.agent.heimdall.classify import _gate_repair

        for code in ("no-criteria", "baseline-red", "stale-pass", "escalate-nudge"):
            self.assertEqual(_gate_repair(code), failures.repair_for(code))


class TestNormalizeSig(unittest.TestCase):
    def test_underscore_and_case_fold(self):
        self.assertEqual(failures.normalize_sig("no_verdict"), "no-verdict")
        self.assertEqual(failures.normalize_sig("  Missing Null Check! "), "missing-null-check")

    def test_korean_preserved_distinct(self):
        # 비ASCII 를 지우면 서로 다른 원인이 한 슬러그로 뭉개진다 — 보존 확인
        self.assertEqual(failures.normalize_sig("테스트 실패"), "테스트-실패")
        self.assertNotEqual(failures.normalize_sig("테스트 실패"), failures.normalize_sig("빌드 실패"))

    def test_empty_and_cap(self):
        self.assertEqual(failures.normalize_sig(""), "unspecified")
        self.assertEqual(failures.normalize_sig("!!!"), "unspecified")
        self.assertLessEqual(len(failures.normalize_sig("a" * 200)), 48)


class TestBaselineFailEvidence(unittest.TestCase):
    def test_pytest_summary_lines_win(self):
        from asgard.hooks.quest_log import fail_lines

        out = (
            b"collected 3 items\n"
            b"E       AssertionError: assert 1 == 2\n"
            b"FAILED tests/test_x.py::test_y - AssertionError: assert 1 == 2\n"
            b"1 failed, 2 passed in 0.10s\n"
        )
        got = fail_lines(out, b"")
        self.assertIn("FAILED tests/test_x.py::test_y - AssertionError: assert 1 == 2", got)
        self.assertTrue(all("passed in" not in ln for ln in got))

    def test_tail_fallback_and_bounds(self):
        from asgard.hooks.quest_log import fail_lines

        out = ("\n".join(f"line{i}" * 60 for i in range(10))).encode()
        got = fail_lines(out, None)
        self.assertLessEqual(len(got), 5)
        self.assertTrue(all(len(ln) <= 200 for ln in got))
        self.assertEqual(fail_lines(b"", b""), [])
