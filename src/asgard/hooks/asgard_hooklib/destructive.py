"""Canon 3 이 열거한 파괴 연산 — 되돌릴 수 없는 자리에서 한 번 멈춘다.

멈춤은 금지가 아니다. git-guard 가 이미 하드 블록으로 잡는 히스토리 재작성·워크트리 소실
계열과 달리, 여기 있는 연산은 정당한 이유로 실행될 때가 있다 (임시 디렉터리 청소, 시험 DB
재생성, 기능 브랜치에 main 을 들이기). 그래서 판정은 차단이 아니라 **동의 요구**다: 차단문이
이 명령 하나에만 듣는 토큰을 함께 주고, Odin 의 동의를 받은 뒤 `ASGARD_CONSENT=<토큰>` 을
앞에 붙여 다시 부르면 통과한다. 토큰은 정규화한 명령의 지문이라 다른 명령에 옮겨 붙지 않는다.

토큰을 에이전트가 스스로 계산해 붙이는 것을 훅은 막을 수 없다 — 훅은 누가 눌렀는지 모른다.
이 통로가 사는 값은 두 가지다: 첫 시도는 **반드시** 멈춰서 Odin 에게 물을 자리가 생기고,
동의로 통과한 호출은 `gate-events.jsonl` 에 `consent_used` 로 남아 사후에 셀 수 있다.

판정은 토큰 분류기로만 한다. 명령문 전체에 정규식을 대면 인용 안쪽의 글자가 연산으로 읽혀,
파일에서 문구를 찾는 읽기가 파괴로 차단된다 (26-08-04 에 git-guard 가 그 형태로 실패했고,
26-08-13 평가에서 통제 표면 가드가 같은 자리에서 네 번 오탐을 냈다).
"""

from __future__ import annotations

import ast
import hashlib
import os
import re

from .shell import drop_inert_operands, lex, segments, without_heredoc_bodies

_CONSENT_VAR = "ASGARD_CONSENT"
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# 재귀 삭제 플래그 — `-r` `-R` `--recursive`, 그리고 `-rf` 처럼 뭉친 표기.
_RECURSIVE = re.compile(r"^-[A-Za-z]*[rR][A-Za-z]*$")

# 인터프리터 스니펫이 트리를 지우는 자리. 파일 하나를 지우는 `os.remove` 는 뺀다 — Canon 3 이
# 요구하는 것은 되돌릴 수 없는 규모이고, 여기까지 넓히면 임시 파일 정리마다 동의를 묻는다.
_TREE_DELETE = re.compile(r"shutil\.rmtree|os\.removedirs|\.rmdir\s*\(|rmtree\s*\(")

# DB 클라이언트 — 이 프로그램의 인자에서만 SQL 파괴 구문을 찾는다. 프로그램을 먼저 가리므로
# `grep "DROP TABLE" schema.sql` 같은 읽기는 여기 닿지 않는다.
_DB_CLIENTS = {"psql", "mysql", "mariadb", "sqlite3", "mongosh", "mongo", "redis-cli", "clickhouse-client", "cqlsh"}
_SQL_DESTRUCTIVE = re.compile(
    r"\bdrop\s+(?:database|schema|table|index|view)\b|\btruncate\s+(?:table\b|\w)|\bflushall\b|\bflushdb\b"
    r"|\bdrop_database\b|\bdropdatabase\s*\(",
    re.IGNORECASE,
)

# 통합 지점을 옮기는 병합 — 기능 브랜치를 main 에 넣거나 main 을 가져오는 자리. `--abort` 와
# `--continue` 는 진행 중인 병합을 되돌리거나 잇는 것이라 뺀다.
_INTEGRATION_BRANCHES = {"main", "master", "develop", "origin/main", "origin/master", "origin/develop"}


def _program(segment: list[str]) -> tuple[str, list[str]]:
    """환경변수 접두와 래퍼를 벗긴 프로그램 이름과 그 인자."""
    index = 0
    while index < len(segment) and _ENV_ASSIGN.match(segment[index]):
        index += 1
    if index >= len(segment):
        return "", []
    program = os.path.basename(segment[index])
    rest = segment[index + 1 :]
    # `uv run --no-project python -c "…"` 처럼 래퍼를 두른 형태는 본체가 실제 프로그램이다.
    if program in {"uv", "poetry", "pipenv"} and rest and rest[0] == "run":
        rest = rest[1:]
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        if rest:
            return os.path.basename(rest[0]), rest[1:]
        return "", []
    if program in {"sudo", "env", "nohup", "time", "xargs"} and rest:
        while rest and (rest[0].startswith("-") or _ENV_ASSIGN.match(rest[0])):
            rest = rest[1:]
        if rest:
            return os.path.basename(rest[0]), rest[1:]
        return "", []
    return program, rest


# 지우는 것이 일상인 자리 — 빌드 산출물과 캐시. 여기까지 동의를 물으면 관문이 소음이 되고,
# 소음이 된 관문은 사람이 토큰부터 붙이고 보게 만든다. 무엇이 git 에 추적되는지 물으려면
# git 을 불러야 하는데 이 판정은 도구 호출마다 돌므로 (26-08-13 실측: PreToolUse 체인 802ms)
# 이름으로만 가른다. 이름이 목록에 없으면 물어보는 쪽으로 기운다.
_REGENERABLE = {
    "build", "dist", "out", "target", "bin", "obj", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".venv", "venv", "coverage", "htmlcov", ".next", ".nuxt",
    ".turbo", ".parcel-cache", ".cache", "tmp", "temp", ".tox", ".gradle", ".terraform",
}  # fmt: skip


def _rm_reason(args: list[str]) -> str | None:
    if not any(_RECURSIVE.match(arg) or arg == "--recursive" for arg in args):
        return None
    targets = [arg for arg in args if not arg.startswith("-")]
    risky = [target for target in targets if os.path.basename(target.rstrip("/")) not in _REGENERABLE]
    if not risky:
        return None
    return "recursive delete (%s)" % " ".join(risky[:3])


def _find_reason(args: list[str]) -> str | None:
    if "-delete" in args:
        return "find -delete (bulk delete)"
    if "-exec" in args or "-execdir" in args:
        index = args.index("-exec") if "-exec" in args else args.index("-execdir")
        if any(os.path.basename(arg) in {"rm", "shred", "unlink"} for arg in args[index + 1 :]):
            return "find -exec rm (bulk delete)"
    return None


def _git_merge_reason(args: list[str]) -> str | None:
    """`git [전역 플래그…] merge <통합 브랜치>` 인가.

    전역 플래그가 값을 받는 자리(`-C <경로>`)를 건너뛰지 않으면 그 값이 하위 명령으로 읽혀
    병합이 통째로 안 보인다."""
    index = 0
    while index < len(args):
        token = args[index]
        if token in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        break
    if index >= len(args) or args[index] != "merge":
        return None
    rest = args[index + 1 :]
    if any(arg in {"--abort", "--continue", "--quit"} for arg in rest):
        return None
    hit = [name for name in rest if not name.startswith("-") and name in _INTEGRATION_BRANCHES]
    if not hit:
        return None
    return "merge %s (integration branch)" % hit[0]


_PY = {"python", "python3", "pypy", "pypy3"}
_SNIPPET_FLAGS = {"-c", "-e", "--eval", "--print"}
_TREE_DELETE_CALLS = {"shutil.rmtree", "rmtree", "os.removedirs", "removedirs"}


def _dotted(node) -> str:
    """`shutil.rmtree` 처럼 점으로 이어진 호출 이름 — 못 읽는 형태는 빈 문자열."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    else:
        return ""
    return ".".join(reversed(parts))


def _python_snippet_deletes_tree(snippet: str) -> bool:
    """스니펫이 트리를 **호출**하는가 — 글자로 스친 것과 실행되는 것을 가른다.

    `python3 -c "print('shutil.rmtree 는 위험하다')"` 는 아무것도 지우지 않는다. 정규식은 그
    차이를 못 보고, 그렇게 막힌 관문은 표기를 바꿔 우회하는 요령만 가르친다. 파싱이 안 되면
    글자로 되돌아간다 — 못 읽는 코드 앞에서는 한 번 묻는 쪽이 낫다."""
    try:
        tree = ast.parse(snippet)
    except (SyntaxError, ValueError):
        return bool(_TREE_DELETE.search(snippet))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if name in _TREE_DELETE_CALLS or name.endswith(".rmdir"):
            return True
    return False


def _interpreter_reason(program: str, args: list[str], raw: str) -> str | None:
    # 스니펫으로 넘어온 코드만 본다 — 파일을 실행하는 형태(`python clean.py`)의 내용은 훅이
    # 읽지 않는다. 그쪽은 write-sentinel 과 판정의 물리 대조가 덮는다.
    snippets = [args[index + 1] for index, arg in enumerate(args) if arg in _SNIPPET_FLAGS and index + 1 < len(args)]
    if not snippets:
        return None
    if program in _PY:
        if not any(_python_snippet_deletes_tree(snippet) for snippet in snippets):
            return None
    elif program in {"node", "deno", "bun", "ruby", "perl"}:
        if not any(_TREE_DELETE.search(snippet) for snippet in snippets):
            return None
    else:
        return None
    return "tree delete via interpreter snippet"


def destructive_reason(command: str) -> str | None:
    """이 명령이 Canon 3 의 파괴 연산인가 — 사유 한 줄, 아니면 None.

    git-guard 의 하드 블록 표와 겹치지 않는다. 거기는 히스토리와 워크트리를 되돌릴 수 없게
    만드는 자리라 동의 통로 자체가 없고, 여기는 동의로 열리는 자리다."""
    try:
        tokens = drop_inert_operands(lex(without_heredoc_bodies(command)))
    except ValueError:
        return None  # 못 읽는 글은 여기서 판정하지 않는다 — git-guard 의 불투명 갈래가 받는다
    for segment in segments(tokens):
        program, args = _program(segment)
        if not program:
            continue
        raw = " ".join(segment)
        if program in {"rm", "shred"}:
            if reason := _rm_reason(args):
                return reason
        elif program == "find":
            if reason := _find_reason(args):
                return reason
        elif program == "git":
            if reason := _git_merge_reason(args):
                return reason
        elif program in _DB_CLIENTS:
            if _SQL_DESTRUCTIVE.search(raw):
                return "destructive DB statement (%s)" % program
        elif reason := _interpreter_reason(program, args, raw):
            return reason
    return None


def _without_consent(command: str) -> str:
    """동의 접두를 뗀 명령 — 토큰 지문의 대상이다."""
    stripped = command.strip()
    while True:
        match = re.match(r"^%s=[A-Za-z0-9]*\s+" % _CONSENT_VAR, stripped)
        if not match:
            return stripped
        stripped = stripped[match.end() :].strip()


def consent_token(command: str) -> str:
    """이 명령 하나에만 듣는 동의 토큰 — 공백만 정규화한 명령의 지문 12자.

    지문이라 다른 명령에 옮겨 붙지 않는다. 공백을 접는 것은 같은 명령을 다시 칠 때 들여쓰기
    한 칸 때문에 토큰이 어긋나는 것을 막기 위해서다."""
    body = re.sub(r"\s+", " ", _without_consent(command))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def consent_given(command: str) -> bool:
    """이 호출이 자기 지문과 맞는 동의를 달고 왔는가."""
    match = re.match(r"^%s=([A-Za-z0-9]+)\s" % _CONSENT_VAR, command.strip())
    if not match:
        return False
    return match.group(1) == consent_token(command)


def consent_refusal(reason: str, command: str) -> str:
    """차단문 — 무엇이 걸렸는지, 어떻게 물을지, 동의 뒤 무엇을 칠지 한 자리에 담는다."""
    return (
        "Asgard Canon Law 3 — destructive operation needs Odin's consent: %s\n"
        "This is not a hard block. Ask Odin for consent on this exact target, then re-run the same "
        "command with the consent token in front:\n"
        "  %s=%s <the same command>\n"
        "The token is a fingerprint of this command — it does not carry over to a different one. "
        "Nobody in the loop to ask (headless)? Canon 8 applies: take the consent yourself only if the "
        "target is scratch or reproducible, say so in your report, and never for data you cannot rebuild."
        % (reason, _CONSENT_VAR, consent_token(command))
    )
