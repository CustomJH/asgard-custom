#!/usr/bin/env python3
"""주입 훅 디스패처 — 출력 동일성 대조와 전/후 실측.

두 가지를 한다.

1. **동일성.** 이벤트마다 훅을 지금처럼 하나씩 따로 돌린 출력과, 디스패처 하나를 돌린 출력을
   채널별로 바이트 대조한다. 채널이 둘인 이유는 훅마다 형식이 다르기 때문이다 — 평문 stdout,
   `hookSpecificOutput.additionalContext`, `systemMessage` 가 한 이벤트에 섞여 나온다.
   합칠 때 보존해야 하는 것은 와이어 형식이 아니라 **채널별 텍스트와 그 순서**다.

2. **값.** 프로세스 수·CPU 시간·벽시계·최대 RSS 를 전/후로 잰다. `%CPU` 는 안 쓴다
   (`resource.getrusage(RUSAGE_CHILDREN)` 차분). 이 기계는 조용하지 않으므로 전/후를
   **번갈아** 재고 최솟값과 중앙값을 둘 다 낸다.

RSS 는 자식 하나마다 새 파이썬 껍데기를 씌워 잰다 — `ru_maxrss` 는 합이 아니라 최댓값이라
한 프로세스에서 이어 재면 훅 13개의 값이 그중 가장 큰 하나로 접힌다.

실행: uv run --no-project python benchmarks/cpu-profile/dispatch_check.py [--rounds N] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_tax import CHILD_ENV, ROOT, make_transcript  # noqa: E402

HOOKS = ROOT / ".claude" / "hooks"
DISPATCH = HOOKS / "hook-dispatch.py"
PY = ["uv", "run", "--no-project", "python"]
SESSION_ID = "dispatchchk-" + uuid.uuid4().hex[:12]

# 합칠 대상 — 배선표 그대로. 각 항목은 `(훅 파일, 추가 인자)`.
PLAN: dict[str, dict] = {
    "UserPromptSubmit": {
        "payload": {"prompt": "디스패처 동일성 대조용 더미 프롬프트 — 실제 작업 없음"},
        "hooks": [
            ("unattended-context.py", []),
            ("lagom-tracker.py", []),
            ("memory-activate.py", []),
            ("charter-activate.py", []),
            ("manual-activate.py", []),
            ("agent-activate.py", []),
            ("map-activate.py", []),
            ("scope-activate.py", []),
            ("siege-inbox.py", []),
            ("tutor-note.py", ["claude", "brief"]),
        ],
    },
    "SubagentStart": {
        "payload": {"agent_type": "asgard-worker", "subagent_type": "asgard-worker"},
        "hooks": [
            ("lagom-subagent.py", []),
            ("charter-activate.py", []),
            ("manual-activate.py", []),
            ("agent-activate.py", []),
            ("map-activate.py", []),
            ("scope-activate.py", []),
            ("dispatch-context.py", []),
        ],
    },
    # 배선된 모양 그대로: 일곱은 묶고 memory-activate 는 자기 matcher(^asgard-thinker$) 위에
    # 그대로 둔다. 그 matcher 가 격리 매트릭스(Verifier·Loki 영구 무주입)의 바깥 겹이라,
    # 묶으려면 그것을 지워야 한다. `standalone` 은 합친 뒤에도 따로 뜨는 훅이다.
    "SubagentStart(thinker)": {
        "event": "SubagentStart",
        "payload": {"agent_type": "asgard-thinker", "subagent_type": "asgard-thinker"},
        "hooks": [
            ("lagom-subagent.py", []),
            ("charter-activate.py", []),
            ("manual-activate.py", []),
            ("agent-activate.py", []),
            ("map-activate.py", []),
            ("scope-activate.py", []),
            ("dispatch-context.py", []),
            ("memory-activate.py", []),
        ],
        "standalone": [("memory-activate.py", [])],
    },
    "SessionStart": {
        "payload": {"source": "startup"},
        "hooks": [
            ("lagom-activate.py", []),
            ("memory-activate.py", []),
            ("charter-activate.py", []),
            ("manual-activate.py", []),
            ("agent-activate.py", []),
            ("map-activate.py", []),
        ],
    },
    "Stop": {
        "payload": {"stop_hook_active": False},
        "hooks": [
            ("memory-activate.py", []),
            ("map-activate.py", []),
            ("tutor-note.py", []),
        ],
    },
}


def payload_for(name: str) -> dict:
    spec = PLAN[name]
    return {
        "session_id": SESSION_ID,
        "cwd": str(ROOT),
        "transcript_path": make_transcript(),
        "hook_event_name": spec.get("event", name),
        **spec["payload"],
    }


def channels(text: str) -> tuple:
    """`hook_dispatch.channels` 와 같은 규칙 — 훅 출력을 (컨텍스트, 사람 표면) 으로 가른다."""
    if not text.strip():
        return "", ""
    try:
        data = json.loads(text)
    except Exception:
        return text, ""
    if not isinstance(data, dict):
        return text, ""
    context = ""
    spec = data.get("hookSpecificOutput")
    if isinstance(spec, dict):
        context = str(spec.get("additionalContext") or "")
    if not context:
        context = str(data.get("additional_context") or "")
    message = str(data.get("systemMessage") or data.get("user_message") or data.get("followup_message") or "")
    return context, message


def run(argv: list, payload: dict) -> dict:
    stdin_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    proc = subprocess.run(argv, input=stdin_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=CHILD_ENV)
    wall_ms = (time.perf_counter() - start) * 1000
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_ms = ((after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)) * 1000
    return {
        "stdout": proc.stdout.decode("utf-8", errors="replace"),
        "stderr": proc.stderr.decode("utf-8", errors="replace"),
        "exit": proc.returncode,
        "cpu_ms": cpu_ms,
        "wall_ms": wall_ms,
    }


_RSS_PROBE = (
    "import json,resource,subprocess,sys;"
    "argv=json.loads(sys.argv[1]);"
    "data=sys.stdin.buffer.read();"
    "subprocess.run(argv,input=data,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
    "print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)"
)


def peak_rss(argv: list, payload: dict) -> int:
    """자식 하나의 최대 RSS(바이트, macOS 기준). 껍데기를 새로 띄워 그 자식만 재게 한다."""
    stdin_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    proc = subprocess.run(
        [*PY, "-c", _RSS_PROBE, json.dumps(argv)],
        input=stdin_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=CHILD_ENV,
    )
    try:
        return int(proc.stdout.decode().strip())
    except Exception:
        return 0


def before_argvs(name: str) -> list:
    return [[*PY, str(HOOKS / hook), *args] for hook, args in PLAN[name]["hooks"]]


def after_argvs(name: str) -> list:
    """합친 뒤 실제로 뜨는 명령들 — 디스패처 하나, 그리고 제자리에 남긴 훅이 있으면 그것들."""
    kept = {hook for hook, _ in PLAN[name].get("standalone", [])}
    argv = [*PY, str(DISPATCH)]
    for hook, args in PLAN[name]["hooks"]:
        if hook not in kept:
            argv += ["--", str(HOOKS / hook), *args]
    return [argv] + [[*PY, str(HOOKS / hook), *args] for hook, args in PLAN[name].get("standalone", [])]


def measure(argvs: list, payload: dict) -> dict:
    """명령 여럿을 돌려 채널별로 이어 붙인 것 + 그 값. 전/후가 같은 함수를 지난다 — 대조하는
    두 문자열이 다른 코드에서 나오면 무엇이 같은지가 흐려진다."""
    runs = [run(argv, payload) for argv in argvs]
    contexts, messages = [], []
    for result in runs:
        context, message = channels(result["stdout"])
        if context.strip():
            contexts.append(context.rstrip("\n"))
        if message.strip():
            messages.append(message.rstrip("\n"))
    return {
        "processes": len(runs),
        "cpu_ms": sum(r["cpu_ms"] for r in runs),
        "wall_ms_sum": sum(r["wall_ms"] for r in runs),
        "wall_ms_parallel": max((r["wall_ms"] for r in runs), default=0.0),
        "context": "\n".join(contexts),
        "message": "\n\n".join(messages),
        "exit": max((r["exit"] for r in runs), default=0),
        "stderr": "".join(r["stderr"] for r in runs)[:400],
    }


def diff_note(left: str, right: str) -> str:
    if left == right:
        return ""
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return "첫 불일치 offset=%d  before=%r  after=%r" % (index, left[index : index + 60], right[index : index + 60])
    return "길이만 다름 before=%d after=%d  꼬리=%r" % (len(left), len(right), (left or right)[min(len(left), len(right)) :][:120])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--only", default="", help="이 이벤트만")
    parser.add_argument("--no-rss", action="store_true")
    args = parser.parse_args()

    names = [n for n in PLAN if not args.only or n == args.only]
    report: dict = {}
    for name in names:
        rows = {"before": [], "after": []}
        equal = {"context": True, "message": True}
        # 순서별 불일치 수 — 한쪽 순서에서만 나면 원인은 합치기가 아니라 한 번만 내는 훅이다.
        by_order = {"before_first": 0, "after_first": 0}
        note = {}
        for index in range(args.rounds):
            # 번갈아 잰다 — 붙여서 재면 캐시·배경 부하가 한쪽에만 들어간다. 순서까지 번갈아
            # 뒤집는 이유는 훅 중에 **한 번만 내는** 것이 있어서다 (`memory tick` 의 넛지는
            # 래치가 걸린다). 먼저 도는 쪽이 그것을 먹으면, 순서가 고정된 대조는 매번 뒤쪽을
            # "다르다"로 판정한다 — 디스패처와 무관한 차이다.
            payload = payload_for(name)
            if index % 2:
                after = measure(after_argvs(name), payload)
                before = measure(before_argvs(name), payload)
            else:
                before = measure(before_argvs(name), payload)
                after = measure(after_argvs(name), payload)
            rows["before"].append(before)
            rows["after"].append(after)
            for channel in ("context", "message"):
                if before[channel] != after[channel]:
                    equal[channel] = False
                    by_order["after_first" if index % 2 else "before_first"] += 1
                    note[channel] = diff_note(before[channel], after[channel])
        stat = {}
        for side in ("before", "after"):
            for key in ("cpu_ms", "wall_ms_sum", "wall_ms_parallel"):
                values = [r[key] for r in rows[side]]
                stat["%s_%s_min" % (side, key)] = min(values)
                stat["%s_%s_med" % (side, key)] = statistics.median(values)
        entry = {
            "processes_before": rows["before"][0]["processes"],
            "processes_after": rows["after"][0]["processes"],
            "identical": equal,
            "mismatches_by_order": by_order,
            "diff": note,
            "context_bytes": len(rows["after"][-1]["context"].encode("utf-8")),
            "message_bytes": len(rows["after"][-1]["message"].encode("utf-8")),
            "after_exit": rows["after"][-1]["exit"],
            "after_stderr": rows["after"][-1]["stderr"],
            **stat,
        }
        if not args.no_rss:
            payload = payload_for(name)
            per_hook = [peak_rss(argv, payload) for argv in before_argvs(name)]
            entry["rss_before_sum_mb"] = sum(per_hook) / 1e6
            entry["rss_before_max_mb"] = (max(per_hook) if per_hook else 0) / 1e6
            entry["rss_after_mb"] = sum(peak_rss(argv, payload) for argv in after_argvs(name)) / 1e6
        report[name] = entry

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    ok = True
    for name, entry in report.items():
        same = entry["identical"]["context"] and entry["identical"]["message"]
        ok = ok and same
        print(
            "== %s  procs %d -> %d  %s"
            % (name, entry["processes_before"], entry["processes_after"], "동일" if same else "다름")
        )
        for channel in ("context", "message"):
            if not entry["identical"][channel]:
                print("   [%s] %s" % (channel, entry["diff"].get(channel, "")))
                print("   불일치 회차: %s" % entry["mismatches_by_order"])
        print(
            "   cpu   min %7.1f -> %7.1f ms   med %7.1f -> %7.1f ms"
            % (
                entry["before_cpu_ms_min"],
                entry["after_cpu_ms_min"],
                entry["before_cpu_ms_med"],
                entry["after_cpu_ms_med"],
            )
        )
        print(
            "   wall  min %7.1f -> %7.1f ms (병렬 가정 %7.1f)   med %7.1f -> %7.1f ms"
            % (
                entry["before_wall_ms_sum_min"],
                entry["after_wall_ms_sum_min"],
                entry["before_wall_ms_parallel_min"],
                entry["before_wall_ms_sum_med"],
                entry["after_wall_ms_sum_med"],
            )
        )
        if "rss_after_mb" in entry:
            print(
                "   rss   합 %6.1f MB (최대 하나 %5.1f) -> %5.1f MB"
                % (entry["rss_before_sum_mb"], entry["rss_before_max_mb"], entry["rss_after_mb"])
            )
        if entry["after_exit"] != 0:
            print("   after exit=%s stderr=%s" % (entry["after_exit"], entry["after_stderr"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
