#!/usr/bin/env python3
# Asgard tutor-note — 되짚기의 두 도달 시점. 인자 하나로 갈린다:
#   (기본)  Stop            — 이 턴이 쓴 코드를 물음으로 되돌린다
#   brief   UserPromptSubmit — 같은 자리를 다시 건드리기 **전에** 남은 물음을 꺼낸다
#
# 두 시점을 한 파일에 두는 이유: 판정기가 하나여야 두 화면이 어긋나지 않는다. 파일을 나누면
# 되짚기 규칙이 두 벌이 되고, 두 벌은 반드시 갈라진다(훅 계약).
#
# 왜 훅인가: 되짚기는 모델이 기억해야 하는 일이 되면 안 된다. 캐논에 "마지막에 리뷰 자료를
# 주어라"를 한 줄 더 쓰는 방식은 이 저장소에서 이미 실패가 측정된 방법이다 — 제약을 얹을수록
# 그만큼 흘린다(2605.06445). 게다가 여기서 흘리면 아무도 모른다: 되짚기가 빠진 턴과 되짚을 것이
# 없던 턴은 화면에서 똑같이 생겼다. 그래서 세는 일은 기계가 하고, 모델의 주의력은 "왜 그렇게
# 했는가"에만 남긴다 — 그 칸은 기계가 못 채운다.
#
# 왜 **안 막는가**: 튜터는 규율이지 관문이 아니다. health와 같은 등급이다. 되짚기를 강제로
# 통과시키면 사람은 되짚기를 끄는 법을 먼저 배운다. 여기서 하는 일은 사용자에게 한 화면을
# 건네는 것뿐이고, 답할지 말지는 사용자가 정한다.
#
# 판정 대상은 **이 세션이 실제로 쓴 경로**다 (write_sentinel이 남긴 목록) — craft-gate와 같은
# 계약. 사용자가 원래 갖고 있던 dirt를 이 턴의 물음으로 돌려주면 그건 남의 빚을 묻는 것이다.
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 산출이 통째로 증발한다. UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass

MAX_SHOWN = 3  # 한 화면에 놓을 물음 수 — 전부 쏟으면 무엇부터 볼지가 사라진다
MAX_BACK = 2  # 되돌아온 물음 상한 — 재방문이 이번 변경보다 길어지면 이번 변경을 안 보게 된다
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
    """`asgard tutor --json`이 유일한 판정 경로 — 훅은 규칙을 자기가 알지 않는다.

    훅은 사용자 저장소 안에서 도는 stdlib 전용 스크립트다(hooks 패키지 계약). 규칙을 복사해
    넣으면 판정이 두 벌이 되고, 두 벌은 반드시 어긋난다.
    """
    # `--record`가 이 호출을 성장 기록에 센다 — 훅이 놓은 물음도 사람 앞에 놓인 물음이다.
    # 안 세면 조절(fading)·재방문이 외부 클라이언트에서만 영원히 1회차에 머문다.
    cmd = [exe, "tutor", "--json", "--record", "--report"]
    for path in paths[:200]:
        cmd += ["--path", path]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=root, encoding="utf-8", errors="replace"
        )
        return json.loads(result.stdout or "{}")
    except Exception:
        return {}


def _signature(points: list[dict], back: list[dict]) -> str:
    """물음 집합의 지문. 같은 물음을 매 턴 다시 놓으면 세 번째부터 아무도 안 읽는다.

    재방문도 지문에 넣는다 — 안 넣으면 오늘 처음 돌아온 옛 물음이 "직전 턴과 같은 카드"로
    판정돼 통째로 사라진다. 래치가 자기 성장 경로를 막는 형상이다.
    """
    rows = ["%s|%s|%s" % (p.get("kind"), p.get("path"), p.get("unit")) for p in points]
    rows += ["revisit|%s|%s" % (r.get("cid"), r.get("asks")) for r in back]
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()[:16]


def _latched(root: str, sid: str, sig: str, slot: str = "") -> bool:
    """이미 이 지문을 놓았으면 True. 기록 실패는 False — 못 세면 한 번 더 보여주는 쪽으로."""
    path = os.path.join(root, ".asgard", "state", "tutor-" + slot + sid + ".json")
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


def _card(lesson: dict, points: list[dict], back: list[dict]) -> str:
    """네이티브 루프의 `tutor._card`와 같은 화면을 낸다 — 형식이 갈리면 같은 판정이 클라이언트마다
    다르게 보이고, 그러면 사용자는 어느 쪽이 진짜인지부터 물어야 한다."""
    added, removed = int(lesson.get("added") or 0), int(lesson.get("removed") or 0)
    files = len(lesson.get("files") or [])
    head = "⠶ 되짚기 — 이번 턴 %d개 파일 · +%d/-%d행. 아래는 **기계가 못 답하는** 것들이다." % (files, added, removed)
    lines = [head, ""]
    shown = 0
    folded, quiet = {}, {}
    for point in points:
        form = point.get("form") or "full"
        if form in ("fold", "quiet"):
            bucket = folded if form == "fold" else quiet
            kind = point.get("kind")
            bucket[kind] = bucket.get(kind, 0) + 1
            continue
        if shown >= MAX_SHOWN:
            continue
        lines.append("  %s — %s  [%s]" % (_label(point), _where(point), point.get("cid") or "?"))
        lines.append("    ▸ %s" % point.get("ask"))
        shown += 1
    over = sum(1 for p in points if (p.get("form") or "full") not in ("fold", "quiet")) - shown
    if over > 0:
        lines.append("  …외 %d건" % over)
    if folded:
        lines.append("  %s — 이미 답해 온 종류라 접었다" % _folded(folded))
    if quiet:
        lines.append("  %s — 계속 못 닿아서 튜터가 접었다 (`asgard tutor --progress`)" % _folded(quiet))
    for row in back[:MAX_BACK]:
        lines.append("  ↩ 다시 — %s  [%s]  (아직 답이 없다)" % (_where(row, False), row.get("cid") or "?"))
        lines.append("    ▸ %s" % row.get("ask"))
    lines.append("")
    lines.append('  답은 `asgard tutor --answer <표식> "..."` · 오탐이면 `asgard tutor --dismiss <표식>`')
    lines.append("  전체와 '왜 이렇게 했는가' 빈칸: %s  (다시 보기: `asgard tutor --report`)" % REPORT_REL)
    return "\n".join(lines)


def _label(row: dict) -> str:
    return _KIND.get(row.get("kind"), row.get("kind"))


def _where(row: dict, with_line: bool = True) -> str:
    unit = row.get("unit") or ""
    base = "%s:%s" % (row.get("path"), row.get("line")) if with_line else str(row.get("path"))
    return base + (" " + unit if unit else "")


def _folded(counts: dict) -> str:
    return " · ".join("%s %d건" % (_KIND.get(k, k), n) for k, n in sorted(counts.items()))


def _brief(exe: str, root: str, prompt: str) -> str:
    """`asgard tutor --brief`를 그대로 옮긴다 — 훅은 자기 규칙을 안 갖는다(판정기 단일)."""
    if not prompt:
        return ""
    try:
        result = subprocess.run(
            [exe, "tutor", "--brief", "--quiet", "--text", prompt[:2000]],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=root,
            encoding="utf-8",
            errors="replace",
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""  # 브리핑 불능이 턴 시작을 막지 않는다 — 앞서 말하는 층도 관문이 아니다


def _prompt_of(data: dict) -> str:
    """이번 턴의 요청 문장 — 클라이언트마다 칸 이름이 다르다(Claude/Codex `prompt`, Cursor `user_message`)."""
    raw = data.get("tool_input")
    tool_input = raw if isinstance(raw, dict) else {}
    return str(data.get("prompt") or tool_input.get("prompt") or data.get("user_message") or "").strip()


def _run_brief(protocol: str, root: str, sid: str, data: dict) -> None:
    """일을 **시작하기 전에**이 자리에 남은 답 없는 물음을 사용자 앞에 놓는다 (UserPromptSubmit).

    사용자에게만 보낸다. 모델에 넣지 않는 이유가 이 층의 핵심이다 — 모델이 열린 물음을 보면
    그 물음에 **대신 답해** 버리고, 그러면 되짚기가 막으려던 바로 그 일이 일어난다(미미르 auga
    계약: 물음은 대신 닫아 주는 체크리스트가 아니다).
    """
    exe = shutil.which("asgard")
    if not exe:
        return
    card = _brief(exe, root, _prompt_of(data))
    if not card:
        return
    if _latched(root, sid, hashlib.sha256(card.encode("utf-8")).hexdigest()[:16], "brief-"):
        return
    if protocol == "cursor":
        sys.stdout.write(json.dumps({"user_message": card}, ensure_ascii=False) + "\n")
    elif protocol == "codex":
        sys.stdout.write(card + "\n")
    else:
        sys.stdout.write(json.dumps({"systemMessage": card}, ensure_ascii=False) + "\n")


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        protocol = sys.argv[1] if len(sys.argv) > 1 else "claude"
        mode = sys.argv[2] if len(sys.argv) > 2 else "note"
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        raw_sid = "cursor" if protocol == "cursor" else data.get("session_id") or "default"
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw_sid))[:64]
        if mode == "brief":
            _run_brief(protocol, root, sid, data)
            sys.exit(0)
        paths = _writes(root, sid)
        if not paths:
            sys.exit(0)
        exe = shutil.which("asgard")
        if not exe:
            sys.exit(0)
        lesson = _lesson(exe, root, paths)
        points = [p for p in (lesson.get("checkpoints") or []) if isinstance(p, dict)]
        back = [r for r in (lesson.get("revisits") or []) if isinstance(r, dict)]
        if not points and not back:
            sys.exit(0)  # 물을 것이 없으면 침묵한다 — 빈 카드는 다음 카드의 신뢰를 깎는다
        if _latched(root, sid, _signature(points, back)):
            sys.exit(0)
        key = "followup_message" if protocol == "cursor" else "systemMessage"
        sys.stdout.write(json.dumps({key: _card(lesson, points, back)}, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 되짚기 불능이 턴을 막지 않는다 — 튜터는 규율이지 관문이 아니다
    sys.exit(0)


if __name__ == "__main__":
    main()
