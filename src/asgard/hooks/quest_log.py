#!/usr/bin/env python3
# Asgard quest-log — Trinity 퀘스트 로그 + 전이 함수 CLI (CUS-118 / CUS-120).
#
# 코디네이터(Heimdall)의 "관찰·기록·배정" 프리미티브. 훅이 아니라 에이전트가 직접 부르는 도구다:
#   open   <quest-id>  과업 로그 시작 (base_ref = 현재 HEAD 고정, ACTIVE 포인터 갱신)
#   append             이벤트 1건 기록 (stdin JSON + 플래그) — verify 는 diff_hash 자동 계산
#   state              로그 요약 관찰 (코디네이터의 state observation)
#   next               전이 함수: 로그 상태 + risk_features → next_role (결정 테이블)
#   close              완료된 quest 의 ACTIVE 해제 (PASS+hash 일치 또는 ESCALATE 만)
#
# 왜 CLI 인가: TRINITY 의 "<20K 파라미터 코디네이터"의 하니스 등가물은 학습 모델이 아니라 결정론적
# 구조다 — 배정(next)을 LLM 임의 판단이 아닌 코드가 내리게 해서 조율을 프롬프트가 아닌 구조로
# 옮긴다 (TRINITY-inspired 적응, CUS-117 코멘트 C 합의).
# 왜 O_APPEND 단일 write 인가: 위협 모델이 악의적 변조가 아니라 LLM 자기기만이라 lock/해시체인은
# 과잉 (Codex 합의 — v1 탈락). 한 줄 원자 append 면 충분하다.
# 완료 위조 방어는 이 파일 몫이 아니다 — verifier-gate.py 가 Stop 시점에 working-tree diff hash 를
# 재계산해 물리 대조한다. 로그에 뭘 쓰든 워킹트리는 위조할 수 없다 (Goodhart 방어, CUS-122).
# diff_hash 를 여기(append)서도 계산하는 이유: verifier 가 손으로 만든 해시는 gate 재계산과 어긋날
# 수 있다 — 같은 알고리즘(아래 diff_state, verifier-gate.py 와 동일 유지)이 유일한 출처여야 한다.
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

SCHEMA = 1
EMPTY = hashlib.sha256(b"").hexdigest()  # 변경 전무(diff 없음 + untracked 없음)의 정준 해시
EVENTS = {
    "plan",
    "work",
    "verify",
    "fail",
    "escalate",
    "delegate",
}  # delegate: 중첩 디스패치 배정 기록 (CUS-142) — Phase 2 통계가 배정 정책 학습
VERDICTS = {"PASS", "FAIL", "ESCALATE", "NA"}
# 로그 v1 = 16필드 고정 (CUS-118, CUS-117 코멘트 A). tier/effort/model 등은 v1 소비자 없음 → Phase 2.
FIELDS = [
    "schema",
    "quest_id",
    "session_id",
    "turn",
    "ts",
    "role",
    "event",
    "base_ref",
    "risk",
    "criteria",
    "changed_files",
    "diff_hash",
    "commands",
    "verdict",
    "failure_sig",
    "failure_count",
]

# 정책 파일이 없어도 동작해야 하므로(fail-open) 기본값을 내장 — .asgard/trinity-policy.json 이 덮는다.
DEFAULT_POLICY = {
    "schema": 1,
    "roles": {
        "thinker": {"tier": "high", "effort": "high"},
        "worker": {"tier": "standard", "effort": "medium"},
        "verifier": {"tier": "high", "effort": "high"},
    },
    # 소비자는 Heimdall(_delivery_model/_model_for) — 여기 두는 이유는 템플릿과 기본값 거울 유지.
    "delivery": {"freyja": "standard", "thor": "standard", "loki": "fast"},
    "budget_priors": {"trivial": {"turns": 1}, "standard": {"turns": 6}, "deep": {"turns": 12}},
    "small_write": {"max_files": 2, "max_lines": 80},
    "sensitive_paths": [
        "hooks",
        "policy",
        "templates",
        "install",
        "security",
        "auth",
        "secret",
        "db",
        "migration",
        "ci",
        ".github",
        ".claude",
        ".cursor",
        ".codex",
    ],
    "readonly_commands": [
        "git status",
        "git diff",
        "git log",
        "git show",
        "git ls-files",
        "git rev-parse",
        "rg",
        "grep",
        "ls",
        "cat",
        "head",
        "tail",
        "find",
        "wc",
        "pwd",
        "which",
    ],
    "failure_threshold": 3,
    # 하네스 소유 베이스라인 체크 (CUS-187) — 비면 보수적 자동 감지 (pytest 만)
    "baseline_checks": [],
    "baseline_timeout": 120,
}


def repo_root() -> str:
    r = os.environ.get("CLAUDE_PROJECT_DIR")
    if r:
        return r
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return os.getcwd()


def quest_dir(root: str) -> str:
    """.asgard/quest/ — 툴 중립 공유 상태 (failure-tracker 와 같은 크로스툴 원칙). .gitignore 자가 설치."""
    d = os.path.join(root, ".asgard")
    os.makedirs(os.path.join(d, "quest"), exist_ok=True)
    gi = os.path.join(d, ".gitignore")
    if not os.path.exists(gi):
        try:
            open(gi, "w").write("*\n")
        except Exception:
            pass
    return os.path.join(d, "quest")


def git(root: str, *args: str, binary: bool = False):
    """(rc, out). 실패는 (rc!=0, '') 로 — 호출측이 fail-open 판단."""
    try:
        p = subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=60)
        out = p.stdout if binary else p.stdout.decode("utf-8", "replace")
        return p.returncode, out
    except Exception:
        return 1, b"" if binary else ""


# ── 물리 증거 해시 — verifier-gate.py 의 diff_state 와 알고리즘 동일 유지 (단일 출처 원칙) ──
# 검증 실행 아티팩트 — 검증 명령이 만든 캐시가 PASS 를 stale 로 만들면 게이트가 자기파괴적이다
# (.gitignore 없는 프로젝트에서 pytest 실행 → __pycache__ → hash 변경, s1 라이브 실측).
# ponytail: 고정 목록 — 정책 파일로 빼면 exclude 확대가 게이트 우회 벡터가 되므로 하드코딩 유지.
_JUNK_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox", "node_modules", ".venv"}


def _junk(p: str) -> bool:
    return p.endswith((".pyc", ".pyo")) or any(seg in _JUNK_DIRS for seg in p.split("/"))


def sensitive_path(path: str, needles) -> bool:
    """경로 세그먼트 기준 민감 매칭 — 나이브 substring 은 'ci' 가 circle.py 를 오탐 (CUS-184).
    규칙: 세그먼트 정확 일치, 또는 4자+ needle 은 세그먼트 내 부분 문자열 허용 (auth→authentication).
    verifier_gate.py 의 sensitive_path 와 동일 유지 (단일 출처 원칙 — 어긋나면 게이트↔전이 판정 분열)."""
    segs = path.lower().split("/")
    for n in needles:
        n = str(n).lower()
        if any(seg == n or (len(n) >= 4 and n in seg) for seg in segs):
            return True
    return False


def diff_state(root: str, base_ref: str | None) -> tuple[str, list[str], int, int]:
    """(diff_hash, changed_files, changed_lines, nontest_lines) — base_ref 트리 ↔ 현재 워킹트리 전체.
    커밋 여부와 무관 (base_ref 는 open 시점 고정 커밋). `.asgard/**` 제외 — 로그 기록 자체가
    diff 를 바꾸면 해시가 자기참조로 영원히 안 맞는다.
    nontest_lines: 테스트 파일 제외 변경 라인 — 테스트 추가는 검증 표면이지 리스크 질량이 아니다
    (CUS-189 스모크 발견: 잠금 테스트 2파일 추가가 big 판정 → 게이트-우선 무력화). 삭제된 테스트는
    별도 하드 트리거 (deleted_tests)."""
    if not base_ref or base_ref == "NONE":
        return EMPTY, [], 0, 0
    spec = [base_ref, "--", ".", ":(exclude).asgard"]
    rc, diff = git(root, "diff", "--binary", *spec, binary=True)
    if rc != 0:
        return EMPTY, [], 0, 0
    _, names = git(root, "diff", "--name-only", *spec)
    _, unt = git(root, "ls-files", "--others", "--exclude-standard", "--", ".", ":(exclude).asgard")
    _, num = git(root, "diff", "--numstat", *spec)
    lines = 0
    nt_lines = 0
    for row in num.splitlines():
        parts = row.split("\t")
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
            n = int(parts[0]) + int(parts[1])
            lines += n
            if not _testfile(parts[2]):
                nt_lines += n
    untracked = sorted(p for p in unt.splitlines() if p.strip() and not _junk(p))
    h = hashlib.sha256(diff)
    for p in untracked:
        try:
            body = open(os.path.join(root, p), "rb").read()
            k = body.count(b"\n") + 1
            lines += k
            if not _testfile(p):
                nt_lines += k
            h.update(p.encode() + b"\0" + hashlib.sha256(body).digest())
        except Exception:
            h.update(p.encode() + b"\0missing")
    changed = sorted(set(n for n in names.splitlines() if n.strip()) | set(untracked))
    return (h.hexdigest() if changed else EMPTY), changed, lines, nt_lines


# ── 하네스 소유 베이스라인 체크 (CUS-187) — 증거 '품질'의 결정론화 ──
# 기존 pass_evidence 는 증거 '존재'만 봤다 — 어떤 명령이었는지는 verifier LLM 재량이라 `echo ok`
# 도 증거가 됐다 (깊이벤치 실증). 여기서는 하네스가 직접 프로젝트 체크를 실행해 exit code 를
# 기록한다 — LLM-as-judge 불신 원칙 (결정론 룰 피드백이 최상위 증거, Anthropic SDK 가이드).
# stdin 으로 들어온 baseline 은 normalize 가 버린다 — 이 코드만이 유일한 기록 경로 (위조 차단).


def detect_checks(root: str, policy: dict) -> list[str]:
    """정책 baseline_checks 우선. 없으면 보수적 자동 감지 — pytest 만.
    ponytail: lint 류 자동 감지 안함 — 기존 위반 false-red 가 게이트 인질이 된다. 명시 설정으로만."""
    cfg = policy.get("baseline_checks")
    if cfg:
        return [str(c) for c in cfg]
    import shutil

    if shutil.which("pytest") and any(
        os.path.exists(os.path.join(root, p)) for p in ("tests", "test", "pytest.ini", "pyproject.toml")
    ):
        return ["pytest -x -q"]
    return []


def run_baseline(root: str, policy: dict, events: list[dict], diff_hash: str) -> dict | None:
    """체크 전부 실행 → {"state": green|red|none, "results": [...]}. 체크 없음 → None (요건 면제).
    같은 diff_hash 의 기존 verify 기록은 재사용 — 동일 트리에 pytest 를 두 번 돌리지 않는다.
    skip(127 미설치·pytest 5 수집 없음·timeout)은 red 아님 — 게이트는 자기기만 방어지 인질극 장치가
    아니다 (verifier_gate.py 서두와 같은 원칙). ponytail: timeout=skip 은 보호 약화 — 느린 스위트는
    baseline_timeout 상향으로 대응."""
    checks = detect_checks(root, policy)
    if not checks:
        return None
    for e in reversed(events):
        bl = e.get("baseline")
        if bl and e.get("event") == "verify" and e.get("diff_hash") == diff_hash:
            return {**bl, "cached": True}
    timeout = int(policy.get("baseline_timeout") or 120)
    auto = not policy.get("baseline_checks")  # 자동 감지 모드 — red 판정을 보수적으로 (아래)
    results: list[dict] = []
    state = "none"
    for cmd in checks[:10]:
        t0 = time.time()
        code: int | None
        try:
            p = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, timeout=timeout)
            code = p.returncode
        except Exception:
            code = None  # timeout 포함 — skip 취급 (fail-open)
        results.append({"cmd": cmd[:120], "exit_code": code, "secs": round(time.time() - t0, 1)})
        # skip = 체크가 "돌 수 없었다": 127 미설치 · pytest 5 수집 없음 · timeout. 자동 감지 pytest 는
        # 2/3/4(수집·사용법 오류 — venv 밖 pytest 가 흔한 원인)도 skip — 환경 문제를 코드 red 로
        # 오판해 게이트가 인질 잡는 것 방지. 명시 설정 체크는 사용자가 커맨드를 보증하므로 엄격 판정.
        if code is None or code == 127 or ("pytest" in cmd.split() and (code == 5 or (auto and code in (2, 3, 4)))):
            continue
        if code != 0:
            state = "red"
            break  # 첫 red 에서 중단 — 나머지는 수리 후 어차피 재실행
        state = "green"
    return {"state": state, "results": results}


def _testfile(p: str) -> bool:
    segs = p.lower().split("/")
    return "tests" in segs or "test" in segs or segs[-1].startswith("test_") or segs[-1].endswith("_test.py")


def deleted_tests(root: str, base_ref: str | None) -> list[str]:
    """base_ref 이후 삭제된 테스트 파일 — 테스트를 지워 green 을 사는 경로 차단 (anti-Goodhart,
    Anthropic feature-ledger "removing tests is unacceptable" analog). 삭제만 본다 — 테스트 수정은
    정상 작업이라 전부 full 로 올리면 세금이 되레 는다. verifier_gate.py 와 동일 유지 (단일 출처 원칙)."""
    if not base_ref or base_ref == "NONE":
        return []
    _, out = git(root, "diff", "--name-only", "--diff-filter=D", base_ref, "--", ".", ":(exclude).asgard")
    return [p for p in out.splitlines() if p.strip() and _testfile(p)]


_SIG_PAT = re.compile(r"^-\s*(def |class |function |export |public |fn )")


def signature_risk(root: str, base_ref: str | None) -> bool:
    """diff 에 삭제·변경된 함수/클래스 시그니처 라인 존재 여부 — 숨은-caller 리스크의 결정론 신호
    (CUS-188, t3 방어 유지 조건). '-' 라인만 본다: 신규 추가(+def)는 기존 caller 가 없다.
    게이트-우선(STANDARD) 라우팅 전용 — verifier_gate 대응 불필요."""
    if not base_ref or base_ref == "NONE":
        return False
    rc, out = git(root, "diff", "-U0", base_ref, "--", ".", ":(exclude).asgard")
    if rc != 0:
        return False
    return any(_SIG_PAT.match(line) for line in out.splitlines())


def load_policy(root: str) -> dict:
    p = dict(DEFAULT_POLICY)
    try:
        p.update(json.load(open(os.path.join(root, ".asgard", "trinity-policy.json"))))
    except Exception:
        pass  # 정책 파일 없음/깨짐 → 내장 기본값 (fail-open)
    return p


def active_quest(root: str) -> str | None:
    try:
        qid = open(os.path.join(root, ".asgard", "quest", "ACTIVE")).read().strip()
        return qid or None
    except Exception:
        return None


def load_events(root: str, qid: str) -> list[dict]:
    path = os.path.join(root, ".asgard", "quest", qid + ".jsonl")
    events = []
    try:
        for line in open(path, encoding="utf-8"):
            try:
                events.append(json.loads(line))
            except Exception:
                continue  # 깨진 한 줄이 로그 전체를 죽이면 안 된다
    except Exception:
        pass
    return events


def write_event(root: str, qid: str, ev: dict) -> None:
    """O_APPEND + 단일 os.write — JSONL 한 줄이 원자 단위. lock 없음 (Codex 합의)."""
    path = os.path.join(quest_dir(root), qid + ".jsonl")
    line = (json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(path, os.O_APPEND | os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def normalize(ev: dict, events: list[dict], qid: str, session: str) -> dict:
    """16필드 고정 스키마로 정규화 — 빠진 필드는 중립값, 모르는 필드는 버린다 (v1 계약 고정)."""
    base_ref = next((e.get("base_ref") for e in events if e.get("base_ref")), None)
    full = {
        "schema": SCHEMA,
        "quest_id": qid,
        "session_id": session,
        "turn": len(events) + 1,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "role": ev.get("role") or "worker",
        "event": ev.get("event") or "work",
        "base_ref": ev.get("base_ref") or base_ref,
        "risk": ev.get("risk") or {},
        "criteria": ev.get("criteria") or [],
        "changed_files": ev.get("changed_files") or [],
        "diff_hash": ev.get("diff_hash"),
        "commands": ev.get("commands") or [],
        "verdict": ev.get("verdict") or "NA",
        "failure_sig": ev.get("failure_sig"),
        "failure_count": int(ev.get("failure_count") or 0),
    }
    if ev.get("level"):  # verify 전용 부가 필드 — gate 의 full-verify 판정 근거
        full["level"] = ev["level"]
    if ev.get("unit") is not None:  # work 전용 부가 필드 — wave 병렬 배정 단위 id (CUS-176)
        full["unit"] = ev["unit"]
    if ev.get("model"):  # 실사용 provider:model 기록 (CUS-177) — CUS-127 결과 기반 정책 조정의 데이터 축
        full["model"] = str(ev["model"])[:80]
    return full


def summarize(root: str, qid: str, events: list[dict], policy: dict) -> dict:
    """코디네이터 관찰용 요약 — next 의 입력이기도 하다."""
    base_ref = next((e.get("base_ref") for e in events if e.get("base_ref")), None)
    cur, changed, lines, nt_lines = diff_state(root, base_ref)
    verifies = [e for e in events if e.get("event") == "verify"]
    passes = [e for e in verifies if e.get("verdict") == "PASS"]
    last_pass = passes[-1] if passes else None
    # verdict 신선도 — 마지막 verify "이후" work 가 있으면 판정은 낡았다(재검증 대기).
    # sticky FAIL 이 WORKER_RETRY 를 무한 재발화시키는 루프 방지 (재검증 없이 재시도 반복).
    last_verify_i = max((i for i, e in enumerate(events) if e.get("event") == "verify"), default=-1)
    work_after_verify = any(e.get("event") == "work" for e in events[last_verify_i + 1 :]) if verifies else False
    # 동종 실패 스트릭 — 같은 failure_sig 의 연속 FAIL 을 결정론 계산 (3-strike, Canon 9).
    # 네이티브 루프는 failure_count 를 이벤트에 안 싣는다 — 퀘스트 로그에서 직접 센다.
    # 마지막 plan(재계획) "이후"의 FAIL 만 센다 — 재계획이 3-strike 의 응답이므로 스트릭 리셋.
    # 안 리셋하면 REPLAN → 여전히 count≥3 → REPLAN 무한 루프 (라이브 재현됨).
    last_plan_i = max((i for i, e in enumerate(events) if e.get("event") == "plan"), default=-1)
    fail_streak, fail_streak_any, sig = 0, 0, None
    for i in range(len(events) - 1, last_plan_i, -1):
        e = events[i]
        if e.get("event") != "verify":
            continue
        if e.get("verdict") != "FAIL":
            break
        fail_streak_any += 1  # sig 무관 연속 FAIL — 자유 텍스트 sig 가 매번 달라도 도돌이표는 탈출해야 한다
        if sig is None:
            sig = e.get("failure_sig")
        if sig and e.get("failure_sig") == sig:
            fail_streak += 1
    sens = [f for f in changed if sensitive_path(f, policy["sensitive_paths"])]
    dts = deleted_tests(root, base_ref)
    # small_write 판정은 테스트 파일 제외 — 테스트 추가는 검증 표면이지 리스크 질량이 아니다
    # (CUS-189: 잠금 테스트 2파일 추가 → big 오판 → full 강제·게이트-우선 무력화). 삭제는 dts 가 잡는다.
    nt_files = [f for f in changed if not _testfile(f)]
    small = policy["small_write"]
    return {
        "quest_id": qid,
        "base_ref": base_ref,
        "turns": len(events),
        "last_event": events[-1].get("event") if events else None,
        "last_verdict": None if work_after_verify else (verifies[-1].get("verdict") if verifies else None),
        "failure_count": max([int(e.get("failure_count") or 0) for e in events] + [fail_streak]),
        "fail_streak_any": fail_streak_any,
        "criteria": next((e.get("criteria") for e in events if e.get("criteria")), []),
        "risk_write": any((e.get("risk") or {}).get("has_write") for e in events),
        "plan_turns": sum(1 for e in events if e.get("event") == "plan"),
        "diff_hash": cur,
        "changed_files": changed,
        "diff_lines": lines,
        "sensitive_files": sens,
        "deleted_tests": dts,
        "nontest_files": len(nt_files),
        "nontest_lines": nt_lines,
        # gate 의 full_required 판정과 동일 기준 — 전이(DONE)와 close 가 gate 와 어긋나면 안 된다.
        "full_required": bool(sens) or bool(dts) or len(nt_files) > small["max_files"] or nt_lines > small["max_lines"],
        "pass_hash_match": bool(last_pass and last_pass.get("diff_hash") == cur),
        "pass_level": (last_pass or {}).get("level"),
        # PASS 의 성공 명령 증거 — 게이트와 동일 기준 (없으면 전이·close 가 거부, CUS-170 깊이 테스트 발견 구멍)
        "pass_evidence": bool(
            last_pass
            and any(isinstance(c, dict) and c.get("exit_code") == 0 for c in (last_pass.get("commands") or []))
        ),
        # 하네스 베이스라인 상태 (CUS-187) — 기록 없음(구 로그·체크 미설정) = none = 요건 면제 (fail-open)
        "baseline_state": ((last_pass or {}).get("baseline") or {}).get("state") or "none",
        # 게이트-우선 라우팅 신호 (CUS-188)
        "checks_available": bool(detect_checks(root, policy)),
        "sig_risk": signature_risk(root, base_ref),
    }


# ── 전이 함수 (CUS-120) — 결정 테이블은 코드가 유일한 출처, 임계값만 정책에서 온다 ──
def transition(s: dict, policy: dict, flags) -> dict:
    small = policy["small_write"]
    # big 은 non-test 질량 기준 (summarize.full_required 와 동일) — 테스트 추가로 full/승격을 트리거하지 않는다
    big = (
        s.get("nontest_files", len(s["changed_files"])) > small["max_files"]
        or s.get("nontest_lines", s["diff_lines"]) > small["max_lines"]
    )
    sensitive = bool(s["sensitive_files"]) or flags.shared
    full_required = s["full_required"] or flags.shared
    has_write = s["diff_hash"] != EMPTY or s["risk_write"] or flags.write_expected
    # risk_features 11종 (CUS-117 코멘트 C) — 결정론 계산 7 + 모델 신고 4 (--flags)
    features = {
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
    }
    level = "full" if (sensitive or big) else "micro"
    # 게이트-우선(STANDARD) 적격 (CUS-188) — 조건 하나라도 깨지면 아래 트리니티 행으로 자연 폴스루
    # = Trinity 승격. 민감/큰 diff/시그니처 변경/테스트 삭제는 LLM Verifier(caller-grep 계약)가 필요.
    standard_ok = (
        getattr(flags, "standard", False)
        and not sensitive
        and not big
        and not s.get("deleted_tests")
        and not s.get("sig_risk")
    )

    def out(role, why):
        return {"next_role": role, "verify_level": level, "why": why, "features": features}

    if flags.destructive:
        return out("ESCALATE_ODIN", "destructive_intent — Canon 3, Odin 명시 동의 필요")
    if s["failure_count"] >= policy["failure_threshold"]:
        return out("THINKER_REPLAN", "동종 %d-실패 — Worker 재시도 금지 (Canon 9)" % s["failure_count"])
    if s.get("fail_streak_any", 0) > policy["failure_threshold"]:
        # 이종-sig 백스톱 — 자유 텍스트 sig 가 매번 달라 동종 판정이 안 잡혀도, 재계획 없이
        # FAIL 이 threshold+1 연속이면 접근 자체가 틀렸다고 본다 (턴 예산 소진 전 탈출).
        return out("THINKER_REPLAN", "연속 %d-실패(이종 포함) — 접근 재설계" % s["fail_streak_any"])
    if s["last_verdict"] == "ESCALATE":
        # Verifier ESCALATE = 진행 불가 블로커 신고 (Canon 8: 승인 요청 용도 아님) — WORKER 폴스루로
        # 예산을 태우지 않고 즉시 Odin 에스컬레이션. 게이트/close 의 ESCALATE 수용과 대칭 (CUS-171).
        return out("ESCALATE_ODIN", "Verifier ESCALATE — 진행 불가 블로커, Odin 결정 필요")
    if s["last_verdict"] == "FAIL":
        if standard_ok and s.get("fail_streak_any", 0) >= 2:
            # 게이트-우선에서 red 2회 = 싼 게이트로 못 넘는 벽 — threshold(3) 전에 선제 승격 (CUS-188)
            return out("THINKER_REPLAN", "게이트-우선 red 2회 — Trinity 승격, 접근 재설계")
        return (
            out("THINKER_REPLAN", "Verifier FAIL(구조적) — 접근 재설계")
            if flags.structural
            else out("WORKER_RETRY", "Verifier FAIL(경미) — 같은 계획으로 수정")
        )
    if s["last_verdict"] == "PASS":
        if not s.get("pass_evidence"):
            # 증거 없는 PASS 는 판정이 아니다 — 게이트가 어차피 차단하므로 전이가 먼저 재검증을 보낸다
            # (판정 불일치 금지). close 우회 구멍의 전이측 봉합 (CUS-170 깊이 테스트 발견).
            return out("VERIFIER", "PASS 에 성공한 검증 명령 증거 없음 — 명령을 직접 실행해 재판정 (Canon 10)")
        if s.get("baseline_state") == "red":
            # 하네스가 직접 돌린 프로젝트 체크가 실패 — 판정이 아니라 코드가 깨져 있다 (CUS-187)
            return out("WORKER_RETRY", "하네스 베이스라인 체크 red — 실패한 체크를 먼저 수리 (Canon 10)")
        if not s["pass_hash_match"]:
            return out("VERIFIER", "PASS 이후 워킹트리 변경(stale PASS) — 재검증 필요")
        if full_required and s["pass_level"] != "full":
            # gate 와 동일 판정 — micro PASS 로 DONE 을 내면 Stop 에서 차단당한다 (판정 불일치 금지)
            return out("VERIFIER", "PASS 가 micro — 민감 경로/큰 diff 는 full-verify 필요")
        return out("DONE", "Verifier PASS + diff-hash 물리 대조 일치")
    if ((flags.ambiguous and has_write) or flags.external_research) and s["plan_turns"] < 2:
        # plan_turns 게이트 — 플래그는 매 전이마다 재전달(sticky)되므로, 실제 Thinker 계획(턴2)
        # 이후엔 실행으로 넘어가야 한다. 안 그러면 THINKER 무한 루프(12턴 소진).
        return out("THINKER", "모호한 범위의 write 또는 외부 조사 — 전략 선행")
    if not has_write:
        return out("DIRECT_DONE", "write 없음 — 게이트 면제 경로")
    if s["last_event"] == "work":
        if standard_ok and s.get("checks_available"):
            # 게이트-우선 — 검증이 싸면 always-verify 가 지배 (arXiv 2606.24453): LLM Verifier 대신
            # 하네스 베이스라인이 판정한다. 체크가 없으면 LLM Verifier 폴백 (아래).
            return out("BASELINE_VERIFY", "게이트-우선 — 하네스 베이스라인 판정 (CUS-188)")
        return out("VERIFIER", "Worker 완료 — %s-verify 판정 차례" % level)
    if (sensitive or big) and s["plan_turns"] < 2:
        # open 의 자동 plan(턴1)은 접수 기록일 뿐 — 민감/큰 write 는 실제 Thinker 계획 턴을 요구한다.
        return out("THINKER", "sensitive/big write — Thinker 계획 선행 (full-verify 경로)")
    return out("WORKER", "배정 단위 실행 차례")


def tests_available(root: str) -> bool:
    return any(
        os.path.exists(os.path.join(root, p)) for p in ("test", "tests", "pytest.ini", "pyproject.toml", "package.json")
    )


def sanitize(qid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", qid)[:80]


def main() -> int:
    ap = argparse.ArgumentParser(prog="quest-log", description="Asgard Trinity quest log")
    ap.add_argument("cmd", choices=["open", "append", "state", "next", "close", "verify-baseline"])
    ap.add_argument("quest_id", nargs="?")
    ap.add_argument("--criteria", action="append", default=[])
    ap.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID", "-"))
    ap.add_argument("--role"), ap.add_argument("--event"), ap.add_argument("--verdict")
    ap.add_argument("--level", choices=["micro", "full"])
    ap.add_argument("--no-write", action="store_true", help="open: write 없는 과업으로 표시")
    # 모델 신고 risk_features (결정론 계산이 불가능한 4종) — next 전용
    ap.add_argument("--ambiguous", action="store_true")
    ap.add_argument("--destructive", action="store_true")
    ap.add_argument("--external-research", action="store_true")
    ap.add_argument("--shared", action="store_true")
    ap.add_argument("--structural", action="store_true", help="next: 직전 FAIL 이 구조적임을 신고")
    ap.add_argument("--write-expected", action="store_true", help="next: 아직 diff 없지만 write 예정")
    ap.add_argument("--standard", action="store_true", help="next: 게이트-우선 경로 (CUS-188) — 비민감 소형 write")
    ap.add_argument("--force", action="store_true", help="close: 판정 없이 강제 해제 (Odin 동의 필요)")
    args = ap.parse_args()
    root = repo_root()
    policy = load_policy(root)

    if args.cmd == "open":
        if not args.quest_id:
            print("usage: quest-log open <quest-id> [--criteria ...]", file=sys.stderr)
            return 2
        qid = sanitize(args.quest_id)
        rc, head = git(root, "rev-parse", "HEAD")
        base_ref = head.strip() if rc == 0 else "NONE"
        ev = normalize(
            {
                "role": "thinker",
                "event": "plan",
                "base_ref": base_ref,
                "risk": {"has_write": not args.no_write},
                "criteria": args.criteria,
            },
            load_events(root, qid),
            qid,
            args.session,
        )
        write_event(root, qid, ev)
        open(os.path.join(quest_dir(root), "ACTIVE"), "w").write(qid + "\n")
        print(json.dumps({"opened": qid, "base_ref": base_ref, "turn": ev["turn"]}, ensure_ascii=False))
        return 0

    qid = sanitize(args.quest_id) if args.quest_id else active_quest(root)
    if not qid:
        print(json.dumps({"error": "no active quest — run: quest-log open <quest-id>"}))
        return 1
    events = load_events(root, qid)

    if args.cmd == "append":
        raw = {}
        if not sys.stdin.isatty():
            try:
                body = sys.stdin.read().strip()
                raw = json.loads(body) if body else {}
            except Exception:
                print(json.dumps({"error": "stdin is not valid JSON"}), file=sys.stderr)
                return 2
        for k, v in (("role", args.role), ("event", args.event), ("verdict", args.verdict), ("level", args.level)):
            if v:
                raw[k] = v
        if isinstance(raw.get("role"), str):
            raw["role"] = raw["role"].lower()  # 전이 함수 출력(WORKER)을 그대로 넣는 세션 실측 — 통계 축 분열 방지
        if args.criteria:
            raw["criteria"] = args.criteria
        if raw.get("event") not in EVENTS:
            print(json.dumps({"error": "event must be one of %s" % sorted(EVENTS)}), file=sys.stderr)
            return 2
        if raw.get("verdict", "NA") not in VERDICTS:
            print(json.dumps({"error": "verdict must be one of %s" % sorted(VERDICTS)}), file=sys.stderr)
            return 2
        ev = normalize(raw, events, qid, args.session)
        if ev["event"] == "verify":
            if ev["verdict"] == "NA":
                print(json.dumps({"error": "verify requires --verdict PASS|FAIL|ESCALATE"}), file=sys.stderr)
                return 2
            # 판정 이벤트의 물리 증거는 이 도구가 계산한다 — 손 계산 해시는 gate 와 어긋난다.
            ev["diff_hash"], ev["changed_files"], _, _ = diff_state(root, ev["base_ref"])
            ev.setdefault("level", "micro")
            if ev["verdict"] == "PASS":
                # 하네스 소유 베이스라인 (CUS-187) — normalize 가 stdin baseline 을 버린 뒤 여기서만 기록
                bl = run_baseline(root, policy, events, ev["diff_hash"])
                if bl:
                    ev["baseline"] = bl
        write_event(root, qid, ev)
        print(
            json.dumps(
                {"appended": ev["event"], "turn": ev["turn"], "verdict": ev["verdict"], "diff_hash": ev["diff_hash"]},
                ensure_ascii=False,
            )
        )
        return 0

    if args.cmd == "verify-baseline":
        # 게이트-우선 판정 턴 (CUS-188) — LLM Verifier 대신 하네스가 프로젝트 체크로 판정을 기록.
        # commands = 하네스가 직접 실행한 체크 (pass_evidence 충족) — verifier 재량 커맨드 아님.
        ev = normalize({"role": "harness", "event": "verify"}, events, qid, args.session)
        ev["diff_hash"], ev["changed_files"], _, _ = diff_state(root, ev["base_ref"])
        ev["level"] = "micro"
        bl = run_baseline(root, policy, events, ev["diff_hash"]) or {}
        state = bl.get("state")
        if state not in ("green", "red"):
            print(
                json.dumps({"error": "baseline 판정 불가 (체크 없음/전부 skip) — LLM Verifier 로 검증하세요"}),
                file=sys.stderr,
            )
            return 1
        results = [c for c in bl.get("results", []) if isinstance(c, dict)]
        ev["verdict"] = "PASS" if state == "green" else "FAIL"
        ev["commands"] = results[:20]
        ev["baseline"] = bl
        failing = [str(c.get("cmd")) for c in results if c.get("exit_code") not in (0, None)]
        if state == "red":
            ev["failure_sig"] = "baseline-red"
        write_event(root, qid, ev)
        print(
            json.dumps(
                {
                    "appended": "verify",
                    "verdict": ev["verdict"],
                    "baseline": state,
                    "failing": failing[:5],
                    "turn": ev["turn"],
                    "diff_hash": ev["diff_hash"],
                },
                ensure_ascii=False,
            )
        )
        return 0

    s = summarize(root, qid, events, policy)
    s["tests_available"] = tests_available(root)

    if args.cmd == "state":
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "next":
        print(json.dumps(transition(s, policy, args), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "close":
        verified = (
            s["last_verdict"] == "PASS"
            and s["pass_hash_match"]
            and s["pass_evidence"]  # 증거 없는 PASS 로 close → LAST 면제로 게이트 우회되던 구멍 봉합
            and s.get("baseline_state") != "red"  # 하네스 베이스라인 red 로는 close 불가 (CUS-187)
            and (not s["full_required"] or s["pass_level"] == "full")
        )  # gate 와 동일 기준
        ok = verified or s["last_verdict"] == "ESCALATE"
        if not ok and not args.force:
            print(
                json.dumps(
                    {
                        "error": "close 거부 — Verifier PASS(+hash 일치) 또는 ESCALATE 후에만. "
                        "우회는 --force (Odin 동의 필요)"
                    }
                ),
                file=sys.stderr,
            )
            return 1
        try:
            os.remove(os.path.join(quest_dir(root), "ACTIVE"))
        except FileNotFoundError:
            pass
        # LAST 포인터: 닫힌 뒤에도 gate 가 "이 워킹트리 상태는 검증됐다"를 증명할 수 있게 —
        # 없으면 close 직후 Stop 에서 write-sentinel 기록이 방금 검증된 write 를 오차단한다.
        try:
            open(os.path.join(quest_dir(root), "LAST"), "w").write(qid + "\n")
        except Exception:
            pass
        print(json.dumps({"closed": qid, "forced": bool(args.force and not ok)}))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
