"""completions — shell completion scripts (bash|zsh|fish|powershell), subcommand-aware.

명령·서브커맨드·플래그는 cli.py의 Typer 앱에서 읽는다 — 이 파일은 그 표면을 다시 적지 않는다.
손으로 쥐는 것은 한 줄 설명(_DESC·_SUB_DESC)과 열거 차례뿐이고, 둘 다 이름을 더하거나 뺄 수
없다: 설명이 없는 이름은 앱 help로 채워지고, 차례표에만 남은 이름은 버려진다(_ordered).
그래서 cli.py에 명령이 늘어도 자동완성에서 빠지지 않는다.

`--install`은 스크립트를 ~/.asgard/completions/에 쓰고 셸 rc에 가드된 source 한 줄을 배선한다
(fish는 네이티브 completions 디렉터리에 놓여 자동 로드 — rc 편집 불필요; powershell은 $PROFILE에
dot-source)."""

import os
import subprocess
import sys
from typing import Any, NamedTuple

from .. import ui

# ── 한 줄 설명 — 사람이 쥐는 표 ────────────────────────────────────────────────────
# cli.py의 help를 그대로 쓰지 않는 이유: 그쪽은 도움말 화면용 완결 문장이라 완성 메뉴 한 줄에는
# 길다 ("check the install — runtime, PATH, and project wiring"). 여기 없는 이름은 앱 help로
# 채우므로 빠지지 않는다. 키 차례가 곧 메뉴 차례다 — 차례표일 뿐이라 이름을 더하지도 빼지도 못한다.
_DESC = {
    "doctor": "check the install",
    "manual": "your own project rules (MANUAL.md) — what is loaded, from where, how big",
    "start": "open the Asgard terminal (Heimdall)",
    "agent": "agents (Einherjar) — many agents on one install, each with its own tier-1 memory",
    "auth": "manage Asgard-owned provider logins",
    "init": "scaffold a project for coding agents",
    "map": "project map — orientation, relation graph, and bounded context",
    "health": "codebase erosion signal — size, duplication, coupling, hotspots",
    "budget": "what this session has spent — cost units, raw components, per-lane attribution",
    "craft": "micro-shape of THIS diff — unit size/nesting, resource lifetime, cost",
    "freyja-gate": "visual surfaces of THIS diff — judged by each Freyja engine, ratcheted vs a base",
    "thor": "backend procedure engine — verb playbooks, the next verb, and the correctness gate",
    "tutor": "hand THIS diff back to you — what changed, and the questions only you can answer",
    "surface": "public API surface vs a base ref — breaking changes and call-site obligations",
    "setup": "set up or refresh project-aware assets",
    "update": "update asgard to the latest release",
    "sync": "refresh scaffolded cores in set-up projects",
    "uninstall": "remove asgard",
    "completions": "print or install shell completion",
    "run": "run one task headless (Trinity loop)",
    "role": "Trinity role bridge",
    "mode": "mode x role settings — agent, model, effort, provider",
    "siege": "siege ledger — runs, task graph, worker questions",
    "tools": "inspect role-scoped tool catalog",
    "skills": "central Asgard skill catalog and router",
    "plugins": "Asgard plugin catalog",
    "memory": "Yggdrasil — personal memory · LLM wiki",
    "open": "open a local Asgard window — studio · map · memory",
    "ticket": "Asgard 업무 — workspace, teams, projects, and the tickets the agent shares",
    "evolve": "self-evolution inbox — skill drafts",
    "humanize": "Bragi — grade text for machine-writing tells, any language",
    "office": "Sága — build, read, verify, and fill documents",
    "k6": "asgard-k6 — Docker load testing, and the harness that checks itself",
}
# 그룹별 서브커맨드 설명 — 위와 같은 규칙(없으면 앱 help, 차례표에만 남은 이름은 버림).
_SUB_DESC = {
    "role": {
        "list": "bridge flags + role placements",
        "model": "list or set role models",
        "run": "run one role turn",
    },
    "auth": {"login": "sign in", "status": "check login", "logout": "remove login"},
    "agent": {
        "list": "every agent on this machine",
        "show": "one agent — identity, memory size, capabilities",
        "create": "raise a new agent",
        "use": "make this the machine's active agent",
        "describe": "set what this agent is good at",
        "delete": "remove an agent and its tier-1 memory",
        "bind": "place an agent in this project (default · mode · role)",
        "unbind": "drop a placement",
        "where": "who works here, and which declaration won",
    },
    "tools": {"list": "list native + Claude Code role tools"},
    "skills": {
        "list": "list skills",
        "show": "print one skill",
        "resolve": "resolve task policy",
        "run": "run a declared skill helper",
        "assign": "assign a skill to a role",
        "unassign": "remove a role assignment",
        "enable": "enable a project skill",
        "disable": "disable a project skill",
    },
    "plugins": {"list": "list plugins", "install": "install a local data-only plugin"},
    "office": {
        "build": "spec to docx, pptx, or xlsx",
        "read": "document to Markdown or JSON",
        "verify": "static delivery gate",
        "fill": "fill placeholders in an existing file",
        "render": "PDF and page images",
        "outline": "genre skeletons",
        "template": "template registry",
    },
    "k6": {
        "doctor": "runner, k6 build, kit, scenarios",
        "scenarios": "built-in and project load scenarios",
        "run": "run a scenario and record the verdict",
        "selftest": "does the harness tell the truth",
        "report": "render a recorded run",
    },
    "map": {
        "update": "draw or redraw the deterministic project map",
        "check": "report drift without writing",
        "context": "show bounded task context",
        "scan": "rebuild the relation graph (no LLM)",
        "trace": "walk relation edges from a node",
        "list": "every node in the graph, with the id to trace from",
        "why": "search the comments and docstrings that recorded a reason",
        "impact": "what a change here could reach, both directions",
    },
    "setup": {"map": "draw or refresh the project code map"},
    "evolve": {
        "scan": "mine quest logs into pending drafts",
        "list": "list pending skill drafts",
        "show": "print one pending draft",
        "approve": "validate and install a draft",
        "reject": "reject a draft (latched)",
        "polish": "LLM-rewrite a pending draft",
        "bench": "A/B a learned skill OFF vs ON",
        "curate": "deterministic learned-skill aging report",
        "archive": "retire a learned skill (reversible)",
        "restore": "bring an archived skill back",
    },
    "memory": {
        "add": "add a page",
        "ingest": "absorb knowledge (dedup-merge)",
        "query": "search the wiki (zero-LLM)",
        "episodes": "search raw session transcript segments",
        "lint": "wiki health check",
        "contradictions": "pages that contradict each other (a human decides)",
        "contradiction-seen": "mark a contradiction as seen — not resolved",
        "proposals": "pending memory proposals awaiting your approval",
        "autosave": "save memories without the approval round-trip",
        "approve": "approve a staged memory proposal",
        "discard": "discard a staged memory proposal",
        "reindex": "rebuild derived index",
        "export-okf": "export personal memory as an OKF bundle",
        "show": "print one page",
        "remove": "delete a page",
        "merge": "absorb one page into another",
        "snapshot": "print the session injection snapshot",
        "recall": "print query-relevant memory context",
        "path": "print or configure the memory directory",
        "norn": "evolve the wiki (LLM deltas, deterministic apply)",
        "norn-restore": "restore a page archived by a norn pass",
        "pattern": "learn observations about Odin from past turns",
        "ask": "answer a question about Odin from every memory tier",
        "provider": "show or set the provider that curates personal memory",
        "semantic": "semantic search state (status/on/off/warmup)",
        "backup": "snapshot, verify, or restore the canonical wiki",
        "sync": "sync the wiki with a shared folder or git remote",
        "obsidian": "prepare and open the personal memory wiki in Obsidian",
        "connect": "select and trust a project-memory backend",
        "project-scan": "preview important project artifacts",
        "project-sync": "sync approved artifacts to the selected backend",
        "project-approve": "approve a staged project-memory record",
        "project-rehydrate": "replay Git canonical records to the selected backend",
        "project-reflect": "LLM-synthesized answer over the project bank (advisory)",
        "project-evolve": "find stale, duplicate, or contradictory project records",
        "project-learn": "configure Hindsight observations and project mental models",
        "project-ingest": "parse thrown documents into project memory",
        "mcp": "stdio MCP bridge (shared memory)",
    },
    # 창을 여는 문은 하나다 — 기획은 스튜디오 안에서만 쓴다(별도 `plan` 그룹 없음).
    "open": {
        "studio": "Asgard Studio — 작업·업무·기획·산출물·스킬·설정",
        "map": "관계 그래프",
        "memory": "위그드라실 대시보드 (읽기 전용)",
    },
    "ticket": {
        "board": "the board, folded into status columns",
        "list": "tickets in priority order",
        "new": "file a ticket (numbers are never reissued)",
        "show": "one ticket — body, sub-tickets, links, comments, activity",
        "move": "change status (start and finish times follow)",
        "set": "change only the fields you name",
        "comment": "leave a note on a ticket",
        "link": "block, relate, or mark a duplicate",
        "delete": "remove a ticket (its number stays retired)",
        "cycle": "cycles — list, open, close (closing rolls unfinished work forward)",
        "team": "teams — the owner of the numbering, workflow, cycles, and triage",
        "project": "projects — dated work that cuts across teams",
        "milestone": "milestones inside a project",
        "update": "a project progress note (health is written by a human)",
        "triage": "the team inbox — accept, decline",
        "import": "bring an old per-folder board into the workspace",
    },
}

# ── 앱에서 못 읽는 값들 — 각각 이유가 다르다 ──────────────────────────────────────────
# --profile: 프로필은 --cc/--cursor/--codex 플래그 조합으로 정해진다(setup.py의
#            `universal = not cc and not cursor and not codex`) — 열거 상수가 없다.
# --lagom:   모드 어휘는 templates/lagom.py 소관이고 여기서 참조할 공개 상수가 없다.
# 나머지 값 옵션(--provider·--kind)은 도메인 상수에서 읽는다 — _surface() 참조.
_MANUAL_VALUES = {
    "--profile": ["claude-code", "cursor", "codex", "universal"],
    "--lagom": ["off", "lite", "full"],
}
_AUTH_PROVIDERS = ["openai-native"]  # commands/auth.py가 받는 유일한 값 — 상수로 노출돼 있지 않다
_OFFICE_LANES = ["docx", "pptx", "xlsx"]  # office build의 metavar가 열거를 잃었을 때의 대비값
_FREE_OPTS = ["--model", "--query", "--effort", "--provider"]  # 값을 갖지만 후보가 없는 옵션
_SHORT = {"--quiet": "q", "--yes": "y"}  # fish만 short를 명시 등록 (bash/zsh는 long 제안으로 충분)
_SHELLS = ["bash", "zsh", "fish", "powershell"]  # completions의 위치 인자
# `role model <host> <role>` 후보의 차례. 후보 자체는 host별 유효 집합의 합집합이다 — 셸은 host를
# 가르지 않는다. host별로 갈라 내려면 네 렌더러의 깊이 4 갈래를 모두 손봐야 해서 여기서는 안 한다.
_MODEL_ROLE_ORDER = [
    "thinker",
    "worker",
    "verifier",
    "freyja",
    "thor-lead",
    "thor",
    "eitri",
    "loki",
    "ullr",
    "mimir",
    "thinker_alt",
    "classify",
]
# fish는 그룹마다 등록 줄을 따로 낸다 — 그 차례. 여기 없는 그룹도 뒤에 붙어 반드시 등록된다.
_FISH_GROUP_ORDER = ["auth", "agent", "map", "setup", "role", "memory", "open", "ticket", "evolve"]
# 서브커맨드의 플래그까지 깊이 3에서 내는 그룹. 나머지 그룹은 서브커맨드 이름까지만 낸다.
_FLAG_GROUPS = ("map", "setup", "open")


# ── 명령 표면 — cli.py의 Typer 앱에서 파생 ─────────────────────────────────────────
class _Surface(NamedTuple):
    """렌더러가 읽는 명령 표면 — 전부 앱에서 나온 값이다."""

    commands: dict[str, str]  # 이름 → 한 줄 설명
    flags: dict[str, list[str]]  # 이름 → 긴 플래그 (선언 차례, `--help` 제외)
    subs: dict[str, dict[str, str]]  # 그룹 → {서브커맨드 → 설명}
    sub_flags: dict[str, dict[str, list[str]]]  # 그룹 → {서브커맨드 → 긴 플래그}
    values: dict[str, list[str]]  # 값 옵션 → 후보
    roles: list[str]  # role run <role>
    model_hosts: list[str]  # role model <host>
    model_roles: list[str]  # role model <host> <role>
    tool_roles: list[str]  # tools list --role
    office_lanes: list[str]  # office build <lane>


def _ordered(names, curated) -> list[str]:
    """파생된 이름을 사람이 정한 차례로 세운다.

    차례표는 차례만 정한다 — 표에 없는 이름은 뒤에 붙고, 표에만 남은 이름은 버려진다. 그래서
    표가 낡아도 자동완성에서 명령이 사라지거나 없는 명령이 생기지 않는다.
    """
    return [n for n in curated if n in names] + [n for n in names if n not in curated]


def _visible(commands) -> dict[str, Any]:
    """숨긴 명령은 뺀다 — `upgrade`·`map generate`처럼 별칭으로만 남긴 이름은 제안하지 않는다."""
    return {name: command for name, command in (commands or {}).items() if not command.hidden}


def _describe(command, name: str, curated) -> str:
    """설명 한 줄 — 사람이 적은 것이 있으면 그것, 없으면 앱 help의 첫 줄."""
    if name in curated:
        return curated[name]
    text = (getattr(command, "short_help", None) or command.help or "").strip()
    return text.splitlines()[0] if text else name


def _long_flags(command) -> list[str]:
    """선언 차례 그대로의 긴 플래그. `--help`는 click이 나중에 다는 것이라 여기 없다 — 셸 쪽에서 붙인다."""
    return [opt for param in command.params for opt in param.opts if opt.startswith("--")]


def _group_head(s: "_Surface", name: str) -> list[str]:
    """그룹의 둘째 낱말 후보 — 서브커맨드 이름에 그룹 자신의 플래그를 더한다.

    `mode`·`siege`는 서브커맨드와 자기 플래그(`--json`)를 함께 받는다. 대부분의 그룹은 자기
    플래그가 없어 서브커맨드 이름만 남는다.
    """
    return [*s.subs[name], *s.flags[name]]


def _enum(text: str | None) -> list[str] | None:
    """`<a|b|c>`·`[a|b|c]`·`a|b|c` 꼴만 후보로 읽고, 산문이면 None.

    파이프가 섞인 설명문을 후보로 오독하면 자동완성이 문장 조각을 뱉는다. 통째로 열거인 것만
    받아들이고 아니면 부르는 쪽이 사람 표로 되돌아간다.
    """
    body = (text or "").strip()
    for opener, closer in (("<", ">"), ("[", "]")):
        if body.startswith(opener) and body.endswith(closer):
            body = body[1:-1]
            break
    parts = [part.strip() for part in body.split("|")]
    if len(parts) < 2:
        return None
    ok = all(part and all(ch.isalnum() or ch in "._-" for ch in part) for part in parts)
    return parts if ok else None


def _arg_enum(group, sub: str, param: str) -> list[str] | None:
    """그룹의 서브커맨드가 위치 인자로 받는 후보 — metavar가 열거일 때만."""
    command = _visible(getattr(group, "commands", {})).get(sub)
    if command is None:
        return None
    found = next((p for p in command.params if p.name == param), None)
    return _enum(getattr(found, "metavar", None)) if found is not None else None


def _surface() -> _Surface:
    """cli.py의 Typer 앱을 읽어 명령 표면을 세운다.

    지연 임포트인 이유: cli.py는 `completions` 명령 본문에서 이 모듈을 부른다. cli를 모듈
    최상단에 올리면 두 모듈이 서로를 임포트하는 자리가 생긴다.
    """
    from typer.main import get_command

    from .. import cli
    from ..memory.store import KINDS
    from ..providers import PROVIDERS, TRINITY_ROLES
    from ..templates.agent_models import AGENT_MODEL_DEFAULTS
    from .role import MODEL_HOSTS, _native_roles
    from .tools import _CLI_ROLES

    # TyperGroup은 이 환경에서 click.Group의 서브클래스가 아니다 — 타입이 아니라 속성으로 본다.
    top = _visible(getattr(get_command(cli.app), "commands", {}))
    names = _ordered(top, _DESC)

    subs: dict[str, dict[str, str]] = {}
    sub_flags: dict[str, dict[str, list[str]]] = {}
    for name in names:
        children = _visible(getattr(top[name], "commands", {}))
        if not children:
            continue
        curated = _SUB_DESC.get(name, {})
        order = _ordered(children, curated)
        subs[name] = {sub: _describe(children[sub], sub, curated) for sub in order}
        sub_flags[name] = {sub: _long_flags(children[sub]) for sub in order}

    # host마다 유효한 role이 다르다 (native는 thinker_alt·classify, 호스트 도구는 planner·ullr).
    # 셸은 host를 가르지 않으므로 합집합을 낸다.
    placeable = list(_native_roles())
    for host in MODEL_HOSTS:
        if host != "native":
            placeable.extend(AGENT_MODEL_DEFAULTS[host])

    return _Surface(
        commands={name: _describe(top[name], name, _DESC) for name in names},
        flags={name: _long_flags(top[name]) for name in names},
        subs=subs,
        sub_flags=sub_flags,
        values={
            "--provider": list(PROVIDERS),
            "--profile": _MANUAL_VALUES["--profile"],
            "--lagom": _MANUAL_VALUES["--lagom"],
            "--kind": list(KINDS),
        },
        roles=list(TRINITY_ROLES),
        model_hosts=list(MODEL_HOSTS),
        model_roles=_ordered(list(dict.fromkeys(placeable)), _MODEL_ROLE_ORDER),
        tool_roles=list(_CLI_ROLES),
        office_lanes=_arg_enum(top.get("office"), "build", "lane") or _OFFICE_LANES,
    )


def _zsh_desc(text: str) -> str:
    """zsh `_describe`는 `'name:desc'`를 홑따옴표 안에서 읽는다.

    그래서 설명문의 홑따옴표는 문자열을 **끝내고**, 콜론은 이름과 설명의 **경계**가 된다. 둘 중
    하나만 들어가도 스크립트가 통째로 깨지는데, 증상이 "모든 명령이 사라짐"이라 원인이 안 보인다
    (실측: 설명에 `verb's`와 백틱을 넣었더니 zsh 기능 시험 6개가 한 번에 죽었다). 저자가 특수문자를
    피하기를 기대하는 대신 여기서 막는다.
    """
    return text.replace("'", "'\\''").replace(":", "\\:")


def _fish_desc(text: str) -> str:
    """fish의 홑따옴표 안에서 이스케이프로 읽히는 것은 `\\'`와 `\\\\` 둘뿐이다."""
    return text.replace("\\", "\\\\").replace("'", "\\'")


# ── bash ──────────────────────────────────────────────────────────────────────
_BASH_TPL = """\
_asgard() {
  local cur prev cmd
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"
  cmd="${COMP_WORDS[1]}"
  if [ "$COMP_CWORD" -eq 1 ]; then
    case "$cur" in
      -*) COMPREPLY=( $(compgen -W "--help --version --agent" -- "$cur") ) ;;
      *)  COMPREPLY=( $(compgen -W "__CMDS__" -- "$cur") ) ;;
    esac
    return
  fi
  case "$prev" in
__VALUE_CASES__
    __FREE_OPTS__) return ;;
  esac
  case "$cmd" in
__CMD_CASES__
  esac
}
complete -F _asgard asgard
"""


def _bash_group(name: str, subs, *branches: str) -> str:
    """서브커맨드를 가진 그룹의 case 갈래 — 셋째 낱말은 서브커맨드, 그 뒤는 branches가 답한다."""
    body = "".join(f"\n{line}" for line in branches)
    return (
        f"    {name})\n"
        '      if [ "$COMP_CWORD" -eq 2 ]; then\n'
        f'        COMPREPLY=( $(compgen -W "{" ".join(subs)} --help" -- "$cur") )'
        f"{body}\n"
        "      fi ;;"
    )


def _bash_reply(words) -> str:
    return f'COMPREPLY=( $(compgen -W "{" ".join(words)}" -- "$cur") )'


def _bash(s: _Surface) -> str:
    value_cases = "\n".join(f"    {opt}) {_bash_reply(vals)}; return ;;" for opt, vals in s.values.items())
    cases = []
    for name in s.commands:
        if name == "role":
            cases.append(
                _bash_group(
                    "role",
                    _group_head(s, "role"),
                    '      elif [ "${COMP_WORDS[2]}" = "run" ] && [ "$COMP_CWORD" -eq 3 ]; then\n'
                    f"        {_bash_reply(s.roles)}",
                    '      elif [ "${COMP_WORDS[2]}" = "model" ] && [ "$COMP_CWORD" -eq 3 ]; then\n'
                    f"        {_bash_reply(s.model_hosts)}",
                    '      elif [ "${COMP_WORDS[2]}" = "model" ] && [ "$COMP_CWORD" -eq 4 ]; then\n'
                    f"        {_bash_reply(s.model_roles)}",
                    '      elif [ "${COMP_WORDS[2]}" = "model" ] && [ "$COMP_CWORD" -ge 5 ]; then\n'
                    f"        {_bash_reply([*s.sub_flags['role']['model'], '--help'])}",
                )
            )
        elif name == "auth":
            cases.append(
                _bash_group(
                    "auth",
                    _group_head(s, "auth"),
                    f'      elif [ "$COMP_CWORD" -eq 3 ]; then\n        {_bash_reply(_AUTH_PROVIDERS)}',
                )
            )
        elif name == "tools":
            cases.append(
                _bash_group(
                    "tools",
                    _group_head(s, "tools"),
                    '      elif [ "${COMP_WORDS[2]}" = "list" ] && [ "$COMP_CWORD" -eq 3 ]; then\n'
                    f"        {_bash_reply([*s.sub_flags['tools']['list'], '--help'])}",
                    f'      elif [ "$prev" = "--role" ]; then\n        {_bash_reply(s.tool_roles)}',
                )
            )
        elif name == "office":
            cases.append(
                _bash_group(
                    "office",
                    _group_head(s, "office"),
                    '      elif [ "${COMP_WORDS[2]}" = "build" ] && [ "$COMP_CWORD" -eq 3 ]; then\n'
                    f"        {_bash_reply(s.office_lanes)}",
                )
            )
        elif name in _FLAG_GROUPS:
            branches = [
                f'      elif [ "${{COMP_WORDS[2]}}" = "{sub}" ]; then\n        {_bash_reply([*flags, "--help"])}'
                for sub, flags in s.sub_flags[name].items()
                if flags
            ]
            cases.append(_bash_group(name, _group_head(s, name), *branches))
        elif name in s.subs:  # 서브커맨드 이름만 내는 그룹 — 갈래를 하나씩 손으로 적지 않는다
            cases.append(_bash_group(name, _group_head(s, name)))
        else:
            args = _SHELLS if name == "completions" else []
            cases.append(f"    {name}) {_bash_reply([*args, *s.flags[name], '--help'])} ;;")
    return (
        _BASH_TPL.replace("__CMDS__", " ".join(s.commands))
        .replace("__VALUE_CASES__", value_cases)
        .replace("__FREE_OPTS__", "|".join(_FREE_OPTS))
        .replace("__CMD_CASES__", "\n".join(cases))
    )


# ── zsh — fpath(_asgard 자동로드)와 source/eval 겸용 (꼬리의 funcstack/compdef 분기) ──
_ZSH_TPL = """\
#compdef asgard
_asgard() {
  local -a cmds=(
__CMDS__
  )
  if (( CURRENT == 2 )); then
    if [[ $words[2] == -* ]]; then compadd -- --help --version --agent; else _describe -t commands 'asgard command' cmds; fi
    return
  fi
  case $words[CURRENT-1] in
__VALUE_CASES__
    __FREE_OPTS__) return ;;
  esac
  case $words[2] in
__CMD_CASES__
  esac
}
if [[ $funcstack[1] == _asgard ]]; then
  _asgard "$@"
elif (( $+functions[compdef] )); then
  compdef _asgard asgard
fi
"""


def _zsh_group(name: str, subs, *branches: str) -> str:
    body = "".join(f"\n{line}" for line in branches)
    return (
        f"    {name})\n      if (( CURRENT == 3 )); then\n        compadd -- {' '.join(subs)} --help{body}\n      fi ;;"
    )


def _zsh(s: _Surface) -> str:
    cmds = "\n".join(f"    '{name}:{_zsh_desc(desc)}'" for name, desc in s.commands.items())
    value_cases = "\n".join(f"    {opt}) compadd -- {' '.join(vals)}; return ;;" for opt, vals in s.values.items())
    cases = []
    for name in s.commands:
        if name == "role":
            cases.append(
                _zsh_group(
                    "role",
                    _group_head(s, "role"),
                    f"      elif [[ $words[3] == run ]] && (( CURRENT == 4 )); then\n        compadd -- {' '.join(s.roles)}",
                    f"      elif [[ $words[3] == model ]] && (( CURRENT == 4 )); then\n        compadd -- {' '.join(s.model_hosts)}",
                    f"      elif [[ $words[3] == model ]] && (( CURRENT == 5 )); then\n        compadd -- {' '.join(s.model_roles)}",
                    "      elif [[ $words[3] == model ]] && (( CURRENT >= 6 )); then\n"
                    f"        compadd -- {' '.join([*s.sub_flags['role']['model'], '--help'])}",
                )
            )
        elif name == "auth":
            cases.append(
                _zsh_group(
                    "auth",
                    _group_head(s, "auth"),
                    f"      elif (( CURRENT == 4 )); then\n        compadd -- {' '.join(_AUTH_PROVIDERS)}",
                )
            )
        elif name == "tools":
            cases.append(
                _zsh_group(
                    "tools",
                    _group_head(s, "tools"),
                    "      elif [[ $words[3] == list ]] && (( CURRENT == 4 )); then\n"
                    f"        compadd -- {' '.join([*s.sub_flags['tools']['list'], '--help'])}",
                    f"      elif [[ $words[CURRENT-1] == --role ]]; then\n        compadd -- {' '.join(s.tool_roles)}",
                )
            )
        elif name == "office":
            cases.append(
                _zsh_group(
                    "office",
                    _group_head(s, "office"),
                    f"      elif [[ $words[3] == build && CURRENT == 4 ]]; then\n        compadd -- {' '.join(s.office_lanes)}",
                )
            )
        elif name in _FLAG_GROUPS:
            branches = [
                f"      elif [[ $words[3] == {sub} ]]; then\n        compadd -- {' '.join([*flags, '--help'])}"
                for sub, flags in s.sub_flags[name].items()
                if flags
            ]
            cases.append(_zsh_group(name, _group_head(s, name), *branches))
        elif name in s.subs:
            cases.append(_zsh_group(name, _group_head(s, name)))
        else:
            args = _SHELLS if name == "completions" else []
            cases.append(f"    {name}) compadd -- {' '.join([*args, *s.flags[name], '--help'])} ;;")
    return (
        _ZSH_TPL.replace("__CMDS__", cmds)
        .replace("__VALUE_CASES__", value_cases)
        .replace("__FREE_OPTS__", "|".join(_FREE_OPTS))
        .replace("__CMD_CASES__", "\n".join(cases))
    )


# ── fish — 조건부 complete 등록 (네이티브 서브커맨드 인지) ───────────────────────────
def _fish(s: _Surface) -> str:
    all_cmds = " ".join(s.commands)
    top = f"not __fish_seen_subcommand_from {all_cmds}"
    lines = ["complete -c asgard -f"]
    for name, desc in s.commands.items():
        lines.append(f"complete -c asgard -n \"{top}\" -a {name} -d '{_fish_desc(desc)}'")
    lines.append(f'complete -c asgard -n "{top}" -l help -s h')
    lines.append(f'complete -c asgard -n "{top}" -l version -s v')
    # 전역 --agent — 어느 하위 명령이든 그 에이전트로 돈다 (cli._main 콜백)
    lines.append(f'complete -c asgard -n "{top}" -l agent -s A -x')
    for name in s.commands:
        cond = f"__fish_seen_subcommand_from {name}"
        for flag in s.flags[name]:
            line = f'complete -c asgard -n "{cond}" -l {flag[2:]}'
            if flag in _SHORT:
                line += f" -s {_SHORT[flag]}"
            if flag in s.values:
                line += f' -x -a "{" ".join(s.values[flag])}"'
            elif flag in _FREE_OPTS:
                line += " -x"
            lines.append(line)
        lines.append(f'complete -c asgard -n "{cond}" -l help -s h')
    lines.append(f'complete -c asgard -n "__fish_seen_subcommand_from completions" -a "{" ".join(_SHELLS)}"')

    def seen(group: str, sub: str) -> str:
        return f"__fish_seen_subcommand_from {group}; and __fish_seen_subcommand_from {sub}"

    for group in _ordered(s.subs, _FISH_GROUP_ORDER):
        subs = s.subs[group]
        group_top = f"__fish_seen_subcommand_from {group}; and not __fish_seen_subcommand_from " + " ".join(subs)
        for sub, desc in subs.items():
            lines.append(f"complete -c asgard -n \"{group_top}\" -a {sub} -d '{_fish_desc(desc)}'")
        if group in _FLAG_GROUPS:
            for sub, flags in s.sub_flags[group].items():
                for flag in flags:
                    lines.append(f'complete -c asgard -n "{seen(group, sub)}" -l {flag[2:]}')
        if group == "auth":
            for sub in subs:
                lines.append(f'complete -c asgard -n "{seen("auth", sub)}" -a {" ".join(_AUTH_PROVIDERS)}')
        elif group == "role":
            lines.append(f'complete -c asgard -n "{seen("role", "run")}" -a "{" ".join(s.roles)}"')
            lines.append(
                f'complete -c asgard -n "{seen("role", "model")}; '
                "and not __fish_seen_subcommand_from " + " ".join(s.model_hosts) + '" -a "'
                f'{" ".join(s.model_hosts)}"'
            )
            lines.append(
                f'complete -c asgard -n "{seen("role", "model")}; '
                "and __fish_seen_subcommand_from " + " ".join(s.model_hosts) + "; "
                "and not __fish_seen_subcommand_from " + " ".join(s.model_roles) + '" -a "'
                f'{" ".join(s.model_roles)}"'
            )
            for flag in s.sub_flags["role"]["model"]:
                suffix = " -x" if flag in ("--effort", "--provider") else ""
                lines.append(f'complete -c asgard -n "{seen("role", "model")}" -l {flag[2:]}{suffix}')
        elif group == "tools":
            lines.append(f'complete -c asgard -n "{seen("tools", "list")}" -l role -x -a "{" ".join(s.tool_roles)}"')
            for flag in s.sub_flags["tools"]["list"]:
                if flag != "--role":
                    lines.append(f'complete -c asgard -n "{seen("tools", "list")}" -l {flag[2:]}')
        elif group == "office":
            lines.append(f'complete -c asgard -n "{seen("office", "build")}" -a "{" ".join(s.office_lanes)}"')
    return "\n".join(lines) + "\n"


# ── powershell — Register-ArgumentCompleter -Native (Windows PowerShell 5.1 / PowerShell 7) ──────
#
# 설명문은 넣지 않는다: 생성물이 ASCII로만 남아야 한다. Windows PowerShell 5.1은 BOM 없는 .ps1을
# 시스템 ANSI 코드페이지로 읽어서, 한글이나 em dash가 한 글자라도 들어가면 한국어 Windows에서
# 스크립트가 깨진 채 로드된다 (install.ps1이 ASCII-only인 것과 같은 이유).
_PS_TPL = """\
# asgard completions for PowerShell 5.1+ / PowerShell 7+
# generated by `asgard completions powershell` -- do not edit by hand

Register-ArgumentCompleter -Native -CommandName asgard -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    $values = @{
__VALUE_ENTRIES__
    }
    $free = @(__FREE_OPTS__)

    $words = @($commandAst.CommandElements | ForEach-Object { $_.ToString() })
    # Once a character is typed the word under the cursor is already an AST element. Drop it, so that
    # $pos means what COMP_CWORD means in the bash script: the slot being filled, not the last word.
    if ($wordToComplete -and $words.Count -gt 1 -and $words[$words.Count - 1] -eq $wordToComplete) {
        $words = @($words[0..($words.Count - 2)])
    }
    $pos = $words.Count
    $prev = if ($pos -ge 1) { $words[$pos - 1] } else { '' }
    $cmd = if ($pos -ge 2) { $words[1] } else { '' }
    $sub = if ($pos -ge 3) { $words[2] } else { '' }

    $out = @()
    if ($pos -le 1) {
        if ("$wordToComplete".StartsWith('-')) { $out = @('--help', '--version', '--agent') }
        else { $out = @(__CMDS__) }
    }
    elseif ($values.ContainsKey($prev)) { $out = $values[$prev] }
    elseif ($free -contains $prev) { $out = @() }
    else {
        switch -CaseSensitive ($cmd) {
__CMD_CASES__
        }
    }
    $out | Where-Object { $_ -like "$wordToComplete*" } | Sort-Object -Unique
}
"""


def _ps_list(items) -> str:
    return ", ".join(f"'{name}'" for name in items)


def _ps_group(name: str, subs, *branches: str) -> str:
    """서브커맨드를 가진 그룹의 switch 갈래 — 세 번째 낱말은 서브커맨드, 그 뒤는 branches가 답한다."""
    body = "".join(f"\n                {line}" for line in branches)
    return (
        f"            '{name}' {{\n"
        f"                if ($pos -eq 2) {{ $out = @({_ps_list(subs)}, '--help') }}{body}\n"
        "            }"
    )


def _ps_case(s: _Surface, name: str) -> str:
    """switch 한 갈래 — bash 쪽 같은 이름의 분기와 같은 자리에서 같은 후보를 낸다."""
    if name == "role":
        return _ps_group(
            "role",
            _group_head(s, "role"),
            f"elseif ($sub -eq 'run' -and $pos -eq 3) {{ $out = @({_ps_list(s.roles)}) }}",
            f"elseif ($sub -eq 'model' -and $pos -eq 3) {{ $out = @({_ps_list(s.model_hosts)}) }}",
            f"elseif ($sub -eq 'model' -and $pos -eq 4) {{ $out = @({_ps_list(s.model_roles)}) }}",
            f"elseif ($sub -eq 'model' -and $pos -ge 5) "
            f"{{ $out = @({_ps_list([*s.sub_flags['role']['model'], '--help'])}) }}",
        )
    if name == "auth":
        return _ps_group(
            "auth", _group_head(s, "auth"), f"elseif ($pos -eq 3) {{ $out = @({_ps_list(_AUTH_PROVIDERS)}) }}"
        )
    if name == "tools":
        return _ps_group(
            "tools",
            _group_head(s, "tools"),
            f"elseif ($sub -eq 'list' -and $pos -eq 3) "
            f"{{ $out = @({_ps_list([*s.sub_flags['tools']['list'], '--help'])}) }}",
            f"elseif ($prev -eq '--role') {{ $out = @({_ps_list(s.tool_roles)}) }}",
        )
    if name == "office":
        return _ps_group(
            "office",
            _group_head(s, "office"),
            f"elseif ($sub -eq 'build' -and $pos -eq 3) {{ $out = @({_ps_list(s.office_lanes)}) }}",
        )
    if name in _FLAG_GROUPS:
        branches = (
            f"elseif ($sub -eq '{sub}') {{ $out = @({_ps_list([*flags, '--help'])}) }}"
            for sub, flags in s.sub_flags[name].items()
            if flags
        )
        return _ps_group(name, _group_head(s, name), *branches)
    if name in s.subs:
        return _ps_group(name, _group_head(s, name))
    args = _SHELLS if name == "completions" else []
    return f"            '{name}' {{ $out = @({_ps_list([*args, *s.flags[name], '--help'])}) }}"


def _powershell(s: _Surface) -> str:
    value_entries = "\n".join(f"        '{opt}' = @({_ps_list(vals)})" for opt, vals in s.values.items())
    return (
        _PS_TPL.replace("__VALUE_ENTRIES__", value_entries)
        .replace("__FREE_OPTS__", _ps_list(_FREE_OPTS))
        .replace("__CMDS__", _ps_list(s.commands))
        .replace("__CMD_CASES__", "\n".join(_ps_case(s, name) for name in s.commands))
    )


def _render(shell: str) -> str | None:
    renderer = {"bash": _bash, "zsh": _zsh, "fish": _fish, "powershell": _powershell}.get(shell)
    return renderer(_surface()) if renderer else None


# ── install — 스크립트 파일 + rc 배선 (멱등: 마커 주석으로 중복 방지) ─────────────────
_RC_MARKER = "# asgard completions"


def _login_shell() -> str:
    """설치 대상 셸 — POSIX는 `$SHELL`, Windows는 PowerShell.

    Windows에서 `$SHELL`은 보통 비어 있다. 그것을 셸 이름으로 읽으면 빈 문자열이 미지원 셸로 떨어져
    Windows 사용자는 자동완성 없이 명령을 친다 (설치 스크립트가 `--install`을 불러도 마찬가지였다).
    """
    name = os.path.basename(os.environ.get("SHELL") or "")
    if not name and os.name == "nt":
        return "powershell"
    return name


def _powershell_profile() -> str:
    """PowerShell 프로파일 경로 — 호스트에게 직접 묻는다.

    `Documents`는 OneDrive 리디렉션으로 자리를 옮겨 있을 수 있어서 경로를 조립하면 엉뚱한 파일에
    쓴다. 물어볼 수 없을 때만(pwsh/powershell 부재·타임아웃) 표준 배치로 돌아간다.
    """
    for exe in ("pwsh", "powershell"):
        try:
            proc = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-Command", "$PROFILE.CurrentUserAllHosts"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
        except OSError, subprocess.SubprocessError:
            continue
        first = next((line.strip() for line in (proc.stdout or "").splitlines() if line.strip()), "")
        if proc.returncode == 0 and first:
            return first
    return os.path.join(os.path.expanduser("~"), "Documents", "PowerShell", "profile.ps1")


def _install_powershell(script: str, home: str) -> int:
    d = os.path.join(home, ".asgard", "completions")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, "asgard.ps1")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(script)
    ui.ok(f"powershell completions → {dest}")
    profile = _powershell_profile()
    try:
        with open(profile, encoding="utf-8") as f:
            wired = _RC_MARKER in f.read()
    except OSError:
        wired = False
    if wired:
        ui.step(ui.dim(f"already wired in {profile}"))
        return 0
    os.makedirs(os.path.dirname(profile) or ".", exist_ok=True)
    with open(profile, "a", encoding="utf-8") as f:
        f.write(f'\n{_RC_MARKER}\nif (Test-Path "{dest}") {{ . "{dest}" }}\n')
    ui.ok(f"wired {profile} — restart PowerShell (or: . $PROFILE)")
    return 0


def _install(shell: str | None) -> int:
    shell = shell or _login_shell()
    script = _render(shell)
    if script is None:
        sys.stderr.write("usage: asgard completions <bash|zsh|fish|powershell> --install\n")
        return 2
    home = os.path.expanduser("~")
    if shell == "powershell":
        return _install_powershell(script, home)
    if shell == "fish":
        d = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "fish", "completions")
        os.makedirs(d, exist_ok=True)
        dest = os.path.join(d, "asgard.fish")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(script)
        ui.ok(f"fish completions → {dest} " + ui.dim("(auto-loaded — new shells pick it up)"))
        return 0
    d = os.path.join(home, ".asgard", "completions")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, "_asgard" if shell == "zsh" else "asgard.bash")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(script)
    rc_home = (os.environ.get("ZDOTDIR") or home) if shell == "zsh" else home
    rc = os.path.join(rc_home, ".zshrc" if shell == "zsh" else ".bashrc")
    ui.ok(f"{shell} completions → {dest}")
    try:
        with open(rc, encoding="utf-8") as f:
            wired = _RC_MARKER in f.read()
    except OSError:
        wired = False
    if wired:
        ui.step(ui.dim(f"already wired in {rc}"))
        return 0
    posix_dest = dest.replace(home, "$HOME", 1)
    with open(rc, "a", encoding="utf-8") as f:
        f.write(f'\n{_RC_MARKER}\n[ -f "{posix_dest}" ] && source "{posix_dest}"\n')
    ui.ok(f"wired {rc} — restart your shell (or: source {rc})")
    return 0


def ensure_installed() -> None:
    """update 후 completion을 기본 설치·재생성 — 베스트에포트 (설치의 기본 동선).

    로그인 셸($SHELL)은 흔적이 없어도 설치하고(구버전에서 올라온 사용자 커버), 설치
    흔적(파일)이 있는 다른 셸은 재생성한다. 구버전 프로세스의 템플릿은 낡았을 수
    있으므로 직접 쓰지 않고 방금 설치된 `asgard`를 서브프로세스로 부른다
    (--install은 멱등 — rc는 마커로 1줄 유지). 실패는 조용히 무시."""
    home = os.path.expanduser("~")
    fish_dir = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "fish", "completions")
    targets = {
        "bash": os.path.join(home, ".asgard", "completions", "asgard.bash"),
        "zsh": os.path.join(home, ".asgard", "completions", "_asgard"),
        "fish": os.path.join(fish_dir, "asgard.fish"),
    }
    if os.name == "nt":
        targets["powershell"] = os.path.join(home, ".asgard", "completions", "asgard.ps1")
    login = _login_shell()
    for shell, path in targets.items():
        if shell == login or os.path.exists(path):
            try:
                subprocess.run(["asgard", "completions", shell, "--install"], capture_output=True, timeout=30)
            except Exception:
                pass


def run_completions(shell: str | None, install: bool = False) -> int:
    if install:
        return _install(shell)
    script = _render(shell or "")
    if script is None:
        sys.stderr.write("usage: asgard completions <bash|zsh|fish|powershell>\n")
        return 2
    sys.stdout.write(script)
    return 0
