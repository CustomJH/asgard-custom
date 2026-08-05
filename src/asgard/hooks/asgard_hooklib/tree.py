"""물리 증거 — 워킹트리를 그대로 트리 객체로 떠서 해시한다.

로그에 뭘 적든 워킹트리는 위조할 수 없다. 그래서 완료 판정의 최종 근거가 여기 있다. 사용자
인덱스를 건드리지 않으려고 임시 `GIT_INDEX_FILE` 위에서만 작업한다.

quest-log 와 verifier-gate 가 같은 해시를 내야 한다는 것이 계약인데, 26-08-06 까지 두 파일에
사본으로 살면서 `current_tree_ref`·`ignored_state`·`artifact_scope` 셋이 이미 갈라져 있었다.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import tempfile

from .integrity import EMPTY
from .paths import git, is_junk, is_testfile, read_bytes
from .scope import UNSCOPED_DRIFT, quest_owned_files, reconcile_ignored, symlink_map_state


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
            if run(*_STAT_NEUTRAL, "add", "-A", "-f", "--", ".asgard/map").returncode:
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


# 임시 인덱스 위의 `add -A` 에서 stat 캐시 밖의 지름길을 끈다. 인덱스 사본은 fsmonitor 표식과
# untracked 캐시를 함께 들고 오는데, 새로 세운 인덱스에는 둘 다 없다 — 켜 둔 채로 두면 씨앗에
# 따라 훑는 범위가 달라져 같은 워킹트리가 다른 트리를 낸다. `assume-unchanged` 를 거르는 것과
# 같은 이유다 (26-08-05 2차 교차검토).
_STAT_NEUTRAL = ("-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false")


def seed_index(root: str, head: str, index_path: str, run) -> bool:
    """임시 인덱스를 HEAD 트리 내용으로 채운다 — 가능하면 저장소 인덱스를 복사해서.

    `read-tree HEAD` 는 stat 정보가 없는 인덱스를 만든다. 그러면 뒤따르는 `git add -A` 가 추적
    파일을 전부 다시 읽고 해시한다: 26-08-05 콜드 실측에서 스냅샷 500ms 중 `add -A` 가 382ms
    였고, 그 값을 Stop 게이트가 매 턴 문다. 저장소 인덱스는 그 stat 캐시를 이미 갖고 있어 같은
    `add -A` 가 56ms 다.

    복사는 **인덱스가 HEAD 와 한 글자도 다르지 않을 때만** 쓴다 (`diff-index --cached --quiet`).
    스테이지된 변경이 있으면 두 씨앗의 트리가 갈리기 때문이다: `add -A` 는 `.asgard` 를 안
    덮으므로 그 구역은 씨앗이 넣은 내용 그대로 실리고, 인덱스에서 지워진 뒤 gitignore 에 걸린
    추적 파일은 `add -A` 가 다시 안 넣는다. 샌드박스 실측에서 `.asgard/policy.json` 을
    스테이지하자 `read-tree` 는 HEAD 판을, 사본은 스테이지 판을 실었다 — `read-tree -m` 도
    그것을 지역 변경으로 보고 그대로 뒀다. 스테이지가 비어 있으면 인덱스 내용이 곧 HEAD 트리라
    그 갈림이 성립할 수 없다. 그때 두 씨앗의 트리는 같다 (이 저장소 실측: 세 상태 전부
    `d3b32f6d…` 동일).

    같은 이유로 `assume-unchanged`·`skip-worktree` 표가 붙은 항목이 하나라도 있으면 사본을 안
    쓴다. `add -A` 는 그 표를 존중해 항목을 건너뛰는데 새로 세운 인덱스에는 표가 없어 같은
    `add -A` 가 다시 해시한다 — 사본을 쓰면 그 파일의 편집이 스냅샷에서 사라지고 게이트가
    증거를 못 본다 (26-08-05 재현: 한 파일에 표를 붙이고 고치자 두 트리가 갈렸다).
    `GIT_INDEX_FILE` 이 이미 환경에 서 있으면 검사와 복사가 서로 다른 인덱스를 보므로 그때도
    느린 길로 간다.

    검사 둘이 이 저장소에서 약 100ms 다 (`ls-files -v` 가 추적 파일 3,900건을 나열한다). 그래도
    남는 값이 크다: 스냅샷 556ms → 250ms, Stop 게이트 742ms → 402ms (26-08-05 콜드 실측).

    검사와 복사 사이에 다른 프로세스가 스테이지하면 그 틈으로 스테이지된 `.asgard` 판이 실릴
    수 있다. 그 구역은 diff 에서 빠져 있어 (`-- . :(exclude).asgard`) PASS 판정을 못 뒤집고,
    `tree_ref` 대조에서는 귀속 밖 드리프트로 잡혀 재검증 쪽으로 기운다.

    돌려주는 값은 씨앗을 세웠는가다 — 실패면 호출자가 스냅샷을 포기한다."""
    if not any(os.environ.get(name) for name in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE")) and (
        git(root, "diff-index", "--cached", "--quiet", head)[0] == 0
    ):
        rc, listing = git(root, "ls-files", "-v")
        listing = listing.decode("utf-8", "replace") if isinstance(listing, bytes) else listing
        # `ls-files -v` 의 머리글자: 소문자 = assume-unchanged, `S` = skip-worktree.
        flagged = rc != 0 or any(row[:1].islower() or row[:1] == "S" for row in listing.splitlines() if row)
        if not flagged:
            try:
                shutil.copy2(os.path.join(root, ".git", "index"), index_path)
                return True
            except OSError:
                pass  # 인덱스가 없는 저장소(첫 커밋 직후)·읽기 실패 — 느린 길이 남아 있다
    return run("read-tree", head).returncode == 0


def current_tree_ref(root: str) -> str | None:
    """Materialize the exact current non-control tree in a temporary index without touching the user's index.

    비싸다 — 이 저장소에서 한 번에 약 75ms 이고 그 대부분이 git 네 번이다. 한 판정이 이것을
    여러 번 필요로 하면 **부르는 쪽이 한 번 지어 나눠 준다** (아래 세 함수의 `current_ref` 인자).
    여기에 캐시를 두지 않는 이유는 정확성이다: 이 함수의 답은 작업 트리가 바뀌면 같이 바뀌어야
    하고, 그 수명을 아는 것은 판정을 조립하는 쪽뿐이다 (26-08-06: 캐시를 여기 두자 파일을 고친
    뒤에도 옛 해시가 나왔다 — 게이트가 낡은 트리로 PASS 를 주는 모양이다)."""
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
        if not seed_index(root, head.strip(), index_path, run):
            return None
        if run(*_STAT_NEUTRAL, "add", "-A", "--", ".", ":(exclude).asgard").returncode:
            return None
        _, raw_untracked = git(
            root, "ls-files", "--others", "--exclude-standard", "-z", "--", ".", ":(exclude).asgard", binary=True
        )
        if isinstance(raw_untracked, str):
            raw_untracked = raw_untracked.encode("utf-8", "surrogateescape")
        junk = [
            path for path in raw_untracked.split(b"\0") if path and is_junk(path.decode("utf-8", "surrogateescape"))
        ]
        if (
            junk
            and run("update-index", "--force-remove", "-z", "--stdin", input_data=b"\0".join(junk) + b"\0").returncode
        ):
            return None
        if os.path.isdir(os.path.join(root, ".asgard", "map")):
            if run(*_STAT_NEUTRAL, "add", "-A", "-f", "--", ".asgard/map").returncode:
                return None
        tree = run("write-tree")
        return tree.stdout.decode().strip() if tree.returncode == 0 and tree.stdout.strip() else None
    finally:
        with contextlib.suppress(OSError):
            os.unlink(index_path)


def diff_state(
    root: str,
    base_ref: str | None,
    ignored_base: dict[str, str] | None = None,
    scope=(),
    current_ref: str | None = None,
) -> tuple[str, list[str], int, int]:
    """(diff_hash, changed_files, changed_lines, nontest_lines) — base_ref 트리 ↔ 현재 워킹트리 전체.
    커밋 여부와 무관 (base_ref는 open 시점 고정 커밋). `.asgard/**` 제외 — 로그 기록 자체가
    diff를 바꾸면 해시가 자기참조로 영원히 안 맞는다.
    nontest_lines: 테스트 파일 제외 변경 라인 — 테스트 추가는 검증 표면이지 리스크 질량이 아니다
    (스모크 벤치 발견: 잠금 테스트 2파일 추가가 big 판정 → 게이트-우선 무력화). 삭제된 테스트는
    별도 하드 트리거 (deleted_tests)."""
    if not base_ref or base_ref == "NONE":
        return EMPTY, [], 0, 0
    current_ref = current_ref or current_tree_ref(root)
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
            after = symlink_map_state(full_path) if is_link else read_bytes(full_path)
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
            if not is_testfile(parts[2]):
                nt_lines += n
    h = hashlib.sha256(diff)
    ignored_changed = reconcile_ignored(root, ignored_base, h, scope)
    changed = sorted(set(n for n in names.splitlines() if n.strip()) | set(map_changed) | set(ignored_changed))
    return (h.hexdigest() if changed else EMPTY), changed, lines, nt_lines


def deleted_tests(root: str, base_ref: str | None, current_ref: str | None = None) -> list[str]:
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
    current_ref = current_ref or current_tree_ref(root)
    refs = [base_ref, current_ref] if current_ref else [base_ref]
    _, out = git(root, "diff", "--name-only", "--diff-filter=D", *refs, "--", ".", ":(exclude).asgard")
    return [p for p in out.splitlines() if p.strip() and is_testfile(p)]


_SIG_PAT = re.compile(r"^-\s*(def |class |function |export |public |fn |return\b|yield\b)")


def signature_risk(root: str, base_ref: str | None, current_ref: str | None = None) -> bool:
    """diff에 삭제·변경된 공개 선언·반환 라인 존재 여부 — 숨은-caller/값 형태 리스크 신호.
    '-' 라인만 본다: 신규 추가(+def)는 기존 caller가 없고, 바뀐 줄은 기존 '-' 절반이 잡힌다.
    게이트-우선(STANDARD) 라우팅 전용 — verifier_gate 대응 불필요.

    현재 쪽을 트리로 맞대는 이유는 deleted_tests와 같다 — 색인과 맞대면 미추적 파일이 통째로
    '-' 라인이 되어 있지도 않은 시그니처 삭제가 잡힌다."""
    if not base_ref or base_ref == "NONE":
        return False
    current_ref = current_ref or current_tree_ref(root)
    refs = [base_ref, current_ref] if current_ref else [base_ref]
    rc, out = git(root, "diff", "-U0", *refs, "--", ".", ":(exclude).asgard")
    if rc != 0:
        return False
    return any(_SIG_PAT.match(line) for line in out.splitlines())


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
