"""개인 메모리를 관리하는 provider — 정본 하나의 해석점.

개인 메모리의 손질(노른)·패턴 학습·회고 합성은 전부 LLM 호출이다. 기본값은 **지금 쓰는
메인 provider** 다 — 오딘이 고른 모델이 오딘의 기억을 본다. 그게 이 계층의 규칙이고,
따로 고를 이유가 있을 때만 (`[memory].manager`) 갈아끼운다: 개인 기억을 원격 대형 모델에
보내고 싶지 않아 로컬 ollama 로 돌리는 경우, 반대로 메인이 로컬이라 손질 품질이 부족한 경우.

주입(읽기)과 관리(쓰기)는 다른 문이다. inject_allowed 는 "이 provider 에게 기억을 보여줘도
되는가"를 판정하고, 여기는 "누가 기억을 손질하는가"를 정한다. 관리자를 따로 지정하면
그 provider 도 기억을 보게 되므로, describe() 가 두 판정을 한 화면에 같이 보고한다.

호출측 계약: complete() 는 provider 미충족을 ManagerUnavailable 로 올린다. 배경 지능은
fail-open 이 원칙이다 — 관리자가 없다고 기억 자체가 멈추면 안 된다 (읽기·저장은 무LLM).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from .policy import _memory_settings, inject_allowed, inject_enabled

if TYPE_CHECKING:  # pragma: no cover - 타입 전용
    pass

MANAGER_ENV = "ASGARD_MEMORY_MANAGER"  # 세션 override — "provider" 또는 "provider:model"
MAX_TOKENS = 3000


class ManagerUnavailable(RuntimeError):
    """개인 메모리를 손질할 provider 가 없다 — 호출측이 조용히 물러날 신호."""


def _parse_spec(spec: str) -> tuple[str, str]:
    """ "provider[:model]" 해석. 모델 id 안의 콜론(ollama `gemma4:12b`)은 첫 구분자만 자른다."""
    provider, separator, model = spec.strip().partition(":")
    return provider.strip(), (model.strip() if separator else "")


def manager_config() -> dict:
    """[memory].manager — {"provider", "model"}. 미설정이면 빈 dict (= 메인 provider 사용)."""
    env = (os.environ.get(MANAGER_ENV) or "").strip()
    if env:
        provider, model = _parse_spec(env)
        return {"provider": provider, "model": model, "source": "env"} if provider else {}
    raw = _memory_settings().get("manager")
    if isinstance(raw, str):
        provider, model = _parse_spec(raw)
        return {"provider": provider, "model": model, "source": "config"} if provider else {}
    if isinstance(raw, dict):
        provider = str(raw.get("provider") or "").strip()
        if provider:
            return {"provider": provider, "model": str(raw.get("model") or "").strip(), "source": "config"}
    return {}


def save_manager(spec: str) -> dict:
    """관리 provider 를 전역 설정에 기록한다. 빈 문자열이면 해제 (= 메인 provider 로 복귀)."""
    from ..settings import load_global, save_global

    configured = dict(load_global().get("memory") or {})
    provider, model = _parse_spec(spec)
    if not provider:
        configured.pop("manager", None)
        save_global("memory", configured)
        return {}
    from ..providers import PROVIDERS

    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider} (choose one of {', '.join(sorted(PROVIDERS))})")
    configured["manager"] = {"provider": provider, "model": model}
    save_global("memory", configured)
    return {"provider": provider, "model": model, "source": "config"}


def resolve_manager(root: str | None = None) -> tuple[Any, str]:
    """관리 provider 해석. 반환 = (ResolvedProvider, source). source ∈ main|config|env."""
    from ..providers import resolve

    root = root or os.getcwd()
    configured = manager_config()
    if not configured:
        return resolve(root), "main"
    return (
        resolve(root, provider=configured["provider"], model=configured["model"] or None),
        str(configured.get("source") or "config"),
    )


def available(root: str | None = None) -> bool:
    """관리 호출이 지금 가능한지 — 예외 없이 판정만 (넛지·doctor 표면용)."""
    try:
        resolved, _ = resolve_manager(root)
        return not resolved.missing
    except Exception:
        return False


def complete(root: str, system: str, user: str, max_tokens: int = MAX_TOKENS) -> str:
    """관리 provider 로 단발 완성 1회. 미충족은 ManagerUnavailable."""
    resolved, source = resolve_manager(root)
    if resolved.missing:
        raise ManagerUnavailable(
            f"personal memory manager ({resolved.profile.name}, source={source}) is not usable: "
            + "; ".join(resolved.missing)
        )
    if source == "main":
        from ..agent.oneshot import complete_once

        return complete_once(root, system, user, max_tokens=max_tokens)
    from ..agent.oneshot import complete_with

    return complete_with(resolved, root, system, user, max_tokens=max_tokens)


def describe(root: str | None = None) -> dict:
    """관리·주입 두 판정을 한 화면으로. doctor/`asgard memory provider` 표면이 쓴다."""
    root = root or os.getcwd()
    configured = manager_config()
    row: dict = {
        "configured": bool(configured),
        "source": str(configured.get("source") or "main"),
        "inject_enabled": inject_enabled(),
    }
    try:
        resolved, source = resolve_manager(root)
        row.update(
            {
                "source": source,
                "provider": resolved.profile.name,
                "model": resolved.model,
                "ready": not resolved.missing,
                "missing": list(resolved.missing),
                # 관리자는 기억 본문을 프롬프트로 받는다 — 주입 게이트와 같은 잣대로 보고한다
                "inject_allowed": inject_allowed(resolved.profile.name, resolved.source),
                "provider_source": resolved.source,
            }
        )
    except Exception as exc:  # 해석 실패가 진단을 막지 않는다
        row.update({"provider": "", "model": "", "ready": False, "missing": [f"{type(exc).__name__}: {exc}"]})
    if row["configured"]:
        try:
            from ..providers import resolve

            main = resolve(root)
            row["main_provider"] = main.profile.name
            row["main_model"] = main.model
        except Exception:
            row["main_provider"] = ""
    return row
