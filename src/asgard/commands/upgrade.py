"""upgrade — self-update via uv (CUS-108 Path B). asgard ships as a `uv tool`, so upgrading is
re-installing the latest (or a pinned) version. Requires uv on PATH (the installer bootstraps it).

Installs the release *wheel* by default — pure-python, so no git or compiler is needed on the host
(a git+URL spec would require git, which minimal systems lack). ASGARD_INSTALL_SPEC overrides."""

import os
import re
import subprocess
import urllib.request

from .. import ui
from ..platform import on_path

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


def _install_spec(version: str | None) -> str | None:
    """uv-installable source for asgard. Override wins; else a release wheel by version. Returns
    None when the version can't be resolved (offline and unpinned)."""
    if _SPEC_OVERRIDE:
        return f"{_SPEC_OVERRIDE}@v{version}" if version and _SPEC_OVERRIDE.startswith("git+") else _SPEC_OVERRIDE
    v = version or _latest_version()
    if not v:
        return None
    return f"https://github.com/{_REPO}/releases/download/v{v}/asgard-{v}-py3-none-any.whl"


def run_upgrade(rest: list[str], dry_run: bool = False) -> int:
    pin = rest[0] if rest else None
    version = pin[1:] if pin and pin.startswith("v") else pin

    ui.head("upgrade", steps=1)
    if dry_run:  # keep dry-run network-free: describe the plan without resolving latest.
        if _SPEC_OVERRIDE:
            shown = f"{_SPEC_OVERRIDE}@v{version}" if version and _SPEC_OVERRIDE.startswith("git+") else _SPEC_OVERRIDE
        else:
            shown = f"asgard v{version} (release wheel)" if version else "asgard (latest release wheel)"
        ui.phase("preview")
        ui.step(f"would install {ui.dim(shown)} via uv tool")
        return 0
    if not on_path("uv"):
        ui.fail("uv not found — install it first: https://astral.sh/uv")
        return 1
    spec = _install_spec(version)
    if spec is None:
        ui.fail("could not resolve the latest version (network?). Pin one: asgard upgrade vX.Y.Z")
        return 1
    ui.phase("install via uv tool")
    with ui.spin(f"installing {ui.dim(spec)}…"):
        result = subprocess.run(["uv", "tool", "install", "--force", "--python", "3.14", spec],
                                capture_output=True, text=True)
    if result.returncode != 0:
        ui.fail(f"upgrade failed (uv exited {result.returncode})")
        return 1
    ui.done(f"upgraded → asgard {('v' + version) if version else '(latest)'}")
    return 0
