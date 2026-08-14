"""전이 함수 — 다음 역할을 코드가 정한다.

TRINITY 의 "작은 코디네이터"를 하네스에서 되풀이하는 자리다: 배정을 모델의 임의 판단이 아니라
결정 테이블이 내리게 해서 조율을 프롬프트가 아닌 구조로 옮긴다. 결정 테이블은 코드가 유일한
출처이고 임계값만 정책에서 온다.
"""

from __future__ import annotations

from .integrity import EMPTY
from .policy import full_verify_required, role_dispatch, verify_strength

# 깊은 변경의 증거 하한 — 하나로는 못 닫는다. 2 는 "계약 한 줄"과 "그 밖의 무엇"을 가르는
# 최소값이고, 작은 변경은 이 하한을 지지 않는다 (기본 low 의 속도 선택 유지).
MIN_DEEP_EVIDENCE = 2


# ── 완료 판정 단일 퍼널 — 승인 경로의 유일한 출처 ──
def completion_decision(s: dict) -> tuple[str, str, str]:
    """(decision, code, why). decision ∈ APPROVED/REJECTED/ESCALATED — transition(PASS 분기)과
    close가 모두 이 함수만 신뢰한다. 불변식: REJECTED는 어떤 호출측에서도 승인으로 승격 금지
    (close --force는 LAST 미기록·게이트 면제 없는 관리적 해제일 뿐, 승인이 아니다).
    verifier-gate.py의 Stop 차단 기준과 동일 유지 (단일 출처 원칙 — 어긋나면 DONE이 Stop에서 차단)."""
    if s.get("last_verdict") == "ESCALATE":
        return "ESCALATED", "escalate", "Verifier ESCALATE — awaiting Odin's decision (Canon 9 regular exit)"
    if s.get("last_verdict") != "PASS":
        return "REJECTED", "no-pass", "no verified PASS verdict"
    if not s.get("criteria"):
        # 게이트와 동일 검사 — close가 이걸 안 보면 무기준 PASS가 LAST 면제로 게이트를 우회한다
        return "REJECTED", "no-criteria", "no success criteria in the log — verification cannot stand without criteria"
    unfinished = [ticket for ticket in (s.get("tickets") or []) if ticket.get("status") != "done"]
    if unfinished:
        ids = ", ".join(str(ticket.get("id")) for ticket in unfinished[:6])
        return "REJECTED", "tickets-incomplete", "incomplete tickets remain: %s" % ids
    if s.get("baseline_state") == "red":
        return "REJECTED", "baseline-red", "harness baseline check is red — failing checks need repair"
    unmet = s.get("contracts_unmet") or []
    if unmet:
        # 계약이 선언된 기준은 그 명령·산출물이 유일한 증거다 — 무관한 exit-0 명령으로 대체 불가
        return "REJECTED", "criteria-unverified", "criteria verify contract unmet: %s" % "; ".join(map(str, unmet[:3]))
    if not s.get("pass_evidence"):
        return "REJECTED", "no-evidence", "PASS has no successful verification-command evidence"
    if s.get("full_verify_risk") and (s.get("pass_evidence_breadth") or 0) < MIN_DEEP_EVIDENCE:
        # 증거가 '있는가'만 물으면 계약 한 줄이 어떤 크기의 변경도 닫는다. 실패가 안 나면 재계획도
        # 안 돌므로, 안 깨진 깊은 변경은 얕은 채로 종결된다 (26-08-06 라이브: 5파일 리팩터가
        # 명령 1개로 PASS). 위험 축은 raw(full_verify_risk)를 쓴다 — verify_level 기본값 low 에서
        # full_required 가 항상 False 라, 설정 강도에 얹으면 이 하한도 같이 꺼진다.
        return (
            "REJECTED",
            "thin-evidence",
            "deep change (sensitive path / large diff / deleted tests) verified by %d evidence item(s) — "
            "needs %d independent ones" % (s.get("pass_evidence_breadth") or 0, MIN_DEEP_EVIDENCE),
        )
    if not s.get("pass_hash_match"):
        return "REJECTED", "stale-pass", "working tree changed after PASS (stale PASS) — re-verification required"
    if s.get("execution_id") and not s.get("verification_identity_match"):
        return (
            "REJECTED",
            "verification-identity",
            "PASS evidence is not bound to this execution, acceptance contract and physical diff",
        )
    if s.get("full_required") and s.get("pass_level") != "full":
        return "REJECTED", "micro-pass", "full-verify required (sensitive path/large diff) but got micro PASS"
    return "APPROVED", "ok", "verified PASS + diff-hash physical match"


def _transition_axes(s: dict, policy: dict, flags) -> dict:
    """전이 입력 축 — risk_features 11종(결정론 계산 7 + 모델 신고 4)과 그것으로 정해지는 등급.

    `standard_ok`는 게이트-우선(STANDARD) 적격이다. 플래그 없는 기본값이고 물리 가드가 전부
    판정한다 — v1은 `--standard` 옵트인이었으나 스모크 3회에서 모델이 플래그를 안 넘겼다
    (프롬프트 계약 한계). 조건 하나라도 깨지면 아래 트리니티 행으로 자연 폴스루 = 승격이다:
    민감 경로·큰 non-test diff·시그니처 변경·테스트 삭제·모호는 LLM Verifier가 필요하다.
    게이트-우선 전용 라인 상한이 따로 있는 이유는 sig_risk가 간접 값 흐름 변경을 못 보기
    때문이다 — 큰 리라이트(+52/-11)는 diff 질량으로 LLM Verifier에 올린다. 가시 테스트
    (baseline)는 near-oracle이 아니므로(2606.24453 regime) 소형 diff에서만 신뢰한다."""
    small = policy["small_write"]
    # big은 non-test 질량 기준 (summarize.full_required와 동일) — 테스트 추가로 full/승격을 트리거하지 않는다
    big = (
        s.get("nontest_files", len(s["changed_files"])) > small["max_files"]
        or s.get("nontest_lines", s["diff_lines"]) > small["max_lines"]
    )
    sensitive = bool(s["sensitive_files"]) or flags.shared
    has_write = s["diff_hash"] != EMPTY or s["risk_write"] or flags.write_expected
    gf_small = s.get("nontest_lines", s["diff_lines"]) <= int(policy.get("gate_first_max_lines") or 25)
    # level과 full_required는 한 식에서 갈라져 나온다. 둘을 따로 쓰면 조용히 어긋난다 — 실제로
    # 어긋나 있었다: level이 deleted_tests를 안 봐서 테스트를 지운 작은 diff가 micro를 배정받고,
    # Verifier가 micro로 PASS를 내면 completion_decision이 그 PASS를 micro-pass로 거부해
    # 같은 diff에 full Verifier 턴이 한 번 더 붙었다 (판정은 그대로, 대기시간만 두 배).
    # 위험 축은 요약이 계산한 raw(full_verify_risk)에 이 턴의 shared 신고를 더한 것이고, 설정
    # 강도가 그 축을 승격으로 바꿀지 정한다. 구 요약(축이 없는 로그)은 결과값으로 폴백한다.
    full_required = full_verify_required(policy, s.get("full_verify_risk", s["full_required"]) or flags.shared)
    return {
        "features": {
            "has_write": has_write,
            "sensitive_path": bool(s["sensitive_files"]),
            "shared_surface": flags.shared,
            "diff_files": len(s["changed_files"]),
            "diff_lines": s["diff_lines"],
            "tests_available": s.get("tests_available", False),
            "verification_possible": bool(s["criteria"]),
            "failure_count": s["failure_count"],
            "ambiguous_scope": flags.ambiguous,
            "destructive_intent": flags.destructive,
            "external_research": flags.external_research,
        },
        "has_write": has_write,
        "full_required": full_required,
        "level": "full" if full_required else "micro",
        "standard_ok": (
            # always 는 "역할이 도는 것을 매번 본다" 는 선언이다 — 게이트-우선이 살아 있으면 작은
            # 변경은 하네스가 조용히 닫아 판정자 턴이 아예 안 생긴다.
            role_dispatch(policy) != "always"
            and verify_strength(policy) != "full"  # 항상 full 설정이면 게이트-우선 micro PASS는 어차피 되돌려진다
            and not sensitive
            and not big
            and gf_small
            and not s.get("deleted_tests")
            and not s.get("sig_risk")
            and not flags.ambiguous
            and not flags.external_research
        ),
    }


def _blocked_step(s: dict, policy: dict, flags) -> tuple[str, str] | None:
    """① 진행이 막혔는가 — 파괴적 의도·반복 실패·ESCALATE. 여기서 답이 나오면 판정은 안 본다."""
    if flags.destructive:
        return "ESCALATE_ODIN", "destructive_intent — Canon 3, requires Odin's explicit consent"
    if s["failure_count"] >= policy["failure_threshold"]:
        return "THINKER_REPLAN", "%d same-signature failures — Worker retry forbidden (Canon 9)" % s["failure_count"]
    if s.get("fail_streak_any", 0) > policy["failure_threshold"]:
        # 이종-sig 백스톱 — 자유 텍스트 sig가 매번 달라 동종 판정이 안 잡혀도, 재계획 없이
        # FAIL이 threshold+1 연속이면 접근 자체가 틀렸다고 본다 (턴 예산 소진 전 탈출).
        return (
            "THINKER_REPLAN",
            "%d consecutive failures (including mixed signatures) — redesign the approach" % s["fail_streak_any"],
        )
    if s["last_verdict"] != "ESCALATE" or s.get("replan_after_escalate"):
        # ESCALATE 이후 재계획(plan)이 남았으면 이 갈래를 건너뛴다 — 재계획이 에스컬레이션을 소비하고
        # 아래 WORKER 폴스루로 실행이 이어진다 (오딘 답변 후 재개 경로와 무인 nudge 경로 공통).
        return None
    if getattr(flags, "unattended", False) and not s.get("escalate_nudged"):
        # 무인 세션 1회 nudge (Canon 8) — 오딘의 답은 오지 않는다. 방어 가능한 기본안으로 재계획을
        # 강제하고, nudge 소진 후의 재-ESCALATE는 진짜 블로커로 인정 (verifier_gate의 마커 파일과
        # 같은 의미론 — 여기선 로그 구조(ESCALATE↔plan 순서)가 상한을 센다).
        return (
            "THINKER_REPLAN",
            "Unattended-session ESCALATE (Canon 8) — pick a defensible default, record it as a "
            "`가정:` criteria entry, and proceed. If no default is defensible (a genuine blocker), "
            "record the reason and re-ESCALATE",
        )
    # Verifier ESCALATE = 진행 불가 블로커 신고 (Canon 8: 승인 요청 용도 아님) — WORKER 폴스루로
    # 예산을 태우지 않고 즉시 Odin 에스컬레이션. 게이트/close의 ESCALATE 수용과 대칭.
    return "ESCALATE_ODIN", "Verifier ESCALATE — blocking issue, Odin's decision required"


def _fail_step(s: dict, flags, priors: dict | None, axes: dict) -> tuple[str, str]:
    """FAIL 뒤의 갈래 — 게이트-우선 red 누적은 threshold 전에 트리니티로 올린다.

    승격 문턱은 Bayesian-lite다: 이 task-class의 게이트-red 이력이 과반이면 red 1회로 선제
    승격한다. Beta(1,1) posterior mean (red+1)/(n+2) > 0.5 ⟺ red > n−red (과반 판정) —
    카운트뿐이고 학습은 없다 (arXiv 2606.24453: 검증이 싸고 critic이 불완전한 구간의 적응 제어)."""
    pc = ((priors or {}).get("classes") or {}).get(getattr(flags, "task_class", None) or "", {})
    red_hist = int(pc.get("red") or 0)
    promote_at = 1 if red_hist > int(pc.get("n") or 0) - red_hist else 2
    if axes["standard_ok"] and s.get("fail_streak_any", 0) >= promote_at:
        # 게이트-우선에서 red 2회 = 싼 게이트로 못 넘는 벽 — threshold(3) 전에 선제 승격.
        # prior 과반-red 클래스는 red 1회로 하향.
        why = "gate-first red %d times — promoting to Trinity, redesign the approach" % s["fail_streak_any"]
        return "THINKER_REPLAN", why + (" (prior: task-class red history is majority)" if promote_at == 1 else "")
    if flags.structural:
        return "THINKER_REPLAN", "Verifier FAIL (structural) — redesign the approach"
    return "WORKER_RETRY", "Verifier FAIL (minor) — fix under the same plan"


def _verdict_step(s: dict, flags, priors: dict | None, axes: dict) -> tuple[str, str] | None:
    """② 마지막 판정에 무엇으로 답하는가 — PASS의 완료 판정은 completion_decision 하나만 믿는다.

    close·게이트와 판정이 갈리면 안 되므로 이 함수는 자기 기준을 따로 갖지 않는다. 퍼널이 낸
    거부 코드마다 누구를 부를지만 정한다. flags.shared는 전이 시점 모델 신고라 요약에 없어서
    퍼널 입력에 병합한다."""
    if s["last_verdict"] == "FAIL":
        return _fail_step(s, flags, priors, axes)
    if s["last_verdict"] != "PASS":
        return None
    decision, code, why = completion_decision({**s, "full_required": axes["full_required"]})
    if decision == "APPROVED":
        return "DONE", why
    if code == "baseline-red":
        # 하네스가 직접 돌린 프로젝트 체크가 실패 — 판정이 아니라 코드가 깨져 있다
        return "WORKER_RETRY", "harness baseline check is red — repair the failing check first (Canon 10)"
    if code == "thin-evidence":
        # 판정이 아니라 검증 폭이 모자라다 — 같은 diff 를 다른 표면에서 한 번 더 짚게 한다
        return (
            "VERIFIER",
            why + " — run a second, independent check (project baseline or a different surface) and re-judge",
        )
    if code == "no-evidence":
        # 증거 없는 PASS는 판정이 아니다 — 게이트가 어차피 차단하므로 전이가 먼저 재검증을 보낸다
        # (판정 불일치 금지). close 우회 구멍의 전이측 봉합 (깊이 테스트 발견).
        return (
            "VERIFIER",
            "PASS has no successful verification-command evidence — run the command directly and re-judge (Canon 10)",
        )
    if code == "no-criteria":
        return "VERIFIER", "no success criteria in the log — record criteria then re-judge (Canon 10)"
    if code == "tickets-incomplete":
        return "WORKER_RETRY", why + " — reassign only the unfinished units"
    if code == "criteria-unverified":
        # 계약 명령이 실패했거나 산출물이 없다 — 재검증 append가 하네스 재실행을 트리거한다
        return "VERIFIER", why + " — repair/re-run the contract command and re-judge (Canon 10)"
    if code == "stale-pass":
        return "VERIFIER", "working tree changed after PASS (stale PASS) — re-verification required"
    if code == "verification-identity":
        return "VERIFIER", "PASS identity is not bound to this execution and diff — re-verification required"
    # micro-pass — gate와 동일 판정: micro PASS로 DONE을 내면 Stop에서 차단당한다 (판정 불일치 금지)
    return "VERIFIER", "PASS is micro — sensitive path/large diff requires full-verify"


def _next_step(s: dict, flags, axes: dict) -> tuple[str, str]:
    """③ 다음 걸음 — 막히지도 않았고 답할 판정도 없을 때. 마지막 줄이 기본값이라 항상 답이 난다."""
    if flags.external_research and axes["has_write"] and not s.get("research_completed"):
        return "WORKER", "external research first — an isolated Research Worker gathers evidence; implementation waits"
    if flags.external_research and s.get("research_pending_plan"):
        return "THINKER", "external research complete — review the gathered evidence and replan units and criteria"
    if flags.parallel_requested and s["plan_turns"] < 2:
        # 병렬 fan-out만 별도 Thinker가 access/file-overlap 그래프를 만든다. 모호함·외부 조사·큰
        # 변경은 단일 Worker가 같은 도구 문맥에서 계획하고 실행한다 — 순차 역할 handoff 비용과
        # 맥락 손실을 피하고, 실제 FAIL/구조적 red가 관측될 때만 THINKER_REPLAN으로 승격한다.
        return "THINKER", "explicit parallel task — plan independent units and the access graph first"
    if not axes["has_write"]:
        return "DIRECT_DONE", "no write — gate-exempt path"
    if s["last_event"] != "work":
        return "WORKER", "single Worker autonomous plan/execute — Thinker replans on failure"
    if s["diff_hash"] == EMPTY:
        if flags.write_expected:
            return (
                "VERIFIER",
                "write expected but no change observed — independently verify that the requested outcome already holds",
            )
        # 무변경 관측 — Worker가 돌았는데 물리 diff 0 (risk_write는 분류 시점 기대치라
        # 판정 축이 아니다 — 물리 관측이 정본). '변경 없음' 주장의 올바른 검증은 트리 관측
        # 그 자체다 (pass_evidence의 no_change=inspection 원칙) — LLM Verifier를 소환해
        # 반증 불가능한 기준을 재량 검증시키지 않고, 하네스가 관측을 기록해 판정한다
        # (0-LLM). 오분류로 Trinity에 들어온 무변경 요청의 결정론 출구 (26-07-21 "안녕"
        # 계열 — 잔여 낭비 경로 봉합). 명시적으로 쓰기를 기대한 요청은 위에서 Verifier로 보내
        # 이미 충족된 요청과 Worker가 변경을 누락한 경우를 tree observation 하나로 합치지 않는다.
        return "BASELINE_VERIFY", "no-change observed — harness tree-observation verdict (0-LLM)"
    if axes["standard_ok"] and s.get("checks_available"):
        return "BASELINE_VERIFY", "small, non-sensitive change — harness baseline takes priority"
    return "VERIFIER", "Worker complete — %s-verify verdict is next" % axes["level"]


UNCHANGED_SINCE_FAIL = (
    "the working tree is byte-identical to the tree that just failed, so nothing a verdict can "
    "observe has moved. Change the source or the tests, or record why the failure cannot be "
    "repaired here, before asking for another verdict"
)


# 역할 → 그 역할을 **어떻게 세우는가**. 배정만으로는 배차가 일어나지 않는다: 호스트 모드에서
# 매 턴 모델에게 실제로 도착하는 신호는 이 응답 한 줄뿐이라, 여기에 "누가 도는가"만 있고 "어디에
# 세우는가"가 없으면 같은 세션이 그 역할을 연기한다. 26-08-13 helios-asgard 실측: 전이 함수가
# VERIFIER 를 12회 배정했고 12회 다 워커가 자기 diff 를 자기가 PASS 로 적었다 (서브에이전트 배차
# 0건). 워커를 인라인으로 도는 것은 합법이고 판정자를 인라인으로 도는 것은 아니라서, 두 문장을
# 함께 둔다 — 경계가 한 자리에서 보여야 지켜진다.
DISPATCH_HOW = {
    "VERIFIER": (
        "dispatch an independent verifier subagent (Claude Code / Cursor: `asgard-verifier`) — the hand that"
        " wrote this diff must not record its own verdict. Only when the host provides no subagents may the"
        " same session record it, and then it judges request + criteria + diff alone, ignoring its own notes."
    ),
    "THINKER": (
        "dispatch a thinker subagent (`asgard-thinker`) — planning is a separate seat from execution, and it"
        " reads the repository itself instead of inheriting the executor's account of it."
    ),
    "THINKER_REPLAN": (
        "dispatch a thinker subagent (`asgard-thinker`) to replan — the hand that hit the failure is the one"
        " least able to see past its own hypothesis (Canon 9)."
    ),
    "WORKER": (
        "plan and execute inline as MAIN_WORKER, or hand it to an `asgard-worker` subagent when the work wants"
        " a context of its own. Either is legal; the verdict that follows is not."
    ),
    "WORKER_RETRY": (
        "the same Worker seat repairs it — inline or `asgard-worker`. Reassign only the unfinished units."
    ),
    "BASELINE_VERIFY": (
        "no subagent — run `quest-log.py verify-baseline` with the same risk flags and let the harness record"
        " the verdict."
    ),
}


def transition(s: dict, policy: dict, flags, priors: dict | None = None) -> dict:
    """다음에 누가 도는가 — 결정 테이블. 물음 셋을 순서대로 묻고 첫 답을 그대로 쓴다."""
    axes = _transition_axes(s, policy, flags)
    role, why = _blocked_step(s, policy, flags) or _verdict_step(s, flags, priors, axes) or _next_step(s, flags, axes)
    # 역할은 안 바꾸고 사유만 늘린다. 역할을 바꾸면 이 관측이 정책이 되는데, 트리가 안 움직인
    # 이유는 워커가 놀았을 수도 있고 고칠 자리가 추적 파일 밖(환경·서비스)일 수도 있어 하네스가
    # 가릴 수 없다. 가릴 수 있는 것은 사실 하나뿐이다 — 판정을 다시 받아도 같은 답이 나온다는 것.
    # 이 문장이 없으면 다음 사유가 "연속 FAIL" 이라 원인을 접근 탓으로 잘못 적는다.
    if s.get("unchanged_since_fail"):
        why = "%s. Note: %s" % (why, UNCHANGED_SINCE_FAIL)
    verdict = {"next_role": role, "verify_level": axes["level"], "why": why, "features": axes["features"]}
    if how := DISPATCH_HOW.get(role):
        verdict["how"] = how
    return verdict
