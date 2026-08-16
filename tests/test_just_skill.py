"""asgard-just 스킬 — 본문이 실제 CLI·엔진과 같은 것을 말하는가.

실행: uv run pytest tests/test_just_skill.py

드리프트가 조용한 자리라 시험이 있다. 본문이 `asgard just sync` 를 적어 두는데 CLI 쪽 이름이
바뀌면 아무것도 빨개지지 않은 채 호스트 모드의 에이전트만 없는 명령을 친다 — 그쪽은 본문을
믿고 `--help` 를 안 보기 때문이다. 표식 문자열도 같다: 본문이 안내하는 두 줄과 엔진이 실제로
쓰는 두 줄이 갈리면, 에이전트는 자기가 안 건드릴 자리를 손으로 고치게 된다.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from typer.main import get_command  # noqa: E402

from asgard import cli, justfile  # noqa: E402
from asgard.commands.setup import plan_files  # noqa: E402
from asgard.skill_registry import _builtin_plugins, show_skill, skills  # noqa: E402
from asgard.templates.just import JUST_SKILL_MD, resolve_just_skills  # noqa: E402

SKILL = "asgard-just"
_ASGARD_JUST_RE = re.compile(r"`asgard just ([a-z][a-z-]*)")


def _subcommands(command: Any) -> dict[str, Any]:
    """하위 명령 표 — 표를 안 드는 명령이면 그 자체가 시험의 전제 붕괴다.

    click 타입을 안 적는 이유는 typer 가 click 을 벤더링해서다 — 여기서 어느 쪽 `Group` 을
    적어도 다른 설치에서는 어긋난다 (tests/test_siege_skill.py 가 같은 이유로 같은 자리를 쓴다).
    재는 것은 클래스가 아니라 표가 있느냐다."""
    assert hasattr(command, "commands"), f"하위 명령을 안 드는 명령이다: {command.name}"
    return command.commands


def _cli_verbs() -> set[str]:
    group = _subcommands(get_command(cli.app))["just"]
    return {name for name, command in _subcommands(group).items() if not command.hidden}


class SkillMatchesCli(unittest.TestCase):
    def test_every_command_the_body_names_exists(self) -> None:
        registered = _cli_verbs()
        named = set(_ASGARD_JUST_RE.findall(JUST_SKILL_MD))
        self.assertTrue(named, "본문이 `asgard just …` 를 한 번도 안 적었어요")
        for verb in named:
            self.assertIn(verb, registered, f"스킬이 없는 명령을 적었어요: asgard just {verb}")

    def test_every_command_is_named_by_the_body(self) -> None:
        named = set(_ASGARD_JUST_RE.findall(JUST_SKILL_MD))
        for verb in _cli_verbs():
            self.assertIn(verb, named, f"스킬 본문에 안 적힌 명령이에요: asgard just {verb}")

    def test_the_markers_the_body_quotes_are_the_ones_the_engine_writes(self) -> None:
        self.assertIn(justfile.BEGIN, JUST_SKILL_MD)
        self.assertIn(justfile.END, JUST_SKILL_MD)

    def test_the_one_line_one_shell_rule_is_stated(self) -> None:
        """모르면 반드시 밟는 자리 — `cd` 를 자기 줄에 두면 다음 줄에서 사라진다."""
        self.assertIn("One line is one shell", JUST_SKILL_MD)

    def test_the_body_says_adoption_is_the_repository_choice(self) -> None:
        """본문이 "기본이다"로 읽히면 에이전트가 Justfile 없는 저장소에 하나 만들어 준다."""
        self.assertIn("asgard just init", JUST_SKILL_MD)
        self.assertIn("no Justfile means it was not, and that is not a gap to close", JUST_SKILL_MD)


class Wiring(unittest.TestCase):
    def test_catalog_carries_the_skill(self) -> None:
        self.assertIn(SKILL, {row["name"] for row in skills(os.getcwd())})

    def test_body_is_served_by_the_registry(self) -> None:
        self.assertIn("the run surface", show_skill(os.getcwd(), SKILL) or "")

    def test_assigned_to_every_role_that_runs_a_command(self) -> None:
        self.assertEqual(_builtin_plugins()["just"]["agents"], ("worker", "thor", "thor-lead", "eitri", "freyja"))

    def test_scaffolded_into_both_skill_scopes(self) -> None:
        files, _label = plan_files(False, False, False, os.path.join("/tmp", "just-scaffold"))
        paths = {path for path, _body in files}
        for scope in (".claude", ".agents"):
            self.assertIn(os.path.join("/tmp", "just-scaffold", scope, "skills", SKILL, "SKILL.md"), paths)


class Resolver(unittest.TestCase):
    def test_run_surface_vocabulary_matches(self) -> None:
        for task in (
            "add a deploy recipe to the justfile",
            "justfile 에 마이그레이션 레시피 하나 추가해 줘",
            "이 저장소의 실행 명령을 정리해 줘",
            "where do the run commands live in this repo",
            "port the makefile targets over",
            "why does `just test` fail here",
            "just test 가 왜 실패하지",
        ):
            self.assertTrue(resolve_just_skills(task), task)

    def test_the_english_adverb_does_not_match(self) -> None:
        """`just <낱말>` 은 영어 명령문 그 자체라, 뒤가 이름인지 동사인지 문장만 봐서 못 가른다.

        첫 판은 레시피 이름 목록(`just test|build|check|…`)으로 잡으려 했고 그 열둘 중 여덟이
        영어에서 그냥 동사였다. 아래 여덟 문장이 그때 실제로 발화한 것들이라 그대로 둔다 —
        사례를 고르는 쪽이 규칙을 쓴 쪽이면 시험은 자기를 재게 되고, 첫 판의 네 사례가 정확히
        그래서 이 결함을 통과시켰다."""
        for task in (
            "just check the logs for the error",
            "just test it and see",
            "just build a new one from scratch",
            "just list the files in src",
            "just format this docstring",
            "just serve the page locally",
            "just deploy whatever is on main",
            "just migrate the config key",
            "add a recipe card to the cooking app",
            "just fix the typo in the readme",
            "this is just a rename, no behaviour change",
            "make the login page prettier",
        ):
            self.assertFalse(resolve_just_skills(task), task)

    def test_resolved_body_drops_the_frontmatter(self) -> None:
        ((_name, body),) = resolve_just_skills("add a deploy recipe to the justfile")
        self.assertFalse(body.startswith("---"))
        self.assertTrue(body.startswith("# asgard-just"))


if __name__ == "__main__":
    unittest.main()
