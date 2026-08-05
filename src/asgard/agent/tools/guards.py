"""명령 하나를 실행 전에 판정하는 자리 — 훅 위임, 파괴적 연산, 통제 표면.

훅(`git-guard`·`release-guard`)에 다시 물어보는 것이 요점이다: 네이티브 실행이 자체 판정을
따로 들면 같은 명령이 호스트에서는 막히고 여기서는 통과하는 두 답이 생긴다."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys


def _hook_guard(root: str, module: str, tool_input: dict) -> str | None:
    """가드 훅을 배포 형태(subprocess stdin 계약)로 통과. 차단이면 사유 문자열, 통과면 None.
    fail-open (훅 오류 = 통과) — 로직 중복 금지, 훅이 단일 출처.

    훅은 아스가르드 자신이고 프로파일 홈에서 설정을 읽는다. `profiles.scoped()`가 contextvar라
    자식에게 안 따라가므로 env로 명시해 넘긴다 — 안 넘기면 에이전트 A의 세션을 B의 설정으로
    판정하게 된다."""
    from ...profiles import subprocess_env

    try:
        p = subprocess.run(
            [sys.executable, "-m", module],
            input=json.dumps({"tool_input": tool_input}),
            capture_output=True,
            text=True,
            timeout=10,
            cwd=root,
            encoding="utf-8",
            errors="replace",
            env=subprocess_env(),
        )
        if p.returncode != 0:
            return (p.stderr or p.stdout or module + " 차단").strip()[:500]
    except Exception:
        pass
    return None


def _git_guard(root: str, command: str) -> str | None:
    return _hook_guard(root, "asgard.hooks.git_guard", {"command": command})


def _release_guard(root: str, command: str) -> str | None:
    return _hook_guard(root, "asgard.hooks.release_guard", {"command": command})


# 셸 파괴 명령 가드 (Canon 3) — git 계열은 git-guard 훅이 단일 출처, 여기는 비-git만.
# 루트 안 rm -rf는 허용 (스크래치 정리는 정당 + git이 복구 지점) — 루트 밖·조상 경로만 차단.
_DEV_DESTRUCTIVE = re.compile(r"\bmkfs(\.\w+)?\b|\bdd\b[^|;&]*\bof=/dev/")
# `readonly_guard._CONTROL_PATHS`·`_BOUNDARY_FILES` 와 같은 표 — 호스트 세 모드와 네이티브가
# 같은 자리를 닫는다. 닫는 것은 판정의 물리 대조가 못 보는 하네스 상태(`.asgard/**`)와 이
# 격리의 뿌리를 정하는 설정 파일 둘뿐이고, 나머지 스캐폴드는 평범한 작업 대상이다.
_CONTROL_PATHS = (".asgard",)
_BOUNDARY_FILES = (".claude/settings.json", ".claude/settings.local.json")


def _destructive_guard(root: str, cmd: str) -> str | None:
    """rm -rf 급 삭제가 프로젝트 루트 밖을 노리면 차단. 파싱 불가 세그먼트는 fail-open
    (lagom: 셸 문법 전체 해석은 안 한다 — 게이트·git이 최종 방어선)."""
    if _DEV_DESTRUCTIVE.search(cmd):
        return f"파괴 명령 차단: {cmd[:80]} (Canon 3 — 디바이스 파괴는 Odin 동의로도 네이티브 루프 밖)"
    rr = os.path.realpath(root)
    for seg in re.split(r"[;&|]+", cmd):
        try:
            toks = shlex.split(seg)
        except ValueError:
            continue
        if not toks or os.path.basename(toks[0]) != "rm":
            continue
        flags = "".join(t.lstrip("-") for t in toks[1:] if t.startswith("-")).lower()
        if not ("r" in flags and "f" in flags):
            continue
        for t in toks[1:]:
            if t.startswith("-"):
                continue
            p = os.path.realpath(os.path.expanduser(t) if t.startswith(("~", "/")) else os.path.join(root, t))
            if p != rr and not p.startswith(rr + os.sep):
                return f"rm -rf가 프로젝트 루트 밖을 대상: {t} (Canon 3 — Odin 명시 동의 필요)"
    return None


def _has_dynamic_expansion(command: str) -> bool:
    """동적 경로를 만들 수 있는 셸 확장 감지. 작은따옴표 안의 정규식 `$` 등은 리터럴이다."""
    single = False
    escaped = False
    for char in command:
        if escaped:
            escaped = False
        elif char == "\\" and not single:
            escaped = True
        elif char == "'":
            single = not single
        elif not single and char in ("$", "`"):
            return True
    return False


def _scope_guard(root: str, command: str) -> str | None:
    """명시 경로·따옴표 결합·셸 확장으로 프로젝트/제어 경계를 넘는 명령을 거부."""
    if _has_dynamic_expansion(command):
        return (
            "동적 셸 확장($/backtick)은 프로젝트 경로 경계를 검증할 수 없어 차단 — 리터럴 경로로"
            " 다시 써라. 임시 파일·캐시는 프로젝트 내부 .gitignore 경로(예: .cache/)를 쓴다"
        )
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = [token for token in lexer if not all(char in "|&;<>()" for char in token)]
    except ValueError:
        return "셸 명령을 안전하게 해석할 수 없어 차단"

    rr = os.path.realpath(root)
    for token in tokens:
        values = [token]
        if "=" in token:
            values.append(token.split("=", 1)[1])
        for value in values:
            normalized = value.replace("\\", "/")
            if normalized.startswith(("http://", "https://")):
                continue
            candidate = os.path.realpath(
                os.path.expanduser(value) if value.startswith(("~", "/")) else os.path.join(root, value)
            )
            if any(
                candidate == os.path.realpath(os.path.join(root, marker))
                or candidate.startswith(os.path.realpath(os.path.join(root, marker)) + os.sep)
                for marker in (*_CONTROL_PATHS, *_BOUNDARY_FILES)
            ):
                return "Asgard 제어 경로는 모델 Bash에서 접근할 수 없음 — 하니스/전용 명령만 사용"
            if (
                (normalized.startswith(("~", "/", "../")) or normalized == ".." or "/../" in normalized)
                and candidate != rr
                and not candidate.startswith(rr + os.sep)
            ):
                return (
                    f"Bash 경로가 프로젝트 루트를 벗어남: {value} — 임시 파일·캐시가 필요하면"
                    " 프로젝트 내부 .gitignore 경로(예: .cache/)를 쓰라"
                )
    # ponytail: 셸은 OS 샌드박스가 아니다. 더 강한 격리가 필요하면 플랫폼 sandbox 프로세스로 교체.
    return None


def validate_bash_command(root: str, command: str) -> str | None:
    """Return a deterministic block reason without executing the command."""
    return (
        _scope_guard(root, command)
        or _git_guard(root, command)
        or _release_guard(root, command)
        or _destructive_guard(root, command)
    )
