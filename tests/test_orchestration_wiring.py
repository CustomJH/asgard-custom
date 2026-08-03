"""사용자가 고른 정책이 **실행 경로에 실제로 닿는가**.

이 파일이 있는 이유는 이번 작업에서 실제로 벌어진 일 때문이다. 정책 층(`orchestration.policy`)
과 표면(`asgard orchestrate`, 스튜디오 패널)이 다 서고 자기 테스트도 전부 녹색이었는데,
`bifrost` 는 여전히 `strategy.choose` 를 직접 부르고 있었다. 즉 설정은 저장되고 화면은 바뀌는데
**도는 모양은 그대로**였다. 아무 일도 안 하는 설정은 없는 설정보다 나쁘다 — 사람은 자기가
무언가 바꿨다고 믿기 때문이다.

각 층의 단위 테스트로는 이 결함을 절대 못 잡는다. 층은 셋 다 옳았고 **사이가 비어 있었다**.
그래서 여기서는 층을 안 보고 이음매만 본다.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.agent.heimdall import bifrost  # noqa: E402

# 병렬을 명시한 깊은 과업 + 배정 단위 셋. 정책이 없으면 이 신호는 언제나 graph 로 간다 —
# 그래서 정책이 이 값을 바꾸면 그건 정책이 실제로 읽혔다는 뜻이다.
_SIGNALS = {
    "write_expected": True,
    "task_class": "deep",
    "parallel_requested": True,
    "unit_count": 3,
    "specialists": [],
    "planned": True,
}
_CLS = {"write_expected": True, "task_class": "deep", "parallel_requested": True}


class _Policy:
    """정책 층 대역 — 고른 값과 닿는 엔진 목록을 함께 고정한다.

    엔진까지 여기서 붙드는 이유가 있다. `_by_policy` 는 `engines.cached(root)` 로 **실제
    저장소의 캐시**를 읽는데, 그 파일은 사람이 `asgard orchestrate --probe` 를 한 번 돌리면
    차고 안 돌리면 빈다. 붙들지 않으면 같은 시험이 개발자 기계에서는 통과하고 CI 에서는
    실패한다 — 판정이 저장소 상태를 따라가면 그건 판정기가 아니다.
    """

    def __init__(self, value: str, engines: list | None = None) -> None:
        self.value = value
        self.engines = list(engines or [])

    def __enter__(self):
        from asgard import engines as engines_mod
        from asgard.orchestration import policy

        self._before = policy.current
        self._before_cached = engines_mod.cached
        policy.current = lambda root: (self.value, "project")
        engines_mod.cached = lambda root, *a, **k: list(self.engines)
        return self

    def __exit__(self, *exc: object) -> None:
        from asgard import engines as engines_mod
        from asgard.orchestration import policy

        policy.current = self._before
        engines_mod.cached = self._before_cached


class TestPolicyReachesTheLoop(unittest.TestCase):
    def test_off_actually_stops_orchestration(self):
        """`off` 를 골랐으면 신호가 무엇을 가리켰든 direct 로 돌아야 한다.

        이 단언 하나가 이음매의 전부다. 신호만 보면 graph 인 입력이라, 결과가 graph 면
        정책을 아무도 안 읽은 것이다.
        """
        with _Policy("off"):
            found = bifrost._by_policy(".", dict(_SIGNALS))
        self.assertIsNotNone(found, "정책 층이 안 읽혔다 — 이음매가 끊겼다")
        self.assertEqual(found["shape"], "direct")

    def test_solo_collapses_a_parallel_signal(self):
        with _Policy("solo"):
            found = bifrost._by_policy(".", dict(_SIGNALS))
        self.assertEqual(found["shape"], "single")

    def test_auto_leaves_the_signal_judgement_alone(self):
        """기본값은 예전 동작을 그대로 보존해야 한다 — 안 그러면 이 배선이 회귀다."""
        from asgard.orchestration.strategy import choose

        with _Policy("auto"):
            found = bifrost._by_policy(".", dict(_SIGNALS))
        self.assertEqual(found["shape"], choose(**_SIGNALS)["shape"])

    def test_a_downgrade_is_written_where_audits_read_it(self):
        """정책이 원한 대로 못 했으면 그 사실이 `shape_why` 로 흘러야 한다.

        조용히 내려앉으면 "왜 squad 로 안 돌았지" 의 답이 어디에도 안 남는다.
        """
        with _Policy("squad"):
            found = bifrost._by_policy(".", dict(_SIGNALS))
        self.assertTrue(found["degraded"].strip(), "내려앉은 사실이 안 적혔다")
        self.assertIn("squad", bifrost._shape_why(found))

    def test_a_placement_failure_is_not_filed_as_a_shape_disagreement(self):
        """축이 둘인데 칸이 하나면 둘 다 못 읽는다.

        `이견` 은 신호와 계획이 다른 답을 냈다는 뜻이다. "닿는 엔진이 없다" 는 배치 사실이라
        거기 들어가면 Run 의 한 줄이 형상 판정의 근거를 잘못 증언한다 — 실제로 이 배선의 첫
        판본이 그렇게 적었고 `test_orchestration_trinity` 가 잡았다.
        """
        # 신호와 계획이 **일치하는** 입력이어야 한다: 병렬을 안 시켰으니 신호도 single 이고
        # 계획이 낸 단위도 0 이라 엇갈릴 것이 없다. (`unit_count=0` 만 바꾸면 신호는 여전히
        # graph 를 가리켜서 진짜 이견이 생기고, 그러면 이 시험이 무엇을 재는지 흐려진다.)
        signals = dict(_SIGNALS, unit_count=0, parallel_requested=False)
        with _Policy("auto"):
            found = bifrost._by_policy(".", signals)
        self.assertEqual(found["disagreement"], "", "배치 실패가 형상 이견 칸으로 샜다")
        # 배치를 못 한 사실 자체는 사라지지 않는다 — 다른 칸에 남는다.
        self.assertTrue(found["degraded"].strip())


class TestTheSeamIsFailOpen(unittest.TestCase):
    """정책을 못 읽어도 퀘스트는 돈다 — 배차 장부는 Trinity 를 막지 않는다(bifrost 계약)."""

    def test_a_broken_policy_layer_falls_back_to_signals(self):
        from asgard.orchestration import policy

        before = policy.current
        policy.current = lambda root: (_ for _ in ()).throw(RuntimeError("정책을 못 읽는다"))
        try:
            self.assertIsNone(bifrost._by_policy(".", dict(_SIGNALS)))
        finally:
            policy.current = before

    def test_choose_shape_still_answers_when_policy_is_dead(self):
        """`_by_policy` 가 None 이어도 형상은 나온다 — 예전 길이 그대로 살아 있어야 한다."""
        before = bifrost._by_policy
        bifrost._by_policy = lambda root, signals: None
        try:
            ledger = bifrost._NullLedger()
            found = ledger.choose_shape(_CLS, unit_count=3, specialists=[], planned=True)
        finally:
            bifrost._by_policy = before
        self.assertEqual(found["shape"], "graph")
        self.assertEqual(ledger.placements, ())


class _Engine:
    """닿는 엔진 하나 — `engines.Engine` 중 정책이 실제로 읽는 칸만 든다."""

    def __init__(self, name: str, model: str = "") -> None:
        self.name = name
        self.display = name
        self.configured = True
        self.reachable = True
        self.models = (model,) if model else ()
        self.model = model
        self.detail = ""
        self.checked = 0.0


class TestAutoPlacementReachesTheLedger(unittest.TestCase):
    """엔진이 여럿 준비돼 있으면 역할이 실제로 갈려서 장부까지 와야 한다.

    사용자가 이 기능에 기대하는 것이 정확히 이것이다 — "여러 모델이 준비돼 있으면 알아서 골라
    쓴다". 정책 층 안에서만 갈리고 장부에 안 오면 실행은 여전히 한 엔진에서 돈다.
    """

    def test_verifier_lands_on_a_different_engine_than_worker(self):
        live = [_Engine("claude-native"), _Engine("ollama", "gemma4:12b-mlx")]
        with _Policy("auto", live):
            ledger = bifrost._NullLedger()
            ledger.choose_shape(_CLS, unit_count=3, specialists=[], planned=True)
        seats = {p.role: p.engine for p in ledger.placements}
        self.assertEqual(len(seats), 3, "세 역할이 다 안 앉았다")
        self.assertNotEqual(
            seats["verifier"], seats["worker"], "같은 엔진이 자기 산출물을 검사하면 auto 가 주는 값이 없다"
        )

    def test_one_engine_seats_every_role_in_the_same_place(self):
        with _Policy("auto", [_Engine("ollama", "gemma4:12b-mlx")]):
            ledger = bifrost._NullLedger()
            ledger.choose_shape(_CLS, unit_count=3, specialists=[], planned=True)
        seats = {p.engine for p in ledger.placements}
        self.assertEqual(seats, {"ollama"})

    def test_every_seat_says_why_it_was_chosen(self):
        """감사할 수 없는 자동 배치는 이 계층이 없애려던 바로 그것이다(`strategy` 독스트링)."""
        live = [_Engine("claude-native"), _Engine("ollama"), _Engine("nvidia")]
        with _Policy("auto", live):
            ledger = bifrost._NullLedger()
            ledger.choose_shape(_CLS, unit_count=3, specialists=[], planned=True)
        for seat in ledger.placements:
            self.assertTrue(seat.why.strip(), f"{seat.role} 배치에 이유가 없다")


class TestBothEntrancesUseTheSamePolicy(unittest.TestCase):
    """장부가 선 경로와 안 선 경로가 같은 답을 내야 한다.

    한쪽만 배선하면 같은 저장소가 어느 길로 들어왔느냐에 따라 다른 모양으로 돌고, 사용자에게는
    "설정이 가끔 듣는다" 로 보인다 — 그건 안 듣는 것보다 진단하기 어렵다.
    """

    def test_the_null_ledger_path_honours_off(self):
        with _Policy("off"):
            ledger = bifrost._NullLedger()
            found = ledger.choose_shape(_CLS, unit_count=3, specialists=[], planned=True)
        self.assertEqual(found["shape"], "direct")
        self.assertEqual(ledger.shape, "direct")


if __name__ == "__main__":
    unittest.main()
