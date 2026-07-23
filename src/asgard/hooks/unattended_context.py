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

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
    except Exception:
        pass


UNATTENDED_MODES = {"bypassPermissions", "dontAsk"}  # verifier_gate.py 와 동일 유지


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    mode = str(data.get("permission_mode") or "")
    if os.environ.get("ASGARD_UNATTENDED") != "1" and mode not in UNATTENDED_MODES:
        sys.exit(0)
    # NOTE: the `가정:` criteria-prefix token is matched elsewhere in the codebase — keep it literal.
    sys.stdout.write(
        "[asgard] Unattended session detected (permission_mode=%s) — Canon 8 auto-proceed "
        "is in effect: do not end the session waiting on a question or approval. Pick a defensible default, "
        "log the assumption as a plan criteria `가정: ...` item, and proceed immediately — state the "
        "assumptions and alternatives in the final report. ESCALATE is for blockers you cannot proceed "
        "past only — never use it to request approval." % (mode or "env")
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
