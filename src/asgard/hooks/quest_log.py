#!/usr/bin/env python3
# Asgard quest-log — Trinity 퀘스트 로그 + 전이 함수 CLI.
#
# 코디네이터(Heimdall)의 "관찰·기록·배정" 프리미티브. 훅이 아니라 에이전트가 직접 부르는 도구다:
#   open   <quest-id>  과업 로그 시작 (base_ref = 현재 HEAD 고정, ACTIVE 포인터 갱신)
#   append             이벤트 1건 기록 (stdin JSON + 플래그) — verify 는 diff_hash 자동 계산
#   state              로그 요약 관찰 (코디네이터의 state observation)
#   next               전이 함수: 로그 상태 + risk_features → next_role (결정 테이블)
#   close              완료된 quest 의 ACTIVE 해제 (PASS+hash 일치 또는 ESCALATE 만)
#   verify-baseline    하네스가 베이스라인 체크를 직접 실행해 verify 판정을 기록 (게이트-우선)
#
# 왜 CLI 인가: TRINITY 의 "<20K 파라미터 코디네이터"의 하니스 등가물은 학습 모델이 아니라 결정론적
# 구조다 — 배정(next)을 LLM 임의 판단이 아닌 코드가 내리게 해서 조율을 프롬프트가 아닌 구조로
# 옮긴다 (TRINITY-inspired 적응).
# 왜 O_APPEND 단일 write 인가: 위협 모델이 악의적 변조가 아니라 LLM 자기기만이라 lock/해시체인은
# 과잉 (Codex 합의 — v1 탈락). 한 줄 원자 append 면 충분하다.
# 완료 위조 방어는 이 파일 몫이 아니다 — verifier-gate.py 가 Stop 시점에 working-tree diff hash 를
# 재계산해 물리 대조한다. 로그에 뭘 쓰든 워킹트리는 위조할 수 없다 (Goodhart 방어).
# diff_hash 를 여기(append)서도 계산하는 이유: verifier 가 손으로 만든 해시는 gate 재계산과 어긋날
# 수 있다 — 같은 알고리즘(아래 diff_state, verifier-gate.py 와 동일 유지)이 유일한 출처여야 한다.
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
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
}  # delegate: 중첩 디스패치 배정 기록 — Phase 2 통계가 배정 정책 학습
VERDICTS = {"PASS", "FAIL", "ESCALATE", "NA"}
# 로그 v1 = 16필드 고정. tier/effort/model 등은 v1 소비자 없음 → Phase 2.
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
    "delivery": {"freyja": "standard", "thor": "standard", "eitri": "standard", "loki": "fast"},
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
    # 하네스 소유 베이스라인 체크 — 비면 보수적 자동 감지 (pytest 만)
    "baseline_checks": [],
    "baseline_timeout": 120,
    # 게이트-우선 적격 상한 — small_write(full-verify 기준)보다 훨씬 좁다:
    # 63라인 리라이트가 소형 판정돼 caller 미방어로 close 된 벤치 결함. 소형 diff 전용.
    "gate_first_max_lines": 25,
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
    canonical = "*\n!.gitignore\n!map/\n!map/**\n!asgard-setting-project.json\n"
    try:
        current = open(gi).read() if os.path.exists(gi) else ""
    except Exception:
        current = ""
    if not current or current.strip() == "*":
        try:
            open(gi, "w").write(canonical)
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
# lagom: 고정 목록 — 정책 파일로 빼면 exclude 확대가 게이트 우회 벡터가 되므로 하드코딩 유지.
_JUNK_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox", "node_modules", ".venv"}


def _junk(p: str) -> bool:
    return p.endswith((".pyc", ".pyo")) or any(seg in _JUNK_DIRS for seg in p.split("/"))


def unsafe_map_links(root: str) -> list[str]:
    """Managed map links are invalid evidence; detect them without following targets."""
    map_dir = os.path.join(root, ".asgard", "map")
    expected = os.path.join(os.path.realpath(root), ".asgard", "map")
    if os.path.islink(map_dir) or os.path.realpath(map_dir) != expected:
        return [".asgard/map"]
    try:
        return [
            ".asgard/map/" + name
            for name in os.listdir(map_dir)
            if name.endswith(".md") and os.path.islink(os.path.join(map_dir, name))
        ]
    except OSError:
        return []


def symlink_map_state(path: str) -> bytes:
    """Hash a linked regular file without blocking on devices/FIFOs."""
    target = os.readlink(path).encode(errors="surrogateescape")
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return b"<unsafe-symlink-nonregular>\0" + target
        digest = hashlib.sha256()
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
        return b"<unsafe-symlink-sha256>\0" + target + b"\0" + digest.digest()
    except OSError:
        return b"<unsafe-symlink-unreadable>\0" + target
    finally:
        if fd is not None:
            os.close(fd)


def sensitive_path(path: str, needles) -> bool:
    """경로 세그먼트 기준 민감 매칭 — 나이브 substring 은 'ci' 가 circle.py 를 오탐.
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
    (스모크 벤치 발견: 잠금 테스트 2파일 추가가 big 판정 → 게이트-우선 무력화). 삭제된 테스트는
    별도 하드 트리거 (deleted_tests)."""
    if not base_ref or base_ref == "NONE":
        return EMPTY, [], 0, 0
    spec = [base_ref, "--", ".", ":(exclude).asgard"]
    rc, diff = git(root, "diff", "--binary", *spec, binary=True)
    if rc != 0:
        return EMPTY, [], 0, 0
    if isinstance(diff, str):
        diff = diff.encode()
    _, names = git(root, "diff", "--name-only", *spec)
    _, unt = git(root, "ls-files", "--others", "--exclude-standard", "--", ".", ":(exclude).asgard")
    names = names.decode(errors="replace") if isinstance(names, bytes) else names
    unt = unt.decode(errors="replace") if isinstance(unt, bytes) else unt
    _, base_maps = git(root, "ls-tree", "-r", "--name-only", base_ref, "--", ".asgard/map")
    base_maps = base_maps.decode(errors="replace") if isinstance(base_maps, bytes) else base_maps
    map_paths = {p for p in base_maps.splitlines() if p.strip()}
    map_dir = os.path.join(root, ".asgard", "map")
    try:
        map_paths.update(
            ".asgard/map/" + p
            for p in os.listdir(map_dir)
            if p.endswith(".md")
            and (os.path.isfile(os.path.join(map_dir, p)) or os.path.islink(os.path.join(map_dir, p)))
        )
    except OSError:
        pass
    map_changed = []
    for p in sorted(map_paths):
        before_rc, before = git(root, "show", f"{base_ref}:{p}", binary=True)
        if isinstance(before, str):
            before = before.encode()
        full_path = os.path.join(root, p)
        is_link = os.path.islink(full_path)
        try:
            after = symlink_map_state(full_path) if is_link else open(full_path, "rb").read()
        except OSError:
            after = None
        link_target = os.readlink(full_path).encode(errors="surrogateescape") if is_link else b""
        if (before if before_rc == 0 else None) != after:
            map_changed.append(p)
            diff += p.encode("utf-8", "surrogateescape") + b"\0" + link_target + b"\0" + (after if after is not None else b"<deleted>")
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
            if not p.startswith(".asgard/map/"):
                k = body.count(b"\n") + 1
                lines += k
                if not _testfile(p):
                    nt_lines += k
            h.update(p.encode() + b"\0" + hashlib.sha256(body).digest())
        except Exception:
            h.update(p.encode() + b"\0missing")
    changed = sorted(set(n for n in names.splitlines() if n.strip()) | set(untracked) | set(map_changed))
    return (h.hexdigest() if changed else EMPTY), changed, lines, nt_lines


# ── 하네스 소유 베이스라인 체크 — 증거 '품질'의 결정론화 ──
# 기존 pass_evidence 는 증거 '존재'만 봤다 — 어떤 명령이었는지는 verifier LLM 재량이라 `echo ok`
# 도 증거가 됐다 (깊이벤치 실증). 여기서는 하네스가 직접 프로젝트 체크를 실행해 exit code 를
# 기록한다 — LLM-as-judge 불신 원칙 (결정론 룰 피드백이 최상위 증거, Anthropic SDK 가이드).
# stdin 으로 들어온 baseline 은 normalize 가 버린다 — 이 코드만이 유일한 기록 경로 (위조 차단).


def detect_checks(root: str, policy: dict) -> list[str]:
    """정책 baseline_checks 우선. 없으면 보수적 자동 감지 — pytest 만.
    lagom: lint 류 자동 감지 안함 — 기존 위반 false-red 가 게이트 인질이 된다. 명시 설정으로만.
    uv 프로젝트(uv.lock)는 `uv run pytest` 로 — PATH pytest 는 venv 밖이라 수집 실패(2/3/4→skip)로
    게이트가 조용히 무력화되고, pytest 가 .venv 안에만 있으면 아예 미감지된다. uv 의 spawn 실패는
    exit 2 라 pytest 미의존 프로젝트도 skip 분류로 fail-open 이 유지된다."""
    cfg = policy.get("baseline_checks")
    if cfg:
        return [str(c) for c in cfg]
    import shutil

    if not any(os.path.exists(os.path.join(root, p)) for p in ("tests", "test", "pytest.ini", "pyproject.toml")):
        return []
    if os.path.exists(os.path.join(root, "uv.lock")) and shutil.which("uv"):
        return ["uv run pytest -x -q"]
    if shutil.which("pytest"):
        return ["pytest -x -q"]
    return []


def run_baseline(root: str, policy: dict, events: list[dict], diff_hash: str) -> dict | None:
    """체크 전부 실행 → {"state": green|red|none, "results": [...]}. 체크 없음 → None (요건 면제).
    같은 diff_hash 의 기존 verify 기록은 재사용 — 동일 트리에 pytest 를 두 번 돌리지 않는다.
    skip(127 미설치·pytest 5 수집 없음·timeout)은 red 아님 — 게이트는 자기기만 방어지 인질극 장치가
    아니다 (verifier_gate.py 서두와 같은 원칙). lagom: timeout=skip 은 보호 약화 — 느린 스위트는
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


def trivial_evidence(cmd) -> bool:
    """verifier_gate.py 의 trivial_evidence 와 동일 유지 (단일 출처 원칙) — `true` 한 방이 PASS
    증거로 성립하던 Goodhart 구멍 봉합: 무조건 exit 0 인 명령은 검증 증거가 아니다."""
    c = " ".join(str(cmd).split())
    return c in ("true", ":", "exit 0", "echo") or c.startswith("echo ")


# ── criteria verify 계약 — 기준별 검증 명령·산출물 결속 ──
# criteria 문자열에 옵트인 계약을 얹는다: "<설명> | verify: <명령> | artifacts: <경로...>".
# 계약이 선언되면 "아무 nontrivial 명령 exit 0" 은 더 이상 그 기준의 증거가 아니다 — 하네스가
# 계약 명령을 직접 실행해 기록하고(모델 신고 exit code 불신, baseline 과 동일 원칙), 퍼널이
# 전 계약 충족을 요구한다. 계약 없는 기준은 현행 동작 유지 (하위호환).
# 잔여 한계(문서화): 계약 명령의 '의미적 관련성'은 결정론으로 판정 불가 — 대신 계약이 open 시점
# 로그에 선언·감사되므로 검증 시점 재량 선택보다 위조 표면이 좁다.


def parse_criterion(text) -> dict:
    """ "설명 | verify: cmd | artifacts: a b" → {description, verify_cmd, artifacts}. 계약 없음 = 빈 값."""
    desc, cmd, arts = str(text), None, []
    parts = [p.strip() for p in str(text).split(" | ")]
    if len(parts) > 1:
        desc = parts[0]
        for p in parts[1:]:
            if p.startswith("verify:"):
                cmd = p[len("verify:") :].strip() or None
            elif p.startswith("artifacts:"):
                arts = [a for a in p[len("artifacts:") :].split() if a]
            else:
                desc = desc + " | " + p  # 계약 키워드가 아닌 ' | ' 는 설명의 일부
    if cmd and trivial_evidence(cmd):
        cmd = None  # trivial 명령은 계약이 될 수 없다 — 증거 필터와 동일 기준 (Goodhart)
    return {"description": desc, "verify_cmd": cmd, "artifacts": arts}


def criteria_contracts(criteria) -> list[dict]:
    """verify 계약이 선언된 기준만 — verify_cmd 또는 artifacts 보유."""
    out = []
    for t in criteria or []:
        c = parse_criterion(t)
        if c["verify_cmd"] or c["artifacts"]:
            out.append(c)
    return out[:5]  # 상한 — 계약 폭주가 verify 턴을 인질로 잡지 않게


def unmet_contracts(root: str, criteria, rec: dict) -> list[str]:
    """PASS 레코드(rec) 기준 미충족 계약 목록. 명령은 하네스 기록(criteria_checks)의 exit 0 만 인정,
    산출물은 지금(호출 시점) 존재를 라이브 재확인 — 산출물은 .gitignore 로 diff-hash 밖일 수 있어
    stale 검사가 삭제를 못 잡는다. 계약이 있는데 기록이 없으면(구버전 이벤트) 미충족 — 재검증 유도."""
    unmet = []
    checks = {(" ".join(str(c.get("cmd", "")).split())): c.get("exit_code") for c in (rec.get("criteria_checks") or [])}
    for c in criteria_contracts(criteria):
        cmd = c["verify_cmd"]
        if cmd and checks.get(" ".join(cmd.split())) != 0:
            unmet.append("verify: " + cmd)
        for a in c["artifacts"]:
            if not os.path.exists(os.path.join(root, a)):
                unmet.append("artifact: " + a)
    return unmet


def run_criteria_checks(root: str, policy: dict, criteria, events: list[dict], diff_hash: str) -> list[dict] | None:
    """계약 명령을 하네스가 직접 실행해 기록 — stdin 위조는 normalize 가 버리고 이 코드만이
    기록 경로 (baseline 과 동일). 같은 diff_hash 의 기존 기록은 재사용. 계약 없음 → None (요건 면제)."""
    contracts = [c for c in criteria_contracts(criteria) if c["verify_cmd"]]
    if not contracts:
        return None
    for e in reversed(events):
        cc = e.get("criteria_checks")
        if cc and e.get("event") == "verify" and e.get("diff_hash") == diff_hash:
            return [{**c, "cached": True} for c in cc if isinstance(c, dict)]
    timeout = int(policy.get("baseline_timeout") or 120)
    results: list[dict] = []
    for c in contracts:
        t0 = time.time()
        code: int | None
        try:
            p = subprocess.run(c["verify_cmd"], shell=True, cwd=root, capture_output=True, timeout=timeout)
            code = p.returncode
        except Exception:
            code = None  # timeout 포함 — 미충족 취급 (계약은 명시 선언이라 skip 면제 없음)
        results.append({"cmd": c["verify_cmd"][:200], "exit_code": code, "secs": round(time.time() - t0, 1)})
    return results


def pass_evidence(rec: dict) -> bool:
    """PASS 레코드의 성공 명령 증거 — trivial 명령 제외 (verifier_gate.py 와 동일 유지).
    하네스가 직접 돌린 베이스라인 green·전 계약 성공(criteria_checks)은 그 자체가 물리 증거 —
    trivial 필터는 모델이 고른 명령에만 적용한다 (둘 다 하네스 소유 기록, 모델 위조 불가)."""
    if (rec.get("baseline") or {}).get("state") == "green":
        return True
    checks = [c for c in (rec.get("criteria_checks") or []) if isinstance(c, dict)]
    if checks and all(c.get("exit_code") == 0 for c in checks):
        return True  # 계약 명령 전부 성공 — 하네스가 직접 실행한 기록
    return any(
        isinstance(c, dict) and c.get("exit_code") == 0 and not trivial_evidence(c.get("cmd", ""))
        for c in (rec.get("commands") or [])
    )


_SIG_PAT = re.compile(r"^-\s*(def |class |function |export |public |fn )")


def signature_risk(root: str, base_ref: str | None) -> bool:
    """diff 에 삭제·변경된 함수/클래스 시그니처 라인 존재 여부 — 숨은-caller 리스크의 결정론 신호
    (벤치 t3 방어 유지 조건). '-' 라인만 본다: 신규 추가(+def)는 기존 caller 가 없다.
    게이트-우선(STANDARD) 라우팅 전용 — verifier_gate 대응 불필요."""
    if not base_ref or base_ref == "NONE":
        return False
    rc, out = git(root, "diff", "-U0", base_ref, "--", ".", ":(exclude).asgard")
    if rc != 0:
        return False
    return any(_SIG_PAT.match(line) for line in out.splitlines())


def load_policy(root: str) -> dict:
    p = dict(DEFAULT_POLICY)
    # 신규 통합 설정(asgard-setting-project.json 의 trinity_policy) 우선, 구 파일 폴백 (fail-open)
    try:
        cfg = json.load(open(os.path.join(root, ".asgard", "asgard-setting-project.json")))
        pol = cfg.get("trinity_policy") if isinstance(cfg, dict) else None
        if isinstance(pol, dict):
            p.update(pol)
            return p
    except Exception:
        pass
    try:
        p.update(json.load(open(os.path.join(root, ".asgard", "trinity-policy.json"))))
    except Exception:
        pass  # 정책 파일 없음/깨짐 → 내장 기본값 (fail-open)
    return p


# ── Bayesian-lite 라우팅 prior — task-class별 게이트-red 이력 카운트 ──
# 학습 없음: 퀘스트 종결마다 {n, red} 카운트 1건 (기록자는 Heimdall — 모델 비노출).
# 소비는 transition 의 게이트-우선 승격 문턱뿐 — 게이트 자체는 여전히 물리 가드가 판정한다
# ("게이트는 메모리 불신" — prior 는 심도 선택 힌트지 증거가 아니다).


def load_priors(root: str) -> dict:
    for rel in (os.path.join("state", "route-priors.json"), "route-priors.json"):  # 신규 state/ 우선
        try:
            return json.load(open(os.path.join(root, ".asgard", rel)))
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
        json.dump(p, open(tmp, "w"))
        os.replace(tmp, f)
    except Exception:
        pass


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
    if ev.get("unit") is not None:  # work 전용 부가 필드 — wave 병렬 배정 단위 id
        full["unit"] = ev["unit"]
    if ev.get("model"):  # 실사용 provider:model 기록 — 라우팅 prior 등 결과 기반 정책 조정의 데이터 축
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
    # (스모크 실측: 잠금 테스트 2파일 추가 → big 오판 → full 강제·게이트-우선 무력화). 삭제는 dts 가 잡는다.
    nt_files = [f for f in changed if not _testfile(f)]
    small = policy["small_write"]
    _esc_i = [i for i, e in enumerate(events) if e.get("event") == "verify" and e.get("verdict") == "ESCALATE"]
    _plan_i = [i for i, e in enumerate(events) if e.get("event") == "plan"]
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
        # PASS 의 성공 명령 증거 — 게이트와 동일 기준 (없으면 전이·close 가 거부 — 깊이 테스트가 발견한 구멍)
        "pass_evidence": bool(last_pass and pass_evidence(last_pass)),
        # 하네스 베이스라인 상태 — 기록 없음(구 로그·체크 미설정) = none = 요건 면제 (fail-open)
        "baseline_state": ((last_pass or {}).get("baseline") or {}).get("state") or "none",
        # criteria verify 계약 미충족 목록 — 계약 없는 기준은 빈 리스트 (하위호환, 요건 면제)
        "contracts_unmet": unmet_contracts(
            root, next((e.get("criteria") for e in events if e.get("criteria")), []), last_pass or {}
        ),
        # 무인 nudge 상태 (Canon 8) — 마커 파일 대신 로그 구조가 상한을 센다:
        #   replan_after_escalate = 마지막 ESCALATE 이후 plan 존재 (nudge/오딘 답변이 소비됨 → 실행 재개)
        #   escalate_nudged       = 어떤 ESCALATE 든 이후 plan 이 존재 (퀘스트당 nudge 1회 소진)
        "replan_after_escalate": bool(_esc_i and _plan_i and _plan_i[-1] > _esc_i[-1]),
        "escalate_nudged": bool(_esc_i and _plan_i and _plan_i[-1] > _esc_i[0]),
        # 게이트-우선 라우팅 신호
        "checks_available": bool(detect_checks(root, policy)),
        "sig_risk": signature_risk(root, base_ref),
    }


# ── 완료 판정 단일 퍼널 — 승인 경로의 유일한 출처 ──
def completion_decision(s: dict) -> tuple[str, str, str]:
    """(decision, code, why). decision ∈ APPROVED/REJECTED/ESCALATED — transition(PASS 분기)과
    close 가 모두 이 함수만 신뢰한다. 불변식: REJECTED 는 어떤 호출측에서도 승인으로 승격 금지
    (close --force 는 LAST 미기록·게이트 면제 없는 관리적 해제일 뿐, 승인이 아니다).
    verifier-gate.py 의 Stop 차단 기준과 동일 유지 (단일 출처 원칙 — 어긋나면 DONE 이 Stop 에서 차단)."""
    if s.get("last_verdict") == "ESCALATE":
        return "ESCALATED", "escalate", "Verifier ESCALATE — Odin 결정 대기 (Canon 9 정규 종료)"
    if s.get("last_verdict") != "PASS":
        return "REJECTED", "no_pass", "Verifier PASS 판정 없음"
    if not s.get("criteria"):
        # 게이트와 동일 검사 — close 가 이걸 안 보면 무기준 PASS 가 LAST 면제로 게이트를 우회한다
        return "REJECTED", "no_criteria", "성공 기준(criteria)이 로그에 없음 — 기준 없이는 검증이 성립하지 않는다"
    if not s.get("pass_evidence"):
        return "REJECTED", "no_evidence", "PASS 에 성공한 검증 명령 증거 없음"
    if s.get("baseline_state") == "red":
        return "REJECTED", "baseline_red", "하네스 베이스라인 체크 red — 실패한 체크 수리 필요"
    unmet = s.get("contracts_unmet") or []
    if unmet:
        # 계약이 선언된 기준은 그 명령·산출물이 유일한 증거다 — 무관한 exit-0 명령으로 대체 불가
        return "REJECTED", "criteria_unverified", "criteria verify 계약 미충족: %s" % "; ".join(map(str, unmet[:3]))
    if not s.get("pass_hash_match"):
        return "REJECTED", "stale_pass", "PASS 이후 워킹트리 변경(stale PASS) — 재검증 필요"
    if s.get("full_required") and s.get("pass_level") != "full":
        return "REJECTED", "micro_pass", "full-verify 필요(민감 경로/큰 diff)한데 micro PASS"
    return "APPROVED", "ok", "Verifier PASS + diff-hash 물리 대조 일치"


# ── 전이 함수 — 결정 테이블은 코드가 유일한 출처, 임계값만 정책에서 온다 ──
def transition(s: dict, policy: dict, flags, priors: dict | None = None) -> dict:
    small = policy["small_write"]
    # big 은 non-test 질량 기준 (summarize.full_required 와 동일) — 테스트 추가로 full/승격을 트리거하지 않는다
    big = (
        s.get("nontest_files", len(s["changed_files"])) > small["max_files"]
        or s.get("nontest_lines", s["diff_lines"]) > small["max_lines"]
    )
    sensitive = bool(s["sensitive_files"]) or flags.shared
    full_required = s["full_required"] or flags.shared
    has_write = s["diff_hash"] != EMPTY or s["risk_write"] or flags.write_expected
    # risk_features 11종 — 결정론 계산 7 + 모델 신고 4 (--flags)
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
    # 게이트-우선(STANDARD) 적격 — 플래그 없는 기본값: 물리 가드가 전부 판정한다.
    # v1 은 --standard 옵트인이었으나 스모크 3회에서 모델이 플래그를 안 넘김 (프롬프트 계약
    # 한계) — 의존성을 삭제하고 전이 함수 기본으로 흡수. 조건 하나라도 깨지면 아래 트리니티 행으로
    # 자연 폴스루 = 승격. 민감/큰 non-test diff/시그니처 변경/테스트 삭제/모호는 LLM Verifier 가 필요.
    # 게이트-우선 전용 라인 상한 (벤치 결함 대응): sig_risk 는 def 삭제만 본다 — def 무변경
    # 리라이트(+52/-11)가 동작 계약을 바꿔 caller 를 깨는 경로는 diff 질량으로만 잡을 수 있다.
    # 가시 테스트(baseline)는 near-oracle 이 아니므로 (2606.24453 regime) 소형 diff 에서만 신뢰.
    gf_small = s.get("nontest_lines", s["diff_lines"]) <= int(policy.get("gate_first_max_lines") or 25)
    standard_ok = (
        not sensitive
        and not big
        and gf_small
        and not s.get("deleted_tests")
        and not s.get("sig_risk")
        and not flags.ambiguous
        and not flags.external_research
    )
    # Bayesian-lite 승격 문턱 — 이 task-class 의 게이트-red 이력이 과반이면 red 1회로
    # 선제 승격. Beta(1,1) posterior mean (red+1)/(n+2) > 0.5 ⟺ red > n−red (과반 판정) —
    # 카운트뿐, 학습 없음 (arXiv 2606.24453: 검증 싸고 critic 불완전한 구간의 적응 제어).
    pc = ((priors or {}).get("classes") or {}).get(getattr(flags, "task_class", None) or "", {})
    red_hist = int(pc.get("red") or 0)
    promote_at = 1 if red_hist > int(pc.get("n") or 0) - red_hist else 2

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
    if s["last_verdict"] == "ESCALATE" and not s.get("replan_after_escalate"):
        # ESCALATE 이후 재계획(plan)이 남았으면 이 분기를 건너뛴다 — 재계획이 에스컬레이션을 소비하고
        # 아래 WORKER 폴스루로 실행이 이어진다 (오딘 답변 후 재개 경로와 무인 nudge 경로 공통).
        if getattr(flags, "unattended", False) and not s.get("escalate_nudged"):
            # 무인 세션 1회 nudge (Canon 8) — 오딘의 답은 오지 않는다. 방어 가능한 기본안으로 재계획을
            # 강제하고, nudge 소진 후의 재-ESCALATE 는 진짜 블로커로 인정 (verifier_gate 의 마커 파일과
            # 같은 의미론 — 여기선 로그 구조(ESCALATE↔plan 순서)가 상한을 센다).
            return out(
                "THINKER_REPLAN",
                "무인 세션 ESCALATE (Canon 8) — 방어 가능한 기본안을 골라 `가정:` criteria 로 기록하고 진행. "
                "어떤 기본안도 방어 불가한 진짜 블로커면 사유 기록 후 재-ESCALATE",
            )
        # Verifier ESCALATE = 진행 불가 블로커 신고 (Canon 8: 승인 요청 용도 아님) — WORKER 폴스루로
        # 예산을 태우지 않고 즉시 Odin 에스컬레이션. 게이트/close 의 ESCALATE 수용과 대칭.
        return out("ESCALATE_ODIN", "Verifier ESCALATE — 진행 불가 블로커, Odin 결정 필요")
    if s["last_verdict"] == "FAIL":
        if standard_ok and s.get("fail_streak_any", 0) >= promote_at:
            # 게이트-우선에서 red 2회 = 싼 게이트로 못 넘는 벽 — threshold(3) 전에 선제 승격.
            # prior 과반-red 클래스는 red 1회로 하향.
            why = "게이트-우선 red %d회 — Trinity 승격, 접근 재설계" % s["fail_streak_any"]
            return out("THINKER_REPLAN", why + (" (prior: 클래스 red 이력 과반)" if promote_at == 1 else ""))
        return (
            out("THINKER_REPLAN", "Verifier FAIL(구조적) — 접근 재설계")
            if flags.structural
            else out("WORKER_RETRY", "Verifier FAIL(경미) — 같은 계획으로 수정")
        )
    if s["last_verdict"] == "PASS":
        # 완료 판정은 단일 퍼널(completion_decision)만 신뢰한다 — close·게이트와 판정 불일치 금지.
        # flags.shared 는 전이 시점 모델 신고라 요약에 없다 — 퍼널 입력에 병합.
        decision, code, why = completion_decision({**s, "full_required": full_required})
        if decision == "APPROVED":
            return out("DONE", why)
        if code == "baseline_red":
            # 하네스가 직접 돌린 프로젝트 체크가 실패 — 판정이 아니라 코드가 깨져 있다
            return out("WORKER_RETRY", "하네스 베이스라인 체크 red — 실패한 체크를 먼저 수리 (Canon 10)")
        if code == "no_evidence":
            # 증거 없는 PASS 는 판정이 아니다 — 게이트가 어차피 차단하므로 전이가 먼저 재검증을 보낸다
            # (판정 불일치 금지). close 우회 구멍의 전이측 봉합 (깊이 테스트 발견).
            return out("VERIFIER", "PASS 에 성공한 검증 명령 증거 없음 — 명령을 직접 실행해 재판정 (Canon 10)")
        if code == "no_criteria":
            return out("VERIFIER", "성공 기준(criteria)이 로그에 없음 — criteria 기록 후 재판정 (Canon 10)")
        if code == "criteria_unverified":
            # 계약 명령이 실패했거나 산출물이 없다 — 재검증 append 가 하네스 재실행을 트리거한다
            return out("VERIFIER", why + " — 계약 명령을 수리/재실행해 재판정 (Canon 10)")
        if code == "stale_pass":
            return out("VERIFIER", "PASS 이후 워킹트리 변경(stale PASS) — 재검증 필요")
        # micro_pass — gate 와 동일 판정: micro PASS 로 DONE 을 내면 Stop 에서 차단당한다 (판정 불일치 금지)
        return out("VERIFIER", "PASS 가 micro — 민감 경로/큰 diff 는 full-verify 필요")
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
            return out("BASELINE_VERIFY", "게이트-우선 — 하네스 베이스라인 판정")
        return out("VERIFIER", "Worker 완료 — %s-verify 판정 차례" % level)
    if (sensitive or big) and s["plan_turns"] < 2:
        # open 의 자동 plan(턴1)은 접수 기록일 뿐 — 민감/큰 write 는 실제 Thinker 계획 턴을 요구한다.
        return out("THINKER", "sensitive/big write — Thinker 계획 선행 (full-verify 경로)")
    return out("WORKER", "배정 단위 실행 차례")


def map_nudge(root: str, base_ref: str | None) -> list[str]:
    """close 시 지도 갱신 리마인더 — base_ref 이후 구조 변경(추가 A/삭제 D/이동 R)만 본다.
    0-LLM·fail-open: git 실패·지도 미도입(.asgard/map 부재)이면 침묵. 내용 수정(M)은 지도 무관.
    diff 는 untracked 를 못 보므로 ls-files --others 를 A 로 합류 (diff_state 와 동일 처리)."""
    if not base_ref or base_ref == "NONE" or not os.path.isdir(os.path.join(root, ".asgard", "map")):
        return []

    def mappable(p: str) -> bool:  # 런타임·캐시·닷디렉토리(.claude 등 스캐폴드) 제외 — 소스 구조만
        return bool(p.strip()) and not _junk(p) and not any(seg.startswith(".") for seg in p.split("/"))

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


def refresh_managed_map(root: str) -> bool:
    """Verifier hash 전에 PROJECT.md를 갱신한다. 지도 미도입/패키지 부재/IO 실패는 fail-open.

    검증 뒤 close에서 쓰면 PASS hash가 즉시 stale해진다. 따라서 자동 지도 변경도 반드시
    Verifier가 판정하는 diff에 포함되도록 이 시점 하나에서만 쓴다.
    """
    if not os.path.isdir(os.path.join(root, ".asgard", "map")):
        return False
    try:
        from asgard.code_map import refresh_map

        return refresh_map(root).changed
    except Exception:
        return False


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
    ap.add_argument(  # Canon 8 무인 진행 — asgard run 이 env 를 심으므로 기본값이 env 를 읽는다
        "--unattended", action="store_true", default=os.environ.get("ASGARD_UNATTENDED") == "1"
    )
    ap.add_argument(
        "--task-class",
        choices=["trivial", "standard", "deep"],
        dest="task_class",
        help="open: 로그 기록 / next: prior 승격 문턱 조회 축",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="close: 판정 없이 강제 해제 (Odin 동의 필요 — LAST 미기록, 게이트 면제 없음)",
    )
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
        risk = {"has_write": not args.no_write}
        if args.task_class:  # prior 집계 축 — 퀘스트가 어느 클래스로 열렸는지 감사 기록
            risk["task_class"] = args.task_class
        ev = normalize(
            {
                "role": "thinker",
                "event": "plan",
                "base_ref": base_ref,
                "risk": risk,
                "criteria": args.criteria,
            },
            load_events(root, qid),
            qid,
            args.session,
        )
        write_event(root, qid, ev)
        # temp+rename — 크래시 절단 ACTIVE(빈 파일)가 게이트를 orphan 경로로 오도하지 않게.
        # lagom: 전역 포인터 자체는 유지 — 동시 세션 경쟁은 open 시 dangling 경고가 표면화
        _ap = os.path.join(quest_dir(root), "ACTIVE")
        _tmp = "%s.%d.tmp" % (_ap, os.getpid())
        open(_tmp, "w").write(qid + "\n")
        os.replace(_tmp, _ap)
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
            # 구조 지도도 판정 대상 diff에 포함 — PASS 뒤 close가 파일을 쓰면 stale hash가 된다.
            refresh_managed_map(root)
            # 판정 이벤트의 물리 증거는 이 도구가 계산한다 — 손 계산 해시는 gate 와 어긋난다.
            ev["diff_hash"], ev["changed_files"], _, _ = diff_state(root, ev["base_ref"])
            unsafe_maps = unsafe_map_links(root)
            if unsafe_maps and ev["verdict"] == "PASS":
                ev["verdict"] = "FAIL"
                ev["failure_sig"] = "unsafe-map-link"
                ev["changed_files"] = sorted(set(ev["changed_files"]) | set(unsafe_maps))
            ev.setdefault("level", "micro")
            if ev["verdict"] == "PASS":
                # 하네스 소유 베이스라인 — normalize 가 stdin baseline 을 버린 뒤 여기서만 기록
                bl = run_baseline(root, policy, events, ev["diff_hash"])
                if bl:
                    ev["baseline"] = bl
                # criteria verify 계약 — 하네스가 계약 명령을 직접 실행해 기록 (stdin 위조는 normalize 가 버림)
                crit = ev.get("criteria") or next((e.get("criteria") for e in events if e.get("criteria")), [])
                cc = run_criteria_checks(root, policy, crit, events, ev["diff_hash"])
                if cc is not None:
                    ev["criteria_checks"] = cc
        write_event(root, qid, ev)
        print(
            json.dumps(
                {"appended": ev["event"], "turn": ev["turn"], "verdict": ev["verdict"], "diff_hash": ev["diff_hash"]},
                ensure_ascii=False,
            )
        )
        return 0

    if args.cmd == "verify-baseline":
        # 게이트-우선 판정 턴 — LLM Verifier 대신 하네스가 프로젝트 체크로 판정을 기록.
        # commands = 하네스가 직접 실행한 체크 (pass_evidence 충족) — verifier 재량 커맨드 아님.
        ev = normalize({"role": "harness", "event": "verify"}, events, qid, args.session)
        refresh_managed_map(root)
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
        elif unsafe_map_links(root):
            ev["verdict"] = "FAIL"
            ev["failure_sig"] = "unsafe-map-link"
        else:
            # criteria verify 계약 — 게이트-우선 경로도 계약을 결속한다: 계약 미충족이면 green 이어도 FAIL
            crit = next((e.get("criteria") for e in events if e.get("criteria")), [])
            cc = run_criteria_checks(root, policy, crit, events, ev["diff_hash"])
            if cc is not None:
                ev["criteria_checks"] = cc
            unmet = unmet_contracts(root, crit, ev)
            if unmet:
                ev["verdict"] = "FAIL"
                ev["failure_sig"] = "criteria-contract"
                failing = [str(u) for u in unmet]
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
        print(json.dumps(transition(s, policy, args, load_priors(root)), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "close":
        # 완료 판정은 단일 퍼널만 신뢰 — transition(DONE)·게이트와 동일 기준.
        decision, code, why = completion_decision(s)
        ok = decision in ("APPROVED", "ESCALATED")
        if not ok and not args.force:
            print(
                json.dumps(
                    {
                        "error": "close 거부(%s: %s) — Verifier PASS(+hash 일치) 또는 ESCALATE 후에만. "
                        "우회는 --force (Odin 동의 필요 — LAST 미기록, 게이트 면제 없음)" % (code, why)
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 1
        forced = bool(args.force and not ok)
        try:
            os.remove(os.path.join(quest_dir(root), "ACTIVE"))
        except FileNotFoundError:
            pass
        # LAST 포인터: 닫힌 뒤에도 gate 가 "이 워킹트리 상태는 검증됐다"를 증명할 수 있게 —
        # 없으면 close 직후 Stop 에서 write-sentinel 기록이 방금 검증된 write 를 오차단한다.
        # forced close 는 LAST 를 기록하지 않는다 — REJECTED 를 --force 로 해제해도
        # 게이트 면제(승인)로 승격되지 않는다. 남은 write 는 Stop 의 orphan 검사가 정상 차단.
        if not forced:
            try:
                _lp = os.path.join(quest_dir(root), "LAST")
                _tmp = "%s.%d.tmp" % (_lp, os.getpid())
                open(_tmp, "w").write(qid + "\n")
                os.replace(_tmp, _lp)
            except Exception:
                pass
        res = {"closed": qid, "forced": forced}
        if forced:
            res["gate_exempt"] = False
            res["rejected"] = "%s: %s" % (code, why)
        try:  # 지도 최신 여부 확인. 자동 갱신 실패 때만 수동 증분 갱신을 리마인드한다.
            from asgard.code_map import check_map

            map_current = check_map(root).ok if os.path.isdir(os.path.join(root, ".asgard", "map")) else False
            nudge = map_nudge(root, s.get("base_ref"))
        except Exception:
            map_current = False
            nudge = []
        if map_current:
            res["map_current"] = True
        elif nudge:
            res["map_update"] = nudge
            res["map_hint"] = "자동 지도 갱신 실패 — asgard setup map 실행 후 영역 지도에 새 지식만 증분 반영"
        print(json.dumps(res, ensure_ascii=False))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
