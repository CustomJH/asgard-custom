#!/usr/bin/env python3
"""cad — CAD 레인 도구 하나의 입구.

    python cad.py step     model.py [--out build] [--formats step,stl,glb]
    python cad.py inspect  refs model.step --facts --planes --positioning
    python cad.py inspect  measure model.step --from '#f13' --to '#f14' --axis z
    python cad.py inspect  align   model.step --moving '#f1' --target '#f9' --mode flush --axis z
    python cad.py inspect  frame   model.step '#f13'
    python cad.py inspect  diff    before.step after.step
    python cad.py dxf      drawing.py [-o out/drawing.dxf]
    python cad.py dxf      check    drawing.dxf
    python cad.py gcode    discover | inspect | slice | validate
    python cad.py parts    search "M3 socket head 12" | download <id> -o parts/m3.step
    python cad.py urdf     robot.py        # srdf · sdf 도 같다

## 두 갈래로 나뉘는 이유

도구마다 요구가 다르다. **형상을 만드는 일**에는 B-Rep 커널이 들고, 커널은 무겁다(첫 실행에
수백 MB 휠). **이미 만들어진 것에서 사실을 읽는 일**에는 아무것도 안 든다 — STEP 도 DXF 도
G-code 도 URDF 도 전부 텍스트고, 위상 산출물은 우리가 쓴 파일이다.

그래서 라우터가 가른다:

    커널 필요   step · dxf(생성)               → uv 격리 실행 (python 3.12 고정)
    즉시 실행   inspect · gcode · robot ·      → 이 프로세스에서 바로
                parts · dxf check

즉시 실행 쪽이 이 런처의 핵심 개선이다. 검증이 싸지면 자주 하고, 자주 해야 실제로 잡힌다.
이전 판은 URDF 문법 검사 한 번에도 격리 환경을 세웠다.

## 커널 레인의 격리

`uv run --no-project` 로 매번 새로 세운다. 저장소의 파이썬(3.14)과 커널이 휠을 내는 버전(3.12)이
달라도 되고, 프로젝트 환경을 건드리지 않는다. 재진입 표시는 환경변수 하나다 — 이 파일이 스스로를
격리 안에서 다시 부른다.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cadlib.report import Report, utf8_console  # noqa: E402

utf8_console()

# OCP(OpenCASCADE 바인딩)가 휠을 내는 버전에 맞춘다. 저장소 본체와 무관하게 고정한다.
CAD_PYTHON = "3.12"
REENTRY = "ASGARD_CAD_IN_KERNEL"

# 커널·외부 라이브러리가 필요한 도구와, 격리 환경에 더 설치할 것.
ISOLATED: dict[str, tuple[str, ...]] = {
    "step": ("build123d",),
    "dxf": ("ezdxf",),
}
INSTANT = ("inspect", "gcode", "parts", "urdf", "srdf", "sdf")
TOOLS = (*ISOLATED, *INSTANT)


def _isolate(tool: str, argv: list[str]) -> int:
    """이 파일을 uv 격리 안에서 다시 부른다."""
    uv = shutil.which("uv")
    if uv is None:
        sys.stderr.write(
            f"uv 를 찾지 못했다. `{tool}` 은 격리 실행을 전제로 한다.\n"
            "  설치: curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            "  (검증 동사 inspect·gcode·urdf 는 uv 없이 바로 돈다.)\n"
        )
        return 3

    command = [uv, "run", "--no-project", "--python", CAD_PYTHON]
    for extra in ISOLATED[tool]:
        command += ["--with", extra]
    if tool == "step" and "3mf" in " ".join(argv):
        command += ["--with", "lib3mf"]
    command += ["python", str(Path(__file__).resolve()), tool, *argv]

    if os.environ.get("ASGARD_CAD_QUIET") != "1":
        extras = "".join(f", +{name}" for name in ISOLATED[tool])
        sys.stderr.write(f"[cad] {tool} — 격리 실행 (python {CAD_PYTHON}{extras}). 첫 실행은 휠을 받느라 오래 걸린다.\n")

    return subprocess.run(command, check=False, env={**os.environ, REENTRY: "1"}).returncode


# ─────────────────────────────────────────────────────────────────────────────
# 도구별 인자
# ─────────────────────────────────────────────────────────────────────────────


def _step(argv: list[str]) -> Report:
    from cadlib import steplane  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="cad.py step", description="소스에서 STEP·위상 산출물·진단을 낸다")
    parser.add_argument("script", help="`gen_step()` 을 정의한 파이썬 소스")
    parser.add_argument("--out", default="build", help="산출물 디렉터리 (기본 build)")
    parser.add_argument("--formats", default="step,stl", help="쉼표 구분 (step,stl,glb,3mf) — step 은 항상 포함된다")
    parser.add_argument("--deflection", type=float, default=0.05, help="메시 선형 편차 mm (기본 0.05)")
    parser.add_argument("--angular", type=float, default=0.3, help="메시 각도 편차 rad (기본 0.3)")
    parser.add_argument("--clearance", type=float, default=0.2, help="조립 간극 목표 mm (기본 0.2)")
    parser.add_argument("--no-detail", action="store_true", help="면·에지 셀렉터 표를 만들지 않는다(대형 모델)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    return steplane.run(
        args.script,
        out=args.out,
        formats=[item.strip().lower() for item in args.formats.split(",") if item.strip()],
        deflection=args.deflection,
        angular=args.angular,
        clearance=args.clearance,
        detail=not args.no_detail,
    )


def _inspect(argv: list[str]) -> Report:
    from cadlib import verbs  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="cad.py inspect", description="셀렉터 참조와 검증 동사 (커널 불필요)")
    sub = parser.add_subparsers(dest="verb", required=True)

    refs = sub.add_parser("refs", help="이 형상에 무엇이 있는가")
    refs.add_argument("target")
    refs.add_argument("selectors", nargs="*")
    refs.add_argument("--facts", action="store_true")
    refs.add_argument("--planes", action="store_true")
    refs.add_argument("--positioning", action="store_true")
    refs.add_argument("--detail", action="store_true")
    refs.add_argument("--topology", action="store_true", help="면·에지 서수 목록 (대형 모델에서 길다)")

    measure = sub.add_parser("measure", help="두 참조 사이 거리")
    measure.add_argument("target")
    measure.add_argument("--from", dest="source", required=True)
    measure.add_argument("--to", dest="to", required=True)
    measure.add_argument("--axis", choices=("x", "y", "z"))

    align = sub.add_parser("align", help="두 참조의 정렬 델타 (읽기 전용)")
    align.add_argument("target")
    align.add_argument("--moving", required=True)
    align.add_argument("--target", dest="reference", required=True)
    align.add_argument("--mode", choices=("flush", "center"), default="flush")
    align.add_argument("--axis", choices=("x", "y", "z"), default="z")

    frame = sub.add_parser("frame", help="이 참조의 월드 좌표계")
    frame.add_argument("target")
    frame.add_argument("selector")

    diff = sub.add_parser("diff", help="고치기 전후 대조")
    diff.add_argument("before")
    diff.add_argument("after")
    diff.add_argument("--planes", action="store_true")

    for item in (refs, measure, align, frame, diff):
        item.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.verb == "refs":
        return verbs.refs(
            args.target,
            selectors=args.selectors,
            facts=args.facts,
            planes=args.planes,
            positioning=args.positioning,
            detail=args.detail,
            show_topology=args.topology,
        )
    if args.verb == "measure":
        return verbs.measure(args.target, source=args.source, target=args.to, axis=args.axis)
    if args.verb == "align":
        return verbs.align(args.target, moving=args.moving, target=args.reference, mode=args.mode, axis=args.axis)
    if args.verb == "frame":
        return verbs.frame(args.target, args.selector)
    return verbs.diff(args.before, args.after, planes=args.planes)


def _dxf(argv: list[str]) -> Report:
    from cadlib import drawing  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="cad.py dxf", description="DXF 생성과 검사")
    parser.add_argument("script", help="`gen_dxf()` 를 정의한 소스, 또는 `check` 다음에 .dxf 경로")
    parser.add_argument("path", nargs="?", help="`check` 일 때 검사할 .dxf")
    parser.add_argument("-o", "--out", help="출력 경로")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.script == "check":
        if not args.path:
            parser.error("check 는 검사할 .dxf 경로가 필요하다")
        return drawing.inspect(args.path)
    return drawing.generate(args.script, args.out)


def _gcode(argv: list[str]) -> Report:
    from cadlib import slicing  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="cad.py gcode", description="슬라이서 발견·슬라이싱·정적 검증 (커널 불필요)")
    sub = parser.add_subparsers(dest="verb", required=True)

    discover = sub.add_parser("discover", help="이 기계의 슬라이서 백엔드")
    discover.add_argument("--search-path", help=argparse.SUPPRESS)

    inspect = sub.add_parser("inspect", help="슬라이스 가능한 입력인가")
    inspect.add_argument("--input", required=True)

    slice_parser = sub.add_parser("slice", help="슬라이서 명령을 만들거나 실행한다")
    slice_parser.add_argument("--input", required=True)
    slice_parser.add_argument("--output", required=True)
    slice_parser.add_argument("--profile", required=True)
    slice_parser.add_argument("--backend", default="auto")
    slice_parser.add_argument("--dry-run", action="store_true", help="명령만 보인다 (기본)")
    slice_parser.add_argument("--execute", action="store_true", help="실제로 슬라이서를 부른다")
    slice_parser.add_argument("--search-path", help=argparse.SUPPRESS)

    validate = sub.add_parser("validate", help="생성된 G-code 를 정적으로 본다")
    validate.add_argument("--gcode", required=True)
    validate.add_argument("--profile", required=True)

    for item in (discover, inspect, slice_parser, validate):
        item.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.verb == "discover":
        return slicing.discover(args.search_path)
    if args.verb == "inspect":
        return slicing.inspect_mesh(args.input)

    profile, error = slicing.load_profile(args.profile)
    if profile is None:
        report = Report(tool=f"gcode {args.verb}", target=args.profile)
        report.fail("profile", f"{error} 실제 프린터 프로파일 없이는 판정하지 않는다 — 지어내지 않는다.")
        return report

    if args.verb == "validate":
        return slicing.validate(args.gcode, profile)

    report = Report(tool="gcode slice", target=args.input)
    command, error = slicing.slice_command(profile, args.input, args.output, args.backend, args.search_path)
    if not command:
        report.fail("slice", error)
        return report
    report.facts["명령"] = " ".join(command)
    if not args.execute:
        report.unverified("dry-run", "드라이런이다 — 아무것도 실행하지 않았다. 명령을 확인한 뒤 --execute 를 붙여라.")
        return report
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    report.facts["종료코드"] = completed.returncode
    if completed.returncode != 0:
        report.fail("slice", f"슬라이서가 실패했다: {(completed.stderr or completed.stdout or '').strip()[:400]}")
        return report
    if not Path(args.output).is_file():
        report.fail("slice", "슬라이서가 0 을 냈는데 출력 파일이 없다.")
        return report
    report.ok("slice", f"{args.output} 를 만들었다. 프린터로 넘기기 전에 `gcode validate` 를 돌려라.")
    return report


def _parts(argv: list[str]) -> Report:
    from cadlib import catalog  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="cad.py parts", description="기성품 STEP 조달 (커널 불필요)")
    sub = parser.add_subparsers(dest="verb", required=True)

    search = sub.add_parser("search", help="부품을 찾는다")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=8)

    download = sub.add_parser("download", help="STEP 을 받는다")
    download.add_argument("part_id")
    download.add_argument("-o", "--out", required=True)

    for item in (search, download):
        item.add_argument("--catalog", help=f"카탈로그 base URL (환경변수 {catalog.ENV_ENDPOINT} 로도 준다)")
        item.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.verb == "search":
        return catalog.search(args.query, catalog=args.catalog, limit=args.limit)
    return catalog.download(args.part_id, args.out, catalog=args.catalog)


def _robot(kind: str, argv: list[str]) -> Report:
    from cadlib import robot  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog=f"cad.py {kind}", description=f"{kind.upper()} 생성과 검증 (커널 불필요)")
    parser.add_argument("script", help=f"`gen_{kind}()` 를 정의한 소스, 또는 `check` 다음에 기존 파일")
    parser.add_argument("path", nargs="?", help=f"`check` 일 때 검사할 .{kind}")
    parser.add_argument("-o", "--out", help="출력 경로")
    parser.add_argument("--urdf", help="SRDF 교차 검증에 쓸 URDF (강력 권장)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.script == "check":
        if not args.path:
            parser.error("check 는 검사할 파일 경로가 필요하다")
        return robot.validate(kind, args.path, urdf=args.urdf)
    return robot.generate(kind, args.script, args.out, urdf=args.urdf)


# ─────────────────────────────────────────────────────────────────────────────


def usage(stream) -> None:
    stream.write(f"{__doc__}\n사용 가능한 도구: {', '.join(TOOLS)}\n")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        usage(sys.stdout if argv else sys.stderr)
        return 0 if argv else 2

    tool, rest = argv[0], argv[1:]
    if tool not in TOOLS:
        sys.stderr.write(f"모르는 도구다: {tool}\n사용 가능한 도구: {', '.join(TOOLS)}\n")
        return 2

    if tool in ISOLATED and not os.environ.get(REENTRY):
        return _isolate(tool, rest)

    as_json = "--json" in rest
    try:
        if tool == "step":
            report = _step(rest)
        elif tool == "inspect":
            report = _inspect(rest)
        elif tool == "dxf":
            report = _dxf(rest)
        elif tool == "gcode":
            report = _gcode(rest)
        elif tool == "parts":
            report = _parts(rest)
        else:
            report = _robot(tool, rest)
    except KeyboardInterrupt:
        sys.stderr.write("\n중단됐다.\n")
        return 130
    except SystemExit:
        raise
    except Exception as error:  # 실패한 실행의 원인이 곧 수리 단서다 — 삼키지 않는다
        import traceback  # noqa: PLC0415

        from cadlib.kernel import KernelMissing  # noqa: PLC0415

        if isinstance(error, KernelMissing):
            sys.stderr.write(f"{error}\n")
            return 3  # 환경 부재는 검증 실패(1)와 다른 종료코드를 쓴다
        report = Report(tool=tool)
        report.fail(f"{tool}-crashed", f"{type(error).__name__}: {error}")
        if as_json:
            report.facts["traceback"] = traceback.format_exc()
        else:
            sys.stderr.write(traceback.format_exc())
        report.emit(as_json)
        return 1

    return report.emit(as_json)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
