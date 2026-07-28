#!/usr/bin/env python3
"""cad — CAD 레인 도구 하나의 입구.

    python cad.py step     model.py
    python cad.py inspect  refs model.step --facts --planes --positioning
    python cad.py snapshot --job job.json
    python cad.py dxf      drawing.py
    python cad.py gcode    discover
    python cad.py parts    "M3 socket head 12" --download
    python cad.py urdf     ...        # srdf · sdf 도 같다

왜 런처가 있는가: 각 도구가 요구하는 격리 의존성이 서로 다르고(build123d·cadpy·playwright·
ezdxf), 그 조합을 사람이 매번 손으로 적으면 언젠가 틀린다. 여기서 한 번 정해두고,
문서는 도구 이름만 부른다. Windows·POSIX 에서 같은 줄이 돈다 — 셸 스크립트를 쓰지 않는
이유가 그것이다.

이 런처는 uv 를 요구한다. 프로젝트 환경을 건드리지 않고(`--no-project`) 매번 격리
실행하므로, 저장소의 파이썬 버전(3.14)과 CAD 커널이 요구하는 버전(3.12)이 달라도 된다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# 한국어 Windows(cp949)·서구권 Windows(cp1252) 콘솔은 이 파일의 엠대시 한 글자를 싣지 못한다.
# stdout 의 기본 오류 처리기는 strict 라, `cad.py --help` 가 UnicodeEncodeError 로 죽는다
# (실측: `'cp949' codec can't encode character '—'`). 저장소가 v0.6.31·32 에서 같은
# 결함을 두 번 고쳤고, 스킬 플러그인 스크립트는 그 청소에서 빠져 있었다. UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
    except Exception:
        pass

# OCP(OpenCASCADE 바인딩)가 휠을 내는 버전에 맞춘다. 저장소 본체와 무관하게 고정한다.
CAD_PYTHON = "3.12"

ENGINE = Path(__file__).resolve().parent.parent
VENDOR = ENGINE / "vendor" / "text-to-cad"
CADPY = VENDOR / "packages" / "cadpy"
CADPY_META = VENDOR / "packages" / "cadpy_metadata"

# 도구 이름 -> (실행할 스크립트, 추가로 설치할 것)
TOOLS: dict[str, tuple[Path, tuple[str, ...]]] = {
    "step": (VENDOR / "skills" / "cad" / "scripts" / "step", ("build123d", str(CADPY))),
    "inspect": (VENDOR / "skills" / "cad" / "scripts" / "inspect", ("build123d", str(CADPY))),
    "snapshot": (VENDOR / "skills" / "cad" / "scripts" / "snapshot", ("build123d", "playwright", str(CADPY))),
    "dxf": (VENDOR / "skills" / "dxf" / "scripts" / "dxf", ("build123d", "ezdxf", str(CADPY))),
    "gcode": (VENDOR / "skills" / "gcode" / "scripts" / "gcode_tool.py", ()),
    "parts": (VENDOR / "skills" / "step-parts" / "scripts" / "download_step_part.py", ()),
    "urdf": (VENDOR / "skills" / "urdf" / "scripts" / "urdf", (str(CADPY_META),)),
    "srdf": (VENDOR / "skills" / "srdf" / "scripts" / "srdf", (str(CADPY_META),)),
    "sdf": (VENDOR / "skills" / "sdf" / "scripts" / "sdf", (str(CADPY_META),)),
}


def usage(stream=sys.stderr) -> None:
    stream.write(f"{__doc__}\n사용 가능한 도구: {', '.join(TOOLS)}\n")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        usage(sys.stdout if argv else sys.stderr)
        return 0 if argv else 2

    name = argv[0]
    if name not in TOOLS:
        sys.stderr.write(f"모르는 도구다: {name}\n사용 가능한 도구: {', '.join(TOOLS)}\n")
        return 2

    script, extras = TOOLS[name]
    if not script.exists():
        sys.stderr.write(
            f"벤더링된 런타임을 찾지 못했다: {script}\n"
            "engine/vendor/text-to-cad/ 가 통째로 빠졌다. UPSTREAM.md 의 재동기화 절차를 보라.\n"
        )
        return 3

    uv = shutil.which("uv")
    if uv is None:
        sys.stderr.write(
            "uv 를 찾지 못했다. CAD 레인은 격리 실행을 전제로 한다.\n"
            "  설치: curl -LsSf https://astral.sh/uv/install.sh | sh\n"
        )
        return 3

    command = [uv, "run", "--no-project", "--python", CAD_PYTHON]
    for extra in extras:
        command += ["--with", extra]
    command += ["python", str(script), *argv[1:]]

    # 첫 실행은 커널 휠을 받느라 오래 걸린다. 침묵하지 않고 그 사실을 먼저 말한다.
    if os.environ.get("ASGARD_CAD_QUIET") != "1":
        sys.stderr.write(f"[cad] {name} — 격리 실행 (python {CAD_PYTHON}{''.join(f', +{e.split('/')[-1]}' for e in extras)})\n")

    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
