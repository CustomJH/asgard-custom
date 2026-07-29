"""리랭크 QPP 게이트 — 분산을 이분 판정이 아니라 **확신도**로 읽는다.

배경 (26-07-29). 게이트는 hard 로 냈다: 분산이 문턱 미만이면 리랭크 표를 아예 안 던진다.
held-out 계측이 그 대가를 보여 줬다 — V2(새 도메인) 퇴행 9건→2건을 얻고, M(건초더미 9배)에서
NDCG −0.9pp·MRR −1.4pp 를 치렀다. M 에서 리랭크는 순증이었으므로 낮은 분산 질의에도
**순위를 다듬는 몫**이 있었는데 기권이 그걸 통째로 버린 것이다.

그래서 soft 를 시도했다 (`w = min(1, 분산/문턱)`) — 그리고 **재 보니 안 됐다**: V2 에서 해를
끼치던 질의의 분산이 문턱 바로 아래에 몰려 있어 가중이 거의 안 깎이고, 결과가 게이트 없음과
같아진다 (V2 R@5 soft 0.760 / 4:8  vs  hard 0.780 / 0:2). 기본이 hard 인 것은 그 계측이다.

이 파일이 지키는 계약:
  · 문턱 이상 → 가중 1.0 (어느 모드에서도)
  · 문턱 미만 → hard 는 0(기본), soft 는 비례 감쇠
  · 문턱 0 (게이트 없음) → 항상 1.0, 즉 게이트 도입 전과 **바이트 동일**
  · 두 모드 다 제품 스위치로 켜고 끌 수 있다 (보고서 재현성)
"""

from __future__ import annotations

import os
import unittest

from asgard.memory import recall


class GateCase(unittest.TestCase):
    def setUp(self) -> None:
        for key in (recall.RERANK_GATE_ENV, recall.RERANK_DISPERSION_ENV):
            self._pop(key)

    def _pop(self, key: str) -> None:
        previous = os.environ.pop(key, None)
        if previous is not None:
            self.addCleanup(os.environ.__setitem__, key, previous)
        self.addCleanup(os.environ.pop, key, None)

    def set_env(self, key: str, value: str) -> None:
        os.environ[key] = value
        self.addCleanup(os.environ.pop, key, None)


class TestGateWeight(GateCase):
    FLOOR = 0.1503  # 실제 보정값 — 상수가 바뀌면 이 검사도 같이 움직여야 한다

    def test_above_the_floor_the_rerank_keeps_a_full_vote(self):
        for dispersion in (self.FLOOR, self.FLOOR + 0.01, 1.0):
            with self.subTest(dispersion=dispersion):
                self.assertEqual(recall._gate_weight(dispersion, self.FLOOR), 1.0)

    def test_soft_attenuates_below_the_floor_instead_of_abstaining(self):
        self.set_env(recall.RERANK_GATE_ENV, "soft")
        half = recall._gate_weight(self.FLOOR / 2, self.FLOOR)
        self.assertAlmostEqual(half, 0.5, places=6)
        self.assertGreater(half, 0.0)  # 기권이 아니다 — 발언권이 줄었을 뿐이다

    def test_soft_is_monotone_in_the_signal(self):
        self.set_env(recall.RERANK_GATE_ENV, "soft")
        weights = [recall._gate_weight(self.FLOOR * f, self.FLOOR) for f in (0.0, 0.25, 0.5, 0.75, 1.0)]
        self.assertEqual(weights, sorted(weights))
        self.assertEqual(weights[0], 0.0)
        self.assertEqual(weights[-1], 1.0)

    def test_hard_abstains_below_the_floor(self):
        self.set_env(recall.RERANK_GATE_ENV, "hard")
        self.assertEqual(recall._gate_weight(self.FLOOR / 2, self.FLOOR), 0.0)
        self.assertEqual(recall._gate_weight(self.FLOOR, self.FLOOR), 1.0)

    def test_a_zero_floor_is_byte_identical_to_no_gate(self):
        """게이트 도입 전 거동 — 어느 모드든, 어떤 분산이든 리랭크는 대등하게 선다."""
        for mode in ("soft", "hard"):
            for dispersion in (0.0, 0.01, 0.5):
                with self.subTest(mode=mode, dispersion=dispersion):
                    os.environ[recall.RERANK_GATE_ENV] = mode
                    self.assertEqual(recall._gate_weight(dispersion, 0.0), 1.0)
        os.environ.pop(recall.RERANK_GATE_ENV, None)


class TestGateModeSwitch(GateCase):
    def test_the_default_is_hard(self):
        """기본이 hard 인 것은 계측 결과다 — soft 는 V2 에서 보호를 못 지켰다 (4:8 vs 0:2)."""
        self.assertEqual(recall._gate_mode(), "hard")

    def test_the_mode_is_switchable_without_monkeypatching(self):
        """보고서의 hard 수치를 재현하려면 제품 스위치로 돌아갈 수 있어야 한다."""
        for value, expected in (("hard", "hard"), ("soft", "soft"), ("SOFT", "soft"), ("nonsense", "hard")):
            with self.subTest(value=value):
                os.environ[recall.RERANK_GATE_ENV] = value
                self.assertEqual(recall._gate_mode(), expected)
        os.environ.pop(recall.RERANK_GATE_ENV, None)


class TestDispersion(GateCase):
    def test_identical_scores_have_no_dispersion(self):
        # 정확히 0 을 요구하지 않는다: 부동소수 제곱합이 1e-16 급 잔차를 남긴다. 문턱이
        # 0.1503 이라 그 잔차는 판정에 닿지 않으므로 코드로 걷어낼 값이 아니다.
        self.assertAlmostEqual(recall._dispersion([0.4, 0.4, 0.4]), 0.0, places=9)

    def test_spread_scores_have_dispersion(self):
        self.assertGreater(recall._dispersion([0.9, 0.4, 0.1]), 0.0)

    def test_fewer_than_two_scores_is_not_a_ranking(self):
        self.assertEqual(recall._dispersion([0.7]), 0.0)
        self.assertEqual(recall._dispersion([]), 0.0)

    def test_a_non_positive_mean_is_treated_as_undifferentiated(self):
        """코사인이 전부 0 근처면 변동계수가 정의되지 않는다 — 갈리지 않는다고 본다."""
        self.assertEqual(recall._dispersion([0.0, 0.0]), 0.0)
        self.assertEqual(recall._dispersion([-0.2, 0.2]), 0.0)

    def test_dispersion_is_scale_free(self):
        """변동계수를 쓰는 이유 — 점수를 통째로 키워도 '갈리는 정도'는 그대로다."""
        base = [0.6, 0.3, 0.1]
        self.assertAlmostEqual(recall._dispersion(base), recall._dispersion([x * 3 for x in base]), places=9)


class TestFloorOverride(GateCase):
    def test_the_floor_is_overridable_for_ablation(self):
        self.set_env(recall.RERANK_DISPERSION_ENV, "0")
        self.assertEqual(recall._dispersion_floor(), 0.0)

    def test_a_malformed_override_falls_back_to_the_calibrated_value(self):
        self.set_env(recall.RERANK_DISPERSION_ENV, "매우높게")
        self.assertEqual(recall._dispersion_floor(), recall.RERANK_DISPERSION_FLOOR)

    def test_the_calibrated_floor_is_the_measured_one(self):
        """S 500문항 보정 산출 — 바꾸려면 calibrate_dispersion.py 를 다시 돌려야 한다."""
        self.assertEqual(recall.RERANK_DISPERSION_FLOOR, 0.1503)


if __name__ == "__main__":
    unittest.main()
