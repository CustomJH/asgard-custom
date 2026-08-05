#!/usr/bin/env python3
# Asgard verifier-gate — Canon 10(완료 증명)의 훅 강제. Claude Code Stop 시점에 실행.
#
# 핵심은 로그 위조 방지가 아니라 **로그 밖 물리 증거 대조**다 (Goodhart 방어):
# 모델이 로그에 가짜 PASS를 append 해도 working-tree 상태는 위조할 수 없다. Stop 시점에 diff hash를
# 재계산해 PASS 레코드의 diff_hash와 대조한다 — 불일치 = stale PASS(PASS 후 추가 변경)도 잡힌다.
#
# 차단 알고리즘 (deterministic violation만 block, 그 외 전부 warn+allow — fail-open 유지):
#   활성 quest 없음 / 비-git / 파싱 실패          → allow
#   write 전무 + mutation 명령 전무 (trivial 면제) → allow
#   검증 PASS 레코드 없음 (하네스 또는 Verifier)   → block
#   PASS.diff_hash != 현재 hash (stale PASS)       → block
#   criteria 없음 / 성공 명령 증거 없음            → block
#   full-verify 필요(민감 경로·큰 diff)한데 micro   → block
#
# 왜 블록 3회 상한인가: Stop block → 모델 재시도 → 또 block의 무한 루프는 Canon 9(3-실패 법칙)
# 위반이다. 같은 세션에서 3회 차단하면 4번째는 경고와 함께 통과시키고 Odin 에스컬레이션을 지시한다.
# 게이트는 자기기만 방어지 인질극 장치가 아니다.
#
# 판정 기반(트리 해시·귀속 범위·증거·계약·정책)은 quest-log 와 **같은 함수**를 부른다. 26-08-06
# 까지는 그것이 이 파일 안의 사본이었고 두 파일 다 "동일 유지 (단일 출처 원칙)"이라고 적고
# 있었지만, 실제로는 `current_tree_ref`·`ignored_state`·`pass_evidence`·`unmet_contracts` 등
# 9개가 이미 갈라져 있었다 — 게이트와 CLI 가 같은 워킹트리에 다른 답을 낼 수 있는 상태였다.
import json
import os
import re
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass

# 공용 라이브러리는 이 훅 **옆에** 깔린다 (setup 의 `library_files`). 스크립트로 돌 때는
# `sys.path[0]` 이 이미 그 폴더다 — 이 세 줄은 저장소 안에서 `asgard.hooks.verifier_gate` 로
# 임포트될 때를 위한 것이다. `asgard` 임포트가 아니므로 자립 계약은 그대로다.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

# `F401` 이 붙은 줄은 이 게이트가 직접 안 부르지만 밖에서 `asgard.hooks.verifier_gate.<이름>` 으로
# 집는 이름이다 — 게이트와 CLI 가 같은 해시를 내는지 보는 패리티 시험(test_gate_ignored_scope)이
# 두 모듈에서 같은 이름을 꺼내 대조한다. 이제 그 대조는 같은 함수 객체끼리라 항상 참이고, 시험이
# 지키는 것은 "두 모듈이 같은 출처를 본다"는 계약 자체다.
from asgard_hooklib.contracts import (  # noqa: E402
    artifact_scope,  # noqa: F401
    contract_criteria,
    criteria_contracts,  # noqa: F401
    quest_events_scope,
    unmet_contracts,
)
from asgard_hooklib.evidence import pass_evidence  # noqa: E402
from asgard_hooklib.integrity import EMPTY, ledger_integrity, verification_identity  # noqa: E402
from asgard_hooklib.paths import git, is_testfile, read_text  # noqa: E402
from asgard_hooklib.policy import (  # noqa: E402
    DEFAULT_POLICY,  # noqa: F401
    full_verify_required,
    load_policy,
    sensitive_path,
)
from asgard_hooklib.scope import (  # noqa: E402
    UNBOUND,  # noqa: F401
    ignored_state,  # noqa: F401
    in_artifact_scope,  # noqa: F401
    unbound_artifacts,  # noqa: F401
    unsafe_map_links,
)
from asgard_hooklib.session import host_session_id  # noqa: E402
from asgard_hooklib.tree import (  # noqa: E402
    current_tree_ref,  # noqa: F401
    deleted_tests,
    diff_state,
    stale_pass_scope,
)

MAX_BLOCKS = 3  # Canon 9 정합 — 동일 세션 4번째 차단 대신 에스컬레이션
UNATTENDED_MODES = {"bypassPermissions", "dontAsk"}  # unattended_context.py와 동일 유지
_HOST_PROTOCOL = "claude"


def unattended(data):
    """무인 세션 신호 — 사람이 승인 루프에 없다. permission_mode는 모든 훅 stdin 공통 필드."""
    return os.environ.get("ASGARD_UNATTENDED") == "1" or str(data.get("permission_mode")) in UNATTENDED_MODES


def readonly(cmd, allow):
    c = str(cmd).strip()
    return any(c == a or c.startswith(a + " ") for a in allow)


# 게이트는 계약 명령을 재실행하지 않는다 (Stop 지연 예산) — quest-log 가 기록한 criteria_checks 를
# 대조하고 산출물 존재만 라이브 재확인한다. 판정 술어 자체는 `asgard_hooklib.contracts` 하나다.


def block_counter_path(root, sid):
    qid = quest_pointer(root, sid) or "orphan"
    scope = re.sub(r"[^A-Za-z0-9_.-]", "_", str(qid))[:64] or "orphan"
    return os.path.join(root, ".asgard", f"gate-blocks-{sid}-{scope}.json")


def gate_event(root, kind, code, subject=None):
    """게이트 운영 이벤트 영속 기록 — 차단 카운터 파일은 성공 통과 시 삭제되므로 운영 지표가
    안 남는다. doctor가 block/escalation 률을 집계할 수 있게 append-only로 남긴다. fail-open.

    `subject`는 그 차단이 무엇을 두고 걸렸는지다(stale-pass 면 드리프트한 파일). 사유 코드만
    남기면 어떤 사유가 몇 번인지는 세어도 무엇을 고칠지는 기록에서 알 수 없다."""
    try:
        path = os.path.join(root, ".asgard", "state", "gate-events.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        row = {"event": kind, "code": code}
        if subject:
            row["subject"] = list(subject)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── 차단 메시지 카탈로그 — 코드가 정본, 문장은 렌더링. 자기완결 배포 제약으로 asgard.failures
# 를 임포트하지 못해 사본을 품는다 — tests/test_failures.py 패리티 테스트가 두 표를 봉인한다. ──
# 문장 속 `uv run --no-project python`은 platform.hook_python_token() 의 정본을 리터럴로 옮겨 적은
# 것이다. 여기서 인터프리터를 다시 탐지하지 않는 이유는 두 가지다 — 이 파일은 asgard 를
# 임포트할 수 없고(자기완결 배포), uv 는 설치 경로가 보장하는 런타임이라 탐지할 것이 없다.
GATE_MESSAGES = {
    "orphan-write": (
        "This session wrote files ({files}) but there is no quest log. Write quests require "
        "the Trinity loop: open a log with uv run --no-project python <hooks>/quest-log.py open <quest-id> "
        '--criteria "..." and record Verifier verification.'
    ),
    "unsafe-map": "unsafe code map symlink/junction: {targets}",
    "snapshot-fail": "Failed to snapshot the current working tree — cannot compute change evidence, refusing to close.",
    "ledger-invalid": "Quest ledger integrity failed ({detail}) — replay or verification cannot trust this history.",
    "no-verdict": "Write quest without a Verifier verdict (PASS/ESCALATE) record.",
    "escalate-nudge": (
        "Ending with ESCALATE in an unattended session without attempting the work "
        "(Canon 8 unattended progress). Odin's answer will not arrive — pick a defensible "
        "default, record the assumption as a plan criteria `가정: ...` item, and dispatch "
        "a Worker. If it is a genuine blocker no default can defend, record the reason and "
        "ESCALATE again to pass."
    ),
    "stale-pass": "stale PASS — the working tree changed after PASS was recorded (physical diff mismatch). Re-verify.",
    "verification-identity": (
        "PASS evidence is not bound to this execution, acceptance contract and physical diff. Re-verify."
    ),
    "no-criteria": "No success criteria in the log. Verification cannot stand without criteria.",
    "tickets-incomplete": "Incomplete tickets remain ({units}) — bring every unit to done before verifying.",
    "criteria-unverified": (
        "criteria verify contract unmet ({unmet}) — for criteria with a declared contract, only that "
        "command/artifact counts as evidence. quest-log append --verdict PASS re-runs the contract "
        "command via the harness."
    ),
    "no-evidence": (
        "PASS lacks successful verification-command evidence (commands[{{cmd,exit_code==0}}]). "
        "The Verifier must run verification commands directly (always-succeeding commands like "
        "true/echo are not evidence)."
    ),
    "baseline-red": "Harness baseline checks red ({failing}) — fix the failing checks, then re-verify.",
    "micro-pass": (
        "full-verify required (sensitive paths {sensitive}{deleted} / diff {files} files·{lines} lines) "
        "but this is a micro PASS. Re-verify with --level full."
    ),
}


def gate_message(code, **params):
    return "[gate:%s] " % code + GATE_MESSAGES[code].format(**params)


def block(root, sid, code, subject=None, **params):
    """차단 — active quest별 MAX_BLOCKS 회까지. 초과 시 warn+allow + Odin 에스컬레이션 지시.
    사유는 코드+파라미터로만 받는다 — 문장은 GATE_MESSAGES가 렌더하고, 소비자(classify·doctor)는
    `[gate:<code>]` 태그/payload code를 직독한다 (문장 파싱 금지).

    `subject`는 운영 기록에만 들어간다. 이름이 `detail`이 아닌 이유는 그것이 `ledger-invalid`
    메시지의 렌더 인자라서다 — 같은 이름을 쓰면 그 값이 `**params`에 안 담기고 이 인자로 들어와
    `gate_message`가 `{detail}` 자리를 채우지 못한다."""
    reason = gate_message(code, **params)
    path = block_counter_path(root, sid)
    n = 0
    try:
        with open(path, encoding="utf-8") as handle:
            n = int(json.load(handle).get("n", 0))
    except Exception:
        pass
    n += 1
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())  # temp+rename — 크래시 절단이 카운터를 리셋하지 않게
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"n": n}, handle)
        os.replace(tmp, path)
    except Exception:
        pass
    gate_event(root, "gate_escalate" if n > MAX_BLOCKS else "gate_block", code, subject)
    if n > MAX_BLOCKS:
        sys.stderr.write(
            "asgard verifier-gate: exceeded %d blocks — allowing through, but Odin escalation "
            "is required (Canon 9)\n" % MAX_BLOCKS
        )
        sys.exit(0)
    message = (
        "Asgard verifier-gate (Canon 10 — proof of completion): "
        + reason
        # 명령 하나 + 상대 경로 — 허용목록이 원문 프리픽스로 맞추므로 파이프라인이면 앞
        # 세그먼트(`echo`)까지 허용목록에 있어야 하고, 없으면 헤드리스에서 자동 거부된다.
        + " Record the Verifier verdict in the log: uv run --no-project python <hooks>/quest-log.py "
        "append --json '{...}' --verdict PASS|FAIL (the verify event auto-computes diff_hash). "
        "If blocked 3+ times, stop and report to Odin (Canon 9)."
    )
    # code 필드는 claude/네이티브 경로만 — codex/cursor 프로토콜은 미지 필드 관용을 보증할 수
    # 없어 메시지 내 [gate:<code>] 태그가 공통 운반자다.
    if _HOST_PROTOCOL == "cursor":
        payload = {"followup_message": message}
    elif _HOST_PROTOCOL == "codex":
        payload = {"continue": False, "stopReason": message}
    else:
        payload = {"decision": "block", "reason": message, "code": code}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.exit(0)


def quest_pointer(root, sid, kind="active"):
    """세션별 quest 포인터 해석 — quest_log.active_quest·subagent_gate와 동일 의미론.

    게이트가 더 약하게 해석하면 session_id 변주만으로 Stop 게이트가 무장해제된다 (적대 벡터).
    미지 세션은 활성 quest가 정확히 1개일 때만 승계하고, 둘 이상이면 fail-closed."""
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(sid or "default"))[:64] or "default"
    sessions = os.path.join(root, ".asgard", "quest", "sessions")
    session_path = os.path.join(sessions, name + "." + kind)
    try:
        qid = read_text(session_path).strip()
        if qid:
            return qid
    except Exception:
        pass
    if kind == "active":
        if os.path.exists(os.path.join(sessions, name + ".known")):
            return None  # 이 세션은 이미 닫혔음 — 다른 세션으로 fallback 금지
        try:
            active = {
                read_text(os.path.join(sessions, entry)).strip()
                for entry in os.listdir(sessions)
                if entry.endswith(".active")
            }
            active.discard("")
            if len(active) == 1:
                return next(iter(active))
        except Exception:
            pass
        if os.path.isdir(sessions):
            return None
    # kind="last": 승인된 close는 legacy LAST도 항상 기록한다 — 세션 포인터 부재 시 안전 폴백
    for path in [os.path.join(root, ".asgard", "quest", "ACTIVE" if kind == "active" else "LAST")]:
        try:
            qid = read_text(path).strip()
            if qid:
                return qid
        except Exception:
            continue
    return None


def session_candidates(data, protocol):
    """이 Stop이 가리킬 수 있는 세션 신원 후보 — 앞선 것이 우선.

    호스트마다 Stop 페이로드가 세션을 넣는 방식이 다르다. Cursor는 아예 넣지 않아 게이트가
    `"cursor"`를 고정으로 봤는데, 정작 모델은 `quest-log.py open`을 **--session 없이** 부른다
    (AGENTS.md의 지시가 그렇다) — 그 기본값은 `$CLAUDE_SESSION_ID` 또는 `"-"` 다. 두 이름이
    영영 안 맞으니 포인터가 안 풀리고, 활성 quest가 둘 이상이면 "정확히 1개만 승계" 규칙마저
    비켜서 Stop 게이트가 조용히 통과했다 (26-07-31 실측: 활성 6개가 남은 저장소에서 무장해제).

    후보를 늘려도 판정은 약해지지 않는다 — 각 후보는 여전히 **자기 포인터 파일로만** 풀리고,
    목록은 고정이라 모델이 고를 수 있는 자리가 아니다 (session_id 변주 벡터는 그대로 막힌다)."""
    seen, out = set(), []
    for raw in (
        data.get("session_id"),
        host_session_id(),  # quest-log.py의 --session 기본값과 같은 이름을 같은 순서로 본다
        "cursor" if protocol == "cursor" else None,
        "-",  # 신원 부재로 열린 구 로그 호환 — 이 이름은 세션끼리 공유된다
        "default",  # 종전 게이트 기본값 (구 로그 호환)
    ):
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw or ""))[:64]
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out or ["default"]


def session_settled(root, name):
    """이 세션은 자기 quest를 닫았다 — 확정된 답이지 '모름'이 아니다.

    답 없음과 닫힘을 가르지 않으면, 방금 정상 종료한 세션이 **남의 남은 활성 포인터**를 물려받아
    오차단된다. 후보 탐색은 이 표식에서 멈춘다."""
    sessions = os.path.join(root, ".asgard", "quest", "sessions")
    return os.path.exists(os.path.join(sessions, name + ".known")) and not os.path.exists(
        os.path.join(sessions, name + ".active")
    )


def _pointer_file(root, name, kind="active"):
    """세션 포인터 파일만 읽는다 — 승계 휴리스틱 없이."""
    sessions = os.path.join(root, ".asgard", "quest", "sessions")
    try:
        return read_text(os.path.join(sessions, name + "." + kind)).strip() or None
    except Exception:
        return None


def _session_writes(root, names):
    """이 세션 이름들이 write-sentinel 에 남긴 경로 목록 — 기록이 없으면 None.

    자리가 둘이다: 신규 `state/writes-<이름>.json` 이 먼저고 구버전 평면 자리가 폴백이다."""
    for name in names:
        for rel in (os.path.join("state", "writes-" + name + ".json"), "writes-" + name + ".json"):
            try:
                with open(os.path.join(root, ".asgard", rel), encoding="utf-8") as handle:
                    return json.load(handle)
            # 없거나 깨진 기록은 "기록 없음"이다 — 이 게이트는 IO 실패에 fail-open 이고
            # (`orphan_writes` 도 같은 자리를 같은 방식으로 읽는다), 그 판단이 이제 승계까지
            # 지배한다: None 이면 `resolve_session` 이 남의 quest 를 안 물려받는다.
            except Exception:
                continue  # 위 주석이 근거다 — 기록 부재와 읽기 실패를 같게 다룬다
    return None


def resolve_session(root, candidates):
    """(quest id, 그 quest를 소유한 세션 이름).

    **엄격 조회를 먼저** 한 바퀴 돈다. `quest_pointer`의 "활성이 정확히 1개면 승계" 규칙을 후보마다
    적용하면, 포인터 파일이 애초에 없는 합성 이름(Cursor의 `"cursor"`)이 1순위에 서는 순간 곧장
    남의 quest를 물려받아 오차단한다 (26-07-31 실측). 승계는 **모든 후보가 답을 못 냈을 때만**
    쓰는 마지막 수단이다.

    그 마지막 수단도 **이 세션이 쓴 흔적이 있을 때만** 쓴다. 승계가 막는 것은 session_id 를 바꿔
    Stop 게이트를 벗어나는 경로인데, 그 경로는 write 를 남기므로 센티널 기록이 함께 남는다. 기록이
    아예 없는 세션 — 커밋만 하는 seal 턴이 그렇다 — 은 막을 write 가 없는데도 마침 하나 열려 있던
    남의 quest 를 물려받아 그 quest 의 판정을 요구받았다 (26-08-05 실측: seal 세션이 발표자료
    quest 에 묶여 Stop 이 네 번 연속 차단). 기록이 없으면 `orphan_writes` 백스톱만 돌고, 그쪽도
    같은 센티널을 보므로 실제 write 는 여전히 잡힌다."""
    for name in candidates:
        qid = _pointer_file(root, name)
        if qid:
            return qid, name
        if session_settled(root, name):
            return None, name  # 이 세션은 자기 quest를 닫았다 — 남의 활성을 승계하지 않는다
    if _session_writes(root, candidates) is None:
        return None, candidates[0]
    return quest_pointer(root, candidates[0]), candidates[0]


def orphan_writes(root, sid, candidates=None):
    """quest 로그 없이 끝나려는 세션의 write 흔적 검사 (write-sentinel 기록 대조).
    기록된 경로가 지금도 HEAD와 다르면 = 검증 안 된 write가 남아 있다 → 차단.
    되돌린 write(경로 clean)·사용자 기존 dirt(기록에 없음)는 차단하지 않는다.
    예외: 직전 close 된 quest(LAST)의 PASS가 현재 워킹트리 hash와 일치하면 이미 검증된 상태 —
    close 직후 Stop이 방금 검증한 write를 오차단하지 않게 한다."""
    # 센티널도 세션 이름으로 갈린다 — 게이트가 신원 연결을 따라갔다면 백스톱도 같은 연결을 봐야
    # 한다. 안 그러면 quest 포인터가 안 풀린 바로 그 경우에 백스톱까지 같이 눈이 먼다.
    writes = _session_writes(root, list(dict.fromkeys([sid, *(candidates or [])])))
    if writes is None:
        return  # 이 세션의 write 기록 없음 → 게이트 대상 아님
    dirty = []
    for rel in writes[:500]:
        rc, out = git(root, "status", "--porcelain", "--", str(rel))
        if rc == 0 and out.strip():
            dirty.append(str(rel))
    if not dirty:
        return
    # LAST is published only for APPROVED close. The checks below also reject legacy
    # ESCALATED/forced LAST pointers written by older versions.
    try:  # LAST quest의 PASS가 현 상태를 물리 증명하면 allow
        qid = quest_pointer(root, sid, "last")
        if not qid:
            raise FileNotFoundError("no last quest for session")
        events: list[dict] = []
        with open(os.path.join(root, ".asgard", "quest", qid + ".jsonl"), encoding="utf-8") as handle:
            for line in handle:
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        base_ref = next((e.get("base_ref") for e in events if e.get("base_ref")), None)
        closed = [e for e in events if e.get("event") == "quest_closed"]
        close_risk = (closed[-1].get("risk") or {}) if closed else {}
        if close_risk.get("decision") != "APPROVED" or close_risk.get("forced"):
            raise ValueError("LAST does not represent approved close")
        verdicts = [e for e in events if e.get("event") == "verify" and e.get("verdict") == "PASS"]
        if base_ref and verdicts and git(root, "rev-parse", "--verify", base_ref)[0] == 0:
            last = verdicts[-1]
            baseline_red = (last.get("baseline") or {}).get("state") == "red"  # --force close 우회 봉합
            ignored_base = next(
                (event.get("ignored_snapshot") for event in events if isinstance(event.get("ignored_snapshot"), dict)),
                None,
            )
            current_hash, last_changed, _, _ = diff_state(root, base_ref, ignored_base, quest_events_scope(events))
            # LAST 면제도 증거 요구 — 무증거 PASS + close 우회 구멍. 무변경은 관측이 곧 증거.
            evidence = pass_evidence(last, no_change=current_hash == EMPTY)
            fresh = last.get("diff_hash") == current_hash or not stale_pass_scope(root, last, events, last_changed)[0]
            if evidence and not baseline_red and "<snapshot-unavailable>" not in last_changed and fresh:
                return
    except Exception:
        pass
    block(
        root,
        sid,
        "orphan-write",
        files=", ".join(dirty[:3]) + (" 외 %d" % (len(dirty) - 3) if len(dirty) > 3 else ""),
    )


def main():
    global _HOST_PROTOCOL
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        _HOST_PROTOCOL = sys.argv[1] if len(sys.argv) > 1 else "claude"
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        candidates = session_candidates(data, _HOST_PROTOCOL)
        qid, sid = resolve_session(root, candidates)
        if not qid:
            # quest 미개설 우회 봉합 — write 흔적이 dirty 면 여기서 block
            orphan_writes(root, sid, candidates)
            sys.exit(0)  # write 흔적 없음 → 게이트 대상 아님
        events: list[dict] = []
        try:
            with open(os.path.join(root, ".asgard", "quest", qid + ".jsonl"), encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        events.append(json.loads(line))
                    except Exception:
                        events.append({"_corrupt": True, "_line": line_number})
        except Exception:
            sys.exit(0)  # 로그 읽기 실패 → warn+allow (fail-open)
        if not events:
            sys.exit(0)
        ledger_ok, ledger_detail = ledger_integrity(events)
        if not ledger_ok:
            block(root, sid, "ledger-invalid", detail=ledger_detail)
        base_ref = next((e.get("base_ref") for e in events if e.get("base_ref")), None)
        if not base_ref or base_ref == "NONE" or git(root, "rev-parse", "--verify", base_ref)[0] != 0:
            sys.stderr.write("asgard verifier-gate: cannot verify base_ref — allow (fail-open)\n")
            sys.exit(0)
        unsafe_maps = unsafe_map_links(root)
        if unsafe_maps:
            block(root, sid, "unsafe-map", targets=", ".join(unsafe_maps[:3]))
        policy = load_policy(root)
        ignored_base = next(
            (event.get("ignored_snapshot") for event in events if isinstance(event.get("ignored_snapshot"), dict)), None
        )
        current, changed, lines, nt_lines = diff_state(root, base_ref, ignored_base, quest_events_scope(events))
        if "<snapshot-unavailable>" in changed:
            block(root, sid, "snapshot-fail")
        cmds = [c for e in events for c in (e.get("commands") or []) if isinstance(c, dict)]
        mutating = [c for c in cmds if not readonly(c.get("cmd", ""), policy["readonly_commands"])]
        risk_write = any((e.get("risk") or {}).get("has_write") for e in events)
        if current == EMPTY and not risk_write and not mutating:
            sys.exit(0)  # trivial 면제 — write·mutation 전무 + read-only 명령만

        # 판정 레코드 = verify 이벤트의 PASS 또는 ESCALATE. ESCALATE는 Canon 9의 정규 종료
        # (close도 인정) — 오딘 보고 세션을 게이트가 인질로 잡으면 정직한 에스컬레이션이
        # 3회 헛차단 + fail-open 상한에 기대게 된다 (E2E 벤치 S4에서 실측된 마찰).
        verdicts = [e for e in events if e.get("event") == "verify" and e.get("verdict") in ("PASS", "ESCALATE")]
        if not verdicts:
            block(root, sid, "no-verdict")
        p = verdicts[-1]
        if p.get("verdict") == "ESCALATE":
            # 무인 세션에서 work 시도 전무한 ESCALATE = 승인 대기 모양 (오딘이 없어
            # 답이 올 수 없다). 1회만 되돌려보내 Canon 8 무인 진행을 지시 — 재차 ESCALATE 하면
            # 진짜 블로커로 인정하고 통과 (마커 파일 = 세션당 1회 상한, 인질극 방지).
            if unattended(data) and not any(e.get("event") == "work" for e in events):
                marker = os.path.join(root, ".asgard", "escalate-nudge-" + sid)
                if not os.path.exists(marker):
                    try:
                        with open(marker, "w", encoding="utf-8") as handle:
                            handle.write("1")
                    except Exception:
                        pass
                    block(root, sid, "escalate-nudge")
            try:
                os.remove(block_counter_path(root, sid))
            except Exception:
                pass
            sys.exit(0)  # 종료 허용 — 단 완료가 아니라 오딘 결정 대기 상태 (퀘스트 로그에 ESCALATE가 남는다)
        if p.get("diff_hash") != current:
            # 해시 불일치 = 즉시 stale이 아니다 — 귀속 범위 대조 (병렬 세션 드리프트 면책,
            # quest_log.summarize와 동일 판정). fail-safe: 대조 불가면 종전대로 차단.
            stale, _drift_out = stale_pass_scope(root, p, events, changed)
            if stale:
                block(root, sid, "stale-pass", subject=stale[:10])
        if p.get("execution_id") and (
            not p.get("verification_id") or p.get("verification_id") != verification_identity(p)
        ):
            block(root, sid, "verification-identity")
        if not any(e.get("criteria") for e in events):
            block(root, sid, "no-criteria")
        ticket_state = {}
        for event in events:
            if event.get("event") == "ticket" and event.get("unit") is not None:
                ticket_state[str(event["unit"])] = event.get("ticket_status")
        unfinished = [unit for unit, status in ticket_state.items() if status != "done"]
        if unfinished:
            block(root, sid, "tickets-incomplete", units=", ".join(unfinished[:6]))
        unmet = unmet_contracts(root, contract_criteria(*(e.get("criteria") for e in events)), p)
        if unmet:
            block(root, sid, "criteria-unverified", unmet="; ".join(map(str, unmet[:3])))
        if not pass_evidence(p, no_change=current == EMPTY):
            block(root, sid, "no-evidence")
        bl = p.get("baseline") or {}
        if bl.get("state") == "red":  # 하네스가 직접 돌린 프로젝트 체크 실패 — 코드가 깨져 있다
            rows = [r for r in (bl.get("results") or []) if isinstance(r, dict)]
            failing = [str(r.get("cmd")) for r in rows if r.get("exit_code") not in (0, None)]
            fails = [str(f) for r in rows for f in (r.get("fails") or [])]  # 정형 실패 줄 (run_baseline 채집)
            block(
                root,
                sid,
                "baseline-red",
                failing=", ".join(failing[:3]) + (" — " + "; ".join(fails[:3]) if fails else ""),
            )
        small = policy["small_write"]
        sensitive = [f for f in changed if sensitive_path(f, policy["sensitive_paths"])]
        dts = deleted_tests(root, base_ref)
        nt_files = [f for f in changed if not is_testfile(f)]  # 테스트 추가 ≠ 리스크 질량
        full_required = full_verify_required(
            policy, bool(sensitive) or bool(dts) or len(nt_files) > small["max_files"] or nt_lines > small["max_lines"]
        )
        if full_required and p.get("level") != "full":
            block(
                root,
                sid,
                "micro-pass",
                sensitive=sensitive[:3],
                deleted=" / deleted tests %s" % dts[:3] if dts else "",
                files=len(changed),
                lines=lines,
            )
        try:  # 통과 → 차단 카운터 리셋 (다음 위반은 새로 3회부터)
            os.remove(block_counter_path(root, sid))
        except Exception:
            pass
    except Exception:
        sys.exit(0)  # 훅 자체 오류 = allow — 게이트가 죽어도 세션을 인질로 잡지 않는다
    sys.exit(0)


if __name__ == "__main__":
    main()
