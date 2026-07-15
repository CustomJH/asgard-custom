#!/usr/bin/env python3
# Asgard memory-activate — 개인 메모리 스냅샷 주입 (memory v3, Claude Code 배선).
#
# 배선 매처: SessionStart startup|resume|clear|compact (lagom-activate 와 동일 —
# compact/clear 는 컨텍스트 소실 지점이라 재주입 필수) + SubagentStart ^asgard-thinker$
# (감사 매트릭스: Thinker 한정. Worker/딜리버리 기본 무주입, Verifier/Loki 영구 무주입 —
# lagom 처럼 전 서브에이전트 보상 주입하는 패턴은 메모리에 적용 금지).
#
# 동작: `asgard memory snapshot` 을 subprocess 로 소비 — 스캔·오염 제외·예산·킬스위치는
# 전부 CLI(단일 출처)가 수행하고, 이 훅은 출력 전달만 한다 (로직 재구현 금지).
# asgard 미설치·빈 출력·타임아웃·어떤 오류든 무주입 통과 (fail-open, 항상 exit 0).
import json
import shutil
import subprocess
import sys

NEVER_INJECT = ("asgard-verifier", "asgard-loki")  # 게이트·반례 탐색 오염 방지 — 매처가 바뀌어도 불변


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    try:
        # SubagentStart 이중 방어 — settings 매처(^asgard-thinker$)가 느슨해져도 스크립트가 지킨다
        agent = str(data.get("agent_type") or data.get("agent_name") or "")
        if data.get("hook_event_name") == "SubagentStart":
            if agent in NEVER_INJECT or agent != "asgard-thinker":
                sys.exit(0)
        exe = shutil.which("asgard")
        if not exe:
            sys.exit(0)  # asgard CLI 부재 = 메모리 기능 없음 — 조용히 통과
        r = subprocess.run([exe, "memory", "snapshot"], capture_output=True, text=True, timeout=10)
        note = (r.stdout or "").strip()
        if r.returncode == 0 and note:
            sys.stdout.write(note + "\n")
    except Exception:
        pass  # fail-open — 메모리 불능이 세션을 막지 않는다
    sys.exit(0)


if __name__ == "__main__":
    main()
