"""`asgard k6` — 부하 시험 레인의 사람 표면.

숫자를 예쁘게 찍는 자리가 아니라 **판정이 보이는** 자리다. 통과/미달은 임계값별로
따로 남고, 실행마다 러너·k6 판·표적이 함께 새겨진다 — 나중에 이 표를 다시 볼 때
"어느 판으로 잰 값인가"를 물을 수 있어야 하기 때문이다.
"""

import json
import os
import shutil
import sys
import tempfile
import time

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .. import k6, theme, ui


def _console() -> Console:
    return Console(
        file=sys.stdout,
        width=ui.term_cols(),
        color_system="auto" if ui._COLOR else None,
        force_terminal=ui._COLOR,
        highlight=False,
    )


def _panel(label: str, table: Table, subtitle: str = "") -> None:
    console = _console()
    title = Text(label, style=f"bold {theme.TEXT}")
    if subtitle:
        title = Text.assemble((label, f"bold {theme.TEXT}"), ("  ", ""), (subtitle, theme.SUBTEXT))
    console.print(Panel(table, title=title, title_align="left", border_style=theme.HAIRLINE, box=box.ROUNDED))


def _mark(ok: bool) -> Text:
    return Text("pass", style="bold green") if ok else Text("FAIL", style="bold red")


def _parse_env(pairs: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in pairs or []:
        if "=" not in item:
            raise ValueError(f"--env 는 KEY=VALUE 형식이다: {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        # 짧은 이름은 시나리오 계약 접두사로 승격 — `--env BANK=x` 가 ASGARD_K6_BANK 로 간다.
        if key.isupper() and not key.startswith("ASGARD_K6_"):
            env[f"ASGARD_K6_{key}"] = value
        else:
            env[key] = value
    return env


# ──────────────────────────────────────────────────────────────────── doctor


def run_k6_doctor(json_: bool = False) -> int:
    runner = k6.resolve_runner()
    kit = k6.kit_dir()
    found = k6.scenarios(os.getcwd())
    version = k6.runner_version(runner) if runner else ""
    state = {
        "schema": "asgard-k6-doctor-v1",
        "runner": runner.label() if runner else "",
        "runner_kind": runner.kind if runner else "",
        "image": runner.image if runner else "",
        "k6_version": version,
        "kit": str(kit),
        "kit_ok": (kit / "lib" / "asgard.js").is_file() and (kit / "pacer.py").is_file(),
        "scenarios": {name: s.origin for name, s in found.items()},
        "ready": bool(runner) and bool(version),
    }
    if json_:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0 if state["ready"] else 1

    table = Table.grid(padding=(0, 2))
    table.add_column(min_width=12, overflow="fold")
    table.add_column(ratio=1, overflow="fold")
    table.add_row(
        Text("runner", style=theme.SUBTEXT), Text(state["runner"] or "없음 — docker/podman 또는 k6 설치 필요")
    )
    table.add_row(Text("k6", style=theme.SUBTEXT), Text(version or "판을 읽지 못했다 (이미지 pull 이 필요할 수 있다)"))
    table.add_row(Text("kit", style=theme.SUBTEXT), Text(str(kit)))
    table.add_row(
        Text("scenarios", style=theme.SUBTEXT),
        Text(", ".join(f"{n}({s.origin[0]})" for n, s in found.items()) or "없음"),
    )
    table.add_row(Text("ready", style=theme.SUBTEXT), _mark(bool(state["ready"])))
    _panel("asgard-k6", table, k6.PROJECT)
    if not state["ready"]:
        print("  docker(또는 podman)를 켜거나 k6 를 설치한 뒤 다시 보라.", file=sys.stderr)
        return 1
    print("  정합성 검사: asgard k6 selftest")
    return 0


# ────────────────────────────────────────────────────────────────── scenarios


def run_k6_list(json_: bool = False) -> int:
    found = k6.scenarios(os.getcwd())
    if json_:
        print(
            json.dumps(
                [{"name": n, "origin": s.origin, "path": str(s.path)} for n, s in found.items()],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not found:
        print("시나리오가 없다 — 키트가 손상됐다.", file=sys.stderr)
        return 1
    table = Table.grid(padding=(0, 2))
    table.add_column(min_width=14, overflow="fold")
    table.add_column(min_width=8, overflow="fold")
    table.add_column(ratio=1, overflow="fold")
    for name, scenario in found.items():
        table.add_row(
            Text(name, style=f"bold {theme.TEXT}"),
            Text(scenario.origin, style=theme.SUBTEXT),
            Text(_headline(scenario.path), style=theme.SUBTEXT),
        )
    _panel("load scenarios", table, f"{len(found)}")
    print("  프로젝트 시나리오는 .asgard/k6/*.js 에 두면 같은 이름으로 잡힌다.")
    return 0


def _headline(path) -> str:
    """시나리오 첫 주석 줄 — 파일이 자기를 설명하게 둔다."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("//"):
                text = stripped.lstrip("/").strip()
                if text:
                    return text
            elif stripped:
                break
    except OSError:
        pass
    return ""


# ───────────────────────────────────────────────────────────────────── run


def run_k6_run(
    scenario_name: str,
    target: str = "",
    vus: int = 0,
    duration: str = "",
    iterations: int = 0,
    p95_max: float = 0.0,
    env_pairs: list[str] | None = None,
    runner_kind: str = "",
    json_: bool = False,
    record: bool = True,
) -> int:
    root = os.getcwd()
    scenario = k6.find_scenario(scenario_name, root)
    if scenario is None:
        print(f"그런 시나리오가 없다: {scenario_name} (asgard k6 scenarios)", file=sys.stderr)
        return 2
    runner = k6.resolve_runner(runner_kind)
    if runner is None:
        print("러너가 없다 — docker/podman 또는 k6 가 필요하다.", file=sys.stderr)
        return 2

    try:
        env = _parse_env(env_pairs or [])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if target:
        env["ASGARD_K6_TARGET"] = target
    if vus:
        env["ASGARD_K6_VUS"] = str(vus)
    if duration:
        env["ASGARD_K6_DURATION"] = duration
    if iterations:
        env["ASGARD_K6_ITERATIONS"] = str(iterations)
    if p95_max:
        env["ASGARD_K6_P95_MAX"] = str(p95_max)
    env.setdefault("ASGARD_K6_SCENARIO", scenario.name)

    stamp = time.strftime("%Y%m%dT%H%M%S") + f"-{scenario.name}"
    out_dir = k6.runs_dir(root) / stamp
    version = k6.runner_version(runner)
    if not json_:
        print(f"  {scenario.name} · {runner.label()} · {version or 'k6 (판 미상)'}")
        print(f"  target {env.get('ASGARD_K6_TARGET', '(시나리오 기본값)')}")

    try:
        report = k6.run_scenario(
            scenario,
            runner=runner,
            out_dir=out_dir,
            env=env,
            k6_version=version,
        )
    except k6.SummaryError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if record:
        k6.record_run(root, report, stamp)
    else:
        shutil.rmtree(out_dir, ignore_errors=True)

    if json_:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        _render_report(report, str(out_dir) if record else "")
    if not report.exit_agrees:
        print(
            "  경고: 종료 코드와 임계값 판정이 어긋난다 — 이 실행의 판정은 믿을 수 없다 (asgard k6 selftest).",
            file=sys.stderr,
        )
        return 1
    return 0 if report.ok else 1


def _render_report(report: k6.Report, out_dir: str = "") -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(min_width=12, overflow="fold")
    table.add_column(ratio=1, overflow="fold")
    lat = report.latency_ms
    table.add_row(Text("verdict", style=theme.SUBTEXT), _mark(report.ok))
    # vus 는 초 단위로 표집된다 — 1초 안에 끝난 실행은 표본이 없어 0 이다. 그 자리에 0 을
    # 찍으면 "동시 사용자 0명"이라는 없는 사실이 표에 남는다.
    # `vus_max` 는 k6 가 **할당한** VU 총합이다 — 계단형 시나리오에서는 단계들의 합이라
    # 동시 접속자 수가 아니다. 이름을 그대로 두어 그 차이가 표면에서 안 뭉개지게 한다.
    vus = f"vus_max {report.vus_max}" if report.vus_max else "vus_max 미표집(실행이 1s 미만)"
    table.add_row(
        Text("requests", style=theme.SUBTEXT),
        Text(
            f"{report.requests} · failed {report.failed} ({report.failed_rate * 100:.2f}%) · "
            f"{report.rate_per_s:.2f} req/s · {vus}"
        ),
    )
    table.add_row(
        Text("latency", style=theme.SUBTEXT),
        Text(
            f"avg {lat.get('avg', 0):.1f}ms · med {lat.get('med', 0):.1f}ms · "
            f"p95 {lat.get('p95', 0):.1f}ms · p99 {lat.get('p99', 0):.1f}ms · max {lat.get('max', 0):.1f}ms"
        ),
    )
    if report.checks_passed or report.checks_failed:
        table.add_row(
            Text("checks", style=theme.SUBTEXT),
            Text(f"{report.checks_passed} pass · {report.checks_failed} fail"),
        )
    for row in report.thresholds:
        table.add_row(
            Text("threshold", style=theme.SUBTEXT),
            Text.assemble(_mark(row.ok), ("  ", ""), (f"{row.metric} {row.expression}", theme.SUBTEXT)),
        )
    for name, values in sorted(report.custom.items()):
        if isinstance(values, dict) and values:
            body = " · ".join(f"{k} {v:.2f}" if isinstance(v, (int, float)) else f"{k} {v}" for k, v in values.items())
            table.add_row(Text(name, style=theme.SUBTEXT), Text(body, style=theme.SUBTEXT))
    _panel(f"{report.scenario}", table, report.k6_version or report.runner)
    if report.target:
        print(f"  target  {report.target}")
    if out_dir:
        print(f"  report  {out_dir}/report.json")


# ─────────────────────────────────────────────────────────────────── selftest


def run_k6_selftest(json_: bool = False, latency_ms: float = 80.0, iterations: int = 40, vus: int = 4) -> int:
    runner = k6.resolve_runner()
    if runner is None:
        print("러너가 없다 — docker/podman 또는 k6 가 필요하다.", file=sys.stderr)
        return 2
    if not json_:
        print(f"  하네스 정합성 검사 · {runner.label()}")
        print("  거동을 아는 표적(pacer)에 걸어 세 판을 돈다 — truth · gate · saturate")

    workdir = tempfile.mkdtemp(prefix="asgard-k6-selftest-")
    try:
        result = k6.selftest(runner=runner, out_dir=workdir, latency_ms=latency_ms, iterations=iterations, vus=vus)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if json_:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return 0 if result.ok else 1

    table = Table.grid(padding=(0, 2))
    table.add_column(min_width=26, overflow="fold")
    table.add_column(min_width=6, overflow="fold")
    table.add_column(ratio=1, overflow="fold")
    for check in result.checks:
        table.add_row(
            Text(check.name, style=f"bold {theme.TEXT}" if not check.ok else theme.TEXT),
            _mark(check.ok),
            Text(
                f"기대 {check.expected} · 관측 {check.observed}" + (f"\n{check.detail}" if not check.ok else ""),
                style=theme.SUBTEXT,
            ),
        )
    _panel("harness integrity", table, result.k6_version or result.runner)
    if result.error:
        print(f"  {result.error}", file=sys.stderr)
        return 1
    if not result.ok:
        print("  하네스가 참을 말하지 못한다 — 이 상태에서 잰 부하 수치는 근거가 아니다.", file=sys.stderr)
        return 1
    print("  하네스 정합성 확인 — 이 레인의 수치는 근거로 쓸 수 있다.")
    return 0


# ───────────────────────────────────────────────────────────────────── report


def run_k6_report(path: str = "", json_: bool = False) -> int:
    root = os.getcwd()
    if not path:
        runs = k6.runs_dir(root)
        candidates = sorted(runs.glob("*/report.json")) if runs.is_dir() else []
        if not candidates:
            print("기록된 실행이 없다 — asgard k6 run <시나리오>", file=sys.stderr)
            return 1
        target = candidates[-1]
    else:
        from pathlib import Path

        target = Path(path)
        if target.is_dir():
            target = target / "report.json"
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"보고서를 읽을 수 없다: {exc}", file=sys.stderr)
        return 1
    if json_:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    try:
        report = k6.parse_summary(payload, exit_code=int(payload.get("exit_code") or 0))
    except k6.SummaryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    report.runner = str(payload.get("runner") or "")
    report.k6_version = str(payload.get("k6_version") or "")
    _render_report(report, str(target.parent))
    return 0 if report.ok else 1
