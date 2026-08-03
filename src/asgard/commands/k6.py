"""`asgard k6` — 부하 시험 레인의 사람 표면.

숫자를 예쁘게 찍는 자리가 아니라 **판정이 보이는** 자리다. 통과/미달은 임계값별로
따로 남고, 실행마다 러너·k6 판·표적이 함께 새겨진다 — 나중에 이 표를 다시 볼 때
"어느 판으로 잰 값인가"를 물을 수 있어야 하기 때문이다.
"""

import json
import shutil
import sys
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


def _verdict(report: k6.Report) -> Text:
    """판정 세 갈래 — 통과 · 미달 · **미판정**. 셋째가 없으면 "잴 것이 없었다"가 초록이 된다."""
    if not report.judged:
        return Text("미판정", style="bold yellow")
    return _mark(report.ok)


def _exit_for(report: k6.Report) -> int:
    """표면의 종료 코드. 판정 없음(3)을 미달(1)과도, 통과(0)와도 가른다."""
    if not report.judged:
        return k6.UNJUDGED_EXIT
    return 0 if report.ok else 1


_BLOCKS = "▁▂▃▄▅▆▇█"


def _spark(values: list[float], width: int = 28) -> str:
    """값의 흐름 한 줄. 바닥은 언제나 0 이다 — 최소값에 맞춰 자르면 3% 흔들림이 절벽이 된다."""
    if not values:
        return ""
    tail = values[-width:]
    top = max(tail)
    if top <= 0:
        return _BLOCKS[0] * len(tail)
    return "".join(_BLOCKS[min(len(_BLOCKS) - 1, int(v / top * (len(_BLOCKS) - 1) + 0.5))] for v in tail)


def _bar(progress: float | None, width: int = 22) -> str:
    """진행 막대. 모르면 안 그린다 — 근거 없이 움직이는 막대는 계기가 아니라 장식이다."""
    if progress is None:
        return "─" * width
    filled = max(0, min(width, int(progress * width + 0.5)))
    return "█" * filled + "░" * (width - filled)


def _live_panel(scenario: str, runner: str, ticks: list, progress: float | None, plan_note: str) -> Panel:
    """도는 동안 보이는 한 판. 네 줄로 가른 이유는 그 넷이 서로 다른 사건이기 때문이다 —
    처리량만 떨어지는 것, 지연만 오르는 것, 실패만 튀는 것, 부하가 안 걸린 것."""
    table = Table.grid(padding=(0, 2))
    table.add_column(min_width=7, overflow="fold")
    table.add_column(ratio=1, overflow="fold")
    last = ticks[-1] if ticks else None
    pct = "  미상" if progress is None else f"{progress * 100:5.1f}%"
    elapsed = f"{last.t:.0f}s" if last else "0s"
    table.add_row(
        Text("진행", style=theme.SUBTEXT),
        Text.assemble((_bar(progress), theme.TEXT), ("  ", ""), (f"{pct}  {elapsed}", theme.SUBTEXT)),
    )
    if last is None:
        table.add_row(
            Text("표본", style=theme.SUBTEXT), Text("첫 표집을 기다려요 — k6는 초당 한 번 재요", theme.SUBTEXT)
        )
        return Panel(
            table,
            title=Text.assemble((scenario, f"bold {theme.TEXT}"), ("  ", ""), (runner, theme.SUBTEXT)),
            title_align="left",
            border_style=theme.HAIRLINE,
            box=box.ROUNDED,
        )
    rps = [t.rps for t in ticks]
    p95 = [t.p95 for t in ticks]
    fails = [t.fail_rate * 100 for t in ticks]
    table.add_row(
        Text("처리량", style=theme.SUBTEXT),
        Text.assemble(
            (f"{last.rps:>7,.0f} req/s", theme.TEXT),
            ("  ", ""),
            (_spark(rps), theme.SUBTEXT),
            ("  ", ""),
            (f"최고 {max(rps):,.0f}", theme.SUBTEXT),
        ),
    )
    table.add_row(
        Text("지연", style=theme.SUBTEXT),
        Text.assemble(
            (f"p95 {last.p95:>6.0f}ms", theme.TEXT),
            ("  ", ""),
            (_spark(p95), theme.SUBTEXT),
            ("  ", ""),
            (f"med {last.med:.0f}ms", theme.SUBTEXT),
        ),
    )
    bad = last.failed_total > 0
    table.add_row(
        Text("실패", style=theme.SUBTEXT),
        Text.assemble(
            (f"{last.fail_rate * 100:>7.2f}%", "bold red" if bad else theme.TEXT),
            ("  ", ""),
            (_spark(fails), theme.SUBTEXT),
            ("  ", ""),
            (f"{last.failed_total:,} / {last.reqs_total:,}건", theme.SUBTEXT),
        ),
    )
    table.add_row(
        Text("동시", style=theme.SUBTEXT),
        Text("미표집" if last.vus is None else f"{last.vus:>7,} VU", style=theme.TEXT),
    )
    if plan_note:
        table.add_row(Text("", style=theme.SUBTEXT), Text(plan_note, style=theme.SUBTEXT))
    return Panel(
        table,
        title=Text.assemble((scenario, f"bold {theme.TEXT}"), ("  ", ""), (runner, theme.SUBTEXT)),
        title_align="left",
        border_style=theme.HAIRLINE,
        box=box.ROUNDED,
    )


def _root() -> str:
    """이 명령이 볼 프로젝트 — 볼륨의 집. 선 자리가 아니라 `.asgard/`가 있는 자리다."""
    return str(k6.project_root())


def _prepare(root: str) -> str | None:
    """실행 전에 레인 자리를 세우고 마운트할 키트 경로를 준다. 못 세우면 이유를 말한다."""
    try:
        return str(k6.prepare_lane(root))
    except OSError as exc:
        print(f"레인 자리를 못 세웠어요 ({k6.lane_dir(root)}): {exc}", file=sys.stderr)
        return None


def _parse_env(pairs: list[str]) -> dict[str, str]:
    """`--env KEY=VALUE` 를 시나리오 계약의 환경 변수로. 못 쓸 이름은 **여기서** 거절한다.

    승격 규칙이 대문자 여부였을 때 두 가지가 조용히 샜다.

    소문자가 그냥 통과했다. `--env bank=hvami` 는 승격도 거절도 안 되고 `-e bank=hvami` 로
    실려 나갔고, 시나리오는 `ASGARD_K6_BANK` 를 읽으므로 그 값을 영영 못 봤다 — 실행은
    **통과**하고 보고서까지 기록되는데 잰 대상이 사람이 지정한 대상이 아니다. 부하 레인에서
    "다른 것을 재고 통과했다"는 조용히 틀린 수치의 정의다. 그래서 접두사가 없는 이름은
    대소문자를 안 보고 전부 승격한다.

    그리고 `"BANK-2".isupper()` 는 참이다(하이픈엔 대소문자가 없어 무시된다). 그 이름은
    승격을 지나 `build_argv` 안쪽에서야 걸렸고, 거기서 나온 평범한 `ValueError` 는 아무도
    안 잡아 트레이스백으로 나갔다 — 이 레인의 다른 입력 오류는 전부 종료 코드 2 로 나가는데
    이 하나만 스택 트레이스였다. 이름 검사를 입구로 당긴다."""
    env: dict[str, str] = {}
    for item in pairs or []:
        if "=" not in item:
            raise ValueError(f"--env는 KEY=VALUE 형식이에요: {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"--env의 이름이 비어 있어요: {item!r}")
        # 접두사가 없는 이름은 전부 시나리오 계약으로 승격한다 — `--env bank=x` = `ASGARD_K6_BANK`.
        name = key if key.startswith("ASGARD_K6_") else f"ASGARD_K6_{key.upper()}"
        if not k6._ENV_RE.match(name):
            raise ValueError(f"--env 이름에 못 쓰는 글자가 있어요: {key!r} (영문·숫자·밑줄만 돼요)")
        env[name] = value
    return env


# ──────────────────────────────────────────────────────────────────── doctor


def run_k6_doctor(json_: bool = False) -> int:
    runner = k6.resolve_runner()
    root = _root()
    kit = k6.kit_dir()
    lane = k6.lane_dir(root)
    mounted = k6.mounted_kit_dir(root)
    synced = k6.kit_is_synced(root)
    home = k6.docker_dir()
    found = k6.scenarios(root)
    version = k6.runner_version(runner) if runner else ""
    image = runner.image if runner else ""
    owned = image.split(":")[0] == k6.OWNED_IMAGE
    state = {
        "schema": "asgard-k6-doctor-v1",
        "runner": runner.label() if runner else "",
        "runner_kind": runner.kind if runner else "",
        "image": image,
        "image_owned": owned,
        "k6_version": version,
        "root": root,
        "lane": str(lane),
        "kit": str(kit),
        "kit_ok": (kit / "lib" / "asgard.js").is_file() and (kit / "pacer.py").is_file(),
        "kit_mounted": str(mounted),
        "kit_synced": synced,
        "docker_home": str(home) if home else "",
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
    if runner and runner.containerized:
        # 어느 이미지로 재는지는 수치의 일부다 — 우리 이미지인지 빌려 온 이미지인지 말한다.
        table.add_row(
            Text("image", style=theme.SUBTEXT),
            Text(f"{image}  {'(asgard 소유)' if owned else '(공개 이미지 — 태그가 움직여요)'}"),
        )
    table.add_row(
        Text("k6", style=theme.SUBTEXT), Text(version or "판을 읽지 못했어요 (이미지 pull이 필요할 수 있어요)")
    )
    # 볼륨의 집이 어디인가는 수치의 일부다 — 마운트되는 것은 배송 경로가 아니라 이 프로젝트의 사본이다.
    table.add_row(Text("project", style=theme.SUBTEXT), Text(root))
    table.add_row(Text("kit", style=theme.SUBTEXT), Text(f"{kit}  (배송 정본)"))
    table.add_row(
        Text("mount", style=theme.SUBTEXT),
        Text(f"{mounted}  {'(동기)' if synced else '(미동기 — asgard k6 sync)'}"),
    )
    if home:
        table.add_row(Text("docker", style=theme.SUBTEXT), Text(str(home)))
    table.add_row(
        Text("scenarios", style=theme.SUBTEXT),
        Text(", ".join(f"{n}({s.origin[0]})" for n, s in found.items()) or "없음"),
    )
    table.add_row(Text("ready", style=theme.SUBTEXT), _mark(bool(state["ready"])))
    _panel("asgard-k6", table, k6.PROJECT)
    if not state["ready"]:
        print("  docker(또는 podman)를 켜거나 k6를 설치한 뒤 다시 확인해 주세요.", file=sys.stderr)
        return 1
    if home and runner and runner.containerized and not owned:
        print(f"  이미지를 고정하려면: docker build -f docker/{k6.PROJECT}/Dockerfile -t {k6.OWNED_IMAGE}:local .")
    print("  정합성 검사: asgard k6 selftest")
    return 0


# ──────────────────────────────────────────────────────────────────── sync


def run_k6_sync(force: bool = False, json_: bool = False) -> int:
    """배송된 키트를 이 프로젝트의 `.asgard/k6/`에 실체화한다 — 볼륨의 원본을 세우는 자리.

    `asgard k6 run`은 매 실행 자동으로 부른다. 이 명령이 따로 있는 이유는 수동 compose
    경로 때문이다: 사람이 스택을 붙들고 있으려면 마운트 원본이 먼저 있어야 한다."""
    root = _root()
    try:
        kit = k6.prepare_lane(root, force=force)
    except OSError as exc:
        print(f"레인 자리를 못 세웠어요 ({k6.lane_dir(root)}): {exc}", file=sys.stderr)
        return 1
    lane = k6.lane_dir(root)
    if json_:
        print(
            json.dumps(
                {
                    "schema": "asgard-k6-sync-v1",
                    "root": root,
                    "lane": str(lane),
                    "kit": str(kit),
                    "out": str(k6.compose_out_dir(root)),
                    "runs": str(k6.runs_dir(root)),
                    "source": str(k6.kit_dir()),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    table = Table.grid(padding=(0, 2))
    table.add_column(min_width=12, overflow="fold")
    table.add_column(ratio=1, overflow="fold")
    table.add_row(Text("project", style=theme.SUBTEXT), Text(root))
    table.add_row(Text("kit", style=theme.SUBTEXT), Text(f"{kit}  ← {k6.kit_dir()}"))
    table.add_row(Text("out", style=theme.SUBTEXT), Text(str(k6.compose_out_dir(root))))
    table.add_row(Text("runs", style=theme.SUBTEXT), Text(str(k6.runs_dir(root))))
    _panel("lane volumes", table, k6.PROJECT)
    print("  수동 스택: ASGARD_K6_LANE=" + str(lane))
    print(f"            docker compose -f docker/{k6.PROJECT}/docker-compose.yml up pacer -d")
    return 0


# ────────────────────────────────────────────────────────────────── scenarios


def run_k6_list(json_: bool = False) -> int:
    found = k6.scenarios(_root())
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
        print("시나리오가 없어요 — 키트가 깨진 것 같아요.", file=sys.stderr)
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
    print("  프로젝트 시나리오는 .asgard/k6/scenarios/*.js에 두면 같은 이름으로 잡혀요.")
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
    live: bool = True,
) -> int:
    root = _root()
    scenario = k6.find_scenario(scenario_name, root)
    if scenario is None:
        print(f"그런 시나리오가 없어요: {scenario_name} (asgard k6 scenarios로 목록을 확인해 주세요)", file=sys.stderr)
        return 2
    runner = k6.resolve_runner(runner_kind)
    if runner is None:
        print("러너가 없어요 — docker나 podman, 아니면 k6가 있어야 해요.", file=sys.stderr)
        return 2
    kit = _prepare(root)
    if kit is None:
        return 1

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

    # 라이브는 사람이 붙어 있을 때만 켠다. `--json` 이면 표준 출력은 기계의 것이고, 파이프
    # 너머에서는 화면을 다시 그리는 것이 로그를 제어 문자로 채울 뿐이다. 켜고 끄는 것이
    # 수치를 바꾸지 않는 것은 계약이다 — 둘 다 같은 요약 파일과 같은 종료 코드로 판정한다.
    watching = live and not json_ and sys.stdout.isatty()
    try:
        report = (
            _run_watched(scenario, runner, out_dir, env, kit, version)
            if watching
            else k6.run_scenario(
                scenario,
                runner=runner,
                out_dir=out_dir,
                env=env,
                kit=kit,
                k6_version=version,
            )
        )
    except k6.SummaryError as exc:
        # 실패해도 자리는 치운다. 여태는 여기서 곧장 나가느라 `--no-record` 가 요약 없는
        # 실행에서 빈 디렉터리를 남겼고, 그 빈 자리가 나중에 "돌긴 돌았다"로 읽혔다.
        if not record:
            shutil.rmtree(out_dir, ignore_errors=True)
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
            "  경고: 종료 코드와 임계값 판정이 어긋나요 — 이번 판정은 믿기 어려워요 (asgard k6 selftest).",
            file=sys.stderr,
        )
        return 1
    if not report.judged:
        print(
            "  이 시나리오엔 임계값이 없어 판정할 것이 없었어요 — 통과가 아니라 미판정이에요.\n"
            "  options.thresholds에 지킬 선을 적으면 그때부터 이 명령이 게이트가 돼요.",
            file=sys.stderr,
        )
    return _exit_for(report)


def _run_watched(scenario, runner, out_dir, env: dict[str, str], kit: str, version: str) -> k6.Report:
    """부하를 걸면서 초 단위로 화면을 고쳐 그린다. 판정은 평소와 같은 자리에서 나온다."""
    from rich.live import Live

    from .. import k6_live

    plan = k6_live.LivePlan.from_env(env)
    note = (
        "" if (plan.total_iterations or plan.total_seconds) else "이 시나리오는 끝을 미리 안 정해요 — 흐른 시간만 재요"
    )
    ticks: list = []
    console = _console()
    with Live(
        _live_panel(scenario.name, runner.label(), ticks, None, note),
        console=console,
        refresh_per_second=4,
        transient=True,  # 끝나면 이 판을 지운다 — 화면에 남는 것은 판정 하나여야 한다
    ) as view:

        def on_tick(tick, progress) -> None:
            ticks.append(tick)
            view.update(_live_panel(scenario.name, runner.label(), ticks, progress, note))

        return k6_live.run_live(
            scenario,
            runner=runner,
            out_dir=out_dir,
            env=env,
            kit=kit,
            k6_version=version,
            on_tick=on_tick,
            plan=plan,
        )


def _render_report(report: k6.Report, out_dir: str = "") -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(min_width=12, overflow="fold")
    table.add_column(ratio=1, overflow="fold")
    lat = report.latency_ms
    table.add_row(Text("verdict", style=theme.SUBTEXT), _verdict(report))
    if not report.judged:
        table.add_row(
            Text("", style=theme.SUBTEXT),
            Text("임계값이 없어 잴 것이 없었어요 — 실패한 요청이 있어도 이 실행은 아무것도 안 막아요", theme.SUBTEXT),
        )
    # vus는 초 단위로 표집된다 — 1초 안에 끝난 실행은 표본이 없어 0 이다. 그 자리에 0을
    # 찍으면 "동시 사용자 0명"이라는 없는 사실이 표에 남는다.
    # `vus_max`는 k6가 **할당한** VU 총합이다 — 계단형 시나리오에서는 단계들의 합이라
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
        print("러너가 없어요 — docker나 podman, 아니면 k6가 있어야 해요.", file=sys.stderr)
        return 2
    root = _root()
    kit = _prepare(root)
    if kit is None:
        return 1
    if not json_:
        print(f"  하네스 정합성 검사 · {runner.label()}")
        print("  거동을 아는 표적(pacer)에 걸어 세 번 돌려요 — truth · gate · saturate")

    # 시스템 임시 디렉터리가 아니라 레인 안에서 돈다: 세 판의 산출도 컨테이너에 마운트되는
    # 볼륨이고, 마운트되는 것은 전부 프로젝트 아래라는 규칙에 예외를 두지 않는다. 임시
    # 디렉터리가 엔진과 공유되는지는 엔진 설정에 달렸지만(도커 데스크톱 기본값은 공유하고,
    # 홈만 공유하는 VM 러너도 있다) 프로젝트 경로는 어차피 공유되어야 하는 자리다.
    workdir = k6.lane_dir(root) / "selftest"
    shutil.rmtree(workdir, ignore_errors=True)
    try:
        result = k6.selftest(
            runner=runner, out_dir=workdir, kit=kit, latency_ms=latency_ms, iterations=iterations, vus=vus
        )
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
        print("  하네스가 참을 말하지 못해요 — 이 상태로 잰 수치는 근거로 못 써요.", file=sys.stderr)
        return 1
    print("  하네스가 멀쩡해요 — 이 레인의 수치는 근거로 써도 돼요.")
    return 0


# ───────────────────────────────────────────────────────────────────── report


def run_k6_report(path: str = "", json_: bool = False) -> int:
    root = _root()
    if not path:
        runs = k6.runs_dir(root)
        candidates = sorted(runs.glob("*/report.json")) if runs.is_dir() else []
        if not candidates:
            print("기록된 실행이 없어요 — asgard k6 run <시나리오>로 한 번 돌려 주세요.", file=sys.stderr)
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
        print(f"보고서를 읽을 수 없어요: {exc}", file=sys.stderr)
        return 1
    # 판정을 먼저 만든다 — 사람 경로와 `--json` 경로가 **같은 종료 코드**로 나가야 한다.
    # 여태 JSON 분기는 payload 를 찍고 무조건 0 을 돌려줬다: 같은 보고서를 사람이 보면
    # `verdict FAIL` · exit 1 인데 자동화가 보면 exit 0 이었고, 그 갈림이 CI 에서 빨간 것을
    # 초록으로 통과시킨다.
    try:
        report = k6.parse_summary(payload, exit_code=int(payload.get("exit_code") or 0))
    except k6.SummaryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if json_:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return _exit_for(report)
    report.runner = str(payload.get("runner") or "")
    report.k6_version = str(payload.get("k6_version") or "")
    _render_report(report, str(target.parent))
    # 되열 때도 같은 경보를 낸다. 이 신호는 "이 판의 판정을 믿지 말라"는 뜻인데, 여태 실행한
    # 그 순간에만 뜨고 기록에서는 사라졌다 — 가장 못 믿을 판정이 가장 조용히 통과했다.
    if not report.exit_agrees:
        print(
            "  경고: 종료 코드와 임계값 판정이 어긋난 실행이에요 — 이 수치는 근거로 쓰기 어려워요.",
            file=sys.stderr,
        )
    return _exit_for(report)


# ────────────────────────────────────────────────────────── baseline · gate


# 기준선으로 삼기를 거절하는 이유 → 사람 문장과 종료 코드.
#
# 코드를 셋으로 가른 이유: 미판정은 이 레인이 이미 낱말과 종료 코드를 정해 둔 사건이라
# `UNJUDGED_EXIT` 로 나가야 다른 표면과 어긋나지 않고, 나머지 둘은 "그 실행을 못 믿는다"는
# 다른 사건이라 1 로 나간다. 셋을 한 코드로 합치면 CI 가 "임계값을 안 적었다"와 "수치가
# 깨졌다"를 못 가른다.
_BASELINE_REFUSAL: dict[str, tuple[str, int]] = {
    "unreadable": ("요약 계약을 안 지킨 기록이에요 — 이 수치가 무엇인지부터 알 수 없어요.", 1),
    "empty": ("요청이 0건인 실행이에요 — 잰 것이 없는 실행은 기준선이 될 수 없어요.", 1),
    "unjudged": (
        "임계값이 없어 판정할 것이 없던 실행이에요 — 아무도 검증하지 않은 실행을 표준으로 삼으면\n"
        "  그 뒤로 똑같이 망가진 실행이 계속 게이트를 통과해요.",
        k6.UNJUDGED_EXIT,
    ),
    "exit-disagrees": (
        "종료 코드와 임계값 판정이 어긋난 실행이에요 — 레인이 이미 못 믿는다고 말한 수치예요.",
        1,
    ),
}

# 판정 못 한 이유 → 사람 문장. 게이트는 이 갈래에서 **막지 않는다**(종료 코드 0).
_GATE_UNDECIDABLE: dict[str, str] = {
    "no-baseline": "기준선이 없어요 — asgard k6 baseline set으로 세우면 그때부터 견줘요",
    "no-run": "견줄 기록이 없어요 — asgard k6 run <시나리오>로 한 번 돌려 주세요",
    "broken-baseline": "기준선 파일을 읽을 수 없어요 — asgard k6 baseline set으로 다시 세워 주세요",
    "not-comparable": "같은 것을 잰 값이 아니어서 수치를 견주지 않았어요",
    "no-measurement": "요청이 0건인 실행이 껴 있어요 — 견줄 수치가 없어요",
}

_AXIS_LABEL = {
    "scenario": "scenario",
    "runner": "runner",
    "k6_version": "k6",
    "target": "target",
    "vus_max": "vus_max",
}


def _numbers(payload: dict) -> str:
    """기준선 한 줄 요약 — 이 실행의 무엇을 표적으로 삼았는지."""
    reqs = payload.get("requests") or {}
    latency = payload.get("latency_ms") or {}
    return (
        f"p95 {float(latency.get('p95') or 0.0):.2f}ms · "
        f"failed {float(reqs.get('failed_rate') or 0.0) * 100:.2f}% · "
        f"{float(reqs.get('rate_per_s') or 0.0):.2f} req/s"
    )


def run_k6_baseline_set(stamp: str = "", json_: bool = False) -> int:
    """어느 실행을 표적으로 삼을지 정한다. 스탬프를 안 주면 가장 최근 기록이다."""
    root = _root()
    record = k6.find_recorded_run(root, stamp)
    if record is None:
        if stamp:
            print(f"그런 기록이 없어요: {stamp} (asgard k6 report로 확인해 주세요)", file=sys.stderr)
            return 2
        print("기록된 실행이 없어요 — asgard k6 run <시나리오>로 한 번 돌려 주세요.", file=sys.stderr)
        return 1

    blocker = k6.baseline_blocker(record.payload)
    if blocker:
        note, code = _BASELINE_REFUSAL[blocker]
        if json_:
            print(
                json.dumps(
                    {"schema": k6.BASELINE_SCHEMA, "ok": False, "stamp": record.stamp, "refused": blocker},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"이 기록은 기준선으로 삼을 수 없어요 — {record.stamp}", file=sys.stderr)
            print(f"  {note}", file=sys.stderr)
        return code

    baseline = k6.write_baseline(root, record)
    if json_:
        print(json.dumps(_baseline_payload(baseline), ensure_ascii=False, indent=2))
        return 0
    _render_baseline(baseline)
    print(f"  baseline  {baseline.path}")
    _render_tolerance(k6.gate_tolerance(root))
    print("  이 실행보다 나빠지면 asgard k6 gate가 막아요.")
    return 0


def run_k6_baseline_show(json_: bool = False) -> int:
    root = _root()
    try:
        baseline = k6.read_baseline(root)
    except k6.SummaryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if baseline is None:
        if json_:
            print(json.dumps({"schema": k6.BASELINE_SCHEMA, "set": False}, ensure_ascii=False, indent=2))
            return 1
        print("기준선이 없어요 — asgard k6 baseline set으로 세워 주세요.", file=sys.stderr)
        return 1
    if json_:
        print(json.dumps(_baseline_payload(baseline), ensure_ascii=False, indent=2))
        return 0
    _render_baseline(baseline)
    print(f"  baseline  {baseline.path}")
    _render_tolerance(k6.gate_tolerance(root))
    return 0


def run_k6_baseline_clear(json_: bool = False) -> int:
    """기준선을 치운다. 없던 것을 치우는 것은 실패가 아니다 — 바라던 상태가 이미 참이다."""
    root = _root()
    removed = k6.clear_baseline(root)
    if json_:
        print(json.dumps({"schema": k6.BASELINE_SCHEMA, "cleared": removed}, ensure_ascii=False, indent=2))
        return 0
    print("기준선을 치웠어요." if removed else "치울 기준선이 없었어요.")
    return 0


def _baseline_payload(baseline: k6.Baseline) -> dict:
    return {
        "schema": k6.BASELINE_SCHEMA,
        "set": True,
        "stamp": baseline.stamp,
        "set_at": baseline.set_at,
        "path": str(baseline.path),
        "run": baseline.run,
    }


def _render_baseline(baseline: k6.Baseline) -> None:
    run = baseline.run
    table = Table.grid(padding=(0, 2))
    table.add_column(min_width=10, overflow="fold")
    table.add_column(ratio=1, overflow="fold")
    table.add_row(Text("stamp", style=theme.SUBTEXT), Text(baseline.stamp))
    table.add_row(Text("set at", style=theme.SUBTEXT), Text(baseline.set_at))
    # 러너·k6 판·표적을 함께 찍는 이유는 장식이 아니다. 이 넷이 비교 가능성 축이고, 지금
    # 기록이 이 값들과 다르면 게이트는 회귀 대신 "견줄 수 없다"고 말한다.
    table.add_row(Text("runner", style=theme.SUBTEXT), Text(str(run.get("runner") or "")))
    table.add_row(Text("k6", style=theme.SUBTEXT), Text(str(run.get("k6_version") or "")))
    table.add_row(Text("target", style=theme.SUBTEXT), Text(str(run.get("target") or "")))
    table.add_row(Text("vus_max", style=theme.SUBTEXT), Text(str(run.get("vus_max") or 0)))
    table.add_row(Text("numbers", style=theme.SUBTEXT), Text(_numbers(run)))
    _panel("load baseline", table, str(run.get("scenario") or ""))


def _render_tolerance(tolerance: k6.Tolerance) -> None:
    print(
        f"  허용 오차  p95 +{tolerance.p95_pct:.1f}% · failed +{tolerance.failed_rate_pp:.2f}%p · "
        f"req/s -{tolerance.rate_per_s_pct:.1f}%"
    )
    print("  덮어쓰려면 pyproject.toml의 [tool.asgard.k6-gate]에 적어 주세요.")


def _gate_verdict_text(verdict: k6.GateVerdict) -> Text:
    if verdict.verdict == k6.VERDICT_PASS:
        return Text("pass", style="bold green")
    if verdict.verdict == k6.VERDICT_REGRESSED:
        return Text("회귀", style="bold red")
    # 못 견줬다는 말은 통과가 아니다. 종료 코드는 둘 다 0 이지만 낱말은 절대 같지 않다.
    return Text("판정 못 함", style="bold yellow")


_DELTA_LABEL = {"p95": "p95", "failed_rate": "failed", "rate_per_s": "req/s"}


def _delta_text(delta: k6.Delta) -> Text:
    """한 축의 변화 한 줄 — 기준선, 지금, 변화율, 그리고 **허용 오차까지** 같이 적는다.

    허용치를 안 적으면 "+7% 인데 왜 통과인가"를 화면에서 못 답한다. 게이트가 왜 그렇게
    판정했는지는 판정과 같은 줄에 있어야 한다."""
    if delta.metric == "failed_rate":
        # 실패율만 퍼센트로 환산해 보인다 — 사람이 0.0125 보다 1.25% 를 빨리 읽는다. 허용치도
        # 비율이 아니라 퍼센트포인트다: 건강한 기준선은 0.0 이라 비율로는 폭을 못 적는다.
        body = f"{delta.baseline * 100:.2f} → {delta.current * 100:.2f} %"
        allowance = f"허용 +{(delta.limit - delta.baseline) * 100:.2f}%p"
    else:
        body = f"{delta.baseline:.2f} → {delta.current:.2f} {delta.unit}  ({delta.change_pct:+.1f}%)"
        margin = (delta.limit / delta.baseline - 1) * 100 if delta.baseline else 0.0
        allowance = f"허용 {margin:+.1f}%"
    parts = [(body, "bold red" if delta.regressed else theme.TEXT), ("  ", ""), (allowance, theme.SUBTEXT)]
    if delta.regressed:
        parts += [("  ", ""), ("FAIL", "bold red")]
    return Text.assemble(*parts)


def _render_gate(verdict: k6.GateVerdict) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(min_width=10, overflow="fold")
    table.add_column(ratio=1, overflow="fold")
    table.add_row(Text("verdict", style=theme.SUBTEXT), _gate_verdict_text(verdict))
    if verdict.baseline_stamp:
        table.add_row(Text("baseline", style=theme.SUBTEXT), Text(verdict.baseline_stamp, style=theme.SUBTEXT))
    if verdict.current_stamp:
        table.add_row(Text("current", style=theme.SUBTEXT), Text(verdict.current_stamp, style=theme.SUBTEXT))
    # 안 맞는 축만 찍는다 — 맞는 축까지 다 늘어놓으면 정작 왜 못 견줬는지가 묻힌다.
    for axis in verdict.mismatched:
        table.add_row(
            Text(_AXIS_LABEL.get(axis.name, axis.name), style=theme.SUBTEXT),
            Text.assemble(
                ("기준선 ", theme.SUBTEXT),
                (axis.baseline or "(없음)", theme.TEXT),
                ("  ·  지금 ", theme.SUBTEXT),
                (axis.current or "(없음)", "bold yellow"),
            ),
        )
    for delta in verdict.deltas:
        table.add_row(Text(_DELTA_LABEL.get(delta.metric, delta.metric), style=theme.SUBTEXT), _delta_text(delta))
    if verdict.reason:
        table.add_row(
            Text("이유", style=theme.SUBTEXT),
            Text(_GATE_UNDECIDABLE.get(verdict.reason, verdict.reason), style=theme.SUBTEXT),
        )
    _panel("load gate", table, verdict.scenario)


def _undecidable(reason: str, json_: bool, scenario: str = "") -> int:
    """판정할 수 없을 때. **막지 않는다** — 표적이 없는 프로젝트에서 이 게이트가 도는 것은
    소음이고, 소음을 내는 게이트는 곧 꺼진다. 대신 이유는 반드시 말한다."""
    verdict = k6.GateVerdict(k6.VERDICT_UNDECIDABLE, reason, scenario=scenario)
    if json_:
        print(json.dumps(verdict.as_dict(), ensure_ascii=False, indent=2))
    else:
        _render_gate(verdict)
    return 0


def run_k6_gate(json_: bool = False) -> int:
    """마지막 기록과 기준선을 견준다. 부하는 안 돈다 — 파일 둘을 읽고 끝난다."""
    root = _root()
    try:
        baseline = k6.read_baseline(root)
    except k6.SummaryError as exc:
        print(f"  {exc}", file=sys.stderr)
        return _undecidable("broken-baseline", json_)
    if baseline is None:
        return _undecidable("no-baseline", json_)

    # 대조군은 **기준선과 같은 시나리오로 돈 가장 최근 기록**이다. 그냥 마지막 기록을 집으면
    # 여러 시나리오를 돌리는 저장소에서 게이트가 상시 "견줄 수 없음"이 된다 — 시나리오는 어차피
    # 비교 가능성 첫 축이라, 그 축에서 미리 고르는 편이 같은 판정을 더 쓸모 있게 만든다.
    current = k6.find_recorded_run(root, scenario=baseline.scenario)
    if current is None:
        return _undecidable("no-run", json_, baseline.scenario)

    verdict = k6.compare_to_baseline(baseline, current, k6.gate_tolerance(root))
    if json_:
        print(json.dumps(verdict.as_dict(), ensure_ascii=False, indent=2))
    else:
        _render_gate(verdict)
        if verdict.verdict == k6.VERDICT_REGRESSED:
            print("  기준선보다 나빠졌어요 — 허용 오차는 asgard k6 baseline show가 보여줘요.", file=sys.stderr)
        elif verdict.verdict == k6.VERDICT_UNDECIDABLE:
            print("  견줄 수 없어 아무것도 막지 않았어요 — 통과가 아니라 미판정이에요.", file=sys.stderr)
    # 미판정 실행을 **대조군으로** 견주는 것은 거절하지 않는다. 기준선은 앞으로를 통과시키는
    # 표준이라 검증을 요구하지만, 대조군은 판정 대상이다 — 임계값이 사라진 시나리오라도
    # 실패율 0.0 → 1.0 같은 악화는 이 비교가 그대로 잡는다. 다만 그 사실은 말해 준다.
    if verdict.deltas and not bool(current.payload.get("judged")) and not json_:
        print(
            "  이 기록은 임계값이 없어 스스로는 미판정이에요 — 여기 판정은 기준선 대비 비교뿐이에요.", file=sys.stderr
        )
    return 1 if verdict.blocked else 0
