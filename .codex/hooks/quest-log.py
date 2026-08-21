#!/usr/bin/env python3
# Asgard quest-log — Trinity 퀘스트 로그 + 전이 함수 CLI.
#
# 코디네이터(Heimdall)의 "관찰·기록·배정" 프리미티브. 훅이 아니라 에이전트가 직접 부르는 도구다:
#   open   <quest-id>  과업 로그 시작 (base_ref = 현재 HEAD 고정, ACTIVE 포인터 갱신)
#   append             이벤트 1건 기록 (--json 또는 stdin JSON + 플래그) — verify는 diff_hash 자동 계산
#   state              로그 요약 관찰 (코디네이터의 state observation)
#   next               전이 함수: 로그 상태 + risk_features → next_role (결정 테이블)
#   close              완료된 quest의 ACTIVE 해제 (PASS+hash 일치 또는 ESCALATE만)
#   verify-baseline    하네스가 베이스라인 체크를 직접 실행해 verify 판정을 기록 (게이트-우선)
#
# 왜 CLI 인가: TRINITY의 "<20K 파라미터 코디네이터"의 하니스 등가물은 학습 모델이 아니라 결정론적
# 구조다 — 배정(next)을 LLM 임의 판단이 아닌 코드가 내리게 해서 조율을 프롬프트가 아닌 구조로
# 옮긴다 (TRINITY-inspired 적응).
# 왜 O_APPEND+해시체인인가: 한 줄 원자 append는 동시 writer의 절단은 막지만, 재개 전에 생긴
# 수동 편집·부분 복사·중간 줄 유실은 탐지하지 못한다. v2는 각 줄을 이전 줄 해시에 묶는다.
# 비밀키 서명이 아니라 crash/replay 무결성 장치다 — 악의적 로컬 writer를 막는다고 주장하지 않는다.
# 완료 위조 방어는 이 파일 몫이 아니다 — verifier-gate.py가 Stop 시점에 working-tree diff hash를
# 재계산해 물리 대조한다. 로그에 뭘 쓰든 워킹트리는 위조할 수 없다 (Goodhart 방어).
# diff_hash를 여기(append)서도 계산하는 이유: verifier가 손으로 만든 해시는 gate 재계산과 어긋날
# 수 있다 — 같은 알고리즘이 유일한 출처여야 한다. 그 알고리즘은 이제 `asgard_hooklib.tree` 하나에
# 있고 게이트도 같은 함수를 부른다 (그전에는 두 파일에 사본이었고, 실제로 갈라져 있었다).
#
# 이 파일은 두 얼굴이다. ① setup이 `.claude/hooks/quest-log.py`로 **원문 그대로 복사**해 배포하는
# 단일 파일 CLI (에이전트가 subprocess로 부른다) ② Trinity가 임포트하는 라이브러리
# (agent/heimdall/*, templates/trinity.py, commands/doctor.py, hooks/memory_activate.py).
# 그 두 얼굴 때문에 26-08-06까지 3,764줄이 여기 있었다: 코어를 asgard 패키지로 옮기면 ①이 죽고
# (배포 사본은 asgard를 임포트할 수 없다), 폴백 구현을 두면 상태기계 정본이 둘이 된다.
# 이제 상태기계는 `asgard_hooklib/`에 있고 **그 패키지가 훅과 같은 폴더에 함께 깔린다** — 배포본은
# 여전히 asgard를 임포트하지 않고(자립 계약 유지), 여기 남은 것은 CLI 갈래다.
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass

# 공용 라이브러리는 이 파일 **옆에** 깔린다. 스크립트로 돌 때는 `sys.path[0]`이 이미 그 폴더라
# 아무것도 안 해도 되지만, 저장소 안에서 `asgard.hooks.quest_log`로 임포트될 때는 아니다.
# 이 세 줄이 두 얼굴을 같은 코드로 묶는다 (`asgard` 임포트가 아니므로 자립 계약은 그대로다).
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

# 이 블록은 CLI 가 쓰는 이름과 **라이브러리 면**을 함께 세운다. `F401` 이 붙은 줄은 이 파일이
# 안 쓰지만 Trinity·doctor·시험이 `asgard.hooks.quest_log`에서 집는 이름이다 — 여기 서 있어야
# 소비처의 임포트 경로가 안 바뀐다. 정의는 전부 `asgard_hooklib` 안이고, 이 블록이 하는 일은
# "어느 모듈에 사는가"를 호출부에 남기는 것뿐이다 (고칠 곳은 여기가 아니라 그 모듈이다).
from asgard_hooklib.baseline import (  # noqa: E402
    MAX_CHECKS,  # noqa: F401
    _parallel_pytest,  # noqa: F401
    _run_check,  # noqa: F401
    baseline_ran,
    fail_lines,  # noqa: F401
    run_baseline,
    run_criteria_checks,
)
from asgard_hooklib.contracts import (  # noqa: E402
    artifact_scope,
    contract_criteria,  # noqa: F401
    criteria_contracts,  # noqa: F401
    effective_criteria,
    quest_events_scope,
    unmet_contracts,
)
from asgard_hooklib.evidence import inspection_evidence, pass_evidence, trivial_evidence  # noqa: E402,F401
from asgard_hooklib.integrity import (  # noqa: E402
    EMPTY,
    acceptance_identity,
    event_identity,  # noqa: F401
    ledger_integrity,
    verification_identity,
)
from asgard_hooklib.ledger import (  # noqa: E402
    APPEND_EVENTS,
    EVENT_FIELDS,
    HARNESS_FIELDS,
    SCHEMA,  # noqa: F401
    TICKET_STATUSES,
    VERDICTS,
    fold_tickets,  # noqa: F401
    load_events,
    normalize,
    quest_lock,
    replay_ledger,
    write_event,
    write_event_unlocked,
)
from asgard_hooklib.paths import git, is_junk, quest_dir, read_text, repo_root  # noqa: E402
from asgard_hooklib.policy import (  # noqa: E402
    DEFAULT_POLICY,  # noqa: F401
    full_verify_required,  # noqa: F401
    load_policy,
    sensitive_path,  # noqa: F401
)
from asgard_hooklib.runners import detect_checks  # noqa: E402,F401
from asgard_hooklib.scope import (  # noqa: E402
    UNBOUND,  # noqa: F401
    ignored_state,
    in_artifact_scope,  # noqa: F401
    unbound_artifacts,  # noqa: F401
    unsafe_map_links,
)
from asgard_hooklib.session import (  # noqa: E402
    active_quest,
    clear_active_quest,
    host_session_id,
    session_pointer,
    set_active_quest,
    write_pointer,
)
from asgard_hooklib.summary import (  # noqa: E402
    load_priors,
    prune_quests,
    summarize,
    update_priors,  # noqa: F401
)
from asgard_hooklib.tickets import DEFAULT_LEASE_SECONDS, ticket_runtime  # noqa: E402
from asgard_hooklib.transition import completion_decision, transition  # noqa: E402
from asgard_hooklib.tree import (  # noqa: E402
    current_tree_ref,
    diff_state,
    peer_base_of,
    peer_current,
    peer_snapshot,
    snapshot_ref,
)


def map_nudge(root: str, base_ref: str | None) -> list[str]:
    """close 시 지도 갱신 리마인더 — base_ref 이후 구조 변경(추가 A/삭제 D/이동 R)만 본다.
    0-LLM·fail-open: git 실패·지도 미도입(.asgard/map 부재)이면 침묵. 내용 수정(M)은 지도 무관.
    diff는 untracked를 못 보므로 ls-files --others를 A로 합류 (diff_state와 동일 처리)."""
    if not base_ref or base_ref == "NONE" or not os.path.isdir(os.path.join(root, ".asgard", "map")):
        return []

    def mappable(p: str) -> bool:  # 런타임·캐시·닷디렉토리(.claude 등 스캐폴드) 제외 — 소스 구조만
        return bool(p.strip()) and not is_junk(p) and not any(seg.startswith(".") for seg in p.split("/"))

    rc, out = git(root, "diff", "--name-status", "--diff-filter=ADR", base_ref, "--", ".", ":(exclude).asgard")
    if rc != 0:
        return []
    changes: list[str] = []
    for row in out.splitlines():
        parts = row.split("\t")
        st = parts[0][:1] if parts else ""
        if st == "R" and len(parts) >= 3 and (mappable(parts[1]) or mappable(parts[2])):
            changes.append(f"R {parts[1]} → {parts[2]}")
        elif st in ("A", "D") and len(parts) >= 2 and mappable(parts[1]):
            changes.append(f"{st} {parts[1]}")
    _, unt = git(root, "ls-files", "--others", "--exclude-standard", "--", ".", ":(exclude).asgard")
    changes += sorted(f"A {p}" for p in unt.splitlines() if mappable(p))
    return changes[:20]  # 상한 — 대량 이동에서 close 출력이 지도 노릇을 하지 않게


def refresh_managed_map(root: str) -> tuple[bool, str | None]:
    """Verifier hash 전에 PROJECT.md와 관계 GRAPH.md를 갱신한다.

    검증 뒤 close에서 쓰면 PASS hash가 즉시 stale해진다. 따라서 자동 지도 변경도 반드시
    Verifier가 판정하는 diff에 포함되도록 이 시점 하나에서만 쓴다. 지도 미도입은 정상이나,
    도입된 지도의 안전/소유권/IO 갱신 실패는 PASS를 허용하면 안 되므로 호출자가 FAIL로 강등한다.
    """
    if not os.path.isdir(os.path.join(root, ".asgard", "map")):
        return True, None
    try:
        from asgard.code_map import refresh_map
        from asgard.map_graph import scan_graph

        refresh_map(root)
        scan_graph(root)
        return True, None
    except Exception as exc:
        import_error = f"{exc.__class__.__name__}: {str(exc)[:300]}"
        for command in (["asgard", "map", "update", "--quiet"], ["asgard", "map", "scan", "--quiet"]):
            try:
                completed = subprocess.run(
                    command, cwd=root, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace"
                )
            except Exception as cli_exc:
                return False, f"{import_error}; CLI fallback {cli_exc.__class__.__name__}: {str(cli_exc)[:200]}"
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()[:300]
                return False, f"{import_error}; CLI fallback: {detail}"
        return True, None


def tests_available(root: str) -> bool:
    return any(
        os.path.exists(os.path.join(root, p)) for p in ("test", "tests", "pytest.ini", "pyproject.toml", "package.json")
    )


def sanitize(qid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", qid)[:80]


# ── 티켓 런타임 — 단위 하나의 소유권과 lease 를 상태 전이로 관리한다 ──
# 갈래마다 한 함수를 둔다. `emit` 은 호출부(ticket_runtime)가 Quest lock 안에서 만든 기록
# 함수다 — lock 밖에서 이벤트를 쓸 수 없게 갈래는 자기 lock 을 잡지 않는다.


# ── CLI 갈래 ──────────────────────────────────────────────────────
# main은 갈래만 고른다. 명령 하나의 계약은 그 명령의 함수 하나가 진다 — 열한 개가 한 함수에
# 있으면 그중 하나를 읽으려고 나머지 열을 같이 읽어야 하고, 하나를 고칠 때 나머지 열이 같이
# 흔들린다. 갈래 함수는 int(종료 코드)를 돌려주고, 출력은 자기가 한다.


def _error(message: str, **extra) -> int:
    """오류 한 줄을 stderr JSON으로 내고 1을 돌려준다 — 실패 표기를 갈래마다 다시 적지 않게."""
    print(json.dumps({"error": message, **extra}), file=sys.stderr)
    return 1


def _parser() -> argparse.ArgumentParser:
    """CLI 표면의 정본 — 명령 이름과 플래그는 여기서만 정의한다."""
    ap = argparse.ArgumentParser(prog="quest-log", description="Asgard Trinity quest log")
    ap.add_argument(
        "cmd",
        choices=[
            "open",
            "attach",
            "append",
            "state",
            "replay",
            "next",
            "close",
            "verify-baseline",
            "amend-criteria",
            "ticket-claim",
            "ticket-heartbeat",
            "ticket-finish",
            "ticket-recover",
        ],
    )
    ap.add_argument("quest_id", nargs="?")
    ap.add_argument("--criteria", action="append", default=[])
    ap.add_argument("--reason", default="", help="amend-criteria: why the opening criteria can no longer bind")
    ap.add_argument("--request", default="", help="open: original task text for crash-safe native resume")
    ap.add_argument("--request-stdin", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--base-ref", help=argparse.SUPPRESS)
    ap.add_argument("--session", default=host_session_id())
    ap.add_argument("--json", help="append: event body as one argument (stdin equivalent, single command)")
    ap.add_argument("--role"), ap.add_argument("--event"), ap.add_argument("--verdict")
    ap.add_argument("--level", choices=["micro", "full"])
    ap.add_argument("--unit")
    ap.add_argument("--worker")
    ap.add_argument("--claim-token")
    ap.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS)
    ap.add_argument(
        "--older-than",
        type=float,
        default=None,
        help="ticket-recover: lease 만료 뒤 이만큼 더 조용했던 것만 회수한다 (초, 기본 300)",
    )
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--status")
    ap.add_argument("--error")
    ap.add_argument("--no-write", action="store_true", help="open: mark as a task with no write")
    # 모델 신고 risk_features (결정론 계산이 불가능한 4종) — next 전용
    ap.add_argument("--ambiguous", action="store_true")
    ap.add_argument("--destructive", action="store_true")
    ap.add_argument("--external-research", action="store_true")
    ap.add_argument("--shared", action="store_true")
    ap.add_argument("--structural", action="store_true", help="next: report that the last FAIL was structural")
    ap.add_argument("--write-expected", action="store_true", help="next: no diff yet, but a write is expected")
    ap.add_argument(
        "--parallel-requested",
        action="store_true",
        help="next: user explicitly requested parallel decomposition/multi-subagent",
    )
    ap.add_argument(  # Canon 8 무인 진행 — asgard run이 env를 심으므로 기본값이 env를 읽는다
        "--unattended", action="store_true", default=os.environ.get("ASGARD_UNATTENDED") == "1"
    )
    ap.add_argument(
        "--task-class",
        choices=["trivial", "standard", "deep"],
        dest="task_class",
        help="open: record in log / next: axis for looking up the prior promotion threshold",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="close: force-release without a verdict (requires Odin's consent — LAST not recorded, no gate exemption)",
    )
    return ap


def _open_request(args) -> tuple[str | None, str]:
    """open의 요청문 — (요청문, 오류). None은 요청문을 못 얻었다는 뜻이다."""
    if not args.request_stdin:
        return args.request, ""
    raw_request = sys.stdin.buffer.read(65537)
    if len(raw_request) > 65536:
        return None, "request payload exceeds 64 KiB limit"
    try:
        return str((json.loads(raw_request.decode("utf-8")) or {}).get("request") or ""), ""
    except Exception:
        return None, "invalid request stdin payload"


def _open_base_ref(root: str, args) -> tuple[str | None, str]:
    """open의 시작 스냅샷 — (base_ref, 오류). 명시 ref는 커밋인지 확인한 뒤에만 쓴다."""
    base_ref = args.base_ref or snapshot_ref(root)
    if args.base_ref:
        valid_rc, raw_type = git(root, "cat-file", "-t", args.base_ref)
        valid_type = raw_type.decode("utf-8", "replace") if isinstance(raw_type, bytes) else raw_type
        if valid_rc != 0 or valid_type.strip() != "commit":
            return None, "invalid quest start snapshot"
    if not base_ref and not args.no_write:
        return None, "write quest requires a Git repository with HEAD and a capturable start tree"
    return base_ref or "NONE", ""


def _open_event(qid: str, args, base_ref: str, request: str, ignored_snapshot: dict, peers: dict) -> dict:
    """개설 이벤트 — 요청문·기준·시작 트리·위험을 수용 해시 하나로 묶는다.

    `peer_snapshot` 은 선언된 짝 저장소의 시작 트리다. `base_ref` 가 세션 뿌리 하나만 담아서,
    이것이 없으면 짝 저장소 작업이 판정 내내 무변경으로 읽힌다."""
    risk = {"has_write": not args.no_write}
    if args.task_class:  # prior 집계 축 — 퀘스트가 어느 클래스로 열렸는지 감사 기록
        risk["task_class"] = args.task_class
    return normalize(
        {
            "role": "thinker",
            "event": "plan",
            "base_ref": base_ref,
            "risk": risk,
            "criteria": args.criteria,
            "request": request,
            "ignored_snapshot": ignored_snapshot,
            "peer_snapshot": peers,
            "execution_id": secrets.token_hex(16),
            "acceptance_hash": acceptance_identity(
                request=request,
                criteria=args.criteria,
                base_ref=base_ref,
                ignored_snapshot=ignored_snapshot,
                risk=risk,
            ),
        },
        [],
        qid,
        args.session,
    )


def _cmd_attach(root: str, args) -> int:
    """attach — 이 세션의 포인터를 이미 열려 있는 퀘스트에 다시 묶는다.

    호스트가 세션 신원을 갈아끼우면 (26-08-04 실측: CLAUDE_CODE_SESSION_ID 가
    39f84a83→2a24f078) `sessions/<sid>.active` 가 없어 모든 명령이 "no active quest" 를 낸다.
    포인터를 쓰는 명령은 `open` 하나인데 그쪽은 같은 id 의 재개통을 거부하므로(한 id = 한 실행)
    돌아갈 길이 아예 없었다 — 진행 중인 기장이 세션 하나를 통째로 잃었다.

    새 실행을 만들지 않는다: 이벤트도, base_ref 도, acceptance_hash 도 그대로다. 옮기는 것은
    **이 세션의** 포인터 파일뿐이라 판정 근거도, 다른 세션이 보는 것도 안 바뀐다.

    다른 세션이 이미 같은 퀘스트를 들고 있어도 막지 않는다 — 그 상태가 바로 이 명령이 푸는
    자리다(옛 신원의 포인터는 남아 있다). 대신 두 세션이 한 기장에 적게 되므로, 누가 적었는지는
    이벤트의 `session_id` 로만 남는다."""
    if not args.quest_id:
        print("usage: quest-log attach <quest-id> [--session <id>]", file=sys.stderr)
        return 2
    qid = sanitize(args.quest_id)
    events = load_events(root, qid)
    if not events:
        return _error("no such quest to attach: %s" % qid)
    if any(event.get("event") == "quest_closed" for event in events):
        return _error("quest is closed — open a new quest id rather than attaching to a finished execution")
    # 이 세션 **자신의** 포인터만 본다. active_quest 의 승계 갈래(활성 퀘스트가 정확히 하나면
    # 물려받는다)를 쓰면 남의 퀘스트를 이유로 재바인딩이 거부된다 — 그 자리가 바로 이 명령이
    # 풀려는 자리다.
    try:
        held = read_text(session_pointer(root, args.session)).strip()
    except Exception:
        held = ""
    if held and held != qid:
        return _error("session already holds an open quest (%s) — close it before attaching to another" % held)
    # 이 세션의 포인터만 옮긴다. `set_active_quest` 는 기계 전역 `ACTIVE` 도 같이 쓰는데, 그것은
    # 세션 이름 없이 묻는 소비처들이 읽는 자리다 (subagent_gate·failure_tracker·verifier_gate·
    # heimdall·memory_activate). 한 세션의 복구 명령이 그 자리를 옮기면 옆 세션의 일이 이쪽
    # 퀘스트로 귀속된다 — 이 명령이 고치려는 사고와 같은 종류다 (26-08-05 교차검토 실측).
    write_pointer(session_pointer(root, args.session), qid)
    write_pointer(session_pointer(root, args.session, "known"), qid)
    first = events[0]
    print(
        json.dumps(
            {
                "attached": qid,
                "session": args.session,
                "execution_id": first.get("execution_id"),
                "acceptance_hash": first.get("acceptance_hash"),
                "base_ref": first.get("base_ref"),
                "turn": events[-1].get("turn"),
                **_next_note(root, qid, events, load_policy(root), args),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _next_note(root: str, qid: str, events: list[dict], policy: dict, args) -> dict:
    """지금 상태에서 누가 도는가 — `next` 가 내는 것과 같은 값, 같은 함수(`transition`)에서.

    `open` 과 `append` 응답에 합류시킨다. 두 명령은 이미 상태를 다 계산해 놓고도 역할은 안
    돌려줘서, 계약이 매번 `next` 를 따로 부르게 했다 — 퀘스트 한 건에 모델 왕복 2회가 그
    사이에 상태가 한 글자도 안 바뀌는 채로 들어갔다 (26-08-04 실측: 슬라이스 한 건 8회 중 2회).

    판정 기준은 옮기지 않는다. 이 함수는 `transition` 을 부를 뿐이고, `next` 도 같은 것을
    부른다 — 두 자리가 갈리면 모델이 보는 역할과 게이트가 세는 역할이 달라진다. 실패는 삼킨다:
    역할 힌트를 못 만든 것이 기장 자체를 막으면 안 된다 (`next` 로 다시 물으면 된다)."""
    try:
        state = summarize(root, qid, events, policy)
        state["tests_available"] = tests_available(root)
        verdict = transition(state, policy, args, load_priors(root))
    except Exception:
        return {}
    return {key: verdict[key] for key in ("next_role", "why", "verify_level", "how") if key in verdict}


def _cmd_open(root: str, args) -> int:
    """open — 과업 로그를 시작한다.

    One qid represents one immutable execution. Reopening would mix two acceptance contracts."""
    if not args.quest_id:
        print("usage: quest-log open <quest-id> [--criteria ...]", file=sys.stderr)
        return 2
    qid = sanitize(args.quest_id)
    request, why = _open_request(args)
    if request is None:
        return _error(why)
    if len(request) > 10000:
        return _error("request exceeds 10,000-character limit")
    base_ref, why = _open_base_ref(root, args)
    if base_ref is None:
        return _error(why)
    ignored_snapshot = ignored_state(root, artifact_scope(args.criteria))
    if "<snapshot-unavailable>" in ignored_snapshot:
        return _error("ignored-file snapshot unavailable")
    ev = _open_event(qid, args, base_ref, request, ignored_snapshot, peer_snapshot(root) if not args.no_write else {})
    with quest_lock(root, qid):
        if os.path.exists(os.path.join(quest_dir(root), qid + ".jsonl")):
            return _error("quest id already exists; resume it or choose a new id")
        write_event_unlocked(root, qid, ev, [])
    set_active_quest(root, args.session, qid)
    print(
        json.dumps(
            {
                "opened": qid,
                "execution_id": ev["execution_id"],
                "acceptance_hash": ev["acceptance_hash"],
                "base_ref": base_ref,
                "turn": ev["turn"],
                **_next_note(root, qid, [ev], load_policy(root), args),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _append_payload(args) -> tuple[dict | None, int]:
    """append가 받을 이벤트 원문 — `--json`(없으면 stdin) 위에 플래그를 덮는다. (원문, 종료 코드).

    `--json`이 있는 이유는 권한 계층이다. 호스트의 Bash 허용목록은 원문 문자열 프리픽스로
    맞추고 셸 연산자를 알아보므로, `echo … | quest-log.py append` 는 앞 세그먼트(`echo`)까지
    허용목록에 있어야 통과한다 — 없으면 헤드리스에서 자동 거부되고, 역할이 이벤트를 못 남기니
    subagent-gate 가 종료를 다시 막아 교착이다. 인자 하나로 받으면 명령이 하나라 그 자리에서
    프리픽스에 걸린다."""
    raw: dict = {}
    if args.json:
        try:
            raw = json.loads(args.json)
        except Exception:
            print(json.dumps({"error": "--json is not valid JSON"}), file=sys.stderr)
            return None, 2
        if not isinstance(raw, dict):
            print(json.dumps({"error": "--json must be a JSON object"}), file=sys.stderr)
            return None, 2
    elif not sys.stdin.isatty():
        try:
            body = sys.stdin.read().strip()
            raw = json.loads(body) if body else {}
        except Exception:
            print(json.dumps({"error": "stdin is not valid JSON"}), file=sys.stderr)
            return None, 2
    for k, v in (("role", args.role), ("event", args.event), ("verdict", args.verdict), ("level", args.level)):
        if v:
            raw[k] = v
    if isinstance(raw.get("role"), str):
        raw["role"] = raw["role"].lower()  # 전이 함수 출력(WORKER)을 그대로 넣는 세션 실측 — 통계 축 분열 방지
    if args.criteria:
        raw["criteria"] = args.criteria
    return raw, 0


def _append_rejection(raw: dict) -> str:
    """append가 받지 않는 원문의 이유 — 빈 문자열이면 받는다."""
    # normalize 는 코어 스키마만 남기고 나머지 키를 버린다 (`ledger.EVENT_FIELDS`). 버려진 서술을
    # 쓴 쪽은 적었다고 보고 읽는 쪽은 빈 칸을 보므로, 침묵 대신 여기서 거절한다 — 아래 `outcome`
    # 오타를 거절하는 것과 같은 이유다.
    forged = sorted(set(raw) & HARNESS_FIELDS)
    if forged:
        return (
            "harness-owned field(s): %s — the tool writes these itself at verdict time; "
            "a caller-supplied value is a forgery and never reaches the record." % ", ".join(forged)
        )
    unknown = sorted(set(raw) - EVENT_FIELDS)
    if unknown:
        return (
            "unknown field(s): %s — normalize keeps only the core schema, so these would be dropped "
            "without a trace. Free-form narration belongs in 'subtask'." % ", ".join(unknown)
        )
    if raw.get("event") not in APPEND_EVENTS:  # ticket_lease는 ticket-heartbeat 전용
        return "event must be one of %s" % sorted(APPEND_EVENTS)
    if raw.get("event") == "ticket":
        if raw.get("unit") is None:
            return "ticket requires unit"
        if raw.get("ticket_status") not in TICKET_STATUSES:
            return "ticket_status must be one of %s" % sorted(TICKET_STATUSES)
        if raw.get("ticket_status") != "todo" or raw.get("role") != "thinker":
            return (
                "ticket runtime transitions require ticket-claim/heartbeat/finish/recover; "
                "raw append only accepts thinker todo definitions"
            )
    # `harness` 이름이 붙은 **통과 판정**은 Stop 게이트에서 판정자 독립성 검사를 면제받는다
    # (`evidence.harness_verdict`). 손으로 적을 수 있게 두면 그 면제가 곧 우회다 — diff 를 쓴
    # 워커가 필드 하나로 자기 PASS 를 하네스 판정으로 위장한다. 진짜 통과 경로
    # (`_cmd_verify_baseline`)는 `normalize` 를 직접 불러 여기를 안 지난다.
    #
    # FAIL 은 막지 않는다. 면제가 붙는 자리는 게이트가 읽는 마지막 PASS·ESCALATE 하나뿐이고,
    # 실패를 하네스 이름으로 적어서 얻는 것은 없다. 네이티브 루프가 실제로 그렇게 적는다 —
    # `trinity/turns.py` 의 `invalid-parallel-plan` 은 코드가 낸 구조 판정이라 그 이름이 맞다.
    if str(raw.get("role") or "").strip().lower() == "harness" and raw.get("verdict") in ("PASS", "ESCALATE"):
        return "a harness PASS is written by verify-baseline, not by append — record the verdict under your own role"
    if raw.get("verdict", "NA") not in VERDICTS:
        return "verdict must be one of %s" % sorted(VERDICTS)
    # 오타를 받아 주면 그 칸이 정규화에서 사라져 배차가 succeeded 로 접힌다 — 실패를 적었다고
    # 믿는 쪽과 성공을 읽는 쪽이 갈린다. `verdict` 와 같은 규약으로 쓰는 자리에서 거절한다.
    if str(raw.get("outcome") or "succeeded").strip().lower() not in ("succeeded", "failed"):
        return "outcome must be succeeded or failed"
    return ""


def _verify_evidence(root: str, policy: dict, events: list[dict], ev: dict) -> None:
    """verify 이벤트의 물리 증거를 이 도구가 채운다 — 손 계산 해시는 게이트 재계산과 어긋난다."""
    # 구조 지도도 판정 대상 diff에 포함 — PASS 뒤 close가 파일을 쓰면 stale hash가 된다.
    map_ok, map_error = refresh_managed_map(root)
    ignored_base = next(
        (event.get("ignored_snapshot") for event in events if isinstance(event.get("ignored_snapshot"), dict)),
        None,
    )
    ev["diff_hash"], ev["changed_files"], _, _ = diff_state(
        root, ev["base_ref"], ignored_base, quest_events_scope([*events, ev]), peer_base=peer_base_of(events)
    )
    unsafe_maps = unsafe_map_links(root)
    if "<snapshot-unavailable>" in ev["changed_files"] and ev["verdict"] == "PASS":
        ev["verdict"] = "FAIL"
        ev["failure_sig"] = "snapshot-unavailable"
        ev["commands"] = [
            *ev.get("commands", []),
            {"cmd": "git write-tree (temporary index)", "exit_code": 1, "error": "snapshot unavailable"},
        ][-20:]
    elif not map_ok and ev["verdict"] == "PASS":
        ev["verdict"] = "FAIL"
        ev["failure_sig"] = "map-refresh-failed"
        ev["changed_files"] = sorted(set(ev["changed_files"]) | {".asgard/map"})
        ev["commands"] = [
            *ev.get("commands", []),
            {"cmd": "asgard map check", "exit_code": 1, "error": map_error},
        ][-20:]
    elif unsafe_maps and ev["verdict"] == "PASS":
        ev["verdict"] = "FAIL"
        ev["failure_sig"] = "unsafe-map-link"
        ev["changed_files"] = sorted(set(ev["changed_files"]) | set(unsafe_maps))
    ev.setdefault("level", "micro")
    if ev["verdict"] != "PASS":
        return
    # 하네스 소유 베이스라인 — normalize가 stdin baseline을 버린 뒤 여기서만 기록.
    # 무변경(diff EMPTY) 퀘스트는 red의 원인이 될 수 없다 — 전 트리 체크의 타 세션 잔여물 red가
    # 무변경 퀘스트를 인질로 잡지 않게 면제 (26-07-23 감사).
    ran: dict[str, dict] = {}
    if ev["diff_hash"] != EMPTY:
        bl = run_baseline(root, policy, events, ev["diff_hash"])
        if bl:
            ev["baseline"] = bl
            ran = baseline_ran(root, policy, bl)
    # criteria verify 계약 — 하네스가 계약 명령을 직접 실행해 기록 (stdin 위조는 normalize가 버림)
    crit = effective_criteria(events, ev.get("criteria"))
    cc = run_criteria_checks(root, policy, crit, events, ev["diff_hash"], ran)
    if cc is not None:
        ev["criteria_checks"] = cc
    # PASS 시점 트리 봉인 — stale 판정의 귀속 범위 대조 축 (stale_pass_scope). 짝 저장소도
    # 같이 봉인한다: 세션 뿌리만 적으면 PASS 뒤 짝 저장소 변조가 드리프트에 안 잡힌다.
    ev["tree_ref"] = current_tree_ref(root)
    ev["peer_tree"] = peer_current(root)
    ev["verification_id"] = verification_identity(ev)


def _cmd_amend_criteria(root: str, qid: str, events: list[dict], args) -> int:
    """amend-criteria — 결속 불가능해진 기준을 기록으로 남기며 고친다.

    개봉 기준은 개봉 시점에 고정되고, 그 뒤의 정당한 변경이 그 기준을 못 채우게 만들 수 있다:
    계약이 부른 시험 파일을 작업 도중의 개명이 없애면 그 계약은 영영 exit 0 을 못 낸다. 지금까지
    그 자리의 출구는 판정자 ESCALATE 나 `close --force` 둘이었고, 둘 다 무엇이 왜 옮겨졌는지를
    기장에 안 적는다 (26-08-20 `tutor-alter-1on1-260820` 이 이 자리에서 세 번 못 닫혔다).

    이 동사가 바꾸는 것은 "바를 옮길 수 있는가"가 아니라 "옮긴 자리가 보이는가"다. 원본 기준은
    개봉 이벤트에 그대로 남고 `acceptance_hash` 도 개봉 기준을 계속 묶으므로 수정은 새 이벤트로만
    설 수 있다. 판정자 주입면이 수정 사실과 사유를 함께 받는다 — 판정받는 쪽이 자기 바를 다시
    쓰는 것을 금지가 아니라 노출로 막는다.

    서 있는 판정은 이 동사가 물린다 (`summary.amend_after_verify`). PASS 뒤의 수정을 금지하면
    이 동사는 정작 필요한 자리에서 못 쓰인다 — 계약이 결속 불가능하다는 사실은 보통 판정자가
    PASS 를 적고 `close` 가 `criteria-unverified` 로 거부할 때 드러나기 때문이다. 그래서 막는
    대신 그 PASS 를 물리고 새 판정을 요구한다. 그 새 판정의 주입면이 수정 사실과 사유를 함께 적는다."""
    reason = " ".join(str(args.reason or "").split())
    if not args.criteria:
        return _error("amend-criteria requires at least one --criteria")
    if not reason:
        return _error(
            "amend-criteria requires --reason — an unexplained amendment is indistinguishable from lowering the bar"
        )
    if any(e.get("event") == "quest_closed" for e in events):
        return _error("quest is closed — its criteria are history, not a live contract")
    previous = effective_criteria(events)
    retired = next((e.get("verdict") for e in reversed(events) if e.get("event") == "verify"), None)
    ev = normalize(
        {"role": args.role or "worker", "event": "amend", "criteria": args.criteria, "subtask": reason},
        events,
        qid,
        args.session,
    )
    write_event(root, qid, ev)
    print(
        json.dumps(
            {
                "amended": qid,
                "turn": ev["turn"],
                "reason": reason,
                "criteria": ev["criteria"],
                "replaced": list(previous),
                # 물린 판정을 여기서 말하지 않으면 호출자는 close 가 왜 no-pass 로 거부하는지를
                # 다음 턴에 가서야 안다.
                "retired_verdict": retired,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_append(root: str, qid: str, events: list[dict], policy: dict, args) -> int:
    """append — 이벤트 1건 기록. verify는 이 도구가 물리 증거를 붙여 쓴다."""
    raw, code = _append_payload(args)
    if raw is None:
        return code
    rejection = _append_rejection(raw)
    if rejection:
        print(json.dumps({"error": rejection}), file=sys.stderr)
        return 2
    ev = normalize(raw, events, qid, args.session)
    if ev["event"] == "verify":
        if ev["verdict"] == "NA":
            print(json.dumps({"error": "verify requires --verdict PASS|FAIL|ESCALATE"}), file=sys.stderr)
            return 2
        _verify_evidence(root, policy, events, ev)
    write_event(root, qid, ev)
    print(
        json.dumps(
            {
                "appended": ev["event"],
                "turn": ev["turn"],
                "verdict": ev["verdict"],
                "diff_hash": ev["diff_hash"],
                "verification_id": ev.get("verification_id"),
                **_next_note(root, qid, [*events, ev], policy, args),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _baseline_observe(root: str, policy: dict, events: list[dict], ev: dict) -> dict:
    """게이트-우선 판정의 물리 관측 — 이벤트에 diff·실행 결과를 채우고 관측 요약을 돌려준다.

    `undecidable`은 판정을 낼 근거가 없다는 뜻이다(체크 없음/전부 skip). 그 자리는 FAIL이
    아니라 LLM Verifier로 넘어간다 — 증거 부재를 판정으로 바꾸면 게이트가 거짓말을 한다."""
    map_ok, map_error = refresh_managed_map(root)
    ignored_base = next(
        (event.get("ignored_snapshot") for event in events if isinstance(event.get("ignored_snapshot"), dict)), None
    )
    ev["diff_hash"], ev["changed_files"], _, _ = diff_state(
        root, ev["base_ref"], ignored_base, quest_events_scope([*events, ev]), peer_base=peer_base_of(events)
    )
    snapshot_ok = "<snapshot-unavailable>" not in ev["changed_files"]
    ev["level"] = "micro"
    # 무변경(diff EMPTY) 판정 — '변경 없음' 주장의 올바른 검증은 트리 관측 그 자체다
    # (pass_evidence의 no_change=inspection 원칙). 베이스라인은 돌리지 않는다: 무변경
    # 퀘스트는 red의 원인이 될 수 없고, 전 트리 체크의 타 세션 잔여물 red가 인질이 된다.
    no_change = ev["diff_hash"] == EMPTY and snapshot_ok
    obs = {"map_ok": map_ok, "map_error": map_error, "snapshot_ok": snapshot_ok, "no_change": no_change}
    if no_change:
        rc_obs, _obs = git(root, "status", "--porcelain")
        ev["commands"] = [{"cmd": "git status --porcelain", "exit_code": rc_obs}]
        return {**obs, "state": None, "results": ev["commands"], "observed_ok": rc_obs == 0}
    bl = run_baseline(root, policy, events, ev["diff_hash"]) or {}
    state = bl.get("state")
    if state not in ("green", "red") and map_ok:
        # 왜 근거가 없는지까지 들려보낸다. 체크가 timeout 으로 끊겨 여기 오는 경우와 체크가 아예
        # 없는 경우는 고칠 곳이 서로 다른데(baseline_timeout·명령 범위 vs baseline_checks),
        # 종전 메시지는 둘을 "all skipped" 한 마디로 뭉개 이 레인이 꺼져 있는 줄도 모르게 했다.
        stalled = [str(r.get("cmd")) for r in (bl.get("results") or []) if isinstance(r, dict) and r.get("timed_out")]
        return {**obs, "state": state, "results": [], "observed_ok": False, "undecidable": True, "stalled": stalled}
    results = [c for c in bl.get("results", []) if isinstance(c, dict)]
    ev["commands"] = results[:20]
    ev["baseline"] = bl
    return {**obs, "state": state, "results": results, "observed_ok": state == "green"}


def _baseline_failing(root: str, policy: dict, events: list[dict], ev: dict, obs: dict) -> list[str]:
    """무엇이 실패했는가 — 실패 서명은 이벤트에 적고 실패한 명령 목록을 돌려준다.

    순서가 계약이다: 앞의 이유가 뒤를 가린다(스냅샷 부재 > 지도 갱신 실패 > 베이스라인 red).
    맨 뒤 criteria 계약은 green이어도 FAIL로 뒤집을 수 있다 — 계약이 선언된 기준은 그 명령이
    유일한 증거이므로 무관한 exit-0으로 대체되지 않는다."""
    failing = [str(c.get("cmd")) for c in obs["results"] if c.get("exit_code") not in (0, None)]
    if not obs["snapshot_ok"]:
        ev["failure_sig"] = "snapshot-unavailable"
        return ["git write-tree (temporary index)"]
    if not obs["map_ok"]:
        ev["failure_sig"] = "map-refresh-failed"
        ev["changed_files"] = sorted(set(ev["changed_files"]) | {".asgard/map"})
        return [obs["map_error"] or "managed map refresh failed"]
    if obs["state"] == "red":
        ev["failure_sig"] = "baseline-red"
        return failing
    if obs["no_change"] and not obs["observed_ok"]:
        ev["failure_sig"] = "tree-observe-failed"
        return ["git status --porcelain"]
    if unsafe_map_links(root):
        ev["verdict"] = "FAIL"
        ev["failure_sig"] = "unsafe-map-link"
        return failing
    crit = effective_criteria(events)
    # 이 경로도 바로 위에서 baseline 을 돌렸다 — 계약이 같은 명령이면 같은 트리에서 두 번 돌 이유가
    # 없다. 종전에는 append 만 공유해서, 정작 LLM 없이 끝나는 싼 레인이 스위트를 두 번 물었다.
    cc = run_criteria_checks(
        root, policy, crit, events, ev["diff_hash"], baseline_ran(root, policy, ev.get("baseline"))
    )
    if cc is not None:
        ev["criteria_checks"] = cc
    unmet = unmet_contracts(root, crit, ev)
    if unmet:
        ev["verdict"] = "FAIL"
        ev["failure_sig"] = "criteria-contract"
        return [str(u) for u in unmet]
    return failing


def _cmd_verify_baseline(root: str, qid: str, events: list[dict], policy: dict, args) -> int:
    """verify-baseline — 하네스가 프로젝트 체크를 직접 실행해 판정을 기록한다 (게이트-우선).

    baseline은 모델이 고르는 축약 경로가 아니다. 현재 물리 diff와 같은 risk flags로 전이를 다시
    계산해 판정 자격을 확인한다 — sig_risk·큰 diff·민감 경로를 MAIN_WORKER가 micro PASS로
    자기강등하는 우회도 여기서 한 번에 막는다. commands는 하네스가 직접 실행한 체크이고
    (pass_evidence 충족), verifier 재량 커맨드가 아니다."""
    eligible = transition(summarize(root, qid, events, policy), policy, args, load_priors(root))
    if eligible["next_role"] != "BASELINE_VERIFY":
        print(
            json.dumps(
                {
                    "error": "not eligible for baseline verification — follow the role assigned by the "
                    "transition function",
                    "next_role": eligible["next_role"],
                    "why": eligible["why"],
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    ev = normalize({"role": "harness", "event": "verify"}, events, qid, args.session)
    obs = _baseline_observe(root, policy, events, ev)
    if obs.get("undecidable"):
        stalled = obs.get("stalled") or []
        if stalled:
            # 이 자리는 설정 결함이지 판정이 아니다 — 체크가 상한보다 느리면 이 레인은 영영 못 서고
            # 모든 쓰기 퀘스트가 LLM Verifier 로 넘어간다. 무엇을 고칠지 명령과 숫자로 말한다.
            return _error(
                "the baseline check did not finish inside baseline_timeout (%ds): %s — this leaves the "
                "deterministic lane permanently off, so every write quest escalates to the LLM Verifier. "
                "Narrow the command or raise trinity_policy.baseline_timeout."
                % (int(policy.get("baseline_timeout") or 120), ", ".join(stalled))
            )
        return _error("cannot render a baseline verdict (no checks/all skipped) — verify with the LLM Verifier")
    ev["verdict"] = "PASS" if obs["observed_ok"] and obs["map_ok"] and obs["snapshot_ok"] else "FAIL"
    failing = _baseline_failing(root, policy, events, ev, obs)
    if ev["verdict"] == "PASS":
        # PASS 시점 트리 봉인 — stale 판정의 귀속 범위 대조 축 (append 경로와 동일)
        ev["tree_ref"] = current_tree_ref(root)
        ev["peer_tree"] = peer_current(root)
        ev["verification_id"] = verification_identity(ev)
    write_event(root, qid, ev)
    fails = [str(f) for c in obs["results"] for f in (c.get("fails") or [])]  # run_baseline 채집 정형 실패 줄
    print(
        json.dumps(
            {
                "appended": "verify",
                "verdict": ev["verdict"],
                "baseline": obs["state"],
                "failing": failing[:5],
                "fails": fails[:5],
                "turn": ev["turn"],
                "diff_hash": ev["diff_hash"],
                "verification_id": ev.get("verification_id"),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_ticket(root: str, qid: str, args) -> int:
    """ticket-* — 티켓 런타임 전이. claim token 검증은 ticket_runtime이 진다."""
    if args.cmd != "ticket-recover" and args.unit is None:
        print(json.dumps({"error": "%s requires --unit" % args.cmd}), file=sys.stderr)
        return 2
    rc, payload = ticket_runtime(
        root,
        qid,
        args.cmd,
        unit=args.unit,
        session=args.session,
        worker=args.worker,
        claim_token=args.claim_token,
        lease_seconds=args.lease_seconds,
        max_attempts=args.max_attempts,
        status=args.status,
        error=args.error,
        older_than=args.older_than,
    )
    print(json.dumps(payload, ensure_ascii=False), file=sys.stdout if rc == 0 else sys.stderr)
    return rc


def _close_event(events: list[dict], qid: str, args, decision: str, code: str, forced: bool) -> dict:
    """종료 이벤트 — 어떤 판정으로 닫혔는지와 그 근거가 된 PASS를 같이 적는다."""
    return normalize(
        {
            "role": "odin",
            "event": "quest_closed",
            "risk": {"forced": forced, "decision": decision, "code": code},
            "verification_id": next(
                (
                    event.get("verification_id")
                    for event in reversed(events)
                    if event.get("event") == "verify" and event.get("verdict") == "PASS"
                ),
                None,
            ),
        },
        events,
        qid,
        args.session,
    )


def _close_map_state(root: str, base_ref) -> tuple[bool, list[str]]:
    """지도 최신 여부와 수동 갱신 안내 — 자동 갱신이 실패했을 때만 안내가 붙는다."""
    try:
        from asgard.code_map import check_map

        current = check_map(root).ok if os.path.isdir(os.path.join(root, ".asgard", "map")) else False
        return current, map_nudge(root, base_ref)
    except Exception:
        return False, []


def _close_verdict(
    root: str, qid: str, events: list[dict], policy: dict, args
) -> tuple[dict, str, str, str, bool] | None:
    """close 직전의 최신 판정 — (요약, decision, code, why, forced). None이면 닫지 않는다.

    lock 안에서 다시 재는 이유: append가 PASS 스냅샷 뒤에 끼어드는 stale-close를 허용하지 않는다."""
    s = summarize(root, qid, events, policy)
    s["tests_available"] = tests_available(root)
    decision, code, why = completion_decision(s)
    ok = decision in ("APPROVED", "ESCALATED")
    if not ok and not args.force:
        print(
            json.dumps(
                {
                    "error": "close rejected (%s: %s) — only after a verified PASS (+hash match) or "
                    "ESCALATE. Bypass with --force (requires Odin's consent — LAST not recorded, "
                    "no gate exemption)" % (code, why)
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return None
    return s, decision, code, why, bool(args.force and not ok)


def _cmd_close(root: str, qid: str, policy: dict, args) -> int:
    """close — 판정·종료 이벤트·ACTIVE 포인터 해제를 같은 Quest lock 안에 묶는다."""
    with quest_lock(root, qid):
        events = load_events(root, qid)
        verdict = _close_verdict(root, qid, events, policy, args)
        if verdict is None:
            return 1
        s, decision, code, why, forced = verdict
        write_event_unlocked(root, qid, _close_event(events, qid, args, decision, code, forced), events)
        # LAST is a verified-state capability, not merely a termination receipt.
        # ESCALATE may end the active loop, but its writes remain unverified.
        if decision == "APPROVED" and not forced:
            try:
                write_pointer(session_pointer(root, args.session, "last"), qid)
                write_pointer(os.path.join(quest_dir(root), "LAST"), qid)
            except Exception as exc:
                return _error(f"close LAST pointer publication failed: {exc}")
        clear_active_quest(root, args.session, qid)
    try:
        pruned = prune_quests(root, policy)
    except Exception:
        pruned = []  # 정리는 부가 기능 — close 성공을 막지 않는다
    res = {"closed": qid, "forced": forced}
    if pruned:
        res["pruned"] = len(pruned)
    if forced or decision != "APPROVED":
        res["gate_exempt"] = False
    if forced:
        res["rejected"] = "%s: %s" % (code, why)
    map_current, nudge = _close_map_state(root, s.get("base_ref"))
    if map_current:
        res["map_current"] = True
    elif nudge:
        res["map_update"] = nudge
        res["map_hint"] = (
            "automatic map refresh failed — run asgard map update, then fold only new knowledge into "
            "the area map incrementally"
        )
    print(json.dumps(res, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None, root: str | None = None) -> int:
    """CLI 진입점 ①, 그리고 같은 인터프리터 안에서 부르는 라이브러리 진입점 ②.

    두 인자 모두 ②를 위해 있다. `argv`가 없으면 `sys.argv`를 읽고 `root`가 없으면 `repo_root()`가
    git 을 한 번 더 띄운다 — 프로세스로 부를 때는 그 두 값을 달리 얻을 방법이 없기 때문이다. 이미
    저장소 위치를 아는 호출부는 넘겨서 둘 다 건너뛴다."""
    args = _parser().parse_args(argv)
    root = root or repo_root()
    policy = load_policy(root)

    if args.cmd == "open":
        return _cmd_open(root, args)
    if args.cmd == "attach":
        return _cmd_attach(root, args)

    qid = sanitize(args.quest_id) if args.quest_id else active_quest(root, args.session)
    if not qid:
        print(
            json.dumps(
                {
                    "error": "no active quest — run: quest-log open <quest-id>, "
                    "or quest-log attach <quest-id> if this session lost its pointer"
                }
            )
        )
        return 1
    events = load_events(root, qid)
    if not events:
        return _error("quest ledger is missing or unreadable")
    ledger_ok, ledger_detail = ledger_integrity(events)
    if not ledger_ok:
        return _error("quest ledger integrity failure", detail=ledger_detail)

    if args.cmd == "replay":
        print(json.dumps({**replay_ledger(events), "ledger": ledger_detail}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd.startswith("ticket-"):
        return _cmd_ticket(root, qid, args)
    if args.cmd == "append":
        return _cmd_append(root, qid, events, policy, args)
    if args.cmd == "verify-baseline":
        return _cmd_verify_baseline(root, qid, events, policy, args)
    if args.cmd == "amend-criteria":
        return _cmd_amend_criteria(root, qid, events, args)

    s = summarize(root, qid, events, policy)
    s["tests_available"] = tests_available(root)
    s["ledger"] = ledger_detail
    if args.cmd == "state":
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "next":
        print(json.dumps(transition(s, policy, args, load_priors(root)), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "close":
        return _cmd_close(root, qid, policy, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
