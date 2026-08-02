"""Unify runtime mode, role model, effort, provider, and agent placement settings.

These settings previously had four separate inspection and editing surfaces: native
``trinity`` placement, hosted ``agent_models``, mode agent placement, and role agent
placement. This module resolves those existing stores into one mode-by-role view and
delegates writes to their current owners so both CLI surfaces keep the same validation.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .. import errors, i18n, profiles, swarm
from ..providers import PROVIDERS

SOURCE_DEFAULT = "built-in default"
SOURCE_GLOBAL = "global"
SOURCE_PROJECT = "project"
_SOURCE_MARK = {SOURCE_DEFAULT: "D", SOURCE_GLOBAL: "G", SOURCE_PROJECT: "P"}


def _text_value(entry: object, key: str) -> str:
    if isinstance(entry, str) and key == "model":
        return entry.strip()
    if isinstance(entry, dict):
        value = entry.get(key)
        return value.strip() if isinstance(value, str) else ""
    return ""


def _configs(root: str) -> tuple[dict, dict]:
    from ..settings import load_global, load_project

    return load_global(), load_project(root)


def _hosted_sources(root: str, mode: str, role: str, selected: dict) -> dict[str, str]:
    sources = {key: SOURCE_DEFAULT for key in selected if key in {"model", "effort"}}
    for label, config in zip((SOURCE_GLOBAL, SOURCE_PROJECT), _configs(root), strict=True):
        hosts = config.get("agent_models")
        roles = hosts.get(mode) if isinstance(hosts, dict) else None
        entry = roles.get(role) if isinstance(roles, dict) else None
        for key in sources:
            if _text_value(entry, key):
                sources[key] = label
    return sources


def _native_sources(root: str, role: str) -> dict[str, str]:
    sources = {"provider": SOURCE_DEFAULT, "model": SOURCE_DEFAULT}
    global_config, project_config = _configs(root)
    for label, config in ((SOURCE_GLOBAL, global_config), (SOURCE_PROJECT, project_config)):
        provider = config.get("provider")
        if isinstance(provider, dict):
            if _text_value(provider, "name"):
                sources["provider"] = label
            if _text_value(provider, "model"):
                sources["model"] = label
        trinity = config.get("trinity")
        entry = trinity.get(role) if isinstance(trinity, dict) else None
        if _text_value(entry, "provider"):
            sources["provider"] = label
        if _text_value(entry, "model"):
            sources["model"] = label
    return sources


def _agent(root: str, mode: str, role: str | None = None) -> dict[str, str]:
    binding = swarm.binding(root)
    declarations = []
    if role:
        declarations.append(binding["roles"].get(role))
    declarations.extend((binding["modes"].get(mode), binding["default"]))
    if any(value and profiles.exists(value) for value in declarations):
        source = SOURCE_PROJECT
    else:
        source = SOURCE_GLOBAL if swarm.resolve(root, mode=mode, role=role) != profiles.DEFAULT else SOURCE_DEFAULT
    return {"value": swarm.resolve(root, mode=mode, role=role), "source": source}


def mode_state(root: str, mode: str | None = None) -> dict[str, Any]:
    """Return effective mode and role settings with the source of every value."""
    from .role import role_model_state

    if mode is not None and mode not in swarm.MODES:
        raise ValueError(f"mode는 {'/'.join(swarm.MODES)} 중 하나")
    models = role_model_state(root)
    selected_modes = (mode,) if mode else swarm.MODES
    resolved: dict[str, dict] = {}
    for selected_mode in selected_modes:
        roles: dict[str, dict] = {}
        for role, model in models[selected_mode].items():
            if selected_mode == "native":
                sources = _native_sources(root, role)
                provider = str(model["provider"])
            else:
                sources = _hosted_sources(root, selected_mode, role, model)
                sources["provider"] = SOURCE_DEFAULT
                provider = selected_mode
            agent = _agent(root, selected_mode, role)
            sources["agent"] = agent["source"]
            roles[role] = {
                "agent": agent["value"],
                "provider": provider,
                "model": str(model["model"]),
                "effort": model.get("effort"),
                "source": sources,
            }
        resolved[selected_mode] = {
            "mode": selected_mode,
            "agent": _agent(root, selected_mode),
            "roles": roles,
        }
    return {"root": os.path.realpath(root), "modes": resolved}


def _validate_role(root: str, mode: str, role: str) -> None:
    from .role import role_model_state

    if mode not in swarm.MODES:
        raise ValueError(f"mode는 {'/'.join(swarm.MODES)} 중 하나")
    roles = role_model_state(root)[mode]
    if role not in roles:
        raise ValueError(f"{mode} role은 {'/'.join(roles)} 중 하나")


def _validate_agent(agent: str) -> None:
    canon = profiles.validate(agent)
    if canon != profiles.DEFAULT and not profiles.exists(canon):
        raise FileNotFoundError(f"에이전트 {canon!r} 없음 — `asgard agent create {canon}`로 먼저 만들어라")


def configure_mode(
    root: str,
    mode: str,
    role: str | None = None,
    *,
    agent: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    provider: str | None = None,
) -> dict:
    """Persist the supplied agent and role-model values through their existing owners."""
    from .role import configure_role_model

    if mode not in swarm.MODES:
        raise ValueError(f"mode는 {'/'.join(swarm.MODES)} 중 하나")
    model_change = any(value is not None for value in (model, effort, provider))
    if role is None:
        if model_change or not agent:
            raise ValueError("role이 없으면 --agent만 설정할 수 있음")
        _validate_agent(agent)
        changed = {"agent": swarm.bind(root, agent, mode=mode)}
    else:
        _validate_role(root, mode, role)
        if not (agent or model_change):
            raise ValueError("--agent/--model/--effort/--provider 중 하나 필요")
        if agent:
            _validate_agent(agent)
        changed = {}
        if model_change:
            changed["model"] = configure_role_model(
                root,
                mode,
                role,
                model=model,
                effort=effort,
                provider=provider,
            )
        if agent:
            changed["agent"] = swarm.bind(root, agent, role=role)
    return {
        "mode": mode,
        "role": role,
        "changed": changed,
        "effective": mode_state(root, mode)["modes"][mode],
    }


def reset_mode(root: str, mode: str, role: str | None = None) -> dict:
    """Remove project overrides for one mode or one mode-role cell."""
    from .role import configure_role_model, reset_role_models

    if mode not in swarm.MODES:
        raise ValueError(f"mode는 {'/'.join(swarm.MODES)} 중 하나")
    if role is None:
        models = reset_role_models(root, mode)
        agent = swarm.unbind(root, mode=mode)
    else:
        _validate_role(root, mode, role)
        models = configure_role_model(root, mode, role, reset=True)
        agent = swarm.unbind(root, role=role)
    return {
        "mode": mode,
        "role": role,
        "reset": {"model": models, "agent": agent},
        "effective": mode_state(root, mode)["modes"][mode],
    }


def _rows(payload: dict) -> list[list[str]]:
    rows: list[list[str]] = []
    for mode, config in payload["modes"].items():
        for role, cell in config["roles"].items():
            source = cell["source"]
            source_text = "/".join(
                _SOURCE_MARK[source[key]] if key in source else "—" for key in ("agent", "provider", "model", "effort")
            )
            rows.append(
                [
                    mode,
                    role,
                    cell["agent"],
                    f"{cell['provider']}:{cell['model']}",
                    str(cell["effort"] or "—"),
                    source_text,
                ]
            )
    return rows


def _print_table(payload: dict) -> None:
    rows = [["MODE", "ROLE", "AGENT", "PROVIDER:MODEL", "EFFORT", "SOURCE"], *_rows(payload)]
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    for index, row in enumerate(rows):
        print("  ".join(value.ljust(widths[column]) for column, value in enumerate(row)).rstrip())
        if index == 0:
            print("  ".join("─" * width for width in widths).rstrip())
    print("SOURCE: agent/provider/model/effort · D=built-in default · G=global · P=project")


def _emit(payload: dict, json_out: bool) -> None:
    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_table(payload)


def _invalid(exc: Exception, mode: str, *, remedy: str) -> errors.AsgardError:
    """설정 소유자(`configure_mode`·`mode_state`)가 던진 것을 경계의 어휘로 옮긴다.

    `ValueError`는 사용자가 적은 값이 틀린 것이고, `FileNotFoundError`는 그 이름의 에이전트가
    이 기계에 없는 것이다. 종료 코드는 둘 다 2지만 `code`가 갈려야 스튜디오가 "고쳐 쓰세요"와
    "먼저 만드세요"를 다르게 안내한다."""
    kind = errors.NotFound if isinstance(exc, FileNotFoundError) else errors.InvalidInput
    return kind(str(exc), remedy=remedy, detail={"mode": mode})


def run_mode(*, json_out: bool = False) -> int:
    root = os.getcwd()
    errors.set_json_surface(json_out)
    i18n.load_lang(root)
    _emit(mode_state(root), json_out)
    return 0


def run_mode_show(mode: str, *, json_out: bool = False) -> int:
    root = os.getcwd()
    errors.set_json_surface(json_out)
    i18n.load_lang(root)
    try:
        payload = mode_state(root, mode)
    except ValueError as exc:
        raise _invalid(exc, mode, remedy="`asgard mode`로 네 모드를 한 화면에서 보세요") from exc
    _emit(payload, json_out)
    return 0


def run_mode_set(
    mode: str,
    role: str | None = None,
    *,
    agent: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    provider: str | None = None,
) -> int:
    try:
        payload = configure_mode(
            os.getcwd(),
            mode,
            role,
            agent=agent,
            model=model,
            effort=effort,
            provider=provider,
        )
    except (ValueError, FileNotFoundError) as exc:
        fix = (
            f"`asgard agent create {agent}`로 먼저 만드세요"
            if isinstance(exc, FileNotFoundError)
            else f"`asgard mode show {mode}`로 지금 값을 보세요"
        )
        raise _invalid(exc, mode, remedy=fix) from exc
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def run_mode_reset(mode: str, role: str | None = None) -> int:
    try:
        payload = reset_mode(os.getcwd(), mode, role)
    except ValueError as exc:
        raise _invalid(exc, mode, remedy="`asgard mode`로 어떤 모드·역할이 있는지 보세요") from exc
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def run_mode_pick() -> int:
    root = os.getcwd()
    i18n.load_lang(root)
    from ..picker import Option, available, pick

    if not available():
        # 취소(아래 `return 1`)와 다른 사건이다: 고를 화면 자체를 못 여는 환경이므로 같은 설정을
        # 타이핑으로 하는 길을 처방으로 준다.
        raise errors.PreflightFailed(
            "mode pick requires an interactive TTY",
            remedy="run: asgard mode set <mode> <role> --model <model>",
        )
    state = mode_state(root)
    mode = pick(i18n.t("pick_host"), [Option(value, value) for value in swarm.MODES])
    if mode is None:
        return 1
    roles = state["modes"][mode]["roles"]
    role = pick(
        i18n.t("pick_role"),
        [Option(value, value, detail=f"{cell['provider']}:{cell['model']}") for value, cell in roles.items()],
    )
    if role is None:
        return 1
    current = roles[role]
    options = [Option("reset", i18n.t("model_override_clear"), detail="agent + model")]
    models = [current["model"]]
    if mode == "native":
        models.extend(profile.default_model for profile in PROVIDERS.values() if profile.default_model)
    else:
        from ..templates.agent_models import AGENT_MODEL_DEFAULTS

        models.extend(value["model"] for value in AGENT_MODEL_DEFAULTS[mode].values())
    for value in dict.fromkeys(models):
        options.append(Option(f"model:{value}", value, detail="model", current=value == current["model"]))
    for row in profiles.listing():
        value = row["id"]
        options.append(Option(f"agent:{value}", value, detail="agent", current=value == current["agent"]))
    if mode == "native":
        for value in PROVIDERS:
            options.append(Option(f"provider:{value}", value, detail="provider", current=value == current["provider"]))
    elif mode != "cursor":
        efforts = dict.fromkeys(filter(None, (current["effort"], "low", "medium", "high", "xhigh", "max")))
        for value in efforts:
            options.append(Option(f"effort:{value}", value, detail="effort", current=value == current["effort"]))
    value = pick(i18n.t("pick_model"), options, manual_hint=i18n.t("picker_manual_model"))
    if value is None:
        return 1
    if value == "reset":
        payload = reset_mode(root, mode, role)
    else:
        kind, separator, selected = value.partition(":")
        key = kind if separator and kind in {"agent", "model", "effort", "provider"} else "model"
        payload = configure_mode(root, mode, role, **{key: selected if separator else value})
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
