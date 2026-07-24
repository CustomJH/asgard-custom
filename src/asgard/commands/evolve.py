"""`asgard evolve` — 진화 인박스 (자가발전 C2, CUS-254).

scan(채굴) → list/show(검토) → approve/reject(처분) → archive(노화 보관).
승인만이 learned 스킬을 활성화하는 유일한 경로 — 자동 활성화는 없다 (CUS-251 헌법)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .. import evolution as evo
from .. import ui


def _root(start: str = ".") -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return str(Path(proc.stdout.strip()).resolve())
    except OSError, subprocess.TimeoutExpired:
        pass
    return str(Path(start).resolve())


def run_scan(quiet: bool = False) -> int:
    root = _root()
    created = evo.mine(root)
    if not created:
        left = evo.unmined_signals(root)
        print(
            f"신규 신호 없음 (미채굴 {left}건)" if left else "신규 신호 없음 — 퀘스트 로그에 hard-won 교훈이 아직 없다"
        )
        return 0
    for m in created:
        detail = (
            f"quest {m['quest_id']}, FAIL {m['fail_count']}회 → PASS"
            if m.get("quest_id")
            else "사용자 정정 신호"  # origin: correction — 제2 채굴원 (26-07-24)
        )
        ui.ok(f"후보 생성 {m['id']} — {m['name']} ({detail})")
    print(ui.dim("검토: asgard evolve list · 승인: asgard evolve approve <id>"))
    return 0


def run_nudge() -> int:
    """훅 소비 표면 — 미채굴 신호가 새로 생겼을 때만 한 줄 출력 (latch), 그 외 침묵.
    memory-activate Stop 훅이 subprocess 로 부른다 — 로직은 evolution.nudge_line 단일 출처."""
    line = evo.nudge_line(_root())
    if line:
        print(line)
    return 0


def run_list() -> int:
    root = _root()
    items = evo.pending_list(root)
    if not items:
        print("인박스 비어 있음 — asgard evolve scan 으로 퀘스트 로그를 채굴")
        return 0
    print(ui.bold(f"pending {len(items)}건") + ui.dim(" — 초안은 승인 전에 파일을 직접 다듬어도 된다"))
    for m in items:
        print(
            f"  {ui.bold(m['id'])}  {m.get('name', '?')}  "
            + ui.dim(f"quest {m.get('quest_id', '?')} · FAIL {m.get('fail_count', '?')}회 · {m.get('created', '')}")
        )
    print(ui.dim(f"파일: {os.path.join('.asgard', 'evolution', 'pending')}/<id>/SKILL.md"))
    return 0


def run_show(cid: str) -> int:
    text = evo.show(_root(), cid)
    if text is None:
        ui.fail(f"후보 없음: {cid}")
        return 1
    print(text)
    return 0


def run_approve(cid: str) -> int:
    ok, msg = evo.approve(_root(), cid)
    (ui.ok if ok else ui.fail)(msg)
    return 0 if ok else 1


def run_reject(cid: str, reason: str = "") -> int:
    ok, msg = evo.reject(_root(), cid, reason)
    (ui.ok if ok else ui.fail)(msg)
    return 0 if ok else 1


def run_polish(cid: str) -> int:
    ok, msg = evo.polish(_root(), cid)
    (ui.ok if ok else ui.fail)(msg)
    return 0 if ok else 1


def run_bench(skill: str, cmd: str, metric: str, runs: int, direction: str, timeout: int) -> int:
    from ..evolution_bench import run_ab

    root = _root()
    print(ui.dim(f"A/B: {skill} OFF({runs}회) vs ON({runs}회) — METRIC {metric} ({direction})"))
    r = run_ab(root, skill, cmd, metric, runs=runs, direction=direction, timeout=timeout)
    conf = f"{r['confidence']:.2f}×MAD" if r["confidence"] is not None else "판정 불가 (run<3 또는 MAD=0)"
    print(f"  baseline(OFF) median={r['baseline_median']}  variant(ON) median={r['variant_median']}  conf={conf}")
    mark = {"keep": ui.ok, "discard": ui.warn}.get(r["verdict"], ui.step)
    mark(f"verdict: {r['verdict']}" + (" — asgard evolve archive 로 보관 권장" if r["verdict"] == "discard" else ""))
    print(ui.dim("계보: .asgard/evolution/bench.jsonl (판정은 기록 — 처분은 사용자 몫)"))
    return 0 if r["verdict"] != "discard" else 1


def run_curate(apply: bool = False) -> int:
    """learned 스킬 노화 보고 (기본 드라이런) — --apply 시 90일 유휴 후보만 보관 전이."""
    from ..skill_curator import curate

    root = _root()
    result = curate(root, apply=apply)
    findings = result["findings"]
    if not findings:
        print("learned 스킬 없음 — 큐레이션 대상이 없다")
        return 0
    marks = {"active": ui.ok, "stale": ui.warn, "archive-candidate": ui.warn, "unreadable": ui.fail}
    for f in findings:
        mark = marks.get(f["state"], ui.step)
        detail = f.get("reason", "")
        mark(f"{f['name']} · {f['state']}" + (f" — {detail}" if detail else ""))
    candidates = [f["name"] for f in findings if f["state"] == "archive-candidate"]
    if result["archived"]:
        ui.ok(
            f"보관 전이 {len(result['archived'])}건: {', '.join(result['archived'])} (복원: asgard evolve restore <name>)"
        )
    elif candidates:
        ui.warn(f"보관 후보 {len(candidates)}건 — 검토 후 asgard evolve curate --apply")
    return 0


def run_archive(name: str) -> int:
    ok, msg = evo.archive_skill(_root(), name)
    (ui.ok if ok else ui.fail)(msg)
    return 0 if ok else 1


def run_restore(name: str) -> int:
    ok, msg = evo.restore_skill(_root(), name)
    (ui.ok if ok else ui.fail)(msg)
    return 0 if ok else 1
