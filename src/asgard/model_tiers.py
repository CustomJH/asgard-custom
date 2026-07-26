"""정책 티어 → 모델 해석 — 세대가 올라가도 표를 손으로 고치지 않는다.

티어(fast/standard/high/max)는 **모델 계열**의 이름이다: haiku·sonnet·opus·fable. 고정해야 할
사실은 그 대응뿐이고, 어떤 세대가 최신인지는 provider 가 이미 안다. 이 모듈은 그 사실을 그대로
읽어 쓴다 — 정본 우선순위:

  ① claude_cli(모드 = 로컬 claude CLI) → **계열 별칭 그대로**. CLI 가 최신 세대로 해석한다
     (26-07-26 확인: opus→claude-opus-5, sonnet→claude-sonnet-5, haiku→claude-haiku-4-5,
     fable→claude-fable-5). 별칭을 쓰면 세대 교체에 이 파일이 개입할 일이 없다.
  ② anthropic(모드 = API 키) → `asgard doctor`/`sync` 가 갱신해 둔 캐시(모델 카탈로그의 계열별
     최신판). 런타임은 네트워크를 타지 않는다 — 매 턴 카탈로그를 묻는 것은 지연·실패 표면이다.
  ③ 그 외 → 커레이션 하한(CURATED). 카탈로그도 캐시도 없을 때만 쓰인다.

티어 매핑이 없는 provider(openai·nvidia·ollama…)는 빈 표를 돌려준다 — 모델 스왑을 하지 않는
종전 동작 그대로다 (커스텀 ID 존중).

26-07-26 실측 동기: 표가 `high → claude-opus-4-8` 로 박혀 있어 opus-5 세션이 역할 턴마다 조용히
이전 세대로 내려갔다. 계열 이름만 남기면 그 종류의 드리프트가 구조적으로 생기지 않는다.
"""

from __future__ import annotations

import json
import os
import re
import time

TIERS = ("fast", "standard", "high", "max")
TIER_UP = {"fast": "standard", "standard": "high", "high": "max", "max": "max"}
# 티어 = 계열. 이 대응만 사실이고 세대는 해석기가 채운다.
FAMILY = {"fast": "haiku", "standard": "sonnet", "high": "opus", "max": "fable"}
# 커레이션 하한 — 카탈로그·캐시 부재 시에만. 정본이 아니라 폴백이다.
CURATED = {
    "fast": "claude-haiku-4-5-20251001",
    "standard": "claude-sonnet-5",
    "high": "claude-opus-5",
    "max": "claude-fable-5",
}
CACHE_TTL = 12 * 3600
_ANTHROPIC_CATALOG = "https://api.anthropic.com/v1/models?limit=100"
_ANTHROPIC_VERSION = "2023-06-01"
_TIERED_MODES = ("anthropic", "claude_cli")


def cache_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".asgard", "state", "model-tiers.json")


def family_tier(model: str) -> str | None:
    """모델 ID/별칭 → 티어. 알려지지 않은 계열은 None (스왑 대상 아님)."""
    name = (model or "").lower()
    for tier in reversed(TIERS):  # max→fast 순 — 'fable' 이 'sonnet' 보다 먼저 걸리게
        if FAMILY[tier] in name:
            return tier
    return None


def generation(model: str) -> tuple[int, ...]:
    """모델 ID 의 세대 키 — 뒤에 붙은 숫자 묶음을 그대로 비교한다.
    `claude-opus-5` (5,) > `claude-opus-4-8` (4,8) > `claude-opus-4` (4,)."""
    return tuple(int(part) for part in re.findall(r"\d+", model or ""))


def newest(models, tier: str) -> str | None:
    """카탈로그에서 그 계열의 최신 세대 ID."""
    marker = FAMILY[tier]
    candidates = [m for m in models if marker in (m or "").lower()]
    return max(candidates, key=generation) if candidates else None


def _load_cache(provider: str) -> dict | None:
    try:
        with open(cache_path(), encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    row = (payload or {}).get(provider)
    if not isinstance(row, dict):
        return None
    if time.time() - float(row.get("at") or 0) > CACHE_TTL:
        return None
    table = row.get("tiers")
    if not isinstance(table, dict) or not all(isinstance(table.get(t), str) for t in TIERS):
        return None
    return {t: table[t] for t in TIERS}


def _save_cache(provider: str, table: dict) -> None:
    path = cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle) or {}
        payload[provider] = {"at": int(time.time()), "tiers": table}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
    except Exception:
        pass  # 캐시는 편의 — 저장 실패가 해석을 막지 않는다


def tiers_for(profile_name: str, api_mode: str) -> dict[str, str]:
    """provider(모드)별 티어 표. 티어 개념이 없는 모드는 빈 표."""
    if api_mode == "claude_cli":
        return dict(FAMILY)  # 별칭 = 계열의 최신 세대 (CLI 가 해석)
    if api_mode != "anthropic":
        return {}
    return _load_cache(profile_name) or dict(CURATED)


def catalog_models(api_key: str, timeout: float = 6.0) -> list[str]:
    """Anthropic 모델 카탈로그 — 실패는 빈 목록 (호출측이 커레이션으로 내려간다)."""
    import urllib.request as request

    req = request.Request(
        _ANTHROPIC_CATALOG,
        headers={"x-api-key": api_key, "anthropic-version": _ANTHROPIC_VERSION, "accept": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 — 고정 https 엔드포인트
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            return []
        payload = json.loads(raw.decode())
    except Exception:
        return []
    items = payload.get("data") if isinstance(payload, dict) else payload
    return [str(item.get("id")) for item in (items or []) if isinstance(item, dict) and item.get("id")]


def refresh(profile_name: str, api_mode: str, api_key: str = "") -> tuple[dict[str, str], str]:
    """티어 표를 갱신해 캐시에 적는다 — doctor/sync 표면에서만 호출 (런타임은 네트워크 무개입).
    반환 = (표, 출처). 출처는 alias|catalog|cache|curated."""
    if api_mode == "claude_cli":
        return dict(FAMILY), "alias"
    if api_mode != "anthropic":
        return {}, "n/a"
    if api_key:
        models = catalog_models(api_key)
        table = {tier: newest(models, tier) for tier in TIERS}
        if all(table.values()):
            resolved = {tier: str(table[tier]) for tier in TIERS}
            _save_cache(profile_name, resolved)
            return resolved, "catalog"
    cached = _load_cache(profile_name)
    return (cached, "cache") if cached else (dict(CURATED), "curated")
