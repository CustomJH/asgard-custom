"""Host probing — PATH lookups and the release-asset name for this OS/arch."""

import os
import platform as _platform
import shutil
import sys

# 창을 독에서 누르면 그 프로세스의 PATH는 셸의 것이 아니라 launchd/Explorer의 것이다 —
# macOS에서는 `/usr/bin:/bin:/usr/sbin:/sbin` 넉 줄이 전부다. 그 안에는 `claude`도
# `codex`도 없다. 그래서 터미널에서는 되던 일이 창에서는 **엔진이 없다**며 통째로 막혔다.
# (Tauri 셸이 `asgard` 실행 파일을 PATH 없이 후보 목록으로 찾는 것과 같은 이유다 —
#  그 셸은 자기 것만 찾았고, 자식이 찾아야 할 엔진은 아무도 안 챙겼다.)
#
# 여기서 하는 일은 **되찾기지 덮어쓰기가 아니다**: 있는 자리만, 이미 없는 것만, 뒤에 붙인다.
# 사용자가 정한 순서는 그대로 우선한다.
_USER_BIN_DIRS = (
    "~/.local/bin",
    "~/.local/share/mise/shims",
    "~/.bun/bin",
    "~/.volta/bin",
    "~/.npm-global/bin",
    "~/.yarn/bin",
    "~/Library/pnpm",
    "~/.asdf/shims",
    "~/.nix-profile/bin",
    "~/bin",
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
)
_WINDOWS_BIN_DIRS = (
    r"%LOCALAPPDATA%\Programs",
    r"%LOCALAPPDATA%\Microsoft\WindowsApps",
    r"%APPDATA%\npm",
    r"%USERPROFILE%\.local\bin",
    r"%USERPROFILE%\.bun\bin",
)


def user_bin_dirs() -> list[str]:
    """이 기계에서 사용자 도구가 실제로 있는 자리 — 존재하는 것만."""
    raw = _WINDOWS_BIN_DIRS if sys.platform == "win32" else _USER_BIN_DIRS
    found = []
    for entry in raw:
        path = os.path.expandvars(os.path.expanduser(entry))
        if "%" not in path and os.path.isdir(path):
            found.append(os.path.normpath(path))
    return list(dict.fromkeys(found))


def ensure_user_path() -> list[str]:
    """빠진 사용자 bin 자리를 PATH 뒤에 되붙이고, 새로 붙인 것을 돌려준다.

    멱등이다 — 두 번 불러도 같은 자리를 두 번 붙이지 않는다. 자식 프로세스는
    `os.environ`을 물려받으므로, 창이 띄우는 `asgard run`도 같은 PATH로 선다."""
    current = os.environ.get("PATH", "")
    known = {os.path.normpath(p) for p in current.split(os.pathsep) if p}
    added = [d for d in user_bin_dirs() if d not in known]
    if added:
        os.environ["PATH"] = os.pathsep.join([current, *added]) if current else os.pathsep.join(added)
    return added


def on_path(binary: str) -> str | None:
    return shutil.which(binary)


# 훅 인터프리터의 정본 **표기**. install.sh·install.ps1은 uv 를 먼저 깔고 그 uv 가 관리하는
# CPython 위에 asgard 를 올린다 — 그러므로 설치가 끝난 기계에서 존재가 보장된 런타임은 uv 뿐이다.
# 에이전트 안내문과 권한 허용목록이 이 한 문자열을 쓴다 (표기가 갈리면 헤드리스에서 자동
# 거부된다). 자기완결 배포 제약으로 이 모듈을 임포트하지 못하는 훅(verifier_gate·
# subagent_gate)은 같은 문자열을 리터럴로 적고 주석으로 이 자리를 가리킨다.
#
# 배선에는 이 맨 표기를 쓰지 않는다 — `hook_python()` 이 내는 절대 경로 형태를 쓴다.
UV_HOOK_PYTHON = "uv run --no-project python"


def _fallback_python() -> str:
    """uv 가 없는 기계의 시스템 파이썬 — POSIX 는 python3, Windows 는 python → py 런처 순.

    스캐폴드는 타깃 머신에서 생성되므로 생성 시점 감지가 맞다."""
    names = ("python3",) if sys.platform != "win32" else ("python", "py")
    return next((c for c in names if shutil.which(c)), names[0])


def hook_python_token() -> str:
    """안내문·허용목록에 적는 맨 토큰 — 모델이 그대로 타이핑하는 형태다.

    기계마다 다른 절대 경로를 여기 담으면 허용목록 항목이 안내문과 어긋나 헤드리스(-p)에서
    자동 거부된다. 그래서 이쪽은 절대 경로로 내려가지 않는다."""
    return UV_HOOK_PYTHON if shutil.which("uv") else _fallback_python()


def hook_python_argv() -> list[str]:
    """훅이 실제로 실행할 인터프리터 — 첫 낱말이 절대 경로다.

    맨 `uv` 를 배선하면 PATH 에 `~/.local/bin` 이 없는 프로세스에서 훅 줄이 전부 exit 127 이
    된다. 독·Finder·launchd 가 띄운 프로세스의 PATH 는 `/usr/bin:/bin:/usr/sbin:/sbin` 넉 줄이
    전부고, 거기에 `python3` 는 있어도 `uv` 는 없다. 훅 계약이 fail-open 이라 그 죽음은
    조용하다 — 가드도 활성기도 아무 일을 안 하는데 doctor 는 초록을 찍는다.
    `shutil.which` 가 이미 푼 절대 경로를 그대로 들고 있으면 PATH 와 무관하게 선다."""
    uv = shutil.which("uv")
    if uv:
        # Windows 경로의 역슬래시는 따옴표 안에서도 셸마다 다르게 읽힌다 — 정방향 슬래시는
        # CreateProcess 도 POSIX 셸도 같이 받는다.
        uv = uv.replace("\\", "/")
        # 작은따옴표가 든 경로는 codex 의 TOML 리터럴 문자열 안에서 탈출할 방법이 없다 —
        # 설정 파일이 통째로 깨지느니 그 기계에서만 맨 토큰(PATH 조회)으로 돌아간다.
        return [uv if "'" not in uv else "uv", "run", "--no-project", "python"]
    return [_fallback_python()]


def hook_python() -> str:
    """훅 배선용 파이썬 명령 — uv 가 있으면 uv 가 정본이고, 경로는 절대 경로다.

    설치 경로(install.sh·install.ps1)가 uv → uv 관리 CPython → `uv tool install asgard` 순서라
    uv 는 어느 호스트에서도 있다고 볼 수 있는 유일한 런타임이다. 반대로 시스템 `python3`는
    없을 수 있고(Windows 는 없는 쪽이 보통), 있어도 설치가 쓴 것보다 낡을 수 있다.

    `--no-project` 는 남의 저장소 `pyproject.toml` 의 `requires-python` 해석을 건너뛴다 —
    그 값이 이 기계에 없는 버전을 요구하면 맨 `uv run` 은 인터프리터를 못 찾고 그대로
    실패한다(실측: `requires-python = ">=3.99"` 에서 `uv run` 은 error, `uv run --no-project`
    는 성공). 프로젝트 venv 를 떼어 주지는 **않는다** — cwd 에 `.venv` 가 있으면 uv 는 그것을
    그대로 쓴다. 훅은 stdlib 만 쓰므로 그 venv 가 무엇이든 상관없다.

    uv 가 없는 기계(패키지 매니저로 따로 깐 경우)를 위해 기존 탐지를 폴백으로 남긴다."""
    program, *rest = hook_python_argv()
    # 공백이 든 경로는 따옴표가 없으면 두 낱말로 쪼개진다 (Windows 의 `C:/Program Files/…`).
    return " ".join([f'"{program}"' if " " in program else program, *rest])


def release_asset() -> str:
    os_name = {"darwin": "darwin", "linux": "linux", "win32": "windows"}.get(sys.platform, "")
    machine = _platform.machine().lower()
    arch = "x64" if machine in ("x86_64", "amd64") else "arm64" if machine in ("arm64", "aarch64") else ""
    if not os_name or not arch:
        raise RuntimeError(f"unsupported platform {sys.platform}/{_platform.machine()}")
    return f"asgard-{os_name}-{arch}" + (".exe" if os_name == "windows" else "")
