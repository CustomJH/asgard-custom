"""셸 명령을 판정 가능한 조각으로 자른다 — 어휘 분석과 세그먼트 분리.

여기 있는 것은 전부 "무엇이 실행되는가"를 드러내는 일이고 허용/거부 판정은 하나도 없다.
그 분리가 중요한 자리다: 26-08-04 에 가드들이 **연산이 아니라 글자**를 봐서, 인용 안쪽의
문자열과 저장소 밖 경로까지 명령으로 읽었다. 히어독 본문을 먼저 제거하고(`without_heredoc_bodies`),
커밋 메시지처럼 실행되지 않는 피연산자를 떨어뜨린 뒤(`drop_inert_operands`) 판정에 넘긴다.
"""

from __future__ import annotations

import os
import re
import shlex

from .workspace import path_token_targets_control, path_token_within_root


def git_flags_safe(tokens: list[str], roots: tuple[str, ...]) -> bool:
    """git 전역 플래그가 임의 실행이나 뿌리 이탈로 이어지지 않는가 — 읽기 레인과 색인 레인이 함께 쓴다.

    이름만 읽기 전용인 git 명령도 설정으로 지정한 헬퍼를 실행할 수 있다. 실행 가능한 설정 키의
    목록을 불완전하게 유지하느니 명령별 설정 자체를 거부한다."""
    for index, token in enumerate(tokens[1:], 1):
        if token == "-c" or token.startswith("-c") or token == "--config-env" or token.startswith("--config-env="):
            return False
        if token in {"--ext-diff", "--textconv", "--paginate", "-p", "--open-files-in-pager"} or token.startswith(
            "--open-files-in-pager="
        ):
            return False
        if token == "-C" and (index + 1 >= len(tokens) or not path_token_within_root(roots, tokens[index + 1])):
            return False
        if token.startswith(("--git-dir=", "--work-tree=")) and not path_token_within_root(
            roots, token.split("=", 1)[1]
        ):
            return False
    return True


def git_subcommand(tokens: list[str]) -> str:
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


# 히어독 여는 낱말 — `<<EOF` · `<<-'EOF'` · `<<\EOF` · `<<"EOF"` · `<<2EOF`. 본문은 다음
# 줄부터 그 낱말만 적힌 줄까지고, 그 사이는 셸이 인자로 넘기지 않는다 (표준 입력으로 간다).
# 낱말 문법을 좁게 잡으면 못 알아본 표기의 본문이 인자로 남아, 그 안에 스친 한 마디가 읽기만
# 하는 명령을 막는다 — 여는 쪽을 넓게 본다.
_HEREDOC_OPEN = re.compile(r"<<-?\s*\\?(['\"]?)([^\s'\"|&;<>]+)\1")


def without_heredoc_bodies(command: str) -> str:
    """히어독 본문을 지운 형태 — **인자 후보를 뽑는 자리에서만** 쓴다.

    본문은 인자가 아니다 (셸이 표준 입력으로 흘려보낸다). 지우지 않으면 스크립트 안에 스친 한
    마디가 경로 인자로 읽혀 관측 명령 전체가 막힌다 (26-08-05 실측: 훅 사본 대조가 이 형태로
    거부됐다).

    본문이 **코드**일 수는 있다 — 그래서 사설 통제 경로의 텍스트 그물(`scannable_text`)은
    본문을 그대로 본다. 여기서 지우는 것은 "이것이 경로 인자인가"라는 질문 하나뿐이다.
    종료 낱말을 못 찾으면 아무것도 안 지운다: 열기만 하고 안 닫은 히어독까지 지우면 그
    뒤의 진짜 인자(`cat <<EOF; rm -rf .claude/hooks`)가 통째로 안 보인다."""
    lines = command.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        out.append(line)
        index += 1
        for match in _HEREDOC_OPEN.finditer(line):
            terminator = match.group(2)
            end = index
            while end < len(lines) and lines[end].strip() != terminator:
                end += 1
            if end < len(lines):
                index = end + 1  # 종료 낱말 줄 자체도 인자가 아니다
    return "\n".join(out)


def first_escaping_operand(roots: tuple[str, ...], command: str) -> str:
    """명령의 경로 피연산자 중 선언된 어느 뿌리에도 안 드는 첫 자리 — 없으면 빈 문자열.

    이것은 차단 **사유를 가르는** 데 쓴다. 뿌리 밖 경로는 읽기 레인에서 먼저 떨어지는데, 그
    뒤의 통제 표면 검사가 명령문 글자에서 `.asgard` 를 찾아내 `control` 로 진단했다. 두 사유는
    처방이 다르다 — `control` 은 아무도 못 고치는 자리라 `asgard init/sync` 를 지목하고,
    이탈은 선언 한 줄로 열리는 자리라 `asgard root add` 를 지목한다. 잘못 진단하면 읽는 쪽이
    엉뚱한 자리를 고치러 간다 (26-08-11 실측: 짝 저장소를 조사하는 순수 읽기가 네 번 그렇게
    막혔고, 처방대로 고칠 자리가 없었다).

    명령 이름 자리는 건너뛴다 — 인터프리터가 뿌리 밖에 사는 것은 정상이고
    (`/Users/…/.local/bin/uv run …`), 그것을 이탈로 읽으면 모든 훅 호출이 이탈이 된다."""
    try:
        tokens = drop_inert_operands(lex(without_heredoc_bodies(command)))
    except ValueError:
        return ""
    head = True
    for token in tokens:
        if token in _SEGMENT_SEPARATORS:
            head = True
            continue
        if head:
            head = False
            continue
        # 경로가 아닌 낱말과 플래그는 뿌리 판정의 대상이 아니다. 뿌리 밖을 가리키려면 구분자가
        # 있어야 하므로 (`../peer/x`, `/abs/path`) 한 세그먼트짜리 낱말은 여기서 뺀다.
        if token.startswith("-") or "/" not in token.replace("\\", "/"):
            continue
        if not path_token_within_root(roots, token):
            return token
    return ""


def command_targets_control(roots: tuple[str, ...], command: str, markers: tuple[str, ...]) -> bool:
    try:
        tokens = drop_inert_operands(lex(without_heredoc_bodies(command)))
    except ValueError:
        return True
    return any(path_token_targets_control(roots, token, markers) for token in tokens[1:])


# 글을 글로만 받는 피연산자 — 그 자리의 문자열은 실행되지도, 열리지도 않는다. 지금은 커밋과
# 태그 메시지뿐이다 (`-F`는 파일을 받으므로 경로 그대로 검사한다). 짧은 플래그는 뭉쳐 오므로
# (`git commit -am "…"`) 낱글자 `m` 으로 끝나는 뭉치도 같은 자리로 본다.
#
# **하위 명령까지 봐야 한다.** `git` 만 보고 `-m` 을 메시지로 읽으면 `git checkout -m <경로>`
# 처럼 `-m` 이 피연산자를 안 받는 자리에서 바로 뒤 경로가 통째로 사라진다 — 그 한 자리가
# 통제 표면 쓰기를 통과시킨다 (26-08-05 2차 교차검토가 잡은 회귀).
_INERT_SUBCOMMANDS = {"git": {"commit", "tag"}}


_INERT_VALUE_FLAGS = re.compile(r"^(?:-[A-Za-z]*m|--message)$")


_INERT_INLINE_FLAG = "--message="


# 메시지 안의 명령 치환은 **실행된다** — `git commit -m "$(python3 -c '…')"`. 그 자리는
# 글이 아니라 코드라 빼지 않는다.
_SUBSTITUTION = re.compile(r"\$\(|`")


def lex(command: str) -> list[str]:
    """명령을 토큰으로 — 구분자(`|` `&&` `;`)는 **자기 토큰**으로 남는다.

    줄바꿈을 `;` 로 바꾸는 것이 요점이다. `shlex.split` 은 줄바꿈을 그냥 공백으로 삼켜서, 여러
    줄로 적은 명령은 첫 줄의 프로그램 이름이 끝까지 따라다닌다 — 같은 명령이 `;` 로 적으면
    통과하고 줄바꿈으로 적으면 막히는, 이 패치가 없애려던 바로 그 표기 차별이 생긴다.
    인용 안의 줄바꿈도 함께 바뀌지만 그 자리는 글이라 판정이 안 달라진다. `shell_parts` 와
    같은 어휘 규칙이다 (구분자 집합 하나만 쓴다)."""
    lexer = shlex.shlex(re.sub(r"\\\r?\n", " ", command).replace("\n", " ; "), posix=True, punctuation_chars="|&;<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def drop_inert_operands(tokens: list[str]) -> list[str]:
    """실행도 개방도 하지 않는 피연산자를 뺀 토큰들 — 지금은 커밋·태그 메시지뿐이다.

    거기 스친 한 마디 때문에 커밋이 막히면 규칙이 아니라 표기 요령을 가르치고, 실제로 3차
    세션은 매번 표기를 바꿔 우회했다 (26-08-05). 메시지에 든 명령 치환은 예외다 —
    `git commit -m "$(python3 -c '…')"` 의 그 자리는 글이 아니라 실행되는 코드다."""
    kept: list[str] = []
    program, subcommand, skip_next = "", "", False
    for index, token in enumerate(tokens):
        if not program or (kept and kept[-1] in _SEGMENT_SEPARATORS):
            program, subcommand = os.path.basename(token), ""
        elif not subcommand and program and token != tokens[0] and not token.startswith("-"):
            subcommand = token
        if skip_next:
            skip_next = False
            # 구분자는 메시지가 아니다. 삼키면 `git commit -m ; ./w -m <경로>` 처럼 앞이 망가진
            # 명령에서 프로그램 판정이 `git commit` 에 붙박여 뒤 세그먼트의 경로까지 사라진다.
            if _SUBSTITUTION.search(token) or token in _SEGMENT_SEPARATORS:
                kept.append(token)
            continue
        if subcommand in _INERT_SUBCOMMANDS.get(program, ()):
            if token.startswith(_INERT_INLINE_FLAG) and not _SUBSTITUTION.search(token):
                continue
            if _INERT_VALUE_FLAGS.fullmatch(token) and index + 1 < len(tokens):
                skip_next = True
                continue
        kept.append(token)
    return kept


def scannable_text(command: str) -> str:
    """사설 통제 경로 표식을 찾을 글 — 실행도 개방도 하지 않는 자리를 뺀 나머지.

    이 검사는 **판정하는 글과 실행되는 글이 다를 때** 남는 마지막 그물이다. 인자로 푼 토큰이
    경로가 아닌데도 나중에 기장 파일을 쓰는 형태 — `python -c "$PAYLOAD"` ·
    `for P in "…write_text('.asgard/quest/x')…"` — 는 여기서만 잡힌다 (26-08-04 교차검증이
    그 형태로 기장을 실제로 위조했다). 그러니 그물은 남긴다.

    히어독 본문은 **안 뺀다**: 본문은 인자가 아니지만 코드일 수는 있어서, 인자를 뽑는
    자리(`command_targets_control`)와 판단이 갈린다. 파싱이 안 되면 원문을 그대로 돌려준다 —
    못 읽는 글은 좁히지 않는다."""
    try:
        return " ".join(drop_inert_operands(lex(command)))
    except ValueError:
        return command


_RUNNERS = {"uv", "poetry", "pipenv"}


# `run`과 본체 명령 사이에 낄 수 있는 플래그 중 **값을 따로 받지 않고 실행 노출도 넓히지 않는**
# 것만 벗긴다. `--with`(임의 패키지 설치) · `--python`/-p(런타임 내려받기) · `--script` ·
# `--module`/-m · `--env-file` 처럼 값이나 새 실행 통로를 동반하는 플래그는 목록 밖이고,
# 하나라도 보이면 판정은 fail-closed 로 떨어진다 (모르는 래퍼는 통과시키지 않는다).
_RUNNER_INERT_FLAGS = {
    "--no-project",
    "--isolated",
    "--frozen",
    "--locked",
    "--offline",
    "--no-sync",
    "--no-dev",
    "-q",
    "--quiet",
}


def strip_runner(tokens: list[str]) -> list[str] | None:
    """`uv|poetry|pipenv run [무해 플래그…] <명령>`에서 래퍼를 벗겨 본체만 돌려준다.

    벗긴 뒤에는 맨 인터프리터와 **완전히 같은 판정 경로**를 탄다. 이게 요점이다: 래퍼를
    통째로 허용하면 `python3 -c` 에는 걸리는 쓰기 스니펫이 `uv run python -c` 로는 새어
    나가고, 반대로 래퍼를 통째로 막으면 정본 훅 명령(`uv run --no-project python
    <hooks>/quest-log.py append`)이 읽기전용 역할에서 차단돼 역할이 자기 이벤트를 못 남긴다 —
    subagent-gate 가 그 상태의 종료를 거부하므로 양쪽이 막히면 교착이다.

    래퍼가 아니거나 판정할 수 없는 형태면 None (호출자는 계속 진행 → 최종적으로 차단)."""
    if len(tokens) < 3 or os.path.basename(tokens[0]) not in _RUNNERS or tokens[1] != "run":
        return None
    rest = tokens[2:]
    while rest and rest[0].startswith("-"):
        if rest[0] not in _RUNNER_INERT_FLAGS:
            return None
        rest = rest[1:]
    return rest or None


# 세그먼트 구분자 — 각 세그먼트를 독립 판정하므로 허용 명령끼리의 연결은 새 권한을 만들지 않는다.
# 반대로 이를 막으면 `git status --porcelain && git diff` 같은 순수 읽기가 통째로 차단되고, 모델은
# 같은 관측을 변형으로 재시도해 턴을 태운다 (26-07-26 helios 실측: 차단 39건의 최다 사유).
# 단일 `&`(백그라운드)는 구분자가 아니다 — 판정 밖에서 계속 도는 프로세스를 허용하지 않는다.
_SEGMENT_SEPARATORS = {"|", "||", "&&", ";"}


# 폐기 리다이렉션 — /dev/null로 버리거나 스트림을 합치는 형태는 프로젝트 파일을 만들지 않는다.
_DISCARD_REDIRECTION = re.compile(r"\s*(?:\d?>>?\s*/dev/null|\d?>&\s*[12]|<\s*/dev/null)")


def shell_parts(command: str) -> tuple[list[list[str]], bool]:
    """Tokenize pipelines and command sequences, keeping metacharacters inside quotes as data."""
    command = _DISCARD_REDIRECTION.sub("", command)
    if "$(" in command or "`" in command:
        return [], False
    # 줄이음(`\` + 줄바꿈)은 셸이 통째로 지우는 것이지 구분자가 아니다. 먼저 안 지우면 아래
    # 치환이 `\ ; ` 를 만들고, posix shlex 가 그 백슬래시를 탈출부호로 읽어 공백 한 칸짜리
    # 토큰을 남긴 뒤 명령을 두 조각으로 쪼갠다. 그러면 여러 줄로 적은 정본 기장 명령이
    # 미분류로 떨어지고, 읽기 전용 레인이 꺼진 자리에서 `.claude/hooks/quest-log.py` 라는
    # 인자가 통제 표면 갈래에 걸려 퀘스트를 못 연다 (26-08-05 실측 — 이 세션의 첫 명령).
    command = re.sub(r"\\\r?\n", " ", command)
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
