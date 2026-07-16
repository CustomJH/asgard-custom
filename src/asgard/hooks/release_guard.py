#!/usr/bin/env python3
# Asgard release-guard — 부작용 승인 모델 (환경 × 외부 부작용). 외부 공개 부작용을 가진 명령
# (패키지 publish / 이미지 push / git tag push / deploy)을 실행 전에 차단한다.
#
# 근거: 딜리버리 계약(asgard-thor·asgard-eitri) — "publish·push·deploy 는 직접 실행 금지,
# 실행 계획(대상·영향·되돌리기)을 반환하고 승인은 Odin 몫" — 을 프롬프트가 아니라 도구로 강제.
# 로컬 빌드·테스트·dry-run 은 건드리지 않는다: 여기 잡히는 것은 조직 밖으로 나가는 명령뿐이다.
#
# 프로토콜·fail-open 원리는 git-guard 와 동일 (단일 스크립트, 페이로드 모양으로 툴 자동 감지):
#   • Claude Code / Codex (PreToolUse): {"tool_input": {"command": ...}} → 차단 = exit 2 + stderr.
#   • Cursor (beforeShellExecution):    {"command": ...}                 → 차단 = stdout {"permission":"deny"}, exit 0.
# 가드 자체가 죽으면 모든 명령이 막혀 사용자를 인질로 잡으므로 오류 시 무조건 allow.
from __future__ import annotations

import json
import os
import shlex
import sys

_WRAPPERS = {"sudo", "command", "exec", "time", "nohup", "env"}


def _segments(command: str) -> list[list[str]]:
    """Shell-tokenize enough to separate command chains (git-guard 와 동일 접근)."""
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


def _program(segment: list[str]) -> tuple[str, list[str]]:
    """세그먼트의 실행 프로그램(basename)과 인자. 선행 VAR=… 대입·래퍼(sudo 등)는 건너뛴다.
    프로그램 위치를 세그먼트 선두로 한정하는 이유: `grep "npm publish" README` 같은
    인용·언급을 차단하지 않기 위해 (실행되는 것만 잡는다)."""
    index = 0
    while index < len(segment):
        token = segment[index]
        if "=" in token and not token.startswith("-") and token.split("=", 1)[0].isidentifier():
            index += 1  # 환경변수 대입 prefix
            continue
        base = os.path.basename(token)
        if base in _WRAPPERS:
            index += 1
            continue
        if token.startswith("-"):
            index += 1  # 래퍼(env -i 등)의 플래그
            continue
        return base, segment[index + 1 :]
    return "", []


def _subcommand(args: list[str]) -> str:
    for token in args:
        if not token.startswith("-"):
            return token
    return ""


# 프로그램 → (판정 함수). 라벨 4류: package publish / image push / git tag push / deploy.
_PUBLISH_SUBCOMMAND = {
    "npm": "publish",
    "pnpm": "publish",
    "cargo": "publish",
    "uv": "publish",
    "poetry": "publish",
    "flit": "publish",
    "hatch": "publish",
}
_DEPLOY_SUBCOMMANDS = {
    "kubectl": {"apply", "delete", "patch", "scale", "rollout", "drain"},
    "oc": {"apply", "delete", "patch", "scale", "rollout", "drain"},
    "terraform": {"apply", "destroy"},
    "tofu": {"apply", "destroy"},
    "pulumi": {"up", "destroy"},
    "fly": {"deploy"},
    "flyctl": {"deploy"},
    "netlify": {"deploy"},
    "firebase": {"deploy"},
    "wrangler": {"deploy", "publish"},
    "cdk": {"deploy"},
    "serverless": {"deploy"},
    "sls": {"deploy"},
    "eb": {"deploy"},
    "kamal": {"deploy"},
}
_IMAGE_PUSH = {"docker", "podman", "nerdctl"}


def _reason(prog: str, args: list[str]) -> str | None:
    sub = _subcommand(args)
    nonflag = [t for t in args if not t.startswith("-")]

    if _PUBLISH_SUBCOMMAND.get(prog) == sub:
        return "package publish"
    if prog == "yarn" and (sub == "publish" or (sub == "npm" and len(nonflag) > 1 and nonflag[1] == "publish")):
        return "package publish"
    if prog == "gem" and sub == "push":
        return "package publish"
    if prog == "twine" and sub == "upload":
        return "package publish"
    if prog in {"mvn", "mvnw"} and "deploy" in nonflag:
        return "package publish"
    if prog in {"gradle", "gradlew"} and any("publish" in t.lower() and "local" not in t.lower() for t in nonflag):
        return "package publish"  # publishToMavenLocal 은 로컬 — 허용
    if prog == "dotnet" and sub == "nuget" and "push" in nonflag:
        return "package publish"
    if prog == "helm":
        if sub == "push":
            return "package publish"
        if sub in {"install", "upgrade", "uninstall", "rollback"}:
            return "deploy"

    if prog in _IMAGE_PUSH:
        if sub == "push" or (sub == "compose" and "push" in nonflag):
            return "image push"
        if sub == "buildx" and "--push" in args:
            return "image push"
    if prog == "crane" and sub in {"push", "copy"}:
        return "image push"

    if prog == "git" and sub == "push":
        if any(t in {"--tags", "--follow-tags"} for t in args) or any("refs/tags/" in t for t in args):
            return "git tag push"  # 브랜치 push 는 일상 흐름 — 태그(=릴리스 공표)만 잡는다

    if sub in _DEPLOY_SUBCOMMANDS.get(prog, ()):
        return "deploy"
    if prog == "vercel" and (sub in {"", "deploy"} or "--prod" in args):
        return "deploy"  # 인자 없는 `vercel` 도 배포다
    if prog == "gcloud" and "deploy" in nonflag:
        return "deploy"
    return None


def blocked_reason(command: str) -> str | None:
    for segment in _segments(command):
        prog, args = _program(segment)
        if not prog:
            continue
        reason = _reason(prog, args)
        if reason:
            return reason
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    cursor = "tool_input" not in data
    cmd = str((data.get("command") if cursor else (data.get("tool_input") or {}).get("command")) or "")

    label = blocked_reason(cmd)
    if label:
        if cursor:
            sys.stdout.write(
                json.dumps(
                    {
                        "permission": "deny",
                        "userMessage": "Asgard release-guard — external side effect (" + label + "). Blocked.",
                        "agentMessage": "This " + label + " was blocked by the Asgard side-effect gate. "
                        "Return an execution plan (target / impact / rollback) and get Odin's explicit "
                        "per-action approval; do not retry.",
                    },
                    separators=(",", ":"),
                )
            )
            sys.exit(0)
        print(
            "Asgard release-guard — 외부 공개 부작용 (" + label + "). "
            "실행 계획(대상·영향·되돌리기)을 반환하고 Odin의 명시적 승인을 받으세요 (매 건, 대상 단위) — 승인 없는 재시도 금지.",
            file=sys.stderr,
        )
        sys.exit(2)

    if cursor:
        sys.stdout.write(json.dumps({"permission": "allow"}, separators=(",", ":")))
    sys.exit(0)


if __name__ == "__main__":
    main()
