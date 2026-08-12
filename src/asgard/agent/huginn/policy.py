"""압축 정책 — 설정 [compress] 해석과 그 값이 지켜야 할 범위.

사다리의 순서(프룬이 요약보다 먼저)를 여기서 강제한다. 이 모듈은 이 패키지의 어느 모듈도
부르지 않는다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompressPolicy:
    mode: str = "full"  # off | prune | full
    prune_at: float = 0.80
    summary_at: float = 0.90
    protect_first_n: int = 2
    tail_tokens: int = 20_000
    min_recovery_tokens: int = 4_000
    summary_max_tokens: int = 4_000
    vault: bool = True  # T4 — 방출 구간을 보관하고 context_recall로 되짚게 한다
    lessons: bool = True  # ACON — 실패 사례에서 요약 지침을 누적한다
    server_side: bool = False  # T3 — anthropic 서버측 압축 (opt-in, 실패 시 클라이언트측 폴백)
    server_trigger_tokens: int = 0  # 0 = summary_at 비율에서 유도


def policy(root: str) -> CompressPolicy:
    """설정 [compress] 해석 — 프로젝트가 글로벌을 덮는다. 미설정은 전부 기본값."""
    try:
        from ...settings import section

        conf = section("compress", root)
    except Exception:
        conf = {}
    base = CompressPolicy()

    def _f(key: str, default: float, lo: float, hi: float) -> float:
        try:
            return max(lo, min(hi, float(conf.get(key, default))))
        except TypeError, ValueError:
            return default

    def _i(key: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(hi, int(conf.get(key, default))))
        except TypeError, ValueError:
            return default

    def _b(key: str, default: bool) -> bool:
        value = conf.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "on", "yes"}
        return default

    mode = str(conf.get("mode", base.mode)).lower()
    if mode not in {"off", "prune", "full"}:
        mode = base.mode
    prune_at = _f("prune_at", base.prune_at, 0.30, 0.98)
    summary_at = _f("summary_at", base.summary_at, 0.35, 0.99)
    return CompressPolicy(
        mode=mode,
        prune_at=prune_at,
        # 요약이 프룬보다 먼저 터지면 사다리가 뒤집힌다 — 순서를 정책 층에서 강제한다.
        summary_at=max(summary_at, prune_at),
        protect_first_n=_i("protect_first_n", base.protect_first_n, 0, 20),
        tail_tokens=_i("tail_tokens", base.tail_tokens, 2_000, 200_000),
        min_recovery_tokens=_i("min_recovery_tokens", base.min_recovery_tokens, 0, 100_000),
        summary_max_tokens=_i("summary_max_tokens", base.summary_max_tokens, 512, 32_000),
        vault=_b("vault", base.vault),
        lessons=_b("lessons", base.lessons),
        server_side=_b("server_side", base.server_side),
        # API 최소치 50k — 그 아래 값은 요청이 거절되므로 정책 층에서 올린다.
        server_trigger_tokens=_i("server_trigger_tokens", base.server_trigger_tokens, 0, 1_000_000),
    )
