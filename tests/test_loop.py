"""loop — 컨트롤러의 앵커. 순위가 아니라 **약속**을 고정한다.

실행: uv run pytest tests/test_loop.py

이 테스트가 지키는 것은 점수 공식이 아니다(공식은 튜닝 대상이다). 지키는 것은 컨트롤러가
거짓말을 안 한다는 것이다:

  ① 고른 걸음을 적용하면 그 지표가 **실제로** 움직인다 — 특히 파일 단위 지표에서.
  ② 리뷰 비용이 큰 걸음이 작은 걸음을 못 이긴다 (분모가 살아 있다).
  ③ 목표가 없으면 아무것도 안 고른다 — 숫자를 지어내지 않는다.
  ④ 후보를 못 낸 지표를 조용히 빼지 않는다.
  ⑤ 센서가 안 보는 파일에 일을 배정하지 않는다.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from asgard import health, loop


def _write(root: str, rel: str, body: str) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def _long_fn(name: str, lines: int, indent: int = 0) -> str:
    """`lines` 행짜리 함수 하나. 본문은 문장만 — 주석은 코드 행에 안 세어진다."""
    pad = " " * indent
    body = "\n".join(f"{pad}    x_{i} = {i}" for i in range(lines - 1))
    return f"{pad}def {name}():\n{body}\n"


def _deep_fn(name: str, depth: int) -> str:
    """중첩 `depth` 짜리 함수 하나."""
    out = [f"def {name}(rows):"]
    for level in range(depth):
        out.append(" " * (4 * (level + 1)) + f"for v{level} in rows:")
    out.append(" " * (4 * (depth + 1)) + "pass")
    return "\n".join(out) + "\n"


def _history(root: str, rows: list[dict]) -> None:
    path = health.history_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)


class TestSetPoint(_Base):
    def test_no_history_means_no_target(self) -> None:
        """기록이 없으면 목표가 없고, 목표가 없으면 아무것도 안 고른다 (약속 ③)."""
        _write(self.root, "a.py", _long_fn("f", 90))
        signal = loop.next_signal(self.root)
        self.assertEqual(signal.targets, ())
        self.assertEqual(signal.picked, ())
        self.assertTrue(signal.undetermined, "목표가 없다는 사실 자체는 실려야 한다")
        self.assertIn("--snapshot", signal.undetermined[0][1])

    def test_target_defaults_to_best_ever_recorded(self) -> None:
        """기본 목표 = 이력의 **최선값**. 마지막 값이 아니다 — 그러면 나빠진 채로 굳는다."""
        _history(self.root, [{"commit": "a", "big_units": 4}, {"commit": "b", "big_units": 9}])
        self.assertEqual(loop.best_recorded(self.root)["big_units"], 4)

    def test_configured_target_wins_over_history(self) -> None:
        _history(self.root, [{"commit": "a", "big_units": 4}])
        _write(
            self.root,
            ".asgard/asgard-setting-project.json",
            json.dumps({"health": {"targets": {"big_units": 1}}}),
        )
        # 오차가 있어야 목표가 실린다 — 설정 1에 위반 2 개를 둔다
        _write(self.root, "a.py", _long_fn("f", 90) + "\n\n" + _long_fn("g", 95))
        picked = {t.metric: t for t in loop.targets(self.root, health.scan(self.root))}
        self.assertEqual(picked["big_units"].target, 1)
        self.assertEqual(picked["big_units"].source, "설정")
        self.assertEqual(picked["big_units"].error, 1.0)

    def test_metric_at_or_under_target_is_not_carried(self) -> None:
        """오차가 없으면 목표를 안 싣는다 — 할 일이 없는 지표가 화면을 채우면 순위가 죽는다."""
        _write(self.root, "a.py", "def f():\n    return 1\n")
        _history(self.root, [{"commit": "a", "big_units": 0, "deep_units": 0}])
        self.assertEqual(loop.targets(self.root, health.scan(self.root)), ())


class TestPromise(_Base):
    def test_file_counted_metric_costs_every_violator_in_the_file(self) -> None:
        """`deep_units`는 파일을 센다 — 한 파일에 깊은 함수가 둘이면 **둘 다** 읽을 값에 든다.

        이걸 어기면 컨트롤러가 "22행이면 지표가 준다"고 말하고 실제로는 안 준다 (약속 ①).
        """
        _write(self.root, "two.py", _deep_fn("a", 5) + "\n\n" + _deep_fn("b", 5))
        _history(self.root, [{"commit": "a", "deep_units": 0}])
        signal = loop.next_signal(self.root, limit=5)
        deep = [c for c in signal.picked + signal.runners_up if c.metric == "deep_units"]
        self.assertEqual(len(deep), 1, "파일 단위 지표는 후보도 파일 단위로 하나여야 한다")
        alone = health._read(self.root, "two.py")
        assert alone is not None
        from asgard import craft_rules

        units = craft_rules.units(alone) or {}
        both = sum(u.lines for u in units.values() if u.depth > health.DEPTH_WARN)
        self.assertEqual(deep[0].read, both, "읽을 값이 그 파일의 위반 단위 전부여야 한다")
        self.assertIn("전부 내려야", deep[0].why)

    def test_unit_counted_metric_costs_only_that_unit(self) -> None:
        """`big_units`는 단위를 센다 — 하나 내리면 하나 준다. 값은 그 함수만이다."""
        _write(self.root, "big.py", _long_fn("f", 90) + "\n\n" + _long_fn("g", 95))
        _history(self.root, [{"commit": "a", "big_units": 0}])
        signal = loop.next_signal(self.root, limit=5)
        big = [c for c in signal.picked + signal.runners_up if c.metric == "big_units"]
        self.assertEqual(len(big), 2, "단위 단위 지표는 위반 단위마다 후보를 낸다")
        self.assertEqual(sorted(c.read for c in big), [90, 95], "읽을 값은 그 함수의 행 수 그대로다")

    def test_applying_the_picked_step_actually_moves_the_metric(self) -> None:
        """고른 걸음을 적용하면 지표가 **진짜로** 움직인다 — 컨트롤러 약속의 종단 검증."""
        _write(self.root, "big.py", _long_fn("f", 90))
        _history(self.root, [{"commit": "a", "big_units": 0}])
        before = health.scan(self.root).big_units
        picked = loop.next_signal(self.root).picked[0]
        self.assertEqual(picked.path, "big.py")
        # 액추에이터가 할 일: 고른 단위를 예산 아래로 내린다
        _write(self.root, "big.py", _long_fn("f", 30) + "\n\n" + _long_fn("f_tail", 40))
        after = health.scan(self.root).big_units
        self.assertEqual(before - after, 1, "약속한 만큼 정확히 움직여야 한다")


class TestRanking(_Base):
    def test_cheaper_review_wins_when_value_is_equal(self) -> None:
        """같은 지표·같은 변경빈도면 **읽을 줄이 적은 쪽**이 이긴다 (약속 ②).

        이 순서가 뒤집히면 컨트롤러가 리뷰 불가능한 걸음을 루프에 넣는다 — blind 루프가 4만 줄
        PR을 만드는 바로 그 경로다.
        """
        _write(self.root, "small.py", _long_fn("s", 75))
        _write(self.root, "huge.py", _long_fn("h", 400))
        _history(self.root, [{"commit": "a", "big_units": 0}])
        signal = loop.next_signal(self.root, limit=2)
        self.assertEqual(signal.picked[0].path, "small.py")
        self.assertLess(signal.picked[0].read, signal.picked[1].read)

    def test_ranking_is_deterministic(self) -> None:
        """같은 트리는 같은 걸음을 낸다 — 루프가 회전마다 다른 답을 내면 추세를 못 읽는다."""
        _write(self.root, "a.py", _long_fn("f", 80))
        _write(self.root, "b.py", _long_fn("g", 80))
        _history(self.root, [{"commit": "a", "big_units": 0}])
        first = loop.next_signal(self.root, limit=3)
        second = loop.next_signal(self.root, limit=3)
        self.assertEqual([c.where for c in first.picked], [c.where for c in second.picked])


class TestHonesty(_Base):
    def test_metric_without_candidates_is_carried_not_dropped(self) -> None:
        """후보를 못 내는 지표는 사유와 함께 실린다 — 조용히 빠지면 "깨끗하다"로 읽힌다 (약속 ④)."""
        # health의 import 그래프는 패키지 뿌리를 기준으로 모듈을 푼다 — 평평한 파일 둘로는
        # 순환이 안 잡힌다(실측). 순환을 만들려면 패키지 안이어야 한다.
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", "from pkg import b\n")
        _write(self.root, "pkg/b.py", "from pkg import a\n")
        _history(self.root, [{"commit": "a", "cycles": 0}])
        signal = loop.next_signal(self.root, limit=1)
        reasons = dict(signal.undetermined)
        self.assertIn("cycles", reasons)
        self.assertIn("순환 경로", reasons["cycles"])

    def test_vendored_paths_get_no_work(self) -> None:
        """센서가 안 세는 파일에 컨트롤러가 일을 배정하면 안 된다 (약속 ⑤)."""
        _write(self.root, "node_modules/pkg/big.py", _long_fn("f", 200))
        _write(self.root, "mine.py", _long_fn("g", 90))
        _history(self.root, [{"commit": "a", "big_units": 0}])
        signal = loop.next_signal(self.root, limit=5)
        paths = {c.path for c in signal.picked + signal.runners_up}
        self.assertNotIn("node_modules/pkg/big.py", paths)
        self.assertIn("mine.py", paths)

    def test_tests_are_not_work(self) -> None:
        """테스트 파일은 지표에서 빠지므로 후보에서도 빠져야 한다 — 두 목록이 갈리면 안 된다."""
        _write(self.root, "tests/test_x.py", _long_fn("f", 200))
        _write(self.root, "mine.py", _long_fn("g", 90))
        _history(self.root, [{"commit": "a", "big_units": 0}])
        signal = loop.next_signal(self.root, limit=5)
        self.assertNotIn("tests/test_x.py", {c.path for c in signal.picked + signal.runners_up})


class TestMandate(_Base):
    def test_signal_round_trips_and_scopes_to_touched_paths(self) -> None:
        """튜터가 읽는 면 — 손댄 경로의 근거만 돌려준다 (안 건드린 자리의 지시는 오귀속이다)."""
        _write(self.root, "big.py", _long_fn("f", 90))
        _history(self.root, [{"commit": "a", "big_units": 0}])
        signal = loop.next_signal(self.root)
        loop.record(self.root, signal)

        hit = loop.mandate_for(self.root, ["big.py"])
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["metric"], "big_units")
        self.assertEqual(hit[0]["path"], "big.py")
        self.assertEqual(hit[0]["target"], 0)
        self.assertTrue(hit[0]["why"])

        self.assertEqual(loop.mandate_for(self.root, ["other.py"]), ())

    def test_no_signal_means_silence(self) -> None:
        """기록이 없으면 튜터는 아무것도 안 그린다 — fail-open, 토큰 회귀 0."""
        self.assertIsNone(loop.load(self.root))
        self.assertEqual(loop.mandate_for(self.root, ["a.py"]), ())

    def test_broken_signal_file_is_silence_not_a_crash(self) -> None:
        _write(self.root, ".asgard/health/next.json", "{ this is not json")
        self.assertIsNone(loop.load(self.root))
        self.assertEqual(loop.mandate_for(self.root, ["a.py"]), ())


if __name__ == "__main__":
    unittest.main()
