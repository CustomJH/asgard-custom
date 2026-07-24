#!/usr/bin/env python3
# Asgard git-guard — Canon Law 3/6 (증거 보존). 되돌릴 수 없는 git 명령을 실행 전에 차단한다.
#
# 헬리오스 교훈(2026-04-27, ref/asgard-helios): 실제 자산을 날린 건 "파괴적" 목록 밖의 평범한
# 명령이었다 — bare `git stash`(전체 트리를 걷어감; 병렬 세션의 미커밋분까지)와 checkout -- <path>.
# stash 는 drop/clear 만이 아니라 쓰기 계열 전부(bare/push/save/-u)를 막는다. 읽기·복원 계열
# (list/show/apply/pop/branch)만 통과. 헬리오스는 stash push 를 스냅샷 후 허용했지만, 이 레포는
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

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
    except Exception:
        pass


# 패턴 공통: `[^|;&]*` 는 명령 구분자(| ; &)를 넘지 않게 탐색을 제한한다 —
# `git push && rm -f x` 의 `-f` 를 push 의 플래그로 오인해 차단하는 오탐을 막는다.
_GIT = (
    r"\bgit(?:\s+(?:-C(?:\s+\S+|\S+)|-c(?:\s+\S+|\S+)|--(?:git-dir|work-tree|namespace|config-env)"
    r"(?:=\S+|\s+\S+)|--(?:exec-path|super-prefix)=\S+|-(?:p|P)|--(?:no-pager|paginate|bare|literal-pathspecs|no-replace-objects)))*\s+"
)
BLOCK = [
    (r"\bgit(?:\s+[^|;&]+)*\s+-c(?:\s+|\S*)alias\.", "inline destructive alias"),
    (_GIT + r"push\b[^|;&]*\s-(-force\b|f\b)", "force-push"),  # 원격 히스토리 덮어쓰기
    (
        _GIT + r"push\b[^|;&]*--force-with-lease\b",
        "force-push",
    ),  # lease 도 결국 덮어쓰기 — 의도를 명시하려고 별도 항목
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
    ),  # 언트래킹 파일 영구 삭제; [a-zA-Z]*f 로 -fd, -xf 등 조합 플래그도 포착
    (_GIT + r"branch\s+-D\b", "branch -D"),  # 병합 확인 없는 강제 삭제 (-d 는 안전하므로 허용)
    (_GIT + r"(rebase|filter-branch|filter-repo)\b", "history rewrite"),  # 커밋 해시가 바뀜 = 증거 재작성
    (_GIT + r"update-ref\s+-d\b", "update-ref -d"),  # ref 직접 삭제 (위 우회 경로)
    (
        # 쓰기 계열 stash 전부 — bare/push/save/-u/drop/clear. 읽기·복원(list/show/apply/pop/branch/
        # create/store)만 lookahead 로 통과. bare stash 는 전체 트리를 걷어가 병렬 세션 미커밋분까지 소실.
        _GIT + r"stash\b(?!\s+(?:list|show|apply|pop|branch|create|store)\b)",
        "stash (worktree sweep)",
    ),
    (_GIT + r"reflog\s+(delete|expire)\b", "drop history"),  # 복구 지점 제거 — Law 3 의 마지막 보루
    (_GIT + r"rm\b[^|;&]*(?:\s-[a-zA-Z]*[rf]|\s--force\b)", "rm force (worktree delete)"),  # 수정분 무시 삭제
    (
        # .git 디렉터리 자체 삭제 = 저장소 전체 증거 파기. .github/.gitignore 는 (/|공백|끝) 경계로 제외.
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
# 워킹트리를 걷어가므로 차단. create/store 는 트리를 건드리지 않는 스냅샷용 저수준 명령.
_STASH_READONLY = {"list", "show", "apply", "pop", "branch", "create", "store"}

# rm 경로가 .git 자체를 겨냥하는지 — .github/.gitignore 는 뒤가 word 문자라 매치되지 않는다.
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


def blocked_reason(command: str) -> str | None:
    for segment in _segments(command):
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
    for pattern, label in BLOCK:  # defense in depth for unusual shell text
        if re.search(pattern, command):
            return label
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    # 프로토콜 감지: Cursor 는 command 를 최상위에, Claude Code / Codex 는 tool_input 안에 넣는다.
    # "tool_input" 키 유무가 두 스키마를 가르는 가장 단순하고 안정적인 판별자다.
    cursor = "tool_input" not in data
    # str(... or ""): command 가 없거나 문자열이 아닌 페이로드에도 죽지 않고 "매치 없음"으로 흘러간다.
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
                        "userMessage": "Asgard Canon Law 3/6 — irreversible git op (" + label + "). Blocked.",
                        "agentMessage": "This " + label + " was blocked by the Asgard Canon (Law 3/6). "
                        "Get Odin's explicit per-action consent; do not retry." + hint,
                    },
                    separators=(",", ":"),
                )
            )
            sys.exit(0)
        # Claude Code / Codex: exit 2 가 차단 신호, stderr 가 에이전트에게 그대로 전달된다.
        print(
            "Asgard Canon Law 3/6 — irreversible git op (" + label + "). "
            "Get Odin's explicit consent first (per action, per target)." + hint,
            file=sys.stderr,
        )
        sys.exit(2)

    if cursor:  # Cursor 는 침묵을 허용으로 안 본다 — 명시적 allow 응답이 프로토콜 요구사항.
        sys.stdout.write(json.dumps({"permission": "allow"}, separators=(",", ":")))
    sys.exit(0)


if __name__ == "__main__":
    main()
