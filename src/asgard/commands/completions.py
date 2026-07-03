"""completions — print a shell completion script (bash|zsh|fish). Ported verbatim from the TS CLI
(hand-rolled scripts, byte-compatible with the existing smoke assertions)."""

import sys

_CMDS = "doctor start init update uninstall completions"  # cli.py 등록 명령과 동기 (hidden 제외)
_FLAGS = "--help --version --json --quiet --dry-run --yes --profile"

_BASH = """\
_asgard() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  if [ "$COMP_CWORD" -eq 1 ]; then
    COMPREPLY=( $(compgen -W "__CMDS__" -- "$cur") )
  else
    COMPREPLY=( $(compgen -W "__FLAGS__" -- "$cur") )
  fi
}
complete -F _asgard asgard
"""

_ZSH = """\
#compdef asgard
_asgard() {
  local -a cmds=(__CMDS__)
  if (( CURRENT == 2 )); then compadd -- $cmds; else compadd -- __FLAGS__; fi
}
_asgard "$@"
"""

_FISH = """\
complete -c asgard -f
complete -c asgard -n __fish_use_subcommand -a "__CMDS__"
complete -c asgard -l help -s h
complete -c asgard -l version -s v
complete -c asgard -l json
complete -c asgard -l quiet -s q
complete -c asgard -l dry-run
complete -c asgard -l yes -s y
complete -c asgard -l profile
"""


def _render(tpl: str) -> str:
    return tpl.replace("__CMDS__", _CMDS).replace("__FLAGS__", _FLAGS)


def run_completions(shell: str | None) -> int:
    tpl = {"bash": _BASH, "zsh": _ZSH, "fish": _FISH}.get(shell or "")
    if tpl is None:
        sys.stderr.write("usage: asgard completions <bash|zsh|fish>\n")
        return 2
    sys.stdout.write(_render(tpl))
    return 0
