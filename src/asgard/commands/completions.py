"""completions — shell completion scripts (bash|zsh|fish), subcommand-aware.

아래 명령 표면 테이블 하나에서 3개 셸 스크립트를 생성한다 — cli.py 등록 명령과의 동기는
tests/test_completions.py 가 Typer 앱 인트로스펙션으로 강제. `--install` 은 스크립트를
~/.asgard/completions/ 에 쓰고 셸 rc 에 가드된 source 한 줄을 배선한다 (fish 는 네이티브
completions 디렉터리에 놓여 자동 로드 — rc 편집 불요)."""

import os
import subprocess
import sys

from .. import ui

# ── 명령 표면 — cli.py 등록 명령과 동기 (hidden(upgrade) 제외) ─────────────────────
_SUMMARY = {
    "doctor": "check the install",
    "start": "open the Asgard terminal (Heimdall)",
    "auth": "manage Asgard-owned provider logins",
    "init": "scaffold a project for coding agents",
    "map": "project map — orientation, relation graph, and bounded context",
    "setup": "set up or refresh project-aware assets",
    "update": "update asgard to the latest release",
    "sync": "refresh scaffolded cores in set-up projects",
    "uninstall": "remove asgard",
    "completions": "print or install shell completion",
    "run": "run one task headless (Trinity loop)",
    "role": "Trinity role bridge",
    "tools": "inspect role-scoped tool catalog",
    "skills": "central Asgard skill catalog and router",
    "plugins": "Asgard plugin catalog",
    "memory": "Yggdrasil — personal memory · LLM wiki",
    "plan": "Asgard Plan — local product planning workspace",
    "desktop": "Asgard Desktop — tasks, artifacts, and settings",
    "evolve": "self-evolution inbox — skill drafts",
}
_FLAGS = {
    "doctor": ["--json", "--quiet"],
    "start": ["--check", "--provider", "--model", "--continue", "--execution", "--sandbox-name"],
    "auth": [],
    "init": ["--cc", "--cursor", "--codex", "--profile", "--force", "--dry-run", "--yes", "--lagom", "--quiet"],
    "map": ["--no-open"],  # bare `asgard map` = 관계 그래프 뷰 오픈 (memory 와 동형)
    "setup": [],
    "update": ["--dry-run", "--no-sync", "--quiet"],
    "sync": ["--dry-run", "--list", "--quiet"],
    "uninstall": ["--yes", "--dry-run", "--quiet"],
    "completions": ["--install"],
    "run": ["--provider", "--model", "--json", "--resume", "--quest", "--dual"],
    "role": [],
    "tools": [],
    "skills": [],
    "plugins": [],
    "memory": ["--port", "--no-open"],  # bare `asgard memory` = 대시보드 오픈 (원커맨드 UX)
    "plan": ["--port", "--no-open"],  # bare `asgard plan` = 기획 워크스페이스 오픈
    "desktop": ["--port", "--no-open", "--browser"],
    "evolve": [],
}
_VALUES = {  # 값을 갖는 열거형 옵션의 후보 — 자유값 옵션은 _FREE_OPTS
    "--provider": [
        "anthropic",
        "claude-native",
        "openai",
        "openai-native",
        "openai_compat",
        "openrouter",
        "ollama",
        "nvidia",
    ],
    "--profile": ["claude-code", "cursor", "codex", "universal"],
    "--lagom": ["off", "lite", "full"],
    "--kind": ["note", "user", "decision", "insight", "reference", "feedback"],
}
_FREE_OPTS = ["--model", "--query", "--effort", "--provider"]  # 값을 갖지만 후보가 없는 옵션
_SHORT = {"--quiet": "q", "--yes": "y"}  # fish 만 short 를 명시 등록 (bash/zsh 는 long 제안으로 충분)
_SHELLS = ["bash", "zsh", "fish"]  # completions 의 위치 인자
_ROLE_SUB = {
    "list": "bridge flags + role placements",
    "model": "list or set role models",
    "run": "run one role turn",
}
_AUTH_SUB = {"login": "sign in", "status": "check login", "logout": "remove login"}
_ROLES = ["thinker", "worker", "verifier"]
_MODEL_HOSTS = ["native", "claude-code", "cursor", "codex"]
_MODEL_FLAGS = ["--effort", "--provider", "--reset", "--help"]
_MODEL_ROLES = [
    "thinker",
    "worker",
    "verifier",
    "freyja-lead",
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
_TOOL_ROLES = ["thinker", "worker", "verifier", "freyja", "thor", "eitri", "loki", "ullr", "mimir"]
_TOOLS_SUB = {"list": "list native + Claude Code role tools"}
_SKILLS_SUB = {
    "list": "list skills",
    "show": "print one skill",
    "resolve": "resolve task policy",
    "run": "run a declared skill helper",
    "assign": "assign a skill to a role",
    "unassign": "remove a role assignment",
    "enable": "enable a project skill",
    "disable": "disable a project skill",
}
_PLUGINS_SUB = {"list": "list plugins", "install": "install a local data-only plugin"}
_MAP_SUB = {
    "generate": "create the deterministic project map",
    "update": "refresh structural facts",
    "check": "report drift without writing",
    "context": "show bounded task context",
    "scan": "rebuild the relation graph (no LLM)",
    "trace": "walk relation edges from a node",
    "view": "open the relation-graph view",
}
_SETUP_SUB = {"map": "draw or refresh the project code map"}
_EVOLVE_SUB = {
    "scan": "mine quest logs into pending drafts",
    "list": "list pending skill drafts",
    "show": "print one pending draft",
    "approve": "validate and install a draft",
    "reject": "reject a draft (latched)",
    "polish": "LLM-rewrite a pending draft",
    "bench": "A/B a learned skill OFF vs ON",
    "archive": "retire a learned skill (reversible)",
    "restore": "bring an archived skill back",
}
_MEM_SUB = {
    "add": "add a page",
    "ingest": "absorb knowledge (dedup-merge)",
    "query": "search the wiki (zero-LLM)",
    "dashboard": "open a read-only local memory dashboard",
    "lint": "wiki health check",
    "reindex": "rebuild derived index",
    "export-okf": "export personal memory as an OKF bundle",
    "show": "print one page",
    "remove": "delete a page",
    "merge": "absorb one page into another",
    "snapshot": "print the session injection snapshot",
    "recall": "print query-relevant memory context",
    "path": "print or configure the memory directory",
    "obsidian": "open the personal memory wiki in Obsidian",
    "connect": "select and trust a project-memory backend",
    "project-scan": "preview important project artifacts",
    "project-sync": "sync approved artifacts to the selected backend",
    "project-approve": "approve a staged project-memory record",
    "project-rehydrate": "replay Git canonical records to the selected backend",
    "mcp": "stdio MCP bridge (shared memory)",
}
_PLAN_SUB = {"dashboard": "open the local Asgard Plan workspace"}

# ── bash ──────────────────────────────────────────────────────────────────────
_BASH_TPL = """\
_asgard() {
  local cur prev cmd
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"
  cmd="${COMP_WORDS[1]}"
  if [ "$COMP_CWORD" -eq 1 ]; then
    case "$cur" in
      -*) COMPREPLY=( $(compgen -W "--help --version" -- "$cur") ) ;;
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


def _bash() -> str:
    value_cases = "\n".join(
        f'    {opt}) COMPREPLY=( $(compgen -W "{" ".join(vals)}" -- "$cur") ); return ;;'
        for opt, vals in _VALUES.items()
    )
    cases = []
    for name in _SUMMARY:
        if name == "role":
            subs = " ".join(_ROLE_SUB)
            cases.append(
                "    role)\n"
                '      if [ "$COMP_CWORD" -eq 2 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{subs} --help" -- "$cur") )\n'
                '      elif [ "${COMP_WORDS[2]}" = "run" ] && [ "$COMP_CWORD" -eq 3 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_ROLES)}" -- "$cur") )\n'
                '      elif [ "${COMP_WORDS[2]}" = "model" ] && [ "$COMP_CWORD" -eq 3 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_MODEL_HOSTS)}" -- "$cur") )\n'
                '      elif [ "${COMP_WORDS[2]}" = "model" ] && [ "$COMP_CWORD" -eq 4 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_MODEL_ROLES)}" -- "$cur") )\n'
                '      elif [ "${COMP_WORDS[2]}" = "model" ] && [ "$COMP_CWORD" -ge 5 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_MODEL_FLAGS)}" -- "$cur") )\n'
                "      fi ;;"
            )
        elif name == "auth":
            cases.append(
                "    auth)\n"
                '      if [ "$COMP_CWORD" -eq 2 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_AUTH_SUB)} --help" -- "$cur") )\n'
                '      elif [ "$COMP_CWORD" -eq 3 ]; then\n'
                '        COMPREPLY=( $(compgen -W "openai-native" -- "$cur") )\n'
                "      fi ;;"
            )
        elif name == "map":
            cases.append(
                "    map)\n"
                '      if [ "$COMP_CWORD" -eq 2 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_MAP_SUB)} --help" -- "$cur") )\n'
                '      elif [ "${COMP_WORDS[2]}" = "generate" ] || [ "${COMP_WORDS[2]}" = "update" ]; then\n'
                '        COMPREPLY=( $(compgen -W "--dry-run --json --quiet --help" -- "$cur") )\n'
                '      elif [ "${COMP_WORDS[2]}" = "check" ]; then\n'
                '        COMPREPLY=( $(compgen -W "--json --quiet --help" -- "$cur") )\n'
                '      elif [ "${COMP_WORDS[2]}" = "context" ]; then\n'
                '        COMPREPLY=( $(compgen -W "--query --refresh --managed-only --json --help" -- "$cur") )\n'
                "      fi ;;"
            )
        elif name == "setup":
            cases.append(
                "    setup)\n"
                '      if [ "$COMP_CWORD" -eq 2 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_SETUP_SUB)} --help" -- "$cur") )\n'
                '      elif [ "${COMP_WORDS[2]}" = "map" ]; then\n'
                '        COMPREPLY=( $(compgen -W "--check --dry-run --json --quiet --help" -- "$cur") )\n'
                "      fi ;;"
            )
        elif name == "tools":
            cases.append(
                "    tools)\n"
                '      if [ "$COMP_CWORD" -eq 2 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_TOOLS_SUB)} --help" -- "$cur") )\n'
                '      elif [ "${COMP_WORDS[2]}" = "list" ] && [ "$COMP_CWORD" -eq 3 ]; then\n'
                '        COMPREPLY=( $(compgen -W "--role --json --help" -- "$cur") )\n'
                '      elif [ "$prev" = "--role" ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_TOOL_ROLES)}" -- "$cur") )\n'
                "      fi ;;"
            )
        elif name == "skills":
            cases.append(
                "    skills)\n"
                '      if [ "$COMP_CWORD" -eq 2 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_SKILLS_SUB)} --help" -- "$cur") )\n'
                "      fi ;;"
            )
        elif name == "plugins":
            cases.append(
                "    plugins)\n"
                '      if [ "$COMP_CWORD" -eq 2 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_PLUGINS_SUB)} --help" -- "$cur") )\n'
                "      fi ;;"
            )
        elif name == "memory":
            cases.append(
                "    memory)\n"
                '      if [ "$COMP_CWORD" -eq 2 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_MEM_SUB)} --help" -- "$cur") )\n'
                "      fi ;;"
            )
        elif name == "plan":
            cases.append(
                "    plan)\n"
                '      if [ "$COMP_CWORD" -eq 2 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_PLAN_SUB)} --help" -- "$cur") )\n'
                "      fi ;;"
            )
        elif name == "evolve":
            cases.append(
                "    evolve)\n"
                '      if [ "$COMP_CWORD" -eq 2 ]; then\n'
                f'        COMPREPLY=( $(compgen -W "{" ".join(_EVOLVE_SUB)} --help" -- "$cur") )\n'
                "      fi ;;"
            )
        else:
            args = _SHELLS if name == "completions" else []
            words = " ".join(args + _FLAGS[name] + ["--help"])
            cases.append(f'    {name}) COMPREPLY=( $(compgen -W "{words}" -- "$cur") ) ;;')
    return (
        _BASH_TPL.replace("__CMDS__", " ".join(_SUMMARY))
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
    if [[ $words[2] == -* ]]; then compadd -- --help --version; else _describe -t commands 'asgard command' cmds; fi
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


def _zsh() -> str:
    cmds = "\n".join(f"    '{name}:{desc}'" for name, desc in _SUMMARY.items())
    value_cases = "\n".join(f"    {opt}) compadd -- {' '.join(vals)}; return ;;" for opt, vals in _VALUES.items())
    cases = []
    for name in _SUMMARY:
        if name == "role":
            cases.append(
                "    role)\n"
                "      if (( CURRENT == 3 )); then\n"
                f"        compadd -- {' '.join(_ROLE_SUB)} --help\n"
                "      elif [[ $words[3] == run ]] && (( CURRENT == 4 )); then\n"
                f"        compadd -- {' '.join(_ROLES)}\n"
                "      elif [[ $words[3] == model ]] && (( CURRENT == 4 )); then\n"
                f"        compadd -- {' '.join(_MODEL_HOSTS)}\n"
                "      elif [[ $words[3] == model ]] && (( CURRENT == 5 )); then\n"
                f"        compadd -- {' '.join(_MODEL_ROLES)}\n"
                "      elif [[ $words[3] == model ]] && (( CURRENT >= 6 )); then\n"
                f"        compadd -- {' '.join(_MODEL_FLAGS)}\n"
                "      fi ;;"
            )
        elif name == "auth":
            cases.append(
                "    auth)\n"
                "      if (( CURRENT == 3 )); then\n"
                f"        compadd -- {' '.join(_AUTH_SUB)} --help\n"
                "      elif (( CURRENT == 4 )); then\n"
                "        compadd -- openai-native\n"
                "      fi ;;"
            )
        elif name == "map":
            cases.append(
                "    map)\n"
                "      if (( CURRENT == 3 )); then\n"
                f"        compadd -- {' '.join(_MAP_SUB)} --help\n"
                "      elif [[ $words[3] == generate || $words[3] == update ]]; then\n"
                "        compadd -- --dry-run --json --quiet --help\n"
                "      elif [[ $words[3] == check ]]; then\n"
                "        compadd -- --json --quiet --help\n"
                "      elif [[ $words[3] == context ]]; then\n"
                "        compadd -- --query --refresh --managed-only --json --help\n"
                "      fi ;;"
            )
        elif name == "setup":
            cases.append(
                "    setup)\n"
                "      if (( CURRENT == 3 )); then\n"
                f"        compadd -- {' '.join(_SETUP_SUB)} --help\n"
                "      elif [[ $words[3] == map ]]; then\n"
                "        compadd -- --check --dry-run --json --quiet --help\n"
                "      fi ;;"
            )
        elif name == "tools":
            cases.append(
                "    tools)\n"
                "      if (( CURRENT == 3 )); then\n"
                f"        compadd -- {' '.join(_TOOLS_SUB)} --help\n"
                "      elif [[ $words[3] == list ]] && (( CURRENT == 4 )); then\n"
                "        compadd -- --role --json --help\n"
                "      elif [[ $words[CURRENT-1] == --role ]]; then\n"
                f"        compadd -- {' '.join(_TOOL_ROLES)}\n"
                "      fi ;;"
            )
        elif name == "skills":
            cases.append(
                "    skills)\n"
                "      if (( CURRENT == 3 )); then\n"
                f"        compadd -- {' '.join(_SKILLS_SUB)} --help\n"
                "      fi ;;"
            )
        elif name == "plugins":
            cases.append(
                "    plugins)\n"
                "      if (( CURRENT == 3 )); then\n"
                f"        compadd -- {' '.join(_PLUGINS_SUB)} --help\n"
                "      fi ;;"
            )
        elif name == "memory":
            cases.append(
                "    memory)\n"
                "      if (( CURRENT == 3 )); then\n"
                f"        compadd -- {' '.join(_MEM_SUB)} --help\n"
                "      fi ;;"
            )
        elif name == "plan":
            cases.append(
                "    plan)\n"
                "      if (( CURRENT == 3 )); then\n"
                f"        compadd -- {' '.join(_PLAN_SUB)} --help\n"
                "      fi ;;"
            )
        elif name == "evolve":
            cases.append(
                "    evolve)\n"
                "      if (( CURRENT == 3 )); then\n"
                f"        compadd -- {' '.join(_EVOLVE_SUB)} --help\n"
                "      fi ;;"
            )
        else:
            args = _SHELLS if name == "completions" else []
            cases.append(f"    {name}) compadd -- {' '.join(args + _FLAGS[name] + ['--help'])} ;;")
    return (
        _ZSH_TPL.replace("__CMDS__", cmds)
        .replace("__VALUE_CASES__", value_cases)
        .replace("__FREE_OPTS__", "|".join(_FREE_OPTS))
        .replace("__CMD_CASES__", "\n".join(cases))
    )


# ── fish — 조건부 complete 등록 (네이티브 서브커맨드 인지) ───────────────────────────
def _fish() -> str:
    all_cmds = " ".join(_SUMMARY)
    top = f"not __fish_seen_subcommand_from {all_cmds}"
    lines = ["complete -c asgard -f"]
    for name, desc in _SUMMARY.items():
        lines.append(f"complete -c asgard -n \"{top}\" -a {name} -d '{desc}'")
    lines.append(f'complete -c asgard -n "{top}" -l help -s h')
    lines.append(f'complete -c asgard -n "{top}" -l version -s v')
    for name in _SUMMARY:
        cond = f"__fish_seen_subcommand_from {name}"
        for flag in _FLAGS[name]:
            line = f'complete -c asgard -n "{cond}" -l {flag[2:]}'
            if flag in _SHORT:
                line += f" -s {_SHORT[flag]}"
            if flag in _VALUES:
                line += f' -x -a "{" ".join(_VALUES[flag])}"'
            elif flag in _FREE_OPTS:
                line += " -x"
            lines.append(line)
        lines.append(f'complete -c asgard -n "{cond}" -l help -s h')
    lines.append(f'complete -c asgard -n "__fish_seen_subcommand_from completions" -a "{" ".join(_SHELLS)}"')
    auth_top = "__fish_seen_subcommand_from auth; and not __fish_seen_subcommand_from " + " ".join(_AUTH_SUB)
    for sub, desc in _AUTH_SUB.items():
        lines.append(f"complete -c asgard -n \"{auth_top}\" -a {sub} -d '{desc}'")
    for sub in _AUTH_SUB:
        lines.append(
            f'complete -c asgard -n "__fish_seen_subcommand_from auth; and __fish_seen_subcommand_from {sub}" '
            "-a openai-native"
        )
    map_top = "__fish_seen_subcommand_from map; and not __fish_seen_subcommand_from " + " ".join(_MAP_SUB)
    for sub, desc in _MAP_SUB.items():
        lines.append(f"complete -c asgard -n \"{map_top}\" -a {sub} -d '{desc}'")
    for sub in ("generate", "update"):
        for flag in ("dry-run", "json", "quiet"):
            lines.append(
                f'complete -c asgard -n "__fish_seen_subcommand_from map; and __fish_seen_subcommand_from {sub}" -l {flag}'
            )
    for flag in ("json", "quiet"):
        lines.append(
            f'complete -c asgard -n "__fish_seen_subcommand_from map; and __fish_seen_subcommand_from check" -l {flag}'
        )
    for flag in ("query", "refresh", "managed-only", "json"):
        lines.append(
            f'complete -c asgard -n "__fish_seen_subcommand_from map; and __fish_seen_subcommand_from context" -l {flag}'
        )
    setup_top = "__fish_seen_subcommand_from setup; and not __fish_seen_subcommand_from " + " ".join(_SETUP_SUB)
    for sub, desc in _SETUP_SUB.items():
        lines.append(f"complete -c asgard -n \"{setup_top}\" -a {sub} -d '{desc}'")
    for flag in ("check", "dry-run", "json", "quiet"):
        lines.append(
            f'complete -c asgard -n "__fish_seen_subcommand_from setup; and __fish_seen_subcommand_from map" -l {flag}'
        )
    role_top = "__fish_seen_subcommand_from role; and not __fish_seen_subcommand_from " + " ".join(_ROLE_SUB)
    for sub, desc in _ROLE_SUB.items():
        lines.append(f"complete -c asgard -n \"{role_top}\" -a {sub} -d '{desc}'")
    lines.append(
        'complete -c asgard -n "__fish_seen_subcommand_from role; and __fish_seen_subcommand_from run" '
        f'-a "{" ".join(_ROLES)}"'
    )
    lines.append(
        'complete -c asgard -n "__fish_seen_subcommand_from role; and __fish_seen_subcommand_from model; '
        "and not __fish_seen_subcommand_from " + " ".join(_MODEL_HOSTS) + '" -a "' + " ".join(_MODEL_HOSTS) + '"'
    )
    lines.append(
        'complete -c asgard -n "__fish_seen_subcommand_from role; and __fish_seen_subcommand_from model; '
        "and __fish_seen_subcommand_from "
        + " ".join(_MODEL_HOSTS)
        + "; and not __fish_seen_subcommand_from "
        + " ".join(_MODEL_ROLES)
        + '" -a "'
        + " ".join(_MODEL_ROLES)
        + '"'
    )
    for flag in _MODEL_FLAGS:
        if flag == "--help":
            continue
        suffix = " -x" if flag in ("--effort", "--provider") else ""
        lines.append(
            'complete -c asgard -n "__fish_seen_subcommand_from role; and __fish_seen_subcommand_from model" '
            f"-l {flag[2:]}{suffix}"
        )
    mem_top = "__fish_seen_subcommand_from memory; and not __fish_seen_subcommand_from " + " ".join(_MEM_SUB)
    for sub, desc in _MEM_SUB.items():
        lines.append(f"complete -c asgard -n \"{mem_top}\" -a {sub} -d '{desc}'")
    plan_top = "__fish_seen_subcommand_from plan; and not __fish_seen_subcommand_from " + " ".join(_PLAN_SUB)
    for sub, desc in _PLAN_SUB.items():
        lines.append(f"complete -c asgard -n \"{plan_top}\" -a {sub} -d '{desc}'")
    evo_top = "__fish_seen_subcommand_from evolve; and not __fish_seen_subcommand_from " + " ".join(_EVOLVE_SUB)
    for sub, desc in _EVOLVE_SUB.items():
        lines.append(f"complete -c asgard -n \"{evo_top}\" -a {sub} -d '{desc}'")
    tools_top = "__fish_seen_subcommand_from tools; and not __fish_seen_subcommand_from " + " ".join(_TOOLS_SUB)
    for sub, desc in _TOOLS_SUB.items():
        lines.append(f"complete -c asgard -n \"{tools_top}\" -a {sub} -d '{desc}'")
    lines.append(
        'complete -c asgard -n "__fish_seen_subcommand_from tools; and __fish_seen_subcommand_from list" '
        '-l role -x -a "' + " ".join(_TOOL_ROLES) + '"'
    )
    skills_top = "__fish_seen_subcommand_from skills; and not __fish_seen_subcommand_from " + " ".join(_SKILLS_SUB)
    for sub, desc in _SKILLS_SUB.items():
        lines.append(f"complete -c asgard -n \"{skills_top}\" -a {sub} -d '{desc}'")
    plugins_top = "__fish_seen_subcommand_from plugins; and not __fish_seen_subcommand_from " + " ".join(_PLUGINS_SUB)
    for sub, desc in _PLUGINS_SUB.items():
        lines.append(f"complete -c asgard -n \"{plugins_top}\" -a {sub} -d '{desc}'")
    lines.append(
        'complete -c asgard -n "__fish_seen_subcommand_from tools; and __fish_seen_subcommand_from list" -l json'
    )
    return "\n".join(lines) + "\n"


def _render(shell: str) -> str | None:
    return {"bash": _bash, "zsh": _zsh, "fish": _fish}.get(shell, lambda: None)()


# ── install — 스크립트 파일 + rc 배선 (멱등: 마커 주석으로 중복 방지) ─────────────────
_RC_MARKER = "# asgard completions"


def _install(shell: str | None) -> int:
    shell = shell or os.path.basename(os.environ.get("SHELL") or "")
    script = _render(shell)
    if script is None:
        sys.stderr.write("usage: asgard completions <bash|zsh|fish> --install\n")
        return 2
    home = os.path.expanduser("~")
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
    """update 후 completion 을 기본 설치·재생성 — 베스트에포트 (설치의 기본 동선).

    로그인 셸($SHELL)은 흔적이 없어도 설치하고(구버전에서 올라온 사용자 커버), 설치
    흔적(파일)이 있는 다른 셸은 재생성한다. 구버전 프로세스의 템플릿은 낡았을 수
    있으므로 직접 쓰지 않고 방금 설치된 `asgard` 를 서브프로세스로 부른다 (--install
    은 멱등 — rc 는 마커로 1줄 유지). 실패는 조용히 무시."""
    home = os.path.expanduser("~")
    fish_dir = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "fish", "completions")
    targets = {
        "bash": os.path.join(home, ".asgard", "completions", "asgard.bash"),
        "zsh": os.path.join(home, ".asgard", "completions", "_asgard"),
        "fish": os.path.join(fish_dir, "asgard.fish"),
    }
    login = os.path.basename(os.environ.get("SHELL") or "")
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
        sys.stderr.write("usage: asgard completions <bash|zsh|fish>\n")
        return 2
    sys.stdout.write(script)
    return 0
