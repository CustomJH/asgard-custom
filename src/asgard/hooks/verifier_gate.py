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
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from typing import Any

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass


EMPTY = hashlib.sha256(b"").hexdigest()
# quest_log.py의 DEFAULT_POLICY와 동일 유지 — 정책 파일이 없어도 두 스크립트가 같은 기준으로 판단.
# dict[str, Any]: 사용자 trinity-policy.json이 update()로 섞이므로 값 타입은 런타임에 열려 있다.
DEFAULT_POLICY: dict[str, Any] = {
    "small_write": {"max_files": 2, "max_lines": 80},
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
    # 하네스 소유 베이스라인 체크 — quest_log.py와 동일 유지. 게이트는 실행하지 않고
    # PASS 레코드에 quest-log가 기록한 결과만 읽는다 (Stop 지연 예산에 pytest를 얹지 않는다).
    "baseline_checks": [],
    "baseline_timeout": 120,
}
MAX_BLOCKS = 3  # Canon 9 정합 — 동일 세션 4번째 차단 대신 에스컬레이션
UNATTENDED_MODES = {"bypassPermissions", "dontAsk"}  # unattended_context.py와 동일 유지
_HOST_PROTOCOL = "claude"


def _canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def event_identity(event):
    return _canonical_hash({key: value for key, value in event.items() if key != "event_hash"})


def verification_identity(event):
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


def ledger_integrity(events):
    """quest_log.py mirror — standalone deployed hook cannot import the package."""
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


def unattended(data):
    """무인 세션 신호 — 사람이 승인 루프에 없다. permission_mode는 모든 훅 stdin 공통 필드."""
    return os.environ.get("ASGARD_UNATTENDED") == "1" or str(data.get("permission_mode")) in UNATTENDED_MODES


def _read_text(path):
    """파일을 통째로 읽는다. 오류는 그대로 올린다 — 호출부마다 삼킬 범위가 다르다. quest_log.py와 동일 유지.

    핸들 수명을 여기서 끝내는 것이 요점이다. `open(p).read()`는 CPython의 참조 계수에 기대
    곧장 닫히는 것이고, 그 기댐은 코드에 안 적혀 있어서 다른 런타임에서 조용히 깨진다."""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def git(root, *args, binary=False):
    # color.ui=false 강제 — quest_log.py의 git과 동일 유지 (ANSI가 경로 파싱을 오염)
    try:
        p = subprocess.run(["git", "-C", root, "-c", "color.ui=false", *args], capture_output=True, timeout=60)
        return p.returncode, (p.stdout if binary else p.stdout.decode("utf-8", "replace"))
    except Exception:
        return 1, b"" if binary else ""


def current_tree_ref(root):
    rc, raw_head = git(root, "rev-parse", "--verify", "HEAD")
    head = raw_head.decode("utf-8", "replace") if isinstance(raw_head, bytes) else raw_head
    if rc != 0 or not head.strip():
        return None
    fd, index_path = tempfile.mkstemp(prefix="asgard-current-index-")
    os.close(fd)
    os.unlink(index_path)
    env = {**os.environ, "GIT_INDEX_FILE": index_path}

    def run(*args, input_data=None):
        return subprocess.run(
            ["git", "-C", root, *args],
            input=input_data,
            capture_output=True,
            timeout=60,
            env=env,
            check=False,
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
        try:
            os.unlink(index_path)
        except OSError:
            pass


# ── quest_log.py의 diff_state와 알고리즘 동일 유지 (단일 출처 원칙 — 어긋나면 위양성 차단) ──
# 검증 실행 아티팩트 — quest_log.py의 _junk와 동일해야 한다 (양쪽 hash 불일치 = 영구 stale).
# lagom: 고정 목록 — 정책 파일로 빼면 exclude 확대가 게이트 우회 벡터가 되므로 하드코딩 유지.
_JUNK_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox", "node_modules", ".venv", ".cache"}


def _junk(p):
    return p.endswith((".pyc", ".pyo")) or any(seg in _JUNK_DIRS for seg in p.split("/"))


def unsafe_map_links(root):
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


def symlink_map_state(path):
    """Hash only the link identity; never open or consume an external target as evidence."""
    target = os.readlink(path).encode(errors="surrogateescape")
    return b"<unsafe-symlink>\0" + target


def sensitive_path(path, needles):
    """quest_log.py의 sensitive_path와 동일 유지 (단일 출처 원칙 — 어긋나면 판정 분열).
    세그먼트 정확 일치 또는 [._-] 토큰 정확 일치 — substring 파생형은 needle 목록에 명시."""
    segs = path.lower().split("/")
    for n in needles:
        n = str(n).lower()
        if any(seg == n or n in re.split(r"[._\-]", seg) for seg in segs):
            return True
    return False


def ignored_state(root):
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
    out = {}
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


def diff_state(root, base_ref, ignored_base=None):
    # nontest_lines 4번째 원소 — quest_log.py와 동일 유지 (테스트 추가 ≠ 리스크 질량)
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
    ignored_changed = []
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


def _testfile(p):
    segs = p.lower().split("/")
    return "tests" in segs or "test" in segs or segs[-1].startswith("test_") or segs[-1].endswith("_test.py")


def deleted_tests(root, base_ref):
    """quest_log.py의 deleted_tests와 동일 유지 (단일 출처 원칙) — 테스트를 지워 green을 사는
    경로 차단 (anti-Goodhart). 삭제된 테스트 파일이 있으면 full-verify 강제."""
    if not base_ref or base_ref == "NONE":
        return []
    _, out = git(root, "diff", "--name-only", "--diff-filter=D", base_ref, "--", ".", ":(exclude).asgard")
    return [p for p in out.splitlines() if p.strip() and _testfile(p)]


def _rel_to_root(root, path):
    """quest_log.py의 _rel_to_root와 동일 유지 — write 저널 절대 경로를 리포 상대로."""
    p = str(path)
    if not os.path.isabs(p):
        return p
    rp = os.path.realpath(root)
    ap = os.path.realpath(p)
    return os.path.relpath(ap, rp) if ap == rp or ap.startswith(rp + os.sep) else p


def quest_owned_files(root, events):
    """quest_log.py의 quest_owned_files와 동일 유지 — 퀘스트 귀속 파일(work 관측 ∪ 세션 write 저널)."""
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


def stale_pass_scope(root, last_pass, events, current_changed):
    """quest_log.py의 stale_pass_scope와 동일 유지 (단일 출처 원칙) — 해시 불일치 시
    PASS 시점 tree_ref ↔ 현재 트리 드리프트가 퀘스트 귀속 파일·관리 지도에 닿을 때만 stale.
    tree_ref 없는 구 로그·귀속 공집합·트리 계산 실패는 종전 엄격 판정(stale) — fail-safe."""
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


def readonly(cmd, allow):
    c = str(cmd).strip()
    return any(c == a or c.startswith(a + " ") for a in allow)


def trivial_evidence(cmd):
    """quest_log.py의 trivial_evidence와 동일 유지 (단일 출처 원칙) — `true` 한 방이 PASS 증거로
    성립하던 Goodhart 구멍 봉합: 무조건 exit 0 이거나 관찰만 하는 명령은 검증 증거가 아니다."""
    try:
        tokens = shlex.split(str(cmd), posix=True)
    except ValueError:
        return True
    if not tokens:
        return True
    segments = [[]]
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


def inspection_evidence(cmd):
    """quest_log.py의 inspection_evidence와 동일 유지 (단일 출처 원칙) — 무변경(diff EMPTY)
    퀘스트 한정 PASS 증거: 트리 관측(git status/diff)이 곧 검증. 아니면 no-op이 영구 FAIL."""
    try:
        tokens = shlex.split(str(cmd), posix=True)
    except ValueError:
        return False
    segments = [[]]
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


def pass_evidence(rec, no_change=False):
    """PASS 레코드의 성공 명령 증거 — trivial 명령 제외 (quest_log.py와 동일 유지).
    하네스가 직접 돌린 베이스라인 green·전 계약 성공(criteria_checks)은 그 자체가 물리 증거 —
    trivial 필터는 모델이 고른 명령에만 적용한다 (둘 다 하네스 소유 기록, 모델 위조 불가).
    no_change=True (하네스 관측 diff가 EMPTY) 면 트리 관측 명령도 증거다."""
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


# ── criteria verify 계약 — quest_log.py의 parse_criterion/criteria_contracts/unmet_contracts와
# 동일 유지 (단일 출처 원칙). 게이트는 계약 명령을 재실행하지 않고(Stop 지연 예산) quest-log가
# 기록한 criteria_checks를 대조하며, 산출물 존재만 라이브 재확인한다.


def parse_criterion(text):
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


def criteria_contracts(criteria):
    """verify 계약이 선언된 기준만 — verify_cmd 또는 artifacts 보유."""
    out = []
    for t in criteria or []:
        c = parse_criterion(t)
        if c["verify_cmd"] or c["artifacts"]:
            out.append(c)
    return out[:5]  # 상한 — 계약 폭주가 verify 턴을 인질로 잡지 않게


def contract_criteria(*sources):
    """계약 추출 원본 — 문자열 항목을 실은 첫 후보. quest_log.py와 동일 유지.

    계약은 문자열 기준에만 담긴다. 판정자가 기준별 판정을 객체로 실은 이벤트를 원본으로 쓰면
    한쪽은 계약 0건(명령 미실행), 게이트는 계약 있음(미충족)으로 갈려 Stop이 영구 차단된다."""
    for src in sources:
        strings = [c for c in (src or []) if isinstance(c, str)]
        if strings:
            return strings
    return []


def unmet_contracts(root, criteria, rec):
    """PASS 레코드(rec) 기준 미충족 계약 목록. 명령은 하네스 기록(criteria_checks)의 exit 0만 인정,
    산출물은 지금(호출 시점) 존재를 라이브 재확인 — 산출물은 .gitignore로 diff-hash 밖일 수 있어
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


def block_counter_path(root, sid):
    qid = quest_pointer(root, sid) or "orphan"
    scope = re.sub(r"[^A-Za-z0-9_.-]", "_", str(qid))[:64] or "orphan"
    return os.path.join(root, ".asgard", f"gate-blocks-{sid}-{scope}.json")


def gate_event(root, kind, code):
    """게이트 운영 이벤트 영속 기록 — 차단 카운터 파일은 성공 통과 시 삭제되므로 운영 지표가
    안 남는다. doctor가 block/escalation 률을 집계할 수 있게 append-only로 남긴다. fail-open."""
    try:
        path = os.path.join(root, ".asgard", "state", "gate-events.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": kind, "code": code}) + "\n")
    except Exception:
        pass


# ── 차단 메시지 카탈로그 — 코드가 정본, 문장은 렌더링. 자기완결 배포 제약으로 asgard.failures
# 를 임포트하지 못해 사본을 품는다 — tests/test_failures.py 패리티 테스트가 두 표를 봉인한다. ──
GATE_MESSAGES = {
    "orphan-write": (
        "This session wrote files ({files}) but there is no quest log. Write quests require "
        "the Trinity loop: open a log with python3 <hooks>/quest-log.py open <quest-id> "
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


def block(root, sid, code, **params):
    """차단 — active quest별 MAX_BLOCKS 회까지. 초과 시 warn+allow + Odin 에스컬레이션 지시.
    사유는 코드+파라미터로만 받는다 — 문장은 GATE_MESSAGES가 렌더하고, 소비자(classify·doctor)는
    `[gate:<code>]` 태그/payload code를 직독한다 (문장 파싱 금지)."""
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
    gate_event(root, "gate_escalate" if n > MAX_BLOCKS else "gate_block", code)
    if n > MAX_BLOCKS:
        sys.stderr.write(
            "asgard verifier-gate: exceeded %d blocks — allowing through, but Odin escalation "
            "is required (Canon 9)\n" % MAX_BLOCKS
        )
        sys.exit(0)
    message = (
        "Asgard verifier-gate (Canon 10 — proof of completion): "
        + reason
        + " Record the Verifier verdict in the log: echo '{...}' | python3 <hooks>/quest-log.py "
        "append --verdict PASS|FAIL (the verify event auto-computes diff_hash). "
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
        qid = _read_text(session_path).strip()
        if qid:
            return qid
    except Exception:
        pass
    if kind == "active":
        if os.path.exists(os.path.join(sessions, name + ".known")):
            return None  # 이 세션은 이미 닫혔음 — 다른 세션으로 fallback 금지
        try:
            active = {
                _read_text(os.path.join(sessions, entry)).strip()
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
            qid = _read_text(path).strip()
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
        os.environ.get("CLAUDE_SESSION_ID"),
        "cursor" if protocol == "cursor" else None,
        "-",  # quest-log.py의 --session 기본값
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
        return _read_text(os.path.join(sessions, name + "." + kind)).strip() or None
    except Exception:
        return None


def resolve_session(root, candidates):
    """(quest id, 그 quest를 소유한 세션 이름).

    **엄격 조회를 먼저** 한 바퀴 돈다. `quest_pointer`의 "활성이 정확히 1개면 승계" 규칙을 후보마다
    적용하면, 포인터 파일이 애초에 없는 합성 이름(Cursor의 `"cursor"`)이 1순위에 서는 순간 곧장
    남의 quest를 물려받아 오차단한다 (26-07-31 실측). 승계는 **모든 후보가 답을 못 냈을 때만**
    쓰는 마지막 수단이다 — 종전 동작은 그 자리에 그대로 남는다."""
    for name in candidates:
        qid = _pointer_file(root, name)
        if qid:
            return qid, name
        if session_settled(root, name):
            return None, name  # 이 세션은 자기 quest를 닫았다 — 남의 활성을 승계하지 않는다
    return quest_pointer(root, candidates[0]), candidates[0]


def orphan_writes(root, sid, candidates=None):
    """quest 로그 없이 끝나려는 세션의 write 흔적 검사 (write-sentinel 기록 대조).
    기록된 경로가 지금도 HEAD와 다르면 = 검증 안 된 write가 남아 있다 → 차단.
    되돌린 write(경로 clean)·사용자 기존 dirt(기록에 없음)는 차단하지 않는다.
    예외: 직전 close 된 quest(LAST)의 PASS가 현재 워킹트리 hash와 일치하면 이미 검증된 상태 —
    close 직후 Stop이 방금 검증한 write를 오차단하지 않게 한다."""
    writes = None
    # 센티널도 세션 이름으로 갈린다 — 게이트가 신원 연결을 따라갔다면 백스톱도 같은 연결을 봐야
    # 한다. 안 그러면 quest 포인터가 안 풀린 바로 그 경우에 백스톱까지 같이 눈이 먼다.
    names = list(dict.fromkeys([sid, *(candidates or [])]))
    for name in names:
        for rel in (os.path.join("state", "writes-" + name + ".json"), "writes-" + name + ".json"):  # 신규 state/ 우선
            try:
                with open(os.path.join(root, ".asgard", rel), encoding="utf-8") as handle:
                    writes = json.load(handle)
                break
            except Exception:
                continue
        if writes is not None:
            break
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
            current_hash, last_changed, _, _ = diff_state(root, base_ref, ignored_base)
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
        policy = dict(DEFAULT_POLICY)
        # 신규 통합 설정 우선, 구 파일 폴백 — quest_log.load_policy와 동일 유지 (단일 출처 원칙)
        loaded = False
        try:
            with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), encoding="utf-8") as handle:
                cfg = json.load(handle)
            pol = cfg.get("trinity_policy") if isinstance(cfg, dict) else None
            if isinstance(pol, dict):
                policy.update(pol)
                loaded = True
        except Exception:
            pass
        if not loaded:
            try:
                with open(os.path.join(root, ".asgard", "trinity-policy.json"), encoding="utf-8") as handle:
                    policy.update(json.load(handle))
            except Exception:
                pass

        ignored_base = next(
            (event.get("ignored_snapshot") for event in events if isinstance(event.get("ignored_snapshot"), dict)), None
        )
        current, changed, lines, nt_lines = diff_state(root, base_ref, ignored_base)
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
                block(root, sid, "stale-pass")
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
        nt_files = [f for f in changed if not _testfile(f)]  # 테스트 추가 ≠ 리스크 질량
        full_required = (
            bool(sensitive) or bool(dts) or len(nt_files) > small["max_files"] or nt_lines > small["max_lines"]
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
