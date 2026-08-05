#!/usr/bin/env python3
"""Conductor(arXiv 2512.04388) 평가 축을 Asgard 조율 계층에 적용 — 0-LLM 정책 롤아웃.

논문은 학습된 7B Conductor 가 문제마다 워크플로(스텝 수·배정 에이전트·접근 리스트)를 새로
짜고, 그 스텝 수가 난이도를 따라간다고 보고한다 (Fig 8: MMLU 1~2 스텝 · LiveCodeBench 3~4,
전체 평균 3 / 상한 5). Asgard 의 대응물은 학습이 아니라 결정 테이블(`transition`)이므로,
같은 축을 LLM 없이 잴 수 있다 — 배포 형태의 훅 CLI 를 격리 저장소에서 그대로 돌려
과업 프로필별 역할 시퀀스를 관측한다.

재는 것 (논문 축 → 여기 축):
  workflow steps        → DONE 까지의 역할 배정 수
  agent calls (Fig 5)   → 그중 LLM 턴이 필요한 역할 수 (BASELINE_VERIFY 는 0-LLM)
  task adaptivity (Fig 8) → 프로필 난이도별 스텝 분포
  agent selection (Fig 7) → 배정된 역할의 분포

실행: uv run python benchmarks/conductor/policy_rollout.py
출력: benchmarks/conductor/results-policy.json + stdout 표
"""

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QLOG = str(ROOT / "src" / "asgard" / "hooks" / "quest_log.py")
SENSITIVE = ".claude/hooks/thing.py"  # 정책의 sensitive_paths 에 걸리는 경로
MAX_STEPS = 12  # 무한 루프 방어 — 정상 롤아웃은 한 자릿수

# 난이도 사다리. tier 는 논문 Fig 8 의 가로축(과업 종류) 대응 — 읽기전용(가장 쉬움) →
# 민감/대형/반복실패(가장 어려움). fails = Verifier 가 FAIL 을 내는 횟수(그 뒤 PASS).
PROFILES = [
    # name,            tier, files, lines, sensitive, fails, flags
    ("readonly", 0, 0, 0, False, 0, {"no_write": True}),
    ("tiny-tested", 1, 1, 6, False, 0, {"tests": True}),
    ("small", 2, 2, 40, False, 0, {}),
    ("medium", 3, 3, 120, False, 0, {}),
    ("large", 4, 8, 400, False, 0, {}),
    ("sensitive", 4, 1, 20, True, 0, {}),
    ("ambiguous", 3, 2, 60, False, 0, {"ambiguous": True}),
    ("parallel", 4, 4, 200, False, 0, {"parallel": True}),
    ("research", 4, 2, 60, False, 0, {"external_research": True}),
    ("fail-1", 3, 2, 60, False, 1, {}),
    ("fail-3", 5, 2, 60, False, 3, {}),
    ("destructive", 5, 1, 10, False, 0, {"destructive": True}),
]

LLM_ROLES = {"THINKER", "THINKER_REPLAN", "WORKER", "WORKER_RETRY", "VERIFIER"}
TERMINAL = {"DONE", "DIRECT_DONE", "ESCALATE_ODIN"}


def sh(cwd, *args):
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True)


def ql(root, *args, stdin=""):
    """배포 형태 그대로 — 매회 새 python 프로세스."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    t0 = time.perf_counter()
    p = subprocess.run(
        [sys.executable, QLOG, *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=root,
        env=env,
        timeout=180,
    )
    ms = (time.perf_counter() - t0) * 1000.0
    try:
        out = json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        out = {"raw": p.stdout, "stderr": p.stderr}
    return ms, out


def mkrepo(tmp: str) -> str:
    root = os.path.join(tmp, "repo")
    os.makedirs(root)
    sh(root, "git", "init", "-q")
    sh(root, "git", "config", "user.email", "b@b")
    sh(root, "git", "config", "user.name", "b")
    Path(root, "app.py").write_text("print('ok')\n")
    lvl = os.environ.get("VERIFY_LEVEL")
    if lvl:
        cfg = Path(root, ".asgard")
        cfg.mkdir(exist_ok=True)
        (cfg / "trinity-policy.json").write_text(json.dumps({"verify_level": lvl}))
    Path(root, "tests").mkdir()
    Path(root, "tests", "test_app.py").write_text("def test_ok():\n    assert True\n")
    sh(root, "git", "add", "-A")
    sh(root, "git", "commit", "-qm", "init")
    return root


def apply_diff(root: str, files: int, lines: int, sensitive: bool):
    """Worker 턴의 물리 결과 — 파일 수·라인 수가 전이 축(diff_files/diff_lines)이다."""
    if sensitive:
        p = Path(root, SENSITIVE)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join("x = %d" % i for i in range(lines)) + "\n")
        return
    per = max(1, lines // max(1, files))
    for i in range(files):
        Path(root, "mod_%d.py" % i).write_text("\n".join("v%d = %d" % (i, j) for j in range(per)) + "\n")


def flags_for(flags: dict) -> list[str]:
    m = {
        "ambiguous": "--ambiguous",
        "destructive": "--destructive",
        "external_research": "--external-research",
        "parallel": "--parallel-requested",
    }
    return [m[k] for k in m if flags.get(k)]


def rollout(root: str, qid: str, prof) -> dict:
    """한 과업의 워크플로 — DONE 까지 누가 몇 번 도는가."""
    name, tier, files, lines, sensitive, fails, flags = prof
    extra = flags_for(flags)
    open_args = ["open", qid, "--criteria", "the check command exits 0", "--request", name]
    if flags.get("no_write"):
        open_args.append("--no-write")
    ql(root, *open_args)

    seq, fired, wall, researched, levels = [], 0, 0.0, False, set()
    for _ in range(MAX_STEPS):
        args = ["next", *extra]
        if not seq and not flags.get("no_write"):
            args.append("--write-expected")  # 아직 diff 0 인 첫 배정
        ms, out = ql(root, *args)
        wall += ms
        role = out.get("next_role", "?")
        levels.add(out.get("verify_level") or "?")
        if role in TERMINAL:
            seq.append(role)
            break
        seq.append(role)
        # 배정된 역할의 턴을 흉내낸다 — 물리 결과만 남기고 판정은 전이 함수가 낸다
        if role in ("WORKER", "WORKER_RETRY"):
            if flags.get("external_research") and not researched:
                # 조사 Worker 는 읽기 전용 — 물리 diff 없이 findings 만 남긴다 (summary._research_i 계약)
                researched = True
                body = {"role": "worker", "event": "work", "research_only": True, "research_findings": "upstream docs"}
            else:
                apply_diff(root, files, lines, sensitive)
                body = {"role": "worker", "event": "work"}
            ms, _ = ql(root, "append", "--json", json.dumps(body))
        elif role in ("THINKER", "THINKER_REPLAN"):
            body = {"role": "thinker", "event": "plan", "criteria": ["the check command exits 0"]}
            ms, _ = ql(root, "append", "--json", json.dumps(body))
        elif role == "VERIFIER":
            verdict = "FAIL" if fired < fails else "PASS"
            fired += 1 if verdict == "FAIL" else 0
            body = {
                "role": "verifier",
                "event": "verify",
                "criteria": ["the check command exits 0"],
                "commands": [{"cmd": "python3 -c pass", "exit_code": 0 if verdict == "PASS" else 1}],
            }
            if verdict == "FAIL":
                body["failure_sig"] = "check-red"
            level = "full" if sensitive or files > 2 else "micro"
            ms, _ = ql(root, "append", "--json", json.dumps(body), "--verdict", verdict, "--level", level)
        elif role == "BASELINE_VERIFY":
            ms, _ = ql(root, "verify-baseline")
        else:
            break
        wall += ms
    assigned = [r for r in seq if r not in TERMINAL]
    return {
        "profile": name,
        "tier": tier,
        "steps": len(assigned),
        "llm_calls": sum(1 for r in assigned if r in LLM_ROLES),
        "sequence": seq,
        "terminal": seq[-1] if seq else None,
        "verify_level": "/".join(sorted(levels - {"?"})) or "-",
        "harness_ms": round(wall, 1),
    }


def main():
    reps = int(os.environ.get("REPS", "3"))
    rows = []
    for rep in range(reps):
        with tempfile.TemporaryDirectory() as tmp:
            for i, prof in enumerate(PROFILES):
                root = mkrepo(os.path.join(tmp, "r%d_%d" % (rep, i)))
                rows.append(rollout(root, "q%d" % i, prof))

    by = {}
    for r in rows:
        by.setdefault(r["profile"], []).append(r)

    print("\n=== workflow steps by task profile (Fig 8 축) ===")
    print("%-14s %4s %7s %10s %-6s %s" % ("profile", "tier", "steps", "llm", "level", "sequence"))
    for name, _t, *_rest in PROFILES:
        rs = by[name]
        seqs = {" → ".join(r["sequence"]) for r in rs}
        print(
            "%-14s %4d %7.1f %10.1f %-6s %s"
            % (
                name,
                rs[0]["tier"],
                statistics.mean(r["steps"] for r in rs),
                statistics.mean(r["llm_calls"] for r in rs),
                rs[0]["verify_level"],
                " | ".join(sorted(seqs)),
            )
        )

    steps = [r["steps"] for r in rows]
    llm = [r["llm_calls"] for r in rows]
    write_rows = [r for r in rows if r["profile"] != "readonly"]
    print("\n=== summary ===")
    print(
        "tasks=%d  steps mean=%.2f median=%d max=%d"
        % (len(rows), statistics.mean(steps), statistics.median(steps), max(steps))
    )
    print("llm_calls mean=%.2f median=%d max=%d" % (statistics.mean(llm), statistics.median(llm), max(llm)))
    print(
        "write-tasks only: steps mean=%.2f  llm_calls mean=%.2f"
        % (statistics.mean(r["steps"] for r in write_rows), statistics.mean(r["llm_calls"] for r in write_rows))
    )

    dist = {}
    for r in rows:
        for role in r["sequence"]:
            dist[role] = dist.get(role, 0) + 1
    total = sum(dist.values())
    print("\n=== role selection distribution (Fig 7 축) ===")
    for role, n in sorted(dist.items(), key=lambda kv: -kv[1]):
        print("  %-16s %4d  %5.1f%%" % (role, n, 100.0 * n / total))

    # 난이도 상관 — 논문의 "어려울수록 스텝을 더 쓴다"
    tiers = sorted({r["tier"] for r in rows})
    print("\n=== steps vs difficulty tier ===")
    for t in tiers:
        rs = [r for r in rows if r["tier"] == t]
        print(
            "  tier %d  n=%2d  steps=%.2f  llm=%.2f"
            % (t, len(rs), statistics.mean(r["steps"] for r in rs), statistics.mean(r["llm_calls"] for r in rs))
        )

    tag = os.environ.get("VERIFY_LEVEL") or "default"
    out = Path(__file__).parent / ("results-policy-%s.json" % tag)
    out.write_text(
        json.dumps(
            {"rows": rows, "role_distribution": dist, "reps": reps, "verify_level": tag}, indent=1, ensure_ascii=False
        )
    )
    print("\nwrote %s" % out)


if __name__ == "__main__":
    main()
