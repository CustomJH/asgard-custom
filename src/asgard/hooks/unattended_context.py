#!/usr/bin/env python3
# Asgard unattended-context — Canon 8(무인이면 진행)의 감지층.
#
# 모델은 headless 여부를 스스로 알 수 없다 — Claude Code 는 print(-p) 모드 신호를 시스템 프롬프트에
# 주입하지 않는다 (code.claude.com/docs/en/headless, 2026-07 확인). 훅만이 안다: 모든 훅 stdin 에
# permission_mode 가 온다. bypassPermissions/dontAsk = 사람이 승인 루프에 없는 자동화 실행이므로
# UserPromptSubmit 에서 무인 계약을 컨텍스트로 주입한다 (stdout + exit 0 = 컨텍스트 주입, 공식 스키마).
# 나머지 모드는 무개입 — 인터랙티브 세션은 이 훅의 존재를 느끼지 못한다. 오류는 전부 allow (fail-open).
import json
import os
import sys

UNATTENDED_MODES = {"bypassPermissions", "dontAsk"}  # verifier_gate.py 와 동일 유지


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    mode = str(data.get("permission_mode") or "")
    if os.environ.get("ASGARD_UNATTENDED") != "1" and mode not in UNATTENDED_MODES:
        sys.exit(0)
    sys.stdout.write(
        "[asgard] 무인 세션 감지(permission_mode=%s) — Canon 8 무인 진행 발동: "
        "질문·승인 대기로 세션을 끝내지 말 것. 방어 가능한 기본안을 골라 가정을 plan criteria "
        "`가정: ...` 항목으로 기록하고 즉시 진행, 최종 보고에 가정·대안을 명기한다. "
        "ESCALATE 는 진행 불가 블로커 전용 — 승인 요청 용도 금지." % (mode or "env")
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
