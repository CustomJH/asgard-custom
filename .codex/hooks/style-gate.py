#!/usr/bin/env python3
# Asgard style-gate — 저장소가 정한 코드 스타일을 이 세션이 쓴 파일에 물린다 (Stop · SubagentStop).
#
# 왜 있는가. 스타일 규격은 팀이 이미 정해 뒀다 — `checkstyle.xml`, `eslint.config.js`,
# `.clang-format`. 문제는 그것이 CI 에서만 돈다는 것이다. 에이전트가 쓴 코드는 커밋되고 푸시된
# 다음에야 규격에 걸리고, 그때 고치는 사람은 그 코드를 안 쓴 사람이다. 이 훅은 그 판정을 세션
# 안으로 당긴다.
#
# **안 들인 저장소에서는 아무 일도 안 한다.** 첫 판단은 설정 파일 한 번 읽는 것이다 —
# `code_style.tools` 가 비었으면 그 자리에서 끝난다. 자식 프로세스를 안 띄우는 것이 요점이다:
# 훅 값의 97%가 `asgard` 자식을 기다리는 시간이라(26-08-14 실측), 안 쓰는 저장소가 Stop 마다
# 그 값을 내면 안 된다. 들이는 문은 `asgard style init` 하나다.
#
# **막는 것은 이번 세션이 쓴 파일에서 나온 위반뿐이다.** 스타일 도구는 저장소 전체를 보고 오래된
# 위반은 어디에나 있다. 그 전부로 막으면 첫 실행에서 사람이 게이트를 끈다 — craft-gate 의
# 래칫과 같은 이유이고, 귀속은 `asgard style check --path` 가 한다.
#
# 상한 2회는 craft-gate·subagent-gate 와 같은 규약이다. 스타일 도구가 안 깔린 기계에서 같은
# 문장을 무한히 되풀이하면 세션이 인질이 된다 — 이 훅은 조기 교정 장치지 최후 방벽이 아니다.
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.firing import event, run  # noqa: E402

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용
    except Exception:
        pass  # 대체 스트림은 reconfigure 가 없다 — 인코딩을 못 바꿔도 훅은 돌아야 한다

MAX_BLOCKS = 2
MAX_SHOWN = 8
MAX_PATHS = 200
TIMEOUT = 600  # gradle 한 판이 이 안에 끝난다. 도구별 상한은 엔진이 따로 쥔다


def _settings(root: str) -> dict:
    """`code_style` 섹션 — 엔진의 `code_style._section` 과 동일 유지 (단일 출처는 그쪽 모듈)."""
    try:
        with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), encoding="utf-8") as handle:
            config = json.load(handle)
    except Exception:
        return {}
    section = config.get("code_style") if isinstance(config, dict) else None
    return section if isinstance(section, dict) else {}


def _tools(section: dict) -> list[dict]:
    """선언된 도구 행. `_` 로 시작하는 키만 있는 시드는 "안 들임"이다."""
    if section.get("enabled") is False:
        return []
    rows = section.get("tools")
    return [r for r in rows if isinstance(r, dict) and r.get("check")] if isinstance(rows, list) else []


def _owned(rows: list[dict], paths: list[str]) -> list[str]:
    """선언된 도구 중 하나라도 맡는 경로만 — 엔진의 `Tool.owns` 와 같은 규칙.

    이 판정을 훅에서 한 번 더 하는 이유는 자식 프로세스다. 파이썬만 고친 세션에서 자바 도구만
    선언돼 있으면 엔진은 "돌릴 도구 없음"을 낼 텐데, 그 답을 받으려면 `asgard` 를 띄워야 한다.
    """
    out = []
    for rel in paths:
        for row in rows:
            languages = row.get("languages")
            suffixes = tuple(str(s) for s in languages) if isinstance(languages, list) else ()
            if suffixes and not rel.endswith(suffixes):
                continue
            prefixes = row.get("paths")
            scope = [str(p).rstrip("/") for p in prefixes] if isinstance(prefixes, list) else []
            if scope and not any(rel == p or rel.startswith(p + "/") for p in scope):
                continue
            out.append(rel)
            break
    return out


def _sentinel(root: str, sid: str) -> str:
    return os.path.join(root, ".asgard", "state", "writes-" + sid + ".json")


def _writes(root: str, sid: str) -> list[str]:
    try:
        with open(_sentinel(root, sid), encoding="utf-8") as handle:
            rows = json.load(handle)
    except Exception:
        return []
    return [str(r) for r in rows] if isinstance(rows, list) else []


def _caught(root: str, sid: str, agent: str, findings: list[dict], over_cap: bool) -> None:
    """이 게이트가 무엇을 잡았는지 남긴다 — craft-gate 와 같은 계약, 같은 이유.

    사유 칸은 발화한 도구 이름이다. 어느 스타일 도구가 실제로 일하는지가 곧 다음 질문이고,
    한 번도 안 잡는 도구는 선언에서 뺄 후보다.
    """
    rules = sorted({str(f.get("rule")) for f in findings if f.get("rule")})
    event(root, "style", "gate_escalate" if over_cap else "gate_block", ",".join(rules) or "unknown", [agent], sid=sid)


def _skipped(root: str, sid: str, code: str) -> None:
    """판정 없이 사라진 자리를 센다 — craft-gate 와 같은 파일, 같은 이유 (꺼진 것과 통과한 것을 가른다)."""
    if not os.path.isdir(os.path.join(str(root), ".asgard", "state")):
        return
    event(root, "style", "gate_skipped", code, sid=sid)


def _bump(root: str, sid: str, agent: str) -> int:
    """차단 횟수를 올리고 현재 값을 준다. 기록 실패는 0이 아니라 1 — 못 세면 덜 막는 쪽으로."""
    path = os.path.join(root, ".asgard", "state", "stylegate-" + sid + ".json")
    counts = {}
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        counts = loaded if isinstance(loaded, dict) else {}
    except Exception:
        pass  # 첫 차단이라 파일이 없거나 지난 세션 파일이 깨졌다 — 둘 다 0 부터 세는 것이 맞다
    n = int(counts.get(agent, 0)) + 1
    counts[agent] = n
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(counts, handle)
        os.replace(tmp, path)
    except Exception:
        pass  # 셈을 못 남기면 다음 차단이 1 부터 다시 센다 — 덜 막는 쪽이지 세션을 멈출 일은 아니다
    return n


def _judge(exe: str, root: str, paths: list[str], autofix: bool) -> dict | None:
    """`asgard style check --json` 이 유일한 판정 경로 — 훅은 규칙도 도구 표도 안 갖는다.

    None 은 "막을 것이 없다"가 아니라 "판정을 못 받았다"다.
    """
    cmd = [exe, "style", "check", "--json"]
    if autofix:
        cmd.append("--autofix")
    for path in paths[:MAX_PATHS]:
        cmd += ["--path", path]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT, cwd=root, encoding="utf-8", errors="replace"
        )
        payload = json.loads(result.stdout or "{}")
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _reason(payload: dict, truncated: int) -> str:
    blocking = [f for f in payload.get("blocking") or [] if isinstance(f, dict)]
    repaired = [str(c) for c in payload.get("repaired") or []]
    head = ""
    if repaired:
        head = (
            "Asgard style-gate ran %d fix command(s) itself, so files changed on disk: %s. Re-read them before "
            "your next edit or you will write the old lines back. What follows is what still blocks.\n\n"
            % (len(repaired), ", ".join(repaired))
        )
    head += (
        "Asgard style-gate: %d code-style violation(s) in the files this session wrote. These are the "
        "repository's own rules, not Asgard's — the tools that judged are declared in "
        ".asgard/asgard-setting-project.json. Fix them and finish. Re-check with `asgard style check`.\n"
        % len(blocking)
    )
    lines = []
    for finding in blocking[:MAX_SHOWN]:
        where = str(finding.get("path"))
        if finding.get("line"):
            where += ":%s" % finding.get("line")
        lines.append(
            "- [%s] %s — %s\n  fix: %s" % (finding.get("rule"), where, finding.get("detail"), finding.get("fix"))
        )
    if len(blocking) > MAX_SHOWN:
        lines.append("- …and %d more (`asgard style check` shows all)" % (len(blocking) - MAX_SHOWN))
    for row in payload.get("runs") or []:
        if isinstance(row, dict) and row.get("error"):
            lines.append("- note: %s did not run — %s" % (row.get("tool"), row.get("error")))
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


def _protocol(argv: list[str]) -> str:
    """호스트 이름 — Cursor 는 이벤트 이름을 넘기고 나머지는 자기 이름을 넘긴다."""
    given = argv[1] if len(argv) > 1 else ""
    return "cursor" if given in {"pre", "start", "stop"} else given or "claude"


def _session(data: dict, protocol: str) -> str:
    """세션 id — 파일 이름으로 쓰이므로 경로에 못 들어가는 글자를 지운다."""
    raw = "cursor" if protocol == "cursor" else data.get("session_id") or "default"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw))[:64]


def _targets(root: str, sid: str, rows: list[dict]) -> list[str] | None:
    """판정할 경로 — 없으면 사유를 장부에 남기고 None. 여기서 끝나면 자식 프로세스는 안 뜬다."""
    paths = _owned(rows, _writes(root, sid))
    if paths:
        return paths
    _skipped(root, sid, "no-owned-writes" if os.path.exists(_sentinel(root, sid)) else "no-sentinel")
    return None


def _verdict(root: str, sid: str, rows: list[dict], paths: list[str]) -> dict | None:
    """판정 payload — 판정기를 못 부르거나 못 읽으면 사유를 남기고 None."""
    exe = shutil.which("asgard")
    if not exe:
        _skipped(root, sid, "no-asgard")
        return None
    payload = _judge(exe, root, paths, any(r.get("autofix") for r in rows))
    if payload is None:
        _skipped(root, sid, "no-verdict")
    return payload


def _receipt(payload: dict) -> None:
    """막을 것이 없는데 디스크는 바뀐 실행 — 조용히 지나가면 아무도 그 변경을 못 본다."""
    repaired = payload.get("repaired") or []
    if repaired:
        sys.stderr.write(
            "asgard style-gate: ran %d fix command(s), nothing left to block — files on disk changed\n" % len(repaired)
        )


def _decide(root: str, sid: str, agent: str, protocol: str, payload: dict, truncated: int) -> None:
    """막을지 통과시킬지. 상한을 넘은 차단은 경고와 함께 통과한다 — 조기 교정 장치지 방벽이 아니다."""
    blocking = [f for f in payload.get("blocking") or [] if isinstance(f, dict)]
    if not blocking:
        _receipt(payload)
        return
    over_cap = _bump(root, sid, agent) > MAX_BLOCKS
    _caught(root, sid, agent, blocking, over_cap)
    if over_cap:
        sys.stderr.write(
            "asgard style-gate: %s exceeded %d block(s) — allowing (violations stand, unfixed)\n" % (agent, MAX_BLOCKS)
        )
        return
    _block(protocol, _reason(payload, truncated))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    root = ""
    sid = "default"
    try:
        if data.get("stop_hook_active") in (True, "true"):
            sys.exit(0)  # 이미 이 Stop 안에서 돌고 있다 — 무한 루프 방지
        protocol = _protocol(sys.argv)
        root = str(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
        rows = _tools(_settings(root))
        if not rows:
            sys.exit(0)  # 이 저장소는 스타일 레인을 안 들였다 — 셈도 자식 프로세스도 없다
        sid = _session(data, protocol)
        agent = str(data.get("agent_type") or data.get("subagent_type") or "session")
        paths = _targets(root, sid, rows)
        if paths is None:
            sys.exit(0)
        payload = _verdict(root, sid, rows, paths)
        if payload is None:
            sys.exit(0)
        _decide(root, sid, agent, protocol, payload, max(0, len(paths) - MAX_PATHS))
    except Exception:
        _skipped(root, sid, "hook-error")
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    run("style-gate", main)
