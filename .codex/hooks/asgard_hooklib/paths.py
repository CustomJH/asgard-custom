"""파일·git 원시 연산 — 이 패키지에서 가장 아래.

여기 있는 것은 전부 "저장소의 어디를 어떻게 읽는가"뿐이다. 판정은 하나도 없다. 위 모듈들이
전부 이 이름들을 쓰므로 여기서 다른 hooklib 모듈을 부르면 곧장 순환이 된다 — 이 파일의
임포트가 표준 라이브러리뿐인 것이 그 계약이다.
"""

from __future__ import annotations

import os
import subprocess

# 숫자 파싱 실패 두 종. 이름으로 묶는 이유: 훅은 asgard의 venv가 아니라 그 기계가 내주는
# 인터프리터로 돈다(`platform.hook_python` — uv 가 있으면 `uv run --no-project python`,
# 없으면 PATH 의 python3/py). 괄호 없는 다중 except는 3.14+ 문법(PEP 758)이라
# 3.13 이하 기계에선 이 파일이 임포트 시점 SyntaxError가 되고, 훅 계약이 fail-open이라 그
# 죽음이 **조용하다**. 그렇다고 괄호로 쓰면 포매터(target-version=py314)가 도로 벗긴다 —
# 이름은 못 건드린다. tests/test_architecture.py의 문법 바닥 검사가 이 불변식을 지킨다.
BAD_NUMBER = (TypeError, ValueError)


# 읽을 수 없는 영수증 두 종 — 파일이 없거나 열리지 않거나(OSError), JSON 이 아니거나
# (JSONDecodeError 는 ValueError 다). 위와 같은 이유로 이름을 붙인다. `except Exception` 으로
# 뭉치면 `_unit_agent` 안의 진짜 결함(AttributeError 류)까지 조용히 건너뛰고, 그 함수는
# 빈 문자열이 정상 답이라 삼킨 자리가 겉으로 드러나지 않는다.
UNREADABLE_RECEIPT = (OSError, ValueError)


def read_text(path: str) -> str:
    """파일을 통째로 읽는다. 오류는 그대로 올린다 — 호출부마다 삼킬 범위가 다르다(없음/깨짐/권한).

    핸들 수명을 여기서 끝내는 것이 요점이다. `open(p).read()`는 CPython의 참조 계수에 기대
    곧장 닫히는 것이고, 그 기댐은 코드에 안 적혀 있어서 다른 런타임에서 조용히 깨진다."""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def read_bytes(path: str) -> bytes:
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


# ── 물리 증거 해시 — verifier-gate.py의 diff_state와 알고리즘 동일 유지 (단일 출처 원칙) ──
# 검증 실행 아티팩트 — 검증 명령이 만든 캐시가 PASS를 stale로 만들면 게이트가 자기파괴적이다
# (.gitignore 없는 프로젝트에서 pytest 실행 → __pycache__ → hash 변경, s1 라이브 실측).
# lagom: 고정 목록 — 정책 파일로 빼면 exclude 확대가 게이트 우회 벡터가 되므로 하드코딩 유지.
# ".cache": 리포 안 XDG 캐시 (CC 샌드박스가 UV_CACHE_DIR를 cwd/.cache/uv로 주입) — uv 캐시
# 전체가 ignored_snapshot에 해시로 실려 퀘스트 로그 1.5MB 블롯이 됐다 (26-07-23 실측).
_JUNK_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox", "node_modules", ".venv", ".cache"}


# 두 목록을 나눠 두는 이유 — 두 소비처가 보는 파일 집합이 다르다.
# `is_junk`는 current_tree_ref에서 **추적되지 않은**(`ls-files --others --exclude-standard`,
# `--ignored` 없음) 파일을 트리 스냅샷에서 뺀다. 여기를 넓히면 gitignore되지 않은 새 소스
# `build/x.py`가 스냅샷에서 사라져 diff 해시에 안 잡힌다 — 게이트가 증거를 못 보는 구멍이다.
# `is_generated`는 ignored_state에서 **이미 무시된** 파일만 본다. 무시된 빌드 산출물은 증거가
# 아니고, 빼지 않으면 비용이 워크트리 크기에 묶인다: cargo 릴리스 빌드 하나가 해시 대상을
# 31MB에서 2,371MB로 올려 ignored_state가 51ms에서 1,257ms가 됐고, 그 값을 state·next·
# verifier-gate 세 자리가 매 턴 따로 문다 (26-08-04 실측).
_GENERATED_DIRS = _JUNK_DIRS | {"target", "dist", "build", ".next", ".gradle", "coverage", "htmlcov"}


def is_junk(p: str) -> bool:
    return p.endswith((".pyc", ".pyo")) or any(seg in _JUNK_DIRS for seg in p.split("/"))


def is_generated(p: str) -> bool:
    return p.endswith((".pyc", ".pyo")) or any(seg in _GENERATED_DIRS for seg in p.split("/"))


def is_testfile(p: str) -> bool:
    segs = p.lower().split("/")
    return "tests" in segs or "test" in segs or segs[-1].startswith("test_") or segs[-1].endswith("_test.py")


def outside_repo(path) -> bool:
    """저장소 밖을 가리키는 산출물 선언인가 — `artifact_scope` 가 결속에서 빼는 것과 같은 술어.

    두 소비처가 한 선언을 다르게 읽으면 안 된다. 결속은 절대 경로를 거절하는데 충족 검사가
    `os.path.join(root, "/tmp/x.json")` 을 그대로 `/tmp/x.json` 으로 풀면 (파이썬의 join 규칙)
    해시에 안 묶인 저장소 밖 파일 하나가 계약을 채운다."""
    normalized = os.path.normpath(str(path)).replace("\\", "/")
    return (
        not normalized or normalized in (".", "..") or normalized.startswith(("../", "/")) or os.path.isabs(str(path))
    )


def rel_to_root(root: str, path) -> str:
    """세션 write 저널의 절대 경로를 리포 상대 경로로 — 귀속 집합 멤버십은 상대 경로 기준."""
    p = str(path)
    if not os.path.isabs(p):
        return p
    rp = os.path.realpath(root)
    ap = os.path.realpath(p)
    return os.path.relpath(ap, rp) if ap == rp or ap.startswith(rp + os.sep) else p


def fsync_dir(path: str) -> None:
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


def mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0
