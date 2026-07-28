#!/usr/bin/env python3
"""pacer — 부하 하네스가 자기 자신을 검증할 때 쓰는 **거동을 아는 표적**.

부하 시험은 표적을 잰다. 그런데 하네스 자체가 틀렸으면 그 수치는 조용히 틀린다 —
지연을 잘못 읽거나, 동시성을 실제로 걸지 않았거나, 임계값이 깨져도 통과로 보고하거나.
그걸 잡으려면 **정답이 미리 계산되는 표적**이 필요하다. 이 서버가 그 자리다.

거동은 전부 결정론이다 (난수 없음):

  지연        요청마다 정확히 ``--latency-ms`` 를 잔다.
  오류        ``--error-rate`` 는 확률이 아니라 **주기**다. 0.25 면 4번째 요청마다 500 —
              N 건을 보내면 실패 건수는 floor(N/4) 로 미리 안다.
  동시성 상한 ``--max-concurrency`` 를 넘는 요청은 세마포어에서 줄을 선다. 처리량 천장은
              Little's law 로 C/S (상한 ÷ 서비스 시간) 이고, 이 값과 하네스가 보고한
              처리량이 어긋나면 부하 생성기가 동시성을 안 걸었다는 뜻이다.

``/stats`` 는 서버가 자기 쪽에서 센 값을 준다. 클라이언트(k6)가 보고한 건수와 이 값이
다르면 둘 중 하나는 요청을 흘린 것이다 — 어느 쪽도 조용히 넘어가면 안 되는 사건이다.

단독 실행 가능 (표준 라이브러리만):
    python3 pacer.py --port 8799 --latency-ms 120 --error-rate 0.25 --max-concurrency 4
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

SCHEMA = "asgard-k6-pacer-v1"


class Pacer:
    """서버가 자기 거동을 스스로 아는 상태 — 카운터와 게이트."""

    def __init__(self, latency_ms: float, error_rate: float, max_concurrency: int) -> None:
        self.latency_ms = max(0.0, float(latency_ms))
        self.error_rate = min(1.0, max(0.0, float(error_rate)))
        self.max_concurrency = max(0, int(max_concurrency))
        self.started_at = time.time()
        self._lock = threading.Lock()
        self._gate = threading.Semaphore(self.max_concurrency) if self.max_concurrency else None
        self.total = 0
        self.served = 0
        self.errored = 0
        self.in_flight = 0
        self.peak_in_flight = 0
        self.by_path: dict[str, int] = {}

    # 오류는 확률이 아니라 주기다 — N 건에서 실패 건수가 floor(N*rate) 로 계산된다.
    def _next_ticket(self, path: str) -> tuple[int, bool]:
        with self._lock:
            self.total += 1
            ticket = self.total
            self.by_path[path] = self.by_path.get(path, 0) + 1
        if self.error_rate <= 0:
            return ticket, False
        if self.error_rate >= 1:
            return ticket, True
        period = 1.0 / self.error_rate
        # floor(n/period) 가 증가하는 지점이 실패 — 주기 4 면 4·8·12번째
        return ticket, int(ticket // period) > int((ticket - 1) // period)

    def _enter(self) -> None:
        if self._gate:
            self._gate.acquire()
        with self._lock:
            self.in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self.in_flight)

    def _leave(self, failed: bool) -> None:
        with self._lock:
            self.in_flight -= 1
            self.served += 1
            if failed:
                self.errored += 1
        if self._gate:
            self._gate.release()

    def handle(self, path: str, sleep_ms: float | None = None) -> tuple[int, bool]:
        """요청 하나를 규정대로 처리하고 (상태코드, 실패여부) 를 준다."""
        _, failed = self._next_ticket(path)
        self._enter()
        try:
            delay = self.latency_ms if sleep_ms is None else max(0.0, sleep_ms)
            if delay:
                time.sleep(delay / 1000.0)
        finally:
            self._leave(failed)
        return (500 if failed else 200), failed

    def stats(self) -> dict:
        with self._lock:
            elapsed = max(1e-9, time.time() - self.started_at)
            return {
                "schema": SCHEMA,
                "config": {
                    "latency_ms": self.latency_ms,
                    "error_rate": self.error_rate,
                    "max_concurrency": self.max_concurrency,
                },
                "requests": self.total,
                "served": self.served,
                "errored": self.errored,
                "in_flight": self.in_flight,
                "peak_in_flight": self.peak_in_flight,
                "by_path": dict(self.by_path),
                "uptime_s": elapsed,
                # 이론 천장 — Little's law. 하네스가 동시성을 실제로 걸었는지 대조하는 기준.
                "throughput_ceiling_rps": (
                    (self.max_concurrency / (self.latency_ms / 1000.0))
                    if self.max_concurrency and self.latency_ms
                    else None
                ),
            }


def _handler(pacer: Pacer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "asgard-k6-pacer"
        sys_version = ""

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _route(self, body: dict | None = None) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path == "/stats":
                self._send(200, pacer.stats())
                return
            if path == "/health":
                self._send(200, {"ok": True, "schema": SCHEMA})
                return
            if path == "/reset":
                fresh = Pacer(pacer.latency_ms, pacer.error_rate, pacer.max_concurrency)
                pacer.__dict__.update({k: v for k, v in fresh.__dict__.items() if k not in ("_lock", "_gate")})
                self._send(200, {"reset": True})
                return
            sleep_ms = None
            if path == "/slow":
                raw = parse_qs(parsed.query).get("ms", ["0"])[0]
                try:
                    sleep_ms = float(raw)
                except ValueError:
                    sleep_ms = 0.0
            status, failed = pacer.handle(path, sleep_ms)
            self._send(
                status,
                {
                    "ok": not failed,
                    "path": path,
                    "latency_ms": pacer.latency_ms if sleep_ms is None else sleep_ms,
                    # 회수형 표적 흉내 — 응답 모양을 재는 시나리오가 붙을 자리
                    "results": [] if failed else [{"id": pacer.total, "echo": body or {}}],
                },
            )

        def do_GET(self) -> None:  # noqa: N802 - stdlib 계약
            self._route()

        def do_POST(self) -> None:  # noqa: N802 - stdlib 계약
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                body = {}
            self._route(body if isinstance(body, dict) else {})

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib 시그니처
            """부하 중 요청 로그는 그 자체가 부하다 — 측정값에 관측자가 섞인다."""

    return Handler


def serve(host: str, port: int, latency_ms: float, error_rate: float, max_concurrency: int):
    pacer = Pacer(latency_ms, error_rate, max_concurrency)
    server = ThreadingHTTPServer((host, port), _handler(pacer))
    server.daemon_threads = True
    return server, pacer


def main() -> int:
    ap = argparse.ArgumentParser(description="deterministic reference target for the asgard-k6 lane")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--latency-ms", type=float, default=120.0)
    ap.add_argument("--error-rate", type=float, default=0.0, help="주기적 실패 비율 (확률 아님)")
    ap.add_argument("--max-concurrency", type=int, default=0, help="0 이면 상한 없음")
    args = ap.parse_args()

    server, pacer = serve(args.host, args.port, args.latency_ms, args.error_rate, args.max_concurrency)
    ceiling = pacer.stats()["throughput_ceiling_rps"]
    print(
        f"pacer on http://{args.host}:{args.port} — latency {args.latency_ms}ms · "
        f"error_rate {args.error_rate} · concurrency {args.max_concurrency or 'unbounded'}"
        + (f" · ceiling {ceiling:.1f} rps" if ceiling else ""),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
