"""health 게이트 — 여덟 지표 중 둘만 막는 자리. 여기서 봉인하는 것은 세 가지다.

실행: uv run pytest tests/test_health_gate.py

① **막는 축이 정말 막는가** — severe_files·cycles 가 기준선을 넘으면 종료 코드가 1이다.
② **안 막는 축이 안 막는가** — 나머지 여섯이 나빠져도 조용하다. 이게 깨지면 게이트는 곧
   꺼진다. 오탐이 쌓인 게이트를 사람이 어떻게 하는지는 이 저장소가 이미 여러 번 적어 뒀다.
③ **기준선이 없을 때 조용히 통과하지 않는가** — 판정 못 한 지표는 `undetermined` 로 나온다.
   "위반 0건"이 "안 봤다"를 뜻할 수 있으면 게이트가 아니라 알리바이다.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from asgard import health
from asgard.commands.health import run_gate

# FILE_LINES_SEVERE(1000) 를 확실히 넘기는 본문 — 주석·빈 줄은 코드 행에 안 세므로 실제 대입문으로 채운다
_SEVERE = "\n".join(f"value_{i} = {i}" for i in range(health.FILE_LINES_SEVERE + 60)) + "\n"


def _write(root: str, rel: str, body: str) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def _pyproject(root: str, table: str) -> None:
    _write(root, "pyproject.toml", '[project]\nname = "probe"\n' + table)


class GateBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/small.py", "def tiny():\n    return 1\n")


class TestBaseline(GateBase):
    def test_missing_pyproject_leaves_both_axes_undetermined(self) -> None:
        """pyproject 가 없는 트리는 통과하되, 두 축 다 '못 봤다'로 나온다."""
        report = health.gate(self.root)
        self.assertFalse(report.blocked)
        self.assertEqual(report.baseline, {})
        self.assertEqual(set(report.undetermined), set(health.GATE_METRICS))

    def test_partial_baseline_reports_the_axis_it_cannot_judge(self) -> None:
        """한 축만 적어 두면 나머지 한 축은 0으로 채우지 않고 미판정으로 남는다."""
        _pyproject(self.root, "\n[tool.asgard.health-gate]\ncycles = 0\n")
        report = health.gate(self.root)
        self.assertEqual(report.baseline, {"cycles": 0})
        self.assertEqual(report.undetermined, ("severe_files",))

    def test_a_value_that_is_not_a_count_is_not_a_baseline(self) -> None:
        """문자열·음수·bool 은 기준선으로 안 읽는다 — 조용히 통과시키느니 미판정이 낫다."""
        for raw in ('"10"', "-1", "true"):
            with self.subTest(raw=raw):
                _pyproject(self.root, f"\n[tool.asgard.health-gate]\nsevere_files = {raw}\ncycles = 0\n")
                report = health.gate(self.root)
                self.assertNotIn("severe_files", report.baseline)
                self.assertIn("severe_files", report.undetermined)

    def test_broken_toml_does_not_take_the_gate_down(self) -> None:
        _write(self.root, "pyproject.toml", "[tool.asgard.health-gate\nsevere_files = 0\n")
        self.assertEqual(health.gate_baseline(self.root), {})


class TestSevereFiles(GateBase):
    def test_a_new_thousand_line_file_blocks(self) -> None:
        _pyproject(self.root, "\n[tool.asgard.health-gate]\nsevere_files = 0\ncycles = 0\n")
        _write(self.root, "pkg/huge.py", _SEVERE)
        report = health.gate(self.root)
        self.assertTrue(report.blocked)
        self.assertEqual([v.metric for v in report.violations], ["severe_files"])
        self.assertEqual((report.violations[0].baseline, report.violations[0].current), (0, 1))

    def test_inherited_debt_is_not_this_change_s_fault(self) -> None:
        """기준선과 같으면 통과한다 — 물려받은 부채는 여기서 묻지 않는다 (craft 래칫과 같은 계약)."""
        _pyproject(self.root, "\n[tool.asgard.health-gate]\nsevere_files = 1\ncycles = 0\n")
        _write(self.root, "pkg/huge.py", _SEVERE)
        self.assertFalse(health.gate(self.root).blocked)

    def test_going_down_is_silent(self) -> None:
        """개선은 판정 대상이 아니다. 내려간 것을 알리는 것은 `asgard health` 의 일이다."""
        _pyproject(self.root, "\n[tool.asgard.health-gate]\nsevere_files = 3\ncycles = 0\n")
        report = health.gate(self.root)
        self.assertFalse(report.blocked)
        self.assertEqual(report.violations, ())

    def test_tests_do_not_count_toward_the_gate(self) -> None:
        """스냅샷이 소스만 세므로 게이트도 소스만 센다 — 큰 픽스처 파일이 제품 판정을 막으면 안 된다."""
        _pyproject(self.root, "\n[tool.asgard.health-gate]\nsevere_files = 0\ncycles = 0\n")
        _write(self.root, "tests/test_huge.py", _SEVERE)
        self.assertFalse(health.gate(self.root).blocked)


class TestCycles(GateBase):
    def test_an_import_cycle_blocks(self) -> None:
        _pyproject(self.root, "\n[tool.asgard.health-gate]\nsevere_files = 0\ncycles = 0\n")
        _write(self.root, "pkg/a.py", "from pkg import b\n\n\ndef fa():\n    return b\n")
        _write(self.root, "pkg/b.py", "from pkg import a\n\n\ndef fb():\n    return a\n")
        report = health.gate(self.root)
        self.assertTrue(report.blocked)
        self.assertEqual([v.metric for v in report.violations], ["cycles"])
        self.assertEqual(report.violations[0].current, 1)


class TestTheSixAxesStayQuiet(GateBase):
    def test_worse_size_and_duplication_do_not_block(self) -> None:
        """big_files·big_units·deep_units·dup_share 가 다 나빠져도 게이트는 조용하다.

        막는 축을 늘리자는 압력은 계속 온다. 이 테스트가 그 압력에 대한 답이다 — 늘리려면
        여기부터 고쳐야 하고, 그때 GATE_METRICS 주석의 근거(되돌리기 비용)를 다시 써야 한다.
        """
        _pyproject(self.root, "\n[tool.asgard.health-gate]\nsevere_files = 0\ncycles = 0\n")
        # 400행 초과(big_files) + 70행 초과 함수(big_units) + DEPTH_WARN(4) 초과 중첩, 1000행 미만
        body = "def big():\n" + "\n".join(f"    x{i} = {i}" for i in range(health.FILE_LINES_WARN + 100))
        deep = "\ndef deep():\n    if a:\n        for b in c:\n            while d:\n                with e:\n"
        deep += "                    if f:\n                        return 1\n"
        _write(self.root, "pkg/fat.py", body + "\n" + deep)
        snap = health.scan(self.root)
        self.assertGreater(snap.big_files, 0)
        self.assertGreater(snap.big_units, 0)
        self.assertGreater(snap.deep_units, 0)
        self.assertEqual(snap.severe_files, 0)
        self.assertFalse(health.gate(self.root, snap).blocked)


class TestRunGate(GateBase):
    """사람·CI 표면 — 판정은 종료 코드로 나간다. 여기가 어긋나면 CI 는 늘 초록이다."""

    def _run(self, **kwargs: bool) -> tuple[int, str]:
        buf = io.StringIO()
        with mock.patch("os.getcwd", return_value=self.root), redirect_stdout(buf):
            code = run_gate(**kwargs)
        return code, buf.getvalue()

    def test_clean_tree_exits_zero(self) -> None:
        _pyproject(self.root, "\n[tool.asgard.health-gate]\nsevere_files = 0\ncycles = 0\n")
        code, _ = self._run(quiet=True)
        self.assertEqual(code, 0)

    def test_regression_exits_one(self) -> None:
        _pyproject(self.root, "\n[tool.asgard.health-gate]\nsevere_files = 0\ncycles = 0\n")
        _write(self.root, "pkg/huge.py", _SEVERE)
        code, _ = self._run(quiet=True)
        self.assertEqual(code, 1)

    def test_json_carries_the_violation_and_the_exit_code(self) -> None:
        _pyproject(self.root, "\n[tool.asgard.health-gate]\nsevere_files = 0\ncycles = 0\n")
        _write(self.root, "pkg/huge.py", _SEVERE)
        code, out = self._run(json_out=True)
        payload = json.loads(out)
        self.assertEqual(code, 1)
        self.assertTrue(payload["blocked"])
        self.assertEqual(payload["violations"], [{"metric": "severe_files", "baseline": 0, "current": 1}])
        self.assertEqual(payload["undetermined"], [])

    def test_json_names_the_axes_it_could_not_judge(self) -> None:
        code, out = self._run(json_out=True)
        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertFalse(payload["blocked"])
        self.assertEqual(sorted(payload["undetermined"]), sorted(health.GATE_METRICS))


class TestThisRepositoryHasABaseline(unittest.TestCase):
    """이 저장소 자신의 기준선이 실재하는가. 게이트를 만들어 놓고 자기한테 안 거는 것을 막는다."""

    def test_both_axes_are_pinned_in_pyproject(self) -> None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        baseline = health.gate_baseline(root)
        self.assertEqual(sorted(baseline), sorted(health.GATE_METRICS), "pyproject.toml 기준선이 비었다")
        self.assertEqual(baseline["cycles"], 0, "순환 0 이 아닌 기준선은 근거 없이 못 올린다")


if __name__ == "__main__":
    unittest.main()
