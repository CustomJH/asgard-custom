"""Container execution boundaries for ``asgard start``."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from hashlib import sha256
from importlib.resources import files
from pathlib import Path

from . import __version__

MODES = ("local", "container", "container-shared", "sandbox", "sandbox-shared")
_NAME_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}")
_API_KEY_ENVS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "NVIDIA_API_KEY",
    "OLLAMA_API_KEY",
)

# 컨테이너 안에서 에이전트 홈을 두는 자리 — assets/container_kit/Dockerfile의 VOLUME과
# **동일 유지**. 호스트 경로를 그대로 넘기면 컨테이너 안에 없는 경로가 되므로 여기로 옮겨서
# 넘긴다. 마지막 조각이 에이전트 이름인 이유: profiles.active()가 이 경로를 뿌리로도
# profiles/<id>로도 못 읽어 `custom`을 돌려주고, profiles.label_for()가 명세 없는 홈을 홈
# 디렉터리 이름으로 부른다. 컨테이너 여럿을 띄웠을 때 서로를 가르는 이름이 이것이다.
CONTAINER_AGENT_ROOT = "/agent"

# 이미지가 root로 도므로 컨테이너 안 기계 뿌리는 /root/.asgard다 (providers.CRED_PATH와 같은 자리).
CONTAINER_CRED_PATH = "/root/.asgard/credentials.json"

# 경로 조각이 될 이름에서 허용하지 않는 문자.
_LABEL_UNSAFE = re.compile(r"[^a-zA-Z0-9_.-]+")

_TRUTHY = ("1", "true", "yes", "on")


def choose_mode(requested: str | None) -> str:
    """Resolve an explicit/env mode, or ask only in an interactive host terminal."""
    mode = requested or os.environ.get("ASGARD_EXECUTION")
    if mode:
        if mode not in MODES:
            raise ValueError(f"execution must be one of: {', '.join(MODES)}")
        return mode
    if not sys.stdin.isatty():
        return "local"
    from . import picker

    if picker.available():  # 인터랙티브 패널 (같은 foundation 계층) — 번호 입력은 폴백
        opts = [
            picker.Option("local", "local", detail="fastest; agent can reach the host"),
            picker.Option("container", "container", detail="private workspace; Docker/Podman on macOS or Windows"),
            picker.Option("container-shared", "container shared", detail="edits the host working tree live"),
            picker.Option("sandbox", "Docker Sandbox", detail="microVM + private Git clone (requires sbx login)"),
        ]
        return picker.pick("execution environment", opts) or "local"
    sys.stdout.write(
        "\n  execution environment\n"
        "    1  local            fastest; agent can reach the host\n"
        "    2  container        private workspace; Docker/Podman on macOS or Windows\n"
        "    3  container shared edits the host working tree live\n"
        "    4  Docker Sandbox   microVM + private Git clone (requires sbx login)\n"
    )
    try:
        answer = input("  number [1]: ").strip() or "1"
    except EOFError, KeyboardInterrupt:
        return "local"
    return {"1": "local", "2": "container", "3": "container-shared", "4": "sandbox"}.get(answer, "local")


def sandbox_name(root: str, shared: bool = False) -> str:
    leaf = re.sub(r"[^a-zA-Z0-9.+-]+", "-", os.path.basename(os.path.abspath(root))).strip("-") or "project"
    digest = sha256(os.path.abspath(root).encode()).hexdigest()[:8]
    return f"asgard-{leaf[:35]}-{digest}-{'shared' if shared else 'isolated'}"


def _container_engine() -> str | None:
    requested = os.environ.get("ASGARD_CONTAINER_ENGINE")
    if requested:
        return shutil.which(requested)
    return shutil.which("docker") or shutil.which("podman")


def _private_workspace(root: str, name: str) -> Path:
    if not _NAME_RE.fullmatch(name):
        raise ValueError("sandbox name must contain only letters, numbers, '.', '_' or '-'")
    target = Path.home() / ".asgard" / "sandboxes" / name
    if target.is_symlink():
        raise ValueError("sandbox workspace cannot be a symlink")
    if target.exists():
        if not target.is_dir():
            raise ValueError("sandbox workspace must be a directory")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)

    git = shutil.which("git")
    if git:
        top = subprocess.run(
            [git, "-C", root, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if top.returncode == 0:
            dirty = subprocess.run(
                [git, "-C", root, "status", "--porcelain"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if dirty.stdout.strip():
                sys.stderr.write("Note: private workspace starts from HEAD; uncommitted host changes are not copied.\n")
            cloned = subprocess.run([git, "clone", "--local", "--no-hardlinks", root, str(target)], check=False)
            if cloned.returncode == 0:
                subprocess.run([git, "-C", str(target), "remote", "remove", "origin"], check=False)
                return target
            if target.exists():
                shutil.rmtree(target)
    shutil.copytree(root, target, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    return target


def agent_label() -> str:
    """컨테이너를 가를 이름 — 활성 에이전트 id, 이름 없는 홈이면 그 홈 디렉터리 이름.

    경로 조각이 되므로 규약 밖 문자는 하이픈으로 접고, 접고 나서 빈 문자열이면 default로
    떨어진다 (빈 조각은 `/agent/`가 되어 홈이 볼륨 뿌리와 같은 자리를 가리킨다)."""
    from . import profiles

    name = profiles.active()
    raw = os.path.basename(os.path.abspath(profiles.home()).rstrip("/\\")) if name == profiles.CUSTOM else name
    return _LABEL_UNSAFE.sub("-", raw).strip("-.") or profiles.DEFAULT


def agent_binding() -> tuple[str, str]:
    """(호스트 에이전트 홈, 컨테이너 안 에이전트 홈).

    `profiles.env_overlay()`가 "이 프로세스는 누구인가"의 정본이다 — 여기서 다시 조립하지
    않고 그 결과의 ASGARD_HOME만 컨테이너 안 경로로 옮긴다.

    ASGARD_PROFILE은 컨테이너에 안 넘긴다. 이름은 호스트의 `~/.asgard/profiles/` 아래에서만
    뜻이 있고 컨테이너 안에는 그 자리가 없어서, 남겨 두면 안에서 ASGARD_HOME을 지웠을 때
    자식이 없는 경로를 고른다. ASGARD_HOME이 서 있는 동안은 profiles.active()·home() 둘 다
    ASGARD_HOME을 먼저 보므로 어차피 안 읽힌다."""
    from . import profiles

    host = profiles.env_overlay().get("ASGARD_HOME") or profiles.home()
    return os.path.abspath(host), f"{CONTAINER_AGENT_ROOT}/{agent_label()}"


def run_container(root: str, *, shared: bool = False, name: str | None = None) -> int:
    """Run Asgard in a login-free Docker-compatible container."""
    engine = _container_engine()
    if not engine:
        sys.stderr.write(
            "A Docker-compatible engine is required.\n"
            "Install OrbStack/Docker on macOS, or Podman Desktop/Docker Desktop on Windows.\n"
            "No Docker Sandboxes account is required.\n"
        )
        return 2

    name = name or sandbox_name(root, shared)
    if not _NAME_RE.fullmatch(name):
        sys.stderr.write("sandbox name must contain only letters, numbers, '.', '_' or '-'\n")
        return 2
    try:
        workspace = Path(root) if shared else _private_workspace(root, name)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"Cannot create isolated workspace: {exc}\n")
        return 2

    image = f"asgard-runtime:{__version__}"
    inspected = subprocess.run(
        [engine, "image", "inspect", image],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if inspected.returncode:
        kit = str(files("asgard").joinpath("assets", "container_kit"))
        built = subprocess.run(
            [engine, "build", "--build-arg", f"ASGARD_VERSION={__version__}", "-t", image, kit], check=False
        )
        if built.returncode:
            return built.returncode

    container_name = f"{name}-{os.getpid()}"
    cmd = [
        engine,
        "run",
        "--rm",
        "--name",
        container_name,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
    ]
    if sys.stdin.isatty() and sys.stdout.isatty():
        cmd.append("-it")
    cmd.extend(("--mount", f"type=bind,src={workspace},dst=/workspace"))

    # 에이전트 홈 — 이 컨테이너가 "기억 없는 기본 에이전트"가 아니라 **지금 이 프로세스의
    # 에이전트**로 뜨게 하는 배선이다. named volume이 아니라 bind인 이유: 이 컨테이너는
    # 호스트에 이미 있는 그 에이전트 자신이라, 안에서 적은 1차 기억이 호스트의
    # `asgard agent show`에 그대로 보여야 한다. named volume은 도커가 쥔 별도 사본이라
    # 호스트 CLI가 그 기억을 못 본다. (compose 쪽은 반대 판단이다 — 그쪽 에이전트는 호스트에
    # 없는 컨테이너 전용이라 named volume이 맞다. 근거는 docker/README.md에 적었다.)
    agent_home, guest_agent_home = agent_binding()
    try:
        os.makedirs(agent_home, exist_ok=True)
    except OSError as exc:
        sys.stderr.write(
            f"Cannot prepare the agent home {agent_home}: {exc}\n"
            "Fix the path permissions, or pick another agent with `asgard agent use <name>`.\n"
        )
        return 2
    cmd.extend(("--mount", f"type=bind,src={agent_home},dst={guest_agent_home}"))
    cmd.extend(("--env", f"ASGARD_HOME={guest_agent_home}"))

    cmd.extend(("--env", "ASGARD_EXECUTION=local", "--env", "ASGARD_ISOLATION=oci-container"))
    for key in _API_KEY_ENVS:
        if key in os.environ:
            cmd.extend(("--env", key))

    # 기계 공용 자격증명은 기본으로 안 넘긴다 — 자격은 기계의 것이고 기억이 에이전트의
    # 것이라는 profiles 계약을 컨테이너 경계에서도 지킨다. 정상 경로는 위 _API_KEY_ENVS
    # 전달이고, 에이전트가 자기 키를 쓰면 그 파일은 에이전트 홈 안에 있어 위 마운트에 이미 포함된다
    # (providers.cred_path()가 `<홈>/credentials.json`을 먼저 본다). 남는 건 기계 공용 키뿐이라
    # 그것만 명시 opt-in으로, 읽기 전용으로 준다.
    if str(os.environ.get("ASGARD_CONTAINER_CREDENTIALS") or "").strip().lower() in _TRUTHY:
        from . import profiles

        shared_cred = os.path.join(profiles.root(), "credentials.json")
        if os.path.isfile(shared_cred):
            cmd.extend(("--mount", f"type=bind,src={shared_cred},dst={CONTAINER_CRED_PATH},readonly"))

    cmd.append(image)
    sys.stderr.write(f"Starting {Path(engine).name} container {container_name}.\n")
    sys.stderr.write(f"Workspace: {workspace}{' (host working tree)' if shared else ' (private copy)'}\n")
    # 이름은 위에서 정한 경로에서 되읽는다 — agent_label()을 다시 부르면 그 사이 활성
    # 에이전트가 바뀌었을 때 마운트한 자리와 다른 이름을 알린다.
    sys.stderr.write(f"Agent: {guest_agent_home.rsplit('/', 1)[-1]} — {agent_home} -> {guest_agent_home}\n")
    return subprocess.run(cmd, cwd=root, check=False).returncode


def run(root: str, *, shared: bool = False, name: str | None = None) -> int:
    """Create or reattach to the Asgard Docker Sandbox for ``root``."""
    sbx = shutil.which("sbx")
    if not sbx:
        sys.stderr.write(
            "Docker Sandboxes CLI (sbx) is required.\n"
            "macOS: brew trust docker/tap && brew install docker/tap/sbx\n"
            "Then run: sbx login\n"
        )
        return 2

    if not shared:
        git_bin = shutil.which("git")
        if not git_bin:
            sys.stderr.write("Private-clone isolation requires Git; use --execution sandbox-shared.\n")
            return 2
        git = subprocess.run(
            [git_bin, "-C", root, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        if git.returncode:
            sys.stderr.write("Private-clone isolation requires a Git repository; use --execution sandbox-shared.\n")
            return 2
        dirty = subprocess.run(
            [git_bin, "-C", root, "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        if dirty.stdout.strip():
            sys.stderr.write("Note: private clone starts from HEAD; uncommitted host changes are not copied.\n")

    name = name or sandbox_name(root, shared)
    listed = subprocess.run(
        [sbx, "ls", "-q"], capture_output=True, text=True, check=False, encoding="utf-8", errors="replace"
    )
    if listed.returncode == 0 and name in listed.stdout.splitlines():
        return subprocess.run([sbx, "run", "--name", name], cwd=root, check=False).returncode

    kit = str(files("asgard").joinpath("assets", "sandbox_kit"))
    cmd = [sbx, "run", "--name", name, "--kit", kit]
    if not shared:
        cmd.append("--clone")
    cmd.extend(("asgard", root))
    sys.stderr.write(f"Starting Docker Sandbox {name} ({'shared workspace' if shared else 'private clone'}).\n")
    sys.stderr.write("Provider secrets stay host-side via sbx; configure the provider inside the sandbox.\n")
    return subprocess.run(cmd, cwd=root, check=False).returncode
