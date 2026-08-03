"""부하 시험 화면의 재료 — 창이 그릴 것을 JSON 으로 만든다. 화면 문장은 여기서 안 만든다.

이 모듈이 지는 것은 셋이다.

  안내   지금 이 자리에서 **다음에 할 수 있는 일**이 무엇인가. 러너가 없으면 시나리오를
         고르는 것은 의미가 없고, 표적이 안 열려 있으면 부하를 거는 것은 측정이 아니라
         오타 확인이다. 그래서 단계마다 "됐다/안 됐다"와 안 됐으면 무엇을 하면 되는지를
         좌표로 내려 보낸다. 문장은 창이 만든다.
  실행   부하 한 판을 뒤에서 돌린다. 창은 붙들려 있지 않고, 실행은 창을 닫아도 끝까지 간다.
  중계   도는 동안의 초 단위 기록(`k6_live`)을 커서로 잘라 배달한다.

중계를 파일로 하는 이유가 있다. 메모리에 들고 있으면 창을 새로 고치는 순간 도는 실행의
앞부분이 사라지고, 실행이 끝난 뒤의 화면과 도는 중의 화면이 서로 다른 것을 읽게 된다.
`live.ndjson` 하나를 양쪽이 같이 읽으면 그 갈림이 없다 — 라이브 화면과 사후 화면이 같은
파일의 같은 줄을 본다.

판정은 여기서 안 만든다. 통과/미달은 임계값과 종료 코드가 정하고(`k6.Report`), 이 모듈은
그것을 그대로 통과시킨다.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ... import k6, k6_gate, k6_live, k6_selftest
from .. import loopback

_json_body = loopback.json_body

# 한 창에서 부하는 한 판만 돈다. 둘이 같이 돌면 서로의 표적·CPU·네트워크를 나눠 쓰고,
# 그 순간 두 실행의 수치는 **둘 다** 근거가 아니게 된다. 막는 것이 친절이다.
_LOCK = threading.Lock()
_ACTIVE: "Run | None" = None
_HISTORY: dict[str, "Run"] = {}

_HISTORY_KEEP = 40  # 창 안에 들고 있을 최근 실행 수 — 그보다 오래된 것은 파일로 다시 읽는다
_PROBE_TIMEOUT = 5.0
_MAX_TAIL = 2000  # 한 왕복에 배달할 최대 줄 수 — 오래 닫아 둔 창이 수만 줄을 한 번에 끌지 않게


@dataclass
class Run:
    """도는(또는 돌았던) 부하 한 판. 창이 커서로 따라오는 대상이다."""

    id: str
    kind: str  # "run" | "selftest"
    scenario: str
    root: str
    out_dir: str
    state: str = "running"  # running | done | failed | stopped
    error: str = ""
    started: float = field(default_factory=time.time)
    stop_asked: bool = False
    report: dict | None = None
    selftest: dict | None = None

    @property
    def live_path(self) -> Path:
        return Path(self.out_dir) / k6_live.LIVE_NAME

    def public(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "scenario": self.scenario,
            "state": self.state,
            "error": self.error,
            "started": self.started,
            "elapsed": max(0.0, time.time() - self.started),
            "report": self.report,
            "selftest": self.selftest,
        }


# ────────────────────────────────────────────────────────────────── 패널 재료


def panel_state(root: str) -> dict:
    """화면 한 판의 재료 — 준비 상태 · 시나리오 · 기록 · 지금 도는 것."""
    runner = k6.resolve_runner()
    version = k6.runner_version(runner) if runner else ""
    found = k6.scenarios(root)
    with _LOCK:
        active = _ACTIVE.public() if _ACTIVE else None
    return {
        "schema": "asgard-k6-panel-v1",
        "project": root,
        "lane": str(k6.lane_dir(root)),
        "runner": runner.label() if runner else "",
        "runner_kind": runner.kind if runner else "",
        "image": runner.image if runner else "",
        "image_owned": bool(runner and runner.image.split(":")[0] == k6.OWNED_IMAGE),
        "k6_version": version,
        "kit_synced": k6.kit_is_synced(root),
        "ready": bool(runner) and bool(version),
        "scenarios": [{"name": name, "origin": s.origin, "headline": _headline(s.path)} for name, s in found.items()],
        "runs": _history(root),
        "active": active,
    }


def _headline(path: Path) -> str:
    """시나리오 첫 주석 줄 — 파일이 자기를 설명하게 둔다 (CLI 목록과 같은 규칙)."""
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


def _history(root: str, limit: int = 30) -> list[dict]:
    """기록된 실행 — 새것부터. 판정과 몇 개의 수치만, 나머지는 열어야 나온다."""
    runs = k6.runs_dir(root)
    if not runs.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(runs.glob("*/report.json"), reverse=True)[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        latency = payload.get("latency_ms") or {}
        requests = payload.get("requests") or {}
        out.append(
            {
                "id": path.parent.name,
                "scenario": payload.get("scenario") or "",
                "ok": bool(payload.get("ok")),
                # 옛 보고서엔 이 칸이 없다 — 없으면 "판정이 있었다"로 본다(그때의 ok 가 그 뜻이었다).
                # 없는 것을 False 로 읽으면 지난 기록이 통째로 미판정으로 뒤집힌다.
                "judged": bool(payload.get("judged", True)),
                "exit_code": payload.get("exit_code"),
                "target": payload.get("target") or "",
                "runner": payload.get("runner") or "",
                "requests": requests.get("count") or 0,
                "failed": requests.get("failed") or 0,
                "rate_per_s": requests.get("rate_per_s") or 0.0,
                "p95": latency.get("p95") or 0.0,
                "has_live": (path.parent / k6_live.LIVE_NAME).is_file(),
            }
        )
    return out


# ──────────────────────────────────────────────────────────────────── 실행


def start_run(payload: dict, root: str) -> tuple[int, str, bytes]:
    """부하 한 판을 뒤에서 시작한다. 창은 곧바로 표식을 받고 커서로 따라온다."""
    name = str(payload.get("scenario") or "").strip()
    if not name:
        return _json_body(400, {"error": "시나리오를 골라 주세요"})
    scenario = k6.find_scenario(name, root)
    if scenario is None:
        return _json_body(404, {"error": f"그런 시나리오가 없어요: {name}"})
    runner = k6.resolve_runner(str(payload.get("runner") or ""))
    if runner is None:
        return _json_body(409, {"error": "러너가 없어요 — docker나 podman, 아니면 k6가 있어야 해요"})
    try:
        kit = str(k6.prepare_lane(root))
    except OSError as exc:
        return _json_body(500, {"error": f"레인 자리를 못 세웠어요: {exc}"})

    env = _env_from(payload, scenario.name)
    stamp = time.strftime("%Y%m%dT%H%M%S") + f"-{scenario.name}"
    out_dir = k6.runs_dir(root) / stamp
    run = Run(id=stamp, kind="run", scenario=scenario.name, root=root, out_dir=str(out_dir))

    claimed, busy = _claim(run)
    if not claimed:
        return _json_body(409, {"error": "이미 부하가 도는 중이에요 — 한 번에 한 판만 돌아요", "active": busy})

    version = k6.runner_version(runner)
    return _launch(
        run,
        _drive_run,
        (run, scenario, runner, out_dir, env, kit, version, bool(payload.get("keep_raw"))),
    )


def _launch(run: Run, target, args: tuple) -> tuple[int, str, bytes]:
    """일꾼을 띄우고, **못 띄우면 잡은 자리를 도로 놓는다**.

    자리를 잡는 것과 그 자리를 쓸 스레드가 실제로 뜨는 것은 다른 사건이다. 스레드 생성이
    실패하면(자원 고갈) `_ACTIVE` 는 영원히 `running` 인 채 남고, 그 뒤로 이 창에서는 부하를
    한 판도 못 건다 — 아무것도 안 도는데 "이미 도는 중"이라고 막는 상태다."""
    try:
        threading.Thread(target=target, args=args, name=f"k6-{run.id}", daemon=True).start()
    except RuntimeError as exc:
        run.state = "failed"
        run.error = f"실행을 띄우지 못했어요: {exc}"
        _release(run)
        return _json_body(500, {"error": run.error})
    return _json_body(200, {"id": run.id, "active": run.public()})


def _release(run: Run) -> None:
    global _ACTIVE
    with _LOCK:
        if _ACTIVE is run:
            _ACTIVE = None


def _env_from(payload: dict, scenario: str) -> dict[str, str]:
    """창이 채운 칸 → 시나리오 계약의 환경 변수. 빈 칸은 안 넘긴다(시나리오 기본값이 산다)."""
    env: dict[str, str] = {}
    for key, field_name in (
        ("ASGARD_K6_TARGET", "target"),
        ("ASGARD_K6_VUS", "vus"),
        ("ASGARD_K6_DURATION", "duration"),
        ("ASGARD_K6_ITERATIONS", "iterations"),
        ("ASGARD_K6_P95_MAX", "p95_max"),
        ("ASGARD_K6_FAIL_MAX", "fail_max"),
    ):
        value = payload.get(field_name)
        if value not in (None, "", 0):
            env[key] = str(value)
    for key, value in (payload.get("env") or {}).items():
        name = str(key).strip()
        if name:
            env[name if name.startswith("ASGARD_K6_") else f"ASGARD_K6_{name}"] = str(value)
    env.setdefault("ASGARD_K6_SCENARIO", scenario)
    return env


def _claim(run: Run) -> tuple[bool, dict | None]:
    """자리를 잡는다 — 이미 도는 판이 있으면 못 잡는다."""
    global _ACTIVE
    with _LOCK:
        if _ACTIVE is not None and _ACTIVE.state == "running":
            return False, _ACTIVE.public()
        _ACTIVE = run
        _HISTORY[run.id] = run
        # 창이 오래 열려 있으면 이 장부가 계속 자란다. 끝난 판의 재료는 파일에 남으므로
        # (`live.ndjson`·`report.json`) 여기서 떨어져 나가도 다시 열 수 있다.
        for stale in list(_HISTORY)[:-_HISTORY_KEEP]:
            _HISTORY.pop(stale, None)
        return True, None


def _drive_run(
    run: Run,
    scenario: k6.Scenario,
    runner: k6.Runner,
    out_dir: Path,
    env: dict[str, str],
    kit: str,
    version: str,
    keep_raw: bool,
) -> None:
    """실행을 끝까지 몬다. 창이 닫혀도 이 자리는 계속 간다 — 기록이 남아야 하기 때문이다."""
    try:
        report = k6_live.run_live(
            scenario,
            runner=runner,
            out_dir=out_dir,
            env=env,
            kit=kit,
            k6_version=version,
            container_name=f"{k6.PROJECT}-{run.id.lower().replace('_', '-')}"[:63],
            should_stop=lambda: run.stop_asked,
            keep_raw=keep_raw,
        )
        k6_gate.record_run(run.root, report, run.id)
        run.report = report.as_dict()
        run.report["exit_agrees"] = report.exit_agrees
        run.report["summary_path"] = report.summary_path
        run.state = "done"
    except k6.SummaryError as exc:
        run.error = str(exc)
        run.state = "stopped" if run.stop_asked else "failed"
    except Exception as exc:  # 뒤에서 도는 자리다 — 여기서 새면 창은 영원히 "도는 중"이 된다
        run.error = f"실행이 예상 못 한 자리에서 끊겼어요: {exc}"
        run.state = "failed"


def stop_run(payload: dict) -> tuple[int, str, bytes]:
    """도는 판을 세운다. 중지된 실행은 요약을 안 남긴다 — 그 사실도 그대로 말한다."""
    wanted = str(payload.get("id") or "").strip()
    with _LOCK:
        run = _ACTIVE
    if run is None or (wanted and run.id != wanted):
        return _json_body(404, {"error": "그 실행은 이미 끝났어요"})
    run.stop_asked = True
    return _json_body(200, {"id": run.id, "stopping": True})


# ──────────────────────────────────────────────────────────────── 라이브 중계


def live_state(params: dict[str, list[str]], root: str) -> tuple[int, str, bytes]:
    """접은 기록을 커서부터 배달한다. 커서는 **줄 번호**다 — 파일이 append 전용이라 안전하다."""
    wanted = (params.get("id") or [""])[0].strip()
    try:
        cursor = max(0, int((params.get("cursor") or ["0"])[0]))
    except ValueError:
        cursor = 0

    with _LOCK:
        run = _HISTORY.get(wanted) or (_ACTIVE if not wanted else None)
    if run is not None:
        path = Path(run.out_dir) / k6_live.LIVE_NAME
    else:
        # 표식은 창이 준 문자열이다. 그대로 경로에 이으면 `../../..` 하나로 레인 밖의 파일을
        # 읽어 내보내게 된다 — 이 창은 루프백에만 열리지만, 루프백은 이 기계에서 도는 **모든**
        # 것이 닿는 자리다. 기록 자리의 이름은 우리가 짓는 이름(`<시각>-<시나리오>`)이므로
        # 경로 성분 하나로 못 쓰면 그 표식은 우리 것이 아니다.
        if not wanted or wanted != Path(wanted).name or wanted in (".", ".."):
            return _json_body(400, {"error": "실행 표식이 올바르지 않아요"})
        path = k6.runs_dir(root) / wanted / k6_live.LIVE_NAME
    if run is None and not path.is_file():
        return _json_body(404, {"error": "그 실행의 기록이 없어요"})

    rows: list[dict] = []
    index = 0
    try:
        with path.open(encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                if index <= cursor:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
                if len(rows) >= _MAX_TAIL:
                    break
    except OSError:
        index = cursor  # 아직 파일이 안 생겼다 — 다음 왕복에 온다

    body = {"id": wanted or (run.id if run else ""), "cursor": max(index, cursor), "rows": rows}
    body["active"] = run.public() if run else None
    body["done"] = bool(run and run.state != "running") or (run is None)
    return _json_body(200, body)


# ─────────────────────────────────────────────────────────────── 정합성 검사


def start_selftest(payload: dict, root: str) -> tuple[int, str, bytes]:
    """하네스가 참을 말하는지 검사한다 — 세 판이 끝나면 열세 검사가 한꺼번에 나온다.

    진행률을 안 내는 이유는 없어서가 아니라 **없기 때문**이다. `k6_selftest.selftest()` 는 세 판을
    안에서 돌고 끝에 한 번 답한다. 여기서 초 단위 막대를 그리면 그 막대는 측정이 아니라
    장식이고, 이 레인은 장식을 안 만든다."""
    runner = k6.resolve_runner()
    if runner is None:
        return _json_body(409, {"error": "러너가 없어요 — docker나 podman, 아니면 k6가 있어야 해요"})
    try:
        kit = str(k6.prepare_lane(root))
    except OSError as exc:
        return _json_body(500, {"error": f"레인 자리를 못 세웠어요: {exc}"})

    stamp = time.strftime("%Y%m%dT%H%M%S") + "-selftest"
    workdir = k6.lane_dir(root) / "selftest"
    run = Run(id=stamp, kind="selftest", scenario="selftest", root=root, out_dir=str(workdir))
    claimed, busy = _claim(run)
    if not claimed:
        return _json_body(409, {"error": "이미 부하가 도는 중이에요 — 한 번에 한 판만 돌아요", "active": busy})

    return _launch(run, _drive_selftest, (run, runner, workdir, kit, payload))


def _drive_selftest(run: Run, runner: k6.Runner, workdir: Path, kit: str, payload: dict) -> None:
    import shutil

    shutil.rmtree(workdir, ignore_errors=True)
    try:
        result = k6_selftest.selftest(
            runner=runner,
            out_dir=workdir,
            kit=kit,
            latency_ms=float(payload.get("latency_ms") or 80.0),
            iterations=int(payload.get("iterations") or 40),
            vus=int(payload.get("vus") or 4),
        )
        run.selftest = result.as_dict()
        run.state = "done" if result.ok else "failed"
        run.error = result.error
    except Exception as exc:
        run.error = f"정합성 검사가 끊겼어요: {exc}"
        run.state = "failed"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ────────────────────────────────────────────────────────────────── 표적 확인


def probe_target(payload: dict) -> tuple[int, str, bytes]:
    """부하를 걸기 전에 표적이 대답하는지 한 번 두드린다.

    이 한 왕복이 없으면, 오타 난 주소에 30초를 걸고 나서 "실패율 100%"라는 그럴듯한
    보고서를 받는다. 그것은 부하 시험의 결과가 아니라 주소가 틀렸다는 사실이다."""
    target = str(payload.get("target") or "").strip()
    if not target:
        return _json_body(400, {"error": "표적 주소가 필요해요"})
    if not target.startswith(("http://", "https://")):
        return _json_body(400, {"error": "http:// 또는 https://로 시작하는 주소여야 해요"})
    started = time.monotonic()
    request = urllib.request.Request(target, method="GET", headers={"User-Agent": "asgard-k6/probe"})
    try:
        with urllib.request.urlopen(request, timeout=_PROBE_TIMEOUT) as resp:  # noqa: S310 - 스킴을 위에서 검사했다
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        # 4xx·5xx 도 "닿았다"는 사실이다 — 부하를 걸 수는 있다. 판정은 사람이 한다.
        status = int(exc.code)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return _json_body(
            200,
            {
                "ok": False,
                "target": target,
                "error": f"표적에 닿지 않아요: {getattr(exc, 'reason', exc)}",
                "ms": round((time.monotonic() - started) * 1000, 1),
            },
        )
    return _json_body(
        200,
        {
            "ok": True,
            "target": target,
            "status": status,
            "ms": round((time.monotonic() - started) * 1000, 1),
        },
    )
