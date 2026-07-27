#!/usr/bin/env python3
# Asgard tutor-note — 턴이 끝날 때 "당신이 직접 확인할 것"을 사용자 앞에 놓는다 (Stop).
#
# 왜 훅인가: 되짚기는 모델이 기억해야 하는 일이 되면 안 된다. 캐논에 "마지막에 리뷰 자료를
# 주어라"를 한 줄 더 쓰는 방식은 이 저장소에서 이미 실패가 측정된 방법이다 — 제약을 얹을수록
# 그만큼 흘린다(2605.06445). 게다가 여기서 흘리면 아무도 모른다: 되짚기가 빠진 턴과 되짚을 것이
# 없던 턴은 화면에서 똑같이 생겼다. 그래서 세는 일은 기계가 하고, 모델의 주의력은 "왜 그렇게
# 했는가"에만 남긴다 — 그 칸은 기계가 못 채운다.
#
# 왜 **안 막는가**: 튜터는 규율이지 관문이 아니다. health 와 같은 등급이다. 되짚기를 강제로
# 통과시키면 사람은 되짚기를 끄는 법을 먼저 배운다. 여기서 하는 일은 사용자에게 한 화면을
# 건네는 것뿐이고, 답할지 말지는 사용자가 정한다.
#
# 판정 대상은 **이 세션이 실제로 쓴 경로**다 (write_sentinel 이 남긴 목록) — craft-gate 와 같은
# 계약. 사용자가 원래 갖고 있던 dirt 를 이 턴의 물음으로 돌려주면 그건 남의 빚을 묻는 것이다.
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 훅 산출이 통째로 증발한다. UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
    except Exception:
        pass

MAX_SHOWN = 3  # 한 화면에 놓을 물음 수 — 전부 쏟으면 무엇부터 볼지가 사라진다
REPORT_REL = os.path.join(".asgard", "tutor", "last-review.md")
_KIND = {
    "contract-break": "공개 계약이 바뀌었다",
    "behavior-removed": "동작이 사라졌다",
    "test-removed": "판정이 사라졌다",
    "silent-failure": "실패를 조용히 삼킨다",
    "new-dependency": "외부 의존이 늘었다",
    "untested-surface": "판정 없는 새 표면",
    "todo-left": "안 끝난 표식",
}


def _writes(root: str, sid: str) -> list[str]:
    path = os.path.join(root, ".asgard", "state", "writes-" + sid + ".json")
    try:
        with open(path, encoding="utf-8") as handle:
            rows = json.load(handle)
    except Exception:
        return []  # 목록이 없으면 이 세션은 쓴 게 없다 — 되짚을 것도 없다
    return [str(r) for r in rows] if isinstance(rows, list) else []


def _lesson(exe: str, root: str, paths: list[str]) -> dict:
    """`asgard tutor --json` 이 유일한 판정 경로 — 훅은 규칙을 자기가 알지 않는다.

    훅은 사용자 저장소 안에서 도는 stdlib 전용 스크립트다(hooks 패키지 계약). 규칙을 복사해
    넣으면 판정이 두 벌이 되고, 두 벌은 반드시 어긋난다.
    """
    cmd = [exe, "tutor", "--json", "--report"]
    for path in paths[:200]:
        cmd += ["--path", path]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=root, encoding="utf-8", errors="replace"
        )
        return json.loads(result.stdout or "{}")
    except Exception:
        return {}


def _signature(points: list[dict]) -> str:
    """물음 집합의 지문. 같은 물음을 매 턴 다시 놓으면 세 번째부터 아무도 안 읽는다."""
    raw = "\n".join(sorted("%s|%s|%s" % (p.get("kind"), p.get("path"), p.get("unit")) for p in points))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _latched(root: str, sid: str, sig: str) -> bool:
    """이미 이 지문을 놓았으면 True. 기록 실패는 False — 못 세면 한 번 더 보여주는 쪽으로."""
    path = os.path.join(root, ".asgard", "state", "tutor-" + sid + ".json")
    try:
        with open(path, encoding="utf-8") as handle:
            if json.load(handle).get("signature") == sig:
                return True
    except Exception:
        pass  # 래치가 없거나 깨졌다 = 아직 안 놓았다 — 못 읽은 것을 "이미 놓았다"로 세면 카드가 통째로 증발한다
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"signature": sig}, handle)
        os.replace(tmp, path)
    except Exception:
        pass  # 못 적었으면 다음 턴에 같은 카드가 한 번 더 나온다 — 중복이 침묵보다 낫다
    return False


def _card(lesson: dict, points: list[dict]) -> str:
    added, removed = int(lesson.get("added") or 0), int(lesson.get("removed") or 0)
    files = len(lesson.get("files") or [])
    head = "⠶ 되짚기 — 이번 턴 %d개 파일 · +%d/-%d행. 아래는 **기계가 못 답하는** 것들이다." % (files, added, removed)
    lines = [head, ""]
    for point in points[:MAX_SHOWN]:
        where = "%s:%s" % (point.get("path"), point.get("line"))
        unit = point.get("unit") or ""
        lines.append(
            "  %s — %s%s" % (_KIND.get(point.get("kind"), point.get("kind")), where, " " + unit if unit else "")
        )
        lines.append("    ▸ %s" % point.get("ask"))
    if len(points) > MAX_SHOWN:
        lines.append("  …외 %d건" % (len(points) - MAX_SHOWN))
    lines.append("")
    lines.append("  전체와 '왜 이렇게 했는가' 빈칸: %s  (다시 보기: `asgard tutor --report`)" % REPORT_REL)
    return "\n".join(lines)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        protocol = sys.argv[1] if len(sys.argv) > 1 else "claude"
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        raw_sid = "cursor" if protocol == "cursor" else data.get("session_id") or "default"
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw_sid))[:64]
        paths = _writes(root, sid)
        if not paths:
            sys.exit(0)
        exe = shutil.which("asgard")
        if not exe:
            sys.exit(0)
        lesson = _lesson(exe, root, paths)
        points = [p for p in (lesson.get("checkpoints") or []) if isinstance(p, dict)]
        if not points:
            sys.exit(0)  # 물을 것이 없으면 침묵한다 — 빈 카드는 다음 카드의 신뢰를 깎는다
        if _latched(root, sid, _signature(points)):
            sys.exit(0)
        key = "followup_message" if protocol == "cursor" else "systemMessage"
        sys.stdout.write(json.dumps({key: _card(lesson, points)}, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 되짚기 불능이 턴을 막지 않는다 — 튜터는 규율이지 관문이 아니다
    sys.exit(0)


if __name__ == "__main__":
    main()
