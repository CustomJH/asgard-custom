#!/usr/bin/env python3
"""PreToolUse 훅 — 깨진/raw HWPX가 사용자에게 전달되기 전에 차단.

Claude Code의 PreToolUse 훅으로 등록하면, Bash 도구 호출 직전에 명령어를
검사해서 .hwpx 파일을 '전달'하는 행위(한컴으로 열기·Downloads로 복사·메일
첨부 등)일 때 그 파일에 `fill_hwpx.py check --strict`를 돌린다.

차단 대상(빈 페이지/손상 문서 사고의 원인):
  - secPr 불완전 (pagePr/margin 누락) → 한컴 '손상된 문서'
  - raw LLM 파일 (미리보기·줄배치 부재) → 한컴 '빈 페이지'

차단 시 exit 2 + stderr 사유 → Claude가 그 사유를 보고 정상 파일로 교정한다.
검사 대상이 아니거나 통과하면 조용히 통과(exit 0).

등록 (settings.json):
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {"type": "command",
           "command": "python3 ${CLAUDE_SKILL_DIR}/scripts/hwpx_guard_hook.py"}
        ]
      }
    ]
  }
}

입력: stdin으로 PreToolUse 훅 JSON ({"tool_input": {"command": "..."}, ...})
"""

import json
import os
import re
import subprocess
import sys

# .hwpx를 '전달'하는 명령으로 보는 패턴 — 이때만 검사 (생성/중간단계는 통과)
DELIVERY_PATTERNS = [
    r"\bopen\b",          # macOS: 한컴에서 열기 (open -a, open file.hwpx)
    r"\bcp\b", r"\bmv\b", r"\brsync\b",  # 복사/이동 (보통 Downloads/Desktop로)
    r"\bditto\b",
]
# 전달 목적지로 보이는 경로 (이 디렉토리로 가는 .hwpx는 사용자 손에 들어감)
DELIVERY_DIRS = ("Downloads", "Desktop", "바탕화면", "다운로드")

HWPX_RE = re.compile(r'([^\s"\'<>|]+\.hwpx)')


def find_target_hwpx(command):
    """명령어에서 '전달'되는 .hwpx 경로를 추출 (없으면 None)."""
    if not any(re.search(p, command) for p in DELIVERY_PATTERNS):
        return None
    candidates = HWPX_RE.findall(command)
    if not candidates:
        return None
    # open 계열: 열리는 파일 자체. cp/mv: 보통 마지막 인자(목적지)가 아니라
    # 전달되는 소스 .hwpx를 검사하면 됨 — 존재하는 .hwpx를 우선 채택.
    is_delivery_dest = any(dirn in command for dirn in DELIVERY_DIRS)
    # open은 목적지 개념 없음 → 무조건 검사. cp/mv는 Downloads 등으로 갈 때만.
    if re.search(r"\bopen\b", command) or is_delivery_dest:
        for c in candidates:
            path = os.path.expanduser(c)
            if os.path.isfile(path):
                return path
        # 존재 파일이 없으면 첫 후보 (목적지로 막 복사될 파일일 수 있음)
        return os.path.expanduser(candidates[0])
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # 훅 입력 파싱 실패 시 통과 (안전 측 = 작업 방해 안 함)

    command = (payload.get("tool_input") or {}).get("command", "")
    if not command:
        return 0

    target = find_target_hwpx(command)
    if not target or not os.path.isfile(target):
        return 0

    skill_dir = os.path.dirname(os.path.abspath(__file__))
    checker = os.path.join(skill_dir, "fill_hwpx.py")

    # 글자 테두리 버그는 안전하게 자동 보정 (표 셀 테두리 보존, idempotent).
    # convert_hwp.py를 안 거친 경로(기존 hwpx 베이스 편집)에서도 배포 직전에 잡힌다.
    try:
        sys.path.insert(0, skill_dir)
        from fill_hwpx import detect_char_border_bug, strip_char_borders
        if detect_char_border_bug(target)["bug"]:
            removed = strip_char_borders(target)
            if removed:
                print(f"[hwpx-guard] 글자 테두리 {removed}개 자동 제거: "
                      f"{os.path.basename(target)}", file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass  # 자동 보정 실패해도 아래 check로 진행

    try:
        proc = subprocess.run(
            [sys.executable, checker, "check", target, "--strict"],
            capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        return 0  # 검사기 실행 실패 시 통과 (작업 차단보다 진행 우선)

    if proc.returncode == 0:
        return 0  # 정상 — 통과

    # 차단: 사유를 stderr로 (Claude가 읽고 교정)
    try:
        report = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        report = {}
    reasons = list(report.get("errors", []))
    if report.get("raw_llm_suspect"):
        reasons.append(
            "한컴 미경유 raw 파일 — 한컴에서 빈 페이지로 열림. 정상 HWPX(한컴 "
            "저장본/워크플로우 H 변환본)를 베이스로 fill/replace만 적용하세요.")
    msg = " | ".join(reasons) or "HWPX 열림 가능성 점검 실패"
    print(f"[hwpx-guard] 차단: {os.path.basename(target)} — {msg}",
          file=sys.stderr)
    return 2  # PreToolUse exit 2 → 도구 호출 차단 + stderr를 Claude에 전달


if __name__ == "__main__":
    sys.exit(main())
