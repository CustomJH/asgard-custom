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

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
    except Exception:
        pass


_READONLY_AGENTS = {"asgard-thinker", "asgard-verifier", "asgard-loki", "asgard-ullr", "asgard-mimir"}
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
_PRIVATE_CONTROL_PATHS = (".asgard/quest", ".asgard/receipts", ".asgard/state")


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


def _path_token_within_root(root: str | None, token: str) -> bool:
    """Reject explicit path escapes; resolve existing symlinks when a project root is known."""
    if not token or token == "-" or token.startswith("-"):
        return True
    normalized = token.replace("\\", "/")
    if normalized.startswith("~") or os.path.isabs(token) or normalized == ".." or normalized.startswith("../"):
        if not root:
            return False
    if not root:
        return True
    candidate = os.path.realpath(
        os.path.expanduser(token) if token.startswith(("~", "/")) else os.path.join(root, token)
    )
    project = os.path.realpath(root)
    try:
        return os.path.commonpath((project, candidate)) == project
    except ValueError:
        return False


def _path_token_targets_control(root: str | None, token: str, markers: tuple[str, ...]) -> bool:
    """Resolve symlink parents before comparing a path operand with protected directories."""
    if not root or not token or token == "-":
        return False
    if token.startswith("-"):
        if "=" not in token:
            return False
        token = token.split("=", 1)[1]
        if not token:
            return False
    candidate = os.path.realpath(
        os.path.expanduser(token) if token.startswith(("~", "/")) else os.path.join(root, token)
    )
    for marker in markers:
        protected = os.path.realpath(os.path.join(root, marker))
        try:
            if os.path.commonpath((protected, candidate)) == protected:
                return True
        except ValueError:
            continue
    return False


def _command_targets_control(root: str, command: str, markers: tuple[str, ...]) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return True
    return any(_path_token_targets_control(root, token, markers) for token in tokens[1:])


def _safe_segment(segment: str, root: str | None = None) -> bool:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return False
    if not tokens:
        return False
    program = os.path.basename(tokens[0])
    if any(not _path_token_within_root(root, token) for token in tokens[1:]):
        return False
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
        for index, token in enumerate(tokens[1:], 1):
            # Nominally read-only Git commands can execute arbitrary configured helpers.
            # Per-command config is unnecessary here, so reject it rather than maintaining
            # an incomplete denylist of executable config keys.
            if token == "-c" or token.startswith("-c") or token == "--config-env" or token.startswith("--config-env="):
                return False
            if token in {"--ext-diff", "--textconv", "--paginate", "-p", "--open-files-in-pager"} or token.startswith(
                "--open-files-in-pager="
            ):
                return False
            if token == "-C" and (index + 1 >= len(tokens) or not _path_token_within_root(root, tokens[index + 1])):
                return False
            if token.startswith(("--git-dir=", "--work-tree=")) and not _path_token_within_root(
                root, token.split("=", 1)[1]
            ):
                return False
        return _git_subcommand(tokens) in _GIT_READ
    if program in {"uv", "poetry", "pipenv"} and len(tokens) >= 3 and tokens[1] == "run":
        return _safe_segment(shlex.join(tokens[2:]), root)
    if program in {"npm", "pnpm", "yarn"}:
        return len(tokens) >= 2 and tokens[1] in {"test", "lint", "check"}
    if program == "cargo":
        return len(tokens) >= 2 and (
            tokens[1] in {"test", "check", "clippy"} or (tokens[1] == "fmt" and "--check" in tokens[2:])
        )
    if program == "go":
        return len(tokens) >= 2 and tokens[1] in {"test", "vet"}
    if program == "asgard" and len(tokens) >= 4 and tokens[1:3] == ["skills", "show"]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", tokens[3]):
            return False
        return len(tokens) == 4 or (
            len(tokens) == 6
            and tokens[4] == "--resource"
            and tokens[5] not in (".", "..")
            and not tokens[5].startswith(("/", "../"))
            and "/../" not in tokens[5]
        )
    if program == "make":
        return len(tokens) >= 2 and all(
            not t.startswith("-") and t in {"test", "check", "lint", "verify"} for t in tokens[1:]
        )
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", program):
        if len(tokens) >= 3 and tokens[1:3] in (["-m", "pytest"], ["-m", "unittest"], ["-m", "compileall"]):
            return True
        if len(tokens) >= 2:
            script = tokens[1].replace("\\", "/")
            return script.endswith(".py") and (
                os.path.basename(script).startswith("test_") or "/tests/" in f"/{script}"
            )
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
        if len(tokens) < 3 or tokens[2] not in {
            "open",
            "append",
            "state",
            "next",
            "close",
            "ticket-claim",
            "ticket-heartbeat",
            "ticket-finish",
            "ticket-recover",
            "verify-baseline",
        }:
            return False
        # close --force 는 검증 실패 상태의 관리적 해제(Odin 동의) — read-only 역할의 권한이 아니다.
        return not (tokens[2] == "close" and "--force" in tokens[3:])
    return name == "verifier-gate.py"


def is_readonly_bash_safe(command: str, root: str | None = None) -> bool:
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
    return all(_safe_segment(shlex.join(part), root) for part in parts)


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
    # Worker/Freyja/Thor/Eitri subagents. Tool-lifecycle hooks provide agent_type for them.
    readonly = not agent or agent in _READONLY_AGENTS
    root = str(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    path = str(tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path") or "")
    normalized_path = os.path.normpath(path).replace("\\", "/")
    try:
        normalized_command = command + " " + " ".join(shlex.split(command))
    except ValueError:
        normalized_command = command
    control_write = tool_name in {"Write", "Edit", "NotebookEdit"} and (
        any(marker in normalized_path for marker in _CONTROL_PATHS)
        or _path_token_targets_control(root, path, _CONTROL_PATHS)
    )
    private_control_access = (
        any(marker in normalized_path for marker in _PRIVATE_CONTROL_PATHS)
        or _path_token_targets_control(root, path, _PRIVATE_CONTROL_PATHS)
        or tool_name == "Bash"
        and (
            any(marker in normalized_command for marker in _PRIVATE_CONTROL_PATHS)
            or _command_targets_control(root, command, _PRIVATE_CONTROL_PATHS)
        )
    )
    path_escape = bool(path) and not _path_token_within_root(root, path)
    control_shell_write = (
        tool_name == "Bash"
        and (
            any(marker in normalized_command for marker in _CONTROL_PATHS)
            or _command_targets_control(root, command, _CONTROL_PATHS)
        )
        and not is_readonly_bash_safe(command, root)
    )
    denied = (
        private_control_access
        or path_escape
        or control_write
        or control_shell_write
        or readonly
        and (
            tool_name in {"Write", "Edit", "NotebookEdit"}
            or (tool_name == "Bash" and not is_readonly_bash_safe(command, root))
        )
    )
    if denied:
        print(
            f"Asgard read-only role policy blocked mutating or unclassified Bash: {command[:160]}",
            file=sys.stderr,
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
