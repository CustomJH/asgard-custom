#!/usr/bin/env python3
"""DIRECT 무세금 재검증 — 읽기 전용 질의에 스캐폴드가 얼마를 더 받는가.

문서 `trinity-orchestrator.html` §8 S5 주장: read-only 과업은 원장·게이트가 관여하지 않아
루프 세금이 없고, 비용 차는 AGENTS.md 컨텍스트 몫뿐이다 ($0.535 vs bare $0.479 = 1.12x).
CC 판정 기준(SPEC.md D1)은 오버헤드 ≤ 1.2x · D2 는 quest 미개설.

usage: direct_overhead.py [reps]
"""

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TASKS = ROOT / "workspace" / "bench-cus168" / "tasks"
BASE = Path(os.environ.get("RUNS") or ROOT / "workspace" / "bench-conductor" / "direct")
PROMPT = "이 저장소의 limiter.py 가 무엇을 하는 코드인지, 어떤 상태를 들고 있는지 설명해줘. 파일은 고치지 마."


def sh(cwd, *args, check=True):
    return subprocess.run(list(args), cwd=str(cwd), capture_output=True, text=True, check=check)


def one(arm: str, rep: int) -> dict:
    wd = BASE / ("%s-r%d" % (arm, rep))
    if wd.exists():
        subprocess.run(["rm", "-rf", str(wd)])
    subprocess.run(["cp", "-R", str(TASKS / "t1-ratelimit" / "repo"), str(wd)], check=True)
    sh(wd, "git", "init", "-q")
    sh(wd, "git", "config", "user.email", "b@b")
    sh(wd, "git", "config", "user.name", "b")
    sh(wd, "git", "add", "-A")
    sh(wd, "git", "commit", "-qm", "init")
    if arm == "asgard":
        subprocess.run(
            ["uv", "run", "--project", str(ROOT), "asgard", "init", "--cc", "--yes", "--quiet"],
            cwd=str(wd),
            capture_output=True,
        )
        sh(wd, "git", "add", "-A")
        sh(wd, "git", "commit", "-qm", "scaffold", check=False)

    env = {
        k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")
    }
    t0 = time.time()
    with open(wd / "out.json", "w") as out:
        subprocess.run(
            ["claude", "-p", PROMPT, "--output-format", "json", "--dangerously-skip-permissions", "--max-turns", "40"],
            cwd=str(wd),
            stdout=out,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    wall = int(time.time() - t0)
    d = json.loads((wd / "out.json").read_text())
    dirty = sh(wd, "git", "status", "--porcelain", check=False).stdout.strip().splitlines()
    quest = list((wd / ".asgard" / "quest").glob("*.jsonl")) if (wd / ".asgard" / "quest").is_dir() else []
    return {
        "arm": arm,
        "rep": rep,
        "cost_usd": d.get("total_cost_usd"),
        "turns": d.get("num_turns"),
        "wall_s": wall,
        "dirty_files": [x for x in dirty if "out.json" not in x],
        "quest_opened": len(quest),
    }


def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    BASE.mkdir(parents=True, exist_ok=True)
    rows = [one(arm, r) for r in range(1, reps + 1) for arm in ("plain", "asgard")]
    (BASE / "results.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    for arm in ("plain", "asgard"):
        rs = [r for r in rows if r["arm"] == arm]
        print(
            "%-8s cost_med=$%.3f wall_med=%.0fs turns_med=%.0f quest=%d dirty=%d"
            % (
                arm,
                statistics.median(r["cost_usd"] for r in rs),
                statistics.median(r["wall_s"] for r in rs),
                statistics.median(r["turns"] for r in rs),
                sum(r["quest_opened"] for r in rs),
                sum(len(r["dirty_files"]) for r in rs),
            )
        )
    pc = statistics.median(r["cost_usd"] for r in rows if r["arm"] == "plain")
    ac = statistics.median(r["cost_usd"] for r in rows if r["arm"] == "asgard")
    pw = statistics.median(r["wall_s"] for r in rows if r["arm"] == "plain")
    aw = statistics.median(r["wall_s"] for r in rows if r["arm"] == "asgard")
    print("overhead: cost %.2fx  wall %.2fx  (문서 D1 통과선 ≤ 1.2x)" % (ac / pc, aw / pw))


if __name__ == "__main__":
    main()
