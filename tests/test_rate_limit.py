#!/usr/bin/env python3
"""RPM 스로틀 결정론 슬라이스 — 슬라이딩 윈도·전역 공유 레지스트리·429 Retry-After 해석.

NVIDIA NIM 무료 티어(API 키 기준 전역 ~40 RPM) 준수가 동기 — 리미터는 API 무호출로
가짜 시계·잠으로 검증한다. resolve() 의 config [provider] rpm 해석도 여기서 다룬다.

실행: uv run pytest tests/test_rate_limit.py
"""

import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from asgard.agent import rate_limit
from asgard.agent.heimdall.classify import classify_api_error
from asgard.agent.rate_limit import RpmLimiter, effective_rpm, limiter_for, retry_after_seconds
from asgard.agent.session import ProviderRetriesExhausted
from asgard.providers import PROVIDERS, ResolvedProvider


class FakeClock:
    """단조 가짜 시계 — sleep 이 시간을 전진시켜 실제 대기 없이 윈도를 검증한다."""

    def __init__(self):
        self.now = 1000.0

    def clock(self):
        return self.now

    def sleep(self, s):
        self.now += s


def _nvidia_rp(rpm: int = 0) -> ResolvedProvider:
    p = PROVIDERS["nvidia"]
    return ResolvedProvider(profile=p, model=p.default_model, base_url=p.base_url, api_key="k", rpm=rpm)


class TestRpmLimiter(unittest.TestCase):
    def test_burst_within_limit_never_waits(self):
        fc = FakeClock()
        lim = RpmLimiter(3, clock=fc.clock, sleep=fc.sleep)
        self.assertEqual([lim.acquire() for _ in range(3)], [0.0, 0.0, 0.0])

    def test_excess_request_waits_until_window_frees(self):
        fc = FakeClock()
        lim = RpmLimiter(2, clock=fc.clock, sleep=fc.sleep)
        lim.acquire()
        fc.now += 10
        lim.acquire()
        t0 = fc.now
        waited = lim.acquire()  # 첫 스탬프가 60s 창을 벗어날 때까지 — 약 50s
        self.assertGreaterEqual(fc.now - t0, 50.0)
        self.assertLess(fc.now - t0, 52.0)  # 과대 대기 금지 (윈도 경계 + 반응성 스텝 이내)
        self.assertGreaterEqual(waited, 50.0)

    def test_window_slides_and_requests_resume_free(self):
        fc = FakeClock()
        lim = RpmLimiter(1, clock=fc.clock, sleep=fc.sleep)
        lim.acquire()
        fc.now += 61
        self.assertEqual(lim.acquire(), 0.0)

    def test_cancel_event_returns_without_consuming_slot(self):
        fc = FakeClock()
        lim = RpmLimiter(1, clock=fc.clock, sleep=fc.sleep)
        lim.acquire()
        cancel = threading.Event()
        cancel.set()
        lim.acquire(cancel)  # 즉시 반환 — 슬롯 계수 금지 (취소 경로)
        self.assertEqual(len(lim._stamps), 1)


class TestRegistry(unittest.TestCase):
    def setUp(self):
        rate_limit._limiters.clear()

    def test_nvidia_profile_defaults_to_40_rpm(self):
        self.assertEqual(PROVIDERS["nvidia"].default_rpm, 40)
        self.assertEqual(effective_rpm(_nvidia_rp()), 40)

    def test_config_override_raises_or_disables(self):
        self.assertEqual(effective_rpm(_nvidia_rp(rpm=200)), 200)  # 승급 티어
        self.assertEqual(effective_rpm(_nvidia_rp(rpm=-1)), 0)  # 명시 해제
        self.assertIsNone(limiter_for(_nvidia_rp(rpm=-1)))

    def test_limiter_shared_across_sessions_for_same_key(self):
        a, b = limiter_for(_nvidia_rp()), limiter_for(_nvidia_rp())
        self.assertIs(a, b)  # Trinity 역할·편대가 같은 API 키 40 RPM 을 나눠 쓴다

    def test_unlimited_provider_has_no_limiter(self):
        p = PROVIDERS["anthropic"]
        rp = ResolvedProvider(profile=p, model=p.default_model, api_key="k")
        self.assertIsNone(limiter_for(rp))

    def test_rpm_change_replaces_limiter(self):
        a = limiter_for(_nvidia_rp())
        b = limiter_for(_nvidia_rp(rpm=200))
        self.assertIsNot(a, b)
        assert b is not None
        self.assertEqual(b.rpm, 200)


class _Resp:
    def __init__(self, headers):
        self.headers = headers


class _RateErr(Exception):
    def __init__(self, status=429, headers=None):
        self.status_code = status
        self.response = _Resp(headers or {})


class TestRetryAfter(unittest.TestCase):
    def test_non_429_returns_none(self):
        self.assertIsNone(retry_after_seconds(_RateErr(status=500)))
        self.assertIsNone(retry_after_seconds(RuntimeError("boom")))

    def test_retry_after_header_respected_and_clamped(self):
        self.assertEqual(retry_after_seconds(_RateErr(headers={"retry-after": "7"})), 7.0)
        self.assertEqual(retry_after_seconds(_RateErr(headers={"Retry-After": "999"})), 120.0)

    def test_fallback_exponential_backoff_capped(self):
        self.assertEqual(retry_after_seconds(_RateErr(), 0), 2.0)
        self.assertEqual(retry_after_seconds(_RateErr(), 3), 16.0)
        self.assertEqual(retry_after_seconds(_RateErr(), 10), 60.0)

    def test_unparseable_header_falls_back(self):
        self.assertEqual(retry_after_seconds(_RateErr(headers={"retry-after": "soon"}), 1), 4.0)


class _Completions:
    def __init__(self, owner, fails):
        self._owner, self._fails = owner, fails

    def create(self, **_kw):
        self._owner.calls += 1
        if self._owner.calls <= self._fails:
            raise _RateErr(headers={"retry-after": "0"})
        from types import SimpleNamespace

        delta = SimpleNamespace(content="hi", tool_calls=None)
        chunk = SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason="stop", delta=delta)])
        return iter([chunk])


class _FlakyClient:
    """create 가 fails 회 429 를 던진 뒤 단일 텍스트 chunk 스트림을 반환한다."""

    def __init__(self, fails: int):
        from types import SimpleNamespace

        self.calls = 0
        self.chat = SimpleNamespace(completions=_Completions(self, fails))


class TestRunOpenai429(unittest.TestCase):
    def setUp(self):
        rate_limit._limiters.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_429_then_success_retries_within_iteration(self):
        from asgard.agent.session import AgentSession

        client = _FlakyClient(fails=1)
        s = AgentSession(client, _nvidia_rp(), self.root, "sys")
        r = s._run_openai("hello")
        self.assertEqual(r.stop_reason, "end_turn")
        self.assertEqual(r.text, "hi")
        self.assertEqual(client.calls, 2)

    def test_429_exhaustion_reraises_for_upper_retry_layer(self):
        from asgard.agent.session import AgentSession

        client = _FlakyClient(fails=99)
        s = AgentSession(client, _nvidia_rp(), self.root, "sys")
        with self.assertRaises(ProviderRetriesExhausted) as raised:
            s._run_openai("hello")
        self.assertEqual(client.calls, 4)  # transport에서 소진 — Heimdall은 동일 provider 재반복 금지
        self.assertIsInstance(raised.exception.__cause__, _RateErr)
        self.assertEqual(classify_api_error(raised.exception), "fatal")


class TestResolveRpm(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _write_project(self, provider_conf: dict):
        from asgard.settings import PROJECT_FILE

        d = os.path.join(self.root, ".asgard")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, PROJECT_FILE), "w").write(json.dumps({"provider": provider_conf}))

    def _resolve(self):
        from asgard.providers import resolve

        with (
            mock.patch("asgard.settings.load_global", return_value={}),
            mock.patch("asgard.providers.load_credentials", return_value={}),
        ):
            return resolve(self.root)

    def test_rpm_unspecified_falls_back_to_profile_default(self):
        self._write_project({"name": "nvidia"})
        rp = self._resolve()
        self.assertEqual(rp.rpm, 0)
        self.assertEqual(effective_rpm(rp), 40)

    def test_rpm_from_project_config(self):
        self._write_project({"name": "nvidia", "rpm": 20})
        self.assertEqual(effective_rpm(self._resolve()), 20)

    def test_rpm_explicit_disable(self):
        self._write_project({"name": "nvidia", "rpm": -1})
        self.assertEqual(effective_rpm(self._resolve()), 0)

    def test_rpm_broken_value_treated_as_unspecified(self):
        self._write_project({"name": "nvidia", "rpm": "fast"})
        self.assertEqual(effective_rpm(self._resolve()), 40)


if __name__ == "__main__":
    unittest.main()
