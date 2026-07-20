"""RPM 스로틀 — provider 요청 속도 상한.

NVIDIA NIM 무료 티어(API 키 기준 전역 ~40 RPM, 모델 합산) 같은 상한을 클라이언트가
선제 준수한다. 리미터는 프로세스 전역 공유 — Trinity 역할·디스패치 편대가 같은 키를
나눠 쓰므로 (provider, base_url) 단위 하나의 슬라이딩 윈도가 모든 호출을 계수한다.

상한 해석은 providers.resolve() 몫 (config [provider] rpm > 프로파일 default_rpm),
여기는 대기·계수만 소유한다. 429 는 서버가 판정한 초과 — retry_after_seconds() 가
Retry-After 헤더를 존중해 재시도 간격을 정한다.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RpmLimiter:
    """슬라이딩 윈도 카운터 — 최근 window 초 안의 요청이 rpm 미만일 때만 통과."""

    def __init__(self, rpm: int, window: float = 60.0, clock=time.monotonic, sleep=time.sleep):
        self.rpm = max(1, int(rpm))
        self.window = window
        self._clock, self._sleep = clock, sleep
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self, cancel: threading.Event | None = None) -> float:
        """슬롯이 빌 때까지 대기 후 계수한다. 반환 = 실제 대기 초.
        cancel 이 서면 계수 없이 즉시 반환 — 호출측이 취소 경로로 빠진다."""
        waited = 0.0
        while True:
            if cancel is not None and cancel.is_set():
                return waited
            with self._lock:
                now = self._clock()
                while self._stamps and now - self._stamps[0] >= self.window:
                    self._stamps.popleft()
                if len(self._stamps) < self.rpm:
                    self._stamps.append(now)
                    return waited
                delay = self.window - (now - self._stamps[0])
            step = min(max(delay, 0.0) + 0.01, 0.5)  # 짧게 쪼개 잠 — 취소 반응성
            self._sleep(step)
            waited += step


_limiters: dict[tuple[str, str], RpmLimiter] = {}
_registry_lock = threading.Lock()


def effective_rpm(rp) -> int:
    """해석된 상한 — config rpm(양수) > 프로파일 default_rpm. 음수 = 명시 무제한, 0 = 미지정."""
    rpm = int(getattr(rp, "rpm", 0) or 0)
    if rpm < 0:
        return 0
    return rpm or int(getattr(rp.profile, "default_rpm", 0) or 0)


def limiter_for(rp) -> RpmLimiter | None:
    """연결의 공유 리미터 — 프로세스 전역, (provider, base_url) 단위 단일 윈도. 무상한 = None."""
    rpm = effective_rpm(rp)
    if rpm <= 0:
        return None
    key = (rp.profile.name, rp.base_url or rp.profile.base_url)
    with _registry_lock:
        lim = _limiters.get(key)
        if lim is None or lim.rpm != rpm:  # config 변경 → 새 윈도로 교체
            lim = _limiters[key] = RpmLimiter(rpm)
        return lim


def throttle(rp, cancel: threading.Event | None = None) -> float:
    """API 호출 직전 훅 — 상한 provider 만 대기, 나머지는 no-op. 반환 = 대기 초."""
    lim = limiter_for(rp)
    return lim.acquire(cancel) if lim is not None else 0.0


def retry_after_seconds(e: Exception, attempt: int = 0) -> float | None:
    """429 판정 + 대기 초 — Retry-After 헤더 존중(0~120s 클램프), 없으면 지수 백오프(≤60s).
    429 가 아니면 None — 호출측은 기존 오류 경로를 유지한다."""
    if getattr(e, "status_code", None) != 429:
        return None
    headers = getattr(getattr(e, "response", None), "headers", None)
    raw = ""
    if headers is not None:
        try:
            raw = str(headers.get("retry-after") or headers.get("Retry-After") or "")
        except Exception:
            raw = ""
    try:
        if raw:
            return min(max(float(raw), 0.0), 120.0)
    except ValueError:
        pass
    return min(2.0 * (2**attempt), 60.0)
