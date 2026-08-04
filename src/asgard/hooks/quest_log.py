#!/usr/bin/env python3
# Asgard quest-log — Trinity 퀘스트 로그 + 전이 함수 CLI.
#
# 코디네이터(Heimdall)의 "관찰·기록·배정" 프리미티브. 훅이 아니라 에이전트가 직접 부르는 도구다:
#   open   <quest-id>  과업 로그 시작 (base_ref = 현재 HEAD 고정, ACTIVE 포인터 갱신)
#   append             이벤트 1건 기록 (stdin JSON + 플래그) — verify는 diff_hash 자동 계산
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
# 수 있다 — 같은 알고리즘(아래 diff_state, verifier-gate.py와 동일 유지)이 유일한 출처여야 한다.
#
# 왜 이 큰 상태기계가 hooks/ 안에 있는가 (재검토한 뒤 남기는 기록):
# 이 파일은 두 얼굴이다. ① setup이 `.claude/hooks/quest-log.py`로 **원문 그대로 복사**해 배포하는
# 단일 파일 CLI (에이전트가 subprocess로 부른다) ② Trinity가 임포트하는 라이브러리
# (agent/heimdall/*, templates/trinity.py, commands/doctor.py, hooks/memory_activate.py).
# 코어를 asgard 패키지로 옮기고 여기를 껍데기로 만들면 ①이 죽는다: 배포 사본은 asgard를 임포트할
# 수 없고(그게 test_hooks_are_self_contained의 계약), 그렇다고 폴백 구현을 두면 상태기계 정본이
# 둘이 된다. 실측으로도 갈라지지 않는다 — 최상위 정의 79개 중 이 파일 자신이 안 쓰는 것은
# update_priors 하나뿐이라, "라이브러리 면"과 "CLI 면"이 같은 코드다. 그래서 분해는 파일 밖이
# 아니라 파일 안에서 한다: 갈래마다 한 함수, 한 함수는 한 추상 수준.
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
import tempfile
import time

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass


SCHEMA = 2
EMPTY = hashlib.sha256(b"").hexdigest()  # 변경 전무(diff 없음 + untracked 없음)의 정준 해시
# 숫자 파싱 실패 두 종. 이름으로 묶는 이유: 훅은 asgard의 venv가 아니라 사용자 PATH의
# python3로 돈다(`platform.hook_python`). 괄호 없는 다중 except는 3.14+ 문법(PEP 758)이라
# 3.13 이하 기계에선 이 파일이 임포트 시점 SyntaxError가 되고, 훅 계약이 fail-open이라 그
# 죽음이 **조용하다**. 그렇다고 괄호로 쓰면 포매터(target-version=py314)가 도로 벗긴다 —
# 이름은 못 건드린다. tests/test_architecture.py의 문법 바닥 검사가 이 불변식을 지킨다.
_BAD_NUMBER = (TypeError, ValueError)
EVENTS = {
    "plan",
    "work",
    "verify",
    "fail",
    "escalate",
    "delegate",
    "ticket",
    "ticket_lease",
    "quest_closed",
}  # delegate: 중첩 디스패치 배정 기록 — Phase 2 통계가 배정 정책 학습
# ticket_lease: lease 갱신 전용 — 상태 전이가 아니다. 갱신이 `ticket`으로 적히면 티켓 이벤트
# 열이 "todo→in_progress→done"이 아니라 "얼마나 오래 돌았는가"를 적게 되고(lease의 1/3마다
# 한 줄), 그 열을 읽는 쪽은 벽시계에 따라 다른 역사를 본다. finish가 실패한 뒤의 lease 단축도
# 같은 이유로 티켓을 in_progress로 되돌려 놓았다.
# 갱신은 claim token을 검증하는 ticket-heartbeat만 적을 수 있다 — raw append로 열어 두면
# 토큰 없이 남의 lease를 미는 문이 된다.
APPEND_EVENTS = EVENTS - {"ticket_lease"}
VERDICTS = {"PASS", "FAIL", "ESCALATE", "NA"}
TICKET_STATUSES = {"todo", "in_progress", "done", "failed", "blocked"}
# v1의 16필드 + v2 실행/승인/체인 identity. tier/effort/model 등은 부가 관측 필드.
FIELDS = [
    "schema",
    "quest_id",
    "execution_id",
    "acceptance_hash",
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
    "prev_event_hash",
    "event_hash",
]

# 정책 파일이 없어도 동작해야 하므로(fail-open) 기본값을 내장 — .asgard/trinity-policy.json이 덮는다.
# dict 주석: 이질형 중첩 리터럴이라 좁은 추론이 소비처 서브스크립트를 오탐한다 (ty).
DEFAULT_POLICY: dict = {
    "schema": 1,
    "roles": {
        "thinker": {"tier": "high", "effort": "high"},
        "worker": {"tier": "standard", "effort": "medium"},
        "verifier": {"tier": "high", "effort": "high"},
    },
    # 소비자는 Heimdall(_delivery_model/_model_for) — 여기 두는 이유는 템플릿과 기본값 거울 유지.
    "delivery": {"freyja": "standard", "thor": "standard", "eitri": "standard", "loki": "fast", "mimir": "standard"},
    "budget_priors": {"trivial": {"turns": 1}, "standard": {"turns": 6}, "deep": {"turns": 12}},
    "small_write": {"max_files": 2, "max_lines": 80},
    # 매칭은 세그먼트/토큰 정확 일치 (sensitive_path) — substring 파생형은 여기 명시한다.
    "sensitive_paths": [
        "hooks",
        "policy",
        "policies",
        "templates",
        "install",
        "security",
        "auth",
        "authn",
        "authz",
        "authentication",
        "authorization",
        "secret",
        "secrets",
        "credentials",
        "db",
        "migration",
        "migrations",
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
    # 하네스 소유 베이스라인 체크 — 비면 보수적 자동 감지 (pytest만)
    "baseline_checks": [],
    "baseline_timeout": 120,
    # 게이트-우선 적격 상한 — small_write(full-verify 기준)보다 훨씬 좁다:
    # 63라인 리라이트가 소형 판정돼 caller 미방어로 close 된 벤치 결함. 소형 diff 전용.
    "gate_first_max_lines": 25,
    # 닫힌 퀘스트 로그 keep-last-N — 세션 상한 정책. 0 = 정리 없음(무한 누적).
    "quest_retention": 30,
    # 병렬 Worker는 기본적으로 독립 clone에서 실행하고 검증된 patch만 canonical root에 병합.
    "ticket_runtime": {"isolation": True, "lease_seconds": 300, "max_attempts": 3},
}


def _canonical_hash(value) -> str:
    """Stable local integrity digest. This is tamper-evident, not an authenticity signature."""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def acceptance_identity(
    *,
    request: str,
    criteria,
    base_ref: str,
    ignored_snapshot: dict,
    risk: dict,
) -> str:
    """Bind the exact requested outcome to the quest-start physical tree."""
    return _canonical_hash(
        {
            "request": request,
            "criteria": list(criteria or []),
            "base_ref": base_ref,
            "ignored_snapshot": ignored_snapshot,
            "risk": risk,
        }
    )


def event_identity(event: dict) -> str:
    """Hash one event without its self-referential digest."""
    return _canonical_hash({key: value for key, value in event.items() if key != "event_hash"})


def verification_identity(event: dict) -> str:
    """Bind a PASS to one execution, acceptance contract, physical diff and evidence set."""
    return _canonical_hash(
        {
            "execution_id": event.get("execution_id"),
            "acceptance_hash": event.get("acceptance_hash"),
            "diff_hash": event.get("diff_hash"),
            "tree_ref": event.get("tree_ref"),
            "level": event.get("level"),
            "verdict": event.get("verdict"),
            "commands": event.get("commands") or [],
            "baseline": event.get("baseline") or {},
            "criteria_checks": event.get("criteria_checks") or [],
        }
    )


def ledger_integrity(events: list[dict]) -> tuple[bool, str]:
    """Validate the v2 hash chain and immutable execution/acceptance identity.

    A legacy unhashed prefix remains readable. Once a hashed event appears, every later event must
    stay protected; this lets active v1 quests migrate on their next append without rewriting history.
    """
    previous = EMPTY
    protected = False
    execution_id = None
    acceptance_hash = None
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get("_corrupt"):
            return False, f"turn {index}: malformed JSON event"
        hashed = bool(event.get("event_hash"))
        if not hashed:
            if protected:
                return False, f"turn {index}: unhashed event after protected chain"
            previous = event_identity(event)
            continue
        protected = True
        if event.get("prev_event_hash") != previous:
            return False, f"turn {index}: previous event hash mismatch"
        if event.get("event_hash") != event_identity(event):
            return False, f"turn {index}: event hash mismatch"
        previous = str(event["event_hash"])
        current_execution = event.get("execution_id")
        current_acceptance = event.get("acceptance_hash")
        if not current_execution or not current_acceptance:
            return False, f"turn {index}: protected event lacks execution identity"
        execution_id = execution_id or current_execution
        acceptance_hash = acceptance_hash or current_acceptance
        if current_execution != execution_id or current_acceptance != acceptance_hash:
            return False, f"turn {index}: execution or acceptance identity changed"
    return True, "protected" if protected else "legacy"


def _read_text(path: str) -> str:
    """파일을 통째로 읽는다. 오류는 그대로 올린다 — 호출부마다 삼킬 범위가 다르다(없음/깨짐/권한).

    핸들 수명을 여기서 끝내는 것이 요점이다. `open(p).read()`는 CPython의 참조 계수에 기대
    곧장 닫히는 것이고, 그 기댐은 코드에 안 적혀 있어서 다른 런타임에서 조용히 깨진다."""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def repo_root() -> str:
    r = os.environ.get("CLAUDE_PROJECT_DIR")
    if r:
        return r
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return os.getcwd()


def quest_dir(root: str) -> str:
    """.asgard/quest/ — 툴 중립 공유 상태 (failure-tracker와 같은 크로스툴 원칙). .gitignore 자가 설치."""
    d = os.path.join(root, ".asgard")
    os.makedirs(os.path.join(d, "quest"), exist_ok=True)
    gi = os.path.join(d, ".gitignore")
    canonical = "*\n!.gitignore\n!map/\n!map/**\n!asgard-setting-project.json\n"
    current = ""
    try:
        if os.path.exists(gi):
            with open(gi, encoding="utf-8") as handle:
                current = handle.read()
    except Exception:
        current = ""
    if not current or current.strip() == "*":
        try:
            with open(gi, "w", encoding="utf-8") as handle:
                handle.write(canonical)
        except Exception:
            pass
    return os.path.join(d, "quest")


def git(root: str, *args: str, binary: bool = False):
    """(rc, out). 실패는 (rc!=0, '')로 — 호출측이 fail-open 판단.
    color.ui=false 강제 — 사용자 git 설정(color always)의 ANSI 이스케이프가 경로 파싱에
    섞이면 ignored_snapshot 키가 오염된다 (26-07-23 실측: \\x1b[36m이 JSON 키에 잔류)."""
    try:
        p = subprocess.run(["git", "-C", root, "-c", "color.ui=false", *args], capture_output=True, timeout=60)
        out = p.stdout if binary else p.stdout.decode("utf-8", "replace")
        return p.returncode, out
    except Exception:
        return 1, b"" if binary else ""


def snapshot_ref(root: str) -> str | None:
    """Create an unreachable commit for the exact quest-start tree without touching the user's index."""
    rc, raw_head = git(root, "rev-parse", "--verify", "HEAD")
    head = raw_head.decode("utf-8", "replace") if isinstance(raw_head, bytes) else raw_head
    if rc != 0 or not head.strip():
        return None
    fd, index_path = tempfile.mkstemp(prefix="asgard-quest-index-")
    os.close(fd)
    os.unlink(index_path)  # Git expects a missing index path, not an empty invalid index.
    env = {
        **os.environ,
        "GIT_INDEX_FILE": index_path,
        "GIT_AUTHOR_NAME": "Asgard Quest",
        "GIT_AUTHOR_EMAIL": "quest@asgard.local",
        "GIT_COMMITTER_NAME": "Asgard Quest",
        "GIT_COMMITTER_EMAIL": "quest@asgard.local",
    }

    def run(*args: str, input_data: bytes | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", root, *args], input=input_data, capture_output=True, timeout=60, env=env, check=False
        )

    try:
        if run("read-tree", head.strip()).returncode:
            return None
        # `add -- . :(exclude).asgard`는 .asgard를 무시하는 리포에서 rc=1로 죽는다("paths are ignored"):
        # exclude가 붙는 순간 git이 `.`을 명시 경로로 보고 무시된 항목을 오류로 보고한다. 그러면
        # 시작 트리를 못 떠서 **모든 write 퀘스트가 거부**됐다. 그래서 먼저 통째로 담고(무시 파일은
        # git이 알아서 건너뛴다) 색인에서 .asgard만 도로 뺀다 — 결과 트리는 이전과 같다.
        if run("add", "-A", "--", ".").returncode:
            return None
        if os.path.isdir(os.path.join(root, ".asgard", "map")):
            if run("add", "-A", "-f", "--", ".asgard/map").returncode:
                return None
        if run("rm", "--cached", "-r", "-q", "--ignore-unmatch", "--", ".asgard", ":(exclude).asgard/map").returncode:
            return None
        tree = run("write-tree")
        if tree.returncode or not tree.stdout.strip():
            return None
        commit = run(
            "commit-tree", tree.stdout.decode().strip(), "-p", head.strip(), input_data=b"Asgard quest snapshot\n"
        )
        return commit.stdout.decode().strip() if commit.returncode == 0 and commit.stdout.strip() else None
    finally:
        with contextlib.suppress(OSError):
            os.unlink(index_path)


def current_tree_ref(root: str) -> str | None:
    """Materialize the exact current non-control tree in a temporary index without touching the user's index."""
    rc, raw_head = git(root, "rev-parse", "--verify", "HEAD")
    head = raw_head.decode("utf-8", "replace") if isinstance(raw_head, bytes) else raw_head
    if rc != 0 or not head.strip():
        return None
    fd, index_path = tempfile.mkstemp(prefix="asgard-current-index-")
    os.close(fd)
    os.unlink(index_path)
    env = {**os.environ, "GIT_INDEX_FILE": index_path}

    def run(*args: str, input_data: bytes | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", root, *args], input=input_data, capture_output=True, timeout=60, env=env, check=False
        )

    try:
        if run("read-tree", head.strip()).returncode:
            return None
        if run("add", "-A", "--", ".", ":(exclude).asgard").returncode:
            return None
        _, raw_untracked = git(
            root, "ls-files", "--others", "--exclude-standard", "-z", "--", ".", ":(exclude).asgard", binary=True
        )
        if isinstance(raw_untracked, str):
            raw_untracked = raw_untracked.encode("utf-8", "surrogateescape")
        junk = [path for path in raw_untracked.split(b"\0") if path and _junk(path.decode("utf-8", "surrogateescape"))]
        if (
            junk
            and run("update-index", "--force-remove", "-z", "--stdin", input_data=b"\0".join(junk) + b"\0").returncode
        ):
            return None
        if os.path.isdir(os.path.join(root, ".asgard", "map")):
            if run("add", "-A", "-f", "--", ".asgard/map").returncode:
                return None
        tree = run("write-tree")
        return tree.stdout.decode().strip() if tree.returncode == 0 and tree.stdout.strip() else None
    finally:
        with contextlib.suppress(OSError):
            os.unlink(index_path)


# ── 물리 증거 해시 — verifier-gate.py의 diff_state와 알고리즘 동일 유지 (단일 출처 원칙) ──
# 검증 실행 아티팩트 — 검증 명령이 만든 캐시가 PASS를 stale로 만들면 게이트가 자기파괴적이다
# (.gitignore 없는 프로젝트에서 pytest 실행 → __pycache__ → hash 변경, s1 라이브 실측).
# lagom: 고정 목록 — 정책 파일로 빼면 exclude 확대가 게이트 우회 벡터가 되므로 하드코딩 유지.
# ".cache": 리포 안 XDG 캐시 (CC 샌드박스가 UV_CACHE_DIR를 cwd/.cache/uv로 주입) — uv 캐시
# 전체가 ignored_snapshot에 해시로 실려 퀘스트 로그 1.5MB 블롯이 됐다 (26-07-23 실측).
_JUNK_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox", "node_modules", ".venv", ".cache"}
# 두 목록을 나눠 두는 이유 — 두 소비처가 보는 파일 집합이 다르다.
# `_junk`는 current_tree_ref에서 **추적되지 않은**(`ls-files --others --exclude-standard`,
# `--ignored` 없음) 파일을 트리 스냅샷에서 뺀다. 여기를 넓히면 gitignore되지 않은 새 소스
# `build/x.py`가 스냅샷에서 사라져 diff 해시에 안 잡힌다 — 게이트가 증거를 못 보는 구멍이다.
# `_generated`는 ignored_state에서 **이미 무시된** 파일만 본다. 무시된 빌드 산출물은 증거가
# 아니고, 빼지 않으면 비용이 워크트리 크기에 묶인다: cargo 릴리스 빌드 하나가 해시 대상을
# 31MB에서 2,371MB로 올려 ignored_state가 51ms에서 1,257ms가 됐고, 그 값을 state·next·
# verifier-gate 세 자리가 매 턴 따로 문다 (26-08-04 실측).
_GENERATED_DIRS = _JUNK_DIRS | {"target", "dist", "build", ".next", ".gradle", "coverage", "htmlcov"}


def _junk(p: str) -> bool:
    return p.endswith((".pyc", ".pyo")) or any(seg in _JUNK_DIRS for seg in p.split("/"))


def _generated(p: str) -> bool:
    return p.endswith((".pyc", ".pyo")) or any(seg in _GENERATED_DIRS for seg in p.split("/"))


def reconcile_ignored(root: str, ignored_base: dict[str, str] | None, digest) -> list[str]:
    """무시 파일의 기준선↔현재 대조. 바뀐 경로를 돌려주고 그 내역을 digest에 먹인다.

    verifier_gate.py의 같은 이름 함수와 동일 유지 (단일 출처 원칙 — 어긋나면 영구 stale).
    ignored_base가 None이면 대조 대상이 없다는 뜻이라 빈 목록."""
    if ignored_base is None:
        return []
    # 기준선도 현재와 같은 _generated를 태운다. 안 그러면 목록이 넓어진 순간, 열려 있던 퀘스트의
    # 스냅샷에만 남은 경로가 전부 "사라짐 = 변경"으로 읽혀 PASS가 통째로 stale이 된다
    # (26-08-04: target 추가 시 changed_files 8,118건).
    base = {path: value for path, value in ignored_base.items() if not _generated(path)}
    current = ignored_state(root)
    changed = sorted(path for path in set(base) | set(current) if base.get(path) != current.get(path))
    for path in changed:
        digest.update(
            b"ignored\0"
            + path.encode("utf-8", "surrogateescape")
            + b"\0"
            + str(base.get(path, "<missing>")).encode()
            + b"\0"
            + str(current.get(path, "<missing>")).encode()
        )
    return changed


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
    """Hash only the link identity; never open or consume an external target as evidence."""
    target = os.readlink(path).encode(errors="surrogateescape")
    return b"<unsafe-symlink>\0" + target


def sensitive_path(path: str, needles) -> bool:
    """경로 세그먼트/토큰 기준 민감 매칭 — 나이브 substring은 'ci'가 circle.py를,
    4자+ substring은 'auth'가 oauth.py·author.py를, 'install'이 installer_utils를 오탐해
    작은 수정 하나가 full-verify+티어 승격으로 흘렀다 (26-07-23 감사). 규칙: 세그먼트 정확
    일치, 또는 세그먼트를 [._-]로 쪼갠 토큰 정확 일치 (auth.py→auth, db_pool→db). 파생형은
    needle 목록에 명시한다 (authentication 등 — DEFAULT_POLICY).
    verifier_gate.py의 sensitive_path와 동일 유지 (단일 출처 원칙 — 어긋나면 게이트↔전이 판정 분열)."""
    segs = path.lower().split("/")
    for n in needles:
        n = str(n).lower()
        if any(seg == n or n in re.split(r"[._\-]", seg) for seg in segs):
            return True
    return False


def ignored_state(root: str) -> dict[str, str]:
    """Hash ignored non-generated files without following symlinks, so they cannot evade quest binding."""
    rc, raw = git(
        root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
        ".",
        ":(exclude).asgard",
        binary=True,
    )
    if rc != 0:
        return {"<snapshot-unavailable>": "ignored-enumeration-failed"}
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "surrogateescape")
    out: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item:
            continue
        path = item.decode("utf-8", "surrogateescape")
        if _generated(path):
            continue
        full = os.path.join(root, path)
        try:
            info = os.lstat(full)
            if stat.S_ISLNK(info.st_mode):
                body = b"<symlink>\0" + os.readlink(full).encode("utf-8", "surrogateescape")
                out[path] = hashlib.sha256(body).hexdigest()
            elif stat.S_ISREG(info.st_mode):
                digest = hashlib.sha256()
                with open(full, "rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                out[path] = digest.hexdigest()
            else:
                out[path] = f"<nonregular:{stat.S_IFMT(info.st_mode):o}>"
        except OSError:
            out[path] = "<missing>"
    return out


def diff_state(
    root: str, base_ref: str | None, ignored_base: dict[str, str] | None = None
) -> tuple[str, list[str], int, int]:
    """(diff_hash, changed_files, changed_lines, nontest_lines) — base_ref 트리 ↔ 현재 워킹트리 전체.
    커밋 여부와 무관 (base_ref는 open 시점 고정 커밋). `.asgard/**` 제외 — 로그 기록 자체가
    diff를 바꾸면 해시가 자기참조로 영원히 안 맞는다.
    nontest_lines: 테스트 파일 제외 변경 라인 — 테스트 추가는 검증 표면이지 리스크 질량이 아니다
    (스모크 벤치 발견: 잠금 테스트 2파일 추가가 big 판정 → 게이트-우선 무력화). 삭제된 테스트는
    별도 하드 트리거 (deleted_tests)."""
    if not base_ref or base_ref == "NONE":
        return EMPTY, [], 0, 0
    current_ref = current_tree_ref(root)
    if not current_ref:
        return hashlib.sha256(b"snapshot-unavailable").hexdigest(), ["<snapshot-unavailable>"], 0, 0
    spec = [base_ref, current_ref, "--", ".", ":(exclude).asgard"]
    rc, diff = git(root, "diff", "--binary", *spec, binary=True)
    if rc != 0:
        return EMPTY, [], 0, 0
    if isinstance(diff, str):
        diff = diff.encode()
    _, names = git(root, "diff", "--name-only", *spec)
    names = names.decode(errors="replace") if isinstance(names, bytes) else names
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
            after = symlink_map_state(full_path) if is_link else _read_bytes(full_path)
        except OSError:
            after = None
        if (before if before_rc == 0 else None) != after:
            map_changed.append(p)
            diff += p.encode("utf-8", "surrogateescape") + b"\0" + (after if after is not None else b"<deleted>")
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
    h = hashlib.sha256(diff)
    ignored_changed = reconcile_ignored(root, ignored_base, h)
    changed = sorted(set(n for n in names.splitlines() if n.strip()) | set(map_changed) | set(ignored_changed))
    return (h.hexdigest() if changed else EMPTY), changed, lines, nt_lines


# ── 하네스 소유 베이스라인 체크 — 증거 '품질'의 결정론화 ──
# 기존 pass_evidence는 증거 '존재'만 봤다 — 어떤 명령이었는지는 verifier LLM 재량이라 `echo ok`
# 도 증거가 됐다 (깊이벤치 실증). 여기서는 하네스가 직접 프로젝트 체크를 실행해 exit code를
# 기록한다 — LLM-as-judge 불신 원칙 (결정론 룰 피드백이 최상위 증거, Anthropic SDK 가이드).
# stdin으로 들어온 baseline은 normalize가 버린다 — 이 코드만이 유일한 기록 경로 (위조 차단).


# Repository policy is untrusted input. A trivial command can erase the LLM Verifier,
# and shell composition can mutate/exfiltrate from the deterministic harness.
SAFE_CHECK_PREFIXES = (
    "pytest ",
    "python -m pytest ",
    "python3 -m pytest ",
    "python -m compileall ",
    "python3 -m compileall ",
    "python -m unittest ",
    "python3 -m unittest ",
    "uv run pytest ",
    "uv run ruff check ",
    "uv run ruff format --check ",
    "uv run ty check",
    "poetry run pytest ",
    "pdm run pytest ",
    "ruff check ",
    "ruff format --check ",
    "mypy ",
    "pyright ",
    "ty check",
    "npm test",
    "npm run test",
    "pnpm test",
    "yarn test",
    "cargo test",
    "cargo check",
    "go test",
    "make test",
    "make check",
    "make verify",
    "test ",
    "false",
)
_PY_EXE = re.compile(r"^python[0-9.]*$")
_SAFE_MODULES = {"pytest", "compileall", "py_compile", "unittest"}


def _strip_env_prefix(tokens: list[str]) -> list[str]:
    """선행 `VAR=…` 대입과 `env` 래퍼를 벗긴 나머지 — 신원은 그 뒤부터다."""

    def drop_assignments(rest: list[str]) -> list[str]:
        while rest and "=" in rest[0] and not rest[0].startswith(("=", "-")):
            rest = rest[1:]
        return rest

    tokens = drop_assignments(tokens)
    if tokens and os.path.basename(tokens[0]) == "env":
        tokens = drop_assignments(tokens[1:])
    return tokens


def runner_shape(cmd: str) -> str:
    """안전 프리픽스와 대조할 정규형 — **판정 전용**이다 (실행은 언제나 원문으로 한다).

    같은 검증을 부르는 정당한 표기가 표를 못 넘어 **조용히 버려지던** 것을 막는다: 절대경로
    인터프리터(`/…/.venv/bin/python -m pytest`)·버전 붙은 인터프리터(`python3.13 -m pytest`)가
    그 예다 (26-07-31 실측: 명시 설정 하나가 통째로 사라져 `checks_available`이 false가 됐고,
    게이트의 유일한 독립 증거 레인이 아무 말 없이 침묵했다).

    넓히되 열지는 않는다 — 경로가 붙은 실행자는 **`.venv/bin/` 아래이거나, `-m <안전 모듈>`을
    부르는 인터프리터**일 때만 이름으로 접는다. `./pytest` 같은 저장소 안 파일을 이름으로 접어
    주면, clone으로 딸려 오는 정책 파일(`.asgard/trinity-policy.json`)이 곧 임의 실행 통로가 된다."""
    try:
        tokens = _strip_env_prefix(shlex.split(cmd, posix=True))
    except ValueError:
        return cmd
    if not tokens:
        return cmd
    head = tokens[0]
    base = os.path.basename(head)
    interpreter = bool(_PY_EXE.match(base))
    safe_module = interpreter and len(tokens) >= 3 and tokens[1] == "-m" and tokens[2] in _SAFE_MODULES
    if "/" in head:
        if not (head.startswith(".venv/") or "/.venv/bin/" in head or safe_module):
            return cmd  # 저장소 안 실행 파일일 수 있다 — 이름으로 접지 않는다
        head = base
    if interpreter:
        if not safe_module and head != "python":
            return cmd  # 버전 붙은 인터프리터로 **스크립트**를 부르는 형태는 접지 않는다
        head = "python"
    return shlex.join([head, *tokens[1:]])


def configured_checks(policy: dict) -> tuple[list[str], list[str]]:
    """명시 `baseline_checks`를 (받아들인 것, 거부한 것)으로 가른다.

    거부를 **돌려주는** 것이 요점이다. 조용히 버리면 게이트가 무장해제된 줄 아무도 모른다 —
    설정한 사람은 체크가 도는 줄 알고, 게이트는 독립 증거 없이 모델 신고를 그대로 받는다."""
    accepted: list[str] = []
    rejected: list[str] = []
    for raw in policy.get("baseline_checks") or []:
        cmd = str(raw).strip()
        if not cmd:
            continue
        shape = runner_shape(cmd)
        ok = (
            not trivial_evidence(cmd)
            and "\n" not in cmd
            and not any(token in cmd for token in (";", "&&", "||", "`", "$(", ">", "<"))
            and any(shape == prefix.rstrip() or shape.startswith(prefix) for prefix in SAFE_CHECK_PREFIXES)
        )
        (accepted if ok else rejected).append(cmd)
    return accepted, rejected


def rejected_checks(policy: dict) -> list[str]:
    """정책에 적혔지만 안전 표를 못 넘어 **실행되지 않는** 체크 — doctor·state가 이걸 말한다."""
    return configured_checks(policy)[1]


def detect_checks(root: str, policy: dict) -> list[str]:
    """정책 baseline_checks 우선. 없으면 보수적 자동 감지 — pytest만.
    lagom: lint 류 자동 감지 안함 — 기존 위반 false-red가 게이트 인질이 된다. 명시 설정으로만.
    uv 프로젝트(uv.lock)는 `uv run pytest`로 — PATH pytest는 venv 밖이라 수집 실패(2/3/4→skip)로
    게이트가 조용히 무력화되고, pytest가 .venv 안에만 있으면 아예 미감지된다. uv의 spawn 실패는
    exit 2라 pytest 미의존 프로젝트도 skip 분류로 fail-open이 유지된다."""
    if policy.get("baseline_checks"):
        return configured_checks(policy)[0]
    import shutil

    if any(os.path.exists(os.path.join(root, p)) for p in ("tests", "test", "pytest.ini", "pyproject.toml")):
        if os.path.exists(os.path.join(root, "uv.lock")) and shutil.which("uv"):
            return ["uv run pytest -x -q"]
        if shutil.which("pytest"):
            return ["pytest -x -q"]
    return _detect_node_checks(root)


def _detect_node_checks(root: str) -> list[str]:
    """JS/TS 저장소의 행위 베이스라인 — package.json의 test 스크립트.

    자동감지가 pytest 전용이던 탓에 JS/TS 저장소는 `baseline_checks`를 손으로 넣지 않으면
    **하네스 실행 증거 레인이 통째로 꺼진 채** 돌았다 (26-07-26 helios 실측: PASS가 diff 정독과
    `node --check` 문법 검사에 얹혔다). 보수 조건 두 개를 함께 요구한다: ① 실제 test 스크립트가
    선언돼 있고 ② 의존성이 이미 설치돼 있다(node_modules). 미설치 상태의 러너 실패는 exit 1이라
    테스트 실패와 구분되지 않아 false-red로 게이트를 인질로 잡기 때문이다 — 그 경우는 명시 설정만."""
    import json as _json
    import shutil

    manifest = os.path.join(root, "package.json")
    if not os.path.exists(manifest) or not os.path.isdir(os.path.join(root, "node_modules")):
        return []
    try:
        with open(manifest, encoding="utf-8") as handle:
            scripts = (_json.load(handle) or {}).get("scripts") or {}
    except Exception:
        return []
    if not str(scripts.get("test") or "").strip():
        return []
    for lockfile, manager in (
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("package-lock.json", "npm"),
        ("bun.lock", "npm"),
    ):
        if os.path.exists(os.path.join(root, lockfile)) and shutil.which(manager):
            return [f"{manager} test"]
    return ["npm test"] if shutil.which("npm") else []


def gate_first_checks_available(root: str, policy: dict) -> bool:
    """Only behavior test runners may replace an LLM Verifier; lint/compile/artifact checks may not."""
    for command in detect_checks(root, policy):
        words = command.split()
        if "pytest" in words or words[:2] in (["npm", "test"], ["pnpm", "test"], ["yarn", "test"]):
            return True
        if words[:2] in (["cargo", "test"], ["go", "test"]):
            return True
    return False


def fail_lines(stdout: bytes | None, stderr: bytes | None, limit: int = 5) -> list[str]:
    """실패한 체크 출력에서 정형 실패 줄만 추출 — 이유 없는 red를 만들지 않는다 (바운디드 증거).
    pytest 요약 줄(FAILED/ERROR ...) 우선, 없으면 출력 꼬리 3줄. 줄당 200자·최대 limit 줄 —
    수리 턴이 '무엇이 왜 깨졌는지'를 exit code 만으로 추측하지 않게 한다."""
    text = b"\n".join(s for s in (stdout, stderr) if s).decode("utf-8", "replace")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hits = [ln for ln in lines if ln.startswith(("FAILED ", "ERROR ")) or "AssertionError" in ln]
    return [ln[:200] for ln in (hits or lines[-3:])[:limit]]


def _timed_out_before(events: list[dict], cmd: str) -> bool:
    """이 퀘스트에서 이미 시간을 다 쓰고 끊긴 체크인가.

    timeout 은 red 도 green 도 아니라 증거 없음이다 (run_baseline 의 skip 규약). 그래서 다시
    돌려도 판정은 한 글자도 안 바뀌고, append 마다 baseline_timeout 만큼 더 기다리기만 한다.
    26-08-04 실측: 이 저장소의 `uv run pytest -x -q` 는 615s 인데 baseline_timeout 은 120s 라
    verify append 가 매번 120s 를 태우고 아무 증거도 못 얻었다."""
    return any(_timed_out_row((event.get("baseline") or {}).get("results"), cmd, 120) for event in events)


def _timed_out_row(rows, cmd: str, width: int) -> bool:
    """기록된 실행 행 중 이 명령이 timeout 으로 끊긴 것이 있는가. width 는 그 표면의 cmd 절단 길이."""
    return any(isinstance(r, dict) and r.get("timed_out") and r.get("cmd") == cmd[:width] for r in rows or [])


def _contract_timed_out_before(events: list[dict], cmd: str) -> bool:
    """이 퀘스트에서 이미 timeout 으로 끊긴 계약 명령인가 (run_criteria_checks 쪽 기록 형상)."""
    return any(_timed_out_row(event.get("criteria_checks"), cmd, 200) for event in events)


def run_baseline(root: str, policy: dict, events: list[dict], diff_hash: str) -> dict | None:
    """체크 전부 실행 → {"state": green|red|none, "results": [...]}. 체크 없음 → None (요건 면제).
    같은 diff_hash의 기존 verify 기록은 재사용 — 동일 트리에 pytest를 두 번 돌리지 않는다.
    skip(127 미설치·pytest 5 수집 없음·timeout)은 red 아님 — 게이트는 자기기만 방어지 인질극 장치가
    아니다 (verifier_gate.py 서두와 같은 원칙). lagom: timeout=skip은 보호 약화 — 느린 스위트는
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
        if _timed_out_before(events, cmd):
            results.append({"cmd": cmd[:120], "exit_code": None, "secs": 0.0, "timed_out": True, "memo": True})
            continue
        t0 = time.time()
        code: int | None
        p = None
        timed_out = False
        try:
            p = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, timeout=timeout)
            code = p.returncode
        except subprocess.TimeoutExpired:
            code, timed_out = None, True  # skip 취급 (fail-open) — 다음 append 는 memo 로 건너뛴다
        except Exception:
            code = None  # 그 밖의 실행 실패도 skip
        row: dict = {"cmd": cmd[:120], "exit_code": code, "secs": round(time.time() - t0, 1)}
        if timed_out:
            row["timed_out"] = True
        results.append(row)
        # skip = 체크가 "돌 수 없었다": 127 미설치 · pytest 5 수집 없음 · timeout. 자동 감지 pytest는
        # 2/3/4(수집·사용법 오류 — venv 밖 pytest가 흔한 원인)도 skip — 환경 문제를 코드 red로
        # 오판해 게이트가 인질 잡는 것 방지. 명시 설정 체크는 사용자가 커맨드를 보증하므로 엄격 판정.
        if code is None or code == 127 or ("pytest" in cmd.split() and (code == 5 or (auto and code in (2, 3, 4)))):
            continue
        if code != 0:
            if p is not None:
                fails = fail_lines(p.stdout, p.stderr)
                if fails:
                    row["fails"] = fails  # 정형 실패 줄 — 게이트 사유·수리 턴 컨텍스트로 흐른다
            state = "red"
            break  # 첫 red에서 중단 — 나머지는 수리 후 어차피 재실행
        state = "green"
    return {"state": state, "results": results}


def _testfile(p: str) -> bool:
    segs = p.lower().split("/")
    return "tests" in segs or "test" in segs or segs[-1].startswith("test_") or segs[-1].endswith("_test.py")


def deleted_tests(root: str, base_ref: str | None) -> list[str]:
    """base_ref 이후 삭제된 테스트 파일 — 테스트를 지워 green을 사는 경로 차단 (anti-Goodhart,
    Anthropic feature-ledger "removing tests is unacceptable" analog). 삭제만 본다 — 테스트 수정은
    정상 작업이라 전부 full로 올리면 세금이 되레 는다. verifier_gate.py와 동일 유지 (단일 출처 원칙).

    현재 쪽도 트리로 맞댄다 (diff_state와 같은 형상). base_ref는 미추적 파일까지 담은 트리라
    (snapshot_ref의 `add -A`) 색인과 맞대면 디스크에 멀쩡히 있는 미추적 파일이 전부 삭제로
    잡힌다 — 미추적 테스트 파일 하나가 모든 쓰기 퀘스트를 full Verifier로 올린다 (26-08-04
    실측: 이 저장소의 미추적 테스트 4개가 24줄 변경을 full로 올렸다). 현재 트리를 못 뜨면
    종전 비교로 남는다 — 과다 트리거는 안전한 방향이다."""
    if not base_ref or base_ref == "NONE":
        return []
    current_ref = current_tree_ref(root)
    refs = [base_ref, current_ref] if current_ref else [base_ref]
    _, out = git(root, "diff", "--name-only", "--diff-filter=D", *refs, "--", ".", ":(exclude).asgard")
    return [p for p in out.splitlines() if p.strip() and _testfile(p)]


def trivial_evidence(cmd) -> bool:
    """verifier_gate.py의 trivial_evidence와 동일 유지 (단일 출처 원칙) — `true` 한 방이 PASS
    증거로 성립하던 Goodhart 구멍 봉합: 무조건 exit 0 이거나 관찰만 하는 명령은 검증 증거가 아니다."""
    try:
        tokens = shlex.split(str(cmd), posix=True)
    except ValueError:
        return True
    if not tokens:
        return True
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"|", "||", "&&", ";"}:
            segments.append([])
        else:
            segments[-1].append(token)
    observational = {
        ":",
        "awk",
        "cat",
        "date",
        "echo",
        "file",
        "find",
        "head",
        "ls",
        "od",
        "printf",
        "pwd",
        "sed",
        "sleep",
        "stat",
        "tail",
        "tree",
        "true",
        "type",
        "wc",
        "which",
        "whoami",
        "xxd",
    }
    for segment in segments:
        while segment and ("=" in segment[0] and not segment[0].startswith(("=", "-"))):
            segment = segment[1:]
        if not segment:
            continue
        head = os.path.basename(segment[0])
        if head in {"sh", "bash", "zsh"} and any(flag in segment for flag in ("-c", "-lc")):
            index = next(i for i, token in enumerate(segment) if token in ("-c", "-lc"))
            if index + 1 < len(segment) and not trivial_evidence(segment[index + 1]):
                return False
            continue
        if head == "git":
            sub = next((token for token in segment[1:] if not token.startswith("-")), "")
            if sub == "diff" and any(flag in segment for flag in ("--check", "--quiet", "--exit-code")):
                return False
            if sub in {"grep", "rev-parse"}:
                return False
            continue
        if head not in observational and not (head == "exit" and segment[1:] == ["0"]):
            return False
    return True


_GIT_INSPECT_SUBS = {"status", "diff", "log", "show", "ls-files"}


def inspection_evidence(cmd) -> bool:
    """워킹트리 상태를 직접 관측하는 read-only git 명령 — 무변경(diff 0) 퀘스트 한정 PASS 증거.

    trivial 필터는 '아무 exit 0 명령'이 증거로 성립하는 Goodhart를 막는 축이고, 이 판정은
    별개 축이다: '변경 없음' 주장의 올바른 검증은 트리 관측(git status/diff) 그 자체인데,
    관측 명령이 전부 trivial로 걸러지면 무변경 퀘스트는 영원히 PASS가 불가능한 교착이 된다
    (26-07-21 "안녕" 실측 — Verifier PASS 5연속 무효화 후 예산 소진)."""
    try:
        tokens = shlex.split(str(cmd), posix=True)
    except ValueError:
        return False
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"|", "||", "&&", ";"}:
            segments.append([])
        else:
            segments[-1].append(token)
    for segment in segments:
        while segment and ("=" in segment[0] and not segment[0].startswith(("=", "-"))):
            segment = segment[1:]
        if not segment or os.path.basename(segment[0]) != "git":
            continue
        sub, rest, index = "", segment[1:], 0
        while index < len(rest):
            token = rest[index]
            if token in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
                index += 2  # 옵션 인자 스킵 — `git -C <path> status`의 <path> 를 sub로 오인 금지
                continue
            if token.startswith("-"):
                index += 1
                continue
            sub = token
            break
        if sub in _GIT_INSPECT_SUBS:
            return True
    return False


# ── criteria verify 계약 — 기준별 검증 명령·산출물 결속 ──
# criteria 문자열에 옵트인 계약을 얹는다: "<설명> | verify: <명령> | artifacts: <경로...>".
# 계약이 선언되면 "아무 nontrivial 명령 exit 0"은 더 이상 그 기준의 증거가 아니다 — 하네스가
# 계약 명령을 직접 실행해 기록하고(모델 신고 exit code 불신, baseline과 동일 원칙), 퍼널이
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
                desc = desc + " | " + p  # 계약 키워드가 아닌 ' | '는 설명의 일부
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


def contract_criteria(*sources) -> list:
    """계약 추출 원본 — 문자열 항목을 실은 첫 후보. verifier_gate.py와 동일 유지.

    계약은 `"<설명> | verify: <명령>"` 문자열에만 담긴다. 그런데 판정자는 기준별 판정을
    `[{"id":..,"status":"met","evidence":..}]` 객체로 함께 보낸다 — 역할 계약이 그것을 요구한다.
    그 객체를 계약 원본으로 쓰면 계약이 0건으로 보여 하네스가 계약 명령을 실행하지 않는데,
    게이트는 퀘스트 선언(문자열)에서 계약을 계속 읽으므로 영구 미충족이 된다 (26-07-26 실측:
    CC 모드에서 `criteria-unverified`로 Stop이 막혀 세션이 49분간 종료하지 못했다).
    형태로 원본을 고르면 두 경로가 같은 계약을 본다.

    형태만으로는 부족하다 — 판정자는 같은 기준별 판정을 **문자열 목록**으로도 보낸다(역할 계약이
    산문 판정을 허용한다). 그러면 계약을 한 줄도 안 실은 원본이 먼저 잡혀 26-07-26 과 똑같은
    영구 미충족이 다른 문으로 되살아난다 (26-08-04 실측: 판정자가 기준 6건을 산문 문자열로 보내
    close 가 `criteria-unverified` 로 두 번 거부됐다). 그래서 계약을 실은 원본을 먼저 고르고,
    어디에도 없을 때만 첫 문자열 원본으로 물러선다."""
    string_sources = [s for s in ([c for c in (src or []) if isinstance(c, str)] for src in sources) if s]
    for strings in string_sources:
        if any(c["verify_cmd"] for c in criteria_contracts(strings)):
            return strings
    return string_sources[0] if string_sources else []


def unmet_contracts(root: str, criteria, rec: dict) -> list[str]:
    """PASS 레코드(rec) 기준 미충족 계약 목록. 명령은 하네스 기록(criteria_checks)의 exit 0만 인정,
    산출물은 지금(호출 시점) 존재를 라이브 재확인 — 산출물은 .gitignore로 diff-hash 밖일 수 있어
    stale 검사가 삭제를 못 잡는다. 계약이 있는데 기록이 없으면(구버전 이벤트) 미충족 — 재검증 유도."""
    unmet = []
    rows = [c for c in (rec.get("criteria_checks") or []) if isinstance(c, dict)]
    checks = {(" ".join(str(c.get("cmd", "")).split())): c.get("exit_code") for c in rows}
    stalled = {" ".join(str(c.get("cmd", "")).split()) for c in rows if c.get("timed_out")}
    for c in criteria_contracts(criteria):
        cmd = c["verify_cmd"]
        if cmd and checks.get(" ".join(cmd.split())) != 0:
            # timeout 은 실패와 다르다. 그대로 미충족이지만(기준 유지) 이유를 실패로 적으면 수리 턴이
            # 멀쩡한 코드를 고치러 가고 계약은 영영 안 채워진다 — 고칠 곳은 명령이나 baseline_timeout 이다.
            if " ".join(cmd.split()) in stalled:
                unmet.append(f"verify: {cmd} (timed out — narrow the command or raise baseline_timeout)")
            else:
                unmet.append("verify: " + cmd)
        for a in c["artifacts"]:
            if not os.path.exists(os.path.join(root, a)):
                unmet.append("artifact: " + a)
    return unmet


def baseline_ran(root: str, policy: dict, baseline: dict | None) -> dict[str, dict]:
    """이번 판정에서 baseline 이 이미 돌린 명령 → 그 실행 행 (정규화된 명령이 키다).

    두 판정 경로(append·verify-baseline)가 각자 이 짝을 세우면 한쪽만 고쳐진다 — 실제로 그랬다.
    baseline 은 detect_checks 순서대로 돌고 첫 red 에서 멈추므로 zip 이 실행된 만큼만 짝짓는다."""
    return {
        " ".join(cmd.split()): row
        for cmd, row in zip(detect_checks(root, policy), (baseline or {}).get("results") or [])
        if isinstance(row, dict)
    }


def run_criteria_checks(
    root: str, policy: dict, criteria, events: list[dict], diff_hash: str, ran: dict[str, dict] | None = None
) -> list[dict] | None:
    """계약 명령을 하네스가 직접 실행해 기록 — stdin 위조는 normalize가 버리고 이 코드만이
    기록 경로 (baseline과 동일). 같은 diff_hash의 기존 기록은 재사용. 계약 없음 → None (요건 면제).

    `ran`은 이번 append 에서 baseline 이 이미 돌린 명령의 결과다(정규화 명령 → 실행 행). 계약이
    baseline 체크와 같은 명령이면 — `verify: uv run pytest -q` 처럼 흔하다 — 같은 트리에서 같은
    스위트를 한 번 더 돌릴 이유가 없다. 물리적으로 같은 실행이고 둘 다 하네스 소유 기록이라
    판정은 그대로고 append 시간만 절반이 된다."""
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
        cmd = c["verify_cmd"]
        shared = (ran or {}).get(" ".join(cmd.split()))
        if shared and shared.get("exit_code") is not None:
            results.append({**shared, "cmd": cmd[:200], "shared": True})
            continue
        if _contract_timed_out_before(events, cmd):
            # 계약 명령이 timeout 보다 느리면 그 계약은 이 설정으로는 영영 충족될 수 없다. 미충족은
            # 그대로 두되(기준 유지) 같은 대기를 append 마다 다시 사지는 않는다 — 판정은 안 바뀌고
            # 재검증 턴마다 timeout 만큼만 늘어나던 자리다.
            results.append({"cmd": cmd[:200], "exit_code": None, "secs": 0.0, "timed_out": True, "memo": True})
            continue
        t0 = time.time()
        code: int | None
        timed_out = False
        try:
            p = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, timeout=timeout)
            code = p.returncode
        except subprocess.TimeoutExpired:
            code, timed_out = None, True
        except Exception:
            code = None  # 미충족 취급 (계약은 명시 선언이라 skip 면제 없음)
        row: dict = {"cmd": cmd[:200], "exit_code": code, "secs": round(time.time() - t0, 1)}
        if timed_out:
            row["timed_out"] = True
        results.append(row)
    return results


def pass_evidence(rec: dict, *, no_change: bool = False) -> bool:
    """PASS 레코드의 성공 명령 증거 — trivial 명령 제외 (verifier_gate.py와 동일 유지).
    하네스가 직접 돌린 베이스라인 green·전 계약 성공(criteria_checks)은 그 자체가 물리 증거 —
    trivial 필터는 모델이 고른 명령에만 적용한다 (둘 다 하네스 소유 기록, 모델 위조 불가).
    no_change=True (하네스 관측 diff가 EMPTY) 면 트리 관측 명령(git status/diff)도 증거다 —
    무변경 주장에는 관측이 곧 검증이며, 아니면 no-op 퀘스트가 영구 FAIL로 교착한다."""
    if (rec.get("baseline") or {}).get("state") == "green":
        return True
    checks = [c for c in (rec.get("criteria_checks") or []) if isinstance(c, dict)]
    if checks and all(c.get("exit_code") == 0 for c in checks):
        return True  # 계약 명령 전부 성공 — 하네스가 직접 실행한 기록
    if no_change and any(
        isinstance(c, dict) and c.get("exit_code") == 0 and inspection_evidence(c.get("cmd", ""))
        for c in (rec.get("commands") or [])
    ):
        return True
    return any(
        isinstance(c, dict) and c.get("exit_code") == 0 and not trivial_evidence(c.get("cmd", ""))
        for c in (rec.get("commands") or [])
    )


_SIG_PAT = re.compile(r"^-\s*(def |class |function |export |public |fn |return\b|yield\b)")


def signature_risk(root: str, base_ref: str | None) -> bool:
    """diff에 삭제·변경된 공개 선언·반환 라인 존재 여부 — 숨은-caller/값 형태 리스크 신호.
    '-' 라인만 본다: 신규 추가(+def)는 기존 caller가 없고, 바뀐 줄은 기존 '-' 절반이 잡힌다.
    게이트-우선(STANDARD) 라우팅 전용 — verifier_gate 대응 불필요.

    현재 쪽을 트리로 맞대는 이유는 deleted_tests와 같다 — 색인과 맞대면 미추적 파일이 통째로
    '-' 라인이 되어 있지도 않은 시그니처 삭제가 잡힌다."""
    if not base_ref or base_ref == "NONE":
        return False
    current_ref = current_tree_ref(root)
    refs = [base_ref, current_ref] if current_ref else [base_ref]
    rc, out = git(root, "diff", "-U0", *refs, "--", ".", ":(exclude).asgard")
    if rc != 0:
        return False
    return any(_SIG_PAT.match(line) for line in out.splitlines())


def _rel_to_root(root: str, path) -> str:
    """세션 write 저널의 절대 경로를 리포 상대 경로로 — 귀속 집합 멤버십은 상대 경로 기준."""
    p = str(path)
    if not os.path.isabs(p):
        return p
    rp = os.path.realpath(root)
    ap = os.path.realpath(p)
    return os.path.relpath(ap, rp) if ap == rp or ap.startswith(rp + os.sep) else p


def quest_owned_files(root: str, events: list[dict]) -> set[str]:
    """퀘스트 귀속 파일 — work 이벤트의 changed_files(세션 관측 write) ∪ 참여 세션 write 저널.
    verify 이벤트의 changed_files는 전 트리 diff라 타 세션 잔여물이 섞인다 — 소유 근거 아님."""
    owned = {
        _rel_to_root(root, p)
        for e in events
        if e.get("event") == "work"
        for p in (e.get("changed_files") or [])
        if str(p).strip()
    }
    for sid in {str(e.get("session_id")) for e in events if e.get("session_id")}:
        try:
            with open(os.path.join(root, ".asgard", "state", f"writes-{sid}.json"), encoding="utf-8") as handle:
                journal = json.load(handle)
            owned.update(_rel_to_root(root, p) for p in journal if str(p).strip())
        except Exception:
            pass
    return owned


UNSCOPED_DRIFT = "<unscoped>"  # 귀속을 못 따진 fail-safe stale — 경로가 아니라 사유 표시다


def stale_pass_scope(root: str, last_pass: dict, events: list[dict], current_changed) -> tuple[list[str], list[str]]:
    """(stale 을 만든 파일, 범위 밖 드리프트) — PASS 이후 트리 변화의 퀘스트 귀속 판정.

    첫 값은 비었을 때 falsy 라 `if stale:` / `not stale` 로 그대로 읽힌다. 목록으로 돌려주는
    이유는 게이트가 차단을 기록할 때 **무엇이 드리프트했는지**까지 남겨야 하기 때문이다 —
    사유 코드만 남기면 stale-pass 가 게이트 마찰의 최대 항목인데도(26-08-04 실측 45건 중 20건)
    기록만 보고는 무엇을 고칠지 알 수 없다. 귀속을 못 따진 fail-safe 경로는 경로 대신
    `UNSCOPED_DRIFT` 한 항목을 담는다 — 그 자리는 "닿은 파일을 못 셌다"이지 "파일 하나"가 아니다.

    전 트리 해시 불일치를 전부 stale로 보면 병렬 세션 쓰기·빌드 아티팩트 1건이 full 재검증을
    재소환하고, 트리가 움직이는 한 예산까지 반복된다 (26-07-21 실측: 타 세션 파일 34개로
    read-only 퀘스트 4연속 FAIL). 판정 범위 = 퀘스트 귀속 파일 원칙(retry 프롬프트와 동일)을
    해시 기계에도 적용한다: PASS 시점 tree_ref ↔ 현재 트리의 변경 경로 중 귀속 파일
    (work 관측 ∪ 세션 write 저널) 또는 관리 지도에 닿은 것만 stale.

    fail-safe: tree_ref 없는 구 로그·귀속 집합 공집합·트리 계산 실패는 종전 엄격 판정(stale).
    한계(문서화): 같은 이름 ignored 파일의 내용만 바뀐 드리프트는 트리 밖이라 못 본다 —
    이름 수준(등장/소멸)은 changed 목록 대칭차로 보수 편입한다."""
    pass_tree = str(last_pass.get("tree_ref") or "")
    owned = quest_owned_files(root, events)
    if not pass_tree or not owned:
        return [UNSCOPED_DRIFT], []
    cur_tree = current_tree_ref(root)
    if not cur_tree:
        return [UNSCOPED_DRIFT], []
    rc, names = git(root, "diff", "--name-only", pass_tree, cur_tree)
    if rc != 0:
        return [UNSCOPED_DRIFT], []
    drift = {n for n in names.splitlines() if n.strip()}
    drift |= set(map(str, current_changed or [])) ^ {str(p) for p in (last_pass.get("changed_files") or [])}
    hits = sorted(p for p in drift if p in owned or p == ".asgard/map" or p.startswith(".asgard/map/"))
    return hits, sorted(drift - set(hits))


def load_policy(root: str) -> dict:
    # 얕은 복사면 중첩 기본값(`ticket_runtime` 등)이 프로세스 전역으로 공유된다 — 한 호출자가
    # `policy["ticket_runtime"]["lease_seconds"]` 를 만지면 그 프로세스의 다음 로드가 그 값을
    # 물려받는다. 정책은 호출자마다 자기 사본이어야 한다.
    p = copy.deepcopy(DEFAULT_POLICY)
    # 신규 통합 설정(asgard-setting-project.json의 trinity_policy) 우선, 구 파일 폴백 (fail-open)
    try:
        with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), encoding="utf-8") as handle:
            cfg = json.load(handle)
        pol = cfg.get("trinity_policy") if isinstance(cfg, dict) else None
        if isinstance(pol, dict):
            p.update(pol)
            return p
    except Exception:
        pass
    try:
        with open(os.path.join(root, ".asgard", "trinity-policy.json"), encoding="utf-8") as handle:
            p.update(json.load(handle))
    except Exception:
        pass  # 정책 파일 없음/깨짐 → 내장 기본값 (fail-open)
    return p


# ── Bayesian-lite 라우팅 prior — task-class별 게이트-red 이력 카운트 ──
# 학습 없음: 퀘스트 종결마다 {n, red} 카운트 1건 (기록자는 Heimdall — 모델 비노출).
# 소비는 transition의 게이트-우선 승격 문턱뿐 — 게이트 자체는 여전히 물리 가드가 판정한다
# ("게이트는 메모리 불신" — prior는 심도 선택 힌트지 증거가 아니다).


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


def _session_key(session: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(session or "default"))[:64] or "default"


def _session_pointer(root: str, session: str, kind: str = "active") -> str:
    directory = os.path.join(quest_dir(root), "sessions")
    return os.path.join(directory, f"{_session_key(session)}.{kind}")


def _write_pointer(path: str, qid: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(qid + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_dir(os.path.dirname(path))


def _fsync_dir(path: str) -> None:
    """Persist directory metadata for pointer rename/unlink operations.

    Windows는 디렉터리를 os.open으로 열 수 없어 PermissionError로 터진다 — 디렉터리
    fsync 자체가 미지원 플랫폼이므로 조용히 생략한다 (내구성 강화일 뿐 정합성 조건이 아니다)."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def active_quest(root: str, session: str | None = None) -> str | None:
    paths = []
    if session is not None:
        session_path = _session_pointer(root, session)
        try:
            qid = _read_text(session_path).strip()
            if qid:
                return qid
        except Exception:
            pass
        sessions = os.path.dirname(session_path)
        if os.path.exists(_session_pointer(root, session, "known")):
            return None  # 이 session은 이미 닫혔음 — 다른 session으로 fallback 금지
        # 구 scaffold는 quest-log CLI와 hook session id를 결속하지 않았다. 알려지지 않은 hook
        # session은 active Quest가 정확히 하나일 때만 안전하게 승계한다. 둘 이상이면 fail closed.
        try:
            active = {
                _read_text(os.path.join(sessions, name)).strip()
                for name in os.listdir(sessions)
                if name.endswith(".active")
            }
            active.discard("")
            if len(active) == 1:
                return next(iter(active))
        except Exception:
            pass
        if os.path.isdir(sessions):
            return None
    paths.append(os.path.join(root, ".asgard", "quest", "ACTIVE"))  # v1 fallback
    for path in paths:
        try:
            qid = _read_text(path).strip()
            if qid:
                return qid
        except Exception:
            continue
    return None


def set_active_quest(root: str, session: str, qid: str) -> None:
    _write_pointer(_session_pointer(root, session), qid)
    _write_pointer(_session_pointer(root, session, "known"), qid)
    _write_pointer(os.path.join(quest_dir(root), "ACTIVE"), qid)  # v1 readers 호환


def clear_active_quest(root: str, session: str, qid: str) -> None:
    for path in (_session_pointer(root, session), os.path.join(quest_dir(root), "ACTIVE")):
        try:
            if _read_text(path).strip() == qid:  # compare-and-delete
                os.remove(path)
                _fsync_dir(os.path.dirname(path))
        except FileNotFoundError:
            pass


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _pointer_qid(path: str) -> str:
    try:
        return _read_text(path).strip()
    except Exception:
        return ""


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
    closed_sessions.sort(key=lambda paths: max(_mtime(p) for p in paths), reverse=True)
    for paths in closed_sessions[keep:]:
        for p in paths:
            with contextlib.suppress(OSError):
                os.remove(p)
    protected = {_pointer_qid(os.path.join(qdir, "ACTIVE")), _pointer_qid(os.path.join(qdir, "LAST"))}
    try:
        for name in os.listdir(sessions):
            if name.endswith((".active", ".last")):
                protected.add(_pointer_qid(os.path.join(sessions, name)))
    except OSError:
        pass
    protected.discard("")
    logs = sorted(
        (
            (_mtime(os.path.join(qdir, name)), name[: -len(".jsonl")])
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
        _fsync_dir(qdir)
    return pruned


def load_events(root: str, qid: str) -> list[dict]:
    path = os.path.join(root, ".asgard", "quest", qid + ".jsonl")
    events = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    # Do not silently replay around a torn/corrupt event. The caller can report the
                    # exact line, while older valid unhashed logs remain readable.
                    events.append({"_corrupt": True, "_line": line_number})
    except Exception:
        pass
    return events


@contextlib.contextmanager
def quest_lock(root: str, qid: str):
    """Quest별 프로세스 lock — 상태 검사→turn 할당→append를 한 임계구역으로 묶는 기반."""
    path = os.path.join(quest_dir(root), qid + ".lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if os.name == "nt":  # pragma: no cover - Windows 전용
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":  # pragma: no cover - Windows 전용
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _write_event_unlocked(root: str, qid: str, ev: dict, events: list[dict]) -> None:
    """quest_lock 보유 호출자 전용 append primitive."""
    path = os.path.join(quest_dir(root), qid + ".jsonl")
    valid, detail = ledger_integrity(events)
    if not valid:
        raise ValueError(f"quest ledger integrity failure: {detail}")
    ev["turn"] = max((int(event.get("turn") or 0) for event in events), default=0) + 1
    ev["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ev["prev_event_hash"] = str(events[-1].get("event_hash") or event_identity(events[-1])) if events else EMPTY
    ev["event_hash"] = event_identity(ev)
    line = (json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(path, os.O_APPEND | os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        written = os.write(fd, line)
        if written != len(line):
            raise OSError("short quest-log write")
        os.fsync(fd)
    finally:
        os.close(fd)


def write_event(root: str, qid: str, ev: dict) -> None:
    """Quest lock 안에서 단조 turn을 할당하고 O_APPEND+fsync로 한 JSONL 레코드를 내구 기록."""
    with quest_lock(root, qid):
        _write_event_unlocked(root, qid, ev, load_events(root, qid))


def normalize(ev: dict, events: list[dict], qid: str, session: str) -> dict:
    """고정 코어 스키마로 정규화 — 빠진 필드는 중립값, 모르는 stdin 필드는 버린다."""
    base_ref = next((e.get("base_ref") for e in events if e.get("base_ref")), None)
    execution_id = next((e.get("execution_id") for e in events if e.get("execution_id")), None)
    acceptance_hash = next((e.get("acceptance_hash") for e in events if e.get("acceptance_hash")), None)
    if events and (not execution_id or not acceptance_hash):
        # First v2 append upgrades a legacy quest without rewriting its historical prefix.
        execution_id = "legacy-" + _canonical_hash({"quest_id": qid, "first": event_identity(events[0])})[:24]
        acceptance_hash = _canonical_hash(
            {
                "execution_id": execution_id,
                "base_ref": base_ref,
                "request": next((e.get("request") for e in events if e.get("request")), ""),
                "criteria": next((e.get("criteria") for e in events if e.get("criteria")), []),
            }
        )
    full = {
        "schema": SCHEMA,
        "quest_id": qid,
        # Only `open` may seed these values. Subsequent stdin cannot replace the first event's identity.
        "execution_id": execution_id or ev.get("execution_id"),
        "acceptance_hash": acceptance_hash or ev.get("acceptance_hash"),
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
    if isinstance(ev.get("ignored_snapshot"), dict):
        full["ignored_snapshot"] = ev["ignored_snapshot"]
    if ev.get("level"):  # verify 전용 부가 필드 — gate의 full-verify 판정 근거
        full["level"] = ev["level"]
    if ev.get("unit") is not None:  # work 전용 부가 필드 — wave 병렬 배정 단위 id
        full["unit"] = ev["unit"]
    if ev.get("ticket_status"):
        full["ticket_status"] = ev["ticket_status"]
    if ev.get("subtask"):
        full["subtask"] = str(ev["subtask"])[:1000]
    if isinstance(ev.get("access"), list):
        full["access"] = ev["access"][:20]
    if ev.get("ticket_error"):
        full["ticket_error"] = str(ev["ticket_error"])[:500]
    if ev.get("claim_token_hash"):
        full["claim_token_hash"] = str(ev["claim_token_hash"])[:128]
    if ev.get("worker_id"):
        full["worker_id"] = str(ev["worker_id"])[:128]
    for key in ("lease_expires_at", "heartbeat_at"):
        if ev.get(key) is not None:
            full[key] = float(ev[key])
    for key in ("attempt", "max_attempts"):
        if ev.get(key) is not None:
            full[key] = int(ev[key])
    if ev.get("model"):
        full["model"] = str(ev["model"])[:80]
    if ev.get("request"):
        full["request"] = str(ev["request"])
    if ev.get("research_only") is True:
        full["research_only"] = True
    if ev.get("research_findings"):
        full["research_findings"] = str(ev["research_findings"])[:6000]
    for key in ("tree_ref", "verification_id"):
        if ev.get(key):
            full[key] = str(ev[key])[:128]
    if isinstance(ev.get("findings"), list):
        # verify 전용 부가 필드 — 결함의 소유자 분류 (기계 수리 auto-fix ↔ 사람 판단 ask-user).
        # 알 수 없는 action은 ask-user로 닫는다: 분류 불가를 기계 수리로 흘리면 판단이 필요한
        # 결함이 조용히 추측으로 해소된다. 필드 자체가 없는 판정은 종전 경로 그대로다.
        rows = []
        for index, item in enumerate(ev["findings"][:20], 1):
            if not isinstance(item, dict) or not str(item.get("description") or "").strip():
                continue
            action = str(item.get("action") or "").strip().lower()
            rows.append(
                {
                    "id": str(item.get("id") or f"f{index}")[:32],
                    "severity": str(item.get("severity") or "")[:16],
                    "file": str(item.get("file") or "")[:200],
                    "action": action if action in ("auto-fix", "ask-user", "no-op") else "ask-user",
                    "description": str(item["description"])[:600],
                }
            )
        if rows:
            full["findings"] = rows
    return full


def fold_tickets(events: list[dict]) -> dict[str, dict]:
    """Append-only ticket events를 최신 materialized view로 접는다 (구 이벤트는 기본값으로 호환)."""
    tickets: dict[str, dict] = {}
    for event in events:
        kind = event.get("event")
        if kind not in ("ticket", "ticket_lease") or event.get("unit") is None:
            continue
        key = str(event["unit"])
        current = tickets.get(key, {})
        if kind == "ticket_lease":
            # 갱신은 만료 시각만 민다. claim 이전의 갱신은 접을 상태가 없으니 버린다.
            for field in ("lease_expires_at", "heartbeat_at"):
                if current and event.get(field) is not None:
                    current[field] = event[field]
            continue
        attempt_value = event.get("attempt") if event.get("attempt") is not None else current.get("attempt")
        max_attempts_value = (
            event.get("max_attempts") if event.get("max_attempts") is not None else current.get("max_attempts")
        )
        try:
            attempt = int(str(attempt_value)) if attempt_value is not None else 0
        except _BAD_NUMBER:
            attempt = 0
        try:
            max_attempts = int(str(max_attempts_value)) if max_attempts_value is not None else 3
        except _BAD_NUMBER:
            max_attempts = 3
        tickets[key] = {
            "id": event["unit"],
            "status": event.get("ticket_status") or current.get("status") or "todo",
            "subtask": event.get("subtask") or current.get("subtask") or "",
            "files": event.get("changed_files") or current.get("files") or [],
            "criteria": event.get("criteria") or current.get("criteria") or [],
            "access": event.get("access") if isinstance(event.get("access"), list) else current.get("access") or [],
            "error": event.get("ticket_error") or current.get("error"),
            "claim_token_hash": event.get("claim_token_hash") or current.get("claim_token_hash"),
            "worker_id": event.get("worker_id") or current.get("worker_id"),
            "lease_expires_at": event.get("lease_expires_at")
            if event.get("lease_expires_at") is not None
            else current.get("lease_expires_at"),
            "heartbeat_at": event.get("heartbeat_at")
            if event.get("heartbeat_at") is not None
            else current.get("heartbeat_at"),
            "attempt": attempt,
            "max_attempts": max_attempts,
        }
    return tickets


def _norm_path(path) -> str:
    return os.path.normpath(str(path)).replace("\\", "/")


def verifiable_units(tickets: list[dict]) -> list[str]:
    """Pipeline (not barrier) eligibility: a `done` unit may verify immediately once its `files`
    no longer overlap any still-open (`todo`/`in_progress`) unit's `files` — Workflow tool's
    `pipeline` semantics (no cross-item barrier) ported to Mode B ticket units. This is early
    *verification* eligibility only; the final close/PASS gate (completion_decision) still
    requires every ticket `done` — no change to that barrier.

    Fail-closed on undeclared files: an open unit with no declared `files` has not proven it is
    disjoint from anything, so no unit is early-verifiable until every open unit declares its
    files (absence of a declaration is not evidence of no overlap)."""
    open_files: set[str] = set()
    for ticket in tickets:
        if ticket.get("status") in ("todo", "in_progress"):
            files = [_norm_path(f) for f in (ticket.get("files") or [])]
            if not files:
                return []
            open_files.update(files)
    return [
        str(ticket["id"])
        for ticket in tickets
        if ticket.get("status") == "done" and open_files.isdisjoint(_norm_path(f) for f in (ticket.get("files") or []))
    ]


def replay_ledger(events: list[dict]) -> dict:
    """Materialize durable execution state from events only; no working-tree reads."""
    first = events[0] if events else {}
    tickets = list(fold_tickets(events).values())
    verifies = [event for event in events if event.get("event") == "verify"]
    closed = [event for event in events if event.get("event") == "quest_closed"]
    last_verify = verifies[-1] if verifies else {}
    return {
        "quest_id": first.get("quest_id"),
        "execution_id": next((event.get("execution_id") for event in events if event.get("execution_id")), None),
        "acceptance_hash": next(
            (event.get("acceptance_hash") for event in events if event.get("acceptance_hash")), None
        ),
        "base_ref": first.get("base_ref"),
        "request": first.get("request") or "",
        "criteria": first.get("criteria") or [],
        "turns": len(events),
        "last_event": events[-1].get("event") if events else None,
        "last_verdict": last_verify.get("verdict"),
        "last_diff_hash": last_verify.get("diff_hash"),
        "verification_id": last_verify.get("verification_id"),
        "tickets": tickets,
        "closed": bool(closed),
        "close_decision": ((closed[-1].get("risk") or {}).get("decision") if closed else None),
    }


def summarize(root: str, qid: str, events: list[dict], policy: dict) -> dict:
    """코디네이터 관찰용 요약 — next의 입력이기도 하다."""
    base_ref = next((e.get("base_ref") for e in events if e.get("base_ref")), None)
    ignored_base = next(
        (e.get("ignored_snapshot") for e in events if isinstance(e.get("ignored_snapshot"), dict)), None
    )
    cur, changed, lines, nt_lines = diff_state(root, base_ref, ignored_base)
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
    dts = deleted_tests(root, base_ref)
    # small_write 판정은 테스트 파일 제외 — 테스트 추가는 검증 표면이지 리스크 질량이 아니다
    # (스모크 실측: 잠금 테스트 2파일 추가 → big 오판 → full 강제·게이트-우선 무력화). 삭제는 dts가 잡는다.
    nt_files = [f for f in changed if not _testfile(f)]
    small = policy["small_write"]
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
        "full_required": bool(sens) or bool(dts) or len(nt_files) > small["max_files"] or nt_lines > small["max_lines"],
        "pass_hash_match": pass_fresh,
        "verification_identity_match": verification_valid,
        "drift_out_of_scope": drift_out[:10],  # 범위 밖 드리프트 — 관측용 (판정 아님)
        "pass_level": (last_pass or {}).get("level"),
        # PASS의 성공 명령 증거 — 게이트와 동일 기준 (없으면 전이·close가 거부 — 깊이 테스트가 발견한 구멍)
        # 무변경(diff EMPTY) 퀘스트는 관측 명령이 곧 증거 (no-op 교착 봉합)
        "pass_evidence": bool(last_pass and pass_evidence(last_pass, no_change=cur == EMPTY)),
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
        "sig_risk": signature_risk(root, base_ref),
        "tickets": list(tickets.values()),
        "ticket_counts": {status: count for status, count in ticket_counts.items() if count},
        # Pipeline eligibility (no cross-unit barrier) — units safe to verify now, before the
        # whole batch is `done`. Final close/PASS keeps the full barrier (completion_decision).
        "verifiable_units": verifiable,
    }


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


# ── 전이 함수 — 결정 테이블은 코드가 유일한 출처, 임계값만 정책에서 온다 ──
# 물음 셋을 순서대로 묻는다: ① 진행이 막혔는가 ② 마지막 판정에 무엇으로 답하는가 ③ 다음
# 걸음은 무엇인가. 앞의 물음이 답을 내면 뒤는 보지 않는다 — 그 우선순위가 곧 계약이다.


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
    full_required = s["full_required"] or flags.shared
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
            not sensitive
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
        # 무변경 관측 — Worker가 돌았는데 물리 diff 0 (risk_write는 분류 시점 기대치라
        # 판정 축이 아니다 — 물리 관측이 정본). '변경 없음' 주장의 올바른 검증은 트리 관측
        # 그 자체다 (pass_evidence의 no_change=inspection 원칙) — LLM Verifier를 소환해
        # 반증 불가능한 기준을 재량 검증시키지 않고, 하네스가 관측을 기록해 판정한다
        # (0-LLM). 오분류로 Trinity에 들어온 무변경 요청의 결정론 출구 (26-07-21 "안녕"
        # 계열 — 잔여 낭비 경로 봉합). 한계(수용): 변경이 필요했는데 Worker가 안 한 경우도
        # 통과한다 — 최종 보고의 변경 0 관측이 그 사실을 드러낸다.
        return "BASELINE_VERIFY", "no-change observed — harness tree-observation verdict (0-LLM)"
    if axes["standard_ok"] and s.get("checks_available"):
        return "BASELINE_VERIFY", "small, non-sensitive change — harness baseline takes priority"
    return "VERIFIER", "Worker complete — %s-verify verdict is next" % axes["level"]


def transition(s: dict, policy: dict, flags, priors: dict | None = None) -> dict:
    """다음에 누가 도는가 — 결정 테이블. 물음 셋을 순서대로 묻고 첫 답을 그대로 쓴다."""
    axes = _transition_axes(s, policy, flags)
    role, why = _blocked_step(s, policy, flags) or _verdict_step(s, flags, priors, axes) or _next_step(s, flags, axes)
    return {"next_role": role, "verify_level": axes["level"], "why": why, "features": axes["features"]}


def map_nudge(root: str, base_ref: str | None) -> list[str]:
    """close 시 지도 갱신 리마인더 — base_ref 이후 구조 변경(추가 A/삭제 D/이동 R)만 본다.
    0-LLM·fail-open: git 실패·지도 미도입(.asgard/map 부재)이면 침묵. 내용 수정(M)은 지도 무관.
    diff는 untracked를 못 보므로 ls-files --others를 A로 합류 (diff_state와 동일 처리)."""
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


def _ticket_recover(emit, tickets: dict, now: float, max_attempts: int) -> tuple[int, dict]:
    """lease 가 끝난 in_progress 를 회수한다 — 재시도 예산이 남았으면 failed, 없으면 blocked."""
    recovered = []
    for ticket in list(tickets.values()):
        if ticket["status"] != "in_progress" or float(ticket.get("lease_expires_at") or 0) > now:
            continue
        exhausted = int(ticket.get("attempt") or 0) >= int(ticket.get("max_attempts") or max_attempts)
        next_status = "blocked" if exhausted else "failed"
        emit(
            {
                "unit": ticket["id"],
                "ticket_status": next_status,
                "ticket_error": "lease expired",
                "attempt": ticket.get("attempt") or 0,
                "max_attempts": ticket.get("max_attempts") or max_attempts,
                "claim_token_hash": ticket.get("claim_token_hash"),
                "worker_id": ticket.get("worker_id"),
                "lease_expires_at": ticket.get("lease_expires_at"),
            }
        )
        recovered.append({"unit": ticket["id"], "status": next_status})
    return 0, {"recovered": recovered}


def _ticket_claim(
    emit, tickets: dict, ticket: dict, now: float, worker, lease_seconds: int, max_attempts: int
) -> tuple[int, dict]:
    """단위 하나를 Worker 한 명에게 준다 — 선행 단위가 done 이고 살아 있는 lease 가 없을 때만."""
    dependencies = [tickets.get(str(dep)) for dep in ticket.get("access") or []]
    if any(not dep or dep.get("status") != "done" for dep in dependencies):
        return 1, {"error": "dependencies incomplete", "unit": ticket["id"]}
    if ticket["status"] == "in_progress" and float(ticket.get("lease_expires_at") or 0) > now:
        return 1, {"error": "ticket already claimed", "unit": ticket["id"]}
    if ticket["status"] in ("done", "blocked"):
        message = "retry budget exhausted" if ticket["status"] == "blocked" else "ticket is terminal"
        return 1, {"error": message, "unit": ticket["id"], "status": ticket["status"]}
    previous_max = int(ticket.get("max_attempts") or max_attempts)
    allowed = min(previous_max, max_attempts) if int(ticket.get("attempt") or 0) else max_attempts
    attempt = int(ticket.get("attempt") or 0) + 1
    if attempt > allowed:
        emit(
            {
                "unit": ticket["id"],
                "ticket_status": "blocked",
                "ticket_error": "retry budget exhausted",
                "attempt": ticket.get("attempt") or 0,
                "max_attempts": allowed,
            }
        )
        return 1, {"error": "retry budget exhausted", "unit": ticket["id"], "status": "blocked"}
    # Keep the first character non-option-like so argparse callers may safely pass
    # the opaque token as a separate value (`--claim-token TOKEN`).
    token = "agt_" + secrets.token_urlsafe(24)
    expiry = now + lease_seconds
    emit(
        {
            "unit": ticket["id"],
            "ticket_status": "in_progress",
            "claim_token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "worker_id": worker or "worker",
            "lease_expires_at": expiry,
            "heartbeat_at": now,
            "attempt": attempt,
            "max_attempts": allowed,
        }
    )
    return 0, {
        "claimed": ticket["id"],
        "claim_token": token,
        "worker_id": worker or "worker",
        "lease_expires_at": expiry,
        "attempt": attempt,
        "max_attempts": allowed,
    }


def _ticket_lease_denial(ticket: dict, claim_token, now: float) -> dict | None:
    """갱신·종료의 자격 검사 — 자기 claim 을 증명해야 한다. None 이면 통과다.

    토큰은 해시로만 대조하고 비교도 상수 시간이다. 토큰 없이 남의 lease 를 밀 수 있으면
    lease 는 소유권이 아니라 권고가 된다."""
    supplied_hash = hashlib.sha256((claim_token or "").encode()).hexdigest()
    stored_hash = str(ticket.get("claim_token_hash") or "")
    if ticket["status"] != "in_progress" or not claim_token or not secrets.compare_digest(supplied_hash, stored_hash):
        return {"error": "claim token mismatch", "unit": ticket["id"]}
    if float(ticket.get("lease_expires_at") or 0) <= now:
        return {"error": "claim lease expired", "unit": ticket["id"]}
    return None


def _ticket_heartbeat(emit, ticket: dict, now: float, lease_seconds: int, max_attempts: int) -> tuple[int, dict]:
    """lease 갱신 — 상태 전이가 아니라 `ticket_lease` 로 적는다.

    갱신이 `ticket` 으로 적히면 티켓 이벤트 열이 "todo→in_progress→done" 이 아니라 "얼마나
    오래 돌았는가"를 적게 되고, 그 열을 읽는 쪽은 벽시계에 따라 다른 역사를 본다."""
    expiry = now + lease_seconds
    emit(
        {
            "event": "ticket_lease",
            "unit": ticket["id"],
            "claim_token_hash": str(ticket.get("claim_token_hash") or ""),
            "worker_id": ticket.get("worker_id"),
            "lease_expires_at": expiry,
            "heartbeat_at": now,
            "attempt": ticket.get("attempt") or 1,
            "max_attempts": ticket.get("max_attempts") or max_attempts,
        }
    )
    return 0, {"heartbeat": ticket["id"], "lease_expires_at": expiry}


def _ticket_finish(emit, ticket: dict, now: float, max_attempts: int, status, error) -> tuple[int, dict]:
    """단위 종료 — 재시도 예산을 다 쓴 failed 는 blocked 로 닫는다 (다시 못 잡는다)."""
    if status not in ("done", "failed"):
        return 2, {"error": "ticket-finish status must be done or failed"}
    attempts = int(ticket.get("attempt") or 1)
    allowed = int(ticket.get("max_attempts") or max_attempts)
    final_status = "blocked" if status == "failed" and attempts >= allowed else status
    emit(
        {
            "unit": ticket["id"],
            "ticket_status": final_status,
            "ticket_error": error,
            "claim_token_hash": str(ticket.get("claim_token_hash") or ""),
            "worker_id": ticket.get("worker_id"),
            "lease_expires_at": ticket.get("lease_expires_at"),
            "heartbeat_at": now,
            "attempt": attempts,
            "max_attempts": allowed,
        }
    )
    return 0, {"finished": ticket["id"], "status": final_status, "attempt": attempts}


def _siege_register(orc, root: str, run_id: str, tickets: dict) -> dict[str, str]:
    """이 퀘스트의 배정 단위를 Task 로 장부에 세우고 unit → task id 표를 돌려준다.

    `access` 가 곧 의존이다. `task_create` 는 만들 때 의존을 받고 나중에 더할 수 없으므로,
    `topo_waves` 로 단위를 의존이 앞서는 순서로 편 뒤 그 순서대로 만든다. 이미 있는 단위는
    다시 만들지 않는다 — 두 번째 claim 이 같은 Task 를 또 만들면 DAG 가 갈린다.
    """
    known = {str(uid): ticket for uid, ticket in tickets.items()}
    order = orc.topo_waves(
        list(known),
        {uid: [a for a in (ticket.get("access") or []) if str(a) in known] for uid, ticket in known.items()},
    )
    by_unit: dict[str, str] = {}
    for wave in order:
        for uid in wave:
            existing = orc.task_for_unit(root, run_id, uid)
            if existing is not None:
                by_unit[uid] = existing["id"]
                continue
            deps = [by_unit[str(a)] for a in (known[uid].get("access") or []) if str(a) in by_unit]
            spec = str(known[uid].get("subtask") or "").strip() or uid
            by_unit[uid] = orc.task_create(root, run_id, spec, deps=deps, unit_id=uid)["id"]
    return by_unit


def _native_loop_owns_the_ledger(worker_id) -> bool:
    """이 단위를 네이티브 Trinity 루프가 잡았는가.

    네이티브 모드도 이 훅으로 티켓을 잡는다(`agent/heimdall/ticket_lease.py`). 하지만 그
    모드에서는 `agent/heimdall/bifrost.py` 가 이미 같은 배차를 장부에 적고 있어서, 여기서 또
    적으면 한 Task 를 둘이 연다 — 뒤에 부른 쪽이 도메인에 거절당해 조용히 버려지고, 어느 쪽이
    이겼는지는 실행마다 달라진다. 장부의 주인은 한 프로세스여야 한다.

    표식은 `ticket_lease._claim` 이 넘기는 워커 id 접두사다. 그쪽이 형식을 바꾸면 이 판정이
    조용히 무너지므로 `tests/test_siege_act.py` 가 두 문자열을 함께 붙든다.
    """
    return str(worker_id or "").startswith("native:")


def _siege_mirror(root: str, qid: str, cmd: str, unit: str, payload: dict) -> None:
    """티켓 전이를 배차 장부(`.asgard/orchestration.db`)에도 적는다.

    호스트 모드(Claude Code·Cursor·Codex)에서 장부가 적히는 **유일한 경로**다. 네이티브 루프는
    `agent/heimdall/bifrost.py` 가 같은 계약을 프로세스 안에서 부르지만 세 호스트 모드에는 그
    루프가 없어서, 여기가 없으면 그 모드들에서 `asgard siege` 는 언제나 빈 장부를 보여 준다.

    실패는 삼킨다. 장부는 퀘스트 로그에서 파생된 것이고(`asgard.orchestration` 모듈 주석),
    파생을 얻으려다 정본의 전이를 잃으면 안 된다. 그래서 이 호출은 Quest lock 밖에 있다 —
    SQLite 대기가 티켓 전이의 임계 구역을 늘리면 병렬 워커가 서로를 기다린다.
    """
    try:
        from asgard import orchestration as orc

        events = load_events(root, qid)
        tickets = fold_tickets(events)
        owner = payload.get("worker_id") or (tickets.get(str(unit)) or {}).get("worker_id")
        if _native_loop_owns_the_ledger(owner):
            return
        objective = next((e.get("request") for e in events if e.get("request")), "") or qid
        run = orc.run_bind(root, qid, str(objective)[:500], coordinator="heimdall")
        by_unit = _siege_register(orc, root, run["id"], tickets)
        task_id = by_unit.get(str(unit))
        if not task_id:
            return
        if cmd == "ticket-claim":
            orc.open_dispatch(root, task_id, worker=str(payload.get("worker_id") or ""), role="worker")
            return
        live = orc.dispatch_show(root, task_id=task_id)
        if live is None or live["state"] != "ready":
            return
        if cmd == "ticket-heartbeat":
            orc.heartbeat(root, run["id"], task_id, live["id"])
            return
        if cmd == "ticket-finish":
            ticket = tickets.get(str(unit)) or {}
            outcome = "succeeded" if payload.get("status") == "done" else "failed"
            orc.worker_done(
                root,
                run["id"],
                task_id,
                live["id"],
                outcome,
                subject=str(ticket.get("error") or "")[:200] or outcome,
                files_modified=[str(f) for f in (ticket.get("files") or [])][:50],
                sender=str(ticket.get("worker_id") or ""),
            )
    except Exception:
        # 장부가 없거나 잠겨 있거나 asgard 를 못 불러도 티켓 전이는 이미 정본에 적혔다.
        return


def ticket_runtime(
    root: str,
    qid: str,
    cmd: str,
    *,
    unit: str | None,
    session: str,
    worker: str | None = None,
    claim_token: str | None = None,
    lease_seconds: int = 300,
    max_attempts: int = 3,
    status: str | None = None,
    error: str | None = None,
) -> tuple[int, dict]:
    """Ticket claim/lease 상태 전이를 Quest lock 아래에서 검사+기록하고, 배차 장부에 옮긴다."""
    now = time.time()
    lease_seconds = max(1, min(int(lease_seconds), 86400))
    max_attempts = max(1, min(int(max_attempts), 20))
    with quest_lock(root, qid):
        events = load_events(root, qid)

        def emit(raw: dict) -> dict:
            event = normalize({"role": "worker", "event": "ticket", **raw}, events, qid, session)
            _write_event_unlocked(root, qid, event, events)
            events.append(event)
            return event

        tickets = fold_tickets(events)
        if cmd == "ticket-recover":
            code, payload = _ticket_recover(emit, tickets, now, max_attempts)
        elif not (ticket := tickets.get(str(unit))):
            return 1, {"error": "unknown ticket", "unit": unit}
        elif cmd == "ticket-claim":
            code, payload = _ticket_claim(emit, tickets, ticket, now, worker, lease_seconds, max_attempts)
        elif denial := _ticket_lease_denial(ticket, claim_token, now):
            return 1, denial
        elif cmd == "ticket-heartbeat":
            code, payload = _ticket_heartbeat(emit, ticket, now, lease_seconds, max_attempts)
        elif cmd == "ticket-finish":
            code, payload = _ticket_finish(emit, ticket, now, max_attempts, status, error)
        else:
            return 2, {"error": "unknown ticket runtime command"}
    # 장부는 lock 밖에서 적는다 — 아래를 참조.
    if code == 0 and unit and cmd != "ticket-recover":
        _siege_mirror(root, qid, cmd, str(unit), payload)
    return code, payload


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
            "append",
            "state",
            "replay",
            "next",
            "close",
            "verify-baseline",
            "ticket-claim",
            "ticket-heartbeat",
            "ticket-finish",
            "ticket-recover",
        ],
    )
    ap.add_argument("quest_id", nargs="?")
    ap.add_argument("--criteria", action="append", default=[])
    ap.add_argument("--request", default="", help="open: original task text for crash-safe native resume")
    ap.add_argument("--request-stdin", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--base-ref", help=argparse.SUPPRESS)
    ap.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID", "-"))
    ap.add_argument("--role"), ap.add_argument("--event"), ap.add_argument("--verdict")
    ap.add_argument("--level", choices=["micro", "full"])
    ap.add_argument("--unit")
    ap.add_argument("--worker")
    ap.add_argument("--claim-token")
    ap.add_argument("--lease-seconds", type=int, default=300)
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


def _open_event(qid: str, args, base_ref: str, request: str, ignored_snapshot: dict) -> dict:
    """개설 이벤트 — 요청문·기준·시작 트리·위험을 수용 해시 하나로 묶는다."""
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
    ignored_snapshot = ignored_state(root)
    if "<snapshot-unavailable>" in ignored_snapshot:
        return _error("ignored-file snapshot unavailable")
    ev = _open_event(qid, args, base_ref, request, ignored_snapshot)
    with quest_lock(root, qid):
        if os.path.exists(os.path.join(quest_dir(root), qid + ".jsonl")):
            return _error("quest id already exists; resume it or choose a new id")
        _write_event_unlocked(root, qid, ev, [])
    set_active_quest(root, args.session, qid)
    print(
        json.dumps(
            {
                "opened": qid,
                "execution_id": ev["execution_id"],
                "acceptance_hash": ev["acceptance_hash"],
                "base_ref": base_ref,
                "turn": ev["turn"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def _append_payload(args) -> tuple[dict | None, int]:
    """append가 받을 이벤트 원문 — stdin JSON 위에 플래그를 덮는다. (원문, 종료 코드)."""
    raw: dict = {}
    if not sys.stdin.isatty():
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
    if raw.get("verdict", "NA") not in VERDICTS:
        return "verdict must be one of %s" % sorted(VERDICTS)
    return ""


def _verify_evidence(root: str, policy: dict, events: list[dict], ev: dict) -> None:
    """verify 이벤트의 물리 증거를 이 도구가 채운다 — 손 계산 해시는 게이트 재계산과 어긋난다."""
    # 구조 지도도 판정 대상 diff에 포함 — PASS 뒤 close가 파일을 쓰면 stale hash가 된다.
    map_ok, map_error = refresh_managed_map(root)
    ignored_base = next(
        (event.get("ignored_snapshot") for event in events if isinstance(event.get("ignored_snapshot"), dict)),
        None,
    )
    ev["diff_hash"], ev["changed_files"], _, _ = diff_state(root, ev["base_ref"], ignored_base)
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
    crit = contract_criteria(ev.get("criteria"), *(e.get("criteria") for e in events))
    cc = run_criteria_checks(root, policy, crit, events, ev["diff_hash"], ran)
    if cc is not None:
        ev["criteria_checks"] = cc
    # PASS 시점 트리 봉인 — stale 판정의 귀속 범위 대조 축 (stale_pass_scope)
    ev["tree_ref"] = current_tree_ref(root)
    ev["verification_id"] = verification_identity(ev)


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
    ev["diff_hash"], ev["changed_files"], _, _ = diff_state(root, ev["base_ref"], ignored_base)
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
    crit = contract_criteria(*(e.get("criteria") for e in events))
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
        _write_event_unlocked(root, qid, _close_event(events, qid, args, decision, code, forced), events)
        # LAST is a verified-state capability, not merely a termination receipt.
        # ESCALATE may end the active loop, but its writes remain unverified.
        if decision == "APPROVED" and not forced:
            try:
                _write_pointer(_session_pointer(root, args.session, "last"), qid)
                _write_pointer(os.path.join(quest_dir(root), "LAST"), qid)
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


def main() -> int:
    args = _parser().parse_args()
    root = repo_root()
    policy = load_policy(root)

    if args.cmd == "open":
        return _cmd_open(root, args)

    qid = sanitize(args.quest_id) if args.quest_id else active_quest(root, args.session)
    if not qid:
        print(json.dumps({"error": "no active quest — run: quest-log open <quest-id>"}))
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
