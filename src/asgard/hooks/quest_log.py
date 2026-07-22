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
import contextlib
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

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
    except Exception:
        pass


SCHEMA = 1
EMPTY = hashlib.sha256(b"").hexdigest()  # 변경 전무(diff 없음 + untracked 없음)의 정준 해시
EVENTS = {
    "plan",
    "work",
    "verify",
    "fail",
    "escalate",
    "delegate",
    "ticket",
    "quest_closed",
}  # delegate: 중첩 디스패치 배정 기록 — Phase 2 통계가 배정 정책 학습
VERDICTS = {"PASS", "FAIL", "ESCALATE", "NA"}
TICKET_STATUSES = {"todo", "in_progress", "done", "failed", "blocked"}
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
    # 하네스 소유 베이스라인 체크 — 비면 보수적 자동 감지 (pytest 만)
    "baseline_checks": [],
    "baseline_timeout": 120,
    # 게이트-우선 적격 상한 — small_write(full-verify 기준)보다 훨씬 좁다:
    # 63라인 리라이트가 소형 판정돼 caller 미방어로 close 된 벤치 결함. 소형 diff 전용.
    "gate_first_max_lines": 25,
    # 닫힌 퀘스트 로그 keep-last-N — 세션 상한 정책. 0 = 정리 없음(무한 누적).
    "quest_retention": 30,
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
    """(rc, out). 실패는 (rc!=0, '') 로 — 호출측이 fail-open 판단.
    color.ui=false 강제 — 사용자 git 설정(color always)의 ANSI 이스케이프가 경로 파싱에
    섞이면 ignored_snapshot 키가 오염된다 (26-07-23 실측: \\x1b[36m 이 JSON 키에 잔류)."""
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
        if run("add", "-A", "--", ".", ":(exclude).asgard").returncode:
            return None
        if os.path.isdir(os.path.join(root, ".asgard", "map")):
            if run("add", "-A", "-f", "--", ".asgard/map").returncode:
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


# ── 물리 증거 해시 — verifier-gate.py 의 diff_state 와 알고리즘 동일 유지 (단일 출처 원칙) ──
# 검증 실행 아티팩트 — 검증 명령이 만든 캐시가 PASS 를 stale 로 만들면 게이트가 자기파괴적이다
# (.gitignore 없는 프로젝트에서 pytest 실행 → __pycache__ → hash 변경, s1 라이브 실측).
# lagom: 고정 목록 — 정책 파일로 빼면 exclude 확대가 게이트 우회 벡터가 되므로 하드코딩 유지.
# ".cache": 리포 안 XDG 캐시 (CC 샌드박스가 UV_CACHE_DIR 를 cwd/.cache/uv 로 주입) — uv 캐시
# 전체가 ignored_snapshot 에 해시로 실려 퀘스트 로그 1.5MB 블롯이 됐다 (26-07-23 실측).
_JUNK_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox", "node_modules", ".venv", ".cache"}


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
    """Hash only the link identity; never open or consume an external target as evidence."""
    target = os.readlink(path).encode(errors="surrogateescape")
    return b"<unsafe-symlink>\0" + target


def sensitive_path(path: str, needles) -> bool:
    """경로 세그먼트/토큰 기준 민감 매칭 — 나이브 substring 은 'ci' 가 circle.py 를,
    4자+ substring 은 'auth' 가 oauth.py·author.py 를, 'install' 이 installer_utils 를 오탐해
    작은 수정 하나가 full-verify+티어 승격으로 흘렀다 (26-07-23 감사). 규칙: 세그먼트 정확
    일치, 또는 세그먼트를 [._-] 로 쪼갠 토큰 정확 일치 (auth.py→auth, db_pool→db). 파생형은
    needle 목록에 명시한다 (authentication 등 — DEFAULT_POLICY).
    verifier_gate.py 의 sensitive_path 와 동일 유지 (단일 출처 원칙 — 어긋나면 게이트↔전이 판정 분열)."""
    segs = path.lower().split("/")
    for n in needles:
        n = str(n).lower()
        if any(seg == n or n in re.split(r"[._\-]", seg) for seg in segs):
            return True
    return False


def ignored_state(root: str) -> dict[str, str]:
    """Hash ignored non-junk files without following symlinks, so they cannot evade quest binding."""
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
        if _junk(path):
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
    커밋 여부와 무관 (base_ref 는 open 시점 고정 커밋). `.asgard/**` 제외 — 로그 기록 자체가
    diff 를 바꾸면 해시가 자기참조로 영원히 안 맞는다.
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
            after = symlink_map_state(full_path) if is_link else open(full_path, "rb").read()
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
    ignored_changed: list[str] = []
    if ignored_base is not None:
        current_ignored = ignored_state(root)
        ignored_changed = sorted(
            path
            for path in set(ignored_base) | set(current_ignored)
            if ignored_base.get(path) != current_ignored.get(path)
        )
        for path in ignored_changed:
            h.update(
                b"ignored\0"
                + path.encode("utf-8", "surrogateescape")
                + b"\0"
                + str(ignored_base.get(path, "<missing>")).encode()
                + b"\0"
                + str(current_ignored.get(path, "<missing>")).encode()
            )
    changed = sorted(set(n for n in names.splitlines() if n.strip()) | set(map_changed) | set(ignored_changed))
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
        checks = [str(c).strip() for c in cfg if str(c).strip()]
        # Repository policy is untrusted input. A trivial command can erase the LLM Verifier,
        # and shell composition can mutate/exfiltrate from the deterministic harness.
        safe_prefixes = (
            "pytest ",
            "python -m pytest ",
            "python3 -m pytest ",
            "python -m compileall ",
            "python3 -m compileall ",
            "uv run pytest ",
            "uv run ruff check ",
            "uv run ruff format --check ",
            "uv run ty check",
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
        return [
            cmd
            for cmd in checks
            if not trivial_evidence(cmd)
            and "\n" not in cmd
            and not any(token in cmd for token in (";", "&&", "||", "`", "$(", ">", "<"))
            and any(cmd == prefix.rstrip() or cmd.startswith(prefix) for prefix in safe_prefixes)
        ]
    import shutil

    if not any(os.path.exists(os.path.join(root, p)) for p in ("tests", "test", "pytest.ini", "pyproject.toml")):
        return []
    if os.path.exists(os.path.join(root, "uv.lock")) and shutil.which("uv"):
        return ["uv run pytest -x -q"]
    if shutil.which("pytest"):
        return ["pytest -x -q"]
    return []


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
    """실패한 체크 출력에서 정형 실패 줄만 추출 — 이유 없는 red 를 만들지 않는다 (바운디드 증거).
    pytest 요약 줄(FAILED/ERROR ...) 우선, 없으면 출력 꼬리 3줄. 줄당 200자·최대 limit 줄 —
    수리 턴이 '무엇이 왜 깨졌는지'를 exit code 만으로 추측하지 않게 한다."""
    text = b"\n".join(s for s in (stdout, stderr) if s).decode("utf-8", "replace")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hits = [ln for ln in lines if ln.startswith(("FAILED ", "ERROR ")) or "AssertionError" in ln]
    return [ln[:200] for ln in (hits or lines[-3:])[:limit]]


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
        p = None
        try:
            p = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, timeout=timeout)
            code = p.returncode
        except Exception:
            code = None  # timeout 포함 — skip 취급 (fail-open)
        row: dict = {"cmd": cmd[:120], "exit_code": code, "secs": round(time.time() - t0, 1)}
        results.append(row)
        # skip = 체크가 "돌 수 없었다": 127 미설치 · pytest 5 수집 없음 · timeout. 자동 감지 pytest 는
        # 2/3/4(수집·사용법 오류 — venv 밖 pytest 가 흔한 원인)도 skip — 환경 문제를 코드 red 로
        # 오판해 게이트가 인질 잡는 것 방지. 명시 설정 체크는 사용자가 커맨드를 보증하므로 엄격 판정.
        if code is None or code == 127 or ("pytest" in cmd.split() and (code == 5 or (auto and code in (2, 3, 4)))):
            continue
        if code != 0:
            if p is not None:
                fails = fail_lines(p.stdout, p.stderr)
                if fails:
                    row["fails"] = fails  # 정형 실패 줄 — 게이트 사유·수리 턴 컨텍스트로 흐른다
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

    trivial 필터는 '아무 exit 0 명령'이 증거로 성립하는 Goodhart 를 막는 축이고, 이 판정은
    별개 축이다: '변경 없음' 주장의 올바른 검증은 트리 관측(git status/diff) 그 자체인데,
    관측 명령이 전부 trivial 로 걸러지면 무변경 퀘스트는 영원히 PASS 가 불가능한 교착이 된다
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
                index += 2  # 옵션 인자 스킵 — `git -C <path> status` 의 <path> 를 sub 로 오인 금지
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


def pass_evidence(rec: dict, *, no_change: bool = False) -> bool:
    """PASS 레코드의 성공 명령 증거 — trivial 명령 제외 (verifier_gate.py 와 동일 유지).
    하네스가 직접 돌린 베이스라인 green·전 계약 성공(criteria_checks)은 그 자체가 물리 증거 —
    trivial 필터는 모델이 고른 명령에만 적용한다 (둘 다 하네스 소유 기록, 모델 위조 불가).
    no_change=True (하네스 관측 diff 가 EMPTY) 면 트리 관측 명령(git status/diff)도 증거다 —
    무변경 주장에는 관측이 곧 검증이며, 아니면 no-op 퀘스트가 영구 FAIL 로 교착한다."""
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
    """diff 에 삭제·변경된 공개 선언·반환 라인 존재 여부 — 숨은-caller/값 형태 리스크 신호.
    '-' 라인만 본다: 신규 추가(+def)는 기존 caller 가 없고, 바뀐 줄은 기존 '-' 절반이 잡힌다.
    게이트-우선(STANDARD) 라우팅 전용 — verifier_gate 대응 불필요."""
    if not base_ref or base_ref == "NONE":
        return False
    rc, out = git(root, "diff", "-U0", base_ref, "--", ".", ":(exclude).asgard")
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
    verify 이벤트의 changed_files 는 전 트리 diff 라 타 세션 잔여물이 섞인다 — 소유 근거 아님."""
    owned = {
        _rel_to_root(root, p)
        for e in events
        if e.get("event") == "work"
        for p in (e.get("changed_files") or [])
        if str(p).strip()
    }
    for sid in {str(e.get("session_id")) for e in events if e.get("session_id")}:
        try:
            journal = json.load(open(os.path.join(root, ".asgard", "state", f"writes-{sid}.json")))
            owned.update(_rel_to_root(root, p) for p in journal if str(p).strip())
        except Exception:
            pass
    return owned


def stale_pass_scope(root: str, last_pass: dict, events: list[dict], current_changed) -> tuple[bool, list[str]]:
    """(stale 여부, 범위 밖 드리프트) — PASS 이후 트리 변화의 퀘스트 귀속 판정.

    전 트리 해시 불일치를 전부 stale 로 보면 병렬 세션 쓰기·빌드 아티팩트 1건이 full 재검증을
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
        return True, []
    cur_tree = current_tree_ref(root)
    if not cur_tree:
        return True, []
    rc, names = git(root, "diff", "--name-only", pass_tree, cur_tree)
    if rc != 0:
        return True, []
    drift = {n for n in names.splitlines() if n.strip()}
    drift |= set(map(str, current_changed or [])) ^ {str(p) for p in (last_pass.get("changed_files") or [])}
    hits = sorted(p for p in drift if p in owned or p == ".asgard/map" or p.startswith(".asgard/map/"))
    return bool(hits), sorted(drift - set(hits))


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

    Windows 는 디렉터리를 os.open 으로 열 수 없어 PermissionError 로 터진다 — 디렉터리
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
            qid = open(session_path, encoding="utf-8").read().strip()
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
                open(os.path.join(sessions, name), encoding="utf-8").read().strip()
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
            qid = open(path, encoding="utf-8").read().strip()
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
            if open(path, encoding="utf-8").read().strip() == qid:  # compare-and-delete
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
        return open(path, encoding="utf-8").read().strip()
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
    세션 포인터도 같은 상한으로 GC 한다 — 닫힌 세션의 .last 가 퀘스트를 영구 보호하면
    보호 집합이 세션 수만큼 무한 성장한다. 실패는 close 를 막지 않는다 (fail-open)."""
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
        for line in open(path, encoding="utf-8"):
            try:
                events.append(json.loads(line))
            except Exception:
                continue  # 깨진 한 줄이 로그 전체를 죽이면 안 된다
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
    ev["turn"] = max((int(event.get("turn") or 0) for event in events), default=0) + 1
    ev["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
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
    if isinstance(ev.get("ignored_snapshot"), dict):
        full["ignored_snapshot"] = ev["ignored_snapshot"]
    if ev.get("level"):  # verify 전용 부가 필드 — gate 의 full-verify 판정 근거
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
    return full


def fold_tickets(events: list[dict]) -> dict[str, dict]:
    """Append-only ticket events를 최신 materialized view로 접는다 (구 이벤트는 기본값으로 호환)."""
    tickets: dict[str, dict] = {}
    for event in events:
        if event.get("event") != "ticket" or event.get("unit") is None:
            continue
        key = str(event["unit"])
        current = tickets.get(key, {})
        attempt_value = event.get("attempt") if event.get("attempt") is not None else current.get("attempt")
        max_attempts_value = (
            event.get("max_attempts") if event.get("max_attempts") is not None else current.get("max_attempts")
        )
        try:
            attempt = int(str(attempt_value)) if attempt_value is not None else 0
        except TypeError, ValueError:
            attempt = 0
        try:
            max_attempts = int(str(max_attempts_value)) if max_attempts_value is not None else 3
        except TypeError, ValueError:
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


def summarize(root: str, qid: str, events: list[dict], policy: dict) -> dict:
    """코디네이터 관찰용 요약 — next 의 입력이기도 하다."""
    base_ref = next((e.get("base_ref") for e in events if e.get("base_ref")), None)
    ignored_base = next(
        (e.get("ignored_snapshot") for e in events if isinstance(e.get("ignored_snapshot"), dict)), None
    )
    cur, changed, lines, nt_lines = diff_state(root, base_ref, ignored_base)
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
    _research_i = [i for i, e in enumerate(events) if e.get("event") == "work" and e.get("research_only")]
    last_research = events[_research_i[-1]] if _research_i else {}
    tickets = fold_tickets(events)
    ticket_counts = {
        status: sum(1 for ticket in tickets.values() if ticket["status"] == status) for status in TICKET_STATUSES
    }
    # stale 판정 — 해시 일치가 1차, 불일치면 퀘스트 귀속 범위 대조 (병렬 세션 드리프트 면책).
    pass_fresh = bool(last_pass and last_pass.get("diff_hash") == cur)
    drift_out: list[str] = []
    if last_pass and not pass_fresh:
        stale, drift_out = stale_pass_scope(root, last_pass, events, changed)
        pass_fresh = not stale
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
        # gate 의 full_required 판정과 동일 기준 — 전이(DONE)와 close 가 gate 와 어긋나면 안 된다.
        "full_required": bool(sens) or bool(dts) or len(nt_files) > small["max_files"] or nt_lines > small["max_lines"],
        "pass_hash_match": pass_fresh,
        "drift_out_of_scope": drift_out[:10],  # 범위 밖 드리프트 — 관측용 (판정 아님)
        "pass_level": (last_pass or {}).get("level"),
        # PASS 의 성공 명령 증거 — 게이트와 동일 기준 (없으면 전이·close 가 거부 — 깊이 테스트가 발견한 구멍)
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
        #   escalate_nudged       = 어떤 ESCALATE 든 이후 plan 이 존재 (퀘스트당 nudge 1회 소진)
        "replan_after_escalate": bool(_esc_i and _plan_i and _plan_i[-1] > _esc_i[-1]),
        "escalate_nudged": bool(_esc_i and _plan_i and _plan_i[-1] > _esc_i[0]),
        # 게이트-우선 라우팅 신호
        "checks_available": gate_first_checks_available(root, policy),
        "sig_risk": signature_risk(root, base_ref),
        "tickets": list(tickets.values()),
        "ticket_counts": {status: count for status, count in ticket_counts.items() if count},
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
        return "REJECTED", "no-pass", "검증 PASS 판정 없음"
    if not s.get("criteria"):
        # 게이트와 동일 검사 — close 가 이걸 안 보면 무기준 PASS 가 LAST 면제로 게이트를 우회한다
        return "REJECTED", "no-criteria", "성공 기준(criteria)이 로그에 없음 — 기준 없이는 검증이 성립하지 않는다"
    unfinished = [ticket for ticket in (s.get("tickets") or []) if ticket.get("status") != "done"]
    if unfinished:
        ids = ", ".join(str(ticket.get("id")) for ticket in unfinished[:6])
        return "REJECTED", "tickets-incomplete", "미완료 ticket 존재: %s" % ids
    if s.get("baseline_state") == "red":
        return "REJECTED", "baseline-red", "하네스 베이스라인 체크 red — 실패한 체크 수리 필요"
    unmet = s.get("contracts_unmet") or []
    if unmet:
        # 계약이 선언된 기준은 그 명령·산출물이 유일한 증거다 — 무관한 exit-0 명령으로 대체 불가
        return "REJECTED", "criteria-unverified", "criteria verify 계약 미충족: %s" % "; ".join(map(str, unmet[:3]))
    if not s.get("pass_evidence"):
        return "REJECTED", "no-evidence", "PASS 에 성공한 검증 명령 증거 없음"
    if not s.get("pass_hash_match"):
        return "REJECTED", "stale-pass", "PASS 이후 워킹트리 변경(stale PASS) — 재검증 필요"
    if s.get("full_required") and s.get("pass_level") != "full":
        return "REJECTED", "micro-pass", "full-verify 필요(민감 경로/큰 diff)한데 micro PASS"
    return "APPROVED", "ok", "검증 PASS + diff-hash 물리 대조 일치"


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
    # 게이트-우선 전용 라인 상한 (벤치 결함 대응): sig_risk가 못 보는 간접 값 흐름 변경도
    # 큰 리라이트(+52/-11)는 diff 질량으로 LLM Verifier에 올린다.
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
        if code == "baseline-red":
            # 하네스가 직접 돌린 프로젝트 체크가 실패 — 판정이 아니라 코드가 깨져 있다
            return out("WORKER_RETRY", "하네스 베이스라인 체크 red — 실패한 체크를 먼저 수리 (Canon 10)")
        if code == "no-evidence":
            # 증거 없는 PASS 는 판정이 아니다 — 게이트가 어차피 차단하므로 전이가 먼저 재검증을 보낸다
            # (판정 불일치 금지). close 우회 구멍의 전이측 봉합 (깊이 테스트 발견).
            return out("VERIFIER", "PASS 에 성공한 검증 명령 증거 없음 — 명령을 직접 실행해 재판정 (Canon 10)")
        if code == "no-criteria":
            return out("VERIFIER", "성공 기준(criteria)이 로그에 없음 — criteria 기록 후 재판정 (Canon 10)")
        if code == "tickets-incomplete":
            return out("WORKER_RETRY", why + " — 미완료 단위만 재배정")
        if code == "criteria-unverified":
            # 계약 명령이 실패했거나 산출물이 없다 — 재검증 append 가 하네스 재실행을 트리거한다
            return out("VERIFIER", why + " — 계약 명령을 수리/재실행해 재판정 (Canon 10)")
        if code == "stale-pass":
            return out("VERIFIER", "PASS 이후 워킹트리 변경(stale PASS) — 재검증 필요")
        # micro-pass — gate 와 동일 판정: micro PASS 로 DONE 을 내면 Stop 에서 차단당한다 (판정 불일치 금지)
        return out("VERIFIER", "PASS 가 micro — 민감 경로/큰 diff 는 full-verify 필요")
    if flags.external_research and has_write and not s.get("research_completed"):
        return out("WORKER", "외부 조사 선행 — 격리 Research Worker가 근거를 수집하고 구현은 보류")
    if flags.external_research and s.get("research_pending_plan"):
        return out("THINKER", "외부 조사 완료 — 수집 근거를 검토해 구현 단위와 criteria를 재계획")
    if flags.parallel_requested and s["plan_turns"] < 2:
        # 병렬 fan-out만 별도 Thinker가 access/file-overlap 그래프를 만든다. 모호함·외부 조사·큰
        # 변경은 단일 Worker가 같은 도구 문맥에서 계획하고 실행한다 — 순차 역할 handoff 비용과
        # 맥락 손실을 피하고, 실제 FAIL/구조적 red가 관측될 때만 THINKER_REPLAN으로 승격한다.
        return out("THINKER", "명시적 병렬 과업 — 독립 단위와 access graph 계획 선행")
    if not has_write:
        return out("DIRECT_DONE", "write 없음 — 게이트 면제 경로")
    if s["last_event"] == "work":
        if s["diff_hash"] == EMPTY:
            # 무변경 관측 — Worker 가 돌았는데 물리 diff 0 (risk_write 는 분류 시점 기대치라
            # 판정 축이 아니다 — 물리 관측이 정본). '변경 없음' 주장의 올바른 검증은 트리 관측
            # 그 자체다 (pass_evidence 의 no_change=inspection 원칙) — LLM Verifier 를 소환해
            # 반증 불가능한 기준을 재량 검증시키지 않고, 하네스가 관측을 기록해 판정한다
            # (0-LLM). 오분류로 Trinity 에 들어온 무변경 요청의 결정론 출구 (26-07-21 "안녕"
            # 계열 — 잔여 낭비 경로 봉합). 한계(수용): 변경이 필요했는데 Worker 가 안 한 경우도
            # 통과한다 — 최종 보고의 변경 0 관측이 그 사실을 드러낸다.
            return out("BASELINE_VERIFY", "무변경 관측 — 하네스 트리 관측 판정 (0-LLM)")
        if standard_ok and s.get("checks_available"):
            return out("BASELINE_VERIFY", "소형·비민감 변경 — 하네스 베이스라인 우선")
        return out("VERIFIER", "Worker 완료 — %s-verify 판정 차례" % level)
    return out("WORKER", "단일 Worker 자율 계획·실행 — 실패 시 Thinker 재계획")


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
                    command,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=60,
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
    """Ticket claim/lease 상태 전이를 Quest lock 아래에서 검사+기록한다."""
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

        key = str(unit)
        ticket = tickets.get(key)
        if not ticket:
            return 1, {"error": "unknown ticket", "unit": unit}

        if cmd == "ticket-claim":
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
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            expiry = now + lease_seconds
            emit(
                {
                    "unit": ticket["id"],
                    "ticket_status": "in_progress",
                    "claim_token_hash": token_hash,
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

        supplied_hash = hashlib.sha256((claim_token or "").encode()).hexdigest()
        stored_hash = str(ticket.get("claim_token_hash") or "")
        if (
            ticket["status"] != "in_progress"
            or not claim_token
            or not secrets.compare_digest(supplied_hash, stored_hash)
        ):
            return 1, {"error": "claim token mismatch", "unit": ticket["id"]}
        if float(ticket.get("lease_expires_at") or 0) <= now:
            return 1, {"error": "claim lease expired", "unit": ticket["id"]}
        if cmd == "ticket-heartbeat":
            expiry = now + lease_seconds
            emit(
                {
                    "unit": ticket["id"],
                    "ticket_status": "in_progress",
                    "claim_token_hash": stored_hash,
                    "worker_id": ticket.get("worker_id"),
                    "lease_expires_at": expiry,
                    "heartbeat_at": now,
                    "attempt": ticket.get("attempt") or 1,
                    "max_attempts": ticket.get("max_attempts") or max_attempts,
                }
            )
            return 0, {"heartbeat": ticket["id"], "lease_expires_at": expiry}
        if cmd == "ticket-finish":
            if status not in ("done", "failed"):
                return 2, {"error": "ticket-finish status must be done or failed"}
            final_status = status
            attempts = int(ticket.get("attempt") or 1)
            allowed = int(ticket.get("max_attempts") or max_attempts)
            if status == "failed" and attempts >= allowed:
                final_status = "blocked"
            emit(
                {
                    "unit": ticket["id"],
                    "ticket_status": final_status,
                    "ticket_error": error,
                    "claim_token_hash": stored_hash,
                    "worker_id": ticket.get("worker_id"),
                    "lease_expires_at": ticket.get("lease_expires_at"),
                    "heartbeat_at": now,
                    "attempt": attempts,
                    "max_attempts": allowed,
                }
            )
            return 0, {"finished": ticket["id"], "status": final_status, "attempt": attempts}
        return 2, {"error": "unknown ticket runtime command"}


def main() -> int:
    ap = argparse.ArgumentParser(prog="quest-log", description="Asgard Trinity quest log")
    ap.add_argument(
        "cmd",
        choices=[
            "open",
            "append",
            "state",
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
    ap.add_argument("--no-write", action="store_true", help="open: write 없는 과업으로 표시")
    # 모델 신고 risk_features (결정론 계산이 불가능한 4종) — next 전용
    ap.add_argument("--ambiguous", action="store_true")
    ap.add_argument("--destructive", action="store_true")
    ap.add_argument("--external-research", action="store_true")
    ap.add_argument("--shared", action="store_true")
    ap.add_argument("--structural", action="store_true", help="next: 직전 FAIL 이 구조적임을 신고")
    ap.add_argument("--write-expected", action="store_true", help="next: 아직 diff 없지만 write 예정")
    ap.add_argument(
        "--parallel-requested",
        action="store_true",
        help="next: 사용자가 병렬 분해/멀티 서브에이전트를 명시적으로 요구",
    )
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
        request = args.request
        if args.request_stdin:
            raw_request = sys.stdin.buffer.read(65537)
            if len(raw_request) > 65536:
                print(json.dumps({"error": "request payload exceeds 64 KiB limit"}), file=sys.stderr)
                return 1
            try:
                request = str((json.loads(raw_request.decode("utf-8")) or {}).get("request") or "")
            except Exception:
                print(json.dumps({"error": "invalid request stdin payload"}), file=sys.stderr)
                return 1
        if len(request) > 10000:
            print(json.dumps({"error": "request exceeds 10,000-character limit"}), file=sys.stderr)
            return 1
        base_ref = args.base_ref or snapshot_ref(root)
        if args.base_ref:
            valid_rc, raw_type = git(root, "cat-file", "-t", args.base_ref)
            valid_type = raw_type.decode("utf-8", "replace") if isinstance(raw_type, bytes) else raw_type
            if valid_rc != 0 or valid_type.strip() != "commit":
                print(json.dumps({"error": "invalid quest start snapshot"}), file=sys.stderr)
                return 1
        if not base_ref and not args.no_write:
            print(
                json.dumps({"error": "write quest requires a Git repository with HEAD and a capturable start tree"}),
                file=sys.stderr,
            )
            return 1
        base_ref = base_ref or "NONE"
        risk = {"has_write": not args.no_write}
        if args.task_class:  # prior 집계 축 — 퀘스트가 어느 클래스로 열렸는지 감사 기록
            risk["task_class"] = args.task_class
        ignored_snapshot = ignored_state(root)
        if "<snapshot-unavailable>" in ignored_snapshot:
            print(json.dumps({"error": "ignored-file snapshot unavailable"}), file=sys.stderr)
            return 1
        ev = normalize(
            {
                "role": "thinker",
                "event": "plan",
                "base_ref": base_ref,
                "risk": risk,
                "criteria": args.criteria,
                "request": request,
                "ignored_snapshot": ignored_snapshot,
            },
            load_events(root, qid),
            qid,
            args.session,
        )
        write_event(root, qid, ev)
        set_active_quest(root, args.session, qid)
        print(json.dumps({"opened": qid, "base_ref": base_ref, "turn": ev["turn"]}, ensure_ascii=False))
        return 0

    qid = sanitize(args.quest_id) if args.quest_id else active_quest(root, args.session)
    if not qid:
        print(json.dumps({"error": "no active quest — run: quest-log open <quest-id>"}))
        return 1
    events = load_events(root, qid)

    if args.cmd.startswith("ticket-"):
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
        if raw.get("event") == "ticket":
            if raw.get("unit") is None:
                print(json.dumps({"error": "ticket requires unit"}), file=sys.stderr)
                return 2
            if raw.get("ticket_status") not in TICKET_STATUSES:
                print(
                    json.dumps({"error": "ticket_status must be one of %s" % sorted(TICKET_STATUSES)}), file=sys.stderr
                )
                return 2
            if raw.get("ticket_status") != "todo" or raw.get("role") != "thinker":
                print(
                    json.dumps(
                        {
                            "error": "ticket runtime transitions require ticket-claim/heartbeat/finish/recover; "
                            "raw append only accepts thinker todo definitions"
                        }
                    ),
                    file=sys.stderr,
                )
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
            map_ok, map_error = refresh_managed_map(root)
            # 판정 이벤트의 물리 증거는 이 도구가 계산한다 — 손 계산 해시는 gate 와 어긋난다.
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
            if ev["verdict"] == "PASS":
                # 하네스 소유 베이스라인 — normalize 가 stdin baseline 을 버린 뒤 여기서만 기록.
                # 무변경(diff EMPTY) 퀘스트는 red 의 원인이 될 수 없다 — 전 트리 체크의 타 세션
                # 잔여물 red 가 무변경 퀘스트를 인질로 잡지 않게 면제 (26-07-23 감사).
                if ev["diff_hash"] != EMPTY:
                    bl = run_baseline(root, policy, events, ev["diff_hash"])
                    if bl:
                        ev["baseline"] = bl
                # criteria verify 계약 — 하네스가 계약 명령을 직접 실행해 기록 (stdin 위조는 normalize 가 버림)
                crit = ev.get("criteria") or next((e.get("criteria") for e in events if e.get("criteria")), [])
                cc = run_criteria_checks(root, policy, crit, events, ev["diff_hash"])
                if cc is not None:
                    ev["criteria_checks"] = cc
                # PASS 시점 트리 봉인 — stale 판정의 귀속 범위 대조 축 (stale_pass_scope)
                ev["tree_ref"] = current_tree_ref(root)
        write_event(root, qid, ev)
        print(
            json.dumps(
                {"appended": ev["event"], "turn": ev["turn"], "verdict": ev["verdict"], "diff_hash": ev["diff_hash"]},
                ensure_ascii=False,
            )
        )
        return 0

    if args.cmd == "verify-baseline":
        # baseline 은 모델이 고르는 축약 경로가 아니다. 현재 물리 diff와 동일 risk flags로
        # 전이를 다시 계산해 하네스 판정 자격을 확인한다 — sig_risk/큰 diff/민감 경로를
        # MAIN_WORKER가 micro PASS로 자기강등하는 우회도 여기서 한 번에 막는다.
        eligible = transition(summarize(root, qid, events, policy), policy, args, load_priors(root))
        if eligible["next_role"] != "BASELINE_VERIFY":
            print(
                json.dumps(
                    {
                        "error": "baseline 검증 부적격 — 전이 함수가 배정한 역할을 따르세요",
                        "next_role": eligible["next_role"],
                        "why": eligible["why"],
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 1
        # 게이트-우선 판정 턴 — LLM Verifier 대신 하네스가 프로젝트 체크로 판정을 기록.
        # commands = 하네스가 직접 실행한 체크 (pass_evidence 충족) — verifier 재량 커맨드 아님.
        ev = normalize({"role": "harness", "event": "verify"}, events, qid, args.session)
        map_ok, map_error = refresh_managed_map(root)
        ignored_base = next(
            (event.get("ignored_snapshot") for event in events if isinstance(event.get("ignored_snapshot"), dict)), None
        )
        ev["diff_hash"], ev["changed_files"], _, _ = diff_state(root, ev["base_ref"], ignored_base)
        snapshot_ok = "<snapshot-unavailable>" not in ev["changed_files"]
        ev["level"] = "micro"
        # 무변경(diff EMPTY) 판정 — '변경 없음' 주장의 올바른 검증은 트리 관측 그 자체다
        # (pass_evidence 의 no_change=inspection 원칙). 베이스라인은 돌리지 않는다: 무변경
        # 퀘스트는 red 의 원인이 될 수 없고, 전 트리 체크의 타 세션 잔여물 red 가 인질이 된다.
        no_change = ev["diff_hash"] == EMPTY and snapshot_ok
        if no_change:
            rc_obs, _obs = git(root, "status", "--porcelain")
            bl = {}
            state = None
            results = [{"cmd": "git status --porcelain", "exit_code": rc_obs}]
            ev["commands"] = results
            observed_ok = rc_obs == 0
        else:
            bl = run_baseline(root, policy, events, ev["diff_hash"]) or {}
            state = bl.get("state")
            if state not in ("green", "red") and map_ok:
                print(
                    json.dumps({"error": "baseline 판정 불가 (체크 없음/전부 skip) — LLM Verifier 로 검증하세요"}),
                    file=sys.stderr,
                )
                return 1
            results = [c for c in bl.get("results", []) if isinstance(c, dict)]
            ev["commands"] = results[:20]
            ev["baseline"] = bl
            observed_ok = state == "green"
        ev["verdict"] = "PASS" if observed_ok and map_ok and snapshot_ok else "FAIL"
        failing = [str(c.get("cmd")) for c in results if c.get("exit_code") not in (0, None)]
        if not snapshot_ok:
            ev["failure_sig"] = "snapshot-unavailable"
            failing = ["git write-tree (temporary index)"]
        elif not map_ok:
            ev["failure_sig"] = "map-refresh-failed"
            failing = [map_error or "managed map refresh failed"]
            ev["changed_files"] = sorted(set(ev["changed_files"]) | {".asgard/map"})
        elif state == "red":
            ev["failure_sig"] = "baseline-red"
        elif no_change and not observed_ok:
            ev["failure_sig"] = "tree-observe-failed"
            failing = ["git status --porcelain"]
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
        if ev["verdict"] == "PASS":
            # PASS 시점 트리 봉인 — stale 판정의 귀속 범위 대조 축 (append 경로와 동일)
            ev["tree_ref"] = current_tree_ref(root)
        write_event(root, qid, ev)
        fails = [str(f) for c in results for f in (c.get("fails") or [])]  # run_baseline 채집 정형 실패 줄
        print(
            json.dumps(
                {
                    "appended": "verify",
                    "verdict": ev["verdict"],
                    "baseline": state,
                    "failing": failing[:5],
                    "fails": fails[:5],
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
        # 최신 상태 판정 → durable close event → pointer compare-delete를 같은 Quest lock에 묶는다.
        # append가 PASS snapshot 뒤에 끼어드는 stale-close race를 허용하지 않는다.
        with quest_lock(root, qid):
            events = load_events(root, qid)
            s = summarize(root, qid, events, policy)
            s["tests_available"] = tests_available(root)
            decision, code, why = completion_decision(s)
            ok = decision in ("APPROVED", "ESCALATED")
            if not ok and not args.force:
                print(
                    json.dumps(
                        {
                            "error": "close 거부(%s: %s) — 검증 PASS(+hash 일치) 또는 ESCALATE 후에만. "
                            "우회는 --force (Odin 동의 필요 — LAST 미기록, 게이트 면제 없음)" % (code, why)
                        },
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                )
                return 1
            forced = bool(args.force and not ok)
            close_event = normalize(
                {
                    "role": "odin",
                    "event": "quest_closed",
                    "risk": {"forced": forced, "decision": decision, "code": code},
                },
                events,
                qid,
                args.session,
            )
            _write_event_unlocked(root, qid, close_event, events)
            # LAST is a verified-state capability, not merely a termination receipt.
            # ESCALATE may end the active loop, but its writes remain unverified.
            if decision == "APPROVED" and not forced:
                try:
                    _write_pointer(_session_pointer(root, args.session, "last"), qid)
                    _write_pointer(os.path.join(quest_dir(root), "LAST"), qid)
                except Exception as exc:
                    print(json.dumps({"error": f"close LAST pointer publication failed: {exc}"}), file=sys.stderr)
                    return 1
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
            res["map_hint"] = "자동 지도 갱신 실패 — asgard map update 실행 후 영역 지도에 새 지식만 증분 반영"
        print(json.dumps(res, ensure_ascii=False))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
