#!/usr/bin/env python3
"""Charter (프로젝트 북극성) 단위 테스트 — load_charter 정규화 + note() 역할별 주입.

핵심 계약 검증:
  · 미설정/파손 = 빈 문자열 (프롬프트 무변화, 토큰 회귀 없음)
  · 문자열 축약형 = through_line 으로 승격
  · verifier 주입은 "criteria 대체 아님" 문구를 반드시 포함 (evidence-first 보존)

실행: uv run pytest tests/test_charter.py
"""

import json
import os
import tempfile
import unittest

from asgard.charter import load_charter, note


def _write_project(root: str, charter) -> None:
    d = os.path.join(root, ".asgard")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "asgard-setting-project.json"), "w", encoding="utf-8") as f:
        json.dump({"charter": charter} if charter is not None else {}, f)


class TestLoadCharter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_absent_is_none(self):
        _write_project(self.root, None)
        self.assertIsNone(load_charter(self.root))

    def test_missing_file_is_none(self):
        self.assertIsNone(load_charter(self.root))  # .asgard 없음 — fail-open

    def test_string_shorthand_promotes_to_through_line(self):
        _write_project(self.root, "속도보다 정합성")
        ch = load_charter(self.root)
        self.assertEqual(ch, {"through_line": "속도보다 정합성", "coherence": []})

    def test_full_shape_normalized(self):
        _write_project(self.root, {"through_line": " tl ", "coherence": ["a", "  ", "b"]})
        ch = load_charter(self.root)
        self.assertEqual(ch["through_line"], "tl")
        self.assertEqual(ch["coherence"], ["a", "b"])  # 공백 항목 제거

    def test_empty_dict_is_none(self):
        _write_project(self.root, {"through_line": "", "coherence": []})
        self.assertIsNone(load_charter(self.root))

    def test_broken_type_is_none(self):
        _write_project(self.root, 42)
        self.assertIsNone(load_charter(self.root))


class TestNote(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_charter_all_sections_empty(self):
        for sec in ("identity", "thinker", "verifier"):
            self.assertEqual(note(self.root, sec), "")

    def test_identity_has_through_line_only(self):
        _write_project(self.root, {"through_line": "TL", "coherence": ["C1"]})
        out = note(self.root, "identity")
        self.assertIn("TL", out)
        self.assertNotIn("C1", out)  # identity 는 coherence 미주입 (관통 원칙만)

    def test_thinker_folds_coherence_into_criteria(self):
        _write_project(self.root, {"through_line": "TL", "coherence": ["C1"]})
        out = note(self.root, "thinker")
        self.assertIn("TL", out)
        self.assertIn("C1", out)
        self.assertIn("criteria", out)  # 협업② — 검증명령 환원 지시

    def test_verifier_is_lens_not_gate(self):
        _write_project(self.root, {"through_line": "TL", "coherence": ["C1"]})
        out = note(self.root, "verifier")
        self.assertIn("C1", out)
        # 판단③ evidence-first 보존 — charter 가 criteria 를 대체하지 않는다는 명시가 반드시 있어야
        self.assertIn("criteria 를 대체하지 않", out)

    def test_unknown_section_empty(self):
        _write_project(self.root, {"through_line": "TL"})
        self.assertEqual(note(self.root, "bogus"), "")


if __name__ == "__main__":
    unittest.main()
