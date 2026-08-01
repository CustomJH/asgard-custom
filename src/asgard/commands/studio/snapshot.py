"""화면이 한 왕복에 받는 것 — 이 자리의 상태 전량.

나눠 주면 왕복마다 어긋난다: 프로바이더는 A를, 카탈로그는 B를 말하는 화면이 된다.
그래서 창이 열릴 때·자리를 옮길 때 한 번에 넣는다.
"""

from __future__ import annotations

import signal  # noqa: E402  (능력 탐지 — 이 자리에서만 쓴다)

from . import dialog
from .boundary import workspace_label
from .state import _SETTING_KEYS
from .tasks import _feed_snapshot, _git_branch, _task_snapshot, load_project_tasks

folder_dialog_available = dialog.folder_dialog_available


def _ticket_summary(root: str) -> dict:
    """메뉴가 드는 티켓 현황. 저장소가 아직 없거나 못 열려도 화면은 뜬다 — 다만 조용히
    '0건'이라고 말하지 않고 `available: False`로 모른다고 말한다."""
    from ...studio import tickets as T

    try:
        return {"available": True, **T.summary(root)}
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}", "open": 0, "started": 0, "total": 0}


_TIER_NOTE = {
    "fast": "짧고 되풀이되는 판정 — 값싸고 빠른 쪽",
    "standard": "보통의 작업 — 기본값으로 두는 자리",
    "high": "어려운 설계와 검증",
    "max": "가장 무거운 판단",
}


def _provider_detail(profile) -> dict:
    """그 프로바이더가 실제로 아는 것만 넣는다 — 검증된 모델 목록·티어 표·연결 요건.

    모델의 성능 설명은 여기서 짓지 않는다. 아스가르드가 가진 사실은 '계열이 어느 티어인가'와
    '무엇이 있어야 연결되는가'뿐이고, 없는 사실을 화면이 지어내면 그 순간 계기가 아니다."""
    from ... import model_tiers

    tiers = model_tiers.tiers_for(profile.name, profile.api_mode)
    models = list(dict.fromkeys([*(profile.fallback_models or ()), profile.default_model or ""]))
    rows = []
    for model in models:
        if not model:
            continue
        tier = model_tiers.family_tier(model)
        rows.append(
            {
                "id": model,
                "tier": tier or "",
                "note": _TIER_NOTE.get(tier or "", ""),
                "default": model == profile.default_model,
            }
        )
    return {
        "name": profile.name,
        "label": profile.display,
        "api_mode": profile.api_mode,
        "default_model": profile.default_model,
        "context_window": getattr(profile, "context_window", 0),
        "key_optional": bool(getattr(profile, "key_optional", False)),
        "env_vars": list(getattr(profile, "env_vars", ()) or ()),
        "signup_hint": getattr(profile, "signup_hint", ""),
        "tiers": tiers,
        "models": rows,
    }


def _provider_state(root: str) -> dict:
    from ...providers import PROVIDERS, resolve

    resolved = resolve(root)
    return {
        "name": resolved.profile.name,
        "label": resolved.profile.display,
        "model": resolved.model,
        "source": resolved.source,
        "ready": not resolved.missing,
        "missing": resolved.missing,
        # 화면이 프로바이더를 바꾸면 그 자리에서 모델 목록이 따라 바뀌어야 한다 — 왕복을 없앤다
        "choices": [_provider_detail(profile) for profile in PROVIDERS.values()],
    }


def _catalog_state(root: str) -> dict:
    from ...skill_registry import plugins, skills

    skill_rows = skills(root)
    plugin_rows = plugins()
    return {
        "skills": [
            {
                "name": row.get("name", ""),
                "description": row.get("description", ""),
                "plugin": row.get("plugin", ""),
                "origin": row.get("origin", ""),
                "invocation": row.get("invocation", ""),
                "enabled": row.get("enabled", True),
            }
            for row in skill_rows
        ],
        "plugins": [
            {
                "name": row.get("name", ""),
                "description": row.get("description", ""),
                "origin": row.get("origin", ""),
                "skills": row.get("skills", []),
            }
            for row in plugin_rows
        ],
    }


# 창이 `desktop`이던 시절 설정 파일에 적힌 이름 — 읽을 때만 새 이름으로 받아 준다.
# 쓰기는 늘 새 이름으로 나가므로, 사용자가 설정을 한 번 저장하면 옛 이름은 저절로 사라진다.
# 이걸 안 두면 "자동 실행"으로 맞춰 둔 창이 개명 직후 조용히 "중요할 때만"으로 되돌아간다 —
# 권한이 말없이 **좁아지는** 쪽이라 사고는 아니지만, 사용자가 시킨 것이 사라지는 것은 같다.
_LEGACY_KEYS = {"ui": {"desktop_permission": "studio_permission"}}


def _pick(name: str, raw: object) -> dict:
    keys = _SETTING_KEYS[name]
    data = dict(raw) if isinstance(raw, dict) else {}
    out = {key: value for key, value in data.items() if key in keys}
    # 옛 이름은 **빈 자리만** 메운다 — 둘 다 적혀 있으면 새 이름이 정본이다
    for old, new in _LEGACY_KEYS.get(name, {}).items():
        if old in data and new in keys and new not in out:
            out[new] = data[old]
    return out


def _safe_sections(data: dict) -> dict:
    return {name: _pick(name, data.get(name)) for name in _SETTING_KEYS}


def settings_state(root: str) -> dict:
    from ...providers import project_section
    from ...settings import load_global, load_project, section

    effective = {name: _pick(name, section(name, root)) for name in _SETTING_KEYS}
    effective["trinity_mode"] = project_section(root, "trinity.mode")
    return {
        "global": _safe_sections(load_global()),
        "project": _safe_sections(load_project(root)),
        "effective": effective,
    }


def snapshot_data(root: str) -> dict:
    from ...memory.policy import inject_enabled, memory_dir
    from .. import studio_store
    from ..role import role_model_state

    load_project_tasks(root)  # 창을 열자마자 그 작업 공간의 이력이 보여야 한다
    catalog = _catalog_state(root)
    scratch = studio_store.is_scratch(root)
    return {
        "project": {
            "name": workspace_label(root),
            "root": root,
            "local": True,
            # 이 자리가 프로젝트인지 개인 작업 공간인지 — 창의 문구와 안내가 여기서 갈린다
            "scratch": scratch,
            "is_project": studio_store.looks_like_project(root),
            # 저장소가 아니면 빈 문자열 — 화면은 없는 값을 지어내지 않고 그 칩을 안 세운다
            "branch": _git_branch(root),
        },
        "projects": studio_store.list_projects(root),
        # 프로젝트를 건너 보는 대화 목록. 창은 폴더가 아니라 사람의 것이라, 어느 자리를 열고
        # 있든 "내가 최근에 뭘 하고 있었지"에 답할 수 있어야 한다.
        "feed": _feed_snapshot(root),
        "provider": _provider_state(root),
        "memory": {"directory": memory_dir(), "inject": inject_enabled()},
        "settings": settings_state(root),
        "roles": role_model_state(root),
        "catalog": {
            "skills": len(catalog["skills"]),
            "plugins": len(catalog["plugins"]),
        },
        "capabilities": {
            "pause": hasattr(signal, "SIGSTOP") and hasattr(signal, "SIGCONT"),
            # 시스템 폴더 고르기가 있는 기계인가 — 없으면 화면이 그 단추를 아예 안 세운다
            "folder_dialog": folder_dialog_available(),
        },
        "tickets": _ticket_summary(root),
        "tasks": _task_snapshot(root),
    }
