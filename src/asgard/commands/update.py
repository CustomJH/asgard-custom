"""update — self-update via uv (CUS-108 Path B). asgard ships as a `uv tool`, so updating is
re-installing the target version. Requires uv on PATH (the installer bootstraps it).

release wheel 을 직접 내려받아(진행률 바) 로컬 파일로 `uv tool install` 한다 — pure-python 이라
git/컴파일러 불요. ASGARD_INSTALL_SPEC 오버라이드(dev/CI)는 다운로드 없이 스펙 그대로 설치.
REPL 의 /update 도 이 함수를 쓴다 (restart_hint — 새 버전은 재시작 후 적용)."""

import os
import re
import shutil
import subprocess
import tempfile
import urllib.request

from .. import __version__, ui
from ..platform import on_path
from .completions import ensure_installed

_REPO = "CustomJH/asgard-custom"
_SPEC_OVERRIDE = os.environ.get("ASGARD_INSTALL_SPEC")  # dev/CI escape hatch (git+…, local path)


def _latest_version() -> str | None:
    """Newest published release tag via the /releases/latest redirect (no git, no API token)."""
    try:
        req = urllib.request.Request(f"https://github.com/{_REPO}/releases/latest", method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as resp:
            final = resp.geturl()  # → …/releases/tag/vX.Y.Z
    except Exception:
        return None
    m = re.search(r"/tag/v([0-9][0-9.]*)", final)
    return m.group(1) if m else None


def _wheel_url(v: str) -> str:
    return f"https://github.com/{_REPO}/releases/download/v{v}/asgard-{v}-py3-none-any.whl"


def _download(url: str, dest: str) -> None:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        with ui.bar("asgard wheel", total) as b, open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                b.advance(len(chunk))


def _uv_install(spec: str, label: str) -> int:
    with ui.spin(label):
        r = subprocess.run(
            ["uv", "tool", "install", "--force", "--python", "3.14", spec], capture_output=True, text=True
        )
    return r.returncode


def _sync_projects() -> None:
    """엔진 설치 성공 후 세팅된 프로젝트 코어 동기화 — 반드시 **새 바이너리**로 실행한다
    (현 프로세스의 템플릿은 아직 구버전). PATH 에 없으면 안내만 (베스트에포트)."""
    exe = shutil.which("asgard")
    if not exe:
        ui.warn("asgard not on PATH — run `asgard sync` to refresh set-up projects")
        return
    subprocess.run([exe, "sync"])


def run_update(rest: list[str], dry_run: bool = False, restart_hint: bool = False, sync: bool = True) -> int:
    pin = rest[0] if rest else None
    version = pin[1:] if pin and pin.startswith("v") else pin

    # 총 단계 수는 check 결과에 달림(최신이면 0, 업데이트면 2) — head 는 분모 없이 열고 늦게 확정.
    ui.head("update · starting…")
    if dry_run:  # keep dry-run network-free: describe the plan without resolving latest.
        ui.steps(1)
        if _SPEC_OVERRIDE:
            shown = f"{_SPEC_OVERRIDE}@v{version}" if version and _SPEC_OVERRIDE.startswith("git+") else _SPEC_OVERRIDE
        else:
            shown = f"asgard v{version} (release wheel)" if version else "asgard (latest release wheel)"
        ui.phase("preview")
        ui.step(f"would install {ui.dim(shown)} via uv tool")
        if sync:
            ui.step(f"would sync set-up projects {ui.dim('(asgard sync — --no-sync to skip)')}")
        return 0
    if not on_path("uv"):
        ui.fail("uv not found — install it first: https://astral.sh/uv")
        return 1

    if _SPEC_OVERRIDE:  # dev/CI — uv 가 스펙을 직접 해석 (다운로드·버전 비교 없음)
        spec = f"{_SPEC_OVERRIDE}@v{version}" if version and _SPEC_OVERRIDE.startswith("git+") else _SPEC_OVERRIDE
        ui.steps(1)
        ui.phase("install via uv tool")
        ui.step(ui.dim(spec))
        if _uv_install(spec, "installing asgard (override)…"):
            ui.fail("update failed (uv tool install)")
            return 1
        ui.done("updated (override spec)")
        ensure_installed()  # 셸 completion 기본 설치·재생성 — 새 바이너리로 (베스트에포트)
        if sync:
            _sync_projects()
        return 0

    # check — 핀이면 즉시, 아니면 최신 릴리스 조회 (스피너)
    if version:
        target = version
    else:
        with ui.spin("checking for updates…"):
            target = _latest_version()
    if not target:
        ui.fail("could not resolve the latest version (network?). Pin one: asgard update vX.Y.Z")
        return 1
    if target == __version__:
        ui.ok(f"already up to date — v{__version__} is the latest release")
        if sync:  # 엔진은 최신이어도 프로젝트 코어가 뒤처졌을 수 있다 — 현 프로세스 템플릿이 곧 최신
            from .sync import run_sync

            run_sync()
        return 0
    ui.step(f"update available: v{__version__} → v{target}")

    ui.steps(2)
    ui.phase("download release wheel")
    tmpd = tempfile.mkdtemp(prefix="asgard-update-")
    wheel = os.path.join(tmpd, f"asgard-{target}-py3-none-any.whl")
    try:
        _download(_wheel_url(target), wheel)
    except Exception as e:
        shutil.rmtree(tmpd, ignore_errors=True)
        ui.fail(f"download failed: {e}")
        return 1
    ui.ok(os.path.basename(wheel))

    ui.phase("install via uv tool")
    rc = _uv_install(wheel, f"installing asgard v{target}…")
    shutil.rmtree(tmpd, ignore_errors=True)
    if rc:
        ui.fail("update failed (uv tool install)")
        return 1
    ui.done(f"v{__version__} → v{target}")
    ensure_installed()  # 셸 completion 기본 설치·재생성 — 새 바이너리로 (베스트에포트)
    if sync:  # 세팅된 프로젝트 코어 갱신 — 새 바이너리 서브프로세스 (현 프로세스 템플릿은 구버전)
        _sync_projects()
    if restart_hint:  # REPL 안에서 실행 — 프로세스는 아직 구버전
        from ..i18n import t

        ui.warn(t("update_restart"))
    return 0
