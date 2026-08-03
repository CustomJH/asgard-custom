"""설정된 모델 엔진이 지금 실제로 닿는지 재고, 짧게 캐시한다."""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass

from . import providers

CACHE_REL = os.path.join(".asgard", "state", "engines.json")
CACHE_TTL = 900.0


@dataclass(frozen=True)
class Engine:
    name: str
    display: str
    configured: bool
    reachable: bool
    detail: str
    models: tuple[str, ...]
    checked: float


def _cache_path(root: str) -> str:
    return os.path.join(root, CACHE_REL)


def _decode(row: object) -> Engine:
    if not isinstance(row, dict):
        raise ValueError("invalid engine cache row")
    name = row.get("name")
    display = row.get("display")
    configured = row.get("configured")
    reachable = row.get("reachable")
    detail = row.get("detail")
    models = row.get("models")
    checked = row.get("checked")
    if (
        not isinstance(name, str)
        or not isinstance(display, str)
        or not isinstance(configured, bool)
        or not isinstance(reachable, bool)
        or not isinstance(detail, str)
        or not isinstance(models, list)
        or not all(isinstance(model, str) for model in models)
        or isinstance(checked, bool)
        or not isinstance(checked, int | float)
    ):
        raise ValueError("invalid engine cache row")
    return Engine(
        name=name,
        display=display,
        configured=configured,
        reachable=reachable,
        detail=detail,
        models=tuple(str(model) for model in models),
        checked=float(checked),
    )


def cached(root: str) -> list[Engine]:
    """마지막 계량값만 읽는다. 엔진이나 네트워크에는 절대 묻지 않는다."""
    try:
        with open(_cache_path(root), encoding="utf-8") as handle:
            rows = json.load(handle).get("engines")
        if not isinstance(rows, list):
            return []
        return [_decode(row) for row in rows]
    except Exception:
        return []


def _save(root: str, rows: list[Engine]) -> None:
    try:
        path = _cache_path(root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"engines": [asdict(row) for row in rows]}, handle, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 캐시는 편의다. 저장 실패가 준비 상태 판정을 막으면 안 된다.


def _probe_one(root: str, name: str, timeout: float, checked: float) -> Engine:
    profile = providers.PROVIDERS.get(name)
    display = profile.display if profile else name
    try:
        resolved = providers.resolve(root, provider=name)
    except Exception as exc:
        return Engine(name, display, False, False, f"설정을 읽지 못했어요 — {type(exc).__name__}: {exc}", (), checked)

    display = resolved.profile.display if profile else display
    configured = not resolved.missing
    if not configured:
        return Engine(name, display, False, False, "설정되지 않았어요 — " + "; ".join(resolved.missing), (), checked)

    try:
        if resolved.profile.api_mode == "claude_cli":
            executable = shutil.which("claude")
            return Engine(
                name,
                display,
                True,
                bool(executable),
                f"claude CLI를 PATH에서 찾았어요 — {executable}"
                if executable
                else "claude CLI를 PATH에서 찾지 못했어요",
                (),
                checked,
            )
        if resolved.profile.api_mode == "codex_responses":
            from .openai_codex import login_status

            reachable, detail = login_status()
            return Engine(
                name,
                display,
                True,
                reachable,
                f"ChatGPT OAuth로 닿아요 — {detail}" if reachable else f"ChatGPT OAuth에 닿지 않아요 — {detail}",
                (),
                checked,
            )

        if resolved.profile.api_mode == "anthropic":
            from .model_tiers import catalog_models

            models = catalog_models(resolved.api_key, timeout=timeout)
            reachable = bool(models)
            detail = (
                f"모델 카탈로그에 닿았어요 — {len(models)}개 모델"
                if reachable
                else "모델 카탈로그에 닿지 않았어요 — 응답을 받지 못했어요"
            )
            return Engine(name, display, True, reachable, detail, tuple(models), checked)

        fallback: list[str] = []
        models = providers.provider_models(resolved, timeout=timeout, on_fallback=fallback.append)
        reachable = bool(models) and not fallback
        detail = (
            f"모델 카탈로그에 닿았어요 — {len(models)}개 모델"
            if reachable
            else "모델 카탈로그에 닿지 않았어요 — " + (fallback[-1] if fallback else "확인된 모델이 없어요")
        )
        return Engine(name, display, True, reachable, detail, tuple(models) if reachable else (), checked)
    except Exception as exc:
        return Engine(
            name, display, True, False, f"준비 상태를 확인하지 못했어요 — {type(exc).__name__}: {exc}", (), checked
        )


def probe(
    root: str,
    names: tuple[str, ...] = (),
    timeout: float = 6.0,
    force: bool = False,
    now: float | None = None,
) -> list[Engine]:
    """설정된 엔진의 준비 상태. ``force``가 아니면 15분 캐시를 쓴다."""
    checked = time.time() if now is None else now
    previous = {row.name: row for row in cached(root)}
    targets = tuple(dict.fromkeys(names or tuple(providers.PROVIDERS)))
    rows: list[Engine] = []
    changed = False
    for name in targets:
        row = previous.get(name)
        if force or row is None or checked - row.checked > CACHE_TTL:
            row = _probe_one(root, name, timeout, checked)
            previous[name] = row
            changed = True
        rows.append(row)
    if changed:
        _save(root, list(previous.values()))
    return rows


def ready(root: str, now: float | None = None) -> list[Engine]:
    """지금 닿는 엔진만 자동 배치 후보로 돌려준다."""
    return [engine for engine in probe(root, now=now) if engine.reachable]
