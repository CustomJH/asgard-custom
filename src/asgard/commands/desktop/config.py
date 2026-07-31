"""설정·스킬·역할 쓰기 — 창에서 고른 것을 디스크의 정본으로.

읽기는 `snapshot` 이 진다. 여기는 **쓰는 쪽**이라 검사가 두껍다: 모르는 칸은 버리고,
화면이 안 보여 준 값은 지우지 않고 그대로 얹는다(안 보여 준 것을 지우면 창이 설정을 삼킨다).
"""

from __future__ import annotations

from .. import loopback
from . import snapshot, state

_json_body = loopback.json_body
_SETTING_KEYS = state._SETTING_KEYS


_PROVIDER_UNSHOWN = ("base_url", "api_key_env", "context_window", "rpm")


def _carry_unshown_provider_keys(scope: str, root: str, values: object) -> object:
    """섹션 저장은 **교체** 계약이다 — 보내지 않은 키는 사라진다. 창은 엔진 이름과 모델만
    보여 주므로, 모델 하나 바꾸는 동작이 손으로 적어 둔 base_url·rpm 을 조용히 지워 왔다.

    다만 엔진 자체가 바뀌면 그 키들은 **옛 엔진의 것**이라 함께 버린다 — providers.resolve 가
    이름이 달라진 config 를 통째로 버리는 것과 같은 규율이다.

    받는 것이 `dict` 라고 적혀 있었지만 실제로는 무엇이든 받아 넘긴다(검사는 아래
    `_validate_settings` 가 한다). 형이 거짓이면 검사기가 매번 손을 든다 — 계약을 사실에 맞춘다."""
    from ...settings import load_global, load_project

    if not isinstance(values, dict):
        return values
    stored = dict((load_global() if scope == "global" else load_project(root)).get("provider") or {})
    if stored.get("name") and stored["name"] != values.get("name"):
        return values
    carried = dict(values)
    for key in _PROVIDER_UNSHOWN:
        if key not in carried and stored.get(key) not in (None, ""):
            carried[key] = stored[key]
    return carried


def _validate_settings(section_name: str, values: object) -> dict:
    from ...providers import PROVIDERS, normalize_model_id

    if section_name not in _SETTING_KEYS or not isinstance(values, dict):
        raise ValueError("unknown settings section")
    unknown = set(values).difference(_SETTING_KEYS[section_name])
    if unknown:
        raise ValueError(f"unknown settings keys: {', '.join(sorted(unknown))}")
    clean = dict(values)
    if section_name == "provider":
        if clean.get("name") and clean["name"] not in PROVIDERS:
            raise ValueError("unknown provider")
        if clean.get("model"):
            clean["model"] = normalize_model_id(str(clean["model"]))
            if not clean["model"]:
                raise ValueError("invalid model")
        for key in ("context_window", "rpm"):
            if key in clean and clean[key] not in (None, ""):
                clean[key] = int(clean[key])
    elif section_name == "ui":
        if clean.get("theme") not in (None, "system", "light", "dark"):
            raise ValueError("theme must be system, light, or dark")
        if clean.get("density") not in (None, "comfortable", "compact"):
            raise ValueError("density must be comfortable or compact")
        if clean.get("desktop_permission") not in (None, "manual", "important", "auto"):
            raise ValueError("invalid permission mode")
    elif section_name == "memory":
        if "inject" in clean:
            clean["inject"] = "on" if str(clean["inject"]).lower() in {"on", "true", "1"} else "off"
        if "providers" in clean and not isinstance(clean["providers"], list):
            raise ValueError("memory providers must be a list")
        if "auto_retain_turns" in clean:
            clean["auto_retain_turns"] = bool(clean["auto_retain_turns"])
        if "autosave" in clean:
            clean["autosave"] = bool(clean["autosave"])
    elif section_name == "lagom" and clean.get("mode") not in (None, "off", "lite", "full"):
        raise ValueError("lagom mode must be off, lite, or full")
    elif section_name == "bridge":
        clean = {key: bool(value) for key, value in clean.items()}
    return {key: value for key, value in clean.items() if value is not None and value != ""}


def save_settings(payload: dict, root: str) -> tuple[int, str, bytes]:
    from ...settings import save_global, save_project

    scope = str(payload.get("scope") or "project")
    section_name = str(payload.get("section") or "")
    try:
        if scope not in {"global", "project"}:
            raise ValueError("scope must be global or project")
        values = payload.get("values")
        if section_name == "provider":
            values = _carry_unshown_provider_keys(scope, root, values)
        values = _validate_settings(section_name, values)
        path = save_global(section_name, values) if scope == "global" else save_project(root, section_name, values)
    except (TypeError, ValueError) as exc:
        return _json_body(400, {"error": str(exc)})
    # 저장은 값을 바꾸는 데서 끝나지 않는다 — 바뀐 값으로 **다시 해석한 엔진**까지 함께 돌려준다.
    # 여태는 settings 만 돌려줘서, 엔진을 바꿔도 창은 옛 엔진의 연결 상태를 계속 말했다.
    return _json_body(
        200,
        {"saved": path, "settings": snapshot.settings_state(root), "provider": snapshot._provider_state(root)},
    )


def save_skill(payload: dict, root: str) -> tuple[int, str, bytes]:
    from ...skill_registry import set_skill_enabled

    name = str(payload.get("name") or "")
    enabled = payload.get("enabled")
    if not name or not isinstance(enabled, bool):
        return _json_body(400, {"error": "name and boolean enabled required"})
    try:
        set_skill_enabled(root, name, enabled=enabled)
    except ValueError as exc:
        return _json_body(400, {"error": str(exc)})
    return _json_body(200, {"name": name, "enabled": enabled})


def save_role(payload: dict, root: str) -> tuple[int, str, bytes]:
    from ..role import configure_role_model

    try:
        result = configure_role_model(
            root,
            str(payload.get("host") or ""),
            str(payload.get("role") or ""),
            model=str(payload.get("model") or "") or None,
            effort=str(payload.get("effort") or "") or None,
            provider=str(payload.get("provider") or "") or None,
            reset=payload.get("reset") is True,
        )
    except ValueError as exc:
        return _json_body(400, {"error": str(exc)})
    return _json_body(200, result)
