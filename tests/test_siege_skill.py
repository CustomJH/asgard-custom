"""asgard-siege 스킬 — 계약 본문이 실제 CLI 와 같은 것을 말하는가.

실행: uv run pytest tests/test_siege_skill.py

이 파일이 있는 까닭은 드리프트다. `asgard siege` 는 동사 25종이고, 그것을 부르는 법이 적힌
자리는 스킬 본문 하나다. 본문이 CLI 와 어긋나면 아무 시험도 빨개지지 않은 채 호스트 모드의
에이전트만 틀린 명령을 친다 — 그쪽은 본문을 믿고 `--help` 를 안 보기 때문이다.

그래서 여기서는 본문을 문서로 안 읽고 **명세로 읽는다**: 본문에 적힌 동사와 플래그를 전부
뽑아 typer 가 실제로 등록한 것과 맞춘다. 양방향이다 — 없는 플래그를 적어도, 있는 동사를
빠뜨려도 빨개진다.

나머지 셋은 배선이다: 카탈로그에 있는가, 네 모드 스캐폴드에 나가는가, 조율 어휘에만 붙는가.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from typer.main import get_command  # noqa: E402

from asgard import cli  # noqa: E402
from asgard.commands.setup import plan_files  # noqa: E402
from asgard.skill_registry import _builtin_plugins, show_skill, skills  # noqa: E402
from asgard.templates.siege import SIEGE_SKILL_MD, resolve_siege_skills  # noqa: E402

SKILL = "asgard-siege"

# 본문의 명령 줄 — `asgard siege <verb> …` 로 시작하는 것만 본다. 산문 안의 백틱 인용
# (`siege show <run>`)은 인자를 다 안 적으므로 명세로 읽으면 안 된다.
_USAGE_RE = re.compile(r"^\s{4}asgard siege(?: (?P<verb>[a-z][a-z-]*))?(?P<rest>.*)$", re.M)
_FLAG_RE = re.compile(r"--[a-z][a-z-]*")


def _subcommands(command: Any) -> dict[str, Any]:
    """하위 명령 표 — 표를 안 드는 명령이면 그 자체가 시험의 전제 붕괴다.

    click 타입을 안 적는 이유는 typer 가 click 을 벤더링해서다 — 여기서 어느 쪽 `Group` 을
    적어도 다른 설치에서는 어긋난다. 재는 것은 클래스가 아니라 표가 있느냐다."""
    assert hasattr(command, "commands"), f"하위 명령을 안 드는 명령이다: {command.name}"
    return command.commands


def _siege_command() -> Any:
    return _subcommands(get_command(cli.app))["siege"]


def _siege_group():
    """typer 가 등록한 `siege` 하위 명령 표 — 스킬이 맞춰야 할 정본.

    숨긴 동사는 뺀다. `note`·`unnote`·`mirror` 는 훅이 장부에 한 줄 적으려고 부르는 문이고
    (배포 인터프리터에서 `asgard` 를 임포트할 수 없어 프로세스로 부른다), 사람이나 에이전트가
    치는 표면이 아니다 — 스킬 본문에 적으면 코디네이터가 수명 계약을 손으로 흉내 내게 된다.
    """
    return {name: command for name, command in _subcommands(_siege_command()).items() if not command.hidden}


def _documented() -> dict[str, set[str]]:
    """스킬 본문이 적어 둔 동사 → 플래그 집합. 동사 없는 줄(`asgard siege [--json]`)은 빈 이름."""
    found: dict[str, set[str]] = {}
    for match in _USAGE_RE.finditer(SIEGE_SKILL_MD):
        verb = match.group("verb") or ""
        # 줄이 이어지면 다음 줄의 들여쓴 인자도 같은 명령의 것이다.
        rest = match.group("rest")
        found.setdefault(verb, set()).update(_FLAG_RE.findall(rest))
    return found


def _continuation_flags() -> dict[str, set[str]]:
    """이어진 줄까지 포함한 동사별 플래그 — 본문은 80칸에서 접히므로 첫 줄만 보면 샌다."""
    flags: dict[str, set[str]] = {}
    current = ""
    for line in SIEGE_SKILL_MD.splitlines():
        match = _USAGE_RE.match(line)
        if match:
            current = match.group("verb") or ""
            flags.setdefault(current, set()).update(_FLAG_RE.findall(match.group("rest")))
            continue
        if current and line.startswith(" " * 8):
            flags[current].update(_FLAG_RE.findall(line))
            continue
        if not line.strip():
            continue
        current = ""
    return flags


class SkillMatchesCli(unittest.TestCase):
    """본문과 CLI 를 한자리에서 붙든다 — 한쪽만 바뀌면 여기서 걸린다."""

    def test_every_documented_verb_exists(self) -> None:
        registered = set(_siege_group())
        for verb in _documented():
            if not verb:
                continue
            self.assertIn(verb, registered, f"스킬이 없는 동사를 적었어요: siege {verb}")

    def test_every_verb_is_documented(self) -> None:
        documented = set(_documented())
        for verb in _siege_group():
            self.assertIn(verb, documented, f"스킬 본문에 안 적힌 동사예요: siege {verb}")

    def test_every_documented_flag_exists(self) -> None:
        group = _siege_group()
        for verb, flags in _continuation_flags().items():
            command = group[verb] if verb else _siege_command()
            real = {opt for param in command.params for opt in param.opts if opt.startswith("--")}
            for flag in flags:
                self.assertIn(flag, real, f"siege {verb} 에 없는 플래그를 적었어요: {flag}")

    def test_completion_report_settles_a_dispatch(self) -> None:
        """`done` 이 받는 것은 dispatch id 다 — 이 표면에서 가장 자주 틀리는 자리."""
        argument = [param for param in _siege_group()["done"].params if not param.opts[0].startswith("--")]
        self.assertEqual(argument[0].name, "dispatch_id")
        self.assertIn("`siege done` takes a `<dispatch_id>`", SIEGE_SKILL_MD)


class Wiring(unittest.TestCase):
    def test_catalog_carries_the_skill(self) -> None:
        names = {row["name"] for row in skills(os.getcwd())}
        self.assertIn(SKILL, names)

    def test_body_is_served_by_the_registry(self) -> None:
        """얇은 어댑터가 `asgard skills show` 로 정본을 부른다 — 그 문이 열려 있는가."""
        body = show_skill(os.getcwd(), SKILL) or ""
        self.assertIn("the dispatch ledger", body)

    def test_assigned_to_the_agents_that_open_dispatches(self) -> None:
        self.assertEqual(_builtin_plugins()["siege"]["agents"], ("worker", "thor-lead"))

    def test_scaffolded_into_both_skill_scopes(self) -> None:
        """Claude Code 는 `.claude/skills/`, Cursor·Codex 는 공용 `.agents/skills/`."""
        files, _label = plan_files(False, False, False, os.path.join("/tmp", "siege-scaffold"))
        paths = {path for path, _body in files}
        for scope in (".claude", ".agents"):
            self.assertIn(
                os.path.join("/tmp", "siege-scaffold", scope, "skills", SKILL, "SKILL.md"),
                paths,
            )


class Resolver(unittest.TestCase):
    """조율 어휘에만 붙는가 — 25종짜리 본문이 단독 작업에 붙으면 값 없이 컨텍스트만 먹는다."""

    def test_coordination_matches(self) -> None:
        for task in (
            "coordinate three parallel workers on a task graph",
            "병렬 유닛 셋을 배차하고 결과를 기다려 줘",
            "escalate to the coordinator when a unit is blocked",
            "hold a decision gate before we ship",
        ):
            self.assertTrue(resolve_siege_skills(task), task)

    def test_solo_work_does_not_match(self) -> None:
        for task in (
            "fix the event dispatcher bug in the websocket layer",
            "add a regression test for the parser",
            "rename this variable and update its callers",
            "make the login page prettier",
        ):
            self.assertFalse(resolve_siege_skills(task), task)

    def test_resolved_body_drops_the_frontmatter(self) -> None:
        """resolve 는 본문만 준다 — 프론트매터가 섞이면 주입된 컨텍스트가 YAML 로 시작한다."""
        ((_name, body),) = resolve_siege_skills("coordinate parallel workers")
        self.assertFalse(body.startswith("---"))
        self.assertTrue(body.startswith("# asgard-siege"))


if __name__ == "__main__":
    unittest.main()
