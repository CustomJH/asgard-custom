#!/usr/bin/env python3
"""Read-only Bash policy shared by native execution and Claude Code role hooks.

The policy is deliberately allowlist-based. Unknown commands are mutating until proven
otherwise. This does not try to understand arbitrary shell programs; it only admits
inspection commands and bounded verification runners without shell write syntax.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

_READONLY_AGENTS = {"asgard-thinker", "asgard-verifier", "asgard-loki", "asgard-ullr"}
_PYTHON = {"python", "python3", "pypy", "pypy3"}
_INSPECT = {
    "cat",
    "diff",
    "fd",
    "file",
    "find",
    "grep",
    "head",
    "ls",
    "pwd",
    "rg",
    "stat",
    "tail",
    "tree",
    "wc",
}
_VERIFY = {"pytest", "mypy", "pyright", "ty"}
_GIT_READ = {"diff", "status", "log", "show", "grep", "ls-files", "rev-parse"}
_CONTROL_PATHS = (".claude", ".asgard")


def _git_subcommand(tokens: list[str]) -> str:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
            index += 2
            continue
        if token.startswith(("--git-dir=", "--work-tree=", "--namespace=")) or token in {
            "--no-pager",
            "--paginate",
            "--bare",
            "--literal-pathspecs",
            "--no-replace-objects",
        }:
            index += 1
            continue
        return token
    return ""


def _safe_segment(segment: str) -> bool:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return False
    if not tokens:
        return False
    program = os.path.basename(tokens[0])
    if any(token == "--output" or token.startswith("--output=") for token in tokens[1:]):
        return False
    if program == "find" and any(token in {"-delete", "-exec", "-execdir", "-ok", "-okdir"} for token in tokens):
        return False
    if program in _INSPECT or program in _VERIFY:
        return True
    if program == "ruff":
        return len(tokens) >= 2 and (
            (tokens[1] == "check" and not any(t in {"--fix", "--unsafe-fixes"} for t in tokens[2:]))
            or (tokens[1] == "format" and "--check" in tokens[2:])
        )
    if program == "tsc":
        return "--noEmit" in tokens[1:]
    if program == "git":
        return _git_subcommand(tokens) in _GIT_READ
    if program in {"uv", "poetry", "pipenv"} and len(tokens) >= 3 and tokens[1] == "run":
        return _safe_segment(shlex.join(tokens[2:]))
    if program in {"npm", "pnpm", "yarn"}:
        return len(tokens) >= 2 and tokens[1] in {"test", "lint", "check"}
    if program == "cargo":
        return len(tokens) >= 2 and (
            tokens[1] in {"test", "check", "clippy"} or (tokens[1] == "fmt" and "--check" in tokens[2:])
        )
    if program == "go":
        return len(tokens) >= 2 and tokens[1] in {"test", "vet"}
    if program == "make":
        return len(tokens) >= 2 and all(not t.startswith("-") and t in {"test", "check", "lint", "verify"} for t in tokens[1:])
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", program):
        if len(tokens) >= 3 and tokens[1:3] in (["-m", "pytest"], ["-m", "unittest"], ["-m", "compileall"]):
            return True
        if len(tokens) >= 2:
            script = tokens[1].replace("\\", "/")
            return script.endswith(".py") and (os.path.basename(script).startswith("test_") or "/tests/" in f"/{script}")
    return False


def _shell_parts(command: str) -> tuple[list[list[str]], bool]:
    """Tokenize pipelines while keeping metacharacters inside quotes as data."""
    if "\n" in command or "$(" in command or "`" in command:
        return [], False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return [], False
    parts: list[list[str]] = [[]]
    for token in tokens:
        if token == "|":
            if not parts[-1]:
                return [], False
            parts.append([])
        elif token and all(char in "|&;<>" for char in token):
            return [], False
        else:
            parts[-1].append(token)
    return parts, bool(parts[-1])


def _safe_asgard_hook(tokens: list[str]) -> bool:
    if len(tokens) < 2 or os.path.basename(tokens[0]) not in _PYTHON:
        return False
    # The trusted hook must be Python's actual script argument. Scanning later
    # arguments would let `python -c ... quest-log.py open` smuggle arbitrary code.
    script = os.path.normpath(tokens[1].replace("\\", "/")).replace("\\", "/")
    if not script.startswith(".claude/hooks/") or script.count("/") != 2:
        return False
    name = os.path.basename(script)
    if name == "quest-log.py":
        return len(tokens) >= 3 and tokens[2] in {"open", "append", "state", "next", "close"}
    return name == "verifier-gate.py"


def is_readonly_bash_safe(command: str) -> bool:
    """Return True only for Bash commands admitted in a read-only role."""
    command = command.strip()
    if not command:
        return False
    parts, valid = _shell_parts(command)
    if not valid:
        return False
    # Canonical quest bookkeeping is an allowed metadata write, not source mutation.
    if len(parts) == 1 and _safe_asgard_hook(parts[0]):
        return True
    if (
        len(parts) == 2
        and parts[0]
        and os.path.basename(parts[0][0]) in {"echo", "printf"}
        and _safe_asgard_hook(parts[1])
        and "append" in parts[1]
    ):
        return True
    # Pipelines are safe only when every stage is independently read-only.
    return all(_safe_segment(shlex.join(part)) for part in parts)


def main() -> None:
    try:
        data = json.load(sys.stdin)
        agent = str(data.get("agent_type") or "")
        tool_name = str(data.get("tool_name") or "Bash")
        tool_input = data.get("tool_input") or {}
        command = str(tool_input.get("command") or "")
    except Exception:
        return
    # Main-thread Odin is coordination/read-only; mutations belong to explicit
    # Worker/Freyja/Thor subagents. Tool-lifecycle hooks provide agent_type for them.
    readonly = not agent or agent in _READONLY_AGENTS
    path = str(tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path") or "")
    normalized_path = os.path.normpath(path).replace("\\", "/")
    try:
        normalized_command = command + " " + " ".join(shlex.split(command))
    except ValueError:
        normalized_command = command
    control_write = tool_name in {"Write", "Edit", "NotebookEdit"} and any(
        marker in normalized_path for marker in _CONTROL_PATHS
    )
    control_shell_write = (
        tool_name == "Bash"
        and any(marker in normalized_command for marker in _CONTROL_PATHS)
        and not is_readonly_bash_safe(command)
    )
    denied = control_write or control_shell_write or readonly and (
        tool_name in {"Write", "Edit", "NotebookEdit"}
        or (tool_name == "Bash" and not is_readonly_bash_safe(command))
    )
    if denied:
        print(
            f"Asgard read-only role policy blocked mutating or unclassified Bash: {command[:160]}",
            file=sys.stderr,
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
