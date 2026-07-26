"""health — 침식 지표의 앵커. 지표는 판정에 쓰이므로 **정확한 수**를 고정한다.

실행: uv run pytest tests/test_health.py

문턱을 바꾸면 이 테스트가 먼저 깨진다 — 의도한 변경이면 기대값을 같이 옮기고, 안 깨졌는데
수가 달라졌으면 계측이 조용히 새고 있는 것이다.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest

from asgard import health


def _write(root: str, rel: str, body: str) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


# 6행 창을 채우고 CLONE_MIN_CHARS(120) 를 넘기는 본문 — 클론 앵커의 재료
_CLONE_BODY = "\n".join(
    f"    value_{i} = compute_something_with_a_long_name({i}, extra_keyword_argument=True)" for i in range(8)
)


class TestScan(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def test_size_metrics_are_exact(self) -> None:
        """큰 파일·큰 함수·중첩 깊이가 문턱 기준으로 정확히 세어진다."""
        long_fn = "def big():\n" + "\n".join(f"    x{i} = {i}" for i in range(health.UNIT_LINES_WARN + 5))
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/big.py", long_fn)
        _write(self.root, "pkg/small.py", "def tiny():\n    return 1\n")
        snap = health.scan(self.root)
        self.assertEqual(snap.big_units, 1, "문턱 초과 함수는 1개뿐이어야 한다")
        self.assertEqual(snap.files, 3)
        self.assertEqual(snap.severe_files, 0)
        # big.py 는 74행 — FILE_LINES_WARN(400) 아래라 큰 파일이 아니다
        self.assertEqual(snap.big_files, 0)

    def test_nesting_depth_counts_branches_only(self) -> None:
        """중첩 깊이는 분기문만 센다 — 중첩 함수는 자기 깊이로 따로 잡힌다."""
        body = "def outer():\n    if a:\n        for b in c:\n            while d:\n                return 1\n"
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/deep.py", body)
        snap = health.scan(self.root)
        self.assertEqual(snap.deep_units, 0, "깊이 3 은 DEPTH_WARN(4) 이하")
        _write(
            self.root,
            "pkg/deeper.py",
            body.replace("return 1", "with e:\n                    with f:\n                        return 1"),
        )
        self.assertEqual(health.scan(self.root).deep_units, 1)

    def test_clone_detection_finds_cross_file_duplication(self) -> None:
        """같은 6행 블록이 두 파일에 있으면 두 파일 모두 중복 행으로 표시된다."""
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", f"def a():\n{_CLONE_BODY}\n")
        _write(self.root, "pkg/b.py", f"def b():\n{_CLONE_BODY}\n")
        snap = health.scan(self.root)
        self.assertGreater(snap.dup_lines, 0)
        self.assertGreater(snap.dup_share, 0)
        paths = {p for group in snap.dup_top for p in group["paths"]}
        self.assertEqual(paths, {"pkg/a.py", "pkg/b.py"})

    def test_import_blocks_are_not_clones(self) -> None:
        """정당하게 반복되는 import 행은 클론으로 세지 않는다 (신호 보존)."""
        imports = "\n".join(f"import module_number_{i}_with_a_long_name" for i in range(12))
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", imports + "\n")
        _write(self.root, "pkg/b.py", imports + "\n")
        self.assertEqual(health.scan(self.root).dup_lines, 0)

    def test_tests_are_split_from_source(self) -> None:
        """테스트 파일은 소스 지표에 섞이지 않는다."""
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", "def a():\n    return 1\n")
        _write(self.root, "tests/test_a.py", "def test_a():\n    assert True\n")
        snap = health.scan(self.root)
        self.assertEqual(snap.files, 2)  # pkg/__init__.py + pkg/a.py
        self.assertEqual(snap.test_files, 1)
        self.assertGreater(snap.test_code_lines, 0)

    def test_non_python_is_unmeasured_not_zero(self) -> None:
        """다른 언어는 크기만 재고 미측정으로 센다 — 0 으로 채워 깨끗한 척하지 않는다."""
        _write(self.root, "web/app.ts", "export function f() {\n  return 1;\n}\n")
        snap = health.scan(self.root)
        self.assertEqual(snap.files, 1)
        self.assertEqual(snap.unmeasured_files, 1)
        self.assertEqual(snap.big_units, 0)
        self.assertGreater(snap.code_lines, 0)
        self.assertEqual(snap.langs, {"TypeScript": 1})

    def test_excludes_are_honored_and_counted(self) -> None:
        """설정 exclude 는 빠진 수를 함께 보고한다 (조용한 절단 금지)."""
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", "def a():\n    return 1\n")
        _write(self.root, "vendored_bundle/dep.py", "def d():\n    return 1\n")
        _write(
            self.root,
            ".asgard/asgard-setting-project.json",
            json.dumps({"health": {"exclude": ["vendored_bundle/**"]}}),
        )
        snap = health.scan(self.root)
        self.assertEqual(snap.files, 2)
        self.assertEqual(snap.excluded_files, 1)

    def test_default_ignored_dirs_are_skipped(self) -> None:
        """node_modules·vendor 류는 설정 없이도 빠진다 (남의 나무는 우리 추세가 아니다)."""
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "node_modules/x/index.js", "var a = 1;\n")
        _write(self.root, "vendor/y.py", "def y():\n    return 1\n")
        snap = health.scan(self.root)
        self.assertEqual(snap.files, 1)
        self.assertEqual(snap.excluded_files, 0, "기본 무시는 exclude 계상 대상이 아니다")

    def test_vendored_skill_bundles_are_ignored_without_configuration(self) -> None:
        """`skill_plugins` 는 코드 기본값으로 빠져야 한다 — 설정에 의존하면 그 설정이 `.asgard/`
        째로 gitignore 되는 리포에서 규칙이 따라가지 않아 남의 코드가 우리 추세로 섞인다."""
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "src/app/assets/skill_plugins/upstream/big.py", "\n".join(f"y{i} = {i}" for i in range(900)))
        snap = health.scan(self.root)
        self.assertEqual(snap.files, 1)
        self.assertEqual(snap.severe_files, 0, "이식한 번들이 심각 파일로 세어지면 추세가 거짓이 된다")


class TestCoupling(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def test_import_cycle_is_detected(self) -> None:
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", "from pkg import b\n")
        _write(self.root, "pkg/b.py", "from pkg import a\n")
        self.assertEqual(health.scan(self.root).cycles, 1)

    def test_lazy_import_inside_function_is_not_an_edge(self) -> None:
        """함수 내부 lazy import 는 의도된 탈출구 — 상시 결합으로 세지 않는다."""
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", "def go():\n    from pkg import b\n    return b\n")
        _write(self.root, "pkg/b.py", "VALUE = 1\n")
        self.assertEqual(health.scan(self.root).cycles, 0)
        self.assertEqual(health.scan(self.root).max_fan_out, 0)

    def test_relative_sibling_import_is_not_a_package_init_edge(self) -> None:
        """`from . import sibling` 은 패키지 __init__ 의존이 아니다 — fan-in 오계상 회귀 앵커."""
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", "from . import b\n")
        _write(self.root, "pkg/b.py", "VALUE = 1\n")
        snap = health.scan(self.root)
        by_path = {f["path"]: f for f in snap.coupling_top}
        # coupling_top 은 결합이 0 인 파일을 아예 싣지 않는다 — 부재 자체가 fan_in 0 의 증거다
        self.assertEqual(by_path.get("pkg/__init__.py", {"fan_in": 0})["fan_in"], 0)
        self.assertEqual(by_path["pkg/b.py"]["fan_in"], 1)
        self.assertEqual(by_path["pkg/a.py"]["fan_out"], 1, "형제 1개만 의존")

    def test_submodule_import_credits_both_package_and_module(self) -> None:
        """`from a.b import c` 는 a.b 에 대한 의존이다 (module 이 명시된 경우)."""
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/sub/__init__.py", "")
        _write(self.root, "pkg/sub/deep.py", "VALUE = 1\n")
        _write(self.root, "pkg/user.py", "from pkg.sub import deep\n")
        snap = health.scan(self.root)
        by_path = {f["path"]: f for f in snap.coupling_top}
        self.assertEqual(by_path["pkg/user.py"]["fan_out"], 2, "pkg.sub 와 pkg.sub.deep 양쪽")
        self.assertEqual(by_path["pkg/sub/deep.py"]["fan_in"], 1)


class TestTrend(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", "def a():\n    return 1\n")

    def test_no_history_means_no_trend(self) -> None:
        self.assertIsNone(health.trend(self.root))

    def test_regression_and_improvement_directions(self) -> None:
        health.record(self.root)
        long_fn = "def big():\n" + "\n".join(f"    x{i} = {i}" for i in range(health.UNIT_LINES_WARN + 5))
        _write(self.root, "pkg/big.py", long_fn)
        tr = health.trend(self.root)
        self.assertIsNotNone(tr)
        assert tr is not None
        worse = {d.metric for d in tr.regressed}
        self.assertIn("big_units", worse)

        health.record(self.root)  # 나빠진 상태를 기준으로 기록
        os.remove(os.path.join(self.root, "pkg/big.py"))
        tr2 = health.trend(self.root)
        assert tr2 is not None
        improved = {d.metric for d in tr2.deltas if d.direction == "improved"}
        self.assertIn("big_units", improved)
        self.assertEqual(tr2.regressed, ())

    def test_flat_when_nothing_moved(self) -> None:
        health.record(self.root)
        tr = health.trend(self.root)
        assert tr is not None
        self.assertEqual(tr.regressed, ())
        self.assertTrue(all(d.direction == "flat" for d in tr.deltas))

    def test_growth_alone_is_not_a_regression(self) -> None:
        """코드가 늘어난 것 자체는 침식이 아니다 — 비율·개수 지표만 추세로 판정한다."""
        health.record(self.root)
        _write(self.root, "pkg/more.py", "\n".join(f"def f{i}():\n    return {i}\n" for i in range(30)))
        tr = health.trend(self.root)
        assert tr is not None
        self.assertEqual(tr.regressed, (), "행 수 증가만으로는 나빠진 게 없다")
        self.assertNotIn("code_lines", {d.metric for d in tr.deltas})

    def test_history_is_bounded(self) -> None:
        for _ in range(health.HISTORY_KEEP + 5):
            health.record(self.root)
        with open(health.history_path(self.root), encoding="utf-8") as fh:
            rows = [line for line in fh if line.strip()]
        self.assertEqual(len(rows), health.HISTORY_KEEP)

    def test_corrupt_history_line_is_skipped(self) -> None:
        """이력이 깨져도 스캔은 죽지 않는다 (fail-open — 신호는 게이트가 아니다)."""
        health.record(self.root)
        with open(health.history_path(self.root), "a", encoding="utf-8") as fh:
            fh.write("{not json\n")
        self.assertIsNotNone(health.trend(self.root))


class TestChurn(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def test_no_git_yields_no_hotspots_not_an_error(self) -> None:
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", "def a():\n    return 1\n")
        snap = health.scan(self.root)
        self.assertEqual(snap.hotspots, [])
        self.assertEqual(snap.churn_window, 0)
        self.assertEqual(snap.commit, "unknown")

    def test_churn_comes_from_git_history(self) -> None:
        def git(*args: str) -> None:
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

        git("init", "-q")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", "def a():\n    return 1\n")
        git("add", "-A")
        git("commit", "-qm", "one")
        _write(self.root, "pkg/a.py", "def a():\n    return 2\n")
        git("add", "-A")
        git("commit", "-qm", "two")
        snap = health.scan(self.root)
        self.assertEqual(snap.churn_window, 2)
        spots = {s["path"]: s["churn"] for s in snap.hotspots}
        self.assertEqual(spots.get("pkg/a.py"), 2)
        self.assertNotEqual(snap.commit, "unknown")


if __name__ == "__main__":
    unittest.main()
