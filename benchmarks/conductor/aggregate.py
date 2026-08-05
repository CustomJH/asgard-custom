#!/usr/bin/env python3
"""Conductor 대조 집계 — 논문 §4.2/§4.3 표 모양으로 결과를 모은다.

usage: aggregate.py [results_dir]
"""

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[1] / "workspace" / "bench-conductor" / "results"
ARMS = ["plain", "reflect", "asgard"]
# 난이도 사다리 — 논문 Fig 8 의 가로축 대응
TASK_TIER = {
    "t6-pagination": "easy (off-by-one)",
    "t5-dates": "medium (timezone bug)",
    "t3-config": "hard (refactor + hidden callers)",
}


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def fmt(v, spec="%.2f"):
    return "—" if v is None else spec % v


def main():
    rows = [json.loads(p.read_text()) for p in sorted(RES.glob("*.json"))]
    if not rows:
        print("no results in %s" % RES)
        return
    by_arm = {a: [r for r in rows if r["arm"] == a] for a in ARMS}

    print("\n=== Table 1 shape — reward by task (논문 §3.1 보상: 0 / 0.5 / 1.0) ===")
    tasks = sorted({r["task"] for r in rows}, key=lambda t: list(TASK_TIER).index(t) if t in TASK_TIER else 9)
    print("%-10s %s  %s" % ("arm", "  ".join("%-22s" % t for t in tasks), "Avg"))
    for a in ARMS:
        cells, allr = [], []
        for t in tasks:
            rs = [r for r in by_arm[a] if r["task"] == t]
            allr += [r["reward"] for r in rs]
            cells.append("%-22s" % ("%.2f (n=%d)" % (statistics.mean(r["reward"] for r in rs), len(rs)) if rs else "—"))
        print("%-10s %s  %s" % (a, "  ".join(cells), fmt(statistics.mean(allr) if allr else None)))

    print("\n=== Fig 5 shape — performance vs efficiency ===")
    print("%-10s %5s %8s %11s %10s %9s %8s" % ("arm", "n", "reward", "agent_calls", "cost_med", "wall_med", "turns"))
    for a in ARMS:
        rs = by_arm[a]
        if not rs:
            continue
        print(
            "%-10s %5d %8s %11s %10s %9s %8s"
            % (
                a,
                len(rs),
                fmt(statistics.mean(r["reward"] for r in rs)),
                fmt(statistics.mean(r["agent_calls"] for r in rs if r.get("agent_calls") is not None)),
                fmt(med([r.get("cost_usd") for r in rs]), "$%.2f"),
                fmt(med([r["wall_s"] for r in rs]), "%.0fs"),
                fmt(med([r.get("turns") for r in rs]), "%.0f"),
            )
        )

    base = by_arm["plain"]
    if base:
        bc, bw = med([r.get("cost_usd") for r in base]), med([r["wall_s"] for r in base])
        print("\n=== 세금 (plain 대비 중앙값 배수) ===")
        for a in ARMS[1:]:
            rs = by_arm[a]
            if not rs:
                continue
            c, w = med([r.get("cost_usd") for r in rs]), med([r["wall_s"] for r in rs])
            print(
                "  %-8s cost %sx  wall %sx"
                % (a, fmt(c / bc if c and bc else None, "%.2f"), fmt(w / bw if w and bw else None, "%.2f"))
            )

    print("\n=== Fig 8 shape — workflow steps by task difficulty (asgard 아암, 라이브) ===")
    print("%-34s %6s %12s %12s %11s" % ("task", "n", "steps", "agent_calls", "verify_cmds"))
    for t in tasks:
        rs = [r for r in by_arm["asgard"] if r["task"] == t]
        if not rs:
            continue
        print(
            "%-34s %6d %12s %12s %11s"
            % (
                TASK_TIER.get(t, t),
                len(rs),
                fmt(statistics.mean(r.get("workflow_steps", 0) for r in rs)),
                fmt(statistics.mean(r.get("agent_calls") or 0 for r in rs)),
                fmt(statistics.mean(r.get("verify_cmds", 0) for r in rs)),
            )
        )

    print("\n=== Fig 7 shape — 배정된 서브에이전트 분포 ===")
    dist = {}
    for r in rows:
        for a in r.get("agents") or []:
            dist[a] = dist.get(a, 0) + 1
    total = sum(dist.values()) or 1
    for a, n in sorted(dist.items(), key=lambda kv: -kv[1]):
        print("  %-20s %4d  %5.1f%%" % (a, n, 100.0 * n / total))
    if not dist:
        print("  (없음)")

    print("\n=== 개별 세션 ===")
    print("%-28s %7s %7s %6s %8s %7s %s" % ("id", "reward", "cases", "calls", "cost", "wall", "verdict"))
    for r in rows:
        print(
            "%-28s %7.1f %7s %6s %8s %7s %s"
            % (
                r["id"],
                r["reward"],
                "%d/%d" % (r["cases_passed"], r["cases_total"]),
                r.get("agent_calls"),
                fmt(r.get("cost_usd"), "$%.2f"),
                "%ds" % r["wall_s"],
                r.get("final_verdict") or ("timeout" if r.get("timeout") else "-"),
            )
        )


if __name__ == "__main__":
    main()
