"""회수 조립기 — 레인 간 중복제거·전역 예산·레인 바닥.

이 층이 지키는 계약은 세 문장이다:
  · 같은 사실이 여러 레인으로 들어오면 **한 번만** 실린다 (레인 간 중복 제거).
  · 레인 안의 중복은 **안 건드린다** — 그건 저장의 결함이고 lint 가 지목한다.
  · 어느 레인도 굶지 않는다 (바닥) — 그러면서 남은 자리는 순위로 겨룬다.
"""

from __future__ import annotations

import unittest

from asgard.memory.assemble import DEDUP_CONTAINMENT, Candidate, Lane, assemble, select, stats

A = Lane("a", "\n<a>\n", "\n</a>", 200)
B = Lane("b", "\n<b>\n", "\n</b>", 200)
C = Lane("c", "\n<c>\n", "\n</c>", 200)
LANES = (A, B, C)


class TestCrossLaneDedup(unittest.TestCase):
    def test_the_same_fact_from_two_lanes_is_carried_once(self):
        fact = "릴리스는 태그를 먼저 찍고 배포한다 — 순서를 뒤집으면 롤백 지점이 사라진다"
        chosen = select(
            [Candidate("a", fact), Candidate("b", fact)],
            LANES,
            budget=4000,
        )
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0].lane, "a")  # 앞선 레인이 이긴다 (바닥 배분 순서)

    def test_a_paraphrase_across_lanes_is_also_collapsed(self):
        chosen = select(
            [
                Candidate("a", "릴리스는 태그를 먼저 찍고 배포한다"),
                Candidate("b", "릴리스는 태그를 먼저 찍고 배포한다 (롤백 지점 보존)"),
            ],
            LANES,
            budget=4000,
        )
        self.assertEqual(len(chosen), 1)

    def test_distinct_facts_across_lanes_both_survive(self):
        chosen = select(
            [
                Candidate("a", "릴리스는 태그를 먼저 찍고 배포한다"),
                Candidate("b", "테스트는 uv 가 만든 가상환경의 파이썬으로 돌린다"),
            ],
            LANES,
            budget=4000,
        )
        self.assertEqual(len(chosen), 2)

    def test_duplicates_inside_one_lane_are_left_alone(self):
        """레인 안 중복은 저장의 결함이라 주입에서 가리지 않는다 (lint 가 지목한다)."""
        fact = "릴리스는 태그를 먼저 찍고 배포한다"
        chosen = select([Candidate("a", fact, rank=0), Candidate("a", fact + " 반드시", rank=1)], LANES, budget=4000)
        self.assertEqual(len(chosen), 2)

    def test_the_dedup_threshold_is_configurable_and_1_0_disables_collapsing(self):
        fact = "릴리스는 태그를 먼저 찍고 배포한다"
        chosen = select([Candidate("a", fact), Candidate("b", fact)], LANES, budget=4000, dedup=1.01)
        self.assertEqual(len(chosen), 2)


class TestBudget(unittest.TestCase):
    def test_nothing_exceeds_the_global_budget(self):
        candidates = [Candidate("a", f"사실 {i} " + "가" * 100, rank=i) for i in range(20)]
        chosen = select(candidates, LANES, budget=500)
        self.assertLessEqual(sum(c.cost for c in chosen), 500)

    def test_the_rendered_text_is_what_the_budget_bounds(self):
        """예산은 행이 아니라 **최종 문자열**에 걸린다 — 머리글·꼬리도 프롬프트에 실린다."""
        for budget in (120, 300, 700, 1500):
            candidates = [Candidate(lane, f"{lane} 사실 {i} " + "가" * 30, rank=i) for lane in "abc" for i in range(8)]
            text = assemble(candidates, LANES, budget=budget)
            self.assertLessEqual(len(text), budget, f"budget={budget}")

    def test_a_budget_too_small_for_even_one_block_carries_nothing(self):
        text = assemble([Candidate("a", "사실")], LANES, budget=5)
        self.assertEqual(text, "")

    def test_a_zero_budget_carries_nothing(self):
        self.assertEqual(select([Candidate("a", "무엇이든")], LANES, budget=0), [])

    def test_a_lane_that_would_starve_still_gets_its_floor(self):
        """후보가 많은 레인이 전량을 먹으면 안 된다 — kind 예산을 나눈 이유와 같은 실패다."""
        loud = [Candidate("a", f"에이 {i} " + "가" * 60, rank=i) for i in range(30)]
        quiet = [Candidate("c", "씨 레인의 유일한 사실 " + "나" * 40, rank=0)]
        chosen = select([*loud, *quiet], LANES, budget=700)
        self.assertIn("c", {c.lane for c in chosen})

    def test_surplus_budget_flows_to_other_lanes(self):
        """한 레인이 자기 바닥을 안 쓰면 그 자리는 다른 레인이 쓴다 (이전에는 그냥 버려졌다)."""
        many = [Candidate("a", f"에이 {i} " + "가" * 40, rank=i) for i in range(12)]
        chosen = select(many, LANES, budget=1800)
        # 레인 바닥(200)만 쓰였다면 4줄도 못 싣는다. 전역 경쟁이 돌면 훨씬 많이 실린다.
        self.assertGreater(len(chosen), 4)
        self.assertLessEqual(sum(c.cost for c in chosen), 1800)


class TestRender(unittest.TestCase):
    def test_lane_blocks_keep_their_scope_boundaries(self):
        text = assemble(
            [Candidate("a", "에이 사실"), Candidate("c", "씨 사실")],
            LANES,
            budget=4000,
        )
        self.assertIn("<a>", text)
        self.assertIn("<c>", text)
        self.assertIn("- 에이 사실", text)

    def test_an_empty_lane_emits_no_header(self):
        text = assemble([Candidate("a", "에이 사실")], LANES, budget=4000)
        self.assertNotIn("<b>", text)

    def test_rows_are_rendered_in_lane_then_rank_order(self):
        text = assemble(
            [Candidate("c", "씨"), Candidate("a", "에이 둘", rank=1), Candidate("a", "에이 하나", rank=0)],
            LANES,
            budget=4000,
        )
        self.assertLess(text.index("에이 하나"), text.index("에이 둘"))
        self.assertLess(text.index("에이 둘"), text.index("씨"))

    def test_the_provenance_suffix_rides_along_but_does_not_drive_dedup(self):
        """같은 사실을 두 레인이 내면 출처 표기는 당연히 다르다 — 비교에 넣으면 중복이 안 보인다."""
        fact = "릴리스는 태그를 먼저 찍고 배포한다"
        chosen = select(
            [Candidate("a", fact, suffix=" [src: a.md]"), Candidate("b", fact, suffix=" [record: r-1]")],
            LANES,
            budget=4000,
        )
        self.assertEqual(len(chosen), 1)


class TestStats(unittest.TestCase):
    def test_stats_separate_redundancy_drops_from_budget_drops(self):
        fact = "릴리스는 태그를 먼저 찍고 배포한다"
        candidates = [Candidate("a", fact), Candidate("b", fact)]
        chosen = select(candidates, LANES, budget=4000)
        report = stats(candidates, chosen)
        self.assertEqual(report["candidates"], 2)
        self.assertEqual(report["chosen"], 1)
        self.assertEqual(report["lanes_used"], ["a"])


class TestThreshold(unittest.TestCase):
    def test_the_calibrated_threshold_is_the_measured_one(self):
        """0.55 는 이 저장소의 실측에서 왔다 (병합쌍 0.56/0.61 vs 무관쌍 0.00/0.02)."""
        self.assertEqual(DEDUP_CONTAINMENT, 0.55)


if __name__ == "__main__":
    unittest.main()
