#!/usr/bin/env python3
"""Hook 프로세스 세금 실측 — 한 턴에 뜨는 훅 프로세스 수와 그 CPU 초를 잰다.

`.claude/settings.json` 을 읽어 이벤트별 훅 배선을 하드코딩 없이 뽑고, 훅마다 실제
Claude Code 가 보낼 payload 형태의 stdin 을 먹여 콜드(이 실행에서 처음 뜬 것,
`.claude/hooks/**/__pycache__` 를 지운 뒤)와 웜(그 뒤 N 회 반복의 중앙값) 을 나눠 잰다.
`%CPU` 는 배경 부하에 흔들려 못 쓴다 — `resource.getrusage(RUSAGE_CHILDREN)` 를
호출 앞뒤로 차분해 자식 프로세스의 user+sys CPU 시간만 뽑는다.

읽기 전용이다 — 프로세스를 죽이지 않고 `.claude/settings.json` 도 고치지 않는다.
훅이 스스로 쓰는 `.asgard/state/*` (Git 미추적, `.gitignore` 로 봉인) 는 실행의
자연스러운 부작용으로 남는다.

실행: uv run --no-project python benchmarks/cpu-profile/hook_tax.py [--reps N] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import resource
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / ".claude" / "settings.json"
HOOKS_DIR = ROOT / ".claude" / "hooks"
SESSION_ID = "hooktax-" + uuid.uuid4().hex[:12]

# 이 프로세스가 실제 Claude Code 세션 안에서 돈다면 CLAUDE_CODE_SESSION_ID 등이 이미 환경에
# 있다 — 그대로 물려주면 훅의 host_session_id() 폴백이 우리 합성 payload 대신 **진짜 세션의
# 활성 퀘스트**를 찾아내 그 퀘스트에 진짜 차단 카운터를 쌓는다(26-08-14 첫 실행에서 실측:
# gate-blocks 카운터가 n=10 까지 오르는 사고). 훅 하위 프로세스에는 세션 신원을 지운 환경만
# 물려준다.
_SESSION_ENV_KEYS = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID", "CURSOR_SESSION_ID", "CODEX_SESSION_ID")
CHILD_ENV = {k: v for k, v in os.environ.items() if k not in _SESSION_ENV_KEYS}

# PreToolUse/PostToolUse matcher 정규식이 실제로 무엇과 맞는지 fullmatch 로 판정하는 후보군 —
# settings.json 에 등장하는 매처가 전부 이 목록의 부분집합이다(Bash/Write/Edit/... 도구 이름들).
TOOL_CANDIDATES = ["Agent", "Bash", "Write", "Edit", "NotebookEdit", "Read", "Grep", "Glob", "NotebookRead"]
AGENT_CANDIDATES = ["asgard-worker", "asgard-thinker", "asgard-verifier", "asgard-thor", "asgard-freyja"]
SOURCE_CANDIDATES = ["startup", "resume", "clear", "compact"]

_PROBE_FILE = str(ROOT / "benchmarks" / "cpu-profile" / ".hooktax-probe.txt")
_PROBE_NB = str(ROOT / "benchmarks" / "cpu-profile" / ".hooktax-probe.ipynb")
TOOL_INPUT = {
    "Agent": {"subagent_type": "asgard-worker", "description": "hook-tax probe", "prompt": "profiling probe, no real work"},
    "Bash": {"command": "echo hook-tax-profile"},
    "Write": {"file_path": _PROBE_FILE, "content": "hook-tax probe\n"},
    "Edit": {"file_path": _PROBE_FILE, "old_string": "a", "new_string": "b"},
    "NotebookEdit": {"notebook_path": _PROBE_NB, "new_source": "1"},
    "Read": {"file_path": str(ROOT / "README.md")},
    "Grep": {"pattern": "hook", "path": str(ROOT)},
    "Glob": {"pattern": "*.py"},
    "NotebookRead": {"notebook_path": _PROBE_NB},
}


def load_events() -> dict[str, list[dict]]:
    """이벤트 → [{matcher, argv, path, name}] — settings.json 배선을 그대로 따라간다."""
    cfg = json.loads(SETTINGS.read_text(encoding="utf-8"))
    events: dict[str, list[dict]] = {}
    for event, blocks in cfg.get("hooks", {}).items():
        rows = []
        for block in blocks:
            matcher = block.get("matcher") or "*"
            for h in block.get("hooks", []):
                rows.append({"matcher": matcher, **parse_command(h.get("command", ""))})
        events[event] = rows
    return events


def parse_command(cmd: str) -> dict:
    """`uv run --no-project python "<hook>.py" [args...]` → 실행 가능한 argv 와 스크립트 신원."""
    resolved = cmd.replace("$CLAUDE_PROJECT_DIR", str(ROOT))
    argv = shlex.split(resolved)
    idx = argv.index("python")
    path = Path(argv[idx + 1])
    return {"argv": argv, "path": path, "name": path.stem}


def matches(matcher: str, candidate: str) -> bool:
    """Claude Code 의 `matcher: "*"` 는 정규식이 아니라 와일드카드(전체 일치) 관용구다."""
    if matcher in ("*", "", None):
        return True
    return bool(re.fullmatch(matcher, candidate))


def fullmatch_first(pattern: str, candidates: list[str]) -> str | None:
    for c in candidates:
        if matches(pattern, c):
            return c
    return None


def make_transcript() -> str:
    """훅이 읽는 transcript_path 용 최소 JSONL — 매 훅 호출마다 새로 만들어 상태를 안 섞는다."""
    p = Path(tempfile.gettempdir()) / f"hooktax-transcript-{uuid.uuid4().hex}.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "hook-tax 프로파일 더미"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}},
    ]
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")
    return str(p)


def payload_for(event: str, matcher: str) -> dict:
    base = {
        "session_id": SESSION_ID,
        "cwd": str(ROOT),
        "transcript_path": make_transcript(),
        "hook_event_name": event,
    }
    if event == "SessionStart":
        return {**base, "source": fullmatch_first(matcher, SOURCE_CANDIDATES) or "startup"}
    if event == "UserPromptSubmit":
        return {**base, "prompt": "hook-tax 프로파일링 더미 프롬프트 — 실제 작업 없음"}
    if event in ("SubagentStart", "SubagentStop"):
        agent = fullmatch_first(matcher, AGENT_CANDIDATES) or "asgard-worker"
        return {**base, "agent_type": agent, "subagent_type": agent}
    if event == "PreToolUse":
        tool = fullmatch_first(matcher, TOOL_CANDIDATES) or "Bash"
        return {**base, "tool_name": tool, "tool_input": TOOL_INPUT[tool]}
    if event == "PostToolUse":
        tool = fullmatch_first(matcher, TOOL_CANDIDATES) or "Bash"
        return {**base, "tool_name": tool, "tool_input": TOOL_INPUT[tool], "tool_response": {"is_error": False, "output": "hook-tax-profile\n"}}
    if event == "Stop":
        return {**base, "stop_hook_active": False}
    return base


def clear_pycache() -> None:
    for d in HOOKS_DIR.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def run_once(argv: list[str], payload: dict) -> dict:
    stdin_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.perf_counter()
    proc = subprocess.run(argv, input=stdin_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=CHILD_ENV)
    wall_ms = (time.perf_counter() - t0) * 1000
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_ms = ((after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)) * 1000
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    return {"wall_ms": wall_ms, "cpu_ms": cpu_ms, "exit_code": proc.returncode, "no_op": proc.returncode == 0 and not out}


def profile_script(entry: dict, event: str, reps: int) -> dict:
    """스크립트 하나(경로 기준 유일)의 콜드 1회 + 웜 reps 회 — pycache 는 이미 지운 상태에서 부른다."""
    payload = payload_for(event, entry["matcher"])
    cold = run_once(entry["argv"], payload)
    warm = [run_once(entry["argv"], payload) for _ in range(reps)]
    return {
        "name": entry["name"],
        "path": str(entry["path"].relative_to(ROOT)),
        "cold_wall_ms": cold["wall_ms"],
        "cold_cpu_ms": cold["cpu_ms"],
        "cold_exit_code": cold["exit_code"],
        "warm_wall_ms": statistics.median(r["wall_ms"] for r in warm),
        "warm_cpu_ms": statistics.median(r["cpu_ms"] for r in warm),
        "warm_no_op_rate": sum(r["no_op"] for r in warm) / len(warm),
        "warm_exit_nonzero": sum(1 for r in warm if r["exit_code"] != 0),
    }


def duplicate_registrations(rows: list[dict]) -> dict:
    """같은 스크립트가 한 이벤트에 여러 matcher 로 등록됐을 때, 실제 도구 호출 하나가
    몇 번 fire 하는지 — matcher 가 겹치지 않으면 등록 횟수와 무관하게 호출당 1회다."""
    by_name: dict[str, list[str]] = {}
    for e in rows:
        by_name.setdefault(e["name"], []).append(e["matcher"])
    out = {}
    for name, matchers in by_name.items():
        if len(matchers) < 2:
            continue
        overlap = {t: sum(1 for m in matchers if matches(m, t)) for t in TOOL_CANDIDATES}
        out[name] = {
            "registrations": matchers,
            "max_fires_per_single_tool_call": max(overlap.values()) if overlap else 0,
            "tools_that_fire_more_than_once": {t: c for t, c in overlap.items() if c > 1},
        }
    return out


def tool_fire_map(events: dict[str, list[dict]], scripts: dict[str, dict]) -> dict:
    """도구 이름 하나가 실제 Bash 호출 하나로 들어왔을 때 뜨는 PreToolUse/PostToolUse 훅 목록."""
    out = {}
    for tool in TOOL_CANDIDATES:
        pre = [e for e in events.get("PreToolUse", []) if matches(e["matcher"], tool)]
        post = [e for e in events.get("PostToolUse", []) if matches(e["matcher"], tool)]
        entries = pre + post
        out[tool] = {
            "pre_hooks": [e["name"] for e in pre],
            "post_hooks": [e["name"] for e in post],
            "process_count": len(entries),
            "warm_cpu_ms": sum(scripts[str(e["path"])]["warm_cpu_ms"] for e in entries),
            "warm_wall_ms": sum(scripts[str(e["path"])]["warm_wall_ms"] for e in entries),
        }
    return out


def turn_tax(event_totals: dict, tool_fire: dict, k: int, tool: str = "Bash") -> dict:
    """도구 호출 K회짜리 턴 하나의 총 프로세스 수·CPU 초 — UserPromptSubmit·Stop 은
    턴당 1회 고정, 도구별 Pre/PostToolUse 는 K 회 반복. 도구 종류는 `tool` 로 대표한다."""
    fixed_procs = event_totals["UserPromptSubmit"]["hook_count"] + event_totals["Stop"]["hook_count"]
    fixed_cpu_ms = event_totals["UserPromptSubmit"]["warm_cpu_ms_sum"] + event_totals["Stop"]["warm_cpu_ms_sum"]
    fixed_wall_ms = event_totals["UserPromptSubmit"]["warm_wall_ms_sum"] + event_totals["Stop"]["warm_wall_ms_sum"]
    per_call = tool_fire[tool]
    return {
        "processes": fixed_procs + k * per_call["process_count"],
        "cpu_s": (fixed_cpu_ms + k * per_call["warm_cpu_ms"]) / 1000,
        "wall_s_serial": (fixed_wall_ms + k * per_call["warm_wall_ms"]) / 1000,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=8, help="웜 반복 횟수 (기본 8)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    events = load_events()
    clear_pycache()  # 콜드 측정의 전제 — 이 실행 안에서만 유효, 재생성은 정상 사용의 일부

    scripts: dict[str, dict] = {}
    for event, rows in events.items():
        for entry in rows:
            key = str(entry["path"])
            if key not in scripts:  # 같은 .py 가 여러 이벤트에 걸려도 콜드/웜은 한 번만
                scripts[key] = profile_script(entry, event, args.reps)

    event_totals = {}
    dup = {}
    for event, rows in events.items():
        hooks = [scripts[str(e["path"])] for e in rows]
        event_totals[event] = {
            "hook_count": len(rows),
            "unique_scripts": len({str(e["path"]) for e in rows}),
            "warm_cpu_ms_sum": sum(h["warm_cpu_ms"] for h in hooks),
            "warm_wall_ms_sum": sum(h["warm_wall_ms"] for h in hooks),
        }
        d = duplicate_registrations(rows)
        if d:
            dup[event] = d

    fire = tool_fire_map(events, scripts)
    turns = {k: turn_tax(event_totals, fire, k, "Bash") for k in (10, 30, 60)}

    no_op = {name: s["warm_no_op_rate"] for name, s in scripts.items()}
    report = {
        "meta": {"reps": args.reps, "python": sys.version.split()[0], "platform": sys.platform},
        "scripts": scripts,
        "events": event_totals,
        "duplicate_registrations": dup,
        "tool_fire": fire,
        "turn_tax_bash_representative": turns,
        "no_op_rate": no_op,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"reps={args.reps} python={report['meta']['python']} platform={report['meta']['platform']}\n")
    print("스크립트별 콜드/웜 (ms)")
    for key, s in sorted(scripts.items()):
        print(
            f"  {s['name']:<20s} cold wall={s['cold_wall_ms']:6.1f} cpu={s['cold_cpu_ms']:6.1f}"
            f"  | warm wall={s['warm_wall_ms']:6.1f} cpu={s['warm_cpu_ms']:6.1f}"
            f"  no_op={s['warm_no_op_rate']:.0%}"
        )

    print("\n이벤트별 합계 (웜 기준)")
    for event, t in event_totals.items():
        print(
            f"  {event:<16s} hooks={t['hook_count']:2d} unique={t['unique_scripts']:2d}"
            f"  cpu_sum={t['warm_cpu_ms_sum']:7.1f}ms  wall_sum={t['warm_wall_ms_sum']:7.1f}ms"
        )

    print("\n중복 등록 판정 (matcher 가 겹칠 때만 실제 중복)")
    if not dup:
        print("  없음 — 여러 matcher 로 등록된 스크립트가 없다")
    for event, d in dup.items():
        for name, info in d.items():
            print(f"  [{event}] {name}: {info['registrations']} -> 도구 호출당 최대 {info['max_fires_per_single_tool_call']}회")
            if info["tools_that_fire_more_than_once"]:
                print(f"    실제 중복 발화 도구: {info['tools_that_fire_more_than_once']}")

    print("\n도구별 PreToolUse+PostToolUse 발화 (웜)")
    for tool, f in fire.items():
        print(f"  {tool:<14s} procs={f['process_count']}  cpu={f['warm_cpu_ms']:6.1f}ms  wall={f['warm_wall_ms']:6.1f}ms  pre={f['pre_hooks']} post={f['post_hooks']}")

    print("\n턴 세금 (Bash 도구 K 회 반복 + UserPromptSubmit/Stop 1회, 웜 기준)")
    for k, t in turns.items():
        print(f"  K={k:<3d} processes={t['processes']:4d}  cpu={t['cpu_s']:.3f}s  wall_serial={t['wall_s_serial']:.3f}s")

    return 0


def clear_synthetic_state() -> list[str]:
    """훅이 이 하네스의 합성 세션 앞으로 남긴 `.asgard/state` 파일을 지운다.

    `hooktax-` 접두사는 `SESSION_ID` 가 이 파일에서만 만드는 것이라 실제 세션 id(접두사 없는
    uuid)와 겹치지 않는다. 지우는 대상이 이 하네스 자신의 산물로 한정된다는 뜻이다.
    """
    state = ROOT / ".asgard" / "state"
    removed = []
    for path in state.glob("*hooktax-*.json"):
        try:
            path.unlink()
            removed.append(str(path))
        except OSError:
            pass  # 다른 프로세스가 먼저 지웠거나 권한이 없으면 그대로 둔다
    return removed


if __name__ == "__main__":
    try:
        _code = main()
    finally:
        clear_synthetic_state()
    sys.exit(_code)
