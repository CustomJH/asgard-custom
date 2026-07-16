"""레포 내장 벤치 fixture 회귀 — 정책 주장(숏컷 벤치 수치)이 fixture 와 어긋나면 실패.

숏컷 36런(benchmarks/shortcut-recall)은 라이브 LLM 실측의 원본 기록이다. 이 테스트는
재실행이 아니라 **기록 재집계**다: REPORT.md 의 헤드라인 수치가 jsonl 에서 결정론으로
재도출되는지 고정한다 (fixture 교체·집계 드리프트 방지)."""

import json
import os
import re
import statistics
import unittest

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "shortcut-recall", "results-36runs.jsonl")

# 교정 판정 — 기록 시점 \b 는 한글 뒤 숫자(`1747초`)에서 경계를 못 잡는다 (REPORT.md 참조)
JUDGES = {
    "retry-ceil": r"(?<!\d)37(?!\d)",
    "gateway-port": r"(?<!\d)8742(?!\d)",
    "cache-ttl": r"(?<!\d)1747(?!\d)",
    "sig-header": r"X-Mrd-Sig-V2",
    "flush-at": r"(?<!\d)233(?!\d)",
    "schema-rev": r"(?<!\d)41(?!\d)",
}


class TestShortcutRecallFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE, encoding="utf-8") as f:
            cls.rows = [json.loads(line) for line in f if line.strip()]

    def arm(self, name):
        return [r for r in self.rows if r["arm"] == name]

    def test_manifest_shape(self):
        self.assertEqual(len(self.rows), 36)  # 6과업 × 2arm × 3반복
        self.assertEqual(len(self.arm("on")), 18)
        self.assertEqual(len(self.arm("off")), 18)
        self.assertEqual({r["fid"] for r in self.rows}, set(JUDGES))

    def test_corrected_success_is_perfect_on_both_arms(self):
        for arm in ("on", "off"):
            ok = sum(bool(re.search(JUDGES[r["fid"]], r["result_head"])) for r in self.arm(arm))
            self.assertEqual(ok, 18, f"{arm} arm 교정 판정 회귀")

    def test_headline_deltas_hold(self):
        def med(arm, key):
            return statistics.median(r[key] for r in self.arm(arm))

        token_delta = med("on", "tokens") / med("off", "tokens") - 1
        wall_delta = med("on", "wall_s") / med("off", "wall_s") - 1
        self.assertLess(token_delta, -0.60)  # REPORT: −67%
        self.assertLess(wall_delta, -0.60)  # REPORT: −69%

    def test_injection_arm_preserved_evidence(self):
        cited = sum("src/meridian" in r["result_head"] for r in self.arm("on"))
        self.assertEqual(cited, 18)  # 메모리는 위치만 담았다 — 값은 파일을 열어 얻었음의 흔적

    def test_runs_are_clean(self):
        self.assertFalse(any(r["timeout"] or r["misroute"] for r in self.rows))
        self.assertTrue(all(r["recall_used"] == 0 for r in self.arm("off")))  # off arm 무주입 검증


if __name__ == "__main__":
    unittest.main(verbosity=2)
