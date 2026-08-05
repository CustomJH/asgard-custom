#!/usr/bin/env python3
# Asgard unattended-context — Canon 8(무인이면 진행)의 감지층.
#
# 모델은 headless 여부를 스스로 알 수 없다 — Claude Code는 print(-p) 모드 신호를 시스템 프롬프트에
# 주입하지 않는다 (code.claude.com/docs/en/headless, 2026-07 확인). 훅만이 안다: 모든 훅 stdin에
# permission_mode가 온다. bypassPermissions/dontAsk = 사람이 승인 루프에 없는 자동화 실행이므로
# UserPromptSubmit에서 무인 계약을 컨텍스트로 주입한다 (stdout + exit 0 = 컨텍스트 주입, 공식 스키마).
# 나머지 모드는 무개입 — 인터랙티브 세션은 이 훅의 존재를 느끼지 못한다. 오류는 전부 allow (fail-open).
import json
import os
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass

# 주입 스키마는 훅과 함께 깔리는 공용 라이브러리가 쥔다 — 아홉 훅이 같은 JSON 리터럴을 손으로
# 적던 자리다 (스키마 오타는 호스트가 조용히 버려서 주입이 통째로 사라진다).
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.inject import client, emit_context  # noqa: E402

UNATTENDED_MODES = {"bypassPermissions", "dontAsk"}  # verifier_gate.py와 동일 유지


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    mode = str(data.get("permission_mode") or "")
    if os.environ.get("ASGARD_UNATTENDED") != "1" and mode not in UNATTENDED_MODES:
        sys.exit(0)
    # NOTE: the `가정:` criteria-prefix token is matched elsewhere in the codebase — keep it literal.
    emit_context(
        client(),
        "[asgard] Unattended session detected (permission_mode=%s) — Canon 8 auto-proceed "
        "is in effect: do not end the session waiting on a question or approval. Pick a defensible default, "
        "log the assumption as a plan criteria `가정: ...` item, and proceed immediately — state the "
        "assumptions and alternatives in the final report. ESCALATE is for blockers you cannot proceed "
        "past only — never use it to request approval." % (mode or "env"),
        # 이 훅은 UserPromptSubmit 에 매달려 있다. 26-08-06 까지 codex 만 구조화 출력을 받았고
        # Claude Code 는 평문이었다 — 같은 이벤트에서 map-activate·budget-guard 는 구조화를 쓰고
        # 있었으니 그 갈림은 결정이 아니라 사본의 흔적이다. 이제 셋이 같은 표를 지난다.
        "UserPromptSubmit",
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
