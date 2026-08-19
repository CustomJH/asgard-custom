"""읽기 전용 레인의 허용 판정 — 이 명령이 트리를 바꾸는가.

Trinity 의 읽기 전용 역할(Thinker·Verifier·Loki·Ullr·Mimir)이 부를 수 있는 Bash 의 경계다.
판정은 허용목록이다: 아는 관측 명령만 통과하고 모르는 것은 막힌다. 넓히면 판정자가 트리를
고칠 수 있어 검증 독립성이 사라지고, 좁히면 판정자가 근거를 못 모은다 — 손으로 항목을 하나씩
넓히면 오탐과 구멍이 번갈아 난다는 것이 이 저장소의 실측이다. 그래서 입구를 하나로 두고
(`shell.shell_parts` 가 자른 세그먼트) 그 위에서만 판정한다.
"""

from __future__ import annotations

import os
import re
import shlex

from .shell import git_flags_safe, git_subcommand, shell_parts, strip_runner
from .workspace import _HOOK_DIRS, path_token_within_root, work_roots

_PYTHON = {"python", "python3", "pypy", "pypy3"}


# 차단이 가르치지 않으면 모델은 같은 명령의 변형으로 턴을 태운다 (26-07-21 실측: Verifier가
# python3 -c 차단 후 히어독·TMPDIR·py_compile 변형 10여 회 순차 시도). 거부 사유에 항상 동봉.
READONLY_BASH_HINT = (
    "Read-only role Bash allowlist: inspection (ls/cat/grep/rg/find/stat/tree/wc), git reads "
    "(status/diff/log/show/grep/ls-files), verification runners (pytest/mypy/pyright/ty/ruff check/tsc "
    "--noEmit — including via uv|poetry|pipenv run, with value-less flags such as --no-project/--isolated/"
    "--frozen/--locked/--offline in between), python -m pytest|unittest|compileall|py_compile, "
    "python -c '<one-line smoke with no writes>', node --check <file>, node [--test] <tests/ script>, "
    "npm|pnpm|yarn test|lint|check, tests/ scripts. "
    "`asgard siege` — reading it (show/inbox/blocked/gates/ready/waves/watch) and speaking about "
    "your own attempt on it (ask/escalate/heartbeat, and `done` only in its self-naming form: "
    "`asgard siege done --quest <quest> --agent <you> --outcome failed` — a positional dispatch id "
    "would let you settle somebody else's attempt). "
    "`gh` observation only, written as <noun> view|list — release/run/workflow/pr/issue. "
    "So `gh release view <tag> --json assets` is how you see what a tag actually shipped; "
    "`gh api`, download, create, upload, delete and merge stay closed. "
    "sed/awk without in-place writes. Allowed commands may be chained with `|`, `&&`, `||`, `;` "
    "(each segment is judged on its own), and `2>/dev/null` / `2>&1` / `< /dev/null` are fine. "
    'Shell loops of read-only commands are fine (`for f in a b; do wc -c "$f"; done`). '
    "Blocked: file writes, redirection to a file, heredocs, $()/backticks, paths outside the "
    "project (the harness's own isolated unit workspace and this project's scratchpad are allowed). "
    "A `$VAR` is fine as an operand, but not as the script of `python -c` / sed / awk — there the "
    "judged text is not the text that runs, so those lanes abstain. "
    "Use python -c with a literal snippet instead of a scratch file, and for a uv project (uv.lock) "
    "use `uv run pytest -x -q`. "
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
    # 표준 라이브러리의 제자리 편집 통로. 여는 모드가 `open()` 자리에 안 드러나서 위 항목이
    # 못 본다 — `fileinput.input(path, inplace=True)` 는 원본을 백업으로 옮기고 stdout 을 그
    # 파일로 돌린다. 이 한 줄이 없던 판에서는 그 스니펫이 **읽기로 인정돼** 통제 표면 판정을
    # 통째로 건너뛰었다 (26-08-13 3차 판정이 찾았다).
    r"|\bfileinput\b"
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


# 셸 변수 참조 — 스크립트나 스니펫 안에 있으면 그 자리의 실제 내용을 이 훅은 못 본다.
# 텍스트를 읽어 판정하는 레인(python -c · sed · awk)은 이것을 만나면 기권한다 (fail-closed).
_SHELL_EXPANSION = re.compile(r"\$\{?[A-Za-z_]")


# awk 프로그램의 쓰기·실행·파일읽기 표면. 비교 연산자 `>`까지 함께 걸리지만 관측용 awk는 쓰지 않는다.
_AWK_WRITE = re.compile(r">|\bsystem\s*\(|\bclose\s*\(|\bgetline\b|\bENVIRON\b|\|")


_VERIFY = {"pytest", "mypy", "pyright", "ty"}


# `ls-remote` 는 여기 넣으면 안 된다. 이름은 읽기지만 **원격 전송로를 여는** 유일한 후보라,
# 그 전송로가 띄울 프로그램을 인자로 받는다: `--upload-pack=<프로그램>` (그리고 `-u`·`--exec=`)
# 은 원격이 로컬 경로일 때 그 프로그램을 여기서 실행한다 (26-08-19 실측: 배포된 훅을 통과해
# `git ls-remote --upload-pack=id .` 이 실제로 `id` 를 돌렸다). 이 저장소는 같은 갈래를 이미
# 금지로 적어 뒀다 — `git -c diff.external=touch` (tests/test_tool_kernel.py).
#
# 위험한 플래그를 세어 막지 않는 이유는 이 저장소가 그 방법으로 세 번 샜기 때문이다. 세는 쪽은
# 매번 빠뜨린 갈래로 새고(`-u`·`--exec=`·`ext::` 전송로가 벌써 셋이다), 넷째를 더하는 대신
# 하위명령 자체를 안 여는 쪽이 맞다. 원격 관측이 필요하면 `_GH_READ` 를 쓴다 — 그쪽은 명사와
# 동사 쌍으로 닫혀 있어 프로그램을 지정할 자리가 없다.
_GIT_READ = {"diff", "status", "log", "show", "grep", "ls-files", "rev-parse"}


# `gh` 의 관측 동사 — (명사, 동사) 쌍으로만 연다. 바이너리 이름으로 열면 `gh release create` 와
# `gh pr merge` 가 같이 열리고, 동사 이름만으로 열면 다른 명사의 같은 동사까지 딸려 온다.
# `download` 계열은 파일을 쓰므로 뺐고 `api` 는 통째로 뺐다 — `-X POST` 하나로 쓰기가 된다.
#
# 이 표가 없는 동안 릴리즈 판정은 구조적으로 불가능했다 (26-08-19 실측: v0.10.19 판정이
# `gh release view`·`git ls-remote`·urllib·작업 출력 파일 네 통로가 모두 막혀 공개된 설치본
# 이름을 한 번도 못 보고 FAIL 로 끝났다 — 릴리즈가 틀려서가 아니라 볼 수가 없어서다).
_GH_READ = {
    ("release", "view"),
    ("release", "list"),
    ("run", "view"),
    ("run", "list"),
    ("workflow", "view"),
    ("workflow", "list"),
    ("pr", "view"),
    ("pr", "list"),
    ("issue", "view"),
    ("issue", "list"),
}


# 색인에만 닿는 git 하위명령 — 작업 트리의 파일을 한 바이트도 안 바꾼다. 아래 통제 표면이
# 닫혀 있는 이유는 "거기 쓴 것이 판정의 물리 대조에 안 잡힌다" 인데, 색인에 담는 것은 그
# 반대다: 커밋 경계 안으로 들여 Odin 이 diff 로 보게 만든다. 무엇이 담기는지는 `.asgard`
# 자신의 무시 규칙이 이미 정해서 (퀘스트 로그·상태·배차 DB 는 무시된 채 남는다) 가드가 그
# 경계를 다시 적지 않는다. `rm` 은 뺐다 — `--cached` 없이 부르면 파일을 지운다.
_GIT_INDEX_ONLY = {"add", "commit"}


# 배차 장부를 읽는 동사. 읽기 전용 역할이 자기가 선 그래프를 보는 자리다.
_SIEGE_READ = {"show", "inbox", "blocked", "gates", "ready", "waves", "watch"}
# 배차받은 쪽이 **자기 시도에 대해** 말하는 동사. 트리를 한 바이트도 안 바꾸고 닿는 곳은
# `.asgard/orchestration.db` 하나라, 판정의 물리 대조가 덮는 자리와 겹치지 않는다 — 여기가
# 닫혀 있으면 읽기 전용 역할은 실패를 보고할 길이 없고, 종료 훅이 그 배차를 succeeded 로 접는다
# (26-08-13 실측: asgard-ullr 의 실패 보고가 이 가드에서 exit 1). 남의 상태를 바꾸는 동사
# (`answer`·`decide`·`force`·`reset`·`settle`)는 여전히 밖에 둔다.
_SIEGE_SELF_REPORT = {"ask", "done", "escalate", "heartbeat"}
# `siege done` 이 값을 받는 플래그. 위치 인자를 가리려면 어느 토큰이 앞 플래그의 값인지 알아야 한다.
_SIEGE_DONE_FLAGS = {
    "--agent",
    "--body",
    "--file",
    "--outcome",
    "--quest",
    "--run",
    "--sender",
    "--subject",
    "--task",
}


def _siege_done_flags(tokens: list[str]) -> dict[str, str] | None:
    """`siege done` 의 플래그와 값. 위치 인자가 하나라도 있으면 None.

    이 동사는 위치 인자로 임의의 dispatch id 를 받는다. 그대로 열면 판정자가 자기가 판정하는
    Run 의 남의 배차를 정산할 수 있어, 같은 변경이 `dispatch-context` 에서 판정자를 빼는 이유와
    정면으로 어긋난다.
    """
    seen: dict[str, str] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        name, sep, inline = token.partition("=")
        if token == "--json":
            index += 1
            continue
        if name in _SIEGE_DONE_FLAGS:
            # `--quest=q1` 은 한 토큰, `--quest q1` 은 두 토큰이다. 값 자리가 비면 그 플래그는
            # 값을 못 받은 것이고, 아래 대조가 빈 문자열을 이름으로 읽지 않게 그대로 둔다.
            seen[name] = inline if sep else (tokens[index + 1] if index + 1 < len(tokens) else "")
            index += 1 if sep else 2
            continue
        return None  # 위치 인자 — 남의 dispatch id 가 들어올 수 있는 자리다
    return seen


def _siege_done_is_self_scoped(tokens: list[str], caller: str = "") -> bool:
    """`siege done` 이 **자기** 시도만 가리키는가.

    `--quest` 와 `--agent` 로 지목하는 형태만 통과시키고, 부르는 쪽 이름을 아는 자리에서는
    `--agent` 가 그 이름인지까지 본다 — 이름을 안 보면 읽기 전용 역할이 `--agent asgard-worker`
    라고 적어 워커의 시도를 접을 수 있고, 그것은 위치 인자를 막은 이유와 같은 구멍이다.

    퀘스트까지는 안 본다. 활성 퀘스트를 아는 것은 세션 상태를 읽는 훅이고 이 라이브러리는 명령문
    하나만 보며, 남의 퀘스트 id 는 지어내야 나오는 값이라 실수로 닿지 않는다 — 이 가드가 서는
    자리는 적대 봉쇄가 아니라 실수 방지다.
    """
    flags = _siege_done_flags(tokens)
    if flags is None or not (flags.get("--quest") and flags.get("--agent")):
        return False
    return not caller or flags["--agent"] == caller


def _safe_siege(tokens: list[str], caller: str = "") -> bool:
    """`asgard siege <동사> …` 하나의 판정 — 읽거나, 자기 시도에 대해 말하거나, 둘 다 아니거나.

    첫 토큰이 플래그일 수 있다 (`asgard siege --json` 은 목록 조회다). 그것을 동사로 읽으면 이
    저장소에서 가장 자주 치는 조회가 막힌다.
    """
    verb = next((token for token in tokens if not token.startswith("-")), "")
    if not verb or verb in _SIEGE_READ:
        return True
    if verb == "done":
        return _siege_done_is_self_scoped(tokens[tokens.index(verb) + 1 :], caller)
    return verb in _SIEGE_SELF_REPORT


_STREAM_EDITORS = {"sed", "gsed", "awk", "gawk", "nawk", "mawk"}


def _in_place_flag(arg: str) -> bool:
    """제자리 편집 플래그인가 — 뭉친 낱글자와 `=` 접미까지 본다.

    `-i` 와 `-i` 로 시작하는 것만 보던 판에서는 `sed -ni s/x/y/ <파일>` 과
    `--in-place=bak` 이 읽기로 인정돼 통과했다 (26-08-13 판정). 낱글자 묶음은 순서가 자유라
    `i` 가 묶음 안 어디에 있든 제자리 편집이고, 긴 플래그는 값이 `=` 로 붙어 온다.
    `-i.bak` 처럼 접미가 붙는 표기는 점 앞까지만 묶음으로 읽는다."""
    if arg.startswith("--"):
        return arg.split("=", 1)[0] in {"--in-place", "--include"}
    if not arg.startswith("-") or len(arg) < 2:
        return False
    return "i" in arg[1:].split(".", 1)[0]


def _safe_stream_editor(program: str, tokens: list[str], roots: tuple[str, ...]) -> bool:
    """sed/awk 판정 — 인플레이스와 스크립트 내 쓰기 표면만 제외하면 stdout 전용 관측이다.

    스크립트 인자는 경로가 아니므로 경로 이탈 검사에서 뺀다: 정규식이 `/`로 시작하면
    (`awk '/^\\.dark/,0'`) 절대경로로 오독돼 정당한 관측이 차단됐다 (26-07-26 실측)."""
    is_sed = program.endswith("sed")
    args = tokens[1:]
    if any(_in_place_flag(a) for a in args):
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
            # 셸 변수가 든 스크립트는 판정 대상 텍스트가 실행 텍스트와 다르다 (`_SHELL_EXPANSION`)
            if _SHELL_EXPANSION.search(arg) or write_pattern.search(arg):
                return False
            continue
        if not path_token_within_root(roots, arg):
            return False
    return script_seen


# 셸 제어문 낱말 — 그 자체로는 아무것도 실행하지 않는다. 없으면 읽기 전용 명령만 담은
# `for f in a b; do wc -c "$f"; done` 이 통째로 미분류가 돼 막힌다 (26-08-04 실측).
# 명령 치환(`$(…)`)은 여전히 `shell_parts` 가 거부한다 — 그 안은 판정할 수 없다.
_BLOCK_OPENERS = {"do", "then", "else"}


_BLOCK_CLOSERS = {"done", "fi", "esac", ";;"}


_COMMAND_HEADERS = {"while", "until", "if", "elif"}  # 뒤에 오는 것이 명령이다


_WORDLIST_HEADERS = {"for", "select"}  # 뒤에 오는 것은 낱말 목록이다


def _safe_segment(segment: str, roots: tuple[str, ...] = (), caller: str = "") -> bool:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return False
    if not tokens:
        return False
    while tokens and tokens[0] in _BLOCK_OPENERS | _COMMAND_HEADERS:
        tokens = tokens[1:]
    if tokens and tokens[0] in _WORDLIST_HEADERS:
        # `for NAME in …` 는 목록 선언이라 실행은 do 뒤 본문이 하지만, **낱말이 곧 경로**다.
        # 본문은 그 경로를 변수로 읽으므로 여기서 안 보면 뿌리 밖 파일이 반복문 형태로만 열린다
        # (같은 파일을 평범한 명령으로 읽으면 막힌다 — 판정이 형태에 따라 갈리면 안 된다).
        return len(tokens) >= 2 and all(path_token_within_root(roots, word) for word in tokens[3:])
    while tokens and tokens[-1] in _BLOCK_CLOSERS:
        tokens = tokens[:-1]
    if not tokens:
        return True  # 닫는 낱말만 남은 조각 (`done`) — 실행이 없다
    # 선행 환경 대입(VAR=x cmd / env VAR=x cmd)은 프로세스-로컬 — 판정은 본체 명령으로.
    # 터미널 폭 스모크(COLUMNS=130 python -c …) 같은 정당한 검증이 env 때문에 막히지 않게 한다.
    if os.path.basename(tokens[0]) == "env":
        tokens = tokens[1:]
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        # 대입만 남은 조각(`D=/some/path`)은 부를 명령이 없다 — 셸 변수 하나가 생길 뿐이다.
        # 이걸 미분류로 떨어뜨리면 조각 하나 때문에 명령 전체가 읽기 레인 밖으로 나가고,
        # 그 다음 통제 표면 그물이 인자에 스친 `.asgard`·`.claude` 를 잡아 순수 관측이 막힌다
        # (26-08-05 실측: `D=<경로>; ls "$D"` 형태가 그렇게 거부됐다). 값에 든 명령 치환은
        # `shell_parts` 가 이미 앞에서 거부한다.
        return True
    program = os.path.basename(tokens[0])
    if program in _STREAM_EDITORS:
        return _safe_stream_editor(program, tokens, roots)  # 스크립트 인자는 경로 검사 대상이 아니다
    if any(not path_token_within_root(roots, token) for token in tokens[1:]):
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
    if _safe_asgard_hook(tokens, roots):
        return True  # 퀘스트 기장(記帳)은 파이프라인 안에서도 같은 허용 명령이다
    if program == "ruff":
        return len(tokens) >= 2 and (
            (tokens[1] == "check" and not any(t in {"--fix", "--unsafe-fixes"} for t in tokens[2:]))
            or (tokens[1] == "format" and "--check" in tokens[2:])
        )
    if program == "tsc":
        return "--noEmit" in tokens[1:]
    if program == "git":
        return git_flags_safe(tokens, roots) and git_subcommand(tokens) in _GIT_READ
    if program == "gh":
        operands = [t for t in tokens[1:] if not t.startswith("-")]
        return len(operands) >= 2 and (operands[0], operands[1]) in _GH_READ
    if (inner := strip_runner(tokens)) is not None:
        return _safe_segment(shlex.join(inner), roots, caller)
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
    if program == "asgard" and tokens[1:2] == ["siege"]:
        return _safe_siege(tokens[2:], caller)
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
            snippet = " ".join(tokens[2:])
            # 셸 변수가 들어 있으면 **판정하는 글과 실행되는 글이 다르다** — 아래 쓰기 휴리스틱이
            # 보는 것은 `$PAYLOAD` 라는 네 글자뿐이고, 셸이 그 자리에 넣는 것은 무엇이든 될 수
            # 있다. 26-08-04 에 그렇게 기장 파일이 만들어졌다:
            #   for PAYLOAD in "…write_text('forged')"; do python -c "$PAYLOAD"; done
            # 스니펫을 판정할 수 없으면 통과시키지 않는다 (fail-closed).
            if _SHELL_EXPANSION.search(snippet):
                return False
            return not _PY_SNIPPET_MUTATION.search(snippet)
        if len(tokens) >= 2:
            return tokens[1].replace("\\", "/").endswith(".py") and _is_test_path(tokens[1])
    return False


def _is_test_path(script: str) -> bool:
    """테스트 자산 경로 판정 — `tests/` 아래이거나 파일명이 test로 시작. 런타임 무관 (py·mjs·ts)."""
    normalized = script.replace("\\", "/")
    return os.path.basename(normalized).startswith("test") or "/tests/" in f"/{normalized}"


def _safe_asgard_hook(tokens: list[str], roots: tuple[str, ...] = ()) -> bool:
    # 훅 명령의 정본 표기는 `uv run --no-project python <hooks>/quest-log.py …`다
    # (platform.hook_python). 래퍼를 먼저 벗겨야 아래 인터프리터·스크립트 판정이 맨 형태와
    # 같은 자리를 본다 — 안 벗기면 정본대로 친 기장 명령이 통째로 차단된다.
    if (inner := strip_runner(tokens)) is not None:
        tokens = inner
    if len(tokens) < 2 or os.path.basename(tokens[0]) not in _PYTHON:
        return False
    # The trusted hook must be Python's actual script argument. Scanning later
    # arguments would let `python -c ... quest-log.py open` smuggle arbitrary code.
    script = tokens[1].replace("\\", "/")
    if os.path.isabs(script) and roots:
        # 절대경로 형태도 같은 훅이다 — 호스트가 프로젝트 절대경로를 그대로 넘기는 일이 흔한데
        # 상대 형태만 인정하면 프로토콜 기록 명령이 막힌다 (26-07-26 실측: Worker가 quest를
        # 열지 못해 같은 명령을 형태만 바꿔 5회 재시도했다). 뿌리 안으로 환원해 판정한다.
        absolute = os.path.realpath(script)
        for candidate in roots:
            try:
                relative = os.path.relpath(absolute, candidate).replace("\\", "/")
            except ValueError:
                continue
            if not relative.startswith("../"):
                script = relative
                break
        else:
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
            "attach",
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


def is_readonly_bash_safe(
    command: str, root: str | None = None, roots: tuple[str, ...] | None = None, agent: str = ""
) -> bool:
    """Return True only for Bash commands admitted in a read-only role.

    `roots`를 넘기면 그것이 정본이다 — 이미 뿌리를 구한 호출자(훅의 main)가 설정을 두 번 읽지
    않게 한다. 안 넘기면 `root` 하나에서 `work_roots`로 편다.

    `agent`는 부르는 쪽의 역할 이름이다. `asgard siege done` 한 자리에서만 쓴다 — 그 동사가
    `--agent` 로 누구를 지목했는지 대조하는 데 필요하고, 이름을 모르는 호출자(통제 표면 갈래)는
    빈 값으로 두어 그 대조를 건너뛴다."""
    command = command.strip()
    if not command:
        return False
    if roots is None:
        roots = work_roots(root)
    parts, valid = shell_parts(command)
    if not valid:
        return False
    if (
        len(parts) == 2
        and parts[0]
        and os.path.basename(parts[0][0]) in {"echo", "printf"}
        and _safe_asgard_hook(parts[1], roots)
        and "append" in parts[1]
    ):
        return True
    # Pipelines are safe only when every stage is independently read-only. 퀘스트 기장은 소스
    # 변경이 아니라 허용된 메타데이터 쓰기이므로 그 단계도 스스로 안전하다 — 단계별로 보지 않고
    # 명령 전체가 한 토막일 때만 인정하면, 계약이 안내하는 형태에 `| tail` 한 번만 붙어도
    # 판정이 뒤집힌다: 그 뒤 `.claude/hooks/quest-log.py` 라는 경로 인자가 통제 표면 갈래에
    # 걸려 기장 자체가 막힌다 (26-08-05 실측 2회 — open 과 사본 대조가 그렇게 거부됐다).
    # 한 토막일 때 되던 것이 파이프 뒤에서 되는 것뿐이라 열리는 권한은 없다.
    return all(_safe_asgard_hook(part, roots) or _safe_segment(shlex.join(part), roots, agent) for part in parts)


def is_index_only_git(command: str, roots: tuple[str, ...]) -> bool:
    """모든 조각이 관측이거나 **색인에만 닿는 git 호출**인가 — 통제 표면 갈래에서만 쓴다.

    통제 표면이 닫혀 있는 이유는 거기 쓴 것이 판정의 물리 대조 밖에 남는다는 것이다. 색인에
    담는 연산은 그 반대다 — 그 자리를 커밋 경계 안으로 들여 Odin 이 diff 로 보게 만든다.
    무엇이 실제로 담기는지는 `.asgard` 자신의 무시 규칙이 정하므로 (런타임은 무시된 채 남는다)
    가드가 그 경계를 다시 적지 않는다.

    읽기 전용 레인(`is_readonly_bash_safe`)에는 안 넣는다. 넣으면 판정자·로키가 색인을 건드릴
    수 있게 되는데, 이 완화가 사려던 것은 그것이 아니다.

    뿌리 이탈·임의 실행은 읽기 레인과 같은 `git_flags_safe` 로 거른다. 경로 인자를 뿌리 안으로
    다시 검사하지는 않는다 — git 이 작업 트리 밖 경로를 스스로 거부하고, 검사하면 커밋 메시지에
    적힌 경로 한 줄이 봉인을 막는다."""
    parts, valid = shell_parts(command)
    if not valid or not parts:
        return False
    for part in parts:
        if not part:
            return False
        if _safe_segment(shlex.join(part), roots):
            continue
        if os.path.basename(part[0]) != "git" or not git_flags_safe(part, roots):
            return False
        if git_subcommand(part) not in _GIT_INDEX_ONLY:
            return False
        # `-f` 는 무시 규칙을 끄는 플래그다. 이 레인의 근거가 "무엇이 담기는지는 무시 규칙이
        # 정한다" 이므로, 그 규칙을 끄는 철자를 함께 열면 근거가 남지 않는다 — `git add -f
        # .asgard` 한 줄이 기장·상태·배차 DB 를 통째로 색인에 넣는다.
        if any(token == "-f" or token == "--force" for token in part[1:]):
            return False
    return True
