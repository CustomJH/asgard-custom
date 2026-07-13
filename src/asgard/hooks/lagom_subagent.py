#!/usr/bin/env python3
# Asgard lagom-subagent — SubagentStart 재주입 (CUS-214, Claude Code 전용 이벤트).
#
# SessionStart 컨텍스트는 부모 스레드 한정 — 서브에이전트에 전파되지 않는다. 이 보상이 없으면
# 서브에이전트 작업은 전부 lagom 밖에서 돈다. 동작:
#   상태파일 off/부재 → 무개입 (lagom 비활성 세션 존중)
#   asgard-verifier → 무주입 (게이트 기준이 lagom 으로 흔들리면 안 된다 — 게이트 신뢰 원칙)
#   matcher(LAGOM_SUBAGENT_MATCHER env > [lagom].subagent_matcher) 있으면 agent_type 매치 시만
# fail-open 방향 주의: matcher 파싱 실패·정규식 오류는 **주입**으로 폴백한다 — 룰 누락이
# 더 큰 실패다 (원본 설계 계승). 훅 자체 오류만 무개입 통과.
import json
import os
import re
import sys

MODES = ("off", "lite", "full", "ultra")

# 모드 마커 필터 — templates/lagom.py render_lagom 과 동일 유지 (단일 출처 원칙)
_ROW = re.compile(r"^\s*\|\s*\*\*(off|lite|full|ultra)\*\*\s*\|")
_EXAMPLE = re.compile(r"^\s*-\s*(off|lite|full|ultra):")

NEVER_INJECT = ("asgard-verifier",)  # 검증 기준 오염 방지 — CUS-209 와 동일 원칙


def norm(m):
    m = str(m or "").strip().lower()
    return m if m in MODES else None


def render(canon, mode):
    """lagom_activate.py render 와 동일 유지 (단일 출처 원칙: templates render_lagom)."""
    out = []
    for line in canon.splitlines():
        m = _ROW.match(line) or _EXAMPLE.match(line)
        if m and m.group(1) != mode:
            continue
        out.append(line)
    return "\n".join(out).replace("__MODE__", mode)


def matcher_pattern(root):
    pat = os.environ.get("LAGOM_SUBAGENT_MATCHER")
    if pat:
        return pat
    try:
        txt = open(os.path.join(root, ".asgard", "config.toml"), encoding="utf-8").read()
        sec = re.search(r"(?ms)^\[lagom\]\s*$(.*?)(?=^\[|\Z)", txt)
        if sec:
            kv = re.search(r'^\s*subagent_matcher\s*=\s*"(.*?)"', sec.group(1), re.M)
            if kv:
                return kv.group(1)
    except Exception:
        pass
    return ""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        agent = str(data.get("agent_type") or "")
        if agent in NEVER_INJECT:
            sys.exit(0)
        mode = None
        try:
            mode = norm(open(os.path.join(root, ".asgard", "lagom-mode"), encoding="utf-8").read())
        except Exception:
            pass
        if mode in (None, "off"):
            sys.exit(0)  # 비활성 세션 — 서브에이전트도 무개입
        pat = matcher_pattern(root)
        if pat:
            try:
                if agent and not re.search(pat, agent, re.I):
                    sys.exit(0)
            except re.error:
                pass  # 잘못된 정규식 = matcher 없음 취급 → 주입 (fail-open=주입)
        canon = open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "lagom-canon.md"), encoding="utf-8"
        ).read()
        sys.stdout.write(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SubagentStart",
                        "additionalContext": "[lagom] mode=%s\n\n%s" % (mode, render(canon, mode)),
                    }
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        pass  # 훅 자체 오류 = 무개입 (서브에이전트를 막지 않는다)
    sys.exit(0)


if __name__ == "__main__":
    main()
