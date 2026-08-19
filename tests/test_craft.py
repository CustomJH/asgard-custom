"""미시 형상 판정 앵커 — 규칙별 진양성 하나와 **오탐 가드 하나**를 짝으로 못박는다.

실행: uv run pytest tests/test_craft.py

이 게이트는 복귀를 막는다. 그래서 여기서 고정할 것은 "잡는가"만이 아니라 "안 잡는가"다 —
판정기가 오탐을 내기 시작하면 다음에 일어나는 일은 게이트를 끄는 것이고, 그러면 규율이 통째로
사라진다. 규칙 하나를 더할 때 음성 대조군을 같이 넣지 않으면 그 규칙은 미완성이다.

래칫 계약도 여기서 고정한다: 물려받은 부채는 막지 않고, 이번 변경이 나쁘게 만든 것만 막는다.
그 계약은 경로가 아니라 파일에 걸린다 — 개명이 기준선을 지우면 파일을 옮긴 것만으로 물려받은
위반이 전부 차단으로 뒤집힌다 (MoveTest).
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
import unittest

from asgard import craft, craft_rules, health


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
        """이름만 open 이고 bool을 돌려준다 — 자원으로 재면 브라우저 여는 자리마다 오탐이 난다."""
        src = "import webbrowser\n\ndef f(url):\n    if not webbrowser.open(url):\n        raise OSError\n"
        self.assertEqual(_patterns(src), set())

    def test_a_handle_stored_in_a_container_has_an_owner(self):
        """`{"process": p}`로 표에 담기면 수명은 그 표 주인의 것이다 — 지역에서 닫을 일이 아니다."""
        src = 'import subprocess\n\ndef f(self, cmd):\n    p = subprocess.Popen(cmd)\n    job = {"process": p}\n    self.jobs["x"] = job\n'
        self.assertEqual(_patterns(src), set())

    def test_a_handle_stored_by_subscript_has_an_owner(self):
        """`table["k"] = p`는 `self.p = p`와 같은 인계다 — 한쪽만 알면 같은 코드가 경로마다 다르게 읽힌다.

        holder가 있으면 `_released`가, 없으면 `_handed_off`가 판정하는데 후자만 Subscript를
        알아서, 이 형태가 막는 오탐으로 나왔다 (실측: 실트리 10,769파일에서 8건).
        """
        src = 'import subprocess\n\ndef f(cmd, table):\n    p = subprocess.Popen(cmd)\n    table["proc"] = p\n'
        self.assertEqual(_patterns(src), set())

    def test_an_alias_before_the_handoff_does_not_end_the_search(self):
        """`q = p`에서 판정을 끝내면 그 **뒤**의 진짜 인계를 못 본다 — 스캔은 계속되어야 한다."""
        src = "import subprocess\n\nclass S:\n    def f(self, cmd):\n        p = subprocess.Popen(cmd)\n        q = p\n        self.p = p\n"
        self.assertEqual(_patterns(src), set())

    def test_an_alias_alone_is_still_a_leak(self):
        """면제는 소유가 **다른 객체로** 갈 때만이다 — 지역 이름끼리 옮겨 담은 것은 인계가 아니다."""
        src = "import subprocess\n\ndef f(cmd):\n    p = subprocess.Popen(cmd)\n    q = p\n"
        self.assertIn("unclosed-acquire", _patterns(src))

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
        """int fd는 해제 규약이 다르다 — 같은 자로 재면 전부 오탐이 된다 (미검출로 남긴 영역)."""
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


def _oversize(branches: int) -> str:
    """예산을 넘는 함수 하나. 분기를 넣는 이유는 데이터 면제(DATA_STMT_MAX)에 걸리지 않기 위해서다."""
    return "def wide(a):\n" + "".join(f"    if a == {i}:\n        a = {i}\n" for i in range(branches))


_INNERMOST = "                            a = c\n"


def _deep_method(owner: str, name: str = "wide") -> str:
    """길이·중첩 예산을 함께 넘는 메서드 하나. 소유 클래스를 인자로 받는다 — 파일을 옮기면서
    메서드가 다른 클래스로 넘어가면 qualname 의 앞마디만 달라지고 본문은 글자 그대로 남는다."""
    block = "".join(
        f"        if a == {i}:\n"
        "            for b in range(a):\n"
        "                if b:\n"
        "                    for c in range(b):\n"
        "                        if c:\n" + _INNERMOST
        for i in range(15)
    )
    return f"class {owner}:\n    def {name}(self, a):\n{block}"


LEAK = "import json\n\n\ndef load(path):\n    return json.load(open(path))\n\n\n"
INHERITED = LEAK + _oversize(40)  # 물려받은 부채 2건 — unclosed-acquire + unit-oversize
# 위와 겹치는 줄이 없는 파일. 삭제와 신설이 한 변경에 있어도 이건 그 삭제의 도착지가 아니다.
UNRELATED = "import os\n\n\ndef other(b):\n" + "".join(f"    if b == {i}0:\n        b = os.sep\n" for i in range(45))

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


class _GitTree:
    """임시 git 저장소를 세우는 손잡이. TestCase 가 아니라서 상속해도 시험이 두 번 돌지 않는다."""

    def _repo(self, stack) -> str:
        root = stack.enter_context(tempfile.TemporaryDirectory())
        for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=root, check=True, env=_ENV, capture_output=True)
        return root

    def _commit(self, root: str) -> None:
        subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=_ENV, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True, env=_ENV, capture_output=True)

    def _write(self, root: str, rel: str, text: str) -> None:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)


class RatchetTest(_GitTree, unittest.TestCase):
    """실제 git 저장소 위에서 base 대조를 확인한다 — 래칫은 파일 내용이 아니라 이력에 걸린다."""

    def test_inherited_debt_passes_and_a_fresh_defect_blocks(self):
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


class MoveTest(_GitTree, unittest.TestCase):
    """개명은 기준선을 지우는 사건이 아니다 — 자리를 옮긴 파일도 물려받은 부채를 그대로 물려받는다.

    이 시험이 없으면 다음에 일어나는 일이 정해져 있다: 가족 단위로 파일 수십 개를 패키지로 묶는
    변경 한 번이 거짓 차단 수십 건으로 돌아오고, 사람은 판정을 고치는 대신 게이트를 끈다.

    한 파일을 여러 파일로 가른 것도 같은 사건이다 — 조각 하나하나는 원본과 안 닮았지만, 그 줄은
    base 에 글자 그대로 있다.

    반대쪽도 같은 무게로 못박는다 — 옮기면서 나빠진 것과, 이동을 가장한 신규 파일은 여전히 막힌다.
    개명을 따라가느라 진짜 악화를 놓치면 래칫이 막아야 할 절반을 잃는다.
    """

    def _base(self, stack) -> str:
        """`pkg/rules.py` 에 물려받은 부채 2건을 담아 커밋한 저장소."""
        root = self._repo(stack)
        self._write(root, "pkg/rules.py", INHERITED)
        self._commit(root)
        return root

    def _git_mv(self, root: str, old: str, new: str) -> None:
        os.makedirs(os.path.dirname(os.path.join(root, new)), exist_ok=True)
        subprocess.run(["git", "mv", old, new], cwd=root, check=True, env=_ENV, capture_output=True)

    def _plain_mv(self, root: str, old: str, new: str, text: str) -> None:
        """색인을 거치지 않은 이동 — 새 파일은 추적되지 않아 git diff 에 아예 안 나온다."""
        self._write(root, new, text)
        os.unlink(os.path.join(root, old))

    def test_a_staged_rename_keeps_its_baseline(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack)
            self._git_mv(root, "pkg/rules.py", "pkg/craft/rules.py")
            report = craft.judge(root, ["pkg/craft/rules.py"])
            self.assertEqual(report.blocking, (), "옮기기만 한 파일이 막히면 게이트가 개명을 벌하는 것이다")
            self.assertEqual(report.inherited, 1)
            self.assertEqual(report.moved, (("pkg/craft/rules.py", "pkg/rules.py"),))

    def test_a_move_git_never_saw_keeps_its_baseline(self):
        """`git mv` 없이 옮긴 자리 — 새 파일이 추적되지 않으면 git 은 개명 짝을 지어 주지 않는다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack)
            self._plain_mv(root, "pkg/rules.py", "pkg/craft/rules.py", INHERITED)
            report = craft.judge(root, ["pkg/craft/rules.py"])
            self.assertEqual(report.blocking, ())
            self.assertEqual(report.moved, (("pkg/craft/rules.py", "pkg/rules.py"),))

    def test_a_move_that_also_grew_a_function_still_blocks(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack)
            self._plain_mv(root, "pkg/rules.py", "pkg/craft/rules.py", LEAK + _oversize(50))
            report = craft.judge(root, ["pkg/craft/rules.py"])
            self.assertEqual(sorted(f.rule for f in report.blocking), ["unit-branchy", "unit-oversize"])

    def test_a_move_that_also_added_a_leak_still_blocks(self):
        with contextlib.ExitStack() as stack:
            root = self._base(stack)
            extra = INHERITED + "\n\ndef load2(path):\n    return json.load(open(path))\n"
            self._plain_mv(root, "pkg/rules.py", "pkg/craft/rules.py", extra)
            report = craft.judge(root, ["pkg/craft/rules.py"])
            self.assertEqual([f.rule for f in report.blocking], ["unclosed-acquire"])

    def test_a_file_split_into_parts_keeps_its_baseline(self):
        """조각은 원본의 일부라서 원본만큼 안 닮았다 — 닮은 정도로만 짝을 지으면 짝이 안 지어진다.

        실측(26-08-12): tests/test_trinity.py 4,386행을 9파일로 가르자 옮겨온 4,437행이 전부
        신규로 잡히고 차단 34건이 났다. 그 34건은 전부 `git show HEAD:tests/test_trinity.py` 에
        글자 그대로 있던 줄이었다.
        """
        with contextlib.ExitStack() as stack:
            root = self._base(stack)
            self._write(root, "pkg/craft/load.py", LEAK)
            self._write(root, "pkg/craft/wide.py", _oversize(40))
            os.unlink(os.path.join(root, "pkg/rules.py"))
            report = craft.judge(root, ["pkg/craft/load.py", "pkg/craft/wide.py"])
            self.assertEqual(report.blocking, (), "옮겨 온 줄을 신규로 세면 분해 한 번이 차단 수십 건이 된다")
            self.assertEqual(
                report.moved,
                (("pkg/craft/load.py", "pkg/rules.py"), ("pkg/craft/wide.py", "pkg/rules.py")),
            )
            self.assertEqual(report.inherited, 1, "조각이 물려받은 부채는 래칫이 넘긴 것으로 세야 보고에 남는다")

    def test_a_defect_added_while_splitting_still_blocks(self):
        """분해를 알아보느라 진짜 신규를 놓치면 래칫이 막아야 할 절반을 잃는다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack)
            self._write(root, "pkg/craft/load.py", LEAK + "\ndef load2(path):\n    return json.load(open(path))\n")
            self._write(root, "pkg/craft/wide.py", _oversize(40))
            os.unlink(os.path.join(root, "pkg/rules.py"))
            report = craft.judge(root, ["pkg/craft/load.py", "pkg/craft/wide.py"])
            self.assertEqual(
                [f"{f.rule} {f.path}:{f.unit}" for f in report.blocking],
                ["unclosed-acquire pkg/craft/load.py:load2"],
            )

    def _moved_method(self, stack, owner: str, current: str) -> craft.Report:
        """`pkg/session.py` 의 `AgentSession.wide` 를 `pkg/parts/chat.py` 로 옮긴 저장소를 판정한다."""
        root = self._repo(stack)
        self._write(root, "pkg/session.py", _deep_method("AgentSession"))
        self._commit(root)
        self._plain_mv(root, "pkg/session.py", "pkg/parts/chat.py", current)
        assert owner in current
        return craft.judge(root, ["pkg/parts/chat.py"])

    def test_a_unit_that_only_changed_its_qualifier_keeps_its_baseline(self):
        """파일을 이었어도 그 안의 함수를 못 이으면 물려받은 부채가 그대로 차단으로 돌아온다.

        실측(26-08-13): src/asgard/agent/session.py 를 패키지로 가르며 메서드 셋의 소유 클래스가
        AgentSession 에서 믹스인으로 바뀌자, 본문을 한 글자도 안 고친 그 셋에서 차단 5건이 났다
        (길이 3 + 중첩 2). 파일 짝은 제대로 지어진 상태였고 끊긴 자리는 qualname 조회 하나였다.
        """
        with contextlib.ExitStack() as stack:
            report = self._moved_method(stack, "_ChatMixin", _deep_method("_ChatMixin"))
            self.assertEqual(report.blocking, (), "한정자만 달라진 메서드를 신규로 세면 분해가 차단으로 돌아온다")

    def test_a_defect_added_to_a_requalified_unit_still_blocks(self):
        """줄 수와 중첩을 그대로 둔 채 자원 하나만 새로 흘린다 — 이동 추적이 그것까지 덮으면 안 된다."""
        with contextlib.ExitStack() as stack:
            leaked = _deep_method("_ChatMixin").replace(_INNERMOST, "                            f = open(self.p)\n", 1)
            report = self._moved_method(stack, "_ChatMixin", leaked)
            self.assertEqual(
                [f"{f.rule} {f.unit}" for f in report.blocking],
                ["unclosed-acquire _ChatMixin.wide"],
            )

    def test_a_name_that_two_classes_share_is_not_matched(self):
        """같은 뒷마디가 둘이면 어느 쪽이 옛 단위의 후신인지 못 정한다 — 안 맺고 신규로 세어 막는다."""
        with contextlib.ExitStack() as stack:
            twin = _deep_method("_ChatMixin") + "\n\nclass _Other:\n    def wide(self, a):\n        return a\n"
            report = self._moved_method(stack, "_Other", twin)
            self.assertEqual(
                sorted(f"{f.rule} {f.unit}" for f in report.blocking),
                [
                    "unit-branchy _ChatMixin.wide",
                    "unit-deep _ChatMixin.wide",
                    "unit-oversize _ChatMixin.wide",
                ],
            )

    def test_a_copy_beside_the_original_inherits_nothing(self):
        """옛 파일이 그대로 있으면 그건 이동이 아니라 신설이다 — 베껴 온 부채는 이번 변경 책임이다."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack)
            self._write(root, "pkg/other.py", INHERITED)
            report = craft.judge(root, ["pkg/other.py"])
            self.assertEqual(
                sorted(f.rule for f in report.blocking), ["unclosed-acquire", "unit-branchy", "unit-oversize"]
            )
            self.assertEqual(report.moved, ())

    def test_an_unrelated_new_file_does_not_adopt_a_deleted_baseline(self):
        """삭제와 신설이 같은 변경에 있어도, 닮지 않았으면 짝이 아니다 (문턱은 git 과 같은 50%)."""
        with contextlib.ExitStack() as stack:
            root = self._base(stack)
            os.unlink(os.path.join(root, "pkg/rules.py"))
            self._write(root, "pkg/other.py", UNRELATED)
            report = craft.judge(root, ["pkg/other.py"])
            self.assertEqual(sorted(f.rule for f in report.blocking), ["unit-branchy", "unit-oversize"])
            self.assertEqual(report.moved, ())


class BudgetTableTest(_GitTree, unittest.TestCase):
    """문턱은 저장소가 정하고(`[tool.asgard.craft-budget]`), 게이트와 계측은 **같은 표**를 읽는다.

    두 번째 시험이 사례가 아니라 불변식인 이유: 한쪽만 켜지면 `asgard health` 가 세는 수와
    `asgard craft` 가 막는 자리가 서로를 설명하지 못한다. 그 어긋남은 화면에 안 보이고, 보이는
    것은 "게이트가 이상하다"뿐이라 다음에 일어나는 일은 게이트를 끄는 것이다.
    """

    _MODULE = "def wide():\n" + "".join(f"    x{i} = {i}\n" for i in range(45))

    def _tree(self, stack, table: str) -> str:
        root = self._repo(stack)
        self._write(root, "pyproject.toml", table)
        self._commit(root)
        return root

    def test_a_repo_without_the_table_keeps_the_defaults(self):
        with contextlib.ExitStack() as stack:
            root = self._tree(stack, '[project]\nname = "probe"\n')
            self.assertEqual(health.budgets(root), health.Budgets(70, 4, 15))

    def test_a_declared_budget_moves_the_gate_and_the_meter_together(self):
        with contextlib.ExitStack() as stack:
            loose = self._tree(stack, '[project]\nname = "probe"\n')
            self._write(loose, "m.py", self._MODULE)
            self.assertEqual(health.scan(loose).big_units, 0, "45행은 기본 예산 70 아래다")
            self.assertEqual([f.rule for f in craft.judge(loose, ["m.py"]).blocking], [])

            tight = self._tree(stack, '[project]\nname = "probe"\n\n[tool.asgard.craft-budget]\nunit_lines = 40\n')
            self._write(tight, "m.py", self._MODULE)
            self.assertEqual(health.scan(tight).big_units, 1, "표를 좁혔는데 계측이 안 따라오면 추세가 거짓말을 한다")
            self.assertIn("unit-oversize", [f.rule for f in craft.judge(tight, ["m.py"]).blocking])

    def test_a_value_that_is_not_a_budget_falls_back(self):
        """bool·음수·문자열은 조용히 무시한다 — 잘못 적은 한 줄이 예산을 0 으로 만들면 이
        저장소의 모든 함수가 한꺼번에 위반이 된다 (`gate_baseline` 과 같은 계약)."""
        table = '[tool.asgard.craft-budget]\nunit_lines = true\ndepth = -1\nbranches = "15"\n'
        with contextlib.ExitStack() as stack:
            root = self._tree(stack, table)
            self.assertEqual(health.budgets(root), health.Budgets(70, 4, 15))


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
