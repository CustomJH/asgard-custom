"""요청 문장에서 스킬 고르기 — 트리거 매칭과 본문 예산."""

from __future__ import annotations

import functools
import os
import re

from ..skill_bank import resolve_learned
from .anchor import _delivered_md
from .builtin import _builtin_plugins, _builtin_resolver
from .bundles import bundled_plugins, installed_plugins
from .catalog import show_skill
from .frontmatter import _description, _file_skill, _implicit
from .manifest import _skill_md
from .policy import _assigned, _skill_policy

_PLUGIN_CAP = 6
_RESOLVED_BODY_BUDGET = 16_000


def _resolve_bundled(root: str, task: str, agent: str) -> list[tuple[str, str]]:
    policy = _skill_policy(root)
    hits: list[tuple[str, str]] = []
    for plugin in _builtin_plugins().values():
        resolver = _builtin_resolver(str(plugin.get("resolver") or ""))
        if resolver is None:
            continue
        defaults = tuple(plugin.get("agents") or ())
        selected = resolver(task)
        hits.extend((name, body) for name, body in selected if _assigned(name, agent, defaults, policy))
    return hits


_ASCII_TRIGGER = re.compile(r"^[a-z0-9][a-z0-9 ._+-]*$")
_TRIGGER_TAIL = r"(?:s|es|ing|ed|er|ers)?"


@functools.lru_cache(maxsize=1024)
def _trigger_pattern(trigger: str) -> re.Pattern[str] | None:
    """라틴 트리거의 낱말 경계 패턴 — 한글 등 비 ASCII 는 None (부분 문자열 그대로).

    뒤 경계는 흔한 굴절만큼 늦춘다. 오탐을 죽이는 것은 **앞** 경계라(`password` ⊃ `word`,
    `cascade` ⊃ `cad`, `serialize` ⊃ `serial` 전부 앞에서 걸린다), 뒤를 넓혀도 오탐은 안
    돌아오고 미탐만 준다. `s?` 만 두었을 때 실측된 미탐: "the designer asked for a hero
    section"(designer), "batching the outbound webhook calls"(batch), "refactoring the domain
    modeling of orders"(refactor·modeling) — 셋 다 평범한 요청 표현이다 (26-08-04 교차검토)."""
    if not _ASCII_TRIGGER.match(trigger):
        return None
    return re.compile(rf"(?<![a-z0-9]){re.escape(trigger)}{_TRIGGER_TAIL}(?![a-z0-9])")


def _trigger_hits(trigger: str, task: str) -> bool:
    """이 트리거가 요청에 실제로 나오는가 — 라틴 트리거는 낱말 경계로 본다.

    부분 문자열로 보던 동안 짧은 영어 트리거가 남의 낱말 안쪽에 붙어 관계없는 스킬 본문을
    끌어왔다 (26-08-04 실측: `password` ⊃ `word` 로 office 스킬, `cascade` ⊃ `cad` 로 CAD
    스킬, `serialize` ⊃ `serial` 로 프로토콜 스킬. 오발 10건 84,941 B). 같은 병을 역할
    프롬프트 쪽은 이미 `templates/worker.py` 의 `_WORD_RE` 로 고쳐 뒀는데 플러그인 경로만
    안 받았다.

    뒤 경계를 한 글자 늦춘다(`s?`). 영어 복수형이 이 트리거 집합의 가장 흔한 굴절이라, 딱
    붙여 끊으면 `endpoints`·`tickets`·`templates`·`migrations` 가 전부 미탐이 된다 (실측:
    진짜 매칭 8/8 → 2/8). 오발 쪽은 앞 경계에서 이미 걸러지므로 `s?` 가 되살리지 않는다.

    한글 트리거는 부분 문자열 그대로 둔다 — 조사와 활용이 붙는 교착어라 낱말 경계가 없다."""
    pattern = _trigger_pattern(trigger)
    return bool(pattern.search(task)) if pattern else trigger in task


def _resolve_file_plugins(root: str, task: str, agent: str, sources: dict[str, dict]) -> list[tuple[str, str]]:
    task = task.lower()
    hits: list[tuple[int, str, str]] = []
    policy = _skill_policy(root)
    for plugin in sources.values():
        for name in plugin["skills"]:
            text = _skill_md(plugin, name)
            parsed = _file_skill(text)
            if not parsed:
                continue
            if not plugin["routing"][name]["implicit"]:
                continue
            _, body = parsed
            route = plugin["routing"][name]
            defaults = tuple(route["defaults"])
            compatible = tuple(route["agents"])
            if agent not in compatible and "any" not in compatible:
                continue
            if not _assigned(name, agent, defaults, policy):
                continue
            matched = sum(1 for trigger in route["triggers"] if _trigger_hits(trigger, task))
            if matched:
                delivered = _file_skill(_delivered_md(root, plugin, name))
                hits.append((-matched, name, delivered[1] if delivered else body))
    hits.sort()
    return [(name, body) for _, name, body in hits[:_PLUGIN_CAP]]


def resolve_installed(task: str, agent: str, root: str | None = None) -> list[tuple[str, str]]:
    return _resolve_file_plugins(root or os.getcwd(), task, agent, installed_plugins())


def resolve_skills(root: str, task: str, agent: str, *, include_learned: bool = True) -> list[tuple[str, str]]:
    """Legacy explicit resolver; automatic runtimes use metadata discovery plus on-demand load."""
    if agent in ("verifier", "loki"):
        return []
    hits = [
        *_resolve_bundled(root, task, agent),
        *_resolve_file_plugins(root, task, agent, bundled_plugins()),
        *(resolve_learned(root, task, agent) if include_learned else []),
        *_resolve_file_plugins(root, task, agent, installed_plugins()),
    ]
    disabled, _, unassigned = _skill_policy(root)
    seen: set[str] = set()
    selected: list[tuple[str, str]] = []
    used = 0
    for name, body in hits:
        if name in disabled or name in unassigned.get(agent, set()) or name in seen:
            continue
        text = show_skill(root, name) or ""
        if not _implicit(text):
            continue
        seen.add(name)
        if name.endswith("-deferred"):
            selected.append((name, body))
            continue
        if used + len(body) > _RESOLVED_BODY_BUDGET:
            description = _description(text)[:140] if text.startswith("---") else ""
            selected.append(
                (
                    name,
                    "# Matched skill — lazy body\n\n"
                    f"`{name}` matched this task, but its full body exceeded the aggregate inline budget. "
                    "Before making decisions in this domain, run the command below and apply its output.\n\n"
                    f"    asgard skills show {name}\n\n"
                    "If that body references a sibling file, load only the needed file with "
                    f"`asgard skills show {name} --resource <relative-path>`.\n\n"
                    f"Catalog description: {description}",
                )
            )
            continue
        selected.append((name, body))
        used += len(body)
    return selected
