"""미시 형상 판정 앵커 — 규칙별 진양성 하나와 **오탐 가드 하나**를 짝으로 못박는다.

실행: uv run pytest tests/test_craft.py

이 게이트는 복귀를 막는다. 그래서 여기서 고정할 것은 "잡는가"만이 아니라 "안 잡는가"다 —
판정기가 오탐을 내기 시작하면 다음에 일어나는 일은 게이트를 끄는 것이고, 그러면 규율이 통째로
사라진다. 규칙 하나를 더할 때 음성 대조군을 같이 넣지 않으면 그 규칙은 미완성이다.

래칫 계약도 여기서 고정한다: 물려받은 부채는 막지 않고, 이번 변경이 나쁘게 만든 것만 막는다.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from asgard import craft, craft_rules


def _patterns(source: str) -> set[str]:
    """규칙 이름 집합 — 줄 번호가 아니라 "무엇을 잡았나"로 고정한다 (본문 편집에 안 깨지게)."""
    units = craft_rules.units(source)
    assert units is not None
    return {f.rule for f in craft_rules.pattern_findings(source, "probe.py", list(units.values()))}


class UnitShapeTest(unittest.TestCase):
    def _shape(self, current: str, base: str | None) -> set[str]:
        cur = craft_rules.units(current)
        assert cur is not None
        prior = craft_rules.units(base) if base is not None else None
        return {f.rule for f in craft_rules.shape_findings("probe.py", cur, prior)}

    def test_a_new_long_function_is_caught(self):
        body = "def wide():\n" + "".join(f"    x{i} = {i}\n" for i in range(80))
        self.assertIn("unit-oversize", self._shape(body, None))

    def test_the_same_long_function_is_not_caught_twice(self):
        """물려받은 부채 — base 에도 똑같이 길었으면 이번 변경의 책임이 아니다."""
        body = "def wide():\n" + "".join(f"    x{i} = {i}\n" for i in range(80))
        self.assertEqual(self._shape(body, body), set())

    def test_a_long_function_that_grew_is_caught(self):
        before = "def wide():\n" + "".join(f"    x{i} = {i}\n" for i in range(80))
        after = "def wide():\n" + "".join(f"    x{i} = {i}\n" for i in range(90))
        self.assertIn("unit-oversize", self._shape(after, before))

    def test_a_long_function_that_shrank_is_silent(self):
        """줄어든 것은 개선이다 — 아직 예산을 넘었어도 침묵해야 수리가 진행된다."""
        before = "def wide():\n" + "".join(f"    x{i} = {i}\n" for i in range(120))
        after = "def wide():\n" + "".join(f"    x{i} = {i}\n" for i in range(80))
        self.assertEqual(self._shape(after, before), set())

    def test_a_long_data_literal_is_not_a_long_function(self):
        """길이는 "한 자리에서 너무 많은 일이 벌어진다"의 대리 지표다 — 표 하나를 돌려주는
        함수는 250행이어도 벌어지는 일이 하나뿐이라 그 대리가 틀린다 (실측 오탐: cc_settings)."""
        table = "def conf():\n    return {\n" + "".join(f'        "k{i}": {i},\n' for i in range(120)) + "    }\n"
        self.assertEqual(self._shape(table, None), set())

    def test_a_long_function_with_real_control_flow_is_still_caught(self):
        """데이터 면제가 로직까지 통과시키면 규칙이 통째로 죽는다 — 문장이 많으면 여전히 잡는다."""
        body = "def wide(a):\n" + "".join(f"    if a == {i}:\n        a = {i}\n" for i in range(40))
        self.assertIn("unit-oversize", self._shape(body, None))

    def test_deep_nesting_is_caught_and_flat_code_is_not(self):
        deep = (
            "def f(a):\n"
            "    if a:\n"
            "        for x in a:\n"
            "            while x:\n"
            "                with x:\n"
            "                    if x:\n"
            "                        pass\n"
        )
        self.assertIn("unit-deep", self._shape(deep, None))
        flat = "def f(a):\n    if not a:\n        return 0\n    return a + 1\n"
        self.assertEqual(self._shape(flat, None), set())


class ResourceLifetimeTest(unittest.TestCase):
    def test_cache_on_method_is_caught(self):
        src = "from functools import lru_cache\n\nclass S:\n    @lru_cache(maxsize=8)\n    def f(self, k):\n        return k\n"
        self.assertIn("cache-on-method", _patterns(src))

    def test_cache_on_a_plain_function_with_a_bound_is_not_caught(self):
        src = "from functools import lru_cache\n\n@lru_cache(maxsize=256)\ndef f(k):\n    return k\n"
        self.assertEqual(_patterns(src), set())

    def test_unbounded_cache_is_caught(self):
        src = "from functools import cache\n\n@cache\ndef f(k):\n    return k\n"
        self.assertIn("cache-unbounded", _patterns(src))

    def test_a_zero_argument_cache_is_not_caught(self):
        """인자가 없으면 키가 하나다 — 상수 메모이제이션은 자라지 않는다."""
        src = "from functools import cache\n\n@cache\ndef f():\n    return 1\n"
        self.assertEqual(_patterns(src), set())

    def test_unclosed_open_is_caught(self):
        self.assertIn("unclosed-acquire", _patterns("import json\n\ndef f(p):\n    return json.load(open(p))\n"))

    def test_with_and_try_finally_and_handoff_are_not_caught(self):
        managed = "def f(p):\n    with open(p) as fh:\n        return fh.read()\n"
        closed = "def f(p):\n    fh = open(p)\n    try:\n        return fh.read()\n    finally:\n        fh.close()\n"
        handed = "def f(p):\n    return open(p)\n"
        for src in (managed, closed, handed):
            self.assertEqual(_patterns(src), set(), src)

    def test_webbrowser_open_is_not_a_resource(self):
        """이름만 open 이고 bool 을 돌려준다 — 자원으로 재면 브라우저 여는 자리마다 오탐이 난다."""
        src = "import webbrowser\n\ndef f(url):\n    if not webbrowser.open(url):\n        raise OSError\n"
        self.assertEqual(_patterns(src), set())

    def test_a_handle_stored_in_a_container_has_an_owner(self):
        """`{"process": p}` 로 표에 담기면 수명은 그 표 주인의 것이다 — 지역에서 닫을 일이 아니다."""
        src = 'import subprocess\n\ndef f(self, cmd):\n    p = subprocess.Popen(cmd)\n    job = {"process": p}\n    self.jobs["x"] = job\n'
        self.assertEqual(_patterns(src), set())

    def test_a_deliberate_detached_spawn_is_not_a_leak(self):
        """새 세션에 파이프 없이 띄운 프로세스는 붙잡을 핸들도 잃을 출력도 없다."""
        detached = (
            "import subprocess\n\ndef f(exe):\n    subprocess.Popen(\n        [exe],\n"
            "        stdout=subprocess.DEVNULL,\n        stderr=subprocess.DEVNULL,\n"
            "        stdin=subprocess.DEVNULL,\n        start_new_session=True,\n    )\n"
        )
        self.assertEqual(_patterns(detached), set())

    def test_a_piped_spawn_is_still_judged(self):
        """면제는 파이프가 없을 때만이다 — 파이프를 열어두고 손을 놓으면 그건 누수다."""
        piped = (
            "import subprocess\n\ndef f(exe):\n    subprocess.Popen(\n        [exe],\n"
            "        stdout=subprocess.PIPE,\n        start_new_session=True,\n    )\n"
        )
        self.assertIn("unclosed-acquire", _patterns(piped))

    def test_os_open_is_not_judged_by_the_file_object_rule(self):
        """int fd 는 해제 규약이 다르다 — 같은 자로 재면 전부 오탐이 된다 (미검출로 남긴 영역)."""
        src = "import os\n\ndef f(p):\n    fd = os.open(p, os.O_RDONLY)\n    os.close(fd)\n"
        self.assertEqual(_patterns(src), set())

    def test_module_accumulator_that_only_grows_is_reported_but_does_not_block(self):
        src = "SEEN = {}\n\ndef put(k, v):\n    SEEN[k] = v\n"
        units = craft_rules.units(src)
        assert units is not None
        found = [f for f in craft_rules.pattern_findings(src, "p.py", list(units.values()))]
        self.assertEqual([f.rule for f in found], ["unbounded-accumulator"])
        self.assertFalse(found[0].blocking, "정적으로 증명 못 하는 것을 막으면 그것이 오탐이다")

    def test_an_accumulator_with_eviction_is_silent(self):
        src = "SEEN = {}\n\ndef put(k, v):\n    SEEN[k] = v\n\ndef drop(k):\n    SEEN.pop(k, None)\n"
        self.assertEqual(_patterns(src), set())

    def test_an_import_time_table_is_not_runtime_growth(self):
        """최상단에서 헬퍼로 짓는 상수 표는 수명이 아니라 정의다."""
        src = 'RULES = []\n\ndef rule(x):\n    RULES.append(x)\n\nrule("a")\nrule("b")\n'
        self.assertEqual(_patterns(src), set())


class CostTest(unittest.TestCase):
    def test_scanning_a_built_list_inside_a_loop_is_caught(self):
        src = "def f(rows, raw):\n    names = [r for r in rows]\n    for item in raw:\n        if item in names:\n            pass\n"
        self.assertIn("quadratic-scan", _patterns(src))

    def test_a_set_lookup_and_a_constant_tuple_are_not_caught(self):
        as_set = "def f(rows, raw):\n    names = {r for r in rows}\n    for item in raw:\n        if item in names:\n            pass\n"
        constant = 'SUFFIX = (".py", ".ts")\n\ndef f(raw):\n    for item in raw:\n        if item in SUFFIX:\n            pass\n'
        for src in (as_set, constant):
            self.assertEqual(_patterns(src), set(), src)

    def test_front_insertion_in_a_loop_is_caught(self):
        src = "def f(raw):\n    q = list(raw)\n    while q:\n        q.pop(0)\n"
        self.assertIn("quadratic-scan", _patterns(src))

    def test_rebuilding_by_concatenation_in_a_loop_is_caught(self):
        src = 'def f(rows):\n    text = ""\n    for r in rows:\n        text = text + str(r)\n    return text\n'
        self.assertIn("quadratic-scan", _patterns(src))

    def test_joining_at_the_end_is_not_caught(self):
        src = 'def f(rows):\n    parts = []\n    for r in rows:\n        parts.append(str(r))\n    return "".join(parts)\n'
        self.assertEqual(_patterns(src), set())

    def test_a_finding_is_not_reported_twice_across_nested_scopes(self):
        """바깥 스코프가 안쪽 함수 노드를 같이 세면 같은 판정이 두 번 나온다."""
        src = "def outer(rows, raw):\n    def inner():\n        names = [r for r in rows]\n        for item in raw:\n            if item in names:\n                pass\n    return inner\n"
        units = craft_rules.units(src)
        assert units is not None
        found = craft_rules.pattern_findings(src, "p.py", list(units.values()))
        self.assertEqual(len(found), 1, [f.detail for f in found])


class RatchetTest(unittest.TestCase):
    """실제 git 저장소 위에서 base 대조를 확인한다 — 래칫은 파일 내용이 아니라 이력에 걸린다."""

    def _repo(self, stack) -> str:
        root = stack.enter_context(tempfile.TemporaryDirectory())
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=root, check=True, env=env, capture_output=True)
        return root

    def _commit(self, root: str) -> None:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True, env=env, capture_output=True)

    def test_inherited_debt_passes_and_a_fresh_defect_blocks(self):
        import contextlib

        leaky = "import json\n\ndef f(p):\n    return json.load(open(p))\n"
        with contextlib.ExitStack() as stack:
            root = self._repo(stack)
            path = os.path.join(root, "m.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(leaky)
            self._commit(root)

            passed = craft.judge(root, ["m.py"])
            self.assertEqual(passed.blocking, (), "이미 있던 결함이 복귀를 막으면 수리가 불가능해진다")
            self.assertEqual(passed.inherited, 1)

            with open(path, "w", encoding="utf-8") as handle:
                handle.write(leaky + "\ndef g(p):\n    return json.load(open(p))\n")
            blocked = craft.judge(root, ["m.py"])
            self.assertTrue(blocked.blocking, "같은 파일에 하나를 더 얹은 것은 이번 변경의 책임이다")

    def test_a_non_python_path_is_undetermined_not_clean(self):
        report = craft.judge(".", ["README.md"])
        self.assertEqual(report.findings, ())
        self.assertEqual(len(report.undetermined), 1, "판정 못 한 것을 통과로 세면 게이트가 거짓말을 한다")


class SelfApplicationTest(unittest.TestCase):
    def test_the_engine_clears_its_own_gate(self):
        """규율을 설치한 코드가 그 규율을 못 지키면 그 규율은 지킬 수 없는 것이다."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        report = craft.judge(root, ["src/asgard/craft.py", "src/asgard/craft_rules.py", "src/asgard/commands/craft.py"])
        self.assertEqual(
            [f"{f.rule} {f.path}:{f.line}" for f in report.blocking],
            [],
        )


if __name__ == "__main__":
    unittest.main()
