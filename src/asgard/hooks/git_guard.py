#!/usr/bin/env python3
# Asgard git-guard — Canon Law 3/6 (증거 보존). 되돌릴 수 없는 git 명령을 실행 전에 차단한다.
#
# 왜 스크립트 하나로 모든 툴을 받는가: BLOCK 목록이 단일 출처여야 해서다. 툴별로 스크립트를
# 나누면 목록이 서로 어긋나게 드리프트한다. 대신 페이로드 모양으로 훅 프로토콜을 자동 감지한다
# (설치 시 인자·환경변수로 툴을 지정하는 방식보다 배선 실수에 강함):
#   • Claude Code / Codex (PreToolUse): {"tool_input": {"command": ...}} → 차단 = exit 2 + stderr.
#   • Cursor (beforeShellExecution):    {"command": ...}                 → 차단 = stdout {"permission":"deny"}, exit 0.
# 왜 fail-open(오류 시 무조건 allow)인가: 가드 자체가 죽으면 모든 shell 명령이 막혀 사용자를
# 인질로 잡는다. 이 훅은 best-effort 안전망이고, 뚫리면 잃는 것은 "한 번의 경고 기회"뿐이다.
import json
import re
import sys

# 패턴 공통: `[^|;&]*` 는 명령 구분자(| ; &)를 넘지 않게 탐색을 제한한다 —
# `git push && rm -f x` 의 `-f` 를 push 의 플래그로 오인해 차단하는 오탐을 막는다.
BLOCK = [
    (r"\bgit\s+push\b[^|;&]*\s-(-force\b|f\b)", "force-push"),          # 원격 히스토리 덮어쓰기
    (r"\bgit\s+push\b[^|;&]*--force-with-lease\b", "force-push"),       # lease 도 결국 덮어쓰기 — 의도를 명시하려고 별도 항목
    (r"\bgit\s+reset\s+--hard\b", "reset --hard"),                       # 워킹트리+인덱스 즉시 소실
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "clean -f"),                        # 언트래킹 파일 영구 삭제; [a-zA-Z]*f 로 -fd, -xf 등 조합 플래그도 포착
    (r"\bgit\s+branch\s+-D\b", "branch -D"),                             # 병합 확인 없는 강제 삭제 (-d 는 안전하므로 허용)
    (r"\bgit\s+(rebase|filter-branch|filter-repo)\b", "history rewrite"),  # 커밋 해시가 바뀜 = 증거 재작성
    (r"\bgit\s+update-ref\s+-d\b", "update-ref -d"),                     # ref 직접 삭제 (위 우회 경로)
    (r"\bgit\s+(stash\s+(drop|clear)|reflog\s+(delete|expire))\b", "drop history"),  # 복구 지점 제거 — Law 3 의 마지막 보루
]


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

    for pat, label in BLOCK:
        if re.search(pat, cmd):
            if cursor:
                sys.stdout.write(json.dumps({
                    "permission": "deny",
                    "userMessage": "Asgard Canon Law 3/6 — irreversible git op (" + label + "). Blocked.",
                    "agentMessage": "This " + label + " was blocked by the Asgard Canon (Law 3/6). "
                                    "Get Odin's explicit per-action consent; do not retry.",
                }, separators=(",", ":")))
                sys.exit(0)
            # Claude Code / Codex: exit 2 가 차단 신호, stderr 가 에이전트에게 그대로 전달된다.
            print(
                "Asgard Canon Law 3/6 — irreversible git op (" + label + "). "
                "Odin의 명시적 동의를 먼저 받으세요 (매 건, 대상 단위).",
                file=sys.stderr,
            )
            sys.exit(2)

    if cursor:  # Cursor 는 침묵을 허용으로 안 본다 — 명시적 allow 응답이 프로토콜 요구사항.
        sys.stdout.write(json.dumps({"permission": "allow"}, separators=(",", ":")))
    sys.exit(0)


if __name__ == "__main__":
    main()
