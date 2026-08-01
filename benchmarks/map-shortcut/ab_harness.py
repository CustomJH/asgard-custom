#!/usr/bin/env python3
"""map 숏컷 A/B — 지도 주입이 **탐색 홉**을 줄이는가 (LLM 실행).

`harness.py`는 "라우팅이 뜨고 맞다"까지만 증명한다. 그래서 에이전트가 grep 사다리를 덜 탔는가는
이것이 답한다 — `benchmarks/shortcut-recall/`가 메모리 주입에 대해 한 것과 같은 형상이다.

**공정성의 핵심: 지도는 자리만 알고 값은 모른다.** 심은 사실은 전부 핸들러 **본문의 상수**이고,
지도가 아는 것은 명령·경로·역할까지다. 그래서 두 arm 모두 파일을 열어야 답할 수 있고, 주입이
줄여 주는 것은 오로지 **찾아가는 비용**이다. 지도가 답을 통째로 들고 있으면 이 벤치는 "답을
붙여 넣으면 빠르다"를 재게 되고, 그건 아무것도 아니다.

arm 은 구조로 가른다: 에이전트는 `.asgard/map` 이 있을 때만 지도를 주입한다(`heimdall/core.py`).
off arm 은 그 폴더를 지우고 돌린다 — 켜고 끄는 플래그를 새로 만들지 않는다.

    python benchmarks/map-shortcut/ab_harness.py build     # 샌드박스 + 0-LLM 사전검증
    python benchmarks/map-shortcut/ab_harness.py pilot     # 과업 전체 × 2 arm × 1회
    python benchmarks/map-shortcut/ab_harness.py full      # × 3회
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SANDBOX = Path(os.environ.get("MAP_AB_SANDBOX") or "/tmp/asgard-map-ab/sandbox")
RESULTS = Path(__file__).parent / "ab-results.jsonl"
ASGARD = shutil.which("asgard") or "asgard"
RUN_TIMEOUT = int(os.environ.get("MAP_AB_TIMEOUT") or 420)

# (id, 명령 경로, help, 핸들러 상수 이름, 값, 한국어 과업, 판정 정규식)
# 과업은 파일명도 명령명도 대지 않는다 — 도메인 낱말만 준다. 그것이 이 벤치의 질문이다.
FACTS = [
    (
        "ticket",
        "ticket move",
        "티켓을 다른 상태 칸으로 옮긴다",
        "MOVE_BATCH_LIMIT",
        "417",
        "티켓 상태를 옮길 때 한 번에 처리하는 상한이 몇인가? 숫자만 확인해서 알려줘.",
        r"(?<!\d)417(?!\d)",
    ),
    (
        "budget",
        "budget report",
        "이 세션이 쓴 비용을 집계한다",
        "COST_UNIT_SCALE",
        "1913",
        "세션 비용 집계에서 쓰는 비용 단위 배율 값이 몇인가? 숫자만 확인해서 알려줘.",
        r"(?<!\d)1913(?!\d)",
    ),
    (
        "recall",
        "memory recall",
        "기억에서 회수한다",
        "RECALL_FANOUT",
        "628",
        "기억 회수의 팬아웃 값이 몇인가? 숫자만 확인해서 알려줘.",
        r"(?<!\d)628(?!\d)",
    ),
    (
        "scan",
        "index scan",
        "저장소를 훑어 색인을 만든다",
        "SCAN_CHUNK_BYTES",
        "7351",
        "색인 스캔이 한 덩이로 읽는 바이트가 몇인가? 숫자만 확인해서 알려줘.",
        r"(?<!\d)7351(?!\d)",
    ),
    (
        "auth",
        "auth login",
        "구독 제공자에 로그인한다",
        "LOGIN_RETRY_WINDOW",
        "2604",
        "로그인 재시도 창의 값이 몇인가? 숫자만 확인해서 알려줘.",
        r"(?<!\d)2604(?!\d)",
    ),
]
# 디코이 — 과업 낱말과 겹치는 어휘를 아무 답도 없는 모듈에 뿌려 grep 한 방을 막는다.
_DECOYS = ("ticket", "budget", "recall", "scan", "auth", "status", "limit", "retry", "chunk", "fanout")


def _filler(index: int) -> str:
    decoy = _DECOYS[index % len(_DECOYS)]
    return (
        f'"""{decoy} helpers — 보조 계산."""\n\n'
        f"{decoy.upper()}_HINT = {1000 + index}\n\n\n"
        f"def {decoy}_normalize(rows: list) -> list:\n"
        f"    # {decoy} 값을 정규화한다\n"
        f"    return sorted(rows)\n\n\n"
        f"def {decoy}_summary(rows: list) -> dict:\n"
        f'    return {{"{decoy}": len(rows)}}\n'
    )


def build_sandbox() -> None:
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    (SANDBOX / "src" / "demo").mkdir(parents=True)
    (SANDBOX / "src" / "demo" / "__init__.py").write_text("", encoding="utf-8")
    for index in range(40):
        (SANDBOX / "src" / "demo" / f"mod_{index:02}.py").write_text(_filler(index), encoding="utf-8")

    handlers = []
    commands = []
    for fid, path, help_text, const, value, _task, _judge in FACTS:
        group, _, leaf = path.partition(" ")
        module = f"src/demo/{fid}_ops.py"
        (SANDBOX / module).write_text(
            f'"""{fid} 작업 — 핸들러 본문."""\n\n'
            f"# 이 상한은 실측으로 정했다 — 넘기면 뒤쪽 배치가 굶는다\n"
            f"{const} = {value}\n\n\n"
            f"def run_{fid}() -> int:\n"
            f"    return {const}\n",
            encoding="utf-8",
        )
        handlers.append((fid, group, leaf, help_text, module))
        commands.append((group, leaf, help_text))

    groups = sorted({group for _f, group, _l, _h, _m in handlers})
    lines = ["import typer", "", 'app = typer.Typer(help="demo CLI")']
    for group in groups:
        lines.append(f'{group}_app = typer.Typer(help="{group} 작업")')
        lines.append(f'app.add_typer({group}_app, name="{group}")')
    lines.append("")
    for fid, group, leaf, help_text, module in handlers:
        target = module.replace("src/", "").replace("/", ".").removesuffix(".py")
        lines += [
            f'@{group}_app.command("{leaf}", help="{help_text}")',
            f"def {group}_{leaf}() -> None:",
            f"    from {target} import run_{fid}",
            "",
            f"    typer.echo(run_{fid}())",
            "",
            "",
        ]
    (SANDBOX / "src" / "demo" / "cli.py").write_text("\n".join(lines), encoding="utf-8")
    (SANDBOX / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.0.0"\n\n[project.scripts]\ndemo = "demo.cli:app"\n', encoding="utf-8"
    )
    (SANDBOX / "README.md").write_text("# demo\n\n## Layout\n\nsrc/demo\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=SANDBOX, check=True)
    subprocess.run(["git", "add", "-A"], cwd=SANDBOX, check=True)
    subprocess.run(
        ["git", "-c", "user.email=b@b", "-c", "user.name=bench", "commit", "-qm", "seed"], cwd=SANDBOX, check=True
    )


def build_map() -> None:
    subprocess.run([ASGARD, "map", "generate", "--quiet"], cwd=SANDBOX, check=True)
    subprocess.run([ASGARD, "map", "scan", "--quiet"], cwd=SANDBOX, check=True)


def precheck() -> bool:
    """0-LLM 사전검증 — 과업 문구가 그 명령으로 라우팅되는가. 여기서 지면 A/B는 잴 것이 없다."""
    sys.path.insert(0, str(REPO / "src"))
    from asgard.map_context import build_map_context

    ok = True
    for fid, path, _help, _const, value, task, _judge in FACTS:
        text = build_map_context(SANDBOX, task).text
        routed = [line for line in text.splitlines() if line.startswith("- `demo ")]
        hit = any(path in line for line in routed)
        top = routed[0][3:].split("`", 1)[0] if routed else "(없음)"
        # 지도가 답을 들고 있으면 이 벤치는 탐색이 아니라 붙여넣기를 재게 된다.
        leaked = value in text
        print(f"  route[{fid}]: {'HIT' if hit else 'MISS'} → {top}" + ("  ⚠ 값 누출" if leaked else ""))
        ok = ok and hit and not leaked
    return ok


def _reset_state() -> None:
    """런 간 독립 — 퀘스트 로그·프라이어 잔재 제거. 지도는 arm 이 정하므로 여기서 안 만든다."""
    state = SANDBOX / ".asgard"
    if state.exists():
        shutil.rmtree(state)
    state.mkdir()
    (state / ".gitignore").write_text("*\n", encoding="utf-8")


def run_one(fid: str, task: str, judge: str, arm: str, rep: int) -> dict:
    _reset_state()
    if arm == "on":
        build_map()
    env = dict(os.environ)
    # 이 벤치가 재는 것은 지도다 — 메모리 주입은 두 arm 모두에서 끈다.
    env["ASGARD_MEMORY_INJECT"] = "off"
    start = time.time()
    stdout = stderr = ""
    exit_code: int | None = None
    timed_out = False
    try:
        proc = subprocess.run(
            [ASGARD, "run", task, "--provider", "claude-native", "--json"],
            cwd=SANDBOX,
            env=env,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
        )
        stdout, stderr, exit_code = proc.stdout or "", proc.stderr or "", proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    wall = round(time.time() - start, 1)
    summary: dict = {}
    for line in reversed(stdout.strip().splitlines() or [""]):
        try:
            summary = json.loads(line)
            break
        except ValueError:
            continue
    answer = str(summary.get("result", ""))
    # 도구 호출 수는 여기서 못 잰다: `asgard run --json` 의 payload 에 그 필드가 없고, stderr 에도
    # 도구 표식이 안 나간다(재보고 확인 — 세던 `⬢ $` 는 이 빌드에 없는 표식이라 늘 0이었다).
    # 그래서 홉의 대리 지표는 **토큰**이다. 탐색이 길수록 읽은 파일이 프롬프트에 쌓인다.
    row = {
        "fid": fid,
        "arm": arm,
        "rep": rep,
        "success": bool(re.search(judge, answer)),
        "tokens": summary.get("tokens"),
        "cache_read_tokens": summary.get("cache_read_tokens"),
        "wall_s": summary.get("wall_s", wall),
        "exit": exit_code,
        "timeout": timed_out,
        "stderr_bytes": len(stderr),
        "answer_head": answer[:160],
    }
    with open(RESULTS, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 0.0


def report(rows: list[dict]) -> None:
    print("\n  arm    n  성공     토큰 median      토큰 범위        벽시계 median")
    for arm in ("on", "off"):
        arm_rows = [row for row in rows if row["arm"] == arm]
        if not arm_rows:
            continue
        tokens = [row["tokens"] for row in arm_rows if isinstance(row["tokens"], (int, float))]
        spread = f"{min(tokens):,.0f}~{max(tokens):,.0f}" if tokens else "-"
        print(
            f"  {arm:4}  {len(arm_rows):2}  {sum(row['success'] for row in arm_rows)}/{len(arm_rows)}"
            f"   {_median(tokens):10,.0f}   {spread:>16}"
            f"   {_median([row['wall_s'] for row in arm_rows]):10.1f}s"
        )
    print()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    if mode == "build":
        build_sandbox()
        build_map()
        passed = precheck()
        print(f"\n샌드박스 준비 — 사전검증 {'PASS' if passed else 'FAIL'}\n")
        return 0 if passed else 1
    if not SANDBOX.exists():
        print("샌드박스가 없다 — 먼저 `build`", file=sys.stderr)
        return 2
    reps = 3 if mode == "full" else 1
    plan = [
        (fid, task, judge, arm, rep)
        for rep in range(reps)
        for fid, _p, _h, _c, _v, task, judge in FACTS
        for arm in ("on", "off")
    ]
    rows = []
    for index, (fid, task, judge, arm, rep) in enumerate(plan, 1):
        row = run_one(fid, task, judge, arm, rep)
        rows.append(row)
        mark = "OK " if row["success"] else "MISS"
        print(f"  [{index:2}/{len(plan)}] {mark} {fid:7} {arm:3} rep{rep}  tok={row['tokens']}  {row['wall_s']}s")
    report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
