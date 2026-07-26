#!/usr/bin/env python3
# Asgard craft-gate — 미시 형상 규율의 구조적 강제 (SubagentStop).
#
# 왜 프롬프트가 아니라 훅인가: 구조 제약은 많이 얹을수록 모델이 그만큼 흘린다 — 백엔드 생성
# 과업에서 제약을 다 걸면 상위 모델도 통과율이 약 30포인트 떨어진다(2605.06445). 그래서 "긴 함수를
# 만들지 마라"를 캐논에 한 줄 더 쓰는 것은 이미 실패한 방법이다. 세는 일은 기계가 하고, 모델의
# 주의력은 판단에 남긴다.
#
# 판정 대상은 **이 세션이 실제로 쓴 경로**다 (write_sentinel 이 남긴 목록). 계약은 래칫 하나 —
# 이번 변경이 더 나쁘게 만든 것만 막고, 물려받은 부채는 통과시킨다.
#
# 상한 2회: SubagentStop 차단 루프는 서브에이전트를 인질로 잡는다. 같은 세션·같은 역할을 2회
# 막으면 3번째는 경고와 함께 통과 — 이 훅은 조기 교정 장치지 최후 방벽이 아니다 (subagent_gate
# 와 같은 규약).
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
    except Exception:
        pass

MAX_BLOCKS = 2
MAX_SHOWN = 6  # 한 번에 싣는 판정 수 — 전부 쏟으면 무엇부터 고칠지가 사라진다


def _writes(root: str, sid: str) -> list[str]:
    path = os.path.join(root, ".asgard", "state", "writes-" + sid + ".json")
    try:
        with open(path, encoding="utf-8") as handle:
            rows = json.load(handle)
    except Exception:
        return []
    return [str(r) for r in rows if isinstance(rows, list) and str(r).endswith(".py")]


def _bump(root: str, sid: str, agent: str) -> int:
    """차단 횟수를 올리고 현재 값을 준다. 기록 실패는 0 이 아니라 1 — 못 세면 덜 막는 쪽으로."""
    path = os.path.join(root, ".asgard", "state", "craftgate-" + sid + ".json")
    counts = {}
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        counts = loaded if isinstance(loaded, dict) else {}
    except Exception:
        pass
    n = int(counts.get(agent, 0)) + 1
    counts[agent] = n
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())  # temp+rename — 크래시 절단이 카운터를 리셋하지 않게
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(counts, handle)
        os.replace(tmp, path)
    except Exception:
        pass
    return n


def _blocking(exe: str, root: str, paths: list[str]) -> list[dict]:
    """`asgard craft --json` 이 유일한 판정 경로 — 훅은 규칙을 자기가 알지 않는다.

    훅은 사용자 저장소 안에서 도는 stdlib 전용 스크립트다(hooks 패키지 계약). 엔진을 import 하면
    그 계약이 깨지고, 규칙을 복사해 넣으면 판정이 두 벌이 되어 곧 어긋난다.
    """
    cmd = [exe, "craft", "--json"]
    for path in paths[:200]:  # 인자 폭주 방지 — 상한 초과분은 아래에서 잘린 사실로 싣는다
        cmd += ["--path", path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90, cwd=root)
    except Exception:
        return []
    try:
        return list(json.loads(result.stdout or "{}").get("blocking") or [])
    except Exception:
        return []


def _reason(findings: list[dict], truncated: int) -> str:
    head = (
        "Asgard craft-gate: this change made %d thing(s) worse than they were at HEAD. "
        "Inherited debt was not counted — these are yours. Fix them, or state why the shape is right "
        "with evidence, then finish. Re-check with `asgard craft`.\n" % len(findings)
    )
    lines = []
    for f in findings[:MAX_SHOWN]:
        where = "%s:%s" % (f.get("path"), f.get("line")) + (" %s" % f["unit"] if f.get("unit") else "")
        lines.append("- [%s] %s — %s\n  fix: %s" % (f.get("rule"), where, f.get("detail"), f.get("fix")))
    if len(findings) > MAX_SHOWN:
        lines.append("- …and %d more (`asgard craft` shows all)" % (len(findings) - MAX_SHOWN))
    if truncated:
        lines.append("- note: %d written path(s) were not judged this run (per-run cap)" % truncated)
    return head + "\n".join(lines)


def _block(protocol: str, message: str) -> None:
    if protocol == "cursor":
        payload = {"followup_message": message}
    elif protocol == "codex":
        payload = {"continue": False, "stopReason": message}
    else:
        payload = {"decision": "block", "reason": message}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.exit(0)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        protocol_arg = sys.argv[1] if len(sys.argv) > 1 else ""
        protocol = "cursor" if protocol_arg in {"pre", "start", "stop"} else protocol_arg or "claude"
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        raw_sid = "cursor" if protocol == "cursor" else data.get("session_id") or "default"
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw_sid))[:64]
        paths = _writes(root, sid)
        if not paths:
            sys.exit(0)  # 이 세션이 Python 을 안 썼다 → 판정 대상 없음 (fail-open)
        exe = shutil.which("asgard")
        if not exe:
            sys.exit(0)
        blocking = _blocking(exe, root, paths)
        if not blocking:
            sys.exit(0)
        agent = str(data.get("agent_type") or data.get("subagent_type") or "session")
        if _bump(root, sid, agent) > MAX_BLOCKS:
            sys.stderr.write(
                "asgard craft-gate: %s exceeded %d block(s) — allowing (findings stand, unfixed)\n"
                % (agent, MAX_BLOCKS)
            )
            sys.exit(0)
        _block(protocol, _reason(blocking, max(0, len(paths) - 200)))
    except Exception:
        sys.exit(0)  # 판정기 고장이 작업을 막아서는 안 된다 — 게이트는 규율이지 관문이 아니다
    sys.exit(0)


if __name__ == "__main__":
    main()
