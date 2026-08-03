"""asgard-k6 정합성 검사 — 하네스가 참을 말하는지 **거동을 아는 표적**에 걸어 대조한다.

부하 하네스는 자기가 틀렸을 때 조용히 틀린다. 지연을 잘못 읽어도, 동시성을 안 걸어도,
임계값이 깨졌는데 통과로 보고해도 숫자는 그럴듯하게 나온다. 그래서 미리 정한 지연·정원·
포화점을 가진 표적(`assets/k6_kit/pacer.py`)에 세 판을 걸어 우리가 낸 수치와 대조한다.
이 검사가 녹색이 아니면 다른 어떤 부하 수치도 근거로 쓰면 안 된다.

레인을 `k6` 에서 가른 기준은 크기가 아니라 묻는 것이다. `k6` 는 부하를 걸고 그 판을
판정하고, 여기는 **판정기 자신을** 판정한다. 그래서 이쪽만 표적을 띄우고 되읽는다.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .k6 import (
    SUMMARY_SCHEMA,
    THRESHOLD_EXIT,
    Pacer,
    Report,
    Runner,
    Scenario,
    SummaryError,
    bind_host,
    container_target,
    kit_dir,
    resolve_runner,
    run_scenario,
    runner_version,
)

# ───────────────────────────────────────────────────── 정합성 검사 (selftest)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    expected: str
    observed: str
    detail: str = ""


@dataclass
class Selftest:
    checks: list[Check] = field(default_factory=list)
    runner: str = ""
    k6_version: str = ""
    reports: dict[str, Report] = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks) and not self.error

    def as_dict(self) -> dict:
        return {
            "schema": "asgard-k6-selftest-v1",
            "ok": self.ok,
            "runner": self.runner,
            "k6_version": self.k6_version,
            "error": self.error,
            "checks": [
                {"name": c.name, "ok": c.ok, "expected": c.expected, "observed": c.observed, "detail": c.detail}
                for c in self.checks
            ],
        }


def _check(name: str, ok: bool, expected: object, observed: object, detail: str = "") -> Check:
    return Check(name, bool(ok), str(expected), str(observed), detail)


def selftest(
    *,
    runner: Runner | None = None,
    out_dir: str | os.PathLike[str],
    kit: str | os.PathLike[str] | None = None,
    latency_ms: float = 80.0,
    iterations: int = 40,
    vus: int = 4,
    timeout: float = 300.0,
) -> Selftest:
    """하네스가 참을 말하는지 검사한다 — 표적의 정답을 미리 알고 대조한다.

    세 판을 돈다:
      truth      상한 없는 표적. 건수·지연·동시성이 설정과 맞는지, 관대한 임계값이 통과하는지.
      gate       같은 표적에 **깨질 수밖에 없는** 임계값. 게이트가 실제로 떨어지는지, 그리고
                 주기적 오류 주입이 보고서에 정확한 건수로 남는지.
      saturate   동시성 상한이 걸린 표적. 부하 생성기가 실제로 줄을 세웠는지 (Little's law).

    검사 하나라도 빨간 채로 얻은 부하 수치는 근거가 아니다.
    """
    runner = runner or resolve_runner()
    result = Selftest()
    if runner is None:
        result.error = "러너가 없어요 — docker나 podman, 아니면 k6가 있어야 해요"
        return result
    result.runner = runner.label()
    result.k6_version = runner_version(runner)
    out_root = Path(out_dir)
    host = bind_host(runner)
    # 프로젝트가 같은 이름의 시나리오를 두고 있어도 자기검증은 **내장본**으로 돈다 —
    # 하네스를 검사하는 자가 검사 대상과 같이 흔들리면 검사가 아니다.
    probe = Scenario("selftest", kit_dir() / "scenarios" / "selftest.js", "builtin")

    # ── 1판 truth — 정답을 아는 표적에 관대한 임계값
    try:
        wall_start = time.monotonic()
        with Pacer(host=host, latency_ms=latency_ms) as pacer:
            report = run_scenario(
                probe,
                runner=runner,
                out_dir=out_root / "truth",
                kit=kit,
                env={
                    "ASGARD_K6_TARGET": container_target(runner, pacer.port),
                    "ASGARD_K6_ITERATIONS": str(iterations),
                    "ASGARD_K6_VUS": str(vus),
                    "ASGARD_K6_P95_MAX": str(latency_ms * 20 + 2000),
                    "ASGARD_K6_FAIL_MAX": "0.01",
                },
                timeout=timeout,
                k6_version=result.k6_version,
            )
            stats = pacer.stats()
        wall_ms = (time.monotonic() - wall_start) * 1000.0
        result.reports["truth"] = report

        result.checks.append(
            _check("summary-schema", True, SUMMARY_SCHEMA, SUMMARY_SCHEMA, "요약이 정본 스키마로 파싱됐어요")
        )
        # 시간축에는 여태 검사가 하나도 없었다. 그래서 `duration_ms` 를 상수로 망가뜨려도 13개
        # 검사가 전부 녹색이었다(실측). 시간은 보고서에서 파생 수치의 분모라, 그것이 거짓이면
        # req/s 와 그것으로 판단한 용량 결론이 통째로 거짓이 된다. 두 각도로 묶는다 —
        # ① 요약이 스스로와 맞는가(건수 = 요청률 × 실행 시간)
        # ② 하네스가 실제로 기다린 벽시계를 넘지 않는가
        implied = report.rate_per_s * (report.duration_ms / 1000.0)
        result.checks.append(
            _check(
                "summary-time-consistency",
                report.duration_ms > 0 and abs(implied - report.requests) <= max(1.0, report.requests * 0.1),
                f"요청률 × 실행 시간 ≈ {report.requests}건",
                f"{implied:.1f}건 (rate {report.rate_per_s:.2f}/s × {report.duration_ms:.0f}ms)",
                "건수·요청률·실행 시간 셋 중 하나가 망가지면 이 곱이 어긋나요 — 시간축의 유일한 자물쇠예요",
            )
        )
        result.checks.append(
            _check(
                "duration-within-wall-clock",
                0 < report.duration_ms <= wall_ms,
                f"0 < 실행 시간 <= {wall_ms:.0f}ms",
                f"{report.duration_ms:.0f}ms",
                "보고된 실행 시간이 하네스가 실제로 기다린 시간을 넘을 수는 없어요",
            )
        )
        result.checks.append(
            _check(
                "request-count",
                report.requests == iterations,
                iterations,
                report.requests,
                "고정 반복인데 보고된 요청 수가 다르면 요약이 다른 메트릭을 읽고 있는 거예요",
            )
        )
        served = int(stats.get("requests") or 0)
        result.checks.append(
            _check(
                "server-parity",
                served == report.requests,
                f"server {report.requests}",
                f"server {served}",
                "표적이 센 건수와 하네스가 센 건수예요 — 어긋나면 한쪽이 요청을 흘린 거예요",
            )
        )
        med = report.latency_ms.get("med", 0.0)
        lower, upper = latency_ms * 0.9, latency_ms + 150.0
        result.checks.append(
            _check(
                "latency-truth",
                lower <= med <= upper,
                f"{lower:.0f}~{upper:.0f}ms",
                f"med {med:.1f}ms",
                f"표적이 정확히 {latency_ms:.0f}ms를 자요 — 보고된 중앙값이 그 값이어야 해요",
            )
        )
        peak = int(stats.get("peak_in_flight") or 0)
        result.checks.append(
            _check(
                "concurrency-applied",
                peak == vus,
                f"peak {vus}",
                f"peak {peak}",
                "상한 없는 표적에서는 동시 처리 정점이 VU 수와 같아야 해요 — 작으면 직렬로 돈 거예요",
            )
        )
        result.checks.append(
            _check(
                "threshold-passes-when-met",
                report.thresholds_ok and report.exit_code == 0,
                "thresholds ok · exit 0",
                f"thresholds {'ok' if report.thresholds_ok else 'FAIL'} · exit {report.exit_code}",
                "충족되는 임계값은 통과해야 해요",
            )
        )
        result.checks.append(
            _check(
                "exit-parity-pass",
                report.exit_agrees,
                "exit code == threshold verdict",
                f"exit {report.exit_code} · thresholds {'ok' if report.thresholds_ok else 'FAIL'}",
            )
        )
    except (SummaryError, OSError) as exc:
        result.error = f"truth 판이 끝나지 못했어요: {exc}"
        return result

    # ── 2판 gate — 깨질 수밖에 없는 임계값 + 주기적 오류 주입
    error_rate = 0.25
    try:
        with Pacer(host=host, latency_ms=latency_ms, error_rate=error_rate) as pacer:
            report = run_scenario(
                probe,
                runner=runner,
                out_dir=out_root / "gate",
                kit=kit,
                env={
                    "ASGARD_K6_TARGET": container_target(runner, pacer.port),
                    "ASGARD_K6_ITERATIONS": str(iterations),
                    "ASGARD_K6_VUS": str(vus),
                    # 표적이 확실히 못 지키는 값 — 게이트가 떨어져야 정상이다
                    "ASGARD_K6_P95_MAX": str(max(1.0, latency_ms / 8)),
                    "ASGARD_K6_FAIL_MAX": "0.01",
                },
                timeout=timeout,
                k6_version=result.k6_version,
            )
            stats = pacer.stats()
        result.reports["gate"] = report

        result.checks.append(
            _check(
                "threshold-fails-when-breached",
                not report.thresholds_ok,
                "thresholds FAIL",
                f"thresholds {'ok' if report.thresholds_ok else 'FAIL'}",
                "안 떨어지는 게이트는 장식이에요 — 지킬 수 없는 임계값은 반드시 깨져야 해요",
            )
        )
        result.checks.append(
            _check(
                "exit-code-on-breach",
                report.exit_code == THRESHOLD_EXIT,
                f"exit {THRESHOLD_EXIT}",
                f"exit {report.exit_code}",
                "임계값 미달은 종료 코드로도 나와야 CI가 잡아요",
            )
        )
        expected_failures = int(iterations * error_rate)
        result.checks.append(
            _check(
                "error-accounting",
                report.failed == expected_failures,
                f"{expected_failures} failed",
                f"{report.failed} failed",
                "표적의 실패는 확률이 아니라 주기예요 — 건수가 정확히 맞아야 해요",
            )
        )
        served_errors = int(stats.get("errored") or 0)
        result.checks.append(
            _check(
                "error-parity",
                served_errors == report.failed,
                f"server {report.failed}",
                f"server {served_errors}",
                "표적이 낸 5xx와 하네스가 센 실패가 같아야 해요",
            )
        )
    except (SummaryError, OSError) as exc:
        result.error = f"gate 판이 끝나지 못했어요: {exc}"
        return result

    # ── 3판 saturate — 동시성 상한이 걸린 표적 (부하 생성기가 실제로 줄을 세웠는가)
    cap = max(1, vus // 2)
    try:
        with Pacer(host=host, latency_ms=latency_ms, max_concurrency=cap) as pacer:
            report = run_scenario(
                probe,
                runner=runner,
                out_dir=out_root / "saturate",
                kit=kit,
                env={
                    "ASGARD_K6_TARGET": container_target(runner, pacer.port),
                    "ASGARD_K6_ITERATIONS": str(iterations),
                    "ASGARD_K6_VUS": str(vus),
                    "ASGARD_K6_P95_MAX": str(latency_ms * 30 + 3000),
                    "ASGARD_K6_FAIL_MAX": "0.01",
                },
                timeout=timeout,
                k6_version=result.k6_version,
            )
            stats = pacer.stats()
        result.reports["saturate"] = report

        peak = int(stats.get("peak_in_flight") or 0)
        result.checks.append(
            _check(
                "queue-cap-respected",
                peak <= cap,
                f"peak <= {cap}",
                f"peak {peak}",
                "상한을 건 표적에서 동시 처리 정점이 상한을 넘으면 표적 쪽 게이트가 샌 거예요",
            )
        )
        ceiling = float(stats.get("throughput_ceiling_rps") or 0.0)
        observed = report.rate_per_s
        # 천장의 절반 아래면 부하 생성기가 상한만큼도 못 채웠다는 뜻 — 위쪽은 물리적으로 못 넘는다.
        result.checks.append(
            _check(
                "throughput-ceiling",
                bool(ceiling) and (ceiling * 0.5) <= observed <= (ceiling * 1.2),
                f"{ceiling * 0.5:.1f}~{ceiling * 1.2:.1f} req/s",
                f"{observed:.1f} req/s",
                f"상한 {cap} ÷ 서비스 시간 {latency_ms:.0f}ms = 이론 천장 {ceiling:.1f} req/s (Little's law)",
            )
        )
    except (SummaryError, OSError) as exc:
        result.error = f"saturate 판이 끝나지 못했어요: {exc}"
        return result

    return result
