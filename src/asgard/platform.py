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
# 배선에는 이 맨 표기를 그대로 쓰지 않는다 — `hook_python()` 이 내는 런처 호출을 쓴다.
UV_HOOK_PYTHON = "uv run --no-project python"

# 배선이 부르는 런처의 파일 이름. 훅 폴더에 훅과 나란히 깔린다(`commands/setup.py`), 본문은
# `templates/env.py` 의 `hook_launcher_sh()` 다.
HOOK_LAUNCHER = "asgard-python"

# 환경 프리플라이트의 두 본문 — 훅 폴더에 훅과 나란히 깔린다. 본문은 `templates/env.py` 가
# 내고, 어느 쪽을 배선에 적을지는 아래 `preflight_command` 가 이 기계를 보고 정한다.
PREFLIGHT_SH = "env-setup.sh"
PREFLIGHT_PS1 = "env-setup.ps1"

# 이 저장소가 서는 CPython 핀 — pyproject 의 `requires-python` 과 같은 값이다. install.sh·
# install.ps1 이 `uv python install` 로 미리 받아 두는 버전이고, `asgard update` 가 도구를
# 다시 깔 때 넘기는 `--python` 값이며, 아스가르드 없이 저장소를 연 사람에게 환경 프리플라이트
# (`templates/env.py`)가 깔아 주는 버전이기도 하다. 네 자리가 갈리면 훅이 서는 파이썬과 패키지가
# 요구하는 파이썬이 어긋난다.
PYTHON_PIN = "3.14"


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
    """지금 이 기계에서 훅 인터프리터를 부르는 argv — 첫 낱말이 절대 경로다.

    배선에 적히는 값이 아니다. 배선은 런처를 거치고(`hook_python`), 이쪽은 **지금 여기서 한 번
    돌려 보는** 쪽이 쓴다 — `doctor` 의 인터프리터 검사가 배선을 못 읽었을 때 물러서는 자리이고,
    `--no-project` 를 포함한 정확한 호출 형태를 아는 유일한 함수다.

    `--no-project` 는 남의 저장소 `pyproject.toml` 의 `requires-python` 해석을 건너뛴다 — 그 값이
    이 기계에 없는 버전을 요구하면 맨 `uv run` 은 인터프리터를 못 찾고 그대로 실패한다(실측:
    `requires-python = ">=3.99"` 에서 `uv run` 은 error, `uv run --no-project` 는 성공). 프로젝트
    venv 를 떼어 주지는 **않는다** — cwd 에 `.venv` 가 있으면 uv 는 그것을 그대로 쓴다. 훅은
    stdlib 만 쓰므로 그 venv 가 무엇이든 상관없다."""
    uv = shutil.which("uv")
    if uv:
        # Windows 경로의 역슬래시는 따옴표 안에서도 셸마다 다르게 읽힌다 — 정방향 슬래시는
        # CreateProcess 도 POSIX 셸도 같이 받는다.
        uv = uv.replace("\\", "/")
        # 작은따옴표가 든 경로는 codex 의 TOML 리터럴 문자열 안에서 탈출할 방법이 없다 —
        # 설정 파일이 통째로 깨지느니 그 기계에서만 맨 토큰(PATH 조회)으로 돌아간다.
        return [uv if "'" not in uv else "uv", "run", "--no-project", "python"]
    return [_fallback_python()]


def hook_python(hooks_dir: str = "") -> str:
    """훅 배선에 적을 인터프리터 명령 — 이 기계에서만 맞는 값은 담지 않는다.

    배선 파일은 팀에 커밋돼 전달된다 (`commands/setup.py` 의 gitignore 블록: 스캐폴드는 팀 공유).
    그래서 스캐폴드를 만든 기계의 uv 절대 경로를 여기에 적으면, 저장소를 받은 다른 기계에서는 훅
    줄이 전부 exit 127 로 끝난다. 훅 계약이 fail-open 이라 그 죽음은 화면에 안 뜬다 — 가드도 주입도
    게이트도 없는 채로 세션이 돈다.

    맨 `uv` 도 적을 수 없다. 독·Finder·launchd 가 띄운 프로세스가 물려받는 PATH 는
    `/usr/bin:/bin:/usr/sbin:/sbin` 넉 줄이 전부고, 거기에 `python3` 는 있어도 `uv` 는 없다.
    두 요구를 같이 푸는 자리가 훅 폴더에 훅과 나란히 깔리는 런처(`HOOK_LAUNCHER`)다: 배선에는
    저장소 안 경로만 적히고, 어느 uv 를 쓸지는 그 기계 위에서 런처가 정한다.

    `hooks_dir` 는 그 런처가 깔린 경로를 배선 문법으로 적은 것이라 호스트마다 다르다
    (`$CLAUDE_PROJECT_DIR/.claude/hooks`, `$(git rev-parse --show-toplevel)/.codex/hooks`,
    `.cursor/hooks`). 안 주면 런처를 거치지 않는 맨 토큰으로 답한다.

    Windows 는 런처를 안 쓴다. PATH 가 넉 줄로 잘리는 것은 launchd 의 성질이고, Explorer 가 띄운
    프로세스는 레지스트리 PATH 를 그대로 물려받아 `uv` 가 잡힌다. 대신 `sh` 가 있다는 보장이 없는
    쪽이라, 그 기계에서는 맨 토큰이 더 넓게 선다."""
    if hooks_dir and sys.platform != "win32":
        return 'sh "%s/%s"' % (hooks_dir.rstrip("/"), HOOK_LAUNCHER)
    return hook_python_token()


def preflight_command(hooks_dir: str, client: str) -> str:
    """프리플라이트를 부르는 배선 한 줄 — 러너는 스캐폴드 시점 플랫폼이 정한다.

    한 기계에는 이 줄이 하나만 선다. 둘 다 걸면 어느 쪽에서든 하나는 러너가 없어 exit 127 로
    끝나고, 훅 계약이 fail-open 이라 그 실패가 매 세션 화면에 남는다.

    Windows 가 PowerShell 인 이유는 `hook_python` 이 거기서 런처를 안 쓰는 이유와 같다 — 그
    기계에 `sh` 가 있다는 보장이 없다. 반대로 PowerShell 은 어느 판에나 실려 있다.

    한계 하나를 적어 둔다. 배선 파일은 팀에 커밋돼 전달되므로, macOS 에서 만든 스캐폴드를
    Windows 에서 열면 이 줄은 여전히 `sh` 를 부른다 (그 반대도 같다). 훅 줄들은 런처가 그
    경우를 흡수하지만 프리플라이트는 러너 자체가 갈려서 못 흡수한다 — 그 기계에서는
    `asgard sync` 가 배선을 다시 써야 한다."""
    base = hooks_dir.rstrip("/")
    if sys.platform == "win32":
        return 'powershell -NoProfile -ExecutionPolicy Bypass -File "%s/%s" %s' % (base, PREFLIGHT_PS1, client)
    return 'sh "%s/%s" %s' % (base, PREFLIGHT_SH, client)


def release_asset() -> str:
    os_name = {"darwin": "darwin", "linux": "linux", "win32": "windows"}.get(sys.platform, "")
    machine = _platform.machine().lower()
    arch = "x64" if machine in ("x86_64", "amd64") else "arm64" if machine in ("arm64", "aarch64") else ""
    if not os_name or not arch:
        raise RuntimeError(f"unsupported platform {sys.platform}/{_platform.machine()}")
    return f"asgard-{os_name}-{arch}" + (".exe" if os_name == "windows" else "")
