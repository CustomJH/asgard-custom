"""로그 상태 관측 — 전이 함수가 읽는 요약 하나.

`summarize` 가 이 패키지에서 유일하게 거의 모든 아래 모듈을 부르는 자리다. 그게 설계다:
관측을 한 함수로 모아 두면 전이 판정이 파일을 다시 읽지 않고 같은 관측 위에서 돈다.
정리(prune)와 라우팅 prior 도 여기 있다 — 둘 다 로그를 통째로 훑는 관측이다.
"""

from __future__ import annotations

import contextlib
import json
import os

from .contracts import quest_events_scope, unmet_contracts
from .evidence import evidence_breadth, evidence_items, pass_evidence
from .integrity import EMPTY, verification_identity
from .ledger import TICKET_STATUSES, fold_tickets, load_events, replay_ledger, verifiable_units
from .paths import fsync_dir, is_testfile, mtime
from .policy import full_verify_required, sensitive_path, verify_strength
from .runners import gate_first_checks_available, rejected_checks
from .session import pointer_qid
from .tree import current_tree_ref, deleted_tests, diff_state, peer_base_of, signature_risk, stale_pass_scope


def load_priors(root: str) -> dict:
    for rel in (os.path.join("state", "route-priors.json"), "route-priors.json"):  # 신규 state/ 우선
        try:
            with open(os.path.join(root, ".asgard", rel), encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            continue
    return {}  # 없음/깨짐 = 이력 없음 (fail-open — 기본 문턱)


def update_priors(root: str, task_class: str, red: bool) -> None:
    """퀘스트 종결 1건 반영. fail-open — 카운트 유실은 문턱이 기본값으로 남을 뿐."""
    try:
        p = load_priors(root)
        c = p.setdefault("classes", {}).setdefault(task_class, {"n": 0, "red": 0})
        c["n"] = int(c.get("n") or 0) + 1
        c["red"] = int(c.get("red") or 0) + (1 if red else 0)
        p["schema"] = 1
        d = os.path.join(root, ".asgard", "state")
        os.makedirs(d, exist_ok=True)
        f = os.path.join(d, "route-priors.json")
        try:  # 레거시 위치 잔재 제거 (이원화 방지 — 다음 로드가 신규만 보게)
            os.remove(os.path.join(root, ".asgard", "route-priors.json"))
        except FileNotFoundError:
            pass
        tmp = "%s.%d.tmp" % (f, os.getpid())  # temp+rename — 크래시 절단이 이력을 리셋하지 않게
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(p, handle)
        os.replace(tmp, f)
    except Exception:
        pass


def _unmined_learning_signal(root: str, qid: str) -> bool:
    """미채굴 hard-won 신호 보유 여부 — 자가발전 소급 채굴(evolution.mine)이 잃을 게 있는가.

    evolution 부재(standalone scaffold)는 채굴 파이프라인 자체가 없으므로 잃을 것도 없다 — False."""
    try:
        from asgard.evolution import unmined_signals

        return unmined_signals(root, qid) > 0
    except Exception:
        return False


def prune_quests(root: str, policy: dict) -> list[str]:
    """닫힌 퀘스트 로그 keep-last-N 정리 — 세션 상한 정책의 물리 집행 (close 시점 자동).

    Tier0 기억은 retain 시점에 자기완결 복사본으로 증류된다(quest log ≠ memory) — 오래
    닫힌 원본 로그 삭제는 기존 기억을 깨지 않는다. 보존 3종:
      - 포인터(ACTIVE/LAST/sessions/*.active·*.last)가 가리키는 퀘스트 — Stop 훅 완료
        판정(memory-activate)과 게이트가 재독하는 대상
      - 미종결 로그(quest_closed 없음) — 크래시 흔적, 증거가 아직 살아있다
      - 미채굴 학습 신호 보유 퀘스트 — 소급 채굴이 잃는 후보 방지
    세션 포인터도 같은 상한으로 GC 한다 — 닫힌 세션의 .last가 퀘스트를 영구 보호하면
    보호 집합이 세션 수만큼 무한 성장한다. 실패는 close를 막지 않는다 (fail-open)."""
    keep = int(policy.get("quest_retention") or 0)
    qdir = os.path.join(root, ".asgard", "quest")
    if keep <= 0 or not os.path.isdir(qdir):
        return []
    sessions = os.path.join(qdir, "sessions")
    by_session: dict[str, list[str]] = {}
    try:
        for name in os.listdir(sessions):
            key, dot, kind = name.rpartition(".")
            if dot and kind in ("active", "known", "last"):
                by_session.setdefault(key, []).append(os.path.join(sessions, name))
    except OSError:
        pass
    closed_sessions = [paths for paths in by_session.values() if not any(p.endswith(".active") for p in paths)]
    closed_sessions.sort(key=lambda paths: max(mtime(p) for p in paths), reverse=True)
    for paths in closed_sessions[keep:]:
        for p in paths:
            with contextlib.suppress(OSError):
                os.remove(p)
    protected = {pointer_qid(os.path.join(qdir, "ACTIVE")), pointer_qid(os.path.join(qdir, "LAST"))}
    try:
        for name in os.listdir(sessions):
            if name.endswith((".active", ".last")):
                protected.add(pointer_qid(os.path.join(sessions, name)))
    except OSError:
        pass
    protected.discard("")
    logs = sorted(
        (
            (mtime(os.path.join(qdir, name)), name[: -len(".jsonl")])
            for name in os.listdir(qdir)
            if name.endswith(".jsonl")
        ),
        reverse=True,
    )
    pruned = []
    for _, qid in logs[keep:]:
        if qid in protected:
            continue
        events = load_events(root, qid)
        if not events or events[-1].get("event") != "quest_closed":
            continue
        if _unmined_learning_signal(root, qid):
            continue
        for suffix in (".jsonl", ".lock"):
            with contextlib.suppress(OSError):
                os.remove(os.path.join(qdir, qid + suffix))
        pruned.append(qid)
    if pruned:
        fsync_dir(qdir)
    return pruned


def summarize(root: str, qid: str, events: list[dict], policy: dict) -> dict:
    """코디네이터 관찰용 요약 — next의 입력이기도 하다."""
    base_ref = next((e.get("base_ref") for e in events if e.get("base_ref")), None)
    ignored_base = next(
        (e.get("ignored_snapshot") for e in events if isinstance(e.get("ignored_snapshot"), dict)), None
    )
    # 한 요약이 트리를 **한 번만** 짓는다. 아래 셋(diff_state·deleted_tests·signature_risk)이
    # 저마다 지으면 같은 워킹트리를 세 번 짓게 되는데, 26-08-06 실측으로 그것이 `state` 한 번의
    # 301ms 중 224ms 였다. 값만의 문제도 아니다 — 셋 사이에 파일이 바뀌면 한 요약이 서로 다른
    # 트리를 근거로 쓴다. 여기서 한 번 지어 나눠 주면 그 창이 닫힌다.
    current_ref = current_tree_ref(root) if base_ref and base_ref != "NONE" else None
    cur, changed, lines, nt_lines = diff_state(
        root,
        base_ref,
        ignored_base,
        quest_events_scope(events),
        current_ref=current_ref,
        peer_base=peer_base_of(events),
    )
    verifies = [e for e in events if e.get("event") == "verify"]
    passes = [e for e in verifies if e.get("verdict") == "PASS"]
    last_pass = passes[-1] if passes else None
    # verdict 신선도 — 마지막 verify "이후" work가 있으면 판정은 낡았다(재검증 대기).
    # sticky FAIL이 WORKER_RETRY를 무한 재발화시키는 루프 방지 (재검증 없이 재시도 반복).
    last_verify_i = max((i for i, e in enumerate(events) if e.get("event") == "verify"), default=-1)
    work_after_verify = any(e.get("event") == "work" for e in events[last_verify_i + 1 :]) if verifies else False
    # 동종 실패 스트릭 — 같은 failure_sig의 연속 FAIL을 결정론 계산 (3-strike, Canon 9).
    # 네이티브 루프는 failure_count를 이벤트에 안 넣는다 — 퀘스트 로그에서 직접 센다.
    # 마지막 plan(재계획) "이후"의 FAIL만 센다 — 재계획이 3-strike의 응답이므로 스트릭 리셋.
    # 안 리셋하면 REPLAN → 여전히 count≥3 → REPLAN 무한 루프 (라이브 재현됨).
    last_plan_i = max((i for i, e in enumerate(events) if e.get("event") == "plan"), default=-1)
    fail_streak, fail_streak_any, sig = 0, 0, None
    for i in range(len(events) - 1, last_plan_i, -1):
        e = events[i]
        if e.get("event") != "verify":
            continue
        if e.get("verdict") != "FAIL":
            break
        fail_streak_any += 1  # sig 무관 연속 FAIL — 자유 텍스트 sig가 매번 달라도 도돌이표는 탈출해야 한다
        if sig is None:
            sig = e.get("failure_sig")
        if sig and e.get("failure_sig") == sig:
            fail_streak += 1
    sens = [f for f in changed if sensitive_path(f, policy["sensitive_paths"])]
    dts = deleted_tests(root, base_ref, current_ref=current_ref)
    # small_write 판정은 테스트 파일 제외 — 테스트 추가는 검증 표면이지 리스크 질량이 아니다
    # (스모크 실측: 잠금 테스트 2파일 추가 → big 오판 → full 강제·게이트-우선 무력화). 삭제는 dts가 잡는다.
    nt_files = [f for f in changed if not is_testfile(f)]
    small = policy["small_write"]
    full_risk = bool(sens) or bool(dts) or len(nt_files) > small["max_files"] or nt_lines > small["max_lines"]
    _esc_i = [i for i, e in enumerate(events) if e.get("event") == "verify" and e.get("verdict") == "ESCALATE"]
    _plan_i = [i for i, e in enumerate(events) if e.get("event") == "plan"]
    _research_i = [i for i, e in enumerate(events) if e.get("event") == "work" and e.get("research_only")]
    last_research = events[_research_i[-1]] if _research_i else {}
    tickets = fold_tickets(events)
    verifiable = verifiable_units(list(tickets.values()))
    ticket_counts = {
        status: sum(1 for ticket in tickets.values() if ticket["status"] == status) for status in TICKET_STATUSES
    }
    # stale 판정 — 해시 일치가 1차, 불일치면 퀘스트 귀속 범위 대조 (병렬 세션 드리프트 면책).
    pass_fresh = bool(last_pass and last_pass.get("diff_hash") == cur)
    drift_out: list[str] = []
    if last_pass and not pass_fresh:
        stale, drift_out = stale_pass_scope(root, last_pass, events, changed)
        pass_fresh = not stale
    replayed = replay_ledger(events)
    identity_required = bool(replayed.get("execution_id"))
    verification_valid = bool(
        last_pass
        and (
            not identity_required
            or (
                last_pass.get("verification_id")
                and last_pass.get("verification_id") == verification_identity(last_pass)
            )
        )
    )
    return {
        "quest_id": qid,
        "execution_id": replayed.get("execution_id"),
        "acceptance_hash": replayed.get("acceptance_hash"),
        "base_ref": base_ref,
        "turns": len(events),
        "last_event": events[-1].get("event") if events else None,
        "last_verdict": None if work_after_verify else (verifies[-1].get("verdict") if verifies else None),
        "failure_count": max([int(e.get("failure_count") or 0) for e in events] + [fail_streak]),
        "fail_streak_any": fail_streak_any,
        "criteria": next((e.get("criteria") for e in events if e.get("criteria")), []),
        "risk_write": any((e.get("risk") or {}).get("has_write") for e in events),
        "plan_turns": sum(1 for e in events if e.get("event") == "plan"),
        "research_completed": bool(_research_i),
        "research_pending_plan": bool(_research_i and (not _plan_i or _plan_i[-1] < _research_i[-1])),
        "research_findings": str(last_research.get("research_findings") or "")[:6000],
        "diff_hash": cur,
        "changed_files": changed,
        "diff_lines": lines,
        "sensitive_files": sens,
        "deleted_tests": dts,
        "nontest_files": len(nt_files),
        "nontest_lines": nt_lines,
        # gate의 full_required 판정과 동일 기준 — 전이(DONE)와 close가 gate와 어긋나면 안 된다.
        # 위험 축(risk)과 그 축에 설정 강도를 적용한 결과를 함께 넣는다: 전이는 risk에 flags.shared를
        # 더해 다시 계산하고, close·게이트는 결과만 본다.
        "full_verify_risk": full_risk,
        "full_required": full_verify_required(policy, full_risk),
        "verify_level_policy": verify_strength(policy),
        "pass_hash_match": pass_fresh,
        "verification_identity_match": verification_valid,
        "drift_out_of_scope": drift_out[:10],  # 범위 밖 드리프트 — 관측용 (판정 아님)
        "pass_level": (last_pass or {}).get("level"),
        # PASS의 성공 명령 증거 — 게이트와 동일 기준 (없으면 전이·close가 거부 — 깊이 테스트가 발견한 구멍)
        # 무변경(diff EMPTY) 퀘스트는 관측 명령이 곧 증거 (no-op 교착 봉합)
        "pass_evidence": bool(last_pass and pass_evidence(last_pass, no_change=cur == EMPTY)),
        # 증거의 폭 — 깊은 변경(full_verify_risk)이 증거 하나로 닫히지 않게 하는 하한의 입력
        "pass_evidence_breadth": evidence_breadth(last_pass) if last_pass else 0,
        # 증거의 출처 구성 — 판정 입력이자 관측 표면 (무엇으로 통과했는지가 로그에 남는다)
        "pass_evidence_kinds": evidence_items(last_pass) if last_pass else {},
        # 하네스 베이스라인 상태 — 기록 없음(구 로그·체크 미설정) = none = 요건 면제 (fail-open)
        "baseline_state": ((last_pass or {}).get("baseline") or {}).get("state") or "none",
        # criteria verify 계약 미충족 목록 — 계약 없는 기준은 빈 리스트 (하위호환, 요건 면제)
        "contracts_unmet": unmet_contracts(
            root, next((e.get("criteria") for e in events if e.get("criteria")), []), last_pass or {}
        ),
        # 무인 nudge 상태 (Canon 8) — 마커 파일 대신 로그 구조가 상한을 센다:
        #   replan_after_escalate = 마지막 ESCALATE 이후 plan 존재 (nudge/오딘 답변이 소비됨 → 실행 재개)
        #   escalate_nudged       = 어떤 ESCALATE 든 이후 plan이 존재 (퀘스트당 nudge 1회 소진)
        "replan_after_escalate": bool(_esc_i and _plan_i and _plan_i[-1] > _esc_i[-1]),
        "escalate_nudged": bool(_esc_i and _plan_i and _plan_i[-1] > _esc_i[0]),
        # 게이트-우선 라우팅 신호
        "checks_available": gate_first_checks_available(root, policy),
        # 적어 두었는데 실행되지 않는 체크 — 비어 있지 않으면 사용자가 켠 줄 아는 증거 레인이
        # 실제로는 꺼져 있다. 조용히 버리지 않고 상태에 넣어 doctor·판정 표면이 말하게 한다.
        "baseline_checks_rejected": rejected_checks(policy),
        "sig_risk": signature_risk(root, base_ref, current_ref=current_ref),
        "tickets": list(tickets.values()),
        "ticket_counts": {status: count for status, count in ticket_counts.items() if count},
        # Pipeline eligibility (no cross-unit barrier) — units safe to verify now, before the
        # whole batch is `done`. Final close/PASS keeps the full barrier (completion_decision).
        "verifiable_units": verifiable,
    }
