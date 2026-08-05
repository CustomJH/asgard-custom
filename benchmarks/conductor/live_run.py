#!/usr/bin/env python3
"""Conductor(arXiv 2512.04388) 대조 실행 — 세션 1건을 격리 테스트 프로젝트에서 돌리고 채점한다.

논문 §4.3 의 대조 구성을 코딩 하네스로 옮긴 것이다:
  plain    단일 에이전트 (논문의 개별 worker LLM — 조율 없음)
  reflect  자기 반성 5턴 (논문의 self-reflection 베이스라인, Madaan et al.)
  asgard   Asgard Trinity 조율 (논문의 Conductor 자리)

채점은 논문 §3.1 의 두 단계 보상을 그대로 쓴다:
  r = 0    형식 조건 미달 — 조율 산출물을 워크플로로 읽을 수 없다
  r = 0.5  워크플로는 성립했으나 최종 답이 정답과 다르다
  r = 1.0  최종 답이 정답과 일치한다 (숨긴 pytest 전건 통과)

이 저장소는 개발 코드이므로 세션은 여기서 돌지 않는다 — 과업마다 pristine 저장소를
`runs/<id>/` 에 새로 깔고 그 안에서만 돈다.

usage: live_run.py <task> <plain|reflect|asgard> <rep>
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TASKS = ROOT / "workspace" / "bench-cus168" / "tasks"
RUNS = Path(os.environ.get("RUNS") or HERE / "runs")
RESULTS = Path(os.environ.get("RESULTS") or HERE / "results")
TIMEOUT = int(os.environ.get("SESSION_TIMEOUT", "2700"))
MAX_TURNS = os.environ.get("MAX_TURNS", "100")
MODEL = os.environ.get("BENCH_MODEL", "")

REFLECT_SUFFIX = (
    "\n\n작업을 마친 뒤에는 스스로 결과를 다시 읽고 잘못된 곳을 고쳐라. "
    "이 검토·수정 사이클을 최대 5회까지 반복하고, 이전 시도의 내용은 모두 유지한 채 "
    "마지막 회차의 결과를 최종 답으로 내라."
)


def sh(cwd, *args, check=True):
    return subprocess.run(list(args), cwd=str(cwd), capture_output=True, text=True, check=check)


def setup(task: str, arm: str, wd: Path) -> str:
    """격리 테스트 프로젝트 — pristine 사본 + (asgard 아암이면) 배포 스캐폴드."""
    if wd.exists():
        shutil.rmtree(wd)
    shutil.copytree(TASKS / task / "repo", wd)
    sh(wd, "git", "init", "-q")
    sh(wd, "git", "config", "user.email", "bench@conductor")
    sh(wd, "git", "config", "user.name", "bench")
    sh(wd, "git", "add", "-A")
    sh(wd, "git", "commit", "-qm", "init")
    if arm == "asgard":
        subprocess.run(
            ["uv", "run", "--project", str(ROOT), "asgard", "init", "--cc", "--yes", "--quiet"],
            cwd=str(wd),
            capture_output=True,
            text=True,
        )
        sh(wd, "git", "add", "-A")
        sh(wd, "git", "commit", "-qm", "scaffold", check=False)
    prompt = (TASKS / task / "prompt.txt").read_text()
    return prompt + (REFLECT_SUFFIX if arm == "reflect" else "")


def run_session(wd: Path, prompt: str) -> tuple[int, int]:
    env = {
        k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")
    }
    cmd = [
        "perl",
        "-e",
        "alarm shift; exec @ARGV",
        str(TIMEOUT),
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--dangerously-skip-permissions",
        "--max-turns",
        MAX_TURNS,
    ]
    if MODEL:
        cmd += ["--model", MODEL]
    t0 = time.time()
    with open(wd / "out.json", "w") as out, open(wd / "claude.err", "w") as err:
        rc = subprocess.run(cmd, cwd=str(wd), stdout=out, stderr=err, env=env).returncode
    return rc, int(time.time() - t0)


def grade(task: str, wd: Path) -> tuple[int, int, list[str]]:
    """숨긴 pytest 주입 후 채점 — (통과, 전체, 실패 케이스)."""
    gdir = wd / "_grade_conductor"
    if gdir.exists():
        shutil.rmtree(gdir)
    shutil.copytree(TASKS / task / "hidden", gdir)
    subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(ROOT),
            "--",
            "pytest",
            "_grade_conductor",
            "-q",
            "-p",
            "no:cacheprovider",
            "--junitxml=grade.xml",
            "--tb=no",
        ],
        cwd=str(wd),
        capture_output=True,
        text=True,
    )
    passed = total = 0
    failed = []
    try:
        for tc in ET.parse(wd / "grade.xml").getroot().iter("testcase"):
            if any(c.tag == "skipped" for c in tc):
                continue
            total += 1
            if any(c.tag in ("failure", "error") for c in tc):
                failed.append(tc.get("name", ""))
            else:
                passed += 1
    except Exception:
        pass
    return passed, total, failed


def transcript_path(wd: Path, session_id: str) -> Path | None:
    slug = "-" + re.sub(r"[^A-Za-z0-9]", "-", str(wd)).strip("-")
    p = Path.home() / ".claude" / "projects" / slug / (session_id + ".jsonl")
    return p if p.is_file() else None


def read_transcript(p: Path) -> dict:
    """조율 비용 — 서브에이전트 호출 수와 그 배정 분포 (논문 Fig 5·7 축)."""
    calls, tools = [], {}
    for line in p.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = (d.get("message") or {}).get("content")
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                tools[c["name"]] = tools.get(c["name"], 0) + 1
                if c["name"] in ("Agent", "Task"):
                    calls.append((c.get("input") or {}).get("subagent_type") or "?")
    return {"agent_calls": len(calls), "agents": calls, "tool_uses": sum(tools.values()), "tools": tools}


def read_quest(wd: Path) -> dict:
    """Asgard 아암의 워크플로 — 로그 이벤트가 곧 스텝이다."""
    qdir = wd / ".asgard" / "quest"
    events, verdicts, verify_cmds = [], [], 0
    for f in sorted(qdir.glob("*.jsonl")) if qdir.is_dir() else []:
        for line in f.read_text(errors="replace").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = e.get("event")
            if ev in ("plan", "work", "verify"):
                events.append(ev)
            if ev == "verify":
                verdicts.append(e.get("verdict"))
                # 검증 증거는 두 자리에 있다: 모델이 신고한 commands 와 하네스가 직접 다시 돌린
                # criteria_checks. 앞엣것만 세면 verify 계약을 쓴 세션이 증거 0 으로 보인다.
                verify_cmds += len(e.get("commands") or []) + len(e.get("criteria_checks") or [])
    return {
        "quest_events": events,
        "workflow_steps": len(events),
        "verdicts": verdicts,
        "verify_cmds": verify_cmds,
        "final_verdict": verdicts[-1] if verdicts else None,
    }


def conductor_reward(arm: str, ok_format: bool, correct: bool) -> float:
    """논문 §3.1 — 형식 조건이 먼저, 그 다음 정답 조건."""
    if not ok_format:
        return 0.0
    return 1.0 if correct else 0.5


def main():
    task, arm, rep = sys.argv[1], sys.argv[2], sys.argv[3]
    rid = "%s-%s-r%s" % (task, arm, rep)
    RESULTS.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    dest = RESULTS / (rid + ".json")
    if dest.exists():
        print("[skip] %s" % rid)
        return
    wd = RUNS / rid

    prompt = setup(task, arm, wd)
    rc, wall = run_session(wd, prompt)
    passed, total, failed = grade(task, wd)

    row = {
        "id": rid,
        "task": task,
        "arm": arm,
        "rep": int(rep),
        "rc": rc,
        "timeout": rc in (124, 142),
        "wall_s": wall,
        "cases_passed": passed,
        "cases_total": total,
        "failed_cases": failed,
    }
    try:
        d = json.loads((wd / "out.json").read_text())
        row.update(
            cost_usd=d.get("total_cost_usd"),
            turns=d.get("num_turns"),
            session_id=d.get("session_id"),
            is_error=d.get("is_error"),
            models=sorted((d.get("modelUsage") or {}).keys()),
        )
    except Exception as e:
        row["out_json_error"] = str(e)

    tp = transcript_path(wd, row.get("session_id") or "")
    row.update(read_transcript(tp) if tp else {"agent_calls": None, "transcript": "missing"})
    if arm == "asgard":
        row.update(read_quest(wd))

    correct = total > 0 and passed == total
    # 형식 조건: 세션이 산출물을 냈는가. asgard 아암은 조율 산출물(퀘스트 워크플로)까지 본다.
    ok_format = not row.get("timeout") and not row.get("is_error") and total > 0
    if arm == "asgard":
        ok_format = ok_format and row.get("workflow_steps", 0) > 0
    row["ok_format"] = bool(ok_format)
    row["correct"] = bool(correct)
    row["reward"] = conductor_reward(arm, ok_format, correct)

    dest.write_text(json.dumps(row, ensure_ascii=False, indent=1))
    print(
        "[done] %s reward=%.1f cases=%d/%d agent_calls=%s cost=%s wall=%ss"
        % (rid, row["reward"], passed, total, row.get("agent_calls"), row.get("cost_usd"), wall)
    )


if __name__ == "__main__":
    main()
