"""카탈로그 — 목록·본문·자원을 역할 정책에 걸러 내보낸다."""

from __future__ import annotations

import os
import re
from pathlib import Path
from xml.sax.saxutils import escape, unescape

from ..skill_bank import learned_skills, record_use
from .anchor import _delivered_md
from .builtin import _builtin_plugins
from .bundles import bundled_plugins, installed_plugins
from .frontmatter import _description, _file_skill, _implicit, _lane, _read_text
from .manifest import _ASSIGNABLE_AGENTS, _skill_md
from .policy import _assigned, _skill_policy, _skill_routes


def skills(root: str) -> list[dict]:
    rows = [
        {
            "name": name,
            "description": _description(text),
            "plugin": plugin_name,
            "origin": "bundled",
            "invocation": "model" if _implicit(text) else "user",
        }
        for plugin_name, plugin in _builtin_plugins().items()
        for name, text in plugin["skills"]
    ]
    seen = {row["name"] for row in rows}
    for plugin_name, plugin in bundled_plugins().items():
        for name in plugin["skills"]:
            if name in seen:
                continue
            text = _skill_md(plugin, name)
            rows.append(
                {
                    "name": name,
                    "description": _description(text),
                    "plugin": plugin_name,
                    "origin": "bundled",
                    "invocation": "model" if _implicit(text) else "user",
                }
            )
            seen.add(name)
    for name, skill in learned_skills(root).items():
        if name in seen:
            continue
        rows.append(
            {
                "name": name,
                "description": str(skill.get("description") or ""),
                "plugin": "learned",
                "origin": "project" if str(skill.get("path", "")).startswith(os.path.realpath(root)) else "global",
                "invocation": "model" if _implicit(_read_text(str(skill["path"]))) else "user",
            }
        )
        seen.add(name)
    for plugin_name, plugin in installed_plugins().items():
        for name in plugin["skills"]:
            if name in seen:
                continue
            text = _skill_md(plugin, name)
            rows.append(
                {
                    "name": name,
                    "description": _description(text),
                    "plugin": plugin_name,
                    "origin": "installed",
                    "invocation": "model" if _implicit(text) else "user",
                }
            )
            seen.add(name)
    return sorted(rows, key=lambda row: row["name"])


def show_skill(root: str, name: str) -> str | None:
    for plugin in _builtin_plugins().values():
        for skill, text in plugin["skills"]:
            if skill == name:
                return text
    for plugin in bundled_plugins().values():
        if name in plugin["skills"]:
            return _delivered_md(root, plugin, name)
    learned = learned_skills(root).get(name)
    if learned:
        return _read_text(str(learned["path"]))
    for plugin in installed_plugins().values():
        if name in plugin["skills"]:
            return _delivered_md(root, plugin, name)
    return None


def skill_lane(root: str, name: str) -> str:
    """Lane declared by one skill's frontmatter — "" for unknown skills and ordinary ones."""
    text = show_skill(root, name)
    return _lane(text) if text else ""


def show_skill_resource(root: str, name: str, relative: str) -> str:
    """Read one text resource next to a file-backed skill without allowing path escape."""
    if not relative or os.path.isabs(relative):
        raise ValueError("skill resource must be a relative path")
    normalized = os.path.normpath(relative)
    if normalized in (".", "..") or normalized.startswith(".." + os.sep):
        raise ValueError("skill resource escapes its skill directory")
    for plugin in [*bundled_plugins().values(), *installed_plugins().values()]:
        if name not in plugin["skills"]:
            continue
        skill_root = Path(plugin["root"], "skills", name).resolve()
        candidate = Path(skill_root, normalized)
        resolved = candidate.resolve()
        try:
            resolved.relative_to(skill_root)
        except ValueError as exc:
            raise ValueError("skill resource escapes its skill directory") from exc
        if candidate.is_symlink() or not resolved.is_file():
            raise ValueError(f"skill resource not found: {name}/{relative}")
        try:
            return resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"skill resource is not UTF-8 text: {name}/{relative}") from exc
    if show_skill(root, name) is None:
        raise ValueError(f"skill not found: {name}")
    raise ValueError(f"skill has no bundled resource: {name}/{relative}")


def invocable_skills(root: str) -> list[dict]:
    """Catalog rows reachable by at least one configured runtime role."""
    policy = _skill_policy(root)
    allowed = set()
    for name, (defaults, compatible) in _skill_routes(root).items():
        if any(
            (agent in compatible or "any" in compatible) and _assigned(name, agent, defaults, policy)
            for agent in _ASSIGNABLE_AGENTS
        ):
            allowed.add(name)
    return [row for row in skills(root) if row["name"] in allowed]


def invoked_skill_prompt(root: str, command: str) -> str | None:
    """Expand an exact ``/skill-name`` invocation without exposing hidden skills to discovery."""
    head, _, arguments = command.strip().partition(" ")
    name = head.removeprefix("/")
    if not name or name not in {row["name"] for row in invocable_skills(root)}:
        return None
    text = show_skill(root, name)
    if text is None:
        return None
    body = text.split("---", 2)[2].lstrip() if text.startswith("---") else text
    return (
        f'<user_invoked_skill name="{escape(name)}">\n{body.rstrip()}\n</user_invoked_skill>\n\n'
        "The user explicitly invoked this skill. Follow its interaction contract; an explicit HITL skill may pause "
        "for the user's next decision even though ordinary unattended work should choose a safe default.\n\n"
        f"Arguments: {arguments.strip() or '(none)'}"
    )


_INVOKED_HEAD = re.compile(r'^<user_invoked_skill name="([^"]+)">')
_INVOKED_ARGS = re.compile(r"^Arguments: (.*)$", re.M)


def invoked_skill_command(request: str) -> str | None:
    """Recover the ``/skill args`` a prompt was expanded from, or None for an ordinary request.

    Consumers that need to know *what was asked* — routing, request classification, the map and
    tutor layers — must not read the expanded body. A SKILL.md is a contract describing what the
    procedure may do, and reading it as the request inverts the answer: `asgard-seal`'s old body
    carried twelve write verbs, so the write-verb veto in `Heimdall._classify` promoted every
    `/asgard-seal` to a full delivery quest. The producer above and this reader are adjacent on
    purpose — the wrapper format has one owner."""
    head = _INVOKED_HEAD.match(request)
    if not head:
        return None
    args = _INVOKED_ARGS.search(request)
    tail = args.group(1).strip() if args else ""
    return f"/{unescape(head.group(1))}" + (f" {tail}" if tail and tail != "(none)" else "")


def client_skill_bodies(agent: str, root: str | None = None, *, include_learned: bool = True) -> list[tuple[str, str]]:
    """Return the canonical skills visible to one agent, before any task is known."""
    root = root or os.getcwd()
    policy = _skill_policy(root)
    hits: dict[str, str] = {}
    core_contracts = {"asgard-freyja", "asgard-thor", "asgard-eitri", "asgard-mimir"}
    for plugin in _builtin_plugins().values():
        defaults = tuple(plugin.get("agents") or ())
        for name, body in plugin["skills"]:
            if name not in core_contracts and _assigned(name, agent, defaults, policy):
                hits.setdefault(name, body)
    for plugin in [*bundled_plugins().values(), *installed_plugins().values()]:
        for name in plugin["skills"]:
            # 스캐폴딩·목록 경로다 — 여기서 앵커를 풀지 않는다 (본문은 프론트매터만 소비된다).
            text = _delivered_md(root, plugin, name, unpack=False)
            parsed = _file_skill(text)
            if not parsed:
                continue
            route = plugin["routing"][name]
            compatible = set(route["agents"])
            if (agent in compatible or "any" in compatible) and _assigned(
                name, agent, tuple(route["defaults"]), policy
            ):
                hits.setdefault(name, text)
    if include_learned:
        for name, skill in learned_skills(root).items():
            defaults = (str(skill.get("agent") or "worker"),)
            if _assigned(name, agent, defaults, policy):
                text = show_skill(root, name)
                if text:
                    hits.setdefault(name, text)
    return sorted(hits.items())


def available_skills(
    root: str,
    agent: str,
    *,
    include_learned: bool = True,
    exclude: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    """Compact discovery tier: names and descriptions only, filtered by agent policy."""
    hidden = set(exclude)
    return [
        {"name": name, "description": _description(text)}
        for name, text in client_skill_bodies(agent, root, include_learned=include_learned)
        if name not in hidden and _implicit(text)
    ]


def skill_catalog(
    root: str,
    agent: str,
    *,
    include_learned: bool = True,
    exclude: tuple[str, ...] = (),
    loader: str = "load_skill",
    matched: set[str] | None = None,
) -> str:
    """Render only the metadata needed for model-native autonomous selection."""
    rows = available_skills(root, agent, include_learned=include_learned, exclude=exclude)
    if not rows:
        return ""
    if matched is not None:
        rows.sort(key=lambda row: (row["name"] not in matched, row["name"]))
        instruction = (
            "Call `load_skill` for every `[task-match]` skill before working. Then scan the remaining "
            "descriptions and load any additional skill that fits the task."
        )
    elif loader == "load_skill":
        instruction = "Call `load_skill` with the exact name only when a description matches the task."
    else:
        # 이 갈래만 파일로 구워져 클라이언트 에이전트 파일에 들어간다 (commands.setup). 구운 시점의 목록이라
        # 그 뒤에 설치된 학습 스킬은 여기 없다 — 26-08-12 실측: 명단 17개인 배포본 옆에서 라이브
        # 목록은 18개였고, 빠진 하나가 그날 자동 설치된 스킬이었다. 그래서 목록을 읽기 전에 런타임
        # 조회를 한 번 시킨다. `resolve` 는 디스크의 지금 상태를 보므로 배포본 나이와 무관하다.
        # (`load_skill` 갈래는 매 턴 계산되므로 이 문제가 없다.)
        instruction = (
            'Run `asgard skills resolve --agent <your-role> "<the request>"` once before planning: it reads '
            "the skills on disk right now, so it also finds ones installed after this file was written, and "
            "it sizes the work shape. Then run `asgard skills show <exact-name>` for anything it named and "
            "for any description below that matches the task, and follow the returned body."
        )
    items = "\n".join(
        f"  - {'[task-match] ' if matched is not None and row['name'] in matched else ''}"
        f"{escape(row['name'])}: {escape(_catalog_line(row['description']))}"
        for row in rows
    )
    return (
        "\n\n## Available skills (progressive disclosure)\n"
        f"{instruction} Do not preload every skill.\n"
        "<available_skills>\n"
        f"{items}\n"
        "</available_skills>"
    )


_CATALOG_LINE_CAP = 240


def _catalog_line(description: str) -> str:
    """카탈로그 한 줄 — 첫 문장, 최대 240자.

    이 목록이 하는 일은 모델이 **이름을 고르게** 하는 것뿐이다. 고른 뒤에 오는 본문이 정책이고,
    트리거 매칭(`_trigger_hits`)은 이 줄을 아예 안 읽는다. 그런데 정본 프론트매터의 description
    을 글자 그대로 썼던 탓에 한 항목이 616B(asgard-office)·412B 까지 길어졌고, 역할 하나가 무는
    합계가 4,818B 였다 (26-08-04 실측, worker 기준 17종). 그 값을 **핸드오프마다** 문다.

    **상한까지 문장을 채운다.** 첫 문장에서 무조건 끊던 판은 예산을 절반도 안 쓰고 버렸다:
    번들 28종 중 14종이 상한을 넘는데 그 첫 문장은 37~185자라 55~200자가 남았고, 남은 자리에
    있던 것이 하필 "언제 이 스킬을 고르는가"였다 (`asgard-freyja-fjadrhamr` 418자 → 37자
    "Freyja Fjadrhamr — the falcon cloak." 처럼 이름만 남았다). 그래서 문장 경계로 자르되
    상한이 허락하는 만큼 이어 붙이고, 한 문장도 못 담으면 그때만 글자로 끊는다.

    잘렸으면 언제나 말줄임표로 끝난다 — 사람이 잘렸음을 알아야 정본을 열어 본다. 트리거 문구는
    정본 본문이 들고 있으므로 라우팅 정확도는 이 길이에 걸려 있지 않다."""
    text = " ".join(str(description or "").split())
    if len(text) <= _CATALOG_LINE_CAP:
        return text
    budget = _CATALOG_LINE_CAP - 2  # 말줄임표(" …") 자리를 미리 뺀다 — 상한은 결과 길이다
    kept = ""
    for piece in re.split(r"(?<=[.!?])\s+|(?<=다\.)\s+|(?<=요\.)\s+", text):
        candidate = f"{kept} {piece}".strip() if kept else piece
        if len(candidate) > budget:
            # 남은 자리가 넉넉하면 다음 문장의 앞부분까지 쓴다 — 그 문장이 대개 "언제 쓰는가"다.
            room = budget - len(kept) - 1
            if room >= 60:
                kept = f"{kept} {piece[:room]}".strip() if kept else piece[:room]
            break
        kept = candidate
    return (kept.rstrip() + " …") if kept else text[: budget - 1].rstrip() + " …"


def load_skill_for_agent(
    root: str,
    agent: str,
    name: str,
    resource: str | None = None,
    *,
    include_learned: bool = True,
    exclude: tuple[str, ...] = (),
) -> str:
    """Load one assigned canonical body/resource; arbitrary catalog access stays closed."""
    allowed = {row["name"] for row in available_skills(root, agent, include_learned=include_learned, exclude=exclude)}
    if name not in allowed:
        raise ValueError(f"skill is not available to agent: {name} -> {agent}")
    if resource:
        loaded = show_skill_resource(root, name, resource)
        if name in learned_skills(root):
            record_use(root, [name])
        return loaded
    text = show_skill(root, name)
    if text is None:
        raise ValueError(f"skill not found: {name}")
    if name in learned_skills(root):
        record_use(root, [name])
    return text.split("---", 2)[2].lstrip() if text.startswith("---") else text
