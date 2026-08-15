"""귀속 범위 — 판정 해시가 무엇을 보고 무엇을 안 보는가.

무시된 파일(`ignored_state`)·심링크·지도 아래 산출물은 diff 에 안 잡히므로 별도로 관측한다.
넓히면 게이트가 증거를 못 보는 구멍이 되고, 좁히면 검증 실행이 만든 캐시가 PASS 를 stale 로
만든다. 그 두 실패가 같은 술어를 공유해야 해서 한 모듈이다.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat

from .paths import git, rel_to_root


def in_artifact_scope(path: str, scope) -> bool:
    """선언된 산출물 자신이거나 그 아래인가 (세그먼트 경계 — `workspace2/`가 `workspace`에 안 걸린다)."""
    return any(path == entry or path.startswith(entry + "/") for entry in scope)


def reconcile_ignored(root: str, ignored_base: dict[str, str] | None, digest, scope=()) -> list[str]:
    """무시 파일의 기준선↔현재 대조. 바뀐 경로를 돌려주고 그 내역을 digest에 먹인다.

    verifier_gate.py의 같은 이름 함수와 동일 유지 (단일 출처 원칙 — 어긋나면 영구 stale).
    ignored_base가 None이면 대조 대상이 없다는 뜻이라 빈 목록. scope가 비면 선언된 산출물이
    없다는 뜻이라 역시 빈 목록 — 그때는 열거조차 하지 않는다 (`artifact_scope` 참고)."""
    if ignored_base is None or not scope:
        return []
    # 기준선도 현재와 같은 scope를 태운다. 안 그러면 목록이 좁아지거나 넓어진 순간, 열려 있던
    # 퀘스트의 스냅샷에만 남은 경로가 전부 "사라짐 = 변경"으로 읽혀 PASS가 통째로 stale이 된다
    # (26-08-04: target 추가 시 changed_files 8,118건).
    base = {path: value for path, value in ignored_base.items() if in_artifact_scope(path, scope)}
    current = ignored_state(root, scope)
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


# 결속 불가 표식 — 이 접두사가 붙은 값은 "지금 이 상태"는 적지만 **내용 변화를 안 따라간다**.
# verifier_gate.py 의 같은 상수와 동일 유지 (단일 출처 원칙 — 어긋나면 영구 stale).
UNBOUND = "<unbound:"


def ignored_state(root: str, scope=()) -> dict[str, str]:
    """Hash ignored non-generated files under `scope` without following symlinks, so declared
    artifacts cannot evade quest binding. 빈 scope는 결속 대상이 없다는 뜻이라 git도 안 부른다 —
    이 저장소에서 전 무시 파일 7,507건 열거·해시가 432ms 였다 (26-08-05 콜드 실측)."""
    if not scope:
        return {}
    rc, raw = git(
        root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
        *scope,
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
        # pathspec 은 glob 을 받는다 — 선언이 `*` 한 글자여도 결속 범위는 넓어지지 않게, 돌려받은
        # 경로를 같은 술어로 한 번 더 거른다 (scope 는 퀘스트를 연 쪽이 쓴 값이다).
        # `is_generated` 는 여기서 안 태운다: 전 저장소를 훑던 시절의 비용 상한이지 결속 규칙이
        # 아니고, 태우면 `artifacts: build/report.json` 처럼 **선언된** 산출물이 조용히 안 묶인다
        # — Gradle·Maven 의 기본 출력 자리가 바로 `build/`·`target/` 이다.
        if not in_artifact_scope(path, scope):
            continue
        full = os.path.join(root, path)
        try:
            info = os.lstat(full)
            if stat.S_ISLNK(info.st_mode):
                # 링크는 따라가지 않는다 — 저장소 밖 자격 증명을 증거로 열지 않기 위해서다.
                # 그래서 이 값은 링크가 가리키는 파일의 내용을 안 담는다: 대상을 고쳐도 값이
                # 그대로라, 선언은 결속을 약속하는데 해시는 안 따라간다. 표식을 붙여 두면
                # `unbound_artifacts` 가 그것을 미충족으로 돌려준다.
                body = b"<symlink>\0" + os.readlink(full).encode("utf-8", "surrogateescape")
                out[path] = UNBOUND + "symlink:" + hashlib.sha256(body).hexdigest()[:16]
            elif stat.S_ISREG(info.st_mode):
                digest = hashlib.sha256()
                with open(full, "rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                out[path] = digest.hexdigest()
            else:
                # `git ls-files` 는 중첩 저장소 안으로 안 내려가고 `sub/` 한 줄만 낸다.
                # 디렉터리의 lstat 값은 그 안에서 무엇이 바뀌어도 그대로다 — 같은 부류다.
                out[path] = UNBOUND + f"nonregular:{stat.S_IFMT(info.st_mode):o}"
        except OSError:
            out[path] = "<missing>"
    return out


def _symlink_on_the_way(root: str, entry: str) -> str:
    """선언한 경로에 닿기까지 거치는 칸 중 첫 심링크 — 없으면 빈 문자열."""
    parts = entry.split("/")
    for depth in range(1, len(parts) + 1):
        branch = "/".join(parts[:depth])
        if os.path.islink(os.path.join(root, branch)):
            return branch
    return ""


def _symlinks_under(root: str, entry: str) -> list[str]:
    """선언한 자리 아래의 심링크 경로들 (저장소 상대). 파일 선언이면 빈 목록."""
    out = []
    for parent, dirs, files in os.walk(os.path.join(root, entry), followlinks=False):
        for name in dirs + files:
            full = os.path.join(parent, name)
            if os.path.islink(full):
                out.append(os.path.relpath(full, root).replace("\\", "/"))
    return out


def _bound_map_page(path: str) -> bool:
    """`.asgard` 아래에서 판정 해시가 유일하게 다시 읽는 자리인가 — 지도 바로 아래의 `*.md`.
    `diff_state` 의 지도 대조와 같은 폭이다 (readonly_guard 의 `within_managed_map` 도 같다)."""
    return path.startswith(".asgard/map/") and path.endswith(".md") and path.count("/") == 2


def unbound_artifacts(root: str, scope) -> list[str]:
    """선언은 결속을 약속하는데 해시가 못 따라가는 산출물 — 사유를 붙여 돌려준다.

    두 형상이 여기 걸린다 (26-08-05 실행 확인). 심링크는 링크 신원만 해시되므로 대상 파일을
    고쳐도 값이 안 움직이고, 중첩 저장소는 `git ls-files` 가 안으로 안 내려가 디렉터리 한 줄만
    나오며 그 lstat 값은 안 바뀐다. 둘 다 링크를 안 따라가는 것 자체는 옳다 — 문제는 안 묶이는
    선언이 조용히 통과하는 것이다. 그래서 미충족으로 돌려주고 PASS 를 막는다.

    추적 파일도 첫 고리에서 본다: 추적된 심링크는 `ignored_state` 의 열거에 안 들어오지만
    링크 뒤 파일의 내용이 안 묶이는 것은 똑같다. verifier_gate.py 의 같은 이름 함수와 동일 유지.

    lagom: 열거를 `diff_state` 와 나눠 쓰지 않고 한 번 더 돈다. 두 호출 사이에 계약 명령이
    끼어 파일을 바꾸므로 (`run_criteria_checks`) 메모한 값은 그 자리에서 이미 낡는다. 값은
    선언한 범위에 비례하고 선언이 없으면 0 이다 — 넓은 선언이 비싸지면 그때 나눠라."""
    reasons: dict[str, str] = {}
    for entry in scope:
        # 하네스 상태는 어느 트리에도 안 들어간다 (`current_tree_ref` 와 `ignored_state` 가 둘 다
        # `.asgard` 를 뺀다). 지도의 `*.md` 만 예외로 다시 읽힌다 — 나머지는 존재만 확인될 뿐
        # 내용이 어디에도 안 묶인다.
        if entry == ".asgard" or (entry.startswith(".asgard/") and not _bound_map_page(entry)):
            reasons[entry] = "under .asgard — the verdict hash excludes harness state"
            continue
        # 선언한 경로 자신뿐 아니라 **거쳐 가는 칸마다** 본다. 중간 칸이 링크면 (`out -> /tmp`,
        # 선언은 `out/x.json`) `os.path.exists` 는 링크를 따라가 "있다"고 답하는데 git 은 링크
        # 하나만 저장하고 그 안으로 안 내려간다 — 저장소 밖 파일이 계약을 채운다.
        ancestor = _symlink_on_the_way(root, entry)
        if ancestor:
            reasons[entry] = f"reached through the symlink `{ancestor}` — git stores the link, not what is behind it"
            continue
        # 선언한 디렉터리 **안의** 링크도 같은 자리다. 추적 여부로 갈리면 안 되므로
        # (추적 링크는 무시 파일 열거에, 새 링크는 어느 열거에도 안 나온다) 걸어서 본다.
        for rel in _symlinks_under(root, entry):
            reasons.setdefault(rel, "symlink — the gate hashes the link, not the file it points at")
    for path, value in ignored_state(root, scope).items():
        if isinstance(value, str) and value.startswith(UNBOUND):
            reasons.setdefault(
                path,
                "symlink — the gate hashes the link, not the file it points at"
                if "symlink" in value
                else "not a regular file — git does not enumerate inside it (a nested repository?)",
            )
    return [f"{path} ({reason})" for path, reason in sorted(reasons.items())]


def quest_owned_files(root: str, events: list[dict]) -> set[str]:
    """퀘스트 귀속 파일 — work 이벤트의 changed_files(세션 관측 write) ∪ 참여 세션 write 저널.
    verify 이벤트의 changed_files는 전 트리 diff라 타 세션 잔여물이 섞인다 — 소유 근거 아님."""
    owned = {
        rel_to_root(root, p)
        for e in events
        if e.get("event") == "work"
        for p in (e.get("changed_files") or [])
        if str(p).strip()
    }
    for sid in {str(e.get("session_id")) for e in events if e.get("session_id")}:
        try:
            with open(os.path.join(root, ".asgard", "state", f"writes-{sid}.json"), encoding="utf-8") as handle:
                journal = json.load(handle)
            owned.update(rel_to_root(root, p) for p in journal if str(p).strip())
        except Exception:
            pass
    return owned


UNSCOPED_DRIFT = "<unscoped>"  # 귀속을 못 따진 fail-safe stale — 경로가 아니라 사유 표시다
