"""update — self-update via uv. asgard ships as a `uv tool`, so updating is
re-installing the target version. Requires uv on PATH (the installer bootstraps it).

release wheel을 직접 내려받아(진행률 바) 로컬 파일로 `uv tool install` 한다 — pure-python이라
git/컴파일러 불필요. ASGARD_INSTALL_SPEC 오버라이드(dev/CI)는 다운로드 없이 스펙 그대로 설치.
REPL의 /update도 이 함수를 쓴다 (restart_hint — 새 버전은 재시작 후 적용)."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request

from .. import __version__, errors, ui
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
            ["uv", "tool", "install", "--force", "--python", "3.14", spec],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    return r.returncode


def _sync_projects() -> int:
    """엔진 설치 성공 후 세팅된 프로젝트 코어 동기화 — 반드시 **새 바이너리**로 실행한다
    (현 프로세스의 템플릿은 아직 구버전).

    Returns:
        자식 프로세스의 반환 코드. PATH 에 새 바이너리가 없으면 0 — 그것만은 안내 후 성공으로
        둔다(설치 자체는 됐고 동기화는 사람이 나중에 할 수 있다). 반면 `asgard sync` 가 실제로
        실패한 것은 0 으로 접지 않는다: 설치 스크립트와 CI 가 프로젝트 코어가 안 갱신됐는데
        업데이트 전체를 성공으로 기록하게 된다.
    """
    exe = shutil.which("asgard")
    if not exe:
        ui.warn("asgard not on PATH — run `asgard sync` to refresh set-up projects")
        return 0
    return subprocess.run([exe, "sync"]).returncode


def _emit(payload: dict, code: int, json_out: bool) -> int:
    """`--json`이면 결과 한 덩어리를 stdout에, 아니면 아무것도 — 사람 화면은 이미 지나갔다.

    `ui.ok`·`warn`·`fail`·`done`은 `--quiet`을 안 본다(성공·경고는 조용해지면 안 되는 표면이라
    의도된 것이다). 그래서 이 명령의 `--json` 분기는 quiet만으로는 안 되고 그 넷을 따로 막는다."""
    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


def _spec_for(spec: str, version: str | None) -> str:
    """override 실행이 실제로 설치할 스펙 — git+ 스펙일 때만 핀을 붙인다.

    스펙을 인자로 받는다: `_SPEC_OVERRIDE`는 `str | None`이라, 부르는 쪽의 `if`로만 좁혀진
    값을 여기서 다시 읽으면 그 좁힘이 함수 경계에서 풀린다."""
    if version and spec.startswith("git+"):
        return f"{spec}@v{version}"
    return spec


def _preview(base: dict, version: str | None, sync: bool, json_out: bool) -> int:
    """--dry-run — 네트워크를 안 탄다. 최신 버전을 조회하지 않고 계획만 말한다."""
    ui.steps(1)
    if _SPEC_OVERRIDE:
        shown = _spec_for(_SPEC_OVERRIDE, version)
    else:
        shown = f"asgard v{version} (release wheel)" if version else "asgard (latest release wheel)"
    ui.phase("preview")
    ui.step(f"would install {ui.dim(shown)} via uv tool")
    if sync:
        ui.step(f"would sync set-up projects {ui.dim('(asgard sync — --no-sync to skip)')}")
    return _emit({**base, "would_install": shown, "updated": False}, 0, json_out)


def _install_override(base: dict, spec: str, sync: bool, json_out: bool) -> int:
    """dev/CI 경로 — uv가 스펙을 직접 해석하므로 릴리스 조회도 휠 다운로드도 없다."""
    ui.steps(1)
    ui.phase("install via uv tool")
    ui.step(ui.dim(spec))
    if _uv_install(spec, "installing asgard (override)…"):
        if not json_out:
            ui.fail("update failed (uv tool install)")
        return _emit({**base, "spec": spec, "updated": False}, 1, json_out)
    if not json_out:
        ui.done("updated (override spec)")
    ensure_installed()  # 셸 completion 기본 설치·재생성 — 새 바이너리로 (베스트에포트)
    code = _sync_projects() if sync else 0
    return _emit({**base, "spec": spec, "updated": True, "synced": code == 0}, code, json_out)


def _install_release(base: dict, target: str, sync: bool, restart_hint: bool, json_out: bool) -> int:
    """릴리스 휠을 받아 uv tool로 얹는다 — 임시 폴더는 어느 갈래로 나가든 지운다."""
    ui.steps(2)
    ui.phase("download release wheel")
    tmpd = tempfile.mkdtemp(prefix="asgard-update-")
    wheel = os.path.join(tmpd, f"asgard-{target}-py3-none-any.whl")
    try:
        _download(_wheel_url(target), wheel)
    except Exception as e:
        shutil.rmtree(tmpd, ignore_errors=True)
        if not json_out:
            ui.fail(f"download failed: {e}")
            return 1
        raise errors.UpstreamError(f"download failed: {e}", detail={"target": target}) from e
    if not json_out:
        ui.ok(os.path.basename(wheel))

    ui.phase("install via uv tool")
    rc = _uv_install(wheel, f"installing asgard v{target}…")
    shutil.rmtree(tmpd, ignore_errors=True)
    if rc:
        if not json_out:
            ui.fail("update failed (uv tool install)")
        return _emit({**base, "target": target, "updated": False}, 1, json_out)
    if not json_out:
        ui.done(f"v{__version__} → v{target}")
    ensure_installed()  # 셸 completion 기본 설치·재생성 — 새 바이너리로 (베스트에포트)
    synced = _sync_projects() if sync else 0
    if restart_hint and not json_out:  # REPL 안에서 실행 — 프로세스는 아직 구버전
        from ..i18n import t

        ui.warn(t("update_restart"))
    return _emit({**base, "target": target, "updated": True, "synced": synced == 0}, synced, json_out)


def run_update(
    rest: list[str],
    dry_run: bool = False,
    restart_hint: bool = False,
    sync: bool = True,
    json_out: bool = False,
) -> int:
    pin = rest[0] if rest else None
    version = pin[1:] if pin and pin.startswith("v") else pin
    ui.set_quiet(ui._QUIET or json_out)
    base = {"current": __version__, "pin": version or "", "dry_run": dry_run, "sync": sync}

    # 총 단계 수는 check 결과에 달림(최신이면 0, 업데이트면 2) — head는 분모 없이 열고 늦게 확정.
    ui.head("update · starting…")
    if dry_run:  # keep dry-run network-free: describe the plan without resolving latest.
        return _preview(base, version, sync, json_out)
    if not on_path("uv"):
        if not json_out:
            ui.fail("uv not found — install it first: https://astral.sh/uv")
            return 1
        raise errors.PreflightFailed("uv not found", remedy="install it first: https://astral.sh/uv", exit_code=1)

    if _SPEC_OVERRIDE:  # dev/CI — uv가 스펙을 직접 해석 (다운로드·버전 비교 없음)
        return _install_override(base, _spec_for(_SPEC_OVERRIDE, version), sync, json_out)

    # check — 핀이면 즉시, 아니면 최신 릴리스 조회 (스피너)
    if version:
        target = version
    else:
        with ui.spin("checking for updates…"):
            target = _latest_version()
    if not target:
        if not json_out:
            ui.fail("could not resolve the latest version (network?). Pin one: asgard update vX.Y.Z")
            return 1
        raise errors.UpstreamError(
            "could not resolve the latest version",
            remedy="네트워크를 확인하거나 버전을 고정하세요: asgard update vX.Y.Z",
        )
    if target == __version__:
        if not json_out:
            ui.ok(f"already up to date — v{__version__} is the latest release")
        code = 0
        if sync:  # 엔진은 최신이어도 프로젝트 코어가 뒤처졌을 수 있다 — 현 프로세스 템플릿이 곧 최신
            from .sync import run_sync

            code = run_sync(json_out=json_out) or 0
        return _emit({**base, "target": target, "updated": False, "up_to_date": True}, code, json_out)
    ui.step(f"update available: v{__version__} → v{target}")
    return _install_release(base, target, sync, restart_hint, json_out)
