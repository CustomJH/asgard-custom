"""uninstall — remove asgard (it's a uv tool). `uv tool uninstall asgard` removes the
managed env + the `asgard` shim. Preview unless --yes.

여기서 지우는 것은 설치물뿐이다. `~/.asgard` 아래의 memory/·credentials.json·profiles/ 는
사용자 데이터라 건드리지 않는다 — 승인 없이 개인 기억을 지울 수 있는 경로를 두지 않는다.
그래서 CLI 도움말과 아래 preview 는 둘 다 "데이터는 남는다"를 말해야 한다."""

import json
import os
import subprocess
import sys
from pathlib import Path

from .. import ui
from ..platform import on_path

# uninstall 이 지우지 않는 경로. 화면에 경로를 그대로 찍어야 사용자가 기억이 지워졌는지
# 따로 확인하러 가지 않는다.
DATA_HOME = Path.home() / ".asgard"


def _installed() -> bool:
    # FORCE_COLOR 류가 켜진 셸에선 uv가 파이프에도 ANSI 코드를 넣어 첫 토큰이
    # "\x1b[1masgard"가 된다 — 설치돼 있는데 미설치로 오판해 uninstall이 무동작 (macOS 실측).
    env: dict[str, str] = {**os.environ, "NO_COLOR": "1"}
    env.pop("FORCE_COLOR", None)
    try:
        out = subprocess.run(
            ["uv", "tool", "list"], capture_output=True, text=True, env=env, encoding="utf-8", errors="replace"
        ).stdout
    except OSError:
        return False
    return any(line.split(" ", 1)[0] == "asgard" for line in out.splitlines())


def _emit(payload: dict, code: int) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


def run_uninstall(yes: bool = False, dry_run: bool = False, json_out: bool = False) -> int:
    """`--json`은 무엇이 지워졌고 **무엇이 남았는지**를 값으로 낸다.

    남은 것을 같이 내는 것이 요점이다: 이 명령은 `~/.asgard`를 건드리지 않는데, 그 사실이
    사람 화면에만 있으면 스크립트로 부른 쪽은 개인 기억이 지워졌는지 따로 확인하러 간다."""
    ui.set_quiet(ui._QUIET or json_out)
    ui.head("uninstall", steps=1)
    kept = str(DATA_HOME)
    if not on_path("uv") or not _installed():
        if json_out:
            return _emit({"installed": False, "removed": False, "kept": kept}, 0)
        ui.warn("asgard not installed as a uv tool here.")
        return 0

    if dry_run or not yes:
        if json_out:
            return _emit({"installed": True, "removed": False, "dry_run": True, "kept": kept}, 0)
        ui.phase("preview")
        ui.step("would run: uv tool uninstall asgard")
        ui.step(f"kept: {DATA_HOME} (memory, credentials, profiles)")
        sys.stdout.write("\n  " + ui.dim("run 'asgard uninstall --yes' to remove.") + "\n")
        return 0

    ui.phase("remove uv tool")
    with ui.spin("uninstalling asgard…"):
        result = subprocess.run(
            ["uv", "tool", "uninstall", "asgard"], capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    removed = result.returncode == 0
    if json_out:
        return _emit({"installed": True, "removed": removed, "kept": kept}, 0 if removed else 1)
    if removed:
        ui.done("asgard removed")
        sys.stdout.write("  " + ui.dim(f"{DATA_HOME} kept — remove it by hand if you want it gone.") + "\n")
        return 0
    ui.warn("uninstall incomplete.")
    return 1
