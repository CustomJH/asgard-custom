"""uninstall — remove what install.sh created: the PATH symlink + ~/.asgard, and strip the guarded
PATH block from shell rc files. Honors ASGARD_HOME / BIN_DIR overrides. Preview unless --yes."""

import os
import re
import shutil
import sys
from pathlib import Path

from .. import ui

# Must stay byte-identical to the block install.sh writes.
ASGARD_BLOCK = re.compile(r"\n?# >>> asgard >>>[\s\S]*?# <<< asgard <<<\n?")


def _rc_files_with_asgard() -> list[str]:
    home = Path.home()
    out: list[str] = []
    for f in (".zshrc", ".bashrc", ".bash_profile", ".zprofile", ".profile"):
        p = home / f
        try:
            if ">>> asgard >>>" in p.read_text():
                out.append(str(p))
        except OSError:
            pass
    return out


def run_uninstall(yes: bool = False, dry_run: bool = False) -> int:
    home = os.environ.get("ASGARD_HOME") or str(Path.home() / ".asgard")
    bindir = os.environ.get("BIN_DIR") or str(Path.home() / ".local" / "bin")
    link = str(Path(bindir) / "asgard")
    files = [t for t in (link, home) if os.path.lexists(t)]
    rcs = _rc_files_with_asgard()

    if not files and not rcs:
        ui.head("uninstall")
        ui.warn("nothing to remove (not installed here).")
        return 0

    if dry_run or not yes:
        ui.head("uninstall")
        for t in files:
            ui.step(f"would remove {ui.dim(t)}")
        for t in rcs:
            ui.step(f"would clean {ui.dim(t)}  {ui.dim('(asgard PATH block)')}")
        hint = "run 'asgard uninstall --yes' to remove."
        sys.stdout.write(f"\n  {ui.dim(hint)}\n")
        return 0

    ui.head("uninstall")
    failed = 0
    for t in files:
        try:
            if os.path.isdir(t) and not os.path.islink(t):
                shutil.rmtree(t)
            else:
                os.unlink(t)
            ui.ok(f"removed {ui.dim(t)}")
        except OSError as e:
            failed += 1
            ui.fail(f"{t}: {e}")
    for rc in rcs:
        try:
            Path(rc).write_text(ASGARD_BLOCK.sub("\n", Path(rc).read_text()))
            ui.ok(f"cleaned {ui.dim(rc)}  {ui.dim('(PATH block)')}")
        except OSError as e:
            failed += 1
            ui.fail(f"{rc}: {e}")
    sys.stdout.write(
        f"\n  {ui.paint('33', '!')} uninstall incomplete.\n" if failed else f"\n  {ui.paint('32', '✔')} asgard removed.\n"
    )
    return 1 if failed else 0
