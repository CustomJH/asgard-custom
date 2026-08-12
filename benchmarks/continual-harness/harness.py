"""Continual Harness 대조 벤치 — prime-agent(arXiv 2605.09998) 의 자기개선 계약을 이 저장소에
옮기면서 무엇이 얼마나 달라지는지 재는 자.

**왜 따로 서는가.** 이 저장소의 자기개선 층은 시험이 두껍지만(`tests/test_evolution.py`)
시험이 재는 것은 "규칙대로 도는가"다. 여기서 묻는 것은 다른 것이다 — **같은 입력에서 배우는
양과 진단의 정확도가 패치 전후로 얼마나 달라지는가.** 그 값은 단위 시험이 못 낸다: 축 하나는
이 저장소에 실제로 쌓인 퀘스트 로그 전수를 입력으로 써야 하고, 축 하나는 같은 사건을 두 규칙에
동시에 통과시켜 비교해야 한다.

**패치 전 규칙은 여기 다시 적는다.** 제품 코드는 안 건드린다 — 각 축의 `_before_*` 함수가
패치 전 판정을 그대로 옮긴 것이고, `_after_*` 는 제품 코드를 그대로 부른다. 두 값이 같으면
그 축은 패치가 아무것도 안 바꾼 것이고, 그것도 결과다.

축 넷:

  1. 채굴 수율 — `.asgard/quest/*.jsonl` 전수에서 학습 후보가 몇 건 나오는가.
     실패 증거를 판정(FAIL/ESCALATE)만 세다가 failure-tracker 의 `event="fail"` 까지 세면
     몇 건이 새로 잡히는가.
  2. 되풀이 판정 진단 — 워커가 트리를 안 고치고 재판정을 요청할 때, 하네스가 워커에게
     원인을 말해 주는가.
  3. 동시 세션 판단 보존 — 사람이 내린 승인·거절이 다른 세션의 자동 채굴 쓰기에 몇 건 지워지는가.
  4. 보관 뒤 재채굴 — 승인이 보관으로 물린 신호를 다시 캘 수 있는가.

실행: .venv/bin/python benchmarks/continual-harness/harness.py [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from asgard import evolution as evo  # noqa: E402
from asgard.hooks.asgard_hooklib import transition as trans  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# ── 축 1 · 채굴 수율 ──────────────────────────────────────────────────────────
def _before_quest_signal(events: list[dict]) -> bool:
    """패치 전 `_quest_signal` 의 실패 판정 — 판정이 낸 FAIL·ESCALATE 만 실패로 셌다.

    `failure-tracker` 가 같은 도구·같은 오류 3회에 적는 `event="fail"` 은 verdict 가 NA 라
    이 목록에 안 들어왔다. 그래서 "워커가 세 번 막히고 스스로 고친 뒤 첫 판정에 통과한"
    퀘스트는 후보를 한 건도 안 냈다."""
    if not events:
        return False
    verdicts = [e for e in events if e.get("verdict") in ("PASS", "FAIL", "ESCALATE")]
    if not verdicts or verdicts[-1]["verdict"] != "PASS":
        return False
    fails = [e for e in verdicts if e["verdict"] in ("FAIL", "ESCALATE")]
    if not fails:
        return False
    sig = next((str(e.get("failure_sig") or "") for e in reversed(fails) if e.get("failure_sig")), "")
    return not (sig and evo._FORBIDDEN_SIG.search(sig))


def axis_mining_yield() -> dict:
    qdir = os.path.join(ROOT, ".asgard", "quest")
    files = sorted(f for f in os.listdir(qdir) if f.endswith(".jsonl")) if os.path.isdir(qdir) else []
    before = after = with_tool_fail = 0
    gained: list[dict] = []
    for name in files:
        events = evo._read_quest(os.path.join(qdir, name))
        if any(e.get("event") == "fail" for e in events):
            with_tool_fail += 1
        old = _before_quest_signal(events)
        new = evo._quest_signal(events)
        before += bool(old)
        after += bool(new)
        if new and not old:
            gained.append({"log": name, "signal": new["signal"], "fail_count": new["fail_count"]})
    return {
        "quest_logs": len(files),
        "logs_with_tool_failures": with_tool_fail,
        "candidates_before": before,
        "candidates_after": after,
        "gained": gained,
    }


# ── 축 2 · 되풀이 판정 진단 ───────────────────────────────────────────────────
def _state(diff_hash: str, fail_hash: str) -> dict:
    """FAIL 하나 뒤에 work 하나가 붙은 퀘스트의 요약 — 두 해시만 바꿔 가며 쓴다."""
    return {
        "last_verdict": None,  # work 가 뒤따라 판정이 낡았다 (summary.work_after_verify)
        "last_event": "work",
        "failure_count": 1,
        "fail_streak_any": 1,
        "diff_hash": diff_hash,
        "unchanged_since_fail": diff_hash == fail_hash,
        "turns": 4,
        "risk_write": True,
        "plan_turns": 1,
        "changed_files": ["app.py"],
        "diff_lines": 4,
        "sensitive_files": [],
        "deleted_tests": [],
        "nontest_files": 1,
        "nontest_lines": 4,
        "full_verify_risk": False,
        "full_required": False,
        "checks_available": False,
        "criteria": ["무언가를 고친다"],
        "sig_risk": False,
        "tickets": {},
    }


class _Flags:
    write_expected = True
    ambiguous = shared = destructive = external_research = parallel_requested = structural = False
    unattended = False
    task_class = ""


def axis_retry_diagnosis() -> dict:
    """워커가 트리를 안 고치고 재판정을 요청할 때 사유가 원인을 말하는가.

    같은 요약을 두 번 통과시킨다: 트리가 움직인 경우와 안 움직인 경우. 패치 전에는 두 사유가
    글자까지 같았다 — 그것이 이 축이 재는 값이다."""
    policy = {
        "failure_threshold": 3,
        "sensitive_paths": [],
        "small_write": {"max_files": 2, "max_lines": 80},
        "verify_level": "low",
    }
    moved = trans.transition(_state("aaa", "bbb"), policy, _Flags(), None)
    frozen = trans.transition(_state("bbb", "bbb"), policy, _Flags(), None)
    return {
        "why_when_tree_moved": moved["why"],
        "why_when_tree_frozen": frozen["why"],
        "role_unchanged": moved["next_role"] == frozen["next_role"],
        "names_the_cause_before": False,  # 패치 전에는 두 사유가 같은 문자열이었다
        "names_the_cause_after": moved["why"] != frozen["why"],
    }


# ── 축 3 · 동시 세션 판단 보존 ────────────────────────────────────────────────
def _before_save_seen(root: str, seen: dict) -> None:
    """패치 전 `_save_seen` — 들고 있던 사본으로 파일을 통째로 덮었다."""
    from asgard import io_files

    io_files.write_json(evo._evo_dir(root, evo.SEEN_FILE), seen)


def _interleave(root: str, save) -> int:
    """사람의 판단 하나와 자동 채굴 하나가 겹쳐 쓸 때 남는 판단 수.

    각본: 두 손이 같은 시각에 `_load_seen` 을 하고(둘 다 빈 파일을 본다), 사람이 먼저 거절을
    쓰고, 자동 채굴이 나중에 자기 후보를 쓴다. Stop 훅의 `autoscan` 과 사람이 치는
    `evolve reject` 가 실제로 이 순서로 겹친다."""
    save(root, {})
    human = evo._load_seen(root)
    miner = evo._load_seen(root)
    human["sig-human"] = {"status": "rejected", "id": "evo-h", "reason": "일반화가 틀렸다"}
    miner["sig-miner"] = {"status": evo.PROPOSED, "id": "evo-m"}
    save(root, human)
    save(root, miner)
    final = evo._load_seen(root)
    return sum(1 for row in final.values() if str((row or {}).get("status")) in evo._DECIDED)


def axis_decision_survival() -> dict:
    with tempfile.TemporaryDirectory() as before_root, tempfile.TemporaryDirectory() as after_root:
        return {
            "decisions_kept_before": _interleave(before_root, _before_save_seen),
            "decisions_kept_after": _interleave(after_root, evo._save_seen),
            "decisions_written": 1,
        }


# ── 축 4 · 보관 뒤 재채굴 ─────────────────────────────────────────────────────
def axis_remine_after_archive() -> dict:
    """승인이 보관으로 물린 신호를 다시 캘 수 있는가.

    패치 전 latch 판정은 키 존재였다 (`signal in seen`) — 보관해도 키가 남아 영영 닫혔다.

    다시 캐는 것과 다시 **설치**하는 것은 갈라야 한다. 재채굴만 열면 매 턴 끝 `nudge_line` 이
    `autoscan` 다음에 부르는 `autoapprove` 가 기본 등급 safe 에서 같은 카드를 되설치해
    `evolve archive` 가 다음 턴에 스스로 취소된다 (판정자 둘이 각자 낸 반례).

    재설치 축은 손으로 만든 메타를 `autoapprove` 에 먹이지 않고 **실제 `nudge_line` 을 두 번
    돌린다** — 관문이 `mine` 경로 밖에 있으면 가짜 메타로는 안 보이기 때문이다. 초기화 한 번을
    사이에 끼우는 이유도 같다: 보관 사실이 `reset` 이 지우는 행에만 있으면 그 자리에서 샌다."""
    seen = {"sig-x": {"status": "approved", "id": "evo-x", "name": "learned-x"}}
    archived = {"sig-x": {**seen["sig-x"], "status": evo.ARCHIVED}}
    with tempfile.TemporaryDirectory() as tmp:
        root = _seed_hard_won_quest(tmp)
        evo.nudge_line(root)  # 첫 턴 — 등급 safe 가 스스로 설치한다
        name = _installed(root)[0]
        evo.archive_skill(root, name)
        evo.nudge_line(root)
        after_tick = _installed(root)
        evo.reset(root)
        evo.nudge_line(root)
        after_reset = _installed(root)
    return {
        "mineable_while_approved_before": "sig-x" not in seen,
        "mineable_while_approved_after": evo._mineable(seen, "sig-x"),
        "mineable_after_archive_before": "sig-x" not in archived,
        "mineable_after_archive_after": evo._mineable(archived, "sig-x"),
        "reinstalled_by_next_tick": bool(after_tick),
        "reinstalled_after_reset": bool(after_reset),
    }


def _installed(root: str) -> list[str]:
    d = os.path.join(root, ".asgard", "skills")
    return sorted(n for n in (os.listdir(d) if os.path.isdir(d) else []) if not n.startswith("."))


def _seed_hard_won_quest(tmp: str) -> str:
    """FAIL → PASS 퀘스트 로그 하나를 깐 임시 저장소 뿌리 — HOME 도 임시로 옮긴다."""
    root = os.path.join(tmp, "proj")
    home = os.path.join(tmp, "home")
    os.makedirs(os.path.join(root, ".asgard", "quest"))
    os.makedirs(home)
    os.environ["HOME"] = home
    os.environ["USERPROFILE"] = home
    qid = "q-hard"

    def line(**kv):
        base = {
            "schema": 1,
            "quest_id": qid,
            "turn": 1,
            "ts": "2026-08-12T00:00:00Z",
            "role": "verifier",
            "event": "verify",
            "risk": {"has_write": True, "task_class": "deep"},
            "criteria": [],
            "changed_files": [],
            "commands": [],
            "verdict": "NA",
            "failure_sig": None,
        }
        return json.dumps({**base, **kv}, ensure_ascii=False)

    rows = [
        line(role="thinker", event="plan"),
        line(verdict="FAIL", failure_sig="verifier-gate-record-missing"),
        line(
            verdict="PASS",
            criteria=["게이트가 판정 레코드를 요구"],
            commands=[{"cmd": "pytest tests/test_gate.py", "exit_code": 0}],
            changed_files=["src/asgard/hooks/verifier_gate.py"],
        ),
    ]
    with open(os.path.join(root, ".asgard", "quest", f"{qid}.jsonl"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(rows) + "\n")
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="측정값만 JSON 으로")
    args = parser.parse_args()
    report = {
        "mining_yield": axis_mining_yield(),
        "retry_diagnosis": axis_retry_diagnosis(),
        "decision_survival": axis_decision_survival(),
        "remine_after_archive": axis_remine_after_archive(),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    my = report["mining_yield"]
    print("축 1 · 채굴 수율 (이 저장소의 실제 퀘스트 로그)")
    print(f"  로그 {my['quest_logs']}건 중 도구 실패 이벤트를 든 것 {my['logs_with_tool_failures']}건")
    print(f"  학습 후보: 패치 전 {my['candidates_before']}건 → 패치 후 {my['candidates_after']}건")
    for row in my["gained"]:
        print(f"    + {row['log']} — signal={row['signal']!r} fail_count={row['fail_count']}")
    if my["logs_with_tool_failures"] == 0:
        print(
            "  주의 — 이 축의 0 은 소비자가 아니라 생산자 쪽 값이다. `failure-tracker` 가\n"
            '  `event="fail"` 을 한 건도 안 적어 읽을 것 자체가 없다. 그쪽 계수기는\n'
            "  `.asgard/state/gate-firing.json` 의 `failure-tracker` 행과\n"
            "  `.asgard/state/failures-*.json` 이고, 여기 옮겨 적으면 곧 낡는다.\n"
            "  채굴 규칙은 열렸고, 그 위층이 먹이를 안 준다."
        )

    rd = report["retry_diagnosis"]
    print("\n축 2 · 되풀이 판정 진단")
    print(f"  역할은 그대로인가: {rd['role_unchanged']}")
    print(f"  트리가 움직였을 때 : {rd['why_when_tree_moved']}")
    print(f"  트리가 멈췄을 때   : {rd['why_when_tree_frozen'][:120]}…")
    print(f"  원인을 말하는가: 패치 전 {rd['names_the_cause_before']} → 패치 후 {rd['names_the_cause_after']}")

    ds = report["decision_survival"]
    print("\n축 3 · 동시 세션 판단 보존 (사람 판단 1건이 겹쳐 쓰기를 만났을 때)")
    print(f"  살아남은 판단: 패치 전 {ds['decisions_kept_before']}/1 → 패치 후 {ds['decisions_kept_after']}/1")

    ra = report["remine_after_archive"]
    print("\n축 4 · 보관 뒤 재채굴")
    print(
        f"  승인 중 재채굴: 패치 전 {ra['mineable_while_approved_before']} → 패치 후 {ra['mineable_while_approved_after']}"
    )
    print(
        f"  보관 뒤 재채굴: 패치 전 {ra['mineable_after_archive_before']} → 패치 후 {ra['mineable_after_archive_after']}"
    )
    print(f"  다음 턴이 되설치하는가: {ra['reinstalled_by_next_tick']}")
    print(f"  초기화 뒤 턴이 되설치하는가: {ra['reinstalled_after_reset']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
