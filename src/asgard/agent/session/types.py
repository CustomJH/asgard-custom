"""세션 턴의 결과·예외·툴콜 형상 — 이 패키지의 어느 모듈도 부르지 않는 바닥."""

from __future__ import annotations

from dataclasses import dataclass, field


class TurnCancelled(Exception):
    """사용자 취소 — 세션 결과가 아니라 턴 전체의 일급 결과.

    재시도·placement 폴백·역할 전이·디스패치 편입·wave 진행·메모리 보존을 전부 멈춘다.
    취소를 이 예외로 승격하지 않으면 stop_reason="cancelled"가 평범한 결과로 흘러
    Trinity가 계속 진행하거나 취소된 산출이 편입된다. (세션 계층 정의 — heimdall
    하위 협력자(dispatch/waves)가 core 순환 임포트 없이 공유한다.)"""


class ProviderRetriesExhausted(RuntimeError):
    """Transport-local retries are spent; the upper layer may fallback but must not repeat them."""

    _asgard_retries_exhausted = True


@dataclass
class SessionResult:
    text: str
    stop_reason: str
    commands: list[dict] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    tokens: int = 0  # 이 세션 누적 토큰 (매 iteration input+output 합산 = 지출량) — status line 사용량
    context_tokens: int = 0  # 마지막 API 호출의 전체 프롬프트+출력 = 현재 컨텍스트 크기 — 창 % 는 이걸로
    # (tokens는 iteration 마다 전체 프롬프트를 재합산하므로 컨텍스트 창 대비 % 가 100을 넘는다)
    # 프롬프트 캐시 계측 (anthropic 트랜스포트) — read는 ~0.1×, write는 ~1.25× 과금
    cache_read_tokens: int = 0  # 캐시에서 읽은 누적 입력 토큰
    cache_write_tokens: int = 0  # 캐시에 쓴 누적 입력 토큰
    uncached_input_tokens: int = 0  # 정가로 처리된 누적 입력 토큰 — 적중률 분모용


# 창 미상 프로바이더의 프룬 폴백 상한 — 주류 창(≥128k) 기준 보수값. 더 작은 모델은
# config [provider] context_window로 실제 창을 알려야 정확히 보호된다.
_FALLBACK_CONTEXT_WINDOW = 128_000


class _Call:
    """트랜스포트 무관 툴콜 — (id, name, input)."""

    def __init__(self, cid, name, inp):
        self.id, self.name, self.input = cid, name, inp
