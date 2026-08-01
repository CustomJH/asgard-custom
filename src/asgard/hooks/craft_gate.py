#!/usr/bin/env python3
# Asgard craft-gate — 미시 형상 + 백엔드 정확성 규율의 구조적 강제 (SubagentStop).
#
# 왜 프롬프트가 아니라 훅인가: 구조 제약은 많이 얹을수록 모델이 그만큼 흘린다 — 백엔드 생성
# 과업에서 제약을 다 걸면 상위 모델도 통과율이 약 30포인트 떨어진다(2605.06445). 그래서 "긴 함수를
# 만들지 마라"를 캐논에 한 줄 더 쓰는 것은 이미 실패한 방법이다. 세는 일은 기계가 하고, 모델의
# 주의력은 판단에 남긴다.
#
# 게이트를 나눈 이유: `craft`는 이 저장소가 정한 **예산**(길이·중첩·수명)을 재고, `thor gate`는
# 예산과 무관하게 **틀린 것**(값 자리 질의 보간·삼킨 예외·타임아웃 없는 외부 호출·박힌 시크릿)을
# 잰다. 후자는 조정할 여지가 없어서 같은 화면에서 다투면 안 된다 — 판정은 합치되 근거는 나눈다.
#
# 수리 레인은 craft 하나뿐이다: `asgard craft --fix --json`이 결정론적 수리를 디스크에 반영한 뒤
# **수리 후 다시 판정한 결과**를 `blocking`에 준다. 훅은 그 남은 것만 막는다. thor gate 와
# freyja gate 는 틀린 값과 시각 표면을 재는데 둘 다 기계가 고를 수 없는 판단이라 수리 레인이
# 없고, 읽기 전용으로만 부른다.
#
# 수리 사실은 차단문 맨 앞에 놓는다. 트리가 자기 밑에서 바뀐 것을 모르는 모델은 마지막으로 읽은
# 내용으로 다시 써서 수리를 되돌린다.
#
# 판정 대상은 **이 세션이 실제로 쓴 경로**다 (write_sentinel이 남긴 목록). 계약은 래칫 하나 —
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

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass

MAX_BLOCKS = 2
MAX_SHOWN = 6  # 한 번에 싣는 판정 수 — 전부 쏟으면 무엇부터 고칠지가 사라진다
MAX_PATHS = 200  # 한 번에 판정기로 넘기는 경로 수 — 초과분은 잘렸다는 사실로 차단문에 넣는다
MAX_FILES = 8  # 수리된 파일을 이름으로 부르는 한도 — 나머지는 개수로만 말한다
TIMEOUT = 90
TIMEOUT_FIX = 120  # 수리 레인은 판정 → 수리 → 재판정이라 읽기 전용보다 오래 걸린다
# 두 판정기가 아는 확장자의 합집합. 훅은 저장소 안에서 도는 stdlib 전용 스크립트라 엔진에서
# 가져올 수 없다(hooks 패키지 계약) — 목록이 어긋나면 판정을 놓치지 과판정하지는 않는다.
JUDGED_SUFFIXES = (
    ".py",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".cs",
    ".swift",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".c",
    ".h",
    ".cpp",
)
# 세 번째 게이트 — 시각 표면. 규칙은 각 프레이야 엔진이 배송한 판정기가 갖고, 이 훅은
# 세 게이트를 같은 `blocking` 계약으로만 읽는다.
GATES = (("craft", ["craft"]), ("thor gate", ["thor", "gate"]), ("freyja gate", ["freyja-gate"]))
REPAIR_GATE = "craft"  # `--fix`를 받는 유일한 게이트. 나머지 둘은 고칠 수 없는 것을 잰다


def _writes(root: str, sid: str) -> list[str]:
    path = os.path.join(root, ".asgard", "state", "writes-" + sid + ".json")
    try:
        with open(path, encoding="utf-8") as handle:
            rows = json.load(handle)
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    return [str(r) for r in rows if str(r).endswith(JUDGED_SUFFIXES)]


def _bump(root: str, sid: str, agent: str) -> int:
    """차단 횟수를 올리고 현재 값을 준다. 기록 실패는 0이 아니라 1 — 못 세면 덜 막는 쪽으로."""
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


def _judge(exe: str, root: str, verb: list[str], paths: list[str], timeout: int = TIMEOUT) -> dict | None:
    """게이트 하나를 부르고 `--json` payload 를 준다. 호출이나 파싱이 실패하면 None.

    None 은 "막을 것이 없다"가 아니라 "판정을 못 받았다"다. 호출자는 둘을 구분해야 한다 —
    빈 payload 로 뭉개면 게이트 고장이 조용한 통과가 된다.
    """
    cmd = [exe, *verb, "--json"]
    for path in paths[:MAX_PATHS]:  # 인자 폭주 방지 — 상한 초과분은 잘린 사실로 차단문에 넣는다
        cmd += ["--path", path]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=root, encoding="utf-8", errors="replace"
        )
        payload = json.loads(result.stdout or "{}")
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _blocking(exe: str, root: str, paths: list[str]) -> tuple[list[dict], dict]:
    """`asgard <게이트> --json`이 유일한 판정 경로 — 훅은 규칙을 자기가 알지 않는다.

    훅은 사용자 저장소 안에서 도는 stdlib 전용 스크립트다(hooks 패키지 계약). 엔진을 import 하면
    그 계약이 깨지고, 규칙을 복사해 넣으면 판정이 두 벌이 되어 곧 어긋난다.

    craft 만 `--fix`를 붙여 부른다. 그 payload 의 `blocking`은 수리 후 다시 판정한 결과이므로
    훅은 남은 것만 막는다. `fix` 칸이 없으면 `--fix`를 모르는 구 CLI 이거나 수리가 죽은 것이라
    읽기 전용으로 다시 불러 예전과 똑같이 막는다 — 판정은 버전 문자열이 아니라 결과로 가른다.

    한쪽 게이트가 고장 나도 다른 쪽 판정은 살린다 — 둘을 한 호출로 묶으면 하나의 실패가 둘 다
    조용히 통과시킨다.

    돌려주는 dict 는 craft 가 낸 `fix` 칸이고, 수리 레인을 못 탔으면 빈 dict 다.
    """
    out: list[dict] = []
    fix: dict = {}
    for label, verb in GATES:
        payload = None
        if label == REPAIR_GATE:
            payload = _judge(exe, root, [*verb, "--fix"], paths, TIMEOUT_FIX)
            repaired = payload.get("fix") if payload else None
            if isinstance(repaired, dict):
                fix = repaired
            else:
                payload = None  # 수리 레인이 없다 — 아래에서 읽기 전용으로 되돌린다
        if payload is None:
            payload = _judge(exe, root, verb, paths)
        if payload is None:
            continue  # 이 게이트가 고장 났다 — 나머지 게이트의 판정은 살린다 (게이트는 규율이지 관문이 아니다)
        found = payload.get("blocking")
        for finding in found if isinstance(found, list) else []:
            if isinstance(finding, dict):
                out.append({**finding, "gate": label})
    return out, fix


def _repaired_files(fix: dict | None) -> list[str]:
    """수리로 다시 쓰인 파일 경로. `files` 칸이 비면 수리 항목의 경로에서 만든다."""
    names = (fix or {}).get("files")
    if isinstance(names, list) and names:
        return [str(n) for n in names]
    applied = (fix or {}).get("applied")
    rows = applied if isinstance(applied, list) else []
    return sorted({str(r.get("path")) for r in rows if isinstance(r, dict) and r.get("path")})


def _applied(fix: dict | None) -> list[dict]:
    rows = (fix or {}).get("applied")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _named(files: list[str]) -> str:
    shown = ", ".join(files[:MAX_FILES])
    if len(files) > MAX_FILES:
        shown += " and %d more" % (len(files) - MAX_FILES)
    return shown


def _repair_head(fix: dict | None) -> str:
    """수리한 개수와 다시 쓰인 파일을 차단문 맨 앞에 놓는다. 수리가 없으면 빈 문자열.

    이 문단이 없으면 모델은 자기가 마지막으로 읽은 내용으로 그 파일을 다시 써서 수리를 되돌린다.
    """
    applied = _applied(fix)
    if not applied:
        return ""
    files = _repaired_files(fix)
    head = "Asgard craft-gate repaired %d finding(s) itself and rewrote %d file(s) on disk" % (
        len(applied),
        len(files),
    )
    if files:
        head += ": " + _named(files)
    return head + (
        ". Those files no longer match what you last read — re-read them before your next edit, or you "
        "will write the repaired lines back. What follows is what still blocks after that repair.\n\n"
    )


def _receipt(fix: dict | None) -> None:
    """수리가 차단을 통과로 바꿨을 때 그 사실을 stderr 에 한 줄 남긴다.

    막을 것이 없어졌다는 이유로 아무 말 없이 통과하면 디스크가 바뀐 것을 아무도 못 본 채 지나간다.
    """
    applied = _applied(fix)
    if not applied:
        return
    sys.stderr.write(
        "asgard craft-gate: repaired %d finding(s) in place, nothing left to block — rewrote %s\n"
        % (len(applied), _named(_repaired_files(fix)) or "no file")
    )


def _reason(findings: list[dict], truncated: int, fix: dict | None = None) -> str:
    gates = sorted({str(f.get("gate") or "craft") for f in findings})
    head = _repair_head(fix) + (
        "Asgard craft-gate: this change made %d thing(s) worse than they were at HEAD. "
        "Inherited debt was not counted — these are yours. Fix them, or state why the shape is right "
        "with evidence, then finish. Re-check with `asgard %s`.\n" % (len(findings), "` and `asgard ".join(gates))
    )
    lines = []
    for f in findings[:MAX_SHOWN]:
        where = "%s:%s" % (f.get("path"), f.get("line")) + (" %s" % f["unit"] if f.get("unit") else "")
        lines.append(
            "- [%s/%s] %s — %s\n  fix: %s"
            % (f.get("gate") or "craft", f.get("rule"), where, f.get("detail"), f.get("fix"))
        )
    if len(findings) > MAX_SHOWN:
        lines.append("- …and %d more (re-run the gates to see all)" % (len(findings) - MAX_SHOWN))
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
            sys.exit(0)  # 이 세션이 판정 가능한 언어를 안 썼다 → 대상 없음 (fail-open)
        exe = shutil.which("asgard")
        if not exe:
            sys.exit(0)
        blocking, fix = _blocking(exe, root, paths)
        if not blocking:
            _receipt(fix)
            sys.exit(0)  # 수리만 하고 남은 것이 없는 실행은 차단이 아니다 — 래칫 카운터를 쓰지 않는다
        agent = str(data.get("agent_type") or data.get("subagent_type") or "session")
        if _bump(root, sid, agent) > MAX_BLOCKS:
            sys.stderr.write(
                "asgard craft-gate: %s exceeded %d block(s) — allowing (findings stand, unfixed)\n"
                % (agent, MAX_BLOCKS)
            )
            sys.exit(0)
        _block(protocol, _reason(blocking, max(0, len(paths) - MAX_PATHS), fix))
    except Exception:
        sys.exit(0)  # 판정기 고장이 작업을 막아서는 안 된다 — 게이트는 규율이지 관문이 아니다
    sys.exit(0)


if __name__ == "__main__":
    main()
