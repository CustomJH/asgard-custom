"""asgard-k6 라이브 계기 — 부하가 도는 **동안**의 초 단위 기록.

여태 부하 실행에는 시작과 끝만 있었다. 명령을 넣고, 몇 분 기다리고, 요약을 받는다. 그
사이는 검은 상자다. 문제는 지루한 것이 아니라 **판단할 수 없다**는 것이다: 지연이 언제부터
올랐는지, 실패가 처음부터인지 램프가 끝난 뒤인지, 표적이 몇 초째에 무릎을 꿇었는지가
요약 한 줄(`p95 214ms`)로 뭉개진다. 같은 p95 라도 "내내 214ms"와 "50초 동안 40ms 이다가
마지막 10초에 900ms"는 전혀 다른 사건이고, 뒤엣것은 요약만 보면 통과한다.

재료는 이미 k6 가 낸다. `--out json=<파일>` 이 표본마다 한 줄씩 흘린다. 이 모듈이 하는 일은
그 줄을 **1초 칸**으로 접어 우리 계약(`asgard-k6-live-v1`)으로 다시 흘리는 것뿐이다.

접는 이유는 크기다. 3 VU · 15 req/s 짜리 6초 실행이 이미 231KB 다 — 요청 하나가 메트릭
아홉 줄을 낳기 때문이다. 500 req/s 면 초당 1MB 를 넘는다. 그래서 원본은 소비하고 버리고,
남기는 것은 초당 한 줄짜리 접은 기록이다. 그 기록은 CLI 라이브 뷰와 창이 함께 읽고,
실행이 끝난 뒤에도 같은 파일로 그대로 다시 그린다 — 라이브 화면과 사후 화면이 다른 것을
읽으면 둘 중 하나는 반드시 거짓말을 하게 된다.

이 모듈은 판정을 내리지 않는다. 판정은 임계값과 종료 코드가 하고(`k6.Report`), 여기는
"그때 무엇이 보였나"만 적는다.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import k6

LIVE_SCHEMA = "asgard-k6-live-v1"
LIVE_NAME = "live.ndjson"  # 접은 기록 — 창과 CLI 가 같이 읽는 자리
RAW_NAME = "stream.ndjson"  # k6 원본 표본 — 기본적으로 실행이 끝나면 지운다

# k6 는 vus 게이지를 초당 한 번 표집한다. 그보다 잘게 접으면 빈 칸이 생기고, 굵게 접으면
# 순간 실패가 평균에 묻힌다 — 칸의 폭을 표집 주기에 맞춘다.
BUCKET_S = 1.0

# 접을 때 실제로 보는 메트릭. 나머지(http_req_blocked·tls·sending…)는 줄 수의 대부분을
# 차지하면서 라이브 화면에 안 쓰이므로 이름만 보고 일찍 버린다.
_WATCHED = frozenset({"http_reqs", "http_req_duration", "http_req_failed", "iterations", "vus"})

# 표본 없는 초를 몇 칸까지 채울 것인가. 진짜 멈춤은 이 안에서 다 보이고, 이보다 긴 구멍은
# 멈춤이 아니라 시계가 튄 것이다 — 그 경우 채우기를 멈추고 `skipped` 에 몇 초를 건너뛰었는지 적는다.
_MAX_GAP_BUCKETS = 300

# 프로세스 종료 시각 뒤로 이만큼은 아직 "도는 중"으로 본다. 표본의 시계(k6)와 종료를 잰 시계
# (우리)가 같은 기계라도 완전히 같지는 않다 — 이 여유가 없으면 마지막 진짜 칸이 정리로 몰린다.
_TEARDOWN_GRACE_S = 1.0

_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h)")


def parse_duration(text: str) -> float:
    """k6 기간 문자열(`30s`·`1m30s`·`500ms`) → 초. 못 읽으면 0.0 — 0 은 "모른다"다.

    진행률을 못 세는 것과 0%인 것은 다르다. 못 읽었으면 0.0 을 돌려 부르는 쪽이
    "진행 미상"으로 그리게 한다 — 여기서 1분 같은 기본값을 지어내면 화면의 막대가
    근거 없이 움직인다."""
    total = 0.0
    for amount, unit in _DURATION_RE.findall(str(text or "")):
        value = float(amount)
        total += value * {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[unit]
    return total


def _pct(ordered: list[float], q: float) -> float:
    """정렬된 표본의 백분위 — 선형 보간. k6 요약과 같은 방식이라 두 수가 서로를 배신하지 않는다."""
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


@dataclass(frozen=True)
class Tick:
    """1초 칸 하나 — 그 초에 실제로 보인 것.

    `vus` 가 None 인 것은 "0명"이 아니라 **표집이 없었다**는 뜻이다(1초를 못 채운 칸에서
    일어난다). 0 으로 적으면 화면에 "동시 사용자 0명"이라는 없는 사실이 남는다."""

    t: float  # 실행 시작으로부터 흐른 초 (이 칸의 끝)
    reqs: int
    failed: int
    rps: float
    fail_rate: float
    med: float
    p95: float
    p99: float
    max_ms: float
    iters: int
    vus: int | None = None
    reqs_total: int = 0
    failed_total: int = 0
    iters_total: int = 0

    def as_dict(self) -> dict:
        return {
            "kind": "tick",
            "t": round(self.t, 3),
            "reqs": self.reqs,
            "failed": self.failed,
            "rps": round(self.rps, 3),
            "fail_rate": round(self.fail_rate, 6),
            "med": round(self.med, 3),
            "p95": round(self.p95, 3),
            "p99": round(self.p99, 3),
            "max_ms": round(self.max_ms, 3),
            "iters": self.iters,
            "vus": self.vus,
            "reqs_total": self.reqs_total,
            "failed_total": self.failed_total,
            "iters_total": self.iters_total,
        }


@dataclass
class Folder:
    """원본 표본 줄 → 1초 칸. 시계는 표본이 들고 온 것을 쓴다.

    호스트 시계를 쓰지 않는 이유가 있다: 컨테이너 안에서 도는 k6 의 표본이 파일에 닿기까지
    지연이 있고, 그 지연은 일정하지 않다. 호스트에서 읽은 순간으로 칸을 나누면 부하가 아니라
    **파일 IO 의 리듬**을 그리게 된다."""

    t0: float | None = None
    thresholds: dict[str, list[str]] = field(default_factory=dict)
    # 프로세스가 끝난 시각(epoch). 빈 칸의 뜻이 여기서 갈린다 — 도는 동안의 빈 칸은 **멈춤**이라
    # 반드시 그려야 하고, 끝난 뒤의 빈 칸은 k6 가 정리하며 흘린 게이지 표집이라 그리면 모든
    # 실행의 끝에 없었던 "처리량 0" 이 붙는다.
    #
    # 이 자리가 처음에는 참/거짓 깃발이었고, 그것이 틀렸다. 깃발은 "마지막 읽기 전에 켠다"는
    # 순서로만 뜻을 얻는데, 그 순서는 파일 flush 타이밍에 달려 있다 — 표적이 죽어 0 req/s 였던
    # 초가 flush 가 늦으면 살아남고 빠르면 지워졌다. 같은 실행이 두 번 다르게 그려지는 계기는
    # 못 믿는다. 그래서 기준을 **표본이 들고 온 시각**으로 바꾼다: 프로세스가 끝난 뒤에 열린
    # 칸만 정리로 본다. 이러면 언제 읽었는지와 무관하게 같은 그림이 나온다.
    ended_epoch: float | None = None
    reqs_total: int = 0
    failed_total: int = 0
    iters_total: int = 0
    skipped: int = 0  # 상한을 넘겨 안 채운 초 — 0 이 아니면 시간축에 구멍이 있다는 사실이다
    _slot: int | None = None
    _dur: list[float] = field(default_factory=list)
    _reqs: int = 0
    _failed: int = 0
    _iters: int = 0
    _vus: int | None = None

    def feed(self, line: str) -> list[Tick]:
        """줄 하나를 먹는다. 칸이 넘어갔으면 그 사이의 칸들을 완성해 돌려준다."""
        line = line.strip()
        if not line or line[0] != "{":
            return []
        try:
            row = json.loads(line)
        except ValueError:
            return []  # 반쯤 쓰인 줄 — 다음 왕복에 온전한 줄로 다시 온다
        metric = row.get("metric")
        if row.get("type") == "Metric":
            self._remember_thresholds(row)
            return []
        if metric not in _WATCHED:
            return []
        data = row.get("data") or {}
        stamp = _epoch(data.get("time"))
        if stamp is None:
            return []
        if self.t0 is None:
            self.t0 = stamp
        slot = int((stamp - self.t0) // BUCKET_S)
        done = self._roll(slot)
        value = data.get("value")
        value = float(value) if isinstance(value, (int, float)) else 0.0
        if metric == "http_reqs":
            self._reqs += int(value)
        elif metric == "http_req_duration":
            self._dur.append(value)
        elif metric == "http_req_failed":
            self._failed += int(value)  # rate 표본은 실패 1 · 성공 0 이다
        elif metric == "iterations":
            self._iters += int(value)
        elif metric == "vus":
            self._vus = int(value)
        return done

    def close(self) -> list[Tick]:
        """마지막 칸을 닫는다 — 실행이 끝나도 채 1초가 안 된 꼬리가 남는다.

        요청도 반복도 없이 게이지 표본 하나만 든 꼬리는 버린다. 그것은 부하가 아니라
        k6 가 종료하며 흘린 마지막 vus 표집이고, 그대로 그리면 모든 실행의 끝에 실제로는
        없었던 "처리량 0" 한 칸이 붙는다."""
        if self._slot is None:
            return []
        if not self._reqs and not self._iters and not self._dur:
            self._slot = None
            return []
        return self._live([self._emit()])

    def _live(self, ticks: list[Tick]) -> list[Tick]:
        """프로세스가 끝난 뒤에 열린 빈 칸만 버린다 — 도는 동안의 빈 칸은 사실이다."""
        if self.ended_epoch is None or self.t0 is None:
            return ticks
        cut = self.ended_epoch - self.t0 + _TEARDOWN_GRACE_S
        return [tick for tick in ticks if tick.reqs or tick.iters or (tick.t - BUCKET_S) < cut]

    def _remember_thresholds(self, row: dict) -> None:
        data = row.get("data") or {}
        rows = [str(x) for x in (data.get("thresholds") or [])]
        if rows:
            self.thresholds[str(data.get("name") or row.get("metric") or "")] = rows

    def _roll(self, slot: int) -> list[Tick]:
        """칸을 넘긴다. 건너뛴 칸은 **빈 칸으로 채운다**.

        표본이 한 줄도 없는 초를 그냥 건너뛰면 화면에서 그 초가 사라지고, 멈춰 있던 구간이
        시간축에서 접혀 "쭉 잘 돌았다"로 보인다. 표적이 무릎을 꿇은 자리가 정확히 그런
        모양이므로, 가장 봐야 할 것을 가장 확실히 지우는 셈이 된다."""
        if self._slot is None:
            self._slot = slot
            return []
        if slot <= self._slot:
            return []
        done = [self._emit()]
        # 채우는 칸에는 상한이 있다. 시계가 앞으로 튀면(NTP 보정·컨테이너와 호스트의 어긋남)
        # 한 표본이 몇 시간짜리 구멍을 열고, 상한이 없으면 그 한 줄이 수천 개의 가짜 칸을
        # 만들어 파일과 화면을 채운다 — 두 시간 점프면 7,200 칸이다.
        gap = min(slot - self._slot - 1, _MAX_GAP_BUCKETS)
        for _ in range(gap):
            self._slot += 1
            done.append(self._emit())  # 표본 없는 초 — 처리량 0 으로 남는다
        self.skipped += max(0, slot - self._slot - 1)
        self._slot = slot
        return self._live(done)

    def _emit(self) -> Tick:
        ordered = sorted(self._dur)
        self.reqs_total += self._reqs
        self.failed_total += self._failed
        self.iters_total += self._iters
        tick = Tick(
            t=float((self._slot or 0) + 1) * BUCKET_S,
            reqs=self._reqs,
            failed=self._failed,
            rps=self._reqs / BUCKET_S,
            fail_rate=(self._failed / self._reqs) if self._reqs else 0.0,
            med=_pct(ordered, 0.5),
            p95=_pct(ordered, 0.95),
            p99=_pct(ordered, 0.99),
            max_ms=ordered[-1] if ordered else 0.0,
            iters=self._iters,
            vus=self._vus,
            reqs_total=self.reqs_total,
            failed_total=self.failed_total,
            iters_total=self.iters_total,
        )
        self._dur = []
        self._reqs = 0
        self._failed = 0
        self._iters = 0
        return tick


def _epoch(text: object) -> float | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


class Tail:
    """append 되는 파일에서 **온전한 줄만** 읽는다.

    바이트 자리를 들고 다니며 마지막 개행까지만 소비한다. 반쯤 쓰인 꼬리를 남겨 두는 것이
    핵심이다 — 그것을 지금 파싱하면 잘린 JSON 이 되고, 그 줄의 표본은 영영 사라진다."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.offset = 0

    def read(self) -> list[str]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size <= self.offset:
            return []
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read(size - self.offset)
        except OSError:
            return []
        cut = chunk.rfind(b"\n")
        if cut < 0:
            return []
        self.offset += cut + 1
        return chunk[: cut + 1].decode("utf-8", "replace").splitlines()


def live_argv(base: list[str], raw_path: str) -> list[str]:
    """k6 argv 에 표본 스트림 출력을 끼운다.

    `k6.build_argv` 의 산물은 어떤 러너든 **시나리오 경로가 맨 끝**이다(네이티브면 호스트
    경로, 컨테이너면 `/asgard/...`). 그 앞에 끼우면 두 러너 모두에서 같은 자리에 붙는다."""
    argv = list(base)
    if not argv:
        raise ValueError("빈 argv에는 스트림 출력을 붙일 수 없어요")
    argv[-1:-1] = ["--out", f"json={raw_path}"]
    return argv


@dataclass
class LivePlan:
    """이 실행이 어디까지 가면 끝나는가 — 진행률의 분모.

    둘 다 0 이면 진행률은 **미상**이다. 지어내지 않는다."""

    total_iterations: int = 0
    total_seconds: float = 0.0

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "LivePlan":
        raw = str(env.get("ASGARD_K6_ITERATIONS") or "0")
        iterations = int(raw) if raw.isdigit() else 0
        return cls(iterations, parse_duration(env.get("ASGARD_K6_DURATION") or ""))

    def progress(self, tick: Tick) -> float | None:
        """지금까지의 진행률. **모르면 None** 이고, 그것은 0% 와 다른 말이다.

        반복 고정은 분모가 참이다 — 몇 번 돌면 끝나는지 시나리오가 그 수로 정한다.

        지속 고정은 참이 아니다. `ASGARD_K6_DURATION` 은 **유지 구간**이고, 램프가 있는
        시나리오의 실제 길이는 그보다 길다(실측: `http-smoke --duration 1s` 는 5s 램프업 +
        1s 유지 + 5s 램프다운 = 11.08s 를 돌았다). 그 값을 총 길이로 쓰면 첫 틱부터 100% 가
        찍히고, 그 뒤 열 개 틱이 전부 100% 였다 — 다 찼는데 계속 도는 막대는 계기가 아니다.

        그래서 지속은 **어림**으로만 쓴다: 어림 안에 있으면 그 비율을 주되 100% 는 안 주고,
        어림을 넘긴 순간 그 어림이 틀렸다는 사실이 증명된 것이므로 모른다고 답한다. 화면은
        거기서 "남은 시간을 모른다"로 바뀐다. 틀린 100% 보다 정직한 미상이 낫다."""
        if self.total_iterations > 0:
            return min(1.0, tick.iters_total / self.total_iterations)
        if self.total_seconds > 0:
            return min(0.99, tick.t / self.total_seconds) if tick.t <= self.total_seconds else None
        return None

    def as_dict(self) -> dict:
        return {"total_iterations": self.total_iterations, "total_seconds": self.total_seconds}


def replay(path: str | os.PathLike[str]) -> Iterator[dict]:
    """접은 기록을 그대로 다시 읽는다 — 사후 화면이 라이브 화면과 같은 것을 본다."""
    try:
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
    except OSError:
        return


def run_live(
    scenario: k6.Scenario,
    *,
    runner: k6.Runner,
    out_dir: str | os.PathLike[str],
    env: dict[str, str] | None = None,
    kit: str | os.PathLike[str] | None = None,
    timeout: float = 1800.0,
    k6_version: str = "",
    container_name: str = "",
    on_tick: Callable[[Tick, float | None], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    keep_raw: bool = False,
    plan: LivePlan | None = None,
) -> k6.Report:
    """시나리오를 돌리면서 초 단위 기록을 흘리고, 끝나면 평소의 판정을 돌려준다.

    `k6.run_scenario` 와 판정 계약은 같다(요약 파일 + 종료 코드). 다른 것은 도는 동안
    `live.ndjson` 이 자란다는 것 하나다 — 그래서 라이브를 켜고 끄는 것이 수치를 바꾸지
    않는다. 바꾸면 그건 계기가 아니라 관찰자 효과다."""
    env = dict(env or {})
    out = Path(out_dir)
    plan = plan or LivePlan.from_env(env)
    _prepare_out(out, runner)

    summary_path = out / k6.SUMMARY_NAME
    raw_host = out / RAW_NAME
    raw_host.unlink(missing_ok=True)
    raw_arg = f"{k6.CONTAINER_MOUNT}/out/{RAW_NAME}" if runner.containerized else str(raw_host)
    name = container_name or k6.container_name()
    argv = live_argv(k6.build_argv(runner, scenario, out, env, quiet=True, container_name=name, kit=kit), raw_arg)

    live_path = out / LIVE_NAME
    console = out / "console.log"
    folder = Folder()
    started = time.monotonic()
    stopped = False

    with live_path.open("w", encoding="utf-8") as sink, console.open("wb") as noise:
        _write(
            sink,
            {
                "schema": LIVE_SCHEMA,
                "kind": "start",
                "scenario": scenario.name,
                "runner": runner.label(),
                "k6_version": k6_version,
                "target": env.get("ASGARD_K6_TARGET", ""),
                **plan.as_dict(),
            },
        )
        try:
            proc = subprocess.Popen(argv, stdout=noise, stderr=subprocess.STDOUT)
        except OSError as exc:
            _write(sink, {"kind": "error", "error": str(exc)})
            raise k6.SummaryError(f"러너를 실행할 수 없어요: {exc}") from exc

        # 창을 닫으면 이 판을 모는 스레드는 daemon 이라 그 자리에서 얼어붙는다 — `finally` 가
        # 안 돌고, 그러면 컨테이너는 **살아서 계속 표적을 때린다**. 아무도 안 보는 부하가
        # 남는 것이 가장 나쁘다: 다음에 뜬 창은 그 위에 또 한 판을 걸고, 그 순간 두 실행의
        # 수치가 둘 다 근거가 아니게 된다. 인터프리터가 내려갈 때 도는 판을 세운다.
        stopper = _atexit_halt(proc, runner, name)

        tail = Tail(raw_host)

        def drain() -> None:
            for line in tail.read():
                for tick in folder.feed(line):
                    _publish(sink, tick, plan, on_tick)

        try:
            while proc.poll() is None:
                drain()
                if should_stop is not None and should_stop() and not stopped:
                    stopped = True
                    _halt(proc, runner, name)
                    _write(sink, {"kind": "stopped", "at": round(time.monotonic() - started, 3)})
                if time.monotonic() - started > timeout:
                    _halt(proc, runner, name)
                    _write(sink, {"kind": "error", "error": f"부하 실행이 {timeout:.0f}s 안에 끝나지 않았어요"})
                    raise k6.SummaryError(f"부하 실행이 {timeout:.0f}s 안에 끝나지 않았어요")
                time.sleep(0.2)
            # 종료 시각을 먼저 새긴다 — 이 뒤에 열리는 빈 칸이 정리다. 마지막 읽기보다 **앞에**
            # 새겨야 하는 이유는, 뒤에 새기면 판정 기준이 다시 읽기 타이밍에 매이기 때문이다.
            folder.ended_epoch = time.time()
            drain()  # 종료와 마지막 flush 사이에 남은 줄
            for tick in folder.close():
                _publish(sink, tick, plan, on_tick)
            if folder.skipped:
                _write(sink, {"kind": "gap", "seconds": folder.skipped})
        finally:
            if proc.poll() is None:
                _halt(proc, runner, name)
            stopper()
            if not keep_raw:
                raw_host.unlink(missing_ok=True)

        code = proc.returncode if proc.returncode is not None else -1
        if not summary_path.is_file():
            noise_tail = _tail_text(console)
            _write(sink, {"kind": "error", "error": f"요약이 없어요 (exit {code})"})
            if stopped:
                raise k6.SummaryError("실행을 중지했어요 — 중지된 실행은 요약을 남기지 않아요.")
            raise k6.SummaryError(
                "요약 파일이 나오지 않았어요 — 시나리오가 handleSummary를 export 하지 않았거나 "
                f"실행이 시작 전에 죽었어요 (exit {code}).\n{noise_tail}"
            )
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _write(sink, {"kind": "error", "error": f"요약을 읽을 수 없어요: {exc}"})
            raise k6.SummaryError(f"요약을 읽을 수 없어요: {exc}") from exc

        report = k6.parse_summary(payload, exit_code=code, runner=runner.label(), k6_version=k6_version)
        report.summary_path = str(summary_path)
        report.stderr = _tail_text(console)
        _write(sink, {"kind": "end", "stopped": stopped, "report": report.as_dict()})
    return report


def _atexit_halt(proc: subprocess.Popen, runner: k6.Runner, name: str) -> Callable[[], None]:
    """인터프리터 종료 때 이 판을 세우는 손을 걸고, 그것을 떼는 함수를 준다.

    정상으로 끝나면 곧바로 떼므로 평소에는 아무 일도 안 한다. 남는 경우는 하나뿐이다 —
    스레드가 얼어붙은 채 프로세스가 내려갈 때, 그때만 이 손이 컨테이너를 회수한다."""

    def halt() -> None:
        if proc.poll() is None:
            _halt(proc, runner, name)

    atexit.register(halt)
    return lambda: atexit.unregister(halt)


def _publish(sink, tick: Tick, plan: LivePlan, on_tick: Callable[[Tick, float | None], None] | None) -> None:
    progress = plan.progress(tick)
    row = tick.as_dict()
    row["progress"] = progress
    _write(sink, row)
    if on_tick is not None:
        on_tick(tick, progress)


def _write(sink, row: dict) -> None:
    """한 줄 쓰고 즉시 내보낸다 — 버퍼에 남으면 라이브가 라이브가 아니다."""
    sink.write(json.dumps(row, ensure_ascii=False) + "\n")
    sink.flush()


def _prepare_out(out: Path, runner: k6.Runner) -> None:
    """산출 자리 세우기 — `k6.run_scenario` 와 같은 계약이다.

    컨테이너 안의 k6 는 비루트로 돌고 그 uid 는 호스트가 모른다. 못 쓰면 요약도 표본도
    통째로 버려지므로 이 실행의 산출 디렉터리 하나만 넓힌다."""
    out.mkdir(parents=True, exist_ok=True)
    if runner.containerized:
        try:
            out.chmod(0o777)
        except OSError:
            pass
    (out / k6.SUMMARY_NAME).unlink(missing_ok=True)  # 이전 실행의 요약을 이번 것으로 읽는 사고를 막는다


def _halt(proc: subprocess.Popen, runner: k6.Runner, name: str) -> None:
    """실행을 세운다. 컨테이너는 밖에서 죽여야 한다 — `docker run` 을 죽여도 안이 남는다."""
    if runner.containerized:
        subprocess.run(
            [runner.binary, "kill", name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _tail_text(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""
