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
import tempfile

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass


_READONLY_AGENTS = {"asgard-thinker", "asgard-verifier", "asgard-loki", "asgard-ullr", "asgard-mimir"}
_PYTHON = {"python", "python3", "pypy", "pypy3"}

# 차단이 가르치지 않으면 모델은 같은 명령의 변형으로 턴을 태운다 (26-07-21 실측: Verifier가
# python3 -c 차단 후 히어독·TMPDIR·py_compile 변형 10여 회 순차 시도). 거부 사유에 항상 동봉.
READONLY_BASH_HINT = (
    "Read-only role Bash allowlist: inspection (ls/cat/grep/rg/find/stat/tree/wc), git reads "
    "(status/diff/log/show/grep/ls-files), verification runners (pytest/mypy/pyright/ty/ruff check/tsc "
    "--noEmit — including via uv|poetry|pipenv run), python -m pytest|unittest|compileall|py_compile, "
    "python -c '<one-line smoke with no writes>', node --check <file>, node [--test] <tests/ script>, "
    "npm|pnpm|yarn test|lint|check, tests/ scripts. "
    "sed/awk without in-place writes. Allowed commands may be chained with `|`, `&&`, `||`, `;` "
    "(each segment is judged on its own), and `2>/dev/null` / `2>&1` / `< /dev/null` are fine. "
    "Blocked: file writes, redirection to a file, heredocs, $()/backticks/$VAR, paths outside the "
    "project (the harness's own isolated unit workspace is allowed). "
    "Use python -c instead of a scratch file, and for a uv project (uv.lock) use `uv run pytest -x -q`. "
    "A blocked command never ran — switch straight to an allowed lane instead of retrying a variant."
)

# 쓰기 도구 거부 — 읽기전용 역할에는 쓰기 레인 자체가 없다. Bash 허용목록을 보여 주면 오히려
# "다른 명령으로 쓰면 되나"로 오독된다: 소유자를 가리키는 것이 유일한 처방이다.
READONLY_WRITE_HINT = (
    "Read-only roles never write files. Hand the change to a write-capable role instead "
    "(Worker/Freyja/Thor/Eitri), or report the required change in your verdict/findings."
)

# python -c 스니펫의 쓰기 표면 휴리스틱 — 이미 허용된 pytest도 임의 프로젝트 코드를 실행하므로
# 이 분기가 그보다 넓지 않다. 적대 봉쇄가 아니라 실수 방지: 명시적 쓰기·프로세스·네트워크 API가
# 보이면 fail-closed. 없으면 Verifier 계약(대표 함수 호출 스모크)의 유일한 실행 통로로 허용.
_PY_SNIPPET_MUTATION = re.compile(
    r"subprocess|os\.(?:system|popen|remove|unlink|rename|replace|rmdir|mkdir|makedirs|chmod|chown|truncate)"
    r"|shutil\.(?:rmtree|move|copy\w*|chown|make_archive|unpack_archive|disk_usage)"
    r"|write_text|write_bytes|\.write\s*\(|pickle\.dump|\bexec\s*\(|\beval\s*\("
    r"|open\s*\([^)]*['\"](?:[wax]b?\+?|[rb]+\+b?)['\"]"
    r"|\bsocket\b|urllib|requests|httpx"
)
_INSPECT = {
    "cat",
    "diff",
    "echo",  # stdout 전용 — 파일 리다이렉션은 _shell_parts가 이미 막는다
    "fd",
    "file",
    "find",
    "grep",
    "head",
    "ls",
    "printf",
    "pwd",
    "rg",
    "stat",
    "tail",
    "tree",
    "wc",
}
# sed 스크립트의 파일 접근 명령 — w/W(쓰기)·r/R(읽기)는 경로 검사를 우회하는 표면이라 함께 막는다
# (`sed '1w /tmp/leak'`·`sed '1r /etc/passwd'`). 낱글자 경계로만 잡아 단어 속 w/r은 통과한다.
_SED_WRITE = re.compile(r"(?<![A-Za-z])[wWrR](?![A-Za-z])")
# awk 프로그램의 쓰기·실행·파일읽기 표면. 비교 연산자 `>`까지 함께 걸리지만 관측용 awk는 쓰지 않는다.
_AWK_WRITE = re.compile(r">|\bsystem\s*\(|\bclose\s*\(|\bgetline\b|\bENVIRON\b|\|")
_VERIFY = {"pytest", "mypy", "pyright", "ty"}
_GIT_READ = {"diff", "status", "log", "show", "grep", "ls-files", "rev-parse"}
# 통제 표면은 클라이언트마다 다른 디렉토리에 산다 — 한 클라이언트만 보호하면 같은 규율이
# 모드에 따라 있고 없다. 스캐폴드(훅·에이전트·설정)는 어느 모드에서도 작업 대상이 아니다.
_CONTROL_PATHS = (".claude", ".cursor", ".codex", ".agents", ".asgard")
_HOOK_DIRS = (".claude/hooks/", ".cursor/hooks/", ".codex/hooks/")
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


_UNIT_WORKSPACE_PREFIX = "asgard-unit-"


def _within_unit_workspace(candidate: str) -> bool:
    """하네스가 만든 격리 배정 작업공간 판정 — 프로젝트 밖이지만 하네스 소유 경로다.

    26-07-26 실측: wave 단위가 격리 워크스페이스($TMPDIR/asgard-unit-*)에서 뛸 때, 그 안의
    자기 파일을 절대경로로 가리키는 `node --test <ws>/tests/...`·`git -C <ws> status`가 경로
    이탈로 차단됐다 — 격리 레인과 경로 레인이 서로를 막아 관측 자체가 불가능해진다."""
    resolved = os.path.realpath(candidate)
    temp_root = os.path.realpath(tempfile.gettempdir())
    try:
        if os.path.commonpath((temp_root, resolved)) != temp_root:
            return False
    except ValueError:
        return False
    return any(part.startswith(_UNIT_WORKSPACE_PREFIX) for part in resolved.split(os.sep))


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
    if _within_unit_workspace(candidate):
        return True
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


_STREAM_EDITORS = {"sed", "gsed", "awk", "gawk", "nawk", "mawk"}


def _safe_stream_editor(program: str, tokens: list[str], root: str | None) -> bool:
    """sed/awk 판정 — 인플레이스와 스크립트 내 쓰기 표면만 제외하면 stdout 전용 관측이다.

    스크립트 인자는 경로가 아니므로 경로 이탈 검사에서 뺀다: 정규식이 `/`로 시작하면
    (`awk '/^\\.dark/,0'`) 절대경로로 오독돼 정당한 관측이 차단됐다 (26-07-26 실측)."""
    is_sed = program.endswith("sed")
    args = tokens[1:]
    if any(a == "-i" or a.startswith("-i") or a in {"--in-place", "--include"} for a in args):
        return False
    if is_sed and any(a in {"-f", "--file"} or a.startswith("--file=") for a in args):
        return False  # 스크립트를 파일로 받으면 내용을 판정할 수 없다 (fail-closed)
    write_pattern = _SED_WRITE if is_sed else _AWK_WRITE
    script_seen = False
    for arg in args:
        if arg.startswith("-"):
            continue
        if not script_seen:  # 첫 비플래그 인자 = 스크립트
            script_seen = True
            if write_pattern.search(arg):
                return False
            continue
        if not _path_token_within_root(root, arg):
            return False
    return script_seen


def _safe_segment(segment: str, root: str | None = None) -> bool:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return False
    if not tokens:
        return False
    # 선행 환경 대입(VAR=x cmd / env VAR=x cmd)은 프로세스-로컬 — 판정은 본체 명령으로.
    # 터미널 폭 스모크(COLUMNS=130 python -c …) 같은 정당한 검증이 env 때문에 막히지 않게 한다.
    if os.path.basename(tokens[0]) == "env":
        tokens = tokens[1:]
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        return False
    program = os.path.basename(tokens[0])
    if program in _STREAM_EDITORS:
        return _safe_stream_editor(program, tokens, root)  # 스크립트 인자는 경로 검사 대상이 아니다
    if any(not _path_token_within_root(root, token) for token in tokens[1:]):
        return False
    if any(token == "--output" or token.startswith("--output=") for token in tokens[1:]):
        return False
    if program == "find" and any(token in {"-delete", "-exec", "-execdir", "-ok", "-okdir"} for token in tokens):
        return False
    if program in _INSPECT or program in _VERIFY:
        return True
    if program == "cd":
        # 디렉터리 이동은 쓰기가 아니다. 경로는 위에서 이미 root(또는 하네스 작업공간) 안으로
        # 검사됐다. `cd sub && <관측>`은 모노레포에서 가장 흔한 관측 형태다 — 이걸 막으면
        # 연결 허용의 이득이 절반은 사라진다 (26-07-26 실측: 재검증 런의 차단 2건이 전부 이 형태).
        return len(tokens) <= 2
    if _safe_asgard_hook(tokens, root):
        return True  # 퀘스트 기장(記帳)은 파이프라인 안에서도 같은 허용 명령이다
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
    if program == "node":
        # Python 레인과 대칭인 검증 통로. 이게 없으면 JS/TS 저장소에서 판정자가 **아무것도 실행할
        # 수 없어**, 배달물이 아무리 멀쩡해도 "실행 증거 없음 = FAIL" 로만 끝난다 (26-07-26 helios
        # 실측: node·npm·python -c subprocess 전 레인이 막혀 판정이 정적 읽기로 후퇴).
        # 임의 프로젝트 코드 실행은 이미 허용된 pytest와 같은 수준의 노출이다 — 새 구멍이 아니라
        # 같은 계약의 다른 런타임. 인라인 실행(-e/-p/--eval)은 쓰기 휴리스틱이 없어 제외한다.
        flags = [t for t in tokens[1:] if t.startswith("-")]
        operands = [t for t in tokens[1:] if not t.startswith("-")]
        if any(
            not (
                f in {"--check", "--test", "--test-only"} or f.startswith(("--test-reporter=", "--test-name-pattern="))
            )
            for f in flags
        ):
            return False
        if "--check" in flags:
            return len(operands) == 1
        if not operands:
            return "--test" in flags  # bare `node --test` = 프로젝트 테스트 전체 (pytest 무인자와 동형)
        # 여러 테스트 파일을 한 번에 — `pytest a b`와 동형. 단일 operand만 받으면 판정자가 파일마다
        # 턴을 나눠 써야 한다 (26-07-26 실측: 다중 형태 차단 후 한 파일씩 재시도).
        return all(_is_test_path(operand) for operand in operands)
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
        if tokens[1:2] in (["--version"], ["-V"], ["-VV"]):
            return True
        if len(tokens) >= 3 and tokens[1:3] in (
            ["-m", "pytest"],
            ["-m", "unittest"],
            ["-m", "compileall"],
            ["-m", "py_compile"],
        ):
            return True
        if len(tokens) >= 3 and tokens[1] == "-c":
            # Verifier 계약의 한 줄 스모크 레인 — 파일 작성 없이 대표 함수를 직접 호출한다.
            return not _PY_SNIPPET_MUTATION.search(" ".join(tokens[2:]))
        if len(tokens) >= 2:
            return tokens[1].replace("\\", "/").endswith(".py") and _is_test_path(tokens[1])
    return False


def _is_test_path(script: str) -> bool:
    """테스트 자산 경로 판정 — `tests/` 아래이거나 파일명이 test로 시작. 런타임 무관 (py·mjs·ts)."""
    normalized = script.replace("\\", "/")
    return os.path.basename(normalized).startswith("test") or "/tests/" in f"/{normalized}"


# 세그먼트 구분자 — 각 세그먼트를 독립 판정하므로 허용 명령끼리의 연결은 새 권한을 만들지 않는다.
# 반대로 이를 막으면 `git status --porcelain && git diff` 같은 순수 읽기가 통째로 차단되고, 모델은
# 같은 관측을 변형으로 재시도해 턴을 태운다 (26-07-26 helios 실측: 차단 39건의 최다 사유).
# 단일 `&`(백그라운드)는 구분자가 아니다 — 판정 밖에서 계속 도는 프로세스를 허용하지 않는다.
_SEGMENT_SEPARATORS = {"|", "||", "&&", ";"}
# 폐기 리다이렉션 — /dev/null로 버리거나 스트림을 합치는 형태는 프로젝트 파일을 만들지 않는다.
_DISCARD_REDIRECTION = re.compile(r"\s*(?:\d?>>?\s*/dev/null|\d?>&\s*[12]|<\s*/dev/null)")


def _shell_parts(command: str) -> tuple[list[list[str]], bool]:
    """Tokenize pipelines and command sequences, keeping metacharacters inside quotes as data."""
    command = _DISCARD_REDIRECTION.sub("", command)
    if "$(" in command or "`" in command:
        return [], False
    # 줄바꿈은 `;`와 같은 구분자다 — 히어독(`<<`)은 아래 토큰 검사가 계속 막는다. 줄바꿈 자체를
    # 금지하면 모델이 관측 뒤에 `\necho "EXIT:$?"` 같은 한 줄을 붙였을 때 명령 전체가 죽는다
    # (26-07-26 실측: 프로토콜 기록 명령이 이 형태로 반복 차단됐다).
    command = command.replace("\n", " ; ")
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return [], False
    parts: list[list[str]] = [[]]
    for token in tokens:
        if token in _SEGMENT_SEPARATORS:
            if not parts[-1]:
                return [], False
            parts.append([])
        elif token and all(char in "|&;<>" for char in token):
            return [], False
        else:
            parts[-1].append(token)
    if len(parts) > 1 and not parts[-1]:
        parts.pop()  # 후행 구분자(`ls;`)는 빈 세그먼트가 아니다
    return parts, bool(parts[-1])


def _safe_asgard_hook(tokens: list[str], root: str | None = None) -> bool:
    if len(tokens) < 2 or os.path.basename(tokens[0]) not in _PYTHON:
        return False
    # The trusted hook must be Python's actual script argument. Scanning later
    # arguments would let `python -c ... quest-log.py open` smuggle arbitrary code.
    script = tokens[1].replace("\\", "/")
    if os.path.isabs(script) and root:
        # 절대경로 형태도 같은 훅이다 — 호스트가 프로젝트 절대경로를 그대로 넘기는 일이 흔한데
        # 상대 형태만 인정하면 프로토콜 기록 명령이 막힌다 (26-07-26 실측: Worker가 quest를
        # 열지 못해 같은 명령을 형태만 바꿔 5회 재시도했다). root 안으로 환원해 판정한다.
        try:
            script = os.path.relpath(os.path.realpath(script), os.path.realpath(root)).replace("\\", "/")
        except ValueError:
            return False
    script = os.path.normpath(script).replace("\\", "/")
    # 훅이 사는 디렉토리는 클라이언트마다 다르다 — `.claude/hooks/`만 인정하면 Cursor·Codex 세션의
    # 퀘스트 기장이 통째로 막혀 역할이 로그를 못 연다 (모드 간 같은 동작이 깨지는 자리).
    if not script.startswith(_HOOK_DIRS) or script.count("/") != 2:
        return False
    name = os.path.basename(script)
    if name == "quest-log.py":
        if len(tokens) < 3 or tokens[2] not in {
            "open",
            "append",
            "state",
            "replay",
            "next",
            "close",
            "ticket-claim",
            "ticket-heartbeat",
            "ticket-finish",
            "ticket-recover",
            "verify-baseline",
        }:
            return False
        # close --force는 검증 실패 상태의 관리적 해제(Odin 동의) — read-only 역할의 권한이 아니다.
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
    if len(parts) == 1 and _safe_asgard_hook(parts[0], root):
        return True
    if (
        len(parts) == 2
        and parts[0]
        and os.path.basename(parts[0][0]) in {"echo", "printf"}
        and _safe_asgard_hook(parts[1], root)
        and "append" in parts[1]
    ):
        return True
    # Pipelines are safe only when every stage is independently read-only.
    return all(_safe_segment(shlex.join(part), root) for part in parts)


def _deny(protocol: str, message: str) -> None:
    """차단 응답 — Cursor는 permission JSON, Claude Code/Codex는 exit 2 + stderr (git-guard와 동일 규약)."""
    if protocol == "cursor":
        sys.stdout.write(
            json.dumps({"permission": "deny", "user_message": message, "agent_message": message}, ensure_ascii=False)
        )
        raise SystemExit(0)
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _refusal(control: bool, tool_name: str, command: str, path: str) -> str:
    """거부 사유 문장 — 실제 규칙과 도구에 맞아야 가르친다.

    통제 표면 차단에 "읽기전용 역할" 문장을 붙이면 쓰기 권한이 있는 역할이 자기 신원을 의심하며
    턴을 태우고, Edit 차단에 Bash 허용목록을 붙이면 없는 레인을 찾는다 (26-07-26 실측)."""
    target = command[:160] if tool_name == "Bash" else (path[:160] or "(no path)")
    if control:
        return (
            f"Asgard control-surface policy blocked {tool_name}: {target}\n"
            "Scaffolds and harness state (.claude/.cursor/.codex/.agents/.asgard) and paths outside "
            "the repo are not work targets — no role edits them. Change the Asgard config through its "
            "own commands (asgard init/sync), and keep the change inside the project."
        )
    if tool_name == "Bash":
        return f"Asgard read-only role policy blocked mutating or unclassified Bash: {target}\n{READONLY_BASH_HINT}"
    return f"Asgard read-only role policy blocked a file write via {tool_name}: {target}\n{READONLY_WRITE_HINT}"


def _allow(protocol: str) -> None:
    """Cursor는 침묵을 허용으로 안 본다 — 명시적 allow가 프로토콜 요구사항 (git-guard와 동일)."""
    if protocol == "cursor":
        sys.stdout.write(json.dumps({"permission": "allow"}, separators=(",", ":")))
    raise SystemExit(0)


def main() -> None:
    protocol = sys.argv[1] if len(sys.argv) > 1 else "claude"
    try:
        data = json.load(sys.stdin)
        agent = str(data.get("agent_type") or data.get("agent_name") or data.get("subagent_type") or "")
        # Cursor beforeShellExecution은 command를 최상위에 싣고 tool_input이 없다 — git-guard와
        # 같은 판별자로 셸 페이로드를 Bash 호출로 정규화한다.
        if "tool_input" not in data and data.get("command") is not None:
            tool_name, tool_input = "Bash", {"command": data.get("command")}
        else:
            tool_name = str(data.get("tool_name") or "Bash")
            tool_input = data.get("tool_input") or {}
        command = str(tool_input.get("command") or "")
    except Exception:
        _allow(protocol)
        return
    # 규율은 세션이 아니라 **역할**에 붙는다 (tool_kernel.ROLE_CAPABILITIES가 정본): worker 계열은
    # mutate를 갖고, thinker/verifier/loki/ullr/mimir은 안 갖는다. 신원이 없는 호출은 메인 세션이
    # 전이 함수가 배정한 역할을 직접 수행하는 자리(MAIN_WORKER)라 쓰기가 그 역할의 몫이다 —
    # 신원 부재를 읽기전용으로 읽으면 모드 B의 단일 변경이 통째로 막힌다: subagent-gate가
    # `[ASGARD_UNIT:<id>]` 없는 asgard-worker 디스패치를 거부하므로 우회로도 없다 (양쪽 차단 = 교착).
    # 퀘스트 없는 쓰기는 이 훅의 소관이 아니다 — write-sentinel이 기록하고 Stop의 verifier-gate가
    # 물리 대조로 잡는다. 같은 것을 두 시점에 재판하면 조기 교정이 아니라 교착이 된다.
    readonly = agent in _READONLY_AGENTS
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
        control = private_control_access or control_write or control_shell_write or path_escape
        _deny(protocol, _refusal(control, tool_name, command, path))
    _allow(protocol)


if __name__ == "__main__":
    main()
