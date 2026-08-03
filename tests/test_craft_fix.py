"""수리 레인 앵커 — 고친 것마다 **증거**를, 안 고친 것마다 **이유**를 고정한다.

실행: uv run pytest tests/test_craft_fix.py

test_craft_note.py 와 규율이 다르다. 판정기의 실패 모드는 오탐이고 무시하면 그만이지만, 수리기의
실패 모드는 **오수리**이고 그것은 파일에 남는다. 그래서 여기서 고정하는 것은 "고치는가"보다
"안 고치는가"다: 코드 바이트를 건드리면 거부, 사실이 빠지면 거부, 판정이 안 줄면 거부,
표준 표현이 둘이면 거부. 예행은 아무것도 쓰지 않고, CRLF 와 끝줄바꿈은 그대로 돌아온다.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from unittest import mock

from asgard import craft_fix, craft_note
from asgard.commands.craft import run_craft
from asgard.hooks import craft_gate


def _rules(source: str, lang: str = "python") -> list[str]:
    return [f.rule for f in craft_note.note_findings(source, "probe.py", [], lang)]


def _repair(source: str, lang: str = "python"):
    return craft_fix.repair(source, "probe.py", lang)


class RepairTest(unittest.TestCase):
    def test_a_jargon_hit_is_repaired_and_every_fact_survives(self):
        src = "# 무매칭이면 26-07-29 실측대로 `craft.py:12` 를 다시 본다 (https://a.b/c)\nx = 1\n"
        out, applied, _ = _repair(src)
        self.assertIn("일치가 없으면", out)  # 활용형이 먼저다 — `일치 없음이면` 은 계약표에 없는 말이다
        self.assertNotIn("무매칭", out)
        for fact in ("26-07-29", "`craft.py:12`", "https://a.b/c"):
            self.assertIn(fact, out, "다시 쓰기는 문체만 바꾼다 — 사실은 글자 그대로 남아야 한다")
        self.assertEqual([r.rule for r in applied], ["note-jargon"])
        self.assertEqual(applied[0].line, 1)

    def test_a_metaphor_with_more_than_one_standard_wording_is_refused_with_a_reason(self):
        """`사슬`은 커밋 274c6c2에서 체인·연쇄·연결 셋으로 갈렸다 — 고르는 것은 사람의 판단이다."""
        src = "# 부모 사슬을 따라간다\nx = 1\n"
        out, applied, refused = _repair(src)
        self.assertEqual(out, src)
        self.assertEqual(applied, [])
        self.assertEqual([r.rule for r in refused], ["note-metaphor"])
        self.assertEqual(refused[0].why, "표준 서술이 여럿이라 어느 쪽인지는 사람이 골라야 해요")
        self.assertTrue(refused[0].detail, "이유 없는 거부는 침묵과 같다")

    def test_the_repaired_text_has_strictly_fewer_note_findings(self):
        """G3 — 고친 뒤 판정이 줄지 않으면 그것은 수리가 아니다."""
        src = "# 명시 옵션이 있으면 그쪽이 이긴다\ndef f():\n    '''저장소가 나른다.'''\n    return 1\n"
        before = _rules(src)
        out, applied, _ = _repair(src)
        after = _rules(out)
        self.assertEqual(len(before), 2)
        self.assertLess(len(after), len(before))
        self.assertEqual(after, [])
        self.assertEqual(len(applied), 2)

    def test_a_docstring_is_repaired_in_place_and_the_code_around_it_is_untouched(self):
        src = 'def f(a):\n    """프롬프트에 실린다.\n\n    두 번째 문단."""\n    return a + 1\n'
        out, applied, _ = _repair(src)
        self.assertIn("프롬프트에 들어간다", out)
        self.assertIn("    return a + 1\n", out)
        self.assertEqual([r.line for r in applied], [2])

    def test_a_repair_that_would_change_code_is_refused(self):
        """G1 — 표가 주석 밖으로 새면 그 수리는 통째로 버린다. 표를 갈아 끼워 실제로 확인한다."""
        broken = (("note-metaphor", re.compile("이긴다"), '우선한다"""\nimport os\n"""'),)
        src = 'def f():\n    """그쪽이 이긴다."""\n    return 1\n'
        with mock.patch.object(craft_fix, "_FIX", broken):
            out, applied, refused = _repair(src)
        self.assertEqual(out, src, "코드가 함께 바뀌는 수리는 적용되면 안 된다")
        self.assertEqual(applied, [])
        self.assertEqual([r.why for r in refused], ["고치면 주석 밖 바이트까지 함께 바뀌어요"])

    def test_a_brace_repair_that_escapes_the_comment_is_refused(self):
        broken = (("note-metaphor", re.compile("이긴다"), "우선한다*/ evil();/*"),)
        src = "/* 그쪽이 이긴다. */\nconst a = 1;\n"
        with mock.patch.object(craft_fix, "_FIX", broken):
            out, applied, refused = _repair(src, "ts")
        self.assertEqual(out, src)
        self.assertEqual(applied, [])
        self.assertEqual([r.why for r in refused], ["고치면 주석 밖 바이트까지 함께 바뀌어요"])

    def test_a_repair_that_drops_a_fact_is_refused(self):
        """G2 — 문체만 바꾼다. 측정값·날짜·경로가 하나라도 사라지면 그 수리는 주석을 파괴한다."""
        broken = (("note-metaphor", re.compile("이긴다"), "우선한다"),)
        src = "# 26-07-29 이긴다\nx = 1\n"
        with mock.patch.object(craft_fix, "_FACT", re.compile(r"이긴다|\d+")):
            with mock.patch.object(craft_fix, "_FIX", broken):
                out, applied, refused = _repair(src)
        self.assertEqual(out, src)
        self.assertEqual(applied, [])
        self.assertEqual([r.why for r in refused], ["사실이 그대로 남지 않아요 — 다시 쓰기는 문체만 바꿔요"])

    def test_a_hit_masked_by_an_unrepairable_one_is_refused_not_half_fixed(self):
        """한 주석에 고칠 수 있는 것과 없는 것이 같이 있으면 그 주석은 손대지 않는다."""
        src = "# 재시작 불요. 무매칭이면 비의존으로 둔다.\nx = 1\n"
        out, applied, refused = _repair(src)
        self.assertEqual(out, src)
        self.assertEqual(applied, [])
        self.assertEqual(
            [r.why for r in refused], ["고쳐도 판정이 줄지 않아요 — 같은 주석에 손댈 수 없는 판정이 함께 있어요"]
        )

    def test_a_coinage_whose_standard_word_is_a_predicate_is_refused_in_a_noun_slot(self):
        src = "# 비의존 계층이다\nx = 1\n"
        out, _applied, refused = _repair(src)
        self.assertEqual(out, src)
        self.assertEqual(
            [r.why for r in refused],
            ["표준어가 서술문이라 명사 자리에 그대로 못 넣어요 — 문장을 다시 세워야 해요"],
        )


class TableTest(unittest.TestCase):
    """표에 올린 항목마다 진양성 하나. 판정기가 안 잡는 말을 고치면 판정을 못 줄여 되돌려진다."""

    PROBES = {
        "이긴다": "# 나중 것이 이긴다",
        "이긴 (?=(?:쪽|것|편))": "# 이긴 쪽을 쓴다",
        "나른다": "# 저장소가 나른다",
        "싣는다": "# 보고에 그대로 싣는다",
        "실린다": "# 보고에 그대로 실린다",
        "싣지": "# 한국어 출력을 싣지 못한다",
        "실으면": "# 상태에 실으면 표면이 말한다",
        "걷어낸다": "# 주석을 걷어낸다",
        "걷어낸": "# 주석을 걷어낸 알맹이",
        "걷어내(?=[는지고면])": "# 주석을 걷어내는 층",
        "(?<=[을를] )든다": "# 팀이 지은 이름을 든다",
        "(?<=[에가] )산다": "# 소유권은 사이드카에 산다",
        r"불요(?!불급)": "# 재시작 불요다",
        "무매칭이면": "# 무매칭이면 넘긴다",
        "무매칭": "# 무매칭 항목은 건너뛴다",
        "비의존이다": "# 이 층은 비의존이다",
        "무임포트이다": "# 이 훅은 무임포트이다",
        "무임포트다": "# 이 훅은 무임포트다",
    }

    def test_every_entry_has_a_probe(self):
        self.assertEqual(sorted(p.pattern for _r, p, _a in craft_fix._FIX), sorted(self.PROBES))

    def test_every_entry_removes_a_finding_the_judge_actually_raised(self):
        for pattern, probe in self.PROBES.items():
            with self.subTest(pattern):
                src = probe + "\nx = 1\n"
                self.assertTrue(_rules(src), "판정기가 안 잡는 말은 표에 올리지 않는다")
                out, applied, _refused = _repair(src)
                self.assertNotEqual(out, src)
                self.assertEqual(_rules(out), [])
                self.assertEqual(len(applied), 1)


class NotACommentTest(unittest.TestCase):
    """문자열 안의 주석 기호는 주석이 아니다 — 여기서 틀리면 수리기가 코드를 고친다."""

    def test_a_python_string_holding_a_hash_comment_is_not_touched(self):
        src = 'BANNER = "# 명시 옵션이 있으면 그쪽이 이긴다"\n'
        out, applied, _ = _repair(src)
        self.assertEqual(out, src)
        self.assertEqual(applied, [])

    def test_a_brace_string_holding_a_line_comment_is_not_touched(self):
        src = '// 명시 옵션이 있으면 그쪽이 이긴다\nconst s = "// 저장소가 나른다";\n'
        out, applied, _ = _repair(src, "ts")
        self.assertIn("그쪽이 우선한다", out)
        self.assertIn('"// 저장소가 나른다"', out, "문자열 안의 `//`를 주석으로 읽으면 코드가 바뀐다")
        self.assertEqual([r.line for r in applied], [1])

    def test_a_non_docstring_string_is_not_a_note(self):
        src = 'def f():\n    return "그쪽이 이긴다"\n'
        out, applied, _ = _repair(src)
        self.assertEqual(out, src)
        self.assertEqual(applied, [])


class EncodingTest(unittest.TestCase):
    def test_crlf_and_a_missing_final_newline_round_trip(self):
        src = "# 그쪽이 이긴다\r\nx = 1\r\n# 저장소가 나른다"
        out, applied, _ = _repair(src)
        self.assertEqual(out, "# 그쪽이 우선한다\r\nx = 1\r\n# 저장소가 전달한다")
        self.assertEqual(out.count("\r\n"), src.count("\r\n"))
        self.assertFalse(out.endswith("\n"), "없던 끝줄바꿈을 만들면 주석 밖 바이트가 바뀐 것이다")
        self.assertEqual([r.line for r in applied], [1, 3])
        self.assertNotIn("\r", applied[0].before, "화면에 실을 줄에는 줄바꿈 문자가 없어야 한다")

    def test_the_file_on_disk_keeps_its_line_endings(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "m.py")
            with open(path, "wb") as handle:
                handle.write("# 그쪽이 이긴다\r\nx = 1\r\n".encode())
            craft_fix.apply(root, ["m.py"], write=True)
            with open(path, "rb") as handle:
                raw = handle.read()
        self.assertEqual(raw, "# 그쪽이 우선한다\r\nx = 1\r\n".encode())


class ApplyTest(unittest.TestCase):
    def _tree(self, stack, files: dict[str, str]) -> str:
        root = stack.enter_context(tempfile.TemporaryDirectory())
        for rel, body in files.items():
            with open(os.path.join(root, rel), "w", encoding="utf-8") as handle:
                handle.write(body)
        return root

    def test_dry_run_computes_everything_and_writes_nothing(self):
        body = "# 명시 옵션이 있으면 그쪽이 이긴다\nx = 1\n"
        with contextlib.ExitStack() as stack:
            root = self._tree(stack, {"m.py": body})
            report = craft_fix.apply(root, ["m.py"], write=False)
            with open(os.path.join(root, "m.py"), encoding="utf-8") as handle:
                after = handle.read()
        self.assertEqual(after, body, "예행이 파일을 건드리면 그것은 예행이 아니다")
        self.assertEqual(len(report.applied), 1)
        self.assertEqual(report.files, ("m.py",))

    def test_write_actually_repairs_the_file(self):
        with contextlib.ExitStack() as stack:
            root = self._tree(stack, {"m.py": "# 그쪽이 이긴다\nx = 1\n"})
            report = craft_fix.apply(root, ["m.py"], write=True)
            with open(os.path.join(root, "m.py"), encoding="utf-8") as handle:
                after = handle.read()
        self.assertEqual(after, "# 그쪽이 우선한다\nx = 1\n")
        self.assertEqual(report.files, ("m.py",))
        self.assertEqual(_rules(after), [])

    def test_code_shape_rules_are_always_refusals_and_carry_the_prescription(self):
        """함수를 스스로 다시 짜는 판정기는 보고만 하는 판정기보다 나쁘다."""
        leaky = "import json\n\n\ndef f(p):\n    return json.load(open(p))\n"
        with contextlib.ExitStack() as stack:
            root = self._tree(stack, {"m.py": leaky})
            report = craft_fix.apply(root, ["m.py"], write=True)
            with open(os.path.join(root, "m.py"), encoding="utf-8") as handle:
                after = handle.read()
        self.assertEqual(after, leaky, "코드 형상은 자동으로 고치지 않는다")
        self.assertEqual(report.applied, ())
        self.assertEqual([r.rule for r in report.refused], ["unclosed-acquire"])
        self.assertTrue(report.refused[0].why, "처방 없는 거부는 재작업을 안내하지 못한다")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root 는 읽기 전용 파일도 쓴다")
    def test_a_file_that_cannot_be_written_is_reported_as_refused_not_applied(self):
        """못 쓴 것을 고친 것으로 세면 다음 판정과 보고가 어긋난다."""
        with contextlib.ExitStack() as stack:
            root = self._tree(stack, {"m.py": "# 그쪽이 이긴다\nx = 1\n"})
            os.chmod(os.path.join(root, "m.py"), 0o444)
            report = craft_fix.apply(root, ["m.py"], write=True)
            os.chmod(os.path.join(root, "m.py"), 0o644)
        self.assertEqual(report.applied, ())
        self.assertEqual(report.files, ())
        self.assertIn("파일을 다시 쓰지 못했어요 — 권한이나 잠금을 확인해 주세요", [r.why for r in report.refused])

    def test_a_file_the_judge_skips_is_never_rewritten(self):
        with contextlib.ExitStack() as stack:
            root = self._tree(stack, {"note.md": "# 그쪽이 이긴다\n"})
            report = craft_fix.apply(root, ["note.md"], write=True)
            with open(os.path.join(root, "note.md"), encoding="utf-8") as handle:
                after = handle.read()
        self.assertEqual(after, "# 그쪽이 이긴다\n")
        self.assertEqual(report.files, ())


class SurfaceTest(unittest.TestCase):
    def _run(self, root: str, **kwargs) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.chdir(root), contextlib.redirect_stdout(buf):
            code = run_craft(base="HEAD", paths=("m.py",), **kwargs)
        return code, buf.getvalue()

    def test_dry_run_without_fix_is_an_error(self):
        with tempfile.TemporaryDirectory() as root:
            code, _out = self._run(root, json_out=True, dry_run=True)
        self.assertEqual(code, 2, "고칠 것을 정하는 것이 --fix 다 — 없으면 예행할 대상이 없다")

    def test_json_gains_the_fix_key_only_when_asked(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "m.py"), "w", encoding="utf-8") as handle:
                handle.write("# 그쪽이 이긴다\nx = 1\n")
            plain = json.loads(self._run(root, json_out=True)[1])
            code, out = self._run(root, json_out=True, fix=True, dry_run=True)
        self.assertNotIn("fix", plain, "안 한 일을 0으로 적지 않는다")
        payload = json.loads(out)
        self.assertEqual(sorted(payload["fix"]), ["applied", "files", "refused", "remaining_blocking"])
        self.assertEqual(payload["fix"]["files"], ["m.py"])
        self.assertEqual(payload["fix"]["applied"][0]["rule"], "note-metaphor")
        self.assertEqual(code, payload["fix"]["remaining_blocking"] and 1 or 0)

    def test_the_exit_code_is_zero_once_the_repair_cleared_the_gate(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "m.py"), "w", encoding="utf-8") as handle:
                handle.write("# 그쪽이 이긴다\nx = 1\n")
            code, out = self._run(root, json_out=True, fix=True)
        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(payload["fix"]["remaining_blocking"], 0)
        self.assertEqual(payload["blocking"], [])

    def test_a_remaining_block_still_fails_after_a_repair(self):
        """ "5건 고침"이 "통과"로 읽히면 안 된다 — 남은 것이 있으면 종료 코드는 1이다."""
        body = "# 그쪽이 이긴다\n\n\ndef f(p):\n    return open(p).read()\n"
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "m.py"), "w", encoding="utf-8") as handle:
                handle.write(body)
            code, out = self._run(root, json_out=True, fix=True)
        payload = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(payload["fix"]["remaining_blocking"], 1)
        self.assertEqual(len(payload["fix"]["applied"]), 1)


class SeamTest(unittest.TestCase):
    """진짜 CLI 가 낸 `fix` 칸을 배포되는 훅의 판독기에 그대로 먹인다.

    test_craft_gate_e2e.py 는 스텁 CLI 로 훅의 처신을 고정하고 위의 SurfaceTest 는 payload 모양을
    고정하는데, 둘 다 초록인 채로 두 쪽의 칸 이름이 갈릴 수 있다. 그 한 자리를 여기서 막는다."""

    def _payload(self, root: str, body: str) -> dict:
        with open(os.path.join(root, "m.py"), "w", encoding="utf-8") as handle:
            handle.write(body)
        buf = io.StringIO()
        with contextlib.chdir(root), contextlib.redirect_stdout(buf):
            run_craft(base="HEAD", paths=("m.py",), json_out=True, fix=True)
        return json.loads(buf.getvalue())

    def test_the_hook_reads_the_repair_the_cli_actually_emits(self):
        with tempfile.TemporaryDirectory() as root:
            payload = self._payload(root, "# 그쪽이 이긴다\n\n\ndef f(p):\n    return open(p).read()\n")
        fix = payload["fix"]
        self.assertEqual(len(craft_gate._applied(fix)), 1)
        self.assertEqual(craft_gate._repaired_files(fix), ["m.py"])
        head = craft_gate._repair_head(fix)
        self.assertIn("rewrote 1 file(s) on disk: m.py", head)
        self.assertIn("re-read them", head)
        self.assertEqual(fix["remaining_blocking"], len(payload["blocking"]), "훅이 막는 수와 같아야 한다")

    def test_a_run_with_nothing_to_repair_leaves_the_hook_silent(self):
        with tempfile.TemporaryDirectory() as root:
            payload = self._payload(root, "# 그쪽이 우선한다\nx = 1\n")
        self.assertEqual(payload["fix"]["applied"], [])
        self.assertEqual(craft_gate._repair_head(payload["fix"]), "", "안 고쳤으면 할 말이 없다")


class SelfApplicationTest(unittest.TestCase):
    def test_the_repair_lane_obeys_the_contract_it_repairs(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in ("src/asgard/craft_fix.py", "src/asgard/commands/craft.py", "tests/test_craft_fix.py"):
            with self.subTest(rel), open(os.path.join(root, rel), encoding="utf-8") as handle:
                self.assertEqual(_rules(handle.read()), [], f"{rel} 이 자기 계약을 어긴다")


if __name__ == "__main__":
    unittest.main()
