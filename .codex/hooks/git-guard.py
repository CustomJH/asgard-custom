#!/usr/bin/env python3
# Asgard git-guard — Canon Law 3/6 (증거 보존). 되돌릴 수 없는 git 명령을 실행 전에 차단한다.
#
# 헬리오스 교훈(2026-04-27, ref/asgard-helios): 실제 자산을 날린 건 "파괴적" 목록 밖의 평범한
# 명령이었다 — bare `git stash`(전체 트리를 걷어감; 병렬 세션의 미커밋분까지)와 checkout -- <path>.
# stash는 drop/clear 만이 아니라 쓰기 계열 전부(bare/push/save/-u)를 막는다. 읽기·복원 계열
# (list/show/apply/pop/branch)만 통과. 헬리오스는 stash push를 스냅샷 후 허용했지만, 이 레포는
# 병렬 세션이 상시라 스냅샷으로도 부족 — 하드 블록 + wip 브랜치 커밋 유도가 정책이다.
#
# 왜 스크립트 하나로 모든 툴을 받는가: BLOCK 목록이 단일 출처여야 해서다. 툴별로 스크립트를
# 나누면 목록이 서로 어긋나게 드리프트한다. 대신 페이로드 모양으로 훅 프로토콜을 자동 감지한다
# (설치 시 인자·환경변수로 툴을 지정하는 방식보다 배선 실수에 강함):
#   • Claude Code / Codex (PreToolUse): {"tool_input": {"command": ...}} → 차단 = exit 2 + stderr.
#   • Cursor (beforeShellExecution):    {"command": ...}                 → 차단 = stdout {"permission":"deny"}, exit 0.
# 왜 fail-open(오류 시 무조건 allow)인가: 가드 자체가 죽으면 모든 shell 명령이 막혀 사용자를
# 인질로 잡는다. 이 훅은 best-effort 안전망이고, 뚫리면 잃는 것은 "한 번의 경고 기회"뿐이다.
from __future__ import annotations

import json
import os
import re
import shlex
import sys

# 발화 계측은 훅과 함께 깔리는 공용 라이브러리가 쥔다 — 이 훅은 자기 이름만 넘긴다.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.destructive import consent_given, consent_refusal, destructive_reason  # noqa: E402
from asgard_hooklib.firing import event, run  # noqa: E402

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass


# 패턴 공통: `[^|;&]*`는 명령 구분자(| ; &)를 넘지 않게 탐색을 제한한다 —
# `git push && rm -f x`의 `-f`를 push의 플래그로 오인해 차단하는 오탐을 막는다.
_GIT = (
    r"\bgit(?:\s+(?:-C(?:\s+\S+|\S+)|-c(?:\s+\S+|\S+)|--(?:git-dir|work-tree|namespace|config-env)"
    r"(?:=\S+|\s+\S+)|--(?:exec-path|super-prefix)=\S+|-(?:p|P)|--(?:no-pager|paginate|bare|literal-pathspecs|no-replace-objects)))*\s+"
)
# 표를 대기 전에 명령을 **한 번** 편다 — 인용부호와 쉼표를 공백으로. 인터프리터가 리스트로
# 넘기는 형태(`run(['git','push','--force'])`)에는 토큰 사이에 공백이 없고 `','` 가 있어서,
# 아래 스무 개 패턴이 저마다 `\s` 를 쓰는 한 자리씩 전부 빗나갔다. 패턴마다 구분자를 넓히면
# 다음 패턴에서 같은 구멍이 다시 난다 — 세 번 연속 그렇게 났다 (26-08-05 재판정). 입구에서
# 한 번 펴면 스무 개가 손 안 대고 같이 맞는다.
#
# 이 정규화는 **불투명 명령에만** 쓴다. 평범한 명령문에 대면 인용 안의 글이 명령으로 읽혀
# `grep -n "git stash" <파일>` 이 막힌다 — 토큰 분류기가 이미 그 자리를 정확히 본다.
# 역따옴표도 함께 편다 — `` `rm -rf .git` `` 은 `.git` 뒤에 공백도 끝도 없어서 그 항목의
# 경계 요구(`(?:\s|$)`)를 못 넘겼다. 다른 파괴 항목은 경계를 안 요구해 이미 잡혔다 (26-08-05).
_TABLE_SEPARATORS = re.compile(r"['\"`,]+")


def _flattened(command: str) -> str:
    return _TABLE_SEPARATORS.sub(" ", command)


BLOCK = [
    # 사이 토큰을 건너뛰는 자리는 **한 토큰씩** 건너뛴다. `(?:\s+[^|;&]+)*` 는 안쪽이 공백까지
    # 먹어서 토큰 n개를 나누는 경우의 수만큼 되짚었다 — 역따옴표가 든 316자 `git commit` 하나가
    # PreToolUse 훅 상한 600초를 통째로 태우고 timedOut 으로 끝났다 (26-08-05 실측, 세션
    # 645d7ee9 hook_cancelled durationMs=600026). 안쪽에서 공백을 빼면 경계가 한 자리로 정해져
    # 되짚을 갈래가 없어지고, 표가 받는 문자열의 집합은 그대로다.
    (r"\bgit(?:\s+[^\s|;&]+)*\s+-c(?:\s+|\S*)alias\.", "inline destructive alias"),
    (_GIT + r"push\b[^|;&]*\s-(-force\b|f\b)", "force-push"),  # 원격 히스토리 덮어쓰기
    (
        _GIT + r"push\b[^|;&]*--force-with-lease\b",
        "force-push",
    ),  # lease도 결국 덮어쓰기 — 의도를 명시하려고 별도 항목
    (_GIT + r"reset\s+--hard\b", "reset --hard"),  # 워킹트리+인덱스 즉시 소실
    (
        _GIT + r"checkout\b[^|;&]*\s--(?:\s|$)",
        "checkout -- (discard worktree)",
    ),  # 파일/트리 복원은 미커밋 변경을 조용히 소실 — 브랜치 전환(checkout name)은 허용
    (_GIT + r"checkout\b[^|;&]*(?:\s-f\b|--force\b)", "checkout force (discard worktree)"),
    (_GIT + r"switch\b[^|;&]*(?:\s-f\b|--force\b|--discard-changes\b)", "switch force (discard worktree)"),
    (_GIT + r"restore\b", "restore (discard worktree)"),  # --source/--worktree 조합 포함, 보수적으로 전부 차단
    (
        _GIT + r"clean\s+-[a-zA-Z]*f",
        "clean -f",
    ),  # 언트래킹 파일 영구 삭제; [a-zA-Z]*f로 -fd, -xf 등 조합 플래그도 포착
    (_GIT + r"branch\s+-D\b", "branch -D"),  # 병합 확인 없는 강제 삭제 (-d는 안전하므로 허용)
    (_GIT + r"(rebase|filter-branch|filter-repo)\b", "history rewrite"),  # 커밋 해시가 바뀜 = 증거 재작성
    (_GIT + r"update-ref\s+-d\b", "update-ref -d"),  # ref 직접 삭제 (위 우회 경로)
    (
        # 쓰기 계열 stash 전부 — bare/push/save/-u/drop/clear. 읽기·복원(list/show/apply/pop/branch/
        # create/store)만 lookahead로 통과. bare stash는 전체 트리를 걷어가 병렬 세션 미커밋분까지 소실.
        _GIT + r"stash\b(?!\s+(?:list|show|apply|pop|branch|create|store)\b)",
        "stash (worktree sweep)",
    ),
    (_GIT + r"reflog\s+(delete|expire)\b", "drop history"),  # 복구 지점 제거 — Law 3의 마지막 보루
    (_GIT + r"rm\b[^|;&]*(?:\s-[a-zA-Z]*[rf]|\s--force\b)", "rm force (worktree delete)"),  # 수정분 무시 삭제
    (
        # .git 디렉터리 자체 삭제 = 저장소 전체 증거 파기. .github/.gitignore는 (/|공백|끝) 경계로 제외.
        r"\brm\b[^|;&]*\s(?:\S*/)?\.git(?:/\S*)?(?:\s|$)",
        "delete .git (repository destruction)",
    ),
]


_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
_GLOBAL_FLAGS = {
    "-p",
    "-P",
    "--paginate",
    "--no-pager",
    "--no-replace-objects",
    "--no-lazy-fetch",
    "--no-optional-locks",
    "--bare",
    "--literal-pathspecs",
    "--glob-pathspecs",
    "--noglob-pathspecs",
    "--icase-pathspecs",
    "--html-path",
    "--man-path",
    "--info-path",
    "--exec-path",
}


def _segments(command: str) -> list[list[str]]:
    """Shell-tokenize enough to preserve quoted paths and separate command chains."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;()<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and all(char in "|&;()<>" for char in token):
            if segments[-1]:
                segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def _git_subcommand(words: list[str], start: int) -> tuple[str, list[str], str | None]:
    index = start + 1
    while index < len(words):
        token = words[index]
        if token in _GLOBAL_WITH_VALUE:
            if index + 1 >= len(words):
                return "", [], "malformed git global option"
            value = words[index + 1]
            if token in {"-c", "--config-env"} and value.casefold().startswith("alias."):
                return "", [], "inline destructive alias"
            index += 2
            continue
        if (token.startswith("-C") or token.startswith("-c")) and len(token) > 2:
            if token.casefold().startswith("-calias."):
                return "", [], "inline destructive alias"
            index += 1
            continue
        if token.casefold().startswith("--config-env=alias."):
            return "", [], "inline destructive alias"
        if token.startswith(("--git-dir=", "--work-tree=", "--namespace=", "--config-env=")):
            index += 1
            continue
        if token.startswith(("--exec-path=", "--super-prefix=", "--list-cmds=", "--attr-source=")):
            index += 1
            continue
        if token in _GLOBAL_FLAGS:
            index += 1
            continue
        if token.startswith("-"):
            return "", [], "unclassified git global option"
        return token, words[index + 1 :], None
    return "", [], None


# 읽기·복원 계열만 통과 — 나머지 stash 서브커맨드(bare/push/save 및 -u 류 플래그 시작)는 전부
# 워킹트리를 걷어가므로 차단. create/store는 트리를 건드리지 않는 스냅샷용 저수준 명령.
_STASH_READONLY = {"list", "show", "apply", "pop", "branch", "create", "store"}

# rm 경로가 .git 자체를 겨냥하는지 — .github/.gitignore는 뒤가 word 문자라 매치되지 않는다.
_DOT_GIT = re.compile(r"(^|/)\.git(/|$)")


def _combined_short_flag(args: list[str], flag: str) -> bool:
    return any(
        token == f"-{flag}" or (token.startswith("-") and not token.startswith("--") and flag in token[1:])
        for token in args
    )


def _destructive_git(subcommand: str, args: list[str]) -> str | None:
    if subcommand == "push" and (
        _combined_short_flag(args, "f")
        or any(token == "--force" or token.startswith("--force-with-lease") for token in args)
    ):
        return "force-push"
    if subcommand == "reset" and "--hard" in args:
        return "reset --hard"
    if subcommand == "checkout" and ("--" in args or _combined_short_flag(args, "f") or "--force" in args):
        return "checkout (discard worktree)"
    if subcommand == "switch" and (_combined_short_flag(args, "f") or "--force" in args or "--discard-changes" in args):
        return "switch force (discard worktree)"
    if subcommand == "restore":
        return "restore (discard worktree)"
    if subcommand == "clean" and (_combined_short_flag(args, "f") or "--force" in args):
        return "clean -f"
    if subcommand == "branch" and ("-D" in args or ("--delete" in args and "--force" in args)):
        return "branch force delete"
    if subcommand in {"rebase", "filter-branch", "filter-repo"}:
        return "history rewrite"
    if subcommand == "update-ref" and ("-d" in args or "--delete" in args):
        return "update-ref delete"
    if subcommand == "stash":
        if args and args[0] in {"drop", "clear"}:
            return "drop history"
        if not args or args[0] not in _STASH_READONLY:
            return "stash (worktree sweep)"
    if subcommand == "reflog" and args and args[0] in {"delete", "expire"}:
        return "drop history"
    if subcommand == "rm" and (_combined_short_flag(args, "f") or _combined_short_flag(args, "r") or "--force" in args):
        return "rm force (worktree delete)"
    return None


# 토큰으로 못 가르는 텍스트 — 여기서만 아래 정규식 표를 명령문 전체에 댄다.
#
# 무엇을 담는가: 셸이나 인터프리터가 **문자열 인자를 다시 명령으로 펴는** 형태 전부. 프로그램
# 본문이 통째로 한 토큰이라 위 토큰 분류기가 `git` 을 못 본다. 처음 낸 목록은 `sh -c` 계열만
# 담아서 인라인 코드(`python -c` · `node -e`)와 파이프 실행(`printf … | sh`)이 빠져 있었다
# (26-08-04 교차검토 지적) — 같은 원리인데 철자만 달랐다.
# `secret_guard._OPAQUE_CORE` 와 글자까지 같아야 한다 — 두 가드가 같은 질문에 다른 답을 들면
# 한쪽에서 막힌 것이 다른 쪽에서는 통과한다. 훅은 배포 디렉터리에서 서로를 임포트하지 못하므로
# (파일 이름이 붙임표다) 같은 글자를 두 벌 두고 시험이 동일성을 고정한다.
_OPAQUE_CORE = (
    r"\$\(|`|\beval\b|\b(?:ba|z|k)?sh\s+-[a-z]*c[a-z]*\b|\bxargs\b"
    r"|\bpython[0-9.]*\s+-c\b|\bnode\s+-(?:e|-eval)\b|\bperl\s+-e\b|\bruby\s+-e\b"
    r"|\|\s*(?:ba|z|k)?sh\b"
)
_OPAQUE = re.compile(_OPAQUE_CORE)
# 프로그램 이름 자리의 셸 확장 — `g=git; $g stash` 처럼 실행자를 변수에 담아 부르는 형태다.
# 토큰 분류기는 `$g` 를 보고 git 이 아니라고 판단하고, `_OPAQUE` 는 `$(` 만 알아서 정규식 표도
# 안 댔다 (26-08-05 감사). 피연산자 자리의 `$VAR` 는 흔하고 무해하므로 **머리 토큰만** 본다.
_HEAD_EXPANSION = re.compile(r"^\$\{?[A-Za-z_]")
# 인터프리터가 파일계를 직접 부수는 형태. git 토큰도 `rm` 도 없어 위의 두 갈래가 모두 비껴간다
# (26-08-05 감사: `python3 -c "import shutil;shutil.rmtree('.git')"`).
_FS_DESTROY = re.compile(
    r"\b(?:rmtree|removedirs|rmdir|unlink|remove|rename|replace|move|rmSync|rmdirSync|rimraf)\s*\("
)


def _interpreter_repo_destruction(command: str) -> str | None:
    """인터프리터 코드가 `.git` 을 지우거나 옮기는가.

    문자열을 다시 코드로 펴는 명령에서만 본다 — 평범한 명령문에 그대로 대면 `.git` 을
    **설명하는** 문서 한 줄이 파괴로 읽힌다."""
    if not _OPAQUE.search(command) or not _FS_DESTROY.search(command):
        return None
    return "delete .git (repository destruction)" if _DOT_GIT_LITERAL.search(command) else None


# 코드 안의 `.git` 경로 리터럴 — 따옴표 안이든 밖이든, 경로 경계에 있을 때만.
_DOT_GIT_LITERAL = re.compile(r"(?:^|[\s'\"(/])\.git(?:[\s'\")/]|$)")


_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_VAR_USE = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")


def _resolve_head_vars(segments: list[list[str]]) -> list[list[str]]:
    """실행자 자리의 변수를 한 겹 편다 — `g=git; $g stash` 는 `git stash` 다.

    토큰 분류기는 `$g` 를 보고 git 이 아니라고 판단했고, 정규식 표는 `git` 과 하위 명령이
    텍스트상 떨어져 있어(`g=git; $g stash`) 역시 못 봤다 — 두 갈래가 같은 자리에서 함께
    비껴갔다 (26-08-05 감사).

    한 겹만, 리터럴 대입만 편다. 값이 또 변수거나 명령 치환이면 펴지 않고 그대로 두는데,
    그 형태는 `_OPAQUE`·`_HEAD_EXPANSION` 이 이미 정규식 표로 넘긴다."""
    known: dict[str, str] = {}
    out: list[list[str]] = []
    for segment in segments:
        rest = list(segment)
        while rest and (m := _ASSIGN.match(rest[0])):
            name, value = m.group(1), m.group(2)
            if value and not value.startswith("$") and "`" not in value:
                known[name] = value
            rest = rest[1:]
        if rest and (use := _VAR_USE.match(rest[0])) and use.group(1) in known:
            rest = [known[use.group(1)], *rest[1:]]
        out.append(rest or segment)
    return out


def blocked_reason(command: str) -> str | None:
    if reason := _interpreter_repo_destruction(command):
        return reason
    segments = _resolve_head_vars(_segments(command))
    # 머리 토큰이 셸 확장이면 그 조각은 무엇을 부르는지 읽히지 않는다 — 토큰이 증거가 아니므로
    # 아래 정규식 표를 대는 쪽으로 넘긴다 (위에서 편 것은 이미 실명으로 바뀌었다).
    opaque_head = any(segment and _HEAD_EXPANSION.match(segment[0]) for segment in segments)
    for segment in segments:
        for index, token in enumerate(segment):
            base = os.path.basename(token)
            if base == "rm":
                if any(_DOT_GIT.search(arg) for arg in segment[index + 1 :] if not arg.startswith("-")):
                    return "delete .git (repository destruction)"
                continue
            if base != "git":
                continue
            subcommand, args, error = _git_subcommand(segment, index)
            if error:
                return error
            reason = _destructive_git(subcommand, args)
            if reason:
                return reason
    # 정규식 표는 **토큰으로 못 읽은 명령**에만 댄다. 명령문 전체를 늘 훑던 종전 갈래는 인용
    # 안쪽의 글자까지 명령으로 읽어서, 파일에서 문구를 찾는 `grep -n "git stash" <파일>` 이
    # 워크트리 소실로 차단됐다 (26-08-04 실측). 위 토큰 분류기가 같은 표를 이미 전부 갖고 있고
    # (`_destructive_git`), 모르는 전역 옵션은 error 로 fail-closed 하므로 파싱이 된 명령에서
    # 이 표는 판정을 더하지 않고 오탐만 더한다. 파싱이 안 됐거나 셸이 문자열을 다시 명령으로
    # 펴는 형태($(...)·eval·sh -c·xargs)에서는 그대로 댄다 — 거기서는 토큰이 증거가 아니다.
    if not segments or opaque_head or _OPAQUE.search(command):
        flattened = _flattened(command)
        for pattern, label in BLOCK:
            if re.search(pattern, command) or re.search(pattern, flattened):
                return label
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    # 프로토콜 감지: Cursor는 command를 최상위에, Claude Code / Codex는 tool_input 안에 넣는다.
    # "tool_input" 키 유무가 두 스키마를 가르는 가장 단순하고 안정적인 판별자다.
    cursor = "tool_input" not in data
    # str(... or ""): command가 없거나 문자열이 아닌 페이로드에도 죽지 않고 "매치 없음"으로 흘러간다.
    cmd = str((data.get("command") if cursor else (data.get("tool_input") or {}).get("command")) or "")

    label = blocked_reason(cmd)
    if label:
        # 가르치는 거부 — 워크트리를 걷어가는 계열은 안전 대안까지 제시해 재시도 루프를 끊는다.
        hint = ""
        if "stash" in label or "worktree" in label or "discard" in label:
            hint = " Safer: commit WIP to a branch (git switch -c wip/<name> && git commit), or operate file-by-file."
        if cursor:
            sys.stdout.write(
                json.dumps(
                    {
                        "permission": "deny",
                        # 필드명은 snake_case가 Cursor 계약이다 (cursor.com/docs/hooks, 26-07-27 확인) —
                        # camelCase로 보내면 차단은 되지만 가르치는 문장이 통째로 버려진다.
                        "user_message": "Asgard Canon Law 3/6 — irreversible git op (" + label + "). Blocked.",
                        "agent_message": "This " + label + " was blocked by the Asgard Canon (Law 3/6). "
                        "Get Odin's explicit per-action consent; do not retry." + hint,
                    },
                    separators=(",", ":"),
                )
            )
            sys.exit(0)
        # Claude Code / Codex: exit 2가 차단 신호, stderr가 에이전트에게 그대로 전달된다.
        print(
            "Asgard Canon Law 3/6 — irreversible git op (" + label + "). "
            "Get Odin's explicit consent first (per action, per target)." + hint,
            file=sys.stderr,
        )
        sys.exit(2)

    # 동의로 열리는 파괴 연산 — 위 표와 달리 이쪽은 정당한 이유로 실행될 때가 있어서, 차단이
    # 아니라 한 번 멈춰 Odin 에게 물을 자리를 만든다. 동의로 통과한 호출은 세어야 뜻이 있다.
    if reason := destructive_reason(cmd):
        root = os.environ.get("CLAUDE_PROJECT_DIR") or str(data.get("cwd") or os.getcwd())
        if not consent_given(cmd):
            event(root, "git-guard", "gate_block", "destructive-consent", [reason])
            message = consent_refusal(reason, cmd)
            if cursor:
                sys.stdout.write(
                    json.dumps(
                        {"permission": "deny", "user_message": message, "agent_message": message},
                        separators=(",", ":"),
                    )
                )
                sys.exit(0)
            print(message, file=sys.stderr)
            sys.exit(2)
        event(root, "git-guard", "consent_used", "destructive-consent", [reason])

    if cursor:  # Cursor는 침묵을 허용으로 안 본다 — 명시적 allow 응답이 프로토콜 요구사항.
        sys.stdout.write(json.dumps({"permission": "allow"}, separators=(",", ":")))
    sys.exit(0)


if __name__ == "__main__":
    run("git-guard", main)
