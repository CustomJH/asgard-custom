"""주석 문체 판정 앵커 — 규칙마다 진양성 하나와 **오탐 가드 하나**를 짝으로 고정한다.

실행: uv run pytest tests/test_craft_note.py

test_craft.py와 같은 규율이다. 이 판정기는 사람이 쓴 문장을 잡으므로 오탐 비용이 특히 크다 —
멀쩡한 주석이 걸리기 시작하면 다음에 일어나는 일은 게이트를 끄는 것이다. 그래서 여기서 못 박는
음성 대조군은 전부 **이 저장소에 실제로 있던 문장**이다: 개발자가 쓰는 관용 표현(`죽는다`·
`샌다`), 어미가 우연히 은유와 겹치는 말(`깨진 파일`·`사라지는 쪽`), 백틱 안의 코드.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from asgard import craft, craft_note
from asgard.craft_rules import units as py_units


def _rules(source: str) -> set[str]:
    """규칙 이름 집합 — 줄 번호가 아니라 "무엇을 잡았나"로 고정한다."""
    units = py_units(source)
    spans = list(units.values()) if units else []
    return {f.rule for f in craft_note.note_findings(source, "probe.py", spans, "python")}


class MetaphorTest(unittest.TestCase):
    def test_a_metaphor_predicate_is_caught(self):
        self.assertIn("note-metaphor", _rules("# 명시 옵션이 있으면 그쪽이 이긴다\nx = 1\n"))

    def test_every_dictionary_entry_fires(self):
        """표에 올렸는데 안 잡히는 항목이 없어야 한다 — 죽은 규칙은 계약을 거짓말로 만든다."""
        probes = {
            "이김": "# 나중 것이 이긴다",
            "섬": "# 임베더가 선다",
            "실림": "# 프롬프트에 실린다",
            "듦": "# 팀이 지은 이름을 든다",
            "먹힘": "# 두 번째 고장이 첫 번째에 먹힌다",
            "삶": "# 소유권은 사이드카에 산다",
            "나름": "# 저장소가 나른다",
            "문지기": "# 문지기는 loopback 한 곳",
            "사슬": "# 부모 사슬을 따라간다",
            "못박음": "# 경계를 선언으로 못 박아 준다",
            "값치름": "# 내려받기를 여기서 치른다",
            "걷어냄": "# 주석을 걷어낸 알맹이",
            "앉힘": "# 허구를 정본에 앉힌다",
            "자": "# 어휘와 코사인은 같은 자로 못 잰다",
            "한벌": "# 세 창이 한 벌을 나눠 쓴다",
        }
        for name, line in probes.items():
            with self.subTest(name):
                self.assertIn("note-metaphor", _rules(line + "\nx = 1\n"))

    def test_developer_idioms_are_not_caught(self):
        """`죽는다`·`샌다`는 사람이 실제로 쓰는 말이다. 이것을 잡으면 판정기가 꺼진다."""
        for line in ("# 명령 전체가 죽는다", "# 상한 밖으로 샌다", "# 컨텍스트가 터진다"):
            with self.subTest(line):
                self.assertEqual(_rules(line + "\nx = 1\n"), set())

    def test_passive_endings_are_not_mistaken_for_losing(self):
        """`깨진 파일`의 `진`은 어미지 승부가 아니다 (1차 교정에서 실제로 잡힌 오탐)."""
        for line in ("# 깨진 파일은 없음과 동일", "# 교훈이 사라지는 쪽이 기본값", "# exclude에 걸려 빠진 파일 수"):
            with self.subTest(line):
                self.assertEqual(_rules(line + "\nx = 1\n"), set())

    def test_code_spans_are_not_judged(self):
        """백틱 안은 글쓴이가 말을 고를 수 있는 자리가 아니다."""
        self.assertEqual(_rules("# `한 벌`이라는 옛 표현을 `sync`가 지운다\nx = 1\n"), set())

    def test_english_comments_are_not_judged(self):
        self.assertEqual(_rules("# the later declaration wins over the earlier one\nx = 1\n"), set())


class JargonTest(unittest.TestCase):
    def test_a_coined_word_is_caught(self):
        self.assertIn("note-jargon", _rules("# 접지 점수가 낮으면 기각\nx = 1\n"))

    def test_the_verb_that_looks_like_it_is_not_caught(self):
        """`접지 않는다`는 접다의 활용형이다 — 글자만 같다 (quest_log.py에서 실제로 걸렸다)."""
        self.assertEqual(_rules("# 저장소 안 실행 파일일 수 있다 — 이름으로 접지 않는다\nx = 1\n"), set())

    def test_the_standard_word_that_starts_with_a_coinage_is_not_caught(self):
        """`불요불급`은 사전에 있는 말이다. 판정기가 이것을 잡으면 수리 표(craft_fix)는 앞보기로
        손대지 않으므로 고칠 방법이 없는 판정이 남는다 — 두 표는 같은 낱말을 같게 봐야 한다."""
        self.assertEqual(_rules("# 불요불급한 재판정을 막는다\nx = 1\n"), set())
        self.assertIn("note-jargon", _rules("# 불요한 재판정을 막는다\nx = 1\n"))


class DocstringTest(unittest.TestCase):
    def test_docstrings_are_judged_too(self):
        self.assertIn("note-metaphor", _rules('def f():\n    """텍스트 한 벌을 읽는다."""\n'))

    def test_the_owning_function_is_named(self):
        """판정에 함수 이름이 붙어야 사람이 어디를 고칠지 안다."""
        source = "def outer():\n    # 그쪽이 이긴다\n    return 1\n"
        units = py_units(source)
        assert units is not None
        found = craft_note.note_findings(source, "probe.py", list(units.values()), "python")
        self.assertEqual([f.unit for f in found], ["outer"])


class ExtractionTest(unittest.TestCase):
    def test_consecutive_comment_lines_merge_into_one_note(self):
        """문장이 줄을 넘어가면 반쪽만 보고는 판정할 수 없다."""
        notes = craft_note.notes("# 앞줄에서 시작해\n# 다음 줄에서 이긴다\nx = 1\n", "python")
        self.assertEqual(len(notes), 1)
        self.assertIn("이긴다", notes[0].text)

    def test_a_string_containing_slashes_is_not_read_as_a_comment(self):
        """중괄호 계열 추출 — 문자열 안의 `//`를 주석으로 읽으면 판정 좌표가 통째로 어긋난다."""
        notes = craft_note.notes('const u = "https://a.example/b"; // 뒤가 이긴다\n', "ts")
        self.assertEqual([n.text for n in notes], ["뒤가 이긴다"])

    def test_unparsable_source_is_silent(self):
        """못 읽은 것을 읽은 척하지 않는다 — craft_lex와 같은 계약."""
        self.assertEqual(craft_note.notes("def (((\n", "python"), [])


class RatchetTest(unittest.TestCase):
    """물려받은 주석은 이번 변경의 책임이 아니다 — craft 래칫이 주석에도 걸리는지."""

    def _repo(self, base: str, current: str) -> craft.Report:
        root = tempfile.mkdtemp()
        run = lambda *a: subprocess.run(a, cwd=root, capture_output=True, check=True)  # noqa: E731
        run("git", "init", "-q")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        path = os.path.join(root, "probe.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(base)
        run("git", "add", "probe.py")
        run("git", "commit", "-qm", "base")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(current)
        return craft.judge(root, ["probe.py"], "HEAD")

    def test_an_inherited_metaphor_does_not_block(self):
        body = "# 그쪽이 이긴다\nx = 1\n"
        report = self._repo(body, body + "y = 2\n")
        self.assertEqual([f.rule for f in report.findings if f.rule.startswith("note-")], [])

    def test_a_newly_added_metaphor_blocks(self):
        report = self._repo("x = 1\n", "# 그쪽이 이긴다\nx = 1\n")
        self.assertIn("note-metaphor", {f.rule for f in report.blocking})


class ContractTest(unittest.TestCase):
    """계약 본문 — 규칙이 빠지면 판정기만 남고 프롬프트 쪽이 침묵한다."""

    def test_the_canon_states_the_grounding_principle(self):
        from asgard.templates.comments import COMMENT_CANON

        plain = COMMENT_CANON.replace("**", "")
        self.assertIn("Say what the code cannot", plain)
        self.assertIn("Explain, do not liken", plain)
        self.assertIn("Every fact survives verbatim", plain)

    def test_the_agents_section_is_fenced_for_sync(self):
        """`asgard sync`가 통째로 갈아끼우는 블록이라 마커가 짝으로 있어야 한다."""
        from asgard.templates.comments import COMMENT_AGENTS_SECTION

        self.assertIn("<!-- >>> asgard:comments >>> -->", COMMENT_AGENTS_SECTION)
        self.assertIn("<!-- <<< asgard:comments <<< -->", COMMENT_AGENTS_SECTION)

    def test_agents_md_carries_the_section(self):
        from asgard.templates import agents_md

        self.assertIn("asgard:comments", agents_md("demo"))

    def test_the_repository_obeys_its_own_rule(self):
        """이 저장소의 주석이 이 판정기를 통과하는가 (26-08-01에 295건을 교정했다).

        규칙을 만든 저장소가 그 규칙을 안 지키면 다음 사람이 규칙을 안 믿는다."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "src" / "asgard"
        hits = []
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            source = path.read_text(encoding="utf-8")
            units = py_units(source)
            spans = list(units.values()) if units else []
            hits += craft_note.note_findings(source, str(path), spans, "python")
        self.assertEqual([f"{f.path}:{f.line} {f.detail}" for f in hits], [])


if __name__ == "__main__":
    unittest.main()
